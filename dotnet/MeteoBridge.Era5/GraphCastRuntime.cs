using System.Diagnostics;
using System.Text;
using System.Text.RegularExpressions;

namespace MeteoBridge.Era5;

internal sealed class GraphCastRuntime(string root)
{
    private readonly string runtime = Path.Combine(root, "runtime", "graphcast");
    private readonly object gate = new();

    private string Python => Path.Combine(runtime, ".venv-gpu", "Scripts", "python.exe");
    private string Script(string name) => Path.Combine(root, "workers", "graphcast", name);
    public bool Available(string name) => File.Exists(Python) && File.Exists(Script(name));

    public ProcessStartInfo Command(string script)
    {
        lock (gate)
        {
            var configuration = Path.Combine(runtime, ".venv-gpu", "pyvenv.cfg");
            var bundledPython = Path.Combine(runtime, "python");
            if (File.Exists(Path.Combine(bundledPython, "python.exe")))
            {
                var content = File.ReadAllText(configuration);
                var rebased = Regex.Replace(content, @"(?m)^home = .*", _ => "home = " + bundledPython);
                if (rebased != content) File.WriteAllText(configuration, rebased);
            }
        }
        var start = new ProcessStartInfo(Python) { WorkingDirectory = runtime, UseShellExecute = false,
            CreateNoWindow = true, RedirectStandardInput = true, RedirectStandardOutput = true,
            RedirectStandardError = true, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
        start.ArgumentList.Add("-u");
        start.ArgumentList.Add(Script(script));
        start.Environment["PYTHONUTF8"] = "1";
        return start;
    }
}
