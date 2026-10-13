/* ============================================================
   WorldPulse Daily —— 前端脚本（A 同学负责）

   下面这段是「示例实现」，作用是让占位页面能跑起来并显示数据，
   目的是帮 A 同学看清数据长什么样、怎么取。请随意删改或重写。

   ------------------------------------------------------------
   data/news.json 数据结构（后端由 B 同学维护，字段不会随便改）
   ------------------------------------------------------------
   {
     "updated_at": "2026-10-13T11:20:18Z",   // 数据更新时间，UTC，ISO 8601
     "news": [
       {
         "id":           "a1b2c3d4e5f6",     // 唯一 ID，由 URL 生成，稳定不变
         "title":        "巴基斯坦对前总理的据点实施紧急统治",
         "summary":      "……",                // 摘要，可能为空字符串
         "category":     "geopolitics",      // 三选一，见下方说明
         "country":      "巴基斯坦",           // 中文国家名；未定位到时为 null
         "lat":          30.3753,            // 纬度；未定位到时为 null
         "lng":          69.3451,            // 经度；未定位到时为 null
         "published_at": "2026-10-13T08:12:00Z",
         "source":       "NPR World",        // 来源名称
         "url":          "https://…",        // 原文链接，可直接跳转
         "heat":         96                  // 热度 0~100，整数，已按此降序排列
       }
     ]
   }

   category 三个取值（做筛选/地图配色时直接用）：
     "geopolitics"  地缘冲突
     "politics"     国际政治
     "markets"      金融市场

   重要提醒（地图功能必看）：
     lat / lng 为 null 时代表「无法确定事件发生地」，
     这类新闻**不要**在地图上打点，只在列表里显示即可。
     当前约 20%~40% 的新闻坐标为 null，属正常现象。
   ============================================================ */

const CATEGORY_LABEL = {
  geopolitics: '地缘冲突',
  politics: '国际政治',
  markets: '金融市场'
};

// 相对路径，在本地和 GitHub Pages 上都能用
const DATA_URL = 'data/news.json';

function formatTime(iso) {
  if (!iso) return '时间未知';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '时间未知';
  return d.toLocaleString('zh-CN', { hour12: false });
}

function renderNews(newsList) {
  const container = document.getElementById('news-list');
  if (!newsList.length) {
    container.innerHTML = '<p class="loading">暂无新闻数据</p>';
    return;
  }

  container.innerHTML = newsList
    .map(item => {
      const place = item.country ? `📍 ${item.country}` : '📍 地点未确定';
      const label = CATEGORY_LABEL[item.category] || item.category;
      return `
        <article class="news-item">
          <h2><a href="${item.url}" target="_blank" rel="noopener">${item.title}</a></h2>
          <p>${item.summary || ''}</p>
          <div class="meta">
            <span>${label}</span> · <span>${place}</span> ·
            <span>${item.source}</span> · <span>${formatTime(item.published_at)}</span> ·
            <span>热度 ${item.heat}</span>
          </div>
        </article>`;
    })
    .join('');
}

async function loadNews() {
  try {
    const res = await fetch(DATA_URL, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    renderNews(data.news || []);
    document.getElementById('update-time').textContent =
      '数据更新时间：' + formatTime(data.updated_at);
  } catch (err) {
    document.getElementById('news-list').innerHTML =
      '<p class="loading">新闻加载失败：' + err.message + '</p>';
  }
}

loadNews();
