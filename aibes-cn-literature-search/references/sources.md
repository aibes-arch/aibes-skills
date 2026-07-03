# 数据源说明

本 skill 目前聚合以下四个国内公开检索入口。各站点反爬策略、登录要求不同，脚本在失败时会返回 `error` 字段，便于上层处理。

## 百度学术 `baidu-xueshu`

- 入口：https://xueshu.baidu.com
- 特点：中文期刊/会议/学位论文聚合，结果加载快。
- 限制：部分结果只展示摘要片段，全文链接可能跳转到第三方付费库。
- 适用：快速摸底、关键词覆盖。
- 实测：常规网络下可正常返回结果。

## 中国知网 `cnki`

- 入口：https://kns.cnki.net
- 特点：国内最大学术期刊、博硕士论文库。
- 限制：未登录/非机构 IP 常触发滑块验证码；频繁请求会被拦截。
- 建议：在校园网/机构 IP 内使用，或通过 `save_auth_state.py` + `--auth-state` 复用已验证状态。

## 万方数据 `wanfang`

- 入口：https://www.wanfangdata.com.cn
- 特点：期刊、学位论文、专利、标准均有覆盖。
- 限制：搜索结果页为动态渲染，直接访问 `/search/searchList` 可能被拦截，脚本改为从首页模拟搜索后跳转。
- 实测：常规网络下可正常返回结果。

## 国家知识产权局 `cnipa`

- 入口：https://epub.cnipa.gov.cn（公布公告查询）
- 特点：官方专利、发明专利公开信息。
- 限制：专利检索子域名在部分网络环境下 HTTP 连接超时；主站 `https://www.cnipa.gov.cn/` 通常可访问。

## 登录状态复用

CNKI、万方、百度学术在部分网络环境下会触发登录/验证码。skill 提供 `scripts/save_auth_state.py`：

```bash
python scripts/save_auth_state.py --target cnki --output cnki_state.json
```

运行后在可视浏览器中完成登录，返回终端按回车保存 Cookie/LocalStorage。检索时传入：

```bash
python scripts/search.py --keyword "..." --sources cnki --auth-state cnki_state.json
```

## 扩展建议

- 对反爬严格的站点，可降低 `concurrency`，增加页面间随机延迟。
- 新增数据源时，在 `scripts/search.py` 中注册 `SOURCE_HANDLERS` 并补充解析器即可。
