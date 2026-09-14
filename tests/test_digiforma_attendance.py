import io
import unittest
from pathlib import Path
from zipfile import ZipFile

import pymupdf
from pypdf import PdfReader
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle

from digiforma_attendance import prepare_digiforma_attendance


def course_pdf(*, result_last=False, continuation=False, full_last_page=False):
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=(595, 842))
    pdf.setTitle("Attestation d'assiduité - exemple")
    style = ParagraphStyle("cell", fontName="Helvetica", fontSize=9, leading=11)
    columns = ["Module", "Avancée pédagogique", "Résultats", "Première connexion", "Dernière connexion"]
    widths = [165, 90, 58, 105, 105]
    if result_last:
        columns.append(columns.pop(2))
        widths.append(widths.pop(2))
    for index in range(1, 9):
        pdf.setFont("Helvetica", 10)
        pdf.drawString(36, 800, "Suivi détaillé de l'assiduité e-learning")
        if not continuation or index != 2:
            pdf.drawString(36, 770, f"Parcours {index} - Prévention et sécurité")
        rows = [] if continuation and index == 2 else [[Paragraph(x, style) for x in columns]]
        for module in range(1, 4):
            values = [f"P{index}M{module} - Risques", "100 %", f"SCORE-{index}-{module}", "07/09/2026 08:30", "08/09/2026 17:15"]
            if result_last:
                values.append(values.pop(2))
            rows.append(values)
        table = Table(rows, colWidths=widths, rowHeights=[40] * len(rows))
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), .5, (.5, .5, .5)),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        table.wrapOn(pdf, 523, 500)
        table.drawOn(pdf, 36, 730 - len(rows) * 40)
        pdf.drawString(36, 24, f"Intégrale Academy - Page {index}")
        pdf.showPage()
    pdf.setFont("Helvetica", 11)
    pdf.drawString(36, 790, "Relevé de connexions à l'extranet")
    pdf.drawString(36, 755, "Adresse email utilisée : alice@example.test")
    pdf.drawString(36, 710, "Total 62 heures")
    if full_last_page:
        pdf.drawString(36, 90, "Dernière connexion conservée intégralement")
    pdf.drawString(36, 24, "Intégrale Academy - Page 9")
    pdf.save()
    return output.getvalue()


def compact_course_pdf(*, merged_total=False):
    """Original 7pt text fits rows too short for insert_textbox's metrics."""
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=(595, 842))
    style = ParagraphStyle("compact", fontName="Helvetica", fontSize=7, leading=8)
    rows = [
        [Paragraph(label, style) for label in (
            "Module", "Avancée pédagogique", "Résultats", "Première connexion", "Dernière connexion",
        )],
        ["DENSE-01 : prévention des risques", "100 %", "SCORE-DENSE", "07/09/2026 08:30", "08/09/2026 17:15"],
        [Paragraph("MULTILINE-02 : accueil<br/>SUITE-02 : consignes de sécurité", style),
         "100 %", "SCORE-MULTI", "07/09/2026 08:30", "08/09/2026 17:15"],
    ]
    heights = [26, 10, 18]
    commands = [
        ("GRID", (0, 0), (-1, -1), .5, (.5, .5, .5)),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]
    if merged_total:
        rows.append(["TOTAL-FUSIONNE : 62 heures de formation suivies, tous les modules et toutes les connexions inclus.", "", "", "", ""])
        heights.append(14)
        commands.extend([
            ("SPAN", (0, 3), (-1, 3)),
            ("FONTSIZE", (0, 3), (-1, 3), 8),
        ])
    table = Table(rows, colWidths=[165, 90, 58, 105, 105], rowHeights=heights)
    table.setStyle(TableStyle(commands))
    table.wrapOn(pdf, 523, 500)
    table.drawOn(pdf, 36, 730 - sum(heights))
    pdf.save()
    return output.getvalue()


class DigiformaAttendanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        template = Path(__file__).parents[1] / "templates_word/tableau_suivi_foad_cnaps.docx"
        with ZipFile(template) as archive:
            cls.signature = archive.read("word/media/image3.png")

    def test_every_course_keeps_only_the_requested_metrics_and_signature(self):
        for result_last in (False, True):
            with self.subTest(result_last=result_last):
                result, metadata = prepare_digiforma_attendance(course_pdf(result_last=result_last), self.signature)
                reader = PdfReader(io.BytesIO(result))
                self.assertEqual(len(reader.pages), 9)
                self.assertEqual(metadata["results_tables_removed"], 8)
                for index, page in enumerate(reader.pages[:8], 1):
                    text = page.extract_text()
                    self.assertNotIn("Résultats", text)
                    self.assertNotIn("SCORE-", text)
                    self.assertIn("Avancée", text)
                    self.assertIn("Première connexion", text)
                    self.assertIn("Dernière connexion", text)
                    for module in range(1, 4):
                        self.assertIn(f"P{index}M{module}", text)
                    self.assertEqual(text.count("07/09/2026 08:30"), 3)
                    self.assertEqual(text.count("08/09/2026 17:15"), 3)
                self.assertIn("Total 62 heures", reader.pages[-1].extract_text())
                self.assertIn("Clément VAILLANT", reader.pages[-1].extract_text())
                self.assertEqual(reader.metadata.title, "Attestation d'assiduité - exemple")
                self.assertTrue(list(reader.pages[-1].images))

    def test_continued_table_without_repeated_header_is_also_processed(self):
        result, metadata = prepare_digiforma_attendance(course_pdf(continuation=True), self.signature)
        text = PdfReader(io.BytesIO(result)).pages[1].extract_text()
        self.assertNotIn("SCORE-", text)
        self.assertIn("P2M3", text)
        self.assertEqual(metadata["results_tables_removed"], 8)

    def test_signature_gets_a_new_page_if_last_page_has_no_space(self):
        result, metadata = prepare_digiforma_attendance(course_pdf(full_last_page=True), self.signature)
        reader = PdfReader(io.BytesIO(result))
        self.assertEqual(metadata["page_count"], 10)
        self.assertIn("Dernière connexion conservée intégralement", reader.pages[-2].extract_text())
        self.assertIn("Clément VAILLANT", reader.pages[-1].extract_text())

    def test_unknown_result_layout_is_rejected_instead_of_partially_cleaned(self):
        output = io.BytesIO()
        pdf = canvas.Canvas(output)
        pdf.drawString(36, 790, "Résultats")
        pdf.drawString(36, 740, "SCORE-SECRET")
        pdf.save()
        with self.assertRaisesRegex(ValueError, "tous les tableaux"):
            prepare_digiforma_attendance(output.getvalue(), self.signature)

    def test_text_is_physically_removed_from_pdf_content(self):
        result, _ = prepare_digiforma_attendance(course_pdf(), self.signature)
        with pymupdf.open(stream=result, filetype="pdf") as document:
            for page in document:
                self.assertFalse(page.search_for("Résultats"))
                self.assertNotIn("SCORE-", page.get_text())
                self.assertFalse(list(page.annots() or []))

    def test_compact_and_multiline_rows_keep_original_text_and_font_size(self):
        source = compact_course_pdf()
        result, metadata = prepare_digiforma_attendance(source, self.signature)
        self.assertEqual(metadata["results_tables_removed"], 1)
        with pymupdf.open(stream=result, filetype="pdf") as document:
            page = document[0]
            text = page.get_text()
            for label in ("DENSE-01", "MULTILINE-02", "SUITE-02"):
                self.assertEqual(text.count(label), 1)
            self.assertEqual(text.count("07/09/2026 08:30"), 2)
            self.assertEqual(text.count("08/09/2026 17:15"), 2)
            self.assertNotIn("SCORE-", text)
            self.assertNotIn("Résultats", text)
            spans = [span for block in page.get_text("dict")["blocks"] if "lines" in block
                     for line in block["lines"] for span in line["spans"]]
            self.assertEqual(next(span["size"] for span in spans if "DENSE-01" in span["text"]), 7)
            self.assertIn("Clément VAILLANT", text)

    def test_merged_total_crossing_removed_column_remains_complete(self):
        result, _ = prepare_digiforma_attendance(compact_course_pdf(merged_total=True), self.signature)
        text = PdfReader(io.BytesIO(result)).pages[0].extract_text()
        self.assertIn("TOTAL-FUSIONNE : 62 heures de formation suivies, tous les modules et toutes les connexions inclus.", text)
        for label in ("DENSE-01", "MULTILINE-02", "SUITE-02", "TOTAL-FUSIONNE"):
            self.assertEqual(text.count(label), 1)
        self.assertEqual(text.count("07/09/2026 08:30"), 2)
        self.assertEqual(text.count("08/09/2026 17:15"), 2)
        self.assertNotIn("SCORE-", text)
        self.assertNotIn("Résultats", text)


if __name__ == "__main__":
    unittest.main()
