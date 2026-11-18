using System.Net;
using System.Net.Http.Json;
using System.Text.Json;

namespace MeteoBridge.Era5.Tests;

public sealed class ForecastTests
{
    private static readonly DateTimeOffset Day = new(2023, 3, 25, 0, 0, 0, TimeSpan.Zero);

    [Fact]
    public async Task OnlyEra5IsInTheMainMapAndLegacyForecastLinksOpenComparison()
    {
        using var folder = new TestDirectory();
        RasterFixtures.Flat(folder.At("era5", "era5-arco-lsp-day.nc"), Day.AddHours(1), 24, 5);
        var id = TestData.Forecast(folder);
        await using var site = await TestSite.StartAsync(folder);
        var catalog = await site.Get(TestSite.MainCatalog);
        Assert.Equal(24, catalog.GetProperty("frames").GetArrayLength());
        Assert.Equal(1, catalog.GetProperty("file_count").GetInt32());
        Assert.All(catalog.GetProperty("frames").EnumerateArray(), frame => Assert.Equal("era5", frame.GetProperty("kind").GetString()));
        Assert.DoesNotContain("graphcast", (await site.Get(TestSite.Priority)).GetRawText());
        var html = await site.Client.GetStringAsync("/");
        Assert.Contains("href=\"/comparison\"", html);
        Assert.DoesNotContain("GrathCast", html);
        using var redirect = await site.Client.GetAsync("/?forecast=" + id);
        Assert.Equal("/comparison?forecast=" + id, redirect.Headers.Location?.OriginalString);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await site.Client.GetAsync($"/map-playback/{id}/catalog")).StatusCode);
        Assert.Contains("id=\"archive-map\"", await site.Client.GetStringAsync("/comparison"));
    }

    [Fact]
    public async Task ComparisonPairsFourSixHourFramesAndDoesNotFillMissingHours()
    {
        using var folder = new TestDirectory();
        var first = RasterFixtures.Flat(folder.At("era5", "era5-arco-lsp-first.nc"), Day.AddHours(1), 24, 2, 5, 0);
        var partial = RasterFixtures.Flat(folder.At("era5", "era5-arco-lsp-partial.nc"), Day.AddHours(2), 5, 5);
        RasterFixtures.Flat(folder.At("era5", "outside.nc"), Day.AddDays(-1).AddHours(1), 24, 5);
        var id = TestData.Forecast(folder);
        await using var site = await TestSite.StartAsync(folder);
        var files = await site.Get("/api/comparison/files?forecast=" + id);
        Assert.Equal(2, files.GetArrayLength());
        Assert.Equal(24, files[0].GetProperty("coveredHours").GetInt32());
        Assert.Equal(5, files[1].GetProperty("coveredHours").GetInt32());
        Assert.Equal(ArchiveFiles.Id(first), files[0].GetProperty("id").GetString());
        var baseline = "/api/comparison/frame?forecast=" + id + "&file=";
        for (var step = 0; step < 4; step++)
        {
            var frame = TestData.Floats(await site.Client.GetByteArrayAsync(baseline + ArchiveFiles.Id(first) + "&step=" + step));
            Assert.Equal(new float[] {0, 12, 30, 0, 12, 30}, frame);
            var prediction = TestData.Floats(await site.Client.GetByteArrayAsync($"/api/graphcast/frame?id={id}&index={step}"));
            Assert.Equal(181 * 360, prediction.Length);
            Assert.Equal(step, prediction[0]);
        }
        Assert.All(TestData.Floats(await site.Client.GetByteArrayAsync(baseline + ArchiveFiles.Id(partial) + "&step=0")),
            value => Assert.True(float.IsNaN(value)));
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await site.Client.GetAsync(baseline + "../bad&step=0")).StatusCode);
    }

    [Fact]
    public async Task DownloadedLspFilesAreSelectableAndTheirEndDeterminesTheForecast()
    {
        using var folder = new TestDirectory();
        var archive = RasterFixtures.Flat(folder.At("era5", "era5-arco-lsp-day.nc"), Day, 24, 10);
        await using var site = await TestSite.StartAsync(folder);
        var files = await site.Get("/api/graphcast/inputs");
        Assert.False(files[0].GetProperty("compatible").GetBoolean());
        Assert.True(files[0].GetProperty("prepare").GetBoolean());
        Assert.Equal(Day.AddHours(23).ToUnixTimeSeconds(), GraphCastArchiveInputs.OpenArchiveDay(archive).End);
        var multiDay = RasterFixtures.Flat(folder.At("multi-day.nc"), Day, 48, 10);
        Assert.Throws<InvalidDataException>(() => GraphCastArchiveInputs.OpenArchiveDay(multiDay));
        using var missing = await site.Client.PostAsJsonAsync("/api/graphcast/generate", new { id = ArchiveFiles.Id(archive) });
        Assert.Equal(HttpStatusCode.UnprocessableEntity, missing.StatusCode);
        Assert.Contains("scripts/setup_graphcast.ps1", (await missing.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("detail").GetString());
        Assert.False((await site.Get("/api/graphcast/status")).GetProperty("model_loaded").GetBoolean());
    }

    [Fact]
    public async Task ForecastRoutesKeepFilesDownloadableAndRejectInvalidImports()
    {
        using var folder = new TestDirectory();
        var id = TestData.Forecast(folder);
        var invalid = folder.At("invalid.nc");
        await File.WriteAllTextAsync(invalid,"not netcdf");
        await using var site = await TestSite.StartAsync(folder);
        using var page = await site.Client.GetAsync("/generation");
        Assert.Equal("no-store", page.Headers.CacheControl?.ToString());
        Assert.False((await site.Get("/api/graphcast/status")).GetProperty("busy").GetBoolean());
        Assert.Single((await site.Get("/api/archive/files?source=graphcast&year=2023")).EnumerateArray());
        Assert.Empty((await site.Get("/api/archive/files?source=graphcast&year=2024")).EnumerateArray());
        Assert.Equal("CDF-test-download", await site.Client.GetStringAsync("/api/graphcast/file?id=" + id));
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await site.Upload("/api/graphcast/import?name=invalid.nc", invalid)).StatusCode);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await site.Upload("/api/graphcast/import?name=../invalid.nc", invalid)).StatusCode);
        Assert.Empty(Directory.GetFiles(folder.At("products", "graphcast-inputs")));
        using var crossOrigin = new HttpRequestMessage(HttpMethod.Post, "/api/graphcast/generate") { Content = JsonContent.Create(new { id }) };
        crossOrigin.Headers.Add("Origin", "https://example.com");
        Assert.Equal(HttpStatusCode.Forbidden, (await site.Client.SendAsync(crossOrigin)).StatusCode);
        Assert.True((await site.Post("/api/archive/delete", new { id })).GetProperty("deleted").GetBoolean());
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await site.Client.GetAsync("/api/graphcast/metadata?id=" + id)).StatusCode);
    }
}
