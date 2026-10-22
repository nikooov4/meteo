using System.Runtime.InteropServices;
using System.Text;

namespace MeteoBridge.Era5;

internal static class NativeNetCdf
{
    internal static object Gate { get; } = new();

    public static void Initialize(string root)
    {
        NativeLibrary.SetDllImportResolver(typeof(NativeNetCdf).Assembly, (name, assembly, search) =>
        {
            if (name != "meteo_netcdf") return IntPtr.Zero;
            var configured = Environment.GetEnvironmentVariable("METEOBRIDGE_NETCDF_LIBRARY");
            if (!OperatingSystem.IsWindows()) return NativeLibrary.Load(configured ?? "libnetcdf.so", assembly, search);
            var directories = new[] { Path.Combine(AppContext.BaseDirectory, "Native"), Path.Combine(root, "runtime", "netcdf") };
            var path = configured ?? directories.Where(Directory.Exists)
                .SelectMany(directory => Directory.GetFiles(directory, "netcdf*.dll")).FirstOrDefault();
            if (path is null) throw new DllNotFoundException("Выполните scripts/setup_runtime.ps1 или задайте METEOBRIDGE_NETCDF_LIBRARY.");
            var library = LoadLibraryExW(Path.GetFullPath(path), IntPtr.Zero, 0x00000100 | 0x00001000);
            if (library == IntPtr.Zero) throw new DllNotFoundException($"Не удалось загрузить NetCDF: {path}; Win32={Marshal.GetLastWin32Error()}");
            return library;
        });
    }

    public static void Check(int status)
    {
        if (status != 0) throw new InvalidDataException(Marshal.PtrToStringUTF8(nc_strerror(status)) ?? $"NetCDF error {status}");
    }

    public static string ReadPath(string path)
    {
        if (!OperatingSystem.IsWindows() || path.All(character => character < 128)) return path;
        var buffer = new StringBuilder(32768);
        if (GetShortPathNameW(path, buffer, (uint)buffer.Capacity) == 0)
            throw new IOException($"Недоступен короткий путь NetCDF: {path}");
        return buffer.ToString();
    }

    [DllImport("kernel32", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr LoadLibraryExW(string path, IntPtr file, uint flags);
    [DllImport("kernel32", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetShortPathNameW(string path, StringBuilder buffer, uint size);
    [DllImport("meteo_netcdf", CallingConvention = CallingConvention.Cdecl)]
    internal static extern int nc_open([MarshalAs(UnmanagedType.LPUTF8Str)] string path, int mode, out int id);
    [DllImport("meteo_netcdf", CallingConvention = CallingConvention.Cdecl)]
    internal static extern int nc_close(int id);
    [DllImport("meteo_netcdf", CallingConvention = CallingConvention.Cdecl)]
    internal static extern IntPtr nc_strerror(int status);
    [DllImport("meteo_netcdf", CallingConvention = CallingConvention.Cdecl)]
    internal static extern int nc_inq_varid(int id, [MarshalAs(UnmanagedType.LPUTF8Str)] string name, out int variable);
    [DllImport("meteo_netcdf", CallingConvention = CallingConvention.Cdecl)]
    internal static extern int nc_inq_varndims(int id, int variable, out int count);
    [DllImport("meteo_netcdf", CallingConvention = CallingConvention.Cdecl)]
    internal static extern int nc_inq_vardimid(int id, int variable, [Out] int[] dimensions);
    [DllImport("meteo_netcdf", CallingConvention = CallingConvention.Cdecl)]
    internal static extern int nc_inq_dim(int id, int dimension, [Out] byte[] name, out nuint length);
    [DllImport("meteo_netcdf", CallingConvention = CallingConvention.Cdecl)]
    internal static extern int nc_inq_att(int id, int variable, [MarshalAs(UnmanagedType.LPUTF8Str)] string name, out int type, out nuint length);
    [DllImport("meteo_netcdf", CallingConvention = CallingConvention.Cdecl)]
    internal static extern int nc_get_att_text(int id, int variable, [MarshalAs(UnmanagedType.LPUTF8Str)] string name, [Out] byte[] value);
    [DllImport("meteo_netcdf", CallingConvention = CallingConvention.Cdecl)]
    internal static extern int nc_get_att_double(int id, int variable, [MarshalAs(UnmanagedType.LPUTF8Str)] string name, [Out] double[] value);
    [DllImport("meteo_netcdf", CallingConvention = CallingConvention.Cdecl)]
    internal static extern int nc_get_var_double(int id, int variable, [Out] double[] values);
    [DllImport("meteo_netcdf", CallingConvention = CallingConvention.Cdecl)]
    internal static extern int nc_get_vara_float(int id, int variable, nuint[] start, nuint[] count, [Out] float[] values);
    [DllImport("meteo_netcdf", CallingConvention = CallingConvention.Cdecl)]
    internal static extern int nc_set_var_chunk_cache(int id, int variable, nuint bytes, nuint slots, float preemption);
}

internal sealed class NetCdfFile : IDisposable
{
    public int Id { get; }

    public NetCdfFile(string path)
    {
        NativeNetCdf.Check(NativeNetCdf.nc_open(NativeNetCdf.ReadPath(path), 0, out var id));
        Id = id;
    }

    public int Variable(string name)
    {
        NativeNetCdf.Check(NativeNetCdf.nc_inq_varid(Id, name, out var variable));
        return variable;
    }

    public (string Name, int Length)[] Dimensions(int variable)
    {
        NativeNetCdf.Check(NativeNetCdf.nc_inq_varndims(Id, variable, out var count));
        if (count > 32) throw new InvalidDataException("Слишком много измерений NetCDF.");
        var ids = new int[count];
        NativeNetCdf.Check(NativeNetCdf.nc_inq_vardimid(Id, variable, ids));
        return ids.Select(dimension =>
        {
            var name = new byte[257];
            NativeNetCdf.Check(NativeNetCdf.nc_inq_dim(Id, dimension, name, out var length));
            return (Encoding.UTF8.GetString(name).TrimEnd('\0'), checked((int)length));
        }).ToArray();
    }

    public string? Text(int variable, string name)
    {
        var status = NativeNetCdf.nc_inq_att(Id, variable, name, out var type, out var length);
        if (status == -43) return null;
        NativeNetCdf.Check(status);
        if (type != 2 || length > 65536) throw new InvalidDataException($"Неверный текстовый атрибут {name}.");
        var value = new byte[(int)length];
        NativeNetCdf.Check(NativeNetCdf.nc_get_att_text(Id, variable, name, value));
        return Encoding.UTF8.GetString(value).TrimEnd('\0');
    }

    public double[] Numbers(int variable, string name)
    {
        var status = NativeNetCdf.nc_inq_att(Id, variable, name, out _, out var length);
        if (status == -43) return [];
        NativeNetCdf.Check(status);
        if (length > 16) throw new InvalidDataException($"Слишком длинный атрибут {name}.");
        var values = new double[(int)length];
        NativeNetCdf.Check(NativeNetCdf.nc_get_att_double(Id, variable, name, values));
        return values;
    }

    public double[] Axis(string name)
    {
        var variable = Variable(name);
        var dimensions = Dimensions(variable);
        if (dimensions.Length != 1 || dimensions[0].Name != name || dimensions[0].Length > 10_000_000)
            throw new InvalidDataException($"Некорректная ось {name}.");
        var values = new double[dimensions[0].Length];
        NativeNetCdf.Check(NativeNetCdf.nc_get_var_double(Id, variable, values));
        if (values.Any(value => !double.IsFinite(value))) throw new InvalidDataException($"Неверные координаты {name}.");
        return values;
    }

    public void Dispose() => NativeNetCdf.Check(NativeNetCdf.nc_close(Id));
}
