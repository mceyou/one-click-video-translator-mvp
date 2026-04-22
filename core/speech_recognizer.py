"""
语音识别器 - 流水线第二环
使用 faster-whisper 将纯人声音频转录为带时间戳的字幕段落。
输出格式为结构化的 Python 列表，供后续翻译模块直接消费。
"""
import json
import os

import torch
from faster_whisper import WhisperModel


def transcribe(vocals_path: str, output_dir: str, model_size: str = "medium") -> list[dict]:
    """
    第二步：将人声 WAV 转录为带时间轴的英文文本段落
    
    Args:
        vocals_path: 纯人声音频文件路径
        output_dir: 输出目录
        model_size: Whisper 模型大小 (tiny/base/small/medium/large-v3)
                    medium 是速度与精度的最佳平衡点
    Returns:
        segments: [{"start": 0.0, "end": 2.5, "text": "Hello world"}, ...]
    """
    print(f"[步骤 2] 正在加载 Whisper {model_size} 模型（首次运行会自动下载）...")

    # 自动检测 GPU，有则优先走 CUDA，无则回退到 CPU。
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"

    print(f"[步骤 2] 推理设备: {device} | 精度: {compute_type}")
    if device == "cpu":
        print("[步骤 2] 检测到当前机器没有可用 CUDA，将使用 CPU 模式，速度会明显变慢。")

    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    print(f"[步骤 2] 模型加载完毕，开始识别语音...")
    
    # 执行转录（beam_size=5 提高准确率，vad_filter 过滤静音段）
    whisper_segments, info = model.transcribe(
        vocals_path,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500)
    )
    
    print(f"[步骤 2] 检测到语言: {info.language} (置信度: {info.language_probability:.1%})")
    
    segments = []
    for seg in whisper_segments:
        segments.append({
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip()
        })
    
    # 保存结构化字幕 JSON（供后续翻译模块直接读取）
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, "transcript.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    
    # 同时导出 SRT 格式（方便人工校验）
    srt_path = os.path.join(output_dir, "transcript.srt")
    _export_srt(segments, srt_path)
    
    print(f"[步骤 2] ✅ 语音识别完成，共 {len(segments)} 个字幕段落")
    print(f"         JSON -> {json_path}")
    print(f"         SRT  -> {srt_path}")
    
    return segments


def _export_srt(segments: list[dict], srt_path: str):
    """将字幕段落导出为标准 SRT 格式"""
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
            f.write(f"{seg['text']}\n\n")


if __name__ == "__main__":
    # 单独测试本模块（需先跑过 audio_separator 生成 vocals.wav）
    VOCALS = r"F:\MVP\workspace\vocals.wav"
    OUT = r"F:\MVP\workspace"
    
    result = transcribe(VOCALS, OUT)
    print(f"\n🎉 识别测试通过！前 3 段内容预览：")
    for seg in result[:3]:
        print(f"  [{seg['start']:.1f}s - {seg['end']:.1f}s] {seg['text']}")
