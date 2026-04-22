"""
音频分离器 - 流水线第一环
使用 Meta 开源的 Demucs 模型，将视频的音轨拆分为：
  1. vocals.wav   (纯人声，用于后续语音识别)
  2. bgm.wav      (纯背景音乐/环境音效，用于最终合成时保留原片灵魂)

本模块直接通过 Python API 调用 Demucs，绕过 torchaudio.save() 的
torchcodec 依赖问题，改用 soundfile 保存音频。
"""
import subprocess
import os
import torch
import numpy as np
import soundfile as sf


def extract_audio(video_path: str, output_dir: str) -> str:
    """
    第零步：用 FFmpeg 从视频中提取原始完整音轨 (WAV)
    """
    os.makedirs(output_dir, exist_ok=True)
    raw_audio = os.path.join(output_dir, "raw_audio.wav")
    
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",                    # 不要视频流
        "-acodec", "pcm_s16le",   # 16bit PCM
        "-ar", "44100",           # 采样率 44.1kHz (Demucs 要求)
        "-ac", "2",               # 双声道
        raw_audio
    ]
    
    print(f"[步骤 0] 正在从视频中提取音轨...")
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"[步骤 0] 音轨提取完成 -> {raw_audio}")
    return raw_audio


def separate_vocals(raw_audio: str, output_dir: str) -> tuple[str, str]:
    """
    第一步：用 Demucs Python API 直接在进程内分离人声与伴奏。
    完全绕过 torchaudio.save() / torchcodec 的兼容性问题。
    """
    print(f"[步骤 1] 正在用 Demucs 分离人声与背景音（首次运行会自动下载模型）...")
    
    # 延迟导入，避免在不需要时拉起整个 demucs 依赖树
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    from demucs.audio import AudioFile
    
    # 加载预训练模型
    model = get_model("htdemucs")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    
    # 读取音频
    wav = AudioFile(raw_audio).read(
        streams=0,
        samplerate=model.samplerate,
        channels=model.audio_channels
    )
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / ref.std()
    
    print(f"  音频时长: {wav.shape[-1] / model.samplerate:.1f} 秒")
    print(f"  使用设备: {device}")
    
    # 执行分离
    sources = apply_model(
        model,
        wav[None].to(device),
        device=device,
        progress=True
    )[0]
    
    # 反标准化
    sources = sources * ref.std() + ref.mean()
    
    # 找到 vocals 和 no_vocals 的索引
    # htdemucs 的 sources 列表顺序: drums, bass, other, vocals
    source_names = model.sources
    vocals_idx = source_names.index("vocals")
    
    vocals_tensor = sources[vocals_idx].cpu().numpy()
    
    # 除 vocals 之外的所有轨道混合为 BGM
    bgm_tensor = torch.zeros_like(sources[0])
    for i, name in enumerate(source_names):
        if name != "vocals":
            bgm_tensor += sources[i]
    bgm_tensor = bgm_tensor.cpu().numpy()
    
    # 用 soundfile 保存（完全绕过 torchaudio）
    final_vocals = os.path.join(output_dir, "vocals.wav")
    final_bgm = os.path.join(output_dir, "bgm.wav")
    
    # soundfile 期望 shape = (samples, channels)，所以需要转置
    sf.write(final_vocals, vocals_tensor.T, model.samplerate)
    sf.write(final_bgm, bgm_tensor.T, model.samplerate)
    
    print(f"[步骤 1] 人声分离完成")
    print(f"         人声 -> {final_vocals}")
    print(f"         BGM  -> {final_bgm}")
    
    return final_vocals, final_bgm


if __name__ == "__main__":
    # 单独测试本模块
    VIDEO = r"F:\MVP\videoplayback.mp4"
    OUT = r"F:\MVP\workspace"
    
    audio = extract_audio(VIDEO, OUT)
    vocals, bgm = separate_vocals(audio, OUT)
    print(f"\n分离测试通过！可以去 {OUT} 目录听一下 vocals.wav 和 bgm.wav 的效果。")
