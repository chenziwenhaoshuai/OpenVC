# 一次性初始化开发环境
#
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
#
# 做三件事：建 venv、装依赖（约 300 MB）、下载 ONNX 模型（约 440 MB）。
# 不需要 PyTorch，不需要 CUDA。

param(
    [switch]$SkipModels,
    [string]$Proxy = "",
    [string]$Mirror = "https://pypi.tuna.tsinghua.edu.cn/simple"
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host '=== 1/3 定位 Python 3.11 ===' -ForegroundColor Cyan
$py = $null
foreach ($candidate in @(
        'py -3.11',
        'python')) {
    try {
        $exe = (& cmd /c "$candidate -c `"import sys;print(sys.executable)`"" 2>$null)
        if ($exe -and (Test-Path $exe.Trim())) {
            $ver = (& cmd /c "$candidate -c `"import sys;print('%d.%d'%sys.version_info[:2])`"" 2>$null)
            if ($ver -eq '3.11') { $py = $exe.Trim(); break }
        }
    } catch { }
}
if (-not $py) { throw '找不到 Python 3.11，请先安装 python.org 的 3.11 版本。' }
Write-Host "  使用: $py"

Write-Host '=== 2/3 创建虚拟环境并安装依赖 ===' -ForegroundColor Cyan
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    & $py -m venv .venv
}
$vpy = Join-Path $root '.venv\Scripts\python.exe'
& $vpy -m pip install --upgrade pip -i $Mirror 2>&1 | Select-Object -Last 1

$pipArgs = @('-m', 'pip', 'install', '--no-cache-dir', '-i', $Mirror, '-r', 'requirements-lite.txt')
if ($Proxy) { $pipArgs += @('--proxy', $Proxy) }
& $vpy @pipArgs
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败' }

if (-not $SkipModels) {
    Write-Host '=== 3/3 下载 ONNX 模型 ===' -ForegroundColor Cyan
    $mArgs = @()
    if ($Proxy) { $mArgs += @('-Proxy', $Proxy) }
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'download_models.ps1') @mArgs
    if ($LASTEXITCODE -ne 0) { throw '模型下载失败' }
} else {
    Write-Host '=== 3/3 跳过模型下载 ===' -ForegroundColor Cyan
}

Write-Host ''
Write-Host '=== 完成 ===' -ForegroundColor Green
Write-Host '  启动: 双击 启动变声器.bat   或   python app\main_qt.py'
Write-Host '  打包: powershell -ExecutionPolicy Bypass -File .\build_portable.ps1'