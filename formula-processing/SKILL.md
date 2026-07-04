---
name: formula-processing
description: 公式处理通用 skill，支持公式识别、LaTeX 转换、变量解释、公式关系抽取。适用于用户要求将图片中的公式转成 LaTeX、把文本公式标准化为 LaTeX、解释公式变量含义或分析变量间关系的场景。图片公式由多模态 LLM 识别，文本公式由文本 LLM 处理。
---

# 公式处理

## 能力范围

1. **公式识别**：识别图片中的数学/物理/化学公式，输出标准 LaTeX。
2. **LaTeX 转换**：将文本形式的公式（如手写格式、ASCII 数学）转换为规范 LaTeX。
3. **变量解释**：解释公式中各变量的含义、单位及公式整体意义。
4. **关系抽取**：分析变量与常量之间的依赖关系（正比、反比、函数关系等）。
5. **综合分析**：一次完成识别/转换 + 解释 + 关系抽取。

## 前置依赖

需要 Python 3.9+。

```bash
cd formula-processing/scripts
pip install -r requirements.txt
```

所有 LLM 任务需要配置 API Key。支持任意 OpenAI 兼容接口：

```bash
# PowerShell
$env:LLM_API_KEY="your-api-key"
$env:LLM_BASE_URL="https://api.moonshot.cn/v1"      # 可选
$env:LLM_MODEL="moonshot-v1-8k"                     # 文本模型默认
$env:LLM_VISION_MODEL="moonshot-v1-8k-vision-preview"  # 视觉模型默认

# Bash
export LLM_API_KEY=your-api-key
export LLM_BASE_URL=https://api.moonshot.cn/v1
export LLM_MODEL=moonshot-v1-8k
export LLM_VISION_MODEL=moonshot-v1-8k-vision-preview
```

也支持在项目根目录放置 `.env` 文件：

```text
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_MODEL=moonshot-v1-8k
LLM_VISION_MODEL=moonshot-v1-8k-vision-preview
```

## 使用方法

### 1. 图片公式识别

```bash
python scripts/formula_process.py recognize formula.png
```

### 2. 文本公式转 LaTeX

```bash
python scripts/formula_process.py convert "E = mc^2"

# 或从文件读取
python scripts/formula_process.py convert formula.txt -o formula.tex
```

### 3. 变量解释

```bash
python scripts/formula_process.py explain "F = G * (m1 * m2) / r^2" -o explanation.json
```

### 4. 关系抽取

```bash
python scripts/formula_process.py relations "y = kx + b" -o relations.json
```

### 5. 综合分析

```bash
# 图片公式
python scripts/formula_process.py analyze formula.png --format json -o result.json

# 文本公式
python scripts/formula_process.py analyze "a^2 + b^2 = c^2" --format json -o result.json
```

### 6. 批量处理目录

```bash
python scripts/formula_process.py analyze ./formulas/ --format jsonl -o batch.jsonl
```

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `input` | 公式文本、文件路径、目录或图片 URL | 必填 |
| `-o` / `--output` | 输出文件路径 | stdout |
| `--format` | 输出格式：`text` / `json` / `jsonl` | `text` |
| `--max-pixels` | 本地图片缩放后的最大像素数 | 2,000,000 |
| `--detail` | 视觉细节级别：`auto` / `low` / `high` | `auto` |
| `--temperature` | LLM 采样温度 | 0.2 |
| `--max-tokens` | LLM 最大输出 token 数 | 2048 |

## 输出格式

### JSON

```json
{
  "input": "formula.png",
  "task": "analyze",
  "result": {
    "latex": "E = mc^{2}",
    "explanation": "...",
    "relations": "..."
  }
}
```

### 批量 JSONL

每行对应一个输入文件，便于后续流水线处理。

## 对话内直接使用

如果用户在对话中直接发送公式图片或文本，可直接使用以下提示词模板。

### 图片公式识别

> 请识别图片中的数学公式，并将其转换为标准 LaTeX 代码。只返回 LaTeX 表达式，不要添加额外说明。

### 文本公式转 LaTeX

> 请将以下公式转换为标准 LaTeX 代码，只返回 LaTeX 表达式：
>
> {formula}

### 变量解释

> 请解释以下公式中每个变量的含义和单位（如有），并说明公式的整体意义。以 JSON 数组返回变量解释，并附带一段整体说明：
>
> {formula}

### 关系抽取

> 请分析以下公式中变量/常量之间的关系，以 JSON 数组返回。每个关系包含 from（来源变量）、to（目标变量）、relation（关系描述）：
>
> {formula}

## 注意事项

- `recognize` 和带图片的 `analyze` 需要多模态 LLM 支持，请确保配置了 `LLM_VISION_MODEL`。
- 公式图片建议清晰、对比度高，避免复杂背景干扰识别。
- LLM 生成的 LaTeX 建议用 Kimi 做二次校验，尤其是复杂分数、矩阵、上下标。
- 批量处理目录时，脚本会根据扩展名自动判断是文本文件还是图片。
