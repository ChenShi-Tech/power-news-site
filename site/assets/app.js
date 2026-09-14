/* ==========================================================================
   电力动态 POWHOT — 应用逻辑
   数据源: data/news.json（列表） + data/bodies/<id>.json（详情，按需加载）
   ========================================================================== */

(function () {
  'use strict';

  const CATEGORIES = ['政策法规', '电力市场', '新能源', '电网建设', '安全生产', '资质监管', '企业动态', '数据统计'];
  const LS_STAR = 'powhot.stars';
  const LS_THEME = 'powhot.theme';

  const state = {
    data: null,
    items: [],
    q: '',
    org: '',
    day: '',
    orgFilter: '',
    stars: new Set(),
    view: 'all',
  };

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  /* ------------------------------------------------------------ 工具 */

  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  const WEEK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

  function fmtDate(iso) {
    if (!iso) return '未标注日期';
    const [y, m, d] = iso.split('-').map(Number);
    return `${m}月${d}日`;
  }
  function fmtDateFull(iso) {
    if (!iso) return '';
    const [y, m, d] = iso.split('-').map(Number);
    return `${y}年${m}月${d}日`;
  }
  function weekOf(iso) {
    if (!iso) return '';
    const dt = new Date(iso + 'T00:00:00');
    return isNaN(dt) ? '' : WEEK[dt.getDay()];
  }
  function isToday(iso) {
    const n = new Date();
    const t = `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}-${String(n.getDate()).padStart(2, '0')}`;
    return iso === t;
  }

  // 机构 → 徽标色
  const ORG_COLOR = {
    '国家能源局': '#176b75',
    '国家发改委': '#8a5a2b',
    '中电联': '#4a6fa5',
    '南方电网': '#2f7d5c',
    '国家电网': '#b3402a',
    '北极星电力网': '#5a6470',
  };
  function orgColor(org) {
    if (ORG_COLOR[org]) return ORG_COLOR[org];
    if (org && org.indexOf('区域能源监管局') === 0) return '#6a4f96';
    return '#8a94a2';
  }

  // 机构显示名（长名转短名）
  function orgLabel(org) {
    return String(org || '').replace(/^区域能源监管局-(.+)$/, '$1能监局');
  }

  /* ------------------------------------------------------------ 数据 */

  async function loadData() {
    const res = await fetch('data/news.json', { cache: 'no-cache' });
    if (!res.ok) throw new Error('数据加载失败 ' + res.status);
    state.data = await res.json();
    state.items = state.data.items || [];
  }

  const bodyCache = new Map();
  async function loadBody(id) {
    if (bodyCache.has(id)) return bodyCache.get(id);
    try {
      const res = await fetch(`data/bodies/${id}.json`);
      if (!res.ok) throw new Error('no body');
      const j = await res.json();
      bodyCache.set(id, j);
      return j;
    } catch (e) {
      const empty = { id, paragraphs: [], attachments: [] };
      bodyCache.set(id, empty);
      return empty;
    }
  }

  /* ------------------------------------------------------------ 收藏 */

  function loadStars() {
    try { state.stars = new Set(JSON.parse(localStorage.getItem(LS_STAR) || '[]')); }
    catch (e) { state.stars = new Set(); }
  }
  function saveStars() {
    try { localStorage.setItem(LS_STAR, JSON.stringify(Array.from(state.stars))); } catch (e) {}
    const el = $('#star-count');
    if (el) el.textContent = state.stars.size ? String(state.stars.size) : '';
  }
  function toggleStar(id) {
    if (state.stars.has(id)) state.stars.delete(id); else state.stars.add(id);
    saveStars();
  }

  /* ------------------------------------------------------------ 主题 */

  function applyTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', t === 'dark' ? '#13191c' : '#faf9f6');
    $$('#theme-toggle button').forEach((b) => b.classList.toggle('active', b.dataset.themeVal === t));
    try { localStorage.setItem(LS_THEME, t); } catch (e) {}
  }

  /* ------------------------------------------------------------ 过滤 */

  function currentList() {
    let arr = state.items.slice();
    if (state.view === 'featured') arr = arr.filter((it) => it.ai && it.body_len > 200);
    if (state.view === 'org') arr = arr.filter((it) => it.org === state.org);
    if (state.view === 'cat') arr = arr.filter((it) => it.category === state.org);
    if (state.view === 'day') arr = arr.filter((it) => it.date === state.day);
    if (state.view === 'star') arr = arr.filter((it) => state.stars.has(it.id));
    if (state.orgFilter) arr = arr.filter((it) => it.org === state.orgFilter);
    if (state.q) {
      const q = state.q.toLowerCase();
      arr = arr.filter((it) =>
        (it.title || '').toLowerCase().includes(q) ||
        (it.excerpt || '').toLowerCase().includes(q) ||
        (it.ai || '').toLowerCase().includes(q) ||
        (it.org || '').toLowerCase().includes(q) ||
        (it.tags || []).join(' ').toLowerCase().includes(q)
      );
    }
    return arr;
  }

  function groupByDay(items) {
    const map = new Map();
    items.forEach((it) => {
      const k = it.date || '';
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(it);
    });
    return Array.from(map.entries()).sort((a, b) => (a[0] < b[0] ? 1 : a[0] > b[0] ? -1 : 0));
  }

  /* ------------------------------------------------------------ 渲染：侧栏 */

  function renderSidebar() {
    const cats = state.data.stats.by_category || {};
    $('#nav-cats').innerHTML = CATEGORIES
      .filter((c) => cats[c])
      .map((c) => navLink(`#/cat/${encodeURIComponent(c)}`, 'cat:' + c, c, cats[c]))
      .join('');

    const orgs = state.data.stats.by_org || {};
    $('#nav-orgs').innerHTML = Object.keys(orgs)
      .map((o) => navLink(
        `#/org/${encodeURIComponent(o)}`, 'org:' + o,
        orgLabel(o), orgs[o], orgColor(o)
      ))
      .join('');

    const r = state.data.stats.date_range || [];
    $('#sidebar-meta').innerHTML =
      `${esc(r[0] || '')} ~ ${esc(r[1] || '')}<br>共 ${state.data.stats.total} 条 · ${state.data.stats.days} 天`;
  }

  function navLink(href, key, label, count, color) {
    return `<a class="side-link" href="${href}" data-nav="${esc(key)}">
      ${color ? `<span class="org-dot" style="background:${color}"></span>` : ''}
      <span class="side-label">${esc(label)}</span>
      <span class="side-count">${count}</span>
    </a>`;
  }

  function markActiveNav(key) {
    $$('.side-link, .m-tab').forEach((el) => {
      const n = el.dataset.nav;
      const on = n === key;
      el.classList.toggle('side-link-active', on && el.classList.contains('side-link'));
      el.classList.toggle('m-tab-active', on && el.classList.contains('m-tab'));
    });
  }

  /* ------------------------------------------------------------ 渲染：列表页 */

  function pageHeader(title, sub, tabs, activeTab) {
    const tabsHtml = tabs
      ? `<div class="tabbar">${tabs.map((t) => `
          <a class="tab${t.key === activeTab ? ' tab-active' : ''}" href="${t.href}">${esc(t.label)}${
            t.count != null ? `<span class="tab-count">${t.count}</span>` : ''
          }</a>`).join('')}</div>`
      : '';
    return `<section class="page-header">
      <h1 class="page-title">${esc(title)}</h1>
      ${sub ? `<p class="page-sub">${esc(sub)}</p>` : ''}
      ${tabsHtml}
    </section>`;
  }

  function toolbarHtml() {
    const orgs = state.data.stats.by_org || {};
    const opts = ['<option value="">全部来源</option>']
      .concat(Object.keys(orgs).map((o) =>
        `<option value="${esc(o)}"${state.orgFilter === o ? ' selected' : ''}>${esc(o)}（${orgs[o]}）</option>`))
      .join('');
    return `<div class="toolbar">
      <div class="toolbar-spacer"></div>
      <div class="select-wrap">
        <select class="select" id="org-filter">${opts}</select>
      </div>
      <div class="search-wrap">
        <input class="search" id="search" type="search" placeholder="搜索标题、摘要、标签" value="${esc(state.q)}" autocomplete="off">
        <svg class="search-icon" viewBox="0 0 16 16"><circle cx="7" cy="7" r="4.6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M10.5 10.5 14 14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
      </div>
    </div>`;
  }

  function metaRowHtml(list) {
    const days = new Set(list.map((i) => i.date)).size;
    const parts = [`共 <strong>${list.length}</strong> 条`];
    if (days > 1) parts.push(`${days} 天`);
    if (state.q) parts.push(`搜索“${esc(state.q)}”`);
    const clear = (state.q || state.orgFilter)
      ? ` <span class="sep">·</span> <button class="link-btn" id="clear-filter">清除筛选</button>` : '';
    return `<div class="meta-row">${parts.join(' <span class="sep">·</span> ')}${clear}</div>`;
  }

  /* ------------------------------------------------------------ 配图 */

  function mediaHtml(images, opts) {
    opts = opts || {};
    if (!images || !images.length) return '';
    const max = opts.max || 6;
    const list = images.slice(0, max);
    return `<div class="media-grid" data-count="${list.length}">
      ${list.map((src, i) => `<button type="button" class="media-cell" data-src="${esc(src)}" aria-label="查看大图 ${i + 1}/${list.length}">
        <img class="media-img" src="${esc(src)}" loading="lazy" decoding="async" alt="">
      </button>`).join('')}
    </div>`;
  }

  function openLightbox(src) {
    const el = document.createElement('div');
    el.className = 'lightbox';
    el.innerHTML = `<button class="lightbox-close" aria-label="关闭">
        <svg viewBox="0 0 16 16" width="16" height="16"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
      </button><img src="${esc(src)}" alt="">`;
    const close = () => el.remove();
    el.addEventListener('click', close);
    document.addEventListener('keydown', function onKey(e) {
      if (e.key === 'Escape') { close(); document.removeEventListener('keydown', onKey); }
    });
    document.body.appendChild(el);
  }

  function cardHtml(it, opts) {
    opts = opts || {};
    const starred = state.stars.has(it.id);
    const hasAi = !!it.ai;
    const showAi = hasAi && !opts.forceExcerpt;

    const aiBlock = showAi ? `<div class="ai-block">
        <div class="ai-block-label">
          <svg viewBox="0 0 12 12"><path d="M6 .8 7.5 4.4 11.2 6 7.5 7.6 6 11.2 4.5 7.6.8 6 4.5 4.4z" fill="currentColor"/></svg>
          AI 摘要
        </div>
        <p>${esc(it.ai)}</p>
      </div>` : '';

    // 原文摘录：与 AI 摘要并存展示（用户要求保留两个版本）
    let excerptBlock = '';
    if (it.excerpt) {
      const same = hasAi && it.excerpt.slice(0, 40) === it.ai.slice(0, 40);
      if (!same) {
        excerptBlock = `<div class="card-src"><q>原文</q> ${esc(it.excerpt)}</div>`;
      }
    }

    const tags = (it.tags || []).slice(0, opts.maxTags || 3)
      .map((t) => `<span class="tag">#${esc(t)}</span>`).join('');

    // 头部右侧：仅当缺少 AI 摘要时标注"原文摘录"，避免与卡片内 AI 摘要块重复
    const scoreHtml = hasAi ? ''
      : `<span class="card-score score-excerpt">原文摘录</span>`;

    return `<article class="timeline-card" data-id="${it.id}">
      <div class="card-head">
        <div class="card-head-left">
          <span class="card-org"><span class="org-dot" style="background:${orgColor(it.org)}"></span>${esc(orgLabel(it.org))}</span>
          <span class="card-col">${esc(it.column || '动态')}</span>
        </div>
        <div class="card-head-right">
          ${scoreHtml}
          <button class="card-star${starred ? ' on' : ''}" data-star="${it.id}" title="${starred ? '取消收藏' : '收藏'}" aria-label="收藏">
            <svg viewBox="0 0 16 16"><path d="M8 1.8l2 4.1 4.5.6-3.3 3.2.8 4.5L8 12.1l-4 2.1.8-4.5L1.5 6.5 6 5.9z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>
          </button>
        </div>
      </div>
      <h3 class="card-title">${esc(it.short_title || it.title)}</h3>
      ${aiBlock}
      ${excerptBlock}
      ${mediaHtml(it.images, { max: 3 })}
      <div class="card-foot">
        <span class="card-cat cat-${esc(it.category)}">${esc(it.category)}</span>
        ${tags}
        ${it.attachment_count ? `<span class="card-attach">
          <svg width="11" height="11" viewBox="0 0 12 12"><path d="M7.4 2.6 3.9 6.1a1.6 1.6 0 0 0 2.3 2.3l3.9-3.9a2.6 2.6 0 0 0-3.7-3.7L2.7 4.5" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
          ${it.attachment_count} 个附件</span>` : ''}
        ${it.body_len > 60 ? `<span class="card-more">全文 ${it.body_len} 字 ›</span>` : ''}
      </div>
    </article>`;
  }

  function timelineHtml(list) {
    const groups = groupByDay(list);
    return `<div class="timeline">${groups.map(([day, arr]) => `
      <section class="timeline-day">
        <div class="timeline-day-head">
          <h2 class="timeline-date">
            <span class="timeline-date-main">${esc(isToday(day) ? '今天' : fmtDate(day))}</span>
            <span class="timeline-date-week">${esc(weekOf(day))}</span>
            <span class="timeline-day-meta">${arr.length} 条</span>
          </h2>
        </div>
        <div class="timeline-day-items">
          ${arr.map((it) => `<div class="timeline-item">
            <div class="timeline-time">${esc(it.time || '')}</div>
            <div class="timeline-rail"><span class="timeline-dot"></span></div>
            ${cardHtml(it)}
          </div>`).join('')}
        </div>
      </section>`).join('')}</div>`;
  }

  function renderList(opts) {
    const list = currentList();
    const view = $('#view');
    const tabs = [{ key: 'all', href: '#/', label: '全部', count: state.items.length }]
      .concat(CATEGORIES.filter((c) => (state.data.stats.by_category || {})[c])
        .map((c) => ({ key: c, href: `#/cat/${encodeURIComponent(c)}`, label: c, count: state.data.stats.by_category[c] })));

    const activeTab = state.view === 'cat' ? state.org : (state.view === 'all' ? 'all' : null);

    view.innerHTML = `<div class="page">
      ${pageHeader(opts.title, opts.sub, tabs, activeTab)}
      ${toolbarHtml()}
      ${metaRowHtml(list)}
      ${list.length ? timelineHtml(list) : emptyHtml(opts.emptyTitle, opts.emptySub)}
    </div>`;

    bindListEvents();
  }

  function emptyHtml(title, sub) {
    return `<div class="empty">
      <svg class="empty-icon" viewBox="0 0 40 40"><polygon points="20,5 35,20 20,35 5,20" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="20" cy="20" r="4" fill="none" stroke="currentColor" stroke-width="2"/></svg>
      <p class="empty-title">${esc(title || '没有匹配的内容')}</p>
      <p class="empty-sub">${esc(sub || '试试调整筛选条件或搜索词')}</p>
    </div>`;
  }

  /* ------------------------------------------------------------ 列表事件 */

  let searchTimer = null;
  function bindListEvents() {
    const s = $('#search');
    if (s && !s.dataset.bound) {
      s.dataset.bound = '1';
      s.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
          state.q = s.value.trim();
          const v = $('#view');
          const list = currentList();
          const meta = v.querySelector('.meta-row');
          if (meta) meta.outerHTML = metaRowHtml(list);
          const tl = v.querySelector('.timeline');
          const em = v.querySelector('.empty');
          const html = list.length ? timelineHtml(list) : emptyHtml();
          if (tl) tl.outerHTML = html;
          else if (em) em.outerHTML = html;
          bindListEvents();
        }, 180);
      });
    }

    const sel = $('#org-filter');
    if (sel && !sel.dataset.bound) {
      sel.dataset.bound = '1';
      sel.addEventListener('change', () => {
        state.orgFilter = sel.value;
        renderCurrent();
      });
    }

    const clr = $('#clear-filter');
    if (clr && !clr.dataset.bound) {
      clr.dataset.bound = '1';
      clr.addEventListener('click', () => {
        state.q = ''; state.orgFilter = '';
        renderCurrent();
      });
    }
  }

  /* ------------------------------------------------------------ 详情页 */

  async function renderDetail(id) {
    const it = state.items.find((x) => x.id === id);
    const view = $('#view');
    if (!it) {
      view.innerHTML = `<div class="page">${emptyHtml('找不到这条动态', '它可能已从数据源中移除')}
        <p style="text-align:center"><a class="btn" href="#/">返回列表</a></p></div>`;
      return;
    }

    const starred = state.stars.has(it.id);
    const body = await loadBody(it.id);
    const paras = (body.paragraphs || []).filter((p) => p && p.trim());
    const bodyChars = paras.join('').length;

    const meta = [
      `<span class="card-org"><span class="org-dot" style="background:${orgColor(it.org)}"></span>${esc(orgLabel(it.org))}</span>`,
      it.column ? esc(it.column) : '',
      `${esc(fmtDateFull(it.date))}${it.time ? ' ' + esc(it.time) : ''}`,
      weekOf(it.date) ? esc(weekOf(it.date)) : '',
    ].filter(Boolean).join('<span class="dot"></span>');

    const related = state.items
      .filter((x) => x.id !== it.id && x.category === it.category)
      .slice(0, 5);

    view.innerHTML = `<div class="page-wide">
      <div class="detail-top">
        <a class="back-link" href="#" id="back">
          <svg viewBox="0 0 16 16"><path d="M10 3.5 5.5 8 10 12.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
          返回
        </a>
        <div class="detail-top-right">
          <span class="card-cat cat-${esc(it.category)}">${esc(it.category)}</span>
          <button class="card-star${starred ? ' on' : ''}" data-star="${it.id}" aria-label="收藏" style="width:26px;height:26px">
            <svg viewBox="0 0 16 16" style="width:16px;height:16px"><path d="M8 1.8l2 4.1 4.5.6-3.3 3.2.8 4.5L8 12.1l-4 2.1.8-4.5L1.5 6.5 6 5.9z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>
          </button>
        </div>
      </div>

      <h1 class="detail-title">${esc(it.title)}</h1>
      <div class="detail-meta">${meta}</div>

      ${it.ai ? `<div class="panel panel-ai">
        <h2 class="panel-title">
          <svg viewBox="0 0 12 12"><path d="M6 .8 7.5 4.4 11.2 6 7.5 7.6 6 11.2 4.5 7.6.8 6 4.5 4.4z" fill="currentColor"/></svg>
          AI 摘要
        </h2>
        <p>${esc(it.ai)}</p>
      </div>` : `<div class="panel panel-ai">
        <h2 class="panel-title">
          <svg viewBox="0 0 14 14"><rect x="2" y="2" width="10" height="10" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>
          摘要
        </h2>
        <p>${esc(it.excerpt || '本条暂无摘要。')}</p>
        <p class="hint">该条目采集时尚未启用 AI 摘要流程，以上为原文摘录。</p>
      </div>`}

      <h2 class="section-title">
        <svg viewBox="0 0 16 16"><path d="M4 2.5h6l3 3v8a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1z" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M10 2.5v3h3" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>
        原文
        ${bodyChars ? `<span class="section-note">${bodyChars} 字</span>` : ''}
      </h2>
      ${mediaHtml(it.images, { max: 6 })}
      ${paras.length ? `<div class="prose">${paras.map((p) => `<p>${esc(p)}</p>`).join('')}</div>`
        : `<div class="origbox origbox-missing">
            <p>该来源未收录可展示的正文，站内仅提供摘要。</p>
           </div>`}

      ${(body.attachments || []).length ? `<div class="panel" style="margin-top:20px">
        <h2 class="panel-title">附件（${body.attachments.length}）</h2>
        ${body.attachments.map((a) => `<p class="attach-line">${esc(a)}</p>`).join('')}
      </div>` : ''}

      <div class="orig-foot">
        <span>源站原文</span>
        <a class="btn" href="${esc(it.url)}" target="_blank" rel="noopener noreferrer">
          访问源站
          <svg viewBox="0 0 14 14"><path d="M5.5 3H3.6A1.6 1.6 0 0 0 2 4.6v5.8A1.6 1.6 0 0 0 3.6 12h5.8A1.6 1.6 0 0 0 11 10.4V8.5M8.5 2H12v3.5M12 2 6.8 7.2" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </a>
      </div>

      <div class="card-foot" style="margin-top:18px">
        ${(it.tags || []).map((t) => `<span class="tag">#${esc(t)}</span>`).join('')}
      </div>

      ${related.length ? `<div class="related">
        <h2 class="related-title">相关阅读 · ${esc(it.category)}</h2>
        <div class="related-list">
          ${related.map((r) => `<a class="related-item" href="#/item/${r.id}">
            <span class="related-date">${esc(fmtDate(r.date))}</span>
            <span>${esc(r.short_title || r.title)}</span>
          </a>`).join('')}
        </div>
      </div>` : ''}
    </div>`;

    $('#back').addEventListener('click', (e) => { e.preventDefault(); history.back(); });
  }

  /* ------------------------------------------------------------ 主题页 */

  const GROUP_BLURB = {
    '机构与主体': '按主管部门、电网企业与市场主体追踪：谁发了什么、又在推什么',
    '区域市场': '按省份追踪电力市场建设、交易组织与工程进展',
    '主题方向': '按业务方向深挖：市场、电价、消纳、储能、安全与许可',
  };

  let topicsCache = null;
  async function loadTopics() {
    if (!topicsCache) {
      const r = await fetch('data/topics.json', { cache: 'no-cache' });
      topicsCache = await r.json();
    }
    return topicsCache;
  }

  async function renderTopics() {
    const data = await loadTopics();
    $('#view').innerHTML = `<div class="page">
      ${pageHeader('按主题看电力', `${data.total} 个主题，持续汇集近期焦点与精选`)}
      ${data.groups.map((g) => `
        <section class="topics-group">
          <div class="topics-group-head">
            <h2 class="topics-group-name">${esc(g.name)}</h2>
            <p class="topics-group-blurb">${esc(GROUP_BLURB[g.name] || '')}</p>
          </div>
          <div class="topics-grid">
            ${g.cards.map((c) => `<a class="topics-card" href="#/topic/${encodeURIComponent(c.name)}">
              <span class="topics-card-name">${esc(c.name)}</span>
              <span class="topics-card-def">${esc(c.blurb)}</span>
              <span class="topics-card-count">查看 ${c.count} 条精选 →</span>
            </a>`).join('')}
          </div>
        </section>`).join('')}
    </div>`;
  }

  async function renderTopicDetail(name) {
    const data = await loadTopics();
    let card = null;
    data.groups.forEach((g) => g.cards.forEach((c) => { if (c.name === name) card = c; }));
    if (!card) {
      $('#view').innerHTML = `<div class="page">${emptyHtml('找不到这个主题', '它可能因条目不足而未被收录')}</div>`;
      return;
    }
    const ids = new Set(card.ids);
    const list = state.items.filter((it) => ids.has(it.id));
    $('#view').innerHTML = `<div class="page">
      ${pageHeader(card.name, card.blurb)}
      ${toolbarHtml()}
      ${metaRowHtml(list)}
      ${list.length ? timelineHtml(list) : emptyHtml()}
    </div>`;
    bindListEvents();
  }

  /* ------------------------------------------------------------ 报告页 */

  let reportsCache = null;
  async function loadReports() {
    if (!reportsCache) {
      const r = await fetch('data/reports.json', { cache: 'no-cache' });
      reportsCache = await r.json();
    }
    return reportsCache;
  }

  const REPORT_META = {
    daily: { kicker: 'DAILY', unit: '今日', side: 'date' },
    weekly: { kicker: 'WEEKLY', unit: '本周', side: 'week' },
    monthly: { kicker: 'MONTHLY', unit: '本月', side: 'month' },
  };

  async function renderReports(kind, key) {
    const data = await loadReports();
    const list = data[kind] || [];
    const view = $('#view');
    if (!list.length) {
      view.innerHTML = `<div class="page">${pageHeader('报告', '')}${emptyHtml('暂无报告', '等下一次采集完成后会自动生成')}</div>`;
      return;
    }
    let cur = key ? list.find((r) => r.key === key) : null;
    if (!cur) cur = list[0];

    const meta = REPORT_META[kind] || REPORT_META.daily;

    // 左侧目录：按「月」（日报/周报）或「年」（月报）分组
    const groups = new Map();
    const monthOf = (r) => {
      if (kind === 'monthly') return r.key.slice(5, 7);
      if (kind === 'weekly') return r.range[0].slice(5, 7);
      return r.key.slice(5, 7);
    };
    const numOf = (r) => {
      if (kind === 'monthly') return r.key.slice(5);
      if (kind === 'weekly') return 'W' + r.key.slice(-2);
      return String(Number(r.key.slice(8, 10)));
    };
    list.forEach((r) => {
      const gk = kind === 'monthly' ? r.key.slice(0, 4) + ' 年' : `${Number(monthOf(r))} 月`;
      if (!groups.has(gk)) groups.set(gk, []);
      groups.get(gk).push(r);
    });

    const idSet = new Set(cur.ids);
    const stories = state.items.filter((it) => idSet.has(it.id));
    const tabHref = (k) => `#/${k}/${cur.key}`;

    view.innerHTML = `<div class="report-layout">
      <aside class="report-side">
        ${Array.from(groups.entries()).map(([gk, arr]) => `
          <div class="report-side-month">
            <div class="report-side-month-head">
              <span class="report-side-month-name">${esc(gk)}</span>
              <span class="report-side-month-count">${arr.length}</span>
            </div>
            <div class="report-side-day-list">
              ${arr.map((r) => `<a class="report-side-day${r.key === cur.key ? ' active' : ''}" href="#/${kind}/${r.key}">
                <span class="report-side-day-num">${esc(numOf(r))}</span>
                <span class="report-side-day-headline">${esc((state.items.find((x) => x.id === r.ids[0]) || {}).short_title || '')}</span>
              </a>`).join('')}
            </div>
          </div>`).join('')}
      </aside>

      <main class="report-main">
        <div class="seg" style="margin-bottom:18px">
          <a class="seg-btn${kind === 'daily' ? ' active' : ''}" href="${tabHref('daily')}">日报</a>
          <a class="seg-btn${kind === 'weekly' ? ' active' : ''}" href="${tabHref('weekly')}">周报</a>
          <a class="seg-btn${kind === 'monthly' ? ' active' : ''}" href="${tabHref('monthly')}">月报</a>
        </div>

        <div class="report-head">
          <div class="report-kicker">${esc(meta.kicker)}</div>
          <div class="report-range">${esc(cur.range[0])} — ${esc(cur.range[1])}</div>
          <h1 class="report-title">${esc(meta.unit)}的 ${cur.count} 件电力大事</h1>
          <div class="report-stat">
            <span>${cur.count} 条核心资讯</span>
            <span class="dot"></span>
            <span>约 ${cur.read_min} 分钟</span>
          </div>
        </div>

        <div class="chip-row">
          ${Object.entries(cur.by_category).map(([c, n]) => `<a class="chip" href="#/cat/${encodeURIComponent(c)}">${esc(c)}<b>${n}</b></a>`).join('')}
        </div>

        ${stories.map((it, i) => `<article class="report-story">
          <div class="report-story-marker">${String(i + 1).padStart(2, '0')}</div>
          <div class="report-story-body">
            <div class="report-story-meta">
              <span class="mono">${esc(fmtDate(it.date))}</span>
              <span class="dot"></span>
              <span>${esc(it.category)}</span>
              <span class="dot"></span>
              <span>${esc(orgLabel(it.org))}</span>
            </div>
            <a href="#/item/${it.id}"><h3 class="report-story-title">${esc(it.short_title || it.title)}</h3></a>
            <p class="report-story-summary">${esc(it.ai || it.excerpt || '')}</p>
            ${mediaHtml(it.images, { max: 3 })}
            <div class="report-story-sources">
              <span class="report-source">
                <span class="report-source-label">来源</span>
                <span class="report-source-name">${esc(it.org)}</span>
              </span>
              <a class="report-source-action" href="${esc(it.url)}" target="_blank" rel="noopener noreferrer">原文</a>
              <a class="report-source-action" href="#/item/${it.id}">站内详情</a>
            </div>
          </div>
        </article>`).join('')}
      </main>
    </div>`;
    window.scrollTo(0, 0);
  }

  /* ------------------------------------------------------------ 关于页 */

  function renderAbout() {
    const s = state.data.stats;
    const orgs = Object.entries(s.by_org || {});
    const maxOrg = Math.max.apply(null, orgs.map((o) => o[1]).concat([1]));
    const cats = Object.entries(s.by_category || {});
    const maxCat = Math.max.apply(null, cats.map((c) => c[1]).concat([1]));

    $('#view').innerHTML = `<div class="page">
      ${pageHeader('关于本站', '电力动态 POWHOT — 电力行业公开信息聚合')}
      <div class="about-grid">
        <div class="stat-grid">
          <div class="stat"><div class="stat-num">${s.total}</div><div class="stat-label">累计条目</div></div>
          <div class="stat"><div class="stat-num">${s.days}</div><div class="stat-label">覆盖天数</div></div>
          <div class="stat"><div class="stat-num">${orgs.length}</div><div class="stat-label">信息源</div></div>
          <div class="stat"><div class="stat-num">${Math.round(s.ai_covered / Math.max(s.total, 1) * 100)}%</div><div class="stat-label">AI 摘要覆盖</div></div>
        </div>

        <div class="panel">
          <h2 class="panel-title">数据来源</h2>
          <p>本站数据全部来自公开渠道，由本地采集任务每日自动抓取并归档，未经人工改写。当前接入：</p>
          <div class="bar-list">
            ${orgs.map(([o, n]) => `<div class="bar-row">
              <span class="bar-name" title="${esc(o)}">${esc(orgLabel(o))}</span>
              <span class="bar-track"><span class="bar-fill" style="width:${(n / maxOrg * 100).toFixed(1)}%;background:${orgColor(o)}"></span></span>
              <span class="bar-num">${n}</span>
            </div>`).join('')}
          </div>
        </div>

        <div class="panel">
          <h2 class="panel-title">主题分布</h2>
          <div class="bar-list">
            ${cats.map(([c, n]) => `<div class="bar-row">
              <span class="bar-name">${esc(c)}</span>
              <span class="bar-track"><span class="bar-fill" style="width:${(n / maxCat * 100).toFixed(1)}%"></span></span>
              <span class="bar-num">${n}</span>
            </div>`).join('')}
          </div>
        </div>

        <div class="panel">
          <h2 class="panel-title">数据说明</h2>
          <div class="kv">
            <div class="kv-row"><span class="kv-key">覆盖区间</span><span class="kv-val">${esc((s.date_range || [])[0])} ~ ${esc((s.date_range || [])[1])}</span></div>
            <div class="kv-row"><span class="kv-key">AI 摘要</span><span class="kv-val">${s.ai_covered} / ${s.total} 条由大模型生成，其余显示原文摘录</span></div>
            <div class="kv-row"><span class="kv-key">正文存档</span><span class="kv-val">${s.with_body} 条有完整原文存档，可在详情页切换查看</span></div>
            <div class="kv-row"><span class="kv-key">更新时间</span><span class="kv-val">${esc(state.data.generated_at)}</span></div>
            <div class="kv-row"><span class="kv-key">更新机制</span><span class="kv-val">每日 05:00 采集源站 → 05:45 重建本站数据并发布</span></div>
          </div>
        </div>

        <div class="panel">
          <h2 class="panel-title">版权与免责</h2>
          <p>本站为个人研究用途的信息聚合工具，所有内容版权归原发布机构所有。</p>
          <p>每条内容均保留原文链接，请以源站发布为准。本站不对信息的完整性、时效性作出保证。</p>
        </div>
      </div>
    </div>`;
  }

  /* ------------------------------------------------------------ 路由 */

  function parseHash() {
    const raw = location.hash.replace(/^#\/?/, '');
    const [path, query] = raw.split('?');
    const parts = path.split('/').filter(Boolean);
    return { path, parts, query };
  }

  async function route() {
    const { parts } = parseHash();
    const view = $('#view');
    const root = parts[0] || '';

    state.view = 'all';
    state.org = '';

    if (root === 'item') {
      markActiveNav('');
      await renderDetail(parts[1]);
      window.scrollTo(0, 0);
      return;
    }

    if (root === 'about') {
      markActiveNav('about');
      renderAbout();
      window.scrollTo(0, 0);
      return;
    }

    if (root === 'topics') {
      markActiveNav('topics');
      await renderTopics();
      window.scrollTo(0, 0);
      return;
    }

    if (root === 'topic') {
      markActiveNav('topics');
      await renderTopicDetail(decodeURIComponent(parts[1] || ''));
      window.scrollTo(0, 0);
      return;
    }

    if (root === 'daily' || root === 'weekly' || root === 'monthly') {
      markActiveNav(root);
      await renderReports(root, parts[1] ? decodeURIComponent(parts[1]) : '');
      return;
    }

    if (root === 'star') {
      state.view = 'star';
      markActiveNav('star');
      renderList({ title: '收藏', sub: '你标记过的条目', emptyTitle: '还没有收藏', emptySub: '在卡片右上角点星标即可收藏' });
      window.scrollTo(0, 0);
      return;
    }

    if (root === 'featured') {
      state.view = 'featured';
      markActiveNav('featured');
      renderList({ title: '精选', sub: '已生成 AI 摘要且收录正文的动态', emptyTitle: '暂无精选内容' });
      window.scrollTo(0, 0);
      return;
    }

    if (root === 'cat') {
      state.view = 'cat';
      state.org = decodeURIComponent(parts[1] || '');
      markActiveNav('cat:' + state.org);
      renderList({ title: state.org, sub: `${(state.data.stats.by_category || {})[state.org] || 0} 条动态` });
      window.scrollTo(0, 0);
      return;
    }

    if (root === 'org') {
      state.view = 'org';
      state.org = decodeURIComponent(parts[1] || '');
      markActiveNav('org:' + state.org);
      const n = (state.data.stats.by_org || {})[state.org] || 0;
      const range = (state.data.stats.date_range || ['', '']);
      renderList({ title: state.org, sub: `${n} 条动态 · 覆盖至 ${range[1] || ''}` });
      window.scrollTo(0, 0);
      return;
    }

    // 首页
    markActiveNav('all');
    const s = state.data.stats;
    renderList({
      title: '全部动态',
      sub: `国家能源局、发改委、中电联、南方电网等 ${Object.keys(s.by_org || {}).length} 个官方信源 · 更新至 ${fmtDate((s.date_range || ['', ''])[1])}`,
    });
    window.scrollTo(0, 0);
  }

  function renderCurrent() {
    const { parts } = parseHash();
    const root = parts[0] || '';
    if (root === '' ) return route();
    if (root === 'featured') return route();
    if (root === 'star') return route();
    if (root === 'cat' || root === 'org' || root === 'day') return route();
    return route();
  }

  /* ------------------------------------------------------------ 全局事件 */

  function bindGlobal() {
    // 星标（事件委托）
    document.addEventListener('click', (e) => {
      // 配图放大（优先于卡片跳转）
      const cell = e.target.closest('.media-cell');
      if (cell) {
        e.preventDefault();
        e.stopPropagation();
        openLightbox(cell.dataset.src);
        return;
      }
      const btn = e.target.closest('[data-star]');
      if (btn) {
        e.preventDefault();
        e.stopPropagation();
        const id = btn.dataset.star;
        toggleStar(id);
        const on = state.stars.has(id);
        btn.classList.toggle('on', on);
        if (state.view === 'star') renderCurrent();
        return;
      }
      const card = e.target.closest('.timeline-card');
      if (card && !e.target.closest('a')) {
        location.hash = '#/item/' + card.dataset.id;
      }
    });

    window.addEventListener('hashchange', route);

    // 主题
    $$('#theme-toggle button').forEach((b) => {
      b.addEventListener('click', () => applyTheme(b.dataset.themeVal));
    });

    // 键盘
    document.addEventListener('keydown', (e) => {
      if (e.key === '/' && !/input|textarea|select/i.test(document.activeElement.tagName)) {
        e.preventDefault();
        const s = $('#search');
        if (s) s.focus();
      }
      if (e.key === 'Escape' && document.activeElement.id === 'search') {
        document.activeElement.value = '';
        state.q = '';
        renderCurrent();
      }
    });

    // 回到顶部
    const btn = document.createElement('button');
    btn.className = 'to-top';
    btn.innerHTML = '<svg viewBox="0 0 16 16"><path d="M8 12.5V3.8M4.2 7.6 8 3.8l3.8 3.8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    btn.title = '回到顶部';
    btn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
    document.body.appendChild(btn);
    window.addEventListener('scroll', () => {
      btn.classList.toggle('show', window.scrollY > 500);
    }, { passive: true });
  }

  /* ------------------------------------------------------------ 启动 */

  async function main() {
    loadStars();
    applyTheme(localStorage.getItem(LS_THEME) || 'light');
    bindGlobal();

    $('#view').innerHTML = `<div class="page"><div class="skeleton">
      <div class="skel-line" style="width:180px;height:22px;margin-bottom:18px"></div>
      <div class="skel-line" style="width:100%;height:80px;margin-bottom:12px"></div>
      <div class="skel-line" style="width:100%;height:80px;margin-bottom:12px"></div>
      <div class="skel-line" style="width:100%;height:80px"></div>
    </div></div>`;

    try {
      await loadData();
    } catch (e) {
      $('#view').innerHTML = `<div class="page">${emptyHtml('数据加载失败', e.message)}</div>`;
      return;
    }
    renderSidebar();
    saveStars();
    await route();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', main);
  else main();
})();
