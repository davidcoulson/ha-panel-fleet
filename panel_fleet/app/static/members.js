// Fleet: Panel Fleet leads, the panels follow. The leader, the fleet
// settings' definitions, and every Kiosk Satellite panel with its place in
// the fleet, drawn from /api/leader and redrawn on each refresh unless
// someone is in the middle of a control on it.

import { $, api, ago, busy, button, card, confirmBox, el, infoRow, tag, toast } from './ui.js';

let status = null;
let deps = null;
// The profile picked for a panel not yet invited, kept across redraws.
const invitePick = new Map();

function banner(kind, title, text) {
  const b = el('div', `banner ${kind}`);
  b.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5h.01"/></svg>';
  const text_ = el('div');
  text_.append(el('b', null, title), document.createTextNode(text));
  b.appendChild(text_);
  return b;
}

async function act(btn, path, method, body, done) {
  return busy(btn, async () => {
    const r = await api(path, { method, body });
    if (!r.ok) toast(r.data?.error || 'That did not work.', 'error', 'Fleet');
    else if (done) done(r);
    await deps.reload();
    return r;
  });
}

function profileSelect(value, onChange) {
  const sel = document.createElement('select');
  for (const p of status.profiles) {
    const o = document.createElement('option');
    o.value = p.id;
    o.textContent = p.name;
    o.selected = p.id === value;
    sel.appendChild(o);
  }
  sel.title = 'Profile';
  sel.addEventListener('change', () => onChange(sel.value, sel));
  return sel;
}

function memberRow(m) {
  const row = el('div', 'row pf-member');
  const info = el('div', 'info');
  const name = el('div', 'name', m.name || m.id);
  const desc = el('div', 'desc');
  desc.appendChild(el('span', 'pf-mono', m.address ? `${m.address}:${m.port}` : m.id));
  if (m.version) desc.appendChild(tag(m.version));
  if (m.tls) desc.appendChild(tag('HTTPS'));
  if (m.agent) desc.appendChild(tag('Agent', 'agent'));
  const stateKind = { member: 'ok', invited: 'warn', declined: 'err', left: '' }[m.state] || '';
  desc.appendChild(tag(m.stateText, stateKind));
  if (m.member && m.profile && m.profile !== 'default') desc.appendChild(tag(m.profileName));
  info.append(name, desc);
  row.appendChild(info);

  const side = el('div', 'pf-member-side');
  if (m.state === 'member') {
    const words = m.phase === 'synced' && m.lastSyncAt ? `In sync · ${ago(m.lastSyncAt)}` : m.status;
    side.appendChild(el('span', `fleet-status ${m.tone === 'ok' ? 'ok' : m.tone === 'warn' ? 'warn' : ''}`, words));
  } else if (m.state === 'invited') {
    side.appendChild(el('span', 'fleet-status warn', m.online === false ? 'Offline' : 'Tap Accept on the panel'));
  }
  if (m.member) {
    side.appendChild(profileSelect(m.profile, (pid, sel) =>
      act(sel, `api/members/${encodeURIComponent(m.id)}/profile`, 'POST', { profile: pid })));
  } else {
    side.appendChild(profileSelect(invitePick.get(m.id) || 'default', (pid) => invitePick.set(m.id, pid)));
  }
  if (m.state === 'member') {
    side.appendChild(button('Sync now', 'btn-ghost', (e) =>
      act(e.currentTarget, 'api/sync', 'POST', { id: m.id })));
  }
  if (m.state !== 'member' && m.state !== 'invited') {
    const label = m.state === 'none' ? 'Invite' : 'Invite again';
    const b = button(label, 'btn-primary', (e) =>
      act(e.currentTarget, `api/members/${encodeURIComponent(m.id)}/invite`, 'POST',
        { profile: m.member ? m.profile : (invitePick.get(m.id) || 'default') },
        () => toast(`Tap Accept on ${m.name || 'the panel'}'s screen to join.`, 'success', 'Invitation sent')));
    b.disabled = m.discovered === false && !m.address;
    side.appendChild(b);
  }
  if (m.member) {
    const label = { member: 'Remove', invited: 'Cancel invitation' }[m.state] || 'Forget';
    side.appendChild(button(label, 'btn-ghost', async (e) => {
      const btn = e.currentTarget;
      if (m.state === 'member' && !await confirmBox(`Remove ${m.name}?`,
        'It keeps the settings it has and stops following Panel Fleet. It can be invited again.',
        'Remove', { danger: true })) return;
      act(btn, `api/members/${encodeURIComponent(m.id)}`, 'DELETE');
    }));
  }
  row.appendChild(side);
  return row;
}

export function renderFleet(data, force = false) {
  if (!data) return;
  status = data;
  const root = $('fleetBody');
  // Someone is choosing a profile or pressing a button: the redraw waits
  // for the next refresh rather than yank the control away.
  if (!force && root.contains(document.activeElement) && document.activeElement !== root) return;
  root.innerHTML = '';
  const L = data.leader;
  if (!L.listening) {
    root.appendChild(banner('error', `Nothing answers on port ${L.port}. `,
      'Panels check an invitation by calling Panel Fleet back on fleet_port, so none can join. See the add-on log, or pick another fleet_port.'));
  }
  if (!data.passwordSet) {
    root.appendChild(banner('warn', 'No panel password. ',
      "Set panel_password in the add-on's Configuration to read the fleet settings from a panel."));
  }

  const lead = card('Leader', root);
  const who = infoRow('Panel Fleet leads this fleet',
    `Leader ${L.id} · panels call back ${L.address || 'this host'}:${L.port}` +
    (L.lastTick ? ` · last checked ${ago(L.lastTick * 1000)}` : ''));
  who.appendChild(button('Sync now', 'btn-primary', (e) => act(e.currentTarget, 'api/sync', 'POST', {})));
  lead.appendChild(who);

  const s = data.store;
  const defs = card('Fleet settings', root);
  defs.appendChild(infoRow(s.version ? `Kiosk Satellite ${s.version}` : 'Not imported yet',
    s.version
      ? `${s.count} settings, read from ${s.source || 'a panel'}${s.importedAt ? ` ${ago(s.importedAt)}` : ''}. Pushed only to panels on this version.`
      : 'Import them from a panel before anything can be pushed.'));
  const sources = data.members.filter((m) => m.discovered && !m.agent && m.reachable !== false);
  const imp = infoRow('Import from panel',
    "Replaces the definitions and every fleet value with that panel's, its credentials included.");
  imp.classList.add('pf-wide');
  const impSide = el('div', 'pf-leader-actions');
  const pick = document.createElement('select');
  for (const m of sources) {
    const o = document.createElement('option');
    o.value = m.id;
    o.textContent = `${m.name}${m.version ? ` (${m.version})` : ''}`;
    // The panel the settings came from, unless it is gone.
    o.selected = m.id === s.sourceId;
    pick.appendChild(o);
  }
  if (!sources.length) {
    const o = document.createElement('option');
    o.textContent = 'No panel online';
    pick.appendChild(o);
    pick.disabled = true;
  }
  const impBtn = button('Import', 'btn-ghost', async (e) => {
    const btn = e.currentTarget;
    const src = sources.find((m) => m.id === pick.value);
    if (s.version && !await confirmBox('Replace the fleet settings?',
      `Every fleet setting becomes what ${src?.name || 'that panel'} has now. Followers get it at the next sync.`,
      'Import')) return;
    act(btn, 'api/fleet-settings/import', 'POST', { panel: pick.value }, () => {
      toast(`Fleet settings read from ${src?.name || 'the panel'}.`, 'success', 'Imported');
      deps.settingsChanged();
    });
  });
  impBtn.disabled = !sources.length || !data.passwordSet;
  impSide.append(pick, impBtn);
  imp.appendChild(impSide);
  defs.appendChild(imp);
  const newest = data.members.find((m) => m.id === data.newestPanel);
  const ref = infoRow('Refresh definitions',
    newest
      ? `When the panels move to a newer version: reads the definitions from ${newest.name} (${newest.version}), keeps the fleet's values, adds new settings with that panel's values and drops removed ones.`
      : 'Needs an online panel to read from.');
  ref.classList.add('pf-wide');
  const refBtn = button('Refresh', 'btn-ghost', (e) =>
    act(e.currentTarget, 'api/fleet-settings/refresh', 'POST', {}, () => {
      toast('Definitions refreshed.', 'success', 'Fleet settings');
      deps.settingsChanged();
    }));
  refBtn.disabled = !newest || !s.version || !data.passwordSet;
  ref.appendChild(refBtn);
  defs.appendChild(ref);

  const list = card('Panels', root);
  if (!data.members.length) {
    list.appendChild(infoRow('No Kiosk Satellite panels found yet',
      'A panel shows here once its remote admin and Find other kiosks are on.'));
  }
  for (const m of data.members) list.appendChild(memberRow(m));
  root.appendChild(el('p', 'group-note',
    "An invitation waits on the panel's own screen until someone taps Accept there; Panel Fleet cannot accept it for the panel. " +
    'A member only gets settings while it runs the version the fleet settings came from.'));
}

export function initFleet(d) { deps = d; }
