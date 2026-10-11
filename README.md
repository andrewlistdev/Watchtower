# aw-sdp-pd-sync (Ticket relay)

Keeps Arctic Wolf tickets and ServiceDesk Plus Cloud requests in step, assigns them to
whoever is on shift in PagerDuty, and gives you an admin page to manage it.

1. **New Arctic Wolf ticket → SDP request.** Each new AW ticket becomes an SDP request
   (`[AW-12345] <title>`), assigned to the person on shift and acknowledged: status set
   to "In Progress" plus a note that marks first response.
2. **Shift handoff.** Whoever is on the PagerDuty schedule gets the ticket, unless their
   shift ends within 30 minutes; then it goes to the person coming on next.
3. **SDP Resolved/Closed → AW closed.** The AW ticket is closed with the SDP resolution as
   the closing comment.
4. **AW closed first → SDP note.** If Arctic Wolf closes a ticket on their side, the SDP
   request gets a note.

Diagrams of each flow are in [docs/flows.md](docs/flows.md).

## Run it

```bash
docker compose up -d --build
docker compose logs aw-sdp-pd-sync
```

The log shows a **setup code**. Open <http://localhost:8080>, enter the code, and create
your admin account. Then:

1. **Settings:** enter the Arctic Wolf, ServiceDesk Plus and PagerDuty credentials. Use
   **Save and test connection** in each section.
2. **People:** check the list of who can be assigned (pre-filled from
   `config/identity_map.csv` on first start).
3. **Dashboard:** confirm the shift strip and the "What going live would do now" preview.
4. **Settings → Sync behaviour:** turn off **Dry run** to go live.

The service starts in dry run and waits quietly until the required settings are saved,
so there's no restart loop. Changes saved in the admin page apply on the next check;
no restart needed.

## Where secrets live

- Credentials are encrypted (Fernet) before they're written to the database in the
  `sync-data` volume. The key is generated once into `/data/secret.key` (mode 600), or
  supplied through `APP_ENCRYPTION_KEY`.
- After saving, the page shows only the last four characters, who saved it and when.
  Leaving a credential field blank keeps the saved value.
- Every settings change is listed under **Recent changes**, without values.
- Admin passwords are hashed (scrypt). Five failed sign-ins from one address lock it out
  for five minutes.

Anyone who can read the whole `sync-data` volume (database plus key file) can decrypt the
credentials, so treat that volume like a password vault. To keep the key out of the
volume, set `APP_ENCRYPTION_KEY` from your secrets manager (see `.env.example`).

**Network exposure.** Compose binds the page to `127.0.0.1:8080`, so only the machine
running Docker can reach it. To use it from elsewhere, put it behind an HTTPS reverse
proxy, then change the port binding and set `COOKIE_SECURE=true`. Don't publish it over
plain HTTP.

## Getting the credentials

**Arctic Wolf:** the Bearer token for the Ticket API and your organization UUID. The API
spec doesn't say how tokens are issued or how long they last; confirm with Arctic Wolf.

**ServiceDesk Plus Cloud (Zoho OAuth):**
1. In the Zoho API Console for your data center (https://api-console.zoho.com for US),
   create a **Self Client** and copy the Client ID and Client Secret.
2. Generate a code with scope `SDPOnDemand.requests.ALL`.
3. Exchange it for a refresh token straight away (the code expires in minutes):
   ```bash
   curl -X POST "https://accounts.zoho.com/oauth/v2/token" \
     -d grant_type=authorization_code -d client_id=CLIENT_ID \
     -d client_secret=CLIENT_SECRET -d code=GENERATED_CODE
   ```
4. Paste `refresh_token` from the response into Settings.

The SDP URL includes your portal, e.g. `https://sdpondemand.manageengine.com/app/itdesk`.
The status names in Settings must exist in your SDP instance.

**PagerDuty:** a read-only REST API key and the schedule ID (the end of the schedule's URL).

## Commands

| Command | What it does |
|---|---|
| `docker compose logs -f aw-sdp-pd-sync` | Watch activity (and find the setup code) |
| `docker compose run --rm aw-sdp-pd-sync check` | Test all three connections |
| `docker compose run --rm aw-sdp-pd-sync whois` | Who would get a ticket right now |
| `docker compose run --rm aw-sdp-pd-sync status` | Tracked tickets and errors |
| `docker compose run --rm aw-sdp-pd-sync resolve-stuck AW_ID SDP_ID\|none` | Fix a ticket stuck in "Check SDP" |
| `docker compose run --rm aw-sdp-pd-sync reset-admins` | Locked out: removes admin accounts; open the page and use the new setup code from the log |
| `docker compose up -d --build` | Deploy code changes |

Never run `docker compose down -v`: it deletes the volume holding your settings and the
record of which tickets were already created.

**Stuck creates.** If an SDP create times out, the outcome is unknown. Rather than risk
a duplicate, the ticket shows "Check SDP: outcome unknown" on the dashboard. Search SDP
for `[AW-<id>]`; if the request exists, run `resolve-stuck <aw_id> <sdp_id>`, otherwise
`resolve-stuck <aw_id> none` and it will be created on the next check.

## Limits to know about

- **Arctic Wolf's API can't assign, acknowledge or reopen.** Assignment and
  acknowledgement happen in SDP only. Once an AW ticket is closed, reopening the SDP
  request won't reopen it. If that matters, set "Statuses that close the AW ticket" to
  `Closed` only.
- **Comments aren't synced.** The closing comment is the only thing sent to Arctic Wolf.
- **Polling cost.** Each check reads every open mapped request from SDP once. Fine for
  tens of open tickets; raise "Check every" if you hit SDP API limits.
- **It only runs while Docker runs.** On a laptop, checks stop while it sleeps.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
```
