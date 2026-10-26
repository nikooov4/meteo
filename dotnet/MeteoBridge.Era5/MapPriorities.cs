using System.Text.Json;
using System.Text.RegularExpressions;

namespace MeteoBridge.Era5;

internal sealed record MapPriorityRequest(string[]? Order);
internal sealed record MapArchive(string Id, string Name, string Format);

internal sealed class MapPriorities
{
    public static readonly MapArchive[] Archives =
    [
        new("amazon", "Amazon S3 · NCAR ERA5", "NC"),
        new("google", "Google · ARCO-ERA5", "NC"),
        new("cds", "Copernicus CDS · ERA5", "GRIB")
    ];
    public static string[] DefaultOrder => Archives.Select(archive => archive.Id).ToArray();
    public static string[] EffectiveOrder(string[] order) => order.Length == 0 ? DefaultOrder : order;
    private readonly string settingsPath, dataPath;

    public MapPriorities(string data)
    {
        data = Path.GetFullPath(data);
        dataPath = data;
        var directory = File.Exists(data) ? Path.GetDirectoryName(data)! : data;
        settingsPath = Path.Combine(directory, ".meteo-settings", "map-priority.json");
    }

    public string[] Load()
    {
        if (!File.Exists(settingsPath)) return [];
        try
        {
            var order = JsonSerializer.Deserialize<string[]>(File.ReadAllText(settingsPath)) ?? [];
            // File-level settings from the previous UI do not define an archive order.
            if (order.Length == 0 || order.All(id => id is not null && Regex.IsMatch(id, "^[a-f0-9]{64}$"))) return [];
            if (!Valid(order)) throw new JsonException();
            return order;
        }
        catch (JsonException error) { throw new InvalidDataException("Повреждены настройки приоритета архивов.", error); }
    }

    private static bool Valid(string[] order) => order.Length == Archives.Length &&
        order.Distinct().Count() == Archives.Length && order.All(DefaultOrder.Contains);

    public static SourceFile[] Order(IEnumerable<SourceFile> files, string[] order)
    {
        var ranks = EffectiveOrder(order).Select((id, rank) => (id, rank)).ToDictionary(item => item.id, item => item.rank);
        return files.OrderBy(file => ranks.GetValueOrDefault(file.ArchiveId ?? "", int.MaxValue))
            .ThenBy(file => file.Priority).ThenBy(file => file.Path, StringComparer.Ordinal).ToArray();
    }

    public object View()
    {
        var files = Era5Index.Files(dataPath).Select(SourceFile.Create).ToArray();
        var order = EffectiveOrder(Load());
        return new
        {
            custom = !order.SequenceEqual(DefaultOrder),
            archives = order.Select(id =>
            {
                var archive = Archives.Single(archive => archive.Id == id);
                var matching = files.Where(file => file.ArchiveId == id).ToArray();
                return new { id, name = archive.Name, format = archive.Format, file_count = matching.Length, bytes = matching.Sum(file => file.Bytes) };
            }).ToArray()
        };
    }

    public void Save(string[]? order)
    {
        if (order is null || order.Length != 0 && !Valid(order))
            throw new ArgumentException("Укажите каждый архив один раз: Amazon S3, Google ARCO и Copernicus CDS.");
        Directory.CreateDirectory(Path.GetDirectoryName(settingsPath)!);
        File.WriteAllText(settingsPath + ".tmp", JsonSerializer.Serialize(order));
        File.Move(settingsPath + ".tmp", settingsPath, true);
    }
}
