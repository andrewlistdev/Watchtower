"""Settings entered in the admin GUI, stored in SQLite.

Secrets are encrypted with Fernet. The key comes from APP_ENCRYPTION_KEY if set,
otherwise it is generated once into <data dir>/secret.key (mode 0600). Keeping the
key out of the database means a copied or backed-up state.db doesn't expose tokens.

Lookup order for every setting: value saved in the GUI, then the environment
variable of the same name in upper case, then the field's default.
"""

from __future__ import annotations

import csv
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from werkzeug.security import check_password_hash, generate_password_hash

from .identity import Person

AW_REGIONS = [
    ("https://ticket-api.managedgw.us001-prod.arcticwolf.net", "US001"),
    ("https://ticket-api.managedgw.us002-prod.arcticwolf.net", "US002"),
    ("https://ticket-api.managedgw.us003-prod.arcticwolf.net", "US003"),
    ("https://ticket-api.managedgw.eu001-prod.arcticwolf.net", "EU001"),
    ("https://ticket-api.managedgw.au001-prod.arcticwolf.net", "AU001"),
    ("https://ticket-api.managedgw.ca001-prod.arcticwolf.net", "CA001"),
]

ZOHO_ACCOUNTS = [
    ("https://accounts.zoho.com", "United States (.com)"),
    ("https://accounts.zoho.eu", "Europe (.eu)"),
    ("https://accounts.zoho.in", "India (.in)"),
    ("https://accounts.zoho.com.au", "Australia (.com.au)"),
    ("https://accounts.zoho.jp", "Japan (.jp)"),
    ("https://accounts.zohocloud.ca", "Canada (.ca)"),
    ("https://accounts.zoho.sa", "Saudi Arabia (.sa)"),
    ("https://accounts.zoho.uk", "United Kingdom (.uk)"),
    ("https://accounts.zoho.com.cn", "China (.com.cn)"),
]


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    section: str
    help: str = ""
    kind: str = "text"  # text | secret | bool | int | select | list
    required: bool = False
    default: str = ""
    choices: tuple[tuple[str, str], ...] = ()
    placeholder: str = ""

    @property
    def env(self) -> str:
        return self.key.upper()

    @property
    def secret(self) -> bool:
        return self.kind == "secret"


SECTIONS = [
    ("aw", "Arctic Wolf", "Ticket source. Watchtower picks up new tickets here and closes them when "
                          "they're resolved in ServiceDesk Plus. The token is the Bearer token for the Ticket API."),
    ("sdp", "ServiceDesk Plus Cloud", "Where tickets are worked and owned. Uses a Zoho self-client refresh token "
                                      "with the SDPOnDemand.requests.ALL scope."),
    ("pd", "PagerDuty", "Who is on call. A read-only API key is enough."),
    ("behaviour", "Routing behaviour", "How often Watchtower checks for tickets and what it does with them. "
                                       "Changes apply on the next check."),
]

FIELDS: list[Field] = [
    # Arctic Wolf
    Field("aw_base_url", "Region", "aw", kind="select", required=True,
          default=AW_REGIONS[0][0], choices=tuple(AW_REGIONS)),
    Field("aw_org_uuid", "Organization UUID", "aw", required=True,
          placeholder="550e8400-e29b-41d4-a716-446655440000"),
    Field("aw_api_token", "API token", "aw", kind="secret", required=True),
    Field("aw_open_statuses", "Statuses to import", "aw", kind="list",
          default="NEW,OPEN,HOLD,PENDING", help="Comma-separated Arctic Wolf statuses."),
    Field("aw_backfill_open", "Import tickets already open", "aw", kind="bool", default="false",
          help="Only affects the first live run. Off: only tickets created after that run are imported."),
    # SDP
    Field("sdp_base_url", "SDP URL with portal", "sdp", required=True,
          placeholder="https://sdpondemand.manageengine.com/app/itdesk"),
    Field("zoho_accounts_url", "Zoho data center", "sdp", kind="select",
          default=ZOHO_ACCOUNTS[0][0], choices=tuple(ZOHO_ACCOUNTS)),
    Field("zoho_client_id", "Client ID", "sdp", required=True),
    Field("zoho_client_secret", "Client secret", "sdp", kind="secret", required=True),
    Field("zoho_refresh_token", "Refresh token", "sdp", kind="secret", required=True),
    Field("sdp_ack_status", "Status after routing", "sdp", default="In Progress",
          help="Set when Watchtower assigns a ticket. Must exist in SDP. This doesn't mean the "
               "responder has acknowledged it."),
    Field("sdp_close_statuses", "Statuses that close the AW ticket", "sdp", kind="list",
          default="Resolved,Closed",
          help="Use only Closed if requests are often reopened after Resolved. Arctic Wolf tickets can't be "
               "reopened."),
    Field("sdp_requester_email", "Requester email", "sdp", help="Optional. Defaults to the API user."),
    Field("sdp_group", "Support group", "sdp", help="Optional."),
    Field("sdp_aw_id_udf", "Field for the AW ticket ID", "sdp", placeholder="udf_sline_301",
          help="Optional. API key of a single-line request field."),
    Field("sdp_fallback_technician_email", "Fallback technician email", "sdp",
          help="Gets the ticket when no eligible on-call responder is found. Leave blank to create it "
               "unassigned."),
    Field("sdp_priority_low", "Priority for AW Low", "sdp", default="Low"),
    Field("sdp_priority_normal", "Priority for AW Normal", "sdp", default="Medium"),
    Field("sdp_priority_high", "Priority for AW High", "sdp", default="High"),
    Field("sdp_priority_urgent", "Priority for AW Urgent", "sdp", default="Urgent"),
    # PagerDuty
    Field("pd_api_token", "API key", "pd", kind="secret", required=True),
    Field("pd_schedule_id", "Schedule ID", "pd", required=True, placeholder="PXXXXXX",
          help="The ID at the end of the schedule's URL."),
    Field("handoff_minutes", "Handoff window (minutes)", "pd", kind="int", default="30",
          help="Within this many minutes of a shift's end, tickets route to the next person on call."),
    Field("pd_lookahead_hours", "Look ahead (hours)", "pd", kind="int", default="48"),
    # Behaviour
    Field("dry_run", "Dry run", "behaviour", kind="bool", default="true",
          help="Show what Watchtower would do without creating, routing or closing anything."),
    Field("poll_seconds", "Check every (seconds)", "behaviour", kind="int", default="60"),
    Field("aw_closed_note", "Add an SDP note when Arctic Wolf closes a ticket first", "behaviour", kind="bool",
          default="true"),
    Field("display_timezone", "Time zone for this page", "behaviour", default="America/New_York",
          help="Times on these pages use this zone. PagerDuty and the APIs use UTC."),
]

FIELDS_BY_KEY = {f.key: f for f in FIELDS}

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    encrypted   INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    updated_by  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admins (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS people (
    pagerduty_id   TEXT PRIMARY KEY,
    pagerduty_user TEXT NOT NULL,
    aw_assignee    TEXT NOT NULL DEFAULT '',
    aw_email       TEXT NOT NULL DEFAULT '',
    sdp_email      TEXT NOT NULL DEFAULT '',
    active         INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS audit (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at     TEXT NOT NULL,
    actor  TEXT NOT NULL,
    action TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class SettingInfo:
    field: Field
    source: str  # "saved" | "environment" | "default" | "missing"
    display: str  # never the full secret
    updated_at: str | None = None
    updated_by: str | None = None


class SettingsStore:
    def __init__(self, db_path: str, key_path: str | None = None):
        self.db_path = db_path
        self.key_path = key_path or os.path.join(os.path.dirname(db_path) or ".", "secret.key")
        self._fernet = Fernet(self._load_key())
        with self._conn() as c:
            c.executescript(SCHEMA)

    # ---- plumbing ---------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _load_key(self) -> bytes:
        env_key = os.environ.get("APP_ENCRYPTION_KEY", "").strip()
        if env_key:
            return env_key.encode()
        if os.path.exists(self.key_path):
            with open(self.key_path, "rb") as fh:
                return fh.read().strip()
        key = Fernet.generate_key()
        fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(key)
        return key

    def audit(self, actor: str, action: str) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO audit(at, actor, action) VALUES(?, ?, ?)", (_now(), actor, action))

    def recent_audit(self, limit: int = 15) -> list[sqlite3.Row]:
        with self._conn() as c:
            return c.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    # ---- settings ---------------------------------------------------------

    def _row(self, key: str) -> sqlite3.Row | None:
        with self._conn() as c:
            return c.execute("SELECT * FROM settings WHERE key = ?", (key,)).fetchone()

    def saved(self, key: str) -> str | None:
        row = self._row(key)
        if row is None:
            return None
        if row["encrypted"]:
            try:
                return self._fernet.decrypt(row["value"].encode()).decode()
            except InvalidToken:
                # Key changed or file replaced: treat as unset rather than crash.
                return None
        return row["value"]

    def resolved(self, key: str) -> str | None:
        """Value the service should use: saved, then environment, then default."""
        value = self.saved(key)
        if value not in (None, ""):
            return value
        f = FIELDS_BY_KEY.get(key)
        env_value = os.environ.get(f.env if f else key.upper(), "").strip()
        if env_value:
            return env_value
        return f.default if f and f.default else None

    def set(self, key: str, value: str, actor: str) -> None:
        f = FIELDS_BY_KEY[key]
        value = value.strip()
        stored = self._fernet.encrypt(value.encode()).decode() if f.secret else value
        with self._conn() as c:
            c.execute(
                "INSERT INTO settings(key, value, encrypted, updated_at, updated_by) VALUES(?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, encrypted=excluded.encrypted, "
                "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                (key, stored, int(f.secret), _now(), actor),
            )

    def clear(self, key: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM settings WHERE key = ?", (key,))

    def info(self, f: Field) -> SettingInfo:
        row = self._row(f.key)
        saved = self.saved(f.key)
        if saved not in (None, ""):
            source, value = "saved", saved
        elif os.environ.get(f.env, "").strip():
            source, value = "environment", os.environ[f.env].strip()
        elif f.default:
            source, value = "default", f.default
        else:
            source, value = "missing", ""
        if f.secret:
            display = f"ends in {value[-4:]}" if len(value) >= 12 else ("set" if value else "")
        else:
            display = value
        return SettingInfo(
            field=f,
            source=source,
            display=display,
            updated_at=row["updated_at"] if row and source == "saved" else None,
            updated_by=row["updated_by"] if row and source == "saved" else None,
        )

    def missing_required(self) -> list[Field]:
        return [f for f in FIELDS if f.required and not self.resolved(f.key)]

    # ---- admins -----------------------------------------------------------

    def has_admin(self) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM admins LIMIT 1").fetchone() is not None

    def create_admin(self, username: str, password: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO admins(username, password_hash, created_at) VALUES(?, ?, ?)",
                (username, generate_password_hash(password), _now()),
            )

    def set_password(self, username: str, password: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE admins SET password_hash = ? WHERE username = ?",
                      (generate_password_hash(password), username))

    def verify_admin(self, username: str, password: str) -> bool:
        with self._conn() as c:
            row = c.execute("SELECT password_hash FROM admins WHERE username = ?", (username,)).fetchone()
        if row is None:
            # Spend the same time hashing so response timing doesn't reveal usernames.
            check_password_hash(generate_password_hash("x"), password)
            return False
        return check_password_hash(row["password_hash"], password)

    def admin_exists(self, username: str) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM admins WHERE username = ?", (username,)).fetchone() is not None

    def list_admins(self) -> list[str]:
        with self._conn() as c:
            return [r["username"] for r in c.execute("SELECT username FROM admins ORDER BY username")]

    def remove_all_admins(self) -> int:
        with self._conn() as c:
            return c.execute("DELETE FROM admins").rowcount

    # ---- people (identity map) -------------------------------------------

    def list_people(self) -> list[Person]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM people ORDER BY pagerduty_user COLLATE NOCASE").fetchall()
        return [
            Person(r["pagerduty_user"], r["pagerduty_id"], r["aw_assignee"], r["aw_email"],
                   r["sdp_email"] or r["aw_email"], bool(r["active"]))
            for r in rows
        ]

    def raw_people(self) -> list[sqlite3.Row]:
        with self._conn() as c:
            return c.execute("SELECT * FROM people ORDER BY pagerduty_user COLLATE NOCASE").fetchall()

    def people_map(self) -> dict[str, Person]:
        return {p.pagerduty_id: p for p in self.list_people()}

    def replace_people(self, rows: list[dict], actor: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM people")
            c.executemany(
                "INSERT INTO people(pagerduty_id, pagerduty_user, aw_assignee, aw_email, sdp_email, active) "
                "VALUES(:pagerduty_id, :pagerduty_user, :aw_assignee, :aw_email, :sdp_email, :active)",
                rows,
            )
        self.audit(actor, f"saved the responder list ({len(rows)} responders)")

    def seed_people_from_csv(self, path: str) -> int:
        """First start only: copy config/identity_map.csv into the database."""
        if self.raw_people() or not os.path.exists(path):
            return 0
        rows = []
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                pd_id = (r.get("pagerduty_id") or "").strip()
                if not pd_id:
                    continue
                rows.append({
                    "pagerduty_id": pd_id,
                    "pagerduty_user": (r.get("pagerduty_user") or "").strip(),
                    "aw_assignee": (r.get("aw_assignee") or "").strip(),
                    "aw_email": (r.get("aw_email") or "").strip(),
                    "sdp_email": (r.get("sdp_email") or "").strip(),
                    "active": int((r.get("status") or "").strip().lower() == "active"),
                })
        if rows:
            self.replace_people(rows, "system")
        return len(rows)
