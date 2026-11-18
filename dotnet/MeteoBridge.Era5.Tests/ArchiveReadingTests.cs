using System.Net;
using System.Net.Http.Json;
using System.Text.Json;

namespace MeteoBridge.Era5.Tests;

public sealed class ArchiveReadingTests
{
    private static readonly DateTimeOffset Origin = new(2023, 1, 1, 6, 0, 0, TimeSpan.Zero);
    private static readonly string[] Default = ["amazon", "google", "cds"];
    private static readonly float[] SixMillimetres = [6, 6, 6, 6, 6, 6];

    private static string Cycles(TestDirectory folder)
    {
        var first = RasterFixtures.Cycles(folder.At("era5", "e5.oper.fc.sfc.accumu.part-0.nc"), Origin, [0, 12]);
        RasterFixtures.Cycles(folder.At("era5", "e5.oper.fc.sfc.accumu.part-1.nc"), Origin, [36, 48], .01f);
        File.Copy(first, folder.At("era5", "e5.oper.fc.sfc.accumu.z-duplicate.nc"));
        return first;
    }

    [Fact]
    public async Task ReadsKnownValuesAcrossCyclesGapsMasksAndDuplicates()
    {
        using var folder = new TestDirectory();
        Cycles(folder);
        await using var site = await TestSite.StartAsync(folder);
        var catalog = await site.Get("/map-archive/catalog");
        Assert.Equal(48, catalog.GetProperty("available_hours").GetInt32());
        Assert.Equal(12, catalog.GetProperty("gap_hours").GetInt32());
        Assert.Equal(24, catalog.GetProperty("duplicate_hours").GetInt32());
        Assert.Equal(new[] {2, 3}, catalog.GetProperty("grid_shape").Deserialize<int[]>());
        Assert.Equal(new[] {.05f, .03f, .04f, .02f, 0, .01f}, await Values(site, 0), new FloatTolerance());
        Assert.True(float.IsNaN((await Values(site, 1))[4]));
        Assert.True(float.IsNaN((await Values(site, 2))[2]));
        Assert.All(await Values(site, 27), value => Assert.True(float.IsNaN(value)));
        Assert.Equal(10.05f, (await Values(site, 36))[0], 4);
        var select = await site.Get("/map-archive/range?start=2023-01-01T06:00:00Z&end=2023-01-02T18:00:00Z");
        Assert.Equal(36, select.GetProperty("hours").GetInt32());
    }

    [Fact]
    public async Task BoundedParallelPrefetchAndRepeatedFramesReuseCycles()
    {
        using var folder = new TestDirectory();
        Cycles(folder);
        await using var site = await TestSite.StartAsync(folder);
        var catalog = await site.Get("/map-archive/catalog");
        var sha = catalog.GetProperty("manifest_sha256").GetString();
        await site.Get($"/map-archive/prefetch?hour=0&end_hour=60&manifest_sha256={sha}");
        await site.WaitFor("/map-archive/metrics", metrics => metrics.GetProperty("ready_cycles").GetInt32() == 4);
        var frames = await Task.WhenAll(Enumerable.Range(0, 18).Select(hour => Values(site, hour)));
        Assert.All(frames, frame => Assert.Equal(6, frame.Length));
        await Values(site, 0);
        var metrics = await site.Get("/map-archive/metrics");
        Assert.InRange(metrics.GetProperty("peak_parallel_workers").GetInt32(), 1, 2);
        Assert.InRange(metrics.GetProperty("cached_cycles").GetInt32(), 1, 6);
        Assert.True(metrics.GetProperty("cache_hits").GetInt32() > 0);
    }

    [Fact]
    public async Task ParallelFallbackReadsPreserveRealZerosAndStayAvailable()
    {
        using var folder = new TestDirectory();
        Cycles(folder);
        RasterFixtures.Flat(folder.At("era5", "era5-arco-lsp-next.nc"), Origin.AddHours(1), 24, 9, 0, 9, 9, 9, float.NaN);
        await using var site = await TestSite.StartAsync(folder);
        await site.Post(TestSite.Priority, new { order = new[] { "google", "amazon", "cds" } });
        var frames = await Task.WhenAll(Enumerable.Range(0, 18).Select(hour => Values(site, hour)));
        Assert.Equal(new[] {.05f, 9, 9, 9, 9, 0}, frames[0], new FloatTolerance());
        Assert.All(frames, frame => Assert.Equal(0, frame[^1]));
    }

    [Fact]
    public async Task CdsPriorityPreservesZerosAndFillsGapsFromNextSource()
    {
        using var folder = new TestDirectory();
        Cycles(folder);
        var path=folder.At("era5","era5-cds-lsp-priority.grib");
        await File.WriteAllBytesAsync(path,RasterFixtures.Grib(Origin.AddHours(1),[.007f,.007f,.007f,.007f,0,float.NaN]));
        await using var site=await TestSite.StartAsync(folder);
        Assert.Equal(.05f,(await Values(site,0))[0],4);
        await site.Post(TestSite.Priority,new {order=new[] {"cds","amazon","google"}});
        Assert.Equal(new[] {7f,0,.04f,7,7,7},await Values(site,0),new FloatTolerance());
    }

    [Fact]
    public async Task ChangedSourcesAndInvalidRangeCannotBeReadUsingStaleState()
    {
        using var folder = new TestDirectory();
        var source = Cycles(folder);
        await using var site = await TestSite.StartAsync(folder);
        var before = await site.Get("/map-archive/catalog");
        File.SetLastWriteTimeUtc(source, DateTime.UtcNow.AddMinutes(2));
        Assert.Equal(HttpStatusCode.UnprocessableEntity, (await site.Frame(0, before)).StatusCode);
        foreach (var parameters in new[] { "start=2023-01-01T06:00:00&end=2023-01-02T00:00:00Z",
            "start=2023-01-01T06:30:00Z&end=2023-01-02T00:00:00Z", "start=2023-01-01T06:00:00Z&end=2023-01-02T00:00:00Z&member=2" })
            Assert.Equal(HttpStatusCode.UnprocessableEntity, (await site.Client.GetAsync("/map-archive/range?" + parameters)).StatusCode);
    }

    [Fact]
    public async Task ThreeFormatsFillMissingCellsAndHoursInPriorityOrder()
    {
        using var folder = new TestDirectory();
        RasterFixtures.Flat(folder.At("era5", "base.nc"), Origin.AddHours(1), 1, 1, float.NaN, 2, 3, 0, float.NaN);
        var tiff = RasterFixtures.Tiff(folder.At("source.tif"), [SixMillimetres]);
        var grib = folder.At("source.grib");
        await File.WriteAllBytesAsync(grib, RasterFixtures.Grib(Origin.AddHours(1), [.007f,.007f,.007f,float.NaN,.007f,.007f]));
        await using var site = await TestSite.StartAsync(folder);
        Assert.Equal(HttpStatusCode.OK, (await site.Upload(TiffQuery("source.tif", Origin), tiff)).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await site.Upload("/api/archive/import?name=source.grib", grib)).StatusCode);
        await site.Client.GetStringAsync("/");
        using var response = await site.Frame(0);
        response.EnsureSuccessStatusCode();
        Assert.Equal(new float[] {6,3,0,2,1,7}, TestData.Floats(await response.Content.ReadAsByteArrayAsync()), new FloatTolerance());
        var sources = JsonSerializer.Deserialize<JsonElement>(Uri.UnescapeDataString(response.Headers.GetValues("X-Frame-Sources").Single()));
        Assert.Equal(new[] {"NetCDF","GRIB","GeoTIFF"}, sources.EnumerateArray().Select(source => source.GetProperty("Format").GetString()));
    }

    [Theory]
    [InlineData("tiff")]
    [InlineData("grib")]
    public async Task CumulativeRasterAmountsAreDifferenced(string format)
    {
        using var folder = new TestDirectory();
        var file = folder.At("cumulative." + format);
        string route;
        if (format == "grib")
        {
            await File.WriteAllBytesAsync(file, [.. RasterFixtures.Grib(Origin.AddHours(1), Enumerable.Repeat(.002f,6).ToArray()),
                .. RasterFixtures.Grib(Origin.AddHours(2), Enumerable.Repeat(.005f,6).ToArray(), 2)]);
            route = "/api/archive/import?name=cumulative.grib";
        }
        else
        {
            file = RasterFixtures.Tiff(folder.At("cumulative.tif"), [Enumerable.Repeat(2f,6).ToArray(), [1,5,5,5,5,2]]);
            route = TiffQuery("cumulative.tif", Origin, "cumulative");
        }
        await using var site = await TestSite.StartAsync(folder);
        using var upload = await site.Upload(route, file);
        Assert.True(upload.IsSuccessStatusCode, await upload.Content.ReadAsStringAsync());
        Assert.All(await Values(site, 0), value => Assert.Equal(2, value, 4));
        var second = await Values(site, 1);
        Assert.Equal(3, second[1], 4);
        if (format == "tiff")
        {
            Assert.Contains(second, float.IsNaN);
            Assert.Contains(0, second);
        }
        else Assert.All(second, value => Assert.Equal(3, value, 4));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task TiffMaskAndProjectedGridPreserveCoverage(bool projected)
    {
        using var folder = new TestDirectory();
        var file = RasterFixtures.Tiff(folder.At("masked.tif"), [SixMillimetres], projected ? null : [255,0,255,255,255,255], projected);
        if (projected) RasterFixtures.Flat(folder.At("era5","earlier.nc"), Origin, 1, 2);
        await using var site = await TestSite.StartAsync(folder);
        using var upload = await site.Upload(TiffQuery("masked.tif", Origin), file);
        Assert.True(upload.IsSuccessStatusCode, await upload.Content.ReadAsStringAsync());
        var result = await Values(site, projected ? 1 : 0);
        Assert.Contains(result, float.IsNaN);
        Assert.Contains(result, float.IsFinite);
        Assert.All(result.Where(float.IsFinite), value => Assert.Equal(6, value, 4));
    }

    [Fact]
    public async Task ArchiveImportValidatesPathsQuantityAndMetadataAndInvalidatesManifest()
    {
        using var folder = new TestDirectory();
        Cycles(folder);
        var file = RasterFixtures.Tiff(folder.At("extra.tif"), [SixMillimetres]);
        var total = folder.At("total.grib");
        await File.WriteAllBytesAsync(total, RasterFixtures.Grib(Origin.AddHours(1), Enumerable.Repeat(.002f,6).ToArray(), parameter: 228));
        await using var site = await TestSite.StartAsync(folder);
        var old = await site.Get("/map-archive/catalog");
        foreach (var (path, source) in new[] {("/api/archive/import?name=extra.tif", file),
            (TiffQuery("extra.tif", Origin, units:"C"), file), (TiffQuery("extra.tif", Origin.AddMinutes(30)), file),
            ("/api/archive/import?name=../../bad.tif", file), ("/api/archive/import?name=total.grib", total)})
            Assert.Equal(HttpStatusCode.UnprocessableEntity, (await site.Upload(path, source)).StatusCode);
        await File.WriteAllBytesAsync(total,RasterFixtures.Grib(Origin.AddHours(2),Enumerable.Repeat(.002f,6).ToArray(),duration:2));
        Assert.Equal(HttpStatusCode.UnprocessableEntity,(await site.Upload("/api/archive/import?name=incomplete.grib",total)).StatusCode);
        Assert.Empty(Directory.GetFiles(folder.At("era5"), "*.tif", SearchOption.AllDirectories));
        Assert.Equal(HttpStatusCode.OK, (await site.Upload(TiffQuery("extra.tif", Origin.AddHours(24)), file)).StatusCode);
        await site.Client.GetStringAsync("/");
        Assert.Equal(HttpStatusCode.Conflict, (await site.Frame(0, old)).StatusCode);
        Assert.Equal(11, (await site.Get("/map-archive/catalog")).GetProperty("gap_hours").GetInt32());
    }

    [Fact]
    public async Task PriorityPersistsAppliesToLaterDownloadsAndMigratesGraphCastOut()
    {
        using var folder = new TestDirectory();
        Cycles(folder);
        var settings = Directory.CreateDirectory(folder.At("era5",".meteo-settings")).FullName;
        await File.WriteAllTextAsync(Path.Combine(settings, "map-priority.json"), """["cds","graphcast","google","amazon"]""");
        var local = RasterFixtures.Flat(folder.At("era5-arco-lsp-new.nc"), Origin.AddHours(1), 1, 9, 0, 9, 9, 9, float.NaN);
        var order = new[] {"google", "cds", "amazon"};
        await using (var site = await TestSite.StartAsync(folder))
        {
            Assert.Equal(new[] {"cds", "google", "amazon"}, await PriorityIds(site));
            await site.Post(TestSite.Priority, new { order });
            var before = await site.Get("/map-archive/catalog");
            Assert.Equal(HttpStatusCode.OK, (await site.Upload("/api/archive/import?name=era5-arco-lsp-new.nc",local)).StatusCode);
            await site.Client.GetStringAsync("/");
            Assert.Equal(HttpStatusCode.Conflict,(await site.Frame(0,before)).StatusCode);
            Assert.Equal(new[] {.05f,9,9,9,9,0}, await Values(site,0), new FloatTolerance());
        }
        await using var restarted = await TestSite.StartAsync(folder);
        Assert.Equal(order, await PriorityIds(restarted));
        await restarted.Post(TestSite.Priority, new { order = Default });
        Assert.Equal(Default, await PriorityIds(restarted));
        Assert.Equal(.05f, (await Values(restarted,0))[0], 4);
    }

    [Fact]
    public async Task PriorityRejectsUnknownPartialDuplicateAndCrossOriginChanges()
    {
        using var folder = new TestDirectory();
        Cycles(folder);
        await using var site = await TestSite.StartAsync(folder);
        foreach (string?[]? order in new string?[]?[] { ["amazon","amazon","cds"], ["amazon"], ["cds","google","other"], [null,"google","cds"], null })
            Assert.Equal(HttpStatusCode.UnprocessableEntity, (await site.Client.PostAsJsonAsync(TestSite.Priority,new {order})).StatusCode);
        using var other = new HttpRequestMessage(HttpMethod.Post,TestSite.Priority) { Content = JsonContent.Create(new {order=Default}) };
        other.Headers.Add("Origin","https://example.com");
        Assert.Equal(HttpStatusCode.Forbidden,(await site.Client.SendAsync(other)).StatusCode);
        Assert.Equal(Default, await PriorityIds(site));
    }

    internal static string TiffQuery(string file, DateTimeOffset start, string mode = "hourly", string units = "mm") =>
        $"/api/archive/import?name={file}&metadata=manual&start_utc={Uri.EscapeDataString(start.ToString("O"))}&units={units}&accumulation={mode}";

    internal static async Task<float[]> Values(TestSite site, int hour)
    {
        using var response = await site.Frame(hour);
        Assert.True(response.IsSuccessStatusCode, await response.Content.ReadAsStringAsync());
        return TestData.Floats(await response.Content.ReadAsByteArrayAsync());
    }

    private static async Task<string?[]> PriorityIds(TestSite site) => (await site.Get(TestSite.Priority))
        .GetProperty("archives").EnumerateArray().Select(archive => archive.GetProperty("id").GetString()).ToArray();

    private sealed class FloatTolerance : IEqualityComparer<float>
    {
        public bool Equals(float x, float y) => Math.Abs(x-y) < .00001f || float.IsNaN(x) && float.IsNaN(y);
        public int GetHashCode(float value) => 0;
    }
}
