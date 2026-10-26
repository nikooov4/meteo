using System.Globalization;
using System.Net;
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
    private readonly Uri api;
    private readonly HttpClient client;
    private readonly CdsTokenStore tokenStore;
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
            if (response.StatusCode is HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden)
                throw await AccessErrorAsync(response, cancellation);
            if (response.StatusCode is HttpStatusCode.NotFound or HttpStatusCode.Gone) throw new FileNotFoundException("Сохранённый запрос CDS истёк. Повторите загрузку для создания нового запроса.");
            if (attempt < 3 && (response.StatusCode == HttpStatusCode.TooManyRequests || (int)response.StatusCode >= 500))
            {
                await Task.Delay(TimeSpan.FromSeconds(Math.Clamp(response.Headers.RetryAfter?.Delta?.TotalSeconds ?? 2 * (attempt + 1), 1, 30)), cancellation);
                continue;
            }
            if (!response.IsSuccessStatusCode)
                throw new InvalidDataException($"CDS вернул HTTP {(int)response.StatusCode}. Проверьте период и состояние запроса на сайте CDS.");
            return JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellation));
        }
    }

    private static async Task<CdsAccessException> AccessErrorAsync(HttpResponseMessage response, CancellationToken cancellation)
    {
        if (response.StatusCode == HttpStatusCode.Unauthorized)
            return new CdsAccessException("invalid_token", "CDS не принял API-токен (HTTP 401). Скопируйте Personal Access Token из профиля CDS и примените его заново.");
        var description = "";
        try
        {
            using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellation));
            if (body.RootElement.ValueKind == JsonValueKind.Object)
                foreach (var field in new[] { "title", "detail" })
                    if (body.RootElement.TryGetProperty(field, out var value) && value.ValueKind == JsonValueKind.String)
                        description += " " + value.GetString();
        }
        catch (JsonException) { }
        if (description.Contains("required licences not accepted", StringComparison.OrdinalIgnoreCase) ||
            description.Contains("required licenses not accepted", StringComparison.OrdinalIgnoreCase) ||
            description.Contains("not all the required licences have been accepted", StringComparison.OrdinalIgnoreCase))
            return new CdsAccessException("licence_required",
                "CDS: для этого аккаунта не приняты условия ERA5 (HTTP 403). Откройте «Принять условия ERA5», войдите в аккаунт владельца токена, примите условия и нажмите «Повторить».", LicenceUrl);
        return new CdsAccessException("forbidden", "CDS запретил доступ (HTTP 403). Проверьте права аккаунта и состояние токена в профиле CDS.");
    }

    public async Task<RemoteEra5File> ResolveAsync(RemoteEra5File file, string directory, Action<string> state, CancellationToken cancellation)
    {
        var date = DateTime.ParseExact(file.Key[4..], "yyyy-MM-dd", CultureInfo.InvariantCulture);
        var receipt = Path.Combine(directory, file.Name + ".cds-request.json");
        string? id = null;
        if (File.Exists(receipt))
        {
            using var saved = JsonDocument.Parse(await File.ReadAllTextAsync(receipt, cancellation));
            if (saved.RootElement.GetProperty("api").GetString() == api.AbsoluteUri)
                id = saved.RootElement.GetProperty("id").GetString();
        }
        if (id is null)
        {
            state("requesting");
            using var submitted = await Call(HttpMethod.Post, "processes/reanalysis-era5-single-levels/execution", new { inputs = new
            {
                product_type = new[] { "reanalysis" }, variable = new[] { "large_scale_precipitation" },
                year = new[] { date.ToString("yyyy") }, month = new[] { date.ToString("MM") }, day = new[] { date.ToString("dd") },
                time = Enumerable.Range(0, 24).Select(hour => $"{hour:00}:00").ToArray(),
                data_format = "grib", download_format = "unarchived"
            } }, cancellation);
            id = submitted.RootElement.GetProperty("jobID").GetString() ?? throw new InvalidDataException("CDS не вернул номер запроса.");
            if (!Regex.IsMatch(id, @"^[a-zA-Z0-9_-]{1,100}$")) throw new InvalidDataException("Неверный номер запроса CDS.");
            await File.WriteAllTextAsync(receipt + ".tmp", JsonSerializer.Serialize(new { api = api.AbsoluteUri, id }), cancellation);
            File.Move(receipt + ".tmp", receipt, true);
        }
        if (!Regex.IsMatch(id, @"^[a-zA-Z0-9_-]{1,100}$")) throw new InvalidDataException("Неверный номер запроса CDS.");
        var delay = 1;
        while (true)
        {
            JsonDocument status;
            try { status = await Call(HttpMethod.Get, "jobs/" + id, null, cancellation); }
            catch (FileNotFoundException) { File.Delete(receipt); throw; }
            using var statusDocument = status;
            var value = status.RootElement.GetProperty("status").GetString();
            if (value == "successful") break;
            if (value is not ("accepted" or "running" or "queued"))
            {
                File.Delete(receipt);
                throw new InvalidDataException("Запрос CDS завершился без результата. Проверьте условия набора и повторите загрузку.");
            }
            state(value == "running" ? "preparing" : "waiting");
            await Task.Delay(TimeSpan.FromSeconds(delay), cancellation);
            delay = Math.Min(30, delay * 2);
        }
        JsonDocument result;
        try { result = await Call(HttpMethod.Get, "jobs/" + id + "/results", null, cancellation); }
        catch (FileNotFoundException) { File.Delete(receipt); throw; }
        using var resultDocument = result;
        var asset = result.RootElement.GetProperty("asset").GetProperty("value");
        var location = new Uri(new Uri(api, "jobs/" + id + "/results"), asset.GetProperty("href").GetString()!);
        ValidateStorage(location);
        var length = asset.GetProperty("file:size");
        var size = length.ValueKind == JsonValueKind.String ? long.Parse(length.GetString()!, CultureInfo.InvariantCulture) : length.GetInt64();
        if (size <= 0 || size > ArchiveImports.MaxBytes) throw new InvalidDataException("Размер результата CDS должен быть от 1 байта до 8 ГиБ.");
        return file with { Bytes = size, Etag = "", RemoteKey = location.AbsoluteUri };
    }

    public void ValidateStorage(Uri location)
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
