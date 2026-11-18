using System.Buffers.Binary;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using MaxRev.Gdal.Core;
using OSGeo.GDAL;

namespace MeteoBridge.Era5.Tests;

internal static class RasterFixtures
{
    private const string Library = "fixture_netcdf";
    private const int Float = 5;
    private const int Double = 6;
    private static readonly double[] GlobalLat = Enumerable.Range(-90,181).Reverse().Select(value=>(double)value).ToArray();
    private static readonly double[] GlobalLon = Enumerable.Range(-180,360).Select(value=>(double)value).ToArray();

    static RasterFixtures()
    {
        NativeNetCdf.Initialize(TestDirectory.Root);
        NativeLibrary.SetDllImportResolver(typeof(RasterFixtures).Assembly, (name, assembly, search) =>
        {
            if (name != Library) return IntPtr.Zero;
            if (!OperatingSystem.IsWindows()) return NativeLibrary.Load("libnetcdf.so", assembly, search);
            var path = Directory.GetFiles(Path.Combine(TestDirectory.Root, "runtime", "netcdf"), "netcdf*.dll").First();
            var handle = LoadLibraryExW(path, IntPtr.Zero, 0x00000100 | 0x00001000);
            return handle != IntPtr.Zero ? handle : throw new DllNotFoundException(path);
        });
    }

    public static string Flat(string path, DateTimeOffset valid, int hours, params float[] millimetres)
    {
        var axes = new[]
        {
            ("time", Enumerable.Range(0, hours).Select(hour => (double)hour).ToArray(), $"hours since {valid:yyyy-MM-dd HH:mm:ss}"),
            ("latitude", new[] { 42d, 40d }, ""),
            ("longitude", new[] { 0d, 1d, 359d }, "")
        };
        var values = Enumerable.Range(0, hours * 6).Select(index =>
            millimetres.Length == 0 ? (float)(index * .001) : millimetres[index % millimetres.Length] / 1000).ToArray();
        return Netcdf(path, axes, [("lsp", values)], format: 0);
    }

    public static string Cycles(string path, DateTimeOffset origin, double[] offsets, float shift = 0)
    {
        var axes = new[]
        {
            ("forecast_initial_time", offsets, $"hours since {origin:yyyy-MM-dd HH:mm:ss}"),
            ("forecast_hour", Enumerable.Range(1, 12).Select(hour => (double)hour).ToArray(), ""),
            ("latitude", new[] { 42d, 40d }, ""),
            ("longitude", new[] { 0d, 1d, 359d }, "")
        };
        var values = Enumerable.Range(0, offsets.Length * 72).Select(index => index / 100000f + shift).ToArray();
        values[6] = -1;
        values[16] = 9.96921e36f;
        return Netcdf(path, axes, [("LSP", values)], format: 4096);
    }

    public static string GlobalArchive(string path, DateTimeOffset firstValid)
    {
        var axes = new[]
        {
            ("time", Enumerable.Range(0,24).Select(hour=>(double)hour).ToArray(), $"hours since {firstValid:yyyy-MM-dd HH:mm:ss}"),
            ("latitude", GlobalLat, ""), ("longitude", GlobalLon, "")
        };
        var values = Enumerable.Repeat(.0001f, 24 * GlobalLat.Length * GlobalLon.Length).ToArray();
        return Netcdf(path, axes, [("lsp",values)], format: 0);
    }

    public static Dictionary<string, byte[]> AtmosphericZarr(DateTimeOffset reference)
    {
        var start = reference.AddHours(-11);
        var levels = new[] { 1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 50 };
        var attributes = new
        {
            valid_time_start = FormattableString.Invariant($"{start:yyyy-MM-dd}"),
            valid_time_stop = FormattableString.Invariant($"{reference:yyyy-MM-dd}")
        };
        var group = new { zarr_format = 2 };
        var metadata = new Dictionary<string, object> { [".zgroup"] = group, [".zattrs"] = attributes };
        var objects = new Dictionary<string, byte[]>
        {
            [".zgroup"] = JsonSerializer.SerializeToUtf8Bytes(group),
            [".zattrs"] = JsonSerializer.SerializeToUtf8Bytes(attributes)
        };
        Coordinate("time", Enumerable.Range(0, 12).ToArray(), "<i4", FormattableString.Invariant($"hours since {start:yyyy-MM-dd HH:mm:ss}"));
        Coordinate("level", levels, "<i4", "hPa");
        Coordinate("latitude", GlobalLat, "<f8", "degrees_north");
        Coordinate("longitude", GlobalLon, "<f8", "degrees_east");
        foreach (var (name, value) in new (string, float)[]
        {
            ("temperature", 270), ("geopotential", 20000), ("u_component_of_wind", 1),
            ("v_component_of_wind", 1), ("vertical_velocity", 0), ("specific_humidity", .001f)
        }) Field(name, value, pressure: true, hours: [5, 11]);
        foreach (var (name, value) in new (string, float)[]
        {
            ("2m_temperature", 280), ("mean_sea_level_pressure", 100000),
            ("10m_u_component_of_wind", 1), ("10m_v_component_of_wind", 1)
        }) Field(name, value, pressure: false, hours: [5, 11]);
        Field("convective_precipitation", .00005f, pressure: false, hours: Enumerable.Range(0, 12));
        objects[".zmetadata"] = JsonSerializer.SerializeToUtf8Bytes(new { zarr_consolidated_format = 1, metadata });
        return objects;

        void Describe(string name, string[] dimensions, int[] shape, int[] chunks, string dtype, string? fill, string units)
        {
            metadata[name + "/.zarray"] = new { zarr_format = 2, shape, chunks, dtype, order = "C",
                fill_value = fill, compressor = (object?)null, filters = (object?)null };
            metadata[name + "/.zattrs"] = new { _ARRAY_DIMENSIONS = dimensions, units };
        }

        void Coordinate<T>(string name, T[] values, string dtype, string units) where T : struct
        {
            Describe(name, [name], [values.Length], [values.Length], dtype, null, units);
            objects[name + "/0"] = MemoryMarshal.AsBytes(values.AsSpan()).ToArray();
        }

        void Field(string name, float value, bool pressure, IEnumerable<int> hours)
        {
            var dimensions = pressure ? new[] { "time", "level", "latitude", "longitude" } : ["time", "latitude", "longitude"];
            var chunks = pressure ? new[] { 1, levels.Length, GlobalLat.Length, GlobalLon.Length } : [1, GlobalLat.Length, GlobalLon.Length];
            var shape = (int[])chunks.Clone();
            shape[0] = 12;
            Describe(name, dimensions, shape, chunks, "<f4", "NaN", name == "convective_precipitation" ? "m" : "");
            var values = Enumerable.Repeat(value, chunks.Aggregate((total, size) => total * size)).ToArray();
            var data = MemoryMarshal.AsBytes(values.AsSpan()).ToArray();
            var spatial = pressure ? ".0.0.0" : ".0.0";
            foreach (var hour in hours) objects[name + "/" + hour + spatial] = data;
        }
    }

    private static string Netcdf(string path, (string Name, double[] Axis, string Units)[] axes,
        (string Name, float[] Values)[] fields, int format)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        lock (NativeNetCdf.Gate)
        {
            var directory = NativeNetCdf.ReadPath(Path.GetDirectoryName(path)!);
            NativeNetCdf.Check(nc_create(Path.Combine(directory, Path.GetFileName(path)), format, out var dataset));
            try
            {
                var dimensions = new int[axes.Length];
                var variables = new int[axes.Length];
                for (var i = 0; i < axes.Length; i++)
                {
                    var (name, axis, units) = axes[i];
                    NativeNetCdf.Check(nc_def_dim(dataset, name, (nuint)axis.Length, out dimensions[i]));
                    NativeNetCdf.Check(nc_def_var(dataset, name, Double, 1, [dimensions[i]], out variables[i]));
                    if (units.Length > 0) Attribute(dataset, variables[i], "units", units);
                }
                var fieldIds = new int[fields.Length];
                for (var i=0;i<fields.Length;i++)
                {
                    var name = fields[i].Name;
                    NativeNetCdf.Check(nc_def_var(dataset, name, Float, dimensions.Length, dimensions, out fieldIds[i]));
                    if (name is "LSP" or "lsp") Attribute(dataset, fieldIds[i], "units", "m");
                    if (name == "LSP") Attribute(dataset, fieldIds[i], "rda_dataset", "ds633.0");
                    if (name == "lsp") Attribute(dataset, fieldIds[i], "standard_name", "lwe_thickness_of_stratiform_precipitation_amount");
                }
                NativeNetCdf.Check(nc_enddef(dataset));
                for (var i = 0; i < axes.Length; i++)
                    NativeNetCdf.Check(nc_put_var_double(dataset, variables[i], axes[i].Axis));
                for (var i=0;i<fields.Length;i++)
                    NativeNetCdf.Check(nc_put_var_float(dataset, fieldIds[i], fields[i].Values));
            }
            finally { NativeNetCdf.Check(nc_close(dataset)); }
        }
        return path;
    }

    private static void Attribute(int dataset, int variable, string name, string value)
    {
        var bytes = Encoding.UTF8.GetBytes(value);
        NativeNetCdf.Check(nc_put_att_text(dataset, variable, name, (nuint)bytes.Length, bytes));
    }

    public static byte[] Grib(DateTimeOffset valid, float[] meters, int duration = 1, byte parameter = 142)
    {
        var start = valid.AddHours(-duration);
        var pds = new byte[28];
        UInt24(pds, 28);
        new byte[] { 128, 98, 255, 255, 192, parameter, 1 }.CopyTo(pds, 3);
        new byte[] { (byte)(start.Year % 100), (byte)start.Month, (byte)start.Day, (byte)start.Hour, 0, 1, 0, (byte)duration, 4 }.CopyTo(pds, 12);
        pds[24] = (byte)(start.Year / 100 + 1);
        pds[27] = 3;
        var gds = new byte[32];
        UInt24(gds, 32);
        gds[4] = 255;
        gds[7] = 3;
        gds[9] = 2;
        UInt24(gds.AsSpan(10), 42000);
        UInt24(gds.AsSpan(13), 0x800000 | 1000);
        gds[16] = 128;
        UInt24(gds.AsSpan(17), 40000);
        UInt24(gds.AsSpan(20), 1000);
        BinaryPrimitives.WriteUInt16BigEndian(gds.AsSpan(23), 1000);
        BinaryPrimitives.WriteUInt16BigEndian(gds.AsSpan(25), 2000);
        byte[] bitmap = [0, 0, 7, 2, 0, 0, 0];
        for (var i = 0; i < meters.Length; i++)
            if (float.IsFinite(meters[i])) bitmap[^1] |= (byte)(128 >> i);
        var values = meters.Where(float.IsFinite).ToArray();
        var data = new byte[11 + 2 * values.Length];
        UInt24(data, data.Length);
        data[10] = 16;
        for (var i = 0; i < values.Length; i++)
            BinaryPrimitives.WriteUInt16BigEndian(data.AsSpan(11 + 2 * i), (ushort)Math.Round(values[i] * 1000));
        byte[] header = [(byte)'G', (byte)'R', (byte)'I', (byte)'B', 0, 0, 0, 1];
        UInt24(header.AsSpan(4), 8 + pds.Length + gds.Length + bitmap.Length + data.Length + 4);
        return [.. header, .. pds, .. gds, .. bitmap, .. data, .. "7777"u8];
    }

    private static void UInt24(Span<byte> destination, int value)
    {
        destination[0] = (byte)(value >> 16);
        destination[1] = (byte)(value >> 8);
        destination[2] = (byte)value;
    }

    public static string Tiff(string path, float[][] layers, byte[]? mask = null, bool projected = false)
    {
        lock (NativeNetCdf.Gate)
        {
            GdalBase.ConfigureAll();
            Gdal.AllRegister();
            Gdal.SetConfigOption("GDAL_TIFF_INTERNAL_MASK", "YES");
            using var driver = Gdal.GetDriverByName("GTiff");
            using var raster = driver.Create(path, 3, 2, layers.Length, DataType.GDT_Float32, []);
            using var reference = new OSGeo.OSR.SpatialReference("");
            reference.ImportFromEPSG(projected ? 3857 : 4326);
            reference.ExportToWkt(out var wkt, []);
            raster.SetProjection(wkt);
            raster.SetGeoTransform(projected ? [-166980, 111320, 0, 5352000, 0, -140000] : [-1.5, 1, 0, 43, 0, -2]);
            for (var i = 0; i < layers.Length; i++)
            {
                using var band = raster.GetRasterBand(i+1);
                band.SetNoDataValue(-9999);
                band.SetUnitType("mm");
                band.WriteRaster(0, 0, 3, 2, layers[i], 3, 2, 0, 0);
                if (mask is null) continue;
                band.CreateMaskBand(2);
                using var maskBand = band.GetMaskBand();
                maskBand.WriteRaster(0, 0, 3, 2, mask, 3, 2, 0, 0);
            }
        }
        return path;
    }

    [DllImport("kernel32", CharSet = CharSet.Unicode)]
    private static extern IntPtr LoadLibraryExW(string path, IntPtr file, uint flags);
    [DllImport(Library, CallingConvention = CallingConvention.Cdecl)]
    private static extern int nc_create([MarshalAs(UnmanagedType.LPUTF8Str)] string path, int mode, out int dataset);
    [DllImport(Library, CallingConvention = CallingConvention.Cdecl)]
    private static extern int nc_close(int dataset);
    [DllImport(Library, CallingConvention = CallingConvention.Cdecl)]
    private static extern int nc_def_dim(int dataset, string name, nuint length, out int dimension);
    [DllImport(Library, CallingConvention = CallingConvention.Cdecl)]
    private static extern int nc_def_var(int dataset, string name, int type, int dimensions, int[] ids, out int variable);
    [DllImport(Library, CallingConvention = CallingConvention.Cdecl)]
    private static extern int nc_put_att_text(int dataset, int variable, string name, nuint length, byte[] value);
    [DllImport(Library, CallingConvention = CallingConvention.Cdecl)]
    private static extern int nc_enddef(int dataset);
    [DllImport(Library, CallingConvention = CallingConvention.Cdecl)]
    private static extern int nc_put_var_double(int dataset, int variable, double[] values);
    [DllImport(Library, CallingConvention = CallingConvention.Cdecl)]
    private static extern int nc_put_var_float(int dataset, int variable, float[] values);
}
