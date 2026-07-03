---
name: wechat-article-extractor
description: 提取微信公众号（mp.weixin.qq.com）文章并保存为 Markdown，同时将文章内图片下载到本地并在 Markdown 中引用本地路径。当用户给出微信公众号文章链接并要求保存/导出/下载文章内容时使用本 skill。
---

# 微信公众号文章提取

## 能力范围

- 验证输入 URL 包含 `mp.weixin.qq.com`。
- 使用 Playwright 渲染文章页面。
- 提取准确的文章标题和正文内容。
- 将正文转换为 Markdown。
- 下载文章中的所有图片到本地 `images/` 目录。
- 在 Markdown 中使用相对路径引用本地图片。
- 返回生成的 Markdown 文件本地路径。

## 前置依赖

运行提取脚本需要 Python 3.9+。

```bash
cd wechat-article-extractor/scripts
pip install -r requirements.txt
playwright install chromium
```

> 首次执行 `playwright install chromium` 会下载 Chromium 浏览器，耗时取决于网络。

## 使用方法

### 1. 提取文章

```bash
python scripts/extract.py --url "https://mp.weixin.qq.com/s/..." --output-dir ./output
```

脚本会打印生成的 Markdown 文件路径，例如：

```
E:\aibes-skills\wechat-article-extractor\scripts\output\文章标题.md
```

### 2. 可视模式（调试）

```bash
python scripts/extract.py --url "https://mp.weixin.qq.com/s/..." --output-dir ./output --headful
```

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--url` / `-u` | 微信公众号文章 URL（必须包含 mp.weixin.qq.com） | 必填 |
| `--output-dir` / `-o` | 输出目录，Markdown 和图片会保存在此 | 当前目录 |
| `--headful` | 是否显示浏览器窗口 | 否 |
| `--timeout` / `-t` | 页面加载超时时间（毫秒） | 30000 |

## 输出结构

```
<output-dir>/
├── 文章标题.md
└── images/
    ├── img_0001_xxx.jpg
    ├── img_0002_xxx.png
    └── ...
```

Markdown 中的图片以相对路径引用：

```markdown
![描述](./images/img_0001_xxx.jpg)
```

## 实现说明

- 标题优先从 `h2.rich_media_title` / `#activity_name` 提取，回退到 `<title>`。
- 正文优先从 `#js_content` / `.rich_media_content` 提取。
- 图片地址优先读取 `data-src`（微信懒加载真实地址），回退到 `src`。
- 下载失败的图片保留原始 URL，不会中断流程。
- 文章标题会经过清理后作为 Markdown 文件名；若已存在则自动添加序号。
- 部分公众号文章会启用字体混淆（反爬），此时 Playwright 读取到的中文字符可能显示为乱码。本脚本未引入 OCR，优先直接读取 DOM 文本；如遇到乱码，可尝试 `--headful` 人工确认页面结构，或改用支持字体反爬的专用工具。

## 扩展

编辑 `scripts/extract.py`：

1. `extract_title(page)`：调整标题选择器。
2. `extract_content_html(page)`：调整正文选择器。
3. `html_to_markdown()`：调整 Markdown 转换选项。
