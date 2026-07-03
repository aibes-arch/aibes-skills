---
name: document-to-markdown
description: 将 Word (.docx)、PDF (.pdf)、PowerPoint (.pptx)、Excel (.xlsx) 等文档转换为 Markdown。底层使用 python-docx、PyMuPDF、python-pptx、openpyxl，并支持通过 pandoc 作为通用回退。当用户要求将文档转成 Markdown、把文件内容提取为 md、批量转换文档时使用本 skill。
---

# 文档转 Markdown

## 能力范围

- 支持 .docx、.pdf、.pptx、.xlsx 等常见办公文档。
- 自动识别输入是单个文件还是整个目录。
- 批量转换目录内所有支持的文档。
- 提取 .docx 内嵌图片到本地 `images/` 目录并在 Markdown 中引用相对路径。
- 对不支持的格式，若系统已安装 pandoc，则尝试通过 pypandoc 回退转换。

## 前置依赖

需要 Python 3.9+。

```bash
cd document-to-markdown/scripts
pip install -r requirements.txt
```

可选（作为通用回退）：

```bash
# Windows: https://pandoc.org/installing.html
pandoc --version
```

## 使用方法

### 1. 转换单个文件

```bash
python scripts/convert.py path/to/document.docx -o output.md
```

### 2. 批量转换目录

```bash
python scripts/convert.py path/to/documents/ -o ./markdown-output/
```

### 3. 不指定输出路径

```bash
python scripts/convert.py report.pdf
# 生成 report.md
```

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `input` | 输入文件或目录 | 必填 |
| `-o` / `--output` | 输出 Markdown 文件或目录 | 与输入同名/同目录 |
| `--page-separator` | PDF/PPT 页面/幻灯片之间的分隔符 | `"\n\n---\n\n"` |

## 输出结构

单个文件：

```text
output.md
images/          # 仅 docx 且包含图片时
└── image_0001.png
```

批量目录：

```text
markdown-output/
├── doc1.md
├── doc2.md
└── images/
    └── image_0001.png
```

## 注意事项

- 旧版 Word .doc 格式、OpenDocument .odt 等未内置直接支持，但可通过 pandoc 回退转换。
- PDF 为扫描版、图片型或没有正确嵌入 ToUnicode 字体映射时，文本层提取可能乱码或为空；如需 OCR，请先用 OCR 工具生成可搜索 PDF。
- 复杂排版（多栏、表格合并单元格、复杂图文混排）转换后可能需要人工校对。
- 批量转换时会跳过不支持的文件并打印错误，继续处理其余文件。

## 扩展

编辑 `scripts/convert.py`：

1. `convert_docx()`：调整 docx 标题/列表/表格/图片转换规则。
2. `convert_pdf()`：调整页面提取模式或启用 OCR 集成。
3. `convert_pptx()`：调整每页文本结构或提取备注。
4. `convert_xlsx()`：调整表格输出格式。
