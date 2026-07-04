#!/usr/bin/env python3
"""
统一存储访问 CLI：Qdrant / Milvus / Neo4j / PostgreSQL / MinIO。

为常见存储后端提供基础连接、查询、写入、管理能力。
可作为其他 skill 的底层客户端，也可独立在命令行使用。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def read_text(path: Optional[str]) -> str:
    if path is None or path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Optional[str], data: Any) -> None:
    content = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    if path is None or path == "-":
        sys.stdout.write(content)
        sys.stdout.write("\n")
    else:
        Path(path).write_text(content, encoding="utf-8")


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------

def get_embeddings(texts: List[str], model: Optional[str] = None) -> List[List[float]]:
    if OpenAI is None:
        raise RuntimeError("openai 包未安装")
    api_key = os.environ.get("EMBEDDING_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("MODEL_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 Embedding API Key")
    base_url = os.environ.get("EMBEDDING_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or os.environ.get("MODEL_BASE_URL")
    model = model or os.environ.get("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL
    kwargs: dict = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)
    response = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------

def get_qdrant_client():
    try:
        from qdrant_client import QdrantClient
    except ImportError:
        raise RuntimeError("qdrant-client 未安装")
    url = os.environ.get("QDRANT_URL")
    api_key = os.environ.get("QDRANT_API_KEY")
    if not url:
        raise RuntimeError("缺少 QDRANT_URL")
    kwargs = {"url": url}
    if api_key:
        kwargs["api_key"] = api_key
    return QdrantClient(**kwargs)


def qdrant_list(args: argparse.Namespace) -> None:
    client = get_qdrant_client()
    cols = client.get_collections()
    write_json(args.output, {"collections": [c.name for c in cols.collections]})


def qdrant_create(args: argparse.Namespace) -> None:
    from qdrant_client.models import Distance, VectorParams

    client = get_qdrant_client()
    client.recreate_collection(
        collection_name=args.collection,
        vectors_config=VectorParams(size=args.dim, distance=Distance.COSINE),
    )
    write_json(args.output, {"status": "created", "collection": args.collection})


def qdrant_upsert(args: argparse.Namespace) -> None:
    from qdrant_client.models import PointStruct

    client = get_qdrant_client()
    text = read_text(args.input)
    chunks = chunk_text(text, args.chunk_size, args.chunk_overlap)
    vectors = get_embeddings(chunks, args.embedding_model)
    points = []
    for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
        pid = hashlib.md5(f"{args.input}:{i}:{chunk}".encode()).hexdigest()
        points.append(
            PointStruct(
                id=pid,
                vector=vec,
                payload={"text": chunk, "source": args.input, "chunk_index": i},
            )
        )
    for i in range(0, len(points), args.batch_size):
        client.upsert(collection_name=args.collection, points=points[i : i + args.batch_size])
    write_json(args.output, {"status": "upserted", "collection": args.collection, "points": len(points)})


def qdrant_search(args: argparse.Namespace) -> None:
    client = get_qdrant_client()
    vector = get_embeddings([args.query], args.embedding_model)[0]
    results = client.search(
        collection_name=args.collection,
        query_vector=vector,
        limit=args.top_k,
        with_payload=True,
    )
    write_json(
        args.output,
        [
            {
                "id": r.id,
                "score": r.score,
                "text": r.payload.get("text", ""),
                "source": r.payload.get("source", ""),
            }
            for r in results
        ],
    )


# ---------------------------------------------------------------------------
# Milvus
# ---------------------------------------------------------------------------

def get_milvus_client():
    try:
        from pymilvus import MilvusClient
    except ImportError:
        raise RuntimeError("pymilvus 未安装")
    uri = os.environ.get("MILVUS_URI")
    token = os.environ.get("MILVUS_TOKEN")
    if not uri:
        raise RuntimeError("缺少 MILVUS_URI")
    kwargs = {"uri": uri}
    if token:
        kwargs["token"] = token
    return MilvusClient(**kwargs)


def milvus_list(args: argparse.Namespace) -> None:
    client = get_milvus_client()
    write_json(args.output, {"collections": client.list_collections()})


def milvus_create(args: argparse.Namespace) -> None:
    client = get_milvus_client()
    if client.has_collection(collection_name=args.collection):
        client.drop_collection(collection_name=args.collection)
    client.create_collection(
        collection_name=args.collection,
        dimension=args.dim,
        metric_type="COSINE",
    )
    write_json(args.output, {"status": "created", "collection": args.collection})


def milvus_insert(args: argparse.Namespace) -> None:
    client = get_milvus_client()
    text = read_text(args.input)
    chunks = chunk_text(text, args.chunk_size, args.chunk_overlap)
    vectors = get_embeddings(chunks, args.embedding_model)
    data = [
        {
            "id": hashlib.md5(f"{args.input}:{i}:{chunk}".encode()).hexdigest(),
            "vector": vec,
            "text": chunk,
            "source": args.input,
            "chunk_index": i,
        }
        for i, (chunk, vec) in enumerate(zip(chunks, vectors))
    ]
    client.insert(collection_name=args.collection, data=data)
    write_json(args.output, {"status": "inserted", "collection": args.collection, "points": len(data)})


def milvus_search(args: argparse.Namespace) -> None:
    client = get_milvus_client()
    vector = get_embeddings([args.query], args.embedding_model)[0]
    results = client.search(
        collection_name=args.collection,
        data=[vector],
        limit=args.top_k,
        output_fields=["text", "source"],
    )
    # Milvus returns list of lists
    flat = []
    for group in results:
        for r in group:
            flat.append(
                {
                    "id": r.get("id"),
                    "score": r.get("distance"),
                    "text": r.get("entity", {}).get("text", ""),
                    "source": r.get("entity", {}).get("source", ""),
                }
            )
    write_json(args.output, flat)


# ---------------------------------------------------------------------------
# Neo4j
# ---------------------------------------------------------------------------

def get_neo4j_driver():
    try:
        from neo4j import GraphDatabase
    except ImportError:
        raise RuntimeError("neo4j 包未安装")
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD")
    if not all([uri, user, password]):
        raise RuntimeError("缺少 NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD")
    return GraphDatabase.driver(uri, auth=(user, password))


def neo4j_query(args: argparse.Namespace) -> None:
    query = read_text(args.input) if Path(args.input).exists() else args.input
    driver = get_neo4j_driver()
    try:
        with driver.session(database=args.database) as session:
            result = session.run(query)
            records = []
            for record in result:
                records.append({k: str(v) for k, v in record.items()})
            write_json(args.output, records)
    finally:
        driver.close()


def neo4j_load(args: argparse.Namespace) -> None:
    data = read_json(args.input)
    driver = get_neo4j_driver()
    try:
        with driver.session(database=args.database) as session:
            for e in data.get("entities", []):
                eid = e.get("id") or e.get("name")
                label = "".join(ch for ch in (e.get("label", "Entity") or "Entity") if ch.isalnum() or ch == "_") or "Entity"
                props = dict(e.get("properties", {}))
                props["id"] = eid
                props["name"] = e.get("name", eid)
                session.run(
                    f"MERGE (n:{label} {{id: $id}}) SET n += $props",
                    {"id": eid, "props": props},
                )
            for r in data.get("relationships", []):
                rel_type = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in (r.get("type", "RELATED_TO") or "RELATED_TO")).upper()
                session.run(
                    f"MATCH (a {{id: $s}}), (b {{id: $t}}) MERGE (a)-[r:{rel_type}]->(b) SET r += $props",
                    {"s": r.get("source"), "t": r.get("target"), "props": r.get("properties", {})},
                )
    finally:
        driver.close()
    write_json(args.output, {"status": "loaded", "entities": len(data.get("entities", [])), "relationships": len(data.get("relationships", []))})


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------

def get_postgres_connection():
    try:
        import psycopg2
    except ImportError:
        raise RuntimeError("psycopg2-binary 未安装")
    dsn = os.environ.get("POSTGRES_DSN")
    if not dsn:
        raise RuntimeError("缺少 POSTGRES_DSN")
    return psycopg2.connect(dsn)


def postgres_query(args: argparse.Namespace) -> None:
    query = read_text(args.input) if Path(args.input).exists() else args.input
    conn = get_postgres_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query)
            if cur.description:
                columns = [desc[0] for desc in cur.description]
                rows = [dict(zip(columns, row)) for row in cur.fetchall()]
                write_json(args.output, rows)
            else:
                conn.commit()
                write_json(args.output, {"status": "ok", "rowcount": cur.rowcount})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# MinIO
# ---------------------------------------------------------------------------

def get_minio_client():
    try:
        from minio import Minio
    except ImportError:
        raise RuntimeError("minio 包未安装")
    endpoint = os.environ.get("MINIO_ENDPOINT")
    access_key = os.environ.get("MINIO_ACCESS_KEY")
    secret_key = os.environ.get("MINIO_SECRET_KEY")
    secure = os.environ.get("MINIO_SECURE", "false").lower() in ("true", "1", "yes")
    if not all([endpoint, access_key, secret_key]):
        raise RuntimeError("缺少 MINIO_ENDPOINT / MINIO_ACCESS_KEY / MINIO_SECRET_KEY")
    return Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)


def minio_list_buckets(args: argparse.Namespace) -> None:
    client = get_minio_client()
    buckets = client.list_buckets()
    write_json(args.output, {"buckets": [b.name for b in buckets]})


def minio_list_objects(args: argparse.Namespace) -> None:
    client = get_minio_client()
    objects = client.list_objects(args.bucket, prefix=args.prefix or "", recursive=True)
    write_json(args.output, [{"name": o.object_name, "size": o.size, "last_modified": str(o.last_modified)} for o in objects])


def minio_upload(args: argparse.Namespace) -> None:
    client = get_minio_client()
    object_name = args.object_name or Path(args.file).name
    client.fput_object(args.bucket, object_name, args.file)
    write_json(args.output, {"status": "uploaded", "bucket": args.bucket, "object": object_name})


def minio_download(args: argparse.Namespace) -> None:
    client = get_minio_client()
    dest = args.output or Path(args.object_name).name
    client.fget_object(args.bucket, args.object_name, dest)
    write_json(None, {"status": "downloaded", "bucket": args.bucket, "object": args.object_name, "file": dest})


def minio_delete(args: argparse.Namespace) -> None:
    client = get_minio_client()
    client.remove_object(args.bucket, args.object_name)
    write_json(args.output, {"status": "deleted", "bucket": args.bucket, "object": args.object_name})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="storage_client.py",
        description="统一存储访问工具：Qdrant / Milvus / Neo4j / PostgreSQL / MinIO。",
    )
    subparsers = parser.add_subparsers(dest="backend", required=True)

    # Qdrant
    qd = subparsers.add_parser("qdrant", help="Qdrant 向量库")
    qd_sub = qd.add_subparsers(dest="command", required=True)

    qd_list = qd_sub.add_parser("list", help="列出 collections")
    qd_list.add_argument("-o", "--output", default="-")
    qd_list.set_defaults(func=qdrant_list)

    qd_create = qd_sub.add_parser("create", help="创建/重建 collection")
    qd_create.add_argument("--collection", required=True)
    qd_create.add_argument("--dim", type=int, default=DEFAULT_EMBEDDING_DIM)
    qd_create.add_argument("-o", "--output", default="-")
    qd_create.set_defaults(func=qdrant_create)

    qd_upsert = qd_sub.add_parser("upsert", help="索引文本文件")
    qd_upsert.add_argument("input", help="文本文件路径或 '-' 表示 stdin")
    qd_upsert.add_argument("--collection", required=True)
    qd_upsert.add_argument("--embedding-model", default=None)
    qd_upsert.add_argument("--chunk-size", type=int, default=500)
    qd_upsert.add_argument("--chunk-overlap", type=int, default=50)
    qd_upsert.add_argument("--batch-size", type=int, default=100)
    qd_upsert.add_argument("-o", "--output", default="-")
    qd_upsert.set_defaults(func=qdrant_upsert)

    qd_search = qd_sub.add_parser("search", help="向量检索")
    qd_search.add_argument("query", help="查询文本")
    qd_search.add_argument("--collection", required=True)
    qd_search.add_argument("--embedding-model", default=None)
    qd_search.add_argument("--top-k", type=int, default=5)
    qd_search.add_argument("-o", "--output", default="-")
    qd_search.set_defaults(func=qdrant_search)

    # Milvus
    mv = subparsers.add_parser("milvus", help="Milvus 向量库")
    mv_sub = mv.add_subparsers(dest="command", required=True)

    mv_list = mv_sub.add_parser("list", help="列出 collections")
    mv_list.add_argument("-o", "--output", default="-")
    mv_list.set_defaults(func=milvus_list)

    mv_create = mv_sub.add_parser("create", help="创建/重建 collection")
    mv_create.add_argument("--collection", required=True)
    mv_create.add_argument("--dim", type=int, default=DEFAULT_EMBEDDING_DIM)
    mv_create.add_argument("-o", "--output", default="-")
    mv_create.set_defaults(func=milvus_create)

    mv_insert = mv_sub.add_parser("insert", help="插入文本文件")
    mv_insert.add_argument("input", help="文本文件路径或 '-' 表示 stdin")
    mv_insert.add_argument("--collection", required=True)
    mv_insert.add_argument("--embedding-model", default=None)
    mv_insert.add_argument("--chunk-size", type=int, default=500)
    mv_insert.add_argument("--chunk-overlap", type=int, default=50)
    mv_insert.add_argument("-o", "--output", default="-")
    mv_insert.set_defaults(func=milvus_insert)

    mv_search = mv_sub.add_parser("search", help="向量检索")
    mv_search.add_argument("query", help="查询文本")
    mv_search.add_argument("--collection", required=True)
    mv_search.add_argument("--embedding-model", default=None)
    mv_search.add_argument("--top-k", type=int, default=5)
    mv_search.add_argument("-o", "--output", default="-")
    mv_search.set_defaults(func=milvus_search)

    # Neo4j
    nj = subparsers.add_parser("neo4j", help="Neo4j 图数据库")
    nj_sub = nj.add_subparsers(dest="command", required=True)

    nj_query = nj_sub.add_parser("query", help="执行 Cypher")
    nj_query.add_argument("input", help="Cypher 文件路径或查询语句")
    nj_query.add_argument("--database", default="neo4j")
    nj_query.add_argument("-o", "--output", default="-")
    nj_query.set_defaults(func=neo4j_query)

    nj_load = nj_sub.add_parser("load", help="加载实体关系 JSON")
    nj_load.add_argument("input", help="JSON 文件路径")
    nj_load.add_argument("--database", default="neo4j")
    nj_load.add_argument("-o", "--output", default="-")
    nj_load.set_defaults(func=neo4j_load)

    # PostgreSQL
    pg = subparsers.add_parser("postgres", help="PostgreSQL 数据库")
    pg_sub = pg.add_subparsers(dest="command", required=True)

    pg_query = pg_sub.add_parser("query", help="执行 SQL")
    pg_query.add_argument("input", help="SQL 文件路径或 SQL 语句")
    pg_query.add_argument("-o", "--output", default="-")
    pg_query.set_defaults(func=postgres_query)

    # MinIO
    mn = subparsers.add_parser("minio", help="MinIO 对象存储")
    mn_sub = mn.add_subparsers(dest="command", required=True)

    mn_buckets = mn_sub.add_parser("list-buckets", help="列出 buckets")
    mn_buckets.add_argument("-o", "--output", default="-")
    mn_buckets.set_defaults(func=minio_list_buckets)

    mn_objects = mn_sub.add_parser("list-objects", help="列出对象")
    mn_objects.add_argument("bucket", help="bucket 名称")
    mn_objects.add_argument("--prefix", default=None)
    mn_objects.add_argument("-o", "--output", default="-")
    mn_objects.set_defaults(func=minio_list_objects)

    mn_up = mn_sub.add_parser("upload", help="上传文件")
    mn_up.add_argument("bucket", help="bucket 名称")
    mn_up.add_argument("file", help="本地文件路径")
    mn_up.add_argument("--object-name", default=None, help="对象名，默认使用文件名")
    mn_up.add_argument("-o", "--output", default="-")
    mn_up.set_defaults(func=minio_upload)

    mn_down = mn_sub.add_parser("download", help="下载文件")
    mn_down.add_argument("bucket", help="bucket 名称")
    mn_down.add_argument("object_name", help="对象名")
    mn_down.add_argument("-o", "--output", default=None, help="本地保存路径")
    mn_down.set_defaults(func=minio_download)

    mn_del = mn_sub.add_parser("delete", help="删除对象")
    mn_del.add_argument("bucket", help="bucket 名称")
    mn_del.add_argument("object_name", help="对象名")
    mn_del.add_argument("-o", "--output", default="-")
    mn_del.set_defaults(func=minio_delete)

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
