import base64
import hashlib
import http.server
import json
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit

import netCDF4 as nc
import numpy as np
import pytest

pytest_plugins = ["test_era5_dotnet"]


@pytest.fixture
def fake_arco(tmp_path):
    objects = {}
    for day in (2, 3):
        path = tmp_path / f"arco-{day}.nc"
        with nc.Dataset(path, "w", format="NETCDF3_64BIT_OFFSET") as dataset:
            for name, size in [("time", 24), ("latitude", 2), ("longitude", 3)]:
                dataset.createDimension(name, size)
            stamp = dataset.createVariable("time", "i4", ("time",))
            stamp.units = f"hours since 2023-01-{day:02d} 00:00:00"
            stamp.calendar = "gregorian"
            stamp[:] = np.arange(24)
            dataset.createVariable("latitude", "f8", ("latitude",))[:] = [42, 40]
            dataset.createVariable("longitude", "f8", ("longitude",))[:] = [0, 1, 359]
            values = dataset.createVariable("lsp", "i2", ("time", "latitude", "longitude"), fill_value=-32767)
            values.units = "m"
            values.standard_name = "lwe_thickness_of_stratiform_precipitation_amount"
            values.scale_factor, values.add_offset = .000001, .002
            values[:] = .004
            values[7, 0, 0] = np.ma.masked
        payload = path.read_bytes() + (b"\0" * (5 * 1048576) if day == 2 else b"")
        key = f"raw/date-variable-single_level/2023/01/{day:02d}/large_scale_precipitation/surface.nc"
        digest = hashlib.md5(payload).digest()
        objects[key] = {"payload": payload, "etag": '"' + digest.hex() + '"', "md5Hash": base64.b64encode(digest).decode()}
    remote = {"objects": objects, "ranges": [], "requests": [], "slow": False}

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):
            remote["requests"].append(self.path)
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            if "prefix" in query:
                matches = [(key, value) for key, value in objects.items() if key.startswith(query["prefix"][0])]
                offset = 1 if "pageToken" in query else 0
                items = [{"name": key, "size": str(len(value["payload"])), "generation": "17", "md5Hash": value["md5Hash"]}
                         for key, value in matches[offset:offset + 1]]
                body = {"items": items}
                if len(matches) > 1 and offset == 0:
                    body["nextPageToken"] = "second-page"
                content = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            item = objects.get(url.path.lstrip("/"))
            if item is None:
                self.send_error(404)
                return
            if self.headers.get("If-Match") != item["etag"]:
                self.send_error(412)
                return
            first, last = map(int, self.headers["Range"].removeprefix("bytes=").split("-"))
            remote["ranges"].append(first)
            content = item["payload"][first:last + 1]
            self.send_response(206)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Content-Range", f"bytes {first}-{last}/{len(item['payload'])}")
            self.end_headers()
            try:
                for offset in range(0, len(content), 32768):
                    self.wfile.write(content[offset:offset + 32768])
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


def wait_download(client, source, key):
    for _ in range(1000):
        rows = client.get("/api/archive/files", params={"year": 2023, "month": 1, "source": source}).raise_for_status().json()
        row = next(row for row in rows if row["key"] == key)
        if row["state"] in {"downloaded", "failed"}:
            assert row["state"] == "downloaded", row
            return row
        time.sleep(.02)
    pytest.fail("Download did not finish")


@pytest.mark.parametrize("dotnet_archive", ["sources"], indirect=True)
def test_google_original_netcdf_download_and_fill_map(dotnet_archive, fake_arco):
    client, directory = dotnet_archive
    source = "google"
    settings = client.get("/api/archive/settings").raise_for_status().json()
    assert [item["id"] for item in settings["sources"]] == ["amazon", "google", "cds"]
    assert [item["format"] for item in settings["sources"]] == ["NetCDF", "NetCDF", "GRIB"]
    files = client.get("/api/archive/files", params={"year": 2023, "month": 1, "source": source}).raise_for_status().json()
    assert len(files) == 2
    assert files[0]["format"] == "NetCDF" and files[0]["provider"] == "Google ARCO-ERA5"
    assert files[0]["start_utc"] == "2023-01-01T23:00:00+00:00"
    assert files[0]["end_utc"] == "2023-01-02T23:00:00+00:00"
    assert "converted" not in files[0]
    staging = directory / ".pending" / "not-published"
    staging.mkdir(parents=True)
    staged_file = staging / files[0]["name"]
    staged_file.write_bytes(b"incomplete")
    snapshot = client.get("/api/archive/files", params={"year": 2023, "month": 1, "source": source}).raise_for_status().json()
    assert snapshot[0]["state"] == "available" and snapshot[0]["downloaded"] is False
    staged_file.unlink()
    staging.rmdir()
    old = client.get("/map-archive/catalog").raise_for_status().json()
    client.post("/api/archive/download", json={"key": files[0]["key"]}).raise_for_status()
    completed = wait_download(client, source, files[0]["key"])
    assert completed["name"].endswith(".nc")
    assert completed["saved_bytes"] == (directory / completed["name"]).stat().st_size
    assert (directory / completed["name"]).read_bytes() == next(iter(fake_arco["objects"].values()))["payload"]
    assert not list(directory.glob("*.grib2")) and not list(directory.glob("*.tif"))
    assert not list((directory / ".pending").rglob("*.*"))
    assert not list(directory.glob("*.partial"))
    client.get("/").raise_for_status()
    catalog = client.get("/map-archive/catalog").raise_for_status().json()
    assert catalog["manifest_sha256"] != old["manifest_sha256"]
    assert catalog["gap_hours"] == 0
    response = client.get("/map-archive/frame", params={"hour": 24, "manifest_sha256": catalog["manifest_sha256"]})
    assert response.is_success, response.text
    values = np.frombuffer(response.content, dtype="<f4").reshape(catalog["grid_shape"])
    assert np.isnan(values[1, 1])
    np.testing.assert_allclose(values[np.isfinite(values)], 4, atol=1e-6)
    assert json.loads(unquote(response.headers["X-Frame-Sources"]))[0]["Format"] == "NetCDF"
    assert client.get("/api/archive/files", params={"year": 2023, "month": 2, "source": source}).json() == []
    assert client.get("/api/archive/files", params={"year": 2023, "source": "unknown"}).status_code == 422


@pytest.mark.parametrize("dotnet_archive", ["sources"], indirect=True)
def test_google_can_resume_an_original_netcdf_download(dotnet_archive, fake_arco):
    client, directory = dotnet_archive
    source = "google"
    files = client.get("/api/archive/files", params={"year": 2023, "month": 1, "source": source}).raise_for_status().json()
    file = files[0]
    remote_key, item = next(iter(fake_arco["objects"].items()))
    partial = directory / (file["name"] + ".partial")
    partial.write_bytes(item["payload"][:4096])
    (directory / (file["name"] + ".download.json")).write_text(json.dumps({"url": fake_arco["url"] + "/" + remote_key + "?generation=17",
        "etag": item["etag"], "bytes": len(item["payload"])}), encoding="utf8")
    client.post("/api/archive/download", json={"key": file["key"]}).raise_for_status()
    wait_download(client, source, file["key"])
    assert fake_arco["ranges"][0] == 4096
    assert not partial.exists()


@pytest.mark.parametrize("dotnet_archive", ["sources"], indirect=True)
def test_delete_downloaded_file_refreshes_map_and_allows_redownload(dotnet_archive):
    client, directory = dotnet_archive
    file = client.get("/api/archive/files", params={"year": 2023, "month": 1, "source": "google"}).raise_for_status().json()[0]
    client.post("/api/archive/download", json={"key": file["key"]}).raise_for_status()
    completed = wait_download(client, "google", file["key"])
    client.get("/").raise_for_status()
    before = client.get("/map-archive/catalog").raise_for_status().json()
    client.get("/map-archive/frame", params={"hour": 24, "manifest_sha256": before["manifest_sha256"]}).raise_for_status()
    assert client.post("/api/archive/delete", json={"id": completed["local_id"]}, headers={"Origin": "https://example.com"}).status_code == 403
    for invalid in ["../../part-0.nc", "0" * 64]:
        assert client.post("/api/archive/delete", json={"id": invalid}).status_code == 422
    deleted = client.post("/api/archive/delete", json={"id": completed["local_id"]}).raise_for_status().json()
    assert deleted == {"deleted": True, "name": completed["name"]}
    assert not (directory / completed["name"]).exists()
    assert not (directory / (completed["name"] + ".download.json")).exists()
    assert not any(row["id"] == completed["local_id"] for row in client.get("/api/archive/local").json()["files"])
    after = client.get("/map-archive/catalog").raise_for_status().json()
    assert after["gap_hours"] == 12
    assert client.get("/map-archive/frame", params={"hour": 24, "manifest_sha256": before["manifest_sha256"]}).status_code == 409
    assert client.get("/api/archive/files", params={"year": 2023, "month": 1, "source": "google"}).json()[0]["state"] == "available"
    client.post("/api/archive/download", json={"key": file["key"]}).raise_for_status()
    assert wait_download(client, "google", file["key"])["downloaded"] is True


@pytest.mark.parametrize("dotnet_archive", ["sources"], indirect=True)
def test_google_file_alone_provides_all_24_animation_frames(dotnet_archive):
    client, _ = dotnet_archive
    file = client.get("/api/archive/files", params={"year": 2023, "month": 1, "source": "google"}).raise_for_status().json()[0]
    client.post("/api/archive/download", json={"key": file["key"]}).raise_for_status()
    completed = wait_download(client, "google", file["key"])
    for local in client.get("/api/archive/local").json()["files"]:
        if local["name"] != completed["name"]:
            client.post("/api/archive/delete", json={"id": local["id"]}).raise_for_status()
    client.get("/").raise_for_status()
    catalog = client.get("/map-archive/catalog").raise_for_status().json()
    assert catalog["file_count"] == 1 and catalog["available_hours"] == 24 and catalog["gap_hours"] == 0
    for hour in range(24):
        response = client.get("/map-archive/frame", params={"hour": hour, "manifest_sha256": catalog["manifest_sha256"]}).raise_for_status()
        values = np.frombuffer(response.content, dtype="<f4").reshape(catalog["grid_shape"])
        np.testing.assert_allclose(values[np.isfinite(values)], 4, atol=1e-6)
        assert np.isnan(values).sum() == (1 if hour == 7 else 0)
        assert json.loads(unquote(response.headers["X-Frame-Sources"]))[0]["Name"] == completed["name"]
