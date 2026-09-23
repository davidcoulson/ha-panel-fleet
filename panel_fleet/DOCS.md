# Panel Fleet

Panel Fleet finds the wall panels on your network and lists them in one place.

## What it shows

| Column | Where it comes from |
| --- | --- |
| **Status** | Each panel's health endpoint, polled every scan interval. A panel reads offline after three missed polls in a row, and stays listed with when it was last seen. |
| **Panel** | Name, model, Android version and the system WebView. A WebView older than the best-updated panel in the fleet is marked. |
| **Display** | Size, orientation, dpi, and by how much the display is turned when it is not upright. |
| **Network** | Ethernet, or Wi-Fi with its band, channel, signal and link speed, and the address the panel answers on. |
| **Details** (the chevron at the end of a row) | Everything the panel reports: display and dpi, Android version, API level and build, WebView package, network, memory, storage, CPU, how long the device has been up beside how long the app has, and battery where there is one. |
| **Version** | The installed app version, compared with the latest GitHub release of [Kiosk Satellite](https://github.com/jxlarrea/kiosk-satellite/releases) or [ha-paneld](https://github.com/maxlyth/ha-paneld/releases). A fork build such as `2026.9.74-djc-…` is compared by the release it is built on. |
| **Showing** | For Kiosk Satellite, its **Current page** sensor in Home Assistant, matched to the panel by its IPv4 address sensor. For ha-paneld, the page it reports, or its home dashboard. |
| **Open** (the icon after the name) | The panel's own admin page: port 2324 for Kiosk Satellite, 8888 for ha-paneld. |

Kiosk Satellite serves all of this from `/api/health`, which needs no token. The
WebView, network and device-uptime rows came with build
`2026.9.77-djc-2026.09.22.07`; on an older build those rows are simply absent,
and the display falls back to the size the panel reports. ha-paneld reports its
own from its info page.

## Discovery

Panels are found over mDNS, the way the ESPHome dashboard finds devices:

- Kiosk Satellite announces `_kiosk-satellite._tcp` while its remote admin is on.
- ha-paneld announces `_ha-paneld._tcp`.

Every panel found is remembered, so one that is switched off stays on the list as offline. **Forget** removes an offline panel until it announces itself again. **Scan now** polls every panel straight away.

Multicast does not cross VLANs without a reflector. A panel on another VLAN appears once an mDNS reflector (or the router's mDNS repeater) passes its announcements to Home Assistant's network.

## Options

| Option | Default | What it does |
| --- | --- | --- |
| `scan_interval` | 60 | Seconds between polls of every panel. |

## What it needs

- The host network, for mDNS.
- Home Assistant's API, to read each Kiosk Satellite panel's Current page sensor. No panel passwords are used: everything it reads is either public on the panel or already in Home Assistant.
