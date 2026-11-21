"""Install the precise Cassandre avatar referenced by CRM email templates.

The source is pinned to the exact Git blob used by the CRM, fetched only at
Docker image build time. It is *not* a generated or cropped screenshot image.
No external image request is needed when recipients open the email.
"""
from hashlib import sha1
from io import BytesIO
from pathlib import Path
import sys

import requests
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "static/images/email/crm-cassandre.png"
SOURCE_URL = (
    "https://raw.githubusercontent.com/integraleacademy/integraleacademyofficiel/"
    "2ed2eae50011b6461981b7ac98459d40bddf0cd6/"
    "public/images/team/cassandre.png"
)
CRM_GIT_BLOB = "64c47eb7349cd504a732d5d5ac08830e864efea8"
MAX_DOWNLOAD = 5 * 1024 * 1024


def exact_original_bytes():
    response = requests.get(SOURCE_URL, timeout=40, stream=True)
    response.raise_for_status()
    try:
        content = bytearray()
        for chunk in response.iter_content(65536):
            content.extend(chunk)
            if len(content) > MAX_DOWNLOAD:
                raise ValueError("CRM portrait exceeds expected maximum size.")
    finally:
        response.close()
    payload = bytes(content)
    expected_blob = sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()
    if expected_blob != CRM_GIT_BLOB:
        raise ValueError("CRM Cassandre portrait differs from the pinned original.")
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("CRM Cassandre portrait is not PNG.")
    return payload


def install(payload, path=DESTINATION):
    with Image.open(BytesIO(payload)) as source:
        if source.format != "PNG":
            raise ValueError("Expected a PNG CRM avatar.")
        avatar = ImageOps.fit(source.convert("RGBA"), (224, 224),
                              method=Image.Resampling.LANCZOS)
        path.parent.mkdir(parents=True, exist_ok=True)
        avatar.save(path, format="PNG", optimize=True)
    with Image.open(path) as checked:
        assert checked.size == (224, 224)
        assert checked.format == "PNG"
    return path


if __name__ == "__main__":
    result = install(exact_original_bytes())
    print("EDOF CRM: verified original Cassandre portrait saved at", result.relative_to(ROOT))
