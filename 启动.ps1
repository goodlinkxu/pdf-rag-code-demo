param([string]$Conda = "", [string]$EnvironmentPath = "", [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$env:PYTHONNOUSERSITE = '1'
try {
    . (Join-Path $PSScriptRoot 'scripts\conda-common.ps1')
    if (-not $EnvironmentPath) {
        $record = Join-Path $PSScriptRoot '.runtime\current.json'
        if (-not (Test-Path -LiteralPath $record)) { throw '请先双击 一键部署.cmd，选择本项目使用的 Conda 环境。' }
        $saved = Get-Content -LiteralPath $record -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($saved.environment_kind -ne 'conda' -or $saved.root.TrimEnd('\') -ne $PSScriptRoot.TrimEnd('\')) { throw '旧部署记录或项目位置已变化，请先运行 一键部署.cmd 重新选择 Conda 环境。' }
        $EnvironmentPath = $saved.environment_path
        if (-not $Conda) { $Conda = $saved.conda }
    }
    if (-not $Conda -or -not (Test-Path -LiteralPath $Conda)) { $Conda = Find-Conda }
    if (-not $Conda) { throw '未找到 Conda，请重新运行 一键部署.cmd。' }
    $info = Get-CondaInfo $Conda
    Assert-ProjectEnvironment $EnvironmentPath $info.root_prefix
    Write-Host "使用 Conda 环境：$EnvironmentPath"
    $runArgs = @('run','--no-capture-output','--prefix',$EnvironmentPath,'python','-m','rag_app','serve')
    if ($NoBrowser) { $runArgs += '--no-browser' }
    & $Conda @runArgs
    if ($LASTEXITCODE -ne 0) { throw '启动失败，请查看上方原因；依赖问题可重新运行一键部署，端口冲突请先关闭旧启动窗口。' }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
