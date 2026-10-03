// Wake word models: the custom models Panel Fleet holds, and mirroring
// them on every member whose profile syncs Voice Satellite, as a panel
// leader passes its own. Off until switched on: mirroring deletes.

import { $, api, busy, button, card, confirmBox, el, infoRow, mb, switchControl, tag, toast, upload } from './ui.js';

let view = null;
let deps = null;
let plan = null;      // the last comparison
let planFor = '';     // '' for the members, else a panel id
let panels = [];      // discovered panels, to compare with

function modelRow(m) {
  const row = infoRow(m.wakeWord ? `${m.wakeWord} (${m.id})` : m.id, '');
  const desc = row.querySelector('.desc');
  desc.appendChild(tag(m.engineName));
  desc.appendChild(document.createTextNode(' ' + m.files.map((f) => `${f.name} · ${mb(f.size)}`).join(', ')));
  row.appendChild(button('Delete', 'btn-ghost', async (e) => {
    const btn = e.currentTarget;
    if (!await confirmBox(`Delete ${m.id}?`,
      view.enabled ? 'It is removed from Panel Fleet, and from every member that mirrors the set at the next sync.'
        : 'It is removed from Panel Fleet.', 'Delete', { danger: true })) return;
    busy(btn, async () => {
      const r = await api(`api/wake-models/${encodeURIComponent(m.engine)}/${encodeURIComponent(m.id)}`, { method: 'DELETE' });
      if (!r.ok) toast(r.data?.error || 'That did not work.', 'error', 'Wake word models');
      plan = null;
      await deps.reload();
    });
  }));
  return row;
}

function list(paths) {
  const ul = el('ul', 'pf-file-list pf-mono-list');
  for (const p of paths.slice(0, 12)) ul.appendChild(el('li', null, p));
  if (paths.length > 12) ul.appendChild(el('li', null, `and ${paths.length - 12} more`));
  return ul;
}

function planRow(r) {
  const row = el('div', 'row pf-member');
  const info = el('div', 'info');
  const desc = el('div', 'desc');
  if (r.error) {
    desc.appendChild(el('span', null, r.error));
  } else {
    desc.appendChild(el('span', null, `${r.theirs} file${r.theirs === 1 ? '' : 's'} there, ${r.same} the same`));
    if (planFor === '' && !r.syncs) desc.appendChild(tag('Its profile does not sync Voice Satellite'));
  }
  info.append(el('div', 'name', r.name), desc);
  if (!r.error && r.send.length) { info.appendChild(el('div', 'desc', `To send (${r.send.length}):`)); info.appendChild(list(r.send)); }
  if (!r.error && r.remove.length) {
    info.appendChild(el('div', 'desc', planFor === '' ? `To remove (${r.remove.length}):` : `Only on the panel (${r.remove.length}):`));
    info.appendChild(list(r.remove));
  }
  row.appendChild(info);
  const side = el('div', 'pf-member-side');
  if (!r.error) {
    const same = !r.send.length && !r.remove.length;
    side.appendChild(el('span', `fleet-status ${same ? 'ok' : 'warn'}`, same ? 'Same set' : 'Differs'));
  }
  row.appendChild(side);
  return row;
}

export function renderWake(data, discovered, force = false) {
  if (!data) return;
  view = data;
  panels = discovered || panels;
  const root = $('wakeBody');
  if (!force && root.contains(document.activeElement) && document.activeElement !== root) return;
  root.innerHTML = '';

  const sync = card('Mirroring', root);
  const on = infoRow('Mirror these models on the members',
    'Every member whose profile syncs Voice Satellite gets exactly this set: missing or changed files are sent, files Panel Fleet does not hold are removed, and the member cannot add or delete models itself. Compared by checksum, so an unchanged set costs one small request.');
  const sw = switchControl(view.enabled, async (v, cb) => {
    if (v && !await confirmBox('Mirror the models?',
      "Members whose profile syncs Voice Satellite lose every custom model that is not in this set. Compare with the members first.",
      'Mirror')) { cb.checked = false; return; }
    cb.disabled = true;
    const r = await api('api/wake-models/enabled', { method: 'POST', body: { enabled: v } });
    if (!r.ok) toast(r.data?.error || 'That did not work.', 'error', 'Wake word models');
    await deps.reload();
  });
  sw.input.disabled = !view.enabled && !view.models.length;
  on.appendChild(sw.el);
  sync.appendChild(on);

  const models = card(`Models (${view.models.length})`, root);
  const add = infoRow('Add models',
    'Pick every file of one or more models at once: name.json and name.tflite for microWakeWord, name.json and name.onnx for vsWakeWord, name.onnx or name.tflite for openWakeWord. The file name is the model\'s id; one of the same name and engine is replaced.');
  add.classList.add('pf-wide');
  const pick = document.createElement('input');
  pick.type = 'file';
  pick.multiple = true;
  pick.accept = '.json,.tflite,.onnx';
  pick.hidden = true;
  pick.addEventListener('change', async () => {
    const files = [...pick.files];
    pick.value = '';
    if (!files.length) return;
    const btn = add.querySelector('button');
    btn.disabled = true;
    btn.textContent = 'Adding…';
    const refused = [];
    for (const f of files) {
      const r = await upload(`api/wake-models/stage?name=${encodeURIComponent(f.name)}`, f);
      if (!r.ok) refused.push(`${f.name}: ${r.data?.error || 'not taken'}`);
    }
    const c = await api('api/wake-models/commit', { method: 'POST', body: {} });
    for (const x of c.data?.rejected || []) refused.push(`${x.file}: ${x.reason}`);
    const added = c.data?.added || [];
    if (added.length) toast(`${added.map((a) => a.id).join(', ')}.`, 'success', `Added ${added.length} model${added.length === 1 ? '' : 's'}`);
    if (refused.length) toast(refused.join(' · '), 'error', 'Refused');
    plan = null;
    await deps.reload();
  });
  add.append(pick, button('Add files', 'btn-primary', () => pick.click()));
  models.appendChild(add);
  for (const m of view.models) models.appendChild(modelRow(m));

  const cmp = card('Compare', root);
  const row = infoRow('Compare by checksum',
    "What mirroring would do on each member, or what a panel holds against this set. A panel's model files cannot be read back through its admin, so models are added here, not imported.");
  row.classList.add('pf-wide');
  const side = el('div', 'pf-leader-actions');
  const sel = document.createElement('select');
  const o = document.createElement('option');
  o.value = '';
  o.textContent = 'The members';
  sel.appendChild(o);
  for (const p of panels) {
    const x = document.createElement('option');
    x.value = p.id;
    x.textContent = p.name;
    sel.appendChild(x);
  }
  sel.value = planFor;
  sel.addEventListener('change', () => { planFor = sel.value; plan = null; renderWake(view, panels, true); });
  side.append(sel, button('Compare', 'btn-ghost', (e) => busy(e.currentTarget, async () => {
    const r = await api('api/wake-models/plan', { method: 'POST', body: { panel: planFor || null } });
    plan = r.ok ? r.data : null;
    if (!r.ok || r.data?.error) toast(r.data?.error || 'That did not work.', 'error', 'Compare');
    renderWake(view, panels, true);
  })));
  row.appendChild(side);
  cmp.appendChild(row);
  if (plan) {
    if (!plan.rows.length) cmp.appendChild(infoRow('Nothing to compare with', planFor ? '' : 'No members yet.'));
    for (const r of plan.rows) cmp.appendChild(planRow(r));
  }
  root.appendChild(el('p', 'group-note',
    'As with a panel leader, models travel only to a member on the fleet settings\' version, after its settings. Panel Fleet checks the files it can without running them (names, manifests, which files belong together, a TFLite header); a member does not check what its leader sends, so try a new model on one panel first.'));
}

export function initWake(d) { deps = d; }
