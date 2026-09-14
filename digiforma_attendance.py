"""Prepare the imported attendance annex, without changing source-based checks."""

import re
import threading
import unicodedata

import pymupdf

_PDF_LOCK = threading.Lock()


def _normalized(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", value).strip().lower()


def _result_column(values):
    labels = [_normalized(value) for value in values]
    if not all(any(label in cell for cell in labels) for label in (
        "avancee pedagogique", "premiere connexion", "derniere connexion",
    )):
        return None
    return next((i for i, label in enumerate(labels) if label == "resultats"), None)


def _table_snapshot(table, result_column, header_row):
    """Copy geometry/text before any change invalidates the table finder."""
    rows = table.extract()
    reference = next((row.cells for row in table.rows if all(cell is not None for cell in row.cells)), None)
    if reference is None:
        raise ValueError("Le tableau Digiforma contient des cellules fusionnées non reconnues.")
    geometries = [
        [(cell[0], row.bbox[1], cell[2], row.bbox[3]) for cell in reference]
        for row in table.rows
    ]
    return {
        "bbox": pymupdf.Rect(table.bbox),
        "rows": rows,
        "geometry": geometries,
        "result_column": result_column,
        "header_row": header_row,
    }


def _draw_table(page, table):
    """Close the removed column's gap, keeping every other cell and row."""
    removed = table["result_column"]
    keep = [i for i in range(len(table["geometry"][0])) if i != removed]
    bbox = table["bbox"]
    original_widths = [table["geometry"][0][i][2] - table["geometry"][0][i][0] for i in keep]
    widths = [width * bbox.width / sum(original_widths) for width in original_widths]
    for row_index, (values, geometry) in enumerate(zip(table["rows"], table["geometry"])):
        y0, y1 = geometry[0][1], geometry[0][3]
        x = bbox.x0
        header = row_index == table["header_row"]
        for index, width in zip(keep, widths):
            cell = pymupdf.Rect(x, y0, x + width, y1)
            page.draw_rect(cell, color=(0.76, 0.79, 0.82), width=0.4,
                           fill=(0.94, 0.96, 0.98) if header else (1, 1, 1))
            value = str(values[index] or "").strip()
            if value:
                # Preserve explicit line breaks; shrink only if the source row is tight.
                box = pymupdf.Rect(cell.x0 + 3, cell.y0 + 2, cell.x1 - 3, cell.y1 - 1)
                for font_size in (9, 8.5, 8, 7.5, 7, 6):
                    shape = page.new_shape()
                    remaining = shape.insert_textbox(
                        box, value, fontsize=font_size,
                        fontname="hebo" if header else "helv", lineheight=1.05,
                        color=(0.12, 0.16, 0.20),
                    )
                    if remaining >= 0:
                        shape.commit()
                        break
                else:
                    raise ValueError("Une cellule Digiforma ne peut pas être conservée lisiblement.")
            x += width


def _append_signature(document, signature):
    page = document[-1]
    # Coordinates in an unrotated PDF page are used for both text and images.
    bounds = page.rect * page.derotation_matrix
    body_bottom = 36.0
    for kind, rect in page.get_bboxlog():
        rect = pymupdf.Rect(rect)
        if rect.y0 >= bounds.height - 55:
            continue  # Keep the existing footer's reserved band.
        if kind == "fill-path" and rect.width >= bounds.width * .9 and rect.height >= bounds.height * .9:
            continue  # A full-page background does not occupy the signature area.
        body_bottom = max(body_bottom, rect.y1)
    top = body_bottom + 18
    if top + 112 > bounds.height - 60:
        page = document.new_page(width=bounds.width, height=bounds.height)
        top = 54
    left = max(36, bounds.width - 240)
    page.insert_text((left, top + 12), "Clément VAILLANT", fontsize=11, fontname="hebo")
    page.insert_text((left, top + 28), "Directeur général Intégrale Academy", fontsize=9)
    page.insert_image(pymupdf.Rect(left, top + 38, left + 180, top + 108), stream=signature)


def prepare_digiforma_attendance(pdf_bytes, signature):
    # MuPDF calls must not overlap in the application's threaded web worker.
    with _PDF_LOCK:
        return _prepare_digiforma_attendance(pdf_bytes, signature)


def _prepare_digiforma_attendance(pdf_bytes, signature):
    """Remove results in course tables and add the provider's signature at the end.

    Callers must extract completion evidence from the original *before* this
    function. All redactions are applied to PDF content, not just painted over.
    Unrecognized result headers cause an explicit error rather than a partial edit.
    """
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        if not document.page_count or document.needs_pass:
            raise ValueError("Le PDF Digiforma est vide ou protégé par un mot de passe.")
        if document.get_sigflags() > 0:
            raise ValueError("Importez le PDF Digiforma original, avant signature électronique.")
        active_schema = None
        removed_tables = 0
        for page in document:
            words = page.get_text("words")
            result_headers = [pymupdf.Rect(word[:4]) for word in words if _normalized(word[4]) == "resultats"]
            connection_titles = page.search_for("Relevé de connexions") + page.search_for("Releve de connexions")
            connection_top = min((rect.y0 for rect in connection_titles), default=float("inf"))
            snapshots = []
            tables = sorted(page.find_tables().tables, key=lambda table: (table.bbox[1], table.bbox[0]))
            for table in tables:
                if table.bbox[1] >= connection_top:
                    active_schema = None
                    continue
                values = table.extract()
                header_row = next((i for i, row in enumerate(values[:2]) if _result_column(row) is not None), None)
                if header_row is not None:
                    column = _result_column(values[header_row])
                    snapshot = _table_snapshot(table, column, header_row)
                    active_schema = (table.col_count, column, table.bbox[0], table.bbox[2])
                elif (active_schema and table.col_count == active_schema[0]
                      and abs(table.bbox[0] - active_schema[2]) < 3
                      and abs(table.bbox[2] - active_schema[3]) < 3):
                    # A course table can continue on the next page without a header.
                    snapshot = _table_snapshot(table, active_schema[1], None)
                else:
                    continue
                snapshots.append(snapshot)
            if any(not any(table["bbox"].contains(rect.tl + (1, 1)) for table in snapshots)
                   for rect in result_headers):
                raise ValueError(
                    "La colonne Résultats n’a pas pu être identifiée dans tous les tableaux. "
                    "Réexportez l’attestation Digiforma en PDF avec les tableaux complets."
                )
            for table in snapshots:
                # Remove all original table objects, then write only the retained cells.
                page.add_redact_annot(table["bbox"] + (-.5, -.5, .5, .5), fill=(1, 1, 1))
            if snapshots:
                page.apply_redactions(images=2, graphics=1, text=0)
                for table in snapshots:
                    _draw_table(page, table)
                removed_tables += len(snapshots)
            if connection_titles:
                active_schema = None
        _append_signature(document, signature)
        return document.tobytes(garbage=4, deflate=True), {
            "page_count": document.page_count,
            "results_tables_removed": removed_tables,
            "provider_signed": True,
            "processing_version": 1,
        }
