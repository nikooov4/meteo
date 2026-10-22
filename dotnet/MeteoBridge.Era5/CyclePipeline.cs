using System.Diagnostics;

namespace MeteoBridge.Era5;

internal sealed class CyclePipeline : IDisposable
{
    private sealed record Entry(Task<byte[]> Payload, CancellationTokenSource Cancellation)
    {
        public long Access { get; set; }
    }

    private readonly Era5Index index;
    private readonly ReaderPool pool;
    private readonly int capacity;
    private readonly object gate = new();
    private readonly Dictionary<string, Entry> cache = [];
    private readonly Dictionary<string, int> positions;
    private readonly CancellationTokenSource shutdown = new();
    private long clock, reads, hits, cancelled, requests;
    private double readSeconds;
    private bool disposed;

    public CyclePipeline(Era5Index index, string root, int workers, int capacity)
    {
        this.index = index;
        this.capacity = capacity;
        pool = new ReaderPool(root, workers);
        positions = index.OrderedCycles.Select((cycle, position) => (cycle.Key, position)).ToDictionary(pair => pair.Key, pair => pair.position);
    }

    private async Task<byte[]> LoadAsync(string key, CancellationToken cancellation)
    {
        var started = Stopwatch.GetTimestamp();
        var payload = await pool.ReadAsync(index.Cycles[key], cancellation);
        lock (gate)
        {
            reads++;
            readSeconds += Stopwatch.GetElapsedTime(started).TotalSeconds;
        }
        return payload;
    }

    private Entry Ensure(string key, HashSet<string> wanted)
    {
        if (cache.TryGetValue(key, out var existing))
        {
            if (!existing.Payload.IsFaulted && !existing.Payload.IsCanceled)
            {
                existing.Access = ++clock;
                return existing;
            }
            Remove(key);
        }
        while (cache.Count >= capacity)
        {
            var victim = cache.Where(pair => !wanted.Contains(pair.Key)).MinBy(pair => pair.Value.Access);
            if (victim.Key is null) throw new InvalidOperationException("Prefetch window exceeds cache budget");
            Remove(victim.Key);
        }
        var cancellation = CancellationTokenSource.CreateLinkedTokenSource(shutdown.Token);
        var task = LoadAsync(key, cancellation.Token);
        _ = task.ContinueWith(failed => { _ = failed.Exception; }, TaskContinuationOptions.OnlyOnFaulted);
        var entry = new Entry(task, cancellation) { Access = ++clock };
        cache.Add(key, entry);
        return entry;
    }

    private void Remove(string key)
    {
        var entry = cache[key];
        if (!entry.Payload.IsCompleted)
        {
            cancelled++;
            entry.Cancellation.Cancel();
        }
        entry.Cancellation.Dispose();
        cache.Remove(key);
    }

    public void Prepare(int hour, int endHour)
    {
        if (hour < 0 || hour >= index.Hours || endHour <= hour || endHour > index.Hours) throw new ArgumentException("Час вне диапазона архива.");
        if (!index.Records.TryGetValue(index.Start + hour * 3600L, out var record)) return;
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            var wanted = new HashSet<string> { record.Key };
            foreach (var next in index.OrderedCycles.Skip(positions[record.Key] + 1).Take(index.Lookahead))
                if (next.Epoch < index.Start + endHour * 3600L) wanted.Add(next.Key);
            foreach (var stale in cache.Where(pair => !wanted.Contains(pair.Key) && !pair.Value.Payload.IsCompleted).Select(pair => pair.Key).ToArray())
                Remove(stale);
            Ensure(record.Key, wanted);
            foreach (var next in wanted.Where(key => key != record.Key)) Ensure(next, wanted);
        }
    }

    public async Task<(byte[] Bytes, bool Available, long? Cycle)> FrameAsync(int hour, int endHour, bool prefetch, CancellationToken cancellation)
    {
        if (hour < 0 || hour >= index.Hours || endHour <= hour || endHour > index.Hours) throw new ArgumentException("Час вне диапазона архива.");
        var epoch = index.Start + hour * 3600L;
        Interlocked.Increment(ref requests);
        if (!index.Records.TryGetValue(epoch, out var record))
        {
            var empty = new float[index.Cells];
            Array.Fill(empty, float.NaN);
            var bytes = new byte[index.Cells * 4];
            Buffer.BlockCopy(empty, 0, bytes, 0, bytes.Length);
            return (bytes, false, null);
        }
        index.Cycles[record.Key].Source.Validate();
        if (!prefetch) Prepare(hour, endHour);
        Task<byte[]> payload;
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            var wanted = new HashSet<string> { record.Key };
            if (cache.TryGetValue(record.Key, out var cached) && cached.Payload.IsCompletedSuccessfully) hits++;
            payload = Ensure(record.Key, wanted).Payload;
        }
        var cycle = await payload.WaitAsync(cancellation);
        index.Cycles[record.Key].Source.Validate();
        var frame = cycle.AsSpan(record.Step * index.Cells * 4, index.Cells * 4).ToArray();
        var any = false;
        for (var offset = 0; offset < frame.Length; offset += 4)
            if (float.IsFinite(BitConverter.ToSingle(frame, offset))) { any = true; break; }
        return (frame, any, record.CycleEpoch);
    }

    public object Metrics()
    {
        lock (gate)
            return new { frame_requests = requests, cycle_reads = reads, cache_hits = hits, cached_cycles = cache.Count,
                ready_cycles = cache.Values.Count(entry => entry.Payload.IsCompletedSuccessfully),
                queued_cycles = cache.Values.Count(entry => !entry.Payload.IsCompleted),
                cache_limit = capacity, active_workers = pool.Active, peak_parallel_workers = pool.Peak,
                cancelled_cycles = cancelled, cycle_read_seconds = readSeconds,
                cached_bytes = cache.Values.Where(entry => entry.Payload.IsCompletedSuccessfully).Sum(entry => (long)entry.Payload.Result.Length),
                process_rss = Environment.WorkingSet };
    }

    public void Dispose()
    {
        lock (gate)
        {
            if (disposed) return;
            disposed = true;
            shutdown.Cancel();
            foreach (var key in cache.Keys.ToArray()) Remove(key);
        }
        pool.Dispose();
        shutdown.Dispose();
    }
}
