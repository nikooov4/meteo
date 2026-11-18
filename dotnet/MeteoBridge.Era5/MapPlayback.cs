using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace MeteoBridge.Era5;

internal sealed record PlaybackGrid(double[] Latitude, double[] Longitude);
internal sealed record PlaybackStep(long Start, long End, string Kind, string Grid, int Index);

internal sealed class MapPlayback(ArchiveSession session, MapPriorities priorities, string data)
{
    private readonly object gate = new();
    private PlaybackView? view;

    public PlaybackView Get(string scope = "all")
    {
        if (scope != "all") throw new ArgumentException("Неизвестный архив карты.");
        var era5 = Era5Index.Files(data).Length > 0 ? session.ForViewer() : null;
        var order = MapPriorities.EffectiveOrder(priorities.Load());
        var signature = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(
            (era5?.Index.Sha ?? "") + string.Join('|', order))));
        lock (gate)
        {
            if (view is null || view.Sha != signature || !ReferenceEquals(view.Era5, era5))
                view = new PlaybackView(signature, era5, order);
            return view;
        }
    }

    public async Task<byte[]> FrameAsync(PlaybackView view, int index, bool prefetch, HttpResponse response, CancellationToken cancellation)
    {
        if (index < 0 || index >= view.Steps.Count) throw new ArgumentException("Кадр вне выбранного периода.");
        var step = view.Steps[index];
        var grid = view.Grids[step.Grid];
        byte[] bytes;
        object sources;
        bool available;
        if (step.Kind == "era5")
        {
            var field = await view.Era5!.Pipeline.FrameAsync(step.Index, view.Era5.Index.Hours, prefetch, cancellation);
            bytes = field.Bytes; sources = field.Sources; available = field.Available;
        }
        else
        {
            var values = Enumerable.Repeat(float.NaN, grid.Latitude.Length * grid.Longitude.Length).ToArray();
            bytes = new byte[values.Length * 4]; Buffer.BlockCopy(values, 0, bytes, 0, bytes.Length);
            sources = Array.Empty<object>(); available = false;
        }
        response.Headers["X-Data-Available"] = available ? "true" : "false";
        response.Headers["X-Cycle-UTC"] = Era5Index.Iso(step.Start);
        response.Headers["X-Frame-Sources"] = Uri.EscapeDataString(JsonSerializer.Serialize(sources));
        response.Headers["X-Manifest-SHA256"] = view.Sha;
        response.Headers.CacheControl = "no-store";
        return bytes;
    }
}

internal sealed class PlaybackView
{
    public string Sha { get; }
    public ArchiveView? Era5 { get; }
    public string[] Order { get; }
    public List<PlaybackStep> Steps { get; } = [];
    public Dictionary<string, PlaybackGrid> Grids { get; } = [];
    public long Start { get; }
    public long End { get; }
    public long[][] Coverage { get; }
    public PlaybackGrid FirstGrid => Grids["era5"];

    public PlaybackView(string sha, ArchiveView? era5, string[] order)
    {
        Sha = sha; Era5 = era5; Order = order;
        Grids["era5"] = era5 is null
            ? new PlaybackGrid(Enumerable.Range(-90, 181).Select(x => (double)x).ToArray(),
                Enumerable.Range(-180, 360).Select(x => (double)x).ToArray())
            : new PlaybackGrid(era5.Index.Latitude, era5.Index.Longitude);
        if (era5 is null)
        {
            Start = End = DateTimeOffset.UtcNow.ToUnixTimeSeconds() / 3600 * 3600;
            Coverage = []; return;
        }
        Start = era5.Index.Start;
        End = era5.Index.End;
        for (var hour = Start; hour < End; hour += 3600)
        {
            var kind = era5.Index.Records.ContainsKey(hour) ? "era5" : "empty";
            Steps.Add(new(hour, hour + 3600, kind, "era5", checked((int)((hour - Start) / 3600))));
        }
        var ranges = new List<long[]>();
        foreach (var step in Steps.Where(step => step.Kind != "empty"))
            if (ranges.Count > 0 && ranges[^1][1] == step.Start) ranges[^1][1] = step.End;
            else ranges.Add([step.Start, step.End]);
        Coverage = ranges.ToArray();
    }

    public object Catalog() => new
    {
        kind = "playback", manifest_sha256 = Sha, streaming = true,
        grid_shape = new[] { FirstGrid.Latitude.Length, FirstGrid.Longitude.Length },
        grids = Grids.ToDictionary(item => item.Key, item => new { latitude = item.Value.Latitude, longitude = item.Value.Longitude }),
        frames = Steps.Select(step => new { start_utc = Era5Index.Iso(step.Start), end_utc = Era5Index.Iso(step.End),
            kind = step.Kind, grid = step.Grid, data_start_utc = Era5Index.Iso(step.Start), data_end_utc = Era5Index.Iso(step.End) }),
        frame_bytes = FirstGrid.Latitude.Length * FirstGrid.Longitude.Length * 4,
        file_count = Era5?.Index.Sources.Count ?? 0,
        data_bytes = Era5?.Index.Sources.Sum(file => file.Bytes) ?? 0,
        available_hours = Coverage.Sum(pair => (pair[1] - pair[0]) / 3600), gap_hours = (End - Start) / 3600 - Coverage.Sum(pair => (pair[1] - pair[0]) / 3600),
        start_epoch = Start, color_max_mm = 50, archive_priority = Order,
        available_ranges = Coverage.Select(pair => pair.Select(Era5Index.Iso).ToArray()),
        members = new[] { new { member = 0, hours = Steps.Count, start_utc = Era5Index.Iso(Start), end_utc = Era5Index.Iso(End) } }
    };

    public object Selection(string? start = null, string? end = null)
    {
        var a = start is null ? Coverage.FirstOrDefault()?[0] ?? Start : DateTimeOffset.Parse(start).ToUnixTimeSeconds();
        var b = end is null ? Coverage.FirstOrDefault()?[1] ?? End : DateTimeOffset.Parse(end).ToUnixTimeSeconds();
        if (a < Start || b > End || a > b || (Steps.Count > 0 && a == b) || a % 3600 != 0 || b % 3600 != 0)
            throw new ArgumentException("Выберите целые часы внутри диапазона карты.");
        var first = Steps.FindIndex(step => step.End > a);
        var last = Steps.FindLastIndex(step => step.Start < b);
        return new { first_hour = Math.Max(0, first), hours = first < 0 ? 0 : last - first + 1, member = 0,
            start_utc = Era5Index.Iso(a), end_utc = Era5Index.Iso(b), manifest_sha256 = Sha };
    }
}
