param([switch]$VerifyOnly)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $project 'runtime/graphcast'
$bundled = Join-Path $runtime 'python'
$python = Join-Path $runtime '.venv-gpu/Scripts/python.exe'
if (-not $IsWindows) { throw 'Подготовленный GPU-бэкенд GrathCast предназначен для Windows x64.' }
if (-not $VerifyOnly) {
    if (-not (Test-Path -LiteralPath (Join-Path $bundled 'python.exe'))) {
        $env:UV_PYTHON_INSTALL_DIR = Join-Path $project '.uv-python'
        & uv python install 3.12
        if ($LASTEXITCODE) { throw 'Не удалось подготовить Python 3.12.' }
        $basePython = (& uv python find 3.12).Trim()
        if ($LASTEXITCODE) { throw 'Не найден Python 3.12.' }
        New-Item -ItemType Directory -Path $runtime -Force | Out-Null
        Copy-Item -LiteralPath (Split-Path -Parent $basePython) -Destination $bundled -Recurse
    }
    if (-not (Test-Path -LiteralPath $python)) {
        & uv venv --python (Join-Path $bundled 'python.exe') (Join-Path $runtime '.venv-gpu')
        if ($LASTEXITCODE) { throw 'Не удалось создать окружение GrathCast.' }
    }
}
if (-not (Test-Path -LiteralPath $python)) { throw 'Окружение не подготовлено. Выполните scripts/setup_graphcast.ps1 без VerifyOnly.' }
$configuration = Join-Path $runtime '.venv-gpu/pyvenv.cfg'
$content = Get-Content -LiteralPath $configuration -Raw
$rebased = [regex]::Replace($content, '(?m)^home = .*', { param($match) 'home = ' + $bundled })
if ($rebased -ne $content) { [IO.File]::WriteAllText($configuration, $rebased) }
if (-not $VerifyOnly) {
    & uv pip sync --python $python (Join-Path $project 'workers/graphcast/requirements.lock.txt')
    if ($LASTEXITCODE) { throw 'Не удалось установить зависимости GrathCast.' }
}
$arguments = @((Join-Path $PSScriptRoot 'setup_graphcast.py'))
if ($VerifyOnly) { $arguments += '--check' }
& $python @arguments
if ($LASTEXITCODE) { throw 'Проверка файлов GrathCast завершилась с ошибкой.' }
Write-Host 'GrathCast готов. Запускайте весь проект через start_app.ps1.'
