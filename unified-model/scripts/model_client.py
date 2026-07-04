#!/usr/bin/env python3
"""
统一模型调用 CLI：LLM / Embedding / VLM / Reranker。

默认通过 OpenAI 兼容接口调用。支持配置 base_url、api_key、model，
可作为其他 skill 的底层模型客户端，也可独立在命令行使用。
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, List, Optional, Tuple
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


DEFAULT_LLM_MODEL = "moonshot-v1-8k"
DEFAULT_EMBEDDING_MODEL = "text-embedding-v2"
DEFAULT_VLM_MODEL = "moonshot-v1-8k-vision-preview"
DEFAULT_RERANKER_MODEL = "jina-reranker-v2-base-multilingual"
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 2048


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def read_text(path: Optional[str]) -> str:
    if path is None or path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def read_lines(path: Optional[str]) -> List[str]:
    text = read_text(path)
    return [line.strip() for line in text.splitlines() if line.strip()]


def read_jsonl(path: Optional[str]) -> List[dict]:
    lines = read_text(path).strip().split("\n")
    return [json.loads(line) for line in lines if line.strip()]


def write_text(path: Optional[str], content: str) -> None:
    if path is None or path == "-":
        sys.stdout.write(content)
        if not content.endswith("\n"):
            sys.stdout.write("\n")
    else:
        Path(path).write_text(content, encoding="utf-8")


def write_json(path: Optional[str], data: Any) -> None:
    content = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    write_text(path, content)


def is_url(value: str) -> bool:
    return urlparse(value).scheme in ("http", "https")


# ---------------------------------------------------------------------------
# Client setup
# ---------------------------------------------------------------------------

def get_client() -> OpenAI:
    if OpenAI is None:
        raise RuntimeError("openai 包未安装，请执行: pip install openai")
    api_key = os.environ.get("MODEL_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        raise RuntimeError(
            "缺少 API Key。请设置 MODEL_API_KEY / OPENAI_API_KEY / LLM_API_KEY。"
        )
    base_url = (
        os.environ.get("MODEL_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("LLM_BASE_URL")
    )
    kwargs: dict = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def get_model_name(default: str) -> str:
    return os.environ.get("MODEL_NAME") or default


# ---------------------------------------------------------------------------
# Image encoding
# ---------------------------------------------------------------------------

def encode_image_local(image_path: str, max_pixels: int = 2_000_000, quality: int = 85) -> str:
    if Image is None:
        raise RuntimeError("VLM 需要 Pillow，请执行: pip install Pillow")
    img = Image.open(image_path)
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")
    width, height = img.size
    current = width * height
    if current > max_pixels:
        scale = (max_pixels / current) ** 0.5
        img = img.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def prepare_image_url(image_path_or_url: str) -> str:
    if is_url(image_path_or_url):
        return image_path_or_url
    return encode_image_local(image_path_or_url)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def call_llm(prompt: str, system: Optional[str], temperature: float, max_tokens: int, model: str) -> str:
    client = get_client()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content
    return content.strip() if content else ""


def call_embedding(texts: List[str], model: str) -> List[List[float]]:
    client = get_client()
    response = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


def call_vlm(prompt: str, image_url: str, temperature: float, max_tokens: int, model: str) -> str:
    client = get_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content
    return content.strip() if content else ""


def call_reranker(query: str, passages: List[str], model: str, top_n: Optional[int] = None) -> List[dict]:
    """调用 OpenAI 兼容 rerank 接口。部分平台提供 /rerank 端点。"""
    client = get_client()
    # Build manual POST for rerank endpoint
    base_url = str(client.base_url).rstrip("/")
    url = f"{base_url}/rerank"
    payload = {
        "model": model,
        "query": query,
        "documents": passages,
        "top_n": top_n or len(passages),
    }
    import httpx
    response = httpx.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {client.api_key}", "Content-Type": "application/json"},
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    return data.get("results", [])


# ---------------------------------------------------------------------------
# CLI handlers
# ---------------------------------------------------------------------------

def cmd_llm(args: argparse.Namespace) -> None:
    prompt = read_text(args.input) if Path(args.input).exists() else args.input
    model = args.model or get_model_name(DEFAULT_LLM_MODEL)
    result = call_llm(prompt, args.system, args.temperature, args.max_tokens, model)
    if args.format == "json":
        write_json(args.output, {"prompt": prompt, "response": result, "model": model})
    else:
        write_text(args.output, result)


def cmd_embedding(args: argparse.Namespace) -> None:
    if args.input.endswith(".jsonl") or args.input.endswith(".json"):
        items = read_jsonl(args.input)
        texts = [item.get("text", item.get("input", "")) for item in items]
    else:
        texts = read_lines(args.input)
    if not texts:
        raise ValueError("没有输入文本")
    model = args.model or os.environ.get("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL
    embeddings = call_embedding(texts, model)
    results = [{"text": t, "embedding": e} for t, e in zip(texts, embeddings)]
    write_json(args.output, results)


def cmd_vlm(args: argparse.Namespace) -> None:
    prompt = args.prompt
    image_url = prepare_image_url(args.image)
    model = args.model or os.environ.get("VLM_MODEL") or DEFAULT_VLM_MODEL
    result = call_vlm(prompt, image_url, args.temperature, args.max_tokens, model)
    if args.format == "json":
        write_json(args.output, {"prompt": prompt, "image": args.image, "response": result, "model": model})
    else:
        write_text(args.output, result)


def cmd_rerank(args: argparse.Namespace) -> None:
    query = args.query
    passages = read_lines(args.input)
    if not passages:
        raise ValueError("没有输入 passages")
    model = args.model or os.environ.get("RERANKER_MODEL") or DEFAULT_RERANKER_MODEL
    top_n = args.top_n or len(passages)
    results = call_reranker(query, passages, model, top_n)
    write_json(args.output, {"query": query, "model": model, "results": results})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="model_client.py",
        description="统一模型调用工具：LLM / Embedding / VLM / Reranker。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # llm
    p_llm = subparsers.add_parser("llm", help="文本 LLM 对话")
    p_llm.add_argument("input", help="提示词文本或文件路径")
    p_llm.add_argument("--system", default=None, help="系统提示词")
    p_llm.add_argument("--model", default=None, help="模型名，默认读取 MODEL_NAME")
    p_llm.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    p_llm.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    p_llm.add_argument("--format", choices=["text", "json"], default="text")
    p_llm.add_argument("-o", "--output", default="-", help="输出文件路径")
    p_llm.set_defaults(func=cmd_llm)

    # embedding
    p_emb = subparsers.add_parser("embedding", help="文本 Embedding")
    p_emb.add_argument("input", help="文本文件、JSONL 文件或 '-' 表示 stdin")
    p_emb.add_argument("--model", default=None, help="模型名，默认读取 EMBEDDING_MODEL")
    p_emb.add_argument("-o", "--output", default="-", help="输出文件路径")
    p_emb.set_defaults(func=cmd_embedding)

    # vlm
    p_vlm = subparsers.add_parser("vlm", help="视觉语言模型")
    p_vlm.add_argument("image", help="图片文件路径或 URL")
    p_vlm.add_argument("--prompt", default="请描述这张图片。", help="视觉提示词")
    p_vlm.add_argument("--model", default=None, help="模型名，默认读取 VLM_MODEL")
    p_vlm.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    p_vlm.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    p_vlm.add_argument("--format", choices=["text", "json"], default="text")
    p_vlm.add_argument("-o", "--output", default="-", help="输出文件路径")
    p_vlm.set_defaults(func=cmd_vlm)

    # rerank
    p_rank = subparsers.add_parser("rerank", help="Reranker")
    p_rank.add_argument("query", help="查询文本")
    p_rank.add_argument("input", help="候选 passages 文件，每行一个")
    p_rank.add_argument("--model", default=None, help="模型名，默认读取 RERANKER_MODEL")
    p_rank.add_argument("--top-n", type=int, default=None, help="返回 TopN")
    p_rank.add_argument("-o", "--output", default="-", help="输出文件路径")
    p_rank.set_defaults(func=cmd_rerank)

    return parser


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
