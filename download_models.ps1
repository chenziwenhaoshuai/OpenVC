# Download the ONNX models used by the voice changer.
#
#   powershell -ExecutionPolicy Bypass -File .\download_models.ps1
#   powershell -ExecutionPolicy Bypass -File .\download_models.ps1 -Lite   # 不下说话人编码器
#
# Source: https://huggingface.co/kiarina/MeanVC2-ONNX
#   conversion graphs : Apache-2.0 (derived from ASLP-lab/MeanVC2)
#   speaker encoder   : CC BY-SA 3.0 (Microsoft WavLM-Large + ECAPA-TDNN)
#
# huggingface.co is tried first, hf-mirror.com is the fallback.

param([switch]$Lite, [string]$Proxy = "")

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$dir = Join-Path $root 'onnx'
New-Item -ItemType Directory -Force -Path $dir | Out-Null

$files = @(
    @{ name = 'fbank.onnx';      size = 1MB    },
    @{ name = 'asr.int8.onnx';   size = 27MB   },
    @{ name = 'gtm.onnx';        size = 16MB   },
    @{ name = 'dit.int8.onnx';   size = 13MB   },
    @{ name = 'vocos.int8.onnx'; size = 12MB   }
)
if (-not $Lite) { $files += @{ name = 'speaker.int8.onnx'; size = 369MB } }

$mirrors = @(
    'https://huggingface.co/kiarina/MeanVC2-ONNX/resolve/main',
    'https://hf-mirror.com/kiarina/MeanVC2-ONNX/resolve/main'
)

foreach ($f in $files) {
    $name = $f.name
    $dst = Join-Path $dir $name
    $want = $f.size
    if ((Test-Path $dst) -and ((Get-Item $dst).Length -ge $want * 0.95)) {
        Write-Host ("  [skip] {0,-22} {1,7:N1} MB" -f $name, ((Get-Item $dst).Length/1MB))
        continue
    }
    $got = $false
    foreach ($mirror in $mirrors) {
        Write-Host ("  [get ] {0,-22} <- {1}" -f $name, ([uri]$mirror).Host)
        $cargs = @('-sL', '--max-time', '900', '-C', '-', '-o', $dst, "$mirror/$name")
        if ($Proxy) { $cargs = @('-x', $Proxy) + $cargs }
        & curl.exe @cargs
        if ((Test-Path $dst) -and ((Get-Item $dst).Length -ge $want * 0.95)) { $got = $true; break }
    }
    if (-not $got) { throw "下载失败: $name" }
    Write-Host ("        -> {0:N1} MB" -f ((Get-Item $dst).Length/1MB))
}

$lic = Join-Path $dir 'licenses'
New-Item -ItemType Directory -Force -Path $lic | Out-Null
$notice = Join-Path $root 'packaging\licenses\NOTICE'
if (Test-Path $notice) { Copy-Item -Force $notice (Join-Path $lic 'NOTICE') }

$total = (Get-ChildItem $dir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ''
Write-Host ("=== 完成: onnx/ 共 {0:N1} MB ===" -f $total) -ForegroundColor Green