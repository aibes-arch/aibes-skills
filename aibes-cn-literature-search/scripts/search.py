#!/usr/bin/env python3
"""
中国国内文献/专利聚合检索脚本（Playwright 驱动）。

支持的数据源：
- baidu-xueshu : 百度学术（期刊/论文聚合）
- cnki         : 中国知网（期刊/博硕士论文）
- wanfang      : 万方数据（期刊/学位论文/专利）
- cnipa        : 国家知识产权局（常规专利）

使用示例：
    python scripts/search.py --keyword "人工智能" --sources baidu-xueshu cnki --limit 10 --output result.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional
from urllib.parse import quote, urljoin

from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout


DEFAULT_TIMEOUT = 30_000  # 毫秒
DEFAULT_NAV_TIMEOUT = 60_000

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
"""


@dataclass
class SearchResult:
    title: str = ""
    authors: List[str] = field(default_factory=list)
    source: str = ""  # 期刊名 / 会议 / 数据库来源
    date: str = ""  # 发表/公开日期
    link: str = ""
    abstract: str = ""
    doi: str = ""
    patent_no: str = ""  # 专利号
    result_type: str = ""  # 论文/期刊/专利/学位论文

    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "authors": self.authors,
            "source": self.source,
            "date": self.date,
            "link": self.link,
            "abstract": self.abstract,
            "doi": self.doi,
            "patent_no": self.patent_no,
            "type": self.result_type,
        }


def _clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _safe_split_authors(text: Optional[str]) -> List[str]:
    text = _clean_text(text)
    if not text:
        return []
    authors = re.split(r"[,;，；]|\s{2,}", text)
    return [a.strip() for a in authors if a.strip()]


async def is_blocked(page: Page) -> bool:
    """检测当前页面是否为验证码/安全验证/错误页。"""
    try:
        title = await page.title()
    except Exception:
        title = ""
    url = page.url.lower()
    try:
        content = await page.content()
    except Exception:
        content = ""

    blocked_signals = [
        "安全验证" in title,
        "验证码" in title,
        "验证" in title and "verify" in url,
        "captcha" in url,
        "verify" in url,
        "content-error" in content,
        "访问受限" in content,
        "请完成验证" in content,
    ]
    return any(blocked_signals)


async def check_and_wait_if_blocked(page: Page, headful: bool) -> bool:
    """
    如果页面被拦截：
    - headful 模式：提示用户在浏览器中完成验证并按回车，返回 False（继续解析）。
    - headless 模式：返回 True（被拦截，应中断）。
    """
    if not await is_blocked(page):
        return False

    if headful:
        print(f"[WARN] {page.url} 触发验证/错误页面。请在浏览器窗口中完成验证后按回车继续...")
        try:
            input()
        except EOFError:
            pass
        return False
    return True


# ---------------------------------------------------------------------------
# 解析器：百度学术
# ---------------------------------------------------------------------------
async def parse_baidu_xueshu(page: Page, limit: int) -> List[SearchResult]:
    results: List[SearchResult] = []
    cards = await page.query_selector_all(".result")
    for card in cards[:limit]:
        try:
            title_el = await card.query_selector("h3.paper-title a, h3 a")
            title = await title_el.inner_text() if title_el else ""
            link = await title_el.get_attribute("href") if title_el else ""

            abstract_el = await card.query_selector(".paper-abstract")
            abstract = await abstract_el.inner_text() if abstract_el else ""

            type_el = await card.query_selector(".paper-type")
            result_type = await type_el.inner_text() if type_el else "论文/期刊"

            info_el = await card.query_selector(".paper-info")
            info_text = await info_el.inner_text() if info_el else ""

            author_els = await card.query_selector_all(".paper-info a[href*='author%3A']")
            authors = []
            for a in author_els:
                author_text = _clean_text(await a.inner_text())
                # 去掉作者名末尾的中英文逗号、省略号等
                author_text = re.sub(r"[,，、;；\.\s…]+$", "", author_text)
                if author_text and author_text not in authors:
                    authors.append(author_text)

            source_el = await card.query_selector(".paper-info a[href*='journal']")
            source = await source_el.inner_text() if source_el else ""

            date_match = re.search(r"(20\d{2}|19\d{2})", info_text)
            date = date_match.group(1) if date_match else ""

            results.append(
                SearchResult(
                    title=_clean_text(title),
                    authors=[_clean_text(a) for a in authors],
                    source=_clean_text(source),
                    date=date,
                    link=urljoin(page.url, link or ""),
                    abstract=_clean_text(abstract),
                    result_type=_clean_text(result_type) or "论文/期刊",
                )
            )
        except Exception:
            continue
    return results


async def search_baidu_xueshu(page: Page, keyword: str, limit: int, headful: bool) -> List[SearchResult]:
    # 先预热百度首页，降低被识别为机器流量的概率
    await page.goto("https://www.baidu.com", wait_until="domcontentloaded", timeout=DEFAULT_NAV_TIMEOUT)
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(1)

    url = f"https://xueshu.baidu.com/s?wd={quote(keyword)}"
    await page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_NAV_TIMEOUT)
    await page.wait_for_load_state("networkidle")
    if await check_and_wait_if_blocked(page, headful):
        return []
    return await parse_baidu_xueshu(page, limit)


# ---------------------------------------------------------------------------
# 解析器：中国知网（CNKI）
# ---------------------------------------------------------------------------
async def parse_cnki(page: Page, limit: int) -> List[SearchResult]:
    results: List[SearchResult] = []
    rows = await page.query_selector_all(".result-table-list tbody tr, .search-result-list .item")
    for row in rows[:limit]:
        try:
            title_el = await row.query_selector("a.title, .name a, td a.fz14")
            title = await title_el.inner_text() if title_el else ""
            link = await title_el.get_attribute("href") if title_el else ""

            authors_els = await row.query_selector_all(".author, td.author")
            authors = [await a.inner_text() for a in authors_els]

            source_el = await row.query_selector(".source, td.source")
            source = await source_el.inner_text() if source_el else ""

            date_el = await row.query_selector(".date, td.date")
            date = await date_el.inner_text() if date_el else ""

            type_el = await row.query_selector(".type, td.type")
            result_type = await type_el.inner_text() if type_el else "期刊/论文"

            results.append(
                SearchResult(
                    title=_clean_text(title),
                    authors=[_clean_text(a) for a in authors if a],
                    source=_clean_text(source),
                    date=_clean_text(date),
                    link=urljoin(page.url, link or ""),
                    result_type=_clean_text(result_type) or "期刊/论文",
                )
            )
        except Exception:
            continue
    return results


async def search_cnki(page: Page, keyword: str, limit: int, headful: bool) -> List[SearchResult]:
    url = (
        "https://kns.cnki.net/kns8/defaultresult/index?"
        "crossids=YSTT4HG0,LSTPFY1C,JUP3MUPD,MPMFIG1A,WQ0UVIAA,BLZOG7CK,"
        "EMRPGLPA,PWFIRAGL,NLBO1Z6R,NN3FJMUV&"
        f"kw={quote(keyword)}&korder=SU"
    )
    await page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_NAV_TIMEOUT)
    await page.wait_for_load_state("networkidle")
    try:
        await page.wait_for_selector(".result-table-list, .search-result-list", timeout=DEFAULT_TIMEOUT)
    except PlaywrightTimeout:
        pass
    if await check_and_wait_if_blocked(page, headful):
        return []
    return await parse_cnki(page, limit)


# ---------------------------------------------------------------------------
# 解析器：万方数据
# ---------------------------------------------------------------------------
async def parse_wanfang(page: Page, limit: int) -> List[SearchResult]:
    results: List[SearchResult] = []
    items = await page.query_selector_all(".normal-list")
    for item in items[:limit]:
        try:
            title_el = await item.query_selector(".title-area .title")
            title = await title_el.inner_text() if title_el else ""

            type_el = await item.query_selector(".author-area .essay-type")
            result_type = await type_el.inner_text() if type_el else "文献"

            source_el = await item.query_selector(".author-area .periodical-title")
            source = await source_el.inner_text() if source_el else ""

            info_el = await item.query_selector(".author-area")
            info_text = await info_el.inner_text() if info_el else ""

            # 作者与日期都混在 .authors 中，按是否包含“年”区分
            author_els = await item.query_selector_all(".author-area .authors")
            authors = []
            date = ""
            for a in author_els:
                text = _clean_text(await a.inner_text())
                if re.search(r"\d{4}\s*年", text):
                    date_match = re.search(r"(20\d{2}|19\d{2})", text)
                    if date_match:
                        date = date_match.group(1)
                elif text:
                    authors.append(text)

            # 若未从 .authors 提取到日期，再从整段 info_text 提取
            if not date:
                date_match = re.search(r"(20\d{2}|19\d{2})", info_text)
                date = date_match.group(1) if date_match else ""

            results.append(
                SearchResult(
                    title=_clean_text(title),
                    authors=authors,
                    source=_clean_text(source),
                    date=date,
                    link=page.url,
                    result_type=_clean_text(result_type) or "文献",
                )
            )
        except Exception:
            continue
    return results


async def search_wanfang(page: Page, keyword: str, limit: int, headful: bool) -> List[SearchResult]:
    # 从首页进入并模拟搜索，直接访问 searchList 容易被拦截
    await page.goto("https://www.wanfangdata.com.cn/", wait_until="domcontentloaded", timeout=DEFAULT_NAV_TIMEOUT)
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(2)

    input_sel = ".top-search-w input[type='text']"
    await page.fill(input_sel, keyword)
    await asyncio.sleep(0.5)
    btn_sel = ".top-search-w .search-buttons button"
    await page.click(btn_sel)
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(3)

    if await check_and_wait_if_blocked(page, headful):
        return []
    return await parse_wanfang(page, limit)


# ---------------------------------------------------------------------------
# 解析器：国家知识产权局（专利）
# ---------------------------------------------------------------------------
async def parse_cnipa(page: Page, limit: int) -> List[SearchResult]:
    results: List[SearchResult] = []
    rows = await page.query_selector_all(".content_listx li, .result-list li, table.biaoge tr")
    for row in rows[:limit]:
        try:
            title_el = await row.query_selector("a, .title")
            title = await title_el.inner_text() if title_el else ""
            link = await title_el.get_attribute("href") if title_el else ""

            text = await row.inner_text()
            patent_match = re.search(r"(?:申请号|公开号|专利号)[：:]\s*(CN\d+)", text)
            patent_no = patent_match.group(1) if patent_match else ""

            date_match = re.search(r"(\d{4}[\-\/]\d{1,2}[\-\/]\d{1,2})", text)
            date = date_match.group(1) if date_match else ""

            results.append(
                SearchResult(
                    title=_clean_text(title),
                    source="国家知识产权局",
                    date=date,
                    link=urljoin(page.url, link or ""),
                    patent_no=patent_no,
                    result_type="专利/发明",
                )
            )
        except Exception:
            continue
    return results


async def search_cnipa(page: Page, keyword: str, limit: int, headful: bool) -> List[SearchResult]:
    url = (
        "https://epub.cnipa.gov.cn/Sw/SwDetailsQuery?"
        f"strSources=fmgb,gwssxx,ymgb&strWhere=PI%3D%27{quote(keyword)}%27"
    )
    await page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_NAV_TIMEOUT)
    await page.wait_for_load_state("networkidle")
    try:
        await page.wait_for_selector(".content_listx, .result-list, table.biaoge", timeout=DEFAULT_TIMEOUT)
    except PlaywrightTimeout:
        pass
    if await check_and_wait_if_blocked(page, headful):
        return []
    return await parse_cnipa(page, limit)


# ---------------------------------------------------------------------------
# 解析器：Bing 公开网页检索（兜底）
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 调度
# ---------------------------------------------------------------------------
SOURCE_HANDLERS: Dict[str, Callable[[Page, str, int, bool], asyncio.Future]] = {
    "baidu-xueshu": search_baidu_xueshu,
    "cnki": search_cnki,
    "wanfang": search_wanfang,
    "cnipa": search_cnipa,
}

VALID_SOURCES = list(SOURCE_HANDLERS.keys())


async def search_one_source(
    browser,
    source: str,
    keyword: str,
    limit: int,
    headless: bool,
    auth_state: Optional[str] = None,
) -> Dict:
    context_kwargs: Dict = {
        "viewport": {"width": 1440, "height": 900},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
    }
    if auth_state:
        context_kwargs["storage_state"] = auth_state
    context = await browser.new_context(**context_kwargs)
    await context.add_init_script(STEALTH_SCRIPT)
    page = await context.new_page()
    page.set_default_timeout(DEFAULT_TIMEOUT)

    try:
        handler = SOURCE_HANDLERS[source]
        results = await handler(page, keyword, limit, headful=not headless)

        # 若结果为空且页面仍被拦截，给出明确错误
        if not results and await is_blocked(page):
            raise RuntimeError("页面被目标站点拦截（验证码/安全验证/错误页）。")

        return {
            "source": source,
            "status": "ok",
            "count": len(results),
            "results": [r.to_dict() for r in results],
        }
    except Exception as exc:
        return {
            "source": source,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "count": 0,
            "results": [],
        }
    finally:
        await context.close()


async def run_search(
    keyword: str,
    sources: List[str],
    limit: int,
    headless: bool,
    concurrency: int = 2,
    auth_state: Optional[str] = None,
) -> Dict:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        try:
            semaphore = asyncio.Semaphore(concurrency)

            async def _wrapped(source: str) -> Dict:
                async with semaphore:
                    return await search_one_source(browser, source, keyword, limit, headless, auth_state)

            tasks = [asyncio.create_task(_wrapped(s)) for s in sources]
            source_results = await asyncio.gather(*tasks)
        finally:
            await browser.close()

    return {
        "keyword": keyword,
        "timestamp": datetime.now().isoformat(),
        "sources": source_results,
        "total": sum(r["count"] for r in source_results),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="中国国内文献/专利聚合检索")
    parser.add_argument("--keyword", "-k", required=True, help="检索关键词")
    parser.add_argument(
        "--sources",
        "-s",
        nargs="+",
        choices=VALID_SOURCES,
        default=VALID_SOURCES,
        help="数据源列表",
    )
    parser.add_argument("--limit", "-l", type=int, default=10, help="每个数据源最多返回条数")
    parser.add_argument("--output", "-o", default="search_result.json", help="输出 JSON 文件路径")
    parser.add_argument("--headful", action="store_true", help="显示浏览器窗口（调试用，可手动过验证）")
    parser.add_argument("--concurrency", "-c", type=int, default=2, help="并发数")
    parser.add_argument(
        "--auth-state",
        default=None,
        help="已登录状态的 storage_state.json 路径，可绕过部分验证码",
    )
    args = parser.parse_args()

    result = asyncio.run(
        run_search(
            keyword=args.keyword,
            sources=args.sources,
            limit=args.limit,
            headless=not args.headful,
            concurrency=args.concurrency,
            auth_state=args.auth_state,
        )
    )

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"检索完成，共 {result['total']} 条结果，已保存至 {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
