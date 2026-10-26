namespace MeteoBridge.Era5;

internal sealed record Grib1Interval(bool Lsp, long Start, long End, long Cycle);

internal static class Grib1Intervals
{
    // GDAL exposes the valid/reference times of GRIB1 but not its statistical
    // interval. Read the product definition (WMO GRIB1 section 1) as well, so
    // a multi-hour accumulation cannot silently become an hourly observation.
    public static Grib1Interval[]? Read(string path)
    {
        using var stream = File.OpenRead(path);
        var header = new byte[8];
        stream.ReadExactly(header);
        if (!header.AsSpan(0, 4).SequenceEqual("GRIB"u8)) throw new InvalidDataException("Отсутствует заголовок GRIB.");
        if (header[7] != 1) return null;
        stream.Position = 0;
        var result = new List<Grib1Interval>();
        while (stream.Position < stream.Length)
        {
            var start = stream.Position;
            stream.ReadExactly(header);
            var length = Number(header.AsSpan(4, 3));
            if (!header.AsSpan(0, 4).SequenceEqual("GRIB"u8) || header[7] != 1 || length < 40 || start + length > stream.Length)
                throw new InvalidDataException("Повреждённая последовательность сообщений GRIB1.");
            var section = new byte[28];
            stream.ReadExactly(section);
            var pdsLength = Number(section.AsSpan(0, 3));
            if (pdsLength < 28 || pdsLength > length - 12) throw new InvalidDataException("Неверная секция времени GRIB1.");
            // ECMWF table 128 parameter 142 is large-scale precipitation.
            var lsp = section[4] == 98 && section[3] == 128 && section[8] == 142 && section[9] == 1;
            long from = 0, to = 0, cycle = 0;
            if (lsp)
            {
                if (section[20] != 4) throw new InvalidDataException("GRIB1 LSP: ожидается накопление (timeRangeIndicator=4).");
                var multiplier = section[17] switch { 0 => 60L, 1 => 3600L, 2 => 86400L, 10 => 10800L, 11 => 21600L, 12 => 43200L, 254 => 1L, _ => 0L };
                if (multiplier == 0) throw new InvalidDataException("GRIB1: неподдерживаемые единицы времени.");
                cycle = new DateTimeOffset((section[24] - 1) * 100 + section[12], section[13], section[14], section[15], section[16], 0, TimeSpan.Zero).ToUnixTimeSeconds();
                from = cycle + section[18] * multiplier;
                to = cycle + section[19] * multiplier;
                if (from % 3600 != 0 || to % 3600 != 0 || to <= from)
                    throw new InvalidDataException("GRIB1: нужен интервал накопления из целых часов UTC.");
            }
            stream.Position = start + length - 4;
            var trailer = new byte[4];
            stream.ReadExactly(trailer);
            if (!trailer.AsSpan().SequenceEqual("7777"u8)) throw new InvalidDataException("Оборванное сообщение GRIB1.");
            result.Add(new Grib1Interval(lsp, from, to, cycle));
        }
        return result.ToArray();
    }

    private static int Number(ReadOnlySpan<byte> value) => value[0] << 16 | value[1] << 8 | value[2];
}
