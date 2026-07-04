---
name: retrieval-qdrant
description: Qdrant 向量检索 skill，支持文档索引、稠密检索、混合检索、重排序与 TopK 召回。适用于用户要求将文本数据索引到向量库、基于语义做 TopK 召回、结合关键词过滤做混合检索，或对召回结果进行重排序的场景。默认使用 OpenAI 兼容 Embedding API，可选本地 sentence-transformers 模型。
---

# Qdrant 检索插件

## 能力范围

1. **Collection 管理**：创建、列出 Qdrant collection。
2. **文档索引**：读取文本文件，分块、生成向量，写入 Qdrant。
3. **稠密检索**：基于向量相似度召回 TopK 片段。
4. **混合检索**：向量相似度 + 关键词过滤（payload match）。
5. **重排序**：使用 cross-encoder 对召回结果重新打分排序。
6. **独立重排序**：对已有候选结果 JSONL 进行重排序。

## 前置依赖

需要 Python 3.9+ 和可用的 Qdrant 服务（本地或云端）。

```bash
cd retrieval-qdrant/scripts
pip install -r requirements.txt
```

配置 Qdrant 和 Embedding：

```bash
# PowerShell
$env:QDRANT_URL="http://localhost:6333"
$env:QDRANT_API_KEY=""                # 本地可留空
$env:QDRANT_COLLECTION="documents"

$env:EMBEDDING_API_KEY="your-api-key"
$env:EMBEDDING_BASE_URL="https://api.moonshot.cn/v1"
$env:EMBEDDING_MODEL="text-embedding-v2"

# Bash
export QDRANT_URL=http://localhost:6333
export QDRANT_API_KEY=
export QDRANT_COLLECTION=documents

export EMBEDDING_API_KEY=your-api-key
export EMBEDDING_BASE_URL=https://api.moonshot.cn/v1
export EMBEDDING_MODEL=text-embedding-v2
```

也支持在项目根目录放置 `.env` 文件。

## 使用方法

### 1. 创建 Collection

```bash
python scripts/retrieval_qdrant.py create --collection documents --dim 1024
```

### 2. 列出 Collections

```bash
python scripts/retrieval_qdrant.py list
```

### 3. 索引文档

```bash
python scripts/retrieval_qdrant.py index article.txt --collection documents
```

可自定义分块大小：

```bash
python scripts/retrieval_qdrant.py index article.txt \
  --chunk-size 1000 --chunk-overlap 100 --batch-size 50
```

### 4. 稠密检索

```bash
python scripts/retrieval_qdrant.py search "什么是 GraphRAG？" \
  --collection documents --top-k 5 -o result.json
```

### 5. 混合检索（加关键词过滤）

```bash
python scripts/retrieval_qdrant.py hybrid "GraphRAG 实现" \
  --keyword "Neo4j,Cypher" --collection documents --top-k 5
```

### 6. 重排序

```bash
python scripts/retrieval_qdrant.py search "GraphRAG" \
  --top-k 20 --reranker "BAAI/bge-reranker-base" \
  -o reranked.json
```

> 使用本地模型前需取消 `requirements.txt` 中 `sentence-transformers` 的注释并安装。

### 7. 对已有候选结果重排序

```bash
python scripts/retrieval_qdrant.py rerank candidates.jsonl "GraphRAG" \
  --reranker "BAAI/bge-reranker-base" -o reranked.json
```

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `query` / `input` | 查询文本或文件路径 | 必填 |
| `--collection` | Qdrant collection 名称 | `QDRANT_COLLECTION` / `documents` |
| `--dim` | 向量维度 | 1024 |
| `--embedding-provider` | `api` 或 `local` | `api` |
| `--embedding-model` | Embedding 模型名 | 读取 `EMBEDDING_MODEL` |
| `--chunk-size` | 文本分块大小 | 500 |
| `--chunk-overlap` | 分块重叠 | 50 |
| `--batch-size` | 写入批量 | 100 |
| `--top-k` | 召回数量 | 5 |
| `--keyword` | 关键词过滤，逗号分隔 | 无 |
| `--reranker` | cross-encoder 模型名 | 无 |
| `-o` / `--output` | 输出文件路径 | stdout |

## 输出格式

检索结果以 JSON 数组返回：

```json
[
  {
    "id": "...",
    "score": 0.92,
    "text": "GraphRAG 是一种结合知识图谱的检索增强生成方法...",
    "source": "article.txt",
    "chunk_index": 3
  }
]
```

## 对话内直接使用

如果用户在对话中提供文本并要求做语义检索/TopK 召回，可直接让 Kimi 用以下思路处理：

1. 将文本分块；
2. 调用 Embedding API 获取向量；
3. 存入 Qdrant；
4. 对查询做相同 embedding；
5. 执行向量搜索并返回 TopK 结果。

### TopK 召回提示词

> 你是一位检索专家。用户查询为：{query}
> 候选文档片段如下：
> {chunks}
>
> 请从中选出最相关的 Top-{k} 片段，按相关度降序排列，并说明理由。

## 注意事项

- 本地 Qdrant 可通过 Docker 快速启动：
  ```bash
  docker run -p 6333:6333 qdrant/qdrant
  ```
- `--dim` 必须与 embedding 模型输出维度一致。
- API embedding 默认使用 OpenAI 兼容接口，Moonshot 的 `text-embedding-v2` 维度为 1024。
- 本地 embedding / 重排序需要安装 `sentence-transformers`，首次下载模型可能需要较长时间。
- `hybrid` 中的关键词过滤使用 Qdrant payload 的文本匹配，适合精确匹配关键词的场景。
