# Panel Fleet

Panel Fleet finds the wall panels on your network and lists them in one place.

## What it shows

| Column | Where it comes from |
| --- | --- |
| **Status** | Each panel's health endpoint, polled every scan interval. A panel reads offline after three missed polls in a row, and stays listed with when it was last seen. |
| **Panel** | Name, model and Android version from the panel. |
| **Version** | The installed app version, compared with the latest GitHub release of [Kiosk Satellite](https://github.com/jxlarrea/kiosk-satellite/releases) or [ha-paneld](https://github.com/maxlyth/ha-paneld/releases). A fork build such as `2026.9.74-djc-…` is compared by the release it is built on. |
| **Showing** | For Kiosk Satellite, its **Current page** sensor in Home Assistant, matched to the panel by its IPv4 address sensor. For ha-paneld, the page it reports, or its home dashboard. |
| **Open** (the icon after the name) | The panel's own admin page: port 2324 for Kiosk Satellite, 8888 for ha-paneld. |

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
