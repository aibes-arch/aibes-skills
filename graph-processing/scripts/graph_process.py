#!/usr/bin/env python3
"""
图处理统一 CLI：实体关系抽取、Neo4j 写入、Cypher 查询、GraphRAG。

- 实体与关系通过 LLM 从文本中抽取。
- Neo4j 驱动负责图数据写入与查询。
- GraphRAG 通过 LLM 生成 Cypher、检索子图、再生成自然语言回答。
"""

from __future__ import annotations

import argparse
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
    from neo4j import GraphDatabase
except ImportError:  # pragma: no cover
    GraphDatabase = None

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


DEFAULT_MODEL = "moonshot-v1-8k"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 2048


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def read_text(path: Optional[str]) -> str:
    if path is None or path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def read_json(path: Optional[str]) -> Any:
    text = read_text(path)
    return json.loads(text)


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


def clean_json_response(text: str) -> str:
    """去除 LLM 返回的 markdown 代码块标记。"""
    text = text.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
        if text.endswith("```"):
            text = text[:-3].strip()
    return text


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_entities_relationships(
    text: str,
    labels: Optional[List[str]],
    relation_types: Optional[List[str]],
    temperature: float,
    max_tokens: int,
) -> dict:
    system = (
        "你是一位知识图谱构建专家。请从用户提供的文本中抽取实体和关系，"
        "并以严格的 JSON 格式返回。只返回 JSON，不要添加额外说明。"
    )
    label_hint = f"实体类型限定为：{', '.join(labels)}。" if labels else "请合理选择实体类型。"
    relation_hint = (
        f"关系类型限定为：{', '.join(relation_types)}。" if relation_types else "请合理选择关系类型。"
    )
    user = (
        "请从以下文本中抽取实体和关系，输出 JSON。\n\n"
        "格式要求：\n"
        "{\n"
        '  "entities": [\n'
        '    {\n'
        '      "id": "唯一标识（英文小写+下划线）",\n'
        '      "label": "实体类型",\n'
        '      "name": "实体名称",\n'
        '      "properties": {}\n'
        '    }\n'
        '  ],\n'
        '  "relationships": [\n'
        '    {\n'
        '      "source": "源实体 id",\n'
        '      "target": "目标实体 id",\n'
        '      "type": "关系类型（英文大写）",\n'
        '      "properties": {}\n'
        '    }\n'
        '  ]\n'
        "}\n\n"
        f"{label_hint}\n{relation_hint}\n\n{text}"
    )
    raw = llm_chat(system, user, temperature, max_tokens)
    raw = clean_json_response(raw)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Neo4j helpers
# ---------------------------------------------------------------------------

def get_neo4j_driver():
    if GraphDatabase is None:
        raise RuntimeError("neo4j 包未安装，请执行: pip install neo4j")
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD")
    if not all([uri, user, password]):
        raise RuntimeError(
            "缺少 Neo4j 连接信息。请设置 NEO4J_URI、NEO4J_USER、NEO4J_PASSWORD。"
        )
    return GraphDatabase.driver(uri, auth=(user, password))


def run_cypher(query: str, parameters: Optional[dict] = None, database: Optional[str] = None) -> List[dict]:
    driver = get_neo4j_driver()
    parameters = parameters or {}
    try:
        with driver.session(database=database) as session:
            result = session.run(query, parameters)
            records = []
            for record in result:
                records.append({key: _serialize_value(value) for key, value in record.items()})
            return records
    finally:
        driver.close()


def _serialize_value(value: Any) -> Any:
    if hasattr(value, "items"):
        return dict(value.items())
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    if isinstance(value, (int, float, str, bool, type(None))):
        return value
    return str(value)


def load_into_neo4j(data: dict, database: Optional[str] = None, batch_size: int = 100) -> None:
    """将抽取结果写入 Neo4j。"""
    entities = data.get("entities", [])
    relationships = data.get("relationships", [])

    driver = get_neo4j_driver()
    try:
        with driver.session(database=database) as session:
            # Create nodes in batches
            for i in range(0, len(entities), batch_size):
                batch = entities[i : i + batch_size]
                for entity in batch:
                    eid = entity.get("id") or entity.get("name")
                    label = _sanitize_label(entity.get("label", "Entity"))
                    props = {k: v for k, v in entity.get("properties", {}).items()}
                    props["id"] = eid
                    props["name"] = entity.get("name", eid)
                    query = f"""
                    MERGE (n:{label} {{id: $id}})
                    SET n += $props
                    """
                    session.run(query, {"id": eid, "props": props})

            # Create relationships in batches
            for i in range(0, len(relationships), batch_size):
                batch = relationships[i : i + batch_size]
                for rel in batch:
                    source = rel.get("source")
                    target = rel.get("target")
                    rel_type = _sanitize_rel_type(rel.get("type", "RELATED_TO"))
                    props = rel.get("properties", {})
                    query = f"""
                    MATCH (a {{id: $source}}), (b {{id: $target}})
                    MERGE (a)-[r:{rel_type}]->(b)
                    SET r += $props
                    """
                    session.run(query, {"source": source, "target": target, "props": props})
    finally:
        driver.close()


def _sanitize_label(label: str) -> str:
    """确保标签名符合 Cypher 标识符规范。"""
    if not label:
        return "Entity"
    return "".join(ch for ch in label if ch.isalnum() or ch == "_") or "Entity"


def _sanitize_rel_type(rel_type: str) -> str:
    """确保关系类型符合 Cypher 规范（大写+下划线）。"""
    if not rel_type:
        return "RELATED_TO"
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in rel_type)
    return cleaned.upper() or "RELATED_TO"


# ---------------------------------------------------------------------------
# Schema retrieval
# ---------------------------------------------------------------------------

def get_graph_schema(database: Optional[str] = None) -> dict:
    """获取 Neo4j 图谱的节点标签、属性、关系类型。"""
    node_query = """
    MATCH (n)
    WITH labels(n) AS labels, keys(n) AS keys
    RETURN labels, collect(DISTINCT keys) AS key_samples
    LIMIT 1000
    """
    rel_query = """
    MATCH ()-[r]->()
    RETURN DISTINCT type(r) AS rel_type
    LIMIT 1000
    """
    nodes = run_cypher(node_query, database=database)
    relationships = run_cypher(rel_query, database=database)

    label_props: Dict[str, set] = {}
    for record in nodes:
        labels = record.get("labels", [])
        key_samples = record.get("key_samples", [])
        for label in labels:
            label_props.setdefault(label, set())
            for sample in key_samples:
                label_props[label].update(sample)

    rel_types = [r.get("rel_type") for r in relationships if r.get("rel_type")]

    return {
        "nodes": {label: sorted(list(props)) for label, props in label_props.items()},
        "relationships": sorted(rel_types),
    }


# ---------------------------------------------------------------------------
# GraphRAG
# ---------------------------------------------------------------------------

def generate_cypher(question: str, schema: dict, temperature: float, max_tokens: int) -> str:
    system = (
        "你是一位 Neo4j Cypher 查询专家。请根据用户问题和图数据库 schema 生成 Cypher 查询。"
        "只返回一条 Cypher 查询语句，不要添加 markdown 代码块或额外说明。"
    )
    user = (
        f"问题：{question}\n\n"
        f"图数据库 schema：\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        "请生成能回答该问题的 Cypher 查询。"
    )
    return llm_chat(system, user, temperature, max_tokens)


def answer_with_context(question: str, cypher: str, records: List[dict], temperature: float, max_tokens: int) -> str:
    system = (
        "你是一位基于知识图谱的问答助手。请根据用户问题、对应的 Cypher 查询及其返回结果，"
        "生成准确、简洁的自然语言回答。如果查询结果为空，请明确说明。"
    )
    user = (
        f"问题：{question}\n\n"
        f"Cypher 查询：{cypher}\n\n"
        f"查询结果：\n{json.dumps(records, ensure_ascii=False, indent=2)}\n\n"
        "请根据以上信息回答问题。"
    )
    return llm_chat(system, user, temperature, max_tokens)


def graphrag(question: str, database: Optional[str], temperature: float, max_tokens: int) -> dict:
    schema = get_graph_schema(database=database)
    cypher = generate_cypher(question, schema, temperature, max_tokens)
    records = run_cypher(cypher, database=database)
    answer = answer_with_context(question, cypher, records, temperature, max_tokens)
    return {
        "question": question,
        "cypher": cypher,
        "records": records,
        "answer": answer,
    }


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_extract(args: argparse.Namespace) -> None:
    text = read_text(args.input)
    labels = args.label.split(",") if args.label else None
    relation_types = args.relation.split(",") if args.relation else None
    result = extract_entities_relationships(
        text, labels, relation_types, args.temperature, args.max_tokens
    )
    write_json(args.output, result)


def cmd_load(args: argparse.Namespace) -> None:
    data = read_json(args.input)
    load_into_neo4j(data, database=args.database, batch_size=args.batch_size)
    write_json(args.output, {"status": "ok", "entities": len(data.get("entities", [])), "relationships": len(data.get("relationships", []))})


def cmd_query(args: argparse.Namespace) -> None:
    query = read_text(args.input) if Path(args.input).exists() else args.input
    records = run_cypher(query, database=args.database)
    write_json(args.output, records)


def cmd_graphrag(args: argparse.Namespace) -> None:
    result = graphrag(args.question, args.database, args.temperature, args.max_tokens)
    write_json(args.output, result)


def cmd_pipeline(args: argparse.Namespace) -> None:
    text = read_text(args.input)
    labels = args.label.split(",") if args.label else None
    relation_types = args.relation.split(",") if args.relation else None
    data = extract_entities_relationships(
        text, labels, relation_types, args.temperature, args.max_tokens
    )
    load_into_neo4j(data, database=args.database, batch_size=args.batch_size)
    result = {
        "extracted": data,
        "loaded": {
            "entities": len(data.get("entities", [])),
            "relationships": len(data.get("relationships", [])),
            "database": args.database,
        },
    }
    write_json(args.output, result)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="graph_process.py",
        description="图处理工具：实体关系抽取、Neo4j 写入、Cypher 查询、GraphRAG。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # extract
    p_extract = subparsers.add_parser("extract", help="从文本抽取实体和关系")
    p_extract.add_argument("input", help="文本文件路径或 '-' 表示 stdin")
    p_extract.add_argument("-o", "--output", default="-", help="输出 JSON 文件路径")
    p_extract.add_argument("--label", help="限定实体类型，逗号分隔，如 'Person,Organization'")
    p_extract.add_argument("--relation", help="限定关系类型，逗号分隔，如 'WORKS_FOR,LOCATED_IN'")
    p_extract.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    p_extract.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    p_extract.set_defaults(func=cmd_extract)

    # load
    p_load = subparsers.add_parser("load", help="将抽取的 JSON 写入 Neo4j")
    p_load.add_argument("input", help="实体关系 JSON 文件路径")
    p_load.add_argument("-o", "--output", default="-", help="输出结果文件路径")
    p_load.add_argument("--database", default="neo4j", help="Neo4j 数据库名")
    p_load.add_argument("--batch-size", type=int, default=100, help="批量写入大小")
    p_load.set_defaults(func=cmd_load)

    # query
    p_query = subparsers.add_parser("query", help="执行 Cypher 查询")
    p_query.add_argument("input", help="Cypher 文件路径或直接输入查询语句")
    p_query.add_argument("-o", "--output", default="-", help="输出结果文件路径")
    p_query.add_argument("--database", default="neo4j", help="Neo4j 数据库名")
    p_query.set_defaults(func=cmd_query)

    # graphrag
    p_gr = subparsers.add_parser("graphrag", help="基于图谱的问答")
    p_gr.add_argument("question", help="自然语言问题")
    p_gr.add_argument("-o", "--output", default="-", help="输出结果文件路径")
    p_gr.add_argument("--database", default="neo4j", help="Neo4j 数据库名")
    p_gr.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    p_gr.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    p_gr.set_defaults(func=cmd_graphrag)

    # pipeline
    p_pipe = subparsers.add_parser("pipeline", help="抽取并写入 Neo4j")
    p_pipe.add_argument("input", help="文本文件路径或 '-' 表示 stdin")
    p_pipe.add_argument("-o", "--output", default="-", help="输出结果文件路径")
    p_pipe.add_argument("--label", help="限定实体类型，逗号分隔")
    p_pipe.add_argument("--relation", help="限定关系类型，逗号分隔")
    p_pipe.add_argument("--database", default="neo4j", help="Neo4j 数据库名")
    p_pipe.add_argument("--batch-size", type=int, default=100)
    p_pipe.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    p_pipe.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    p_pipe.set_defaults(func=cmd_pipeline)

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
