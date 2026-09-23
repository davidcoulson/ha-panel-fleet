# Changelog

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
