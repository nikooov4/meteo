using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace MeteoBridge.Era5;

internal sealed record SourceFile(string Path, long Bytes, long ModifiedTicks, string? MetadataHash = null, string? ArchiveId = null)
{
    public static SourceFile Create(string path)
    {
        var info = new FileInfo(path);
        var name = info.Name;
        string? archive = name.StartsWith("e5.oper.fc.sfc.accumu.", StringComparison.OrdinalIgnoreCase) ? "amazon" :
            name.StartsWith("era5-arco-lsp-", StringComparison.OrdinalIgnoreCase) ? "google" :
            name.StartsWith("era5-cds-lsp-", StringComparison.OrdinalIgnoreCase) ? "cds" : null;
        if (archive is null && info.Extension.Equals(".nc", StringComparison.OrdinalIgnoreCase))
        {
            // Recognise the supported NCAR/ARCO layouts in existing renamed files.
            lock (NativeNetCdf.Gate)
            {
                using var dataset = new NetCdfFile(path);
                if (dataset.TryVariable("LSP", out var ncar) && dataset.Text(ncar, "rda_dataset") == "ds633.0") archive = "amazon";
                else if (dataset.TryVariable("lsp", out var arco) &&
                    dataset.Text(arco, "standard_name") == "lwe_thickness_of_stratiform_precipitation_amount") archive = "google";
            }
        }
        return new SourceFile(path, info.Length, info.LastWriteTimeUtc.Ticks, MetadataSignature(path), archive);
    }
    private static string? MetadataSignature(string path) => File.Exists(path + ".meteo.json")
        ? Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(path + ".meteo.json"))) : null;
    public string Name => System.IO.Path.GetFileName(Path);
    public string Format => System.IO.Path.GetExtension(Path).ToLowerInvariant() switch
    { ".nc" => "NetCDF", ".tif" or ".tiff" => "GeoTIFF", _ => "GRIB" };
    public int Priority => Format switch { "NetCDF" => 0, "GRIB" => 1, _ => 2 };
    public void Validate()
    {
        var info = new FileInfo(Path);
        if (!info.Exists || info.Length != Bytes || info.LastWriteTimeUtc.Ticks != ModifiedTicks || MetadataSignature(Path) != MetadataHash)
            throw new IOException("Файл ERA5 изменился. Повторно откройте архив.");
    }
}

internal sealed record CycleRead(SourceFile Source, int Cycle, int Steps, int Height, int Width,
    int[] Rows, int[] Columns, int MaxReadMiB, double[]? SourceLatitude = null, double[]? SourceLongitude = null,
    double[]? Latitude = null, double[]? Longitude = null, RasterBandRead[]? Bands = null,
    string Variable = "LSP", bool FlatTime = false);
internal sealed record HourRecord(string Key, int Step, long CycleEpoch);

internal sealed class Era5Index
{
    public Dictionary<long, List<HourRecord>> Records { get; } = [];
    public Dictionary<string, CycleRead> Cycles { get; } = [];
    public List<SourceFile> Sources { get; } = [];
    public SourceFile[] ReadingOrder { get; }
    public bool CustomPriority { get; }
    public string[] ArchivePriority { get; }
    public List<(long Epoch, string Key)> OrderedCycles { get; } = [];
    public double[] Latitude { get; }
    public double[] Longitude { get; }
    public double[] Bbox { get; }
    public long Start { get; }
    public long End { get; }
    public int Hours => checked((int)((End - Start) / 3600));
    public string Sha { get; }
    public int Duplicates { get; private set; }
    public int Cells => Latitude.Length * Longitude.Length;
    public List<long[]> Coverage { get; } = [];
    public int Lookahead { get; }
    public static bool Supported(string path) => Path.GetExtension(path).ToLowerInvariant() is ".nc" or ".grib" or ".grb" or ".grib2" or ".grb2" or ".tif" or ".tiff";
    public static string[] Files(string path) => Directory.Exists(path)
        ? Directory.GetFiles(path, "*", SearchOption.AllDirectories).Where(file => Supported(file) &&
            !Path.GetRelativePath(path, file).Split(Path.DirectorySeparatorChar).Contains(".pending")).ToArray()
        : File.Exists(path) && Supported(path) ? [path] : [];

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
        var files = Files(path);
        if (files.Length == 0) throw new ArgumentException("Не найдены файлы .nc, .grib или GeoTIFF (.tif/.tiff).");
        var latitudes = new SortedSet<double>();
        var longitudes = new SortedSet<double>();
        foreach (var file in files.OrderBy(file => Path.GetExtension(file).Equals(".nc", StringComparison.OrdinalIgnoreCase) ? 0 : 1).ThenBy(file => file, StringComparer.Ordinal))
        {
            var info = new FileInfo(file);
            var source = SourceFile.Create(file);
            if (source.Format != "NetCDF")
            {
                var raster = RasterSources.Inspect(source, maxReadMiB);
                foreach (var value in raster.Latitude.Where(value => value >= bbox[2] && value <= bbox[3])) latitudes.Add(value);
                foreach (var value in raster.Longitude.Where(value => value >= bbox[0] && value <= bbox[1])) longitudes.Add(value);
                foreach (var band in raster.Bands)
                {
                    var key = $"{Sources.Count}:{band.Band}";
                    Add(band.Epoch, new HourRecord(key, 0, band.CycleEpoch));
                    Cycles[key] = new CycleRead(source, band.Band, 1, raster.Height, raster.Width, [], [], maxReadMiB, Bands: [band]);
                }
                source.Validate();
                Sources.Add(source);
                continue;
            }
            using var dataset = new NetCdfFile(file);
            if (!dataset.TryVariable("LSP", out _) && dataset.TryVariable("lsp", out var cfVariable))
            {
                if (dataset.Text(cfVariable, "units") != "m" ||
                    dataset.Text(cfVariable, "standard_name") != "lwe_thickness_of_stratiform_precipitation_amount" ||
                    !dataset.Dimensions(cfVariable).Select(dimension => dimension.Name).SequenceEqual(new[] { "time", "latitude", "longitude" }))
                    throw new InvalidDataException($"{info.Name}: нужен почасовой ERA5 CF-NetCDF LSP в метрах.");
                var cfLat = dataset.Axis("latitude");
                var cfLon = dataset.Axis("longitude");
                var cfRows = Enumerable.Range(0, cfLat.Length).OrderBy(row => cfLat[row]).ToArray();
                var cfColumns = Enumerable.Range(0, cfLon.Length).OrderBy(column => Normalize(cfLon[column])).ToArray();
                var orderedCfLat = cfRows.Select(row => cfLat[row]).ToArray();
                var orderedCfLon = cfColumns.Select(column => Normalize(cfLon[column])).ToArray();
                GridAlignment.ValidateAxis(orderedCfLat, "latitude");
                GridAlignment.ValidateAxis(orderedCfLon, "longitude");
                foreach (var value in orderedCfLat.Where(value => value >= bbox[2] && value <= bbox[3])) latitudes.Add(value);
                foreach (var value in orderedCfLon.Where(value => value >= bbox[0] && value <= bbox[1])) longitudes.Add(value);
                var cfTime = dataset.Variable("time");
                var cfCalendar = dataset.Text(cfTime, "calendar") ?? "standard";
                if (cfCalendar is not ("standard" or "gregorian" or "proleptic_gregorian")) throw new InvalidDataException("Неподдерживаемый календарь CF-NetCDF.");
                var cfUnits = dataset.Text(cfTime, "units") ?? "";
                var cfMatch = Regex.Match(cfUnits, @"^(seconds?|minutes?|hours?|days?) since (.+)$");
                if (!cfMatch.Success) throw new InvalidDataException($"Неподдерживаемое время: {cfUnits}");
                var cfOrigin = DateTimeOffset.Parse(cfMatch.Groups[2].Value, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal).ToUnixTimeSeconds();
                var cfMultiplier = cfMatch.Groups[1].Value[0] switch { 's' => 1, 'm' => 60, 'h' => 3600, _ => 86400 };
                var cfTimes = dataset.Axis("time").Select(value => cfOrigin + value * cfMultiplier).ToArray();
                if (cfTimes.Length == 0 || cfTimes.Any(value => value % 3600 != 0) || cfTimes.Zip(cfTimes.Skip(1)).Any(pair => pair.Second - pair.First != 3600))
                    throw new InvalidDataException("В CF-NetCDF ожидаются последовательные целые часы UTC.");
                // ERA5 CDS single-level accumulations are labelled by the END of
                // the previous hour. NCAR forecast_hour=1 labels that same hour.
                for (var startStep = 0; startStep < cfTimes.Length; startStep += 12)
                {
                    var steps = Math.Min(12, cfTimes.Length - startStep);
                    if ((long)steps * cfLat.Length * cfLon.Length * 4 > maxReadMiB * 1048576L)
                        throw new InvalidDataException("Исходный блок CF-NetCDF превышает MaxReadMiB.");
                    var key = $"{Sources.Count}:{startStep}";
                    var cycleEpoch = checked((long)cfTimes[startStep] - 3600);
                    for (var step = 0; step < steps; step++) Add(checked((long)cfTimes[startStep + step] - 3600), new HourRecord(key, step, cycleEpoch));
                    Cycles[key] = new CycleRead(source, startStep, steps, cfLat.Length, cfLon.Length, cfRows, cfColumns, maxReadMiB,
                        orderedCfLat, orderedCfLon, Variable: "lsp", FlatTime: true);
                }
                source.Validate();
                Sources.Add(source);
                continue;
            }
            var variable = dataset.Variable("LSP");
            var dimensions = dataset.Dimensions(variable);
            if (!dimensions.Select(dimension => dimension.Name).SequenceEqual(new[] { "forecast_initial_time", "forecast_hour", "latitude", "longitude" }) ||
                dataset.Text(variable, "units") != "m" || dataset.Text(variable, "rda_dataset") != "ds633.0")
                throw new InvalidDataException($"{info.Name}: нужен NCAR ERA5 LSP ds633.0 в метрах.");
            var lat = dataset.Axis("latitude");
            var lon = dataset.Axis("longitude");
            var rows = Enumerable.Range(0, lat.Length).OrderBy(index => lat[index]).ToArray();
            var columns = Enumerable.Range(0, lon.Length).OrderBy(index => Normalize(lon[index])).ToArray();
            var orderedLat = rows.Select(row => lat[row]).ToArray();
            var orderedLon = columns.Select(column => Normalize(lon[column])).ToArray();
            GridAlignment.ValidateAxis(orderedLat, "latitude");
            GridAlignment.ValidateAxis(orderedLon, "longitude");
            foreach (var value in orderedLat.Where(value => value >= bbox[2] && value <= bbox[3])) latitudes.Add(value);
            foreach (var value in orderedLon.Where(value => value >= bbox[0] && value <= bbox[1])) longitudes.Add(value);
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
                for (var step = 0; step < hours.Length; step++)
                    Add(epoch + step * 3600, new HourRecord(key, step, epoch));
                Cycles[key] = new CycleRead(source, cycle, hours.Length, lat.Length, lon.Length, rows, columns, maxReadMiB, orderedLat, orderedLon);
            }
            source.Validate();
            Sources.Add(source);
        }
        if (Records.Count == 0) throw new InvalidDataException("Нет почасовых данных ERA5.");
        if (latitudes.Count == 0 || longitudes.Count == 0) throw new ArgumentException("В выбранной области нет ячеек.");
        var stride = Math.Max(1, (int)Math.Ceiling(Math.Sqrt((double)latitudes.Count * longitudes.Count / maxCells)));
        while ((long)((latitudes.Count + stride - 1) / stride) * ((longitudes.Count + stride - 1) / stride) > maxCells) stride++;
        Latitude = latitudes.Where((_, ordinal) => ordinal % stride == 0).ToArray();
        Longitude = longitudes.Where((_, ordinal) => ordinal % stride == 0).ToArray();
        foreach (var key in Cycles.Keys.ToArray()) Cycles[key] = Cycles[key] with { Latitude = Latitude, Longitude = Longitude };
        var savedPriority = new MapPriorities(path).Load();
        ArchivePriority = MapPriorities.EffectiveOrder(savedPriority);
        CustomPriority = !ArchivePriority.SequenceEqual(MapPriorities.DefaultOrder);
        ReadingOrder = MapPriorities.Order(Sources, savedPriority);
        var ranks = ReadingOrder.Select((source, rank) => (source.Path, rank)).ToDictionary(item => item.Path, item => item.rank);
        foreach (var candidates in Records.Values)
            candidates.Sort((left, right) =>
            {
                var a = Cycles[left.Key].Source;
                var b = Cycles[right.Key].Source;
                var comparison = ranks[a.Path].CompareTo(ranks[b.Path]);
                if (comparison != 0) return comparison;
                return left.CycleEpoch.CompareTo(right.CycleEpoch);
            });
        foreach (var group in Records.GroupBy(pair => pair.Value[0].Key))
            OrderedCycles.Add((group.Min(pair => pair.Key), group.Key));
        Start = Records.Keys.Min();
        End = Records.Keys.Max() + 3600;
        foreach (var epoch in Records.Keys.Order())
        {
            if (Coverage.Count > 0 && Coverage[^1][1] == epoch) Coverage[^1][1] += 3600;
            else Coverage.Add([epoch, epoch + 3600]);
        }
        OrderedCycles.Sort((left, right) => left.Epoch.CompareTo(right.Epoch));
        Sha = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(System.Text.Json.JsonSerializer.Serialize(new { version = 4, Sources, Bbox, Latitude, Longitude,
            reading_order = ReadingOrder.Select(source => ArchiveFiles.Id(source.Path)).ToArray(), ArchivePriority,
            imports = Sources.Where(source => File.Exists(source.Path + ".meteo.json")).Select(source => File.ReadAllText(source.Path + ".meteo.json")).ToArray() }))));
    }

    private void Add(long epoch, HourRecord record)
    {
        if (Records.TryGetValue(epoch, out var candidates)) { candidates.Add(record); Duplicates++; }
        else Records[epoch] = [record];
    }

    private static double Normalize(double longitude) => GridAlignment.Normalize(longitude);

    public object Catalog() => new
    {
        kind = "era5", manifest_sha256 = Sha, file_count = Sources.Count,
        data_bytes = Sources.Sum(source => source.Bytes), grid_shape = new[] { Latitude.Length, Longitude.Length },
        start_epoch = Start, unit = "mm", quantity = "large_scale_precipitation", color_max_mm = 50,
        color_scale_from_full_scan = false, frame_bytes = Cells * 4, available_hours = Records.Count,
        gap_hours = Hours - Records.Count, duplicate_hours = Duplicates,
        available_ranges = Coverage.Select(pair => pair.Select(Iso).ToArray()),
        formats = Sources.Select(source => source.Format).Distinct(),
        source_priority = new[] { "NetCDF", "GRIB", "GeoTIFF" },
        custom_priority = CustomPriority,
        archive_priority = ArchivePriority,
        file_priority = ReadingOrder.Select(source => ArchiveFiles.Id(source.Path)),
        files = Sources.Select(source => new { name = source.Name, format = source.Format }),
        members = new[] { new { member = 0, first_hour = 0, hours = Hours, start_utc = Iso(Start), end_utc = Iso(End) } },
        semantics = "LSP hourly amounts in mm, UTC; archive order: " + string.Join(" > ", ArchivePriority) +
            "; missing cells filled from all matching sources",
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
