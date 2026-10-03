// Fleet: Panel Fleet leads, the panels follow. The leader, the fleet
// settings' definitions, and every Kiosk Satellite panel with its place in
// the fleet, drawn from /api/leader and redrawn on each refresh unless
// someone is in the middle of a control on it.

import { $, api, ago, busy, button, card, confirmBox, el, infoRow, tag, toast } from './ui.js';

let status = null;
let deps = null;
// The profile picked for a panel not yet invited, and whether to accept the
// invitation for it, kept across redraws.
const invitePick = new Map();
const acceptPick = new Map();
// Add by IP: what was typed and who answered there.
const ip = { address: '', port: '2324', found: null };

const ACCEPT_LABEL = 'Accept remotely using the panel password';

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

// An agent (a projector, a media box) gets Updates only unless told
// otherwise: it shows no dashboard, so the wall panels' settings mean
// nothing to it.
function defaultProfile(m) {
  return m.agent ? status.updatesOnly : 'default';
}

// Accepting for the panel is on by default for an agent: tapping Accept on
// its screen would mean waking a projector in an empty room.
function acceptBox(key, agent) {
  const lbl = el('label', 'pf-accept');
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.disabled = !status.passwordSet;
  cb.checked = status.passwordSet && (acceptPick.has(key) ? acceptPick.get(key) : !!agent);
  cb.addEventListener('change', () => acceptPick.set(key, cb.checked));
  lbl.title = status.passwordSet
    ? "Logs in to the panel's remote admin and accepts there, as tapping Accept in its admin would. Nothing shows on its screen."
    : 'Set panel_password in the add-on configuration first.';
  lbl.append(cb, el('span', null, ACCEPT_LABEL));
  return { el: lbl, input: cb };
}

function invited(r, name) {
  const d = r.data || {};
  if (d.accepted) toast(`${name} joined the fleet.`, 'success', 'Accepted for it');
  else if (d.acceptError) toast(`Invited, but not accepted: ${d.acceptError}`, 'error', 'Fleet');
  else if (d.pending) toast(`Tap Accept on ${name}'s screen to join.`, 'success', 'Invitation sent');
  else toast(`${name} is in the fleet again.`, 'success', 'Fleet');
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
    side.appendChild(profileSelect(invitePick.get(m.id) || defaultProfile(m), (pid) => invitePick.set(m.id, pid)));
  }
  if (m.state === 'member') {
    side.appendChild(button('Sync now', 'btn-ghost', (e) =>
      act(e.currentTarget, 'api/sync', 'POST', { id: m.id })));
  }
  if (m.state === 'invited') {
    const b = button('Accept for it', 'btn-primary', (e) =>
      act(e.currentTarget, `api/members/${encodeURIComponent(m.id)}/accept`, 'POST', {},
        () => toast(`${m.name || 'The panel'} joined the fleet.`, 'success', 'Accepted for it')));
    b.disabled = !status.passwordSet;
    b.title = status.passwordSet ? `${ACCEPT_LABEL}: nothing shows on its screen.`
      : 'Set panel_password in the add-on configuration first.';
    side.appendChild(b);
  }
  if (m.state !== 'member' && m.state !== 'invited') {
    const accept = acceptBox(m.id, m.agent);
    side.appendChild(accept.el);
    const label = m.state === 'none' ? 'Invite' : 'Invite again';
    const b = button(label, 'btn-primary', (e) =>
      act(e.currentTarget, `api/members/${encodeURIComponent(m.id)}/invite`, 'POST',
        { profile: m.member ? m.profile : (invitePick.get(m.id) || defaultProfile(m)),
          accept: accept.input.checked },
        (r) => invited(r, m.name || 'the panel')));
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

  renderAddByIp(root);

  const list = card('Panels', root);
  if (!data.members.length) {
    list.appendChild(infoRow('No Kiosk Satellite panels found yet',
      'A panel shows here once its remote admin and Find other kiosks are on.'));
  }
  for (const m of data.members) list.appendChild(memberRow(m));
  root.appendChild(el('p', 'group-note',
    "An invitation waits on the panel's own screen until someone taps Accept there, or until Panel Fleet accepts it for the panel " +
    "through its remote admin with panel_password (on by default for agents, whose screen is never woken). " +
    'A member only gets settings while it runs the version the fleet settings came from.'));
}

// Add by IP: a kiosk discovery cannot see (another VLAN, no multicast
// reflector), found by its address the way a panel leader's Add by IP
// finds one, then invited like any other.
function renderAddByIp(root) {
  const box = card('Add by IP', root);
  const row = infoRow('Find a kiosk by its address',
    "For one mDNS does not reach. Panel Fleet checks who answers there before anything is sent; the kiosk must reach this host's fleet_port too.");
  row.classList.add('pf-wide');
  const form = el('div', 'pf-ip-form');
  const addr = document.createElement('input');
  addr.type = 'text';
  addr.placeholder = '10.2.1.4';
  addr.value = ip.address;
  addr.setAttribute('aria-label', 'IP address');
  addr.addEventListener('input', () => { ip.address = addr.value; });
  const port = document.createElement('input');
  port.type = 'number';
  port.min = '1';
  port.max = '65535';
  port.value = ip.port;
  port.setAttribute('aria-label', 'Remote admin port');
  port.addEventListener('input', () => { ip.port = port.value; });
  const find = button('Find kiosk', 'btn-ghost', (e) => busy(e.currentTarget, async () => {
    const r = await api('api/members/lookup', { method: 'POST', body: { address: addr.value.trim(), port: port.value } });
    ip.found = r.ok ? r.data.kiosk : null;
    if (!r.ok) toast(r.data?.error || 'That did not work.', 'error', 'Add by IP');
    renderFleet(status, true);
  }));
  addr.addEventListener('keydown', (e) => { if (e.key === 'Enter') find.click(); });
  form.append(addr, port, find);
  row.appendChild(form);
  box.appendChild(row);

  const k = ip.found;
  if (!k) return;
  const known = status.members.find((m) => m.id === k.id);
  const found = el('div', 'row pf-member');
  const info = el('div', 'info');
  const desc = el('div', 'desc');
  desc.appendChild(el('span', 'pf-mono', `${k.address}:${k.port}`));
  if (k.version) desc.appendChild(tag(k.version));
  if (k.tls) desc.appendChild(tag('HTTPS'));
  if (known?.agent) desc.appendChild(tag('Agent', 'agent'));
  info.append(el('div', 'name', k.name || k.id), desc);
  found.appendChild(info);
  const side = el('div', 'pf-member-side');
  const key = `ip:${k.id}`;
  side.appendChild(profileSelect(invitePick.get(key) || (known?.agent ? status.updatesOnly : 'default'),
    (pid) => invitePick.set(key, pid)));
  // Not knowing what it is, accepting for it is the safe default: an agent
  // must never be asked on its screen.
  const accept = acceptBox(key, known ? known.agent : true);
  side.appendChild(accept.el);
  side.appendChild(button('Send invitation', 'btn-primary', (e) =>
    act(e.currentTarget, `api/members/${encodeURIComponent(k.id)}/invite`, 'POST',
      { profile: invitePick.get(key) || (known?.agent ? status.updatesOnly : 'default'),
        address: k.address, port: k.port, accept: accept.input.checked },
      (r) => { ip.found = null; invited(r, k.name || 'the kiosk'); })));
  side.appendChild(button('Cancel', 'btn-text', () => { ip.found = null; renderFleet(status, true); }));
  found.appendChild(side);
  box.appendChild(found);
}

export function initFleet(d) { deps = d; }
