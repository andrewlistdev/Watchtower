# Watchtower

Watchtower watches Arctic Wolf for new tickets, opens each one in ServiceDesk Plus Cloud,
and hands it to whoever is on shift in PagerDuty. When the request is resolved in SDP,
Watchtower closes the Arctic Wolf ticket.

Current version: **1.0.0** ([changelog](CHANGELOG.md))

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
docker compose logs watchtower
```

The log shows a **setup code**. Open <http://localhost:8080>, enter the code, and create
your admin account. Then:

1. **Settings:** enter the Arctic Wolf, ServiceDesk Plus and PagerDuty credentials. Use
   **Save and test connection** in each section.
2. **People:** check the list of who can be assigned (pre-filled from
   `config/identity_map.csv` on first start).
3. **Dashboard:** confirm the shift strip and the "What going live would do now" preview.
4. **Settings → Sync behaviour:** turn off **Dry run** to go live.

Watchtower starts in dry run and waits quietly until the required settings are saved, so
there's no restart loop. Changes saved in the admin page apply on the next check; no
restart needed.

## Upgrading from aw-sdp-pd-sync (0.2.0)

The rename gives Watchtower a new Docker volume, so copy your settings, credentials and
ticket history across once. From the folder you unzipped Watchtower into:

```bash
docker compose -f ../aw-sdp-pd-sync/docker-compose.yml down
docker compose up --no-start --build
docker run --rm --user 0 --entrypoint sh \
  -v aw-sdp-pd-sync_sync-data:/from:ro -v watchtower_watchtower-data:/to \
  watchtower:1.0.0 -c 'test -f /from/state.db || { echo "Old volume not found. Check its name with: docker volume ls"; exit 1; }; cp -a /from/. /to/ && chown -R 10001 /to && echo Copied.'
docker compose up -d
```

You'll sign in again once (the session cookie was renamed). When everything looks right,
remove the old pieces:

```bash
docker volume rm aw-sdp-pd-sync_sync-data
docker image rm aw-sdp-pd-sync:latest
```

## Where secrets live

- Credentials are encrypted (Fernet) before they're written to the database in the
  `watchtower-data` volume. The key is generated once into `/data/secret.key` (mode 600),
  or supplied through `APP_ENCRYPTION_KEY`.
- After saving, the page shows only the last four characters, who saved it and when.
  Leaving a credential field blank keeps the saved value.
- Every settings change is listed under **Recent changes**, without values.
- Admin passwords are hashed (scrypt). Five failed sign-ins from one address lock it out
  for five minutes.

Anyone who can read the whole `watchtower-data` volume (database plus key file) can
decrypt the credentials, so treat that volume like a password vault. To keep the key out
of the volume, set `APP_ENCRYPTION_KEY` from your secrets manager (see `.env.example`).

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
| `docker compose logs -f watchtower` | Watch activity (and find the setup code) |
| `docker compose run --rm watchtower check` | Test all three connections |
| `docker compose run --rm watchtower whois` | Who would get a ticket right now |
| `docker compose run --rm watchtower status` | Tracked tickets and errors |
| `docker compose run --rm watchtower resolve-stuck AW_ID SDP_ID\|none` | Fix a ticket stuck in "Check SDP" |
| `docker compose run --rm watchtower reset-admins` | Locked out: removes admin accounts; open the page and use the new setup code from the log |
| `docker compose run --rm watchtower --version` | Print the version |
| `docker compose up -d --build` | Deploy a new version |

Never run `docker compose down -v`: it deletes the volume holding your settings and the
record of which tickets were already created.

**Stuck creates.** If an SDP create times out, the outcome is unknown. Rather than risk
a duplicate, the ticket shows "Check SDP: outcome unknown" on the dashboard. Search SDP
for `[AW-<id>]`; if the request exists, run `resolve-stuck <aw_id> <sdp_id>`, otherwise
`resolve-stuck <aw_id> none` and it will be created on the next check.

## Releasing a new version

1. Bump `__version__` in `watchtower/__init__.py` and the image tag in
   `docker-compose.yml` (a test fails if they differ).
2. Add an entry at the top of `CHANGELOG.md`.
3. Commit, then tag: `git tag -a v1.0.1 -m "Watchtower 1.0.1"`.

Older images stay on the machine, so rolling back is: check out the previous tag, then
`docker compose up -d`.

## Limits to know about

- **Arctic Wolf's API can't assign, acknowledge or reopen.** Assignment and
  acknowledgement happen in SDP only. Once an AW ticket is closed, reopening the SDP
  request won't reopen it. If that matters, set "Statuses that close the AW ticket" to
  `Closed` only.
- **Comments aren't synced.** The closing comment is the only thing sent to Arctic Wolf.
- **Polling cost.** Each check reads every open mapped request from SDP once. Fine for
  tens of open tickets; raise "Check every" if you hit SDP API limits.
- **It only runs while Docker runs.** On a laptop, checks stop while it sleeps.
- **The name is shared** with the popular containrrr Watchtower image updater. The two
  can run side by side: this one uses the container name `watchtower-app` and is labeled
  so the updater leaves it alone.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
```
