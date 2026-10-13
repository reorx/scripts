#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Inspect, scan, edit and restore macOS application preferences.

Saved preferences are facts; static scan results are candidates, not a schema.
Usage and boundaries: kb/docs/app-defaults.md.
"""

import argparse
import base64
import json
import math
import plistlib
import re
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

BACKUPS = Path.home() / "Library/Application Support/app-defaults/backups"
DEFAULTS_OBJECT = object()
DEFAULTS_CLASS = object()
SECRET_KEY = re.compile(r"api.?key|password|secret|token|credential|authorization|cookie", re.I)
APIS = {
    "stringForKey:": ("read", "string", "x2"),
    "boolForKey:": ("read", "bool", "x2"),
    "doubleForKey:": ("read", "float", "x2"),
    "integerForKey:": ("read", "int", "x2"),
    "floatForKey:": ("read", "float", "x2"),
    "arrayForKey:": ("read", "array", "x2"),
    "dictionaryForKey:": ("read", "dict", "x2"),
    "dataForKey:": ("read", "data", "x2"),
    "objectForKey:": ("read", "unknown", "x2"),
    "setObject:forKey:": ("write", "unknown", "x3"),
    "setBool:forKey:": ("write", "bool", "x3"),
    "setDouble:forKey:": ("write", "float", "x2"),
    "setFloat:forKey:": ("write", "float", "x2"),
    "setInteger:forKey:": ("write", "int", "x3"),
    "removeObjectForKey:": ("delete", "unknown", "x2"),
}


@dataclass
class Target:
    bundle_id: str
    domain: str
    app_path: Path | None = None
    executable: Path | None = None


@dataclass
class Finding:
    key: str
    access: str
    value_type: str
    address: str
    function: str
    receiver_identified: bool


def run_command(args: list[str], *, input_data: bytes | None = None) -> bytes:
    result = subprocess.run(args, input=input_data, capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace").strip() or f"命令失败：{args[0]}")
    return result.stdout


def find_apps(name: str) -> list[Path]:
    roots = [Path("/Applications"), Path.home() / "Applications", Path("/System/Applications"), Path("/System/Applications/Utilities")]
    paths = sorted({p for root in roots for p in root.glob("*.app")})
    by_name = [p for p in paths if name.casefold() in (p.name.casefold(), p.stem.casefold())]
    if by_name or "." not in name:
        return by_name
    matches = []
    for path in paths:
        result = subprocess.run(
            ["plutil", "-extract", "CFBundleIdentifier", "raw", "-o", "-", str(path / "Contents/Info.plist")],
            capture_output=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.decode().strip() == name:
            matches.append(path)
    return matches


def resolve_target(name: str, store: str = "auto") -> Target:
    path = Path(name).expanduser()
    if path.is_dir() and path.suffix.lower() == ".app":
        apps = [path.resolve()]
    elif "/" in name:
        raise ValueError(f"应用路径不存在或不是 .app：{name}")
    else:
        apps = find_apps(name)
    if len(apps) > 1:
        raise ValueError("找到多个应用，请使用完整路径：" + ", ".join(map(str, apps)))
    if apps:
        path = apps[0]
        info = plistlib.loads(run_command(["plutil", "-convert", "binary1", "-o", "-", str(path / "Contents/Info.plist")]))
        bundle_id = info["CFBundleIdentifier"]
        executable = path / "Contents/MacOS" / info["CFBundleExecutable"]
    elif re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+", name):
        bundle_id, path, executable = name, None, None
    else:
        raise ValueError(f"未找到应用：{name}；可使用 .app 完整路径或 Bundle ID")
    standard = Path.home() / "Library/Preferences" / f"{bundle_id}.plist"
    container = Path.home() / "Library/Containers" / bundle_id / "Data/Library/Preferences" / f"{bundle_id}.plist"
    if store == "auto" and standard.exists() and container.exists():
        raise ValueError("普通偏好与沙盒偏好都存在，请用 --store standard 或 --store container 指定")
    use_container = store == "container" or (store == "auto" and container.exists())
    if use_container and not container.exists():
        raise ValueError(f"沙盒偏好文件尚不存在：{container}")
    return Target(bundle_id, str(container.with_suffix("")) if use_container else bundle_id, path, executable)


def read_preferences(target: Target) -> dict:
    result = subprocess.run(["defaults", "export", target.domain, "-"], capture_output=True, timeout=30)
    if result.returncode:
        error = result.stderr.decode(errors="replace")
        if "does not exist" in error or "could not be found" in error:
            return {}
        raise RuntimeError(error.strip())
    value = plistlib.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("偏好域不是字典")
    return value


def value_type(value) -> str:
    for cls, name in [(bool, "bool"), (int, "int"), (float, "float"), (str, "string"), (bytes, "data"), (datetime, "date"), (list, "array"), (dict, "dict")]:
        if isinstance(value, cls):
            return name
    raise ValueError(f"不支持的 plist 类型：{type(value).__name__}")


def display_value(value, key: str = "", show_secrets: bool = False):
    if not show_secrets and SECRET_KEY.search(key) and not key.startswith("KeyboardShortcuts_"):
        return "<redacted>"
    if isinstance(value, dict):
        return {k: display_value(v, k, show_secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [display_value(v, key, show_secrets) for v in value]
    if isinstance(value, bytes):
        return {"bytes": len(value), **({"base64": base64.b64encode(value).decode()} if show_secrets else {})}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and not show_secrets and re.search(r'"(?:api.?key|password|secret|token)"\s*:', value, re.I):
        return "<redacted: structured string>"
    return value


def validate_plist(value):
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        raise ValueError("plist 不接受 null 或非有限浮点数")
    if isinstance(value, dict):
        for child in value.values():
            validate_plist(child)
    elif isinstance(value, list):
        for child in value:
            validate_plist(child)
    plistlib.dumps(value)
    return value


def parse_value(kind: str, text: str):
    if kind == "bool":
        if text.lower() not in ("true", "false", "yes", "no", "1", "0"):
            raise ValueError("bool 值必须为 true/false、yes/no 或 1/0")
        return text.lower() in ("true", "yes", "1")
    parsers = {"string": str, "int": int, "float": float, "json": json.loads, "data": bytes.fromhex}
    return validate_plist(parsers[kind](text))


def save_backup(target: Target, preferences: dict, directory: Path | None = None) -> Path:
    directory = directory or BACKUPS
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = f"{target.bundle_id}-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.plist"
    path = directory / name
    payload = {"format_version": 1, "bundle_id": target.bundle_id, "domain": target.domain, "preferences": preferences}
    with path.open("xb") as output:
        path.chmod(0o600)
        output.write(plistlib.dumps(payload, fmt=plistlib.FMT_BINARY))
    return path


def write_arguments(target: Target, key: str, kind: str, value) -> list[str]:
    flags = {"string": "-string", "bool": "-bool", "int": "-int", "float": "-float", "data": "-data"}
    base = ["defaults", "write", target.domain, key]
    if kind == "json":
        return base + [plistlib.dumps(value).decode()]
    text = value.hex() if kind == "data" else str(value).lower() if kind == "bool" else str(value)
    return base + [flags[kind], text]


def set_preference(target: Target, key: str, kind: str, text: str) -> Path:
    value = parse_value(kind, text)
    preferences = read_preferences(target)
    backup = save_backup(target, preferences)
    print(f"修改前备份：{backup}", file=sys.stderr)
    run_command(write_arguments(target, key, kind, value))
    actual = read_preferences(target)
    if key not in actual or actual[key] != value or value_type(actual[key]) != value_type(value):
        raise RuntimeError(f"写入后读回不匹配；可使用备份恢复：{backup}")
    return backup


def delete_preference(target: Target, key: str) -> Path:
    preferences = read_preferences(target)
    if key not in preferences:
        raise ValueError(f"已保存的键不存在：{key}")
    backup = save_backup(target, preferences)
    print(f"修改前备份：{backup}", file=sys.stderr)
    run_command(["defaults", "delete", target.domain, key])
    if key in read_preferences(target):
        raise RuntimeError(f"删除后键仍存在；备份：{backup}")
    return backup


def restore_preferences(target: Target, path: Path) -> Path:
    payload = plistlib.loads(path.expanduser().read_bytes())
    if payload.get("format_version") != 1 or payload.get("domain") != target.domain or payload.get("bundle_id") != target.bundle_id:
        raise ValueError("备份的版本、应用或偏好来源不匹配")
    preferences = payload["preferences"]
    if not isinstance(preferences, dict):
        raise ValueError("备份中的 preferences 必须是字典")
    backup = save_backup(target, read_preferences(target))
    print(f"恢复前备份：{backup}", file=sys.stderr)
    # `defaults import` merges and retains keys introduced after the snapshot.
    run_command(["defaults", "write", target.domain, plistlib.dumps(preferences).decode()])
    if read_preferences(target) != preferences:
        raise RuntimeError(f"恢复后读回不匹配；恢复前备份：{backup}")
    return backup


def swift_string(a, b) -> str | None:
    if isinstance(b, str):
        return b
    if isinstance(a, int) and isinstance(b, int) and b >> 60 == 14:
        count = (b >> 56) & 15
        return (a.to_bytes(8, "little") + b.to_bytes(8, "little"))[:count].decode("utf-8", errors="replace")
    return None


@dataclass
class Arm64Scanner:
    registers: dict = field(default_factory=dict)
    memory: dict = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    unresolved: int = 0
    function: str = ""

    def clear_call_registers(self):
        for n in range(19):
            self.registers.pop(f"x{n}", None)

    def call(self, args: str, address: str):
        regs = self.registers
        result = None
        if "bridgeToObjectiveCSo8NSString" in args:
            result = swift_string(regs.get("x0"), regs.get("x1"))
        elif "standardUserDefaults" in args or "initWithSuiteName:" in args:
            result = DEFAULTS_OBJECT
        elif any(name in args for name in ("_objc_retainAutoreleasedReturnValue", "_objc_retain", "_objc_opt_self")):
            result = regs.get("x0")
        else:
            self.preference_call(args, address)
        self.clear_call_registers()
        regs["x0"] = result

    def preference_call(self, args: str, address: str):
        selector = args.split("_objc_msgSend$", 1)[-1].strip('"')
        if "_objc_msgSend$" not in args or selector not in APIS:
            return
        access, kind, key_register = APIS[selector]
        known_receiver = self.registers.get("x0") is DEFAULTS_OBJECT
        if kind == "unknown" and not known_receiver:
            return  # NSDictionary and KVC calls must not become preference keys.
        key = self.registers.get(key_register)
        if not isinstance(key, str):
            self.unresolved += 1
            return
        self.findings.append(Finding(key, access, kind, address, self.function, known_receiver))

    def move(self, op: str, operands: list[str]):
        dst, src = operands[:2]
        dst = dst.replace("w", "x", 1) if dst.startswith("w") else dst
        if not src.startswith("#"):
            self.registers[dst] = self.registers.get(src.replace("w", "x", 1) if src.startswith("w") else src)
            return
        value = int(src[1:], 0) & ((1 << 64) - 1)
        if op == "movk":
            shift = int(operands[2].split("#")[1], 0) if len(operands) > 2 else 0
            old = self.registers.get(dst)
            value = (old & ~(65535 << shift) | value << shift) if isinstance(old, int) else None
        self.registers[dst] = value

    def arithmetic(self, op: str, operands: list[str]):
        dst, src, rhs = operands[:3]
        old = self.registers.get(src)
        value = None
        if isinstance(old, str) and rhs.startswith("#"):
            value = old
        elif isinstance(old, int) and rhs.startswith("#") and len(operands) == 3:
            number = int(rhs[1:], 0)
            value = ((old + number) if op == "add" else (old - number) if op == "sub" else old | number) & ((1 << 64) - 1)
        self.registers[dst] = value

    def load_store(self, op: str, operands: list[str], args: str):
        match = re.search(r"\[(x\d+)(?:,\s*#(0x[0-9a-f]+|\d+))?\]", args)
        base = self.registers.get(match[1]) if match else None
        location = base + int(match[2] or "0", 0) if isinstance(base, int) else None
        if op == "str":
            if location is not None:
                self.memory[location] = self.registers.get(operands[0])
        elif "_OBJC_CLASS_$_NSUserDefaults" in args:
            self.registers[operands[0]] = DEFAULTS_CLASS
        else:
            self.registers[operands[0]] = self.memory.get(location)

    def instruction(self, address: str, op: str, args: str):
        operands = [v.strip() for v in args.split(";")[0].split(",")]
        literal = re.search(r'literal pool for: "(.*)"', args)
        if literal:
            self.registers[operands[0]] = literal[1]
        elif op == "bl":
            self.call(args, address)
        elif op == "blr":
            self.clear_call_registers()
        elif op == "adrp":
            page = re.search(r";\s*(0x[0-9a-f]+)", args)
            self.registers[operands[0]] = int(page[1], 16) if page else None
        elif op in ("mov", "movk") and len(operands) >= 2:
            self.move(op, operands)
        elif op in ("add", "sub", "orr") and len(operands) >= 3:
            self.arithmetic(op, operands)
        elif op in ("ldr", "str"):
            self.load_store(op, operands, args)
        elif op in ("ldp", "ldur", "ldrb", "adr", "csel", "and", "ubfx", "orr", "add", "sub"):
            self.registers[operands[0]] = None
            if op == "ldp":
                self.registers[operands[1]] = None


def scan_arm64(lines) -> tuple[list[Finding], int]:
    scanner = Arm64Scanner()
    for line in lines:
        match = re.match(r"([0-9a-f]{16})\s+(\S+)\s*(.*)", line)
        if match:
            scanner.instruction(*match.groups())
        elif line.strip().endswith(":"):
            scanner.function = line.strip()[:-1]
            scanner.registers.clear()
    return scanner.findings, scanner.unresolved


def scan_application(target: Target) -> dict:
    if target.executable is None or not target.executable.is_file():
        raise ValueError("scan 需要已安装应用的路径或名称，无法只扫描偏好域")
    architectures = run_command(["xcrun", "lipo", "-archs", str(target.executable)]).decode().split()
    if "arm64" not in architectures:
        raise ValueError("静态扫描目前支持 ARM64 Mach-O；此应用仍可使用 inspect/set/delete/backup/restore")
    assembly = run_command(["xcrun", "otool", "-arch", "arm64", "-tvV", str(target.executable)]).decode(errors="replace")
    findings, unresolved = scan_arm64(assembly.splitlines())
    saved = read_preferences(target)
    grouped = {}
    for finding in findings:
        row = grouped.setdefault(finding.key, {"key": finding.key, "saved": finding.key in saved, "types": set(), "access": set(), "references": []})
        row["types"].add(finding.value_type)
        row["access"].add(finding.access)
        row["references"].append(asdict(finding))
    candidates = [{**row, "types": sorted(row["types"]), "access": sorted(row["access"])} for _, row in sorted(grouped.items())]
    return {"bundle_id": target.bundle_id, "executable": str(target.executable), "candidates": candidates,
            "unresolved_calls": unresolved, "limitations": [
                "仅扫描主 ARM64 可执行文件，不覆盖全部框架、插件、Electron/JavaScript 配置或动态生成的键。",
                "寄存器跟踪为静态启发式；候选键、类型与读写调用不保证运行时生效，也不代表默认值或完整参数清单。",
                "候选调用可能属于其他 suite；扫描不能确认每个键都属于当前应用的主偏好域。",
                "scan 不检查钥匙串，不修改或启动应用。",
            ]}


def inspect_application(target: Target, show_secrets: bool, query: str) -> dict:
    values = read_preferences(target)
    rows = [{"key": key, "type": value_type(value), "value": display_value(value, key, show_secrets)}
            for key, value in sorted(values.items()) if query.casefold() in key.casefold()]
    return {"bundle_id": target.bundle_id, "domain": target.domain, "app_path": str(target.app_path) if target.app_path else None,
            "saved_preferences": rows, "note": "这些是已保存的值，不含全部代码默认值、注册默认值、全局/ByHost/其他 suite 的继承值或钥匙串。"}


def print_report(report: dict, json_output: bool):
    if json_output:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(f"应用：{report['bundle_id']}")
    if "saved_preferences" in report:
        print(f"来源：{report['domain']}\n键\t类型\t已保存的值")
        for row in report["saved_preferences"]:
            print(f"{row['key']}\t{row['type']}\t{json.dumps(row['value'], ensure_ascii=False)}")
        print(report["note"])
    else:
        print("键\t调用\t候选类型\t已有保存值")
        for row in report["candidates"]:
            print(f"{row['key']}\t{','.join(row['access'])}\t{','.join(row['types'])}\t{row['saved']}")
        print(f"无法恢复键名的调用：{report['unresolved_calls']}")
        print("\n".join(report["limitations"]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检查、扫描、修改 macOS 应用偏好；修改前自动备份。")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in [("inspect", "列出已保存设置"), ("scan", "扫描原生 ARM64 候选键"), ("set", "写入一个设置"),
                            ("delete", "删除一个覆盖值"), ("backup", "备份当前偏好域"), ("restore", "恢复一个完整偏好域备份")]:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("target", help="应用名称、.app 路径或 Bundle ID")
        command.add_argument("--store", choices=["auto", "standard", "container"], default="auto", help="选择普通/沙盒偏好来源")
        if name in ("inspect", "scan"):
            command.add_argument("--json", action="store_true")
            command.add_argument("--filter", default="", help="按键名过滤")
        if name == "inspect":
            command.add_argument("--show-secrets", action="store_true", help="显示敏感键值与二进制数据")
        if name in ("set", "delete"):
            command.add_argument("key")
            command.add_argument("--dry-run", action="store_true", help="预览，不写入或创建备份")
        if name == "set":
            command.add_argument("value")
            command.add_argument("--type", choices=["string", "bool", "int", "float", "json", "data"], required=True, dest="kind")
        if name == "restore":
            command.add_argument("backup", type=Path)
    return parser


def execute(args):
    target = resolve_target(args.target, args.store)
    if args.command == "inspect":
        print_report(inspect_application(target, args.show_secrets, args.filter), args.json)
    elif args.command == "scan":
        report = scan_application(target)
        report["candidates"] = [row for row in report["candidates"] if args.filter.casefold() in row["key"].casefold()]
        print_report(report, args.json)
    elif args.command == "backup":
        print(save_backup(target, read_preferences(target)))
    elif args.command == "restore":
        restore_preferences(target, args.backup)
        print("已恢复整个偏好域；重新打开应用以加载设置。")
    elif args.dry_run:
        old = read_preferences(target).get(args.key)
        new = parse_value(args.kind, args.value) if args.command == "set" else "<delete saved override>"
        print(json.dumps({"domain": target.domain, "key": args.key, "old": display_value(old, args.key),
                          "new": display_value(new, args.key), "dry_run": True}, ensure_ascii=False, indent=2))
    elif args.command == "set":
        set_preference(target, args.key, args.kind, args.value)
        print(f"已写入 {args.key} 并读回验证；重新打开应用以加载设置。")
    else:
        delete_preference(target, args.key)
        print(f"已删除 {args.key} 的保存值；应用可能回退到代码默认值或继承值。")


def main() -> int:
    args = build_parser().parse_args()
    try:
        execute(args)
    except (ValueError, KeyError, RuntimeError, OSError, OverflowError, subprocess.TimeoutExpired, plistlib.InvalidFileException) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
