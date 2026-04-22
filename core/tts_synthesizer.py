"""
语音合成器 - 流水线第四环
使用微软 Edge TTS（免费、高质量）将翻译后的中文文本合成为语音片段。
每个字幕段落生成独立的音频文件，便于后续按时间轴精确对齐。
"""
import asyncio
import json
import os
import re

import edge_tts


# 可选的中文语音列表（微软 Edge TTS 免费提供）
VOICE_OPTIONS = {
    "女声-温柔": "zh-CN-XiaoxiaoNeural",
    "女声-活泼": "zh-CN-XiaoyiNeural",
    "男声-沉稳": "zh-CN-YunjianNeural",
    "男声-热血": "zh-CN-YunxiNeural",
    # 东南亚出海备用
    "越南语-女": "vi-VN-HoaiMyNeural",
    "日语-女": "ja-JP-NanamiNeural",
    "英语-男": "en-US-GuyNeural",
}

DEFAULT_VOICE = "zh-CN-YunxiNeural"  # 默认：男声-热血（最适合短视频解说）


async def _synthesize_one(text: str, output_path: str, voice: str, rate: str = "+0%", volume: str = "+50%"):
    """合成单段语音，并适当放大音量（针对短视频场景）"""
    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
    await communicate.save(output_path)


def _sanitize_tts_text(text: str) -> str:
    """清理容易导致 TTS 不稳定的文本，尽量保留原意。"""
    cleaned = (text or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.replace('"', "")
    cleaned = cleaned.replace("'", "")
    cleaned = cleaned.replace("`", "")
    return cleaned


async def _synthesize_with_retries(
    text: str,
    output_path: str,
    voice: str,
    rate: str = "+0%",
    volume: str = "+50%",
    retries: int = 3,
):
    """
    Edge TTS 对少数句子会偶发 NoAudioReceived。
    这里做多次重试，并在后续尝试中使用更干净的文本。
    """
    variants = [text, _sanitize_tts_text(text)]
    seen = set()
    last_error = None

    for attempt in range(retries):
        candidate = variants[min(attempt, len(variants) - 1)]
        if candidate in seen and len(variants) > 1:
            candidate = variants[-1]
        seen.add(candidate)

        try:
            await _synthesize_one(candidate, output_path, voice, rate=rate, volume=volume)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return candidate
        except edge_tts.exceptions.NoAudioReceived as exc:
            last_error = exc
            await asyncio.sleep(1.0)
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(1.0)

    raise last_error or RuntimeError("TTS 合成失败，且没有捕获到具体异常。")


def _generate_silence_clip(output_path: str, duration: float):
    """当某段 TTS 无法生成时，用静音片段占位，避免整条任务失败。"""
    import subprocess

    safe_duration = max(duration, 0.3)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=stereo",
        "-t", str(safe_duration),
        "-q:a", "9",
        "-acodec", "libmp3lame",
        output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


async def synthesize_all(
    translated_segments: list[dict],
    output_dir: str,
    voice: str = DEFAULT_VOICE
) -> list[dict]:
    """
    第四步：将翻译后的所有字幕段落合成为中文语音

    Args:
        translated_segments: 来自 translator 的翻译结果列表
        output_dir: 输出目录
        voice: Edge TTS 语音名称
    Returns:
        synthesis_results: 每段附带生成的音频路径和时长信息
    """
    tts_dir = os.path.join(output_dir, "tts_clips")
    os.makedirs(tts_dir, exist_ok=True)
    
    print(f"[步骤 4] 正在合成 {len(translated_segments)} 段中文语音 (语音: {voice})...")
    
    results = []
    
    for i, seg in enumerate(translated_segments):
        clip_path = os.path.join(tts_dir, f"clip_{i:04d}.mp3")
        text = seg["translated"]
        
        # 计算原始段落的时长窗口
        original_duration = seg["end"] - seg["start"]
        
        speed_ratio = 1.0

        try:
            # 先用正常语速合成
            text = await _synthesize_with_retries(text, clip_path, voice)

            # 获取合成音频的实际时长
            actual_duration = _get_audio_duration(clip_path)

            # 如果合成的中文语音比原始英文时间窗口长太多，加速播放
            # 这是 MVP 阶段最简洁的语速匹配策略
            if actual_duration > 0 and original_duration > 0:
                ratio = actual_duration / original_duration
                if ratio > 1.3:  # 超出原时长 30% 以上才加速
                    # 限制最大加速到 1.5 倍，否则听感太差
                    speed_factor = min(ratio, 1.5)
                    rate_percent = int((speed_factor - 1) * 100)
                    rate_str = f"+{rate_percent}%"
                    await _synthesize_with_retries(text, clip_path, voice, rate=rate_str)
                    actual_duration = _get_audio_duration(clip_path)
                    speed_ratio = speed_factor
        except Exception as exc:
            print(f"  [警告] 第 {i+1} 段配音失败，已自动改为静音占位。")
            print(f"         文本: {text}")
            print(f"         原因: {type(exc).__name__}: {exc}")
            _generate_silence_clip(clip_path, original_duration)
            actual_duration = _get_audio_duration(clip_path)
        
        results.append({
            **seg,
            "tts_path": clip_path,
            "tts_duration": actual_duration,
            "original_duration": original_duration,
            "speed_ratio": speed_ratio
        })
        
        if (i + 1) % 10 == 0 or i == len(translated_segments) - 1:
            print(f"  已合成 {i+1}/{len(translated_segments)} 段")
    
    # 保存合成结果的元数据
    meta_path = os.path.join(output_dir, "synthesis_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"[步骤 4] ✅ 语音合成完成")
    print(f"         语音片段 -> {tts_dir}")
    print(f"         元数据   -> {meta_path}")
    
    return results


def _get_audio_duration(audio_path: str) -> float:
    """用 FFmpeg 获取音频文件的精确时长（秒）"""
    import subprocess
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def run_synthesis(translated_segments: list[dict], output_dir: str, voice: str = DEFAULT_VOICE):
    """同步入口（包装异步调用，方便外部模块直接调用）"""
    return asyncio.run(synthesize_all(translated_segments, output_dir, voice))


if __name__ == "__main__":
    # 单独测试（需先跑过 translator 生成 translated.json）
    WORKSPACE = r"F:\MVP\workspace"
    
    with open(os.path.join(WORKSPACE, "translated.json"), "r", encoding="utf-8") as f:
        segments = json.load(f)
    
    results = run_synthesis(segments, WORKSPACE)
    print(f"\n🎉 合成测试通过！前 3 段信息：")
    for r in results[:3]:
        print(f"  [{r['start']:.1f}s] {r['translated']}")
        print(f"         语速调整: {r['speed_ratio']:.1f}x | 合成时长: {r['tts_duration']:.1f}s vs 原始窗口: {r['original_duration']:.1f}s")
