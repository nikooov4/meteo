import json

import netCDF4 as nc
import numpy as np
from raster_fixtures import raster
from test_cds_archive import second_instance
from test_multiformat import frame, upload

pytest_plugins = ["test_era5_dotnet"]
DEFAULT = ["amazon", "google", "cds"]


def priorities(client):
    return client.get("/map-archive/priority").raise_for_status().json()


def google_file(path, values):
    with nc.Dataset(path, "w") as dataset:
        for name, length in [("time", 1), ("latitude", 2), ("longitude", 3)]:
            dataset.createDimension(name, length)
        stamp = dataset.createVariable("time", "i4", ("time",))
        stamp.units = "hours since 2023-01-01 07:00:00"
        stamp[:] = [0]
        dataset.createVariable("latitude", "f8", ("latitude",))[:] = [42, 40]
        dataset.createVariable("longitude", "f8", ("longitude",))[:] = [0, 1, 359]
        lsp = dataset.createVariable("lsp", "f4", ("time", "latitude", "longitude"), fill_value=9.999e20)
        lsp.units = "m"
        lsp.standard_name = "lwe_thickness_of_stratiform_precipitation_amount"
        lsp[:] = np.ma.masked_invalid(np.asarray(values, dtype="float32") / 1000)
    return path


def test_google_overrides_amazon_with_same_format_and_preserves_zero_and_fallback(dotnet_archive, tmp_path):
    client, _ = dotnet_archive
    path = google_file(tmp_path / "era5-arco-lsp-20230101.nc", [[9, 0, 9], [9, 9, np.nan]])
    upload(client, path).raise_for_status()
    client.get("/").raise_for_status()
    original, _ = frame(client, 0)
    old = client.get("/map-archive/catalog").json()
    view = priorities(client)
    assert [item["id"] for item in view["archives"]] == DEFAULT
    assert [item["format"] for item in view["archives"]] == ["NC", "NC", "GRIB"]
    assert [item["file_count"] for item in view["archives"]] == [3, 1, 0]
    order = ["google", "amazon", "cds"]
    response = client.post("/map-archive/priority", json={"order": order}).raise_for_status().json()
    assert response["priority"]["custom"]
    assert response["catalog"]["archive_priority"] == order
    assert response["catalog"]["manifest_sha256"] != old["manifest_sha256"]
    assert response["catalog"]["available_hours"] == old["available_hours"]
    assert response["catalog"]["grid_shape"] == old["grid_shape"]
    values, sources = frame(client, 0)
    np.testing.assert_allclose(values, [[.05, 9, 9], [9, 9, 0]], atol=1e-6)
    assert [source["Name"] for source in sources] == [path.name, "part-0.nc"]
    assert [source["Cells"] for source in sources] == [5, 1]
    assert client.get("/map-archive/frame", params={"hour": 0, "manifest_sha256": old["manifest_sha256"]}).status_code == 409
    restored = client.post("/map-archive/priority", json={"order": DEFAULT}).raise_for_status().json()
    assert not restored["priority"]["custom"]
    assert restored["catalog"]["manifest_sha256"] == old["manifest_sha256"]
    np.testing.assert_array_equal(frame(client, 0)[0], original)


def test_cds_archive_can_override_netcdf_without_losing_zero_or_fallback(dotnet_archive, tmp_path):
    client, _ = dotnet_archive
    path = tmp_path / "era5-cds-lsp-20230101.grib"
    raster(path, [[7, 7, 7], [7, 0, -9999]], format="GRIB", end_hour=1)
    upload(client, path).raise_for_status()
    client.get("/").raise_for_status()
    assert frame(client, 0)[0][0, 0] != 7
    client.post("/map-archive/priority", json={"order": ["cds", "amazon", "google"]}).raise_for_status()
    values, sources = frame(client, 0)
    np.testing.assert_allclose(values, [[7, 0, .04], [7, 7, 7]], atol=1e-6)
    assert [source["Format"] for source in sources] == ["GRIB", "NetCDF"]
    assert [source["Cells"] for source in sources] == [5, 1]


def test_archive_priority_persists_and_applies_to_new_files_even_when_archive_was_empty(dotnet_archive, tmp_path):
    client, folder = dotnet_archive
    view = priorities(client)
    assert len(view["archives"]) == 3
    assert [item["file_count"] for item in view["archives"]] == [3, 0, 0]
    order = ["google", "cds", "amazon"]
    client.post("/map-archive/priority", json={"order": order}).raise_for_status()
    saved = folder / ".meteo-settings/map-priority.json"
    assert json.loads(saved.read_text()) == order
    for day in (1, 2):
        path = google_file(tmp_path / f"era5-arco-lsp-202301{day:02d}.nc", np.full((2, 3), 9))
        upload(client, path).raise_for_status()
    client.get("/").raise_for_status()
    assert [item["id"] for item in priorities(client)["archives"]] == order
    assert priorities(client)["archives"][0]["file_count"] == 2
    np.testing.assert_allclose(frame(client, 0)[0], 9, atol=1e-6)
    with second_instance(folder, tmp_path, {"url": "http://127.0.0.1:9"}) as restarted:
        restored = priorities(restarted)
        assert restored["custom"]
        assert [item["id"] for item in restored["archives"]] == order
        catalog = restarted.get("/map-archive/catalog").raise_for_status().json()
        assert catalog["archive_priority"] == order
        np.testing.assert_allclose(frame(restarted, 0)[0], 9, atol=1e-6)


def test_archive_priority_rejects_unknown_partial_duplicate_and_cross_origin_changes(dotnet_archive):
    client, _ = dotnet_archive
    view = priorities(client)
    old_sha = client.get("/map-archive/catalog").json()["manifest_sha256"]
    for order in [["amazon", "amazon", "cds"], ["amazon"], ["google", "cds", "unknown"], ["0" * 64], [None, "google", "cds"], None]:
        assert client.post("/map-archive/priority", json={"order": order}).status_code == 422
    assert client.post("/map-archive/priority", json={"order": DEFAULT}, headers={"Origin": "https://example.com"}).status_code == 403
    assert priorities(client) == view
    assert client.get("/map-archive/catalog").json()["manifest_sha256"] == old_sha
