import json
import os
import sqlite3
from pathlib import Path

from .resources import sha256_file


def connect():
    root = Path(os.environ.get("METEOBRIDGE_HOME", ".meteo")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "catalog.sqlite", timeout=20)
    db.execute("CREATE TABLE IF NOT EXISTS archives (name TEXT PRIMARY KEY, path TEXT, hash TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS datasets (id TEXT PRIMARY KEY, payload TEXT)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS queries (id TEXT, revision INTEGER, payload TEXT, PRIMARY KEY(id,revision))"
    )
    db.commit()
    return db


def register_manifest(name, manifest):
    path = Path(manifest).resolve()
    data = json.loads(path.read_text())
    if data["status"] != "complete" or not data["shards"]:
        raise ValueError("only completed manifest datasets can be registered")
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO archives VALUES (?,?,?)", (name, str(path), sha256_file(path)))
    return {
        "name": name,
        "manifest": str(path),
        "sha256": sha256_file(path),
        "data_bytes": data["data_bytes"],
    }


def archives():
    with connect() as db:
        return [
            {"name": n, "path": p, "sha256": h}
            for n, p, h in db.execute("SELECT name,path,hash FROM archives")
        ]
