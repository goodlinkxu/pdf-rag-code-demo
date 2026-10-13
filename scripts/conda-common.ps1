function Find-Conda {
    $candidates = @($env:CONDA_EXE, $env:_CONDA_EXE)
    $cmd = Get-Command conda.exe -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
    foreach ($baseDir in @("$env:USERPROFILE\miniconda3","$env:USERPROFILE\anaconda3","$env:LOCALAPPDATA\miniconda3","$env:LOCALAPPDATA\anaconda3","$env:LOCALAPPDATA\Programs\Miniconda3","$env:ProgramData\miniconda3","$env:ProgramData\anaconda3")) {
        $candidates += Join-Path $baseDir 'Scripts\conda.exe'
    }
    $registry = Join-Path $env:USERPROFILE '.conda\environments.txt'
    if (Test-Path -LiteralPath $registry) {
        foreach ($prefix in (Get-Content -LiteralPath $registry | Where-Object { $_.Trim() })) {
            $candidates += Join-Path $prefix 'Scripts\conda.exe'
            $candidates += [IO.Path]::GetFullPath((Join-Path $prefix '..\..\Scripts\conda.exe'))
        }
    }
    foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return [IO.Path]::GetFullPath($candidate) }
    }
    return $null
}
function Get-CondaInfo {
    param([string]$CondaExe)
    $raw = & $CondaExe info --json
    if ($LASTEXITCODE -ne 0) { throw '无法读取 Conda 环境，请确认 Conda 本身可用。' }
    return ($raw | ConvertFrom-Json)
}
function Get-ProjectEnvironments {
    param($Info)
    return @($Info.envs | Where-Object {
        [IO.Path]::GetFullPath($_).TrimEnd('\') -ne [IO.Path]::GetFullPath($Info.root_prefix).TrimEnd('\') -and
        (Test-Path -LiteralPath (Join-Path $_ 'conda-meta\history')) -and
        (Test-Path -LiteralPath (Join-Path $_ 'python.exe'))
    })
}
function Assert-ProjectEnvironment {
    param([string]$Prefix, [string]$BasePrefix)
    if ([IO.Path]::GetFullPath($Prefix).TrimEnd('\') -eq [IO.Path]::GetFullPath($BasePrefix).TrimEnd('\')) { throw '禁止使用 base 环境，请选择或新建独立 Conda 环境。' }
    if (-not (Test-Path -LiteralPath (Join-Path $Prefix 'conda-meta\history'))) { throw '所选路径不是有效的 Conda 环境。' }
    $pythonExe = Join-Path $Prefix 'python.exe'
    & $pythonExe -c "import sys,struct,pathlib; sys.exit(0 if (3,11)<=sys.version_info[:2]<(3,14) and struct.calcsize('P')==8 and pathlib.Path(sys.prefix).resolve()!=pathlib.Path(sys.argv[1]).resolve() else 1)" $BasePrefix
    if ($LASTEXITCODE -ne 0) { throw '所选环境需要 64 位 Python 3.11–3.13，且不能是 base。请选择其他环境或新建项目环境。' }
}
