# B 侧任务完成报告（V3.0）

> 对应《WorldPulse-Daily工作台升级方案V3.0》第五章 B 任务清单  
> 完成时间：2026-10-18 · 提交：`035b358` · 状态：**B1–B7 全部实现并在真实数据上验证通过**

---

## 一、总览

| 编号 | 任务 | 状态 | 关键产物 |
|---|---|---|---|
| **B1** | id 稳定化 | ✅ | `news.json` 中 id 形如 `46ee43f3cce0` |
| **B2** | 历史归档 | ✅ | `data/archive/` + `index.json` |
| **B3** | 翻译异常保护 | ✅ | 失败率 > 30% 拒绝覆盖，退出码 3 |
| **B4** | 运行日志 | ✅ | `data/logs/YYYY-MM-DD_HHMM.json` |
| **B5** | 翻译服务容错 | ✅ | 主源配额耗尽自动切备用源 |
| **B6** | 每日概览 | ✅ | `data/digest.json` |
| **B7** | 概览入归档 | ✅ | `archive/YYYY-MM-DD-digest.json` |

本轮真实运行结果：**原始 100 条 → 过滤 57 → 分类 42 → 输出 20 条，翻译成功 20/20，0 条回退英文**。

---

## 二、B1：id 稳定化（这是所有功能的地基）

### 原来错在哪

旧 id 是输出顺序的序号 `news-001`。今天第 1 条是"A 新闻"，明天第 1 条可能变成"B 新闻"。
前端拿 id 做列表 key、做收藏、做"这条昨天排第几"的对比，**全会错位**。

### 现在怎么做

```python
def make_stable_id(url):
    key = normalize_url(url) or url or ""
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
```

id = **URL 规范化后的 sha1 前 12 位**。同一条新闻无论排第几、隔多少天再抓，id 都不变。

```
旧: news-001, news-002, ...           （每天重排）
新: 46ee43f3cce0, 07944f18f402, ...   （跟着新闻走）
```

**验收**：20 条 id 全部匹配 `[0-9a-f]{12}`、全部唯一、旧序号残留 0 条、按 URL 重算后与原 id 完全一致。

---

## 三、B2：历史归档

```
data/archive/
  index.json                 索引，按日期倒序
  2026-10-18.json            当日终版 20 条
  2026-10-18-pm.json         班次快照（am 早班 / pm 晚班）
  2026-10-18-digest.json     当日概览（B7）
```

索引结构：

```json
{"dates": [{"date": "2026-10-18", "count": 20,
            "generated_at": "2026-10-18T09:01:46Z", "has_digest": true}]}
```

两个容易踩的细节：

1. **日期按北京时间划分**（`BEIJING_TZ`），不是 UTC —— 否则晚上 8 点那班会被记到前一天；
2. **归档失败不影响 `news.json`**（`try/except` 包住）。宁可少一份归档，不能让新闻更新失败。

**验收**：归档 20 条与 `news.json` 的 id 序列完全一致；90 天保留策略实测通过（构造 100/95/91 天前数据被删，30 天前保留）。

---

## 四、B3 + B5：翻译保护与容错

### B3 为什么需要

单条翻译失败回退英文没问题。但如果一整期 20 条里七八条都是 `[EN]`，
那是**翻译服务挂了，不是新闻的问题**。这时覆盖线上，等于把读者昨天还能看的中文日报换成英文。

```
失败率 = 标题翻译失败数 / 标题总数
> 30%  →  不覆盖 news.json，保留上一期，退出码 3，Actions 显示红叉
```

### B5 在 B3 之上补的一层

只做"失败就不覆盖"还不够——服务好了以后依然会全变英文。所以加了**换源**：

| 情况 | 行为 |
|---|---|
| 主源返回 `429` 或 `MYMEMORY WARNING...` | 判定服务级配额耗尽，自动切备用源 `gtx` |
| 备用源也挂了 | 回退英文，**只告警一次**，不反复重试 |
| 单条网络抖动 | 只算这一条失败，不触发换源（避免误判） |

### 实测中踩到的两个问题（都已修掉）

**问题 1：告警刷屏。** 第一版实现里，配额耗尽时 20 条新闻打印了 20 行一模一样的"备用源均不可用"，
把真正有用的「标题失败率 40%」那行冲出了屏幕。修法：探测失败也标记为"已切换"，之后不再重复告警。

**问题 2：`[EN]` 泄漏进摘要。** 摘要正文里出现了"最受关注的是《[EN] Major fire breaks out…》"。
修法：摘要生成时在显示层去掉 `[EN] ` 前缀，`news.json` 里保持原样（前端仍需判断翻译状态）。

**验收**：强制翻译全失败 → 退出码 **3**、旧数据 md5 完全一致、控制台明确打印"本次不覆盖线上数据"。

---

## 五、B4：运行日志

每次运行写一份 `data/logs/YYYY-MM-DD_HHMM.json`，保留最近 30 份：

```json
{
  "run_at": "2026-10-18T17:01:46+08:00",
  "ok_sources": 6, "total_sources": 6,
  "raw_count": 100, "dedup_count": 100,
  "time_filtered_count": 57, "classified_count": 42,
  "dropped_by_category": 15, "located_count": 25,
  "final_count": 20,
  "category_dist": {"geopolitics": 5, "politics": 7, "markets": 8},
  "source_dist": {"NPR World": 6, "CNBC World News": 10, "MarketWatch Top": 3, "NPR Politics": 1},
  "translate": {"provider": "mymemory", "title_ok": 20, "title_fail": 0, "fail_ratio": 0.0},
  "status": "success"
}
```

`status` 三个取值：`success` / `translate_degraded`（B3 触发）/ `fetch_failed`（抓取失败）。

**排查价值**：下次出现"今天为什么只有 15 条"，看一眼 `classified_count` 和 `dropped_by_category` 就知道卡在哪一步，不用重跑。

---

## 六、B6 + B7：每日概览

### 输出结构

```json
{
  "date": "2026-10-18",
  "updated_at": "2026-10-18T09:01:46Z",
  "total": 20,
  "by_category": {"geopolitics": 5, "politics": 7, "markets": 8},
  "top3": [{"id": "46ee43f3cce0", "title": "在军事基地发生致命事件后，艾伯塔省发生重大火灾", "heat": 91}],
  "geo": {"located": 16, "countries": 6, "top_country": "美国"},
  "sections": [{"category": "geopolitics", "count": 5, "text": "..."}]
}
```

### 本轮真实生成的摘要

> 地缘冲突 5 条，最受关注的是《在军事基地发生致命事件后，艾伯塔省发生重大火灾》（热度 91），来自 NPR World。其余报道来自 CNBC World News。
>
> 国际政治 7 条，最受关注的是《金伯利·吉尔福伊尔（ Kimberly Guilfoyle ）丑闻后国务院的状况》（热度 80），来自 NPR World。其余报道来自 CNBC World News、NPR Politics。
>
> 金融市场 8 条，最受关注的是《为什么对冲基金可能会使债券市场更有可能受到冲击》（热度 84），来自 CNBC World News。其余报道来自 MarketWatch Top。

### 三条硬约束（写死在代码注释里）

1. **只陈述数据中客观存在的事实**——条数、最热那条、来源，每句都能点回原文核对；
2. **不预测、不评价**——不出现"预计…将""说明…""值得关注"这类句子；
3. **某领域当天 0 条时 `text` 留空字符串**，绝不为凑字数编话。

**验收**：禁用词扫描（预计/将会/因此/表明/意味着/有望/前景…）命中 **0**；每段都含客观条数；`[EN]` 泄漏 **False**；归档概览与 `digest.json` 逐字节一致。

---

## 七、顺带修掉的两个隐患

| 隐患 | 后果 | 修法 |
|---|---|---|
| 工作流只 `git add data/news.json` | 归档、概览、日志在 Actions 上跑完就丢了——本地有、线上没有 | 改为 `git add -A data/news.json data/digest.json data/archive data/logs` |
| `.gitignore` 只忽略 `data/*.tmp` | 归档/日志目录下原子写入的 `.tmp` 会混进提交 | 补 `data/archive/*.tmp`、`data/logs/*.tmp` |

另外**刻意没有加 `push` 触发器**：加了的话 A 每推一次前端都会跑一遍完整抓取，白耗 Actions 额度；更麻烦的是两次定时任务之间数据被重抓，同一期的 id 会变，"这一期 20 条"就说不清了。

---

## 八、给 A 的接口变化（需要转达）

1. **`id` 换格式了**：`news-001` → `46ee43f3cce0`。**不要再用数组下标当 id**，用 `item.id`；
2. **新增 `data/digest.json`**：直接渲染 `sections[].text` 就是一句成文的中文小结，注意 `text` 可能为空串要跳过；
3. **新增 `data/archive/index.json`**：日期选择器读 `dates` 数组即可，但要能处理"文件还不存在"的情况（首次部署后才开始累积）；
4. **别把概览叫"AI 助手"**：它是规则生成的客观汇总，叫「今日概览」更准确。标成 AI 会让人以为能追问、能分析，反而露怯。

以上四点已写入 `docs/前端对接说明.md` 和 `docs/示例数据速查.md`。

---

## 九、待你操作

本地已提交（`035b358`），**推送到 GitHub 还需要一个新的 PAT**（需要 `repo` + `workflow` 两个 scope，因为改了 `.github/workflows/update.yml`）。

推送后建议立刻手动跑一次 Actions，确认线上 `data/digest.json` 和 `data/archive/index.json` 都出现了。
