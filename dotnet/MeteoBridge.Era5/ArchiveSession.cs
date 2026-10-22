namespace MeteoBridge.Era5;

internal sealed record ArchiveView(Era5Index Index, CyclePipeline Pipeline);

internal sealed class ArchiveSession(string data, double[] bbox, int maxCells, int maxReadMiB,
    int lookahead, string root, int workers, int capacity) : IDisposable
{
    private readonly object gate = new();
    private ArchiveView? current;
    private long revision, loadedRevision = -1;

    public ArchiveView Current => Get(false);

    public ArchiveView ForViewer() => Get(true);

    public void Changed() => Interlocked.Increment(ref revision);

    private ArchiveView Get(bool refresh)
    {
        lock (gate)
        {
            var version = Interlocked.Read(ref revision);
            if (current is null || refresh && loadedRevision != version)
            {
                Era5Index index;
                lock (NativeNetCdf.Gate) index = new Era5Index(data, bbox, maxCells, maxReadMiB, lookahead);
                var replacement = new ArchiveView(index, new CyclePipeline(index, root, workers, capacity));
                current?.Pipeline.Dispose();
                current = replacement;
                loadedRevision = version;
            }
            return current;
        }
    }

    public void Dispose()
    {
        lock (gate) current?.Pipeline.Dispose();
    }
}
