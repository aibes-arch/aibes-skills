---
name: table-processing
description: 表格处理通用 skill，支持 Excel/CSV/HTML 表格解析、表头识别、结构化转换。适用于用户要求将表格文件转成 JSON/CSV/Markdown、识别表头、批量处理 Excel 多工作表或 HTML 多表格、查看表格结构的场景。基于 pandas + openpyxl + BeautifulSoup 确定性执行。
---

# 表格处理

## 能力范围

1. **表格解析**：支持 `.xlsx`、`.xls`、`.csv`、`.tsv`、`.html`、`.htm`。
2. **表头识别**：自动检测、首行作为表头、无表头、指定行作为表头。
3. **结构化转换**：输出为 JSON、CSV、Markdown、Python records。
4. **批量处理**：自动处理 Excel 多工作表、HTML 多表格。
5. **结构检查**：快速查看文件中有哪些表格及各自的行列数。

## 前置依赖

需要 Python 3.9+。

```bash
cd table-processing/scripts
pip install -r requirements.txt
```

## 使用方法

### 1. 解析并转换表格

```bash
# Excel → JSON
python scripts/table_process.py convert data.xlsx -o data.json

# CSV → Markdown
python scripts/table_process.py convert data.csv --format markdown -o data.md

# HTML（多表格）→ JSON
python scripts/table_process.py convert page.html --format json -o tables.json

# 指定 Excel 工作表
python scripts/table_process.py convert data.xlsx --sheet Sheet1 --sheet Sheet2 -o data.json
```

### 2. 表头模式

```bash
# 自动识别表头（默认）
python scripts/table_process.py convert data.csv -o data.json

# 强制第一行作为表头
python scripts/table_process.py convert data.csv --header first -o data.json

# 指定第 2 行作为表头（0-based 索引为 1）
python scripts/table_process.py convert data.csv --header row --header-row 1 -o data.json

# 无表头，自动生成 col_0, col_1 ...
python scripts/table_process.py convert data.csv --header none -o data.json
```

### 3. 查看表格结构

```bash
python scripts/table_process.py inspect data.xlsx -o structure.json
```

输出示例：

```json
[
  {"source": "data.xlsx", "rows": 100, "columns": 5, "sheet": "Sheet1"},
  {"source": "data.xlsx", "rows": 50, "columns": 3, "sheet": "Sheet2"}
]
```

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `input` | 输入文件路径 | 必填 |
| `-o` / `--output` | 输出文件路径 | stdout |
| `--format` | 输出格式：`json` / `csv` / `markdown` / `python` | `json` |
| `--header` | 表头模式：`auto` / `first` / `none` / `row` | `auto` |
| `--header-row` | `--header row` 时的表头行索引 | 无 |
| `--sheet` | Excel 工作表，可多次指定 | 全部 |
| `--encoding` | CSV/HTML 编码 | `utf-8` |
| `--delimiter` | CSV 分隔符 | 自动推断 |
| `--orient` | JSON 输出结构：`records` / `index` / `columns` | `records` |

## 输出格式

### JSON

```json
{
  "source": "data.xlsx",
  "sheet": "Sheet1",
  "shape": [100, 5],
  "columns": ["姓名", "年龄", "城市"],
  "data": [
    {"姓名": "张三", "年龄": 28, "城市": "北京"}
  ]
}
```

### CSV

单表直接输出 CSV；多表时会在文件名后追加 `_Sheet1`、`_0` 等后缀分别保存。

### Markdown

多表时每个表格用二级标题分隔。

## 对话内直接使用

如果用户直接在对话中粘贴表格内容，可直接用 pandas 思维或提示词处理。

### 表头识别提示词

> 下面是表格数据。请判断第一行是否为表头，如果是则使用第一行作为列名；否则生成 col_0, col_1 等列名。将结果以 JSON 数组形式返回。
>
> {table_text}

### 表格转 Markdown

> 请将以下表格转换为 Markdown 表格格式：
>
> {table_text}

## 注意事项

- 自动表头检测使用启发式规则：首行全为字符串、互不相同、非纯数字时视为表头。
- HTML 文件可能包含非表格元素，脚本使用 pandas `read_html` 提取所有 `<table>`。
- 复杂表头（多行合并单元格）建议先用 `--header row` 指定，或用 `--header none` 后由 Kimi 进一步处理。
- 输出 JSON 前会清理全空行和全空列。
