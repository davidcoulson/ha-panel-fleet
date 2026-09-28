// The fleet's settings, one page per category a leader can push, drawn from
// the definitions a panel's admin served, the way that admin draws its own
// (rows.js and settings.js in Kiosk Satellite's remote-ui): a switch for a
// boolean, a dropdown for a choice, a slider for a bounded number, a field
// for the rest; rows grouped into cards by section, second-level pages
// behind an entry row, hidden rows and rows whose gate is shut left out.
// Built once per load of the definitions: the periodic refresh never
// touches these pages, so nothing typed is ever wiped.

import { subpageIcon } from './ks-icons.js';
import { $, api, el, tag } from './ui.js';

let view = null;          // /api/fleet-settings
let defaults = null;      // the Default profile, for the row flags
let byKey = {};
let onNavigate = null;

// core.js dependsSatisfiedBy / depSatisfied, as the panel admin has them:
// a gate holds when its setting has the wanted value (true by default, a
// list for any of several, {gt} or {ne} for the odd ones), transitively,
// and a dependency that is not here (per device, another category) does
// not hide anything.
function dependsSatisfiedBy(value, want) {
  if (want && typeof want === 'object' && typeof want.gt === 'number') {
    return typeof value === 'number' && value > want.gt;
  }
  if (want && typeof want === 'object' && 'ne' in want) return value !== want.ne;
  return Array.isArray(want) ? want.includes(value) : value === (want ?? true);
}
function depSatisfied(s) {
  const holds = (key, want) => {
    if (!key) return true;
    const dep = byKey[key];
    if (!dep) return true;
    return dependsSatisfiedBy(dep.value, want) && depSatisfied(dep);
  };
  return holds(s.dependsOn, s.dependsOnValue) && holds(s.alsoDependsOn, s.alsoDependsOnValue);
}
const visible = (s) => !s.hidden && depSatisfied(s);
const gatedOn = (key) => view.definitions.filter((o) => o.dependsOn === key || o.alsoDependsOn === key);

export const categoryOf = (s) => (s.category === 'Web Content' ? 'Browser' : s.category);

// What the Default profile leaves at home, said on the row itself.
function flagFor(s) {
  if (!defaults) return null;
  const credentials = ['ha.token', 'sendspin.ma_token', 'screensaver.immich_api_key', 'intercom.key'];
  if (credentials.includes(s.key)) {
    return defaults.credentials.includes(s.key) ? null : ['Kept per panel', 'Credential the Default profile does not share'];
  }
  if (s.key === 'browser.start_url') {
    return defaults.dashboard ? null : ['Not synced', 'The Default profile leaves out the dashboard'];
  }
  if (defaults.excluded.includes(s.key)) return ['Excluded', 'The Default profile excludes this setting'];
  if (!defaults.categories.includes(categoryOf(s))) return ['Not synced', 'The Default profile leaves out this category'];
  return null;
}

function showRowError(row, message) {
  let e = row.querySelector('.row-error');
  if (!e) { e = el('div', 'row-error'); row.appendChild(e); }
  e.textContent = message;
}

async function save(s, row, value) {
  const r = await api('api/fleet-settings', { method: 'PATCH', body: { [s.key]: value } });
  if (!r.ok || r.data?.rejected?.includes(s.key)) {
    showRowError(row, r.data?.errors?.[s.key] || r.data?.error || 'Could not save this setting. Try again.');
    return false;
  }
  row.querySelector('.row-error')?.remove();
  s.value = s.secret ? (value ? '__set__' : s.value) : value;
  // A flip that gates other rows redraws its page; everything else stays
  // exactly as it is on screen.
  if (gatedOn(s.key).length) renderCategory(categoryOf(s));
  return true;
}

function sliderLabel(s, v) {
  return s.unit === '%' ? `${Math.round(s.max <= 1 ? v * 100 : v)}%` : `${v}${s.unit || ''}`;
}
function paintRange(inp) {
  const min = Number(inp.min) || 0, max = inp.max === '' ? 100 : Number(inp.max);
  const pct = max > min ? ((Number(inp.value) - min) / (max - min)) * 100 : 0;
  inp.style.setProperty('--pct', `${Math.max(0, Math.min(100, pct)).toFixed(2)}%`);
}

function settingRow(s) {
  const row = el('div', 'row');
  row.dataset.key = s.key;
  const info = el('div', 'info');
  const name = el('div', 'name', s.title || s.key);
  const flag = flagFor(s);
  if (flag) {
    const t = tag(flag[0]);
    t.classList.add('pf-flag');
    t.title = flag[1];
    name.appendChild(t);
  }
  info.append(name, el('div', 'desc', s.description || ''));
  if (s.notice) info.appendChild(el('div', 'desc pf-notice', s.notice));
  row.appendChild(info);

  if (s.type === 'number' && s.min != null && s.max != null) {
    row.classList.add('slider-row');
    const val = el('span', 'slider-value');
    const inp = document.createElement('input');
    inp.type = 'range';
    inp.className = 'range';
    inp.min = String(s.min);
    inp.max = String(s.max);
    inp.step = String(s.step ?? 'any');
    inp.value = String(typeof s.value === 'number' ? s.value : s.min);
    const paint = () => { val.textContent = sliderLabel(s, Number(inp.value)); paintRange(inp); };
    paint();
    inp.addEventListener('input', paint);
    inp.addEventListener('change', async () => {
      if (!await save(s, row, Number(inp.value))) { inp.value = String(s.value); paint(); }
    });
    row.append(val, inp);
    return row;
  }
  if (s.type === 'boolean') {
    const lbl = el('label', 'switch');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = !!s.value;
    cb.addEventListener('change', async () => {
      if (!await save(s, row, cb.checked)) cb.checked = !!s.value;
    });
    lbl.append(cb, el('span', 'slider'));
    row.appendChild(lbl);
  } else if (s.type === 'select') {
    const sel = document.createElement('select');
    const opts = [...(s.options || [])];
    // A value the definitions no longer offer still shows as what it is.
    if (s.value != null && !opts.includes(s.value)) opts.unshift(s.value);
    for (const o of opts) {
      const opt = document.createElement('option');
      opt.value = o;
      opt.textContent = (s.optionLabels && s.optionLabels[o]) || (o ? o[0].toUpperCase() + o.slice(1) : o);
      opt.selected = o === s.value;
      sel.appendChild(opt);
    }
    sel.addEventListener('change', async () => {
      if (!await save(s, row, sel.value)) sel.value = s.value ?? '';
    });
    row.appendChild(sel);
  } else if (s.multiline) {
    row.classList.add('pf-textarea-row');
    const ta = document.createElement('textarea');
    ta.className = 'pf-textarea';
    ta.spellcheck = false;
    ta.rows = 5;
    if (s.secret) ta.placeholder = s.value === '__set__' ? '•••••• (set)' : 'Not set';
    else { ta.value = s.value ?? ''; if (s.placeholder) ta.placeholder = s.placeholder; }
    ta.addEventListener('change', async () => {
      if (s.secret && !ta.value) return;
      if (await save(s, row, ta.value) && s.secret) { ta.value = ''; ta.placeholder = '•••••• (set)'; }
    });
    row.appendChild(ta);
  } else {
    const inp = document.createElement('input');
    const secret = s.secret || s.type === 'password';
    inp.type = secret ? 'password' : s.type === 'number' ? 'number' : 'text';
    inp.autocomplete = secret ? 'new-password' : 'off';
    if (secret) {
      // Masked: the value never comes to the page, and only a typed one
      // replaces it.
      inp.placeholder = s.value === '__set__' ? '•••••• (set)' : 'Not set';
    } else {
      inp.value = s.value ?? '';
      if (s.placeholder) inp.placeholder = s.placeholder;
      if (s.type === 'number') {
        if (s.min != null) inp.min = s.min;
        if (s.max != null) inp.max = s.max;
        if (s.step != null) inp.step = s.step;
      }
    }
    inp.addEventListener('change', async () => {
      if (secret && !inp.value) return;
      const value = s.type === 'number' ? Number(inp.value) : inp.value;
      if (s.type === 'number' && (inp.value === '' || !Number.isFinite(value))) {
        showRowError(row, 'Enter a number.');
        return;
      }
      if (await save(s, row, value) && secret) {
        inp.value = '';
        inp.placeholder = '•••••• (set)';
      }
    });
    row.appendChild(inp);
    if (s.unit && s.type === 'number') row.appendChild(el('span', 'device', s.unit));
  }
  return row;
}

function subpageEntry(cat, sub) {
  const row = el('div', 'row subpage-entry');
  row.dataset.subpageEntry = sub;
  const info = el('div', 'info');
  info.append(el('div', 'name', sub), el('div', 'desc', (view.subpageHints || {})[sub] || ''));
  const chev = el('span', 'chev');
  chev.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>';
  row.append(subpageIcon(sub), info, chev);
  row.addEventListener('click', () => onNavigate(`settings/${encodeURIComponent(cat)}/${encodeURIComponent(sub)}`));
  return row;
}

// renderInto from the panel admin's settings.js: settings sharing a
// `section` get a card of their own under a small heading, and a `subpage`
// leaves an entry row where its group would be.
function renderInto(target, cat, list, subpage) {
  let heading = null, rows = [], entryRun = false;
  const flush = () => {
    if (!rows.length) return;
    if (heading && !(heading === subpage && !target.children.length)) {
      target.appendChild(el('h2', 'card-title', heading));
    }
    const c = el('div', 'card');
    rows.forEach((r) => c.appendChild(r));
    target.appendChild(c);
    rows = [];
  };
  const seen = new Set();
  for (const s of list) {
    const sub = s.subpage || null;
    if (sub !== subpage) {
      if (sub && !subpage && !seen.has(sub)) {
        seen.add(sub);
        flush();
        heading = null;
        entryRun = true;
        rows.push(subpageEntry(cat, sub));
      }
      continue;
    }
    const want = s.section || null;
    if (entryRun || want !== heading) { flush(); entryRun = false; heading = want; }
    rows.push(settingRow(s));
  }
  flush();
}

export function tabIdFor(cat) {
  return 'tab-set-' + cat.replace(/[^a-z0-9]+/gi, '-').toLowerCase();
}

function renderCategory(cat) {
  const tabEl = document.getElementById(tabIdFor(cat));
  if (!tabEl) return;
  const openSub = tabEl.querySelector(':scope > .subpage.open')?.dataset.subpage;
  const scroll = window.scrollY;
  tabEl.innerHTML = '';
  const list = view.definitions.filter((s) => categoryOf(s) === cat && visible(s));
  const meta = view.categories.find((c) => c.id === cat);
  if (meta && meta.note) {
    tabEl.appendChild(el('p', 'group-note', `Stays on each panel whatever the profile: ${meta.note}.`));
    tabEl.lastChild.style.margin = '0 20px 14px';
  }
  if (!list.length) {
    card(null, tabEl).appendChild(el('div', 'desc', 'Nothing to set here right now.'));
  }
  renderInto(tabEl, cat, list, null);
  const subs = [...new Set(list.filter((s) => s.subpage).map((s) => s.subpage))];
  for (const sub of subs) {
    const panel = el('div', 'subpage');
    panel.dataset.subpage = sub;
    renderInto(panel, cat, list, sub);
    tabEl.appendChild(panel);
  }
  if (openSub) {
    const p = tabEl.querySelector(`:scope > .subpage[data-subpage="${CSS.escape(openSub)}"]`);
    if (p) { p.classList.add('open'); tabEl.classList.add('sub-open'); }
    else tabEl.classList.remove('sub-open');
  }
  window.scrollTo(0, scroll);
}

// The categories with anything in them, in the order a panel lists them.
export function settingsCategories() {
  if (!view) return [];
  const have = new Set(view.definitions.map(categoryOf));
  return view.categories.filter((c) => have.has(c.id));
}

export function renderSettings(v, defaultProfile) {
  view = v;
  defaults = defaultProfile;
  byKey = Object.fromEntries(view.definitions.map((s) => [s.key, s]));
  const root = $('settingsTabs');
  root.innerHTML = '';
  for (const c of settingsCategories()) {
    const tabEl = el('div', 'tab');
    tabEl.id = tabIdFor(c.id);
    tabEl.dataset.category = c.id;
    root.appendChild(tabEl);
    renderCategory(c.id);
  }
}

// Show a category, or one of its second-level pages. Answers the subpage
// actually opened ('' for the page itself).
export function openCategory(cat, sub) {
  const tabEl = document.getElementById(tabIdFor(cat));
  if (!tabEl) return null;
  tabEl.querySelectorAll(':scope > .subpage').forEach((p) => p.classList.remove('open'));
  const panel = sub ? tabEl.querySelector(`:scope > .subpage[data-subpage="${CSS.escape(sub)}"]`) : null;
  if (panel) panel.classList.add('open');
  tabEl.classList.toggle('sub-open', !!panel);
  return panel ? sub : '';
}

// Settings search: every visible setting whose words match, by page.
export function searchSettings(q) {
  if (!view) return [];
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const inTitle = (s) => words.every((w) => `${s.title} ${s.key}`.toLowerCase().includes(w));
  return view.definitions.filter((s) => visible(s) &&
    words.every((w) => `${s.title} ${s.description} ${s.key} ${s.section || ''} ${s.subpage || ''}`.toLowerCase().includes(w)))
    // A match in the name before one in the description.
    .sort((a, b) => inTitle(b) - inTitle(a))
    .slice(0, 60);
}

export function initSettings({ navigate }) { onNavigate = navigate; }
