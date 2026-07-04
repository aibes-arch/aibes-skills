---
name: unified-storage
description: 统一存储访问 skill，支持 Qdrant、Milvus、Neo4j、PostgreSQL、MinIO 五种常见存储后端。适用于作为其他 skill 的底层存储客户端，或在命令行直接管理向量库、图数据库、关系型数据库和对象存储的场景。
---

# 统一存储访问

## 能力范围

1. **Qdrant**：创建 collection、索引文本、向量检索。
2. **Milvus**：创建 collection、插入文本、向量检索。
3. **Neo4j**：执行 Cypher、加载实体关系 JSON。
4. **PostgreSQL**：执行 SQL 查询和更新。
5. **MinIO**：列出 buckets/objects、上传、下载、删除对象。

## 前置依赖

需要 Python 3.9+。

```bash
cd unified-storage/scripts
pip install -r requirements.txt
```

根据实际使用的后端配置环境变量：

```bash
# Qdrant
$env:QDRANT_URL="http://localhost:6333"
$env:QDRANT_API_KEY=""        # 本地可留空

# Milvus
$env:MILVUS_URI="http://localhost:19530"
$env:MILVUS_TOKEN=""

# Neo4j
$env:NEO4J_URI="bolt://localhost:7687"
$env:NEO4J_USER="neo4j"
$env:NEO4J_PASSWORD="password"

# PostgreSQL
$env:POSTGRES_DSN="postgresql://user:password@localhost:5432/dbname"

# MinIO
$env:MINIO_ENDPOINT="localhost:9000"
$env:MINIO_ACCESS_KEY="minioadmin"
$env:MINIO_SECRET_KEY="minioadmin"
$env:MINIO_SECURE="false"     # true/false

# Embedding（Qdrant/Milvus 索引与检索需要）
$env:EMBEDDING_API_KEY="your-api-key"
$env:EMBEDDING_BASE_URL="https://api.moonshot.cn/v1"
$env:EMBEDDING_MODEL="text-embedding-v2"
```

也支持在项目根目录放置 `.env` 文件。

## 使用方法

### Qdrant

```bash
# 列出 collections
python scripts/storage_client.py qdrant list

# 创建 collection
python scripts/storage_client.py qdrant create --collection docs --dim 1024

# 索引文本
python scripts/storage_client.py qdrant upsert article.txt --collection docs

# 检索
python scripts/storage_client.py qdrant search "什么是 RAG？" --collection docs --top-k 5
```

### Milvus

```bash
python scripts/storage_client.py milvus list
python scripts/storage_client.py milvus create --collection docs --dim 1024
python scripts/storage_client.py milvus insert article.txt --collection docs
python scripts/storage_client.py milvus search "什么是 RAG？" --collection docs --top-k 5
```

### Neo4j

```bash
# 执行 Cypher
python scripts/storage_client.py neo4j query "MATCH (n) RETURN n LIMIT 10"

# 从 JSON 加载图谱
python scripts/storage_client.py neo4j load graph.json
```

### PostgreSQL

```bash
python scripts/storage_client.py postgres query "SELECT * FROM users LIMIT 10"

# 从文件执行 SQL
python scripts/storage_client.py postgres query query.sql
```

### MinIO

```bash
# 列出 buckets
python scripts/storage_client.py minio list-buckets

# 列出对象
python scripts/storage_client.py minio list-objects my-bucket --prefix data/

# 上传
python scripts/storage_client.py minio upload my-bucket report.pdf

# 下载
python scripts/storage_client.py minio download my-bucket report.pdf -o local_report.pdf

# 删除
python scripts/storage_client.py minio delete my-bucket report.pdf
```

## 参数说明

### 通用

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-o` / `--output` | 输出文件路径 | stdout |

### Qdrant / Milvus

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--collection` | collection 名称 | 必填 |
| `--dim` | 向量维度 | 1024 |
| `--embedding-model` | Embedding 模型名 | 读取 `EMBEDDING_MODEL` |
| `--chunk-size` | 文本分块大小 | 500 |
| `--chunk-overlap` | 分块重叠 | 50 |
| `--top-k` | 检索数量 | 5 |

### Neo4j

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--database` | 数据库名 | `neo4j` |

### MinIO

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--prefix` | 对象前缀过滤 | 无 |
| `--object-name` | 上传后对象名 | 本地文件名 |

## 在其他 skill 中使用

其他 skill 可以导入 `storage_client.py` 中的函数直接访问存储：

```python
from storage_client import get_qdrant_client, get_neo4j_driver

client = get_qdrant_client()
# ...
```

## 注意事项

- 使用前请确保对应存储服务已启动且网络可达。
- Qdrant / Milvus 的索引/检索需要配置 Embedding API Key。
- PostgreSQL 的 SQL 文件可以包含多条语句，但查询结果只返回最后一条 SELECT 的结果。
- MinIO 的 `MINIO_SECURE` 用于控制是否使用 HTTPS，本地测试通常设为 `false`。
