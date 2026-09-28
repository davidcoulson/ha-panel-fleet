// Panels: every Kiosk Satellite panel on the network, one row each, with
// the filters over them. Rebuilt on every refresh; the expanded rows and
// the filters survive it.

import { $, esc } from './ui.js';

const OPEN_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6M20 4l-9 9"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/></svg>';
const CHEVRON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>';

function lastSeen(ts, now) {
  if (!ts) return 'never seen';
  const s = Math.max(0, now - ts);
  if (s < 60) return 'last seen just now';
  if (s < 3600) return `last seen ${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `last seen ${Math.floor(s / 3600)}h ago`;
  return `last seen ${Math.floor(s / 86400)}d ago`;
}
function duration(s) {
  if (s == null) return '';
  if (s < 3600) return Math.round(s / 60) + ' min';
  if (s < 172800) return Math.round(s / 3600) + ' h';
  return Math.round(s / 86400) + ' days';
}
// Every panel's WebView, with the Android it runs on, so one left behind can
// be told from one that has simply run out of road: Chrome and the WebView
// stop shipping for old Android, and WebView 138 is as far as Android 8.1
// goes. A panel counts as behind only when another panel on the same Android
// or older runs something newer - a comparison the fleet can make from what
// it has, without a table of ceilings that would need maintaining.
let fleetWebviews = [];
function major(v) { const n = parseInt(String(v || ''), 10); return Number.isFinite(n) ? n : null; }
function bestWebviewFor(d) {
  const api = d.android_api;
  let best = null;
  for (const other of fleetWebviews) {
    if (api != null && other.api != null && other.api > api) continue;
    if (best == null || other.major > best) best = other.major;
  }
  return best;
}
function webviewBehind(d) {
  const mine = major(d.webview), best = bestWebviewFor(d);
  return mine != null && best != null && mine < best;
}
function webviewText(d) {
  if (!d.webview) return '';
  const behind = webviewBehind(d);
  return `<span class="${behind ? 'pf-lag' : ''}" title="${esc(d.webview_package || '')} ${esc(d.webview)}${
    behind ? ` — another panel on this Android or older runs ${bestWebviewFor(d)}` : ''
  }">WebView ${esc(String(major(d.webview) ?? d.webview))}${behind ? ' ↓' : ''}</span>`;
}
// A channel's centre frequency as the band and channel people name it by.
// 2484 is channel 14 and 5935 is 6 GHz channel 2; both sit outside their
// band's arithmetic, which is why they are spelled out.
function channel(mhz) {
  if (!mhz) return null;
  if (mhz === 2484) return { band: '2.4 GHz', ch: 14 };
  if (mhz >= 2412 && mhz <= 2472) return { band: '2.4 GHz', ch: (mhz - 2407) / 5 };
  if (mhz >= 5160 && mhz <= 5885) return { band: '5 GHz', ch: (mhz - 5000) / 5 };
  if (mhz === 5935) return { band: '6 GHz', ch: 2 };
  if (mhz >= 5955 && mhz <= 7115) return { band: '6 GHz', ch: (mhz - 5950) / 5 };
  return null;
}
const LINK = { ethernet: 'Ethernet', wifi: 'Wi-Fi', cellular: 'Cellular', vpn: 'VPN' };

function displayCell(d) {
  // An agent's screen shows whatever that box shows - a projector's own
  // launcher, usually. Its size is not a fact about a dashboard.
  if (d.agent) return '<span class="sub">—</span>';
  const s = d.screen;
  if (!s) return '<span class="sub">unknown</span>';
  const under = [s.orientation, s.rotation ? `turned ${s.rotation}°` : ''].filter(Boolean).join(' · ');
  return `<div class="mono">${s.width}×${s.height}</div>` + (under ? `<div class="sub">${esc(under)}</div>` : '');
}
function networkCell(d) {
  const l = d.link || {};
  const c = channel(l.frequencyMhz);
  const name = LINK[l.type] || '';
  const radio = l.type === 'wifi'
    ? [l.rssi != null ? `${l.rssi} dBm` : '', l.speedMbps ? `${l.speedMbps} Mbps` : ''].filter(Boolean).join(' · ')
    : '';
  // Band on the first line with the medium, channel down with the numbers.
  const under = [c ? `ch ${c.ch}` : '', radio].filter(Boolean).join(' · ');
  return (name ? `<div>${esc(name)}${c ? ` ${esc(c.band)}` : ''}</div>` : '') +
    (under ? `<div class="sub pf-nowrap">${esc(under)}</div>` : '') +
    `<div class="sub mono">${esc(d.host || '')}</div>`;
}
function detailRow(d) {
  const sc = d.screen;
  const rows = [
    ['Display', [sc ? `${sc.width}×${sc.height}` : '', sc && sc.orientation,
      sc && sc.dpi ? `${sc.dpi} dpi` : '', sc && sc.rotation ? `turned ${sc.rotation}°` : ''].filter(Boolean).join(' · ')],
    ['Android', [d.android, d.android_api ? `API ${d.android_api}` : ''].filter(Boolean).join(' · '), d.android_build],
    ['System WebView', d.webview || '', d.webview_package],
    ['Memory', d.ram_text || ''],
    ['Storage', d.storage_text || ''],
    ['CPU', d.cpu_text || ''],
    ['Uptime', d.uptime_device != null ? `device up ${duration(d.uptime_device)}` : '',
      d.uptime != null ? `app up ${duration(d.uptime)}` : ''],
    ['Battery', d.battery != null ? `${d.battery}%${d.charging ? ' · charging' : ''}` : ''],
    ['Fleet', d.fleet ? d.fleet.text : ''],
  ].filter(([, value]) => value);
  return `<tr class="detail"><td colspan="8"><dl class="pf-grid">` +
    rows.map(([label, value, sub]) =>
      `<div><dt>${esc(label)}</dt><dd>${esc(value)}${sub ? `<span class="sub mono">${esc(sub)}</span>` : ''}</dd></div>`).join('') +
    '</dl></td></tr>';
}
function versionCell(d) {
  if (!d.version) return '<span class="sub">unknown</span>';
  const base = d.fork ? d.version.slice(0, d.version.length - d.fork.length) : d.version;
  const [label, kind] = {
    current: ['Current', 'ok'],
    outdated: ['Update to ' + (d.latest || ''), 'warn'],
    ahead: ['Newer than release', ''],
    unknown: ['Latest unknown', ''],
  }[d.version_status] || ['', ''];
  return `<div class="mono pf-nowrap">${esc(base)}</div>` +
    (d.fork ? `<div class="sub mono pf-nowrap" title="Fork build">${esc(d.fork.replace(/^-/, ''))}</div>` : '') +
    `<div class="pf-tags"><span class="tag ${kind}">${esc(label)}</span></div>`;
}
function pageCell(d) {
  if (d.agent) return '<span class="sub" title="An agent shows no dashboard">—</span>';
  if (!d.dashboard_href) return '<span class="sub">not reported</span>';
  return `<a class="pf-page mono" href="${esc(d.dashboard_href)}" target="_blank" rel="noopener" title="${esc(d.dashboard_href)}">${esc(d.dashboard_path)}</a>`;
}
function statusCell(d, now) {
  if (d.online == null) return '<div class="pf-state"><span class="dot"></span>Checking…</div>';
  if (!d.online) {
    return `<div class="pf-state"><span class="dot off"></span>Offline</div><div class="sub">${lastSeen(d.last_seen || d.announced, now)}</div>`;
  }
  return '<div class="pf-state"><span class="dot on"></span>Online</div>' +
    (d.uptime != null ? `<div class="sub">up ${duration(d.uptime)}</div>` : '') +
    (d.screen_on === false ? '<div class="sub">screen off</div>' : '');
}
function fleetTag(d) {
  const f = d.fleet || {};
  if (!f.state || f.state === 'none') return '';
  const kind = f.state === 'member' ? (f.tone === 'warn' ? 'warn' : 'ok') : '';
  const word = { member: 'Fleet', invited: 'Invited', declined: 'Declined', left: 'Left' }[f.state] || '';
  return `<span class="tag ${kind}" title="${esc(f.text || '')}">${esc(word)}</span>`;
}
function row(d, now) {
  const platform = [d.model, d.android].filter(Boolean).join(' · ');
  const wv = webviewText(d);
  return `<tr class="${d.online === false ? 'offline' : ''}">
    <td>${statusCell(d, now)}</td>
    <td><div class="name">${esc(d.name || d.id)}${d.admin
          ? `<a class="pf-open" href="${esc(d.admin)}" target="_blank" rel="noopener" title="Open the panel's admin" aria-label="Open the admin page for ${esc(d.name || d.id)}">${OPEN_ICON}</a>` : ''}</div>
        ${d.hostname ? `<div class="sub mono pf-nowrap">${esc(d.hostname)}.local</div>` : ''}
        <div class="pf-tags">${d.agent ? '<span class="tag agent" title="Runs as a management agent: no dashboard, voice or screensaver">Agent</span>' : ''}${fleetTag(d)}</div></td>
    <td><div>${esc(platform)}</div>${wv ? `<div class="sub">${wv}</div>` : ''}</td>
    <td>${displayCell(d)}</td>
    <td>${networkCell(d)}</td>
    <td>${versionCell(d)}</td>
    <td>${pageCell(d)}</td>
    <td class="pf-actions">
      ${d.online !== false ? '' : `<button type="button" class="btn-ghost" data-forget="${esc(d.key)}" title="Remove until it is discovered again">Forget</button>`}
      <button type="button" class="icon-btn pf-more" data-more="${esc(d.key)}" aria-expanded="${open.has(d.key)}"
        title="Everything this panel reports" aria-label="Details for ${esc(d.name || d.id)}">${CHEVRON}</button>
    </td>
  </tr>` + (open.has(d.key) ? detailRow(d) : '');
}

// Which panels are expanded, kept across the refresh so a detail being read
// does not fold itself up mid-sentence.
const open = new Set();
let last = null;

// One dropdown, one section per question the fleet can answer about itself.
// Ticking several inside a section widens the list, across sections narrows.
const SECTIONS = [
  { key: 'status', label: 'Status', of: (d) => [d.online === true ? 'Online' : d.online === false ? 'Offline' : 'Checking'] },
  { key: 'fleet', label: 'Fleet', of: (d) => [(d.fleet && {
      member: 'Member', invited: 'Invited', declined: 'Declined', left: 'Left',
    }[d.fleet.state]) || 'Not in fleet'] },
  { key: 'model', label: 'Platform', of: (d) => [d.model || 'Unknown'] },
  { key: 'android', label: 'Android', of: (d) => [d.android || 'Unknown'] },
  { key: 'link', label: 'Network', of: (d) => [LINK[(d.link || {}).type] || 'Unknown'] },
  // The only section where a panel can land in more than one row, or none.
  { key: 'attention', label: 'Needs attention', of: (d) => [
      d.version_status === 'outdated' ? 'Update available' : null,
      webviewBehind(d) ? 'WebView behind the fleet' : null,
      d.screen_on === false ? 'Screen off' : null,
      d.fleet && d.fleet.tone === 'warn' ? 'Fleet sync held' : null,
    ].filter(Boolean) },
];

// Ticked values per section, remembered per browser. Storage can throw
// (private windows), so every touch is guarded.
let picked = {};
function loadFilters() {
  try {
    const saved = JSON.parse(localStorage.getItem('panel-fleet-filters') || '{}');
    picked = {};
    for (const sec of SECTIONS) if (Array.isArray(saved[sec.key])) picked[sec.key] = new Set(saved[sec.key]);
    if (typeof saved.q === 'string') $('q').value = saved.q;
  } catch (e) { /* fine */ }
}
function saveFilters() {
  const out = { q: $('q').value };
  for (const [k, v] of Object.entries(picked)) if (v.size) out[k] = [...v];
  try { localStorage.setItem('panel-fleet-filters', JSON.stringify(out)); } catch (e) { /* fine */ }
}
const activeCount = () => Object.values(picked).reduce((n, v) => n + v.size, 0);
function matchesSearch(d) {
  const q = $('q').value.trim().toLowerCase();
  if (!q) return true;
  return [d.name, d.id, d.model, d.android, d.host, d.hostname, d.version, d.dashboard_path,
    d.webview].filter(Boolean).join(' ').toLowerCase().includes(q);
}
// `except` leaves one section out, so its counts say what ticking gives.
function matches(d, except) {
  if (!matchesSearch(d)) return false;
  for (const sec of SECTIONS) {
    if (sec.key === except) continue;
    const want = picked[sec.key];
    if (want && want.size && !sec.of(d).some((v) => want.has(v))) return false;
  }
  return true;
}
function renderFilters(all) {
  $('filter-sections').innerHTML = SECTIONS.map((sec) => {
    const counts = new Map();
    for (const d of all.filter((x) => matches(x, sec.key))) {
      for (const v of sec.of(d)) counts.set(v, (counts.get(v) || 0) + 1);
    }
    for (const v of picked[sec.key] || []) if (!counts.has(v)) counts.set(v, 0);
    const chosen = picked[sec.key] ? picked[sec.key].size : 0;
    const opts = [...counts.entries()].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(b[0]));
    const body = opts.length
      ? opts.map(([v, n]) => `<label class="pf-opt"><input type="checkbox" data-sec="${esc(sec.key)}" value="${esc(v)}"${
          picked[sec.key] && picked[sec.key].has(v) ? ' checked' : ''}><span>${esc(v)}</span><span class="n">${n}</span></label>`).join('')
      : '<div class="pf-opt none">Nothing to filter by</div>';
    return `<details${chosen ? ' open' : ''}><summary>${esc(sec.label)}${chosen ? ` <span class="tag">${chosen}</span>` : ''}</summary><div>${body}</div></details>`;
  }).join('');
}

export function renderPanels(data) {
  if (!data) return;
  last = data;
  const all = data.devices || [];
  fleetWebviews = all.filter((d) => major(d.webview) != null).map((d) => ({ major: major(d.webview), api: d.android_api ?? null }));
  const ds = all.filter((d) => matches(d));
  renderFilters(all);
  const active = activeCount();
  $('filter-count').textContent = active;
  $('filter-count').hidden = !active;
  $('clear').hidden = !active && !$('q').value;
  const online = all.filter((d) => d.online).length;
  const outdated = all.filter((d) => d.version_status === 'outdated').length;
  const members = all.filter((d) => d.fleet && d.fleet.state === 'member').length;
  const latest = (data.latest || {}).ks;
  $('summary').innerHTML =
    `<span><b>${all.length}</b> panels</span>` +
    (ds.length !== all.length ? `<span><b>${ds.length}</b> shown</span>` : '') +
    `<span><b>${online}</b> online</span>` +
    `<span><b>${members}</b> in the fleet</span>` +
    `<span class="${outdated ? 'warn' : ''}"><b>${outdated}</b> need an update</span>` +
    (latest ? `<span>Latest: <a href="${esc(latest.url)}" target="_blank" rel="noopener" class="pf-mono">${esc(latest.version)}</a></span>` : '');
  $('note').textContent = data.ha_error ? `Dashboards need Home Assistant (${data.ha_error}).` : '';
  $('note').classList.toggle('hidden', !data.ha_error);
  $('rows').innerHTML = ds.length
    ? ds.map((d) => row(d, data.now)).join('')
    : `<tr><td colspan="8" class="pf-empty">${all.length
        ? 'No panel matches these filters.'
        : 'No panels found yet. Kiosk Satellite panels announce themselves when their remote admin and Find other kiosks are on.'}</td></tr>`;
}

export function initPanels({ reload, scan }) {
  loadFilters();
  $('scan').addEventListener('click', async (e) => {
    const b = e.currentTarget;
    b.disabled = true;
    b.textContent = 'Scanning…';
    await scan();
    b.disabled = false;
    b.textContent = 'Scan now';
  });
  $('rows').addEventListener('click', async (e) => {
    const forget = e.target.closest('[data-forget]');
    if (forget) {
      open.delete(forget.dataset.forget);
      await reload('api/devices/' + encodeURIComponent(forget.dataset.forget), 'DELETE');
      return;
    }
    const more = e.target.closest('[data-more]');
    if (more) {
      const key = more.dataset.more;
      open.has(key) ? open.delete(key) : open.add(key);
      renderPanels(last);
    }
  });
  $('q').addEventListener('input', () => { saveFilters(); renderPanels(last); });
  $('filter-sections').addEventListener('change', (e) => {
    const box = e.target.closest('input[data-sec]');
    if (!box) return;
    const set = picked[box.dataset.sec] || (picked[box.dataset.sec] = new Set());
    box.checked ? set.add(box.value) : set.delete(box.value);
    saveFilters();
    renderPanels(last);
  });
  $('clear').addEventListener('click', () => {
    picked = {};
    $('q').value = '';
    saveFilters();
    renderPanels(last);
  });
  // The dropdown closes on a click outside it or on Escape; clicks inside
  // must not close it, since ticking is what it is for.
  const pop = $('filter-pop'), btn = $('filter-btn');
  const setPop = (on) => { pop.hidden = !on; btn.setAttribute('aria-expanded', String(on)); };
  btn.addEventListener('click', () => setPop(pop.hidden));
  document.addEventListener('click', (e) => {
    if (!pop.hidden && !pop.contains(e.target) && !btn.contains(e.target)) setPop(false);
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') setPop(false); });
}
