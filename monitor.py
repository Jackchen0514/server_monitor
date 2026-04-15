#!/usr/bin/env python3
"""
Lightweight server monitor with Telegram notifications.
No third-party dependencies — pure stdlib only.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Tuple, Optional

# ──────────────────────────── Config ────────────────────────────

DEFAULT_CONFIG = {
    "telegram": {
        "bot_token": "",
        "chat_id": ""
    },
    "interval": 30,          # seconds between checks
    "thresholds": {
        "cpu_percent": 85,    # alert if CPU stays above this
        "cpu_consecutive": 3, # ...for this many consecutive checks
        "mem_percent": 90,
        "disk_percent": 90,
        "disk_paths": ["/"],
        "net_interface": "eth0",
        "net_max_mbps": 100,          # your uplink in Mbps
        "net_percent": 90,            # alert if usage >= X% of max
        "net_consecutive": 3          # ...for this many consecutive checks
    },
    "cooldown": 1800          # seconds before re-alerting same issue
}

CONFIG_PATH = Path(os.getenv("MONITOR_CONFIG", "/etc/monitor/config.json"))


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        # merge missing keys from defaults
        for k, v in DEFAULT_CONFIG.items():
            if k not in cfg:
                cfg[k] = v
            elif isinstance(v, dict):
                for kk, vv in v.items():
                    cfg[k].setdefault(kk, vv)
        return cfg
    return DEFAULT_CONFIG.copy()


# ──────────────────────────── Telegram ────────────────────────────

def send_tg(token: str, chat_id: str, text: str) -> bool:
    if not token or not chat_id:
        print(f"[WARN] Telegram not configured, skipping: {text}", flush=True)
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except urllib.error.URLError as e:
        print(f"[ERROR] Telegram send failed: {e}", flush=True)
        return False


# ──────────────────────────── Metrics ────────────────────────────

def cpu_percent(prev: Dict) -> Tuple[float, Dict]:
    """
    Returns (cpu_usage_percent, new_prev) using /proc/stat.
    prev = {"total": int, "idle": int}
    """
    with open("/proc/stat") as f:
        line = f.readline()   # "cpu  ..."
    fields = list(map(int, line.split()[1:]))
    # user nice system idle iowait irq softirq steal guest guest_nice
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)  # idle + iowait
    total = sum(fields)
    cur = {"total": total, "idle": idle}
    if prev:
        d_total = total - prev["total"]
        d_idle  = idle  - prev["idle"]
        pct = (1 - d_idle / d_total) * 100 if d_total else 0.0
    else:
        pct = 0.0
    return round(pct, 1), cur


def mem_percent() -> Tuple[float, int, int]:
    """Returns (percent_used, used_mb, total_mb)."""
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            info[k.strip()] = int(v.split()[0])   # kB
    total = info["MemTotal"]
    avail = info.get("MemAvailable", info.get("MemFree", 0))
    used  = total - avail
    pct   = used / total * 100 if total else 0.0
    return round(pct, 1), used // 1024, total // 1024


def disk_percent(path: str) -> Tuple[float, float, float, float]:
    """Returns (percent_used, used_gb, total_gb, avail_gb)."""
    s = os.statvfs(path)
    total = s.f_blocks * s.f_frsize
    free  = s.f_bavail * s.f_frsize
    used  = total - free
    pct   = used / total * 100 if total else 0.0
    gb    = 1024 ** 3
    return round(pct, 1), round(used / gb, 1), round(total / gb, 1), round(free / gb, 1)


def net_bytes(iface: str) -> Tuple[int, int]:
    """Returns (rx_bytes, tx_bytes) from /proc/net/dev."""
    with open("/proc/net/dev") as f:
        for line in f:
            if iface + ":" in line:
                cols = line.split()
                # col[0]=iface: rx: [1]bytes [2]packets ...  tx: [9]bytes ...
                rx = int(cols[1])
                tx = int(cols[9])
                return rx, tx
    return 0, 0


# ──────────────────────────── Alert state ────────────────────────────

class AlertState:
    """Tracks cooldowns and consecutive counters."""

    def __init__(self, cooldown: int):
        self.cooldown  = cooldown
        self._last: dict[str, float] = {}
        self._count: dict[str, int]  = {}

    def inc(self, key: str) -> int:
        self._count[key] = self._count.get(key, 0) + 1
        return self._count[key]

    def reset(self, key: str):
        self._count[key] = 0

    def count(self, key: str) -> int:
        return self._count.get(key, 0)

    def can_alert(self, key: str) -> bool:
        now = time.time()
        last = self._last.get(key, 0)
        return (now - last) >= self.cooldown

    def mark_alerted(self, key: str):
        self._last[key] = time.time()


# ──────────────────────────── Main loop ────────────────────────────

def format_bytes(b: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def hostname() -> str:
    try:
        with open("/etc/hostname") as f:
            return f.read().strip()
    except Exception:
        return "unknown"


def run():
    cfg     = load_config()
    thr     = cfg["thresholds"]
    token   = cfg["telegram"]["bot_token"]
    chat_id = cfg["telegram"]["chat_id"]
    interval = cfg["interval"]
    state   = AlertState(cfg["cooldown"])
    host    = hostname()

    prev_cpu  = {}
    prev_net  = {}
    prev_time = None

    print(f"[INFO] Monitor started on {host}. Interval={interval}s", flush=True)

    while True:
        now = time.time()

        # ── CPU ──
        cpu_pct, prev_cpu = cpu_percent(prev_cpu)
        if cpu_pct >= thr["cpu_percent"]:
            n = state.inc("cpu")
            if n >= thr["cpu_consecutive"] and state.can_alert("cpu"):
                msg = (f"🔴 <b>[{host}] HIGH CPU</b>\n"
                       f"Usage: <b>{cpu_pct}%</b> "
                       f"(threshold {thr['cpu_percent']}%, "
                       f"{n} consecutive checks)")
                send_tg(token, chat_id, msg)
                state.mark_alerted("cpu")
                print(f"[ALERT] CPU {cpu_pct}%", flush=True)
        else:
            state.reset("cpu")

        # ── Memory ──
        mem_pct, mem_used, mem_total = mem_percent()
        if mem_pct >= thr["mem_percent"]:
            if state.can_alert("mem"):
                msg = (f"🔴 <b>[{host}] HIGH MEMORY</b>\n"
                       f"Usage: <b>{mem_pct}%</b> "
                       f"({mem_used} MB / {mem_total} MB)\n"
                       f"Threshold: {thr['mem_percent']}%")
                send_tg(token, chat_id, msg)
                state.mark_alerted("mem")
                print(f"[ALERT] MEM {mem_pct}%", flush=True)

        # ── Disk ──
        for path in thr.get("disk_paths", ["/"]):
            try:
                disk_pct, disk_used, disk_total, disk_avail = disk_percent(path)
            except OSError:
                continue
            key = f"disk:{path}"
            if disk_pct >= thr["disk_percent"]:
                if state.can_alert(key):
                    msg = (f"🔴 <b>[{host}] HIGH DISK ({path})</b>\n"
                           f"Usage: <b>{disk_pct}%</b> "
                           f"({disk_used} GB / {disk_total} GB)\n"
                           f"Available: <b>{disk_avail} GB</b>\n"
                           f"Threshold: {thr['disk_percent']}%")
                    send_tg(token, chat_id, msg)
                    state.mark_alerted(key)
                    print(f"[ALERT] DISK {path} {disk_pct}%", flush=True)

        # ── Network bandwidth ──
        iface = thr.get("net_interface", "eth0")
        cur_rx, cur_tx = net_bytes(iface)
        if prev_net and prev_time:
            dt = now - prev_time
            if dt > 0:
                rx_bps = (cur_rx - prev_net[0]) / dt
                tx_bps = (cur_tx - prev_net[1]) / dt
                max_bps = thr["net_max_mbps"] * 1_000_000 / 8   # Mbps → bytes/s
                # alert on either direction
                max_usage = max(rx_bps, tx_bps)
                usage_pct = max_usage / max_bps * 100 if max_bps else 0

                if usage_pct >= thr["net_percent"]:
                    n = state.inc("net")
                    if n >= thr["net_consecutive"] and state.can_alert("net"):
                        direction = "RX" if rx_bps >= tx_bps else "TX"
                        msg = (f"🔴 <b>[{host}] BANDWIDTH SATURATION ({iface})</b>\n"
                               f"Usage: <b>{usage_pct:.1f}%</b> of {thr['net_max_mbps']} Mbps\n"
                               f"RX: {format_bytes(rx_bps)}/s  "
                               f"TX: {format_bytes(tx_bps)}/s\n"
                               f"Saturated direction: {direction} "
                               f"({n} consecutive checks)")
                        send_tg(token, chat_id, msg)
                        state.mark_alerted("net")
                        print(f"[ALERT] NET {usage_pct:.1f}% ({format_bytes(rx_bps)}/s rx, {format_bytes(tx_bps)}/s tx)", flush=True)
                else:
                    state.reset("net")

        prev_net  = (cur_rx, cur_tx)
        prev_time = now

        time.sleep(interval)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n[INFO] Monitor stopped.", flush=True)
        sys.exit(0)
