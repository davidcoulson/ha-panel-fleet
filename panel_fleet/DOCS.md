# Panel Fleet

Panel Fleet finds the Kiosk Satellite wall panels on your network, lists them in one place, and leads them as a Kiosk Satellite fleet: it keeps one set of settings for the fleet and pushes each panel what its profile allows, the way a panel leading the fleet would. No wall panel has to lead.

It appears in the sidebar as **Kiosk Satellite**, and looks like a panel's own remote admin. While it is open, Home Assistant's own sidebar is hidden so the fleet fills the window; **Exit to Home Assistant** (the last item under Fleet in the menu) brings it back and returns to your default dashboard. Leaving the page any other way brings the sidebar back too. Nothing is changed in Home Assistant's own settings.

## Panels

| Column | Where it comes from |
| --- | --- |
| **Status** | Each panel's health endpoint, polled every scan interval. A panel reads offline after three missed polls in a row, and stays listed with when it was last seen. |
| **Panel** | Name, the panel's `.local` address, and tags: **Agent** for a panel in agent mode, and its place in the fleet (**Fleet**, **Invited**, **Declined**, **Left**). |
| **Platform** | Model, Android version and the system WebView. A WebView is marked only when another panel on the same Android version or older runs a newer one — Chrome and the WebView stop shipping for old Android (8.1 ends at WebView 138), and a panel at the end of its road is not behind. |
| **Display** | Size, orientation, and by how much the display is turned when it is not upright. An agent reads "—". |
| **Network** | Ethernet, or Wi-Fi with its band, channel, signal and link speed, and the address the panel answers on. |
| **Version** | The installed app version, compared with the latest [Kiosk Satellite](https://github.com/jxlarrea/kiosk-satellite/releases) release. A fork build such as `2026.9.74-djc-…` is compared by the release it is built on. |
| **Dashboard** | The panel's **Current page** sensor in Home Assistant, matched to the panel by its IPv4 address sensor. An agent reads "—". |
| **Open** (the icon after the name) | The panel's own admin page. |
| **Details** (the chevron at the end of a row) | Everything the panel reports: display and dpi, Android version, API level and build, WebView package, memory, storage, CPU, uptimes, battery, and its fleet state. |

A search box narrows the list. **Filters** has a section per question — Status, Fleet, Platform, Android, Network and Needs attention — each listing the values the fleet actually has, with counts. Ticking several values inside a section widens the list; ticking across sections narrows it. Filters are remembered in the browser.

Panels are found over mDNS (`_kiosk-satellite._tcp`, announced while a panel's remote admin and **Find other kiosks** are on). Every panel found is remembered, so one that is switched off stays on the list as offline. **Forget** removes an offline panel until it announces itself again. **Scan now** polls every panel straight away. Multicast does not cross VLANs without a reflector.

## Leading the fleet

Panel Fleet speaks Kiosk Satellite's own fleet protocol, as a leader. The panels need nothing new: a panel follows Panel Fleet exactly as it would follow another panel.

### First run

1. In the add-on's **Configuration**, set **panel_password** to the remote admin password of your panels, save, and restart the add-on.
2. Open **Kiosk Satellite** in the sidebar, go to **Fleet**, pick a panel under **Import from panel** (a wall panel, not an agent) and press **Import**. Panel Fleet logs in to that panel's admin, reads its settings definitions and every value, credentials included, and keeps them as the fleet's settings. The version that panel runs becomes the fleet's version.
3. Check the settings pages under **Fleet settings** and the **Default** profile under **Profiles**.
4. On **Fleet**, press **Invite** beside a panel. The invitation appears on that panel's own screen; someone has to tap **Accept** there — Panel Fleet cannot accept it for the panel. The row reads **Invited – confirm on the panel** until then.
5. Once accepted, Panel Fleet collects the panel's fleet token and pushes its settings at once. The row reads **In sync**.

A panel that leads a fleet of its own, or follows another leader, refuses the invitation; its reason is shown as the panel gives it (for example "This kiosk leads a fleet of its own"). Turn off **Lead this fleet** on it, or leave that fleet on it, first. To move a fleet a panel leads today, turn off **Lead this fleet** on that panel: it tells its followers to leave, and each can then be invited here.

### How the sync runs

- **When:** every 30 seconds while the page is open, every 5 minutes otherwise, and a couple of seconds after any change to the settings, a profile or the members. **Sync now** pushes at once, whether or not anything changed.
- **What:** the full set a panel's profile allows, every time. The panel only applies what differs. Each panel reports the revision (an md5 of the settings) it last applied, so only a panel whose settings changed is pushed, and a setting changed on the panel itself is put back at the next tick.
- **Versions:** settings are pushed only to a panel on the version the fleet settings came from (build numbers ignored). A panel on another version reads **Needs update to …**, or, when the panels have moved ahead, **Runs …: refresh the definitions**. Press **Refresh definitions** then: it reads the definitions from the panel on the newest version, keeps the fleet's values, adds new settings with that panel's values and drops the ones that are gone.
- **Membership:** Panel Fleet sends every member the member directory, with itself listed as an agent (so no panel offers it as an intercom peer). A panel that leaves the fleet on its own screen reads **Left the fleet**; **Remove** tells a member to forget Panel Fleet, and it keeps the settings it has.
- **Never synced:** anything Kiosk Satellite marks per device (its name, remote admin, fleet state, hardware picks…), plugin screensavers, gestures bound to plugin actions and plugin entity exclusions. These rules are Kiosk Satellite's own, ported.
- **Not yet:** custom wake word models and fleet updates (installing a release or an uploaded APK on the members) are not pushed by Panel Fleet. Update the panels from their own admin for now.

### Profiles

A profile decides what a member gets, as on a panel's own Fleet Management page:

| Part | What it does |
| --- | --- |
| Categories | Which settings pages travel. |
| Credentials | Home Assistant token (off by default: it names a user), Music Assistant token, Immich API key and intercom key, each on its own switch. |
| Dashboard | Whether the start page (`browser.start_url`) travels. Off by default. |
| Excluded settings | Settings taken out whatever their category says. By default the ones that belong to one screen or room: zoom and scales, brightness, volumes, orientation, local files, camera tuning, intercom answer mode, the voice mute. |

**Default** is what a member gets unless it is given another; it can be edited. **Updates only** syncs nothing and cannot be changed. Add your own under **Profiles**, and pick a member's profile on **Fleet**. The settings pages mark each row the Default profile leaves at home.

### Fleet settings

One page per category, in the order a panel lists them, drawn from the definitions: switches, dropdowns, sliders and fields as on the panel, grouped into the same sections and second-level pages, with hidden settings and settings whose switch is off left out. A change is saved at once and reaches the members a couple of seconds later. Credentials show as set or not set, never their value; typing a new one replaces it. Settings a panel edits with a picker of its own (album lists, gesture mappings, schedules) are plain text fields here, holding the JSON the panel stores. The search box in the rail finds any fleet setting.

## What it holds, and where

Panel Fleet holds secrets. It keeps them in its `/data` folder, which **Home Assistant includes in its backups**:

| File | Contents |
| --- | --- |
| `options.json` (the add-on configuration) | **panel_password**, your panels' remote admin password. |
| `secrets.json` (readable by the add-on only) | Each member's **fleet token**, and the nonce of an invitation still waiting. A fleet token opens only a panel's fleet endpoints and its update commands, and stops working when the panel leaves the fleet. |
| `fleet_settings.json` | The fleet's settings, **credentials included**: the Home Assistant token, Music Assistant token, Immich API key, intercom key, kiosk PIN and any other secret setting the source panel held. |
| `profiles.json`, `members.json`, `leader.json`, `devices.json` | Profiles, the members' public facts, the leader's id, and what discovery found. |

No page ever receives a token, the password or a secret setting's value. Treat a Home Assistant backup containing this add-on as holding your panels' credentials. The admin password is used for nothing but reading the settings from a panel when you press Import or Refresh; the session it opens stays in memory.

## Options

| Option | Default | What it does |
| --- | --- | --- |
| `scan_interval` | 60 | Seconds between polls of every panel. |
| `panel_password` | — | Your panels' remote admin password, to read the settings definitions and values from a panel. |
| `fleet_port` | 2330 | The port on this host a panel calls back to check an invitation came from this leader. Only `GET /api/fleet/identity` is served there; everything else is a 404. The panels must be able to reach it. |

## What it needs

- The host network, for mDNS and for the panels to call it back on `fleet_port`.
- Home Assistant's API, to read each panel's Current page sensor.
- Kiosk Satellite panels with the remote admin and **Find other kiosks** on, on a build with Fleet Management.
- A Home Assistant administrator: the page is not in other users' sidebars.
