# YouTube Downloader

Windows 桌面端 YouTube 下载工具：**Python + PySide6 + yt-dlp**，深色 UI，多任务并行，支持 Cookie 配置与内置登录。

> 请仅下载您有权访问的内容，遵守当地法律与 [YouTube 服务条款](https://www.youtube.com/t/terms)。

## 功能

- 视频 / 播放列表 URL，多线程并行（可设最大并发 1–8）
- 画质：最佳 / 1080p / 720p / 仅音频 (mp3)
- 登录：**Cookie 配置** 命名保存、应用内登录、JSON 导入、可选 cookies 文件
- 下载列表：取消、重试、打开文件、复制链接；清除已完成 / 重试失败
- 后台提交任务，界面不卡死

## 环境要求

- Windows 10+
- Python 3.11+
- [ffmpeg](https://ffmpeg.org/)（合并高清音视频，加入系统 `PATH`）

## 安装

```powershell
git clone https://github.com/YOUR_USER/YOUR_REPO.git
cd YOUR_REPO
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

依赖包含 `PySide6`、`PySide6-Addons`（内置 Web 登录需要 WebEngine）。

## 运行

```powershell
.\.venv\Scripts\activate
python -m app.main
```

或双击项目根目录 `run.bat`。

## 使用提示

1. **公开视频**：登录态选「不登录（公开视频）」即可。
2. **年龄限制 / 需登录**：推荐「在应用内登录 YouTube」→ 保存为 **Cookie 配置** → 登录态选「已保存 Cookie 配置」。
3. 浏览器导出的 **JSON Cookie**：点「导入 JSON Cookie」。
4. Windows 上「从浏览器导入」常因 DPAPI 失败，请优先应用内登录或 JSON。

本机数据目录（不随仓库分发）：`%LOCALAPPDATA%\YouTubeDownloader\`

## 项目结构

```
app/
  main.py
  config.py
  core/          # yt-dlp、任务队列、Cookie 配置
  ui/            # 主窗口、登录对话框、styles.qss
requirements.txt
run.bat
```

## 第三方依赖

- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [PySide6](https://doc.qt.io/qtforpython/)

## License

MIT — 见 [LICENSE](LICENSE)。分发或打包时请同时遵守上述第三方许可证。