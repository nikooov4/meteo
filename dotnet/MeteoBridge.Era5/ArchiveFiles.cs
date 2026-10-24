using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace MeteoBridge.Era5;

internal sealed record DeleteFileRequest(string Id);

internal sealed class ArchiveFiles(string data, ArchiveSession session, ArchiveDownloads downloads)
{
    private readonly string directory = Path.TrimEndingDirectorySeparator(File.Exists(data) ? Path.GetDirectoryName(data)! : data);

    public static string Id(string path)
    {
        var normalized = Path.GetFullPath(path);
        if (OperatingSystem.IsWindows()) normalized = normalized.ToUpperInvariant();
        return Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(normalized)));
    }

    public object List() => new
    {
        priority = new[] { "NetCDF", "GRIB", "GeoTIFF" },
        files = Era5Index.Files(directory).Order(StringComparer.Ordinal).Select(path =>
        {
            var info = new FileInfo(path);
            var source = new SourceFile(path, info.Length, info.LastWriteTimeUtc.Ticks);
            return new { id = Id(path), name = source.Name, format = source.Format, bytes = info.Length };
        })
    };

    public object Delete(string id)
    {
        if (!Regex.IsMatch(id ?? "", "^[a-f0-9]{64}$")) throw new ArgumentException("Неверный идентификатор файла.");
        var path = Era5Index.Files(directory).FirstOrDefault(path => Id(path) == id)
            ?? throw new ArgumentException("Файл не найден. Обновите список файлов.");
        var relative = Path.GetRelativePath(directory, path);
        if (Path.IsPathRooted(relative) || relative.Split(Path.DirectorySeparatorChar).Contains(".."))
            throw new ArgumentException("Файл находится вне папки архива.");
        if (new FileInfo(path).LinkTarget is not null) throw new IOException("Удаление файлов по символической ссылке не поддерживается.");
        for (var parent = new DirectoryInfo(Path.GetDirectoryName(path)!); parent is not null; parent = parent.Parent)
        {
            if (parent.LinkTarget is not null) throw new IOException("Удаление файлов через ссылку на папку не поддерживается.");
            if (string.Equals(parent.FullName, Path.GetFullPath(directory), OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal)) break;
        }
        downloads.DeleteFile(path, () => session.ChangeFiles(() =>
        {
            File.Delete(path);
            foreach (var suffix in new[] { ".download.json", ".meteo.json", ".aux.xml", ".msk" })
            {
                // Removing the data file is the operation; stale optional metadata
                // must not turn a successful deletion into a misleading failure.
                try { File.Delete(path + suffix); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }));
        return new { deleted = true, name = Path.GetFileName(path) };
    }
}
