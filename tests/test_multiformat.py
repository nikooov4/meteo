import json
from urllib.parse import unquote

import netCDF4 as nc
import numpy as np
from raster_fixtures import native_path, raster

pytest_plugins = ["test_era5_dotnet"]


def upload(client, path, **options):
    response = client.post("/api/archive/import", params={"name": path.name, **options}, content=path.read_bytes(),
                           headers={"Content-Type": "application/octet-stream"})
    if response.is_success:
        assert response.json()["name"] == path.name
        assert response.json()["hours"] >= 1
    return response


def frame(client, hour):
    catalog = client.get("/map-archive/catalog").raise_for_status().json()
    response = client.get("/map-archive/frame", params={"hour": hour, "manifest_sha256": catalog["manifest_sha256"]})
    assert response.is_success, response.text
    return np.frombuffer(response.content, dtype="<f4").reshape(catalog["grid_shape"]), json.loads(unquote(response.headers["X-Frame-Sources"]))


def test_all_three_formats_fill_cells_and_hours_with_netcdf_priority(dotnet_archive, tmp_path):
    client, folder = dotnet_archive
    for name in ["part-0.nc", "z-duplicate.nc"]:
        with nc.Dataset(native_path(folder / name), "r+") as dataset:
            dataset["LSP"][0, 1, 1, 1] = dataset["LSP"]._FillValue
    tif = tmp_path / "дополнение.tif"
    raster(tif, np.full((2, 3), 9))
    upload(client, tif, metadata="manual", start_utc="2023-01-01T07:00:00Z", units="mm", accumulation="hourly").raise_for_status()
    grib = tmp_path / "осадки.grib"
    grib_values = np.full((2, 3), 7, dtype="float32")
    grib_values[1, 2] = -9999
    raster(grib, grib_values, format="GRIB", end_hour=2)
    upload(client, grib).raise_for_status()
    client.get("/").raise_for_status()
    values, sources = frame(client, 1)
    assert values[1, 1] == 7  # invalid NetCDF cell comes from GRIB rather than GeoTIFF
    np.testing.assert_allclose(values[0], [.11, .09, 9], atol=1e-6)
    assert [source["Format"] for source in sources] == ["NetCDF", "GRIB", "GeoTIFF"]
    assert [source["Cells"] for source in sources] == [4, 1, 1]
    gap = tmp_path / "missing-hour.tif"
    raster(gap, np.full((2, 3), .002))
    upload(client, gap, metadata="manual", start_utc="2023-01-02T06:00:00Z", units="m", accumulation="hourly").raise_for_status()
    client.get("/").raise_for_status()
    values, sources = frame(client, 24)
    np.testing.assert_allclose(values, 2)
    assert sources == [{"Name": gap.name, "Format": "GeoTIFF", "Cells": 6}]
    assert client.get("/map-archive/catalog").json()["gap_hours"] == 11


def test_geotiff_deaccumulation_masks_and_spatial_alignment(dotnet_archive, tmp_path):
    client, _ = dotnet_archive
    tif = tmp_path / "cumulative.tif"
    # Finer source grid, reversed latitude. Zero is a real value; a reset is missing.
    first = np.full((3, 5), .002, dtype="float32")
    second = np.full((3, 5), .005, dtype="float32")
    second[0, 0] = .001
    second[2, 4] = first[2, 4]
    raster(tif, [first, second], transform=(-1.25, .5, 0, 42.5, 0, -1))
    upload(client, tif, metadata="manual", start_utc="2023-01-02T06:00:00Z", units="m", accumulation="cumulative").raise_for_status()
    client.get("/").raise_for_status()
    values, _ = frame(client, 24)
    np.testing.assert_allclose(values, 2)
    values, _ = frame(client, 25)
    assert np.isnan(values[-1, 0])
    assert values[0, -1] == 0
    assert values[1, 1] == 3


def test_grib_cumulative_intervals_are_differenced(dotnet_archive, tmp_path):
    client, _ = dotnet_archive
    first = tmp_path / "first.grib"
    second = tmp_path / "second.grib"
    raster(first, np.full((2, 3), 2), format="GRIB", end_hour=25, duration=1)
    # Same start at hour 24; the second band is accumulated over two hours.
    raster(second, np.full((2, 3), 5), format="GRIB", end_hour=26, duration=2)
    combined = tmp_path / "cumulative.grib"
    combined.write_bytes(first.read_bytes() + second.read_bytes())
    upload(client, combined).raise_for_status()
    client.get("/").raise_for_status()
    values, sources = frame(client, 25)
    np.testing.assert_allclose(values, 3)
    assert sources[0]["Format"] == "GRIB"


def test_import_validation_atomicity_and_stale_manifest(dotnet_archive, tmp_path):
    client, folder = dotnet_archive
    old = client.get("/map-archive/catalog").raise_for_status().json()
    path = tmp_path / "no-time.tif"
    raster(path, np.ones((2, 3)))
    assert upload(client, path).status_code == 422
    assert not list(folder.rglob("no-time.tif"))
    for options in [{"units": "C"}, {"start_utc": "2023-01-02T06:30:00Z"}]:
        settings = {"metadata": "manual", "start_utc": "2023-01-02T06:00:00Z", "units": "mm", "accumulation": "hourly", **options}
        assert upload(client, path, **settings).status_code == 422
    assert client.post("/api/archive/import", params={"name": "../../bad.nc"}, content=b"bad").status_code == 422
    assert client.post("/api/archive/import", params={"name": "bad.tif"}, content=b"bad").status_code == 422
    assert client.post("/api/archive/import", params={"name": "bad.nc"}, content=b"bad", headers={"Origin": "https://example.com"}).status_code == 403
    total = tmp_path / "total.grib"
    raster(total, np.ones((2, 3)), format="GRIB", parameter=8)
    assert upload(client, total).status_code == 422
    upload(client, path, metadata="manual", start_utc="2023-01-02T06:00:00Z", units="mm", accumulation="hourly").raise_for_status()
    client.get("/").raise_for_status()
    assert client.get("/map-archive/frame", params={"hour": 0, "manifest_sha256": old["manifest_sha256"]}).status_code == 409
    assert len(client.get("/api/archive/local").json()["files"]) == old["file_count"] + 1


def test_netcdf_fallback_with_different_extent_preserves_valid_zero(dotnet_archive):
    client, folder = dotnet_archive
    with nc.Dataset(native_path(folder / "z-duplicate.nc"), "r+") as dataset:
        dataset["latitude"][:] = [43, 41]
        dataset["LSP"][:] = .005
    client.get("/").raise_for_status()
    grid = client.get("/grid").json()
    assert grid["latitude"] == [40, 41, 42, 43]
    values, _ = frame(client, 0)
    assert values[2, 1] == 0  # original zero is authoritative, never replaced with five
    np.testing.assert_allclose(values[-1], 5)
    values, sources = frame(client, 1)
    assert values[2, 1] == 5
    assert [source["Name"] for source in sources] == ["part-0.nc", "z-duplicate.nc"]


def test_geotiff_internal_mask_is_missing_instead_of_zero(dotnet_archive, tmp_path):
    client, _ = dotnet_archive
    path = tmp_path / "masked.tif"
    raster(path, np.full((2, 3), 4), mask=[[255, 0, 255], [255, 255, 255]])
    upload(client, path, metadata="manual", start_utc="2023-01-02T06:00:00Z", units="mm", accumulation="hourly").raise_for_status()
    client.get("/").raise_for_status()
    values, sources = frame(client, 24)
    assert np.isnan(values[1, 1])
    np.testing.assert_allclose(values[np.isfinite(values)], 4)
    assert sources[0]["Cells"] == 5


def test_projected_geotiff_metadata_and_coverage(dotnet_archive, tmp_path):
    client, _ = dotnet_archive
    path = tmp_path / "projected.tif"
    raster(path, np.full((3, 3), 4), projection="EPSG:3857",
           transform=(-150000, 100000, 0, 5200000, 0, -100000), metadata={
               "METEO_START_UTC": "2023-01-02T06:00:00Z", "METEO_UNITS": "kg m-2",
               "METEO_QUANTITY": "large_scale_precipitation", "METEO_ACCUMULATION": "hourly"})
    upload(client, path).raise_for_status()
    client.get("/").raise_for_status()
    values, _ = frame(client, 24)
    np.testing.assert_allclose(values[np.isfinite(values)], 4)
    assert np.isfinite(values).any()
    assert np.isnan(values[0]).all()  # latitude 40 lies outside the projected source
