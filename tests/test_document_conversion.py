"""Conversion contracts: real image/PDF contents, bounded failures and Office I/O."""
import io
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

import document_conversion as conversion


def image_bytes(fmt="PNG", size=(64, 96), **kwargs):
    output = io.BytesIO()
    Image.new("RGB", size, "#143857").save(output, format=fmt, **kwargs)
    return output.getvalue()


def pdf_bytes(pages=1, password=None):
    output = io.BytesIO()
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)
    if password:
        writer.encrypt(password)
    writer.write(output)
    return output.getvalue()


def zipped(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return output.getvalue()


@pytest.mark.parametrize("extension,fmt", [("jpg", "JPEG"), ("jpeg", "JPEG"), ("png", "PNG"), ("webp", "WEBP"), ("gif", "GIF"), ("bmp", "BMP"), ("tif", "TIFF"), ("tiff", "TIFF"), ("avif", "AVIF")])
def test_images_really_become_deterministic_pdfs(extension, fmt):
    data = image_bytes(fmt)
    result, filename = conversion.convert_upload(data, "My scan." + extension)
    assert filename == "My_scan.pdf"
    assert len(PdfReader(io.BytesIO(result)).pages) == 1
    assert PdfReader(io.BytesIO(result)).pages[0].images
    assert conversion.convert_upload(data, "My scan." + extension)[0] == result


def test_heic_photo_is_jpeg_and_document_is_pdf():
    pytest.importorskip("pillow_heif")
    data = image_bytes("HEIF")
    document, filename = conversion.convert_upload(data, "iPhone.HEIC")
    assert filename == "iPhone.pdf" and document.startswith(b"%PDF-")
    photo, filename = conversion.convert_upload(data, "iPhone.HEIC", photo=True)
    assert filename == "iPhone.jpg"
    with Image.open(io.BytesIO(photo)) as img:
        assert img.format == "JPEG" and img.size == (64, 96)


@pytest.mark.parametrize("extension,fmt", [("jpg", "JPEG"), ("jpeg", "JPEG"), ("png", "PNG")])
def test_original_identity_photo_bytes_are_preserved(extension, fmt):
    data = image_bytes(fmt)
    result, filename = conversion.convert_upload(data, "portrait." + extension, photo=True)
    assert result == data
    assert filename.endswith(".png" if extension == "png" else ".jpg")


def test_existing_pdf_bytes_are_not_rewritten():
    data = pdf_bytes()
    result, filename = conversion.convert_upload(data, "../../signed file.PDF")
    assert result is data  # Rewriting would invalidate an electronic signature.
    assert filename == "signed_file.pdf"


def test_pdf_never_becomes_an_identity_photo():
    with pytest.raises(conversion.ConversionError, match="photo.*image"):
        conversion.convert_upload(pdf_bytes(), "portrait.pdf", photo=True)


def test_exif_orientation_applies_to_converted_document():
    exif = Image.Exif()
    exif[274] = 6
    data = image_bytes("JPEG", size=(80, 120), exif=exif)
    result, _ = conversion.convert_upload(data, "rotated.jpg")
    box = PdfReader(io.BytesIO(result)).pages[0].mediabox
    assert (float(box.width), float(box.height)) == (120, 80)


@pytest.mark.parametrize("fmt,extension", [("TIFF", "tiff"), ("GIF", "gif"), ("PNG", "png")])
def test_all_pages_or_animation_frames_are_preserved(fmt, extension):
    output = io.BytesIO()
    Image.new("RGB", (40, 60), "red").save(output, format=fmt, save_all=True, append_images=[Image.new("RGB", (40, 60), "blue")])
    result, _ = conversion.convert_upload(output.getvalue(), "both." + extension)
    pages = PdfReader(io.BytesIO(result)).pages
    assert len(pages) == 2
    assert pages[0].images[0].data != pages[1].images[0].data
    with pytest.raises(conversion.ConversionError, match="image fixe"):
        conversion.convert_upload(output.getvalue(), "both." + extension, photo=True)


def test_transparent_photo_has_a_white_background():
    buffer = io.BytesIO()
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(buffer, "WEBP", lossless=True)
    result, filename = conversion.convert_upload(buffer.getvalue(), "photo.webp", photo=True)
    with Image.open(io.BytesIO(result)) as img:
        assert img.getpixel((0, 0)) == (255, 255, 255)
    assert filename == "photo.jpg"


@pytest.mark.parametrize("data,name", [(b"", "file.pdf"), (b"%PDF-1.4\ninvalid", "file.pdf"), (b"garbage", "photo.jpg"), (image_bytes(), "fake.pdf"), (pdf_bytes(), "fake.png"), (image_bytes(), "fake.jpg"), (b"MZ executable", "fake.txt"), (b"\x00\x01", "file.csv"), (b"not a document", "file.docx"), (b"not OLE", "file.doc"), (b"not RTF", "file.rtf")])
def test_empty_malformed_and_disguised_contents_fail_cleanly(data, name):
    with pytest.raises(conversion.ConversionError):
        conversion.convert_upload(data, name)


@pytest.mark.parametrize("filename", ["file.zip", "file.exe", "file.mp4", "file.unknown", "no_extension"])
def test_unsupported_formats_are_not_mislabeled_as_pdf(filename):
    with pytest.raises(conversion.ConversionError, match="exportez-le en PDF"):
        conversion.convert_upload(b"content", filename)


def test_encrypted_and_empty_pdfs_fail():
    with pytest.raises(conversion.ConversionError, match="mot de passe"):
        conversion.convert_upload(pdf_bytes(password="secret"), "encrypted.pdf")
    with pytest.raises(conversion.ConversionError):
        conversion.convert_upload(pdf_bytes(pages=0), "empty.pdf")


def test_pdf_page_limit_does_not_silently_truncate(monkeypatch):
    monkeypatch.setattr(conversion, "MAX_PAGES", 2)
    with pytest.raises(conversion.ConversionError, match="2 pages"):
        conversion.convert_upload(pdf_bytes(pages=3), "large.pdf")


def test_image_resource_and_byte_limits(monkeypatch):
    monkeypatch.setattr(conversion, "MAX_IMAGE_PIXELS", 10)
    with pytest.raises(conversion.ConversionError, match="trop grande"):
        conversion.convert_upload(image_bytes(), "large.png")
    monkeypatch.setattr(conversion, "MAX_IMAGE_PIXELS", 25_000_000)
    data = image_bytes()
    with pytest.raises(conversion.ConversionError, match="dépasse la limite"):
        conversion.convert_upload(data, "small.png", max_bytes=len(data) - 1)
    # Source fits, but the converted PDF does not; no oversize output is returned.
    with pytest.raises(conversion.ConversionError, match="PDF obtenu"):
        conversion.convert_upload(data, "small.png", max_bytes=len(data) + 1)


def test_busy_converter_and_slots_released_after_errors():
    assert conversion._slots.acquire(blocking=False)
    try:
        with pytest.raises(conversion.ConversionError, match="déjà en cours"):
            conversion.convert_upload(image_bytes(), "image.png")
    finally:
        conversion._slots.release()
    with pytest.raises(conversion.ConversionError):
        conversion.convert_upload(b"broken", "image.png")
    assert conversion.convert_upload(image_bytes(), "image.png")[0].startswith(b"%PDF-")


def test_missing_office_engine_is_actionable(monkeypatch):
    monkeypatch.setattr(conversion.shutil, "which", lambda _: None)
    with pytest.raises(conversion.ConversionError, match="temporairement indisponible"):
        conversion.convert_upload(b"Bonjour", "letter.txt")


def test_office_validates_containers_and_zip_expansion(monkeypatch):
    docx = zipped({"word/document.xml": "<xml/>", "[Content_Types].xml": "<xml/>"})
    assert conversion._validate_office(docx, "docx") == docx
    with pytest.raises(conversion.ConversionError):
        conversion._validate_office(docx, "xlsx")
    monkeypatch.setattr(conversion, "MAX_EXPANDED_OFFICE_BYTES", 5)
    with pytest.raises(conversion.ConversionError, match="décompression"):
        conversion._validate_office(docx, "docx")


def test_odf_encryption_rejected_before_office():
    data = zipped({"mimetype": b"application/vnd.oasis.opendocument.text", "content.xml": b"encrypted bytes", "META-INF/manifest.xml": b"<manifest:encryption-data/>"})
    with pytest.raises(conversion.ConversionError):
        conversion._validate_office(data, "odt")


def test_office_output_validated_and_temporary_files_removed(monkeypatch):
    seen = []
    monkeypatch.setattr(conversion.shutil, "which", lambda _: "/usr/bin/libreoffice")
    expected = pdf_bytes()
    def fake_engine(command, directory):
        seen.append(directory)
        source = Path(command[-1])
        assert source.read_text() == "Déclaration\nBonjour"
        assert str(source.parent) == str(directory)
        profile = (directory / "profile/user/registrymodifications.xcu").read_text()
        assert "DisableMacrosExecution" in profile and "DisableActiveContent" in profile
        assert any(argument.startswith("--infilter=Text (encoded):UTF8") for argument in command)
        (directory / "output/document.pdf").write_bytes(expected)
    monkeypatch.setattr(conversion, "_run_office", fake_engine)
    result, name = conversion.convert_upload("Déclaration\nBonjour".encode("cp1252"), "déclaration.txt")
    assert result == expected and name == "declaration.pdf"
    assert all(not directory.exists() for directory in seen)


@pytest.mark.parametrize("engine_result", [b"garbage", b"", None, pdf_bytes(password="secret")])
def test_office_never_accepts_missing_or_invalid_output(monkeypatch, engine_result):
    monkeypatch.setattr(conversion.shutil, "which", lambda _: "/usr/bin/libreoffice")
    paths = []
    def fake_engine(command, directory):
        paths.append(directory)
        if engine_result is not None:
            (directory / "output/document.pdf").write_bytes(engine_result)
    monkeypatch.setattr(conversion, "_run_office", fake_engine)
    with pytest.raises(conversion.ConversionError):
        conversion.convert_upload(b"Bonjour", "document.txt")
    assert all(not directory.exists() for directory in paths)


def test_csv_formula_import_disabled(monkeypatch):
    captured = []
    monkeypatch.setattr(conversion.shutil, "which", lambda _: "/usr/bin/libreoffice")
    def fake_engine(command, directory):
        captured.extend(command)
        (directory / "output/document.pdf").write_bytes(pdf_bytes())
    monkeypatch.setattr(conversion, "_run_office", fake_engine)
    conversion.convert_upload(b'Nom;Valeur\nExemple;=WEBSERVICE("https://example.com")', "table.csv")
    options = next(value for value in captured if value.startswith("--infilter="))
    assert options.split(":", 1)[1].split(",")[12] == "false"
    assert options.split(":", 1)[1].split(",")[0] == "59"
    assert "pdf:calc_pdf_Export" in captured


def test_office_timeout_kills_the_process_group_and_has_no_secrets(monkeypatch, tmp_path):
    killed = []
    captured = {}
    class Process:
        pid = 12345
        attempts = 0
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def wait(self, timeout=None):
            if timeout:
                raise subprocess.TimeoutExpired("libreoffice", timeout)
            return -9
    def fake_process(command, **kwargs):
        captured.update(kwargs)
        return Process()
    monkeypatch.setenv("OPENAI_API_KEY", "never-forward-this")
    monkeypatch.setenv("DATABASE_URL", "never-forward-that")
    monkeypatch.setattr(conversion.subprocess, "Popen", fake_process)
    monkeypatch.setattr(conversion.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(conversion.ConversionError, match="trop de temps"):
        conversion._run_office(["/usr/bin/libreoffice", "--headless"], tmp_path)
    assert killed and killed[0][0] == 12345
    assert "OPENAI_API_KEY" not in captured["env"] and "DATABASE_URL" not in captured["env"]
    assert captured["start_new_session"] is True


@pytest.mark.skipif(not (shutil.which("libreoffice") or shutil.which("soffice")), reason="LibreOffice not installed locally")
def test_real_office_conversion_contains_text():
    result, name = conversion.convert_upload("Justificatif de formation — été".encode(), "justificatif.txt")
    assert name == "justificatif.pdf"
    assert "Justificatif de formation" in PdfReader(io.BytesIO(result)).pages[0].extract_text()


def test_large_document_is_bounded_to_a4_resolution_without_cropping():
    data = image_bytes("PNG", size=(4000, 2000))
    result, _ = conversion.convert_upload(data, "large.png")
    image = PdfReader(io.BytesIO(result)).pages[0].images[0].image
    assert image.size == (conversion.MAX_RENDER_EDGE, conversion.MAX_RENDER_EDGE // 2)


def test_temporary_storage_failure_is_a_conversion_error(monkeypatch):
    monkeypatch.setattr(conversion.shutil, "which", lambda _: "/usr/bin/libreoffice")
    def no_space(*args, **kwargs):
        raise OSError("No space left on device")
    monkeypatch.setattr(conversion.tempfile, "TemporaryDirectory", no_space)
    with pytest.raises(conversion.ConversionError, match="temporairement indisponible"):
        conversion.convert_upload(b"Bonjour", "document.txt")
