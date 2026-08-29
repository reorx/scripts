#!/usr/bin/env python3
"""Audit macOS Full Disk Access (FDA) entries in the system TCC database.

Lists each entry with its name, kind, auth state, last-modified time and the
resolved on-disk path, then flags entries whose app/binary can no longer be
found (stale entries that are safe to remove).

Requires the terminal itself to have Full Disk Access to read TCC.db.

Usage:
  ./fda-audit.py             # table + stale analysis
  ./fda-audit.py --json      # raw JSON output
  ./fda-audit.py --commands  # print cleanup commands for stale entries
"""

import argparse
import datetime
import json
import os
import sqlite3
import subprocess
import sys

TCC_DB = "/Library/Application Support/com.apple.TCC/TCC.db"
SERVICE = "kTCCServiceSystemPolicyAllFiles"

AUTH_LABELS = {0: "OFF", 1: "unknown", 2: "ON", 3: "limited"}

APP_SEARCH_DIRS = [
    "/Applications",
    "/Applications/Utilities",
    "/System/Applications",
    "/System/Applications/Utilities",
    os.path.expanduser("~/Applications"),
    "/Library/PreferencePanes",
]


def mdfind_bundle(bundle_id: str) -> list[str]:
    """Locate installed bundles by bundle id via Spotlight."""
    try:
        out = subprocess.run(
            ["mdfind", f"kMDItemCFBundleIdentifier == '{bundle_id}'"],
            capture_output=True, text=True, timeout=15,
        )
        return [p for p in out.stdout.strip().splitlines() if p]
    except Exception:
        return []


def scan_apps_for_bundle(bundle_id: str) -> list[str]:
    """Fallback: scan common app dirs and read each bundle's Info.plist id."""
    import plistlib
    hits = []
    for d in APP_SEARCH_DIRS:
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            info = os.path.join(d, name, "Contents", "Info.plist")
            if not os.path.isfile(info):
                continue
            try:
                with open(info, "rb") as f:
                    pl = plistlib.load(f)
                if pl.get("CFBundleIdentifier") == bundle_id:
                    hits.append(os.path.join(d, name))
            except Exception:
                continue
    return hits


def resolve_entry(client: str, client_type: int) -> dict:
    """Resolve a TCC client to on-disk locations and existence."""
    if client_type == 1:  # absolute path to a binary
        return {"kind": "path", "paths": [client], "exists": os.path.exists(client)}
    # client_type == 0: bundle identifier
    paths = mdfind_bundle(client)
    if not paths:
        paths = scan_apps_for_bundle(client)
    return {"kind": "bundle", "paths": paths, "exists": bool(paths)}


def load_entries() -> list[dict]:
    uri = f"file:{TCC_DB}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    rows = con.execute(
        "SELECT client, client_type, auth_value, last_modified "
        "FROM access WHERE service = ? ORDER BY client COLLATE NOCASE",
        (SERVICE,),
    ).fetchall()
    con.close()

    entries = []
    for client, client_type, auth_value, last_modified in rows:
        info = resolve_entry(client, client_type)
        entries.append({
            "client": client,
            "kind": info["kind"],
            "auth": AUTH_LABELS.get(auth_value, str(auth_value)),
            "modified": datetime.datetime.fromtimestamp(last_modified).strftime("%Y-%m-%d %H:%M"),
            "paths": info["paths"],
            "exists": info["exists"],
        })
    return entries


def print_table(entries: list[dict]) -> None:
    name_w = max(len(e["client"]) for e in entries)
    hdr = f"{'CLIENT':<{name_w}}  {'KIND':<6} {'AUTH':<4} {'MODIFIED':<16} {'EXISTS':<6} PATH"
    print(hdr)
    print("-" * len(hdr))
    for e in entries:
        path = e["paths"][0] if e["paths"] else "(not found)"
        print(f"{e['client']:<{name_w}}  {e['kind']:<6} {e['auth']:<4} "
              f"{e['modified']:<16} {'yes' if e['exists'] else 'NO':<6} {path}")
        for extra in e["paths"][1:]:
            print(f"{'':<{name_w}}  {'':<6} {'':<4} {'':<16} {'':<6} {extra}")


def print_cleanup_commands(stale: list[dict]) -> None:
    """Print commands that remove stale entries from the FDA list.

    Bundle-id entries can be removed with tccutil; path entries have no
    tccutil support, so emit sqlite deletes against the system TCC.db
    (terminal needs FDA, run with sudo).
    """
    bundles = [e for e in stale if e["kind"] == "bundle"]
    paths = [e for e in stale if e["kind"] == "path"]
    if bundles:
        print("# bundle-id entries (removes the entry for this service only):")
        for e in bundles:
            print(f"sudo tccutil reset SystemPolicyAllFiles {e['client']}")
    if paths:
        print("\n# path entries (tccutil cannot target these; delete rows directly):")
        for e in paths:
            q = e["client"].replace("'", "''")
            print(f"sudo sqlite3 '{TCC_DB}' \"DELETE FROM access "
                  f"WHERE service='{SERVICE}' AND client='{q}';\"")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="output JSON")
    ap.add_argument("--commands", action="store_true",
                    help="print cleanup commands for stale entries")
    args = ap.parse_args()

    if not os.path.exists(TCC_DB):
        sys.exit(f"TCC db not found: {TCC_DB}")
    try:
        entries = load_entries()
    except sqlite3.OperationalError as e:
        sys.exit(f"Cannot read {TCC_DB}: {e}\n"
                 "Grant Full Disk Access to your terminal first.")

    if args.json:
        json.dump(entries, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return

    stale = [e for e in entries if not e["exists"]]
    if args.commands:
        print_cleanup_commands(stale)
        return

    print_table(entries)
    print(f"\nTotal: {len(entries)}   stale (target missing): {len(stale)}")
    if stale:
        print("\nStale entries (app/binary no longer on disk):")
        for e in stale:
            print(f"  - {e['client']}  [{e['kind']}, auth={e['auth']}, modified={e['modified']}]")


if __name__ == "__main__":
    main()
