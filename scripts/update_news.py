# -*- coding: utf-8 -*-
"""
WorldPulse Daily —— 新闻自动更新脚本（B 同学负责）
====================================================

功能：RSS 获取 → 去重 → 时效过滤 → 三领域分类 → 地点匹配 → 热度评分
      → 配额挑选 20 条 → 中文翻译 → 输出 data/news.json
      → 同时生成：历史归档 data/archive/、当日概览 data/digest.json、运行日志 data/logs/

设计原则（与项目方案一致）：
  1. 优先单文件、初学者可读，不使用数据库或复杂后端；
  2. 翻译接口可配置，密钥只从环境变量读取，绝不写进代码或仓库；
  3. 翻译失败时回退显示英文原文（标题前加 [EN] 标记），绝不编造内容；
     翻译整体失败比例过高时，保留上一次有效数据，不覆盖成"整期英文"；
  4. 地点无法确认时输出 null 坐标，不在地图上乱放点；
  5. RSS 全部失败或结果过少时，保留最后一次有效数据（不覆盖旧 JSON）；
  6. 每条新闻的 id 由原文 URL 哈希生成，跨天稳定，不会因为排名变化而指向别的新闻；
  7. 归档、概览、日志任一环节失败都不影响 data/news.json 的生成（互不阻塞）。

运行方法：
    cd WorldPulse-Daily
    python3 scripts/update_news.py

本地测试环境准备：
    pip3 install -r requirements.txt
"""

import hashlib
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

# —— 本轮新增：归档 / 概览 / 日志 的输出位置 ——
DATA_DIR = os.path.join(BASE_DIR, "data")
ARCHIVE_DIR = os.path.join(DATA_DIR, "archive")          # 每日归档目录
ARCHIVE_INDEX_PATH = os.path.join(ARCHIVE_DIR, "index.json")   # 归档索引（前端读这个拿日期列表）
DIGEST_JSON_PATH = os.path.join(DATA_DIR, "digest.json")       # 当日概览摘要
LOGS_DIR = os.path.join(DATA_DIR, "logs")                # 运行日志目录

# 北京时间（归档按北京日期分文件夹，跟"日报"的产品定位一致）
BEIJING_TZ = timezone(timedelta(hours=8))

# 归档保留天数：超过这个天数的归档会被清理，避免仓库无限变大
ARCHIVE_KEEP_DAYS = 90
# 运行日志保留份数
LOG_KEEP_FILES = 30

# RSS 新闻源（已实测可用；如需更换，先用浏览器打开链接确认能访问）
# score 是"来源基础分"，会算进热度（0~20），权威/主源给高分
# 注意：单个 NPR 频道只吐 10 条，所以要多挂几个频道才凑得够 20 条
RSS_SOURCES = [
    # —— 地缘冲突 / 国际政治主力 ——
    {"name": "NPR World",       "url": "https://feeds.npr.org/1004/rss.xml",   "score": 20},
    {"name": "NPR Politics",    "url": "https://feeds.npr.org/1014/rss.xml",   "score": 18},
    {"name": "NPR Business",    "url": "https://feeds.npr.org/1006/rss.xml",   "score": 18},
    # —— 金融市场主力 ——
    {"name": "MarketWatch Top", "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories", "score": 20},
    {"name": "MarketWatch Markets", "url": "https://feeds.content.dowjones.io/public/rss/mw_marketpulse", "score": 16},
    {"name": "CNBC World News", "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362", "score": 17},
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
        "migrants", "migrant", "immigration", "lawmakers", "legislation",
        "lawsuit", "court", "governor", "mayor", "united nations", "nato",
        "eu leaders", "state department", "white house",
    ],
    # 金融市场 markets
    # （investing / economics / billion 等是后来补的：原先词典漏了它们，
    #   导致"SpaceX 千亿投资热潮""诺贝尔经济学奖"这类财经新闻被误杀）
    "markets": [
        "stock", "stocks", "market", "markets", "economy", "economic",
        "economics", "inflation",
        "interest rate", "interest rates", "fed", "federal reserve", "bank",
        "banking", "dollar", "gdp", "tariff", "tariffs", "earnings", "shares",
        "bonds", "investors", "investor", "investing", "invest", "investment",
        "recession", "currency", "crypto", "bitcoin",
        "oil prices", "wall street", "nasdaq", "dow", "s&p", "ipo", "merger",
        "billion", "trillion", "outlook", "forecast", "revenue", "profit",
        "quarterly", "portfolio", "financial", "financially", "fund", "funds",
        "unemployment", "jobless", "rate cut", "treasury", "yields", "stake",
    ],
}

# 翻译配置：
#   TRANSLATE_PROVIDER 环境变量决定主用哪个服务：
#     none     —— 不翻译（最快，全部显示英文，用于调试）
#     mymemory —— MyMemory 免费接口（无需密钥，但每天有次数限制）
#     deepl    —— DeepL 官方 API（需要 TRANSLATE_API_KEY）
#   未设置时默认尝试 mymemory。
#
#   【故障转移】主服务返回"配额用尽"这类全局性错误时，自动切到 TRANSLATE_FALLBACKS
#   里的备用源继续翻，而不是让整期标题都变 [EN]。这是对 B3 的补强：
#   B3 解决的是"翻译全挂时不要用英文覆盖线上中文数据"，
#   这里解决的是"翻译还没全挂、只是这一个源用完了"时仍然能拿到中文。
TRANSLATE_PROVIDER = os.environ.get("TRANSLATE_PROVIDER", "mymemory").lower()
TRANSLATE_API_KEY = os.environ.get("TRANSLATE_API_KEY", "")  # 只从环境变量读，禁止写进代码
# 备用源按顺序尝试；gtx 是 Google 网页版翻译的公开端点，无需密钥。
# 不保证长期可用，所以只作为兜底，不设成默认。
TRANSLATE_FALLBACKS = [p.strip().lower() for p in
                       os.environ.get("TRANSLATE_FALLBACKS", "gtx").split(",") if p.strip()]

# 翻译失败比例阈值：标题翻译失败率超过这个值，视为翻译服务整体异常，
# 本次不覆盖 news.json，保留上一次有效数据（见 B3）
TRANSLATE_FAIL_RATIO_LIMIT = 0.30

# 时效过滤与输出数量
MAX_HOURS = 48          # 只保留最近 48 小时的新闻
RELAX_HOURS = 24 * 7    # 如果 48 小时内不足 MIN_NEWS 条，放宽到 7 天
MIN_NEWS = 8            # 放宽阈值
MAX_NEWS = 20           # 最多输出 20 条
MIN_VALID_TO_WRITE = 3  # 少于 3 条有效新闻就视为异常，不覆盖旧数据

# 三领域配额（软配额）：先给每个领域各留够名额，剩下的再按热度补位。
# 这么做的原因：财经源（MarketWatch / CNBC）每次吐的条目远多于政治源，
# 纯按热度排会让首页被财经新闻刷屏，地图上也只剩美国一个点。
# 某领域当天确实没那么多新闻时，名额自动让给其他领域，不会硬凑。
TARGET_NEWS = 20
CATEGORY_QUOTA = {"geopolitics": 5, "politics": 7, "markets": 8}

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


def make_stable_id(url):
    """【B1】由原文 URL 生成稳定 id：sha1 前 12 位十六进制。

    为什么不用序号（news-001 这种）：
      序号是"排名"的副产品，每天重排一次。今天排第 3 的新闻明天排到第 8，
      但 news-003 这个 id 没变，于是 id 指向了另一条完全不同的新闻。
      归档、热度对比、收藏、已读标记全都依赖"同一个 id 永远指同一条新闻"。

    用 URL 哈希的好处：同一条新闻无论排第几、哪天被抓到，id 都完全一致。
    先做 normalize_url 规范化（去掉 utm 等跟踪参数），避免同一篇文章因
    不同来源的跟踪参数不同而算出两个 id。
    """
    key = normalize_url(url) or url or ""
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def now_beijing():
    """当前北京时间（归档按北京日期命名，与"日报"的产品语义一致）。"""
    return datetime.now(BEIJING_TZ)


def write_json_atomic(path, payload):
    """原子写入 JSON：先写 .tmp 再替换。

    好处：写到一半出错时，目标文件要么是旧的、要么是新的，绝不会是半截损坏的。
    前端最怕的就是读到损坏的 JSON（整页白屏）。
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_json_safe(path, default=None):
    """读 JSON，失败返回 default（不抛异常，用于容错）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


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


def _translate_one(text, provider):
    """调一个具体服务翻译一段文本。

    返回 (译文, 状态)：
      ("中文", "ok")        成功
      ("", "quota")        该服务配额用尽 / 被限流 —— 是**服务级**故障，
                           继续用它只会让整期都变英文，应换源
      ("", "fail")         单条失败（网络抖动、文本过长等），不影响其他条
    """
    if not text:
        return text, "ok"
    try:
        if provider == "mymemory":
            import urllib.parse
            q = urllib.parse.quote(text[:450])
            url = (f"https://api.mymemory.translated.net/get?q={q}&langpair=en|zh-CN"
                   + (f"&de={TRANSLATE_API_KEY}" if TRANSLATE_API_KEY else ""))
            raw = json.loads(fetch_url_with_timeout(url, timeout=15))
            out = (raw.get("responseData") or {}).get("translatedText", "") or ""
            status = raw.get("responseStatus")
            # 配额耗尽时 MyMemory 把警告文本当译文返回，状态码 429，必须识别出来
            if "MYMEMORY WARNING" in out or str(status) == "429":
                return "", "quota"
            if str(status) in ("200", "200.0") and out:
                return out.strip(), "ok"
            return "", "fail"
        if provider == "gtx":
            # Google 网页版翻译的公开端点，无需密钥；返回嵌套数组，拼起来就是译文
            import urllib.parse
            q = urllib.parse.quote(text[:450])
            url = ("https://translate.googleapis.com/translate_a/single"
                   f"?client=gtx&sl=en&tl=zh-CN&dt=t&q={q}")
            raw = json.loads(fetch_url_with_timeout(url, timeout=15))
            out = "".join(seg[0] for seg in raw[0] if seg and seg[0])
            return (out.strip(), "ok") if out.strip() else ("", "fail")
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
            return out.strip(), "ok"
    except Exception as e:
        # 403/456 这类也可能是配额，但无法可靠区分，统一按单条失败处理，
        # 由调用方的失败率阈值兜底，不会因为一次网络抖动就误判服务挂掉。
        if "429" in str(e) or "456" in str(e):
            return "", "quota"
    return "", "fail"


# 当前生效的翻译源（可能因为配额切到备用源），供日志和 stats 记录
_active_provider = {"name": TRANSLATE_PROVIDER, "switched": False}


def translate_text(text, provider):
    """翻译单条文本。返回 (译文, 是否成功)。失败返回原文。

    主源报"配额用尽"时自动切到备用源，并记住切换结果，后续条目直接用新源。
    """
    out, status = _translate_one(text, provider)
    if status == "ok":
        return out, True

    if status == "quota" and not _active_provider["switched"]:
        for alt in TRANSLATE_FALLBACKS:
            if alt == provider:
                continue
            probe, st = _translate_one(text, alt)
            if st == "ok":
                log("翻译", f"主源 {provider} 配额用尽，自动切换到备用源 {alt}")
                _active_provider.update(name=alt, switched=True)
                TRANSLATE_FALLBACKS.insert(0, provider)  # 下次优先试回主源
                return probe, True
        # 关键：探测失败也要标记已切换，并且只告警一次。
        # 否则 20 条新闻会打印 20 行同样的"备用源均不可用"，把整段日志冲掉，
        # 真正有用的「标题失败率」那行反而看不见了。这是实测踩到的问题。
        _active_provider.update(name=provider, switched=True)
        log("翻译", f"主源 {provider} 配额用尽，备用源均不可用，本期标题将回退英文")
        return text, False

    if status == "quota" and _active_provider["switched"]:
        # 已切过源（不论切成功与否）：回退原文，不重试、不重复告警
        return text, False
    return text, False


def step5_translate(items):
    """翻译标题与短摘要；失败回退英文原文（标题前加 [EN] 标记）。

    【B3】返回标题翻译的失败率，交给主流程判断是否整体异常。
    理由：单条失败回退英文没问题，但如果一整期 20 条里七八条都变 [EN]，
    那是翻译服务挂了，不是新闻的问题 —— 这时候覆盖线上数据，
    等于把读者昨天还能看懂的中文日报换成英文，体验更差。宁可保留旧的一期。
    """
    if TRANSLATE_PROVIDER == "none":
        log("翻译", "TRANSLATE_PROVIDER=none，跳过翻译，全部保留英文原文")
        for it in items:
            it["title_cn"] = "[EN] " + it["title"]
            it["summary_cn"] = it["summary"]
        return items, {"provider": "none", "title_ok": 0, "title_fail": 0,
                       "summary_ok": 0, "summary_fail": 0, "fail_ratio": 0.0, "skipped": True}

    # 分两轮：先把所有标题翻完，再翻摘要。
    # 原因：免费接口每天有配额，如果逐条「标题+摘要」交替请求，
    # 配额一断就是后半段新闻标题和摘要双双变英文，列表页会很难看。
    # 先保标题，最坏情况也只是摘要残留英文，主展示仍是中文。
    #
    # 注意：这里每条都用 _active_provider 的当前值，而不是固定的 TRANSLATE_PROVIDER ——
    # 主源中途配额用尽切换到备用源后，后面的条目要立刻跟着换源。
    _active_provider.update(name=TRANSLATE_PROVIDER, switched=False)
    ok = fail = 0
    for it in items:
        t, ok1 = translate_text(it["title"], _active_provider["name"])
        if ok1:
            it["title_cn"] = t
            ok += 1
        else:
            it["title_cn"] = "[EN] " + it["title"]  # 回退：保留英文原文并打标记
            fail += 1
        time.sleep(0.3)  # 免费接口限速
    log("翻译", f"标题：成功 {ok} 条，回退英文 {fail} 条（标记为 [EN]）")

    ok2 = fail2 = 0
    for it in items:
        s, good = translate_text(it["summary"], _active_provider["name"])
        it["summary_cn"] = s if good else it["summary"]
        if good:
            ok2 += 1
        else:
            fail2 += 1
        time.sleep(0.3)
    log("翻译", f"摘要：成功 {ok2} 条，回退英文 {fail2} 条")

    total = ok + fail
    ratio = (fail / total) if total else 0.0
    log("翻译", f"标题失败率 {ratio:.0%}（阈值 {TRANSLATE_FAIL_RATIO_LIMIT:.0%}）")
    return items, {"provider": TRANSLATE_PROVIDER,
                   "provider_final": _active_provider["name"],
                   "switched": _active_provider["switched"],
                   "title_ok": ok, "title_fail": fail,
                   "summary_ok": ok2, "summary_fail": fail2,
                   "fail_ratio": round(ratio, 4), "skipped": False}


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


def step7b_quota(items):
    """配额挑选：先满足各领域名额，剩余席位按热度补位，最后统一重排。

    【与 id 契约相关】这里同时做一次"按规范化 URL 去重"。
    step2_dedup 已经去过一次，但那是按标题/URL 双规则；而 id 是按 URL 哈希算的，
    只要两条新闻的规范化 URL 相同，它们就会算出同一个 id。
    在挑选阶段就按 URL 去重，输出端就不可能出现重复 id，
    也不会因为丢掉重复条目而凑不满 20 条 —— 名额会让给下一条候选。
    """
    items = list(items)          # 不改动调用方的列表
    seen_url = set()
    deduped = []
    for it in items:
        key = normalize_url(it["url"]) or it["url"] or ""
        if key in seen_url:
            continue
        seen_url.add(key)
        deduped.append(it)
    if len(deduped) != len(items):
        log("配额", f"按 URL 去掉 {len(items) - len(deduped)} 条重复候选项（保证 id 唯一）")
    items = deduped

    used = [False] * len(items)
    picked = []
    log_count = {}

    for cat, quota in CATEGORY_QUOTA.items():
        got = 0
        for i, it in enumerate(items):
            if used[i] or it["category"] != cat:
                continue
            used[i] = True
            picked.append(it)
            got += 1
            if got >= quota:
                break
        log_count[cat] = got

    for i, it in enumerate(items):
        if len(picked) >= TARGET_NEWS:
            break
        if not used[i]:
            used[i] = True
            picked.append(it)

    picked.sort(key=lambda x: (-x["heat"], -x["published_at"].timestamp()))
    log("配额", "各领域入选：地缘冲突 {}｜国际政治 {}｜金融市场 {}，合计 {} 条".format(
        log_count["geopolitics"], log_count["politics"], log_count["markets"], len(picked)))
    return picked[:MAX_NEWS]


def step8_output(items, now):
    """输出：按协议生成 data/news.json（原子写入，失败不会留下半截文件）。

    【B1】id 用 make_stable_id(url) 生成，不再用 news-001 这种序号。
    排名会变，id 不变 —— 这是归档、热度对比、前端收藏功能的地基。

    【id 契约】两条硬要求：
      ① 同一期内 id 唯一；
      ② 同一条新闻跨期必须是同一个 id。
    这两条能同时成立，靠的是一个前提：**id 只由 URL 决定，不掺杂任何位置信息**。

    早期版本在撞哈希时写的是 `nid[:10] + "%02x" % len(seen_ids)`，
    后缀取的是"当前处理到第几条"。同一条新闻换一期排位变了，后缀就跟着变 ——
    等于把位置信息偷偷塞回了 id，跨期稳定性当场失效。这个坑由前端同学指出
    （前端不得不用"加后缀 + warn"兜底，本身就说明生成端有问题），已修正。

    现在撞哈希只剩一种可能：**规范化 URL 不同，但哈希前 12 位相同**
    （约 1e-12，20 条时实际不可能）。处理方式是用 URL 指纹替换后 4 位 ——
    指纹只与 URL 有关、与排位无关，跨期依然稳定。
    "同一条新闻被重复收录"这种情况已经在 step7b_quota 按 URL 去掉了，不会走到这里。
    """
    news_list = []
    id_owner = {}   # id -> 规范化 URL，用于识别真正的哈希碰撞
    for it in items[:MAX_NEWS]:
        key = normalize_url(it["url"]) or it["url"] or ""
        nid = make_stable_id(it["url"])

        if nid in id_owner and id_owner[nid] != key:
            # 不同 URL 算出同一个 id。用 URL 指纹替换后 4 位，与排位无关。
            first = id_owner[nid]          # 先存下原主，改完 nid 就查不到了
            fp = hashlib.sha1(key.encode("utf-8")).hexdigest()
            cand = nid[:8] + fp[:4]
            i = 4
            # 加了指纹也可能恰好又撞（概率极低），再往后取几位继续试。
            # 取的是 URL 指纹的连续片段，仍然只跟 URL 有关，跨期稳定。
            while cand in id_owner and id_owner[cand] != key and i + 4 <= len(fp):
                cand = nid[:8] + fp[i:i + 4]
                i += 4
            nid = cand
            log("输出", f"⚠ id 碰撞（{first[:40]}），已用 URL 指纹区分：{nid}")

        id_owner[nid] = key
        news_list.append({
            "id": nid,
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

    write_json_atomic(NEWS_JSON_PATH, payload)
    log("输出", f"已写入 {NEWS_JSON_PATH}（{len(news_list)} 条新闻，id 为 URL 哈希）")
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
# 四、归档与概览（B2 / B6 / B7）
# ============================================================

CATEGORY_CN = {"geopolitics": "地缘冲突", "politics": "国际政治", "markets": "金融市场"}


def step9_build_digest(payload, now_bj):
    """【B6】生成每日概览摘要（纯规则，不调用任何大模型）。

    数据来源只有本次输出的 20 条新闻，因此每一句都能回溯到具体条目。
    硬约束（方案第十节风险表）：
      · 只陈述数据中客观存在的事实；
      · 不做因果判断、不做趋势预测、不做价值评价；
      · 某领域当天为零条时，该领域 text 留空字符串，绝不凑字。
    """
    news = payload["news"]
    total = len(news)

    # [EN] 是给前端识别"这条没翻出来"的技术标记，不能出现在摘要正文里。
    # 摘要是一句给读者看的中文人话，夹个 [EN] 会把句子读断。
    # 这里只做显示层的去标，news.json 里的 title 保持原样，前端仍能判断。
    def clean(title):
        return title[5:] if title.startswith("[EN] ") else title

    by_category = {"geopolitics": 0, "politics": 0, "markets": 0}
    for n in news:
        if n["category"] in by_category:
            by_category[n["category"]] += 1

    # 最热三条（数组本身已按 heat 降序）
    top3 = [{"id": n["id"], "title": clean(n["title"]), "heat": n["heat"]} for n in news[:3]]

    # 地理覆盖
    located = [n for n in news if n["lat"] is not None]
    countries = [n["country"] for n in located if n["country"]]
    counter = {}
    for c in countries:
        counter[c] = counter.get(c, 0) + 1
    top_country = max(counter, key=counter.get) if counter else None
    geo = {
        "located": len(located),
        "countries": len(set(countries)),
        "top_country": top_country,
    }

    # 各领域一句小结：句式固定，只拼接客观事实
    sections = []
    for cat in ("geopolitics", "politics", "markets"):
        cat_news = [n for n in news if n["category"] == cat]
        if not cat_news:
            sections.append({"category": cat, "count": 0, "text": ""})
            continue
        head = cat_news[0]  # 该领域热度最高的一条
        sources = sorted({n["source"] for n in cat_news})
        text = "{} {} 条，最受关注的是《{}》（热度 {}），来自 {}。".format(
            CATEGORY_CN[cat], len(cat_news), clean(head["title"]), head["heat"], head["source"])
        if len(sources) > 1:
            text += "其余报道来自 {}。".format("、".join([s for s in sources if s != head["source"]]))
        sections.append({"category": cat, "count": len(cat_news), "text": text})

    return {
        "date": now_bj.strftime("%Y-%m-%d"),
        "updated_at": payload["updated_at"],
        "total": total,
        "by_category": by_category,
        "top3": top3,
        "geo": geo,
        "sections": sections,
    }


def step10_write_archive(payload, digest, now_bj):
    """【B2 + B7】写历史归档与归档索引。

    文件规划：
      data/archive/2026-10-18.json          当日新闻（结构与 news.json 完全一致）
      data/archive/2026-10-18-digest.json   当日概览（供前端日期联动）
      data/archive/index.json               索引，前端读它拿可用日期列表

    同日多次运行（早班 + 晚班）采用「当日终版」策略：
      日期文件被最后一次成功运行覆盖，语义最清晰 —— 用户选"10 月 18 日"
      看到的就是那一整天最后确定下来的那一期。
      若需要保留两个班次用于热度对比，另写入带班次后缀的文件。
    """
    date_str = now_bj.strftime("%Y-%m-%d")
    label = "am" if now_bj.hour < 12 else "pm"

    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    # 1. 当日归档（终版）
    news_path = os.path.join(ARCHIVE_DIR, f"{date_str}.json")
    write_json_atomic(news_path, payload)

    # 2. 当日概览归档
    has_digest = False
    if digest:
        digest_path = os.path.join(ARCHIVE_DIR, f"{date_str}-digest.json")
        write_json_atomic(digest_path, digest)
        has_digest = True

    # 3. 班次快照（用于热度对比；不作为日期选择器的选项）
    shift_path = os.path.join(ARCHIVE_DIR, f"{date_str}-{label}.json")
    write_json_atomic(shift_path, payload)

    # 4. 更新索引
    index = read_json_safe(ARCHIVE_INDEX_PATH, {"dates": []}) or {"dates": []}
    dates = [d for d in index.get("dates", []) if isinstance(d, dict) and d.get("date") != date_str]
    dates.append({
        "date": date_str,
        "count": len(payload["news"]),
        "generated_at": payload["updated_at"],
        "has_digest": has_digest,
    })
    dates.sort(key=lambda d: d["date"], reverse=True)  # 倒序：第一个就是最新一天
    write_json_atomic(ARCHIVE_INDEX_PATH, {"dates": dates})

    # 5. 清理过期归档（保留最近 ARCHIVE_KEEP_DAYS 天）
    cutoff = (now_bj - timedelta(days=ARCHIVE_KEEP_DAYS)).strftime("%Y-%m-%d")
    kept, removed = [], 0
    for d in dates:
        if d["date"] >= cutoff:
            kept.append(d)
            continue
        # 该日期的所有相关文件一并删除
        for name in (f"{d['date']}.json", f"{d['date']}-digest.json",
                     f"{d['date']}-am.json", f"{d['date']}-pm.json"):
            p = os.path.join(ARCHIVE_DIR, name)
            if os.path.exists(p):
                os.remove(p)
                removed += 1
    if removed:
        write_json_atomic(ARCHIVE_INDEX_PATH, {"dates": kept})
        log("归档", f"清理超过 {ARCHIVE_KEEP_DAYS} 天的归档：删除 {removed} 个文件")

    log("归档", f"已写入 {date_str} 归档（{len(payload['news'])} 条，概览{'已' if has_digest else '未'}生成），"
                f"索引共 {len(kept)} 天，班次 {label}")
    return date_str


def step11_write_digest(digest):
    """【B7】把当日概览写到 data/digest.json，供前端首页直接读取。"""
    if not digest:
        log("概览", "概览为空，跳过写入 data/digest.json")
        return
    write_json_atomic(DIGEST_JSON_PATH, digest)
    log("概览", f"已写入 {DIGEST_JSON_PATH}（{digest['total']} 条，"
                f"地缘 {digest['by_category']['geopolitics']}｜"
                f"政治 {digest['by_category']['politics']}｜"
                f"市场 {digest['by_category']['markets']}）")


def step12_write_log(stats, now_bj):
    """【B4】写运行日志。

    为什么要留日志：长期运营时，"今天为什么只出了 12 条""为什么全变英文了"
    这类问题只能靠当时的统计数字回溯。控制台输出在 Actions 里几十次之后
    就被淹没了，落成文件才查得动。
    """
    os.makedirs(LOGS_DIR, exist_ok=True)
    stamp = now_bj.strftime("%Y-%m-%d_%H%M")
    path = os.path.join(LOGS_DIR, f"{stamp}.json")
    record = {"run_at": now_bj.strftime("%Y-%m-%dT%H:%M:%S+08:00")}
    record.update(stats)
    write_json_atomic(path, record)

    # 只保留最近 LOG_KEEP_FILES 份
    files = sorted(f for f in os.listdir(LOGS_DIR) if f.endswith(".json"))
    for old in files[:-LOG_KEEP_FILES]:
        os.remove(os.path.join(LOGS_DIR, old))

    log("日志", f"已写入 {os.path.relpath(path, BASE_DIR)}（保留最近 {LOG_KEEP_FILES} 份）")


# ============================================================
# 四、主流程
# ============================================================

def main():
    print("=" * 60)
    print("WorldPulse Daily 新闻更新流水线启动")
    print("=" * 60)
    now = datetime.now(timezone.utc)
    now_bj = now_beijing()

    # 统计容器：所有环节的数字都记下来，最后统一写日志（B4）
    stats = {
        "ok_sources": 0, "total_sources": len(RSS_SOURCES),
        "raw_count": 0, "dedup_count": 0, "time_filtered_count": 0,
        "classified_count": 0, "dropped_by_category": 0,
        "located_count": 0, "final_count": 0,
        "category_dist": {}, "source_dist": {},
        "translate": {}, "status": "unknown", "message": "",
    }

    # 1. 获取
    raw_items, ok_sources = step1_fetch()
    stats["raw_count"] = len(raw_items)
    stats["ok_sources"] = ok_sources
    if ok_sources == 0 or not raw_items:
        stats["status"] = "failed"
        stats["message"] = "所有 RSS 源都不可用"
        step12_write_log(stats, now_bj)
        keep_old_data("所有 RSS 源都不可用")
        sys.exit(2)  # 非零退出码：告诉 GitHub Actions 本次失败，不发布

    # 2~3. 去重 + 时效过滤
    deduped = step2_dedup(raw_items)
    stats["dedup_count"] = len(deduped)
    items = step3_filter_by_time(deduped, now)
    stats["time_filtered_count"] = len(items)
    if not items:
        stats["status"] = "failed"
        stats["message"] = "过滤后没有符合条件的新闻"
        step12_write_log(stats, now_bj)
        keep_old_data("过滤后没有符合条件的新闻")
        sys.exit(2)

    # 4. 分类
    before_classify = len(items)
    items = step4_classify(items)
    stats["classified_count"] = len(items)
    stats["dropped_by_category"] = before_classify - len(items)
    if not items:
        stats["status"] = "failed"
        stats["message"] = "没有新闻落入三个分类领域"
        step12_write_log(stats, now_bj)
        keep_old_data("没有新闻落入三个分类领域")
        sys.exit(2)

    # 5. 定位（必须排在评分前：热度里的「地理定位分」依赖这一步的结果）
    items = step6_locate(items)
    stats["located_count"] = sum(1 for i in items if i["lat"] is not None)

    # 6. 评分 + 按配额挑选出最终入选的新闻
    items = step7b_quota(step7_heat(items, now))
    if len(items) < MIN_VALID_TO_WRITE:
        stats["status"] = "failed"
        stats["message"] = f"有效新闻不足 {MIN_VALID_TO_WRITE} 条（只有 {len(items)} 条）"
        step12_write_log(stats, now_bj)
        keep_old_data(f"有效新闻不足 {MIN_VALID_TO_WRITE} 条（只有 {len(items)} 条）")
        sys.exit(2)

    # 7. 只翻译入选的这 20 条（关键：先挑后翻）
    #    早期版本是先翻译全部候选再挑，100 条候选里只留 20 条，
    #    等于白烧掉约 60% 的免费翻译配额，还让单次运行慢了 3 倍。
    items, translate_stats = step5_translate(items)
    stats["translate"] = translate_stats

    # 7b. 【B3】翻译整体异常检查
    #     失败率超阈值时，不覆盖线上数据。注意要排除 PROVIDER=none 的调试场景。
    if (not translate_stats["skipped"]
            and translate_stats["fail_ratio"] > TRANSLATE_FAIL_RATIO_LIMIT):
        msg = (f"翻译失败率 {translate_stats['fail_ratio']:.0%} 超过阈值 "
               f"{TRANSLATE_FAIL_RATIO_LIMIT:.0%}，判定翻译服务异常")
        log("告警", msg + "，本次不覆盖线上数据")
        stats["status"] = "translate_degraded"
        stats["message"] = msg
        step12_write_log(stats, now_bj)
        keep_old_data(msg)
        sys.exit(3)  # 单独退出码：方便在 Actions 里区分"翻译挂了"和"抓取挂了"

    # 8. 输出主数据
    payload = step8_output(items, now)
    stats["final_count"] = len(payload["news"])
    stats["category_dist"] = {c: sum(1 for n in payload["news"] if n["category"] == c)
                              for c in ("geopolitics", "politics", "markets")}
    src_dist = {}
    for n in payload["news"]:
        src_dist[n["source"]] = src_dist.get(n["source"], 0) + 1
    stats["source_dist"] = src_dist

    # 9~11. 概览 + 归档 + 概览落盘
    #   这三个环节用 try 包住：它们是"增强功能"，任何一处出错
    #   都不能影响已经写好的 news.json —— 主数据永远优先。
    digest = None
    try:
        digest = step9_build_digest(payload, now_bj)
        step11_write_digest(digest)
    except Exception as ex:
        log("概览", f"⚠ 生成概览失败（不影响主数据）：{ex}")
        digest = None

    try:
        step10_write_archive(payload, digest, now_bj)
    except Exception as ex:
        log("归档", f"⚠ 写归档失败（不影响主数据）：{ex}")

    # 12. 运行日志
    stats["status"] = "success"
    stats["message"] = "本次更新完成"
    step12_write_log(stats, now_bj)

    # 结果预览（方便本地检查和答辩演示）
    print("-" * 60)
    for n in payload["news"][:5]:
        print(f"  {n['id']}  heat={n['heat']:>3} [{n['category']:<11}] {n['title'][:40]}")
    print("-" * 60)
    print("本次更新完成。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        keep_old_data(f"发生未预期错误：{e}")
        raise
