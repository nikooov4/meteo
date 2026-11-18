using System.Diagnostics;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace MeteoBridge.Era5;

internal sealed record GraphCastPreparation(string State, string? Message = null)
{
    public static GraphCastPreparation Ready { get; } = new("ready");
}

internal sealed class GraphCastArchiveInputs(string root, string era5, string inputs, string? arcoUrl, GraphCastRuntime runtime) : IAsyncDisposable
{
    private sealed class Job(SourceFile source, CancellationToken cancellation)
    {
        public SourceFile Source { get; } = source;
        public CancellationTokenSource Cancellation { get; } = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        public volatile GraphCastPreparation Progress = new("queued", "Подготовка для ИИ в очереди");
        public Task<string?> Task { get; set; } = null!;
        public bool Finished { get; set; }
    }

    private const string Converter = "archive_input.py";
    private const string ArcoDefaultUrl = "https://storage.googleapis.com/gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3";
    private const string RuntimeRequired = "Подготовьте окружение и статические поля GrathCast через scripts/setup_graphcast.ps1.";
    private readonly string arcoFields = ValidateArcoUrl(arcoUrl);
    private readonly string cache = Path.Combine(inputs, ".era5");
    private readonly string staticFields = Path.Combine(inputs, "era5-example-2022-01-01.nc");
    private readonly CancellationTokenSource shutdown = new();
    private readonly SemaphoreSlim processing = new(1);
    private readonly Dictionary<string, Job> jobs = [];
    private readonly object gate = new();
    private bool stopping;

    private GraphCastPreparation Availability() =>
        !runtime.Available(Converter) || !File.Exists(staticFields) ? new("runtime_required", RuntimeRequired) : new("available");

    private static string ValidateArcoUrl(string? configured)
    {
        var url = new Uri((configured ?? ArcoDefaultUrl).TrimEnd('/'));
        if (url.AbsoluteUri != ArcoDefaultUrl && !(url.Scheme == "http" && url.IsLoopback &&
            url.UserInfo.Length == 0 && url.Query.Length == 0 && url.Fragment.Length == 0))
            throw new ArgumentException("Нужен официальный Google ARCO-ERA5 или loopback test server.");
        return url.AbsoluteUri;
    }

    private static string Revision(SourceFile source) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(
        FormattableString.Invariant($"1/{source.Bytes}/{source.ModifiedTicks}/{source.MetadataHash}"))))[..32];
    private string Entry(string id) => Path.Combine(cache, id);
    private string Prepared(SourceFile source) => Path.Combine(Entry(ArchiveFiles.Id(source.Path)), Revision(source) + ".nc");
    private static string Pending(string entry) => Path.Combine(entry, "pending");
    private string Find(string id) => Era5Index.Files(era5).SingleOrDefault(path => ArchiveFiles.Id(path) == id)
        ?? throw new ArgumentException("Файл ERA5 не найден. Обновите архив.");

    public GraphCastPreparation View(FileInfo file)
    {
        lock (gate)
        {
            if (!file.Exists) return new("available");
            try { return View(SourceFile.Snapshot(file)); }
            catch (IOException error) { return new("failed", error.Message); }
            catch (UnauthorizedAccessException error) { return new("failed", error.Message); }
        }
    }

    private GraphCastPreparation View(SourceFile source)
    {
        if (File.Exists(Prepared(source))) return GraphCastPreparation.Ready;
        if (!jobs.TryGetValue(ArchiveFiles.Id(source.Path), out var job) || job.Source != source)
            return Availability();
        var progress = job.Progress;
        if (progress.State != "queued") return progress;
        var active = jobs.Values.FirstOrDefault(other => other != job && other.Progress.State is "preparing" or "downloading");
        return active is null ? progress : progress with
        {
            Message = $"Подготовка для ИИ в очереди. Сейчас обрабатывается {Path.GetFileName(active.Source.Path)}"
        };
    }

    public void ScheduleDownloaded(string path)
    {
        try
        {
            lock (gate)
                if (!stopping) Enqueue(SourceFile.Snapshot(new FileInfo(path)), allowDeferred: true);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            // Saving an input for the model is independent of the completed archive download.
            Trace.TraceWarning("GraphCast preparation could not be queued: {0}", error.Message);
        }
    }

    public GraphCastPreparation Start(string id)
    {
        var source = SourceFile.Snapshot(new FileInfo(Find(id)));
        lock (gate)
        {
            Enqueue(source);
            return View(source);
        }
    }

    public void CheckAvailability(string path)
    {
        var source = SourceFile.Snapshot(new FileInfo(path));
        lock (gate)
        {
            if (File.Exists(Prepared(source)) ||
                jobs.TryGetValue(ArchiveFiles.Id(path), out var job) && job.Source == source && !job.Finished) return;
            var availability = Availability();
            if (availability.State != "available") throw new ArgumentException(availability.Message);
        }
    }

    public async Task<string> GetOrPrepareAsync(string path, CancellationToken cancellation)
    {
        var source = SourceFile.Snapshot(new FileInfo(path));
        Job? job;
        lock (gate) job = Enqueue(source);
        if (job is null) return Prepared(source);
        return await job.Task.WaitAsync(cancellation)
            ?? throw new IOException(job.Progress.Message ?? "Не удалось подготовить данные для GrathCast.");
    }

    private Job? Enqueue(SourceFile source, bool allowDeferred = false)
    {
        if (stopping) throw new OperationCanceledException("Приложение завершает работу.");
        var id = ArchiveFiles.Id(source.Path);
        if (File.Exists(Prepared(source))) return null;
        if (jobs.TryGetValue(id, out var existing) && !existing.Finished)
        {
            if (source != existing.Source) throw new IOException("Архив ERA5 изменился во время подготовки. Остановите подготовку и повторите.");
            return existing;
        }
        var availability = Availability();
        if (availability.State != "available" && !allowDeferred) throw new ArgumentException(availability.Message);
        var entry = Entry(id);
        Directory.CreateDirectory(entry);
        var pending = Pending(entry);
        File.WriteAllText(pending + ".tmp", Revision(source));
        File.Move(pending + ".tmp", pending, true);
        if (availability.State != "available") { jobs.Remove(id); return null; }
        var job = new Job(source, shutdown.Token);
        jobs[id] = job;
        job.Task = Task.Run(() => PrepareAsync(job, entry, pending));
        return job;
    }

    public void Resume()
    {
        if (Availability().State != "available" || !Directory.Exists(cache)) return;
        var entries = Directory.EnumerateDirectories(cache).Where(entry => File.Exists(Pending(entry))).ToArray();
        if (entries.Length == 0) return;
        var files = Era5Index.Files(era5).ToDictionary(ArchiveFiles.Id);
        lock (gate)
        foreach (var entry in entries)
        {
            try
            {
                var pending = Pending(entry);
                if (!File.Exists(pending)) continue;
                if (files.TryGetValue(Path.GetFileName(entry), out var path))
                {
                    var source = SourceFile.Snapshot(new FileInfo(path));
                    if (File.ReadAllText(pending) == Revision(source) && !File.Exists(Prepared(source)))
                    {
                        Enqueue(source);
                        continue;
                    }
                }
                File.Delete(pending);
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException)
            {
                Trace.TraceWarning("GraphCast preparation could not be resumed: {0}", error.Message);
            }
        }
    }

    public GraphCastPreparation Cancel(string id)
    {
        var source = SourceFile.Snapshot(new FileInfo(Find(id)));
        lock (gate)
        {
            if (File.Exists(Prepared(source))) return GraphCastPreparation.Ready;
            var pending = Pending(Entry(id));
            if (File.Exists(pending)) File.Delete(pending);
            if (!jobs.TryGetValue(id, out var job) || job.Finished) return Availability();
            job.Progress = new("stopping", "Останавливаю подготовку для ИИ");
            job.Cancellation.Cancel();
            return job.Progress;
        }
    }

    public void DeleteFile(string path, Action delete)
    {
        var id = ArchiveFiles.Id(path);
        lock (gate)
        {
            if (jobs.TryGetValue(id, out var job) && !job.Finished)
                throw new IOException("Остановите подготовку для ИИ перед удалением файла.");
            delete();
            jobs.Remove(id);
            Cleanup(Entry(id));
        }
    }

    internal static Era5Index OpenArchiveDay(string input)
    {
        lock (NativeNetCdf.Gate)
        {
            var grid = new PlaybackGrid(Enumerable.Range(-90, 181).Select(value => (double)value).ToArray(),
                Enumerable.Range(-180, 360).Select(value => (double)value).ToArray());
            var index = new Era5Index(input, [-180, 180, -90, 90], 100_000, 256, 0, grid);
            if (index.Hours != 24 || index.Records.Count != 24)
                throw new InvalidDataException("Выберите архив с 24 непрерывными часами данных.");
            return index;
        }
    }

    private async Task<string?> PrepareAsync(Job job, string entry, string pending)
    {
        var work = Path.Combine(entry, ".work-" + Revision(job.Source));
        var cancellation = job.Cancellation.Token;
        var entered = false;
        var cleanWork = false;
        try
        {
            await processing.WaitAsync(cancellation);
            entered = true;
            job.Progress = new("preparing", "Читаются осадки выбранного архива ERA5");
            job.Source.Validate();
            var index = OpenArchiveDay(job.Source.Path);
            Directory.CreateDirectory(work);
            var rain = Path.Combine(work, "lsp.bin");
            using (var pipeline = new CyclePipeline(index, root, 1, 2))
            await using (var stream = File.Create(rain))
            {
                foreach (var start in new[] { index.End - 43200, index.End - 21600 })
                {
                    var values = await ArchiveComparison.AccumulateAsync(start, index, pipeline, cancellation);
                    if (values.Any(value => !float.IsFinite(value)))
                        throw new InvalidDataException("Для ИИ нужен суточный архив LSP с глобальным покрытием без пропусков в последние 12 часов.");
                    var bytes = new byte[values.Length * sizeof(float)];
                    Buffer.BlockCopy(values, 0, bytes, 0, bytes.Length);
                    await stream.WriteAsync(bytes, cancellation);
                }
            }
            var reference = DateTimeOffset.FromUnixTimeSeconds(index.End);
            job.Progress = new("downloading", "Открывается каталог Google ARCO-ERA5");
            var output = Path.Combine(work, "input.nc");
            await ConvertAsync(job, new { arco_url = arcoFields, reference = reference.ToString("yyyy-MM-ddTHH:mm:ss", CultureInfo.InvariantCulture),
                static_fields = staticFields, archive_rain = rain, output }, cancellation);
            cleanWork = true;
            var prepared = Prepared(job.Source);
            lock (gate)
            {
                cancellation.ThrowIfCancellationRequested();
                job.Source.Validate();
                File.Move(output, prepared, true);
                job.Progress = GraphCastPreparation.Ready;
            }
            return prepared;
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested)
        {
            job.Progress = new("paused", "Подготовка для ИИ остановлена");
            return null;
        }
        catch (Exception error)
        {
            job.Progress = new("failed", error.Message);
            return null;
        }
        finally
        {
            if (cleanWork) Cleanup(work);
            lock (gate)
            {
                if (!shutdown.IsCancellationRequested)
                {
                    try { File.Delete(pending); }
                    catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
                }
                if (entered) processing.Release();
                job.Cancellation.Dispose();
                job.Finished = true;
            }
        }
    }

    private async Task ConvertAsync(Job job, object request, CancellationToken cancellation)
    {
        using var process = Process.Start(runtime.Command(Converter)) ?? throw new IOException("Не удалось запустить подготовку GrathCast.");
        var output = ReadProgressAsync();
        var errors = process.StandardError.ReadToEndAsync();
        try
        {
            await process.StandardInput.WriteLineAsync(JsonSerializer.Serialize(request).AsMemory(), cancellation);
            process.StandardInput.Close();
            await process.WaitForExitAsync(cancellation);
            if (process.ExitCode != 0) throw new InvalidDataException("Подготовка NetCDF для ИИ: " + (await errors).Trim());
        }
        finally
        {
            if (!process.HasExited) process.Kill(entireProcessTree: true);
            await process.WaitForExitAsync(CancellationToken.None);
            await Task.WhenAll(output, errors);
        }

        async Task ReadProgressAsync()
        {
            while (await process.StandardOutput.ReadLineAsync() is { } line)
            {
                var progress = JsonSerializer.Deserialize<GraphCastPreparation>(line, JsonSerializerOptions.Web);
                if (progress is not null && !cancellation.IsCancellationRequested) job.Progress = progress;
            }
        }
    }

    private static void Cleanup(string path)
    {
        try { if (Directory.Exists(path)) Directory.Delete(path, true); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
    }

    public async ValueTask DisposeAsync()
    {
        Task[] active;
        lock (gate)
        {
            stopping = true;
            shutdown.Cancel();
            active = jobs.Values.Select(job => job.Task).ToArray();
        }
        await Task.WhenAll(active);
        processing.Dispose();
        shutdown.Dispose();
    }
}
