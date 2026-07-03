---
name: cn-literature-search
description: 根据关键词检索中国国内期刊、论文、学位论文、专利、发明等学术/知识产权公开信息。底层使用 Playwright 访问百度学术、中国知网（CNKI）、万方数据、国家知识产权局等公开入口。当用户需要查找中文文献、期刊论文、国内专利或发明专利信息时使用本 skill。
---

# 中国国内文献/专利检索

## 能力范围

- 使用关键词同时检索多个国内公开数据源。
- 支持的检索类型：期刊论文、学位论文、会议论文、专利/发明专利。
- 数据源：
  - `baidu-xueshu`：百度学术（聚合）
  - `cnki`：中国知网（期刊/博硕士论文）
  - `wanfang`：万方数据（期刊/学位/专利）
  - `cnipa`：国家知识产权局（专利公布公告）

## 前置依赖

运行检索脚本需要 Python 3.9+ 与 Playwright。

```bash
cd cn-literature-search/scripts
pip install -r requirements.txt
playwright install chromium
```

> 首次执行 `playwright install chromium` 会下载 Chromium 浏览器，耗时取决于网络。

## 使用方法

### 1. 一键检索全部数据源

```bash
python scripts/search.py --keyword "人工智能" --output result.json
```

### 2. 指定数据源

```bash
python scripts/search.py --keyword "新能源电池" \
  --sources cnki cnipa \
  --limit 20 \
  --output battery.json
```

### 3. 调试用（显示浏览器窗口）

```bash
python scripts/search.py --keyword "量子计算" --headful
```

### 4. 复用登录状态（绕过验证码）

对于 CNKI、万方等需要登录/验证的站点，先使用 `save_auth_state.py` 在可视浏览器中完成登录并保存状态：

```bash
python scripts/save_auth_state.py --target cnki --output cnki_state.json
```

然后在检索时传入该状态文件：

```bash
python scripts/search.py --keyword "量子计算" \
  --sources cnki \
  --auth-state cnki_state.json \
  --output result.json
```

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--keyword` / `-k` | 检索关键词 | 必填 |
| `--sources` / `-s` | 数据源列表，空格分隔 | 全部 |
| `--limit` / `-l` | 每个数据源返回条数 | 10 |
| `--output` / `-o` | 输出 JSON 文件 | `search_result.json` |
| `--headful` | 是否显示浏览器窗口 | 否 |
| `--concurrency` / `-c` | 同时打开的数据源数量 | 2 |
| `--auth-state` | 已登录状态文件路径 | 无 |

## 输出格式

结果保存为 JSON，结构如下：

```json
{
  "keyword": "人工智能",
  "timestamp": "2026-07-02T18:30:00",
  "total": 25,
  "sources": [
    {
      "source": "baidu-xueshu",
      "status": "ok",
      "count": 10,
      "results": [
        {
          "title": "...",
          "authors": ["..."],
          "source": "期刊名",
          "date": "2024",
          "link": "https://...",
          "abstract": "...",
          "doi": "",
          "patent_no": "",
          "type": "论文/期刊"
        }
      ]
    }
  ]
}
```

当某个数据源触发验证码、登录拦截或解析失败时，`status` 为 `error`，`error` 字段会给出原因，其他数据源的结果仍然保留。

## 注意事项

- **百度学术、万方数据**：在常规网络下已可正常返回结果。
- **中国知网（CNKI）**：对当前 IP 常触发滑块验证码，建议在机构网络内运行，或使用 `--headful` 手动完成验证，亦可用 `save_auth_state.py` 保存登录状态后通过 `--auth-state` 复用。
- **国家知识产权局**：其专利检索域名（`epub.cnipa.gov.cn` / `pss-system.cponline.cnipa.gov.cn`）在部分网络环境下无法建立 HTTP 连接，如遇超时请更换网络或机构 IP。
- `--headful` 模式下若触发验证码，脚本会暂停并提示在浏览器窗口中完成验证，完成后返回终端按回车继续。
- 各站点 DOM 会不定期变化，解析器无法保证永久有效；遇到大量空结果时，先使用 `--headful` 人工确认页面结构。
- 本 skill 只抓取公开检索结果，不用于绕过付费全文下载。

## 扩展

新增数据源时，编辑 `scripts/search.py`：

1. 实现 `search_<source>(page, keyword, limit)` 和 `parse_<source>(page, limit)`。
2. 将 source 注册到 `SOURCE_HANDLERS` 字典。
3. 在 `references/sources.md` 中补充站点说明。
