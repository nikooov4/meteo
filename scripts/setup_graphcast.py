"""Prepare pinned GraphCast assets and the two-state example for the application."""
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "workers" / "graphcast"
RUNTIME = PROJECT / "runtime" / "graphcast"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url, path, sha):
    if path.is_file() and digest(path) == sha:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": "MeteoBridge"})
    with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
        while block := response.read(1048576):
            output.write(block)
    if digest(temporary) != sha:
        raise ValueError(f"SHA256 mismatch: {path.name}")
    temporary.replace(path)
    print(f"Prepared {path.name}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Verify installed assets without network or GPU")
    args = parser.parse_args()
    assets = json.loads((SOURCE / "assets-manifest.json").read_text(encoding="utf-8"))
    seed = PROJECT / "data" / "graphcast-inputs" / "era5-example-2022-01-01.nc"
    for item in assets["files"]:
        path = RUNTIME / item["path"].replace("\\", "/")
        example = path.name == "example.nc"
        if example and seed.exists():
            continue
        if args.check:
            if not path.exists() or digest(path) != item["sha256"]:
                raise ValueError(f"Missing or changed asset: {path}")
        else:
            download(item["url"], path, item["sha256"])
        if example and not args.check:
            import xarray as xr

            with xr.open_dataset(path, engine="scipy") as raw:
                selected = raw.isel(time=slice(0, 2)).load()
            seed.parent.mkdir(parents=True, exist_ok=True)
            selected.to_netcdf(seed, engine="scipy", format="NETCDF3_64BIT")
            path.unlink()  # Only the two input states belong in the application.
    sources = json.loads((SOURCE / "sources-manifest.json").read_text(encoding="utf-8"))
    for name, item in sources.items():
        destination = RUNTIME / "vendor" / name
        marker = destination / ".meteo-commit"
        ready = marker.exists() and marker.read_text().strip() == item["commit"]
        if args.check:
            if not ready or not (destination / "LICENSE").is_file():
                raise ValueError(f"Source not prepared: {name}")
            continue
        if ready:
            continue
        archive = RUNTIME / "vendor" / f"{name}.zip"
        download(item["url"], archive, item["sha256"])
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                relative = Path(*Path(member.filename).parts[1:])
                target = (destination / relative).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise ValueError("Unsafe source archive path")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read(member))
        marker.write_text(item["commit"], encoding="utf-8")
        archive.unlink()
    print("GraphCast assets verified; no model was loaded into GPU.", flush=True)


if __name__ == "__main__":
    main()
