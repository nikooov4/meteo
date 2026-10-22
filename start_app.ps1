param([int]$Port = 8766,
      [string]$Data = 'data/era5', [int]$Workers = 2)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$requestedData = [IO.Path]::GetFullPath($Data, $PSScriptRoot)
try {
    $running = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
    if ($running.application -eq 'MeteoBridge.Era5' -and $running.project_root -eq $PSScriptRoot -and
        $running.data_path -eq $requestedData -and $running.workers -eq $Workers) {
        Write-Host "Карта уже запущена: http://127.0.0.1:$Port/"
        exit 0
    }
} catch { }
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'runtime/plotly/plotly.min.js')) -or
    -not (Get-ChildItem -Path (Join-Path $PSScriptRoot 'runtime/netcdf/netcdf*.dll') -ErrorAction SilentlyContinue)) {
    & (Join-Path $PSScriptRoot 'scripts/setup_runtime.ps1')
}
$env:DOTNET_CLI_HOME = Join-Path $PSScriptRoot '.dotnet-home'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:MSBuildEnableWorkloadResolver = 'false'
Write-Host 'Запускаю карту ERA5. Адрес появится после запуска сервера.'
& dotnet run --project dotnet/MeteoBridge.Era5 -c Release --no-launch-profile -- --urls "http://127.0.0.1:$Port" --Era5:Data $Data --Era5:Workers $Workers
exit $LASTEXITCODE
