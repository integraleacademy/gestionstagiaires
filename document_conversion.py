"""Local, bounded document normalization for trainee uploads.

Existing PDFs and valid JPEG/PNG identity photos remain byte-identical. Other
supported documents become PDF; other identity images become JPEG. The caller
must bind any verification receipt to the returned bytes, since Office PDF
metadata may vary between conversions. No uploaded file is sent to a service.
"""

import csv
import errno
import io
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import warnings
import zipfile

from PIL import Image, ImageOps
from pypdf import PdfReader
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from werkzeug.utils import secure_filename

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    # JPEG/PNG/PDF still work in installations awaiting the HEIF dependency.
    pass


IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "tif", "tiff", "bmp", "gif", "heic", "heif", "avif"})
OFFICE_EXTENSIONS = frozenset({"doc", "docx", "odt", "rtf", "xls", "xlsx", "ods", "csv", "ppt", "pptx", "odp", "txt"})
DOCUMENT_EXTENSIONS = IMAGE_EXTENSIONS | OFFICE_EXTENSIONS | {"pdf"}
MAX_PAGES = 100
MAX_IMAGE_PIXELS = 25_000_000
MAX_TOTAL_IMAGE_PIXELS = 50_000_000
# A4 at 300 dpi is enough for document reading and keeps the 512 MB service
# from holding several full-size 25 MP copies while creating a PDF.
MAX_RENDER_EDGE = 3508
MAX_RENDER_SHORT_EDGE = 2480
MAX_EXPANDED_OFFICE_BYTES = 100 * 1024 * 1024
OFFICE_TIMEOUT_SECONDS = 40
# One expensive conversion per web worker; callers receive a retryable error
# instead of accumulating subprocesses or decoded images while the server is busy.
_slots = threading.BoundedSemaphore(1)


class ConversionError(ValueError):
    """A safe French explanation suitable for the upload form."""


def accepted_upload_types(photo=False):
    """HTML accept value. Server-side content validation remains mandatory."""
    return ",".join("." + ext for ext in sorted(IMAGE_EXTENSIONS if photo else DOCUMENT_EXTENSIONS))


def _invalid():
    return ConversionError("Le fichier ne s’ouvre pas correctement ou son contenu ne correspond pas à son extension. Exportez une nouvelle copie ; pour un document protégé, retirez le mot de passe.")


def _too_large(max_bytes):
    return ConversionError(f"Le fichier ou le PDF obtenu dépasse la limite de {max_bytes / (1024 * 1024):g} Mo. Réduisez sa taille, puis réessayez.")


def _output_name(filename, extension):
    name = secure_filename(str(filename).replace("\\", "/").rsplit("/", 1)[-1])
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return (stem[:150] or "document") + "." + extension


def _validate_pdf(data):
    if not data.startswith(b"%PDF-"):
        raise _invalid()
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ConversionError("Ce PDF est protégé. Retirez son mot de passe, puis déposez une nouvelle copie.")
        # Do not rewrite PDFs: doing so would invalidate existing signatures.
        if not len(reader.pages):
            raise _invalid()
        if len(reader.pages) > MAX_PAGES:
            raise ConversionError(f"Ce document dépasse {MAX_PAGES} pages. Déposez uniquement les pages demandées.")
        for page in reader.pages:
            if any(not math.isfinite(float(x)) for x in page.mediabox) or page.mediabox.width <= 0 or page.mediabox.height <= 0:
                raise _invalid()
    except ConversionError:
        raise
    except Exception as exc:
        raise _invalid() from exc


class _LimitedBuffer(io.BytesIO):
    def __init__(self, max_bytes):
        super().__init__()
        self.max_bytes = max_bytes

    def write(self, data):
        if self.tell() + len(data) > self.max_bytes:
            raise _too_large(self.max_bytes)
        return super().write(data)


_IMAGE_FORMATS = {
    "jpg": {"JPEG"}, "jpeg": {"JPEG"}, "png": {"PNG"}, "webp": {"WEBP"},
    "tif": {"TIFF"}, "tiff": {"TIFF"}, "bmp": {"BMP"}, "gif": {"GIF"},
    "heic": {"HEIF"}, "heif": {"HEIF"}, "avif": {"AVIF"},
}


def _rgb_image(frame):
    oriented = ImageOps.exif_transpose(frame)
    if oriented.mode in {"RGBA", "LA"} or "transparency" in oriented.info:
        rgba = oriented.convert("RGBA")
        result = Image.new("RGB", rgba.size, "white")
        result.paste(rgba, mask=rgba.getchannel("A"))
        return result
    return oriented.convert("RGB")


def _convert_image(data, ext, photo, max_bytes):
    output = _LimitedBuffer(max_bytes)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as check:
                if check.format not in _IMAGE_FORMATS[ext]:
                    raise _invalid()
                check.verify()
            with Image.open(io.BytesIO(data)) as picture:
                count = getattr(picture, "n_frames", 1)
                if photo and count != 1:
                    raise ConversionError("Pour la photo d’identité, sélectionnez une image fixe contenant une seule photo, sans animation.")
                if count > MAX_PAGES:
                    raise ConversionError(f"Ce fichier contient plus de {MAX_PAGES} images. Déposez uniquement les pages demandées.")
                total_pixels = 0
                pdf = None if photo else Canvas(output, invariant=1, pageCompression=1)
                if pdf:
                    pdf.setTitle("Document stagiaire")
                    pdf.setAuthor("")
                for index in range(count):
                    picture.seek(index)
                    pixels = picture.width * picture.height
                    total_pixels += pixels
                    if pixels > MAX_IMAGE_PIXELS or total_pixels > MAX_TOTAL_IMAGE_PIXELS:
                        raise ConversionError("L’image est trop grande. Réduisez chaque image à moins de 25 mégapixels et l’ensemble à moins de 50 mégapixels, en gardant le texte lisible.")
                    picture.load()  # Also catches truncated JPEGs; verify alone does not.
                    if photo and ext in {"jpg", "jpeg", "png"}:
                        return data, "png" if ext == "png" else "jpg"
                    # Work on a copy so resizing one TIFF/GIF frame cannot alter
                    # the decoder's next frame. Resize before EXIF/RGB copies.
                    with picture.copy() as reduced:
                        bounds = (MAX_RENDER_EDGE, MAX_RENDER_SHORT_EDGE) if reduced.width > reduced.height else (MAX_RENDER_SHORT_EDGE, MAX_RENDER_EDGE)
                        reduced.thumbnail(bounds, resample=Image.Resampling.LANCZOS, reducing_gap=3)
                        with _rgb_image(reduced) as frame:
                            if photo:
                                frame.save(output, format="JPEG", quality=95, subsampling=0)
                            else:
                                # Fit within A4 without cropping; retain aspect
                                # ratio and up to A4/300dpi document resolution.
                                scale = min(595.276 / frame.width, 841.89 / frame.height, 1)
                                width, height = frame.width * scale, frame.height * scale
                                pdf.setPageSize((width, height))
                                pdf.drawImage(ImageReader(frame), 0, 0, width=width, height=height)
                                pdf.showPage()
                if pdf:
                    pdf.save()
    except ConversionError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ConversionError("L’image est trop grande. Exportez une copie de moins de 25 mégapixels.") from exc
    except Exception as exc:
        raise _invalid() from exc
    return output.getvalue(), "jpg" if photo else "pdf"


_ZIP_MAIN = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml"}
_ODF_MIME = {"odt": b"application/vnd.oasis.opendocument.text", "ods": b"application/vnd.oasis.opendocument.spreadsheet", "odp": b"application/vnd.oasis.opendocument.presentation"}


def _validate_office(data, ext):
    """Validate containers without extracting any uploaded archive paths."""
    if ext in _ZIP_MAIN or ext in _ODF_MIME:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > 4000 or sum(item.file_size for item in entries) > MAX_EXPANDED_OFFICE_BYTES:
                    raise ConversionError("Le document est trop complexe ou trop volumineux après décompression. Exportez-le en PDF depuis votre logiciel.")
                if any(item.flag_bits & 1 for item in entries):
                    raise _invalid()
                names = set(archive.namelist())
                if ext in _ZIP_MAIN and not {_ZIP_MAIN[ext], "[Content_Types].xml"}.issubset(names):
                    raise _invalid()
                if ext in _ODF_MIME:
                    if "content.xml" not in names or archive.read("mimetype") != _ODF_MIME[ext]:
                        raise _invalid()
                    if "META-INF/manifest.xml" in names and b"encryption-data" in archive.read("META-INF/manifest.xml"):
                        raise _invalid()
        except ConversionError:
            raise
        except Exception as exc:
            raise _invalid() from exc
    elif ext in {"doc", "xls", "ppt"}:
        if not data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise _invalid()
    elif ext == "rtf":
        if not data.lstrip().startswith(b"{\\rtf"):
            raise _invalid()
    elif ext in {"txt", "csv"}:
        if data.startswith((b"MZ", b"PK\x03\x04", b"\x7fELF", b"%PDF-")):
            raise _invalid()
        # Normalize common text encodings before the explicit UTF-8 import.
        try:
            if data.startswith((b"\xff\xfe", b"\xfe\xff")):
                text = data.decode("utf-16")
            else:
                try:
                    text = data.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = data.decode("cp1252")
            if any(ord(char) < 32 and char not in "\n\r\t\f" for char in text):
                raise _invalid()
            return text.encode("utf-8")
        except (UnicodeError, ValueError) as exc:
            raise _invalid() from exc
    return data


# Values are defined in LibreOffice's Common.xcs, Writer.xcs and Calc.xcs.
# DisableMacrosExecution also covers Python, JavaScript and Basic macros.
_OFFICE_PROFILE = '''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting">
 <prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>
 <prop oor:name="DisableActiveContent" oor:op="fuse"><value>true</value></prop>
 <prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>
 <prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop>
</item>
<item oor:path="/org.openoffice.Office.Writer/Content/Update">
 <prop oor:name="Link" oor:op="fuse"><value>2</value></prop>
 <prop oor:name="Field" oor:op="fuse"><value>false</value></prop>
</item>
<item oor:path="/org.openoffice.Office.Calc/Content/Update">
 <prop oor:name="Link" oor:op="fuse"><value>1</value></prop>
</item>
</oor:items>'''


def _office_command(binary, source, profile, output_dir, ext, data):
    command = [binary, "-env:UserInstallation=" + profile.as_uri(), "--headless", "--nologo", "--nodefault", "--nolockcheck", "--norestore"]
    if ext == "csv":
        try:
            separator = csv.Sniffer().sniff(data[:8192].decode("utf-8"), delimiters=",;\t").delimiter
        except csv.Error:
            separator = ","
        # Token 13=false: formula-looking cells are imported as text.
        command += [f"--infilter=Text - txt - csv (StarCalc):{ord(separator)},34,76,1,,0,true,false,false,false,false,0,false"]
    elif ext == "txt":
        command += ["--infilter=Text (encoded):UTF8,LF,DejaVu Sans,fr-FR"]
    pdf_filter = "calc_pdf_Export" if ext in {"xls", "xlsx", "ods", "csv"} else "impress_pdf_Export" if ext in {"ppt", "pptx", "odp"} else "writer_pdf_Export"
    return command + ["--convert-to", "pdf:" + pdf_filter, "--outdir", str(output_dir), str(source)]


def _run_office(command, directory):
    # No API keys/database URLs inherited by the converter. Never use a shell.
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT"}}
    env.update({"HOME": str(directory), "TMPDIR": str(directory), "SAL_USE_VCLPLUGIN": "svp"})
    worker = [sys.executable, str(Path(__file__).resolve()), "--office-worker", *command]
    if sys.platform == "darwin":
        # Local developer verification; production uses the Linux seccomp worker.
        worker = ["/usr/bin/sandbox-exec", "-p", "(version 1) (allow default) (deny network*) (allow network* (local unix-socket) (remote unix-socket))", *worker]
    try:
        with subprocess.Popen(worker, cwd=directory, env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              start_new_session=True) as process:
            try:
                result = process.wait(timeout=OFFICE_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired as exc:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise ConversionError("La conversion a pris trop de temps. Exportez ce document en PDF depuis votre logiciel, puis déposez-le à nouveau.") from exc
            if result != 0:
                raise ConversionError("La conversion n’a pas pu aboutir. Si le document est protégé, retirez son mot de passe ; sinon, exportez-le en PDF depuis votre logiciel.")
    except ConversionError:
        raise
    except OSError as exc:
        raise ConversionError("Le convertisseur bureautique est temporairement indisponible. Réessayez ou exportez votre document en PDF.") from exc


def _convert_office(data, ext, max_bytes):
    data = _validate_office(data, ext)
    binary = shutil.which("libreoffice") or shutil.which("soffice")
    if not binary:
        raise ConversionError("Le convertisseur bureautique est temporairement indisponible. Exportez votre document en PDF, puis déposez-le à nouveau.")
    with tempfile.TemporaryDirectory(prefix="trainee-document-") as temporary:
        directory = Path(temporary)
        profile = directory / "profile"
        (profile / "user").mkdir(parents=True)
        (profile / "user" / "registrymodifications.xcu").write_text(_OFFICE_PROFILE, encoding="utf-8")
        source = directory / ("document." + ext)
        source.write_bytes(data)
        output_dir = directory / "output"
        output_dir.mkdir()
        _run_office(_office_command(binary, source, profile, output_dir, ext, data), directory)
        output = output_dir / "document.pdf"
        if not output.is_file() or output.stat().st_size == 0:
            raise _invalid()
        if output.stat().st_size > max_bytes:
            raise _too_large(max_bytes)
        result = output.read_bytes()
        _validate_pdf(result)
        return result


def convert_upload(data: bytes, filename: str, *, photo: bool = False,
                   max_bytes: int = 25 * 1024 * 1024) -> tuple[bytes, str]:
    """Return checked/converted bytes and a safe filename, or ConversionError."""
    if not data:
        raise ConversionError("Le fichier est vide. Sélectionnez une nouvelle copie du document.")
    if len(data) > max_bytes:
        raise _too_large(max_bytes)
    ext = str(filename).rsplit(".", 1)[-1].lower() if "." in str(filename) else ""
    if photo and ext not in IMAGE_EXTENSIONS:
        raise ConversionError("La photo d’identité doit être une image (JPEG, PNG, HEIC, WebP…). Sélectionnez la photo originale ; un PDF ne convient pas.")
    if ext not in DOCUMENT_EXTENSIONS:
        raise ConversionError("Ce type de fichier ne peut pas être converti en PDF. Sélectionnez un PDF, une image, un document Word, Excel, PowerPoint, LibreOffice ou texte ; pour un autre format, exportez-le en PDF depuis votre logiciel.")
    if not _slots.acquire(blocking=False):
        raise ConversionError("Une conversion est déjà en cours. Patientez quelques instants, puis réessayez.")
    try:
        if ext == "pdf":
            _validate_pdf(data)
            return data, _output_name(filename, "pdf")
        if ext in IMAGE_EXTENSIONS:
            result, suffix = _convert_image(data, ext, photo, max_bytes)
        else:
            result, suffix = _convert_office(data, ext, max_bytes), "pdf"
        if len(result) > max_bytes:
            raise _too_large(max_bytes)
        return result, _output_name(filename, suffix)
    except OSError as exc:
        raise ConversionError("La conversion est temporairement indisponible. Réessayez dans quelques instants ou exportez votre document en PDF depuis votre logiciel.") from exc
    finally:
        _slots.release()


def _restrict_office_worker():
    """Apply limits in a fresh child (no unsafe threaded preexec_fn)."""
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_EXPANDED_OFFICE_BYTES, MAX_EXPANDED_OFFICE_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if sys.platform.startswith("linux"):
        # Also bounds decompression/rendering by the native Office libraries.
        resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024 * 1024, 1536 * 1024 * 1024))
        import ctypes
        import socket
        lib = ctypes.CDLL("libseccomp.so.2")
        class Argument(ctypes.Structure):
            _fields_ = [("arg", ctypes.c_uint), ("op", ctypes.c_int),
                        ("a", ctypes.c_uint64), ("b", ctypes.c_uint64)]
        lib.seccomp_init.argtypes = [ctypes.c_uint32]
        lib.seccomp_init.restype = ctypes.c_void_p
        lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
        lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
        lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
        lib.seccomp_load.argtypes = [ctypes.c_void_p]
        lib.seccomp_release.argtypes = [ctypes.c_void_p]
        context = lib.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
        if not context:
            raise RuntimeError("seccomp initialization failed")
        try:
            deny = 0x00050000 | errno.EPERM  # SCMP_ACT_ERRNO
            socket_call = lib.seccomp_syscall_resolve_name(b"socket")
            for family in (socket.AF_INET, socket.AF_INET6):
                if socket_call < 0 or lib.seccomp_rule_add(context, deny, socket_call, 1, Argument(0, 4, family, 0)) != 0:
                    raise RuntimeError("seccomp socket rule failed")
            # io_uring can create sockets without the socket syscall.
            ring_call = lib.seccomp_syscall_resolve_name(b"io_uring_setup")
            if ring_call >= 0 and lib.seccomp_rule_add(context, deny, ring_call, 0) != 0:
                raise RuntimeError("seccomp io_uring rule failed")
            if lib.seccomp_load(context) != 0:
                raise RuntimeError("seccomp load failed")
        finally:
            lib.seccomp_release(context)
    elif sys.platform != "darwin":
        raise RuntimeError("unsupported converter isolation platform")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "--office-worker":
        raise SystemExit(2)
    _restrict_office_worker()
    os.execv(sys.argv[2], sys.argv[2:])
