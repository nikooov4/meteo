using System.Diagnostics;

namespace MeteoBridge.Era5;

internal sealed record FrameSource(string Name, string Format, int Cells);
internal sealed record MapFrame(byte[] Bytes, bool Available, long? Cycle, FrameSource[] Sources);

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
    private readonly Dictionary<string, int> inUse = [];
    private readonly SemaphoreSlim frameReaders;
    private readonly Dictionary<string, int> positions;
    private readonly CancellationTokenSource shutdown = new();
    private long clock, reads, hits, cancelled, requests;
    private double readSeconds;
    private bool disposed;

    public CyclePipeline(Era5Index index, string root, int workers, int capacity)
    {
        this.index = index;
        this.capacity = capacity;
        frameReaders = new SemaphoreSlim(capacity);
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
            var victim = cache.Where(pair => !wanted.Contains(pair.Key) && !inUse.ContainsKey(pair.Key)).MinBy(pair => pair.Value.Access);
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
        if (!index.Records.TryGetValue(index.Start + hour * 3600L, out var records)) return;
        var record = records[0];
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (!cache.ContainsKey(record.Key) && inUse.Count >= capacity) return;
            var wanted = inUse.Keys.ToHashSet();
            wanted.Add(record.Key);
            foreach (var next in index.OrderedCycles.Skip(positions[record.Key] + 1).Take(index.Lookahead))
                if (next.Epoch < index.Start + endHour * 3600L && wanted.Count < capacity) wanted.Add(next.Key);
            foreach (var stale in cache.Where(pair => !wanted.Contains(pair.Key) && !pair.Value.Payload.IsCompleted).Select(pair => pair.Key).ToArray())
                Remove(stale);
            Ensure(record.Key, wanted);
            foreach (var next in wanted.Where(key => key != record.Key)) Ensure(next, wanted);
        }
    }

    public async Task<MapFrame> FrameAsync(int hour, int endHour, bool prefetch, CancellationToken cancellation)
    {
        if (hour < 0 || hour >= index.Hours || endHour <= hour || endHour > index.Hours) throw new ArgumentException("Час вне диапазона архива.");
        var epoch = index.Start + hour * 3600L;
        Interlocked.Increment(ref requests);
        if (!index.Records.TryGetValue(epoch, out var records))
        {
            var empty = new float[index.Cells];
            Array.Fill(empty, float.NaN);
            var bytes = new byte[index.Cells * 4];
            Buffer.BlockCopy(empty, 0, bytes, 0, bytes.Length);
            return new MapFrame(bytes, false, null, []);
        }
        if (!prefetch) Prepare(hour, endHour);
        var result = new float[index.Cells];
        Array.Fill(result, float.NaN);
        var missing = index.Cells;
        var sources = new List<FrameSource>();
        long? primaryCycle = null;
        foreach (var record in records)
        {
            if (missing == 0) break;
            cancellation.ThrowIfCancellationRequested();
            var source = index.Cycles[record.Key].Source;
            source.Validate();
            byte[] cycle;
            await frameReaders.WaitAsync(cancellation);
            var pinned = false;
            try
            {
                Task<byte[]> payload;
                lock (gate)
                {
                    ObjectDisposedException.ThrowIf(disposed, this);
                    inUse[record.Key] = inUse.GetValueOrDefault(record.Key) + 1;
                    pinned = true;
                    var wanted = new HashSet<string> { record.Key };
                    if (cache.TryGetValue(record.Key, out var cached) && cached.Payload.IsCompletedSuccessfully) hits++;
                    payload = Ensure(record.Key, wanted).Payload;
                }
                cycle = await payload.WaitAsync(cancellation);
            }
            finally
            {
                lock (gate)
                    if (pinned && --inUse[record.Key] == 0) inUse.Remove(record.Key);
                frameReaders.Release();
            }
            source.Validate();
            var contributed = 0;
            for (var cell = 0; cell < result.Length; cell++)
            {
                if (float.IsFinite(result[cell])) continue;
                var sample = BitConverter.ToSingle(cycle, (record.Step * index.Cells + cell) * 4);
                if (!float.IsFinite(sample)) continue;
                result[cell] = sample;
                contributed++;
            }
            if (contributed == 0) continue;
            primaryCycle ??= record.CycleEpoch;
            missing -= contributed;
            sources.Add(new FrameSource(source.Name, source.Format, contributed));
        }
        var frame = new byte[index.Cells * 4];
        Buffer.BlockCopy(result, 0, frame, 0, frame.Length);
        return new MapFrame(frame, missing < index.Cells, primaryCycle, sources.ToArray());
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
