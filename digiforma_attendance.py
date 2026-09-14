"""Extract Digiforma evidence and rebuild a complete, paginated attendance PDF."""

import re
import threading
import unicodedata
from collections import Counter

import pymupdf

from digiforma_layout import render_attendance
from digiforma_duration import journal_attendance

_PDF_LOCK = threading.Lock()
PROCESSING_VERSION = 4


def _normalized(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"\s+", " ", "".join(c for c in value if not unicodedata.combining(c))).strip().lower()


def _compact(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _header_map(values):
    mapping = {}
    for index, value in enumerate(values):
        label = _normalized(value)
        if label in ("n°", "no", "nº"):
            mapping["number"] = index
        elif label == "type":
            mapping["type"] = index
        elif label in ("nom", "module", "activite"):
            mapping["name"] = index
        elif label == "duree prevue":
            mapping["duration"] = index
        elif label.startswith("premiere"):
            mapping["first"] = index
        elif label.startswith("derniere"):
            mapping["last"] = index
        elif label.startswith("avancee"):
            mapping["progress"] = index
        elif label == "resultats":
            mapping["results"] = index
    return mapping if all(key in mapping for key in ("name", "first", "last", "progress")) else None


def _cell_text(words):
    lines = []
    for word in sorted(words, key=lambda w: (w[1], w[0])):
        if not lines or abs(word[1] - lines[-1][0]) > 2:
            lines.append((word[1], [word]))
        else:
            lines[-1][1].append(word)
    return "\n".join(" ".join(w[4] for w in sorted(line, key=lambda w: w[0])) for _, line in lines)


def _rows_from_geometry(page_words, table, reference):
    """Striped Word tables have false merged rows: reuse actual column bounds.

    Values come from words inside each logical row/column, never from the
    table finder's text for a falsely merged white row.
    """
    for row in table.rows:
        buckets = [[] for _ in reference]
        for word in page_words:
            cx, cy = (word[0] + word[2]) / 2, (word[1] + word[3]) / 2
            if not row.bbox[1] <= cy < row.bbox[3]:
                continue
            for index, cell in enumerate(reference):
                if cell[0] <= cx < cell[2]:
                    buckets[index].append(word)
                    break
        yield [_cell_text(bucket) for bucket in buckets]


def _first_match(pattern, text):
    match = re.search(pattern, text, re.I | re.M)
    return _compact(match.group(1)) if match else ""


def extract_digiforma_attendance(document):
    text = "\n".join(page.get_text() for page in document)
    identity = {
        "attested_name": _first_match(r"atteste\s+que\s*:\s*([^\n]+)", text),
        "training_title": _first_match(r"a\s+suivi\s+la\s+formation\s*:\s*([^\n]+)", text),
        "period": _first_match(r"Dates de la formation\s*:\s*([^\n]+)", text),
        "location": _first_match(r"Lieu de la formation\s*:\s*([^\n]+)", text),
        "action_type": _first_match(r"Type d'action de formation\s*:\s*([^\n]+)", text),
        "planned_duration": _first_match(r"Durée de la formation\s*:\s*([^\n]+)", text),
        "effective_duration": _first_match(r"Durée effectivement suivie[^:]*:\s*([^\n]+)", text),
        "completion_rate": _first_match(r"taux de réalisation de\s*([\d.,]+\s*%)", text),
        "connection_duration": _first_match(r"Durée totale de connexion à l['’]extranet\s*:\s*([^\n]+)", text),
        "access_days": _first_match(r"Nombre de jour\(s\) d['’]accès à l['’]extranet\s*:\s*(\d+)", text),
        "email": _first_match(r"Adresse email utilisée\s*:\s*([^\s]+)", text),
    }
    identity["effective_duration"] = re.sub(r"\s+h\s*,?\s*$", "", identity["effective_duration"]).strip(" ,")
    matches = list(re.finditer(r"^Parcours\s+(\d+)\s*[—–-]\s*([^\n]+)", text, re.I | re.M))
    courses = {}
    for index, match in enumerate(matches):
        number = int(match.group(1))
        block = text[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(text)]
        courses[number] = {
            "number": number, "title": _compact(match.group(2)), "activities": [],
            "planned": _first_match(r"Durée totale de la séquence\s*\n([^\n]+)", block),
            "completed": _first_match(r"progression et la durée des activités\s*\n([^\n]+)", block),
            "status": _first_match(r"Statut\s+(Terminé|En cours|Non commencé)", block),
            "progress": _first_match(r"Progression\s+([\d.,]+\s*%)", block),
        }
    connections, connection_total = [], ""
    active_course = None
    active_schema = None
    active_columns = None
    in_connections = False
    handled_headers = 0
    source_headers = 0
    for page in document:
        words = page.get_text("words")
        source_headers += sum(_normalized(word[4]) == "resultats" for word in words)
        events = []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                line_text = "".join(span["text"] for span in line["spans"])
                match = re.match(r"Parcours\s+(\d+)\s*[—–-]", line_text, re.I)
                if match:
                    events.append((line["bbox"][1], "course", int(match.group(1))))
                if _normalized(line_text).startswith("releve de connexions"):
                    events.append((line["bbox"][1], "connections", None))
        for table in page.find_tables().tables:
            events.append((table.bbox[1], "table", table))
        for _, kind, value in sorted(events, key=lambda event: event[0]):
            if kind == "course":
                active_course = value
                continue
            if kind == "connections":
                in_connections = True
                active_schema = None
                continue
            table = value
            extracted = table.extract()
            reference = next((row.cells for row in table.rows if all(c is not None for c in row.cells)), None)
            if in_connections:
                if table.col_count != 4 or reference is None:
                    continue
                for row in _rows_from_geometry(words, table, reference):
                    values = [_compact(v) for v in row]
                    if _normalized(values[0]) == "total":
                        connection_total = next((v for v in values[1:] if v), connection_total)
                    elif re.match(r"(?:Le\s+)?\d{2}/\d{2}/\d{4}", values[0]):
                        if not re.match(r"(?:Le\s+)?\d{2}/\d{2}/\d{4}", values[1]):
                            raise ValueError("Une ligne du journal Digiforma est incomplète. Réexportez le PDF complet.")
                        connections.append(values)
                continue
            header = next((_header_map(row) for row in extracted[:2] if _header_map(row)), None)
            if header:
                active_schema = header
                active_columns = reference
            elif active_schema and table.col_count == len(active_columns or []):
                reference = reference or active_columns
            else:
                continue
            if not reference:
                raise ValueError("Les colonnes du tableau Digiforma n’ont pas pu être reconnues.")
            rows = list(_rows_from_geometry(words, table, reference))
            for row in rows:
                if _header_map(row):
                    handled_headers += int(any(_normalized(v) == "resultats" for v in row))
                    continue
                record = {key: row[column] for key, column in active_schema.items() if key != "results"}
                name = _compact(record.get("name"))
                if not any(_compact(v) for v in record.values()):
                    continue
                # Second line of a header split by the source page break.
                if not name and all(_normalized(record.get(key)) in ("", "connexion", "pedagogique")
                                    for key in ("first", "last", "progress")):
                    continue
                module = re.search(r"\bP(\d+)M\d+\b", name, re.I)
                evaluation = re.search(r"[ÉE]valuation\s+Parcours\s+(\d+)", name, re.I)
                if module or evaluation:
                    active_course = int((module or evaluation).group(1))
                if active_course is None:
                    raise ValueError("Le parcours associé à une activité Digiforma n’a pas été reconnu.")
                course = courses.setdefault(active_course, {"number": active_course, "title": f"Parcours {active_course}", "activities": []})
                is_total = any(_normalized(v).startswith("total") for v in row[:active_schema["name"] + 1])
                if is_total:
                    course["total"] = {k: _compact(v) for k, v in record.items() if k in ("duration", "first", "last", "progress")}
                    continue
                if (not name or ("number" in active_schema and not _compact(record.get("number"))
                                 and not _compact(record.get("type")) and not module and not evaluation)):
                    # A source row can continue on the following page. Results
                    # fragments are already excluded from this logical record.
                    previous = course["activities"][-1] if course["activities"] else None
                    if previous:
                        for key, fragment in record.items():
                            if key not in ("number", "type") and _compact(fragment):
                                previous[key] = _compact(previous.get(key, "") + " " + fragment)
                    continue
                record["name"] = name
                for key in ("number", "type", "duration", "progress"):
                    record[key] = _compact(record.get(key))
                course["activities"].append(record)
    if source_headers != handled_headers:
        raise ValueError("Les en-têtes de tous les tableaux Digiforma n’ont pas pu être reconnus. Réexportez le PDF original complet.")
    expected_modules = set(re.findall(r"\bP\d+M\d+\b", text, re.I))
    extracted_modules = set(re.findall(r"\bP\d+M\d+\b", " ".join(a["name"] for c in courses.values() for a in c["activities"]), re.I))
    if expected_modules != extracted_modules:
        raise ValueError("Des modules Digiforma n’ont pas pu être repris intégralement. Aucun document n’a été remplacé.")
    expected_evaluations = set(re.findall(r"[ÉE]valuation\s+Parcours\s+(\d+)", text, re.I))
    actual_evaluations = set(re.findall(r"[ÉE]valuation\s+Parcours\s+(\d+)", " ".join(a["name"] for c in courses.values() for a in c["activities"]), re.I))
    if expected_evaluations != actual_evaluations:
        raise ValueError("Des évaluations Digiforma n’ont pas pu être reprises intégralement. Aucun document n’a été remplacé.")
    journal_sections = re.split(r"Relevé de connexions[^\n]*", text, flags=re.I, maxsplit=1)
    if len(journal_sections) == 2:
        timestamp = r"\b\d{2}/\d{2}/\d{4}\s*(?:à\s*)?\d{1,2}h\d{2}m\d{2}s"
        expected = Counter(_compact(v) for v in re.findall(timestamp, journal_sections[1]))
        actual = Counter(_compact(v) for row in connections for value in row[:2] for v in re.findall(timestamp, value))
        if expected != actual:
            raise ValueError("Le journal de connexions Digiforma n’a pas pu être repris intégralement. Aucun document n’a été remplacé.")
    provider_lines = []
    first_page = document[0].get_text()
    for line in first_page.splitlines() if "Attestation d'assiduité" in first_page else []:
        if line.startswith(("Attestation d'assiduité", "Je soussigné")):
            break
        if line.strip() and not re.match(r"Page\s+\d", line.strip()):
            provider_lines.append(line.strip())
    if not connection_total:
        journal_text = re.split(r"Relevé de connexions", text, flags=re.I)[-1]
        totals = re.findall(r"(?:^|\n)Total\s*\n?([^\n]+)", journal_text, re.I)
        connection_total = _compact(totals[-1]) if totals else ""
    return {
        "identity": identity, "courses": sorted(courses.values(), key=lambda c: c["number"]),
        "connections": connections, "connection_total": connection_total,
        "issued": _first_match(r"(Fait\s+[àa][^\n]+)", text),
        "provider": "\n".join(provider_lines), "results_tables_removed": handled_headers,
    }


def prepare_digiforma_attendance(pdf_bytes, signature, stamp):
    with _PDF_LOCK:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as original:
            if not original.page_count or original.needs_pass:
                raise ValueError("Le PDF Digiforma est vide ou protégé par un mot de passe.")
            if original.get_sigflags() > 0:
                raise ValueError("Importez le PDF Digiforma original, avant signature électronique.")
            report = extract_digiforma_attendance(original)
        rendered = render_attendance(report, signature, stamp)
        with pymupdf.open(stream=rendered, filetype="pdf") as document:
            for index, page in enumerate(document, 1):
                page.insert_textbox(pymupdf.Rect(455, page.rect.height - 43, page.rect.width - 40, page.rect.height - 25),
                                    f"Page {index} / {len(document)}", fontsize=8, align=2)
            return document.tobytes(garbage=4, deflate=True), {
                "page_count": len(document), "results_tables_removed": report["results_tables_removed"],
                "provider_signed": True, "provider_stamped": True, "processing_version": PROCESSING_VERSION,
                "connection_log_total": report["connection_total"],
                **journal_attendance(report["connection_total"]),
            }
