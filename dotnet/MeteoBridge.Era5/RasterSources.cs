using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;
using MaxRev.Gdal.Core;
using OSGeo.GDAL;
using OSGeo.OSR;

namespace MeteoBridge.Era5;

internal sealed record ImportOptions(string? StartUtc = null, string? Units = null,
    string Accumulation = "hourly", string Quantity = "large_scale_precipitation");
internal sealed record RasterBandRead(int Band, int PreviousBand, double Factor, long Epoch, long CycleEpoch);
internal sealed record RasterDescription(int Height, int Width, double[] Latitude, double[] Longitude, RasterBandRead[] Bands);

internal static class RasterSources
{
    private static bool initialized;
    public static void Initialize()
    {
        if (initialized) return;
        GdalBase.ConfigureAll();
        // Native GDAL/PROJ data lookup on Windows still needs an ASCII path in
        // some distributions, including installations in a Cyrillic workspace.
        var gdalData = Path.Combine(AppContext.BaseDirectory, "runtimes", "any", "native", "gdal-data");
        var projData = Path.Combine(AppContext.BaseDirectory, "runtimes", OperatingSystem.IsWindows() ? "win-x64" : "linux-x64", "native", "maxrev.gdal.core.libshared");
        if (Directory.Exists(gdalData)) Gdal.SetConfigOption("GDAL_DATA", NativeNetCdf.ReadPath(gdalData));
        if (Directory.Exists(projData))
        {
            Gdal.SetConfigOption("PROJ_LIB", NativeNetCdf.ReadPath(projData));
            Osr.SetPROJSearchPaths([NativeNetCdf.ReadPath(projData)]);
        }
        Gdal.SetConfigOption("GDAL_NUM_THREADS", "1");
        Gdal.SetConfigOption("GDAL_CACHEMAX", "32");
        initialized = true;
    }

    private static Dataset Open(string path)
    {
        Initialize();
        var dataset = Gdal.Open(NativeNetCdf.ReadPath(path), Access.GA_ReadOnly) ?? throw new InvalidDataException("GDAL не смог открыть файл.");
        using var driver = dataset.GetDriver();
        var expected = Path.GetExtension(path).ToLowerInvariant() is ".tif" or ".tiff" ? "GTiff" : "GRIB";
        if (driver.ShortName != expected) { dataset.Dispose(); throw new InvalidDataException("Содержимое не соответствует формату файла."); }
        return dataset;
    }

    private static Dataset Geographic(Dataset dataset, bool mask = false)
    {
        var projection = dataset.GetProjectionRef();
        if (string.IsNullOrWhiteSpace(projection)) throw new InvalidDataException("В файле отсутствует географическая привязка (CRS).");
        using var target = new SpatialReference("");
        target.ImportFromEPSG(4326);
        using var original = new SpatialReference(projection);
        var transform = new double[6];
        dataset.GetGeoTransform(transform);
        // ERA5's spherical geographic CRS uses the same degree coordinates.
        // An unnecessary warp makes non-square cells square and shifts their
        // centres, creating artificial intersections/gaps between archives.
        if (original.IsGeographic() != 0 && transform[2] == 0 && transform[4] == 0 &&
            Math.Abs(original.GetAngularUnits() - Math.PI / 180) < 1e-12 &&
            double.TryParse(original.GetAttrValue("PRIMEM", 1), NumberStyles.Float, CultureInfo.InvariantCulture, out var meridian) && meridian == 0)
        {
            using var copy = new GDALTranslateOptions(["-of", "VRT"]);
            return Gdal.wrapper_GDALTranslate("", dataset, copy, null, null)
                ?? throw new InvalidDataException("Не удалось открыть географическую сетку.");
        }
        target.ExportToWkt(out var wkt, null);
        using var options = new GDALWarpAppOptions(["-of", "VRT", "-t_srs", wkt, "-r", "near",
            "-dstnodata", mask ? "0" : "nan", "-wo", mask ? "INIT_DEST=0" : "INIT_DEST=NO_DATA"]);
        return Gdal.Warp("", [dataset], options, null, null)
            ?? throw new InvalidDataException("Не удалось привести сетку к WGS84.");
    }

    public static double UnitFactor(string? units) => (units ?? "").Trim().Trim('[', ']').ToLowerInvariant().Replace(" ", "") switch
    {
        "m" => 1000,
        "mm" or "kgm-2" or "kgm**-2" or "kg/m2" or "kg/(m^2)" or "kg/m^2" => 1,
        _ => throw new InvalidDataException("Нужны единицы m, mm или kg m-2 для количества осадков за час.")
    };

    public static long Hour(string value)
    {
        if (!Regex.IsMatch(value, @"(Z|[+-]\d{2}:\d{2})$") ||
            !DateTimeOffset.TryParse(value, CultureInfo.InvariantCulture, DateTimeStyles.None, out var stamp) ||
            stamp.Ticks % TimeSpan.TicksPerHour != 0) throw new InvalidDataException("Начало должно быть целым часом с UTC offset.");
        return stamp.ToUnixTimeSeconds();
    }

    public static RasterDescription Inspect(SourceFile source, int maxReadMiB)
    {
        using var dataset = Open(source.Path);
        if ((long)dataset.RasterXSize * dataset.RasterYSize * 8 > maxReadMiB * 1048576L)
            throw new InvalidDataException($"{source.Name}: растровый слой превышает MaxReadMiB.");
        if (dataset.RasterCount < 1 || dataset.RasterCount > 100000) throw new InvalidDataException("Неверное число временных слоёв.");
        ImportOptions? options = null;
        if (File.Exists(source.Path + ".meteo.json"))
            options = JsonSerializer.Deserialize<ImportOptions>(File.ReadAllText(source.Path + ".meteo.json"))
                ?? throw new InvalidDataException("Пустое описание импорта.");
        else if (source.Format == "GeoTIFF" && dataset.GetMetadataItem("METEO_START_UTC", "") is { Length: > 0 } start)
            options = new ImportOptions(start, dataset.GetMetadataItem("METEO_UNITS", ""),
                dataset.GetMetadataItem("METEO_ACCUMULATION", "") is { Length: > 0 } accumulation ? accumulation : "hourly",
                dataset.GetMetadataItem("METEO_QUANTITY", "") ?? "");
        if (options is not null && (options.Quantity != "large_scale_precipitation" || options.Accumulation is not ("hourly" or "cumulative")))
            throw new InvalidDataException("Карта LSP принимает только крупномасштабные осадки: почасовые или накопленные от начала прогноза.");
        if (source.Format == "GeoTIFF" && options is null)
            throw new InvalidDataException($"{source.Name}: укажите начало UTC, единицы и тип накопления в разделе загрузки.");

        var bands = new List<RasterBandRead>();
        var windows = new List<(int Band, long Start, long End, long Cycle, double Factor)>();
        var grib1 = source.Format == "GRIB" && options is null ? Grib1Intervals.Read(source.Path) : null;
        if (grib1 is not null && grib1.Length != dataset.RasterCount) throw new InvalidDataException("Количество сообщений GRIB1 не соответствует слоям GDAL.");
        for (var number = 1; number <= dataset.RasterCount; number++)
        {
            using var band = dataset.GetRasterBand(number);
            if (grib1 is not null)
            {
                var interval = grib1[number - 1];
                if (interval.Lsp) windows.Add((number, interval.Start, interval.End, interval.Cycle, UnitFactor(band.GetMetadataItem("GRIB_UNIT", ""))));
                continue;
            }
            if (source.Format == "GRIB")
            {
                var element = band.GetMetadataItem("GRIB_ELEMENT", "") ?? "";
                var comment = band.GetMetadataItem("GRIB_COMMENT", "") ?? "";
                if (element is not ("LSP" or "NCPCP") && !comment.Contains("large-scale", StringComparison.OrdinalIgnoreCase) &&
                    !comment.Contains("large scale", StringComparison.OrdinalIgnoreCase)) continue;
            }
            if (options is not null)
            {
                if (options.StartUtc is null) throw new InvalidDataException("Укажите начало UTC.");
                var epoch = checked(Hour(options.StartUtc) + bands.Count * 3600L);
                bands.Add(new RasterBandRead(number, options.Accumulation == "cumulative" && bands.Count > 0 ? bands[^1].Band : 0,
                    UnitFactor(options.Units), epoch, Hour(options.StartUtc)));
                continue;
            }
            // GRIB2 PDT 4.8 explicitly describes the accumulation interval.
            // Never mistake a six-hour amount or a rate for a one-hour observation.
            if (band.GetMetadataItem("GRIB_PDS_PDTN", "") != "8")
                throw new InvalidDataException($"{source.Name}: интервал GRIB не определён. Укажите его при импорте.");
            var template = (band.GetMetadataItem("GRIB_PDS_TEMPLATE_ASSEMBLED_VALUES", "") ?? "")
                .Split(' ', StringSplitOptions.RemoveEmptyEntries).Select(value => long.Parse(value, CultureInfo.InvariantCulture)).ToArray();
            if (template.Length < 29 || template[21] != 1 || template[23] != 1)
                throw new InvalidDataException("GRIB: ожидается один интервал накопления осадков.");
            var multiplier = template[25] switch { 0 => 60L, 1 => 3600L, 2 => 86400L, 13 => 1L, _ => 0L };
            var seconds = checked(template[26] * multiplier);
            if (seconds < 3600 || seconds % 3600 != 0 || multiplier == 0) throw new InvalidDataException("GRIB: нужен интервал, кратный часу.");
            var end = new DateTimeOffset((int)template[15], (int)template[16], (int)template[17], (int)template[18],
                (int)template[19], (int)template[20], TimeSpan.Zero).ToUnixTimeSeconds();
            var reference = Regex.Match(band.GetMetadataItem("GRIB_REF_TIME", "") ?? "", @"^-?\d+").Value;
            if (reference.Length == 0 || end % 3600 != 0) throw new InvalidDataException("GRIB: неверное время UTC.");
            windows.Add((number, end - seconds, end, long.Parse(reference, CultureInfo.InvariantCulture), UnitFactor(band.GetMetadataItem("GRIB_UNIT", ""))));
        }
        foreach (var window in windows)
        {
            var previous = windows.FirstOrDefault(other => other.Start == window.Start && other.End == window.End - 3600 && other.Cycle == window.Cycle && other.Factor == window.Factor);
            if (window.End - window.Start != 3600 && previous.Band == 0)
                throw new InvalidDataException($"{source.Name}: для почасового значения отсутствует предыдущее накопление GRIB.");
            bands.Add(new RasterBandRead(window.Band, window.End - window.Start == 3600 ? 0 : previous.Band,
                window.Factor, window.End - 3600, window.Cycle));
        }
        if (bands.Count == 0) throw new InvalidDataException($"{source.Name}: нет крупномасштабных осадков LSP. Суммарные осадки и другие величины не смешиваются с LSP.");
        using var geographic = Geographic(dataset);
        if (geographic.RasterXSize > 10_000_000 || geographic.RasterYSize > 10_000_000 ||
            (long)geographic.RasterXSize * geographic.RasterYSize * 8 > maxReadMiB * 1048576L)
            throw new InvalidDataException("Репроекция превышает MaxReadMiB.");
        var transform = new double[6];
        geographic.GetGeoTransform(transform);
        var xs = Enumerable.Range(0, geographic.RasterXSize).Select(column => GridAlignment.Normalize(transform[0] + (column + .5) * transform[1])).Order().ToArray();
        var ys = Enumerable.Range(0, geographic.RasterYSize).Select(row => transform[3] + (row + .5) * transform[5]).Order().ToArray();
        GridAlignment.ValidateAxis(xs, "longitude");
        GridAlignment.ValidateAxis(ys, "latitude");
        return new RasterDescription(dataset.RasterYSize, dataset.RasterXSize, ys, xs, bands.ToArray());
    }

    public static byte[] Read(CycleRead request)
    {
        request.Source.Validate();
        using var dataset = Open(request.Source.Path);
        using var geographic = Geographic(dataset);
        var width = geographic.RasterXSize;
        var height = geographic.RasterYSize;
        if ((long)width * height * 8 > request.MaxReadMiB * 1048576L) throw new InvalidDataException("Репроекция превышает MaxReadMiB.");
        var transform = new double[6];
        geographic.GetGeoTransform(transform);
        var columns = Enumerable.Range(0, width).OrderBy(column => GridAlignment.Normalize(transform[0] + (column + .5) * transform[1])).ToArray();
        var rows = Enumerable.Range(0, height).OrderBy(row => transform[3] + (row + .5) * transform[5]).ToArray();
        var xs = columns.Select(column => GridAlignment.Normalize(transform[0] + (column + .5) * transform[1])).ToArray();
        var ys = rows.Select(row => transform[3] + (row + .5) * transform[5]).ToArray();
        var output = new float[checked(request.Steps * request.Latitude!.Length * request.Longitude!.Length)];
        var position = 0;
        foreach (var layer in request.Bands!)
        {
            float[] ReadBand(int number)
            {
                using var band = geographic.GetRasterBand(number);
                var raw = new float[checked(width * height)];
                if (band.ReadRaster(0, 0, width, height, raw, width, height, 0, 0) != CPLErr.CE_None)
                    throw new InvalidDataException("Не удалось прочитать растровый слой.");
                band.GetNoDataValue(out var nodata, out var hasNodata);
                band.GetScale(out var scale, out var hasScale);
                band.GetOffset(out var offset, out var hasOffset);
                byte[]? mask = null;
                using (var original = dataset.GetRasterBand(number))
                {
                    // A stored mask may coexist with NoData. Warping the values
                    // alone can discard that mask, so align it independently.
                    if (original.GetMaskFlags() is not (1 or 8))
                    {
                        using var maskOptions = new GDALTranslateOptions(["-of", "VRT", "-b", $"mask,{number}"]);
                        using var maskSource = Gdal.wrapper_GDALTranslate("", dataset, maskOptions, null, null);
                        using var alignedMask = Geographic(maskSource, true);
                        if (alignedMask.RasterXSize != width || alignedMask.RasterYSize != height)
                            throw new InvalidDataException("Размер маски не соответствует растровому слою.");
                        using var maskBand = alignedMask.GetRasterBand(1);
                        mask = new byte[raw.Length];
                        if (maskBand.ReadRaster(0, 0, width, height, mask, width, height, 0, 0) != CPLErr.CE_None)
                            throw new InvalidDataException("Не удалось прочитать маску растрового слоя.");
                    }
                }
                for (var cell = 0; cell < raw.Length; cell++)
                    raw[cell] = !float.IsFinite(raw[cell]) || mask is not null && mask[cell] == 0 || hasNodata != 0 && raw[cell] == (float)nodata ? float.NaN
                        : (float)((raw[cell] * (hasScale != 0 ? scale : 1) + (hasOffset != 0 ? offset : 0)) * layer.Factor);
                return raw;
            }
            var current = ReadBand(layer.Band);
            var previous = layer.PreviousBand > 0 ? ReadBand(layer.PreviousBand) : null;
            for (var cell = 0; cell < current.Length; cell++)
            {
                if (previous is not null) current[cell] -= previous[cell];
                if (!float.IsFinite(current[cell]) || current[cell] < 0) current[cell] = float.NaN;
            }
            foreach (var y in request.Latitude)
            foreach (var x in request.Longitude)
                output[position++] = GridAlignment.Sample(x, y, xs, ys, (row, column) => current[rows[row] * width + columns[column]]);
        }
        request.Source.Validate();
        var bytes = new byte[output.Length * 4];
        Buffer.BlockCopy(output, 0, bytes, 0, bytes.Length);
        return bytes;
    }
}
