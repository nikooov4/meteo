using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace MeteoBridge.Era5;

internal sealed record SourceFile(string Path, long Bytes, long ModifiedTicks)
{
    public void Validate()
    {
        var info = new FileInfo(Path);
        if (!info.Exists || info.Length != Bytes || info.LastWriteTimeUtc.Ticks != ModifiedTicks)
            throw new IOException("Файл ERA5 изменился. Повторно откройте архив.");
    }
}

internal sealed record CycleRead(SourceFile Source, int Cycle, int Steps, int Height, int Width,
    int[] Rows, int[] Columns, int MaxReadMiB);
internal sealed record HourRecord(string Key, int Step, long CycleEpoch);

internal sealed class Era5Index
{
    public Dictionary<long, HourRecord> Records { get; } = [];
    public Dictionary<string, CycleRead> Cycles { get; } = [];
    public List<SourceFile> Sources { get; } = [];
    public List<(long Epoch, string Key)> OrderedCycles { get; } = [];
    public double[] Latitude { get; }
    public double[] Longitude { get; }
    public double[] Bbox { get; }
    public long Start { get; }
    public long End { get; }
    public int Hours => checked((int)((End - Start) / 3600));
    public string Sha { get; }
    public int Duplicates { get; }
    public int Cells => Latitude.Length * Longitude.Length;
    public List<long[]> Coverage { get; } = [];
    public int Lookahead { get; }

    public static string Iso(long epoch) => DateTimeOffset.FromUnixTimeSeconds(epoch).ToString("yyyy-MM-dd'T'HH:mm:sszzz");

    public Era5Index(string path, double[] bbox, int maxCells, int maxReadMiB, int lookahead)
    {
        if (bbox.Length != 4 || bbox.Any(value => !double.IsFinite(value)) ||
            !(bbox[0] >= -180 && bbox[0] < bbox[1] && bbox[1] <= 180 && bbox[2] >= -90 && bbox[2] < bbox[3] && bbox[3] <= 90))
            throw new ArgumentException("Нужны west < east в [-180,180], south < north в [-90,90].");
        if (maxCells is < 1 or > 1_000_000) throw new ArgumentException("MaxCells: 1..1000000.");
        Bbox = bbox;
        Lookahead = lookahead;
        path = Path.GetFullPath(path);
        var files = Directory.Exists(path) ? Directory.GetFiles(path, "*.nc", SearchOption.AllDirectories)
            : File.Exists(path) && Path.GetExtension(path) == ".nc" ? [path] : [];
        if (files.Length == 0) throw new ArgumentException("Не найдены файлы ERA5 .nc.");
        double[]? rawLatitude = null, rawLongitude = null;
        int[] rows = [], columns = [];
        foreach (var file in files.Order(StringComparer.Ordinal))
        {
            var info = new FileInfo(file);
            var source = new SourceFile(file, info.Length, info.LastWriteTimeUtc.Ticks);
            using var dataset = new NetCdfFile(file);
            var variable = dataset.Variable("LSP");
            var dimensions = dataset.Dimensions(variable);
            if (!dimensions.Select(dimension => dimension.Name).SequenceEqual(new[] { "forecast_initial_time", "forecast_hour", "latitude", "longitude" }) ||
                dataset.Text(variable, "units") != "m" || dataset.Text(variable, "rda_dataset") != "ds633.0")
                throw new InvalidDataException($"{info.Name}: нужен NCAR ERA5 LSP ds633.0 в метрах.");
            var lat = dataset.Axis("latitude");
            var lon = dataset.Axis("longitude");
            if (rawLatitude is null)
            {
                rawLatitude = lat;
                rawLongitude = lon;
                rows = Enumerable.Range(0, lat.Length).Where(index => lat[index] >= bbox[2] && lat[index] <= bbox[3]).OrderBy(index => lat[index]).ToArray();
                columns = Enumerable.Range(0, lon.Length).Where(index => Normalize(lon[index]) >= bbox[0] && Normalize(lon[index]) <= bbox[1]).OrderBy(index => Normalize(lon[index])).ToArray();
                if (rows.Length == 0 || columns.Length == 0) throw new ArgumentException("В области нет ячеек ERA5.");
                var stride = Math.Max(1, (int)Math.Ceiling(Math.Sqrt((double)rows.Length * columns.Length / maxCells)));
                while (((rows.Length + stride - 1) / stride) * ((columns.Length + stride - 1) / stride) > maxCells) stride++;
                rows = rows.Where((_, index) => index % stride == 0).ToArray();
                columns = columns.Where((_, index) => index % stride == 0).ToArray();
            }
            else if (!rawLatitude.SequenceEqual(lat) || !rawLongitude!.SequenceEqual(lon))
                throw new InvalidDataException($"{info.Name}: географическая сетка отличается от остальных файлов.");
            var hours = dataset.Axis("forecast_hour");
            if (hours.Length is < 1 or > 12 || !hours.SequenceEqual(Enumerable.Range(1, hours.Length).Select(value => (double)value)))
                throw new InvalidDataException("Ожидаются почасовые шаги от 1 до 12.");
            if ((long)hours.Length * lat.Length * lon.Length * 4 > maxReadMiB * 1048576L)
                throw new InvalidDataException("Исходный цикл превышает MaxReadMiB. Увеличьте лимит с учётом числа workers.");
            var time = dataset.Variable("forecast_initial_time");
            var calendar = dataset.Text(time, "calendar") ?? "standard";
            if (calendar is not ("standard" or "gregorian" or "proleptic_gregorian")) throw new InvalidDataException("Неподдерживаемый календарь ERA5.");
            var units = dataset.Text(time, "units") ?? "";
            var match = Regex.Match(units, @"^(seconds?|minutes?|hours?|days?) since (.+)$");
            if (!match.Success) throw new InvalidDataException($"Неподдерживаемое время: {units}");
            var origin = DateTimeOffset.Parse(match.Groups[2].Value, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal);
            var multiplier = match.Groups[1].Value[0] switch { 's' => 1, 'm' => 60, 'h' => 3600, _ => 86400 };
            var dates = dataset.Axis("forecast_initial_time");
            if (dimensions[0].Length != dates.Length || dimensions[1].Length != hours.Length || dimensions[2].Length != lat.Length || dimensions[3].Length != lon.Length)
                throw new InvalidDataException("Оси не соответствуют размерам LSP.");
            for (var cycle = 0; cycle < dates.Length; cycle++)
            {
                var seconds = origin.ToUnixTimeSeconds() + dates[cycle] * multiplier;
                if (seconds % 3600 != 0) throw new InvalidDataException("Цикл должен начинаться в целый час UTC.");
                var epoch = checked((long)seconds);
                var key = $"{Sources.Count}:{cycle}";
                var used = false;
                for (var step = 0; step < hours.Length; step++)
                {
                    if (Records.TryAdd(epoch + step * 3600, new HourRecord(key, step, epoch))) used = true;
                    else Duplicates++;
                }
                if (used)
                {
                    Cycles[key] = new CycleRead(source, cycle, hours.Length, lat.Length, lon.Length, rows, columns, maxReadMiB);
                    OrderedCycles.Add((epoch, key));
                }
            }
            source.Validate();
            Sources.Add(source);
        }
        if (Records.Count == 0) throw new InvalidDataException("Нет почасовых данных ERA5.");
        Latitude = rows.Select(index => rawLatitude![index]).ToArray();
        Longitude = columns.Select(index => Normalize(rawLongitude![index])).ToArray();
        Start = Records.Keys.Min();
        End = Records.Keys.Max() + 3600;
        foreach (var epoch in Records.Keys.Order())
        {
            if (Coverage.Count > 0 && Coverage[^1][1] == epoch) Coverage[^1][1] += 3600;
            else Coverage.Add([epoch, epoch + 3600]);
        }
        OrderedCycles.Sort((left, right) => left.Epoch.CompareTo(right.Epoch));
        Sha = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(System.Text.Json.JsonSerializer.Serialize(new { Sources, Bbox, Latitude, Longitude }))));
    }

    private static double Normalize(double longitude) => ((longitude + 180) % 360 + 360) % 360 - 180;

    public object Catalog() => new
    {
        kind = "era5", manifest_sha256 = Sha, file_count = Sources.Count,
        data_bytes = Sources.Sum(source => source.Bytes), grid_shape = new[] { Latitude.Length, Longitude.Length },
        start_epoch = Start, unit = "mm", quantity = "large_scale_precipitation", color_max_mm = 50,
        color_scale_from_full_scan = false, frame_bytes = Cells * 4, available_hours = Records.Count,
        gap_hours = Hours - Records.Count, duplicate_hours = Duplicates,
        available_ranges = Coverage.Select(pair => pair.Select(Iso).ToArray()),
        members = new[] { new { member = 0, first_hour = 0, hours = Hours, start_utc = Iso(Start), end_utc = Iso(End) } },
        semantics = "ERA5 HRES previous-hour amounts; missing hours remain empty",
        streaming = true, lookahead_cycles = Lookahead
    };

    public object Selection(int member, string start, string end)
    {
        static long Stamp(string value)
        {
            if (!Regex.IsMatch(value, @"(Z|[+-]\d{2}:\d{2})$")) throw new ArgumentException("Время требует UTC offset.");
            var stamp = DateTimeOffset.Parse(value, CultureInfo.InvariantCulture);
            if (stamp.Ticks % TimeSpan.TicksPerHour != 0) throw new ArgumentException("Выберите целые часы.");
            return stamp.ToUnixTimeSeconds();
        }
        var first = Stamp(start);
        var last = Stamp(end);
        if (member != 0 || first < Start || first >= last || last > End || first % 3600 != 0 || last % 3600 != 0)
            throw new ArgumentException("Выберите полные часы внутри диапазона ERA5.");
        var available = Records.Keys.Count(epoch => first <= epoch && epoch < last);
        return new { first_hour = (first - Start) / 3600, hours = (last - first) / 3600, member = 0,
            start_utc = Iso(first), end_utc = Iso(last), manifest_sha256 = Sha,
            available_hours = available, gap_hours = (last - first) / 3600 - available };
    }
}
