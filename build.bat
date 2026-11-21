@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo 请先创建虚拟环境并安装依赖:
  echo   python -m venv .venv
  echo   .\.venv\Scripts\pip install -r requirements-build.txt
  exit /b 1
)

echo Installing build deps...
".venv\Scripts\python.exe" -m pip install -q -r requirements-build.txt
if errorlevel 1 exit /b 1

echo Fetching bundled ffmpeg (vendor\ffmpeg)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\fetch_ffmpeg_windows.ps1"
if errorlevel 1 exit /b 1

echo Building YouTubeDownloader (PyInstaller onedir)...
".venv\Scripts\pyinstaller.exe" --noconfirm --clean YouTubeDownloader.spec
if errorlevel 1 exit /b 1

set "OUT=%~dp0dist\YouTubeDownloader"
if not exist "%OUT%\YouTubeDownloader.exe" (
  echo Build failed: missing %OUT%\YouTubeDownloader.exe
  exit /b 1
)

(
  echo @echo off
  echo cd /d "%%~dp0"
  echo start "" "%%~dp0YouTubeDownloader.exe"
) > "%OUT%\启动 YouTube 下载器.bat"

if not exist "%~dp0vendor\ffmpeg\ffmpeg.exe" (
  echo WARNING: vendor\ffmpeg\ffmpeg.exe missing; dist will not include ffmpeg.
) else (
  if not exist "%OUT%\ffmpeg" mkdir "%OUT%\ffmpeg"
  copy /Y "%~dp0vendor\ffmpeg\ffmpeg.exe" "%OUT%\ffmpeg\" >nul
  if exist "%~dp0vendor\ffmpeg\ffprobe.exe" copy /Y "%~dp0vendor\ffmpeg\ffprobe.exe" "%OUT%\ffmpeg\" >nul
  if exist "%~dp0vendor\ffmpeg\FFMPEG-NOTICE.txt" copy /Y "%~dp0vendor\ffmpeg\FFMPEG-NOTICE.txt" "%OUT%\ffmpeg\" >nul
)

echo.
echo OK: "%OUT%\YouTubeDownloader.exe"
echo      或双击 "%OUT%\启动 YouTube 下载器.bat"
echo.
echo 分发时请携带整个 YouTubeDownloader 文件夹（含 ffmpeg 子目录）。
endlocal
exit /b 0