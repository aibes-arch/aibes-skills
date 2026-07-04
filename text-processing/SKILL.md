---
name: text-processing
description: 文本处理通用 skill，支持文本清洗、分块、摘要、关键词提取、命名实体抽取。适用于用户要求清洗/清理文本、将长文本切分成块、生成摘要、提取关键词、抽取人名/机构/地名等实体，或需要组合执行以上步骤的场景。摘要/关键词/实体通过 LLM 完成，清洗与分块由本地 Python 脚本确定性执行。
---

# 文本处理

## 能力范围

1. **文本清洗**：去除多余空白、统一换行、移除 URL/邮箱/电话、转小写等。
2. **文本分块**：按字符、token、句子、段落切分，支持重叠窗口。
3. **文本摘要**：调用 LLM 生成简洁摘要。
4. **关键词提取**：调用 LLM 提取主题关键词。
5. **命名实体抽取**：调用 LLM 抽取人名、机构名、地名、时间、产品名等实体。
6. **组合流水线**：清洗 → 分块 → 摘要/关键词/实体，一步完成。

## 前置依赖

需要 Python 3.9+。

```bash
cd text-processing/scripts
pip install -r requirements.txt
```

摘要/关键词/实体需要配置 LLM API Key。支持任意 OpenAI 兼容接口（如 Moonshot、OpenAI、OpenRouter、本地 vLLM 等）：

```bash
# PowerShell
$env:LLM_API_KEY="your-api-key"
$env:LLM_BASE_URL="https://api.moonshot.cn/v1"  # 可选
$env:LLM_MODEL="moonshot-v1-8k"                  # 可选，默认 moonshot-v1-8k

# Bash
export LLM_API_KEY=your-api-key
export LLM_BASE_URL=https://api.moonshot.cn/v1
export LLM_MODEL=moonshot-v1-8k
```

也可在项目根目录放置 `.env` 文件：

```text
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_MODEL=moonshot-v1-8k
```

## 使用方法

### 1. 文本清洗

```bash
# 清洗文件
python scripts/text_process.py clean article.txt -o cleaned.txt

# 同时移除 URL 和邮箱
python scripts/text_process.py clean article.txt -o cleaned.txt --remove-urls --remove-emails

# 从 stdin 读取
cat article.txt | python scripts/text_process.py clean > cleaned.txt
```

### 2. 文本分块

```bash
# 按 1000 字符分块，块间重叠 200 字符
python scripts/text_process.py chunk long_text.txt --size 1000 --overlap 200

# 按 token 分块（需要 tiktoken）
python scripts/text_process.py chunk long_text.txt --mode token --size 512 --overlap 50

# 按句子分块
python scripts/text_process.py chunk long_text.txt --mode sentence --format jsonl -o chunks.jsonl
```

### 3. 文本摘要

```bash
python scripts/text_process.py summarize article.txt -o summary.txt
```

### 4. 关键词提取

```bash
python scripts/text_process.py keywords article.txt --count 15 -o keywords.txt
```

### 5. 命名实体抽取

```bash
python scripts/text_process.py entities article.txt -o entities.json
```

### 6. 组合流水线

```bash
python scripts/text_process.py pipeline article.txt \
  --chunk-size 2000 --chunk-overlap 200 \
  --summarize --keywords --entities \
  -o result.json
```

## 输出格式

- `clean` 输出纯文本。
- `chunk` 支持 `text`（默认）、`json`、`jsonl`。
- `summarize` / `keywords` / `entities` 输出纯文本；其中 `entities` 返回 JSON 数组。
- `pipeline` 输出 `json` 或 `jsonl`，每条记录包含 `chunk_index`、`text` 以及选择的 LLM 任务结果。

## 对话内直接使用

如果用户直接把文本贴在对话里，不经过本地文件，可直接用以下提示词模板调用 LLM 完成对应任务。

### 摘要

> 请对以下文本生成一段简洁的中文摘要，保留核心观点和关键信息，不添加原文没有的内容：
>
> {text}

### 关键词

> 请从以下文本中提取 {n} 个关键词，按重要性降序排列，每行一个，不要带编号和额外解释：
>
> {text}

### 命名实体

> 请从以下文本中抽取命名实体。每个实体包含 type（实体类型：人名、机构名、地名、时间、产品名、专有名词）和 name（实体名称）两个字段。以 JSON 数组格式返回，不要添加额外说明：
>
> {text}

## 注意事项

- 长文本建议先 `chunk` 再调用 LLM 任务，避免超出模型上下文长度。
- 实体抽取结果由 LLM 直接返回，建议让 Kimi 对 JSON 做二次校验。
- 若未配置 `LLM_API_KEY`，摘要/关键词/实体脚本会报错并提示配置方法。
- `.env` 文件会被脚本自动加载，方便在项目中统一管理密钥。
