---
name: graph-processing
description: 图处理与知识图谱 skill，支持从文本抽取实体关系、写入 Neo4j、执行 Cypher 查询、GraphRAG 问答。适用于用户要求构建知识图谱、将文本/表格数据导入图数据库、生成 Cypher 查询或基于图谱进行问答的场景。实体关系抽取和查询生成由 LLM 完成，图存储与检索由 Neo4j 完成。
---

# 图处理与知识图谱

## 能力范围

1. **实体关系抽取**：从文本中抽取实体、关系和属性，输出结构化 JSON。
2. **Neo4j 写入**：将抽取结果批量写入 Neo4j，自动创建节点和关系。
3. **Cypher 查询**：执行 Cypher 查询并返回 JSON 结果。
4. **GraphRAG**：自然语言问题 → Cypher 生成 → 子图检索 → 自然语言回答。
5. **流水线**：文本 → 抽取 → 写入 Neo4j，一步完成。

## 前置依赖

需要 Python 3.9+ 和可用的 Neo4j 数据库（本地或远程）。

```bash
cd graph-processing/scripts
pip install -r requirements.txt
```

配置 LLM 和 Neo4j：

```bash
# PowerShell
$env:LLM_API_KEY="your-api-key"
$env:LLM_BASE_URL="https://api.moonshot.cn/v1"
$env:LLM_MODEL="moonshot-v1-8k"

$env:NEO4J_URI="bolt://localhost:7687"
$env:NEO4J_USER="neo4j"
$env:NEO4J_PASSWORD="your-password"

# Bash
export LLM_API_KEY=your-api-key
export LLM_BASE_URL=https://api.moonshot.cn/v1
export LLM_MODEL=moonshot-v1-8k

export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=your-password
```

也支持在项目根目录放置 `.env` 文件：

```text
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_MODEL=moonshot-v1-8k

NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password
```

## 使用方法

### 1. 从文本抽取实体和关系

```bash
python scripts/graph_process.py extract article.txt -o graph.json
```

限定实体类型和关系类型：

```bash
python scripts/graph_process.py extract article.txt \
  --label "Person,Organization,Location" \
  --relation "WORKS_FOR,LOCATED_IN,FOUNDED" \
  -o graph.json
```

输出结构：

```json
{
  "entities": [
    {"id": "alice", "label": "Person", "name": "Alice", "properties": {}}
  ],
  "relationships": [
    {"source": "alice", "target": "acme", "type": "WORKS_FOR", "properties": {}}
  ]
}
```

### 2. 写入 Neo4j

```bash
python scripts/graph_process.py load graph.json --database neo4j
```

### 3. 执行 Cypher 查询

```bash
python scripts/graph_process.py query "MATCH (n) RETURN n LIMIT 10" -o result.json

# 从文件读取查询
python scripts/graph_process.py query query.cypher -o result.json
```

### 4. GraphRAG 问答

```bash
python scripts/graph_process.py graphrag "谁是 Alice 的同事？" -o answer.json
```

输出包含生成的 Cypher、查询结果和自然语言回答。

### 5. 完整流水线

```bash
python scripts/graph_process.py pipeline article.txt --database neo4j -o pipeline_result.json
```

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `input` / `question` | 输入文件、查询语句或问题 | 必填 |
| `-o` / `--output` | 输出文件路径 | stdout |
| `--label` | 限定实体类型，逗号分隔 | 无 |
| `--relation` | 限定关系类型，逗号分隔 | 无 |
| `--database` | Neo4j 数据库名 | `neo4j` |
| `--batch-size` | 写入批量大小 | 100 |
| `--temperature` | LLM 采样温度 | 0.2 |
| `--max-tokens` | LLM 最大输出 token 数 | 2048 |

## GraphRAG 流程

1. **Schema 获取**：查询 Neo4j 中的节点标签、属性、关系类型。
2. **Cypher 生成**：将用户问题 + schema 传给 LLM，生成可执行 Cypher。
3. **子图检索**：执行 Cypher 查询，获取相关节点和关系。
4. **答案生成**：将问题、Cypher 和查询结果传给 LLM，生成自然语言回答。

## 对话内直接使用

如果用户在对话中直接提供文本并要求构建图谱，可直接使用以下提示词模板。

### 实体关系抽取

> 请从以下文本中抽取实体和关系，以 JSON 格式返回。
> entities 数组每个元素包含 id、label、name、properties。
> relationships 数组每个元素包含 source、target、type、properties。
>
> {text}

### Cypher 生成

> 已知 Neo4j 图数据库 schema 如下：
> {schema}
>
> 请为以下问题生成一条 Cypher 查询：
> {question}

### GraphRAG 回答

> 问题：{question}
> Cypher 查询：{cypher}
> 查询结果：{records}
>
> 请根据以上信息用中文回答问题。

## 注意事项

- 写入 Neo4j 前请确保数据库服务已启动且可以连接。
- 实体 `id` 字段用于去重和关联关系，建议使用英文小写+下划线格式。
- LLM 生成的 Cypher 可能在复杂 schema 上需要人工校验；GraphRAG 结果中会保留原始 Cypher 方便排查。
- 大批量写入时可通过 `--batch-size` 调整单次事务大小。
- 当前 schema 获取不依赖 APOC，仅使用基础 `MATCH` 语句采样。
