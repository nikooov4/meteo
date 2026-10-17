import hashlib
import json
import os
import platform
import re
import subprocess
import threading
import time
from pathlib import Path

import psutil


def size_bytes(value):
    if isinstance(value, int):
        return value
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(B|KB|MB|GB|TB|KiB|MiB|GiB|TiB)?", value, re.I)
    if not m:
        raise ValueError(f"invalid byte size: {value}")
    units = {
        "b": 1,
        "kb": 10**3,
        "mb": 10**6,
        "gb": 10**9,
        "tb": 10**12,
        "kib": 2**10,
        "mib": 2**20,
        "gib": 2**30,
        "tib": 2**40,
    }
    from decimal import Decimal

    return int(Decimal(m[1]) * units[(m[2] or "B").lower()])


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(4 * 2**20):
            h.update(block)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    with partial.open("w", encoding="utf8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    # Windows scanners/readers can briefly deny ReplaceFile/MoveFileEx sharing.
    for attempt in range(10):
        try:
            os.replace(partial, path)
            break
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.02 * (attempt + 1))


def safe_data_path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path.suffix not in {".nc", ".parquet"}:
        raise ValueError("unsafe/non-data manifest path")
    return path


class MemoryGuard:
    """Sample summed resident sets of coordinator and descendants (OS cache excluded)."""

    def __init__(self, limit):
        self.limit, self.peak, self.exceeded = size_bytes(limit), 0, False
        self.stop = threading.Event()
        self.proc = psutil.Process()
        self.thread = threading.Thread(target=self._monitor, daemon=True)

    def sample(self):
        total = 0
        try:
            processes = [self.proc] + self.proc.children(recursive=True)
        except psutil.Error:
            processes = [self.proc]
        for process in processes:
            try:
                total += process.memory_info().rss
            except psutil.Error:
                pass
        self.peak = max(total, self.peak)
        self.exceeded |= total > self.limit

    def _monitor(self):
        while not self.stop.wait(0.05):
            self.sample()

    def check(self):
        self.sample()
        if self.exceeded:
            raise MemoryError(f"process-tree RSS budget exceeded: {self.peak} > {self.limit}")

    def __enter__(self):
        self.sample()
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()
        self.sample()


def environment():
    import importlib.metadata as md

    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "physical_ram_bytes": psutil.virtual_memory().total,
        "versions": {p: md.version(p) for p in ("numpy", "scipy", "pydantic", "netCDF4", "pyarrow")},
        "memory_measurement": "50 ms sampled sum of process-tree RSS; OS filesystem cache excluded",
    }


def timed_io():
    try:
        return psutil.Process().io_counters()._asdict()
    except (psutil.Error, AttributeError):
        return {}


def source_files(root):
    return sorted(
        path
        for directory in ("src", "scripts", "ui", "tests")
        for path in (root / directory).rglob("*.py")
    )


def code_hash():
    root = Path(__file__).resolve().parents[2]
    h = hashlib.sha256()
    for path in source_files(root):
        h.update(path.relative_to(root).as_posix().encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def git_metadata(root):
    """Read revision/dirty state without changing Git config or requiring Git."""
    # A dataset/temp directory inside another checkout is not itself a project
    # root. Do not silently attribute its provenance to an ancestor repository.
    if not (Path(root) / ".git").exists():
        return {"git_revision": "not_a_git_repository", "git_dirty": None}
    try:
        command = ["git", "-C", str(root)]
        revision = subprocess.run(command + ["rev-parse", "--verify", "HEAD"],
                                  capture_output=True, text=True, timeout=5)
        if revision.returncode:
            state = "unborn_or_unavailable" if (Path(root) / ".git").exists() else "not_a_git_repository"
            return {"git_revision": state, "git_dirty": None}
        status = subprocess.run(command + ["status", "--porcelain", "--untracked-files=normal"],
                                capture_output=True, text=True, timeout=5)
        return {"git_revision": revision.stdout.strip(),
                "git_dirty": bool(status.stdout) if status.returncode == 0 else None}
    except (OSError, subprocess.TimeoutExpired):
        return {"git_revision": "unavailable", "git_dirty": None}


def run_metadata():
    import zipfile

    root = Path(__file__).resolve().parents[2]
    lock = root / "uv.lock"
    revision = code_hash()
    snapshot = root / "experiments" / "source_snapshots" / f"{revision}.zip"
    if not snapshot.exists():
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(snapshot, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for path in source_files(root):
                z.write(path, path.relative_to(root).as_posix())
            for name in ("pyproject.toml", "uv.lock", ".python-version"):
                if (root / name).exists():
                    z.write(root / name, name)
    return {
        **environment(),
        "code_sha256": revision,
        "source_snapshot": str(snapshot.relative_to(root)),
        "source_scope": "src, scripts, ui and tests Python files; project/lock metadata in ZIP",
        **git_metadata(root),
        "uv_lock_sha256": sha256_file(lock) if lock.exists() else None,
        "unix_time": time.time(),
    }
