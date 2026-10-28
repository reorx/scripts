#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""清理指定荣耀手机的第三方应用：默认预览，--apply 按顶部白名单卸载。

仅处理主用户 0，不删除系统应用，不自动安装缺失的白名单应用。
白名单不会阻止手机以后安装新应用；修改保留范围时直接编辑下面的表。
"""

import argparse
import re
import subprocess
import sys

# 这台手机专用；不要替换成自动选择第一台已连接设备。
DEVICE_SERIAL = "AB9UUT4510000125"
DEVICE_MODELS = {"ALI-AN00", "ALI_AN00"}
ANDROID_USER = "0"

# 白名单：包名 → 应用名。新增条目须经手机主人明确要求保留。
WHITELIST = {
    "com.tencent.mm": "微信",
    "com.eg.android.AlipayGphone": "支付宝",
    "com.icbc": "中国工商银行",
    "cn.com.hbnxmbank.Android": "湖北农信",
    "com.autonavi.minimap": "高德地图",
    "com.baidu.searchbox": "百度",
    "com.ss.android.ugc.aweme": "抖音（普通版）",
    "com.phoenix.read": "红果免费短剧",
    "tv.danmaku.bili": "哔哩哔哩",
    "com.ximalaya.ting.android": "喜马拉雅",
    "com.tencent.news": "腾讯新闻",
    "com.taobao.idlefish": "闲鱼",
    "com.lianjia.beike": "贝壳找房",
}


def adb(*args: str) -> str:
    result = subprocess.run(
        ["adb", "-s", DEVICE_SERIAL, *args],
        check=True, capture_output=True, text=True, timeout=60,
    )
    return result.stdout.strip()


def check_device() -> None:
    result = subprocess.run(
        ["adb", "devices"], check=True, capture_output=True, text=True, timeout=15,
    )
    devices = dict(
        line.split()[:2] for line in result.stdout.splitlines()
        if line.startswith(DEVICE_SERIAL + "\t") or line.startswith(DEVICE_SERIAL + " ")
    )
    if devices.get(DEVICE_SERIAL) != "device":
        raise RuntimeError(f"指定手机 {DEVICE_SERIAL} 未连接或未授权 USB 调试")
    model = adb("shell", "getprop", "ro.product.model")
    if model not in DEVICE_MODELS:
        raise RuntimeError(f"设备型号不匹配：{model!r}，停止操作")
    print(f"手机：{model} / {DEVICE_SERIAL}，Android 用户：{ANDROID_USER}")


def installed_packages() -> set[str]:
    output = adb("shell", "pm", "list", "packages", "-3", "--user", ANDROID_USER)
    lines = output.splitlines()
    if not lines or any(not re.fullmatch(r"package:[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+", line) for line in lines):
        raise RuntimeError("无法可靠读取第三方应用清单，停止操作：" + output)
    return {line.removeprefix("package:") for line in lines}


def cleanup(apply: bool) -> None:
    check_device()
    installed = installed_packages()
    extras = sorted(installed - WHITELIST.keys())
    print(f"已安装第三方应用：{len(installed)}；白名单外：{len(extras)}")
    for package in extras:
        print(f"  待卸载：{package}")
    for package in sorted(WHITELIST.keys() - installed):
        print(f"  未安装（不自动安装）：{WHITELIST[package]} / {package}")
    if not apply:
        print("预览完成，未修改手机。执行清理请加 --apply。")
        return
    for package in extras:
        result = adb("shell", "pm", "uninstall", "--user", ANDROID_USER, package)
        if result != "Success":
            raise RuntimeError(f"卸载 {package} 失败：{result}")
        print(f"  已卸载：{package}", flush=True)
    remaining = installed_packages()
    unexpected = remaining - WHITELIST.keys()
    if unexpected:
        raise RuntimeError("复查仍存在白名单外应用：" + ", ".join(sorted(unexpected)))
    print(f"复查通过：保留 {len(remaining)} 个第三方应用，均在白名单中。")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="实际卸载主用户中白名单外的第三方应用及其数据")
    args = parser.parse_args()
    try:
        cleanup(args.apply)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError):
            print((exc.stderr or exc.stdout or "").strip(), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
