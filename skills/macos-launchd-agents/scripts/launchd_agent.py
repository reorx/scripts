#!/usr/bin/env python3
"""Inspect and manage macOS app-installed launchd jobs."""

from __future__ import annotations

import argparse
import os
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Iterable


LAUNCHD_DIRS = [
    Path("/Library/LaunchDaemons"),
    Path("/Library/LaunchAgents"),
    Path.home() / "Library/LaunchAgents",
]
HELPER_DIR = Path("/Library/PrivilegedHelperTools")


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def read_plist(path: Path) -> dict:
    with path.open("rb") as fh:
        return plistlib.load(fh)


def iter_plists() -> Iterable[Path]:
    for directory in LAUNCHD_DIRS:
        if directory.exists():
            yield from sorted(directory.glob("*.plist"))


def normalize_domain(domain: str | None) -> str | None:
    if not domain:
        return None
    uid = os.getuid()
    if domain == "gui":
        return f"gui/{uid}"
    if domain == "user":
        return f"user/{uid}"
    return domain


def plist_domain(path: Path) -> str | None:
    path = path.expanduser().resolve()
    uid = os.getuid()
    if str(path).startswith("/Library/LaunchDaemons/"):
        return "system"
    if str(path).startswith("/Library/LaunchAgents/"):
        return f"gui/{uid}"
    if str(path).startswith(str((Path.home() / "Library/LaunchAgents").resolve())):
        return f"gui/{uid}"
    return None


def service_target(domain: str, label: str) -> str:
    return f"{domain}/{label}"


def plist_summary(path: Path) -> tuple[str | None, str | None]:
    try:
        data = read_plist(path)
    except Exception:
        return None, None
    label = data.get("Label")
    program = data.get("Program")
    args = data.get("ProgramArguments")
    if not program and isinstance(args, list) and args:
        program = str(args[0])
    return str(label) if label else None, str(program) if program else None


def find_plists(target: str) -> list[Path]:
    maybe_path = Path(target).expanduser()
    if maybe_path.exists() and maybe_path.suffix == ".plist":
        return [maybe_path]

    matches: list[Path] = []
    for path in iter_plists():
        label, program = plist_summary(path)
        haystacks = [path.name, str(path), label or "", program or ""]
        if target in haystacks or any(target.lower() in value.lower() for value in haystacks):
            matches.append(path)
    return matches


def resolve_single(target: str, plist_arg: str | None, domain_arg: str | None) -> tuple[Path, str, str]:
    if plist_arg:
        plist_path = Path(plist_arg).expanduser()
        if not plist_path.exists():
            raise SystemExit(f"plist does not exist: {plist_path}")
        label, _ = plist_summary(plist_path)
        label = label or target
    else:
        matches = find_plists(target)
        if not matches:
            raise SystemExit(f"no matching plist found for: {target}")
        if len(matches) > 1:
            print("Multiple plist matches; pass --plist to choose one:", file=sys.stderr)
            for match in matches:
                label, program = plist_summary(match)
                print(f"- {match} label={label or '?'} program={program or '?'}", file=sys.stderr)
            raise SystemExit(2)
        plist_path = matches[0]
        label, _ = plist_summary(plist_path)
        label = label or target

    domain = normalize_domain(domain_arg) or plist_domain(plist_path)
    if not domain:
        raise SystemExit("could not infer launchd domain; pass --domain system, gui, gui/<uid>, user, or user/<uid>")
    return plist_path, label, domain


def applescript_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def run_shell(shell_command: str, admin_prompt: bool) -> int:
    if admin_prompt:
        script = f"do shell script {applescript_quote(shell_command)} with administrator privileges"
        proc = run(["osascript", "-e", script])
    else:
        proc = run(["/bin/sh", "-c", shell_command])

    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    return proc.returncode


def command_search(args: argparse.Namespace) -> int:
    query = args.query.lower()
    found = False

    for path in iter_plists():
        raw = ""
        try:
            raw = path.read_text(errors="ignore")
        except Exception:
            pass
        label, program = plist_summary(path)
        searchable = "\n".join([str(path), path.name, label or "", program or "", raw]).lower()
        if query in searchable:
            found = True
            print(f"PLIST={path}")
            print(f"LABEL={label or ''}")
            print(f"PROGRAM={program or ''}")
            print()

    if HELPER_DIR.exists():
        for path in sorted(HELPER_DIR.iterdir()):
            if query in path.name.lower() or query in str(path).lower():
                found = True
                print(f"HELPER={path}")

    return 0 if found else 1


def print_launchctl_state(label: str, domain: str) -> None:
    target = service_target(domain, label)
    proc = run(["launchctl", "print", target])
    print(f"$ launchctl print {target}")
    if proc.returncode == 0:
        lines = proc.stdout.splitlines()
        for line in lines[:80]:
            print(line)
        if len(lines) > 80:
            print(f"... truncated {len(lines) - 80} lines")
    else:
        message = (proc.stderr or proc.stdout).strip()
        print(message or f"exit {proc.returncode}")
    print()

    proc = run(["launchctl", "print-disabled", domain])
    print(f"$ launchctl print-disabled {domain} | contains label")
    if proc.returncode == 0:
        matches = [line for line in proc.stdout.splitlines() if label in line]
        print("\n".join(matches) if matches else "(no disabled override found)")
    else:
        print((proc.stderr or proc.stdout).strip() or f"exit {proc.returncode}")
    print()


def matching_process_lines(pattern: str) -> list[str]:
    proc = run(["ps", "-axo", "pid=,args="])
    if proc.returncode != 0:
        return []
    needle = pattern.lower()
    script_name = Path(__file__).name
    matches: list[str] = []
    for line in proc.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, args = stripped.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        lowered = args.lower()
        if pid == os.getpid() or script_name.lower() in lowered:
            continue
        if needle in lowered:
            matches.append(stripped)
    return matches


def command_inspect(args: argparse.Namespace) -> int:
    matches = find_plists(args.target)
    if not matches:
        print(f"No plist matched: {args.target}", file=sys.stderr)
        return 1

    for path in matches:
        label, program = plist_summary(path)
        domain = normalize_domain(args.domain) or plist_domain(path)
        print(f"PLIST={path}")
        print(f"LABEL={label or ''}")
        print(f"PROGRAM={program or ''}")
        print(f"DOMAIN={domain or ''}")
        print()
        if label and domain:
            print_launchctl_state(label, domain)

    print(f"$ ps -axo pid=,args= | filtered for {shlex.quote(args.target)}")
    matches = matching_process_lines(args.target)
    if matches:
        print("\n".join(matches))
    else:
        print("(no process matched)")
    return 0


def command_disable(args: argparse.Namespace) -> int:
    plist_path, label, domain = resolve_single(args.target, args.plist, args.domain)
    target = service_target(domain, label)
    shell_command = (
        f"launchctl disable {shlex.quote(target)}; "
        "disable_status=$?; "
        f"launchctl bootout {shlex.quote(domain)} {shlex.quote(str(plist_path))}; "
        'bootout_status=$?; '
        'if [ "$disable_status" -ne 0 ]; then exit "$disable_status"; fi; '
        "exit 0"
    )
    print(f"PLIST={plist_path}")
    print(f"LABEL={label}")
    print(f"DOMAIN={domain}")
    print(f"COMMAND={shell_command}")
    if not args.confirm:
        print("Refusing to change launchd state without --confirm.", file=sys.stderr)
        return 2
    if domain == "system" and os.geteuid() != 0 and not args.admin_prompt:
        print("System domain changes need root. Add --admin-prompt or run as root.", file=sys.stderr)
        return 2
    return run_shell(shell_command, args.admin_prompt)


def command_enable(args: argparse.Namespace) -> int:
    plist_path, label, domain = resolve_single(args.target, args.plist, args.domain)
    target = service_target(domain, label)
    shell_command = (
        f"launchctl enable {shlex.quote(target)}; "
        "enable_status=$?; "
        f"launchctl bootstrap {shlex.quote(domain)} {shlex.quote(str(plist_path))}; "
        "bootstrap_status=$?; "
        'if [ "$enable_status" -ne 0 ]; then exit "$enable_status"; fi; '
        'if [ "$bootstrap_status" -ne 0 ]; then exit "$bootstrap_status"; fi; '
        "exit 0"
    )
    print(f"PLIST={plist_path}")
    print(f"LABEL={label}")
    print(f"DOMAIN={domain}")
    print(f"COMMAND={shell_command}")
    if not args.confirm:
        print("Refusing to change launchd state without --confirm.", file=sys.stderr)
        return 2
    if domain == "system" and os.geteuid() != 0 and not args.admin_prompt:
        print("System domain changes need root. Add --admin-prompt or run as root.", file=sys.stderr)
        return 2
    return run_shell(shell_command, args.admin_prompt)


def command_verify(args: argparse.Namespace) -> int:
    domain = normalize_domain(args.domain)
    if not domain:
        matches = find_plists(args.target)
        if not matches:
            raise SystemExit("pass --domain when verifying a label without a matching plist")
        domain = plist_domain(matches[0])
    if not domain:
        raise SystemExit("could not infer launchd domain; pass --domain")
    print_launchctl_state(args.target, domain)
    print(f"$ ps -axo pid=,args= | filtered for {shlex.quote(args.target)}")
    matches = matching_process_lines(args.target)
    if matches:
        print("\n".join(matches))
    else:
        print("(no process matched)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search, inspect, disable, verify, and enable macOS launchd jobs.")
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="Search launchd plist files and PrivilegedHelperTools.")
    search.add_argument("query")
    search.set_defaults(func=command_search)

    inspect = sub.add_parser("inspect", help="Inspect matching plist and launchctl state.")
    inspect.add_argument("target", help="Label, plist path, helper name, or search fragment.")
    inspect.add_argument("--domain", help="system, gui, gui/<uid>, user, or user/<uid>.")
    inspect.set_defaults(func=command_inspect)

    disable = sub.add_parser("disable", help="Disable and boot out one launchd job.")
    disable.add_argument("target", help="Label or plist path.")
    disable.add_argument("--plist", help="Explicit plist path if target is a label.")
    disable.add_argument("--domain", help="system, gui, gui/<uid>, user, or user/<uid>.")
    disable.add_argument("--confirm", action="store_true", help="Required to make changes.")
    disable.add_argument("--admin-prompt", action="store_true", help="Use a macOS administrator prompt via osascript.")
    disable.set_defaults(func=command_disable)

    enable = sub.add_parser("enable", help="Enable and bootstrap one launchd job.")
    enable.add_argument("target", help="Label or plist path.")
    enable.add_argument("--plist", help="Explicit plist path if target is a label.")
    enable.add_argument("--domain", help="system, gui, gui/<uid>, user, or user/<uid>.")
    enable.add_argument("--confirm", action="store_true", help="Required to make changes.")
    enable.add_argument("--admin-prompt", action="store_true", help="Use a macOS administrator prompt via osascript.")
    enable.set_defaults(func=command_enable)

    verify = sub.add_parser("verify", help="Verify disabled/loaded state and matching process.")
    verify.add_argument("target", help="Label to verify.")
    verify.add_argument("--domain", help="system, gui, gui/<uid>, user, or user/<uid>.")
    verify.set_defaults(func=command_verify)
    return parser


def main() -> int:
    if sys.platform != "darwin":
        print("This helper is intended for macOS only.", file=sys.stderr)
        return 2
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
