using System.Collections.Concurrent;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;

namespace MeteoBridge.Era5.Tests;

public sealed class ArchiveDownloadTests
{
    private static readonly DateTimeOffset Day = new(2023, 1, 2, 0, 0, 0, TimeSpan.Zero);
    private const string Token = "local-test-token";
    private const string Api = "/api/retrieve/v1";
    private const string CdsKey = "cds:2023-01-02";
    private const string QueueLimit = "Maximum number queued requests for this dataset has been reached. Please configure your scripts to request data sequentially";

    [Theory]
    [InlineData("amazon")]
    [InlineData("google")]
    public async Task RangeDownloadResumesAndPublishesTheOriginalFile(string source)
    {
        using var folder = new TestDirectory();
        var google = source == "google";
        var name = google ? "era5-arco-lsp-20230102.nc" : "e5.oper.fc.sfc.accumu.128_142_lsp.ll025sc.2023010106_2023011606.nc";
        var path = google ? RasterFixtures.Flat(folder.At("source.nc"),Day,24,4) :
            RasterFixtures.Cycles(folder.At("source.nc"),Day.AddHours(-1),[0,12],.004f);
        var input = await File.ReadAllBytesAsync(path);
        Array.Resize(ref input, input.Length + 5 * 1024 * 1024);
        var key = google ? "raw/date-variable-single_level/2023/01/02/large_scale_precipitation/surface.nc" :
            "e5.oper.fc.sfc.accumu/202301/" + name;
        var md5 = MD5.HashData(input);
        var etag = "\"" + Convert.ToHexStringLower(md5) + "\"";
        var ranges = new ConcurrentQueue<long>();
        var requests = new ConcurrentQueue<string>();
        var stall = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var waiting = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var shouldPause = 1;
        await using var remote = await TestRemote.StartAsync(app =>
        {
            app.MapGet("/", (HttpContext context) =>
            {
                var prefix = context.Request.Query["prefix"].ToString();
                requests.Enqueue(prefix);
                if (google && !context.Request.Query.ContainsKey("pageToken"))
                    return Results.Json(new { items = Array.Empty<object>(), nextPageToken = "second-page" });
                if (google)
                    return Results.Json(new { items = new[] { new { name = key, size = input.Length.ToString(), generation = "17", md5Hash = Convert.ToBase64String(md5) } } });
                return Results.Text($"""<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false</IsTruncated><Contents><Key>{key}</Key><Size>{input.Length}</Size><ETag>{etag}</ETag></Contents></ListBucketResult>""","application/xml");
            });
            app.MapGet("/" + key, async context =>
            {
                var from = Range(context).From!.Value;
                ranges.Enqueue(from);
                if (from > 0 && Volatile.Read(ref shouldPause) == 1)
                {
                    waiting.TrySetResult();
                    await stall.Task.WaitAsync(context.RequestAborted);
                }
                if (context.Request.Headers.IfMatch.ToString() != etag) { context.Response.StatusCode=412; return; }
                await WriteData(context, input, true);
            });
        });
        await using var site = await TestSite.StartAsync(folder,
            [google ? "--Era5:ArcoBaseUrl" : "--Era5:ArchiveBaseUrl", remote.Url]);
        var list = await site.Get(Catalog(source));
        var row = Assert.Single(list.EnumerateArray());
        var local = row.GetProperty("key").GetString()!;
        Assert.Equal(name, row.GetProperty("name").GetString());
        await site.Post("/api/archive/download", new {key=local});
        await waiting.Task.WaitAsync(TimeSpan.FromSeconds(20));
        await site.Post("/api/archive/cancel", new {key=local});
        await WaitRow(site, source, local, "paused", "cancelled");
        Assert.False(File.Exists(folder.At("era5",name)));
        Volatile.Write(ref shouldPause,0);
        stall.TrySetResult();
        await site.Post("/api/archive/download", new {key=local});
        var downloaded = await WaitRow(site, source, local, "downloaded");
        Assert.Equal(input, await File.ReadAllBytesAsync(folder.At("era5",name)));
        if (google)
        {
            Assert.Equal("runtime_required", downloaded.GetProperty("graphcast").GetProperty("state").GetString());
            var id = ArchiveFiles.Id(folder.At("era5",name));
            await site.WaitFor(Catalog(source), _ => File.Exists(folder.At("products","graphcast-inputs",".era5",id,"pending")));
        }
        else Assert.Equal(JsonValueKind.Null, downloaded.GetProperty("graphcast").ValueKind);
        Assert.Equal(new long[] {0, 4 * 1024 * 1024, 4 * 1024 * 1024}, ranges.ToArray());
        if (google) Assert.Equal(2, requests.Count);
        var catalog = await site.Get(TestSite.MainCatalog);
        Assert.Equal(24, catalog.GetProperty("available_hours").GetInt32());
        Assert.True((await site.Post("/api/archive/delete", new {id=ArchiveFiles.Id(folder.At("era5",name))})).GetProperty("deleted").GetBoolean());
        Assert.False(File.Exists(folder.At("era5", name)));
        Assert.Equal(0, (await site.Get(TestSite.MainCatalog)).GetProperty("available_hours").GetInt32());
        await site.Post("/api/archive/download", new {key=local});
        await WaitRow(site, source, local, "downloaded");
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task CdsDownloadsOriginalGribAndAll24Frames(bool range)
    {
        using var folder = new TestDirectory();
        var state = new CdsState { Range = range };
        await using var remote = await CdsServer(state);
        await using var site = await TestSite.StartAsync(folder, ["--Era5:CdsBaseUrl",remote.Url + Api]);
        await site.Post("/api/archive/cds-token", new {token=Token});
        var catalog = await site.Get(Catalog("cds"));
        Assert.True(catalog.GetArrayLength() >= 2);
        await site.Post("/api/archive/download", new {key=CdsKey});
        await WaitRow(site,"cds",CdsKey,"downloaded");
        Assert.Equal(state.Payload, await File.ReadAllBytesAsync(folder.At("era5","era5-cds-lsp-20230102.grib")));
        Assert.Null(state.StorageToken);
        Assert.Equal("large_scale_precipitation", state.Inputs.Single().GetProperty("variable")[0].GetString());
        Assert.Equal(24,state.Inputs.Single().GetProperty("time").GetArrayLength());
        Assert.Equal(24,(await site.Get(TestSite.MainCatalog)).GetProperty("available_hours").GetInt32());
        var frames = await Task.WhenAll(Enumerable.Range(0,24).Select(hour=>ArchiveReadingTests.Values(site,hour)));
        Assert.All(frames.Where((_,hour)=>hour!=8), cells=>Assert.All(cells,value=>Assert.Equal(7,value,4)));
        Assert.Contains(0f, frames[8]);
        Assert.Contains(frames[8],float.IsNaN);
    }

    [Fact]
    public async Task CdsPausedRequestAndTokenSurviveRestartAndCanBeCleared()
    {
        using var folder = new TestDirectory();
        var state = new CdsState { Waiting = true };
        await using var remote = await CdsServer(state);
        var options = new[] {"--Era5:CdsBaseUrl",remote.Url + Api};
        await using (var site = await TestSite.StartAsync(folder, options))
        {
            await site.Post("/api/archive/cds-token", new {token=Token});
            await site.Get(Catalog("cds"));
            await site.Post("/api/archive/download",new {key=CdsKey});
            await WaitRow(site,"cds",CdsKey,"waiting");
            await site.Post("/api/archive/cancel",new {key=CdsKey});
            await WaitRow(site,"cds",CdsKey,"paused","cancelled");
            await site.Post("/api/archive/download",new {key=CdsKey});
            await WaitRow(site,"cds",CdsKey,"waiting");
        }
        Assert.Single(state.Inputs);
        state.Waiting=false;
        await using (var restarted = await TestSite.StartAsync(folder, options))
        {
            Assert.True((await restarted.Get("/api/archive/settings")).GetProperty("cds_configured").GetBoolean());
            await WaitRow(restarted, "cds", CdsKey, "downloaded");
            await restarted.Post("/api/archive/cds-token", new {token=""});
        }
        await using var cleared = await TestSite.StartAsync(folder, options);
        Assert.False((await cleared.Get("/api/archive/settings")).GetProperty("cds_configured").GetBoolean());
        Assert.False(File.Exists(folder.At("era5",".meteo-settings","cds-token.bin")));
        Assert.Single(state.Inputs);
    }

    [Fact]
    public async Task CdsResumesTheSameResultFromPersistedBytesAfterRestart()
    {
        using var folder = new TestDirectory();
        const int prefix = 128;
        const string name = "era5-cds-lsp-20230102.grib";
        var state = new CdsState { Waiting = true };
        await using var remote = await CdsServer(state);
        var options = new[] {"--Era5:CdsBaseUrl",remote.Url + Api,"--Era5:CdsToken",Token};
        await using (var site = await TestSite.StartAsync(folder,options))
        {
            await site.Get(Catalog("cds"));
            await site.Post("/api/archive/download",new {key=CdsKey});
            await WaitRow(site,"cds",CdsKey,"waiting");
        }
        using var receipt = JsonDocument.Parse(await File.ReadAllTextAsync(folder.At("era5",name+".cds-request.json")));
        var job = receipt.RootElement.GetProperty("id").GetString();
        await File.WriteAllBytesAsync(folder.At("era5",name+".partial"),state.Payload[..prefix]);
        await File.WriteAllTextAsync(folder.At("era5",name+".download.json"), JsonSerializer.Serialize(new
        {
            key=CdsKey,url=remote.Url+"/result/"+job,etag="",bytes=state.Payload.Length
        }));
        state.Waiting = false;
        await using (var restarted = await TestSite.StartAsync(folder,options))
            await WaitRow(restarted,"cds",CdsKey,"downloaded");
        Assert.Single(state.Inputs);
        Assert.Equal(prefix,Assert.Single(state.Ranges));
        Assert.Equal(state.Payload,await File.ReadAllBytesAsync(folder.At("era5",name)));
    }

    [Fact]
    public async Task ArchiveDownloadsWaitForTheSameCdsSlot()
    {
        using var folder = new TestDirectory();
        var state = new CdsState { Waiting = true };
        await using var remote = await CdsServer(state);
        using var cds = new CdsArchive(remote.Url + Api, Token, folder.At("cds-token.bin"));
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        var files = CdsArchive.List(2023, 1);
        var first = cds.ResolveAsync(files.Single(file => file.Key == CdsKey), folder.Path, _ => { }, deadline.Token);
        try
        {
            await state.FirstPoll.Task.WaitAsync(deadline.Token);
            var second = cds.ResolveAsync(files.Single(file => file.Key == "cds:2023-01-03"),
                folder.Path, _ => { }, deadline.Token);
            await Task.Delay(200, deadline.Token);
            Assert.Equal("02", Assert.Single(state.Inputs).GetProperty("day")[0].GetString());
            state.Waiting = false;
            await Task.WhenAll(first, second);
            Assert.Equal(new[] { "02", "03" }, state.Inputs.Select(input => input.GetProperty("day")[0].GetString()));
        }
        finally { state.Waiting = false; }
    }

    [Fact]
    public async Task RejectedArchiveExplainsTheQueueLimitAndCanBeRetried()
    {
        using var folder = new TestDirectory();
        var state = new CdsState { RejectedVariable = "large_scale_precipitation" };
        await using var remote = await CdsServer(state);
        using var cds = new CdsArchive(remote.Url + Api, Token, folder.At("cds-token.bin"));
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        var file = CdsArchive.List(2023, 1).Single(file => file.Key == CdsKey);
        Task<RemoteEra5File> Resolve() => cds.ResolveAsync(file, folder.Path, _ => { }, deadline.Token);

        var error = await Assert.ThrowsAsync<CdsAccessException>(Resolve);
        Assert.Equal("queue_limit", error.Code);
        Assert.Equal(CdsArchive.RequestsUrl, error.ActionUrl);
        Assert.Single(state.Inputs);
        Assert.False(File.Exists(folder.At(file.Name + ".cds-request.json")));

        state.RejectedVariable = null;
        Assert.Equal(state.Payload.Length, (await Resolve()).Bytes);
        Assert.Equal(2, state.Inputs.Count);
    }

    [Fact]
    public async Task NewCdsRequestWaitsForAPausedRemoteJobAfterRestart()
    {
        using var folder = new TestDirectory();
        var state = new CdsState { Waiting = true };
        await using var remote = await CdsServer(state);
        var tokenPath = folder.At("cds-token.bin");
        var files = CdsArchive.List(2023, 1);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        using (var first = new CdsArchive(remote.Url + Api, Token, tokenPath))
        using (var pause = CancellationTokenSource.CreateLinkedTokenSource(deadline.Token))
        {
            var paused = first.ResolveAsync(files.Single(file => file.Key == CdsKey), folder.Path, _ => { }, pause.Token);
            await state.FirstPoll.Task.WaitAsync(deadline.Token);
            pause.Cancel();
            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => paused);
        }

        using var restarted = new CdsArchive(remote.Url + Api, Token, tokenPath);
        var next = restarted.ResolveAsync(files.Single(file => file.Key == "cds:2023-01-03"), folder.Path, _ => { }, deadline.Token);
        try
        {
            await Task.Delay(200, deadline.Token);
            Assert.Single(state.Inputs);
            state.Waiting = false;
            await next;
            Assert.Equal(new[] { "02", "03" }, state.Inputs.Select(input => input.GetProperty("day")[0].GetString()));
        }
        finally { state.Waiting = false; }
    }

    [Theory]
    [InlineData(401,"invalid_token","Invalid credentials")]
    [InlineData(403,"licence_required","Required licences not accepted")]
    [InlineData(403,"forbidden","Forbidden")]
    [InlineData(429,"queue_limit",QueueLimit)]
    public async Task CdsDistinguishesAccessErrors(int status,string code,string detail)
    {
        using var folder = new TestDirectory();
        var state = new CdsState { Denied = status, Detail = detail };
        await using var remote = await CdsServer(state);
        await using var site = await TestSite.StartAsync(folder, ["--Era5:CdsBaseUrl",remote.Url + Api,"--Era5:CdsToken",Token]);
        await site.Get(Catalog("cds"));
        await site.Post("/api/archive/download",new {key=CdsKey});
        var row = await WaitRow(site, "cds", CdsKey, "failed");
        Assert.Equal(code, row.GetProperty("error_code").GetString());
        Assert.False(File.Exists(folder.At("era5","era5-cds-lsp-20230102.grib")));
        if (code == "licence_required")
            Assert.Equal(CdsArchive.LicenceUrl, row.GetProperty("action_url").GetString());
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task CdsRejectsUntrustedStorageAndCanRepeatExpiredResults(bool untrusted)
    {
        using var folder = new TestDirectory();
        var state = new CdsState { Untrusted = untrusted, Expire = !untrusted };
        await using var remote = await CdsServer(state);
        await using var site = await TestSite.StartAsync(folder, ["--Era5:CdsBaseUrl",remote.Url + Api,"--Era5:CdsToken",Token]);
        await site.Get(Catalog("cds"));
        await site.Post("/api/archive/download",new {key=CdsKey});
        await WaitRow(site,"cds",CdsKey,"failed");
        Assert.False(File.Exists(folder.At("era5","era5-cds-lsp-20230102.grib")));
        if (untrusted)
        {
            Assert.Equal(0, state.StorageCalls);
            return;
        }
        state.Expire=false;
        await site.Post("/api/archive/download",new {key=CdsKey});
        await WaitRow(site,"cds",CdsKey,"downloaded");
        Assert.Equal(2,state.Inputs.Count);
    }

    private static string Catalog(string source) => "/api/archive/files?year=2023&month=1&source=" + source;
    private static string FirstVariable(JsonElement input) => input.GetProperty("variable")[0].GetString()!;

    private static async Task<JsonElement> WaitRow(TestSite site, string source,string key,params string[] states)
    {
        static JsonElement Find(JsonElement items, string id) =>
            items.EnumerateArray().Single(row => row.GetProperty("key").GetString()==id);
        var list = await site.WaitFor(Catalog(source), items =>
        {
            var row = Find(items,key);
            var state = row.GetProperty("state").GetString()!;
            if (state == "failed" && !states.Contains(state)) throw new InvalidDataException(row.GetRawText());
            return states.Contains(state);
        });
        return Find(list,key);
    }

    private static RangeItemHeaderValue Range(HttpContext context) =>
        RangeHeaderValue.Parse(context.Request.Headers.Range.ToString()).Ranges.Single();

    private static async Task WriteData(HttpContext context, byte[] payload,bool partial)
    {
        var range = Range(context);
        var from = partial ? checked((int)range.From!.Value) : 0;
        var to = partial ? checked((int)range.To!.Value) : payload.Length - 1;
        context.Response.StatusCode=partial ? 206 : 200;
        context.Response.ContentLength=to-from+1;
        if (partial) context.Response.Headers.ContentRange=$"bytes {from}-{to}/{payload.Length}";
        await context.Response.Body.WriteAsync(payload.AsMemory(from,to-from+1),context.RequestAborted);
    }

    private sealed class CdsState
    {
        public volatile bool Waiting, Untrusted, Expire;
        public volatile string? RejectedVariable;
        public TaskCompletionSource FirstPoll { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public bool Range {get; init;} = true;
        public int Denied {get; init;}
        public string Detail {get; init;} = "";
        public string? StorageToken;
        public int StorageCalls;
        public ConcurrentQueue<long> Ranges {get;} = new();
        public ConcurrentQueue<JsonElement> Inputs {get;}=new();
        public byte[] Payload {get;}=Enumerable.Range(0,24).SelectMany(hour=>RasterFixtures.Grib(Day.AddHours(hour),
            hour==8 ? [0,.007f,.007f,.007f,.007f,float.NaN] : Enumerable.Repeat(.007f,6).ToArray())).ToArray();
    }

    private static Task<TestRemote> CdsServer(CdsState state) => TestRemote.StartAsync(app =>
    {
        var jobs = new ConcurrentDictionary<string,string>();
        app.MapPost(Api+"/processes/{dataset}/execution",async (HttpContext context) =>
        {
            if (state.Denied!=0) return Results.Json(new {detail=state.Detail},statusCode:state.Denied);
            if (context.Request.Headers["PRIVATE-TOKEN"]!=Token) return Results.Unauthorized();
            var request=await context.Request.ReadFromJsonAsync<JsonElement>();
            var input = request.GetProperty("inputs");
            state.Inputs.Enqueue(input);
            var id=Guid.NewGuid().ToString("N");
            jobs.TryAdd(id,FirstVariable(input));
            return Results.Json(new {jobID=id,status="accepted"}, statusCode:201);
        });
        app.MapGet(Api+"/jobs/{id}", (string id) =>
        {
            if (!jobs.TryGetValue(id, out var variable)) return Results.NotFound();
            state.FirstPoll.TrySetResult();
            return Results.Json(new {status=variable==state.RejectedVariable?"rejected":state.Waiting?"accepted":"successful"});
        });
        app.MapGet(Api+"/jobs/{id}/results", (HttpContext context,string id) =>
        {
            if (state.Expire || !jobs.TryGetValue(id, out var variable)) return Results.NotFound();
            if (variable == state.RejectedVariable)
                return Results.Json(new {title="The job has been rejected",traceback=QueueLimit}, statusCode:400);
            return Results.Json(new {asset=new {value=new Dictionary<string,object>{
                ["href"] = state.Untrusted?"https://example.com/invalid.grib":$"http://{context.Request.Host}/result/{id}",
                ["file:size"]=state.Payload.Length}}});
        });
        app.MapGet("/result/{id}",async context =>
        {
            Interlocked.Increment(ref state.StorageCalls);
            state.StorageToken=context.Request.Headers["PRIVATE-TOKEN"].FirstOrDefault();
            state.Ranges.Enqueue(Range(context).From!.Value);
            await WriteData(context,state.Payload,state.Range);
        });
    });
}
