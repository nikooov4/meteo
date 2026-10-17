"""Start a temporary loopback service, exercise external client, stop service."""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from meteo_bridge.resources import atomic_json, run_metadata, sha256_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--precision", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "reports/validation" / ("precision-http" if args.precision else "acquisition-http")
    output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, METEOBRIDGE_HOME=str(output / "catalog"))
    base = f"http://127.0.0.1:{port}"
    with (output / "server.log").open("w", encoding="utf8") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "meteo_bridge.api:app",
                                    "--host", "127.0.0.1", "--port", str(port)], cwd=root, env=env,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            ready = False
            deadline = time.monotonic() + 25
            with httpx.Client(trust_env=False, timeout=1) as client:
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        ready = client.get(base + "/health").status_code == 200
                    except httpx.HTTPError:
                        pass
                    if ready:
                        break
                    time.sleep(0.1)
            if not ready:
                raise RuntimeError("loopback server did not become ready; see server.log")
            command = [sys.executable, str(root / "examples/acquisition_client.py"),
                       "--url", base, "--output", str(output / "bundle.json")]
            if args.precision:
                example = root / "experiments/runs/precision-diagnostics-v1/daily"
                command.extend(["--precision", "--case", str(example / "case.json"),
                                "--actions", str(example / "actions.json")])
            response = subprocess.run(command,
                                      cwd=root, env=env, capture_output=True, text=True, timeout=60)
            (output / "client.log").write_text(response.stdout + response.stderr, encoding="utf8")
            response.check_returncode()
            bundle = json.loads((output / "bundle.json").read_text(encoding="utf8"))
            context = {"metadata": run_metadata(), "url": base, "local_checker": bundle["local_checker"],
                       "bundle_sha256": sha256_file(output / "bundle.json"),
                       "client_sha256": sha256_file(root / "examples/acquisition_client.py")}
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    context["server_stopped"] = process.poll() is not None
    atomic_json(output / "context.json", context)
    print(json.dumps({"valid": context["local_checker"]["valid"], "server_stopped": context["server_stopped"]}))


if __name__ == "__main__":
    main()
