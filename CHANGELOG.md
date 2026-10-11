# Changelog

Watchtower uses [semantic versioning](https://semver.org): bug fixes bump the last
number, new features the middle one, and changes that need you to do something when
upgrading the first. The version lives in `watchtower/__init__.py`; the image tag in
`docker-compose.yml` must match it.

## 1.2.0 (2026-10-11)

Credentials can be set up entirely from the Settings page.

- **Arctic Wolf:** "Save and look up organization" asks Arctic Wolf's Organizations API
  which organizations your Personal API Key can see; "Use this organization" fills in
  the region and organization ID. Regions beyond the built-in list are accepted.
- **ServiceDesk Plus:** paste a Zoho Self Client grant code and Watchtower exchanges it
  for a refresh token, so there's no terminal step and no secrets in shell history.
- **Save and test connection** now tests each service on its own, so you can check
  Arctic Wolf before PagerDuty is filled in.
- Settings help text says where to find each credential; README has the full steps.

## 1.1.0 (2026-10-11)

Applies the Watchtower brand guide (`docs/BRAND_GUIDE.md`).

- **Look:** dark-first theme with the guide's navy and teal palette, Space Grotesk,
  Inter and IBM Plex Mono (bundled, no external requests), all from central tokens in
  `static/tokens.css`. Light and "match my system" themes are on the Account page.
- **Logo:** new fire-watch tower mark and WATCHTOWER wordmark, with a reusable
  `WatchtowerLogo` component and SVG files for dark, light, monochrome, mark-only,
  small-icon and favicon use.
- **Honest ticket states:** Routed, Unassigned, Needs check, Routing failed, Resolving,
  Close failed, Resolved and Closed in Arctic Wolf, each with a text label. Nothing is
  shown as "Acknowledged", because Watchtower can't see a responder accept a ticket.
  Tickets whose state couldn't be refreshed are marked "Out of date".
- **Current owner:** read back from ServiceDesk Plus on every check, so reassignments
  made in SDP show up.
- **Routing history:** every routing decision, ownership and status change, resolution
  and failure is recorded. New ticket page shows it with the reason the owner was chosen;
  new Activity page lists it alongside settings changes.
- **Copy:** pages, routing reasons and SDP notes use the guide's terminology (routed,
  responder, on call, current owner). The SDP note now says Watchtower routed the ticket
  and that the responder hasn't acknowledged it yet. Behaviour is unchanged: the routed
  status is still set and first response is still marked.
- People page is now **Responders** (`/people` redirects). The setting "Status when
  acknowledged" is now "Status after routing"; your saved value carries over.
- Existing databases are upgraded automatically on start.

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
