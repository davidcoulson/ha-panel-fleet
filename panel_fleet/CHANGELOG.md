# Changelog

## 0.4.0

- **Updates**, a new page in the Fleet group: upload Kiosk Satellite APKs and install them on the members, as a panel leader's **Install on the fleet** does. Panel Fleet reads each APK's version and ABIs from the file and keeps one per ABI (arm64-v8a for the wall panels, armeabi-v7a for the projectors and other 32-bit boxes, or a universal one); each member gets the one its own ABIs take, read from its remote admin. The APK is streamed to each member's upload endpoint with its fleet token, one member at a time, then installed there, with progress and the member's own answer per row. **Keep members on this version** sends a member its APK whenever it falls behind.
- **Agents are never woken by an update.** An agent's installer is checked before the upload and again before the install; one that would need Android's on-screen confirmation is skipped as **Needs adb/Shizuku**. Start the update helper over adb, or turn on Shizuku updates, on a projector to update it from here.
- **Add by IP** on the Fleet page: find a kiosk mDNS cannot see by its address and port, then invite it. It is listed on Panels from then on.
- **Accept remotely using the panel password**: Panel Fleet can accept an invitation for a panel through its remote admin (Kiosk Satellite's `fleetAccept`), after checking the invitation waiting there is its own. Nothing shows on the panel's screen. On by default for agents; **Accept for it** does the same for an invitation already sent.
- **Wake word models**, a new page: hold a set of custom wake word models (uploaded and checked like a panel checks them) and mirror it, by checksum, on every member whose profile syncs Voice Satellite. Off until switched on, never with an empty set, and **Compare** shows what it would send and remove first.
- An agent gets the **Updates only** profile by default when invited.
- The panel password, fleet tokens, admin sessions and invitation nonces are kept out of the add-on log.

## 0.3.3

- The sidebar entry uses the tablet-dashboard icon again.

## 0.3.2

- **The portal fills the window.** While the fleet page is on screen, Home Assistant's own sidebar is hidden (and, on a phone, the title bar above the page), so it reads like a panel's own admin. It is a temporary style only: Home Assistant's docked-sidebar preference is never touched, and the sidebar comes back on **Exit to Home Assistant**, when the page is left or reloaded, and whenever the page is not on screen. A watcher in Home Assistant's window puts it back even if the page cannot.
- **Exit to Home Assistant**, the last item of the Fleet group, returns to Home Assistant's default page with its sidebar. It only shows inside Home Assistant.
- **The menu is grouped like a panel's**: Fleet (Panels, Fleet, Profiles), then the settings under Home Assistant, Display, Media & Cameras, Kiosk and System, as a panel's remote admin groups them. Each heading folds its group, remembered in the browser.
- On a phone, settings search results show in the menu itself, in place of the list, as on a panel.

## 0.3.1

- Each panel is given the leader's address on its own network. Home Assistant sits on more than one network, and replies follow its default route, so a panel on the IoT network is told the IoT address and a panel elsewhere the main one. The fleet list used to carry one address for everyone, picked from whichever panel came first.

## 0.3.0

- **Panel Fleet leads the Kiosk Satellite fleet.** It takes the place of the panel that led: it invites panels (the invitation is accepted on the panel's own screen), keeps one set of fleet settings, and pushes each member what its profile allows over Kiosk Satellite's own fleet protocol — the same revision fingerprint, version gate, member directory and never-synced rules as a panel leader, ported from Kiosk Satellite 2026.9.87. Panels need nothing new.
- **Fleet settings, styled like a panel.** The page is rebuilt on the Kiosk Satellite remote admin's own stylesheet: the rail, cards, switches, sliders and second-level pages. One page per category a leader can push, drawn from the definitions of a panel you import from, with the rows the Default profile leaves at home marked. **Import from panel** reads the definitions and values (credentials included); **Refresh definitions** moves them to a newer version and keeps your values.
- **Profiles** as on a panel: Default (editable), Updates only, and your own, each with categories, credentials, the dashboard and excluded settings.
- **Fleet** lists every panel with its place in the fleet (Not in fleet, Invited – confirm on the panel, Member, Declined, Left) and its sync state (In sync, Syncing, Needs update to …, Offline, or the panel's own error), with Invite, Remove, a profile per member and Sync now.
- The sidebar entry is now **Kiosk Satellite** with `mdi:satellite-variant`, and the page's header reads Kiosk Satellite · Fleet, like a panel's admin. Administrators only.
- New options: **panel_password** (the panels' remote admin password, used only to read the settings definitions) and **fleet_port** (default 2330, where panels check an invitation came from this leader; only the leader's identity is served there).
- The add-on now holds secrets — the panels' admin password, each member's fleet token and the fleet's credentials — in `/data`, which Home Assistant backs up. No page ever receives them. See DOCS.
- ha-paneld is no longer supported: no discovery, polling or mention of it. Panels it found are dropped from the list.
- A panel with HTTPS on is polled over HTTPS.
- Not yet: custom wake word models and fleet updates are not pushed from Panel Fleet.

## 0.2.3

- A Kiosk Satellite running in agent mode is tagged **Agent** (from its mDNS record), and its Display and Dashboard columns read "—": an agent shows no dashboard, so its screen size is not a fact about one. Everything else — version, network, platform, uptime, the details drawer — is unchanged, because that is exactly what an agent is there to report.
- Needs Kiosk Satellite build `2026.9.81-djc-2026.09.25.08` or newer, which is what advertises `agent=1`.

## 0.2.2

- Nothing that is one string wraps any more: the `.local` name, the version and its fork build, and the Wi-Fi channel/signal/speed each stay on their own line. A long dashboard path ends in an ellipsis with the whole path in its tooltip.
- The page is wider, so the table no longer scrolls sideways and hides the details chevron. Screen dpi moved from the Display column into the details, where it does not cost a column its width.

## 0.2.0

- The filters are one dropdown, laid out like the ESPHome dashboard's: a search box on its own, then **Filters** with a section per question — Status, Software, Platform, Android, Network and Needs attention — each listing the values the fleet actually has, with counts. Tick several inside a section to widen, across sections to narrow.
- A WebView is only marked as behind when another panel **on the same Android version or older** runs a newer one. Android 8.1 stops at WebView 138, so those panels are no longer flagged for standing still where the road ends.
- A panel's name keeps its open-in-new icon on the same line.

## 0.1.9

- **Platform** is a column of its own: model, Android version and the system WebView. The panel column keeps the name, the `.local` address under it, and which software it runs.
- **Showing** is now **Dashboard**.
- Filters above the table: a search over name, model, address, version and dashboard, plus status, software, version and "WebView behind the fleet". They are remembered per browser, and the summary says how many of the fleet are shown.

## 0.1.8

- The add-on's own version sits beside the title, so a stale page can be told from an update that did not take.
- The page itself is no longer cached. The sidebar holds it in a long-lived frame, where a cached copy could outlive several updates.

## 0.1.7

- Display and Network are columns of their own. The panel column keeps the name, model, Android version and WebView; the address moved under Network, beside how the panel reaches it.

## 0.1.6

- A Wi-Fi panel says which band and channel it is on: "Wi-Fi 5 GHz · ch 60 · −45 dBm · 432 Mbps". Needs Kiosk Satellite build `2026.9.77-djc-2026.09.22.09` or newer.

## 0.1.5

- Every panel row now carries its display (size, orientation and, when it is turned, by how much), its system WebView and how it is on the network — Ethernet, or Wi-Fi with signal and link speed.
- A WebView older than the best-updated panel in the fleet is marked, so the odd panel rendering a dashboard differently is one glance away.
- The chevron at the end of a row opens everything a panel reports: display and dpi, Android version, API level and build, WebView package, network, memory, storage, CPU, how long the device has been up beside the app, and battery where there is one.
- Kiosk Satellite panels need build 2026.9.77-djc-2026.09.22.07 or newer for the WebView, network and device-uptime rows; ha-paneld reports its own from its info page.

## 0.1.4

- Sidebar icon is now `mdi:monitor-dashboard`, so it is not mistaken for Panel Assistant's `mdi:tablet-dashboard`.

## 0.1.3

- An icon and logo for the add-on store.

## 0.1.2

- An offline panel says how long ago it was last seen: "last seen 3h ago", or "2d ago" past a day.

## 0.1.1

- The panels now show the page they are on: the add-on reaches Home Assistant (its container start no longer drops the Supervisor token).
- A newly found panel is checked at once instead of at the next scan.
- The admin link is an open-in-new icon after the panel name, as in the ESPHome dashboard.

## 0.1.0

- First release: mDNS discovery of Kiosk Satellite and ha-paneld panels, online status, version against the latest release, the page each panel is showing, and a link to each panel's admin page.
