"""CLI entry point.

  python -m app run                 poll forever (default; what the container runs)
  python -m app once                one sync cycle, then exit
  python -m app whois [--at ISO]    who would get a ticket right now (read-only)
  python -m app check               test credentials for all three APIs (read-only)
  python -m app status              list tracked tickets from the state DB
  python -m app resolve-stuck AW_ID SDP_ID|none
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone

from .arcticwolf import ArcticWolfClient
from .config import Config
from .identity import load_identity_map
from .oncall import merge_adjacent, parse_ts, pick_on_shift
from .pagerduty import PagerDutyClient
from .servicedesk import ServiceDeskClient
from .state import State
from .sync import Syncer

log = logging.getLogger("app")


def build(cfg: Config) -> Syncer:
    os.makedirs(os.path.dirname(cfg.db_path) or ".", exist_ok=True)
    return Syncer(
        cfg=cfg,
        aw=ArcticWolfClient(cfg.aw_base_url, cfg.aw_api_token, cfg.aw_org_uuid),
        sdp=ServiceDeskClient(
            cfg.sdp_base_url,
            cfg.zoho_accounts_url,
            cfg.zoho_client_id,
            cfg.zoho_client_secret,
            cfg.zoho_refresh_token,
        ),
        pd=PagerDutyClient(cfg.pd_api_token),
        state=State(cfg.db_path),
        people=load_identity_map(cfg.identity_map_path),
    )


def cmd_run(syncer: Syncer, once: bool) -> int:
    stop = {"flag": False}

    def _stop(*_):
        stop["flag"] = True
        log.info("Shutdown requested; finishing current cycle")

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    log.info(
        "Starting: poll=%ss dry_run=%s handoff=%smin close_on=%s ack_status=%r",
        syncer.cfg.poll_seconds, syncer.cfg.dry_run, syncer.cfg.handoff_minutes,
        syncer.cfg.sdp_close_statuses, syncer.cfg.sdp_ack_status,
    )
    while True:
        try:
            syncer.run_cycle()
        except Exception:
            log.exception("Sync cycle failed; will retry next cycle")
            if once:
                return 1
        if once or stop["flag"]:
            return 0
        for _ in range(syncer.cfg.poll_seconds):
            if stop["flag"]:
                return 0
            time.sleep(1)


def cmd_whois(syncer: Syncer, at: str | None) -> int:
    if at:
        moment = parse_ts(at)
        syncer.now = lambda: moment
    now = syncer.now()
    entries = syncer.pd.schedule_entries(syncer.cfg.pd_schedule_id, now, syncer.cfg.pd_lookahead_hours)
    print(f"Schedule {syncer.cfg.pd_schedule_id} from {now:%Y-%m-%d %H:%M} UTC:")
    for e in merge_adjacent(entries)[:8]:
        person = syncer.people.get(e.user_id)
        mapped = f"-> {person.sdp_email}" if person and person.active else "-> NOT IN IDENTITY MAP"
        print(f"  {e.start:%a %H:%M} - {e.end:%a %H:%M} UTC  {e.user_name} ({e.user_id}) {mapped}")
    sel = pick_on_shift(entries, now, syncer.cfg.handoff_minutes)
    who = syncer.choose_assignee()
    print(f"\nA ticket arriving now goes to: {who.email or '(unassigned)'}")
    print(f"Why: {who.reason}")
    return 0 if sel else 2


def cmd_check(syncer: Syncer) -> int:
    ok = True
    checks = [
        ("Arctic Wolf", lambda: next(iter(syncer.aw.list_tickets(["OPEN"])), None)),
        ("ServiceDesk Plus", syncer.sdp.ping),
        ("PagerDuty", lambda: syncer.pd.schedule_entries(
            syncer.cfg.pd_schedule_id, datetime.now(timezone.utc), 1)),
    ]
    for name, fn in checks:
        try:
            fn()
            print(f"OK    {name}")
        except Exception as exc:
            ok = False
            print(f"FAIL  {name}: {exc}")
    missing = [p for p in syncer.people.values() if not p.active]
    print(f"Identity map: {len(syncer.people)} people, {len(missing)} inactive")
    return 0 if ok else 1


def cmd_status(syncer: Syncer) -> int:
    rows = syncer.state.all_rows()
    if not rows:
        print("No tickets tracked yet.")
        return 0
    for r in rows:
        print(f"AW {r['aw_id']:>8}  SDP {r['sdp_id'] or '-':>8}  {r['state']:<14} "
              f"{(r['assigned_email'] or '-'):<38} {(r['aw_title'] or '')[:40]}"
              + (f"  ERROR: {r['last_error'][:80]}" if r["last_error"] else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    parser = argparse.ArgumentParser(prog="python -m app")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run")
    sub.add_parser("once")
    w = sub.add_parser("whois")
    w.add_argument("--at", help="ISO timestamp to evaluate instead of now, e.g. 2026-10-12T21:45:00Z")
    sub.add_parser("check")
    sub.add_parser("status")
    rs = sub.add_parser("resolve-stuck")
    rs.add_argument("aw_id", type=int)
    rs.add_argument("sdp_id", help="SDP request ID you found, or 'none' to let it be recreated")
    args = parser.parse_args(argv)

    syncer = build(Config.from_env())
    cmd = args.cmd or "run"
    if cmd in ("run", "once"):
        return cmd_run(syncer, once=cmd == "once")
    if cmd == "whois":
        return cmd_whois(syncer, args.at)
    if cmd == "check":
        return cmd_check(syncer)
    if cmd == "status":
        return cmd_status(syncer)
    if cmd == "resolve-stuck":
        sdp_id = None if args.sdp_id.lower() == "none" else args.sdp_id
        done = syncer.state.resolve_stuck(args.aw_id, sdp_id)
        print("Updated." if done else f"AW {args.aw_id} is not in 'creating' state.")
        return 0 if done else 1
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
