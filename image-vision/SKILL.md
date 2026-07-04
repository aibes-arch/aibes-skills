---
name: image-vision
description: 图像/视觉处理通用 skill，支持图片理解、OCR、图像描述、图中对象识别与关系抽取。适用于用户要求描述图片内容、识别图中文字、提取图片中的对象或分析对象间关系的场景。所有理解类任务通过多模态 LLM 完成；本地脚本负责图片编码、批量处理与结果输出。
---

# 图像/视觉处理

## 能力范围

1. **图像描述**：用自然语言描述图片主体、场景、颜色、构图、氛围等。
2. **OCR**：识别图片中的所有文字，保留排版结构。
3. **对象识别**：列出图片中的主要对象，返回结构化 JSON。
4. **关系抽取**：分析对象之间的空间位置、交互动作、从属关系等。
5. **综合分析**：一次调用完成描述 + OCR + 对象 + 关系。

## 前置依赖

需要 Python 3.9+。

```bash
cd image-vision/scripts
pip install -r requirements.txt
```

所有视觉理解任务需要多模态 LLM API Key。支持任意 OpenAI 兼容接口（如 Moonshot、OpenAI、OpenRouter 等）：

```bash
# PowerShell
$env:LLM_API_KEY="your-api-key"
$env:LLM_BASE_URL="https://api.moonshot.cn/v1"      # 可选
$env:LLM_MODEL="moonshot-v1-8k-vision-preview"      # 可选

# Bash
export LLM_API_KEY=your-api-key
export LLM_BASE_URL=https://api.moonshot.cn/v1
export LLM_MODEL=moonshot-v1-8k-vision-preview
```

也支持在项目根目录放置 `.env` 文件：

```text
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_MODEL=moonshot-v1-8k-vision-preview
```

## 使用方法

### 1. 图像描述

```bash
python scripts/image_process.py describe path/to/image.jpg
```

### 2. OCR 文字识别

```bash
python scripts/image_process.py ocr path/to/image.jpg -o ocr_result.txt
```

### 3. 对象识别

```bash
python scripts/image_process.py objects path/to/image.jpg --format json -o objects.json
```

### 4. 关系抽取

```bash
python scripts/image_process.py relations path/to/image.jpg --format json -o relations.json
```

### 5. 综合分析

```bash
python scripts/image_process.py analyze path/to/image.jpg --format json -o analyze_result.json
```

### 6. 批量处理目录

```bash
python scripts/image_process.py analyze path/to/images/ --format jsonl -o batch_results.jsonl
```

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `input` | 图片路径、图片目录或图片 URL | 必填 |
| `-o` / `--output` | 输出文件路径 | stdout |
| `--language` | 输出语言 | 中文 |
| `--format` | 输出格式：`text` / `json` / `jsonl` | `text` |
| `--max-pixels` | 本地图片缩放后的最大像素数 | 2,000,000 |
| `--detail` | 视觉细节级别：`auto` / `low` / `high` | `auto` |
| `--temperature` | LLM 采样温度 | 0.3 |
| `--max-tokens` | LLM 最大输出 token 数 | 2048 |

## 输出格式

- 单张图片 + `text` 格式：直接输出文本结果；`analyze` 会输出 JSON。
- 单张图片 + `json` 格式：
  ```json
  {
    "input": "path/to/image.jpg",
    "task": "describe",
    "result": "..."
  }
  ```
- 目录批量 + `jsonl` 格式：每行一个图片结果，便于后续流水线处理。

## 对话内直接使用

如果用户在对话中直接发送图片，不经过本地脚本，可直接使用以下提示词模板。

### 图像描述

> 请用中文详细描述这张图片。说明画面主体、场景、颜色、构图、文字信息（如有）以及整体氛围。

### OCR

> 请识别这张图片中的所有文字，按原样输出，保留原始排版。如果图片中没有文字，请直接说明。

### 对象识别

> 请识别图片中的主要对象，以 JSON 数组返回。每个对象包含 name（名称）和 description（简短描述）。只返回 JSON 数组。

### 关系抽取

> 请分析图片中对象之间的关系，以 JSON 数组返回。每个关系包含 subject（主体）、predicate（关系）、object（客体），可选 description（补充说明）。只返回 JSON 数组。

### 综合分析

> 请对这张图片进行全面分析，依次输出：
> 1. 图像描述
> 2. 图中文字（OCR）
> 3. 主要对象列表（JSON）
> 4. 对象关系（JSON）

## 注意事项

- 本地图片会被编码为 base64 JPEG 后发送给 LLM，超大图片会先按 `--max-pixels` 等比缩放。
- 支持的图片格式：jpg、jpeg、png、gif、webp、bmp。
- 如果输入是 URL，脚本会直接透传 URL，请确保 LLM 服务能够访问该地址。
- 对象识别和关系抽取依赖 LLM 的 JSON 输出能力，建议让 Kimi 对返回结果做二次校验和格式化。
