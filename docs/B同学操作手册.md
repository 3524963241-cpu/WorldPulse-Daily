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
| `requirements.txt` | Python 依赖清单 | ✅ 已完成 |
| `.github/workflows/update.yml` | 定时自动更新 + 发布 GitHub Pages | ✅ 已完成 |
| `docs/B同学操作手册.md` | 本手册 | ✅ |

---

## 二、RSS 源验证结果（已实测）

经真实网络测试，以下 3 个源稳定可用（BBC / Al Jazeera / Google News 在部分网络环境下不可达，故未采用）：

| 源 | 地址 | 实测 |
|---|---|---|
| NPR World | `https://feeds.npr.org/1004/rss.xml` | ✅ 10 条/次 |
| NPR Business | `https://feeds.npr.org/1006/rss.xml` | ✅ 10 条/次 |
| MarketWatch Top | `https://feeds.content.dowjones.io/public/rss/mw_topstories` | ✅ 10 条/次 |

源地址集中在 `update_news.py` 顶部的 `RSS_SOURCES` 配置区，更换/新增源只改这一处。

---

## 三、data/news.json 数据协议（已与 A 约定，冻结）

```json
{
  "updated_at": "2026-10-12T14:28:17Z",
  "news": [
    {
      "id": "news-001",
      "title": "中文标题（翻译失败时为 [EN] 英文原文）",
      "summary": "中文短摘要（同上回退规则）",
      "category": "geopolitics | politics | markets 之一",
      "country": "匹配到的中文地名，匹配不到为 null",
      "lat": 35.86,
      "lng": 104.19,
      "published_at": "2026-10-12T13:12:00Z（UTC，前端负责转北京时间）",
      "source": "NPR World",
      "url": "https://... 原文链接",
      "heat": 95
    }
  ]
}
```

规则要点：
- 最多 20 条，按热度降序，id 按 `news-001` 顺序编号；
- `lat/lng` 允许为 null —— 该新闻仍显示在列表，但不上地图；
- `heat` 是**编辑规则热度**（见第六节），不是全网真实搜索热度，A 需在页面标注。

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
[获取] ✓ NPR Business 取得 10 条
[获取] ✓ MarketWatch Top 取得 10 条
[去重] 30 条 → 30 条
[过滤] 保留最近 48 小时新闻：23 条
[分类] 保留 14 条（地缘冲突 4｜国际政治 2｜金融市场 8）
[翻译] 翻译成功 0 条，回退英文 14 条（标记为 [EN]）
[定位] 14 条中 6 条匹配到地点，其余 8 条坐标为 null（不上地图）
[输出] 已写入 data/news.json（14 条新闻）
```

**验收检查**（对照方案「Day 1 验收要求」）：
1. ✅ 真实 RSS 新闻可获取（30 条原始数据）；
2. ✅ Python 输出有效 JSON（已用脚本校验全部字段合规）；
3. ✅ 分类结果可检查（日志直接给出三分类数量）；
4. ✅ 翻译失败时明确回退（`[EN]` 前缀），不生成假新闻；
5. 打开 `data/news.json` 逐条核对标题、来源、链接真实有效。

**翻译失败的说明**：默认免费接口 MyMemory 有每日次数限制，配额耗尽时自动回退英文。想稳定出中文：
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

定时说明：cron 设为 UTC 00:30 = **北京时间 08:30**。GitHub 定时任务可能延迟几分钟到几十分钟；公开仓库长期无活动时定时任务可能被自动停用（正常 push 一次即可恢复）——这是 GitHub 的机制，不是脚本故障。

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
| 翻译接口配额耗尽/挂掉 | 该条回退英文原文并标 `[EN]`，流水线继续 | ✅ 实测通过（三种失败场景模拟） |
| 写 JSON 中途断电 | 临时文件 + 原子替换，旧文件不会被写坏 | ✅ `os.replace` 实现 |

**重要原则**：失败时线上网站继续用上一次成功的数据 —— 「故障时仍能正常打开网站」。

---

## 八、常见错误排查

| 症状 | 原因 | 解决 |
|---|---|---|
| `ModuleNotFoundError: feedparser` | 没装依赖 | `pip3 install -r requirements.txt` |
| 获取步骤全部 `✗` | 网络无法访问境外 RSS | 换网络环境，或把 `RSS_SOURCES` 换成可达源 |
| 新闻只有 8~10 条 | RSS 源每次只给最近 10 条，属正常 | 正常现象，满足"最多 20 条"要求 |
| 标题全是 `[EN]` 开头 | 翻译接口当日配额耗尽 | 正常回退；或配置 DeepL 密钥 |
| Actions 定时没跑 | GitHub 延迟或仓库闲置被停用 | 手动 Run workflow；push 一次代码 |
| Actions 权限报错 403 | workflow 权限未生效 | 确认使用本仓库的 `update.yml`（已声明 `contents: write` 等）；仓库 Settings → Actions → General → Workflow permissions 选 "Read and write" |
| Pages 404 | Pages Source 未选 GitHub Actions | 按第五节第 2 步设置 |

---

## 九、答辩演示建议（B 的 2 分钟技术流程）

1. 打开终端，运行 `python3 scripts/update_news.py`，展示中文日志流水线；
2. 打开 `data/news.json`，指出真实新闻的 title/source/url 可点开核对；
3. 打开 GitHub Actions 页面，手动 Run workflow，展示「更新新闻数据 → 发布到 GitHub Pages」两个绿色步骤；
4. 强调异常保护：「即使现在断网，网站仍然显示上次成功的数据」——可当场演示断网运行脚本退出码 2 且旧数据完好。
