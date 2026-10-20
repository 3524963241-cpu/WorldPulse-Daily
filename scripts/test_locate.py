#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定位回归测试：把联调中发现的真实错误固化成用例。

为什么要有这个文件：
    定位逻辑是"规则+词典"，改一个别名就可能把别的案例弄坏。
    前端同学在联调里实测出过两个错（曼谷会议判成中国、某条判成沙特），
    这类问题不会让页面崩，但地图会飞到错误的点 —— 属于"静默错误"，
    只能靠用例守住。

用法：
    python3 scripts/test_locate.py          # 全部用例
    python3 scripts/test_locate.py -v       # 打印每条的实际判定

退出码：0 全过；1 有用例失败
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("update_news", os.path.join(HERE, "update_news.py"))
un = importlib.util.module_from_spec(spec)
spec.loader.exec_module(un)

# (说明, 标题, 摘要, 期望country, 期望city, 期望basis)
#   None 表示"这一项不校验"；"__NONE__" 表示必须是空
CASES = [
    # —— 联调实测的两个真实错误 ——
    (
        "曼谷会议：摘要里顺带提到 China（对比 2018），不能判成中国",
        "The world's finance chiefs see new risks",
        "Debt, AI and Ukraine dominated the conversation at the IMF-World Bank "
        "meetings in Bangkok, while China, the focus in 2018, slipped into the background.",
        "泰国", "曼谷", "summary",
    ),
    (
        "摘要里同时出现多个城市（东京/纽约）→ 多地基综述，宁可不出点也不猜",
        "Markets wobble",
        "Investors in Tokyo and New York disagreed, while Germany and Brazil stayed quiet.",
        "__NONE__", "__NONE__", None,
    ),
    # —— 城市优先于国家 ——
    (
        "标题写 Tehran，应给城市级坐标而不是伊朗国家中心点",
        "Explosions reported near Tehran airport",
        "",
        "伊朗", "德黑兰", "title",
    ),
    (
        "标题同时出现国家和城市：以色列 < 特拉维夫，城市优先",
        "Tel Aviv rally draws thousands as Israel weighs ceasefire",
        "",
        "以色列", "特拉维夫", "title",
    ),
    (
        "标题是乌克兰，正文提 Moscow，事件地仍取标题的乌克兰",
        "Ukraine and Russia exchange strikes",
        "Moscow says it intercepted drones overnight.",
        "乌克兰", None, "title",
    ),
    # —— 弱证据：机构名不等于地点 ——
    (
        "只有 Wall Street，没有别的国家 → 不算有国家",
        "Wall Street weighs the odds of a December cut",
        "",
        "__NONE__", "__NONE__", None,
    ),
    # —— 中国相关（含港澳台口径）——
    (
        "香港应识别为城市，国家记为中国香港地区",
        "Hong Kong stocks slip as property fears return",
        "",
        "中国香港地区", "香港", "title",
    ),
    (
        "北京应识别为城市，国家记为中国",
        "Beijing announces new stimulus measures",
        "",
        "中国", "北京", "title",
    ),
    # —— 纯市场报道的来源兜底由 step6 处理，这里只测扫描器 ——
]


def run(verbose=False):
    country_tbl, city_tbl = un._load_gazetteer()
    passed = failed = 0
    for desc, title, summary, exp_c, exp_city, exp_basis in CASES:
        # 复用真实的 step6_locate，但只喂一条，避免被别的条目的日志干扰
        it = {
            "title": title, "summary": summary, "category": "politics",
            "source": "NPR World", "url": "https://example.com/x",
            "source_score": 10, "category_hits": 1,
        }
        un.step6_locate([it])
        got_c, got_city, got_basis = it["country"], it["city"], it["locate_basis"]

        def norm(v):
            return None if v == "__NONE__" else v

        ok = True
        if norm(exp_c) != got_c:
            ok = False
        if norm(exp_city) != got_city:
            ok = False
        if exp_basis is not None and exp_basis != got_basis:
            ok = False

        if ok:
            passed += 1
            print(f"  ✓ {desc}")
        else:
            failed += 1
            print(f"  ✗ {desc}")
            print(f"      期望 country={exp_c!r} city={exp_city!r} basis={exp_basis!r}")
            print(f"      实际 country={got_c!r} city={got_city!r} basis={got_basis!r}")
        if verbose:
            print(f"      → {got_c} / {got_city} / {got_basis}")
    print(f"\n用例 {passed + failed} 条：通过 {passed}，失败 {failed}")
    return failed == 0


if __name__ == "__main__":
    print("定位回归测试\n" + "=" * 50)
    ok = run(verbose="-v" in sys.argv)
    sys.exit(0 if ok else 1)
