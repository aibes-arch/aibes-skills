#!/usr/bin/env python3
"""
表格处理统一 CLI：解析 Excel/CSV/HTML 表格、识别表头、转换为 JSON/CSV/Markdown。

基于 pandas + openpyxl + BeautifulSoup，所有解析与转换均为确定性执行，
不依赖 LLM。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List, Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

import pandas as pd


SUPPORTED_EXCEL = {".xlsx", ".xls", ".xlsm", ".xlsb"}
SUPPORTED_CSV = {".csv", ".tsv"}
SUPPORTED_HTML = {".html", ".htm"}


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def read_text(path: Optional[str]) -> str:
    if path is None or path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def write_text(path: Optional[str], content: str) -> None:
    if path is None or path == "-":
        sys.stdout.write(content)
        if not content.endswith("\n"):
            sys.stdout.write("\n")
    else:
        Path(path).write_text(content, encoding="utf-8")


def write_json(path: Optional[str], data: Any) -> None:
    content = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    write_text(path, content)


# ---------------------------------------------------------------------------
# Header detection
# ---------------------------------------------------------------------------

def looks_like_header(row: pd.Series) -> bool:
    """启发式判断一行是否为表头。"""
    values = [v for v in row if pd.notna(v)]
    if not values:
        return False

    # 表头通常全为字符串，且互不相同
    string_ratio = sum(1 for v in values if isinstance(v, str)) / len(values)
    if string_ratio < 0.8:
        return False

    unique_values = [str(v).strip() for v in values]
    if len(set(unique_values)) < len(unique_values):
        return False

    # 表头单元格通常不为纯数字
    numeric_count = sum(
        1 for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)
    )
    if numeric_count / len(values) > 0.5:
        return False

    return True


def detect_header(df: pd.DataFrame) -> pd.DataFrame:
    """自动检测并设置表头；若无法识别则生成 col_0, col_1 ..."""
    if df.empty:
        df.columns = [f"col_{i}" for i in range(len(df.columns))]
        return df

    if looks_like_header(df.iloc[0]):
        headers = [str(v).strip() if pd.notna(v) else f"col_{i}" for i, v in enumerate(df.iloc[0])]
        df = df.iloc[1:].reset_index(drop=True)
        df.columns = headers
    else:
        df.columns = [f"col_{i}" for i in range(len(df.columns))]

    return df


def apply_header_mode(df: pd.DataFrame, mode: str, header_row: Optional[int] = None) -> pd.DataFrame:
    """根据表头模式处理 DataFrame。"""
    if mode == "auto":
        return detect_header(df)
    if mode == "none":
        df.columns = [f"col_{i}" for i in range(len(df.columns))]
        return df
    if mode == "first":
        headers = [str(v).strip() if pd.notna(v) else f"col_{i}" for i, v in enumerate(df.iloc[0])]
        df = df.iloc[1:].reset_index(drop=True)
        df.columns = headers
        return df
    if mode == "row" and header_row is not None:
        if header_row >= len(df):
            raise ValueError(f"表头行索引 {header_row} 超出数据范围")
        headers = [str(v).strip() if pd.notna(v) else f"col_{i}" for i, v in enumerate(df.iloc[header_row])]
        df = df.iloc[header_row + 1 :].reset_index(drop=True)
        df.columns = headers
        return df
    raise ValueError(f"不支持的表头模式: {mode}")


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_excel(path: str, sheets: Optional[List[str]]) -> List[dict]:
    xl = pd.ExcelFile(path)
    sheet_names = sheets if sheets else xl.sheet_names
    results = []
    for sheet in sheet_names:
        if sheet not in xl.sheet_names:
            raise ValueError(f"Excel 中不存在工作表: {sheet}")
        df = pd.read_excel(path, sheet_name=sheet, header=None, dtype=object)
        results.append({"source": path, "sheet": sheet, "dataframe": df})
    return results


def parse_csv(path: str, delimiter: Optional[str], encoding: str) -> List[dict]:
    kwargs: dict = {"header": None, "encoding": encoding, "dtype": object}
    if delimiter:
        kwargs["sep"] = delimiter
    df = pd.read_csv(path, **kwargs)
    return [{"source": path, "sheet": None, "dataframe": df}]


def parse_html(path: str) -> List[dict]:
    tables = pd.read_html(path, header=None)
    return [
        {"source": path, "table_index": i, "dataframe": df}
        for i, df in enumerate(tables)
    ]


def load_tables(path: str, args: argparse.Namespace) -> List[dict]:
    ext = Path(path).suffix.lower()
    if ext in SUPPORTED_EXCEL:
        return parse_excel(path, args.sheet)
    if ext in SUPPORTED_CSV:
        return parse_csv(path, args.delimiter, args.encoding)
    if ext in SUPPORTED_HTML:
        return parse_html(path)
    raise ValueError(f"不支持的文件格式: {ext}")


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------

def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """清理 DataFrame：去除全空行/列、转换 NaN。"""
    df = df.dropna(how="all").dropna(axis=1, how="all")
    return df.reset_index(drop=True)


def convert_to_json(df: pd.DataFrame, orient: str = "records") -> Any:
    return df.to_dict(orient=orient)


def convert_to_csv(df: pd.DataFrame, args: argparse.Namespace) -> str:
    sep = args.delimiter if args.delimiter else ","
    return df.to_csv(index=False, sep=sep, encoding="utf-8")


def convert_to_markdown(df: pd.DataFrame) -> str:
    try:
        return df.to_markdown(index=False)
    except Exception:
        # fallback to simple markdown table
        lines = []
        lines.append("| " + " | ".join(str(c) for c in df.columns) + " |")
        lines.append("| " + " | ".join(["---"] * len(df.columns)) + " |")
        for _, row in df.iterrows():
            lines.append("| " + " | ".join(str(v) for v in row) + " |")
        return "\n".join(lines)


def convert_table(item: dict, args: argparse.Namespace) -> dict:
    df = item["dataframe"]
    df = clean_dataframe(df)
    df = apply_header_mode(df, args.header, args.header_row)

    result = {
        "source": item["source"],
        "shape": [int(df.shape[0]), int(df.shape[1])],
        "columns": list(df.columns),
    }

    if "sheet" in item:
        result["sheet"] = item["sheet"]
    if "table_index" in item:
        result["table_index"] = item["table_index"]

    if args.format == "json":
        result["data"] = convert_to_json(df, args.orient)
    elif args.format == "csv":
        result["data"] = convert_to_csv(df, args)
    elif args.format == "markdown":
        result["data"] = convert_to_markdown(df)
    elif args.format == "python":
        result["data"] = convert_to_json(df, "records")
    else:
        raise ValueError(f"不支持的输出格式: {args.format}")

    return result


# ---------------------------------------------------------------------------
# CLI handlers
# ---------------------------------------------------------------------------

def cmd_convert(args: argparse.Namespace) -> None:
    path = args.input
    if not Path(path).exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    tables = load_tables(path, args)
    results = [convert_table(t, args) for t in tables]

    if args.format == "csv":
        # CSV 只支持单表；多表时分别输出
        if len(results) == 1:
            write_text(args.output, results[0]["data"])
        else:
            output_path = Path(args.output) if args.output != "-" else None
            for r in results:
                suffix = f"_{r.get('sheet', r.get('table_index', 0))}"
                if output_path:
                    out = output_path.with_stem(output_path.stem + suffix)
                    out.write_text(r["data"], encoding="utf-8")
                else:
                    sys.stdout.write(f"# Table: {suffix.lstrip('_')}\n")
                    sys.stdout.write(r["data"])
                    sys.stdout.write("\n")
    elif args.format in ("json", "python"):
        if len(results) == 1:
            write_json(args.output, results[0])
        else:
            write_json(args.output, results)
    elif args.format == "markdown":
        parts = []
        for r in results:
            title = r.get("sheet") if r.get("sheet") is not None else f"Table {r.get('table_index', 0)}"
            parts.append(f"## {title}\n\n{r['data']}")
        write_text(args.output, "\n\n".join(parts))


def cmd_inspect(args: argparse.Namespace) -> None:
    """检查文件中的所有表格结构（工作表/表格索引、形状）。"""
    path = args.input
    if not Path(path).exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    tables = load_tables(path, args)
    summary = []
    for t in tables:
        df = clean_dataframe(t["dataframe"])
        item = {
            "source": t["source"],
            "rows": int(df.shape[0]),
            "columns": int(df.shape[1]),
        }
        if "sheet" in t:
            item["sheet"] = t["sheet"]
        if "table_index" in t:
            item["table_index"] = t["table_index"]
        summary.append(item)

    write_json(args.output, summary)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="table_process.py",
        description="表格处理工具：解析 Excel/CSV/HTML，识别表头，转换格式。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # convert
    p_convert = subparsers.add_parser("convert", help="解析并转换表格")
    p_convert.add_argument("input", help="输入文件路径（.xlsx/.xls/.csv/.html/.htm）")
    p_convert.add_argument("-o", "--output", default="-", help="输出文件路径，默认 stdout")
    p_convert.add_argument(
        "--format",
        choices=["json", "csv", "markdown", "python"],
        default="json",
        help="输出格式",
    )
    p_convert.add_argument(
        "--header",
        choices=["auto", "first", "none", "row"],
        default="auto",
        help="表头识别模式：auto 自动，first 首行，none 无表头，row 指定行",
    )
    p_convert.add_argument("--header-row", type=int, default=None, help="--header row 时的表头行索引（0-based）")
    p_convert.add_argument("--sheet", action="append", help="Excel 工作表名称，可多次指定；默认全部")
    p_convert.add_argument("--encoding", default="utf-8", help="CSV 文件编码")
    p_convert.add_argument("--delimiter", default=None, help="CSV 分隔符，默认自动推断")
    p_convert.add_argument("--orient", choices=["records", "index", "columns"], default="records", help="JSON 输出格式")
    p_convert.set_defaults(func=cmd_convert)

    # inspect
    p_inspect = subparsers.add_parser("inspect", help="查看文件中的表格结构")
    p_inspect.add_argument("input", help="输入文件路径")
    p_inspect.add_argument("-o", "--output", default="-", help="输出文件路径")
    p_inspect.add_argument("--sheet", action="append", help="Excel 工作表名称")
    p_inspect.add_argument("--encoding", default="utf-8")
    p_inspect.add_argument("--delimiter", default=None)
    p_inspect.set_defaults(func=cmd_inspect)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
