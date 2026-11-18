using System.Globalization;
using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace MeteoBridge.Era5;

internal sealed record CdsCredentials(string Token);

internal sealed class CdsAccessException(string code, string message, string? actionUrl = null) : IOException(message)
{
    public string Code { get; } = code;
    public string? ActionUrl { get; } = actionUrl;
}

// CDS builds a result asynchronously. API credentials are only sent to the
// processing API, never to result storage or redirects.
internal sealed class CdsArchive : IDisposable
{
    public const string LicenceUrl = "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=download#manage-licences";
    public const string RequestsUrl = "https://cds.climate.copernicus.eu/requests?tab=all";
    private readonly Uri api;
    private readonly HttpClient client;
    private readonly CdsTokenStore tokenStore;
    private readonly SemaphoreSlim requests = new(1);
    private readonly string activeReceipt;
    private string? activeRequest;
    private string? token;
    public bool Configured => !string.IsNullOrEmpty(Volatile.Read(ref token));

    public CdsArchive(string? baseUrl, string? configuredToken, string tokenPath)
    {
        api = new Uri((baseUrl ?? "https://cds.climate.copernicus.eu/api/retrieve/v1").TrimEnd('/') + "/");
        if (!(api.Scheme == "https" && api.Host == "cds.climate.copernicus.eu" && api.AbsolutePath == "/api/retrieve/v1/") &&
            !(api.Scheme == "http" && api.IsLoopback)) throw new ArgumentException("Нужен официальный CDS API или loopback test server.");
        client = new HttpClient(new SocketsHttpHandler { AllowAutoRedirect = false, UseProxy = !api.IsLoopback })
            { Timeout = TimeSpan.FromSeconds(60), MaxResponseContentBufferSize = 4 * 1048576 };
        tokenStore = new CdsTokenStore(tokenPath);
        activeReceipt = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(tokenPath))!, "cds-active-request.json");
        token = configuredToken ?? Environment.GetEnvironmentVariable("CDSAPI_KEY") ?? tokenStore.Load();
    }

    public object Configure(string? value)
    {
        value = (value ?? "").Trim();
        if (value.Length > 4096 || value.Any(char.IsControl)) throw new ArgumentException("Неверный API-токен CDS.");
        tokenStore.Save(value);
        Volatile.Write(ref token, value.Length == 0 ? null : value);
        return new { configured = Configured };
    }

    public static RemoteEra5File[] List(int year, int month)
    {
        var last = DateTime.UtcNow.Date.AddDays(-6); // include only complete days
        return (month == 0 ? Enumerable.Range(1, 12) : [month]).SelectMany(selected =>
            Enumerable.Range(1, DateTime.DaysInMonth(year, selected)).Select(day => new DateTime(year, selected, day)))
            .Where(day => day <= last).Select(day => new RemoteEra5File("cds:" + day.ToString("yyyy-MM-dd"),
                "era5-cds-lsp-" + day.ToString("yyyyMMdd") + ".grib", 0, "",
                Era5Index.Iso(new DateTimeOffset(DateTime.SpecifyKind(day, DateTimeKind.Utc)).AddHours(-1).ToUnixTimeSeconds()),
                Era5Index.Iso(new DateTimeOffset(DateTime.SpecifyKind(day, DateTimeKind.Utc)).AddHours(23).ToUnixTimeSeconds()), "cds")).ToArray();
    }

    private async Task<JsonDocument> Call(HttpMethod method, string path, object? body, CancellationToken cancellation)
    {
        var credential = Volatile.Read(ref token);
        if (string.IsNullOrEmpty(credential)) throw new InvalidDataException("Укажите API-токен Copernicus CDS в разделе загрузки.");
        for (var attempt = 0; ; attempt++)
        {
            using var request = new HttpRequestMessage(method, new Uri(api, path));
            request.Headers.Add("PRIVATE-TOKEN", credential);
            if (body is not null) request.Content = new StringContent(JsonSerializer.Serialize(body), Encoding.UTF8, "application/json");
            using var response = await client.SendAsync(request, cancellation);
            if (response.IsSuccessStatusCode)
                return JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellation));
            if (response.StatusCode is HttpStatusCode.NotFound or HttpStatusCode.Gone) throw new FileNotFoundException("Сохранённый запрос CDS истёк. Повторите загрузку для создания нового запроса.");
            if (method == HttpMethod.Get && attempt < 3 &&
                (response.StatusCode == HttpStatusCode.TooManyRequests || (int)response.StatusCode >= 500))
            {
                await Task.Delay(TimeSpan.FromSeconds(Math.Clamp(response.Headers.RetryAfter?.Delta?.TotalSeconds ?? 2 * (attempt + 1), 1, 30)), cancellation);
                continue;
            }
            var detail = await ReadErrorAsync(response, cancellation);
            if (IsQueueLimit(detail)) throw QueueLimit();
            if (response.StatusCode is HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden)
                throw AccessError(response.StatusCode, detail);
            throw new CdsAccessException("service_error", $"CDS вернул HTTP {(int)response.StatusCode}. {detail}".TrimEnd(), RequestsUrl);
        }
    }

    private static string ErrorDetail(JsonElement body)
    {
        if (body.ValueKind != JsonValueKind.Object) return "";
        var descriptions = new List<string>(4);
        foreach (var field in new[] { "detail", "message", "title", "traceback" })
        {
            if (body.TryGetProperty(field, out var value) && value.ValueKind == JsonValueKind.String &&
                value.GetString()?.Trim() is { Length: > 0 } detail)
                descriptions.Add(detail);
        }
        return string.Join(" ", descriptions.Distinct());
    }

    private static async Task<string> ReadErrorAsync(HttpResponseMessage response, CancellationToken cancellation)
    {
        try
        {
            using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellation));
            return ErrorDetail(body.RootElement);
        }
        catch (JsonException) { return ""; }
    }

    private static bool IsQueueLimit(string detail) =>
        detail.Contains("queued requests", StringComparison.OrdinalIgnoreCase) &&
        (detail.Contains("maximum number", StringComparison.OrdinalIgnoreCase) ||
            detail.Contains("temporarily limited", StringComparison.OrdinalIgnoreCase));

    private static CdsAccessException QueueLimit() => new("queue_limit",
        "CDS достиг лимита очереди для этого набора. Дождитесь завершения активных запросов в CDS и повторите загрузку или подготовку.",
        RequestsUrl);

    private static CdsAccessException AccessError(HttpStatusCode status, string description)
    {
        if (status == HttpStatusCode.Unauthorized)
            return new CdsAccessException("invalid_token", "CDS не принял API-токен (HTTP 401). Скопируйте Personal Access Token из профиля CDS и примените его заново.");
        if (description.Contains("required licences not accepted", StringComparison.OrdinalIgnoreCase) ||
            description.Contains("required licenses not accepted", StringComparison.OrdinalIgnoreCase) ||
            description.Contains("not all the required licences have been accepted", StringComparison.OrdinalIgnoreCase))
            return new CdsAccessException("licence_required",
                "CDS: для этого аккаунта не приняты условия ERA5 (HTTP 403). Откройте «Принять условия ERA5», войдите в аккаунт владельца токена, примите условия и нажмите «Повторить».",
                LicenceUrl);
        return new CdsAccessException("forbidden", "CDS запретил доступ (HTTP 403). Проверьте права аккаунта и состояние токена в профиле CDS.");
    }

    public Task<RemoteEra5File> ResolveAsync(RemoteEra5File file, string directory, Action<string> state, CancellationToken cancellation)
    {
        var date = DateTime.ParseExact(file.Key[4..], "yyyy-MM-dd", CultureInfo.InvariantCulture);
        return ResolveAsync(file, "reanalysis-era5-single-levels", new
        {
            product_type = new[] { "reanalysis" }, variable = new[] { "large_scale_precipitation" },
            year = new[] { date.ToString("yyyy") }, month = new[] { date.ToString("MM") }, day = new[] { date.ToString("dd") },
            time = Enumerable.Range(0, 24).Select(hour => $"{hour:00}:00").ToArray(),
            data_format = "grib", download_format = "unarchived"
        }, Path.Combine(directory, file.Name + ".cds-request.json"), state, cancellation);
    }

    private async Task<RemoteEra5File> ResolveAsync(RemoteEra5File file, string dataset, object inputs, string receipt,
        Action<string> state, CancellationToken cancellation)
    {
        state("queued");
        await requests.WaitAsync(cancellation);
        try
        {
            var id = await ReadReceiptAsync(receipt, cancellation);
            var previous = activeRequest ??= await ReadReceiptAsync(activeReceipt, cancellation);
            if (previous is not null && previous != id)
            {
                // Pausing a local download leaves its accepted CDS request in flight.
                try { await WaitForTerminalAsync(previous, null, cancellation); }
                catch (FileNotFoundException) { }
                catch (CdsAccessException error) when (error.Code == "forbidden") { }
                ClearActiveRequest();
            }
            if (id is null)
            {
                state("requesting");
                cancellation.ThrowIfCancellationRequested();
                // Once sent, capture the job ID even if the local task is paused.
                id = await SubmitAsync(dataset, inputs, CancellationToken.None);
                await TrackAsync(id);
                await SaveReceiptAsync(receipt, id);
            }
            else if (activeRequest != id) await TrackAsync(id);
            return await ResultAsync(file, id, state, cancellation, receipt);
        }
        finally { requests.Release(); }
    }

    private async Task<string?> ReadReceiptAsync(string path, CancellationToken cancellation)
    {
        if (!File.Exists(path)) return null;
        using var saved = JsonDocument.Parse(await File.ReadAllTextAsync(path, cancellation));
        return saved.RootElement.GetProperty("api").GetString() == api.AbsoluteUri
            ? saved.RootElement.GetProperty("id").GetString() : null;
    }

    private async Task SaveReceiptAsync(string path, string id)
    {
        await File.WriteAllTextAsync(path + ".tmp", JsonSerializer.Serialize(new { api = api.AbsoluteUri, id }));
        File.Move(path + ".tmp", path, true);
    }

    private async Task TrackAsync(string id)
    {
        activeRequest = id;
        Directory.CreateDirectory(Path.GetDirectoryName(activeReceipt)!);
        await SaveReceiptAsync(activeReceipt, id);
    }

    private void ClearActiveRequest()
    {
        activeRequest = null;
        if (File.Exists(activeReceipt)) File.Delete(activeReceipt);
    }

    private async Task<string> SubmitAsync(string dataset, object inputs, CancellationToken cancellation)
    {
        using var submitted = await Call(HttpMethod.Post, $"processes/{dataset}/execution", new { inputs }, cancellation);
        var id = submitted.RootElement.GetProperty("jobID").GetString()
            ?? throw new InvalidDataException("CDS не вернул номер запроса.");
        if (!Regex.IsMatch(id, @"^[a-zA-Z0-9_-]{1,100}$")) throw new InvalidDataException("Неверный номер запроса CDS.");
        return id;
    }

    private async Task<(string Status, string Detail)> WaitForTerminalAsync(string id, Action<string>? state,
        CancellationToken cancellation)
    {
        if (!Regex.IsMatch(id, @"^[a-zA-Z0-9_-]{1,100}$")) throw new InvalidDataException("Неверный номер запроса CDS.");
        var delay = 1;
        while (true)
        {
            using var status = await Call(HttpMethod.Get, $"jobs/{id}", null, cancellation);
            var value = status.RootElement.GetProperty("status").GetString() ?? "unknown";
            if (value is not ("accepted" or "running" or "queued"))
                return (value, ErrorDetail(status.RootElement));
            state?.Invoke(value == "running" ? "preparing" : "waiting");
            await Task.Delay(TimeSpan.FromSeconds(delay), cancellation);
            delay = Math.Min(30, delay * 2);
        }
    }

    private async Task<RemoteEra5File> ResultAsync(RemoteEra5File file, string id, Action<string> state,
        CancellationToken cancellation, string receipt)
    {
        (string Status, string Detail) terminal;
        try { terminal = await WaitForTerminalAsync(id, state, cancellation); }
        catch (FileNotFoundException)
        {
            ClearActiveRequest();
            File.Delete(receipt);
            throw;
        }
        ClearActiveRequest();
        if (terminal.Status != "successful")
        {
            File.Delete(receipt);
            throw await JobErrorAsync(id, terminal.Status, terminal.Detail, cancellation);
        }
        using var result = await ReadResultAsync();
        var asset = result.RootElement.GetProperty("asset").GetProperty("value");
        var location = new Uri(new Uri(api, "jobs/" + id + "/results"), asset.GetProperty("href").GetString()!);
        ValidateStorage(location);
        var length = asset.GetProperty("file:size");
        var size = length.ValueKind == JsonValueKind.String ? long.Parse(length.GetString()!, CultureInfo.InvariantCulture) : length.GetInt64();
        if (size <= 0 || size > ArchiveImports.MaxBytes) throw new InvalidDataException("Размер результата CDS должен быть от 1 байта до 8 ГиБ.");
        return file with { Bytes = size, Etag = "", RemoteKey = location.AbsoluteUri };

        async Task<JsonDocument> ReadResultAsync()
        {
            try { return await Call(HttpMethod.Get, $"jobs/{id}/results", null, cancellation); }
            catch (FileNotFoundException) { File.Delete(receipt); throw; }
        }
    }

    private async Task<CdsAccessException> JobErrorAsync(string id, string status, string detail, CancellationToken cancellation)
    {
        if (IsQueueLimit(detail)) return QueueLimit();
        if (status is "rejected" or "failed")
        {
            try
            {
                using var result = await Call(HttpMethod.Get, $"jobs/{id}/results", null, cancellation);
                var resultDetail = ErrorDetail(result.RootElement);
                if (resultDetail.Length != 0) detail = resultDetail;
            }
            catch (CdsAccessException error) { return error; }
            catch (Exception error) when (error is FileNotFoundException or HttpRequestException or JsonException) { }
        }
        return IsQueueLimit(detail) ? QueueLimit() : new CdsAccessException("processing_failed",
            $"CDS завершил запрос без результата ({status}). {detail}".TrimEnd(), RequestsUrl);
    }

    public static bool ResultExpired(HttpResponseMessage result) =>
        result.StatusCode is HttpStatusCode.Forbidden or HttpStatusCode.NotFound or HttpStatusCode.Gone;

    public async Task<HttpResponseMessage> OpenResultAsync(Uri url, long first, long last, CancellationToken cancellation)
    {
        for (var redirects = 0; ; redirects++)
        {
            ValidateStorage(url);
            using var request = new HttpRequestMessage(HttpMethod.Get, url);
            request.Headers.Range = new RangeHeaderValue(first, last);
            var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellation);
            if ((int)response.StatusCode is not (301 or 302 or 303 or 307 or 308)) return response;
            var location = response.Headers.Location;
            response.Dispose();
            if (redirects >= 4 || location is null) throw new IOException("Слишком много перенаправлений хранилища CDS.");
            url = new Uri(url, location);
        }
    }

    private void ValidateStorage(Uri location)
    {
        if (location.UserInfo.Length > 0 || location.Fragment.Length > 0 ||
            !(api.IsLoopback && location.Scheme == "http" && location.Authority == api.Authority) &&
            !(location.Scheme == "https" && location.IsDefaultPort &&
              (location.Host == "cds.climate.copernicus.eu" || location.Host.EndsWith(".climate.copernicus.eu", StringComparison.OrdinalIgnoreCase) ||
               location.Host.EndsWith(".ecmwf.int", StringComparison.OrdinalIgnoreCase))))
            throw new InvalidDataException("CDS вернул ссылку вне официального хранилища ECMWF.");
    }

    public void Dispose() => client.Dispose();
}
