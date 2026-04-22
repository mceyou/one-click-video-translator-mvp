# 一键译制机 MVP

一个面向短视频场景的本地译制原型工具。

当前版本支持把 1 到 5 分钟左右的短视频跑通这条流程：

- 提取音频
- 分离人声和背景音
- 语音识别生成字幕
- 调用大模型翻译
- 合成中文配音
- 混音并输出成品视频

当前主打场景：

- 英文短视频 -> 中文配音视频

## 当前形态

这是一个本地运行的 Python 项目，界面使用 Gradio。

启动后会在本机打开一个网页界面，但它本质上仍然是本地应用，不是云端网页服务。

## 项目结构

- `app_gradio.py`: Gradio 图形界面入口
- `pipeline.py`: 总流程入口
- `core/audio_separator.py`: 提取音频、分离人声与背景音
- `core/speech_recognizer.py`: 语音识别
- `core/translator.py`: 字幕翻译
- `core/tts_synthesizer.py`: 配音合成
- `core/video_composer.py`: 最终视频合成
- `api_config.example.json`: API 配置示例

## 环境要求

建议环境：

- Windows
- Python 3.11 及以上
- 已安装 `ffmpeg` 和 `ffprobe`
- NVIDIA 显卡可获得更快速度

兼容说明：

- 如果检测到可用 CUDA，Whisper 会优先使用 GPU
- 如果没有 NVIDIA/CUDA，也会自动回退到 CPU 模式
- CPU 模式可以运行，但速度会明显变慢

## 安装依赖

先安装 Python 依赖：

```powershell
pip install -r requirements.txt
```

确认系统中可以直接调用：

```powershell
ffmpeg -version
ffprobe -version
```

如果上面两条命令报错，需要先安装 FFmpeg 并加入系统环境变量。

## 配置翻译 API

在项目根目录创建 `api_config.json`。

你可以直接复制 `api_config.example.json`，然后改成自己的真实配置：

```json
{
  "api_key": "你的真实API_KEY",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat"
}
```

也支持用环境变量：

```powershell
$env:VIDEO_TRANSLATOR_API_KEY="你的真实API_KEY"
```

可选环境变量：

- `VIDEO_TRANSLATOR_API_KEY`
- `VIDEO_TRANSLATOR_BASE_URL`
- `VIDEO_TRANSLATOR_MODEL`

## 启动方式

运行：

```powershell
python app_gradio.py
```

启动后会自动打开本地网页界面，默认地址通常是：

```text
http://127.0.0.1:7860
```

## 使用流程

1. 打开界面
2. 上传一个短视频
3. 选择源语言
4. 选择目标语言
5. 选择配音音色
6. 点击“开始译制”
7. 等待输出成品视频和日志

每次运行的中间文件和输出文件会保存在：

- `workspace/gradio_runs/时间戳目录`

## 当前推荐使用范围

建议先用于：

- 1 到 5 分钟短视频
- 语音清晰的视频
- 单人解说或对白相对清楚的视频

## 已知限制

- 当前更偏向 MVP，不是成熟商用版本
- 不保证所有语言方向都同样稳定
- 没有时间轴精修界面
- 没有批量任务管理
- 没有安装包
- 首次运行可能需要下载模型，速度会更慢
- CPU 环境下整体处理速度可能较慢
