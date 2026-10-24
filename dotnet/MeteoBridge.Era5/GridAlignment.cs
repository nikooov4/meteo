namespace MeteoBridge.Era5;

// Every reader samples the same immutable grid. Missing neighbours stay missing;
// they must be filled by another observation, never treated as zero rainfall.
internal static class GridAlignment
{
    public static double Normalize(double longitude) => ((longitude + 180) % 360 + 360) % 360 - 180;

    public static float Sample(double x, double y, double[] xs, double[] ys, Func<int, int, float> value)
    {
        static (int Lower, int Upper, double Weight)? Locate(double[] axis, double point)
        {
            const double epsilon = 1e-7;
            if (!double.IsFinite(point) || point < axis[0] - epsilon || point > axis[^1] + epsilon) return null;
            var found = Array.BinarySearch(axis, point);
            if (found >= 0) return (found, found, 0);
            var upper = ~found;
            if (upper < axis.Length && Math.Abs(axis[upper] - point) < epsilon) return (upper, upper, 0);
            if (upper > 0 && Math.Abs(axis[upper - 1] - point) < epsilon) return (upper - 1, upper - 1, 0);
            if (upper == 0 || upper == axis.Length) return null;
            return (upper - 1, upper, (point - axis[upper - 1]) / (axis[upper] - axis[upper - 1]));
        }
        var horizontal = Locate(xs, x);
        var vertical = Locate(ys, y);
        if (horizontal is not { } a || vertical is not { } b) return float.NaN;
        // Do not interpolate across the unobserved side of the date line.
        if (a.Upper != a.Lower && xs[a.Upper] - xs[a.Lower] > 180) return float.NaN;
        double sum = 0;
        for (var dy = 0; dy < 2; dy++)
        for (var dx = 0; dx < 2; dx++)
        {
            var (row, wy) = dy == 0 ? (b.Lower, 1 - b.Weight) : (b.Upper, b.Weight);
            var (column, wx) = dx == 0 ? (a.Lower, 1 - a.Weight) : (a.Upper, a.Weight);
            var weight = wx * wy;
            if (weight <= 1e-12) continue;
            var sample = value(row, column);
            if (!float.IsFinite(sample)) return float.NaN;
            sum += sample * weight;
        }
        return (float)sum;
    }

    public static void ValidateAxis(double[] axis, string name)
    {
        if (axis.Length == 0 || axis.Any(value => !double.IsFinite(value)) ||
            axis.Zip(axis.Skip(1)).Any(pair => pair.First >= pair.Second))
            throw new InvalidDataException($"Некорректная или повторяющаяся координата {name}.");
    }
}
