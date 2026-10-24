using System.Text.Json;

namespace MeteoBridge.Era5;

internal sealed class ArchiveImports(string data, double[] bbox, int maxCells, int maxReadMiB, int lookahead, Action changed)
{
    public const long MaxBytes = 8L * 1024 * 1024 * 1024;
    private readonly SemaphoreSlim transfers = new(2);
    private string DirectoryPath => File.Exists(data) ? Path.GetDirectoryName(data)! : data;

    public async Task<object> ImportAsync(HttpRequest request, CancellationToken cancellation)
    {
        var name = request.Query["name"].ToString();
        if (string.IsNullOrWhiteSpace(name) || name != Path.GetFileName(name) || name.Contains(':') || name.Length > 180 || !Era5Index.Supported(name))
            throw new ArgumentException("Выберите .nc, .grib/.grib2 или GeoTIFF (.tif/.tiff).");
        if (request.ContentLength is <= 0 or > MaxBytes) throw new ArgumentException("Нужен непустой файл размером до 8 ГиБ.");
        ImportOptions? options = null;
        if (!Path.GetExtension(name).Equals(".nc", StringComparison.OrdinalIgnoreCase) && request.Query["metadata"] == "manual")
        {
            options = new ImportOptions(request.Query["start_utc"], request.Query["units"], request.Query["accumulation"].ToString());
            RasterSources.Hour(options.StartUtc ?? "");
            RasterSources.UnitFactor(options.Units);
            if (options.Accumulation is not ("hourly" or "cumulative")) throw new ArgumentException("Неверный тип накопления.");
        }
        await transfers.WaitAsync(cancellation);
        var id = Guid.NewGuid().ToString("N");
        var staging = Path.Combine(DirectoryPath, ".pending", id);
        var target = Path.Combine(DirectoryPath, "imports", id);
        var temporary = Path.Combine(staging, name);
        try
        {
            Directory.CreateDirectory(staging);
            await using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1048576, true))
            {
                var buffer = new byte[1048576];
                long total = 0;
                int length;
                while ((length = await request.Body.ReadAsync(buffer, cancellation)) > 0)
                {
                    total += length;
                    if (total > MaxBytes) throw new ArgumentException("Файл превышает 8 ГиБ.");
                    await output.WriteAsync(buffer.AsMemory(0, length), cancellation);
                }
                if (total == 0) throw new ArgumentException("Файл пуст.");
            }
            if (options is not null)
                await File.WriteAllTextAsync(temporary + ".meteo.json", JsonSerializer.Serialize(options), cancellation);
            Era5Index index;
            lock (NativeNetCdf.Gate) index = new Era5Index(temporary, bbox, maxCells, maxReadMiB, lookahead);
            cancellation.ThrowIfCancellationRequested();
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            Directory.Move(staging, target);
            changed();
            return new { name, format = index.Sources[0].Format, hours = index.Records.Count,
                start_utc = Era5Index.Iso(index.Start), end_utc = Era5Index.Iso(index.End) };
        }
        finally
        {
            if (File.Exists(temporary)) File.Delete(temporary);
            if (File.Exists(temporary + ".meteo.json")) File.Delete(temporary + ".meteo.json");
            if (Directory.Exists(staging)) Directory.Delete(staging);
            transfers.Release();
        }
    }
}
