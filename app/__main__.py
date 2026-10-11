"""Entry point.

  python -m app run                 admin GUI + sync worker (what the container runs)
  python -m app once                one sync check, then exit
  python -m app check               test credentials for all three APIs (read-only)
  python -m app whois [--at ISO]    who would get a ticket right now (read-only)
  python -m app status              list tracked tickets
  python -m app resolve-stuck AW_ID SDP_ID|none
  python -m app reset-admins        remove all admin accounts; a new setup code is logged
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

from .config import Config, ConfigMissing
from .runtime import build_syncer, check_connections, db_path, open_store, shift_view
from .oncall import parse_ts
from .state import State

log = logging.getLogger("app")


def load_config(store) -> Config:
    try:
        return Config.load(store.resolved)
    except ConfigMissing as exc:
        print("Not configured yet. Add these on the admin Settings page:")
        for m in exc.missing:
            print(f"  - {m}")
        raise SystemExit(2)


def cmd_run() -> int:
    from waitress import serve

    from .web import create_app
    from .worker import Worker

    store = open_store()
    worker = Worker(store, db_path())
    worker.start()
    app = create_app(store, worker, db_path())
    port = int(os.environ.get("PORT", "8080"))
    log.info("Admin page listening on port %s", port)
    if not store.has_admin():
        app.extensions["setup_token"]()  # log the setup code now so `docker compose logs` shows it
    serve(app, host="0.0.0.0", port=port, threads=8, ident=None)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("waitress.queue").setLevel(logging.ERROR)
    parser = argparse.ArgumentParser(prog="python -m app")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run")
    sub.add_parser("once")
    sub.add_parser("check")
    w = sub.add_parser("whois")
    w.add_argument("--at", help="ISO timestamp to evaluate instead of now, e.g. 2026-10-12T21:45:00Z")
    sub.add_parser("status")
    rs = sub.add_parser("resolve-stuck")
    rs.add_argument("aw_id", type=int)
    rs.add_argument("sdp_id", help="SDP request ID you found, or 'none' to let it be recreated")
    sub.add_parser("reset-admins")
    args = parser.parse_args(argv)
    cmd = args.cmd or "run"

    if cmd == "run":
        return cmd_run()

    store = open_store()
    if cmd == "reset-admins":
        n = store.remove_all_admins()
        store.audit("cli", f"removed {n} admin account(s)")
        print(f"Removed {n} admin account(s). Open the admin page; the new setup code is in the log.")
        return 0
    if cmd == "status":
        rows = State(db_path()).all_rows()
        if not rows:
            print("No tickets tracked yet.")
        for r in rows:
            print(f"AW {r['aw_id']:>8}  SDP {r['sdp_id'] or '-':>8}  {r['state']:<14} "
                  f"{(r['assigned_email'] or '-'):<38} {(r['aw_title'] or '')[:40]}"
                  + (f"  ERROR: {r['last_error'][:80]}" if r["last_error"] else ""))
        return 0
    if cmd == "resolve-stuck":
        sdp_id = None if args.sdp_id.lower() == "none" else args.sdp_id
        done = State(db_path()).resolve_stuck(args.aw_id, sdp_id)
        print("Updated." if done else f"AW {args.aw_id} is not in 'creating' state.")
        return 0 if done else 1

    cfg = load_config(store)
    if cmd == "check":
        results = check_connections(cfg)
        for r in results:
            print(f"{'OK  ' if r.ok else 'FAIL'}  {r.service}: {r.message}")
        return 0 if all(r.ok for r in results) else 1
    if cmd == "whois":
        now = parse_ts(args.at) if args.at else datetime.now(timezone.utc)
        view = shift_view(cfg, store.people_map(), now=now)
        for entry, person in view.shifts:
            mapped = f"-> {person.sdp_email}" if person and person.active else "-> not in People"
            print(f"  {entry.start:%a %H:%M} - {entry.end:%a %H:%M} UTC  {entry.user_name} ({entry.user_id}) {mapped}")
        print(f"\nA ticket arriving now goes to: {view.assignee_name or view.assignee_email or 'nobody (unassigned)'}")
        print(f"Why: {view.reason}")
        return 0
    if cmd == "once":
        syncer = build_syncer(cfg, State(db_path()), store.people_map())
        syncer.run_cycle()
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
