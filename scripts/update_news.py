# -*- coding: utf-8 -*-
"""
WorldPulse Daily —— 新闻自动更新脚本（B 同学负责）
====================================================

功能：RSS 获取 → 去重 → 时效过滤 → 三领域分类 → 中文翻译（可配置）
      → 地点匹配 → 透明规则热度评分 → 最多 20 条 → 输出 data/news.json

设计原则（与项目方案一致）：
  1. 优先单文件、初学者可读，不使用数据库或复杂后端；
  2. 翻译接口可配置，密钥只从环境变量读取，绝不写进代码或仓库；
  3. 翻译失败时回退显示英文原文（标题前加 [EN] 标记），绝不编造内容；
  4. 地点无法确认时输出 null 坐标，不在地图上乱放点；
  5. RSS 全部失败或结果过少时，保留最后一次有效数据（不覆盖旧 JSON）。

运行方法：
    cd WorldPulse-Daily
    python3 scripts/update_news.py

本地测试环境准备：
    pip3 install -r requirements.txt
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from html import unescape
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import feedparser

# ============================================================
# 一、配置区（初学者只需要改这里）
# ============================================================

# 项目根目录（脚本在 scripts/ 下，根目录是它的上一级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS_JSON_PATH = os.path.join(BASE_DIR, "data", "news.json")
LOCATIONS_JSON_PATH = os.path.join(BASE_DIR, "data", "locations.json")

# RSS 新闻源（已实测可用；如需更换，先用浏览器打开链接确认能访问）
RSS_SOURCES = [
    {"name": "NPR World",       "url": "https://feeds.npr.org/1004/rss.xml",   "score": 20},
    {"name": "NPR Business",    "url": "https://feeds.npr.org/1006/rss.xml",   "score": 18},
    {"name": "MarketWatch Top", "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories", "score": 20},
]

# 三领域分类关键词词典（英文小写；命中次数最多的类别获胜）
CATEGORY_KEYWORDS = {
    # 地缘冲突 geopolitics
    "geopolitics": [
        "war", "military", "missile", "strike", "strikes", "conflict", "ceasefire",
        "attack", "attacks", "troops", "drone", "drones", "killed", "clashes",
        "invasion", "bombing", "airstrike", "airstrikes", "weapon", "weapons",
        "rebel", "militant", "militants", "fighting", "offensive", "nuclear",
        "hostage", "hostages", "gunmen", "explosion", "shelling",
    ],
    # 国际政治 politics
    "politics": [
        "election", "elections", "president", "prime minister", "government",
        "parliament", "minister", "diplomat", "diplomacy", "summit", "treaty",
        "talks", "protest", "protests", "policy", "vote", "cabinet", "senate",
        "congress", "impeach", "sanctions", "trade deal", "diplomatic",
        "election commission", "referendum", "coup",
    ],
    # 金融市场 markets
    "markets": [
        "stock", "stocks", "market", "markets", "economy", "inflation",
        "interest rate", "interest rates", "fed", "federal reserve", "bank",
        "banking", "dollar", "gdp", "tariff", "tariffs", "earnings", "shares",
        "bonds", "investors", "recession", "currency", "crypto", "bitcoin",
        "oil prices", "wall street", "nasdaq", "dow", "s&p", "ipo", "merger",
    ],
}

# 翻译配置：
#   TRANSLATE_PROVIDER 环境变量决定用哪个服务：
#     none     —— 不翻译（最快，全部显示英文，用于调试）
#     mymemory —— MyMemory 免费接口（无需密钥，但每天有次数限制）
#     deepl    —— DeepL 官方 API（需要 TRANSLATE_API_KEY）
#   未设置时默认尝试 mymemory。
TRANSLATE_PROVIDER = os.environ.get("TRANSLATE_PROVIDER", "mymemory").lower()
TRANSLATE_API_KEY = os.environ.get("TRANSLATE_API_KEY", "")  # 只从环境变量读，禁止写进代码

# 时效过滤与输出数量
MAX_HOURS = 48          # 只保留最近 48 小时的新闻
RELAX_HOURS = 24 * 7    # 如果 48 小时内不足 MIN_NEWS 条，放宽到 7 天
MIN_NEWS = 8            # 放宽阈值
MAX_NEWS = 20           # 最多输出 20 条
MIN_VALID_TO_WRITE = 3  # 少于 3 条有效新闻就视为异常，不覆盖旧数据

# 请求超时与礼貌间隔（秒），避免被新闻源封禁
REQUEST_INTERVAL = 1.0

# ============================================================
# 二、工具函数
# ============================================================

def log(step, msg):
    """带步骤号的中文日志，方便在 GitHub Actions 里看运行过程。"""
    print(f"[{step}] {msg}", flush=True)


def strip_html(text):
    """去掉 RSS 摘要里的 HTML 标签和多余空白。"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_url(url):
    """URL 规范化：去掉查询参数中的跟踪字段并排序，用于去重。"""
    try:
        p = urlparse(url.strip())
        keep = [(k, v) for k, v in parse_qsl(p.query)
                if k not in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")]
        return urlunparse((p.scheme, p.netloc.lower(), p.path, "", urlencode(sorted(keep)), ""))
    except Exception:
        return url.strip()


def normalize_title(title):
    """标题规范化（去多余空白、统一小写），作为去重的辅助手段。"""
    return re.sub(r"\s+", " ", strip_html(title)).lower()


def entry_time_utc(entry):
    """把 RSS 条目的发布时间统一转成 UTC datetime；缺失时按'现在'处理。"""
    for key in ("published_parsed", "updated_parsed"):
        t = getattr(entry, key, None)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def fetch_url_with_timeout(url, timeout=20):
    """带超时的抓取（feedparser 自带的请求没有超时，会卡死，所以自己抓）。"""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "WorldPulseDaily/1.0 (+educational project)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ============================================================
# 三、流水线各步骤
# ============================================================

def step1_fetch():
    """获取：从所有 RSS 源抓取新闻，返回原始条目列表。"""
    all_raw = []
    ok_sources = 0
    for src in RSS_SOURCES:
        try:
            log("获取", f"正在读取 {src['name']} ...")
            raw = fetch_url_with_timeout(src["url"])
            parsed = feedparser.parse(raw)
            if not parsed.entries:
                log("获取", f"⚠ {src['name']} 返回 0 条（可能是网络或源故障）")
            else:
                ok_sources += 1
                log("获取", f"✓ {src['name']} 取得 {len(parsed.entries)} 条")
                for e in parsed.entries:
                    all_raw.append({
                        "source": src["name"],
                        "source_score": src["score"],
                        "title": strip_html(e.get("title", "")),
                        "summary": strip_html(e.get("summary", ""))[:300],  # 只要短摘要
                        "url": e.get("link", ""),
                        "published_at": entry_time_utc(e),
                    })
            time.sleep(REQUEST_INTERVAL)  # 礼貌间隔
        except Exception as ex:
            log("获取", f"✗ {src['name']} 抓取失败：{ex}")
            time.sleep(REQUEST_INTERVAL)
    log("获取", f"共取得原始新闻 {len(all_raw)} 条，可用源 {ok_sources}/{len(RSS_SOURCES)}")
    return all_raw, ok_sources


def step2_dedup(items):
    """去重：以规范化 URL 为主、标题为辅。"""
    seen_urls, seen_titles, result = set(), set(), []
    for it in items:
        nu, nt = normalize_url(it["url"]), normalize_title(it["title"])
        if nu and nu in seen_urls:
            continue
        if nt and nt in seen_titles:
            continue
        if nu:
            seen_urls.add(nu)
        if nt:
            seen_titles.add(nt)
        result.append(it)
    log("去重", f"{len(items)} 条 → {len(result)} 条（去掉 {len(items) - len(result)} 条重复）")
    return result


def step3_filter_by_time(items, now):
    """时效过滤：默认只保留最近 48 小时；不足 MIN_NEWS 条时自动放宽到 7 天。"""
    def within(items_, hours):
        return [i for i in items_ if (now - i["published_at"]) <= timedelta(hours=hours)]

    fresh = within(items, MAX_HOURS)
    if len(fresh) >= MIN_NEWS:
        log("过滤", f"保留最近 {MAX_HOURS} 小时新闻：{len(fresh)} 条")
        return fresh
    relaxed = within(items, RELAX_HOURS)
    log("过滤", f"最近 {MAX_HOURS} 小时仅 {len(fresh)} 条（不足 {MIN_NEWS}），放宽到 {RELAX_HOURS} 小时：{len(relaxed)} 条")
    return relaxed


def step4_classify(items):
    """分类：统计标题+摘要中各领域关键词命中次数，取最高者；全 0 则丢弃。"""
    result = []
    stats = {"geopolitics": 0, "politics": 0, "markets": 0, "dropped": 0}
    for it in items:
        text = (it["title"] + " " + it["summary"]).lower()
        scores = {}
        for cat, words in CATEGORY_KEYWORDS.items():
            hits = 0
            for w in words:
                # 用词边界匹配，避免 bank 命中 banking 这类误报
                hits += len(re.findall(r"\b" + re.escape(w) + r"\b", text))
            scores[cat] = hits
        best = max(scores, key=scores.get)
        if scores[best] == 0:
            stats["dropped"] += 1
            continue
        it["category"] = best
        it["category_hits"] = scores[best]
        stats[best] += 1
        result.append(it)
    log("分类", f"保留 {len(result)} 条（地缘冲突 {stats['geopolitics']}｜国际政治 {stats['politics']}｜金融市场 {stats['markets']}），"
               f"不属于三领域丢弃 {stats['dropped']} 条")
    return result


def translate_text(text, provider):
    """翻译单条文本。返回 (译文, 是否成功)。失败返回原文。"""
    if not text:
        return text, True
    try:
        if provider == "mymemory":
            import urllib.request, urllib.parse
            q = urllib.parse.quote(text[:450])
            url = (f"https://api.mymemory.translated.net/get?q={q}&langpair=en|zh-CN"
                   + (f"&de={TRANSLATE_API_KEY}" if TRANSLATE_API_KEY else ""))
            raw = json.loads(fetch_url_with_timeout(url, timeout=15))
            out = (raw.get("responseData") or {}).get("translatedText", "")
            # MyMemory 配额耗尽时会把警告文本当结果返回，要识别并视为失败
            if raw.get("responseStatus") in (200, "200") and out and "MYMEMORY WARNING" not in out:
                return out.strip(), True
            return text, False
        if provider == "deepl" and TRANSLATE_API_KEY:
            import urllib.request
            body = json.dumps({"text": [text[:450]],
                               "target_lang": "ZH"}).encode("utf-8")
            req = urllib.request.Request(
                "https://api-free.deepl.com/v2/translate", data=body,
                headers={"Authorization": f"DeepL-Auth-Key {TRANSLATE_API_KEY}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                out = json.loads(resp.read())["translations"][0]["text"]
            return out.strip(), True
    except Exception:
        pass
    return text, False


def step5_translate(items):
    """翻译标题与短摘要；失败回退英文原文（标题前加 [EN] 标记）。"""
    if TRANSLATE_PROVIDER == "none":
        log("翻译", "TRANSLATE_PROVIDER=none，跳过翻译，全部保留英文原文")
        for it in items:
            it["title_cn"] = "[EN] " + it["title"]
            it["summary_cn"] = it["summary"]
        return items

    ok = fail = 0
    for it in items:
        t, ok1 = translate_text(it["title"], TRANSLATE_PROVIDER)
        s, ok2 = translate_text(it["summary"], TRANSLATE_PROVIDER)
        if ok1:
            it["title_cn"] = t
            ok += 1
        else:
            it["title_cn"] = "[EN] " + it["title"]  # 回退：保留英文原文并打标记
            fail += 1
        it["summary_cn"] = s if ok2 else it["summary"]
        time.sleep(0.3)  # 免费接口限速
    log("翻译", f"翻译成功 {ok} 条，回退英文 {fail} 条（标记为 [EN]）")
    return items


def step6_locate(items):
    """定位：用本地地名词典匹配国家；匹配不到就输出 null，不放地图点。"""
    try:
        with open(LOCATIONS_JSON_PATH, "r", encoding="utf-8") as f:
            locs = json.load(f)["locations"]
    except Exception as ex:
        log("定位", f"⚠ 读取 locations.json 失败：{ex}，全部输出 null 坐标")
        locs = []

    located = 0
    for it in items:
        text = (it["title"] + " " + it["summary"]).lower()
        country, lat, lng = None, None, None
        for loc in locs:
            for alias in loc["aliases"]:
                # 词典里带空格/标点的别名（如 "united states"）直接子串匹配；
                # 单词别名用词边界匹配，避免 india 命中 indianapolis 这类误报
                if " " in alias or alias.endswith((".", " ")) or alias.startswith(" "):
                    matched = alias in text
                else:
                    matched = re.search(r"\b" + re.escape(alias.strip()) + r"\b", text) is not None
                if matched:
                    country, lat, lng = loc["name"], loc["lat"], loc["lng"]
                    break
            if country:
                break
        it["country"], it["lat"], it["lng"] = country, lat, lng
        if country:
            located += 1
    log("定位", f"{len(items)} 条中 {located} 条匹配到地点，其余 {len(items) - located} 条坐标为 null（不上地图）")
    return items


def step7_heat(items, now):
    """热度评分（透明规则，0-100）：
         新鲜度   0-50 分：48 小时内线性衰减（越新分越高）
         主题相关 0-20 分：分类关键词命中数 × 4，封顶 20
         地理定位 0-10 分：有可信坐标 +10
         来源基础 0-20 分：每个源固定分（NPR/MarketWatch 主源分高）
       这是'编辑规则热度'，不是全网真实搜索热度。
    """
    for it in items:
        age_h = max(0.0, (now - it["published_at"]).total_seconds() / 3600)
        fresh = 50 * max(0.0, 1 - age_h / MAX_HOURS)
        topic = min(20, it["category_hits"] * 4)
        geo = 10 if it["lat"] is not None else 0
        it["heat"] = int(round(min(100, fresh + topic + geo + it["source_score"])))
    items.sort(key=lambda x: (-x["heat"], -x["published_at"].timestamp()))
    return items


def step8_output(items, now):
    """输出：按协议生成 data/news.json（原子写入，失败不会留下半截文件）。"""
    news_list = []
    for i, it in enumerate(items[:MAX_NEWS], start=1):
        news_list.append({
            "id": f"news-{i:03d}",
            "title": it["title_cn"],
            "summary": it["summary_cn"],
            "category": it["category"],
            "country": it["country"],
            "lat": it["lat"],
            "lng": it["lng"],
            "published_at": it["published_at"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": it["source"],
            "url": it["url"],
            "heat": it["heat"],
        })
    payload = {"updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "news": news_list}

    os.makedirs(os.path.dirname(NEWS_JSON_PATH), exist_ok=True)
    tmp = NEWS_JSON_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, NEWS_JSON_PATH)  # 原子替换：要么成功，要么旧文件原封不动
    log("输出", f"已写入 {NEWS_JSON_PATH}（{len(news_list)} 条新闻）")
    return payload


def keep_old_data(reason):
    """异常保护：本次运行失败，保留最后一次有效数据。"""
    if os.path.exists(NEWS_JSON_PATH):
        with open(NEWS_JSON_PATH, "r", encoding="utf-8") as f:
            old = json.load(f)
        log("保护", f"{reason}。保留旧数据（{len(old.get('news', []))} 条，更新于 {old.get('updated_at')}）")
    else:
        log("保护", f"{reason}。注意：尚无旧数据可保留，data/news.json 不存在。")


# ============================================================
# 四、主流程
# ============================================================

def main():
    print("=" * 60)
    print("WorldPulse Daily 新闻更新流水线启动")
    print("=" * 60)
    now = datetime.now(timezone.utc)

    # 1. 获取
    raw_items, ok_sources = step1_fetch()
    if ok_sources == 0 or not raw_items:
        keep_old_data("所有 RSS 源都不可用")
        sys.exit(2)  # 非零退出码：告诉 GitHub Actions 本次失败，不发布

    # 2~3. 去重 + 时效过滤
    items = step3_filter_by_time(step2_dedup(raw_items), now)
    if not items:
        keep_old_data("过滤后没有符合条件的新闻")
        sys.exit(2)

    # 4. 分类
    items = step4_classify(items)
    if not items:
        keep_old_data("没有新闻落入三个分类领域")
        sys.exit(2)

    # 5~6. 翻译 + 定位
    items = step6_locate(step5_translate(items))

    # 7~8. 评分 + 输出
    items = step7_heat(items, now)
    if len(items) < MIN_VALID_TO_WRITE:
        keep_old_data(f"有效新闻不足 {MIN_VALID_TO_WRITE} 条（只有 {len(items)} 条）")
        sys.exit(2)

    payload = step8_output(items, now)

    # 结果预览（方便本地检查和答辩演示）
    print("-" * 60)
    for n in payload["news"][:5]:
        print(f"  heat={n['heat']:>3} [{n['category']:<11}] {n['title'][:45]}")
    print("-" * 60)
    print("本次更新完成。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        keep_old_data(f"发生未预期错误：{e}")
        raise
