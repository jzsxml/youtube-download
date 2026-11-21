# YouTube Downloader

Windows 桌面端 YouTube 下载工具：**Python · PySide6 · yt-dlp**。支持多任务并行、内置登录、Cookie 配置、深色/白天主题，可打包为免安装 exe。

> 请仅下载您有权访问的内容，遵守当地法律与 [YouTube 服务条款](https://www.youtube.com/t/terms)。

---

## 功能概览

| 类别 | 说明 |
|------|------|
| **下载** | 视频 / Shorts / 播放列表 URL；可展开列表并行下载；画质：最佳 / 1080p / 720p / 仅音频 (mp3) |
| **任务** | 暂停、继续、取消、重试；断点续传（`.part`）；关闭窗口时确认（可最小化后台继续） |
| **登录** | 应用内 WebView 登录、Cookie 配置命名保存、JSON 导入、cookies 文件 |
| **界面** | 深色 / 白天主题；下载列表进度、速度/剩余时间；系统托盘快捷菜单 |
| **性能** | 后台解析与入队，多 worker 下载；进度 UI 节流，列表增量刷新 |

默认保存目录：`%USERPROFILE%\Downloads\YouTube`（可在界面修改）。

---

## 给最终用户：直接用打包版

无需安装 Python。

1. 获取 **`dist\YouTubeDownloader`** 整个文件夹（需包含子目录 **`ffmpeg`**）。
2. 双击 **`YouTubeDownloader.exe`** 或 **`启动 YouTube 下载器.bat`**。
3. 粘贴 URL → 选择画质 → **开始下载**。

| 注意 | |
|------|--|
| 不要只复制一个 `.exe`，必须连同 **`_internal`**（或 PyInstaller 生成的依赖目录）和 **`ffmpeg`** 一起分发 |
| 配置与 Cookie 在本机：`%LOCALAPPDATA%\YouTubeDownloader\` |
| 高清合并依赖 **ffmpeg**；官方 `build.bat` 构建版已自带，无需用户单独安装 |

---

## 给开发者：从源码运行

### 环境要求

- Windows 10+
- Python 3.11+
- **ffmpeg**：任选其一  
  - 运行 `scripts\fetch_ffmpeg_windows.ps1` → 使用 `vendor\ffmpeg\`（推荐）  
  - 或本机安装 [ffmpeg](https://ffmpeg.org/) 并加入 **PATH**  
- 可选：本机 **Node.js**（部分 YouTube 解析可增强 yt-dlp EJS 能力）

### 安装与运行

```powershell
git clone https://github.com/YOUR_USER/YOUR_REPO.git
cd YOUR_REPO

python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

# 首次建议拉取内置 ffmpeg（与打包同源）
powershell -ExecutionPolicy Bypass -File scripts\fetch_ffmpeg_windows.ps1

python -m app.main
```

或双击根目录 **`run.bat`**。

主要依赖：`PySide6`、`PySide6-Addons`（应用内登录需要 **Qt WebEngine**）、`yt-dlp`。

---

## 打包发布（PyInstaller）

```powershell
.\.venv\Scripts\activate
pip install -r requirements-build.txt
.\build.bat
```

`build.bat` 会：

1. 下载 **ffmpeg** essentials 到 `vendor\ffmpeg\`（若不存在）  
2. 执行 `YouTubeDownloader.spec`（**onedir**，含 WebEngine）  
3. 将 ffmpeg 复制到 `dist\YouTubeDownloader\ffmpeg\`  
4. 生成 `启动 YouTube 下载器.bat`

产物路径：**`dist\YouTubeDownloader\`**

- 体积较大（含 Qt WebEngine + 依赖）属正常  
- 分发时压缩/拷贝 **整个文件夹**  
- FFmpeg 许可说明见 `vendor\ffmpeg\FFMPEG-NOTICE.txt`（构建后亦在 `dist\...\ffmpeg\`）

---

## 使用说明

### 公开视频

登录态选择 **「不登录（公开视频）」**，粘贴 URL 即可下载。

### 年龄限制 / 需登录视频

1. 点击 **「在应用内登录 YouTube」**，完成 Google / 扫码登录。  
2. 年龄限制视频：在 WebView 中打开目标页并确认年满 18 岁后再 **「保存登录状态」**。  
3. 可将 Cookie **保存为配置**（命名），登录态选 **「已保存 Cookie 配置」**。

### Cookie 其它方式

| 方式 | 说明 |
|------|------|
| **导入 JSON Cookie** | 浏览器扩展导出的 JSON → 转为本机会话 |
| **cookies 文件** | 高级区启用，指定 Netscape `cookies.txt` |
| **Edge/Chrome 实时读取** | 常因 DPAPI / 文件锁失败；**不推荐**，优先应用内登录 |

### 播放列表

勾选 **「展开播放列表」**：仅当 URL 含 `list=` 或为播放列表链接时展开为多任务；普通 `watch?v=` 不会额外解析。

### 下载列表操作

- **暂停 / 继续**：暂停保留进度，继续时断点续传  
- **取消**：放弃任务（仍可 **重试** 续传）  
- **清除已完成 / 重试失败 / 清空列表**  
- 有关闭前台下载时：**最小化继续下载** 或 **退出**（未下完文件保留在下载目录）

---

## 本机数据目录

路径：`%LOCALAPPDATA%\YouTubeDownloader\`

| 文件 / 用途 | |
|-------------|--|
| `app_settings.json` | 界面主题等 |
| `profiles.json` / 各配置目录 | 命名 Cookie 配置 |
| `youtube_cookies.txt` | 当前会话（部分流程使用） |
| `session_meta.json` | 会话元信息 |

**勿将 Cookie 文件提交到 Git。**

---

## 常见问题

**`Requested format is not available`**  
换画质预设或更新 yt-dlp；已登录时可尝试「不登录」下公开回退（程序内部分场景会自动重试）。

**`Sign in to confirm your age`**  
应用内登录并在页面确认年龄，保存 Cookie 后使用「已保存 Cookie 配置」。

**`Could not copy Chrome cookie database`**  
Chrome/Edge 正在运行导致；不要用实时读浏览器，改用应用内登录或 JSON。

**下载合并失败 / 无声音**  
确认 ffmpeg 可用（日志会显示 `ffmpeg（内置）` 或 `ffmpeg（系统）`）。打包版检查是否存在 `ffmpeg\ffmpeg.exe`。

**打包后无法打开 / WebEngine 白屏**  
确认分发完整目录；勿杀毒软件误删 `QtWebEngineProcess` 等文件。

**界面「未找到 ffmpeg」**  
源码：执行 `fetch_ffmpeg_windows.ps1`；打包：重新 `build.bat` 并带上 `ffmpeg` 目录。

---

## 项目结构

```
app/
  main.py              # 入口
  config.py            # 默认路径、画质预设
  paths.py             # 开发 / PyInstaller 资源路径
  core/
    download_manager.py
    downloader.py
    ffmpeg_locator.py
    auth.py, cookie_*.py, validators.py, errors.py, ...
  ui/
    main_window.py
    login_dialog.py
    themes.py, themes/*.qss
    app_icon.py
  resources/app.ico
scripts/
  fetch_ffmpeg_windows.ps1
  build_app_icon.py
vendor/ffmpeg/         # 构建时下载，不进 Git（*.exe）
run.bat
build.bat
YouTubeDownloader.spec
requirements.txt
requirements-build.txt
.github/workflows/ci.yml
```

---

## 第三方组件与许可

| 组件 | 链接 | 说明 |
|------|------|------|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 下载引擎 | 须遵守其许可与平台规则 |
| [PySide6 / Qt](https://doc.qt.io/qtforpython/) | 界面与 WebEngine | 本仓库 MIT；Qt 另有许可条款 |
| [FFmpeg](https://ffmpeg.org/) | 合并音视频、转 mp3 | 打包版附带 gyan.dev essentials 构建，见 `FFMPEG-NOTICE.txt` |

本项目源码：**MIT**，见 [LICENSE](LICENSE)。再分发打包程序时请保留上述第三方许可与声明。

---

## 开发检查

```powershell
python -m compileall -q app
```

CI（`.github/workflows/ci.yml`）在 Windows 上对 `app` 执行 `compileall`。