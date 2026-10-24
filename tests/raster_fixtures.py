"""Small real GeoTIFF/GRIB fixtures, using the GDAL runtime shipped with the app."""
import ctypes as c
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
_handles = []


def native_path(path):
    if os.name != "nt":
        return str(path)
    buffer = c.create_unicode_buffer(32768)
    assert c.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))
    return buffer.value


def library():
    binary = ROOT / "dotnet/MeteoBridge.Era5/bin/Release/net10.0"
    gdal_data = binary / "runtimes/any/native/gdal-data"
    if os.name == "nt":
        native = binary / "runtimes/win-x64/native"
        _handles.append(os.add_dll_directory(str(native)))
        os.environ["GDAL_DATA"] = native_path(gdal_data)
        os.environ["PROJ_LIB"] = native_path(native / "maxrev.gdal.core.libshared")
        gdal = c.CDLL(str(native / "gdal.dll"))
    else:
        native = binary / "runtimes/linux-x64/native"
        os.environ["GDAL_DATA"] = str(gdal_data)
        os.environ["PROJ_LIB"] = str(native / "maxrev.gdal.core.libshared")
        gdal = c.CDLL(str(next(native.glob("libgdal.so*"))))
    functions = {
        "GDALAllRegister": (None, []),
        "GDALGetDriverByName": (c.c_void_p, [c.c_char_p]),
        "GDALCreate": (c.c_void_p, [c.c_void_p, c.c_char_p, c.c_int, c.c_int, c.c_int, c.c_int, c.c_void_p]),
        "GDALCreateCopy": (c.c_void_p, [c.c_void_p, c.c_char_p, c.c_void_p, c.c_int, c.c_void_p, c.c_void_p, c.c_void_p]),
        "GDALSetProjection": (c.c_int, [c.c_void_p, c.c_char_p]),
        "GDALSetGeoTransform": (c.c_int, [c.c_void_p, c.POINTER(c.c_double)]),
        "GDALGetRasterBand": (c.c_void_p, [c.c_void_p, c.c_int]),
        "GDALSetRasterNoDataValue": (c.c_int, [c.c_void_p, c.c_double]),
        "GDALSetRasterUnitType": (c.c_int, [c.c_void_p, c.c_char_p]),
        "GDALCreateMaskBand": (c.c_int, [c.c_void_p, c.c_int]),
        "GDALGetMaskBand": (c.c_void_p, [c.c_void_p]),
        "GDALSetMetadataItem": (c.c_int, [c.c_void_p, c.c_char_p, c.c_char_p, c.c_char_p]),
        "GDALRasterIO": (c.c_int, [c.c_void_p, c.c_int, c.c_int, c.c_int, c.c_int, c.c_int,
                                   c.c_void_p, c.c_int, c.c_int, c.c_int, c.c_int, c.c_int]),
        "GDALClose": (None, [c.c_void_p]),
    }
    for name, (result, arguments) in functions.items():
        function = getattr(gdal, name)
        function.restype, function.argtypes = result, arguments
    gdal.GDALAllRegister()
    os.environ["GDAL_TIFF_INTERNAL_MASK"] = "YES"
    return gdal


def raster(path, values, *, format="GTiff", transform=(-1.5, 1, 0, 43, 0, -2), metadata=None,
           end_hour=1, duration=1, parameter=9, mask=None, projection=None):
    gdal = library()
    array = np.asarray(values, dtype="float32")
    if array.ndim == 2:
        array = array[None]
    bands, height, width = array.shape
    source = gdal.GDALCreate(gdal.GDALGetDriverByName(b"MEM"), b"", width, height, bands, 6, None)
    assert source
    try:
        wkt = b'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
        assert gdal.GDALSetProjection(source, projection.encode() if projection else wkt) == 0
        assert gdal.GDALSetGeoTransform(source, (c.c_double * 6)(*transform)) == 0
        for name, value in (metadata or {}).items():
            assert gdal.GDALSetMetadataItem(source, name.encode(), value.encode(), None) == 0
        for number, layer in enumerate(array, 1):
            band = gdal.GDALGetRasterBand(source, number)
            assert gdal.GDALSetRasterNoDataValue(band, -9999) == 0
            assert gdal.GDALSetRasterUnitType(band, b"mm") == 0
            layer = np.ascontiguousarray(layer)
            assert gdal.GDALRasterIO(band, 1, 0, 0, width, height, layer.ctypes.data, width, height, 6, 0, 0) == 0
            if mask is not None:
                assert gdal.GDALCreateMaskBand(band, 2) == 0
                mask_band = gdal.GDALGetMaskBand(band)
                mask_array = np.ascontiguousarray(mask, dtype="uint8")
                assert gdal.GDALRasterIO(mask_band, 1, 0, 0, width, height, mask_array.ctypes.data, width, height, 1, 0, 0) == 0
        options = []
        if format == "GRIB":
            end = datetime(2023, 1, 1, 6, tzinfo=timezone.utc) + timedelta(hours=end_hour)
            template = [1, parameter, 2, 0, 0, 0, 0, 1, end_hour - duration, 1, 0, 0, 255, -1, -2147483647,
                        end.year, end.month, end.day, end.hour, 0, 0, 1, 0, 1, 2, 1, duration, 255, 0]
            options = [b"DATA_ENCODING=IEEE_FLOATING_POINT", b"DISCIPLINE=0",
                       b"IDS=CENTER=98 SUBCENTER=0 MASTER_TABLE=35 LOCAL_TABLE=1 SIGNF_REF_TIME=1 REF_TIME=2023-01-01T06:00:00Z PROD_STATUS=0 TYPE=1",
                       b"PDS_PDTN=8", ("PDS_TEMPLATE_ASSEMBLED_VALUES=" + " ".join(map(str, template))).encode()]
        settings = (c.c_char_p * (len(options) + 1))(*options, None)
        result = gdal.GDALCreateCopy(gdal.GDALGetDriverByName(format.encode()), str(path).encode("utf8"),
                                     source, 0, settings, None, None)
        assert result, f"GDAL could not create {format} fixture"
        gdal.GDALClose(result)
    finally:
        gdal.GDALClose(source)
    return Path(path).read_bytes()
