#!/usr/bin/env python3
"""
文本处理统一 CLI：清洗、分块、摘要、关键词、实体抽取。

支持从文件或标准输入读取文本，结果输出到标准输出或文件。
摘要/关键词/实体默认通过 OpenAI 兼容接口调用 LLM 完成。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, List

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

try:
    import tiktoken
except ImportError:  # pragma: no cover
    tiktoken = None

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


DEFAULT_MODEL = "moonshot-v1-8k"
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 2048


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def read_text(path: str | None) -> str:
    """从文件或标准输入读取文本。"""
    if path is None or path == "-":
        return sys.stdin.read()
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"输入文件不存在: {path}")
    return p.read_text(encoding="utf-8")


def write_text(path: str | None, content: str) -> None:
    """写入文件或标准输出。"""
    if path is None or path == "-":
        sys.stdout.write(content)
        if not content.endswith("\n"):
            sys.stdout.write("\n")
    else:
        Path(path).write_text(content, encoding="utf-8")


def write_json(path: str | None, data: object) -> None:
    """以 JSON 格式输出。"""
    content = json.dumps(data, ensure_ascii=False, indent=2)
    write_text(path, content)


def write_jsonl(path: str | None, items: Iterable[object]) -> None:
    """以 JSON Lines 格式输出。"""
    lines = [json.dumps(item, ensure_ascii=False) for item in items]
    write_text(path, "\n".join(lines))


# ---------------------------------------------------------------------------
# 文本清洗
# ---------------------------------------------------------------------------

def clean_text(
    text: str,
    *,
    strip_lines: bool = True,
    collapse_blank_lines: bool = True,
    remove_urls: bool = False,
    remove_emails: bool = False,
    remove_phone: bool = False,
    lowercase: bool = False,
    keep_tabs: bool = False,
) -> str:
    """执行基础文本清洗。"""
    # 统一换行符
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 移除非打印控制字符（保留换行、制表符）
    allowed = {"\n", "\t"} if keep_tabs else {"\n"}
    text = "".join(ch for ch in text if ch >= " " or ch in allowed)

    # 折叠行内空白
    if keep_tabs:
        text = re.sub(r"[ \t]+", " ", text)
    else:
        text = re.sub(r" +", " ", text)
        text = re.sub(r"\t+", " ", text)

    if strip_lines:
        text = "\n".join(line.strip() for line in text.splitlines())

    if collapse_blank_lines:
        text = re.sub(r"\n{3,}", "\n\n", text)

    if remove_urls:
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"www\.\S+", "", text)

    if remove_emails:
        text = re.sub(r"\S+@\S+\.\S+", "", text)

    if remove_phone:
        # 适配中国大陆常见手机号/固话格式
        text = re.sub(r"(?:(?:\+?86[- ]?)?1[3-9]\d{9}|\d{3,4}-\d{7,8})", "", text)

    if lowercase:
        text = text.lower()

    return text.strip()


# ---------------------------------------------------------------------------
# 文本分块
# ---------------------------------------------------------------------------

def split_sentences(text: str) -> List[str]:
    """按句子切分（支持中英文常见句末标点）。"""
    pattern = r"(?<=[。！？．.?!])\s*"
    parts = re.split(pattern, text)
    return [p.strip() for p in parts if p.strip()]


def split_paragraphs(text: str) -> List[str]:
    """按段落切分。"""
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def chunk_by_char(text: str, size: int, overlap: int) -> List[str]:
    step = max(1, size - overlap)
    return [text[i : i + size] for i in range(0, len(text), step)]


def chunk_by_token(
    text: str, size: int, overlap: int, encoding_name: str = "cl100k_base"
) -> List[str]:
    if tiktoken is None:
        raise RuntimeError("token 分块需要 tiktoken，请执行: pip install tiktoken")
    enc = tiktoken.get_encoding(encoding_name)
    tokens = enc.encode(text)
    step = max(1, size - overlap)
    chunks: List[str] = []
    for i in range(0, len(tokens), step):
        chunk_tokens = tokens[i : i + size]
        chunks.append(enc.decode(chunk_tokens))
    return chunks


def chunk_text(
    text: str,
    mode: str = "char",
    size: int = 1000,
    overlap: int = 0,
    encoding: str = "cl100k_base",
) -> List[dict]:
    """将文本切分为块，返回带索引的字典列表。"""
    if mode == "char":
        raw = chunk_by_char(text, size, overlap)
    elif mode == "token":
        raw = chunk_by_token(text, size, overlap, encoding)
    elif mode == "sentence":
        raw = split_sentences(text)
    elif mode == "paragraph":
        raw = split_paragraphs(text)
    else:
        raise ValueError(f"不支持的分块模式: {mode}")

    return [{"index": i, "text": t} for i, t in enumerate(raw) if t.strip()]


# ---------------------------------------------------------------------------
# LLM 客户端与提示词
# ---------------------------------------------------------------------------

def get_llm_client():
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


def llm_chat(system: str, user: str, temperature: float, max_tokens: int) -> str:
    client, model = get_llm_client()
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


def summarize(text: str, language: str = "中文", temperature: float = DEFAULT_TEMPERATURE, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    system = (
        "你是一位专业的文本摘要助手。请用简洁、准确的语言总结用户提供的文本，"
        "保留核心观点、关键数据和结论，不添加原文没有的信息。"
    )
    user = f"请用{language}对以下文本生成一段摘要：\n\n{text}"
    return llm_chat(system, user, temperature, max_tokens)


def keywords(text: str, count: int = 10, temperature: float = DEFAULT_TEMPERATURE, max_tokens: int = 512) -> str:
    system = (
        "你是一位关键词提取专家。请从用户文本中提取最重要的关键词，"
        "关键词应能准确反映文本主题。"
    )
    user = (
        f"请从以下文本中提取 {count} 个关键词，按重要性降序排列，"
        "每行一个，不要带编号和额外解释：\n\n{text}"
    )
    return llm_chat(system, user, temperature, max_tokens)


def entities(text: str, temperature: float = DEFAULT_TEMPERATURE, max_tokens: int = 1024) -> str:
    system = (
        "你是一位命名实体识别专家。请从用户文本中抽取人名、机构名、地名、"
        "时间、产品名、专有名词等实体，并以 JSON 数组形式返回。"
    )
    user = (
        "请从以下文本中抽取命名实体。每个实体包含 type（实体类型）和 "
        "name（实体名称）两个字段。以 JSON 数组格式返回，不要添加额外说明：\n\n"
        f"{text}"
    )
    return llm_chat(system, user, temperature, max_tokens)


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------

def cmd_clean(args: argparse.Namespace) -> None:
    text = read_text(args.input)
    cleaned = clean_text(
        text,
        strip_lines=not args.no_strip_lines,
        collapse_blank_lines=not args.keep_blank_lines,
        remove_urls=args.remove_urls,
        remove_emails=args.remove_emails,
        remove_phone=args.remove_phone,
        lowercase=args.lowercase,
        keep_tabs=args.keep_tabs,
    )
    write_text(args.output, cleaned)


def cmd_chunk(args: argparse.Namespace) -> None:
    text = read_text(args.input)
    chunks = chunk_text(
        text,
        mode=args.mode,
        size=args.size,
        overlap=args.overlap,
        encoding=args.encoding,
    )
    if args.format == "json":
        write_json(args.output, chunks)
    elif args.format == "jsonl":
        write_jsonl(args.output, chunks)
    else:
        sep = args.separator.replace("\\n", "\n").replace("\\t", "\t")
        write_text(args.output, sep.join(c["text"] for c in chunks))


def cmd_summarize(args: argparse.Namespace) -> None:
    text = read_text(args.input)
    result = summarize(text, args.language, args.temperature, args.max_tokens)
    write_text(args.output, result)


def cmd_keywords(args: argparse.Namespace) -> None:
    text = read_text(args.input)
    result = keywords(text, args.count, args.temperature, args.max_tokens)
    write_text(args.output, result)


def cmd_entities(args: argparse.Namespace) -> None:
    text = read_text(args.input)
    result = entities(text, args.temperature, args.max_tokens)
    write_text(args.output, result)


def cmd_pipeline(args: argparse.Namespace) -> None:
    text = read_text(args.input)

    if not args.no_clean:
        text = clean_text(
            text,
            strip_lines=True,
            collapse_blank_lines=True,
            remove_urls=args.remove_urls,
            remove_emails=args.remove_emails,
            remove_phone=args.remove_phone,
            lowercase=False,
        )

    if args.no_chunk:
        chunks = [{"index": 0, "text": text}]
    else:
        chunks = chunk_text(
            text,
            mode=args.chunk_mode,
            size=args.chunk_size,
            overlap=args.chunk_overlap,
            encoding=args.encoding,
        )

    results = []
    for chunk in chunks:
        item = {"chunk_index": chunk["index"], "text": chunk["text"]}
        if args.summarize:
            item["summary"] = summarize(
                chunk["text"], args.language, args.temperature, args.max_tokens
            )
        if args.keywords:
            item["keywords"] = keywords(
                chunk["text"], args.keyword_count, args.temperature, 512
            )
        if args.entities:
            item["entities"] = entities(chunk["text"], args.temperature, 1024)
        results.append(item)

    if args.format == "jsonl":
        write_jsonl(args.output, results)
    else:
        write_json(args.output, results)


# ---------------------------------------------------------------------------
# CLI 构建
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="text_process.py",
        description="文本处理工具：清洗、分块、摘要、关键词、实体抽取。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # clean
    p_clean = subparsers.add_parser("clean", help="清洗文本")
    _add_io_args(p_clean)
    p_clean.add_argument("--no-strip-lines", action="store_true", help="不去除行首尾空白")
    p_clean.add_argument("--keep-blank-lines", action="store_true", help="保留连续空行")
    p_clean.add_argument("--remove-urls", action="store_true", help="移除 URL")
    p_clean.add_argument("--remove-emails", action="store_true", help="移除邮箱")
    p_clean.add_argument("--remove-phone", action="store_true", help="移除电话号码")
    p_clean.add_argument("--lowercase", action="store_true", help="转小写")
    p_clean.add_argument("--keep-tabs", action="store_true", help="保留制表符")
    p_clean.set_defaults(func=cmd_clean)

    # chunk
    p_chunk = subparsers.add_parser("chunk", help="文本分块")
    _add_io_args(p_chunk)
    p_chunk.add_argument(
        "--mode",
        choices=["char", "token", "sentence", "paragraph"],
        default="char",
        help="分块模式",
    )
    p_chunk.add_argument("--size", type=int, default=1000, help="块大小（字符或 token 数）")
    p_chunk.add_argument("--overlap", type=int, default=0, help="相邻块重叠量")
    p_chunk.add_argument("--encoding", default="cl100k_base", help="tiktoken encoding 名称")
    p_chunk.add_argument("--format", choices=["text", "json", "jsonl"], default="text")
    p_chunk.add_argument("--separator", default="\n\n---\n\n", help="text 格式下的块分隔符")
    p_chunk.set_defaults(func=cmd_chunk)

    # summarize
    p_sum = subparsers.add_parser("summarize", help="文本摘要（LLM）")
    _add_io_args(p_sum)
    p_sum.add_argument("--language", default="中文", help="摘要语言")
    _add_llm_args(p_sum)
    p_sum.set_defaults(func=cmd_summarize)

    # keywords
    p_kw = subparsers.add_parser("keywords", help="关键词提取（LLM）")
    _add_io_args(p_kw)
    p_kw.add_argument("--count", type=int, default=10, help="关键词数量")
    _add_llm_args(p_kw)
    p_kw.set_defaults(func=cmd_keywords)

    # entities
    p_ent = subparsers.add_parser("entities", help="命名实体抽取（LLM）")
    _add_io_args(p_ent)
    _add_llm_args(p_ent)
    p_ent.set_defaults(func=cmd_entities)

    # pipeline
    p_pipe = subparsers.add_parser("pipeline", help="组合处理流程")
    _add_io_args(p_pipe)
    p_pipe.add_argument("--no-clean", action="store_true", help="跳过清洗")
    p_pipe.add_argument("--no-chunk", action="store_true", help="跳过分块")
    p_pipe.add_argument("--chunk-mode", default="char", choices=["char", "token", "sentence", "paragraph"])
    p_pipe.add_argument("--chunk-size", type=int, default=2000)
    p_pipe.add_argument("--chunk-overlap", type=int, default=200)
    p_pipe.add_argument("--encoding", default="cl100k_base")
    p_pipe.add_argument("--summarize", action="store_true", help="生成摘要")
    p_pipe.add_argument("--keywords", action="store_true", help="提取关键词")
    p_pipe.add_argument("--entities", action="store_true", help="抽取实体")
    p_pipe.add_argument("--keyword-count", type=int, default=5)
    p_pipe.add_argument("--language", default="中文")
    p_pipe.add_argument("--format", choices=["json", "jsonl"], default="json")
    p_pipe.add_argument("--remove-urls", action="store_true")
    p_pipe.add_argument("--remove-emails", action="store_true")
    p_pipe.add_argument("--remove-phone", action="store_true")
    _add_llm_args(p_pipe)
    p_pipe.set_defaults(func=cmd_pipeline)

    return parser


def _add_io_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("input", nargs="?", default="-", help="输入文件路径，默认从 stdin 读取")
    p.add_argument("-o", "--output", default="-", help="输出文件路径，默认输出到 stdout")


def _add_llm_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    p.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)


def main(argv: List[str] | None = None) -> int:
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
