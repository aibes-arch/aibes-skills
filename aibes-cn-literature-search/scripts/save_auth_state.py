#!/usr/bin/env python3
"""
登录状态保存工具。

部分数据源（如 CNKI、万方）在机构网络外会触发验证码或登录拦截。
使用本脚本在可视浏览器中完成登录后，将 Cookie/LocalStorage 保存为 JSON，
后续 search.py 通过 --auth-state 复用该状态，可大幅提升成功率。

使用示例：
    python scripts/save_auth_state.py --target cnki --output cnki_state.json
"""

import argparse
import asyncio
import sys

from playwright.async_api import async_playwright


LOGIN_URLS = {
    "cnki": "https://kns.cnki.net/kns8/defaultresult/index",
    "wanfang": "https://www.wanfangdata.com.cn/",
    "baidu-xueshu": "https://xueshu.baidu.com/",
}


async def main() -> int:
    parser = argparse.ArgumentParser(description="保存目标站点登录状态")
    parser.add_argument(
        "--target",
        "-t",
        choices=list(LOGIN_URLS.keys()),
        required=True,
        help="要登录的目标站点",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="auth_state.json",
        help="保存的 storage_state 文件路径",
    )
    args = parser.parse_args()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        await page.goto(LOGIN_URLS[args.target], timeout=60_000)
        print(
            f"已打开 {args.target} 登录页面。请在浏览器窗口中完成登录/验证，"
            "完成后返回本终端按回车键保存状态。"
        )
        try:
            input()
        except EOFError:
            pass

        await context.storage_state(path=args.output)
        await browser.close()

    print(f"登录状态已保存至 {args.output}")
    print(f"后续检索可添加参数：--auth-state {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
