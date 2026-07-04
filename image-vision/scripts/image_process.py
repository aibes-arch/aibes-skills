#!/usr/bin/env python3
"""
图像/视觉处理统一 CLI：图像描述、OCR、对象识别、关系抽取。

所有理解类任务均通过多模态 LLM（OpenAI 兼容接口）完成。
支持单张图片、图片目录批处理，以及直接传入图片 URL。
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
from urllib.parse import urlparse

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


DEFAULT_MODEL = "moonshot-v1-8k-vision-preview"
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 2048
SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def is_url(path_or_url: str) -> bool:
    parsed = urlparse(path_or_url)
    return parsed.scheme in ("http", "https")


def list_image_files(directory: str) -> List[Path]:
    p = Path(directory)
    if not p.is_dir():
        raise NotADirectoryError(f"不是目录: {directory}")
    files = []
    for ext in SUPPORTED_IMAGE_EXTS:
        files.extend(p.glob(f"*{ext}"))
        files.extend(p.glob(f"*{ext.upper()}"))
    return sorted(set(files))


def write_text(path: Optional[str], content: str) -> None:
    if path is None or path == "-":
        sys.stdout.write(content)
        if not content.endswith("\n"):
            sys.stdout.write("\n")
    else:
        Path(path).write_text(content, encoding="utf-8")


def write_json(path: Optional[str], data: object) -> None:
    content = json.dumps(data, ensure_ascii=False, indent=2)
    write_text(path, content)


def write_jsonl(path: Optional[str], items: Iterable[object]) -> None:
    lines = [json.dumps(item, ensure_ascii=False) for item in items]
    write_text(path, "\n".join(lines))


# ---------------------------------------------------------------------------
# Image encoding
# ---------------------------------------------------------------------------

def encode_image_local(
    image_path: str,
    max_pixels: int = 2_000_000,
    quality: int = 85,
) -> str:
    """将本地图片编码为 base64 data URL（JPEG）。"""
    if Image is None:
        raise RuntimeError("PIL 未安装，请执行: pip install Pillow")

    img = Image.open(image_path)

    # 统一转换为 RGB
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # 等比缩放，避免超过最大像素
    width, height = img.size
    current_pixels = width * height
    if current_pixels > max_pixels:
        scale = (max_pixels / current_pixels) ** 0.5
        new_size = (int(width * scale), int(height * scale))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def prepare_image_url(image_path_or_url: str, max_pixels: int) -> str:
    """将输入转换为 LLM 可消费的 image URL。"""
    if is_url(image_path_or_url):
        return image_path_or_url
    return encode_image_local(image_path_or_url, max_pixels=max_pixels)


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------

def get_llm_client() -> Tuple[OpenAI, str]:
    if OpenAI is None:
        raise RuntimeError("openai 包未安装，请执行: pip install openai")
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "缺少 LLM API Key。请设置环境变量 LLM_API_KEY 或 OPENAI_API_KEY。"
        )
    base_url = os.environ.get("LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    model = os.environ.get("LLM_MODEL") or DEFAULT_MODEL
    kwargs: dict = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs), model


def vision_chat(
    system: str,
    user_text: str,
    image_url: str,
    temperature: float,
    max_tokens: int,
    detail: str = "auto",
) -> str:
    client, model = get_llm_client()
    image_payload: dict = {"url": image_url}
    if detail != "auto":
        image_payload["detail"] = detail
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": image_payload},
                ],
            },
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content
    return content.strip() if content else ""


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def describe_image(
    image_url: str,
    language: str,
    temperature: float,
    max_tokens: int,
    detail: str,
) -> str:
    system = (
        "你是一位专业的图像描述专家。请用准确、客观的语言描述图片内容，"
        "包括画面主体、场景、颜色、构图、文字信息（如有）以及整体氛围。"
    )
    user = (
        f"请用{language}详细描述这张图片。如果图片包含文字，请一并说明文字内容；"
        "如果包含多个人物或对象，请分别说明。"
    )
    return vision_chat(system, user, image_url, temperature, max_tokens, detail)


def ocr_image(
    image_url: str,
    language: str,
    temperature: float,
    max_tokens: int,
    detail: str,
) -> str:
    system = (
        "你是一位 OCR 专家。请尽可能准确地识别图片中的所有文字，"
        "保留原始排版和段落结构，不要添加图片中没有的内容。"
    )
    user = (
        f"请识别这张图片中的所有文字，并用{language}按原样输出。"
        "如果图片中没有文字，请直接回复「图片中未识别到文字」。"
    )
    return vision_chat(system, user, image_url, temperature, max_tokens, detail)


def objects_image(
    image_url: str,
    language: str,
    temperature: float,
    max_tokens: int,
    detail: str,
) -> str:
    system = (
        "你是一位计算机视觉专家。请识别图片中的主要对象，"
        "以结构化 JSON 数组返回，每个对象包含 name（名称）和 description（简短描述）。"
    )
    user = (
        f"请识别这张图片中的主要对象，并用{language}以 JSON 数组格式返回。"
        "示例：[{{\"name\": \"猫\", \"description\": \"一只橘色的猫坐在沙发上\"}}]。"
        "只返回 JSON 数组，不要添加额外说明。"
    )
    return vision_chat(system, user, image_url, temperature, max_tokens, detail)


def relations_image(
    image_url: str,
    language: str,
    temperature: float,
    max_tokens: int,
    detail: str,
) -> str:
    system = (
        "你是一位视觉关系抽取专家。请分析图片中主要对象之间的空间位置、"
        "交互动作、从属关系等，并以结构化 JSON 数组返回。"
    )
    user = (
        f"请分析这张图片中对象之间的关系，并用{language}以 JSON 数组格式返回。"
        "每个关系包含 subject（主体）、predicate（关系）、object（客体），"
        "可选添加 description（补充说明）。"
        "示例：[{{\"subject\": \"人\", \"predicate\": \"坐在\", \"object\": \"椅子\", "
        "\"description\": \"一位男士坐在木椅上\"}}]。只返回 JSON 数组。"
    )
    return vision_chat(system, user, image_url, temperature, max_tokens, detail)


def analyze_image(
    image_url: str,
    language: str,
    temperature: float,
    max_tokens: int,
    detail: str,
) -> dict:
    """综合分析：描述 + OCR + 对象 + 关系。"""
    return {
        "description": describe_image(image_url, language, temperature, max_tokens, detail),
        "ocr": ocr_image(image_url, language, temperature, max_tokens, detail),
        "objects": objects_image(image_url, language, temperature, max_tokens, detail),
        "relations": relations_image(image_url, language, temperature, max_tokens, detail),
    }


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def run_single(
    task: str,
    image_path_or_url: str,
    args: argparse.Namespace,
) -> dict:
    image_url = prepare_image_url(image_path_or_url, args.max_pixels)
    if task == "describe":
        result = describe_image(image_url, args.language, args.temperature, args.max_tokens, args.detail)
    elif task == "ocr":
        result = ocr_image(image_url, args.language, args.temperature, args.max_tokens, args.detail)
    elif task == "objects":
        result = objects_image(image_url, args.language, args.temperature, args.max_tokens, args.detail)
    elif task == "relations":
        result = relations_image(image_url, args.language, args.temperature, args.max_tokens, args.detail)
    elif task == "analyze":
        result = analyze_image(image_url, args.language, args.temperature, args.max_tokens, args.detail)
    else:
        raise ValueError(f"未知任务: {task}")
    return {"input": image_path_or_url, "task": task, "result": result}


def cmd_task(args: argparse.Namespace, task: str) -> None:
    if os.path.isdir(args.input):
        image_files = list_image_files(args.input)
        if not image_files:
            print(f"目录中未找到支持的图片: {args.input}", file=sys.stderr)
            sys.exit(1)
        results = [run_single(task, str(f), args) for f in image_files]
        if args.format == "jsonl":
            write_jsonl(args.output, results)
        else:
            write_json(args.output, results)
    else:
        result = run_single(task, args.input, args)
        if args.format == "text":
            if isinstance(result["result"], dict):
                write_json(args.output, result["result"])
            else:
                write_text(args.output, str(result["result"]))
        elif args.format == "jsonl":
            write_jsonl(args.output, [result])
        else:
            write_json(args.output, result)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="image_process.py",
        description="图像/视觉处理工具：描述、OCR、对象识别、关系抽取。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for task in ("describe", "ocr", "objects", "relations", "analyze"):
        p = subparsers.add_parser(task, help=_task_help(task))
        p.add_argument("input", help="图片文件路径、图片目录或图片 URL")
        p.add_argument("-o", "--output", default="-", help="输出文件路径，默认 stdout")
        p.add_argument("--language", default="中文", help="输出语言")
        p.add_argument("--format", choices=["text", "json", "jsonl"], default="text")
        p.add_argument("--max-pixels", type=int, default=2_000_000, help="本地图片最大像素数")
        p.add_argument("--detail", choices=["auto", "low", "high"], default="auto", help="图片细节级别")
        p.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
        p.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
        p.set_defaults(func=lambda args, task=task: cmd_task(args, task))

    return parser


def _task_help(task: str) -> str:
    mapping = {
        "describe": "图像描述",
        "ocr": "文字识别",
        "objects": "对象识别",
        "relations": "关系抽取",
        "analyze": "综合分析",
    }
    return mapping[task]


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
