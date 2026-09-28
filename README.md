# Panel Fleet

A Home Assistant add-on that leads your Kiosk Satellite wall panels as one fleet. It shows every panel on the network at a glance — whether it is online, whether its app is current, what it is showing, a link to its own admin page — and it takes the fleet leader's place: one set of settings for the fleet, edited in pages styled like a panel's own remote admin, profiles for what each panel gets, and a push to every member that has accepted its invitation. No wall panel has to lead.

It appears in the sidebar as **Kiosk Satellite**.

## Install

1. In Home Assistant, go to **Settings > Add-ons > Add-on Store**, open the menu and choose **Repositories**.
2. Add `https://github.com/davidcoulson/ha-panel-fleet`.
3. Install **Panel Fleet**, set **panel_password** in its Configuration, start it and turn on **Show in sidebar**.

See [DOCS.md](panel_fleet/DOCS.md) for the first run, how the sync works, and what the add-on keeps (it holds your panels' admin password, fleet tokens and credentials, and Home Assistant backs them up).

## Development

    python3 -m venv .venv
    .venv/bin/pip install -r panel_fleet/requirements.txt -r requirements-dev.txt
    .venv/bin/python -m pytest

Run it by hand with `DATA_DIR=/some/dir PORT=8099 python3 panel_fleet/app/main.py`; without `SUPERVISOR_TOKEN` the page is open to any local client.
