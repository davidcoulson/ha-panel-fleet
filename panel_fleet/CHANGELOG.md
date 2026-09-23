# Changelog

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
