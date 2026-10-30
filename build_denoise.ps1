# 编译降噪组件（DeepFilterNet3 / libDF）
#
#   powershell -ExecutionPolicy Bypass -File .\build_denoise.ps1
#
# 产物: denoise\df.dll + denoise\DeepFilterNet3_onnx.tar.gz
#
# 为什么要自己编译：
#   官方 Python 版依赖 PyTorch（约 1.9 GB）。同一个作者的 libDF 用 Rust
#   实现了等价的 DSP + 推理，直接给 C 接口，本程序用 ctypes 调用，
#   因此整个应用不需要 PyTorch。
#
# 依赖：Rust 工具链 + mingw gcc（libDF 的构建脚本需要 C 编译器）

param(
    [string]$Work = "$env:TEMP\openvc-dfn",
    [string]$Proxy = ""
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$mingw = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages\BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe\mingw64\bin'
if (-not (Test-Path (Join-Path $mingw 'gcc.exe'))) {
    $gccCmd = Get-Command gcc -ErrorAction SilentlyContinue
    if (-not $gccCmd) { throw '找不到 gcc.exe，请安装 mingw-w64 并加入 PATH' }
    $mingw = Split-Path $gccCmd.Source
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { throw '找不到 cargo，请安装 Rust 工具链' }

Write-Host '=== 1/4 下载官方源码 ===' -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $Work | Out-Null
Set-Location $Work
$tarball = Join-Path $Work 'dfn.tar.gz'
if (-not (Test-Path $tarball)) {
    $url = 'https://codeload.github.com/Rikorose/DeepFilterNet/tar.gz/refs/heads/main'
    $args = @('-sL', '--max-time', '600', '-o', $tarball, $url)
    if ($Proxy) { $args = @('-x', $Proxy) + $args }
    & curl.exe @args
}
if (Test-Path 'DeepFilterNet-main') { Remove-Item -Recurse -Force 'DeepFilterNet-main' }
tar -xzf $tarball

Write-Host '=== 2/4 调整构建配置 ===' -ForegroundColor Cyan
$src = Join-Path $Work 'DeepFilterNet-main'
Set-Location $src
# 工作区里有本仓库没有的成员（pyDF 等），去掉
@"
[workspace]
resolver = "2"

members = [
  "libDF",
]

[profile.release]
strip = true
debug = false
opt-level = 3
lto = "thin"
"@ | Set-Content Cargo.toml -Encoding UTF8
# 不再把模型编进二进制：运行时从 tar.gz 加载，体积小 11 MB 且可换模型
$c = Get-Content libDF\Cargo.toml -Raw
$c = $c.Replace('capi = ["tract", "default-model", "dep:ndarray", "logging"]',
                'capi = ["tract", "dep:ndarray", "logging"]')
Set-Content libDF\Cargo.toml $c -Encoding UTF8

Write-Host '=== 3/4 编译 libDF ===' -ForegroundColor Cyan
$env:PATH = "$mingw;$env:PATH"
$env:CC = Join-Path $mingw 'gcc.exe'
if ($Proxy) { $env:HTTPS_PROXY = $Proxy; $env:HTTP_PROXY = $Proxy; $env:CARGO_HTTP_PROXY = $Proxy }
Set-Location (Join-Path $src 'libDF')
cargo build --release --features capi
if ($LASTEXITCODE -ne 0) { throw '编译失败' }

Write-Host '=== 4/4 收集产物 ===' -ForegroundColor Cyan
$dll = Join-Path $src 'target\release\df.dll'
$model = Join-Path $src 'models\DeepFilterNet3_onnx.tar.gz'
if (-not (Test-Path $dll)) { throw "找不到 $dll" }
if (-not (Test-Path $model)) { throw "找不到 $model" }
$dst = Join-Path $root 'denoise'
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item $dll $dst -Force
Copy-Item $model $dst -Force

Set-Location $root
Write-Host ''
Write-Host ("=== 完成: denoise\df.dll {0:N1} MB ===" -f ((Get-Item (Join-Path $dst 'df.dll')).Length/1MB)) -ForegroundColor Green