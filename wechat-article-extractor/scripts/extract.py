#!/usr/bin/env python3
"""Extract a WeChat public account article to Markdown with images saved locally."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import markdownify
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

DEFAULT_TIMEOUT = 30_000
IMAGE_TIMEOUT = 30


def sanitize_filename(name: str, max_len: 80) -> str:
    """Make a string safe to use as a filename."""
    name = re.sub(r"[<>:/\\|?*\"'\n\r]+", "_", name).strip(" ._")
    if not name:
        name = "untitled"
    if len(name) > max_len:
        name = name[:max_len].rsplit("_", 1)[0]
    return name


def extract_title(page) -> str:
    """Extract article title from the rendered page."""
    # WeChat uses h2.rich_media_title with id activity_name
    selectors = [
        "h2.rich_media_title",
        "#activity_name",
        "h1.rich_media_title",
        "title",
    ]
    for selector in selectors:
        try:
            el = page.locator(selector).first
            if el.count() > 0:
                text = el.inner_text(timeout=5_000).strip()
                if text:
                    return text
        except Exception:
            continue
    return "untitled"


def extract_content_html(page) -> str:
    """Extract the article content HTML."""
    selectors = [
        "#js_content",
        ".rich_media_content",
    ]
    for selector in selectors:
        try:
            el = page.locator(selector).first
            if el.count() > 0:
                return el.inner_html(timeout=5_000)
        except Exception:
            continue
    return ""


def collect_image_urls(content_html: str) -> list[tuple[str, str]]:
    """Return (original_url, suggested_ext) pairs found in the content HTML."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(content_html, "html.parser")
    images: list[tuple[str, str]] = []
    seen = set()
    for img in soup.find_all("img"):
        url = img.get("data-src") or img.get("src") or ""
        url = url.strip()
        if not url or url.startswith("data:") or url in seen:
            continue
        seen.add(url)
        # Derive extension from URL or content-type later
        ext = Path(urlparse(url).path).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}:
            ext = ".jpg"
        images.append((url, ext))
    return images


def download_image(url: str, dest: Path, timeout: int = IMAGE_TIMEOUT) -> bool:
    """Download an image to dest, returning True on success."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://mp.weixin.qq.com/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return True
    except Exception:
        return False


def replace_image_urls(content_html: str, url_map: dict[str, str]) -> str:
    """Replace image src/data-src attributes with local relative paths."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(content_html, "html.parser")
    for img in soup.find_all("img"):
        for attr in ("data-src", "src"):
            url = img.get(attr)
            if url and url in url_map:
                img["src"] = url_map[url]
                if "data-src" in img.attrs:
                    del img.attrs["data-src"]
                break
    return str(soup)


def build_image_filename(url: str, ext: str, index: int) -> str:
    """Build a stable local filename for an image."""
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    return f"img_{index:04d}_{digest}{ext}"


def html_to_markdown(html: str, title: str) -> str:
    """Convert article HTML to Markdown."""
    md = markdownify.markdownify(
        html,
        heading_style="ATX",
        strip=["script", "style", "iframe"],
        autolinks=False,
    )
    md = md.strip()
    # Ensure title is at the top
    title_line = f"# {title}"
    if not md.startswith("# "):
        md = f"{title_line}\n\n{md}"
    return md


def extract_article(url: str, output_dir: Path, headful: bool = False, timeout: int = DEFAULT_TIMEOUT) -> Path:
    """Main entry point: fetch article and save as Markdown with local images."""
    if "mp.weixin.qq.com" not in url:
        raise ValueError(f"URL must contain 'mp.weixin.qq.com': {url}")

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headful)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        try:
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            # Wait for the content area to appear
            for selector in ("#js_content", ".rich_media_content"):
                try:
                    page.wait_for_selector(selector, timeout=timeout // 2)
                    break
                except PlaywrightTimeout:
                    continue
            # Give JS a moment to render lazy images
            time.sleep(1)
            title = extract_title(page)
            content_html = extract_content_html(page)
        finally:
            browser.close()

    if not content_html:
        raise RuntimeError("Could not locate article content (#js_content).")

    # Download images
    image_list = collect_image_urls(content_html)
    url_map: dict[str, str] = {}
    for idx, (img_url, ext) in enumerate(image_list, start=1):
        filename = build_image_filename(img_url, ext, idx)
        dest = images_dir / filename
        if download_image(img_url, dest):
            rel_path = f"./images/{filename}"
            url_map[img_url] = rel_path

    # Replace image URLs with local paths
    content_html = replace_image_urls(content_html, url_map)

    # Convert to Markdown
    md_content = html_to_markdown(content_html, title)

    # Save
    safe_title = sanitize_filename(title, max_len=80)
    md_path = output_dir / f"{safe_title}.md"
    counter = 1
    while md_path.exists():
        md_path = output_dir / f"{safe_title}_{counter}.md"
        counter += 1

    md_path.write_text(md_content, encoding="utf-8")
    return md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a WeChat article to Markdown.")
    parser.add_argument("--url", "-u", required=True, help="WeChat article URL containing mp.weixin.qq.com")
    parser.add_argument("--output-dir", "-o", default=".", help="Directory to save Markdown and images")
    parser.add_argument("--headful", action="store_true", help="Show browser window")
    parser.add_argument("--timeout", "-t", type=int, default=DEFAULT_TIMEOUT, help="Page load timeout in ms")
    args = parser.parse_args()

    try:
        md_path = extract_article(
            url=args.url,
            output_dir=Path(args.output_dir),
            headful=args.headful,
            timeout=args.timeout,
        )
        print(md_path)
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
