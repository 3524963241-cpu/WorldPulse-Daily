#!/usr/bin/env node
/**
 * id 契约回归测试（B 侧本地版，等价于 A 的 id-contract-test.js）
 *
 * 校验三条契约：
 *   C1 同一期内 id 唯一
 *   C2 同一期内 id 格式为 12 位小写十六进制
 *   C3 跨期：同一条新闻（规范化 url 相同）必须是同一个 id
 *
 * 用法：
 *   node .workbuddy/tmp/id-contract-test.js           # 读本地 data/
 *   node .workbuddy/tmp/id-contract-test.js --plain   # 不请求注入，纯本地文件
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '../..');
const PLAIN = process.argv.includes('--plain');

function normalizeUrl(u) {
  try {
    const p = new URL(u.trim());
    const drop = new Set(['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content']);
    const keep = [...p.searchParams.entries()].filter(([k]) => !drop.has(k));
    keep.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
    const q = keep.map(([k, v]) => `${k}=${v}`).join('&');
    return `${p.protocol}//${p.host.toLowerCase()}${p.pathname}${q ? '?' + q : ''}`;
  } catch {
    return u.trim();
  }
}

function load(file) {
  const p = path.join(ROOT, file);
  if (!fs.existsSync(p)) return null;
  const d = JSON.parse(fs.readFileSync(p, 'utf8'));
  return Array.isArray(d.news) ? d.news : null;
}

// 收集所有可用的期次
const periods = [];
const cur = load('data/news.json');
if (cur) periods.push({ name: 'news.json', news: cur });

const archDir = path.join(ROOT, 'data/archive');
if (fs.existsSync(archDir)) {
  for (const f of fs.readdirSync(archDir).sort()) {
    if (!/^\d{4}-\d{2}-\d{2}\.json$/.test(f)) continue;
    const news = load(`data/archive/${f}`);
    if (news) periods.push({ name: f, news });
  }
}

let fail = 0;
const RE = /^[0-9a-f]{12}$/;

console.log(`读取 ${periods.length} 个期次${PLAIN ? '（--plain）' : ''}\n`);

// C1 + C2
for (const p of periods) {
  const ids = p.news.map(n => n.id);
  const dup = ids.filter((v, i) => ids.indexOf(v) !== i);
  const badFmt = ids.filter(v => !RE.test(v));
  const ok1 = dup.length === 0, ok2 = badFmt.length === 0;
  if (!ok1 || !ok2) fail++;
  console.log(`[${p.name}] ${p.news.length} 条`);
  console.log(`  C1 唯一      ${ok1 ? '✓' : '✗ 重复 ' + [...new Set(dup)].join(',')}`);
  console.log(`  C2 格式合法  ${ok2 ? '✓' : '✗ 非法 ' + [...new Set(badFmt)].join(',')}`);
}

// C3 跨期一致性
if (periods.length >= 2) {
  console.log('\nC3 跨期一致性');
  const seen = new Map();   // normUrl -> [{id, period}]
  for (const p of periods) {
    for (const n of p.news) {
      const k = normalizeUrl(n.url);
      if (!seen.has(k)) seen.set(k, []);
      seen.get(k).push({ id: n.id, period: p.name });
    }
  }
  let checked = 0, bad = 0;
  for (const [url, list] of seen) {
    if (list.length < 2) continue;
    checked++;
    const uniq = new Set(list.map(x => x.id));
    if (uniq.size > 1) {
      bad++;
      console.log(`  ✗ ${url}`);
      console.log(`     ${list.map(x => `${x.period}:${x.id}`).join('  ')}`);
    }
  }
  console.log(`  跨期重复出现的新闻 ${checked} 条，id 不一致 ${bad} 条 ${bad === 0 ? '✓' : '✗'}`);
  if (bad > 0) fail++;
} else {
  console.log('\nC3 跨期一致性：期次不足 2 个，跳过');
}

console.log(`\n${fail === 0 ? '全部通过' : fail + ' 项失败'}`);
process.exit(fail === 0 ? 0 : 1);
