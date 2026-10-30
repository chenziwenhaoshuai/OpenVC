# Build the portable (no installer, no PyInstaller) OpenVC build.
#
#   powershell -ExecutionPolicy Bypass -File .\build_portable.ps1
#   powershell -ExecutionPolicy Bypass -File .\make_release.ps1    # 带驱动的分发版
#
# Output: dist-portable\OpenVC\OpenVC.exe   (the whole folder can be zipped)
#
# How it works: the official *embeddable* CPython + only the packages this app
# imports + a 21 KB C launcher. Nothing is unpacked at startup, so the window
# appears in well under a second. No PyTorch: inference runs on ONNX Runtime.

param([switch]$SkipDeps)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$sp = Join-Path $root '.venv\Lib\site-packages'
$out = Join-Path $root 'dist-portable\OpenVC'
$rt = Join-Path $out 'runtime'
$embed = Join-Path $root 'packaging\python-embed.zip'
$onnx_src = Join-Path $root 'onnx'

if (-not (Test-Path $embed)) {
    # Official embeddable CPython, fetched on demand so a fresh clone can build.
    Write-Host '=== 0/5 下载内嵌 Python ===' -ForegroundColor Cyan
    $pyMirrors = @(
        'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip',
        'https://mirrors.huaweicloud.com/python/3.11.9/python-3.11.9-embed-amd64.zip'
    )
    New-Item -ItemType Directory -Force -Path (Split-Path $embed) | Out-Null
    $got = $false
    foreach ($u in $pyMirrors) {
        Write-Host ("  [get ] python-3.11.9-embed-amd64.zip <- {0}" -f ([uri]$u).Host)
        & curl.exe -sL --max-time 600 -o $embed $u
        if ((Test-Path $embed) -and ((Get-Item $embed).Length -gt 5MB)) { $got = $true; break }
    }
    if (-not $got) { throw "下载 python-3.11.9-embed-amd64.zip 失败" }
    Write-Host ("  -> {0:N1} MB" -f ((Get-Item $embed).Length/1MB))
}
if (-not (Test-Path $onnx_src)) { throw "缺少 onnx/ 目录，请先运行 download_models.ps1" }

Write-Host '=== 1/5 解压内嵌 Python ===' -ForegroundColor Cyan
if (Test-Path $rt) { Remove-Item -Recurse -Force $rt }
New-Item -ItemType Directory -Force -Path $rt | Out-Null
Expand-Archive -Path $embed -DestinationPath $rt -Force
Write-Host ("  runtime: {0:N0} MB" -f ((Get-ChildItem $rt -Recurse -File | Measure-Object Length -Sum).Sum/1MB))

$deps = Join-Path $rt 'Lib\site-packages'
if (-not $SkipDeps) {
    Write-Host '=== 2/5 复制依赖（白名单，不含 torch） ===' -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $deps | Out-Null

    # Copy everything except what this app provably never imports. A whitelist
    # is too easy to under-run: sounddevice needs cffi, soundfile needs
    # typing_extensions, onnxruntime needs coloredlogs, and so on.
    $skipPatterns = @('torch*', 'torchaudio*', 'torchgen*', 'torio*', 'transformers*',
                      'scipy*', 'sympy*', 'mpmath*', 'networkx*', 'onnx', 'onnx-*', 'onnx_ir*',
                      'onnxscript*', 'PyInstaller*', 'pip*', 'setuptools*', 'wheel*',
                      'pkg_resources*', 'pandas*', 'matplotlib*', 'IPython*', 'jupyter*',
                      'notebook*', 'huggingface_hub*', 'hf_xet*', 'tokenizers*', 'pygments*',
                      'rich*', 's3prl*', 'safetensors*', 'x_transformers*', 'einops*',
                      'einx*', 'loguru*', '__pycache__')
    Get-ChildItem -Path $sp | Where-Object {
        $n = $_.Name
        $drop = $false
        foreach ($pat in $skipPatterns) { if ($n -like $pat) { $drop = $true } }
        -not $drop
    } | ForEach-Object {
        if ($_.PSIsContainer) {
            robocopy $_.FullName (Join-Path $deps $_.Name) /E /NFL /NDL /NJH /NJS /NP /MT:16 | Out-Null
        } else {
            Copy-Item $_.FullName $deps -Force
        }
    }
    Write-Host ("  site-packages: {0:N0} MB" -f ((Get-ChildItem $deps -Recurse -File | Measure-Object Length -Sum).Sum/1MB))
}

Write-Host '=== 3/5 精简 Qt（只留 Core/Gui/Widgets） ===' -ForegroundColor Cyan
$qt = Join-Path $deps 'PySide6'
if (Test-Path $qt) {
    $dropFiles = @(
        'Qt6Quick.dll','Qt6QuickControls2.dll','Qt6QuickControls2Impl.dll','Qt6QuickWidgets.dll',
        'Qt6QuickLayouts.dll','Qt6QuickTemplates2.dll','Qt6Qml.dll','Qt6QmlModels.dll',
        'Qt6QmlWorkerScript.dll','Qt6QmlMeta.dll','Qt6Designer.dll','Qt6DesignerComponents.dll',
        'Qt6Test.dll','Qt6Sql.dll','Qt6Network.dll','Qt6DBus.dll','Qt6Concurrent.dll',
        'Qt6Svg.dll','Qt6Xml.dll','Qt6PrintSupport.dll','Qt6OpenGL.dll','Qt6OpenGLWidgets.dll',
        'Qt6VirtualKeyboard.dll','opengl32sw.dll','qmlls.exe','qmlcachegen.exe','qmlformat.exe',
        'qmlimportscanner.exe','qmljsrootgen.exe','qmltyperegistrar.exe','lrelease.exe',
        'lupdate.exe','designer.exe','linguist.exe'
    )
    foreach ($f in $dropFiles) {
        $p = Join-Path $qt $f
        if (Test-Path $p) { Remove-Item -Force $p }
    }
    $dropPy = @(
        'QtOpenGL.pyd','QtQml.pyd','QtQuick.pyd','QtQuickWidgets.pyd','QtQuickControls2.pyd',
        'QtDesigner.pyd','QtTest.pyd','QtSql.pyd','QtNetwork.pyd','QtDBus.pyd','QtConcurrent.pyd',
        'QtSvg.pyd','QtSvgWidgets.pyd','QtXml.pyd','QtPrintSupport.pyd','QtHelp.pyd',
        'QtUiTools.pyd','QtStateMachine.pyd','QtOpenGLWidgets.pyd'
    )
    foreach ($p in $dropPy) {
        $full = Join-Path $qt $p
        if (Test-Path $full) { Remove-Item -Recurse -Force $full }
    }
    foreach ($d in 'qml','translations','metatypes','typesystems','include','scripts','doc','support','glue') {
        $full = Join-Path $qt $d
        if (Test-Path $full) { Remove-Item -Recurse -Force $full }
    }
    Get-ChildItem $qt -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host '=== 4/5 应用 + ONNX 模型 ===' -ForegroundColor Cyan
@('python311.zip', '.', 'Lib\site-packages', '..') |
    Set-Content (Join-Path $rt 'python311._pth') -Encoding ASCII

New-Item -ItemType Directory -Force -Path (Join-Path $out 'app') | Out-Null
foreach ($d in 'backend', 'ui') {
    $dest = Join-Path $out "app\$d"
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Copy-Item -Recurse -Force (Join-Path $root "app\$d") $dest
}
Copy-Item -Force (Join-Path $root 'app\main_qt.py') (Join-Path $out 'app\main_qt.py')
Get-ChildItem (Join-Path $out 'app') -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

$onnx_dir = Join-Path $out 'onnx'
if (Test-Path $onnx_dir) { Remove-Item -Recurse -Force $onnx_dir }
New-Item -ItemType Directory -Force -Path $onnx_dir | Out-Null
foreach ($f in 'fbank.onnx','asr.int8.onnx','gtm.onnx','dit.int8.onnx','vocos.int8.onnx') {
    $src = Join-Path $onnx_src $f
    if (-not (Test-Path $src)) { throw "缺少 onnx/$f" }
    Copy-Item -Force $src (Join-Path $onnx_dir $f)
}
# The speaker encoder (369 MB) is NOT shipped: the app downloads it the first
# time someone adds a voice. That keeps the package under 300 MB.
Write-Host '  说话人编码器按需下载，未随包分发'

$lic = Join-Path $onnx_dir 'licenses'
New-Item -ItemType Directory -Force -Path $lic | Out-Null
Get-ChildItem (Join-Path $onnx_src 'licenses') -File -ErrorAction SilentlyContinue |
    Copy-Item -Destination $lic -Force

# Optional DeepFilterNet3 denoiser (native libDF + official model).
$dn_src = Join-Path $root 'denoise'
if (Test-Path $dn_src) {
    $dn_dst = Join-Path $out 'denoise'
    if (Test-Path $dn_dst) { Remove-Item -Recurse -Force $dn_dst }
    Copy-Item -Recurse -Force $dn_src $dn_dst
    Write-Host '  已包含降噪组件 (DeepFilterNet3)'
} else {
    Write-Host '  [warn] 缺少 denoise/ 目录，降噪功能不可用'
}

foreach ($d in 'voices', 'assets') {
    $dest = Join-Path $out $d
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Copy-Item -Recurse -Force (Join-Path $root $d) $dest
}
Remove-Item -Recurse -Force (Join-Path $out 'data') -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path (Join-Path $out 'data') | Out-Null
Copy-Item -Force (Join-Path $root '使用说明.txt') $out -ErrorAction SilentlyContinue
Copy-Item -Force (Join-Path $root 'README.md') $out -ErrorAction SilentlyContinue

& (Join-Path $rt 'python.exe') -m compileall -q -j 0 (Join-Path $out 'app') 2>&1 | Out-Null

Write-Host '=== 5/5 编译启动器 ===' -ForegroundColor Cyan
$gcc = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages\BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe\mingw64\bin\gcc.exe'
if (-not (Test-Path $gcc)) { $gcc = 'gcc' }
Push-Location (Join-Path $root 'packaging')
$windres = Join-Path (Split-Path $gcc) 'windres.exe'
if (Test-Path $windres) {
    & $windres openvc.rc -O coff -o openvc.res
    if ($LASTEXITCODE -ne 0) { throw '图标资源编译失败' }
    & $gcc -municode -mwindows -O2 -s -o (Join-Path $out 'OpenVC.exe') 'launcher.c' 'openvc.res'
} else {
    & $gcc -municode -mwindows -O2 -s -o (Join-Path $out 'OpenVC.exe') 'launcher.c'
}
if ($LASTEXITCODE -ne 0) { throw '启动器编译失败' }
Pop-Location

$size = (Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
Write-Host ''
Write-Host ("=== 完成: {0}  ({1:N2} GB) ===" -f $out, $size) -ForegroundColor Green
Write-Host ("   双击 {0}" -f (Join-Path $out 'OpenVC.exe'))