using System.Collections.Concurrent;
using System.Globalization;
using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;

namespace MeteoBridge.Era5;

internal sealed record RemoteEra5File(string Key, string Name, long Bytes, string Etag, string Start, string End);
internal sealed record DownloadRequest(string Key);

internal sealed class ArchiveDownloads : IDisposable
{
    private sealed class Job(RemoteEra5File file, CancellationTokenSource cancellation)
    {
        public RemoteEra5File File { get; } = file;
        public CancellationTokenSource Cancellation { get; } = cancellation;
        public string State = "queued";
        public string? Error;
        public long Received;
        public Task? Task;
    }

    private readonly string directory;
    private readonly Uri bucket;
    private readonly HttpClient client;
    private readonly Action changed;
    private readonly SemaphoreSlim transfers = new(2), catalogGate = new(1);
    private readonly CancellationTokenSource shutdown = new();
    private readonly ConcurrentDictionary<string, RemoteEra5File> known = new();
    private readonly ConcurrentDictionary<string, Job> jobs = new();
    private readonly Dictionary<(int, int), (DateTime At, RemoteEra5File[] Files)> catalogs = [];
    private readonly object jobGate = new();
    private static readonly Regex FilePattern = new(@"^e5\.oper\.fc\.sfc\.accumu/(?<month>\d{6})/e5\.oper\.fc\.sfc\.accumu\.128_142_lsp\.ll025sc\.(?<start>\d{10})_(?<end>\d{10})\.nc$", RegexOptions.Compiled);

    public ArchiveDownloads(string data, string? baseUrl, Action changed)
    {
        directory = Path.GetExtension(data) == ".nc" ? Path.GetDirectoryName(data)! : data;
        bucket = new Uri((baseUrl ?? "https://nsf-ncar-era5.s3.us-west-2.amazonaws.com").TrimEnd('/') + "/");
        if (!(bucket.Scheme == "https" && bucket.Host == "nsf-ncar-era5.s3.us-west-2.amazonaws.com") &&
            !(bucket.Scheme == "http" && bucket.IsLoopback)) throw new ArgumentException("Нужен официальный S3 NCAR или loopback test server.");
        client = new HttpClient(new SocketsHttpHandler { AllowAutoRedirect = false, UseProxy = !bucket.IsLoopback })
            { Timeout = TimeSpan.FromSeconds(60), MaxResponseContentBufferSize = 4 * 1048576 };
        this.changed = changed;
    }

    public object Settings()
    {
        var years = Directory.Exists(directory) ? Directory.EnumerateFiles(directory, "*.nc", SearchOption.AllDirectories)
            .Select(path => Regex.Match(Path.GetFileName(path), @"\.ll025sc\.(\d{4})\d{6}_"))
            .Where(match => match.Success).Select(match => int.Parse(match.Groups[1].Value)).ToArray() : [];
        return new { directory, default_year = years.Length > 0 ? years.Max() : DateTime.UtcNow.Year - 1,
            first_year = 1940, last_year = DateTime.UtcNow.Year, parallel_downloads = 2 };
    }

    public async Task<object[]> FilesAsync(int year, int month, CancellationToken cancellation)
    {
        if (year < 1940 || year > DateTime.UtcNow.Year || month is < 0 or > 12) throw new ArgumentException("Неверный год или месяц.");
        await catalogGate.WaitAsync(cancellation);
        RemoteEra5File[] files;
        try
        {
            if (catalogs.TryGetValue((year, month), out var cached) && DateTime.UtcNow - cached.At < TimeSpan.FromHours(6)) files = cached.Files;
            else
            {
                var found = new ConcurrentBag<RemoteEra5File>();
                await Parallel.ForEachAsync(month == 0 ? Enumerable.Range(1, 12) : [month],
                    new ParallelOptions { MaxDegreeOfParallelism = 2, CancellationToken = cancellation }, async (selected, token) =>
                    {
                        foreach (var file in await ListMonthAsync(year, selected, token)) found.Add(file);
                    });
                files = found.OrderBy(file => file.Start, StringComparer.Ordinal).ToArray();
                catalogs[(year, month)] = (DateTime.UtcNow, files);
                foreach (var file in files) known[file.Key] = file;
            }
        }
        finally { catalogGate.Release(); }
        return files.Select(Snapshot).ToArray();
    }

    private async Task<List<RemoteEra5File>> ListMonthAsync(int year, int month, CancellationToken cancellation)
    {
        var prefix = $"e5.oper.fc.sfc.accumu/{year}{month:00}/e5.oper.fc.sfc.accumu.128_142_lsp.ll025sc.";
        string? continuation = null;
        var files = new List<RemoteEra5File>();
        for (var page = 0; page < 4; page++)
        {
            var query = "?list-type=2&max-keys=1000&prefix=" + Uri.EscapeDataString(prefix) +
                (continuation is null ? "" : "&continuation-token=" + Uri.EscapeDataString(continuation));
            var catalogUrl = new Uri(bucket, query);
            string? xml = null;
            for (var attempt = 0; attempt < 3; attempt++)
            {
                try { xml = await client.GetStringAsync(catalogUrl, cancellation); break; }
                catch (HttpRequestException error) when (attempt < 2 && !cancellation.IsCancellationRequested &&
                    (error.StatusCode is null || (int)error.StatusCode >= 500))
                { await Task.Delay(TimeSpan.FromMilliseconds(250 * (attempt + 1)), cancellation); }
            }
            if (xml is null) throw new IOException("Не удалось получить каталог NCAR.");
            using var reader = XmlReader.Create(new StringReader(xml), new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, MaxCharactersInDocument = 4 * 1048576 });
            var document = XDocument.Load(reader);
            var space = document.Root?.Name.Namespace ?? XNamespace.None;
            foreach (var entry in document.Descendants(space + "Contents"))
            {
                var key = entry.Element(space + "Key")?.Value ?? "";
                var match = FilePattern.Match(key);
                if (!key.StartsWith(prefix, StringComparison.Ordinal) || !match.Success) continue;
                static string Iso(string stamp) => DateTime.ParseExact(stamp, "yyyyMMddHH", CultureInfo.InvariantCulture,
                    DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal).ToString("yyyy-MM-dd'T'HH:mm:ss'Z'");
                var size = long.Parse(entry.Element(space + "Size")?.Value ?? "0", CultureInfo.InvariantCulture);
                if (size <= 0) continue;
                files.Add(new RemoteEra5File(key, Path.GetFileName(key), size, entry.Element(space + "ETag")?.Value ?? "",
                    Iso(match.Groups["start"].Value), Iso(match.Groups["end"].Value)));
            }
            if (document.Root?.Element(space + "IsTruncated")?.Value != "true") return files;
            continuation = document.Root.Element(space + "NextContinuationToken")?.Value ?? throw new IOException("Неполный каталог NCAR.");
        }
        throw new IOException("Каталог NCAR превышает лимит страниц.");
    }

    private string Target(RemoteEra5File file)
    {
        var candidate = Path.Combine(directory, file.Name);
        if (File.Exists(candidate) || !Directory.Exists(directory)) return candidate;
        return Directory.EnumerateFiles(directory, file.Name, SearchOption.AllDirectories).FirstOrDefault() ?? candidate;
    }

    private object Snapshot(RemoteEra5File file)
    {
        var path = Target(file);
        var existing = new FileInfo(path);
        jobs.TryGetValue(file.Key, out var job);
        var downloaded = existing.Exists && existing.Length == file.Bytes;
        var partial = new FileInfo(Path.Combine(directory, file.Name + ".partial"));
        var state = downloaded ? "downloaded" : job is not null ? Volatile.Read(ref job.State) :
            existing.Exists ? "conflict" : partial.Exists ? "paused" : "available";
        var received = downloaded ? file.Bytes : job is not null ? Interlocked.Read(ref job.Received) : partial.Exists ? partial.Length : 0;
        return new { key = file.Key, name = file.Name, bytes = file.Bytes, start_utc = file.Start, end_utc = file.End,
            state, received_bytes = received, error = job?.Error, downloaded };
    }

    public object Start(string key)
    {
        if (!known.TryGetValue(key, out var file)) throw new ArgumentException("Сначала откройте каталог выбранного периода.");
        lock (jobGate)
        {
            var target = new FileInfo(Target(file));
            if (target.Exists)
            {
                if (target.Length != file.Bytes) throw new IOException("Локальный файл имеет другой размер. Он не будет перезаписан.");
                return Snapshot(file);
            }
            if (jobs.TryGetValue(key, out var running) && running.Task is { IsCompleted: false }) return Snapshot(file);
            if (jobs.Values.Count(job => job.Task is { IsCompleted: false }) >= 24) throw new IOException("В очереди уже 24 файла. Дождитесь завершения загрузок.");
            Directory.CreateDirectory(directory);
            var reserved = jobs.Values.Where(job => job.Task is { IsCompleted: false })
                .Sum(job => Math.Max(0, job.File.Bytes - Interlocked.Read(ref job.Received)));
            var partial = new FileInfo(Path.Combine(directory, file.Name + ".partial"));
            var remaining = file.Bytes - (partial.Exists ? Math.Min(file.Bytes, partial.Length) : 0);
            if (new DriveInfo(Path.GetPathRoot(directory)!).AvailableFreeSpace < reserved + remaining + 512L * 1048576)
                throw new IOException("Недостаточно свободного места для очереди загрузок с резервом 512 MiB.");
            var job = new Job(file, CancellationTokenSource.CreateLinkedTokenSource(shutdown.Token));
            if (running is not null) running.Cancellation.Dispose();
            jobs[key] = job;
            job.Task = TransferAsync(job);
            return Snapshot(file);
        }
    }

    public object Cancel(string key)
    {
        if (!jobs.TryGetValue(key, out var job)) throw new ArgumentException("Загрузка не найдена.");
        job.Cancellation.Cancel();
        return Snapshot(job.File);
    }

    private async Task TransferAsync(Job job)
    {
        var entered = false;
        var token = job.Cancellation.Token;
        var file = job.File;
        var partial = Path.Combine(directory, file.Name + ".partial");
        var checkpoint = Path.Combine(directory, file.Name + ".download.json");
        try
        {
            await transfers.WaitAsync(token);
            entered = true;
            job.State = "downloading";
            var url = new Uri(bucket, file.Key);
            var offset = 0L;
            if (File.Exists(partial) && File.Exists(checkpoint))
            {
                using var pin = JsonDocument.Parse(await File.ReadAllTextAsync(checkpoint, token));
                if (pin.RootElement.GetProperty("etag").GetString() == file.Etag &&
                    pin.RootElement.GetProperty("bytes").GetInt64() == file.Bytes &&
                    pin.RootElement.GetProperty("url").GetString() == url.AbsoluteUri) offset = new FileInfo(partial).Length;
            }
            if (offset > file.Bytes) throw new IOException("Частичный файл длиннее оригинала.");
            var drive = new DriveInfo(Path.GetPathRoot(directory)!);
            if (drive.AvailableFreeSpace < file.Bytes - offset + 512L * 1048576) throw new IOException("Недостаточно свободного места с резервом 512 MiB.");
            var pinPath = checkpoint + ".tmp";
            await File.WriteAllTextAsync(pinPath, JsonSerializer.Serialize(new { url = url.AbsoluteUri, etag = file.Etag, bytes = file.Bytes }), token);
            File.Move(pinPath, checkpoint, true);
            await using (var stream = new FileStream(partial, offset == 0 ? FileMode.Create : FileMode.Open,
                FileAccess.Write, FileShare.Read, 65536, useAsync: true))
            {
                stream.Position = offset;
                Interlocked.Exchange(ref job.Received, offset);
                while (offset < file.Bytes)
                {
                    var last = Math.Min(file.Bytes, offset + 4 * 1048576) - 1;
                    byte[]? payload = null;
                    for (var attempt = 0; attempt < 3; attempt++)
                    {
                        try
                        {
                            using var request = new HttpRequestMessage(HttpMethod.Get, url);
                            request.Headers.Range = new RangeHeaderValue(offset, last);
                            if (file.Etag.Length > 0) request.Headers.IfMatch.ParseAdd(file.Etag);
                            using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, token);
                            response.EnsureSuccessStatusCode();
                            var range = response.Content.Headers.ContentRange;
                            if (response.StatusCode != HttpStatusCode.PartialContent || range?.From != offset || range.To != last || range.Length != file.Bytes)
                                throw new IOException("NCAR вернул неверный диапазон файла.");
                            if (response.Content.Headers.ContentLength != last - offset + 1) throw new IOException("Неверная длина блока NCAR.");
                            payload = new byte[checked((int)(last - offset + 1))];
                            await using var body = await response.Content.ReadAsStreamAsync(token);
                            await body.ReadExactlyAsync(payload, token);
                            break;
                        }
                        catch (Exception error) when (!token.IsCancellationRequested && attempt < 2 && error is HttpRequestException or IOException or TaskCanceledException)
                        {
                            await Task.Delay(TimeSpan.FromSeconds(attempt + 1), token);
                        }
                    }
                    await stream.WriteAsync(payload ?? throw new IOException("Пустой блок NCAR."), token);
                    await stream.FlushAsync(token);
                    offset = stream.Position;
                    Interlocked.Exchange(ref job.Received, offset);
                }
            }
            job.State = "validating";
            lock (NativeNetCdf.Gate)
            {
                using var dataset = new NetCdfFile(partial);
                var variable = dataset.Variable("LSP");
                if (dataset.Text(variable, "units") != "m" || dataset.Text(variable, "rda_dataset") != "ds633.0" ||
                    !dataset.Dimensions(variable).Select(dimension => dimension.Name).SequenceEqual(new[] { "forecast_initial_time", "forecast_hour", "latitude", "longitude" }))
                    throw new InvalidDataException("Загруженный файл не соответствует NCAR ERA5 LSP.");
                var steps = dataset.Axis("forecast_hour");
                if (!steps.SequenceEqual(Enumerable.Range(1, steps.Length).Select(value => (double)value)) || steps.Length is < 1 or > 12)
                    throw new InvalidDataException("Неверные почасовые шаги NCAR.");
            }
            token.ThrowIfCancellationRequested();
            File.Move(partial, Path.Combine(directory, file.Name), overwrite: false);
            job.State = "downloaded";
            changed();
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { job.State = "paused"; }
        catch (Exception error) { job.Error = error.Message; job.State = "failed"; }
        finally { if (entered) transfers.Release(); }
    }

    public void Dispose()
    {
        shutdown.Cancel();
        client.Dispose();
    }
}
