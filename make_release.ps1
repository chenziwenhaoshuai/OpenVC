# 组装可分发的 release 文件夹（含虚拟声卡驱动）
#
#   powershell -ExecutionPolicy Bypass -File .\make_release.ps1
#   powershell -ExecutionPolicy Bypass -File .\make_release.ps1 -Zip
#
# 产物：
#   release\OpenVC-1.0.0\          整个文件夹压成 zip 就能发给别人
#   release\OpenVC-1.0.0.zip       加 -Zip 时生成

param(
    [string]$Version = "1.0.0",
    [switch]$Zip,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$app = Join-Path $root 'dist-portable\OpenVC'
$rel = Join-Path $root "release\OpenVC-$Version"

if (-not $SkipBuild) {
    Write-Host '=== 构建程序 ===' -ForegroundColor Cyan
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'build_portable.ps1')
    if ($LASTEXITCODE -ne 0) { throw '构建失败' }
}
if (-not (Test-Path (Join-Path $app 'OpenVC.exe'))) { throw "缺少 $app\OpenVC.exe" }

Write-Host '=== 组装 release ===' -ForegroundColor Cyan
if (Test-Path $rel) { Remove-Item -Recurse -Force $rel }
New-Item -ItemType Directory -Force -Path $rel | Out-Null
robocopy $app $rel /E /NFL /NDL /NJH /NJS /NP /MT:16 | Out-Null
Remove-Item -Recurse -Force (Join-Path $rel 'data') -ErrorAction SilentlyContinue

# --- 虚拟声卡驱动（VB-Audio VB-CABLE 原始安装包，未做任何修改）---
$drv = Join-Path $rel '驱动'
New-Item -ItemType Directory -Force -Path $drv | Out-Null
$pack = Get-ChildItem (Join-Path $root 'packaging\driver') -Filter 'VBCABLE_Driver_Pack*.zip' -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $pack) { throw '缺少驱动包 packaging\driver\VBCABLE_Driver_Pack*.zip' }
Copy-Item -Force $pack.FullName $drv

$guide = @"
虚拟声卡安装说明（必装）
========================================

1. 解压本文件夹里的 $($pack.Name)
2. 右键 VBCABLE_Setup_x64.exe -> 以管理员身份运行
3. 点 "Install Driver"，等待完成
4. 重启电脑

装好后，在会议软件里把麦克风选成：
    CABLE Output (VB-Audio Virtual Cable)

然后在变声器里把"虚拟麦克风（输出）"选成：
    CABLE Input (VB-Audio Virtual Cable)

区分方法：
    CABLE Input  = 我们把声音"送进去"的一端
    CABLE Output = 会议软件"取走"声音的一端
    选反了对方听不到声音。

如果安装后看不到设备：
  - 控制面板 -> 设备管理器 -> 声音、视频和游戏控制器，看有没有 VB-Audio Virtual Cable
  - 或者重装一次，必须"以管理员身份运行"

关于这个驱动：
  由 VB-Audio 提供，免费（赞助制）：https://vb-audio.com/Cable/
  本文件夹内是官方原始安装包，未做任何修改。
"@
$bom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText((Join-Path $drv '安装虚拟声卡.txt'), ($guide -replace "`r`n","`n" -replace "`n","`r`n"), $bom)
Set-Content (Join-Path $drv '来源.txt') -Value "VB-CABLE Virtual Audio Device`r`n官方主页: https://vb-audio.com/Cable/`r`n下载: https://download.vb-audio.com/Download_CABLE/$($pack.Name)`r`n本包为官方原版，未修改。" -Encoding UTF8

# --- 文档 ---
Copy-Item -Force (Join-Path $root '使用说明.txt') $rel -ErrorAction SilentlyContinue
Copy-Item -Force (Join-Path $root 'README.md') $rel -ErrorAction SilentlyContinue
Copy-Item -Force (Join-Path $root 'SOURCES.md') $rel -ErrorAction SilentlyContinue
Copy-Item -Force (Join-Path $root 'THIRD_PARTY.md') $rel -ErrorAction SilentlyContinue

$size = (Get-ChildItem $rel -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ''
Write-Host ("=== 完成: {0}  ({1:N0} MB) ===" -f $rel, $size) -ForegroundColor Green
Write-Host '   把这个文件夹（或下面的 zip）发给别人即可'

if ($Zip) {
    $zipPath = Join-Path $root "release\OpenVC-$Version.zip"
    if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
    Write-Host '=== 压缩 ===' -ForegroundColor Cyan
    Compress-Archive -Path $rel -DestinationPath $zipPath -CompressionLevel Optimal
    Write-Host ("   {0}  ({1:N0} MB)" -f $zipPath, ((Get-Item $zipPath).Length/1MB)) -ForegroundColor Green

    # 发布说明（含校验值），模板在 packaging/release-notes.md
    $tpl = Join-Path $root 'packaging\release-notes.md'
    if (Test-Path $tpl) {
        $hash = (Get-FileHash $zipPath -Algorithm SHA256).Hash
        $text = [System.IO.File]::ReadAllText($tpl, [System.Text.Encoding]::UTF8)
        $text = $text.Replace('__SHA256__', $hash).Replace('__VERSION__', $Version)
        $outNotes = Join-Path $root "release\OpenVC-$Version-notes.md"
        [System.IO.File]::WriteAllText($outNotes, $text, (New-Object System.Text.UTF8Encoding($true)))
        Write-Host ("   发布说明: {0}" -f $outNotes)
    }
}