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
4. On **Fleet**, press **Invite** beside a panel. The invitation appears on that panel's own screen, where someone taps **Accept** — or tick **Accept remotely using the panel password** before inviting, and Panel Fleet accepts it for the panel through its remote admin (see below). The row reads **Invited – confirm on the panel** until it is accepted; **Accept for it** on that row does the same later.
5. Once accepted, Panel Fleet collects the panel's fleet token and pushes its settings at once. The row reads **In sync**.

### Accepting for a panel

Kiosk Satellite lets an invitation be accepted on the panel's screen or in its own remote admin. With **Accept remotely using the panel password** ticked, Panel Fleet does the second: it logs in to the panel's remote admin with **panel_password**, checks that the invitation waiting there is Panel Fleet's own (it never accepts another leader's), runs the panel's `fleetAccept` command, collects the fleet token and checks the panel now follows it. Nothing appears on the panel's screen. The box is ticked by default for an agent, where tapping Accept would mean waking a projector's screen, and unticked for a wall panel. It needs **panel_password**; the password and the admin session are never logged or shown.

### Add by IP

A panel that mDNS does not reach (another VLAN without a multicast reflector) can be added by its address, as on a panel leader: under **Add by IP** enter its IP address and remote admin port (2324 unless changed) and press **Find kiosk**. Panel Fleet asks that address who it is, over HTTP and then HTTPS, and refuses a kiosk that leads a fleet, follows another leader or is already a member. Pick a profile, choose whether to accept for it, and press **Send invitation**. The panel is listed on **Panels** from then on and reached at that address. It still has to reach this host on **fleet_port** to check the invitation. A kiosk found this way is treated as an agent until its admin says otherwise (an agent defaults to the **Updates only** profile).

A panel that leads a fleet of its own, or follows another leader, refuses the invitation; its reason is shown as the panel gives it (for example "This kiosk leads a fleet of its own"). Turn off **Lead this fleet** on it, or leave that fleet on it, first. To move a fleet a panel leads today, turn off **Lead this fleet** on that panel: it tells its followers to leave, and each can then be invited here.

### How the sync runs

- **When:** every 30 seconds while the page is open, every 5 minutes otherwise, and a couple of seconds after any change to the settings, a profile or the members. **Sync now** pushes at once, whether or not anything changed.
- **What:** the full set a panel's profile allows, every time. The panel only applies what differs. Each panel reports the revision (an md5 of the settings) it last applied, so only a panel whose settings changed is pushed, and a setting changed on the panel itself is put back at the next tick.
- **Versions:** settings are pushed only to a panel on the version the fleet settings came from (build numbers ignored). A panel on another version reads **Needs update to …**, or, when the panels have moved ahead, **Runs …: refresh the definitions**. Press **Refresh definitions** then: it reads the definitions from the panel on the newest version, keeps the fleet's values, adds new settings with that panel's values and drops the ones that are gone.
- **Membership:** Panel Fleet sends every member the member directory, with itself listed as an agent (so no panel offers it as an intercom peer). A panel that leaves the fleet on its own screen reads **Left the fleet**; **Remove** tells a member to forget Panel Fleet, and it keeps the settings it has.
- **Never synced:** anything Kiosk Satellite marks per device (its name, remote admin, fleet state, hardware picks…), plugin screensavers, gestures bound to plugin actions and plugin entity exclusions. These rules are Kiosk Satellite's own, ported.
- **Custom wake word models** travel to a member only once it is in step (see **Wake word models**).

### Updates

**Updates** installs a Kiosk Satellite APK on the members, as a panel leader's **Install on the fleet** does.

1. **Upload APK**: Panel Fleet reads the file itself — package, version name, build (versionCode) and the ABIs it carries native code for — and refuses anything that is not Kiosk Satellite. It keeps one APK per ABI: upload the arm64-v8a build for the wall panels and the armeabi-v7a build for 32-bit boxes (the projectors, the Echo Show), or one universal APK. A new upload replaces the APK for the same ABIs.
2. **Check** (also run when the page opens) reads each member's ABIs and installer through its remote admin with **panel_password**. Each member is shown the APK it gets: the first of Android's own ABIs (in its order of preference) that an APK carries, a single-ABI APK before a universal one — the rule Kiosk Satellite uses to pick a release download.
3. **Update the fleet** (or **Update** on one member) sends each member its APK, one at a time, then asks it to install. The upload is streamed to the member's `POST /api/update/upload` with its fleet token, and the install is its `installUploadedApk` command; the member checks the file again (Kiosk Satellite, not older than what it runs, room for two copies) and its refusal is shown as it gives it. Progress, then **Installing…**, **Waiting for Install to be tapped on its screen**, or **Updated**, shows per member.

A member already on the APK's version is skipped. Versions are compared by every number in the version name, so the fork's builds of one release (which share a build number) are told apart.

**Keep members on this version** sends a member its APK whenever it is found behind it — coming back online, or after a new APK is uploaded — once per APK.

**How a member installs** is its own: silently as device owner, or on Android 12 and newer once Kiosk Satellite is its own installer of record; through the update helper started over adb; through Shizuku when **Install updates through Shizuku** is on; otherwise Android shows its install confirmation on the screen. A wall panel in that last case is updated anyway and asks for the tap, as with a panel leader.

**An agent is only updated when it installs silently.** Android's confirmation would bring the installer up on the agent's screen — on a projector, in an empty room. So an agent's installer is read before anything is sent and again right before the install (the upload takes minutes), and an agent that would need the confirmation is skipped as **Needs adb/Shizuku**. Projectors on Android 9 and 11 have no silent path of their own: start the update helper once after each reboot,

```sh
adb -s <projector> shell "content read --uri content://me.jxl.kiosk_satellite.update-helper/start | sh"
```

or set up Shizuku and turn on **Install updates through Shizuku** on it, then press **Check**. An agent found by IP whose agent mode is not known yet is treated as an agent.

### Wake word models

Kiosk Satellite's leader passes its custom wake word models to every follower whose profile syncs **Voice Satellite**, and the followers mirror its set. **Wake word models** holds that set for Panel Fleet.

- **Add files**: pick every file of one or more models at once — `name.json` and `name.tflite` for microWakeWord, `name.json` and `name.onnx` for vsWakeWord, one `name.onnx` or `name.tflite` for openWakeWord. Panel Fleet sorts them by engine as a panel does and refuses incomplete or mismatched models with the reason. It cannot run a model: try a new one on one panel first, since a member does not check what its leader sends.
- **Mirror these models on the members** (off until switched on): every member on the fleet settings' version whose profile syncs Voice Satellite gets exactly this set over its fleet endpoints — missing or changed files are sent, files Panel Fleet does not hold are **removed**. Files are compared by SHA-256, so an unchanged set costs one small request per member, and a member that was away catches up at its next sync. It cannot be switched on with an empty set, which would delete every member's models.
- **Compare** shows what mirroring would send and remove on each member, or what any panel holds against the set, without changing anything.

A panel's model files cannot be read back through any Kiosk Satellite endpoint (they live in the app's private storage), so the set cannot be imported from a panel: upload the same files you added to the panels.

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
| `profiles.json`, `members.json`, `leader.json`, `devices.json` | Profiles, the members' public facts (including their ABIs and agent mode), the leader's id, and what discovery found. |
| `apks/` | The uploaded APKs, one per ABI. |
| `wake_models/`, `wake_models.json` | The custom wake word models, and whether they are mirrored. |

No page ever receives a token, the password or a secret setting's value, and none of them is logged. Treat a Home Assistant backup containing this add-on as holding your panels' credentials. The admin password is used to read the settings from a panel (Import, Refresh), to accept an invitation for a panel when asked to, to read a member's ABIs, agent mode and installer for an update, and to compare a non-member's wake word models; the sessions it opens stay in memory.

## Options

| Option | Default | What it does |
| --- | --- | --- |
| `scan_interval` | 60 | Seconds between polls of every panel. |
| `panel_password` | — | Your panels' remote admin password: to read the settings from a panel, accept invitations for panels, and read each member's ABI and installer before an update. |
| `fleet_port` | 2330 | The port on this host a panel calls back to check an invitation came from this leader. Only `GET /api/fleet/identity` is served there; everything else is a 404. The panels must be able to reach it. |

## What it needs

- The host network, for mDNS and for the panels to call it back on `fleet_port`.
- Home Assistant's API, to read each panel's Current page sensor.
- Kiosk Satellite panels with the remote admin and **Find other kiosks** on, on a build with Fleet Management.
- A Home Assistant administrator: the page is not in other users' sidebars.
