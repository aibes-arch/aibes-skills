#!/usr/bin/env python3
"""
公式处理统一 CLI：公式识别、LaTeX 转换、变量解释、公式关系抽取。

- 图片中的公式：通过多模态 LLM 识别并转换为 LaTeX。
- 文本形式的公式：通过文本 LLM 转换为 LaTeX、解释变量、抽取关系。
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple
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


DEFAULT_TEXT_MODEL = "moonshot-v1-8k"
DEFAULT_VISION_MODEL = "moonshot-v1-8k-vision-preview"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 2048

TEXT_EXTS = {".txt", ".md", ".tex", ".math"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def is_url(path_or_url: str) -> bool:
    return urlparse(path_or_url).scheme in ("http", "https")


def read_text(path: Optional[str]) -> str:
    if path is None or path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def write_text(path: Optional[str], content: str) -> None:
    if path is None or path == "-":
        sys.stdout.write(content)
        if not content.endswith("\n"):
            sys.stdout.write("\n")
    else:
        Path(path).write_text(content, encoding="utf-8")


def write_json(path: Optional[str], data: object) -> None:
    content = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    write_text(path, content)


def write_jsonl(path: Optional[str], items: List[dict]) -> None:
    lines = [json.dumps(item, ensure_ascii=False, default=str) for item in items]
    write_text(path, "\n".join(lines))


def list_files(directory: str) -> List[Path]:
    p = Path(directory)
    if not p.is_dir():
        raise NotADirectoryError(f"不是目录: {directory}")
    files: List[Path] = []
    for ext in TEXT_EXTS | IMAGE_EXTS:
        files.extend(p.glob(f"*{ext}"))
        files.extend(p.glob(f"*{ext.upper()}"))
    return sorted(set(files))


def input_type(path_or_url: str) -> str:
    if is_url(path_or_url):
        return "image" if any(path_or_url.lower().endswith(ext) for ext in IMAGE_EXTS) else "text"
    ext = Path(path_or_url).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in TEXT_EXTS:
        return "text"
    return "text"


# ---------------------------------------------------------------------------
# Image encoding
# ---------------------------------------------------------------------------

def encode_image_local(image_path: str, max_pixels: int = 2_000_000, quality: int = 85) -> str:
    if Image is None:
        raise RuntimeError("PIL 未安装，请执行: pip install Pillow")
    img = Image.open(image_path)
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")
    width, height = img.size
    current_pixels = width * height
    if current_pixels > max_pixels:
        scale = (max_pixels / current_pixels) ** 0.5
        img = img.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def prepare_image_url(path_or_url: str, max_pixels: int) -> str:
    if is_url(path_or_url):
        return path_or_url
    return encode_image_local(path_or_url, max_pixels=max_pixels)


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------

def get_llm_client() -> Tuple[OpenAI, str, str]:
    if OpenAI is None:
        raise RuntimeError("openai 包未安装，请执行: pip install openai")
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "缺少 LLM API Key。请设置环境变量 LLM_API_KEY 或 OPENAI_API_KEY。"
        )
    base_url = os.environ.get("LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    text_model = os.environ.get("LLM_TEXT_MODEL") or os.environ.get("LLM_MODEL") or DEFAULT_TEXT_MODEL
    vision_model = os.environ.get("LLM_VISION_MODEL") or os.environ.get("LLM_MODEL") or DEFAULT_VISION_MODEL
    kwargs: dict = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs), text_model, vision_model


def text_chat(system: str, user: str, temperature: float, max_tokens: int) -> str:
    client, model, _ = get_llm_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content
    return content.strip() if content else ""


def vision_chat(system: str, user: str, image_url: str, temperature: float, max_tokens: int, detail: str = "auto") -> str:
    client, _, model = get_llm_client()
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
                    {"type": "text", "text": user},
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

def recognize_formula(image_url: str, temperature: float, max_tokens: int, detail: str) -> str:
    system = (
        "你是一位数学公式识别专家。请仔细观察图片中的公式，"
        "将其转换为标准 LaTeX 代码，只返回 LaTeX 表达式本身，不要添加额外说明。"
    )
    user = "请将图片中的数学公式转换为 LaTeX 代码。"
    return vision_chat(system, user, image_url, temperature, max_tokens, detail)


def convert_to_latex(formula_text: str, temperature: float, max_tokens: int) -> str:
    system = (
        "你是一位 LaTeX 公式转换专家。请将用户提供的数学公式转换为标准 LaTeX 代码，"
        "只返回 LaTeX 表达式本身。"
    )
    user = f"请将以下公式转换为 LaTeX：\n\n{formula_text}"
    return text_chat(system, user, temperature, max_tokens)


def explain_variables(formula_text: str, temperature: float, max_tokens: int) -> str:
    system = (
        "你是一位数学公式解释专家。请解释给定公式中每个变量的含义、单位（如有）以及 "
        "公式整体的物理/数学意义。以 JSON 数组返回变量解释，并附带一段整体说明。"
    )
    user = (
        "请解释以下公式中的变量，并说明公式含义。\n\n"
        "输出格式要求：\n"
        "1. variables: JSON 数组，每个元素包含 name（变量名）、meaning（含义）、unit（单位，可选）。\n"
        "2. summary: 一段整体说明。\n\n"
        f"{formula_text}"
    )
    return text_chat(system, user, temperature, max_tokens)


def extract_relations(formula_text: str, temperature: float, max_tokens: int) -> str:
    system = (
        "你是一位公式关系抽取专家。请分析给定公式中变量与常量之间的依赖关系，"
        "例如 'y 与 x 成正比'、'z 是 x 和 y 的函数' 等。"
    )
    user = (
        "请分析以下公式中变量/常量之间的关系，以 JSON 数组返回。"
        "每个关系包含 from（来源变量）、to（目标变量）、relation（关系描述）。\n\n"
        f"{formula_text}"
    )
    return text_chat(system, user, temperature, max_tokens)


def analyze_formula_text(formula_text: str, temperature: float, max_tokens: int) -> dict:
    return {
        "latex": convert_to_latex(formula_text, temperature, max_tokens),
        "explanation": explain_variables(formula_text, temperature, max_tokens),
        "relations": extract_relations(formula_text, temperature, max_tokens),
    }


def analyze_formula_image(image_url: str, temperature: float, max_tokens: int, detail: str) -> dict:
    latex = recognize_formula(image_url, temperature, max_tokens, detail)
    return {
        "latex": latex,
        "explanation": explain_variables(latex, temperature, max_tokens),
        "relations": extract_relations(latex, temperature, max_tokens),
    }


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def process_single(path_or_text: str, task: str, args: argparse.Namespace) -> dict:
    itype = input_type(path_or_text)
    result: dict = {"input": path_or_text, "task": task}

    if task == "recognize":
        if itype != "image":
            raise ValueError("recognize 任务需要图片输入")
        image_url = prepare_image_url(path_or_text, args.max_pixels)
        result["result"] = recognize_formula(image_url, args.temperature, args.max_tokens, args.detail)
        return result

    if task == "convert":
        text = read_text(path_or_text) if not is_url(path_or_text) and Path(path_or_text).exists() else path_or_text
        result["result"] = convert_to_latex(text, args.temperature, args.max_tokens)
        return result

    if task == "explain":
        text = read_text(path_or_text) if not is_url(path_or_text) and Path(path_or_text).exists() else path_or_text
        result["result"] = explain_variables(text, args.temperature, args.max_tokens)
        return result

    if task == "relations":
        text = read_text(path_or_text) if not is_url(path_or_text) and Path(path_or_text).exists() else path_or_text
        result["result"] = extract_relations(text, args.temperature, args.max_tokens)
        return result

    if task == "analyze":
        if itype == "image":
            image_url = prepare_image_url(path_or_text, args.max_pixels)
            result["result"] = analyze_formula_image(image_url, args.temperature, args.max_tokens, args.detail)
        else:
            text = read_text(path_or_text) if not is_url(path_or_text) and Path(path_or_text).exists() else path_or_text
            result["result"] = analyze_formula_text(text, args.temperature, args.max_tokens)
        return result

    raise ValueError(f"未知任务: {task}")


def cmd_task(args: argparse.Namespace, task: str) -> None:
    if os.path.isdir(args.input):
        files = list_files(args.input)
        if not files:
            print(f"目录中未找到支持的文件: {args.input}", file=sys.stderr)
            sys.exit(1)
        results = [process_single(str(f), task, args) for f in files]
        if args.format == "jsonl":
            write_jsonl(args.output, results)
        else:
            write_json(args.output, results)
    else:
        result = process_single(args.input, task, args)
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
        prog="formula_process.py",
        description="公式处理工具：识别、LaTeX 转换、变量解释、关系抽取。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for task in ("recognize", "convert", "explain", "relations", "analyze"):
        p = subparsers.add_parser(task, help=_task_help(task))
        p.add_argument(
            "input",
            help="公式文本、文本文件路径、图片路径、图片目录或图片 URL",
        )
        p.add_argument("-o", "--output", default="-", help="输出文件路径，默认 stdout")
        p.add_argument("--format", choices=["text", "json", "jsonl"], default="text")
        p.add_argument("--max-pixels", type=int, default=2_000_000, help="本地图片最大像素数")
        p.add_argument("--detail", choices=["auto", "low", "high"], default="auto", help="图片细节级别")
        p.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
        p.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
        p.set_defaults(func=lambda args, task=task: cmd_task(args, task))

    return parser


def _task_help(task: str) -> str:
    mapping = {
        "recognize": "图片公式识别（输出 LaTeX）",
        "convert": "文本公式转 LaTeX",
        "explain": "解释公式变量与含义",
        "relations": "抽取公式变量关系",
        "analyze": "综合分析：LaTeX + 解释 + 关系",
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
