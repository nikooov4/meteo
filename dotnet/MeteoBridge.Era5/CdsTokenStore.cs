using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

namespace MeteoBridge.Era5;

internal sealed class CdsTokenStore(string path)
{
    private static readonly byte[] Header = "MeteoBridge.CDS.DPAPI1\n"u8.ToArray();

    public string? Load()
    {
        if (!File.Exists(path)) return null;
        byte[]? plain = null;
        try
        {
            var saved = File.ReadAllBytes(path);
            if (OperatingSystem.IsWindows())
            {
                if (!saved.AsSpan().StartsWith(Header)) return null;
                plain = Protect(saved[Header.Length..], false);
            }
            else plain = saved;
            return Encoding.UTF8.GetString(plain);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or CryptographicException) { return null; }
        finally { if (plain is not null) CryptographicOperations.ZeroMemory(plain); }
    }

    public void Save(string? token)
    {
        if (string.IsNullOrEmpty(token)) { File.Delete(path); return; }
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var plain = Encoding.UTF8.GetBytes(token);
        var temporary = path + ".tmp";
        try
        {
            var payload = OperatingSystem.IsWindows() ? Header.Concat(Protect(plain, true)).ToArray() : plain;
            var options = new FileStreamOptions { Mode = FileMode.Create, Access = FileAccess.Write, Share = FileShare.None };
            if (!OperatingSystem.IsWindows()) options.UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite;
            using (var output = new FileStream(temporary, options)) { output.Write(payload); output.Flush(true); }
            File.Move(temporary, path, true);
        }
        catch (CryptographicException error)
        {
            throw new IOException("Не удалось зашифровать и сохранить токен CDS для текущей учётной записи Windows.", error);
        }
        finally
        {
            CryptographicOperations.ZeroMemory(plain);
            if (File.Exists(temporary)) File.Delete(temporary);
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct Blob { public int Size; public IntPtr Data; }

    [DllImport("crypt32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptProtectData(ref Blob input, string description, IntPtr entropy, IntPtr reserved, IntPtr prompt, int flags, out Blob output);
    [DllImport("crypt32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptUnprotectData(ref Blob input, IntPtr description, IntPtr entropy, IntPtr reserved, IntPtr prompt, int flags, out Blob output);
    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr memory);

    private static byte[] Protect(byte[] payload, bool encrypt)
    {
        var input = new Blob { Size = payload.Length, Data = Marshal.AllocHGlobal(payload.Length) };
        Blob output = default;
        try
        {
            Marshal.Copy(payload, 0, input.Data, payload.Length);
            var success = encrypt
                ? CryptProtectData(ref input, "MeteoBridge CDS token", IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 1, out output)
                : CryptUnprotectData(ref input, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 1, out output);
            if (!success) throw new CryptographicException(Marshal.GetLastWin32Error());
            var result = new byte[output.Size];
            Marshal.Copy(output.Data, result, 0, result.Length);
            return result;
        }
        finally
        {
            Marshal.Copy(new byte[input.Size], 0, input.Data, input.Size);
            Marshal.FreeHGlobal(input.Data);
            if (output.Data != IntPtr.Zero)
            {
                if (!encrypt) Marshal.Copy(new byte[output.Size], 0, output.Data, output.Size);
                LocalFree(output.Data);
            }
        }
    }
}
