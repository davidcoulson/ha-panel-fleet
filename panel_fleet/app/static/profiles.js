// Profiles: what a follower gets. The Default (editable), Updates only
// (syncs nothing, fixed) and the leader's own, each with its categories,
// credentials, dashboard switch and excluded settings, as on a panel's own
// Fleet Management page. Drawn when loaded or saved, never on a timer.

import { $, api, busy, button, card, confirmBox, el, infoRow, switchControl, tag, toast } from './ui.js';

let view = null;
let draft = null;      // the profile being edited, a copy
let excludedQuery = '';
let deps = null;

const isUpdatesOnly = (p) => p.id === 'updates-only';

function checkRow(name, desc, checked, disabled, onChange) {
  const row = infoRow(name, desc);
  row.classList.add('pf-check-row');
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.checked = checked;
  cb.disabled = disabled;
  cb.addEventListener('change', () => onChange(cb.checked));
  row.prepend(cb);
  if (!disabled) {
    row.addEventListener('click', (e) => {
      if (e.target !== cb) { cb.checked = !cb.checked; onChange(cb.checked); }
    });
  }
  return row;
}

function renderList(root) {
  const top = card(null, root);
  const add = infoRow('New profile', "Starts from the Default's choices. Assign it to a panel on the Fleet page.");
  add.appendChild(button('New profile', 'btn-primary', () => {
    const d = view.profiles.find((p) => p.id === 'default');
    draft = { id: '', name: '', categories: [...d.categories], credentials: [...d.credentials],
      dashboard: d.dashboard, excluded: [...d.excluded] };
    renderProfiles(view);
  }));
  top.appendChild(add);
  const list = card('Profiles', root);
  for (const p of view.profiles) {
    const row = infoRow(p.name, p.describe);
    row.classList.add('fleet-row');
    row.tabIndex = 0;
    const side = el('div', 'pf-member-side');
    side.appendChild(tag(`${p.members} panel${p.members === 1 ? '' : 's'}`));
    if (p.builtIn) side.appendChild(tag('Built in'));
    const chev = el('span', 'chev');
    chev.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>';
    chev.style.color = 'var(--muted)';
    side.appendChild(chev);
    row.appendChild(side);
    const open = () => { draft = JSON.parse(JSON.stringify(p)); excludedQuery = ''; renderProfiles(view); };
    row.addEventListener('click', open);
    row.addEventListener('keydown', (e) => { if (e.key === 'Enter') open(); });
    list.appendChild(row);
  }
  root.appendChild(el('p', 'group-note',
    'What never travels, whatever a profile says: each panel\'s identity, its remote admin and fleet settings, and the hardware picks Kiosk Satellite marks per device.'));
}

function renderEditor(root) {
  const fixed = isUpdatesOnly(draft);
  const isDefault = draft.id === 'default';
  const back = el('div', 'pf-profile-actions');
  back.style.justifyContent = 'flex-start';
  back.appendChild(button('← All profiles', 'btn-text', () => { draft = null; renderProfiles(view); }));
  root.appendChild(back);

  const named = card(draft.id ? 'Profile' : 'New profile', root);
  const nameRow = infoRow('Name', isDefault ? 'The Default is what a panel gets unless it is given another.'
    : fixed ? 'Syncs nothing: a panel on it keeps every setting of its own.' : '');
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'pf-profile-name';
  input.value = draft.name;
  input.disabled = isDefault || fixed;
  input.placeholder = 'Hallway panels';
  input.addEventListener('input', () => { draft.name = input.value; });
  nameRow.appendChild(input);
  named.appendChild(nameRow);

  const cats = card('Categories', root);
  for (const c of view.categories) {
    cats.appendChild(checkRow(c.title, c.note ? `Stays on each panel: ${c.note}.` : '',
      draft.categories.includes(c.id), fixed, (on) => {
        draft.categories = on ? [...draft.categories, c.id] : draft.categories.filter((x) => x !== c.id);
      }));
  }

  const creds = card('Credentials', root);
  for (const c of view.credentials) {
    const row = infoRow(c.title, `${c.key}: off keeps each panel's own.`);
    row.appendChild(switchControl(draft.credentials.includes(c.key), (on) => {
      draft.credentials = on ? [...draft.credentials, c.key] : draft.credentials.filter((x) => x !== c.key);
    }).el);
    row.querySelector('input').disabled = fixed;
    creds.appendChild(row);
  }
  const dash = infoRow('Include the dashboard', `${view.dashboardKeys.join(', ')}: the start page each panel opens.`);
  dash.appendChild(switchControl(draft.dashboard, (on) => { draft.dashboard = on; }).el);
  dash.querySelector('input').disabled = fixed;
  creds.appendChild(dash);

  const exHead = el('h2', 'card-title', `Excluded settings (${draft.excluded.length})`);
  root.appendChild(exHead);
  const ex = el('div', 'card');
  root.appendChild(ex);
  if (!view.syncable.length) {
    ex.appendChild(infoRow('No fleet settings yet', 'Import them from a panel on the Fleet page to pick from them.'));
  } else {
    const search = document.createElement('input');
    search.type = 'search';
    search.className = 'field';
    search.style.marginTop = '12px';
    search.placeholder = 'Search settings to exclude';
    search.value = excludedQuery;
    const list = el('div', 'pf-excluded-list');
    const draw = () => {
      list.innerHTML = '';
      const q = excludedQuery.trim().toLowerCase();
      const all = view.syncable.filter((s) => !q ||
        `${s.title} ${s.key} ${s.category} ${s.subpage || ''}`.toLowerCase().includes(q));
      // What is excluded first, so the list says what the profile leaves out.
      all.sort((a, b) => (draft.excluded.includes(b.key) - draft.excluded.includes(a.key)));
      for (const s of all.slice(0, 400)) {
        list.appendChild(checkRow(s.title,
          `${s.category}${s.subpage ? ' › ' + s.subpage : ''} · ${s.key}${s.hidden ? ' · hidden' : ''}`,
          draft.excluded.includes(s.key), fixed, (on) => {
            draft.excluded = on ? [...draft.excluded, s.key] : draft.excluded.filter((k) => k !== s.key);
            exHead.textContent = `Excluded settings (${draft.excluded.length})`;
          }));
      }
      if (!all.length) list.appendChild(infoRow('Nothing matches', ''));
    };
    search.addEventListener('input', () => { excludedQuery = search.value; draw(); });
    ex.append(search, list);
    draw();
  }

  const actions = el('div', 'pf-profile-actions');
  if (draft.id) {
    actions.appendChild(button('Duplicate', 'btn-ghost', () => {
      draft = { ...JSON.parse(JSON.stringify(draft)), id: '', name: `${draft.name} copy` };
      renderProfiles(view);
    }));
  }
  if (draft.id && !draft.builtIn) {
    actions.appendChild(button('Delete', 'btn-ghost', async (e) => {
      const btn = e.currentTarget;
      if (!await confirmBox(`Delete ${draft.name}?`, 'Panels on it get the Default.', 'Delete', { danger: true })) return;
      await busy(btn, async () => {
        const r = await api(`api/profiles/${encodeURIComponent(draft.id)}`, { method: 'DELETE' });
        if (!r.ok) return toast(r.data?.error || 'Could not delete it.', 'error', 'Profiles');
        draft = null;
        await deps.reloadProfiles();
      });
    }));
  }
  if (!fixed) {
    actions.appendChild(button('Save', 'btn-primary', async (e) => {
      await busy(e.currentTarget, async () => {
        const { members, describe, builtIn, ...profile } = draft;
        const r = await api('api/profiles', { method: 'POST', body: { profile } });
        if (!r.ok) return toast(r.data?.error || 'Could not save it.', 'error', 'Profiles');
        toast(`${profile.name || 'Profile'} saved. Its panels get it at the next sync.`, 'success', 'Profiles');
        draft = null;
        await deps.reloadProfiles();
      });
    }));
  }
  root.appendChild(actions);
}

export function renderProfiles(v) {
  if (!v) return;
  view = v;
  const root = $('profilesBody');
  root.innerHTML = '';
  if (draft) renderEditor(root); else renderList(root);
}

export function initProfiles(d) { deps = d; }
