"""
视频合成器 - 流水线第五环（最终输出）
将所有零件组装为成品视频：
  原始画面 + 保留的BGM + 新中文配音 + 中文硬字幕

修复记录：
  - 修复了迭代 amix 导致音量随叠加次数指数级衰减的问题
  - 修复了逐段叠加累积重采样引起的时间轴漂移
  - 改为单次 FFmpeg 调用完成所有 TTS 片段的定位混合
  - 最终合成使用 volume + amix=normalize=0 避免不必要的音量归一化
"""
import json
import os
import subprocess


def compose_final_video(
    original_video: str,
    bgm_path: str,
    synthesis_meta: list[dict],
    output_dir: str,
    output_filename: str = "final_output.mp4",
    subtitle_font_size: int = 14,  # 从 24 调小到 14，更适合竖屏/高分辨率视频
    bgm_volume: float = 0.2  # BGM 音量进一步调低，突出人声
) -> str:
    """
    第五步：将所有音频片段按时间轴混合，叠加字幕，输出成品

    核心思路（修复后）：
    1. 单次 FFmpeg 调用：用 adelay 将每段 TTS 定位到正确时间，用 amix 一次性混合
       -> 避免逐段迭代导致的音量衰减和时间轴漂移
    2. 将 BGM 降低音量
    3. 用 volume 滤镜 + amix(normalize=0) 混合配音和 BGM，保持原始音量
    4. 烧录中文硬字幕（直接烧进画面，任何平台通吃）
    5. 用原始视频的画面 + 新混合音轨 = 最终成品
    """
    os.makedirs(output_dir, exist_ok=True)

    print(f"[步骤 5] 正在组装最终视频...")

    # === 5a. 单次生成完整的中文配音轨 ===
    full_tts_path = os.path.join(output_dir, "full_chinese_voice.wav")

    # 获取原视频总时长
    video_duration = _get_duration(original_video)

    # 过滤掉不存在的 TTS 片段
    valid_segments = [
        seg for seg in synthesis_meta
        if os.path.exists(seg["tts_path"])
    ]

    if not valid_segments:
        print("  ⚠️ 没有有效的 TTS 片段，生成静音配音轨")
        _generate_silence(full_tts_path, video_duration)
    else:
        # 为了避免 FFmpeg 命令行过长（Windows 限制 ~8192 字符），
        # 如果片段过多，分批处理再合并
        MAX_BATCH = 50
        if len(valid_segments) <= MAX_BATCH:
            _mix_tts_clips_single_pass(valid_segments, full_tts_path, video_duration)
        else:
            _mix_tts_clips_batched(valid_segments, full_tts_path, video_duration, output_dir, MAX_BATCH)

    print("  中文配音轨生成完毕")

    # === 5b. 生成翻译后的 SRT 字幕文件（用于烧录硬字幕）===
    srt_path = os.path.join(output_dir, "final_subtitle.srt")
    _export_srt(synthesis_meta, srt_path)

    # === 5c. 最终合成：原始画面 + BGM(降音量) + 中文配音 + 硬字幕 ===
    output_path = os.path.join(output_dir, output_filename)

    # 字幕样式：白色常态字、黑色描边、带浅阴影、底部居中
    subtitle_style = (
        f"FontSize={subtitle_font_size},"
        f"FontName=Microsoft YaHei,"  # 微软雅黑
        f"PrimaryColour=&H00FFFFFF,"  # 白色
        f"OutlineColour=&H00000000,"  # 黑色描边
        f"BackColour=&H66000000,"     # 阴影颜色稍微透明
        f"BorderStyle=1,"             # 1代表非底形（去除难看的黑框），只保留描边
        f"Outline=1.5,"               # 描边粗细
        f"Shadow=1.5,"                # 阴影大小，增加文字立体感
        f"MarginV=40"                 # 提高一点，防止被短视频平台的进度条和文案挡住
    )

    # 转义 Windows 路径中的反斜杠和冒号（FFmpeg subtitles 滤镜的要求）
    srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")

    cmd = [
        "ffmpeg", "-y",
        "-i", original_video,     # 输入 0: 原始视频（取画面）
        "-i", full_tts_path,      # 输入 1: 中文配音轨
        "-i", bgm_path,           # 输入 2: 原始 BGM
        "-filter_complex",
        # BGM 降音量，配音轨保持原始音量（volume=1.0 显式声明）
        # 使用 amix 的 normalize=0 参数，禁止自动音量归一化
        # 这样就不会出现 amix 默认把每个输入音量除以 N 的问题
        f"[1:a]volume=1.0[voice];"
        f"[2:a]volume={bgm_volume}[bgm_low];"
        f"[voice][bgm_low]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mixed_audio];"
        f"[0:v]subtitles='{srt_escaped}':force_style='{subtitle_style}'[subbed_video]",
        "-map", "[subbed_video]",
        "-map", "[mixed_audio]",
        "-c:v", "libx264",
        "-preset", "fast",        # 编码速度优先
        "-crf", "20",             # 高画质
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        output_path
    ]

    print(f"  正在编码最终视频 (这可能需要一些时间)...")
    subprocess.run(cmd, check=True, capture_output=True)

    # 清理中间文件
    if os.path.exists(full_tts_path):
        os.remove(full_tts_path)

    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print("[步骤 5] 最终视频合成完成！")
    print(f"         输出 -> {output_path} ({file_size_mb:.1f} MB)")

    return output_path


def _mix_tts_clips_single_pass(segments: list[dict], output_path: str, total_duration: float):
    """
    单次 FFmpeg 调用：用 adelay 定位每段 TTS，然后 amix 一次性混合。
    
    关键修复点：
    - 所有片段在同一次 amix 中混合，音量不会被迭代衰减
    - 每段的 adelay 直接从原始时间戳计算，无累积误差
    - 使用 normalize=0 禁止 amix 的自动音量归一化
    """
    n = len(segments)
    
    # 构建 FFmpeg 输入列表 + filter_complex
    inputs = []
    filter_parts = []
    
    # 输入 0: 有限长度的静音基底（必须显式限制时长，避免 anullsrc 无限输出导致混音卡死）
    inputs.extend(["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={total_duration}"])
    
    for i, seg in enumerate(segments):
        # 输入 i+1: 各 TTS 片段
        inputs.extend(["-i", seg["tts_path"]])
        
        delay_ms = int(seg["start"] * 1000)
        # 对每个 TTS 片段：提升音量 + 精确延迟定位
        # volume=1.5 是针对 edge-tts 输出偏安静的补偿
        filter_parts.append(
            f"[{i+1}:a]volume=1.5,adelay={delay_ms}|{delay_ms},apad=whole_dur={total_duration}[d{i}]"
        )
    
    # 所有延迟后的片段 + 静音基底一次性 amix
    mix_inputs = "[0:a]" + "".join(f"[d{i}]" for i in range(n))
    # normalize=0: 不做自动音量归一化（核心修复）
    filter_parts.append(
        f"{mix_inputs}amix=inputs={n+1}:duration=first:dropout_transition=0:normalize=0"
    )
    
    filter_complex = ";".join(filter_parts)
    
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-ar", "44100",
        "-ac", "2",
        "-acodec", "pcm_s16le",
        output_path
    ]
    
    print(f"  正在单次混合 {n} 段配音（时间轴精确定位）...")
    subprocess.run(cmd, check=True, capture_output=True)


def _mix_tts_clips_batched(
    segments: list[dict],
    output_path: str,
    total_duration: float,
    output_dir: str,
    batch_size: int
):
    """
    分批混合 TTS 片段（片段过多时避免 FFmpeg 命令行过长）。
    每批单次混合后，最终再将各批次结果叠加。
    """
    batch_files = []
    
    for batch_idx in range(0, len(segments), batch_size):
        batch = segments[batch_idx:batch_idx + batch_size]
        batch_path = os.path.join(output_dir, f"_batch_{batch_idx}.wav")
        _mix_tts_clips_single_pass(batch, batch_path, total_duration)
        batch_files.append(batch_path)
        print(f"  批次 {batch_idx // batch_size + 1} 完成 ({len(batch)} 段)")
    
    if len(batch_files) == 1:
        os.replace(batch_files[0], output_path)
        return
    
    # 将所有批次结果叠加
    n = len(batch_files)
    inputs = []
    for bf in batch_files:
        inputs.extend(["-i", bf])
    
    mix_inputs = "".join(f"[{i}:a]" for i in range(n))
    filter_complex = f"{mix_inputs}amix=inputs={n}:duration=first:dropout_transition=0:normalize=0"
    
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-ar", "44100",
        "-ac", "2",
        "-acodec", "pcm_s16le",
        output_path
    ]
    
    print(f"  正在合并 {n} 个批次...")
    subprocess.run(cmd, check=True, capture_output=True)
    
    # 清理批次临时文件
    for bf in batch_files:
        if os.path.exists(bf):
            os.remove(bf)


def _get_duration(file_path: str) -> float:
    """获取音视频文件的时长"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def _generate_silence(output_path: str, duration: float):
    """生成指定时长的静音 WAV 文件"""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=r=44100:cl=stereo",
        "-t", str(duration),
        "-acodec", "pcm_s16le",
        output_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _export_srt(segments: list[dict], srt_path: str):
    """导出最终的中文字幕 SRT"""
    def _ts(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{i}\n")
            f.write(f"{_ts(seg['start'])} --> {_ts(seg['end'])}\n")
            f.write(f"{seg['translated']}\n\n")


if __name__ == "__main__":
    WORKSPACE = r"F:\MVP\workspace"
    VIDEO = r"F:\MVP\videoplayback.mp4"
    BGM = os.path.join(WORKSPACE, "bgm.wav")

    with open(os.path.join(WORKSPACE, "synthesis_meta.json"), "r", encoding="utf-8") as f:
        meta = json.load(f)

    output = compose_final_video(VIDEO, BGM, meta, WORKSPACE)
    print(f"\n🎉 全流程测试通过！最终视频: {output}")
