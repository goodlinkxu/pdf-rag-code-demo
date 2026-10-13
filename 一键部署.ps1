param(
    [string]$Conda = "",
    [ValidatePattern("^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")]
    [string]$EnvName,
    [switch]$CheckOnly,
    [switch]$NoLaunch
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
Set-Location -LiteralPath $ProjectRoot
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$env:PYTHONNOUSERSITE = '1'
$stage = '检查项目'
$lockHandle = $null
$logging = $false

function Invoke-Checked {
    param([string]$File, [string[]]$CommandArgs)
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $File @CommandArgs | Out-Host
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { throw "命令执行失败（退出码 $code）：$File $($CommandArgs -join ' ')" }
}
. (Join-Path $PSScriptRoot 'scripts\conda-common.ps1')
function Invoke-App {
    param([string[]]$CommandArgs)
    $allArgs = @('run','--no-capture-output','--prefix',$environmentPath,'python') + $CommandArgs
    Invoke-Checked $Conda $allArgs
}
function Refresh-ProcessPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:Path
}
function Install-UserPackage {
    param([string]$Id)
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) { throw '缺少 WinGet。请从 Microsoft Store 安装“应用安装程序”（App Installer），然后重新双击一键部署。也可按 一键部署说明.md 手动安装 Miniconda/Ollama。' }
    Invoke-Checked $winget.Source @('install','--id',$Id,'--exact','--source','winget','--scope','user','--architecture','x64','--silent','--accept-package-agreements','--accept-source-agreements','--disable-interactivity')
    Refresh-ProcessPath
}
function Find-Ollama {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidate = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    if (Test-Path -LiteralPath $candidate) { return $candidate }
    return $null
}
function Get-OllamaModels {
    param([string]$BaseUrl)
    try { return Invoke-RestMethod -Uri "$BaseUrl/api/tags" -TimeoutSec 3 } catch { return $null }
}

try {
    foreach ($required in @('rag_app\__main__.py','scripts\deployment.py','requirements-lock.txt','config.example.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot $required))) { throw "项目文件缺失：$required。请先完整解压交付包，不能在压缩包内部双击运行。" }
    }
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw '此脚本面向 Windows x64，当前架构不在自动部署范围。' }
    $configPath = Join-Path $ProjectRoot 'config.json'
    if (-not (Test-Path -LiteralPath $configPath)) { $configPath = Join-Path $ProjectRoot 'config.example.json' }
    $config = Get-Content -LiteralPath (Join-Path $ProjectRoot 'config.example.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($configPath -ne (Join-Path $ProjectRoot 'config.example.json')) {
        $overrides = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($property in $overrides.PSObject.Properties) { $config | Add-Member -MemberType NoteProperty -Name $property.Name -Value $property.Value -Force }
    }
    $sourcePath = [string]$config.source_pdf
    if (-not [IO.Path]::IsPathRooted($sourcePath)) { $sourcePath = Join-Path $ProjectRoot $sourcePath }
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) { throw "找不到论文：$sourcePath。请完整解压；迁移配置请使用相对路径。" }
    $uri = [Uri]$config.ollama_base_url
    if ($uri.Scheme -ne 'http' -or $uri.Host -notin @('127.0.0.1','localhost') -or $uri.UserInfo -or $uri.AbsolutePath -ne '/') { throw '一键部署只支持本机 HTTP Ollama。请先检查 config.json 中的 ollama_base_url。' }
    $baseUrl = $uri.GetLeftPart([UriPartial]::Authority)
    if ($EnvName -in @('base','root')) { throw '禁止选择 base/root，请使用独立 Conda 环境。' }
    if (-not $Conda) { $Conda = Find-Conda }
    elseif (-not (Test-Path -LiteralPath $Conda -PathType Leaf)) { throw '指定的 Conda 可执行文件不存在。' }
    $ollama = Find-Ollama
    if ($CheckOnly) {
        Write-Host "项目目录：$ProjectRoot"
        Write-Host "Conda：$(if ($Conda) {$Conda} else {'缺失，部署时将安装 Miniconda'})"
        if ($Conda) {
            $checkInfo = Get-CondaInfo $Conda
            foreach ($prefix in (Get-ProjectEnvironments $checkInfo)) { Write-Host "可选环境：$(Split-Path $prefix -Leaf)  $prefix" }
        }
        Write-Host "目标环境：$(if ($EnvName) {$EnvName} else {'实际部署时由用户选择，或输入 N 新建 rag-homework'})"
        Write-Host "Ollama：$(if ($ollama) {$ollama} else {'缺失，部署时将安装 Ollama'})"
        Write-Host "模型：$($config.generation_model)；服务：$baseUrl"
        Write-Host '实际部署顺序：选择 Conda 环境 → Python 依赖 → 本地模型 → 检索资料 → 健康检查 → 启动页面。'
        Write-Host '检查模式结束。未安装软件、下载模型或修改项目。'
        exit 0
    }
    $runtimeDir = Join-Path $ProjectRoot '.runtime'
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    try { $lockHandle = [IO.File]::Open((Join-Path $runtimeDir 'deploy.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None) }
    catch { throw '另一个部署窗口正在运行，请等待它完成。' }
    $logDir = Join-Path $ProjectRoot 'logs'
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $logPath = Join-Path $logDir ("deploy-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
    Start-Transcript -LiteralPath $logPath | Out-Null
    $logging = $true
    Write-Host '论文问答 · 一键部署' -ForegroundColor Green
    Write-Host '首次运行将下载所需软件、依赖及模型；默认 9B 模型约 6.6 GB。下载期间请保持联网。'
    Write-Host '保留已有 config.json 与 outputs；重复运行会复用已完成的安装。'

    $stage = '1/6 选择 Conda 环境'
    Write-Host "`n[$stage]" -ForegroundColor Cyan
    if (-not $Conda) { Install-UserPackage 'Anaconda.Miniconda3'; $Conda = Find-Conda }
    if (-not $Conda) { throw 'Miniconda 安装后仍未找到，请重新运行脚本或用 -Conda 指定 conda.exe。' }
    $info = Get-CondaInfo $Conda
    $environments = @(Get-ProjectEnvironments $info)
    $environmentPath = $null
    $createName = $null
    if ($EnvName) {
        $matches = @($environments | Where-Object { (Split-Path $_ -Leaf) -eq $EnvName })
        if ($matches.Count -gt 1) { throw '发现多个同名环境，请不带 -EnvName 运行，按编号选择具体路径。' }
        if ($matches.Count -eq 1) { $environmentPath = $matches[0] }
        else { $createName = $EnvName }
    } else {
        Write-Host '请选择用于本项目的 Conda 环境。base 已排除。'
        Write-Host '已有环境会按项目要求补齐或调整依赖版本；其他项目共用该环境时，建议选择 N 新建。'
        for ($i=0; $i -lt $environments.Count; $i++) { Write-Host "  $($i+1). $(Split-Path $environments[$i] -Leaf)  $($environments[$i])" }
        Write-Host '  N. 新建专用环境 rag-homework'
        Write-Host '  Q. 取消部署'
        while (-not $environmentPath -and -not $createName) {
            $choice = Read-Host '输入环境编号、N 或 Q'
            if ($choice -eq 'Q') { throw '用户已取消，尚未安装项目依赖。' }
            if ($choice -eq 'N') {
                if (@($environments | Where-Object { (Split-Path $_ -Leaf) -eq 'rag-homework' }).Count) {
                    Write-Host 'rag-homework 已存在，请选择它对应的编号。'
                } else { $createName = 'rag-homework' }
                continue
            }
            $number = 0
            if ([int]::TryParse($choice,[ref]$number) -and $number -ge 1 -and $number -le $environments.Count) { $environmentPath = $environments[$number-1] }
            else { Write-Host '请输入列表中的编号，或 N/Q。' }
        }
    }
    if ($createName) {
        Invoke-Checked $Conda @('create','--name',$createName,'--override-channels','--channel','conda-forge','python=3.12','pip','--yes')
        $info = Get-CondaInfo $Conda
        $matches = @(Get-ProjectEnvironments $info | Where-Object { (Split-Path $_ -Leaf) -eq $createName })
        if ($matches.Count -ne 1) { throw '创建后未能找到唯一的目标环境，请重新运行并按编号选择。' }
        $environmentPath = $matches[0]
    }
    Assert-ProjectEnvironment $environmentPath $info.root_prefix
    Write-Host "Conda 程序：$Conda"
    Write-Host "选定环境：$environmentPath" -ForegroundColor Green
    Write-Host '后续命令均通过 conda run 在此环境执行。'
    $stage = '2/6 检查并安装依赖'
    Write-Host "`n[$stage]" -ForegroundColor Cyan
    & $Conda run --no-capture-output --prefix $environmentPath python (Join-Path $ProjectRoot 'scripts\deployment.py') dependencies --check
    if ($LASTEXITCODE -ne 0) {
        Invoke-App @('-m','pip','install','--upgrade','pip','--disable-pip-version-check','--retries','2','--timeout','30')
        Invoke-App @('-m','pip','install','torch>=2.6','--index-url','https://download.pytorch.org/whl/cpu','--disable-pip-version-check','--retries','2','--timeout','30')
        Invoke-App @('-m','pip','install','-r',(Join-Path $ProjectRoot 'requirements-lock.txt'),'--disable-pip-version-check','--retries','2','--timeout','30')
    }
    Invoke-App @((Join-Path $ProjectRoot 'scripts\deployment.py'),'dependencies','--check')
    Invoke-App @('-m','pip','check')

    $stage = '3/6 准备 Ollama'
    Write-Host "`n[$stage]" -ForegroundColor Cyan
    if (-not $ollama) { Install-UserPackage 'Ollama.Ollama'; $ollama = Find-Ollama }
    if (-not $ollama) { throw 'Ollama 安装后仍未找到，请重新运行本脚本。' }
    # Refresh persisted model location when this shell inherited stale settings.
    if (-not $env:OLLAMA_MODELS) { $env:OLLAMA_MODELS = [Environment]::GetEnvironmentVariable('OLLAMA_MODELS','User') }
    $env:OLLAMA_HOST = $uri.Authority
    $tags = Get-OllamaModels $baseUrl
    if (-not $tags) {
        Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'ollama-out.log') -RedirectStandardError (Join-Path $logDir 'ollama-error.log') | Out-Null
        for ($i=0; $i -lt 30; $i++) { Start-Sleep -Seconds 1; $tags = Get-OllamaModels $baseUrl; if ($tags) { break } }
    }
    if (-not $tags) { throw "Ollama 无法启动，检查 $logDir\ollama-error.log；请确认 $($uri.Port) 端口没有被其他程序占用。" }
    $stage = '4/6 准备回答模型'
    Write-Host "`n[$stage]" -ForegroundColor Cyan
    $model = [string]$config.generation_model
    if (-not $model -or $model.StartsWith('-')) { throw '配置中的 generation_model 无效。' }
    if ($model -notin @($tags.models | ForEach-Object { $_.name })) { Invoke-Checked $ollama @('pull',$model) }
    else { Write-Host "已安装 $model，跳过下载。" }

    $stage = '5/6 准备检索模型和论文索引'
    Write-Host "`n[$stage]" -ForegroundColor Cyan
    Invoke-App @((Join-Path $ProjectRoot 'scripts\deployment.py'),'prepare')
    $stage = '6/6 健康检查'
    Write-Host "`n[$stage]" -ForegroundColor Cyan
    Invoke-App @('-m','rag_app','doctor')
    Invoke-App @((Join-Path $ProjectRoot 'scripts\deployment.py'),'record','--conda',$Conda)
    Write-Host "`n部署完成。以后双击 启动.cmd 即可。日志：$logPath" -ForegroundColor Green
    $lockHandle.Dispose(); $lockHandle = $null
    Stop-Transcript | Out-Null; $logging = $false
    if (-not $NoLaunch) { & (Join-Path $ProjectRoot '启动.ps1') -Conda $Conda -EnvironmentPath $environmentPath }
} catch {
    Write-Host "`n部署未完成：$stage" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host '已完成的下载与历史记录会保留。解决上方问题后重新双击 一键部署.cmd 即可。'
    if ($logging) { Write-Host "日志位置：$logPath" }
    exit 1
} finally {
    if ($lockHandle) { $lockHandle.Dispose() }
    if ($logging) { Stop-Transcript | Out-Null }
}
