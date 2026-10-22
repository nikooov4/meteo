using System.Diagnostics;
using Microsoft.AspNetCore.Connections;

namespace MeteoBridge.Era5;

internal static class LocalWebHost
{
    public static async Task RunAsync(Func<string?, WebApplication> create)
    {
        string? retryAddress = null;
        for (var attempt = 0; attempt <= 20; attempt++)
        {
            await using var app = create(retryAddress);
            try
            {
                await app.StartAsync();
            }
            catch (IOException error) when (AddressInUse(error))
            {
                var configured = app.Configuration["urls"] ?? "http://127.0.0.1:8766";
                var addresses = configured.Split(';', StringSplitOptions.RemoveEmptyEntries);
                if (attempt == 20 || addresses.Length != 1 || !Uri.TryCreate(addresses[0], UriKind.Absolute, out var current) ||
                    current.Scheme != "http" || !current.IsLoopback)
                {
                    Console.Error.WriteLine($"Не удалось запустить карту: адрес {configured} занят. Задайте другой порт через --urls.");
                    Environment.ExitCode = 1;
                    return;
                }
                var port = attempt == 19 || current.Port == 65535 ? 0 : current.Port + 1;
                retryAddress = new UriBuilder("http", "127.0.0.1", port).Uri.GetLeftPart(UriPartial.Authority);
                Console.WriteLine($"Порт {current.Port} занят. Пробую {retryAddress}.");
                continue;
            }
            var address = app.Urls.First();
            Console.WriteLine($"Карта ERA5: {address}/");
            if (app.Configuration.GetValue("Era5:OpenBrowser", false))
            {
                try { Process.Start(new ProcessStartInfo(address) { UseShellExecute = true }); }
                catch (System.ComponentModel.Win32Exception) { Console.WriteLine("Откройте указанный адрес в браузере."); }
            }
            await app.WaitForShutdownAsync();
            return;
        }
    }

    private static bool AddressInUse(Exception error) => error is AddressInUseException ||
        error.InnerException is { } inner && AddressInUse(inner);
}
