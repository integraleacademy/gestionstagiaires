"""Extract the BTS rates from the official France compétences workbooks.

Run with --directory pointing to the downloaded, unmodified .xlsx files named
2025-09.xlsx and 2026-09.xlsx. No applicant or employer data is used.
The runtime only reads the resulting small, versioned JSON reference.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import gzip
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

SOURCES = (
    ("2025-09", "2025-09-01", "2026-05-28", "https://www.francecompetences.fr/app/uploads/2026/05/Referentiel-des-NPEC-01.09.2025_vMAJ-28.05.2026.zip"),
    ("2026-09", "2026-09-01", "2026-08-31", "https://www.francecompetences.fr/app/uploads/2026/08/Referentiel-unique-des-NPEC-1er-septembre-2026.zip"),
)
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def rows(archive, sheet, strings):
    with archive.open("xl/worksheets/sheet%d.xml" % sheet) as stream:
        for _, row in ET.iterparse(stream, events=("end",)):
            if row.tag != NS + "row":
                continue
            values = {}
            for cell in row:
                column = re.sub(r"\d", "", cell.attrib["r"])
                value = cell.find(NS + "v")
                if value is not None:
                    raw = value.text or ""
                    values[column] = strings[int(raw)] if cell.get("t") == "s" else raw
                elif cell.get("t") == "inlineStr":
                    values[column] = "".join(t.text or "" for t in cell.iter(NS + "t"))
            yield values
            row.clear()


def extract(path, name, effective, published, url):
    with zipfile.ZipFile(path) as archive:
        strings = ["".join(t.text or "" for t in si.iter(NS + "t"))
                   for si in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        cpnes, idccs = {}, {}
        for row in rows(archive, 4, strings):
            if not row.get("A", "").isdigit():
                continue
            code = row["A"]
            cpnes[code] = row["B"]
            for idcc in re.findall(r"\d+", row.get("C", "")):
                idccs.setdefault(idcc.zfill(4), set()).add(code)
        groups = {}
        for row in rows(archive, 3, strings):
            if row.get("D", "").strip().upper() != "BTS":
                continue
            codes = re.findall(r"RNCP(\d+)", row["A"])
            if not codes or not row.get("E", "").isdigit():
                raise ValueError("Unexpected BTS RNCP/CPNE row")
            # Excel stores dates as serial day numbers; the workbook uses 1900.
            start = (dt.date(1899, 12, 30) + dt.timedelta(days=int(float(row["I"])))).isoformat()
            amount = float(row["G"])
            if amount <= 0 or amount != int(amount):
                raise ValueError("Unexpected NPEC amount")
            group = groups.setdefault(row["A"], {"codes": codes, "title": row["B"], "rates": {}})
            rate = [int(amount) * 100, start, row.get("H", "")]
            if row["E"] in group["rates"] and group["rates"][row["E"]] != rate:
                raise ValueError("Conflicting NPEC rates")
            group["rates"][row["E"]] = rate
        if len(groups) < 80 or len(idccs) < 200:
            raise ValueError("Incomplete reference")
    return {"id": name, "effective_from": effective, "published_at": published,
            "source_url": url, "xlsx_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "cpne_names": cpnes, "idcc_to_cpne": {k: sorted(v) for k, v in idccs.items()},
            "certifications": list(groups.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data/bts_npec.json.gz")
    args = parser.parse_args()
    editions = []
    for name, effective, published, url in SOURCES:
        edition = extract(args.directory / (name + ".xlsx"), name, effective, published, url)
        editions.append(edition)
        print(name, len(edition["certifications"]), "BTS", len(edition["idcc_to_cpne"]), "IDCC", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps({"schema": 1, "editions": editions}, ensure_ascii=False,
                         sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    args.output.write_bytes(gzip.compress(payload, mtime=0))
    print(args.output, args.output.stat().st_size, "bytes", flush=True)


if __name__ == "__main__":
    main()
