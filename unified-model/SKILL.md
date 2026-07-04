---
name: unified-model
description: 统一模型调用 skill，支持 LLM、Embedding、VLM、Reranker 的 OpenAI 兼容接口调用。适用于作为其他 skill 的底层模型客户端，或在命令行直接调用各类模型 API 的场景。
---

# 统一模型调用

## 能力范围

1. **LLM 调用**：发送文本提示，获取文本回复。
2. **Embedding 调用**：批量获取文本向量。
3. **VLM 调用**：发送图片 + 文本提示，获取视觉理解回复。
4. **Reranker 调用**：对候选 passages 按查询相关性重排序。

## 前置依赖

需要 Python 3.9+。

```bash
cd unified-model/scripts
pip install -r requirements.txt
```

配置模型 API：

```bash
# PowerShell
$env:MODEL_API_KEY="your-api-key"
$env:MODEL_BASE_URL="https://api.moonshot.cn/v1"
$env:MODEL_NAME="moonshot-v1-8k"
$env:EMBEDDING_MODEL="text-embedding-v2"
$env:VLM_MODEL="moonshot-v1-8k-vision-preview"
$env:RERANKER_MODEL="jina-reranker-v2-base-multilingual"

# Bash
export MODEL_API_KEY=your-api-key
export MODEL_BASE_URL=https://api.moonshot.cn/v1
export MODEL_NAME=moonshot-v1-8k
export EMBEDDING_MODEL=text-embedding-v2
export VLM_MODEL=moonshot-v1-8k-vision-preview
export RERANKER_MODEL=jina-reranker-v2-base-multilingual
```

也支持在项目根目录放置 `.env` 文件。

## 使用方法

### 1. LLM 调用

```bash
# 直接输入提示词
python scripts/model_client.py llm "你好，请介绍一下自己"

# 从文件读取提示词
python scripts/model_client.py llm prompt.txt -o response.txt

# 带系统提示词
python scripts/model_client.py llm prompt.txt \
  --system "你是一位 helpful assistant" \
  --model moonshot-v1-8k \
  --format json -o response.json
```

### 2. Embedding 调用

```bash
# 每行一个文本
python scripts/model_client.py embedding texts.txt -o embeddings.json

# JSONL 输入
python scripts/model_client.py embedding texts.jsonl -o embeddings.json
```

### 3. VLM 调用

```bash
python scripts/model_client.py vlm image.jpg \
  --prompt "请描述这张图片" \
  --model moonshot-v1-8k-vision-preview \
  -o description.txt
```

### 4. Reranker 调用

```bash
python scripts/model_client.py rerank "什么是 RAG？" passages.txt \
  --top-n 5 -o ranked.json
```

> Reranker 需要后端提供 OpenAI 兼容的 `/rerank` 端点（如 Jina AI、部分私有化部署）。

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `input` / `image` / `query` | 输入文本、文件、图片或查询 | 必填 |
| `--model` | 模型名 | 读取对应 `MODEL_NAME` / `EMBEDDING_MODEL` / `VLM_MODEL` / `RERANKER_MODEL` |
| `--system` | LLM 系统提示词 | 无 |
| `--temperature` | 采样温度 | 0.3 |
| `--max-tokens` | 最大输出 token 数 | 2048 |
| `--format` | LLM/VLM 输出格式：`text` / `json` | `text` |
| `--top-n` | Reranker 返回数量 | 全部 |
| `-o` / `--output` | 输出文件路径 | stdout |

## 输出格式

### LLM JSON

```json
{
  "prompt": "你好",
  "response": "你好！有什么可以帮你的吗？",
  "model": "moonshot-v1-8k"
}
```

### Embedding JSON

```json
[
  {
    "text": "你好",
    "embedding": [0.1, 0.2, ...]
  }
]
```

### Reranker JSON

```json
{
  "query": "什么是 RAG？",
  "model": "jina-reranker-v2-base-multilingual",
  "results": [
    {"index": 0, "relevance_score": 0.95, "document": {"text": "..."}}
  ]
}
```

## 在其他 skill 中使用

其他 skill 可以通过导入 `model_client.py` 中的函数直接调用模型：

```python
from model_client import call_llm, call_embedding, call_vlm, call_reranker

response = call_llm("你好", system=None, temperature=0.3, max_tokens=1024, model="moonshot-v1-8k")
```

## 注意事项

- 默认使用 OpenAI 兼容协议。若 provider 不支持某类模型（如 Reranker），会返回相应错误。
- VLM 图片会被编码为 base64 JPEG，超大图片会自动缩放。
- Embedding 输入支持纯文本文件（每行一条）或 JSONL（字段 `text` 或 `input`）。
- Reranker 输出结构取决于后端实现，常见字段包括 `index` 和 `relevance_score`。
