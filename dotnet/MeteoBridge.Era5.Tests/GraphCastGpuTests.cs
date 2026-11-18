using System.Collections.Concurrent;
using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;

namespace MeteoBridge.Era5.Tests;

public sealed class GpuFactAttribute : FactAttribute
{
    public GpuFactAttribute()
    {
        if (!OperatingSystem.IsWindows() || Environment.GetEnvironmentVariable("METEOBRIDGE_TEST_GPU") != "1")
            Skip = "Requires the prepared Windows NVIDIA runtime and METEOBRIDGE_TEST_GPU=1.";
    }
}

public sealed class GraphCastGpuTests
{
    [GpuFact]
    public async Task FirstArchiveDownloadPreparesAnInputAndForecastsReuseItOffline()
    {
        using var folder = new TestDirectory();
        var first = new DateTimeOffset(2023, 3, 24, 0, 0, 0, TimeSpan.Zero);
        var upstream = SelectArchive("METEOBRIDGE_TEST_ARCHIVE_INPUT", "upstream", "era5-arco-lsp-20230324.nc", first);
        var reference = DateTimeOffset.FromUnixTimeSeconds(GraphCastArchiveInputs.OpenArchiveDay(upstream).End);
        var day = reference.UtcDateTime;
        var dayName = day.ToString("yyyyMMdd", CultureInfo.InvariantCulture);
        var early = folder.At("era5", $"era5-arco-lsp-{dayName}.nc");
        var next = SelectArchive("METEOBRIDGE_TEST_ARCHIVE_BASELINE", "era5", "era5-arco-lsp-20230325.nc", reference.AddHours(1));
        var inputs = Directory.CreateDirectory(folder.At("products","graphcast-inputs")).FullName;
        const string seed = "era5-example-2022-01-01.nc";
        File.Copy(Path.Combine(TestDirectory.Root,"data","graphcast-inputs",seed),Path.Combine(inputs,seed));
        var fields = RasterFixtures.AtmosphericZarr(reference);
        var requestedFields = new ConcurrentDictionary<string, byte>();
        byte[] md5;
        using (var original = File.OpenRead(upstream)) md5 = MD5.HashData(original);
        var key = FormattableString.Invariant($"raw/date-variable-single_level/{day:yyyy/MM/dd}/large_scale_precipitation/surface.nc");
        var etag = new Microsoft.Net.Http.Headers.EntityTagHeaderValue("\"" + Convert.ToHexStringLower(md5) + "\"");
        var catalog = $"/api/archive/files?year={day.Year}&month={day.Month}&source=google";
        var archiveId = ArchiveFiles.Id(early);
        await using var remote = await TestRemote.StartAsync(app =>
        {
            app.MapGet("/", () => Results.Json(new { items = new[] { new { name = key,
                size = new FileInfo(upstream).Length.ToString(CultureInfo.InvariantCulture), md5Hash = Convert.ToBase64String(md5) } } }));
            app.MapGet("/" + key, () => Results.File(upstream, entityTag: etag, enableRangeProcessing: true));
            app.MapMethods("/arco/{**name}", ["GET", "HEAD"], (HttpContext context, string name) =>
            {
                if (context.Request.Headers.ContainsKey("PRIVATE-TOKEN")) return Results.BadRequest();
                if (!fields.TryGetValue(name, out var bytes)) return Results.NotFound();
                if (HttpMethods.IsGet(context.Request.Method)) requestedFields.TryAdd(name, 0);
                return Results.Bytes(bytes, enableRangeProcessing: true);
            });
        });
        var preparedDirectory = Path.Combine(inputs, ".era5", archiveId);
        await using (var online = await TestSite.StartAsync(folder,["--Era5:ArcoBaseUrl",remote.Url,
            "--GraphCast:ArcoFieldsUrl", remote.Url+"/arco", "--Era5:CdsToken="]))
        {
            await online.Get(catalog);
            Assert.False((await online.Get("/api/archive/settings")).GetProperty("cds_configured").GetBoolean());
            await online.Post("/api/archive/download", new { key = "google:" + key });
            await online.WaitFor(catalog, list =>
            {
                var row = list[0];
                var preparation = row.GetProperty("graphcast");
                if (preparation.ValueKind == JsonValueKind.Null) return false;
                var state = preparation.GetProperty("state").GetString();
                if (state == "failed") throw new InvalidDataException(preparation.GetProperty("message").GetString());
                return state == "ready";
            });
            Assert.Single(Directory.GetFiles(preparedDirectory, "*.nc"));
            var status = await online.Get("/api/graphcast/status");
            Assert.False(status.GetProperty("model_loaded").GetBoolean());
            Assert.Equal(JsonValueKind.Null,status.GetProperty("pid").ValueKind);
            Assert.Equal("ready",(await online.Post("/api/graphcast/prepare",new {id=archiveId})).GetProperty("state").GetString());
        }
        await using var site = await TestSite.StartAsync(folder,["--GraphCast:ArcoFieldsUrl","http://127.0.0.1:1/arco","--Era5:CdsToken="]);
        Assert.False((await site.Get("/api/archive/settings")).GetProperty("cds_configured").GetBoolean());
        Assert.Equal("ready",await PreparationState());
        Assert.Equal(12, requestedFields.Keys.Count(key => key.StartsWith("convective_precipitation/")));
        Assert.Contains("temperature/5.0.0.0", requestedFields.Keys);
        Assert.Contains("temperature/11.0.0.0", requestedFields.Keys);
        Assert.Equal(32, requestedFields.Keys.Count(key => key.Contains('.')
            && !key.StartsWith('.') && key.Contains('/')));
        var firstId = await Generate(archiveId);
        var metadata = await site.Get("/api/graphcast/metadata?id="+firstId);
        Assert.Equal(reference,DateTimeOffset.Parse(metadata.GetProperty("start_utc").GetString()!));
        Assert.Equal(reference.AddDays(1),DateTimeOffset.Parse(metadata.GetProperty("end_utc").GetString()!));
        Assert.Equal(4,metadata.GetProperty("valid_times").GetArrayLength());
        Assert.Equal(Path.GetFileName(early),metadata.GetProperty("source_file").GetString());
        Assert.Equal(24,(await site.Get("/api/comparison/files?forecast="+firstId))[0].GetProperty("coveredHours").GetInt32());
        var comparison = TestData.Floats(await site.Client.GetByteArrayAsync($"/api/comparison/frame?forecast={firstId}&file={ArchiveFiles.Id(next)}&step=0"));
        if (Environment.GetEnvironmentVariable("METEOBRIDGE_TEST_ARCHIVE_BASELINE") is null)
            Assert.All(comparison,value=>Assert.Equal(.6f,value,4));
        else Assert.Contains(comparison,value=>float.IsFinite(value) && value>0);
        for (var step=0;step<4;step++)
        {
            var frame=TestData.Floats(await site.Client.GetByteArrayAsync($"/api/graphcast/frame?id={firstId}&index={step}"));
            Assert.Equal(181*360,frame.Length);
            Assert.All(frame,value=>Assert.True(float.IsFinite(value) && value>=0));
        }
        var secondId = await Generate(ArchiveFiles.Id(folder.At("products","graphcast",firstId,"forecast.nc")));
        var second = await site.Get("/api/graphcast/metadata?id="+secondId);
        Assert.True(JsonElement.DeepEquals(metadata.GetProperty("end_utc"),second.GetProperty("start_utc")));
        Assert.Equal(metadata.GetProperty("pid").GetInt32(),second.GetProperty("pid").GetInt32());
        Assert.Equal(1,second.GetProperty("model_load_count").GetInt32());
        Assert.Equal(second.GetProperty("compile_count_before").GetInt32(),second.GetProperty("compile_count_after").GetInt32());
        Assert.True((await site.Post("/api/graphcast/delete",new {id=secondId})).GetProperty("deleted").GetBoolean());
        Assert.Empty(Directory.GetDirectories(folder.At("products","graphcast",".pending")));
        File.SetLastWriteTimeUtc(early, File.GetLastWriteTimeUtc(early).AddSeconds(5));
        Assert.Equal("available",await PreparationState());
        Assert.True((await site.Post("/api/archive/delete",new {id=archiveId})).GetProperty("deleted").GetBoolean());
        Assert.False(Directory.Exists(preparedDirectory));

        async Task<string?> PreparationState() => (await site.Get("/api/graphcast/inputs")).EnumerateArray()
            .Single(file => file.GetProperty("id").GetString() == archiveId).GetProperty("preparation").GetProperty("state").GetString();

        async Task<string> Generate(string id)
        {
            await site.Post("/api/graphcast/generate",new {id});
            var state=await site.WaitFor("/api/graphcast/status",value=>!value.GetProperty("busy").GetBoolean(),TimeSpan.FromMinutes(3));
            Assert.True(state.GetProperty("state").GetString()=="completed",state.GetProperty("message").GetString());
            return state.GetProperty("result_id").GetString()!;
        }

        string SelectArchive(string variable, string folderName, string fixture, DateTimeOffset firstValid)
        {
            var source = Environment.GetEnvironmentVariable(variable);
            if (source is null) return RasterFixtures.GlobalArchive(folder.At(folderName,fixture),firstValid);
            var directory=Directory.CreateDirectory(folder.At(folderName)).FullName;
            var destination=Path.Combine(directory,Path.GetFileName(source));
            File.Copy(source,destination);
            return destination;
        }
    }
}
