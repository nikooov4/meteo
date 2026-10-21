param([int]$Port = 8501, [switch]$Archive)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'

if ($Archive) {
    if (-not $PSBoundParameters.ContainsKey('Port')) { $Port = 8765 }
    Write-Host "Карта синтетического архива: http://127.0.0.1:$Port/"
    & uv run --frozen python scripts/serve_precipitation_map.py --port $Port
} else {
    Write-Host "Карта осадков: http://127.0.0.1:$Port/?view=map"
    & uv run --frozen streamlit run ui/app.py --server.address 127.0.0.1 --server.port $Port --server.headless true --browser.gatherUsageStats false
}
exit $LASTEXITCODE
