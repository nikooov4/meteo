using MeteoBridge.Era5;

static string FindRoot(string[] arguments)
{
    var position = Array.IndexOf(arguments, "--root");
    if (position >= 0 && position + 1 < arguments.Length) return Path.GetFullPath(arguments[position + 1]);
    foreach (var start in new[] { AppContext.BaseDirectory, Directory.GetCurrentDirectory() })
    {
        var directory = new DirectoryInfo(start);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "MeteoBridge.sln"))) return directory.FullName;
            directory = directory.Parent;
        }
    }
    throw new DirectoryNotFoundException("Не найден корень MeteoBridge. Передайте --root PATH.");
}

var root = FindRoot(args);
NativeNetCdf.Initialize(root);
if (args.Contains("--worker"))
{
    await WorkerProtocol.RunAsync();
    return;
}

await LocalWebHost.RunAsync(address => CreateApplication(args, root, address));

static WebApplication CreateApplication(string[] arguments, string root, string? address)
{
    var builder = WebApplication.CreateBuilder(new WebApplicationOptions { Args = arguments, ContentRootPath = AppContext.BaseDirectory });
    builder.WebHost.ConfigureKestrel(options => options.Limits.MaxRequestBodySize = ArchiveImports.MaxBytes);
    if (builder.Configuration["urls"] is null) builder.WebHost.UseUrls("http://127.0.0.1:8766");
    if (address is not null) builder.WebHost.UseUrls(address);
    builder.Logging.AddFilter("Microsoft.Extensions.Hosting.Internal.Host", LogLevel.Critical);
    var settings = builder.Configuration.GetSection("Era5");
    var workers = settings.GetValue("Workers", 2);
    var lookahead = settings.GetValue("LookaheadCycles", 3);
    var capacity = settings.GetValue("CacheCycles", 6);
    var maxCells = settings.GetValue("MaxCells", 100_000);
    var maxReadMiB = settings.GetValue("MaxReadMiB", 256);
    if (workers is < 1 or > 4 || lookahead is < 0 or > 6 || capacity < lookahead + 1 || capacity > 12 || maxReadMiB is < 1 or > 1024)
        throw new ArgumentException("Workers: 1..4, LookaheadCycles: 0..6, CacheCycles: LookaheadCycles+1..12, MaxReadMiB: 1..1024.");
    var data = Path.GetFullPath(settings["Data"] ?? "data/era5", root);
    var bbox = settings.GetSection("Bbox").Get<double[]>() ?? [-180, 180, -90, 90];
    builder.Services.AddSingleton(_ => new ArchiveSession(data, bbox, maxCells, maxReadMiB, lookahead, root, workers, capacity));
    builder.Services.AddSingleton(provider => new ArchiveDownloads(data, settings["ArchiveBaseUrl"], provider.GetRequiredService<ArchiveSession>().Changed,
        settings["ArcoBaseUrl"], settings["CdsBaseUrl"], settings["CdsToken"]));
    builder.Services.AddSingleton(provider => new ArchiveImports(data, bbox, maxCells, maxReadMiB, lookahead, provider.GetRequiredService<ArchiveSession>().Changed));
    builder.Services.AddSingleton(provider => new ArchiveFiles(data, provider.GetRequiredService<ArchiveSession>(), provider.GetRequiredService<ArchiveDownloads>()));
    var app = builder.Build();
    var session = app.Services.GetRequiredService<ArchiveSession>();
    var downloads = app.Services.GetRequiredService<ArchiveDownloads>();
    var imports = app.Services.GetRequiredService<ArchiveImports>();
    var localFiles = app.Services.GetRequiredService<ArchiveFiles>();
    var priorities = new MapPriorities(data);
    app.Use(async (context, next) =>
    {
        if (context.Connection.RemoteIpAddress is not { } remote || !System.Net.IPAddress.IsLoopback(remote))
        {
            context.Response.StatusCode = 403;
            return;
        }
        if (HttpMethods.IsPost(context.Request.Method) && context.Request.Headers.Origin is { Count: > 0 } origins &&
            (!Uri.TryCreate(origins[0], UriKind.Absolute, out var origin) || origin.Authority != context.Request.Host.Value))
        {
            context.Response.StatusCode = 403;
            return;
        }
        try { await next(context); }
        catch (OperationCanceledException) when (context.RequestAborted.IsCancellationRequested) { }
        catch (Exception error) when (error is ArgumentException or IOException or InvalidDataException or FormatException or OverflowException or DllNotFoundException or ApplicationException)
        {
            context.Response.StatusCode = 422;
            await context.Response.WriteAsJsonAsync(new { detail = error.Message });
        }
        catch (HttpRequestException error)
        {
        app.Logger.LogWarning(error, "Не удалось получить данные архива");
            context.Response.StatusCode = 502;
            await context.Response.WriteAsJsonAsync(new { detail = "Не удалось получить данные архива: " + error.Message });
        }
        catch (TaskCanceledException)
        {
            context.Response.StatusCode = 504;
            await context.Response.WriteAsJsonAsync(new { detail = "Источник не ответил вовремя. Повторите запрос." });
        }
    });
    app.MapGet("/health", () => new { status = "ok", engine = "csharp", application = "MeteoBridge.Era5",
        project_root = root, data_path = data, workers, lookahead_cycles = lookahead });
    app.MapGet("/", () =>
    {
        var files = Era5Index.Files(data).Length > 0;
        return files ? Results.Content(MapPage.Create(session.ForViewer().Index), "text/html; charset=utf-8") : Results.Redirect("/downloads");
    });
    app.MapGet("/downloads", async (HttpContext context) =>
    {
        // Read the current workspace template in development; standalone
        // deployments keep using the bundled copy. Do not cache HTML screens.
        var source = Path.Combine(root, "web", "archive_viewer.html");
        var path = File.Exists(source) ? source : Path.Combine(AppContext.BaseDirectory, "Assets", "archive_viewer.html");
        context.Response.Headers.CacheControl = "no-store";
        return Results.Content(await File.ReadAllTextAsync(path, context.RequestAborted), "text/html; charset=utf-8");
    });
    app.MapGet("/api/archive/settings", () => downloads.Settings());
    app.MapPost("/api/archive/cds-token", (CdsCredentials credentials) => downloads.ConfigureCds(credentials.Token));
    app.MapGet("/api/archive/local", () => localFiles.List());
    app.MapPost("/api/archive/delete", (DeleteFileRequest request) => localFiles.Delete(request.Id));
    app.MapPost("/api/archive/import", async (HttpRequest request, CancellationToken cancellation) =>
        Results.Json(await imports.ImportAsync(request, cancellation)));
    app.MapGet("/api/archive/files", async (HttpContext context, int year, int month = 0, string source = "amazon") =>
        await downloads.FilesAsync(year, month, context.RequestAborted, source));
    app.MapPost("/api/archive/download", (DownloadRequest request) => downloads.Start(request.Key));
    app.MapPost("/api/archive/cancel", (DownloadRequest request) => downloads.Cancel(request.Key));
    app.MapGet("/grid", () => new { latitude = session.Current.Index.Latitude, longitude = session.Current.Index.Longitude });
    app.MapGet("/land.json", () => Results.File(Path.Combine(AppContext.BaseDirectory, "Assets", "land.json"), "application/json"));
    app.MapGet("/plotly.min.js", () =>
    {
        var path = Environment.GetEnvironmentVariable("METEOBRIDGE_PLOTLY_JS")
            ?? new[] { Path.Combine(AppContext.BaseDirectory, "Assets", "plotly.min.js"),
                       Path.Combine(root, "runtime", "plotly", "plotly.min.js") }.FirstOrDefault(File.Exists);
        return File.Exists(path) ? Results.File(path, "text/javascript")
            : Results.Problem("Не найден Plotly: выполните scripts/setup_runtime.ps1 или задайте METEOBRIDGE_PLOTLY_JS.", statusCode: 503);
    });
    app.MapGet("/map-archive/catalog", () => session.Current.Index.Catalog());
    app.MapGet("/map-archive/priority", (HttpContext context) =>
    {
        context.Response.Headers.CacheControl = "no-store";
        return priorities.View();
    });
    app.MapPost("/map-archive/priority", (MapPriorityRequest request) =>
    {
        session.ChangeFiles(() => priorities.Save(request.Order));
        return new { priority = priorities.View(), catalog = session.Current.Index.Catalog() };
    });
    app.MapGet("/map-archive/range", (string start, string end, int member = 0) => session.Current.Index.Selection(member, start, end));
    app.MapGet("/map-archive/metrics", () => session.Current.Pipeline.Metrics());
    app.MapGet("/map-archive/prefetch", (int hour, int end_hour, string manifest_sha256) =>
    {
        var view = session.Current;
        if (manifest_sha256 != view.Index.Sha) return Results.Conflict(new { detail = "Архив изменился." });
        view.Pipeline.Prepare(hour, end_hour);
        return Results.Ok(new { status = "preparing" });
    });
    app.MapGet("/map-archive/frame", async (HttpContext context, int hour, string manifest_sha256, int member = 0, int? end_hour = null, bool prefetch = false) =>
    {
        var view = session.Current;
        var current = view.Index;
        if (manifest_sha256 != current.Sha) return Results.Conflict(new { detail = "Архив изменился. Перестройте карту." });
        if (member != 0) throw new ArgumentException("У ERA5 нет синтетических сценариев.");
        var frame = await view.Pipeline.FrameAsync(hour, end_hour ?? current.Hours, prefetch, context.RequestAborted);
        context.Response.Headers["X-Frame-Start"] = Era5Index.Iso(current.Start + hour * 3600L);
        context.Response.Headers["X-Data-Available"] = frame.Available ? "true" : "false";
        context.Response.Headers["X-Cycle-UTC"] = frame.Cycle is { } cycle ? Era5Index.Iso(cycle) : "";
        context.Response.Headers["X-Frame-Sources"] = Uri.EscapeDataString(System.Text.Json.JsonSerializer.Serialize(frame.Sources));
        context.Response.Headers["X-Manifest-SHA256"] = current.Sha;
        context.Response.Headers.CacheControl = "no-store";
        return Results.Bytes(frame.Bytes, "application/octet-stream");
    });
    return app;
}
