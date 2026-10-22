import os
import shutil
import socket
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import netCDF4 as nc
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
DLL = ROOT / "dotnet/MeteoBridge.Era5/bin/Release/net10.0/MeteoBridge.Era5.dll"


@pytest.fixture
def dotnet_archive(tmp_path, request):
    if not DLL.exists() or not shutil.which("dotnet"):
        pytest.skip("Build the C# reader first: dotnet build MeteoBridge.sln -c Release")
    for ordinal, dates in enumerate(([0, 12], [36, 48])):
        with nc.Dataset(tmp_path / f"part-{ordinal}.nc", "w") as dataset:
            for name, length in [("forecast_initial_time", 2), ("forecast_hour", 12),
                                 ("latitude", 2), ("longitude", 3)]:
                dataset.createDimension(name, length)
            stamp = dataset.createVariable("forecast_initial_time", "i8", ("forecast_initial_time",))
            stamp.units = "hours since 2023-01-01 06:00:00"
            stamp[:] = dates
            dataset.createVariable("forecast_hour", "i4", ("forecast_hour",))[:] = np.arange(1, 13)
            dataset.createVariable("latitude", "f8", ("latitude",))[:] = [42, 40]
            dataset.createVariable("longitude", "f8", ("longitude",))[:] = [0, 1, 359]
            values = dataset.createVariable("LSP", "f4", ("forecast_initial_time", "forecast_hour",
                                                          "latitude", "longitude"), fill_value=9.999e20)
            values.units, values.rda_dataset = "m", "ds633.0"
            values[:] = np.arange(144, dtype="float32").reshape(2, 12, 2, 3) / 100000 + ordinal / 100
            values[0, 1, 0, 0] = -1
            values[0, 2, 1, 1] = values._FillValue
    shutil.copyfile(tmp_path / "part-0.nc", tmp_path / "z-duplicate.nc")
    folder = tmp_path / "архив"
    folder.mkdir()
    for path in tmp_path.glob("*.nc"):
        path.rename(folder / path.name)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    log = (tmp_path / "server.log").open("w", encoding="utf8")
    arguments = ["dotnet", str(DLL), "--urls", f"http://127.0.0.1:{port}", "--Era5:Data", str(folder),
                 "--Era5:Workers", "2", "--Era5:LookaheadCycles", "3"]
    if getattr(request, "param", None) == "downloads":
        remote = request.getfixturevalue("fake_ncar")
        arguments.extend(["--Era5:ArchiveBaseUrl", remote["url"]])
    process = subprocess.Popen(
        arguments,
        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False) as client:
            for attempt in range(100):
                if process.poll() is not None:
                    pytest.fail((tmp_path / "server.log").read_text(encoding="utf8"))
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(.05)
            else:
                pytest.fail("C# service did not start")
            yield client, folder
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()


def test_dotnet_runs_without_python_or_research_directories(dotnet_archive, tmp_path):
    _, folder = dotnet_archive
    deployment = tmp_path / "отдельный сайт"
    binary = deployment / "bin"
    shutil.copytree(DLL.parent, binary)
    (deployment / "MeteoBridge.sln").touch()
    assert not (deployment / ".venv").exists()
    assert not (deployment / "pyproject.toml").exists()
    assert not (deployment / "research").exists()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    with (tmp_path / "isolated-server.log").open("w", encoding="utf8") as log:
        process = subprocess.Popen(["dotnet", str(binary / DLL.name), "--urls", f"http://127.0.0.1:{port}",
                                    "--Era5:Data", str(folder)], cwd=deployment, stdout=log, stderr=subprocess.STDOUT)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False) as client:
                for attempt in range(100):
                    assert process.poll() is None, (tmp_path / "isolated-server.log").read_text(encoding="utf8")
                    try:
                        health = client.get("/health").raise_for_status().json()
                        break
                    except httpx.TransportError:
                        time.sleep(.05)
                else:
                    pytest.fail("Isolated C# service did not start")
                assert Path(health["project_root"]) == deployment
                for endpoint in ["/", "/downloads", "/plotly.min.js", "/land.json"]:
                    client.get(endpoint).raise_for_status()
                catalog = client.get("/map-archive/catalog").raise_for_status().json()
                frame = client.get("/map-archive/frame", params={"hour": 0,
                                   "manifest_sha256": catalog["manifest_sha256"]}).raise_for_status()
                assert len(frame.content) == catalog["frame_bytes"]
                assert frame.headers["X-Data-Available"] == "true"
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_dotnet_matches_known_values_across_files_gaps_masks_and_duplicates(dotnet_archive):
    client, _ = dotnet_archive
    catalog = client.get("/map-archive/catalog").raise_for_status().json()
    assert catalog["available_hours"] == 48 and catalog["gap_hours"] == 12
    assert catalog["duplicate_hours"] == 24
    assert catalog["available_ranges"] == [
        ["2023-01-01T06:00:00+00:00", "2023-01-02T06:00:00+00:00"],
        ["2023-01-02T18:00:00+00:00", "2023-01-03T18:00:00+00:00"],
    ]
    grid = client.get("/grid").raise_for_status().json()
    assert grid == {"latitude": [40, 42], "longitude": [-1, 0, 1]}
    origin = datetime(2023, 1, 1, 6, tzinfo=timezone.utc)
    for hour in range(60):
        response = client.get("/map-archive/frame", params={"hour": hour, "manifest_sha256": catalog["manifest_sha256"]})
        response.raise_for_status()
        assert response.headers["X-Frame-Start"] == (origin + timedelta(hours=hour)).isoformat()
        if 24 <= hour < 36:
            expected = np.full((2, 3), np.nan, dtype="float32")
            assert response.headers["X-Data-Available"] == "false"
            assert response.headers["X-Cycle-UTC"] == ""
        else:
            ordinal = int(hour >= 36)
            local_hour = hour - ordinal * 36
            cycle, step = divmod(local_hour, 12)
            source_indices = np.array([[5, 3, 4], [2, 0, 1]], dtype="float32") + cycle * 72 + step * 6
            expected = (source_indices / np.float32(100000) + np.float32(ordinal) / np.float32(100)) * np.float32(1000)
            if cycle == 0 and step == 1:
                expected[1, 1] = np.nan
            if cycle == 0 and step == 2:
                expected[0, 2] = np.nan
            assert response.headers["X-Data-Available"] == "true"
            assert response.headers["X-Cycle-UTC"] == (origin + timedelta(hours=hour - step)).isoformat()
        np.testing.assert_array_equal(np.frombuffer(response.content, dtype="<f4").reshape(2, 3), expected)


def test_dotnet_prefetch_is_parallel_bounded_and_reuses_cycles(dotnet_archive):
    client, _ = dotnet_archive
    catalog = client.get("/map-archive/catalog").raise_for_status().json()
    params = {"hour": 0, "manifest_sha256": catalog["manifest_sha256"]}
    client.get("/map-archive/frame", params=params).raise_for_status()
    for attempt in range(100):
        metrics = client.get("/map-archive/metrics").raise_for_status().json()
        if metrics["ready_cycles"] == 4:
            break
        time.sleep(.02)
    assert metrics["ready_cycles"] == 4
    assert metrics["peak_parallel_workers"] == 2
    assert metrics["cached_cycles"] <= metrics["cache_limit"]
    assert metrics["cached_bytes"] <= 6 * 12 * catalog["frame_bytes"]
    for hour in [1, 12, 36, 48]:
        client.get("/map-archive/frame", params={**params, "hour": hour, "prefetch": "true"}).raise_for_status()
    after = client.get("/map-archive/metrics").json()
    assert after["cycle_reads"] == 4
    assert after["cache_hits"] >= 4


def test_dotnet_rejects_changed_sources_and_invalid_selections(dotnet_archive):
    client, folder = dotnet_archive
    catalog = client.get("/map-archive/catalog").raise_for_status().json()
    params = {"hour": 0, "manifest_sha256": catalog["manifest_sha256"], "end_hour": 12}
    client.get("/map-archive/frame", params=params).raise_for_status()
    for attempt in range(100):
        metrics = client.get("/map-archive/metrics").json()
        if metrics["queued_cycles"] == 0:
            break
        time.sleep(.01)
    assert metrics["cycle_reads"] == 1
    path = folder / "part-0.nc"
    signature = path.stat()
    os.utime(path, ns=(signature.st_atime_ns, signature.st_mtime_ns + 1_000_000_000))
    assert client.get("/map-archive/frame", params=params).status_code == 422
    assert client.get("/map-archive/frame", params={**params, "manifest_sha256": "wrong"}).status_code == 409
    assert client.get("/map-archive/frame", params={**params, "hour": -1}).status_code == 422
    assert client.get("/map-archive/range", params={"start": "2023-01-01T06:30:00Z",
                                                  "end": "2023-01-02T06:00:00Z"}).status_code == 422
    assert client.get("/").status_code == 200
    assert client.get("/plotly.min.js").status_code == 200


def test_dotnet_occupied_port_falls_back_and_launcher_reuses_server(dotnet_archive, tmp_path):
    client, folder = dotnet_archive
    output = tmp_path / "second-server.log"
    with output.open("w", encoding="utf8") as log:
        process = subprocess.Popen(["dotnet", str(DLL), "--urls", str(client.base_url).rstrip("/"),
                                    "--Era5:Data", str(folder)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        try:
            import re

            for attempt in range(100):
                text = output.read_text(encoding="utf8")
                match = re.search(r"Карта ERA5: (http://127\.0\.0\.1:\d+)/", text)
                if match:
                    break
                assert process.poll() is None, text
                time.sleep(.05)
            else:
                pytest.fail(text)
            assert match[1] != str(client.base_url).rstrip("/")
            assert httpx.get(match[1] + "/health", trust_env=False).json()["application"] == "MeteoBridge.Era5"
            assert "Hosting failed to start" not in text
            assert "AddressInUseException" not in text
            launcher = subprocess.run(["pwsh", "-NoProfile", "-File", str(ROOT / "start_app.ps1"),
                                       "-Port", str(client.base_url.port), "-Data", str(folder)],
                                      cwd=ROOT, capture_output=True, text=True, encoding="utf8", timeout=15)
            assert launcher.returncode == 0, launcher.stdout + launcher.stderr
            assert "уже запущена" in launcher.stdout
        finally:
            process.terminate()
            process.wait(timeout=10)


@pytest.fixture
def fake_ncar(tmp_path):
    import hashlib
    import http.server
    import threading
    from urllib.parse import parse_qs, urlsplit
    from xml.sax.saxutils import escape

    paths = []
    for month in (1, 2):
        path = tmp_path / f"remote-{month}.nc"
        with nc.Dataset(path, "w") as dataset:
            for name, length in [("forecast_initial_time", 1), ("forecast_hour", 12),
                                 ("latitude", 2), ("longitude", 3)]:
                dataset.createDimension(name, length)
            stamp = dataset.createVariable("forecast_initial_time", "i8", ("forecast_initial_time",))
            stamp.units = "hours since 2023-01-01 06:00:00"
            stamp[:] = [(month - 1) * 31 * 24]
            dataset.createVariable("forecast_hour", "i4", ("forecast_hour",))[:] = np.arange(1, 13)
            dataset.createVariable("latitude", "f8", ("latitude",))[:] = [42, 40]
            dataset.createVariable("longitude", "f8", ("longitude",))[:] = [0, 1, 359]
            values = dataset.createVariable("LSP", "f4", ("forecast_initial_time", "forecast_hour", "latitude", "longitude"))
            values.units, values.rda_dataset = "m", "ds633.0"
            values[:] = .002 * month
        paths.append(path)
    objects = {}
    for month, path in enumerate(paths, 1):
        key = f"e5.oper.fc.sfc.accumu/2023{month:02d}/e5.oper.fc.sfc.accumu.128_142_lsp.ll025sc.2023{month:02d}0106_2023{month:02d}1606.nc"
        payload = path.read_bytes() + (b"\0" * (5 * 1048576) if month == 2 else b"")
        objects[key] = {"payload": payload, "etag": '"' + hashlib.sha256(payload).hexdigest() + '"'}
    remote = {"objects": objects, "ranges": [], "requests": [], "slow": True}

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):
            remote["requests"].append(self.path)
            parsed = urlsplit(self.path)
            if parsed.query:
                prefix = parse_qs(parsed.query)["prefix"][0]
                content = "".join(f"<Contents><Key>{escape(key)}</Key><Size>{len(item['payload'])}</Size>"
                                  f"<ETag>{escape(item['etag'])}</ETag></Contents>"
                                  for key, item in objects.items() if key.startswith(prefix))
                body = (f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                        f"<IsTruncated>false</IsTruncated>{content}</ListBucketResult>").encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            key = parsed.path.lstrip("/")
            item = objects[key]
            if self.headers.get("If-Match") != item["etag"]:
                self.send_error(412)
                return
            first, last = map(int, self.headers["Range"].removeprefix("bytes=").split("-"))
            remote["ranges"].append((key, first, last))
            body = item["payload"][first:last + 1]
            self.send_response(206)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Range", f"bytes {first}-{last}/{len(item['payload'])}")
            self.end_headers()
            try:
                for offset in range(0, len(body), 32768):
                    self.wfile.write(body[offset:offset + 32768])
                    self.wfile.flush()
                    if remote["slow"]:
                        time.sleep(.003)
            except (ConnectionError, OSError):
                pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    remote["url"] = f"http://127.0.0.1:{server.server_port}"
    try:
        yield remote
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("dotnet_archive", ["downloads"], indirect=True)
def test_dotnet_archive_download_cancel_resume_and_refresh(dotnet_archive, fake_ncar):
    import json

    client, folder = dotnet_archive
    first, second = fake_ncar["objects"].items()
    assert httpx.get(fake_ncar["url"], params={"prefix": "e5.oper.fc.sfc.accumu/202301/"},
                     trust_env=False).status_code == 200
    (folder / first[0].rsplit("/", 1)[1]).write_bytes(first[1]["payload"])
    old = client.get("/map-archive/catalog").raise_for_status().json()
    listing = client.get("/api/archive/files", params={"year": 2023})
    assert listing.status_code == 200, listing.text + str(fake_ncar["requests"]) + (folder.parent / "server.log").read_text(encoding="utf8")
    files = listing.json()
    assert len(files) == 2 and files[0]["downloaded"]
    assert files[0]["state"] == "downloaded" and files[1]["state"] == "available"
    assert files[1]["start_utc"] == "2023-02-01T06:00:00Z"
    assert files[1]["end_utc"] == "2023-02-16T06:00:00Z"
    name = second[0].rsplit("/", 1)[1]
    partial = folder / (name + ".partial")
    partial.write_bytes(second[1]["payload"][:4096])
    (folder / (name + ".download.json")).write_text(json.dumps({"url": fake_ncar["url"] + "/" + second[0],
         "etag": second[1]["etag"], "bytes": len(second[1]["payload"])}), encoding="utf8")
    response = client.post("/api/archive/download", json={"key": second[0]})
    response.raise_for_status()
    for attempt in range(100):
        if fake_ncar["ranges"]:
            break
        time.sleep(.01)
    client.post("/api/archive/cancel", json={"key": second[0]}).raise_for_status()
    for attempt in range(100):
        files = client.get("/api/archive/files", params={"year": 2023}).json()
        if files[1]["state"] == "paused":
            break
        time.sleep(.01)
    assert files[1]["state"] == "paused"
    assert fake_ncar["ranges"][0][1] == 4096
    assert not (folder / name).exists()
    fake_ncar["slow"] = False
    client.post("/api/archive/download", json={"key": second[0]}).raise_for_status()
    for attempt in range(200):
        files = client.get("/api/archive/files", params={"year": 2023}).json()
        if files[1]["state"] in {"downloaded", "failed"}:
            break
        time.sleep(.02)
    assert files[1]["state"] == "downloaded", files[1]
    assert (folder / name).read_bytes() == second[1]["payload"]
    assert not partial.exists()
    client.get("/").raise_for_status()
    updated = client.get("/map-archive/catalog").raise_for_status().json()
    assert updated["file_count"] == old["file_count"] + 1
    assert updated["available_hours"] == old["available_hours"] + 12
    assert updated["manifest_sha256"] != old["manifest_sha256"]
    assert client.post("/api/archive/download", json={"key": "../../bad.nc"}).status_code == 422
    assert client.post("/api/archive/download", json={"key": second[0]}, headers={"Origin": "https://example.com"}).status_code == 403
    assert client.get("/downloads").status_code == 200
