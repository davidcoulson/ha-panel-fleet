// Panel Fleet's page: a Kiosk Satellite remote admin whose "device" is the
// fleet. The rail and pages are the panel admin's (app.css); this wires the
// navigation, the theme, the refresh and the pages together.

import { exitToHa, haDarkMode, initHaFrame } from './ha-frame.js';
import { SUBPAGE_ICONS } from './ks-icons.js';
import { renderFleet, initFleet } from './members.js';
import { CATEGORY_NAV, PAGE_NAV } from './nav-icons.js';
import { initPanels, renderPanels } from './panels.js';
import { initProfiles, renderProfiles } from './profiles.js';
import { $, api, el, esc } from './ui.js';
import {
  categoryOf, initSettings, openCategory, renderSettings, searchSettings, settingsCategories, tabIdFor,
} from './settings.js';

const PAGES = {
  panels: { title: 'Panels', sub: 'Every panel on the network' },
  fleet: { title: 'Fleet', sub: 'Invite, sync, remove' },
  profiles: { title: 'Profiles', sub: 'What each panel gets' },
};
const BACK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>';

let settingsView = null;
let profilesView = null;
let route = 'panels';

// ── Theme ────────────────────────────────────────────────────────────
// Auto follows Home Assistant's dark mode when this page is in its frame,
// the system's otherwise; light and dark are picks for this browser.

const THEME_ICONS = {
  auto: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 0 0 16z" fill="currentColor"/></svg>',
  light: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4m11.4-11.4 1.4-1.4"/></svg>',
  dark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>',
};
const media = matchMedia('(prefers-color-scheme: dark)');
function themePick() { try { return localStorage.getItem('pf_theme') || 'auto'; } catch (e) { return 'auto'; } }
function systemDark() {
  return haDarkMode() ?? media.matches;
}
function applyTheme() {
  const pick = themePick();
  document.documentElement.dataset.theme = pick === 'auto' ? (systemDark() ? 'dark' : 'light') : pick;
  $('themeBtn').innerHTML = THEME_ICONS[pick];
  $('themeBtn').title = `Theme: ${pick}`;
  $('footTheme').textContent = { auto: 'Automatic theme', light: 'Light theme', dark: 'Dark theme' }[pick];
}
$('themeBtn').addEventListener('click', () => {
  const next = { auto: 'light', light: 'dark', dark: 'auto' }[themePick()];
  try { localStorage.setItem('pf_theme', next); } catch (e) { /* fine */ }
  applyTheme();
});
media.addEventListener('change', applyTheme);

// ── Navigation ───────────────────────────────────────────────────────

// The rail's groups as a panel's remote admin has them (index.html in its
// remote-ui): the heading, then each settings category it holds, with the
// disc colour it wears there. A category this list has not met yet lands
// under System.
const NAV_GROUPS = [
  { head: 'Home Assistant', items: [['Home Assistant', 1], ['ESPHome', 2], ['Voice Satellite', 3]] },
  { head: 'Display', items: [['Screen & Audio', 4], ['Screensaver', 1], ['Browser', 2]] },
  { head: 'Media & Cameras', items: [['Sendspin', 3], ['DLNA', 4], ['Intercom', 1], ['Camera', 2], ['Cameras', 3]] },
  { head: 'Kiosk', items: [['Kiosk', 4], ['Lockdown', 1], ['Home', 2], ['Launcher', 3], ['Gestures', 4]] },
  { head: 'System', items: [['Device', 1]] },
];
const EXIT_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 17l-5-5 5-5M5 12h11"/><path d="M14 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/></svg>';

function navButton(tab, disc, title, sub, svg, onClick) {
  const b = el('button');
  b.type = 'button';
  if (tab) b.dataset.tab = tab;
  b.innerHTML = `<span class="disc d${disc}">${svg}</span><span class="nav-text"><span class="nav-title">${esc(title)}</span><span class="nav-sub">${esc(sub)}</span></span>`;
  b.addEventListener('click', onClick || (() => { leaveSearch(); go(tab); closeDrawer(); }));
  return b;
}

// Rolled-up groups, by heading as the panel admin keys them, kept in this
// browser. Storage can throw (private windows): then nothing is rolled up.
function collapsed() {
  try {
    const list = JSON.parse(localStorage.getItem('pf_nav_collapsed') || '[]');
    return new Set(Array.isArray(list) ? list.filter((h) => typeof h === 'string') : []);
  } catch (e) { return new Set(); }
}
function navGroup(head, buttons) {
  const slug = head.toLowerCase().replace(/[^a-z0-9]+/g, '-');
  const g = el('div', 'nav-group');
  g.setAttribute('role', 'group');
  g.setAttribute('aria-labelledby', `navhead-${slug}`);
  const h = el('h2', 'nav-head', head);
  h.id = `navhead-${slug}`;
  h.setAttribute('role', 'button');
  h.tabIndex = 0;
  const paint = (on) => { g.classList.toggle('collapsed', on); h.setAttribute('aria-expanded', String(!on)); };
  const toggle = () => {
    const folded = collapsed();
    if (!folded.delete(head)) folded.add(head);
    paint(folded.has(head));
    try { localStorage.setItem('pf_nav_collapsed', JSON.stringify([...folded].sort())); } catch (e) { /* fine */ }
  };
  h.addEventListener('click', toggle);
  h.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
  paint(collapsed().has(head));
  g.append(h, ...buttons);
  return g;
}
function buildNav() {
  const nav = $('tabs');
  nav.innerHTML = '';
  const fleet = [
    navButton('panels', 4, PAGES.panels.title, PAGES.panels.sub, PAGE_NAV.panels),
    navButton('fleet', 2, PAGES.fleet.title, PAGES.fleet.sub, PAGE_NAV.fleet),
    navButton('profiles', 3, PAGES.profiles.title, PAGES.profiles.sub, PAGE_NAV.profiles),
  ];
  // Only inside Home Assistant: the way back, with its sidebar restored.
  if (inHa) {
    fleet.push(navButton(null, 1, 'Exit to Home Assistant', 'Back to its sidebar and dashboards',
      EXIT_ICON, () => exitToHa()));
  }
  nav.appendChild(navGroup('Fleet', fleet));
  const cats = settingsCategories();
  if (!cats.length) {
    nav.appendChild(navGroup('Fleet settings', [navButton('fleet', 4, 'No settings yet',
      'Import them on the Fleet page', PAGE_NAV.profiles)]));
  }
  const placed = new Set();
  const groups = NAV_GROUPS.map((g) => ({ head: g.head, items: g.items.filter(([id]) => cats.some((c) => c.id === id)) }));
  for (const [id] of groups.flatMap((g) => g.items)) placed.add(id);
  const system = groups.find((g) => g.head === 'System');
  cats.forEach((c, i) => { if (!placed.has(c.id)) system.items.push([c.id, (i % 4) + 1]); });
  for (const g of groups) {
    if (!g.items.length) continue;
    nav.appendChild(navGroup(g.head, g.items.map(([id, disc]) => {
      const c = cats.find((x) => x.id === id);
      const icon = CATEGORY_NAV[id] || { sub: '', svg: PAGE_NAV.profiles };
      return navButton(`settings/${encodeURIComponent(id)}`, disc, c.title, icon.sub, icon.svg);
    })));
  }
  markNav();
}
function markNav() {
  const top = route.startsWith('settings/') ? route.split('/').slice(0, 2).join('/') : route;
  $('tabs').querySelectorAll('button[data-tab]').forEach((b) => b.classList.toggle('active', b.dataset.tab === top));
}

function setTitle(text, svg, back) {
  const h = $('pageTitle');
  h.innerHTML = '';
  if (back) {
    const b = el('button', 'title-back');
    b.type = 'button';
    b.setAttribute('aria-label', 'Back');
    b.innerHTML = BACK;
    b.addEventListener('click', () => go(back));
    h.appendChild(b);
  }
  if (svg) {
    const icon = el('span', 'page-icon');
    icon.innerHTML = svg;
    h.appendChild(icon);
  }
  h.appendChild(document.createTextNode(text));
}

function show(tabId) {
  document.querySelectorAll('main .tab').forEach((t) => t.classList.toggle('active', t.id === tabId));
}

// Routes: panels, fleet, profiles, settings/<category>[/<page>].
function go(to, { push = true } = {}) {
  route = to || 'panels';
  if (push && location.hash !== '#' + route) history.pushState(null, '', '#' + route);
  if (route.startsWith('settings/')) {
    const [, rawCat, rawSub] = route.split('/');
    const cat = decodeURIComponent(rawCat || '');
    const meta = settingsCategories().find((c) => c.id === cat);
    if (!meta) { go('fleet', { push }); return; }
    const sub = openCategory(cat, rawSub ? decodeURIComponent(rawSub) : '');
    show(tabIdFor(cat));
    const icon = CATEGORY_NAV[cat];
    if (sub) {
      setTitle(sub, SUBPAGE_ICONS[sub] || null, `settings/${encodeURIComponent(cat)}`);
    } else {
      setTitle(meta.title, icon ? icon.svg : null);
    }
  } else {
    const page = PAGES[route] ? route : 'panels';
    route = page;
    show(`tab-${page}`);
    setTitle(PAGES[page].title, PAGE_NAV[page]);
    if (page === 'fleet') refresh();
  }
  markNav();
  window.scrollTo(0, 0);
}
window.addEventListener('popstate', () => go(location.hash.slice(1), { push: false }));

// The phone drawer.
function closeDrawer() {
  $('sidebar').classList.remove('open');
  $('navBackdrop').classList.remove('show');
  $('navToggle').setAttribute('aria-expanded', 'false');
}
$('navToggle').addEventListener('click', () => {
  const open = !$('sidebar').classList.contains('open');
  $('sidebar').classList.toggle('open', open);
  $('navBackdrop').classList.toggle('show', open);
  $('navToggle').setAttribute('aria-expanded', String(open));
});
$('navBackdrop').addEventListener('click', closeDrawer);

// ── Search over the fleet settings ───────────────────────────────────

// Picking a result, or a page in the rail, leaves the search.
function leaveSearch() {
  if (!$('settingsSearch').value) return;
  $('settingsSearch').value = '';
  $('settingsSearch').closest('.side-search').classList.remove('has-text');
  $('sidebar').classList.remove('searching');
  $('sideResults').innerHTML = '';
}
// Results land in the content pane and, on a phone, in the drawer in the
// nav list's place (app.css #sidebar.searching), as the panel admin does.
function runSearch() {
  const q = $('settingsSearch').value;
  $('settingsSearch').closest('.side-search').classList.toggle('has-text', !!q);
  $('sidebar').classList.toggle('searching', !!q.trim());
  if (!q.trim()) { $('sideResults').innerHTML = ''; if (route === 'search') go('panels'); return; }
  const body = $('searchBody');
  body.innerHTML = '';
  const hits = searchSettings(q);
  const titles = Object.fromEntries(settingsCategories().map((c) => [c.id, c.title]));
  for (const s of hits) {
    const row = el('div', 'row');
    const info = el('div', 'info');
    info.append(el('div', 'name', s.title || s.key),
      el('div', 'desc', [titles[categoryOf(s)], s.subpage].filter(Boolean).join(' › ')));
    row.appendChild(info);
    row.addEventListener('click', () => {
      leaveSearch();
      const cat = encodeURIComponent(categoryOf(s));
      go(s.subpage ? `settings/${cat}/${encodeURIComponent(s.subpage)}` : `settings/${cat}`);
      closeDrawer();
      const target = document.querySelector(`#${tabIdFor(categoryOf(s))} [data-key="${CSS.escape(s.key)}"]`);
      if (target) {
        target.scrollIntoView({ block: 'center' });
        target.classList.remove('search-hit');
        void target.offsetWidth;
        target.classList.add('search-hit');
      }
    });
    body.appendChild(row);
  }
  if (!hits.length) body.appendChild(el('div', 'row', settingsView && settingsView.definitions.length
    ? 'No fleet setting matches.' : 'No fleet settings yet: import them on the Fleet page.'));
  const side = $('sideResults');
  side.innerHTML = '';
  for (const row of body.children) {
    const copy = row.cloneNode(true);
    copy.addEventListener('click', () => row.click());
    side.appendChild(copy);
  }
  route = 'search';
  show('tab-search');
  setTitle(`Search: ${q}`, null);
  markNav();
}
$('settingsSearch').addEventListener('input', runSearch);
$('settingsSearchClear').addEventListener('click', () => { $('settingsSearch').value = ''; runSearch(); });

// ── Data ─────────────────────────────────────────────────────────────

let lastDevices = null;
async function refresh() {
  const [devices, leader] = await Promise.all([api('api/devices'), api('api/leader')]);
  const ok = devices.status === 200 && leader.status === 200;
  $('connDot').className = 'dot ' + (ok ? 'on' : 'off');
  if (devices.status === 200) {
    lastDevices = devices.data;
    renderPanels(devices.data);
    $('footVersion').textContent = devices.data.version ? `Panel Fleet v${devices.data.version}` : 'Panel Fleet';
  } else if (!lastDevices) {
    $('note').textContent = devices.data?.error || 'Could not reach the add-on.';
    $('note').classList.remove('hidden');
  }
  if (leader.status === 200) {
    renderFleet(leader.data);
    const n = leader.data.members.filter((m) => m.state === 'member').length;
    $('footStat').textContent = `${n} in the fleet`;
  }
}

async function loadSettings() {
  const [s, p] = await Promise.all([api('api/fleet-settings'), api('api/profiles')]);
  if (s.status === 200) settingsView = s.data;
  if (p.status === 200) profilesView = p.data;
  const def = profilesView?.profiles.find((x) => x.id === 'default') || null;
  if (settingsView) renderSettings(settingsView, def);
  renderProfiles(profilesView);
  buildNav();
}

initPanels({
  reload: async (path, method) => {
    const r = await api(path, { method });
    if (r.status === 200) renderPanels(r.data);
  },
  scan: async () => {
    const r = await api('api/scan', { method: 'POST' });
    if (r.status === 200) renderPanels(r.data);
  },
});
initFleet({
  reload: async () => {
    const r = await api('api/leader');
    if (r.status === 200) renderFleet(r.data, true);
    const p = await api('api/profiles');
    if (p.status === 200) { profilesView = p.data; renderProfiles(profilesView); }
  },
  settingsChanged: async () => { await loadSettings(); go(route, { push: false }); },
});
initProfiles({
  reloadProfiles: async () => {
    await loadSettings();
    const r = await api('api/leader');
    if (r.status === 200) renderFleet(r.data, true);
  },
});
initSettings({ navigate: (to) => go(to) });

const inHa = initHaFrame();
applyTheme();
await loadSettings();
go(location.hash.slice(1) || 'panels', { push: false });
await refresh();
// The tables refresh; the settings pages never do on a timer.
setInterval(refresh, 15000);
