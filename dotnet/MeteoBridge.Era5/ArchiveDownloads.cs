using System.Collections.Concurrent;
using System.Globalization;
using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;

namespace MeteoBridge.Era5;

internal sealed record RemoteEra5File(string Key, string Name, long Bytes, string Etag, string Start, string End,
    string Source = "amazon", string? RemoteKey = null)
{
    public string Format => Source == "cds" ? "GRIB" : "NetCDF";
    public string Provider => Source switch { "amazon" => "Amazon S3 · NCAR ERA5", "cds" => "Copernicus CDS · ERA5", _ => "Google ARCO-ERA5" };
}
internal sealed record DownloadRequest(string Key);

internal sealed class ArchiveDownloads : IDisposable
{
    private sealed class Job(RemoteEra5File file, CancellationTokenSource cancellation)
    {
        public RemoteEra5File File = file;
        public CancellationTokenSource Cancellation { get; } = cancellation;
        public string State = "queued";
        public string? Error;
        public string? ErrorCode, ActionUrl;
        public long Received;
        public DateTime StartedUtc { get; } = DateTime.UtcNow;
        public Task? Task;
    }

    private readonly string directory;
    private readonly Uri bucket;
    private readonly Uri arcoBucket, arcoCatalog;
    private readonly HttpClient client;
    private readonly CdsArchive cds;
    private readonly string queuePath;
    private readonly HashSet<string> wantedCds = [];
    private long estimatedCdsBytes;
    private readonly Action changed;
    private readonly SemaphoreSlim transfers = new(2), catalogGate = new(1);
    private readonly CancellationTokenSource shutdown = new();
    private readonly ConcurrentDictionary<string, RemoteEra5File> known = new();
    private readonly ConcurrentDictionary<string, Job> jobs = new();
    private readonly Dictionary<(string, int, int), (DateTime At, RemoteEra5File[] Files)> catalogs = [];
    private readonly object jobGate = new();
    private static readonly Regex FilePattern = new(@"^e5\.oper\.fc\.sfc\.accumu/(?<month>\d{6})/e5\.oper\.fc\.sfc\.accumu\.128_142_lsp\.ll025sc\.(?<start>\d{10})_(?<end>\d{10})\.nc$", RegexOptions.Compiled);

    public ArchiveDownloads(string data, string? baseUrl, Action changed, string? arcoBaseUrl = null,
        string? cdsBaseUrl = null, string? cdsToken = null)
    {
        directory = File.Exists(data) ? Path.GetDirectoryName(data)! : data;
        bucket = new Uri((baseUrl ?? "https://nsf-ncar-era5.s3.us-west-2.amazonaws.com").TrimEnd('/') + "/");
        arcoBucket = new Uri((arcoBaseUrl ?? "https://storage.googleapis.com/gcp-public-data-arco-era5").TrimEnd('/') + "/");
        if (!(arcoBucket.Scheme == "https" && arcoBucket.Host == "storage.googleapis.com" && arcoBucket.AbsolutePath == "/gcp-public-data-arco-era5/") &&
            !(arcoBucket.Scheme == "http" && arcoBucket.IsLoopback)) throw new ArgumentException("Нужен официальный архив Google ARCO-ERA5 или loopback test server.");
        arcoCatalog = arcoBucket.IsLoopback ? arcoBucket : new Uri("https://storage.googleapis.com/storage/v1/b/gcp-public-data-arco-era5/o");
        if (!(bucket.Scheme == "https" && bucket.Host == "nsf-ncar-era5.s3.us-west-2.amazonaws.com") &&
            !(bucket.Scheme == "http" && bucket.IsLoopback)) throw new ArgumentException("Нужен официальный S3 NCAR или loopback test server.");
        client = new HttpClient(new SocketsHttpHandler { AllowAutoRedirect = false, UseProxy = !bucket.IsLoopback && !arcoBucket.IsLoopback })
            { Timeout = TimeSpan.FromSeconds(60), MaxResponseContentBufferSize = 4 * 1048576 };
        this.changed = changed;
        var settings = Path.Combine(directory, ".meteo-settings");
        cds = new CdsArchive(cdsBaseUrl, cdsToken, Path.Combine(settings, "cds-token.bin"));
        queuePath = Path.Combine(settings, "cds-queue.json");
        if (File.Exists(queuePath))
        {
            try
            {
                foreach (var key in JsonSerializer.Deserialize<string[]>(File.ReadAllText(queuePath)) ?? [])
                    if (Regex.IsMatch(key, @"^cds:\d{4}-\d{2}-\d{2}$")) wantedCds.Add(key);
            }
            catch (Exception error) when (error is IOException or JsonException) { }
        }
        ResumeCdsQueue();
    }

    public object ConfigureCds(string token)
    {
        var result = cds.Configure(token);
        ResumeCdsQueue();
        return result;
    }

    private void SaveCdsQueue()
    {
        Directory.CreateDirectory(Path.GetDirectoryName(queuePath)!);
        File.WriteAllText(queuePath + ".tmp", JsonSerializer.Serialize(wantedCds.Order()));
        File.Move(queuePath + ".tmp", queuePath, true);
    }

    private void ForgetCds(string key)
    {
        lock (jobGate)
        {
            if (!wantedCds.Remove(key)) return;
            try { SaveCdsQueue(); }
            catch (IOException) { } // A completed file stays complete if optional queue cleanup fails.
        }
    }

    private void ResumeCdsQueue()
    {
        if (!cds.Configured) return;
        lock (jobGate)
        {
            foreach (var key in wantedCds.Take(512).ToArray())
            {
                if (!DateTime.TryParseExact(key[4..], "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var day) ||
                    day.Year < 1940 || day.Year > DateTime.UtcNow.Year) continue;
                var file = CdsArchive.List(day.Year, day.Month).FirstOrDefault(file => file.Key == key);
                if (file is null) continue;
                known.TryAdd(key, file);
                try { Start(key); }
                catch (Exception error) when (error is ArgumentException or IOException) { }
            }
        }
    }

    public object Settings()
    {
        var years = Directory.Exists(directory) ? Era5Index.Files(directory)
            .Select(path => Regex.Match(Path.GetFileName(path), @"(?:\.ll025sc\.|^era5-arco-lsp-|^era5-cds-lsp-)(\d{4})\d{4}"))
            .Where(match => match.Success).Select(match => int.Parse(match.Groups[1].Value)).ToArray() : [];
        return new { directory, default_year = years.Length > 0 ? years.Max() : DateTime.UtcNow.Year - 1,
            first_year = 1940, last_year = DateTime.UtcNow.Year, parallel_downloads = 2, cds_configured = cds.Configured,
            sources = new[]
            {
                new { id = "amazon", label = "Amazon S3 · NCAR ERA5", format = "NetCDF", provider = "Amazon S3 · NCAR ERA5",
                    archive_url = "https://nsf-ncar-era5.s3.us-west-2.amazonaws.com/?prefix=e5.oper.fc.sfc.accumu/",
                    description = "Исходные NetCDF из Amazon S3 / NCAR: первая и вторая половины месяца. Файлы сохраняются без преобразования." },
                new { id = "google", label = "Google · ARCO-ERA5", format = "NetCDF", provider = "Google ARCO-ERA5",
                    archive_url = "https://storage.googleapis.com/gcp-public-data-arco-era5?prefix=raw/date-variable-single_level/",
                    description = "Исходные суточные NetCDF ERA5 LSP из Google ARCO. Файлы сохраняются без преобразования и читаются картой напрямую." },
                new { id = "cds", label = "Copernicus CDS · ERA5", format = "GRIB", provider = "Copernicus CDS · ERA5",
                    archive_url = "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=download",
                    description = "Суточные запросы ERA5 LSP в исходном GRIB, все 24 часа UTC, весь мир. Размер известен после подготовки CDS. Нужны API-токен и принятие условий ERA5 на сайте CDS. Последние 6 дней не запрашиваются." }
            } };
    }

    public async Task<object[]> FilesAsync(int year, int month, CancellationToken cancellation, string source = "amazon")
    {
        if (source is not ("amazon" or "google" or "cds")) throw new ArgumentException("Выберите Amazon, Google или Copernicus CDS.");
        if (year < 1940 || year > DateTime.UtcNow.Year || month is < 0 or > 12) throw new ArgumentException("Неверный год или месяц.");
        if (source == "cds")
        {
            // An estimate never participates in byte counts or transfer progress.
            // Compare only the same full-day, global CDS LSP product.
            var samples = Directory.Exists(directory) ? Directory.EnumerateFiles(directory, "era5-cds-lsp-*.grib")
                .Where(path => Regex.IsMatch(Path.GetFileName(path), @"^era5-cds-lsp-\d{8}\.grib$"))
                .Select(path => new FileInfo(path).Length).Where(size => size > 0).Order().ToArray() : [];
            Interlocked.Exchange(ref estimatedCdsBytes, samples.Length == 0 ? 0 : samples[samples.Length / 2]);
            return CdsArchive.List(year, month).Select(file =>
            {
                file = known.GetOrAdd(file.Key, file);
                return Snapshot(file);
            }).ToArray();
        }
        await catalogGate.WaitAsync(cancellation);
        RemoteEra5File[] files;
        try
        {
            if (catalogs.TryGetValue((source, year, month), out var cached) && DateTime.UtcNow - cached.At < TimeSpan.FromHours(6)) files = cached.Files;
            else
            {
                var found = new ConcurrentBag<RemoteEra5File>();
                await Parallel.ForEachAsync(month == 0 ? Enumerable.Range(1, 12) : [month],
                    new ParallelOptions { MaxDegreeOfParallelism = 2, CancellationToken = cancellation }, async (selected, token) =>
                    {
                        foreach (var file in source == "amazon" ? await ListMonthAsync(year, selected, token) : await ListArcoAsync(year, selected, token)) found.Add(file);
                    });
                files = found.OrderBy(file => file.Start, StringComparer.Ordinal).ToArray();
                catalogs[(source, year, month)] = (DateTime.UtcNow, files);
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

    private async Task<List<RemoteEra5File>> ListArcoAsync(int year, int month, CancellationToken cancellation)
    {
        var prefix = $"raw/date-variable-single_level/{year}/{month:00}/";
        var pattern = new Regex($@"^raw/date-variable-single_level/{year}/{month:00}/(?<day>\d{{2}})/large_scale_precipitation/surface\.nc$");
        string? continuation = null;
        var files = new List<RemoteEra5File>();
        for (var page = 0; page < 64; page++)
        {
            var query = "?prefix=" + Uri.EscapeDataString(prefix) + "&matchGlob=" + Uri.EscapeDataString(prefix + "**/large_scale_precipitation/surface.nc") +
                "&maxResults=1000&fields=" + Uri.EscapeDataString("items(name,size,md5Hash,generation),nextPageToken") +
                (continuation is null ? "" : "&pageToken=" + Uri.EscapeDataString(continuation));
            using var response = await client.GetAsync(new Uri(arcoCatalog.AbsoluteUri.TrimEnd('/') + query), cancellation);
            response.EnsureSuccessStatusCode();
            using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellation));
            if (document.RootElement.TryGetProperty("items", out var items))
                foreach (var item in items.EnumerateArray())
                {
                    var key = item.GetProperty("name").GetString() ?? "";
                    var match = pattern.Match(key);
                    if (!match.Success) continue;
                    var day = int.Parse(match.Groups["day"].Value, CultureInfo.InvariantCulture);
                    if (day < 1 || day > DateTime.DaysInMonth(year, month)) continue;
                    var bytes = long.Parse(item.GetProperty("size").GetString() ?? "0", CultureInfo.InvariantCulture);
                    if (bytes <= 0 || bytes > ArchiveImports.MaxBytes) continue;
                    var date = new DateTimeOffset(year, month, day, 0, 0, 0, TimeSpan.Zero);
                    var name = $"era5-arco-lsp-{year}{month:00}{day:00}.nc";
                    var etag = item.TryGetProperty("md5Hash", out var md5) ? "\"" + Convert.ToHexStringLower(Convert.FromBase64String(md5.GetString()!)) + "\"" : "";
                    var generation = item.TryGetProperty("generation", out var version) ? version.GetString() : null;
                    if (generation is not null && !Regex.IsMatch(generation, @"^\d+$")) throw new InvalidDataException("Неверная версия объекта ARCO.");
                    var remoteKey = key + (generation is null ? "" : "?generation=" + generation);
                    files.Add(new RemoteEra5File("google:" + key, name, bytes, etag,
                        Era5Index.Iso(date.AddHours(-1).ToUnixTimeSeconds()), Era5Index.Iso(date.AddHours(23).ToUnixTimeSeconds()), "google", remoteKey));
                }
            if (!document.RootElement.TryGetProperty("nextPageToken", out var next) || string.IsNullOrEmpty(next.GetString())) return files;
            continuation = next.GetString();
        }
        throw new IOException("Каталог ARCO превышает лимит страниц.");
    }

    private bool Downloaded(RemoteEra5File file, FileInfo existing)
    {
        if (!existing.Exists) return false;
        if (file.Source == "cds" && file.Bytes == 0)
        {
            var receipt = existing.FullName + ".download.json";
            if (!File.Exists(receipt)) return false;
            try
            {
                using var saved = JsonDocument.Parse(File.ReadAllText(receipt));
                return saved.RootElement.TryGetProperty("key", out var key) && key.GetString() == file.Key &&
                    saved.RootElement.GetProperty("bytes").GetInt64() == existing.Length && existing.Length > 0;
            }
            catch (Exception error) when (error is IOException or JsonException or KeyNotFoundException or InvalidOperationException) { return false; }
        }
        return existing.Length == file.Bytes;
    }

    private Uri Url(RemoteEra5File file) => file.Source == "cds" ? new Uri(file.RemoteKey!) : new(file.Source == "amazon" ? bucket : arcoBucket, file.RemoteKey ?? file.Key);

    private string Target(RemoteEra5File file)
    {
        var candidate = Path.Combine(directory, file.Name);
        if (File.Exists(candidate) || !Directory.Exists(directory)) return candidate;
        return Directory.EnumerateFiles(directory, file.Name, SearchOption.AllDirectories)
            .FirstOrDefault(path => !Path.GetRelativePath(directory, path).Split(Path.DirectorySeparatorChar).Contains(".pending")) ?? candidate;
    }

    private object Snapshot(RemoteEra5File file)
    {
        if (jobs.TryGetValue(file.Key, out var resolved)) file = resolved.File;
        var path = Target(file);
        var existing = new FileInfo(path);
        jobs.TryGetValue(file.Key, out var job);
        var downloaded = Downloaded(file, existing);
        var partial = new FileInfo(Path.Combine(directory, file.Name + ".partial"));
        var state = downloaded ? "downloaded" : existing.Exists ? "conflict" : job is not null ? Volatile.Read(ref job.State) :
            partial.Exists || file.Source == "cds" && File.Exists(Path.Combine(directory, file.Name + ".cds-request.json")) ? "paused" : "available";
        var size = file.Bytes > 0 ? file.Bytes : downloaded ? existing.Length : 0;
        var received = downloaded ? size : job is not null ? Interlocked.Read(ref job.Received) : partial.Exists ? partial.Length : 0;
        return new { key = file.Key, name = file.Name, bytes = size, start_utc = file.Start, end_utc = file.End,
            estimated_bytes = file.Source == "cds" && size == 0 ? Interlocked.Read(ref estimatedCdsBytes) : 0,
            elapsed_seconds = job is null ? 0 : Math.Max(0, (int)(DateTime.UtcNow - job.StartedUtc).TotalSeconds),
            state, received_bytes = received, error = job?.Error, error_code = job?.ErrorCode, action_url = job?.ActionUrl,
            downloaded, format = file.Format, provider = file.Provider,
            source = file.Source, saved_bytes = downloaded ? existing.Length : (long?)null,
            local_id = existing.Exists ? ArchiveFiles.Id(path) : null };
    }

    public object Start(string key)
    {
        if (!known.TryGetValue(key, out var file)) throw new ArgumentException("Сначала откройте каталог выбранного периода.");
        lock (jobGate)
        {
            var target = new FileInfo(Target(file));
            if (target.Exists)
            {
                if (!Downloaded(file, target)) throw new IOException("Локальный файл отличается от выбранного источника. Он не будет перезаписан.");
                if (file.Source == "cds") ForgetCds(key);
                return Snapshot(file);
            }
            if (jobs.TryGetValue(key, out var running) && running.Task is { IsCompleted: false }) return Snapshot(file);
            if (file.Source == "cds" && !cds.Configured) throw new ArgumentException("Укажите API-токен Copernicus CDS в разделе загрузки.");
            if (jobs.Values.Count(job => job.Task is { IsCompleted: false }) >= 512) throw new IOException("В очереди уже 512 файлов. Дождитесь завершения загрузок.");
            Directory.CreateDirectory(directory);
            var reserved = jobs.Values.Where(job => job.Task is { IsCompleted: false })
                .Sum(job => Math.Max(0, job.File.Bytes - Interlocked.Read(ref job.Received)));
            var partial = new FileInfo(Path.Combine(directory, file.Name + ".partial"));
            var remaining = file.Bytes - (partial.Exists ? Math.Min(file.Bytes, partial.Length) : 0);
            if (new DriveInfo(Path.GetPathRoot(directory)!).AvailableFreeSpace < reserved + remaining + 512L * 1048576)
                throw new IOException("Недостаточно свободного места для очереди загрузок с резервом 512 MiB.");
            if (file.Source == "cds") { wantedCds.Add(key); SaveCdsQueue(); }
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
        if (job.File.Source == "cds") ForgetCds(key);
        job.Cancellation.Cancel();
        return Snapshot(job.File);
    }

    public void DeleteFile(string path, Action delete)
    {
        lock (jobGate)
        {
            var matches = jobs.Where(pair => string.Equals(Path.GetFullPath(Target(pair.Value.File)), Path.GetFullPath(path),
                OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal)).ToArray();
            if (matches.Any(pair => pair.Value.Task is { IsCompleted: false }))
                throw new IOException("Дождитесь завершения загрузки или остановите её перед удалением.");
            delete();
            foreach (var pair in matches)
                if (jobs.TryRemove(pair.Key, out var job)) job.Cancellation.Dispose();
        }
    }

    private async Task<HttpResponseMessage> StorageAsync(RemoteEra5File file, Uri url, long first, long last, CancellationToken token)
    {
        for (var redirects = 0; ; redirects++)
        {
            if (file.Source == "cds") cds.ValidateStorage(url);
            using var request = new HttpRequestMessage(HttpMethod.Get, url);
            request.Headers.Range = new RangeHeaderValue(first, last);
            if (file.Etag.Length > 0) request.Headers.IfMatch.ParseAdd(file.Etag);
            var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, token);
            if (file.Source == "cds" && (int)response.StatusCode is 301 or 302 or 303 or 307 or 308)
            {
                var location = response.Headers.Location;
                response.Dispose();
                if (redirects >= 4 || location is null) throw new IOException("Слишком много перенаправлений хранилища CDS.");
                url = new Uri(url, location);
                continue;
            }
            if (file.Source == "cds" && response.StatusCode is HttpStatusCode.Forbidden or HttpStatusCode.NotFound or HttpStatusCode.Gone)
            {
                response.Dispose();
                File.Delete(Path.Combine(directory, file.Name + ".cds-request.json"));
                throw new InvalidDataException("Результат CDS больше недоступен. Нажмите «Повторить» для нового запроса.");
            }
            return response;
        }
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
            if (file.Source == "cds")
            {
                file = await cds.ResolveAsync(file, directory, state => job.State = state, token);
                job.File = file;
                known[file.Key] = file;
            }
            job.State = "downloading";
            var url = Url(file);
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
            await File.WriteAllTextAsync(pinPath, JsonSerializer.Serialize(new { key = file.Key, url = url.AbsoluteUri, etag = file.Etag, bytes = file.Bytes }), token);
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
                            using var response = await StorageAsync(file, url, offset, last, token);
                            response.EnsureSuccessStatusCode();
                            if (file.Source == "cds" && response.StatusCode == HttpStatusCode.OK)
                            {
                                // Some CDS result stores ignore Range. Restart
                                // safely and stream the full immutable result.
                                if (response.Content.Headers.ContentLength != file.Bytes) throw new IOException("Неверный размер результата CDS.");
                                stream.Position = 0; stream.SetLength(0);
                                await using var full = await response.Content.ReadAsStreamAsync(token);
                                var block = new byte[65536];
                                while (stream.Position < file.Bytes)
                                {
                                    var count = (int)Math.Min(block.Length, file.Bytes - stream.Position);
                                    await full.ReadExactlyAsync(block.AsMemory(0, count), token);
                                    await stream.WriteAsync(block.AsMemory(0, count), token);
                                    Interlocked.Exchange(ref job.Received, stream.Position);
                                }
                                payload = [];
                                break;
                            }
                            var range = response.Content.Headers.ContentRange;
                            if (response.StatusCode != HttpStatusCode.PartialContent || range?.From != offset || range.To != last || range.Length != file.Bytes)
                                throw new IOException("Источник вернул неверный диапазон файла.");
                            if (response.Content.Headers.ContentLength != last - offset + 1) throw new IOException("Неверная длина блока источника.");
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
                    await stream.WriteAsync(payload ?? throw new IOException("Пустой блок источника."), token);
                    await stream.FlushAsync(token);
                    offset = stream.Position;
                    Interlocked.Exchange(ref job.Received, offset);
                }
            }
            job.State = "validating";
            lock (NativeNetCdf.Gate)
            {
                if (file.Source == "cds")
                {
                    // Keep the GRIB extension for GDAL validation while hiding
                    // the incomplete file from the map's archive scanner.
                    var staging = Path.Combine(directory, ".pending", "cds-" + Guid.NewGuid().ToString("N"));
                    Directory.CreateDirectory(staging);
                    var grib = Path.Combine(staging, file.Name);
                    try
                    {
                        File.Move(partial, grib);
                        var index = new Era5Index(grib, [-180, 180, -90, 90], 100_000, 256, 0);
                        if (index.Records.Count != 24 || index.Start != DateTimeOffset.Parse(file.Start, CultureInfo.InvariantCulture).ToUnixTimeSeconds() ||
                            index.End != DateTimeOffset.Parse(file.End, CultureInfo.InvariantCulture).ToUnixTimeSeconds())
                            throw new InvalidDataException("CDS: ожидаются все 24 почасовых поля LSP выбранных суток.");
                    }
                    finally
                    {
                        if (File.Exists(grib)) File.Move(grib, partial);
                        foreach (var auxiliary in Directory.EnumerateFiles(staging)) File.Delete(auxiliary);
                        Directory.Delete(staging);
                    }
                }
                else
                {
                    using var dataset = new NetCdfFile(partial);
                    if (file.Source == "google")
                    {
                        var variable = dataset.Variable("lsp");
                        if (dataset.Text(variable, "units") != "m" ||
                            dataset.Text(variable, "standard_name") != "lwe_thickness_of_stratiform_precipitation_amount" ||
                            !dataset.Dimensions(variable).Select(dimension => dimension.Name).SequenceEqual(new[] { "time", "latitude", "longitude" }))
                            throw new InvalidDataException("Загруженный файл не соответствует Google ARCO ERA5 LSP.");
                        var time = dataset.Axis("time");
                        if (time.Length != 24 || !time.Zip(time.Skip(1)).All(pair => pair.Second > pair.First))
                            throw new InvalidDataException("Ожидаются 24 последовательных часа Google ARCO.");
                    }
                    else
                    {
                        var variable = dataset.Variable("LSP");
                        if (dataset.Text(variable, "units") != "m" || dataset.Text(variable, "rda_dataset") != "ds633.0" ||
                            !dataset.Dimensions(variable).Select(dimension => dimension.Name).SequenceEqual(new[] { "forecast_initial_time", "forecast_hour", "latitude", "longitude" }))
                            throw new InvalidDataException("Загруженный файл не соответствует NCAR ERA5 LSP.");
                        var steps = dataset.Axis("forecast_hour");
                        if (!steps.SequenceEqual(Enumerable.Range(1, steps.Length).Select(value => (double)value)) || steps.Length is < 1 or > 12)
                            throw new InvalidDataException("Неверные почасовые шаги NCAR.");
                    }
                }
            }
            token.ThrowIfCancellationRequested();
            File.Move(partial, Path.Combine(directory, file.Name), overwrite: false);
            job.State = "downloaded";
            if (file.Source == "cds") ForgetCds(file.Key);
            changed();
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { job.State = "paused"; }
        catch (Exception error)
        {
            if (file.Source == "cds" && !shutdown.IsCancellationRequested) ForgetCds(file.Key);
            job.Error = file.Source == "cds" && error is HttpRequestException ? "Не удалось скачать результат CDS. Повторите загрузку." : error.Message;
            if (error is CdsAccessException access) { job.ErrorCode = access.Code; job.ActionUrl = access.ActionUrl; }
            job.State = "failed";
        }
        finally { if (entered) transfers.Release(); }
    }

    public void Dispose()
    {
        shutdown.Cancel();
        client.Dispose();
        cds.Dispose();
    }
}
