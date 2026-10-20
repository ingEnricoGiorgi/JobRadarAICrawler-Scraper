"""Build offline gazetteer from ISTAT and attributed municipal coordinates.

Run explicitly: python tools/update_geodata.py. Network is never used at app startup.
"""
import csv
from datetime import datetime, timezone
import hashlib
from io import BytesIO, StringIO
import json
from pathlib import Path
import urllib.request
import ssl

import truststore

from openpyxl import load_workbook

TARGET = Path(__file__).resolve().parents[1] / "jobradar" / "data"
SOURCES = {
    "istat": "https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.xlsx",
    "coordinates": "https://raw.githubusercontent.com/opendatasicilia/comuni-italiani/main/dati/coordinate.csv",
    "coordinate_names": "https://raw.githubusercontent.com/opendatasicilia/comuni-italiani/main/dati/comuni.csv",
}


def build():
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    blobs = {k: urllib.request.urlopen(url, timeout=90, context=context).read() for k, url in SOURCES.items()}
    workbook = load_workbook(BytesIO(blobs["istat"]), read_only=True, data_only=True)
    rows = iter(workbook.active.values)
    headers = next(rows)
    print("ISTAT columns:", headers)

    def find(fragment):
        return next(i for i, name in enumerate(headers) if name and fragment.lower() in str(name).lower())

    cols = {
        "code": find("comune formato alfanumerico"),
        "name": find("Denominazione (Italiana e straniera)"),
        "province_code": find("Sigla automobilistica"),
        "province": find("Denominazione dell'Unità territoriale"),
        "region_code": find("Codice Regione"),
        "region": find("Denominazione Regione"),
    }
    old_code_column = find("107 Province (dal 2017 al 2025)")
    italian_name_column = find("Denominazione in italiano")
    names = {r["pro_com_t"].zfill(6): r["comune"] for r in
             csv.DictReader(StringIO(blobs["coordinate_names"].decode("utf-8-sig")))}
    coordinates = {r["pro_com_t"].zfill(6): r for r in
                   csv.DictReader(StringIO(blobs["coordinates"].decode("utf-8-sig")))}
    output = []
    for row in rows:
        if row[cols["code"]] is None:
            continue
        r = {name: str(row[i]).strip() if row[i] is not None else "" for name, i in cols.items()}
        r["code"] = r["code"].zfill(6)
        r["region_code"] = r["region_code"].zfill(2)
        r.update(latitude="", longitude="")
        # A matching ID alone is unsafe after administrative recoding. Also require exact denomination.
        official_names = {r["name"], str(row[italian_name_column]).strip()}
        historical = str(row[old_code_column]).zfill(6) if row[old_code_column] is not None else None
        candidates = [code for code in (r["code"], historical) if code and names.get(code) in official_names]
        point = next((coordinates[code] for code in candidates if code in coordinates), None)
        if point:
            try:
                lat, lon = float(point["lat"]), float(point["long"])
                if 35 <= lat <= 48 and 6 <= lon <= 19:
                    r.update(latitude=lat, longitude=lon)
            except (TypeError, ValueError):
                pass
        output.append(r)
    if len(output) < 7800 or len({r["code"] for r in output}) != len(output):
        raise ValueError("Archivio ISTAT incompleto o duplicato")
    TARGET.mkdir(parents=True, exist_ok=True)
    temporary = TARGET / "municipalities.csv.tmp"
    with temporary.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(cols) + ["latitude", "longitude"])
        writer.writeheader()
        writer.writerows(output)
    temporary.replace(TARGET / "municipalities.csv")
    manifest = {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "sources": {k: {"url": url, "sha256": hashlib.sha256(blobs[k]).hexdigest()} for k, url in SOURCES.items()},
        "municipalities": len(output),
        "with_coordinates": sum(bool(r["latitude"]) for r in output),
        "coordinate_system": "EPSG:4326",
        "coordinate_description": "Punto municipale da Open Data Sicilia, fonte integrativa non ISTAT; join per codice corrente o storico ufficiale ISTAT e denominazione ufficiale esatta (anche italiana)",
    }
    (TARGET / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()
