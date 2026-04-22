"""
翻译器 - 流水线第三环
调用兼容 OpenAI 协议的大语言模型 API，将英文字幕批量翻译为中文。
支持 DeepSeek / GPT / 通义千问等任何兼容接口。
"""
import json
import os
from pathlib import Path

from openai import OpenAI


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "api_config.json"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


def _load_api_config() -> tuple[str, str, str]:
    """
    优先级：
    1. 环境变量
    2. 项目根目录下的 api_config.json
    3. 默认 base_url / model
    """
    env_api_key = os.getenv("VIDEO_TRANSLATOR_API_KEY") or os.getenv("OPENAI_API_KEY")
    env_base_url = os.getenv("VIDEO_TRANSLATOR_BASE_URL")
    env_model = os.getenv("VIDEO_TRANSLATOR_MODEL")

    file_api_key = None
    file_base_url = None
    file_model = None

    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        file_api_key = config.get("api_key")
        file_base_url = config.get("base_url")
        file_model = config.get("model")

    api_key = env_api_key or file_api_key
    base_url = env_base_url or file_base_url or DEFAULT_BASE_URL
    model = env_model or file_model or DEFAULT_MODEL

    if not api_key:
        raise RuntimeError(
            "未配置翻译 API Key。请设置环境变量 VIDEO_TRANSLATOR_API_KEY "
            "（或 OPENAI_API_KEY），或者在项目根目录创建 api_config.json。"
        )

    return api_key, base_url, model


def translate_segments(
    segments: list[dict],
    output_dir: str,
    source_lang: str = "英文",
    target_lang: str = "中文",
    batch_size: int = 20
) -> list[dict]:
    """
    第三步：将识别出的字幕段落翻译为目标语言

    Args:
        segments: 来自 speech_recognizer 的字幕段落列表
        output_dir: 输出目录
        source_lang: 源语言名称
        target_lang: 目标语言名称
        batch_size: 每次送给大模型翻译的段落数量（控制 Token 消耗）
    Returns:
        translated: 翻译后的段落列表 (保留原始时间轴)
    """
    api_key, base_url, model = _load_api_config()
    client = OpenAI(api_key=api_key, base_url=base_url)
    
    print(f"[步骤 3] 开始翻译 {len(segments)} 段字幕 ({source_lang} -> {target_lang})...")
    print(f"[步骤 3] 翻译模型: {model}")
    
    translated = []
    
    # 分批处理，防止单次 Prompt 过长导致截断或高延迟
    for i in range(0, len(segments), batch_size):
        batch = segments[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(segments) + batch_size - 1) // batch_size
        
        print(f"  翻译批次 {batch_num}/{total_batches} (第 {i+1}-{i+len(batch)} 段)...")
        
        # 构建结构化输入：只传文本，不传时间轴（省 Token）
        texts = [seg["text"] for seg in batch]
        numbered = "\n".join([f"{j+1}. {t}" for j, t in enumerate(texts)])
        
        system_prompt = f"""你是一个专业的短视频字幕翻译员。请将以下{source_lang}字幕逐句翻译为地道的{target_lang}。
规则：
1. 保持编号顺序，每行一句，格式为"编号. 译文"
2. 翻译要口语化、接地气，适合短视频配音（不要书面语）
3. 严禁添加任何解释或额外内容
4. 严禁合并或拆分句子，输入多少句就输出多少句"""
        
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": numbered}
            ],
            temperature=0.3  # 低温度 = 更稳定/更忠实的翻译
        )
        
        reply = response.choices[0].message.content.strip()
        
        # 解析大模型返回的编号列表
        translated_texts = _parse_numbered_response(reply, len(batch))
        
        for j, seg in enumerate(batch):
            translated.append({
                "start": seg["start"],
                "end": seg["end"],
                "original": seg["text"],
                "translated": translated_texts[j] if j < len(translated_texts) else seg["text"]
            })
    
    # 保存翻译结果
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, "translated.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(translated, f, ensure_ascii=False, indent=2)
    
    # 导出中文 SRT
    srt_path = os.path.join(output_dir, "translated.srt")
    _export_srt(translated, srt_path)
    
    print(f"[步骤 3] ✅ 翻译完成")
    print(f"         JSON -> {json_path}")
    print(f"         SRT  -> {srt_path}")
    
    return translated


def _parse_numbered_response(text: str, expected_count: int) -> list[str]:
    """解析大模型返回的编号列表，容错处理"""
    lines = text.strip().split("\n")
    results = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 去掉开头的编号（如 "1. ", "2、", "3："等）
        import re
        cleaned = re.sub(r"^\d+[\.\、\:\：\)\）]\s*", "", line)
        if cleaned:
            results.append(cleaned)
    
    # 如果解析数量不匹配，用原文兜底
    if len(results) < expected_count:
        results.extend(["[翻译缺失]"] * (expected_count - len(results)))
    
    return results[:expected_count]


def _export_srt(segments: list[dict], srt_path: str):
    """导出翻译后的 SRT 字幕"""
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
    # 单独测试（需先跑过 speech_recognizer 生成 transcript.json）
    WORKSPACE = r"F:\MVP\workspace"
    
    with open(os.path.join(WORKSPACE, "transcript.json"), "r", encoding="utf-8") as f:
        segments = json.load(f)
    
    result = translate_segments(segments, WORKSPACE)
    print(f"\n🎉 翻译测试通过！前 3 段预览：")
    for seg in result[:3]:
        print(f"  [{seg['start']:.1f}s] {seg['original']}")
        print(f"       -> {seg['translated']}")
