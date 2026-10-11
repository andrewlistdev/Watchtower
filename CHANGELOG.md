# Changelog

Watchtower uses [semantic versioning](https://semver.org): bug fixes bump the last
number, new features the middle one, and changes that need you to do something when
upgrading the first. The version lives in `watchtower/__init__.py`; the image tag in
`docker-compose.yml` must match it.

## 1.0.0 (2026-10-11)

The project is now **Watchtower**.

- Renamed the app, Docker service (`watchtower`), image (`watchtower:1.0.0`), volume
  (`watchtower-data`) and Python package. Upgrading from 0.2.0 needs the one-time
  settings copy in the README ("Upgrading from aw-sdp-pd-sync").
- The version shows in the admin page footer, `/healthz`, the startup log and
  `--version`. API calls identify themselves as `Watchtower/1.0.0`.
- New Watchtower mark in the masthead and browser tab.
- SDP notes now say Watchtower made the assignment.
- You'll need to sign in again once: the session cookie was renamed.

## 0.2.0 (2026-10-10)

- Admin page: first-run setup code, sign-in, Settings with encrypted credentials and
  connection tests, People page, dashboard with the shift strip and dry-run preview.
- Settings are read on every check, so changes apply without a restart. The service
  waits for missing settings instead of restarting in a loop.

## 0.1.1 (2026-10-10)

- Fixed the Docker build: the container user can't be named `sync` on Debian.

## 0.1.0 (2026-10-10)

- First version: Arctic Wolf tickets become SDP requests assigned to the PagerDuty
  on-shift person with a 30-minute handoff; resolving in SDP closes the Arctic Wolf
  ticket; dry-run mode.
