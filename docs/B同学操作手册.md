# WorldPulse Daily · B 同学操作手册

> 负责范围：新闻数据与自动化（RSS → Python → JSON → GitHub Actions → GitHub Pages）
> 对应方案文档中 B 的全部任务。A 同学负责 index.html / css / js，请勿改动。

---

## 一、我负责的文件清单

| 文件 | 作用 | 状态 |
|---|---|---|
| `scripts/update_news.py` | 新闻更新主脚本（单文件，含全部流水线逻辑） | ✅ 已完成并实测 |
| `data/locations.json` | 本地地名词典（约 80 个国家/地区 → 坐标） | ✅ 已完成 |
| `data/news.json` | 输出的统一数据文件（A 只读，B 只写） | ✅ 已生成真实数据 |
| `data/digest.json` | **每日概览**（B6），当日摘要，前端可直接渲染 | ✅ V3.0 新增 |
| `data/archive/` | **历史归档**（B2），按天存盘 + `index.json` 索引 | ✅ V3.0 新增 |
| `data/logs/` | **运行日志**（B4），每次运行一份，便于排查 | ✅ V3.0 新增 |
| `data/sample-news.json` | 固定快照，永不变化，供 A 调样式/离线用 | ✅ |
| `requirements.txt` | Python 依赖清单 | ✅ 已完成 |
| `.github/workflows/update.yml` | 定时自动更新 + 发布 GitHub Pages | ✅ 已完成 |
| `docs/B同学操作手册.md` | 本手册 | ✅ |

---

## 一·B、V3.0 新增能力一览（B1~B7）

| 编号 | 任务 | 实现位置 | 验收方式 |
|---|---|---|---|
| **B1** | id 稳定化 | `make_stable_id()` | id 形如 `46ee43f3cce0`，同一条新闻跨天不变 |
| **B2** | 历史归档 | `step10_write_archive()` | `data/archive/` 下出现 `YYYY-MM-DD.json` 与 `index.json` |
| **B3** | 翻译异常保护 | `step5_translate()` + `main()` | 翻译失败率 > 30% 时**不覆盖**线上数据，退出码 3 |
| **B4** | 运行日志 | `step12_write_log()` | `data/logs/` 下每次运行一份，含各阶段条数 |
| **B6** | 每日概览 | `step9_build_digest()` | `data/digest.json` 有三段中文小结 |
| **B7** | 概览入归档 | `step10_write_archive()` | 归档目录里有 `YYYY-MM-DD-digest.json` |
| B5 | 翻译服务容错 | `_translate_one()` + `translate_text()` | 主源配额耗尽时自动切备用源 |

### B1 为什么要换掉 `news-001`

旧 id 是输出顺序的序号：今天第 1 条是"A 新闻"，明天第 1 条可能变成"B 新闻"。
前端拿 `id` 做列表 key、做收藏、做"这条昨天排第几"的对比，**全会错位**。

现在 id = `sha1(规范化URL)` 的前 12 位十六进制：

```python
def make_stable_id(url):
    key = normalize_url(url) or url or ""
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
```

同一条新闻无论排第几、隔多少天再抓一次，id 都不变。这是归档、热度变化榜、收藏功能的**地基**。

### id 契约（前端会按这个验，别破坏）

| 契约 | 含义 | 保证方式 |
|---|---|---|
| **C1 同期唯一** | 同一份 `news.json` 里不出现两个相同 id | `step7b_quota` 挑选阶段按规范化 URL 去重 |
| **C2 格式固定** | 12 位小写十六进制 `[0-9a-f]{12}` | `make_stable_id()` 单一出口 |
| **C3 跨期稳定** | 同一条新闻换一期仍是同一个 id | id **只由 URL 决定**，不掺杂任何位置信息 |

**曾经踩过的坑（前端同学指出，已修）**：早先撞哈希时写的是

```python
nid = nid[:10] + "%02x" % len(seen_ids)   # ✗ 错
```

`len(seen_ids)` 是"当前处理到第几条"。同一条新闻换一期排位变了，后缀就跟着变——
等于把位置信息偷偷塞回了 id，**C3 当场失效**。而且这会让前端不得不加"后缀 + warn"兜底，
那个 warn 就是生成端有问题的信号。

**现在的做法**：撞哈希只剩"不同 URL、同哈希前 12 位"一种可能（约 1e-12，20 条时可忽略），
用 URL 指纹替换后 4 位——指纹只与 URL 有关，跨期依然稳定。
"同一篇新闻重复收录"这种情况在挑选阶段就按 URL 去掉了，根本走不到输出端。

**回归脚本**（B 侧本地版，等价于前端的 `id-contract-test.js`）：

```bash
node .workbuddy/tmp/id-contract-test.js --plain
```

它会读 `data/news.json` 和 `data/archive/*.json`，逐期校验 C1/C2，并跨期校验 C3。
改完 `update_news.py` 推之前跑一次，三项全绿再推。

### B2 归档结构

```
data/archive/
  index.json                 索引：{"dates":[{date, count, generated_at, has_digest}, ...]}，按日期倒序
  2026-10-18.json            当日终版 20 条（被下一次同日运行覆盖）
  2026-10-18-pm.json         班次快照（am / pm），用于算"半天内热度变化"
  2026-10-18-digest.json     当日概览（B7）
```

- 日期按**北京时间**划分（`BEIJING_TZ`），不是 UTC ——否则晚上 8 点那班会被记到前一天；
- 保留最近 **90 天**，更早的自动删除（`ARCHIVE_KEEP_DAYS`）；
- 归档失败**不影响** `news.json`写入（`try/except` 包住），宁可少一份归档，不能让新闻更新失败。

### B3 翻译异常保护（重要）

单条翻译失败回退英文没问题；但如果一整期 20 条里七八条都变 `[EN]`，
说明**翻译服务挂了，不是新闻的问题**。这时候覆盖线上，等于把读者昨天还能看的中文日报换成英文。

```
失败率 = 标题翻译失败数 / 标题总数
失败率 > 30%  →  不覆盖 news.json，保留上一期，退出码 3，Actions 显示为失败（红叉）便于发现
```

实测：强制翻译全失败 → 打印「判定翻译服务异常，本次不覆盖线上数据」，旧数据 md5 前后一致，退出码 3。

### B5 翻译服务容错（B3 的补强）

只做"失败就不覆盖"还不够——服务好了以后依然会全变英文。所以加了一层**换源**：

| 情况 | 行为 |
|---|---|
| 主源返回 `429` 或返回 `MYMEMORY WARNING...` 文本 | 判定为**服务级**配额耗尽，自动切到备用源 `gtx` |
| 已切到备用源且备用源也挂了 | 回退英文，不再反复重试 |
| 单条网络抖动 | 只算这一条失败，不触发换源（避免误判） |

备用源用环境变量 `TRANSLATE_FALLBACKS` 配置，默认 `gtx`（Google 网页翻译公开端点，无需密钥）。

> 沙箱环境访问不了 Google，这条链路是用模拟响应验证的（见第七节测试记录）；
> 真实环境里 MyMemory 配额耗尽时才会走到它。**不要把它当主源**——公开端点不保证长期可用。

### B4 运行日志

每次运行写一份 `data/logs/YYYY-MM-DD_HHMM.json`，保留最近 30 份：

```json
{
  "run_at": "2026-10-18T16:55:59+08:00",
  "status": "success",
  "raw_count": 100,
  "dedup_count": 100,
  "time_filtered_count": 59,
  "classified_count": 44,
  "dropped_by_category": 15,
  "located_count": 27,
  "final_count": 20,
  "source_dist": {"NPR World": 5, "CNBC World News": 8},
  "translate": {"provider": "mymemory", "title_ok": 20, "title_fail": 0, "fail_ratio": 0.0}
}
```

排查"今天为什么只有 15 条"时，看一眼 `classified_count` 和 `dropped_by_category` 就知道卡在哪一步，不用重跑。

### B6 每日概览（纯规则，不是大模型）

`data/digest.json`：

```json
{
  "date": "2026-10-18",
  "updated_at": "2026-10-18T08:48:01Z",
  "total": 20,
  "by_category": {"geopolitics": 5, "politics": 7, "markets": 8},
  "top3": [{"id": "46ee43f3cce0", "title": "...", "heat": 91}],
  "geo": {"located": 16, "countries": 6, "top_country": "美国"},
  "sections": [
    {"category": "geopolitics", "count": 5,
     "text": "地缘冲突 5 条，最受关注的是《阿尔伯塔省军事基地发生致命事件后爆发大火》（热度 91），来自 NPR World。其余报道来自 CNBC World News。"}
  ]
}
```

三条硬约束（写死在 `step9_build_digest` 的注释里）：

1. **只陈述数据中客观存在的事实**——条数、最热那条、来源，都能点回原文核对；
2. **不做因果判断、不做趋势预测、不做价值评价**——不出现"因为…所以""预计…将"这类句子；
3. **某领域当天零条时 `text` 留空字符串**，绝不为凑字数编话。

> 为什么不用在线大模型：静态站点把 API Key 放进前端等于公开泄露；后端每天跑一次也就 20 条数据，
> 规则生成零成本、零延迟、永远可用，而且可审计。**前端不要把它标成"AI 助手"**，叫"今日概览"更准确。

`[EN]` 标记不会出现在摘要正文里（显示层去掉），但 `news.json` 里的 `title` 保持原样，前端仍能判断翻译状态。

---

## 二、RSS 源验证结果（已实测）

经真实网络测试，以下 **6 个**源稳定可用（BBC / Al Jazeera / Guardian / DW / NYT / CNN / France24 在部分网络环境下不可达，故未采用）：

| 源 | 地址 | 实测 | 定位 |
|---|---|---|---|
| NPR World | `https://feeds.npr.org/1004/rss.xml` | ✅ 10 条/次 | 地缘 + 政治 |
| NPR Politics | `https://feeds.npr.org/1014/rss.xml` | ✅ 10 条/次 | 政治 |
| NPR Business | `https://feeds.npr.org/1006/rss.xml` | ✅ 10 条/次 | 财经 + 政治 |
| MarketWatch Top | `https://feeds.content.dowjones.io/public/rss/mw_topstories` | ✅ 10 条/次 | 财经 |
| MarketWatch Markets | `https://feeds.content.dowjones.io/public/rss/mw_marketpulse` | ✅ 30 条/次 | 财经 |
| CNBC World News | `https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362` | ✅ 30 条/次 | 财经 |

源地址集中在 `update_news.py` 顶部的 `RSS_SOURCES` 配置区，更换/新增源只改这一处。

> **为什么要 6 个源**：单个 NPR 频道每次只吐 10 条，3 个源合计 30 条，
> 经 48 小时过滤和分类后只剩 15~16 条，凑不满约定的 20 条。
> 加上 MarketWatch Markets 和 CNBC（各 30 条）后，原始条目达到 100 条，
> 最终稳定输出 20 条。这是"条数不够"问题的根本解法。

---

## 三、data/news.json 数据协议（已与 A 约定，冻结）

```json
{
  "updated_at": "2026-10-20T13:57:12Z",
  "generated_at": "2026-10-20T13:57:12Z",
  "date_beijing": "2026-10-20",
  "shift": "am | pm",
  "news": [
    {
      "id": "46ee43f3cce0",
      "title": "中文标题（翻译失败时为 [EN] 英文原文）",
      "summary": "中文短摘要（同上回退规则）",
      "category": "geopolitics | politics | markets 之一",
      "country": "中文国家/地区名，定位不到为 null",
      "city": "中文城市名，多数为 null（见下方说明）",
      "lat": 35.86,
      "lng": 104.19,
      "locate_basis": "title | summary | source | null",
      "image": "https://... 封面图绝对 URL，取不到为 null",
      "published_at": "2026-10-12T13:12:00Z（UTC，前端负责转北京时间）",
      "source": "NPR World",
      "url": "https://... 原文链接",
      "heat": 95
    }
  ]
}
```

规则要点：
- **固定输出 20 条**，按热度降序；
- **`id` 是 URL 哈希的 12 位十六进制**（B1），跨天稳定，不再是 `news-001` 序号；
- 20 条按**三领域软配额**分配（地缘 5 / 政治 7 / 市场 8），某领域当天条数不足时名额让给其他领域；
- `lat/lng` 允许为 null —— 该新闻仍显示在列表，但不上地图；
- `heat` 是**编辑规则热度**（见第六节），不是全网真实搜索热度，A 需在页面标注。

### 三个当期标识字段（2026-10-21 新增）

| 字段 | 作用 |
|---|---|
| `generated_at` | 与 `updated_at` 同值，名字对齐归档索引里的同名字段 |
| `date_beijing` | **本次数据属于哪一天（北京时间），恒等于归档文件名** |
| `shift` | `am`（北京 08:30 班）/ `pm`（北京 20:30 班） |

> 为什么非要加 `date_beijing`：`updated_at` 是 UTC，归档文件名是北京时间，
> 北京时间 00:00–08:00 这一班两者会差一天。定时任务在 08:30 / 20:30 跑不受影响，
> 但手动触发可能撞上。加了这字段，前端就不用自己推日期了。

### 定位结果怎么读

| 字段 | 含义 |
|---|---|
| `country` | 国家/地区名。**绝大多数条目都有**（纯市场报道按来源兜底记"美国"） |
| `city` | 城市名。**多数为 null，这是正常的**，见下 |
| `locate_basis` | 地点可信度，决定前端怎么画点，见下 |

`locate_basis` 四个取值：

| 值 | 含义 | 地理分 |
|---|---|---|
| `title` | 标题里明确出现地名 | 10 |
| `summary` | 标题没写，摘要里出现且没矛盾 | 7 |
| `source` | 文中没有任何地名，按"美股市场新闻"推断为美国 | 4 |
| `null` | 没定位到 | 0 |

> **为什么 `city` 大多是 null**：实测 100 条原始新闻里，标题含城市名的只有 1 条。
> NPR / CNBC 的标题写的是"某国内部发生了什么"，几乎不点城市名（如
> `Alberta voters reject a move toward independence`）。
> 词典已备好 121 个城市，新闻自己带出城市名时会自动生效。
> 这不是缺陷，是国际新闻标题的写作习惯。

### 定位的两级词典（`data/locations.json`）

```
locations  国家/地区 88 条  → 国家代表点，zoom 5~6
cities     城市     121 条  → 城市中心点，zoom 9
```

匹配顺序（`step6_locate`）：

1. **标题命中城市** → 用城市坐标，`country` 取该城市所属国（城市优先于国家）；
2. **标题命中（强证据）国家** → 用国家坐标；
3. **标题没中，退回摘要**：
   - 摘要里只有一个城市 → 采用；
   - 摘要里多个城市互相打架 → **放弃，输出 null 不猜**；
   - 摘要里多个国家 → 取**最先出现**的那个（导语主语通常是真事件地）；
4. **都没有**，且分类是 `markets`、来源是美股媒体 → 兜底记美国，`locate_basis="source"`。

**弱证据词**（`white house` / `wall street` / `kremlin` / `pentagon` 等）单独处理，
不单独决定地点 —— 白宫发言不必然发生在华盛顿。

### 踩过的坑：曼谷会议被判成中国（真实 bug，已修）

原实现把城市名混在国家 `aliases` 里，且"谁先匹配到用谁"。于是：

> 原文摘要：`Debt, AI and Ukraine dominated the conversation at the IMF-World Bank
> meetings in Bangkok, while China, the focus in 2018, slipped into the background.`
>
> `china` 在词典里排在 `thailand` 前面 → 整条被判成**中国**，而会议实际在**曼谷**。

修法：城市单独成表 + 城市优先 + 摘要多城市时不猜。
这个案例已固化在 `scripts/test_locate.py`，改定位逻辑后**必须**跑一遍：

```bash
python3 scripts/test_locate.py      # 8 条用例，应该全过
```

### 封面图是怎么来的

| 源 | RSS 里有图吗 | 取法 | 耗时 |
|---|---|---|---|
| MarketWatch | 有 `media:content` | 直接读 | 0 |
| NPR | 没有 | 抓页面 `og:image` | ~2.7s/条 |
| CNBC | 没有 | 抓页面 `og:image` | ~6s/条 |

放在**挑选出 20 条之后**执行，只为最终条目发请求，6 线程并发。
实测 17 条补抓 **10~19 秒**（串行要 1~2 分钟）。全部是绝对 URL。


> 为什么要有配额：财经源每次吐的条目远多于政治源（30 vs 10），
> 纯按热度排会让首页 60% 都是财经新闻，地图上也只剩美国一个点。
> 配额保证三个领域都有内容可展示，是"编辑推荐"逻辑的一部分。

---

## 四、本地运行步骤（每次开发的验收方法）

```bash
# 1. 进入项目根目录
cd WorldPulse-Daily

# 2. 安装依赖（只需第一次）
pip3 install -r requirements.txt

# 3. 运行流水线
python3 scripts/update_news.py
```

**预期输出**（已在开发机实测通过）：

```
[获取] ✓ NPR World 取得 10 条
[获取] ✓ CNBC World News 取得 30 条
[获取] 共取得原始新闻 100 条，可用源 6/6
[去重] 100 条 → 100 条（去掉 0 条重复）
[过滤] 保留最近 48 小时新闻：59 条
[分类] 保留 44 条（地缘冲突 5｜国际政治 16｜金融市场 23），不属于三领域丢弃 15 条
[定位] 44 条中 27 条匹配到地点，其余 17 条坐标为 null（不上地图）
[配额] 各领域入选：地缘冲突 5｜国际政治 7｜金融市场 8，合计 20 条
[翻译] 标题：成功 20 条，回退英文 0 条
[翻译] 摘要：成功 20 条，回退英文 0 条
[翻译] 标题失败率 0%（阈值 30%）
[输出] 已写入 data/news.json（20 条新闻，id 为 URL 哈希）
[归档] 已写入 2026-10-18 归档（20 条，概览已生成），索引共 1 天，班次 pm
[概览] 已写入 data/digest.json（20 条，地缘 5｜政治 7｜市场 8）
[日志] 已写入 data/logs/2026-10-18_HHMM.json（保留最近 30 份）
```

**验收检查**（对照方案「Day 1 验收要求」）：
1. ✅ 真实 RSS 新闻可获取（100 条原始数据，6/6 源可用）；
2. ✅ Python 输出有效 JSON（已用脚本校验全部字段合规）；
3. ✅ 分类结果可检查（日志直接给出三分类数量）；
4. ✅ 翻译失败时明确回退（`[EN]` 前缀），不生成假新闻；
5. ✅ 归档、概览、日志三份衍生数据都生成了（B2/B6/B4）；
6. 打开 `data/news.json` 逐条核对标题、来源、链接真实有效。

**翻译失败的说明**：默认免费接口 MyMemory 有每日次数限制，配额耗尽时会先尝试自动切备用源（B5），仍失败才回退英文。想稳定出中文：
- 注册 [DeepL 免费版](https://www.deepl.com/pro-api)（每月 50 万字符免费），拿到密钥后：
  ```bash
  export TRANSLATE_PROVIDER=deepl
  export TRANSLATE_API_KEY=你的密钥
  python3 scripts/update_news.py
  ```
- ⚠️ 密钥只放环境变量 / GitHub Secrets，**绝对不能写进代码或提交到仓库**。

---

## 五、GitHub 配置（Day 2 部署，一次性操作）

1. **推送代码到 GitHub 仓库**（建议 B 在 `feature/news-pipeline` 分支开发，测试通过后合并到 `main`）。
2. **开启 Pages**：仓库 `Settings` → `Pages` → Build and deployment → Source 选 **GitHub Actions**。
3. **配置翻译密钥（可选）**：`Settings` → `Secrets and variables` → `Actions`：
   - 添加 Secret：`TRANSLATE_API_KEY` = DeepL 密钥（不用可跳过）；
   - 可选变量 `TRANSLATE_PROVIDER`：`mymemory`（默认）/ `deepl` / `none`。
4. **手动触发测试**：`Actions` 页 → 选「更新新闻并发布网站」→ `Run workflow`。
5. **验收**：运行成功后，打开 `https://<你的用户名>.github.io/<仓库名>/`，
   再刷新 `data/news.json` 的 `updated_at` 是否更新为刚才的时间。

定时说明：cron 设了两班，**UTC 00:30 = 北京时间 08:30**（早班，覆盖欧美夜间新闻）和 **UTC 12:30 = 北京时间 20:30**（晚班，覆盖当天亚洲时段与美股盘中）。

关于定时任务的三个注意点：

1. GitHub 定时任务可能**延迟几分钟到几十分钟**，尤其高峰期，属正常现象；
2. 公开仓库**长期（约 60 天）无 push 活动**时，GitHub 会自动停用 schedule，
   重新 push 一次即可恢复 —— 这是 GitHub 的机制，不是脚本故障；
3. 除了定时，任何时候都能在 `Actions` 页手动 `Run workflow` 立即更新，答辩演示用这个。

---

## 六、热度评分规则（透明可解释）

```
heat = 新鲜度(0-50) + 主题相关(0-20) + 地理定位(0-10) + 来源基础(0-20)   上限 100

新鲜度   ：48 小时内线性衰减，越新分越高（50 × (1 - 新闻年龄/48h)）
主题相关 ：三领域关键词命中数 × 4，封顶 20
地理定位 ：词典匹配到可信地点 +10
来源基础 ：每个源固定分（主源 20，辅助源 18）
```

分类规则：统计标题+摘要中三个领域关键词的命中次数（英文词边界匹配），取最高者为该条分类；三个领域全部 0 命中的新闻直接丢弃。

定位规则：用 `data/locations.json` 词典匹配国家/地区名（如 Russia、Gaza、Beijing），**匹配不到就输出 null 坐标**，绝不乱放地图点——尤其是地缘政治新闻，提到某国 ≠ 事件发生在该国。

**已知局限（答辩时主动说明）**：当前实现是"标题/摘要中出现地名即定位"，多国新闻（如"美国宣布对俄制裁"）会定位到先匹配到的国家，可能不是事件发生地。这正是方案中"无法可靠定位的新闻应显示在列表里，但不在地图上随意放点"的边界——两天 MVP 采用词典方案，升级方向是只匹配"事件动词附近的地点"或接入地理编码服务。

---

## 七、异常保护（已实测验证）

| 场景 | 脚本行为 | 验证结果 |
|---|---|---|
| 所有 RSS 源不可达 | 退出码 2，**不覆盖旧 news.json**，Actions 不发布 | ✅ 实测通过（md5 前后一致） |
| 有效新闻 < 3 条 | 同上，保留最后一次有效数据 | ✅ 代码路径覆盖 |
| 翻译单条失败 | 该条回退英文原文并标 `[EN]`，流水线继续 | ✅ 实测通过 |
| **翻译失败率 > 30%**（B3） | **不覆盖 news.json**，保留上一期，退出码 3 | ✅ 实测通过（强制全失败，旧数据 md5 一致） |
| **主源配额耗尽**（B5） | 自动切备用源 `gtx` 继续翻 | ✅ 模拟响应验证（沙箱访问不了 Google） |
| 归档 / 概览 / 日志写入失败 | `try/except` 包住，**不影响** news.json | ✅ 代码路径覆盖 |
| 同一天跑两次 | 终版 `YYYY-MM-DD.json` 覆盖，班次 `am/pm` 各留一份 | ✅ 实测通过 |
| 归档超过 90 天 | 自动删除，`index.json` 同步清理 | ✅ 实测通过（构造 100/95/91 天前数据，30 天前保留） |
| 写 JSON 中途断电 | 临时文件 + 原子替换，旧文件不会被写坏 | ✅ `os.replace` 实现 |

**退出码约定**（`.github/workflows/update.yml` 据此判断）：

| 退出码 | 含义 | 线上表现 |
|---|---|---|
| `0` | 成功 | 数据已更新并发布 |
| `2` | 抓取失败（源全挂或有效新闻太少） | 保留上次数据，Actions 红叉告警 |
| `3` | 翻译服务异常（失败率 > 30%） | 保留上次数据，Actions 红叉告警 |

**重要原则**：失败时线上网站继续用上一次成功的数据 —— 「故障时仍能正常打开网站」。
红叉不是坏事：它让你第一时间知道翻译挂了，而不是过一周才发现满屏英文。

---

## 八、常见错误排查

| 症状 | 原因 | 解决 |
|---|---|---|
| `ModuleNotFoundError: feedparser` | 没装依赖 | `pip3 install -r requirements.txt` |
| 获取步骤全部 `✗` | 网络无法访问境外 RSS | 换网络环境，或把 `RSS_SOURCES` 换成可达源 |
| 新闻只有 8~15 条 | 源数量不足，或分类词典误杀（关键词没覆盖到） | ① 在 `RSS_SOURCES` 增源；② 看日志「分类」那行丢弃了多少条，把漏掉的关键词补进 `CATEGORY_KEYWORDS` |
| 输出条数不到 20 | 某领域当天新闻太少，配额补不满 | 属正常，配额是**软**的；如长期不足就增源 |
| 标题全是 `[EN]` 开头 | 免费翻译接口当天配额用尽，备用源也不可用 | 配 DeepL 密钥（`TRANSLATE_API_KEY`）一劳永逸；或等配额重置 |
| Actions 显示红叉、退出码 3 | 翻译失败率超 30%，按 B3 保护性跳过 | 看 `data/logs/` 里最新一份的 `translate.fail_ratio`，多半是配额问题 |
| `digest.json` 里某段 `text` 是空字符串 | 该领域当天 0 条（软配额下正常） | 不是 bug，前端遇到空串就不渲染那一段 |
| 归档目录只有 `-am` / `-pm` 没有终版 | 当日运行被 B3/B4 保护性跳过，没走到归档 | 属预期行为，次日正常运行会补上 |
| Actions 定时没跑 | GitHub 延迟或仓库闲置被停用 | 手动 Run workflow；push 一次代码 |
| Actions 权限报错 403 | workflow 权限未生效 | 确认使用本仓库的 `update.yml`（已声明 `contents: write` 等）；仓库 Settings → Actions → General → Workflow permissions 选 "Read and write" |
| Pages 404 | Pages Source 未选 GitHub Actions | 按第五节第 2 步设置 |
| Actions 全绿，但线上 `news.json` 是旧的 | **不要把「更新新闻」和「发布网站」拆成两个 job** | 拆开时发布 job 的 checkout 拿到的是本次运行开始时的旧 commit，会把更新前的数据发布出去。本仓库的 `update.yml` 已合并为单 job，请勿改回 |

---

## 九、答辩演示建议（B 的 2 分钟技术流程）

1. 打开终端，运行 `python3 scripts/update_news.py`，展示中文日志流水线；
2. 打开 `data/news.json`，指出真实新闻的 title/source/url 可点开核对，并强调 **id 是 URL 哈希**："同一条新闻明天还是这个 id，所以我们才能做历史归档和热度对比"；
3. 打开 `data/digest.json`，说明"今日概览"是**规则生成**的：每句话都能点回原文核对，不编内容、不预测；
4. 打开 `data/archive/index.json`，展示 90 天历史，说明这是"可回溯"的落地方式；
5. 打开 GitHub Actions 页面，手动 Run workflow，展示一个绿色任务里依次跑完「抓取 → 去重 → 过滤 → 分类 → 翻译 → 定位 → 评分 → 输出 → 归档 → 概览 → 日志 → 提交 → 发布」；
   然后打开线上 `https://<用户名>.github.io/WorldPulse-Daily/data/news.json`，确认 `updated_at` 是刚才的运行时间；
6. 强调异常保护（这是最容易拿分的地方）："翻译失败率超 30% 我们会**拒绝覆盖**线上数据，宁可少一期，也不让读者看到满屏英文"——可当场把 `TRANSLATE_PROVIDER=mymemory` 换成失效配置运行演示退出码 3。
