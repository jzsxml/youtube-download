# Download ffmpeg essentials (Windows x64) into vendor/ffmpeg for bundling.
# Source: https://www.gyan.dev/ffmpeg/builds/ (essentials build)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Dest = Join-Path $Root "vendor\ffmpeg"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

if (Test-Path (Join-Path $Dest "ffmpeg.exe")) {
    Write-Host "ffmpeg already present: $Dest"
    exit 0
}

$Url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$Zip = Join-Path $env:TEMP "ffmpeg-release-essentials.zip"
$Extract = Join-Path $env:TEMP "ffmpeg-essentials-extract"

Write-Host "Downloading $Url ..."
Invoke-WebRequest -Uri $Url -OutFile $Zip -UseBasicParsing

if (Test-Path $Extract) { Remove-Item -Recurse -Force $Extract }
Expand-Archive -Path $Zip -DestinationPath $Extract

$ffmpeg = Get-ChildItem -Path $Extract -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
if (-not $ffmpeg) {
    throw "ffmpeg.exe not found inside archive"
}
$binDir = $ffmpeg.DirectoryName
Copy-Item -Force (Join-Path $binDir "ffmpeg.exe") $Dest
$probe = Join-Path $binDir "ffprobe.exe"
if (Test-Path $probe) {
    Copy-Item -Force $probe $Dest
}

$notice = @"
FFmpeg is bundled for convenience when distributing YouTubeDownloader.
Obtain source and license: https://ffmpeg.org/legal.html
This build type: gyan.dev ffmpeg-release-essentials (third-party binary).
"@
Set-Content -Path (Join-Path $Dest "FFMPEG-NOTICE.txt") -Value $notice -Encoding UTF8

Write-Host "Installed to $Dest"