"""
Monitor + rule matching + draft generator.

Sources:
- file_html: local HTML
- http_html: GET a URL and parse by selectors
- http_html_search: GET search_url_template with {query}
- browser_search: use undetected-chromedriver to search
- search_engine: DuckDuckGo with optional site filter (zhihu/csdn/tieba/reddit)
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import List, Dict, Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except Exception:
    uc = None  # optional; only needed for browser_search


def log(msg: str) -> None:
    print(msg, flush=True)


def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_events_with_selectors(html: str, cfg: Dict[str, Any], source_name: str) -> List[Dict[str, Any]]:
    sel = cfg.get("selectors", {})
    soup = BeautifulSoup(html, "html.parser")
    container_sel = sel.get("container", "article")
    title_sel = sel.get("title", "h2")
    content_sel = sel.get("content", "p")
    link_sel = sel.get("link", "a")
    id_attr = sel.get("id_attr", "data-id")
    created_attr = sel.get("created_at_attr", "data-created-at")
    lang_attr = sel.get("lang_attr", "data-lang")

    events: List[Dict[str, Any]] = []
    containers = soup.select(container_sel)
    for idx, c in enumerate(containers, 1):
        event_id = c.get(id_attr) or f"{source_name}_{idx}"
        title_tag = c.select_one(title_sel)
        content_tag = c.select_one(content_sel)
        link_tag = c.select_one(link_sel)
        events.append(
            {
                "id": event_id,
                "source": source_name,
                "url": link_tag["href"] if link_tag and link_tag.has_attr("href") else "",
                "title": title_tag.get_text(strip=True) if title_tag else "",
                "content": content_tag.get_text(strip=True) if content_tag else "",
                "created_at": c.get(created_attr, ""),
                "lang": c.get(lang_attr, "en"),
                "metadata": {},
            }
        )
    return events


def parse_events_from_html(html_path: Path, source_name: str = "sample_forum") -> List[Dict[str, Any]]:
    html = html_path.read_text(encoding="utf-8")
    return parse_events_with_selectors(html, {"selectors": {}}, source_name=source_name)


def rule_matches(event: Dict[str, Any], rule: Dict[str, Any]) -> bool:
    conditions = rule.get("conditions", [])
    text_fields = {
        "title": event.get("title", "").lower(),
        "content": event.get("content", "").lower(),
        "source": event.get("source", "").lower(),
    }
    for cond in conditions:
        ctype = cond.get("type")
        field = cond.get("field", "")
        value = cond.get("value", "")
        values = cond.get("values", [])
        text = text_fields.get(field, "").lower()

        if ctype == "contains":
            if value.lower() not in text:
                return False
        elif ctype == "contains_any":
            if not any(v.lower() in text for v in values):
                return False
        elif ctype == "equals":
            if text != value.lower():
                return False
        elif ctype == "not_contains_any":
            if any(v.lower() in text for v in values):
                return False
        else:
            return False
    return True


def generate_draft(event: Dict[str, Any], rule: Dict[str, Any], templates: Dict[str, str]) -> Dict[str, Any]:
    template_id = rule.get("template")
    tpl = templates.get(template_id, "Hello, saw your post '{title}'.")
    draft_text = tpl.format(
        title=event.get("title", ""),
        content=event.get("content", ""),
        url=event.get("url", ""),
        source=event.get("source", ""),
    )
    return {
        "event_id": event["id"],
        "rule_id": rule.get("id"),
        "lang": rule.get("target_lang", event.get("lang", "en")),
        "draft_text": draft_text,
    }


def browser_search_fetch(source_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    if uc is None:
        raise ImportError("undetected-chromedriver/selenium not available; install to use browser_search.")
    search_url = source_cfg.get("search_page_url", "")
    if not search_url:
        log("[browser_search] 缺少 search_page_url，跳过浏览器搜索")
        return []
    queries = source_cfg.get("queries", [])
    sel = source_cfg.get("selectors", {})
    input_sel = sel.get("search_input")
    submit_sel = sel.get("search_button")
    wait_selector = sel.get("wait_for", "body")
    user_data_dir = source_cfg.get("user_data_dir")
    profile_directory = source_cfg.get("profile_directory")
    wait_login = source_cfg.get("wait_login", False)
    events: List[Dict[str, Any]] = []

    options = uc.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # 复用本地已登录的 Chrome 配置，避免重复登录
    if user_data_dir:
        options.add_argument(f"--user-data-dir={user_data_dir}")
    if profile_directory:
        options.add_argument(f"--profile-directory={profile_directory}")
    driver = uc.Chrome(options=options, use_subprocess=False)
    try:
        login_prompted = False
        for q in queries:
            url = search_url.format(query=q) if "{query}" in search_url else search_url
            driver.get(url)
            if wait_login and not login_prompted:
                log("[browser_search] 已打开浏览器，请在窗口内登录/验证后，回到终端按 Enter 继续...")
                try:
                    input()
                except Exception:
                    pass
                login_prompted = True
            # 如果提供搜索框选择器，则尝试输入；否则直接用带 query 的 URL
            if input_sel:
                try:
                    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, input_sel)))
                    inp = driver.find_element(By.CSS_SELECTOR, input_sel)
                    inp.clear()
                    inp.send_keys(q)
                    if submit_sel:
                        driver.find_element(By.CSS_SELECTOR, submit_sel).click()
                    else:
                        inp.submit()
                except Exception as e:
                    log(f"[browser_search] 未找到搜索框，直接使用带参数的 URL。错误: {e}")
            try:
                WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector)))
            except Exception as e:
                log(f"[browser_search] 等待结果元素超时，继续。错误: {e}")
            time.sleep(2)
            html = driver.page_source
            evs = parse_events_with_selectors(html, source_cfg, source_name=source_cfg.get("name", "browser_source"))
            for ev in evs:
                ev["metadata"]["query"] = q
            events.extend(evs)
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return events


def duckduckgo_search_fetch(queries: List[str], site: str = "duckduckgo", max_results: int = 10) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    domain_map = {
        "duckduckgo": None,
        "zhihu": "zhihu.com",
        "csdn": "csdn.net",
        "tieba": "tieba.baidu.com",
        "reddit": "reddit.com",
    }
    domain = domain_map.get(site)
    for q in queries:
        full_q = f"site:{domain} {q}" if domain else q
        log(f"[搜索引擎] DuckDuckGo 查询[{site}]: {full_q}")
        try:
            resp = requests.get(
                "https://duckduckgo.com/html/",
                params={"q": full_q, "kl": "cn-zh", "kad": "zh_CN"},
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            results = soup.select("div.result")
            if not results:
                results = soup.select("td.result-link")
            results = results[:max_results]
            for idx, r in enumerate(results, 1):
                a = r.select_one("a.result__a") or r.select_one("a")
                snippet = r.select_one("a.result__snippet") or r.select_one("div.result__snippet") or r.select_one("td.result-snippet")
                title = a.get_text(strip=True) if a else ""
                link = a["href"] if a and a.has_attr("href") else ""
                content = snippet.get_text(strip=True) if snippet else ""
                events.append(
                    {
                        "id": f"{site}_{q}_{idx}",
                        "source": site,
                        "url": link,
                        "title": title,
                        "content": content,
                        "created_at": "",
                        "lang": "en",
                        "metadata": {"query": q},
                    }
                )
            log(f"[搜索引擎] 查询“{full_q}”解析到结果: {len(results)} 条")
        except Exception as e:
            log(f"[搜索引擎] 查询“{full_q}”失败，跳过。错误: {e}")
    return events


def apply_site_defaults(source_cfg: Dict[str, Any], site: str) -> bool:
    """Fill in search_page_url and selectors for browser_search based on site.
    Returns True if filled, False if no defaults available.
    """
    defaults = {
        "zhihu": {
            "search_page_url": "https://www.zhihu.com/search?q={query}",
            "selectors": {
                "container": "div.Card.SearchResult",
                "title": ".ContentItem-title",
                "content": ".RichContent-inner",
                "link": ".ContentItem-title a",
                "id_attr": "data-id",
                "created_at_attr": "",
                "lang_attr": "",
                "search_input": "input.SearchBar-input",
                "search_button": "",
                "wait_for": ".Card.SearchResult",
            },
        },
        "csdn": {
            "search_page_url": "https://so.csdn.net/so/search?q={query}",
            "selectors": {
                "container": "div.result-item",
                "title": ".result-title",
                "content": ".result-desc",
                "link": ".result-title a",
                "id_attr": "data-id",
                "created_at_attr": "",
                "lang_attr": "",
                "search_input": "input#keyword",
                "search_button": "button[type='submit']",
                "wait_for": "div.result-item",
            },
        },
        "tieba": {
            "search_page_url": "https://tieba.baidu.com/f?ie=utf-8&kw={query}",
            "selectors": {
                "container": "div.threadlist_li_right",
                "title": "a.j_th_tit",
                "content": "div.threadlist_abs",
                "link": "a.j_th_tit",
                "id_attr": "data-tid",
                "created_at_attr": "",
                "lang_attr": "",
                "search_input": "input.tbui_aside_search_input",
                "search_button": "a.search_btn",
                "wait_for": "div.threadlist_li_right",
            },
        },
        "reddit": {
            "search_page_url": "https://www.reddit.com/search/?q={query}",
            "selectors": {
                "container": "div.Search__results article",
                "title": "h3",
                "content": "div[data-click-id='body']",
                "link": "a[data-click-id='body']",
                "id_attr": "",
                "created_at_attr": "",
                "lang_attr": "",
                "search_input": "input#header-search-bar",
                "search_button": "",
                "wait_for": "div.Search__results article",
            },
        },
    }
    if site in defaults:
        cfg = defaults[site]
        source_cfg["search_page_url"] = cfg["search_page_url"]
        source_cfg["selectors"] = cfg["selectors"]
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description="Monitor + match + draft generator (prototype)")
    parser.add_argument("--config", required=True, help="Path to config JSON")
    parser.add_argument("--output", default="drafts_output.json", help="Where to write drafts JSON")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    language = cfg.get("language", "en")
    rules = cfg.get("rules", [])
    templates = cfg.get("templates", {})
    repeat = cfg.get("repeat", False)
    interval = cfg.get("interval_seconds", 900)
    max_cycles = cfg.get("max_cycles", 1)
    min_matches = cfg.get("min_matches", 0)

    cycle = 0
    while True:
        cycle += 1
        source_cfg = cfg["source"]
        source_type = source_cfg["type"]

        if source_type == "file_html":
            source_path = Path(source_cfg["path"])
            log(f"[来源:file_html] 读取本地文件 {source_path}")
            events = parse_events_from_html(source_path, source_name=source_cfg.get("name", "sample_forum"))
        elif source_type == "http_html":
            url = source_cfg["url"]
            log(f"[来源:http_html] 请求 {url}")
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            html = resp.text
            events = parse_events_with_selectors(html, source_cfg, source_name=source_cfg.get("name", "http_source"))
        elif source_type == "http_html_search":
            template = source_cfg["search_url_template"]
            queries = source_cfg.get("queries", [])
            events = []
            for q in queries:
                url = template.format(query=q)
                log(f"[来源:http_html_search] 关键词“{q}” -> {url}")
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                html = resp.text
                evs = parse_events_with_selectors(html, source_cfg, source_name=source_cfg.get("name", "search_source"))
                for ev in evs:
                    ev["metadata"]["query"] = q
                events.extend(evs)
            log(f"[来源:http_html_search] 解析到事件总数: {len(events)}")
        elif source_type == "browser_search":
            log("[来源:browser_search] 启动浏览器执行搜索")
            events = browser_search_fetch(source_cfg)
        elif source_type == "search_engine":
            engine = source_cfg.get("engine", "duckduckgo")
            queries = source_cfg.get("queries", [])
            site = source_cfg.get("site", "duckduckgo")
            if engine == "duckduckgo":
                events = duckduckgo_search_fetch(queries, site=site, max_results=source_cfg.get("max_results", 10))
                log(f"[来源:search_engine] 聚合事件总数: {len(events)}")
            elif engine == "browser":
                log(f"[来源:search_engine/browser] 通过浏览器搜索站点 {site}")
                filled = apply_site_defaults(source_cfg, site)
                if not filled or not source_cfg.get("search_page_url"):
                    log(f"[来源:search_engine/browser] 无站点 {site} 配置，回退到 DuckDuckGo")
                    events = duckduckgo_search_fetch(queries, site="duckduckgo", max_results=source_cfg.get("max_results", 10))
                    log(f"[来源:search_engine] 聚合事件总数: {len(events)}")
                else:
                    events = browser_search_fetch(source_cfg)
            else:
                raise ValueError(f"Unsupported search_engine engine: {engine}")
        else:
            raise ValueError(f"Unsupported source type: {source_type}")

        drafts: List[Dict[str, Any]] = []
        events_brief: List[Dict[str, Any]] = []
        matched_events = 0
        for ev in events:
            # 简单过滤：剔除机构/工具域名，优先保留帖子/问答
            url = ev.get("url", "")
            parsed = urlparse(url if url.startswith("http") else "http://" + url)
            host = parsed.netloc.lower()
            path = parsed.path.lower()
            blacklist = [
                "acabridge.cn",
                "editsprings.com",
                "xueshut.com",
                "xueshulin.com",
                "100xuexi.com",
                "xueshubang.org",
                "163.com",
                "paperqq.cn",
                "papernex.cn",
                "paperface.cn",
                "paperbert.com",
                "csdnimg.cn",
                "sohu.com",
                "qq.com",
            ]
            if any(bad in host for bad in blacklist):
                continue
            # 只保留疑似问答/帖子链接
            keep_patterns = ["/question", "/p/", "/r/", "/tieba.baidu.com/p", "thread"]
            title_text = (ev.get("title", "") or "").lower()
            want_words = ["求助", "帮忙", "怎么办", "怎么写", "question", "help", "降重"]
            if not any(pat in path for pat in keep_patterns) and not any(w.lower() in title_text for w in want_words):
                continue

            events_brief.append(
                {
                    "id": ev.get("id", ""),
                    "source": ev.get("source", ""),
                    "title": ev.get("title", ""),
                    "url": ev.get("url", ""),
                    "content": ev.get("content", ""),
                    "metadata": ev.get("metadata", {}),
                }
            )
            for rule in rules:
                if not rule.get("enabled", True):
                    continue
                if rule_matches(ev, rule):
                    matched_events += 1
                    draft = generate_draft(ev, rule, templates)
                    drafts.append(draft)

        output_path = Path(args.output)
        output_data = {
            "language": language,
            "cycle": cycle,
            "total_events": len(events),
            "matched_events": matched_events,
            "events": events_brief,
            "drafts": drafts,
        }
        output_path.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8")
        status = "[OK]" if matched_events >= min_matches else "[警告]"
        log(f"{status} 第 {cycle} 轮: 事件数={len(events)}, 命中={matched_events}, 输出={output_path}")

        if not repeat or cycle >= max_cycles:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
