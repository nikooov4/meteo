using System.Buffers.Binary;
using System.Diagnostics;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Threading.Channels;

namespace MeteoBridge.Era5;

internal static class WorkerProtocol
{
    public static async Task RunAsync()
    {
        using var input = new StreamReader(Console.OpenStandardInput(), Encoding.UTF8);
        using var output = Console.OpenStandardOutput();
        while (await input.ReadLineAsync() is { } line)
        {
            byte[] payload;
            var failed = false;
            try
            {
                var request = JsonSerializer.Deserialize<CycleRead>(line) ?? throw new InvalidDataException("Empty worker request");
                payload = ReadCycle(request);
            }
            catch (Exception error)
            {
                payload = Encoding.UTF8.GetBytes(error.Message);
                failed = true;
            }
            var header = new byte[4];
            BinaryPrimitives.WriteInt32LittleEndian(header, failed ? -payload.Length : payload.Length);
            await output.WriteAsync(header);
            await output.WriteAsync(payload);
            await output.FlushAsync();
        }
    }

    private static byte[] ReadCycle(CycleRead request)
    {
        request.Source.Validate();
        var length = checked(request.Steps * request.Height * request.Width);
        if ((long)length * 4 > request.MaxReadMiB * 1048576L) throw new InvalidDataException("Worker read budget exceeded");
        using var dataset = new NetCdfFile(request.Source.Path);
        var variable = dataset.Variable("LSP");
        NativeNetCdf.Check(NativeNetCdf.nc_set_var_chunk_cache(dataset.Id, variable, 64 * 1048576, 1009, .5f));
        var raw = new float[length];
        NativeNetCdf.Check(NativeNetCdf.nc_get_vara_float(dataset.Id, variable,
            [(nuint)request.Cycle, 0, 0, 0], [1, (nuint)request.Steps, (nuint)request.Height, (nuint)request.Width], raw));
        var fill = dataset.Numbers(variable, "_FillValue").Concat(dataset.Numbers(variable, "missing_value")).Select(value => (float)value).ToArray();
        if (fill.Length == 0) fill = [9.969209968386869e36f];
        var scale = dataset.Numbers(variable, "scale_factor").FirstOrDefault(1);
        var offset = dataset.Numbers(variable, "add_offset").FirstOrDefault();
        var range = dataset.Numbers(variable, "valid_range");
        var minimum = range.Length == 2 ? range[0] : dataset.Numbers(variable, "valid_min").FirstOrDefault(double.NegativeInfinity);
        var maximum = range.Length == 2 ? range[1] : dataset.Numbers(variable, "valid_max").FirstOrDefault(double.PositiveInfinity);
        var selected = new float[checked(request.Steps * request.Rows.Length * request.Columns.Length)];
        var destination = 0;
        for (var step = 0; step < request.Steps; step++)
        foreach (var row in request.Rows)
        foreach (var column in request.Columns)
        {
            var value = raw[(step * request.Height + row) * request.Width + column];
            var amount = (float)(value * scale + offset) * 1000f;
            selected[destination++] = !float.IsFinite(value) || fill.Contains(value) || value < minimum || value > maximum ||
                !float.IsFinite(amount) || amount < 0 ? float.NaN : amount;
        }
        request.Source.Validate();
        var payload = new byte[selected.Length * 4];
        Buffer.BlockCopy(selected, 0, payload, 0, payload.Length);
        return payload;
    }
}

internal sealed class ReaderWorker(string root) : IDisposable
{
    private Process? process;
    private string lastError = "";

    private void Start()
    {
        if (process is { HasExited: false }) return;
        process?.Dispose();
        var executable = Environment.ProcessPath ?? throw new InvalidOperationException("Cannot find .NET executable");
        var start = new ProcessStartInfo(executable)
        {
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = root,
            StandardInputEncoding = new UTF8Encoding(false)
        };
        if (Path.GetFileNameWithoutExtension(executable).Equals("dotnet", StringComparison.OrdinalIgnoreCase))
            start.ArgumentList.Add(Assembly.GetExecutingAssembly().Location);
        start.ArgumentList.Add("--worker");
        start.ArgumentList.Add("--root");
        start.ArgumentList.Add(root);
        process = Process.Start(start) ?? throw new IOException("Cannot start NetCDF worker");
        process.ErrorDataReceived += (_, args) => { if (args.Data is { } message) lastError = message[..Math.Min(1024, message.Length)]; };
        process.BeginErrorReadLine();
    }

    public async Task<byte[]> ReadAsync(CycleRead request, CancellationToken cancellation)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        timeout.CancelAfter(TimeSpan.FromSeconds(60));
        try
        {
            Start();
            var running = process!;
            await running.StandardInput.WriteLineAsync(JsonSerializer.Serialize(request).AsMemory(), timeout.Token);
            await running.StandardInput.FlushAsync(timeout.Token);
            var header = new byte[4];
            await running.StandardOutput.BaseStream.ReadExactlyAsync(header, timeout.Token);
            var length = BinaryPrimitives.ReadInt32LittleEndian(header);
            var expected = checked(request.Steps * request.Rows.Length * request.Columns.Length * 4);
            if (length != expected && (length >= 0 || length < -65536)) throw new IOException("Invalid worker payload length");
            var payload = new byte[Math.Abs(length)];
            await running.StandardOutput.BaseStream.ReadExactlyAsync(payload, timeout.Token);
            if (length < 0) throw new InvalidDataException(Encoding.UTF8.GetString(payload));
            return payload;
        }
        catch (EndOfStreamException error)
        {
            Dispose();
            throw new IOException($"NetCDF worker stopped: {lastError}", error);
        }
        catch
        {
            Dispose();
            throw;
        }
    }

    public void Dispose()
    {
        if (process is not null)
        {
            if (!process.HasExited) process.Kill(entireProcessTree: true);
            process.Dispose();
            process = null;
        }
    }
}

internal sealed class ReaderPool : IDisposable
{
    private readonly Channel<ReaderWorker> available;
    private readonly ReaderWorker[] workers;
    private int active, peak;
    public int Peak => peak;
    public int Active => active;

    public ReaderPool(string root, int count)
    {
        workers = Enumerable.Range(0, count).Select(_ => new ReaderWorker(root)).ToArray();
        available = Channel.CreateBounded<ReaderWorker>(count);
        foreach (var worker in workers) available.Writer.TryWrite(worker);
    }

    public async Task<byte[]> ReadAsync(CycleRead request, CancellationToken cancellation)
    {
        var worker = await available.Reader.ReadAsync(cancellation);
        var current = Interlocked.Increment(ref active);
        int observed;
        do { observed = peak; } while (current > observed && Interlocked.CompareExchange(ref peak, current, observed) != observed);
        try { return await worker.ReadAsync(request, cancellation); }
        finally
        {
            Interlocked.Decrement(ref active);
            available.Writer.TryWrite(worker);
        }
    }

    public void Dispose()
    {
        available.Writer.TryComplete();
        foreach (var worker in workers) worker.Dispose();
    }
}
