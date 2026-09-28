// Small pieces every page shares, drawn with the panel admin's classes
// (app.css): rows, cards, tags, the toast and the confirm dialog.

export const $ = (id) => document.getElementById(id);

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// Every call is relative, so the page works under ingress's path prefix.
// Answers { ok, status, data }; a network failure is status 0.
export async function api(path, { method = 'GET', body } = {}) {
  try {
    const r = await fetch(path, {
      method,
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
    });
    const data = await r.json().catch(() => null);
    return { ok: r.ok && (data?.ok !== false), status: r.status, data };
  } catch (e) {
    return { ok: false, status: 0, data: { error: 'Could not reach the add-on: ' + e.message } };
  }
}

export function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

export function tag(text, kind = '') {
  return el('span', 'tag' + (kind ? ' ' + kind : ''), text);
}

// A small primary-tinted heading over a rounded card, the device's section.
export function card(title, parent) {
  const out = [];
  if (title) out.push(el('h2', 'card-title', title));
  const c = el('div', 'card');
  out.push(c);
  if (parent) parent.append(...out);
  return c;
}

// A row with a name and a description, nothing trailing yet.
export function infoRow(name, desc = '') {
  const row = el('div', 'row');
  const info = el('div', 'info');
  info.append(el('div', 'name', name), el('div', 'desc', desc));
  row.appendChild(info);
  return row;
}

export function button(label, cls, onClick) {
  const b = el('button', cls, label);
  b.type = 'button';
  if (onClick) b.addEventListener('click', onClick);
  return b;
}

// Disable a button while its action runs, so a slow panel is not asked twice.
export async function busy(btn, fn) {
  const was = btn.textContent;
  btn.disabled = true;
  try { return await fn(); } finally { btn.disabled = false; btn.textContent = was; }
}

export function switchControl(checked, onChange) {
  const lbl = el('label', 'switch');
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.checked = !!checked;
  if (onChange) cb.addEventListener('change', () => onChange(cb.checked, cb));
  lbl.append(cb, el('span', 'slider'));
  return { el: lbl, input: cb };
}

const TOAST_ICONS = {
  success: '<path d="M5 12.5 10 17 19 7"/>',
  error: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5h.01"/>',
};
let toastTimer = null;

// The device's toast: one at a time, bottom center, gone after a while.
export function toast(message, kind = 'info', title = '') {
  document.querySelectorAll('.toast').forEach((t) => t.remove());
  const t = el('div', `toast toast-${kind === 'error' ? 'error' : kind === 'success' ? 'success' : 'info'}`);
  t.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  const disc = el('span', 'toast-disc');
  disc.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${TOAST_ICONS[kind] || TOAST_ICONS.info}</svg>`;
  const text = el('div', 'toast-text');
  if (title) text.appendChild(el('span', 'toast-title', title));
  text.appendChild(el('span', 'toast-msg', message));
  t.append(disc, text);
  t.addEventListener('click', () => t.remove());
  document.body.appendChild(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.remove(), kind === 'error' ? 8000 : 4000);
}

// The one modal scaffold: title, body, Cancel and the action. Resolves
// true when the action is picked.
export function confirmBox(title, message, action = 'OK', { danger = false } = {}) {
  return new Promise((resolve) => {
    const back = el('div', 'modal-back');
    const box = el('div', 'card modal-card');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    const body = el('div', 'modal-body desc', message);
    body.style.fontSize = '14.5px';
    const foot = el('div', 'modal-foot');
    const done = (v) => { back.remove(); document.removeEventListener('keydown', onKey); resolve(v); };
    const onKey = (e) => { if (e.key === 'Escape') done(false); };
    const ok = button(action, 'btn-primary', () => done(true));
    if (danger) ok.style.background = 'var(--error)';
    foot.append(button('Cancel', 'btn-text', () => done(false)), ok);
    box.append(el('h2', 'modal-title', title), body, foot);
    back.appendChild(box);
    back.addEventListener('click', (e) => { if (e.target === back) done(false); });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(back);
    ok.focus();
  });
}

// "3 min ago", the way a panel's own Fleet Management page says it.
export function ago(ms) {
  if (!ms) return '';
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 60) return 'just now';
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.floor(h / 24)} days ago`;
}
