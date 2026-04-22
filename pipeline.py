"""
===============================================
  一键译制机 MVP - 全流程主控脚本
  One-Click Video Translator Pipeline
===============================================
将一个外国视频从头到尾自动处理为中文配音视频。

使用方法：
  python pipeline.py

当前为测试模式，直接处理 videoplayback.mp4
"""
import os
import sys
import time

# Windows GBK 编码兼容：强制 stdout/stderr 使用 UTF-8
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 将 core 目录加入搜索路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.audio_separator import extract_audio, separate_vocals
from core.speech_recognizer import transcribe
from core.translator import translate_segments
from core.tts_synthesizer import run_synthesis
from core.video_composer import compose_final_video


def run_pipeline(
    video_path: str,
    output_dir: str = None,
    voice: str = "zh-CN-YunxiNeural",
    source_lang: str = "英文",
    target_lang: str = "中文"
):
    """
    全自动流水线主函数

    Args:
        video_path: 输入视频的绝对路径
        output_dir: 输出工作目录（默认在视频同级目录下创建 workspace）
        voice: TTS 语音选择
        source_lang: 源语言
        target_lang: 目标语言
    """
    start_time = time.time()
    
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(video_path), "workspace")
    
    os.makedirs(output_dir, exist_ok=True)
    
    print("=" * 60)
    print("  🎬 一键译制机 MVP - 全自动流水线启动")
    print("=" * 60)
    print(f"  输入视频: {video_path}")
    print(f"  工作目录: {output_dir}")
    print(f"  翻译方向: {source_lang} -> {target_lang}")
    print(f"  配音语音: {voice}")
    print("=" * 60)
    print()
    
    # ========== 步骤 0+1: 提取音轨并分离人声与BGM ==========
    raw_audio = extract_audio(video_path, output_dir)
    vocals_path, bgm_path = separate_vocals(raw_audio, output_dir)
    print()
    
    # ========== 步骤 2: 语音识别（英文字幕提取） ==========
    segments = transcribe(vocals_path, output_dir)
    print()
    
    # ========== 步骤 3: 翻译（英文 -> 中文） ==========
    translated = translate_segments(
        segments, output_dir,
        source_lang=source_lang,
        target_lang=target_lang
    )
    print()
    
    # ========== 步骤 4: 中文语音合成 ==========
    synthesis_meta = run_synthesis(translated, output_dir, voice=voice)
    print()
    
    # ========== 步骤 5: 最终视频合成 ==========
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    output_filename = f"{video_name}_中文版.mp4"
    
    final_path = compose_final_video(
        video_path, bgm_path, synthesis_meta,
        output_dir, output_filename
    )
    
    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    
    print()
    print("=" * 60)
    print(f"  🎉 全流程完成！")
    print(f"  总耗时: {minutes}分{seconds}秒")
    print(f"  成品视频: {final_path}")
    print("=" * 60)
    
    return final_path


if __name__ == "__main__":
    # ============================
    #  测试入口：直接处理测试视频
    # ============================
    VIDEO_PATH = r"F:\MVP\videoplayback.mp4"
    
    if not os.path.exists(VIDEO_PATH):
        print(f"❌ 测试视频不存在: {VIDEO_PATH}")
        sys.exit(1)
    
    run_pipeline(VIDEO_PATH)
