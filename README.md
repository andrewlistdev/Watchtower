# aw-sdp-pd-sync

Keeps Arctic Wolf tickets and ServiceDesk Plus Cloud requests in step, and assigns
them to whoever is on shift in PagerDuty.

1. **New Arctic Wolf ticket → SDP request.** Each new AW ticket becomes an SDP request
   (`[AW-12345] <title>`), assigned to the person on shift and acknowledged: status set
   to `SDP_ACK_STATUS` plus a note that marks first response.
2. **Shift handoff.** Whoever is on the PagerDuty schedule gets the ticket, unless their
   shift ends within 30 minutes; then it goes to the person coming on next.
3. **SDP Resolved/Closed → AW closed.** When the SDP request reaches one of
   `SDP_CLOSE_STATUSES`, the AW ticket is closed with the SDP resolution as the closing
   comment.
4. **AW closed first → SDP note.** If Arctic Wolf closes a ticket on their side, the SDP
   request gets a note so the technician knows.

Diagrams of each flow are in [docs/flows.md](docs/flows.md).

## Quick start

```bash
git clone <this repo> && cd aw-sdp-pd-sync
cp .env.example .env          # fill in credentials (see below); leave DRY_RUN=true
docker compose build

docker compose run --rm aw-sdp-pd-sync check    # tests all three API credentials
docker compose run --rm aw-sdp-pd-sync whois    # who would get a ticket right now, and why
docker compose up -d                            # dry run: logs what it would do
docker compose logs -f
```

When the dry-run log looks right, set `DRY_RUN=false` in `.env` and
`docker compose up -d` again.

**First live run:** with `AW_BACKFILL_OPEN=false` (the default), only AW tickets created
after the first live run are imported. Set it to `true` before the first live run to
also bring in every ticket that is open at that moment.

## Credentials

### Arctic Wolf
- `AW_BASE_URL`: your region's server (US001/US002/US003/EU001/AU001/CA001).
- `AW_API_TOKEN`: the Bearer token for the Ticket API.
- `AW_ORG_UUID`: your organization UUID.

The API spec doesn't say how tokens are issued or how long they last. Confirm with
Arctic Wolf; if tokens expire, the service will log 401s until `.env` is updated.

### ServiceDesk Plus Cloud (Zoho OAuth)
1. Go to the Zoho API Console for your data center (https://api-console.zoho.com
   for US) → **Self Client** → note the Client ID and Client Secret.
2. Generate a code with scope `SDPOnDemand.requests.ALL` (a few minutes' expiry).
3. Exchange it for a refresh token straight away:
   ```bash
   curl -X POST "https://accounts.zoho.com/oauth/v2/token" \
     -d grant_type=authorization_code -d client_id=CLIENT_ID \
     -d client_secret=CLIENT_SECRET -d code=GENERATED_CODE
   ```
4. Put `refresh_token` from the response in `ZOHO_REFRESH_TOKEN`. The service refreshes
   access tokens itself.

Use the accounts server and SDP domain for your data center (`.eu`, `.in`, `.com.au`,
etc.). `SDP_BASE_URL` includes your portal path, e.g.
`https://sdpondemand.manageengine.com/app/itdesk`.

Create the requests from a technician account that is allowed to assign to all
six people. `SDP_ACK_STATUS` and the close statuses must match status names that exist
in your SDP instance.

### PagerDuty
- `PD_API_TOKEN`: a **read-only** REST API key is enough.
- `PD_SCHEDULE_ID`: the ID at the end of the schedule's URL (`/schedules/PXXXXXX`).

The service reads the schedule's final layer, so overrides are respected.

## Identity map

`config/identity_map.csv` maps PagerDuty user IDs to people. The SDP technician is
found by email: `sdp_email` if filled in, otherwise `aw_email`. Set `status` to anything
other than `Active` to stop assigning to someone. Restart the container after editing.

If PagerDuty shows someone who isn't in the map (or is inactive), the ticket goes to
`SDP_FALLBACK_TECHNICIAN_EMAIL` if set, otherwise it's left unassigned with a note
explaining why. If SDP rejects the technician email, the request is still created,
unassigned, with a note.

## Commands

All read-only except `run`/`once` (and those only write when `DRY_RUN=false`).

| Command | What it does |
|---|---|
| `run` | Poll forever (the container default) |
| `once` | One sync cycle, then exit |
| `check` | Test credentials for Arctic Wolf, SDP and PagerDuty |
| `whois [--at 2026-10-12T21:45:00Z]` | Show upcoming shifts and who would get a ticket |
| `status` | List tracked tickets and any errors |
| `resolve-stuck AW_ID SDP_ID\|none` | Fix a ticket stuck in `creating` (see below) |

Run them with `docker compose run --rm aw-sdp-pd-sync <command>`.

**Stuck creates.** If an SDP create times out, the outcome is unknown. Rather than
risk a duplicate, the ticket stays in `creating` and a CRITICAL line is logged. Search
SDP for `[AW-<id>]`: if the request exists, run `resolve-stuck <aw_id> <sdp_id>`;
if not, run `resolve-stuck <aw_id> none` and it will be created next cycle.

## Limits to know about

- **Arctic Wolf's API can't assign, acknowledge or reopen.** Assignment and
  acknowledgement happen in SDP only. Once an AW ticket is closed, reopening the SDP
  request won't reopen it. If that's a problem, set `SDP_CLOSE_STATUSES=Closed` so
  only a final close triggers it.
- **Comments are not synced** between the systems. The closing comment is the only
  thing sent to Arctic Wolf, and it is visible to them.
- **Polling cost.** Each cycle makes one SDP read per open mapped ticket. Fine for
  tens of open tickets; raise `POLL_SECONDS` if you hit SDP API limits.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
```
