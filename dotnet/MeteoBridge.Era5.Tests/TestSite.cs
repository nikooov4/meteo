using System.Diagnostics;
using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.Extensions.Logging;

namespace MeteoBridge.Era5.Tests;

internal sealed class TestDirectory : IDisposable
{
    public static readonly string Root = FindRoot();
    public string Path { get; } = Directory.CreateTempSubdirectory("meteo-xunit-").FullName;

    public string At(params string[] parts) => System.IO.Path.Combine([Path, .. parts]);

    private static string FindRoot()
    {
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
            if (File.Exists(System.IO.Path.Combine(directory.FullName, "MeteoBridge.sln"))) return directory.FullName;
        throw new DirectoryNotFoundException("MeteoBridge.sln");
    }

    public void Dispose()
    {
        for (var attempt = 0; ; attempt++)
        {
            try { Directory.Delete(Path, true); return; }
            catch (Exception error) when (attempt < 30 && error is (IOException or UnauthorizedAccessException))
            { Thread.Sleep(50); }
        }
    }
}

internal sealed class TestSite : IAsyncDisposable
{
    private readonly Process process;
    public HttpClient Client { get; }
    public const string MainCatalog = "/map-playback/all/catalog";
    public const string Priority = "/map-archive/priority";
    private TestSite(Process process, Uri address)
    {
        this.process = process;
        Client = new HttpClient(new SocketsHttpHandler { AllowAutoRedirect = false, UseProxy = false })
            { BaseAddress = address, Timeout = TimeSpan.FromSeconds(60) };
    }

    public static string Binary =>
        Path.Combine(TestDirectory.Root, "dotnet", "MeteoBridge.Era5", "bin",
            new DirectoryInfo(AppContext.BaseDirectory).Parent!.Name, "net10.0", "MeteoBridge.Era5.dll");

    public static async Task<TestSite> StartAsync(TestDirectory folder, string[]? options = null, string? binary = null, string? root = null)
    {
        var start = new ProcessStartInfo("dotnet")
        {
            UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
            WorkingDirectory = root ?? TestDirectory.Root, StandardOutputEncoding = System.Text.Encoding.UTF8
        };
        foreach (var argument in new[] { binary ?? Binary, "--root", root ?? TestDirectory.Root,
            "--urls", "http://127.0.0.1:0", "--Era5:Data", folder.At("era5"), "--GraphCast:Data", folder.At("products"),
            "--Logging:LogLevel:Default", "Warning" }.Concat(options ?? []))
            start.ArgumentList.Add(argument);
        var process = Process.Start(start) ?? throw new InvalidOperationException("Could not run MeteoBridge.");
        var stderr = process.StandardError.ReadToEndAsync();
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
            while (await process.StandardOutput.ReadLineAsync(timeout.Token) is { } line)
            {
                const string prefix = "MeteoBridge: ";
                if (!line.StartsWith(prefix, StringComparison.Ordinal)) continue;
                _ = process.StandardOutput.ReadToEndAsync();
                return new TestSite(process, new Uri(line[prefix.Length..]));
            }
            throw new InvalidOperationException(await stderr);
        }
        catch
        {
            if (!process.HasExited) process.Kill(entireProcessTree: true);
            await process.WaitForExitAsync();
            process.Dispose();
            throw;
        }
    }

    public async Task<JsonElement> Get(string path) => (await Client.GetFromJsonAsync<JsonElement>(path));

    public async Task<JsonElement> Post(string path, object value)
    {
        using var response = await Client.PostAsJsonAsync(path, value);
        Assert.True(response.IsSuccessStatusCode, await response.Content.ReadAsStringAsync());
        return await response.Content.ReadFromJsonAsync<JsonElement>();
    }

    public async Task<HttpResponseMessage> Upload(string path, string file) =>
        await Client.PostAsync(path, new ByteArrayContent(await File.ReadAllBytesAsync(file)));

    public async Task<HttpResponseMessage> Frame(int hour, JsonElement? catalog = null)
    {
        var manifest = (catalog ?? await Get("/map-archive/catalog")).GetProperty("manifest_sha256").GetString();
        return await Client.GetAsync($"/map-archive/frame?hour={hour}&manifest_sha256={manifest}");
    }

    public async Task<JsonElement> WaitFor(string path, Func<JsonElement, bool> ready, TimeSpan? wait = null)
    {
        using var timeout = new CancellationTokenSource(wait ?? TimeSpan.FromSeconds(45));
        var value = default(JsonElement);
        do
        {
            try
            {
                value = await Client.GetFromJsonAsync<JsonElement>(path, timeout.Token);
                if (ready(value)) return value;
                await Task.Delay(50, timeout.Token);
            }
            catch (OperationCanceledException) when (timeout.IsCancellationRequested)
            {
                throw new TimeoutException($"{path}: {value}");
            }
        } while (true);
    }

    public async ValueTask DisposeAsync()
    {
        Client.Dispose();
        if (!process.HasExited) process.Kill(entireProcessTree: true);
        await process.WaitForExitAsync();
        process.Dispose();
    }
}

internal sealed class TestRemote(WebApplication app) : IAsyncDisposable
{
    public string Url => app.Urls.Single().TrimEnd('/');

    public static async Task<TestRemote> StartAsync(Action<WebApplication> configure)
    {
        var builder = WebApplication.CreateSlimBuilder();
        builder.Logging.ClearProviders();
        builder.WebHost.UseUrls("http://127.0.0.1:0");
        var application = builder.Build();
        configure(application);
        await application.StartAsync();
        return new TestRemote(application);
    }

    public async ValueTask DisposeAsync()
    {
        await app.StopAsync();
        await app.DisposeAsync();
    }
}

internal static class TestData
{
    public static float[] Floats(byte[] bytes)
    {
        var result = new float[bytes.Length / sizeof(float)];
        Buffer.BlockCopy(bytes, 0, result, 0, bytes.Length);
        return result;
    }

    public static string Forecast(TestDirectory folder, string start = "2023-03-25T00:00:00Z")
    {
        var id = Guid.NewGuid().ToString("N");
        var directory = Directory.CreateDirectory(folder.At("products", "graphcast", id)).FullName;
        File.WriteAllBytes(Path.Combine(directory, "forecast.nc"), "CDF-test-download"u8.ToArray());
        var frame = new byte[181 * 360 * 4 * sizeof(float)];
        for (var index = 0; index < 4; index++)
        {
            var field = Enumerable.Repeat((float)index, 181 * 360).ToArray();
            Buffer.BlockCopy(field, 0, frame, index * 181 * 360 * sizeof(float), field.Length * sizeof(float));
        }
        File.WriteAllBytes(Path.Combine(directory, "frames.bin"), frame);
        File.WriteAllText(Path.Combine(directory, "metadata.json"), JsonSerializer.Serialize(new
        {
            id, name = "forecast-test.nc", start_utc = start, end_utc = DateTimeOffset.Parse(start).AddDays(1).ToString("O"),
            bytes = 17, grid_shape = new[] { 181, 360 }, units = "mm/6h",
            latitude = Enumerable.Range(-90,181).ToArray(), longitude = Enumerable.Range(-180,360).ToArray()
        }));
        return id;
    }
}
