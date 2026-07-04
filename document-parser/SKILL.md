---
name: document-parser
description: 文档解析 skill，支持 PDF / Word / PPT 的结构化提取与版面分析。适用于用户要求提取文档段落、表格、图片位置、标题层级、幻灯片结构，或分析页面版面（列数、阅读顺序、文本块坐标）的场景。基于 pypdfium2、pdfplumber、python-docx、python-pptx 确定性执行。
---

# 文档解析

## 能力范围

1. **PDF 解析**：提取文本块、表格、图片位置、页面尺寸、阅读顺序。
2. **Word 解析**：提取段落、标题层级、表格、样式信息。
3. **PPT 解析**：提取幻灯片文本框、表格、图片位置、演讲者备注。
4. **版面分析**：PDF 列数检测、文本块分布、PPT/Word 内容摘要。
5. **内容提取**：将文本和表格导出到目录，便于下游处理。

## 前置依赖

需要 Python 3.9+。

```bash
cd document-parser/scripts
pip install -r requirements.txt
```

## 使用方法

### 1. 解析文档为结构化 JSON

```bash
# PDF
python scripts/document_parse.py parse report.pdf -o report.json

# Word
python scripts/document_parse.py parse report.docx -o report.json

# PPT
python scripts/document_parse.py parse slides.pptx -o slides.json
```

### 2. 版面分析

```bash
python scripts/document_parse.py layout report.pdf -o layout.json
```

### 3. 提取文本和表格到目录

```bash
python scripts/document_parse.py extract report.pdf -o ./report_extracted/
```

输出目录结构：

```text
report_extracted/
├── text.txt
└── tables.json
```

## 输出格式

### PDF 解析结果

```json
{
  "file": "report.pdf",
  "type": "pdf",
  "page_count": 10,
  "pages": [
    {
      "page_number": 1,
      "width": 612,
      "height": 792,
      "elements": [
        {
          "type": "text",
          "text": "第一章 引言",
          "bbox": [72, 72, 200, 90]
        },
        {
          "type": "table",
          "rows": [["...", "..."]],
          "bbox": null
        }
      ],
      "table_count": 1,
      "image_count": null
    }
  ]
}
```

### Word 解析结果

```json
{
  "file": "report.docx",
  "type": "docx",
  "paragraph_count": 120,
  "table_count": 3,
  "elements": [
    {"type": "heading", "text": "摘要", "style": "Heading 1", "index": 0},
    {"type": "paragraph", "text": "本文研究了...", "style": "Normal", "index": 1},
    {"type": "table", "table_index": 0, "rows": [["..."]]}
  ]
}
```

### PPT 解析结果

```json
{
  "file": "slides.pptx",
  "type": "pptx",
  "slide_count": 20,
  "slides": [
    {
      "slide_number": 1,
      "elements": [
        {"type": "text", "text": "标题", "left": 100, "top": 50, "width": 500, "height": 80}
      ],
      "notes": "演讲者备注"
    }
  ]
}
```

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `input` | 输入文件路径 | 必填 |
| `-o` / `--output` | 输出文件路径或目录 | stdout |
| `--extract-images` | 尝试提取图片位置信息 | False |

## 版面分析提示词

如果用户在对话中直接提供 PDF/Word/PPT 并要求分析版面，可直接使用以下提示词模板。

### PDF 版面分析

> 请分析以下 PDF 页面元素的版面结构：
> - 判断页面是单栏还是多栏布局；
> - 按阅读顺序（从上到下、从左到右）排列文本块；
> - 区分标题、正文、表格、图片。
>
> 页面元素：
> {elements_json}

### PPT 幻灯片结构

> 请分析以下 PPT 幻灯片内容，按位置顺序整理文本框、表格和图片，并总结每页核心观点。
>
> {slides_json}

## 注意事项

- 旧版 `.doc` 和 `.ppt` 格式不直接支持，请先转换为 `.docx` / `.pptx`。
- PDF 表格提取依赖 `pdfplumber`，复杂表格可能需要后处理校验。
- PDF 图片位置提取通过 `--extract-images` 开启，目前返回边界框；图片二进制导出可在此基础上扩展。
- 文本块默认按坐标排序，阅读顺序推断对简单版面效果较好，复杂版面可结合 LLM 进一步分析。
