"""Fetch three small public station archives; preserve a seven-day bounded CSV excerpt."""

import csv
import io
import json
import zipfile
from pathlib import Path

import httpx

from meteo_bridge.resources import atomic_json, sha256_file

BASE = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/precipitation/"
KEYS = [
    "stundenwerte_RR_00191_20050301_20251231_hist.zip",
    "stundenwerte_RR_00433_19950901_20251231_hist.zip",
    "stundenwerte_RR_01048_19950901_20251231_hist.zip",
]


def main():
    raw = Path(".meteo/raw/dwd")
    raw.mkdir(parents=True, exist_ok=True)
    out = Path("data/real/dwd")
    out.mkdir(parents=True, exist_ok=True)
    manifests = []
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for key in KEYS:
            path = raw / key
            url = BASE + "historical/" + key
            if not path.exists():
                with client.stream("GET", url) as r:
                    r.raise_for_status()
                    with path.open("wb") as f:
                        for block in r.iter_bytes(65536):
                            if f.tell() + len(block) > 4 * 2**20:
                                raise ValueError("DWD archive budget")
                            f.write(block)
            rows = []
            metadata = []
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    if info.file_size > 64 * 2**20:
                        raise ValueError("ZIP member exceeds bound")
                    if info.filename.startswith("produkt_rr_stunde"):
                        with z.open(info) as f:
                            for row in csv.DictReader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";"):
                                row = {k.strip(): v.strip() for k, v in row.items()}
                                if "2023010100" <= row["MESS_DATUM"] < "2023010800":
                                    rows.append(row)
                    elif "Parameter" in info.filename:
                        text = z.read(info).decode("latin1")
                        metadata.append({"file": info.filename, "text": text})
                        print(text[:6000].encode("ascii", "backslashreplace").decode())
            dest = out / (key.split("_")[2] + "-20230101-07.csv")
            with dest.open("w", newline="", encoding="utf8") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            manifests.append(
                {
                    "dataset_id": dest.stem,
                    "provider": "DWD",
                    "product_kind": "station_observation",
                    "version": "historical archive listing 2026-06-10",
                    "request": {"days": "2023-01-01/07"},
                    "url": url,
                    "license": "CC-BY-4.0",
                    "sha256": sha256_file(dest),
                    "raw_archive_sha256": sha256_file(path),
                    "raw_archive_bytes": path.stat().st_size,
                    "rows": len(rows),
                    "path": str(dest),
                    "parameter_metadata": metadata,
                    "documentation_version": "DWD v24.03, updated 2024-05-06",
                }
            )
    atomic_json("data/manifests/dwd-subset.json", manifests)
    print(json.dumps([{k: m[k] for k in ("dataset_id", "rows", "sha256")} for m in manifests]))


if __name__ == "__main__":
    main()
