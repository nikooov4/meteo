$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$projectId = '{8B883C39-9DAB-4786-BDE8-5D8374D78083}'
$folderType = '{2150E333-8FDC-42A3-9474-1A3956D46DE8}'
$groups = @{
    'web' = 'Web'; 'docs' = 'Documentation'; 'scripts' = 'Tools'; 'tests' = 'Tests';
    'data' = 'Data'; 'runtime' = 'Runtime'; 'artifacts' = 'Validation';
    '.github' = 'CI'
}

function Get-FolderId([string]$Name) {
    $hash = [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes('MeteoBridge/' + $Name))
    return '{' + [Guid]::new([byte[]]$hash[0..15]).ToString().ToUpperInvariant() + '}'
}

Push-Location -LiteralPath $project
try {
    $files = @(& git -c "safe.directory=$($project.Replace('\', '/'))" -c core.quotepath=false ls-files --cached --others --exclude-standard)
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось получить список файлов Git.' }
    $files = @($files | Sort-Object -Unique | Where-Object {
        $_ -ne 'MeteoBridge.sln' -and -not $_.StartsWith('dotnet/') -and (Test-Path -LiteralPath $_ -PathType Leaf)
    })
    $folders = @{}
    $folders['Solution files'] = @{ Id = (Get-FolderId 'Solution files'); Parent = $null; Files = @() }
    foreach ($file in $files) {
        $directory = ([IO.Path]::GetDirectoryName($file)).Replace('\', '/')
        if (-not $directory) {
            $folders['Solution files'].Files += $file
            continue
        }
        $parts = $directory.Split('/')
        if (-not $groups.ContainsKey($parts[0])) { throw "Не классифицирован файл: $file" }
        $parts[0] = $groups[$parts[0]]
        $parent = $null
        for ($position = 0; $position -lt $parts.Length; $position++) {
            $name = $parts[0..$position] -join '/'
            if (-not $folders.ContainsKey($name)) {
                $folders[$name] = @{ Id = (Get-FolderId $name); Parent = $parent; Files = @() }
            }
            $parent = $name
        }
        $folders[$parent].Files += $file
    }
    $text = [Text.StringBuilder]::new()
    @('Microsoft Visual Studio Solution File, Format Version 12.00', '# Visual Studio Version 18',
        'VisualStudioVersion = 18.0.0.0', 'MinimumVisualStudioVersion = 10.0.40219.1',
        ('Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "MeteoBridge.Era5", "dotnet\MeteoBridge.Era5\MeteoBridge.Era5.csproj", "' + $projectId + '"'),
        'EndProject') | ForEach-Object { [void]$text.AppendLine($_) }
    $ordered = @('Solution files') + @($folders.Keys | Where-Object { $_ -ne 'Solution files' } | Sort-Object)
    foreach ($name in $ordered) {
        $folder = $folders[$name]
        $label = ($name -split '/')[-1]
        [void]$text.AppendLine("Project(`"$folderType`") = `"$label`", `"$label`", `"$($folder.Id)`"")
        if ($folder.Files.Count) {
            [void]$text.AppendLine("`tProjectSection(SolutionItems) = preProject")
            foreach ($file in ($folder.Files | Sort-Object)) {
                $path = $file.Replace('/', '\')
                [void]$text.AppendLine("`t`t$path = $path")
            }
            [void]$text.AppendLine("`tEndProjectSection")
        }
        [void]$text.AppendLine('EndProject')
    }
    [void]$text.AppendLine('Global')
    [void]$text.AppendLine("`tGlobalSection(SolutionConfigurationPlatforms) = preSolution")
    foreach ($configuration in @('Debug', 'Release')) {
        [void]$text.AppendLine("`t`t$configuration|Any CPU = $configuration|Any CPU")
    }
    [void]$text.AppendLine("`tEndGlobalSection")
    [void]$text.AppendLine("`tGlobalSection(ProjectConfigurationPlatforms) = postSolution")
    foreach ($configuration in @('Debug', 'Release')) {
        [void]$text.AppendLine("`t`t$projectId.$configuration|Any CPU.ActiveCfg = $configuration|Any CPU")
        [void]$text.AppendLine("`t`t$projectId.$configuration|Any CPU.Build.0 = $configuration|Any CPU")
    }
    [void]$text.AppendLine("`tEndGlobalSection")
    [void]$text.AppendLine("`tGlobalSection(SolutionProperties) = preSolution")
    [void]$text.AppendLine("`t`tHideSolutionNode = FALSE")
    [void]$text.AppendLine("`tEndGlobalSection")
    [void]$text.AppendLine("`tGlobalSection(NestedProjects) = preSolution")
    foreach ($name in $ordered) {
        $folder = $folders[$name]
        if ($folder.Parent) { [void]$text.AppendLine("`t`t$($folder.Id) = $($folders[$folder.Parent].Id)") }
    }
    [void]$text.AppendLine("`tEndGlobalSection")
    [void]$text.AppendLine('EndGlobal')
    [IO.File]::WriteAllText((Join-Path $project 'MeteoBridge.sln'), $text.ToString().Replace("`r`n", "`n"), [Text.UTF8Encoding]::new($false))
    Write-Host "Обновлено решение: $($files.Count) ссылок на файлы сайта, инструменты и проверки."
} finally {
    Pop-Location
}
