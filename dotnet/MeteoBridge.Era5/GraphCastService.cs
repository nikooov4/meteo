using System.Diagnostics;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace MeteoBridge.Era5;

internal sealed record GraphCastRequest(string Id);
internal sealed record GraphCastInput(string Id, string Name, string Archive, bool Compatible, string? Reason, long Bytes,
    bool Prepare = false, GraphCastPreparation? Preparation = null);

internal sealed class GraphCastService : IDisposable
{
    private const string Worker = "service.py";
    private readonly string archive, inputs, era5, logPath;
    private readonly GraphCastRuntime runtime;
    private readonly GraphCastArchiveInputs archiveInputs;
    private readonly ArchiveSession session;
    private readonly object gate = new();
    private readonly SemaphoreSlim generation = new(1);
    private readonly CancellationTokenSource lifetime = new();
    private Process? process;
    private TaskCompletionSource<JsonElement>? completion;
    private string state = "idle", message = "Модель будет загружена при первой генерации", job = "", inputName = "", activeInput = "";
    private bool loaded;
    private bool waitingForArchive;
    private int step, loads, disposed;
    private int? modelPid;
    private DateTimeOffset? started;
    private string? resultId;

    public GraphCastService(string root, string era5Data, string storage, GraphCastRuntime runtime,
        GraphCastArchiveInputs archiveInputs, ArchiveSession session)
    {
        this.runtime = runtime;
        archive = Path.Combine(storage, "graphcast");
        inputs = Path.Combine(storage, "graphcast-inputs");
        era5 = era5Data;
        this.archiveInputs = archiveInputs;
        this.session = session;
        logPath = Path.Combine(root, "artifacts", "logs", "graphcast.log");
        Directory.CreateDirectory(archive);
        Directory.CreateDirectory(inputs);
    }

    public object Status()
    {
        lock (gate) return new { state, message = waitingForArchive ? archiveInputs.View(new FileInfo(activeInput)).Message ?? message : message,
            model_loaded = loaded, model_load_count = loads,
            pid = process is { HasExited: false } ? modelPid : null, step, steps = 4, job_id = job,
            input_name = inputName, started_utc = started, result_id = resultId,
            runtime_available = runtime.Available(Worker), busy = generation.CurrentCount == 0 };
    }

    private IEnumerable<string> InputPaths() => Directory.GetFiles(inputs, "*.nc", SearchOption.TopDirectoryOnly)
        .Concat(Era5Index.Files(era5))
        .Concat(Directories().Select(directory => Path.Combine(directory, "forecast.nc"))).Distinct();

    private static GraphCastInput Describe(string path, string source)
    {
        var info = new FileInfo(path);
        string? reason = null;
        try
        {
            lock (NativeNetCdf.Gate)
            {
                using var file = new NetCdfFile(path);
                var required = new[] { "2m_temperature", "mean_sea_level_pressure", "10m_u_component_of_wind",
                    "10m_v_component_of_wind", "total_precipitation_6hr", "temperature", "geopotential",
                    "u_component_of_wind", "v_component_of_wind", "vertical_velocity", "specific_humidity",
                    "land_sea_mask", "geopotential_at_surface" };
                if (required.Any(name => !file.TryVariable(name, out _)))
                    reason = "Нужен полный набор полей GraphCast; одного LSP недостаточно";
                else if (!file.TryVariable("datetime", out _) && !file.TryVariable("valid_time", out _) &&
                         !file.TryVariable("time", out _)) reason = "Нет времени UTC";
                else
                {
                    var lat = file.TryVariable("lat", out _) ? "lat" : "latitude";
                    var lon = file.TryVariable("lon", out _) ? "lon" : "longitude";
                    var level = file.TryVariable("level", out _) ? "level" : "pressure_level";
                    if (file.Axis(lat).Length != 181 || file.Axis(lon).Length != 360 || file.Axis(level).Length < 13)
                        reason = "Нужна глобальная сетка 1° и 13 уровней атмосферы";
                }
            }
        }
        catch (Exception error) when (error is IOException or InvalidDataException or ApplicationException)
        { reason = "Не удалось прочитать NetCDF: " + error.Message; }
        var name = info.Name;
        if (source == "GrathCast")
            name = JsonSerializer.Deserialize<JsonElement>(File.ReadAllText(Path.Combine(info.DirectoryName!, "metadata.json"))).GetProperty("name").GetString() ?? name;
        return new GraphCastInput(ArchiveFiles.Id(path), name, source, reason is null, reason, info.Length);
    }

    private GraphCastInput DescribeInput(string path)
    {
        var source =
        path.StartsWith(archive + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase) ? "GrathCast" :
        path.StartsWith(inputs + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase) ? "Подготовленные входы" : "ERA5";
        var input = Path.GetExtension(path).Equals(".nc", StringComparison.OrdinalIgnoreCase) ? Describe(path, source)
            : new GraphCastInput(ArchiveFiles.Id(path), Path.GetFileName(path), source, false, null, new FileInfo(path).Length);
        if (source != "ERA5" || input.Compatible) return input;
        return input with { Prepare = true, Reason = "Нужно дополнить полями Google ARCO-ERA5" };
    }

    public object InputFiles()
    {
        var candidates = InputPaths().Select(DescribeInput).ToArray();
        if (!candidates.Any(input => input.Prepare)) return candidates;
        var index = session.ForViewer().Index;
        var hours = new Dictionary<string, (long First, long Last, int Count)>();
        var ids = index.Sources.ToDictionary(source => source.Path, source => ArchiveFiles.Id(source.Path));
        foreach (var (epoch, records) in index.Records)
        foreach (var path in records.Select(record => index.Cycles[record.Key].Source.Path).Distinct())
        {
            var id = ids[path];
            hours[id] = hours.TryGetValue(id, out var span)
                ? (Math.Min(span.First, epoch), Math.Max(span.Last, epoch), span.Count + 1) : (epoch, epoch, 1);
        }
        var sources = index.Sources.ToDictionary(source => ids[source.Path]);
        return candidates.Select(input => !input.Prepare ? input :
            hours.TryGetValue(input.Id, out var span) && span.Count == 24 && span.Last - span.First == 23 * 3600
                ? input with { Preparation = archiveInputs.View(new FileInfo(sources[input.Id].Path)) }
                : input with { Prepare = false, Reason = "Нужен архив на 24 непрерывных часа" }).ToArray();
    }

    public async Task<object> ImportAsync(HttpRequest request, CancellationToken cancellation)
    {
        var name = request.Query["name"].ToString();
        if (name != Path.GetFileName(name) || name.Length is < 1 or > 160 || name.Contains(':') ||
            !name.EndsWith(".nc", StringComparison.OrdinalIgnoreCase)) throw new ArgumentException("Выберите файл NetCDF (.nc).");
        if (request.ContentLength is <= 0 or > 2L * 1024 * 1024 * 1024) throw new ArgumentException("Нужен файл до 2 ГиБ.");
        var target = Path.Combine(inputs, Guid.NewGuid().ToString("N") + "-" + name);
        var temporary = target + ".partial";
        try
        {
            await using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                var buffer = new byte[1048576];
                long received = 0;
                int length;
                while ((length = await request.Body.ReadAsync(buffer, cancellation)) > 0)
                {
                    received += length;
                    if (received > 2L * 1024 * 1024 * 1024) throw new ArgumentException("Файл превышает 2 ГиБ.");
                    await output.WriteAsync(buffer.AsMemory(0, length), cancellation);
                }
                if (received == 0) throw new ArgumentException("Файл пуст.");
            }
            var description = Describe(temporary, "Подготовленные входы");
            if (!description.Compatible) throw new ArgumentException(description.Reason);
            File.Move(temporary, target);
            return Describe(target, "Подготовленные входы");
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }

    private string[] Directories() => Directory.GetDirectories(archive).Where(path =>
        Regex.IsMatch(Path.GetFileName(path), "^[a-f0-9]{32}$") && File.Exists(Path.Combine(path, "metadata.json"))).ToArray();

    private string Find(string id)
    {
        if (!Regex.IsMatch(id ?? "", "^[a-f0-9]{32}$")) throw new ArgumentException("Неверный идентификатор GrathCast.");
        return Directories().SingleOrDefault(path => Path.GetFileName(path) == id)
            ?? throw new ArgumentException("Файл GrathCast не найден. Обновите архив.");
    }

    public JsonElement Metadata(string id) => JsonSerializer.Deserialize<JsonElement>(File.ReadAllText(Path.Combine(Find(id), "metadata.json")));
    public object[] Files(int year = 0, int month = 0) => Directories().Select(path =>
    {
        var metadata = Metadata(Path.GetFileName(path));
        var date = DateTimeOffset.Parse(metadata.GetProperty("start_utc").GetString()!);
        return (metadata, date);
    }).Where(item => (year == 0 || item.date.Year == year) && (month == 0 || item.date.Month == month))
        .OrderByDescending(item => item.date).Select(item => (object)new
        {
            id = item.metadata.GetProperty("id").GetString(), local_id = item.metadata.GetProperty("id").GetString(),
            name = item.metadata.GetProperty("name").GetString(), bytes = item.metadata.GetProperty("bytes").GetInt64(),
            start_utc = item.metadata.GetProperty("start_utc").GetString(), end_utc = item.metadata.GetProperty("end_utc").GetString(),
            format = "NetCDF", provider = "GrathCast", source = "graphcast", downloaded = true, state = "available"
        }).ToArray();

    public object Delete(string id)
    {
        lock (gate)
        {
            var directory = Find(id);
            if (activeInput == Path.Combine(directory, "forecast.nc")) throw new ArgumentException("Этот файл используется текущей генерацией.");
            if (new DirectoryInfo(directory).LinkTarget is not null) throw new IOException("Архив не должен быть символической ссылкой.");
            // Delete only the three known products inside the validated UUID directory.
            foreach (var name in new[] { "forecast.nc", "frames.bin", "metadata.json" }) File.Delete(Path.Combine(directory, name));
            Directory.Delete(directory);
            if (resultId == id) { resultId = null; state = "idle"; message = "Прогноз удалён. Модель готова к генерации"; }
            return new { deleted = true, id };
        }
    }

    public object DeleteArchive(string id, Func<object> delete)
    {
        lock (gate)
        {
            if (activeInput.Length != 0 && ArchiveFiles.Id(activeInput) == id)
                throw new ArgumentException("Этот архив используется текущей генерацией.");
            return delete();
        }
    }
    public string Download(string id) => Path.Combine(Find(id), "forecast.nc");
    public byte[] Frame(string id, int index)
    {
        if (index is < 0 or > 3) throw new ArgumentException("Кадр GrathCast: 0..3.");
        var path = Path.Combine(Find(id), "frames.bin");
        const int bytes = 181 * 360 * 4;
        using var stream = File.OpenRead(path);
        if (stream.Length != bytes * 4L) throw new InvalidDataException("Повреждены кадры GrathCast.");
        stream.Position = index * bytes;
        var result = new byte[bytes];
        stream.ReadExactly(result);
        return result;
    }

    public object Start(string id)
    {
        var path = InputPaths().SingleOrDefault(path => ArchiveFiles.Id(path) == id)
            ?? throw new ArgumentException("Входной файл не найден.");
        var description = DescribeInput(path);
        if (!description.Compatible && !description.Prepare) throw new ArgumentException(description.Reason);
        if (description.Prepare) archiveInputs.CheckAvailability(path);
        if (!runtime.Available(Worker)) throw new ArgumentException("Не подготовлено окружение GrathCast. Выполните scripts/setup_graphcast.ps1.");
        lock (gate)
        {
            if (!File.Exists(path)) throw new ArgumentException("Входной файл не найден.");
            if (!generation.Wait(0)) throw new ArgumentException("Генерация уже выполняется. Дождитесь завершения.");
            job = Guid.NewGuid().ToString("N"); state = "queued"; message = "Подготовка генерации";
            inputName = description.Name; activeInput = path; step = 0; resultId = null; started = DateTimeOffset.UtcNow;
        }
        _ = Task.Run(() => GenerateAsync(path, job, description.Prepare));
        return Status();
    }

    private async Task GenerateAsync(string input, string id, bool prepare)
    {
        var staging = Path.Combine(archive, ".pending", id);
        try
        {
            var modelInput = input;
            if (prepare)
            {
                lock (gate)
                {
                    waitingForArchive = true;
                    state = "preparing";
                    message = "Подготовка входа из архива ERA5";
                }
                try { modelInput = await archiveInputs.GetOrPrepareAsync(input, lifetime.Token); }
                finally { lock (gate) waitingForArchive = false; }
            }
            completion = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
            EnsureWorker();
            await process!.StandardInput.WriteLineAsync(JsonSerializer.Serialize(new
            { id, input = modelInput, source_name = Path.GetFileName(input), output = staging }));
            await process.StandardInput.FlushAsync();
            await completion.Task.WaitAsync(TimeSpan.FromMinutes(20), lifetime.Token);
            if (!File.Exists(Path.Combine(staging, "forecast.nc")) || !File.Exists(Path.Combine(staging, "frames.bin")))
                throw new IOException("Модель не сохранила результат.");
            Directory.Move(staging, Path.Combine(archive, id));
            lock (gate) { state = "completed"; message = "Прогноз сохранён в архив GrathCast"; resultId = id; }
        }
        catch (Exception error)
        {
            lock (gate) { state = "error"; message = error.Message; }
            if (error is TimeoutException) StopWorker();
        }
        finally
        {
            try
            {
                if (Directory.Exists(staging))
                {
                    foreach (var name in new[] { "forecast.nc", "frames.bin", "metadata.json" })
                        File.Delete(Path.Combine(staging, name));
                    if (!Directory.EnumerateFileSystemEntries(staging).Any()) Directory.Delete(staging);
                }
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
            finally { lock (gate) activeInput = ""; generation.Release(); }
        }
    }

    private void EnsureWorker()
    {
        lock (gate)
        {
            if (process is { HasExited: false }) return;
            loaded = false;
            var start = runtime.Command(Worker);
            start.ArgumentList.Add("--parent"); start.ArgumentList.Add(Environment.ProcessId.ToString());
            process = Process.Start(start) ?? throw new IOException("Не удалось запустить GrathCast.");
            var worker = process;
            _ = Task.Run(async () =>
            {
                try
                {
                    while (await worker.StandardOutput.ReadLineAsync() is { } line)
                    {
                        JsonElement update;
                        try { update = JsonSerializer.Deserialize<JsonElement>(line); }
                        catch (JsonException) { continue; }
                        lock (gate)
                        {
                            if (!ReferenceEquals(process, worker)) continue;
                            var kind = update.GetProperty("event").GetString();
                            if (update.TryGetProperty("pid", out var pid)) modelPid = pid.GetInt32();
                            if (update.TryGetProperty("model_loaded", out var ready)) loaded = ready.GetBoolean();
                            if (update.TryGetProperty("model_load_count", out var count)) loads = count.GetInt32();
                            if (update.TryGetProperty("message", out var text)) message = text.GetString() ?? "";
                            if (kind is "loading" or "preparing" or "generating") state = kind;
                            if (kind == "step") { step = update.GetProperty("step").GetInt32(); message = $"Рассчитано +{step * 6} часов"; }
                            if (kind == "completed") completion?.TrySetResult(update.GetProperty("metadata").Clone());
                            if (kind == "error") completion?.TrySetException(new IOException(update.GetProperty("error").GetString()));
                        }
                    }
                }
                finally
                {
                    lock (gate)
                    {
                        if (ReferenceEquals(process, worker))
                        {
                            loaded = false;
                            completion?.TrySetException(new IOException("Процесс GrathCast завершился. Повторите генерацию."));
                        }
                    }
                }
            });
            _ = Task.Run(async () =>
            {
                Directory.CreateDirectory(Path.GetDirectoryName(logPath)!);
                while (await worker.StandardError.ReadLineAsync() is { } line)
                    await File.AppendAllTextAsync(logPath, line + Environment.NewLine);
            });
        }
    }
    private void StopWorker()
    {
        lock (gate)
        {
            if (process is { HasExited: false }) process.Kill(true);
            loaded = false;
        }
    }
    public void Dispose()
    {
        if (Interlocked.Exchange(ref disposed, 1) != 0) return;
        lifetime.Cancel(); StopWorker();
    }
}
