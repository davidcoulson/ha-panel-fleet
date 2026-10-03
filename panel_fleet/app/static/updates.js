// Updates: the APKs Panel Fleet holds (one per ABI) and installing them on
// the members, as a panel leader's "Install on the fleet" does: streamed to
// each member with its fleet token, then installed there, one at a time.
// An agent is only ever updated when it installs silently.

import { $, ago, api, bar, busy, button, card, confirmBox, el, infoRow, mb, switchControl, tag, toast, upload } from './ui.js';

let view = null;
let deps = null;
let uploading = null; // {name, fraction} while an APK goes up

function phaseWords(r) {
  switch (r.phase) {
    case 'queued': return ['Waiting its turn', ''];
    case 'sending': return [`Sending ${Math.round((r.progress || 0) * 100)}%`, ''];
    case 'installing': return [r.reason || 'Installing…', ''];
    case 'updated': return [r.reason || 'Updated', 'ok'];
    case 'current': return [r.reason || 'Up to date', 'ok'];
    case 'skipped': return [r.reason || 'Skipped', 'warn'];
    case 'failed': return [r.reason || 'Failed', 'warn'];
    default: return null;
  }
}

function memberRow(r) {
  const row = el('div', 'row pf-member');
  const info = el('div', 'info');
  const desc = el('div', 'desc');
  if (r.version) desc.appendChild(tag(r.version));
  if (r.agent) desc.appendChild(tag(r.agentKnown ? 'Agent' : 'Agent?', 'agent'));
  if (r.abis?.length) desc.appendChild(el('span', 'pf-mono', r.abis[0]));
  if (r.installer) desc.appendChild(el('span', null, r.installer));
  info.append(el('div', 'name', r.name || r.id), desc);
  row.appendChild(info);
  const side = el('div', 'pf-member-side');
  const phase = phaseWords(r);
  if (r.phase === 'sending') side.appendChild(bar(r.progress));
  if (phase) {
    side.appendChild(el('span', `fleet-status ${phase[1]}`, phase[0]));
  } else if (r.blocker) {
    side.appendChild(el('span', `fleet-status ${r.blocker.startsWith('Already') ? 'ok' : 'warn'}`, r.blocker));
  } else if (r.apk) {
    side.appendChild(el('span', 'fleet-status', `Gets ${r.apk.versionName} (${r.apk.abis.join(', ') || 'any ABI'})`));
  }
  const b = button('Update', 'btn-ghost', (e) => busy(e.currentTarget, async () => {
    const res = await api('api/updates/install', { method: 'POST', body: { id: r.id } });
    if (!res.ok) toast(res.data?.error || 'That did not work.', 'error', 'Updates');
    await deps.reload();
  }));
  b.disabled = view.running || !!r.blocker;
  side.appendChild(b);
  row.appendChild(side);
  return row;
}

function apkRow(a) {
  const row = infoRow(`${a.versionName} · ${a.abis.length ? a.abis.join(', ') : 'any ABI'}`,
    `Build ${a.versionCode} · ${mb(a.size)}${a.name ? ` · ${a.name}` : ''} · uploaded ${ago(a.uploadedAt)}`);
  row.appendChild(button('Remove', 'btn-ghost', async (e) => {
    const btn = e.currentTarget;
    if (!await confirmBox('Remove this APK?', `${a.versionName} for ${a.abis.join(', ') || 'any ABI'} is deleted from Panel Fleet.`, 'Remove', { danger: true })) return;
    busy(btn, async () => {
      const r = await api(`api/updates/apk/${encodeURIComponent(a.id)}`, { method: 'DELETE' });
      if (!r.ok) toast(r.data?.error || 'That did not work.', 'error', 'Updates');
      await deps.reload();
    });
  }));
  return row;
}

export function renderUpdates(data, force = false) {
  if (!data) return;
  view = data;
  const root = $('updatesBody');
  if (!force && root.contains(document.activeElement) && document.activeElement !== root
    && !view.running) return;
  root.innerHTML = '';

  const apks = card('APKs', root);
  const add = infoRow('Upload an APK',
    'A Kiosk Satellite APK, read here for its version and ABIs. Panel Fleet keeps one per ABI: arm64-v8a for the wall panels, armeabi-v7a for 32-bit boxes such as the projectors, or a universal one. A new one replaces the one for the same ABIs.');
  add.classList.add('pf-wide');
  const pick = document.createElement('input');
  pick.type = 'file';
  pick.accept = '.apk,application/vnd.android.package-archive';
  pick.hidden = true;
  pick.addEventListener('change', async () => {
    const f = pick.files[0];
    pick.value = '';
    if (!f) return;
    uploading = { name: f.name, fraction: 0 };
    renderUpdates(view, true);
    const r = await upload(`api/updates/apk?name=${encodeURIComponent(f.name)}`, f, (x) => {
      uploading.fraction = x;
      const b = root.querySelector('.pf-uploading .pf-bar > span');
      if (b) b.style.width = `${Math.round(x * 100)}%`;
    });
    uploading = null;
    if (r.ok) toast(`${r.data.apk.versionName} for ${r.data.apk.abis.join(', ') || 'any ABI'} (${mb(r.data.apk.size)}).`, 'success', 'APK stored');
    else toast(r.data?.error || 'The upload failed.', 'error', 'Updates');
    await deps.reload();
  });
  const upBtn = button('Upload APK', 'btn-primary', () => pick.click());
  upBtn.disabled = !!uploading || view.running;
  add.append(pick, upBtn);
  apks.appendChild(add);
  if (uploading) {
    const u = infoRow(`Uploading ${uploading.name}`, '');
    u.classList.add('pf-uploading');
    u.appendChild(bar(uploading.fraction));
    apks.appendChild(u);
  }
  for (const a of view.apks) apks.appendChild(apkRow(a));
  if (view.mixedVersions) {
    const warn = infoRow('The APKs are different versions', 'Upload the same build for every ABI, or the members end up on different versions.');
    warn.querySelector('.name').classList.add('pf-notice');
    apks.appendChild(warn);
  }

  const fleet = card('Install on the fleet', root);
  const keep = infoRow('Keep members on this version',
    "A member that comes back behind its APK is sent it, once per APK, under the same rules as Update the fleet.");
  keep.appendChild(switchControl(view.keep, async (on, cb) => {
    cb.disabled = true;
    const r = await api('api/updates/keep', { method: 'POST', body: { keep: on } });
    if (!r.ok) toast(r.data?.error || 'That did not work.', 'error', 'Updates');
    await deps.reload();
  }).el);
  fleet.appendChild(keep);
  const go = infoRow('Update the fleet',
    view.run && !view.run.done
      ? `Under way since ${ago(view.run.startedAt)}${view.run.auto ? ' (Keep members on this version)' : ''}.`
      : view.run ? `Last run ${ago(view.run.finishedAt)}.` : 'Sends each member its APK, then asks it to install. One member at a time.');
  const goSide = el('div', 'pf-leader-actions');
  goSide.appendChild(button('Check', 'btn-ghost', (e) => busy(e.currentTarget, async () => {
    const r = await api('api/updates/check', { method: 'POST' });
    const errors = Object.entries(r.data?.errors || {});
    if (errors.length) toast(errors.map(([n, m]) => `${n}: ${m}`).join(' · '), 'error', 'Check');
    await deps.reload();
  })));
  const all = button('Update the fleet', 'btn-primary', async (e) => {
    const btn = e.currentTarget;
    const n = view.members.filter((m) => !m.blocker).length;
    if (!await confirmBox('Update the fleet?',
      `${n} member${n === 1 ? '' : 's'} will be sent an APK and asked to install it. A wall panel that cannot install silently asks for a tap on its screen; an agent that cannot is skipped.`,
      'Update')) return;
    busy(btn, async () => {
      const r = await api('api/updates/install', { method: 'POST', body: {} });
      if (!r.ok) toast(r.data?.error || 'That did not work.', 'error', 'Updates');
      await deps.reload();
    });
  });
  all.disabled = view.running || !view.apks.length;
  goSide.appendChild(all);
  go.appendChild(goSide);
  go.classList.add('pf-wide');
  fleet.appendChild(go);

  const list = card('Members', root);
  if (!view.members.length) list.appendChild(infoRow('No members yet', 'Invite panels on the Fleet page.'));
  for (const r of view.members) list.appendChild(memberRow(r));

  root.appendChild(el('p', 'group-note',
    "How each member installs is its own: silently as a device owner or, on Android 12 and newer, once Kiosk Satellite is its own installer; " +
    "through the update helper started over adb, or through Shizuku when its updates are on; otherwise Android asks on its screen. " +
    "An agent (a projector, a media box) is only ever updated when it installs silently, since Android's question would light up its screen: " +
    "start the update helper (adb shell \"content read --uri content://me.jxl.kiosk_satellite.update-helper/start | sh\") or turn on Shizuku updates on it, then press Check. " +
    (view.passwordSet ? '' : 'Set panel_password: the ABIs and installers are read through each panel\'s remote admin.')));
}

export function initUpdates(d) { deps = d; }
