param([string]$EnvironmentPath = '.venv')

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$environment = [IO.Path]::GetFullPath($EnvironmentPath, $project)
$packages = Join-Path $environment 'Lib/site-packages'
$native = Join-Path $packages 'netCDF4.libs'
$plotly = Join-Path $packages 'plotly/package_data/plotly.min.js'
if (-not (Test-Path -LiteralPath $native) -or -not (Test-Path -LiteralPath $plotly)) {
    throw 'Не найдены библиотеки. Выполните uv sync --frozen --no-dev в корне проекта и повторите scripts/setup_runtime.ps1.'
}
$runtime = Join-Path $project 'runtime'
$nativeTarget = Join-Path $runtime 'netcdf'
$plotlyTarget = Join-Path $runtime 'plotly'
New-Item -ItemType Directory -Force -Path $nativeTarget, $plotlyTarget | Out-Null
Get-ChildItem -LiteralPath $native -Filter *.dll -File | Copy-Item -Destination $nativeTarget -Force
Copy-Item -LiteralPath $plotly -Destination (Join-Path $plotlyTarget 'plotly.min.js') -Force
$versions = @()
foreach ($pattern in @('netcdf4-*.dist-info', 'plotly-*.dist-info')) {
    $package = Get-ChildItem -LiteralPath $packages -Directory -Filter $pattern | Select-Object -First 1
    if (-not $package) { throw "Не найдены сведения о пакете: $pattern" }
    $licenses = Join-Path $runtime ('licenses/' + $package.Name)
    New-Item -ItemType Directory -Force -Path $licenses | Out-Null
    Copy-Item -LiteralPath (Join-Path $package.FullName 'METADATA') -Destination $licenses -Force
    $sourceLicenses = Join-Path $package.FullName 'licenses'
    if (Test-Path -LiteralPath $sourceLicenses) {
        Copy-Item -LiteralPath $sourceLicenses -Destination $licenses -Recurse -Force
    }
    $versions += $package.Name
}
$files = @(Get-ChildItem -LiteralPath $nativeTarget, $plotlyTarget -File | Sort-Object FullName | ForEach-Object {
    [ordered]@{ path = [IO.Path]::GetRelativePath($runtime, $_.FullName).Replace('\', '/'); bytes = $_.Length;
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
})
[ordered]@{ packages = $versions; files = $files } | ConvertTo-Json -Depth 5 |
    Set-Content -LiteralPath (Join-Path $runtime 'manifest.json') -Encoding utf8
Write-Host 'Готово: runtime/netcdf и runtime/plotly. Сайт не обращается к Python-окружению.'
