"""Process-local CUDA setup for WinJAX in a Unicode Windows workspace."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path


def prepare_native_cuda() -> dict:
    root = Path(__file__).resolve().parents[2] / "runtime" / "graphcast"
    cuda = root / ".venv-gpu" / "Lib" / "site-packages" / "nvidia" / "cu13"
    if not (cuda / "bin" / "ptxas.exe").is_file():
        raise FileNotFoundError("CUDA compiler was not installed in the GPU environment")
    get_short_path = ctypes.windll.kernel32.GetShortPathNameW
    get_short_path.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    get_short_path.restype = ctypes.c_uint32
    buffer = ctypes.create_unicode_buffer(32768)
    if not get_short_path(str(cuda), buffer, len(buffer)):
        raise OSError("Cannot obtain the Windows short path to CUDA")
    short = buffer.value
    if not short.isascii():
        raise RuntimeError("WinJAX CUDA compilation requires an ASCII CUDA path on this Windows build")
    for variable in ("CUDA_ROOT", "CUDA_HOME", "CUDA_PATH"):
        os.environ[variable] = short
    os.environ["XLA_PYTHON_CLIENT_PREALLOCATE"] = "false"
    # This wheel's built-in autotuning fill kernel is not compiled for sm_86.
    # Skip the autotuner and use standard CUDA GEMMs rather than Triton.
    flags = "--xla_gpu_autotune_level=0 --xla_gpu_enable_triton_gemm=false"
    os.environ["XLA_FLAGS"] = (os.environ.get("XLA_FLAGS", "") + " " + flags).strip()
    return {"cuda_root": str(cuda), "cuda_root_short": short,
            "xla_flags": os.environ["XLA_FLAGS"]}
