#!/usr/bin/env python3
"""
Qdrant 检索插件：索引、稠密检索、混合检索、重排序、TopK 召回。

- 默认使用 OpenAI 兼容 Embedding API 生成向量。
- 可选本地 sentence-transformers 模型。
- 可选 cross-encoder 重排序。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchText,
        PointStruct,
        VectorParams,
    )
except ImportError:  # pragma: no cover
    QdrantClient = None

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


DEFAULT_EMBEDDING_MODEL = "text-embedding-v2"
DEFAULT_EMBEDDING_DIM = 1024
DEFAULT_TOP_K = 5
DEFAULT_TEMPERATURE = 0.0


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def read_text(path: Optional[str]) -> str:
    if path is None or path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def read_jsonl(path: str) -> List[dict]:
    lines = Path(path).read_text(encoding="utf-8").strip().split("\n")
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


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """简单按字符分块，支持重叠。"""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


# ---------------------------------------------------------------------------
# Embedding provider
# ---------------------------------------------------------------------------

class EmbeddingProvider:
    def embed(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError


class APIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, api_key: str, base_url: Optional[str], model: str):
        if OpenAI is None:
            raise RuntimeError("openai 包未安装")
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)
        self.model = model

    def embed(self, texts: List[str]) -> List[List[float]]:
        response = self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]


class LocalEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model_name: str):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise RuntimeError(
                "本地 embedding 需要 sentence-transformers，请取消 requirements.txt 中的注释并安装。"
            )
        self.model = SentenceTransformer(model_name)

    def embed(self, texts: List[str]) -> List[List[float]]:
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()


def get_embedding_provider(provider: str, model: Optional[str] = None) -> EmbeddingProvider:
    if provider == "api":
        api_key = os.environ.get("EMBEDDING_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
        if not api_key:
            raise RuntimeError(
                "API embedding 需要 EMBEDDING_API_KEY / OPENAI_API_KEY / LLM_API_KEY"
            )
        base_url = os.environ.get("EMBEDDING_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or os.environ.get("LLM_BASE_URL")
        model = model or os.environ.get("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL
        return APIEmbeddingProvider(api_key, base_url, model)
    if provider == "local":
        model = model or os.environ.get("LOCAL_EMBEDDING_MODEL") or "BAAI/bge-small-zh-v1.5"
        return LocalEmbeddingProvider(model)
    raise ValueError(f"不支持的 embedding provider: {provider}")


# ---------------------------------------------------------------------------
# Reranker provider
# ---------------------------------------------------------------------------

class RerankerProvider:
    def rerank(self, query: str, passages: List[str]) -> List[Tuple[int, float]]:
        raise NotImplementedError


class CrossEncoderReranker(RerankerProvider):
    def __init__(self, model_name: str):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            raise RuntimeError(
                "重排序需要 sentence-transformers，请取消 requirements.txt 中的注释并安装。"
            )
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, passages: List[str]) -> List[Tuple[int, float]]:
        pairs = [(query, p) for p in passages]
        scores = self.model.predict(pairs)
        indexed = list(enumerate(scores))
        indexed.sort(key=lambda x: x[1], reverse=True)
        return indexed


def get_reranker(model_name: Optional[str]) -> Optional[RerankerProvider]:
    if not model_name:
        return None
    return CrossEncoderReranker(model_name)


# ---------------------------------------------------------------------------
# Qdrant client
# ---------------------------------------------------------------------------

def get_qdrant_client() -> QdrantClient:
    if QdrantClient is None:
        raise RuntimeError("qdrant-client 未安装")
    url = os.environ.get("QDRANT_URL")
    api_key = os.environ.get("QDRANT_API_KEY")
    if not url:
        raise RuntimeError("缺少 QDRANT_URL")
    kwargs: dict = {"url": url}
    if api_key:
        kwargs["api_key"] = api_key
    return QdrantClient(**kwargs)


def get_collection_name(name: Optional[str]) -> str:
    return name or os.environ.get("QDRANT_COLLECTION") or "documents"


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_create(args: argparse.Namespace) -> None:
    client = get_qdrant_client()
    collection_name = get_collection_name(args.collection)
    client.recreate_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=args.dim, distance=Distance.COSINE),
    )
    write_json(args.output, {"status": "created", "collection": collection_name, "dim": args.dim})


def cmd_list(args: argparse.Namespace) -> None:
    client = get_qdrant_client()
    collections = client.get_collections()
    names = [c.name for c in collections.collections]
    write_json(args.output, {"collections": names})


def cmd_index(args: argparse.Namespace) -> None:
    client = get_qdrant_client()
    collection_name = get_collection_name(args.collection)
    embedder = get_embedding_provider(args.embedding_provider, args.embedding_model)

    # Read input
    text = read_text(args.input)
    chunks = chunk_text(text, args.chunk_size, args.chunk_overlap)

    # Prepare points
    embeddings = embedder.embed(chunks)
    points = []
    for i, (chunk, vec) in enumerate(zip(chunks, embeddings)):
        point_id = hashlib.md5(f"{args.input}:{i}:{chunk}".encode()).hexdigest()
        points.append(
            PointStruct(
                id=point_id,
                vector=vec,
                payload={"text": chunk, "source": args.input, "chunk_index": i},
            )
        )

    # Upsert in batches
    batch_size = args.batch_size
    for i in range(0, len(points), batch_size):
        client.upsert(collection_name=collection_name, points=points[i : i + batch_size])

    write_json(
        args.output,
        {
            "status": "indexed",
            "collection": collection_name,
            "chunks": len(points),
            "source": args.input,
        },
    )


def cmd_search(args: argparse.Namespace) -> None:
    client = get_qdrant_client()
    collection_name = get_collection_name(args.collection)
    embedder = get_embedding_provider(args.embedding_provider, args.embedding_model)

    query_vector = embedder.embed([args.query])[0]
    results = client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=args.top_k,
        with_payload=True,
    )

    passages = [r.payload.get("text", "") for r in results]
    reranker = get_reranker(args.reranker)
    if reranker and passages:
        ranked = reranker.rerank(args.query, passages)
        results = [results[idx] for idx, _ in ranked]

    output = [
        {
            "id": r.id,
            "score": r.score,
            "text": r.payload.get("text", ""),
            "source": r.payload.get("source", ""),
            "chunk_index": r.payload.get("chunk_index", -1),
        }
        for r in results
    ]
    write_json(args.output, output)


def cmd_hybrid(args: argparse.Namespace) -> None:
    client = get_qdrant_client()
    collection_name = get_collection_name(args.collection)
    embedder = get_embedding_provider(args.embedding_provider, args.embedding_model)

    query_vector = embedder.embed([args.query])[0]

    # Build keyword filter
    flt = None
    if args.keyword:
        conditions = [
            FieldCondition(key="text", match=MatchText(text=kw))
            for kw in args.keyword.split(",")
        ]
        flt = Filter(should=conditions)

    results = client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        query_filter=flt,
        limit=args.top_k,
        with_payload=True,
    )

    passages = [r.payload.get("text", "") for r in results]
    reranker = get_reranker(args.reranker)
    if reranker and passages:
        ranked = reranker.rerank(args.query, passages)
        results = [results[idx] for idx, _ in ranked]

    output = [
        {
            "id": r.id,
            "score": r.score,
            "text": r.payload.get("text", ""),
            "source": r.payload.get("source", ""),
            "chunk_index": r.payload.get("chunk_index", -1),
        }
        for r in results
    ]
    write_json(args.output, output)


def cmd_rerank(args: argparse.Namespace) -> None:
    """对已有的候选结果（JSONL）进行重排序。"""
    reranker = get_reranker(args.reranker)
    if not reranker:
        raise RuntimeError("请通过 --reranker 指定重排序模型")
    candidates = read_jsonl(args.input)
    passages = [c.get("text", "") for c in candidates]
    ranked = reranker.rerank(args.query, passages)
    output = [
        {
            **candidates[idx],
            "rerank_score": float(score),
            "rank": i + 1,
        }
        for i, (idx, score) in enumerate(ranked)
    ]
    write_json(args.output, output)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="retrieval_qdrant.py",
        description="Qdrant 检索插件：索引、检索、混合检索、重排序。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create
    p_create = subparsers.add_parser("create", help="创建/重建 Qdrant collection")
    p_create.add_argument("--collection", help="集合名称，默认读取 QDRANT_COLLECTION")
    p_create.add_argument("--dim", type=int, default=DEFAULT_EMBEDDING_DIM, help="向量维度")
    p_create.add_argument("-o", "--output", default="-", help="输出文件路径")
    p_create.set_defaults(func=cmd_create)

    # list
    p_list = subparsers.add_parser("list", help="列出所有 collections")
    p_list.add_argument("-o", "--output", default="-", help="输出文件路径")
    p_list.set_defaults(func=cmd_list)

    # index
    p_index = subparsers.add_parser("index", help="将文本文件索引到 Qdrant")
    p_index.add_argument("input", help="文本文件路径或 '-' 表示 stdin")
    p_index.add_argument("--collection", help="集合名称")
    p_index.add_argument("--embedding-provider", choices=["api", "local"], default="api")
    p_index.add_argument("--embedding-model", default=None, help="embedding 模型名")
    p_index.add_argument("--chunk-size", type=int, default=500)
    p_index.add_argument("--chunk-overlap", type=int, default=50)
    p_index.add_argument("--batch-size", type=int, default=100)
    p_index.add_argument("-o", "--output", default="-", help="输出文件路径")
    p_index.set_defaults(func=cmd_index)

    # search
    p_search = subparsers.add_parser("search", help="稠密向量检索")
    p_search.add_argument("query", help="查询文本")
    p_search.add_argument("--collection", help="集合名称")
    p_search.add_argument("--embedding-provider", choices=["api", "local"], default="api")
    p_search.add_argument("--embedding-model", default=None)
    p_search.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p_search.add_argument("--reranker", default=None, help="cross-encoder 模型名，如 BAAI/bge-reranker-base")
    p_search.add_argument("-o", "--output", default="-", help="输出文件路径")
    p_search.set_defaults(func=cmd_search)

    # hybrid
    p_hybrid = subparsers.add_parser("hybrid", help="稠密 + 关键词混合检索")
    p_hybrid.add_argument("query", help="查询文本")
    p_hybrid.add_argument("--keyword", help="关键词过滤，逗号分隔")
    p_hybrid.add_argument("--collection", help="集合名称")
    p_hybrid.add_argument("--embedding-provider", choices=["api", "local"], default="api")
    p_hybrid.add_argument("--embedding-model", default=None)
    p_hybrid.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p_hybrid.add_argument("--reranker", default=None)
    p_hybrid.add_argument("-o", "--output", default="-", help="输出文件路径")
    p_hybrid.set_defaults(func=cmd_hybrid)

    # rerank
    p_rerank = subparsers.add_parser("rerank", help="对候选结果 JSONL 重排序")
    p_rerank.add_argument("input", help="候选结果 JSONL 文件路径")
    p_rerank.add_argument("query", help="查询文本")
    p_rerank.add_argument("--reranker", required=True, help="cross-encoder 模型名")
    p_rerank.add_argument("-o", "--output", default="-", help="输出文件路径")
    p_rerank.set_defaults(func=cmd_rerank)

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
