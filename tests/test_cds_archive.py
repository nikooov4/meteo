import http.server
import json
import os
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
import numpy as np
import pytest
from raster_fixtures import grib1
from test_archive_sources import wait_download
from test_era5_dotnet import DLL, ROOT
from test_multiformat import frame, upload

pytest_plugins = ["test_era5_dotnet"]
TOKEN = "test-only-cds-token"


@pytest.fixture
def fake_cds(tmp_path):
    remote = {"requests": [], "jobs": {}, "waiting": False, "reject": False, "unsafe": False, "ranges": []}

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def send_json(self, data, status=200):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            remote["requests"].append((self.path, data))
            if "deny_status" in remote:
                self.send_json(remote["deny_body"], remote["deny_status"])
                return
            if self.headers.get("PRIVATE-TOKEN") != TOKEN or remote["reject"]:
                self.send_json({}, 403)
                return
            assert self.path == "/api/retrieve/v1/processes/reanalysis-era5-single-levels/execution"
            inputs = data["inputs"]
            day = datetime(int(inputs["year"][0]), int(inputs["month"][0]), int(inputs["day"][0]), tzinfo=timezone.utc)
            path = tmp_path / "field.grib"
            fields = []
            for hour in range(24):
                values = np.full((2, 3), .007)
                if hour == 8:
                    values[0, 0] = 0
                    values[1, 2] = np.nan
                fields.append(grib1(path, values, valid=day + timedelta(hours=hour)))
            id_ = f"job-{len(remote['jobs']) + 1}"
            remote["jobs"][id_] = b"".join(fields)
            self.send_json({"jobID": id_, "status": "accepted"}, 201)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path.startswith("/api/"):
                if self.headers.get("PRIVATE-TOKEN") != TOKEN:
                    self.send_json({}, 401)
                    return
                id_ = path.split("/")[5]
                if id_ not in remote["jobs"]:
                    self.send_json({}, 404)
                elif path.endswith("/results"):
                    if remote.pop("expire_results", False):
                        self.send_json({}, 404)
                        return
                    href = "https://example.com/leak.grib" if remote["unsafe"] else remote["url"] + "/result/" + id_
                    self.send_json({"asset": {"value": {"href": href, "file:size": len(remote["jobs"][id_])}}})
                else:
                    self.send_json({"status": "accepted" if remote["waiting"] else "successful"})
                return
            assert self.headers.get("PRIVATE-TOKEN") is None
            payload = remote["jobs"][path.rsplit("/", 1)[1]]
            if not remote.get("range_supported", True):
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            first, last = map(int, self.headers["Range"].removeprefix("bytes=").split("-"))
            remote["ranges"].append(first)
            data = payload[first:last + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {first}-{last}/{len(payload)}")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

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


def cds_file(client, day=2):
    return client.get("/api/archive/files", params={"source": "cds", "year": 2023, "month": 1}).raise_for_status().json()[day - 1]


@contextmanager
def second_instance(folder, tmp_path, remote):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    with (tmp_path / "second-instance.log").open("w", encoding="utf8") as log:
        process = subprocess.Popen(["dotnet", str(DLL), "--urls", f"http://127.0.0.1:{port}",
                                    "--Era5:Data", str(folder), "--Era5:CdsBaseUrl", remote["url"] + "/api/retrieve/v1"],
                                   cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False) as client:
                for _ in range(100):
                    assert process.poll() is None
                    try:
                        client.get("/health").raise_for_status()
                        break
                    except httpx.TransportError:
                        time.sleep(.05)
                else:
                    pytest.fail("Second app instance did not start")
                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.parametrize("dotnet_archive", ["cds"], indirect=True)
@pytest.mark.parametrize("range_supported", [True, False])
def test_cds_grib_original_download_map_overlap_and_all_24_frames(dotnet_archive, fake_cds, range_supported):
    client, folder = dotnet_archive
    fake_cds["range_supported"] = range_supported
    settings = client.get("/api/archive/settings").json()
    assert [source["id"] for source in settings["sources"]] == ["amazon", "google", "cds"]
    assert settings["cds_configured"] is False
    file = cds_file(client)
    assert file["format"] == "GRIB" and file["bytes"] == 0
    assert client.post("/api/archive/download", json={"key": file["key"]}).status_code == 422
    client.post("/api/archive/cds-token", json={"token": TOKEN}).raise_for_status()
    assert TOKEN not in client.get("/api/archive/settings").text
    old = client.get("/map-archive/catalog").json()
    client.post("/api/archive/download", json={"key": file["key"]}).raise_for_status()
    completed = wait_download(client, "cds", file["key"])
    assert (folder / completed["name"]).read_bytes() == fake_cds["jobs"]["job-1"]
    estimate = cds_file(client, 3)
    assert estimate["bytes"] == 0 and estimate["estimated_bytes"] == completed["bytes"]
    assert TOKEN not in (folder / (file["name"] + ".cds-request.json")).read_text()
    inputs = fake_cds["requests"][0][1]["inputs"]
    assert inputs["variable"] == ["large_scale_precipitation"]
    assert inputs["data_format"] == "grib" and inputs["download_format"] == "unarchived"
    assert inputs["time"] == [f"{hour:02d}:00" for hour in range(24)]
    client.get("/").raise_for_status()
    catalog = client.get("/map-archive/catalog").json()
    assert catalog["manifest_sha256"] != old["manifest_sha256"]
    assert catalog["gap_hours"] == 0
    # At an overlap, the original NetCDF value wins; in the gap GRIB fills cells.
    values, sources = frame(client, 17)
    assert [source["Format"] for source in sources] == ["NetCDF"]
    assert values.max() < 7
    values, sources = frame(client, 25)
    assert values[1, 0] == 0 and np.isnan(values[0, 2])
    assert sources == [{"Name": completed["name"], "Format": "GRIB", "Cells": 5}]
    for local in client.get("/api/archive/local").json()["files"]:
        if local["name"] != completed["name"]:
            client.post("/api/archive/delete", json={"id": local["id"]}).raise_for_status()
    client.get("/").raise_for_status()
    catalog = client.get("/map-archive/catalog").json()
    assert catalog["available_hours"] == 24 and catalog["gap_hours"] == 0
    for hour in range(24):
        values, _ = frame(client, hour)
        if hour == 8:
            assert values[1, 0] == 0 and np.isnan(values[0, 2])
        else:
            np.testing.assert_allclose(values, 7, atol=1e-5)


@pytest.mark.parametrize("dotnet_archive", ["cds"], indirect=True)
def test_cds_pause_resume_reuses_prepared_request(dotnet_archive, fake_cds):
    client, _ = dotnet_archive
    fake_cds["waiting"] = True
    client.post("/api/archive/cds-token", json={"token": TOKEN}).raise_for_status()
    file = cds_file(client)
    client.post("/api/archive/download", json={"key": file["key"]}).raise_for_status()
    for _ in range(100):
        if cds_file(client)["state"] == "waiting":
            break
        time.sleep(.02)
    else:
        pytest.fail("CDS did not enter queue")
    client.post("/api/archive/cancel", json={"key": file["key"]}).raise_for_status()
    for _ in range(100):
        if cds_file(client)["state"] == "paused":
            break
        time.sleep(.02)
    assert cds_file(client)["state"] == "paused"
    fake_cds["waiting"] = False
    client.post("/api/archive/download", json={"key": file["key"]}).raise_for_status()
    wait_download(client, "cds", file["key"])
    assert len(fake_cds["requests"]) == 1


@pytest.mark.parametrize("dotnet_archive", ["cds"], indirect=True)
def test_cds_request_partial_bytes_and_downloaded_marker_survive_restart(dotnet_archive, fake_cds, tmp_path):
    client, folder = dotnet_archive
    fake_cds["waiting"] = True
    client.post("/api/archive/cds-token", json={"token": TOKEN}).raise_for_status()
    file = cds_file(client)
    client.post("/api/archive/download", json={"key": file["key"]}).raise_for_status()
    for _ in range(100):
        if cds_file(client)["state"] == "waiting":
            break
        time.sleep(.02)
    client.post("/api/archive/cancel", json={"key": file["key"]}).raise_for_status()
    for _ in range(100):
        if cds_file(client)["state"] == "paused":
            break
        time.sleep(.02)
    assert cds_file(client)["state"] == "paused"
    payload = fake_cds["jobs"]["job-1"]
    (folder / (file["name"] + ".partial")).write_bytes(payload[:128])
    (folder / (file["name"] + ".download.json")).write_text(json.dumps({"key": file["key"],
        "url": fake_cds["url"] + "/result/job-1", "bytes": len(payload), "etag": ""}), encoding="utf8")
    fake_cds["waiting"] = False
    with second_instance(folder, tmp_path, fake_cds) as resumed:
        assert resumed.get("/api/archive/settings").json()["cds_configured"] is True
        assert cds_file(resumed)["state"] == "paused"
        resumed.post("/api/archive/cds-token", json={"token": TOKEN}).raise_for_status()
        resumed.post("/api/archive/download", json={"key": file["key"]}).raise_for_status()
        wait_download(resumed, "cds", file["key"])
    assert fake_cds["ranges"][0] == 128
    assert len(fake_cds["requests"]) == 1
    with second_instance(folder, tmp_path, fake_cds) as reopened:
        row = cds_file(reopened)
        assert row["downloaded"] is True and row["bytes"] == len(payload)


@pytest.mark.parametrize("dotnet_archive", ["cds"], indirect=True)
def test_cds_token_and_active_queue_resume_automatically_after_restart(dotnet_archive, fake_cds, tmp_path):
    _, folder = dotnet_archive
    fake_cds["waiting"] = True
    with second_instance(folder, tmp_path, fake_cds) as first:
        first.post("/api/archive/cds-token", json={"token": TOKEN}).raise_for_status()
        file = cds_file(first)
        first.post("/api/archive/download", json={"key": file["key"]}).raise_for_status()
        for _ in range(100):
            if cds_file(first)["state"] == "waiting":
                break
            time.sleep(.02)
        assert cds_file(first)["state"] == "waiting"
        queue = folder / ".meteo-settings/cds-queue.json"
        assert file["key"] in json.loads(queue.read_text())
        saved = folder / ".meteo-settings/cds-token.bin"
        assert saved.is_file()
        if os.name == "nt":
            assert TOKEN.encode() not in saved.read_bytes()
            assert saved.read_bytes().startswith(b"MeteoBridge.CDS.DPAPI1\n")
    fake_cds["waiting"] = False
    with second_instance(folder, tmp_path, fake_cds) as restarted:
        assert restarted.get("/api/archive/settings").json()["cds_configured"] is True
        wait_download(restarted, "cds", file["key"])
    assert len(fake_cds["requests"]) == 1
    assert json.loads(queue.read_text()) == []


@pytest.mark.parametrize("dotnet_archive", ["cds"], indirect=True)
def test_clearing_cds_token_removes_persistent_copy(dotnet_archive, fake_cds, tmp_path):
    client, folder = dotnet_archive
    client.post("/api/archive/cds-token", json={"token": TOKEN}).raise_for_status()
    saved = folder / ".meteo-settings/cds-token.bin"
    assert saved.is_file()
    client.post("/api/archive/cds-token", json={"token": ""}).raise_for_status()
    assert not saved.exists()
    with second_instance(folder, tmp_path, fake_cds) as restarted:
        assert restarted.get("/api/archive/settings").json()["cds_configured"] is False


@pytest.mark.parametrize("dotnet_archive", ["cds"], indirect=True)
def test_cds_expired_result_can_be_requested_again(dotnet_archive, fake_cds):
    client, folder = dotnet_archive
    fake_cds["expire_results"] = True
    client.post("/api/archive/cds-token", json={"token": TOKEN}).raise_for_status()
    file = cds_file(client)
    client.post("/api/archive/download", json={"key": file["key"]}).raise_for_status()
    for _ in range(100):
        if cds_file(client)["state"] == "failed":
            break
        time.sleep(.02)
    assert cds_file(client)["state"] == "failed"
    assert not (folder / (file["name"] + ".cds-request.json")).exists()
    client.post("/api/archive/download", json={"key": file["key"]}).raise_for_status()
    wait_download(client, "cds", file["key"])
    assert len(fake_cds["requests"]) == 2


@pytest.mark.parametrize("dotnet_archive", ["cds"], indirect=True)
@pytest.mark.parametrize("failure", ["reject", "unsafe"])
def test_cds_access_errors_and_untrusted_result_are_not_published(dotnet_archive, fake_cds, failure):
    client, folder = dotnet_archive
    fake_cds[failure] = True
    assert client.post("/api/archive/cds-token", json={"token": TOKEN}, headers={"Origin": "https://example.com"}).status_code == 403
    client.post("/api/archive/cds-token", json={"token": TOKEN}).raise_for_status()
    file = cds_file(client)
    client.post("/api/archive/download", json={"key": file["key"]}).raise_for_status()
    for _ in range(200):
        result = cds_file(client)
        if result["state"] == "failed":
            break
        time.sleep(.02)
    assert result["state"] == "failed", result
    assert TOKEN not in json.dumps(result)
    assert not (folder / file["name"]).exists()
    assert not fake_cds["ranges"]


@pytest.mark.parametrize("dotnet_archive", ["cds"], indirect=True)
@pytest.mark.parametrize("status,body,code,message", [
    (403, {"type": "permission denied", "title": "required licences not accepted",
           "detail": "Not all the required licences have been accepted; test-only-cds-token"},
     "licence_required", "не приняты условия ERA5"),
    (401, {"title": "invalid token"}, "invalid_token", "не принял API-токен"),
    (403, {"title": "permission denied"}, "forbidden", "запретил доступ"),
    (403, "Unexpected gateway response", "forbidden", "запретил доступ"),
])
def test_cds_distinguishes_licence_token_and_other_access_errors(dotnet_archive, fake_cds, status, body, code, message):
    client, folder = dotnet_archive
    fake_cds.update(deny_status=status, deny_body=body)
    client.post("/api/archive/cds-token", json={"token": TOKEN}).raise_for_status()
    file = cds_file(client)
    client.post("/api/archive/download", json={"key": file["key"]}).raise_for_status()
    for _ in range(100):
        row = cds_file(client)
        if row["state"] == "failed":
            break
        time.sleep(.02)
    assert row["state"] == "failed", row
    assert row["error_code"] == code and message in row["error"]
    assert TOKEN not in json.dumps(row)
    if code == "licence_required":
        assert row["action_url"] == "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=download#manage-licences"
    else:
        assert row["action_url"] is None
    assert not (folder / file["name"]).exists()
    assert not fake_cds["ranges"]


def test_grib1_import_intervals_quantity_and_overlapping_files(dotnet_archive, tmp_path):
    client, _ = dotnet_archive
    path = tmp_path / "a-regional.grib"
    grib1(path, [[0, np.nan], [.004, .004]])
    upload(client, path).raise_for_status()
    other = tmp_path / "z-other.grib"
    grib1(other, [[np.nan, .009, .009], [np.nan, np.nan, .009]])
    upload(client, other).raise_for_status()
    client.get("/").raise_for_status()
    values, sources = frame(client, 24)
    np.testing.assert_allclose(values, [[4, 4, 9], [0, 9, 9]])
    assert {source["Name"] for source in sources} == {"a-regional.grib", "z-other.grib"}
    assert [source["Cells"] for source in sources] == [3, 3]
    total = tmp_path / "total.grib"
    grib1(total, [[.001, .001], [.001, .001]], parameter=228)
    assert upload(client, total).status_code == 422
    incomplete = tmp_path / "multi-hour.grib"
    grib1(incomplete, [[.005, .005], [.005, .005]], duration=2)
    assert upload(client, incomplete).status_code == 422
