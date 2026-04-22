from __future__ import annotations

import io
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path

import gradio as gr

from core.tts_synthesizer import DEFAULT_VOICE, VOICE_OPTIONS
from pipeline import run_pipeline


PROJECT_ROOT = Path(__file__).resolve().parent
RUNS_DIR = PROJECT_ROOT / "workspace" / "gradio_runs"

LANGUAGE_OPTIONS = [
    "英文",
    "中文",
    "日语",
    "韩语",
    "法语",
    "德语",
    "西班牙语",
]


def _make_run_dir() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _format_summary(final_path: str, run_dir: Path, voice_label: str, source_lang: str, target_lang: str) -> str:
    return "\n".join(
        [
            "处理完成",
            f"输出视频: {final_path}",
            f"工作目录: {run_dir}",
            f"翻译方向: {source_lang} -> {target_lang}",
            f"配音音色: {voice_label}",
        ]
    )


def launch_translation(
    video_path: str,
    voice_label: str,
    source_lang: str,
    target_lang: str,
):
    if not video_path:
        raise gr.Error("请先上传或选择一个视频文件。")

    if source_lang == target_lang:
        raise gr.Error("源语言和目标语言不能相同。")

    run_dir = _make_run_dir()
    selected_voice = VOICE_OPTIONS.get(voice_label, DEFAULT_VOICE)
    stream = io.StringIO()

    try:
        with redirect_stdout(stream), redirect_stderr(stream):
            final_path = run_pipeline(
                video_path=video_path,
                output_dir=str(run_dir),
                voice=selected_voice,
                source_lang=source_lang,
                target_lang=target_lang,
            )

        logs = stream.getvalue().strip()
        summary = _format_summary(final_path, run_dir, voice_label, source_lang, target_lang)
        return summary, logs, final_path, final_path, str(run_dir)
    except Exception:
        logs = stream.getvalue()
        error_text = traceback.format_exc()
        combined_logs = "\n".join(part for part in [logs.strip(), error_text.strip()] if part)
        return "处理失败", combined_logs, None, None, str(run_dir)


def build_demo() -> gr.Blocks:
    default_voice_label = next(
        (label for label, value in VOICE_OPTIONS.items() if value == DEFAULT_VOICE),
        next(iter(VOICE_OPTIONS)),
    )

    with gr.Blocks(title="一键译制机 MVP") as demo:
        gr.Markdown(
            """
            # 一键译制机 MVP
            上传一个短视频，选择翻译方向和配音音色，直接跑完整流水线。

            建议先用 1 到 5 分钟的短视频测试。
            """
        )

        with gr.Row():
            with gr.Column(scale=3):
                video_input = gr.File(
                    label="输入视频",
                    type="filepath",
                    file_types=["video"],
                )
            with gr.Column(scale=2):
                source_lang = gr.Dropdown(
                    choices=LANGUAGE_OPTIONS,
                    value="英文",
                    label="源语言",
                )
                target_lang = gr.Dropdown(
                    choices=LANGUAGE_OPTIONS,
                    value="中文",
                    label="目标语言",
                )
                voice_choice = gr.Dropdown(
                    choices=list(VOICE_OPTIONS.keys()),
                    value=default_voice_label,
                    label="配音音色",
                )
                run_button = gr.Button("开始译制", variant="primary", size="lg")

        summary_output = gr.Textbox(label="处理结果", lines=5)
        output_video = gr.Video(label="成品视频", height=360)
        output_file = gr.File(label="下载成品视频")
        workspace_output = gr.Textbox(label="本次输出目录")
        log_output = gr.Textbox(label="运行日志", lines=18, max_lines=30)

        run_button.click(
            fn=launch_translation,
            inputs=[video_input, voice_choice, source_lang, target_lang],
            outputs=[summary_output, log_output, output_video, output_file, workspace_output],
            show_progress="full",
        )

    return demo


if __name__ == "__main__":
    demo = build_demo()
    demo.launch(server_name="127.0.0.1", server_port=7860, inbrowser=True)
