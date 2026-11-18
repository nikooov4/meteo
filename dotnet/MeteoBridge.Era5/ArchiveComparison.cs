namespace MeteoBridge.Era5;

internal sealed record ComparisonFile(string Id, string Name, string Format, string StartUtc, string EndUtc,
    int CoveredHours);

internal sealed class ArchiveComparison(string data, string root, ArchiveSession session, GraphCastService graphcast)
{
    public ComparisonFile[] Files(string forecast)
    {
        var first = ForecastStart(forecast);
        if (Era5Index.Files(data).Length == 0) return [];
        var index = session.ForViewer().Index;
        var hours = new Dictionary<SourceFile, List<long>>();
        for (var epoch = first; epoch < first + 86400; epoch += 3600)
        {
            if (!index.Records.TryGetValue(epoch, out var records)) continue;
            foreach (var source in records.Select(record => index.Cycles[record.Key].Source).Distinct())
            {
                if (!hours.TryGetValue(source, out var covered)) hours[source] = covered = [];
                covered.Add(epoch);
            }
        }
        return hours.Select(pair => new ComparisonFile(ArchiveFiles.Id(pair.Key.Path), pair.Key.Name, pair.Key.Format,
            Era5Index.Iso(pair.Value[0]), Era5Index.Iso(pair.Value[^1] + 3600), pair.Value.Count))
            .OrderByDescending(file => file.CoveredHours).ThenBy(file => file.Name, StringComparer.Ordinal).ToArray();
    }

    public object Grid(string file)
    {
        var index = Open(file);
        return new { latitude = index.Latitude, longitude = index.Longitude };
    }

    public async Task<byte[]> FrameAsync(string forecast, string file, int step, CancellationToken cancellation)
    {
        if (step is < 0 or > 3) throw new ArgumentException("Кадр сравнения: 0..3.");
        var first = ForecastStart(forecast) + step * 21600L;
        var index = Open(file);
        using var pipeline = new CyclePipeline(index, root, 1, 2);
        var sums = await AccumulateAsync(first, index, pipeline, cancellation);
        var result = new byte[sums.Length * sizeof(float)];
        Buffer.BlockCopy(sums, 0, result, 0, result.Length);
        return result;
    }

    internal static async Task<float[]> AccumulateAsync(long first, Era5Index index, CyclePipeline pipeline, CancellationToken cancellation)
    {
        var sums = new float[index.Cells];
        if (Enumerable.Range(0, 6).All(hour => index.Records.ContainsKey(first + hour * 3600L)))
        {
            var offset = checked((int)((first - index.Start) / 3600L));
            for (var hour = offset; hour < offset + 6; hour++)
            {
                var frame = await pipeline.FrameAsync(hour, offset + 6, false, cancellation);
                AddHour(sums, frame.Bytes);
            }
        }
        else Array.Fill(sums, float.NaN);
        return sums;
    }

    internal static void AddHour(float[] sums, byte[] frame)
    {
        var values = System.Runtime.InteropServices.MemoryMarshal.Cast<byte, float>(frame);
        for (var cell = 0; cell < sums.Length; cell++) sums[cell] += values[cell];
    }

    private long ForecastStart(string forecast) =>
        DateTimeOffset.Parse(graphcast.Metadata(forecast).GetProperty("start_utc").GetString()!).ToUnixTimeSeconds();

    private Era5Index Open(string id)
    {
        var path = Era5Index.Files(data).SingleOrDefault(path => ArchiveFiles.Id(path) == id)
            ?? throw new ArgumentException("Файл ERA5 не найден. Обновите список архивов.");
        lock (NativeNetCdf.Gate) return new Era5Index(path, [-180, 180, -90, 90], 100_000, 256, 0);
    }
}
