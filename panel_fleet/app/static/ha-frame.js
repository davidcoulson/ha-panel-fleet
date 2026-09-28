// Panel Fleet inside Home Assistant. While the portal is on screen, Home
// Assistant's own sidebar (and, on a narrow screen, the ingress view's title
// bar with its menu button) is hidden by a temporary style, so the fleet
// fills the window like a panel's own admin. Exit to Home Assistant, leaving
// the page, or the portal's frame being hidden or removed takes the style
// away again. Nothing Home Assistant keeps is changed: no dockedSidebar
// preference, no event it acts on, only <style> elements this file owns.
//
// The ingress page is same-origin with Home Assistant, but it sits one or
// two frames down (the Supervisor panel can embed its own frame), so the
// frames are walked up to the window that holds <home-assistant>. Every
// step is guarded: a structure that is not what is expected means nothing
// is hidden, never an error.
//
// What is reached for (Home Assistant frontend, 2026.9):
//   home-assistant > #shadow-root > home-assistant-main > #shadow-root
//     > ha-drawer (an mwc drawer: aside.mdc-drawer, .mdc-drawer-app-content,
//       sized by --mdc-drawer-width) > ha-sidebar
//   hassio-ingress-view > #shadow-root > .header (narrow only) + iframe

const STYLE_ID = 'panel-fleet-hide-sidebar';
const MARK = 'data-panel-fleet-hidden';

const MAIN_CSS = `
  :host { --mdc-drawer-width: 0px !important; }
  ha-drawer { --mdc-drawer-width: 0px !important; }
  ha-sidebar { display: none !important; }`;
const DRAWER_CSS = `
  .mdc-drawer, .mdc-drawer-scrim { display: none !important; }
  .mdc-drawer-app-content { padding-left: 0 !important; padding-inline-start: 0 !important;
    margin-left: 0 !important; margin-inline-start: 0 !important; }`;
const INGRESS_CSS = `
  [${MARK}] { display: none !important; }
  iframe { height: 100% !important; }`;

// This window's ancestors, nearest first, each with the element that holds
// the frame below it. Stops at the first one another origin owns.
function ancestry() {
  const out = [];
  try {
    let w = window;
    while (w.parent && w.parent !== w) {
      const frame = w.frameElement;
      const up = w.parent;
      void up.document; // throws for another origin
      if (!frame) break;
      out.push({ win: up, frame });
      w = up;
    }
  } catch (e) { /* another origin above: stop here */ }
  return out;
}

// The window whose document holds <home-assistant>, or null outside it.
export function haWindow() {
  for (const { win } of ancestry()) {
    try {
      if (win.document.querySelector('home-assistant')) return win;
    } catch (e) { /* keep looking */ }
  }
  return null;
}

// Home Assistant's own dark mode, or null when it cannot be read.
export function haDarkMode() {
  try {
    const hass = haWindow()?.document.querySelector('home-assistant')?.hass;
    return typeof hass?.themes?.darkMode === 'boolean' ? hass.themes.darkMode : null;
  } catch (e) {
    return null;
  }
}

// The first element named `tag` in `root` or any shadow root under it,
// within a budget: Home Assistant's tree is a few thousand nodes.
function deepFind(root, tag, budget = { n: 20000 }) {
  const stack = [root];
  while (stack.length) {
    const node = stack.pop();
    for (const el of node.querySelectorAll('*')) {
      if (--budget.n < 0) return null;
      if (el.localName === tag) return el;
      if (el.shadowRoot) stack.push(el.shadowRoot);
    }
  }
  return null;
}

function addStyle(root, css) {
  let s = root.querySelector(`style#${STYLE_ID}`);
  if (!s) {
    s = (root.ownerDocument || root).createElement('style');
    s.id = STYLE_ID;
    s.textContent = css;
    root.appendChild(s);
  }
  return s;
}

// Whether every frame from here up to Home Assistant is attached and shown.
function shown(chain) {
  return chain.every(({ frame }) => frame.isConnected && frame.getClientRects().length > 0);
}

let applied = null; // { styles, marked } while the sidebar is hidden

function hide(ha, chain) {
  const styles = [], marked = [];
  const main = deepFind(ha.document, 'home-assistant-main');
  if (main?.shadowRoot) {
    styles.push(addStyle(main.shadowRoot, MAIN_CSS));
    const drawer = main.shadowRoot.querySelector('ha-drawer');
    if (drawer?.shadowRoot) styles.push(addStyle(drawer.shadowRoot, DRAWER_CSS));
  }
  // The ingress view that holds one of this page's frames: its narrow-screen
  // title bar goes, never an element that holds the portal itself.
  const frames = chain.map((c) => c.frame);
  for (const { win } of chain) {
    const view = deepFind(win.document, 'hassio-ingress-view');
    const root = view?.shadowRoot;
    if (!root || !frames.some((f) => root.contains(f))) continue;
    styles.push(addStyle(root, INGRESS_CSS));
    for (const bar of root.querySelectorAll('.header, .toolbar, ha-top-app-bar, ha-top-app-bar-fixed')) {
      if (frames.some((f) => bar.contains(f))) continue;
      bar.setAttribute(MARK, '');
      marked.push(bar);
    }
    break;
  }
  if (!styles.length) return null;
  armDeadMan(ha, styles, marked, frames);
  return { styles, marked };
}

function unhide(state) {
  if (!state) return;
  for (const s of state.styles) { try { s.remove(); } catch (e) { /* gone */ } }
  for (const el of state.marked) { try { el.removeAttribute(MARK); } catch (e) { /* gone */ } }
}

// A watcher that lives in Home Assistant's own window, so it outlives this
// page: should the portal's frame be removed or hidden without this page
// hearing about it, the styles still go within a second. Built with Home
// Assistant's Function so it runs in that realm; if that is refused, the
// page's own listeners below are the only guard.
function armDeadMan(ha, styles, marked, frames) {
  try {
    const watch = new ha.Function('styles', 'marked', 'frames', 'MARK', `
      const t = setInterval(() => {
        const live = styles.filter((s) => s.isConnected);
        if (!live.length) { clearInterval(t); return; }
        if (frames.every((f) => f.isConnected && f.getClientRects().length > 0)) return;
        live.forEach((s) => s.remove());
        marked.forEach((el) => el.removeAttribute(MARK));
        clearInterval(t);
      }, 1000);`);
    watch(styles, marked, frames, MARK);
  } catch (e) { /* no eval there: the page's listeners still restore */ }
}

// Hide while the portal is on screen, restore when it is not. Idempotent:
// run on load and every second after, so a Home Assistant re-render that
// dropped a style is covered, and a frame hidden then shown again is too.
function sync() {
  try {
    const ha = haWindow();
    if (!ha) return;
    const chain = ancestry();
    if (!shown(chain)) {
      unhide(applied);
      applied = null;
      return;
    }
    if (applied && applied.styles.every((s) => s.isConnected)) return;
    unhide(applied);
    applied = hide(ha, chain);
  } catch (e) {
    // Never leave Home Assistant half-styled on a surprise.
    unhide(applied);
    applied = null;
  }
}

export function restoreHaSidebar() {
  unhide(applied);
  applied = null;
}

// Exit to Home Assistant: its sidebar back first, then its default page.
export function exitToHa() {
  restoreHaSidebar();
  stopped = true;
  const ha = haWindow();
  try {
    (ha || window.top).location.assign('/');
  } catch (e) {
    window.top.location.href = '/';
  }
}

let stopped = false;
export function initHaFrame() {
  if (!haWindow()) return false;
  sync();
  setInterval(() => { if (!stopped) sync(); }, 1000);
  window.addEventListener('pagehide', restoreHaSidebar);
  window.addEventListener('beforeunload', restoreHaSidebar);
  try { window.addEventListener('unload', restoreHaSidebar); } catch (e) { /* unload may be blocked */ }
  return true;
}
