#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据契约自检：把"A 会真坏 / 只是降级"的边界写成可执行检查。

用法：
    python3 scripts/check_contract.py            # 查本地 data/
    python3 scripts/check_contract.py --online   # 查线上 Pages

退出码：0 全部通过；1 有 FATAL（会真坏）；2 仅 WARN（只是降级）
设计原则：FATAL 与 WARN 严格分开 —— 页面缺一块不代表前端崩了，
          但 id 重复、news 非数组、category 越界是真的会让页面挂掉。
"""
import json
import os
import re
import sys
import urllib.request

ONLINE = "--online" in sys.argv
BASE = ("https://3524963241-cpu.github.io/WorldPulse-Daily/data/" if ONLINE
        else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data") + "/")

FATAL, WARN = [], []
ENUM = {"geopolitics", "politics", "markets"}


def load(name):
    """读取一个数据文件；线上走 HTTP，本地走文件。返回 (数据|None, 错误信息)。"""
    try:
        if ONLINE:
            with urllib.request.urlopen(BASE + name, timeout=30) as r:
                return json.loads(r.read().decode()), None
        path = os.path.join(BASE, name)
        if not os.path.exists(path):
            return None, "文件不存在"
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def check_news(name, payload):
    """校验一份 news 结构。FATAL = 前端会崩；WARN = 有降级但不影响正文。"""
    if not isinstance(payload, dict):
        FATAL.append(f"{name}: 顶层不是对象")
        return []
    if not isinstance(payload.get("updated_at"), str):
        FATAL.append(f"{name}: 缺 updated_at")
    news = payload.get("news")
    if not isinstance(news, list):
        FATAL.append(f"{name}: news 不是数组 —— 前端会直接崩")
        return []
    if not news:
        FATAL.append(f"{name}: news 为空数组")

    ids = []
    for i, n in enumerate(news):
        tag = f"{name}[{i}]"
        if not isinstance(n, dict):
            FATAL.append(f"{tag}: 不是对象")
            continue
        # --- FATAL：会让前端崩或数据错 ---
        nid = n.get("id")
        if not isinstance(nid, str) or not nid:
            FATAL.append(f"{tag}: id 缺失")
        else:
            ids.append(nid)
        if n.get("category") not in ENUM:
            FATAL.append(f"{tag}: category 越界 -> {n.get('category')!r}")
        if not isinstance(n.get("title"), str):
            FATAL.append(f"{tag}: title 不是字符串")
        if not isinstance(n.get("url"), str) or not n.get("url", "").startswith("http"):
            FATAL.append(f"{tag}: url 非法")
        # --- 定位字段一致性（A 的 P0：city / 坐标 / country 三者不能自相矛盾）---
        has_lat = n.get("lat") is not None and n.get("lng") is not None
        if n.get("city") and not has_lat:
            FATAL.append(f"{tag}: 有 city 却没有坐标 —— 地图飞不过去")
        if n.get("city") and not n.get("country"):
            FATAL.append(f"{tag}: 有 city 却没有 country —— 前端两级回退会断")
        if has_lat:
            try:
                la, ln = float(n["lat"]), float(n["lng"])
                if not (-90 <= la <= 90 and -180 <= ln <= 180):
                    FATAL.append(f"{tag}: 坐标越界 ({la}, {ln})")
            except (TypeError, ValueError):
                FATAL.append(f"{tag}: 坐标不是数字 -> {n.get('lat')!r}, {n.get('lng')!r}")
        if n.get("image") is not None:
            img = n["image"]
            # 必须是绝对 URL：相对路径在 Pages 子路径下会 404
            if not isinstance(img, str) or not img.startswith(("http://", "https://")):
                FATAL.append(f"{tag}: image 不是绝对 URL -> {img!r}")
        # --- WARN：降级，不影响正文 ---
        if not n.get("summary"):
            WARN.append(f"{tag}: summary 为空（前端需兜底，属正常）")
        if not has_lat:
            WARN.append(f"{tag}: 无坐标（不上地图，属正常）")
        if not n.get("image"):
            WARN.append(f"{tag}: 无封面图（前端需显占位图）")
        if n.get("locate_basis") not in ("title", "summary", "source", None):
            WARN.append(f"{tag}: locate_basis 取值陌生 -> {n.get('locate_basis')!r}")
        if n.get("locate_basis") == "source":
            WARN.append(f"{tag}: 地点为来源推断（非文中明说），前端建议淡显")
        if isinstance(n.get("title"), str) and n["title"].startswith("[EN]"):
            WARN.append(f"{tag}: 标题回退英文 [EN]（翻译配额问题）")
        if not isinstance(n.get("heat"), (int, float)):
            WARN.append(f"{tag}: heat 非数值")

    dup = {x for x in ids if ids.count(x) > 1}
    if dup:
        FATAL.append(f"{name}: id 重复 {sorted(dup)} —— 前端 key 冲突")
    return ids


def main():
    scope = "线上" if ONLINE else "本地"
    print(f"数据契约自检（{scope}）\n" + "=" * 56)

    news, err = load("news.json")
    if err:
        FATAL.append(f"news.json: 读取失败 {err}")
    else:
        ids = check_news("news.json", news)
        print(f"news.json            : {len(ids)} 条")
        # —— 当期标识三件套：generated_at / date_beijing / shift ——
        # date_beijing 是"这份数据属于哪一天"的权威字段，等于归档文件名。
        # 前端切日期时应该用它，不要用 updated_at 推日期（那是 UTC，
        # 北京时间 00:00~08:00 这一班会被算成前一天）。
        for k in ("generated_at", "date_beijing", "shift"):
            if not news.get(k):
                WARN.append(f"news.json: 缺 {k}（旧版数据，前端需回退到 digest.date）")
        if news.get("date_beijing") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}",
                                                        str(news["date_beijing"])):
            FATAL.append(f"news.json: date_beijing 格式错 -> {news['date_beijing']!r}")

    dg, err = load("digest.json")
    if err:
        WARN.append(f"digest.json 不可用（{err}），概览模块降级")
    elif not isinstance(dg.get("sections"), list):
        WARN.append("digest.json: sections 非数组，概览降级")

    idx, err = load("archive/index.json")
    if err:
        WARN.append(f"archive/index.json 不可用（{err}），历史模块降级")
    else:
        dates = [d.get("date") for d in idx.get("dates", [])]
        if dates != sorted(dates, reverse=True):
            FATAL.append(f"archive/index.json: dates 未倒序 -> {dates}")
        else:
            print(f"archive/index.json   : {len(dates)} 天，倒序 ✓")

        # 同日一致性：当期 news 必须与归档里同一天的文件内容一致。
        # 当前期取 digest.date，不取 news.updated_at 的日期 ——
        # 后者是 UTC，归档文件名是北京时间，北京时间 00:00~08:00 之间会差一天。
        cur = dg.get("date") if isinstance(dg, dict) else None
        if cur not in dates:
            cur = None
        if cur and news:
            arch, e2 = load(f"archive/{cur}.json")
            if e2:
                WARN.append(f"archive/{cur}.json 读取失败")
            elif [x["id"] for x in arch.get("news", [])] != [x["id"] for x in news.get("news", [])]:
                FATAL.append(f"archive/{cur}.json 与 news.json 内容不一致 —— 切换会漂数字")
            else:
                print(f"同日一致性           : news.json == archive/{cur}.json ✓")

        # 归档可用性：拿不到就是降级，不是崩
        for d in dates[:3]:
            _, e3 = load(f"archive/{d}.json")
            if e3:
                WARN.append(f"archive/{d}.json 不可用（{e3}）")

    print()
    if FATAL:
        print(f"FATAL（会真坏，必须修）{len(FATAL)} 项：")
        for x in FATAL:
            print("  ✗", x)
    else:
        print("FATAL: 无 ✓")
    print()
    if WARN:
        print(f"WARN（只是降级，前端应正常兜底）{len(WARN)} 项，前 8 条：")
        for x in WARN[:8]:
            print("  ·", x)
        if len(WARN) > 8:
            print(f"  … 另有 {len(WARN) - 8} 条同类")
    else:
        print("WARN: 无")

    return 1 if FATAL else (2 if WARN else 0)


if __name__ == "__main__":
    sys.exit(main())
