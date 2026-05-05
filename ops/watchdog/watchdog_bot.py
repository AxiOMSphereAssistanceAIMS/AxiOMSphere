#!/usr/bin/env python3
"""
AIMS Watchdog Bot — always-on health monitor and automatic project recovery.

Runs OUTSIDE the main Docker stack (host process or standalone container) so it
survives a full stack restart.

Features:
- Automatic startup sequence after hardware reboot
- Dependency-aware service startup order
- Health validation with timeout
- Telegram notifications on success/failure
- Manual control via Telegram commands

Env vars:
  AIMS_WATCHDOG_BOT_TOKEN         — Telegram bot token (required)
  AIMS_WATCHDOG_ALLOWED_USER_IDS  — comma-separated Telegram user ids (required)
  AIMS_WATCHDOG_OWNER_CHAT_IDS    — comma-separated chat ids for proactive alerts (optional)
  AIMS_WATCHDOG_COMPOSE_FILE      — path to docker-compose.yml (default: auto-detected)
  AIMS_WATCHDOG_COMPOSE_PROJECT   — compose project name (default: axiomsphere)
  AIMS_WATCHDOG_AUTO_STARTUP      — enable automatic startup on boot (default: true)
  AIMS_WATCHDOG_STARTUP_TIMEOUT   — startup validation timeout in seconds (default: 300)

Commands:
  /status         — show which always-on services are up/down
  /rebuild_all    — docker compose build + up (all profiles) + health check + report
  /up             — docker compose up -d (no build, all profiles)
  /restart <svc>  — restart one service
  /logs <svc>     — last 40 lines of logs for a service
  /auto_startup   — trigger automatic startup sequence manually
  /whoami         — show your Telegram user id
  /help
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import threading
import time
import traceback
import urllib.parse
import urllib.request
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────

_SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
_WORKSPACE = _SCRIPT_DIR.parent.parent  # ops/watchdog/ → ops/ → workspace/

_COMPOSE_FILE_DEFAULT = str(_WORKSPACE / "docker-compose.yml")

COMPOSE_FILE = os.environ.get("AIMS_WATCHDOG_COMPOSE_FILE", _COMPOSE_FILE_DEFAULT)
COMPOSE_PROJECT = os.environ.get("AIMS_WATCHDOG_COMPOSE_PROJECT", "axiomsphere")
AUTO_STARTUP = os.environ.get("AIMS_WATCHDOG_AUTO_STARTUP", "true").lower() in ("true", "1", "yes")
STARTUP_TIMEOUT = int(os.environ.get("AIMS_WATCHDOG_STARTUP_TIMEOUT", "300"))

TOKEN = (os.environ.get("AIMS_WATCHDOG_BOT_TOKEN") or "").strip()
ALLOWED_USERS_RAW = os.environ.get("AIMS_WATCHDOG_ALLOWED_USER_IDS", "").strip()
OWNER_CHATS_RAW = os.environ.get("AIMS_WATCHDOG_OWNER_CHAT_IDS", "").strip()

if not TOKEN:
    raise SystemExit("Missing AIMS_WATCHDOG_BOT_TOKEN")

ALLOWED_USERS = {
    int(x.strip())
    for x in ALLOWED_USERS_RAW.replace(" ", "").split(",")
    if x.strip().isdigit()
}

OWNER_CHAT_IDS: list[int] = [
    int(x.strip())
    for x in OWNER_CHATS_RAW.replace(" ", "").split(",")
    if x.strip().isdigit()
]

BOT_API = f"https://api.telegram.org/bot{TOKEN}"

# ── Always-on service list ─────────────────────────────────────────────────
# Services with restart:unless-stopped or restart:always in docker-compose.yml.
# Excludes: restart:'no' (omi-register, job-filter-bot, omi-sync — scheduled)
#           nim-* (GPU-heavy, started on demand)
#           firecrawl-* (optional)
# All have explicit container_name: axiomsphere-<service>

# Startup sequence: services grouped by dependency tier
TIER_1_INFRASTRUCTURE = [
    "aims-redis",
    "qdrant",
]

TIER_2_CORE_SERVICES = [
    "task-registry",
    "omi-api",
    "litellm",
    "flaresolverr",
    "prometheus",
]

TIER_3_AGENTS = [
    "doc-agent",
    "aims-api",
    "aims-worker",
    "aims-orchestrator",
    "omi-quality-gate",
]

TIER_4_BOTS_AND_WORKERS = [
    "axi-bot",
    "omi-bot",
    "argus-bot",
    "inbox-cleanup",
    "ocr-watcher",
    "omi-batch-ingest",
    "schedule",
    "grafana",
]

CORE_SERVICES = TIER_1_INFRASTRUCTURE + TIER_2_CORE_SERVICES + TIER_3_AGENTS
TELEGRAM_SERVICES = ["axi-bot", "omi-bot", "argus-bot"]
ALWAYS_ON: list[str] = TIER_1_INFRASTRUCTURE + TIER_2_CORE_SERVICES + TIER_3_AGENTS + TIER_4_BOTS_AND_WORKERS

# Startup sequence for automatic recovery
STARTUP_SEQUENCE = [
    TIER_1_INFRASTRUCTURE,
    TIER_2_CORE_SERVICES,
    TIER_3_AGENTS,
    TIER_4_BOTS_AND_WORKERS,
]

# Profiles needed to bring up all ALWAYS_ON services
ALL_PROFILES = ["telegram-bots", "legacy-axi-bot"]

# ── Lock (one rebuild/up at a time) ───────────────────────────────────────────

_op_lock = threading.Lock()

# ── Docker helpers ────────────────────────────────────────────────────────────

def _base_compose() -> list[str]:
    cmd = ["docker", "compose", "-f", COMPOSE_FILE, "-p", COMPOSE_PROJECT]
    for p in ALL_PROFILES:
        cmd += ["--profile", p]
    return cmd


def _run(cmd: list[str], timeout: int = 600) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, f"timeout after {timeout}s"
    except Exception as exc:
        return -1, str(exc)


def _container_name(service: str) -> str:
    return f"{COMPOSE_PROJECT}-{service}"


def _running_containers() -> set[str]:
    """Return container names that are actually Up (not Restarting/Exited)."""
    rc, out = _run(["docker", "ps", "--filter", "status=running", "--format", "{{.Names}}"])
    if rc != 0:
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def _health_status(container_name: str) -> str:
    """Return docker healthcheck status: healthy / unhealthy / starting / none."""
    rc, out = _run(
        ["docker", "inspect", "--format", "{{.State.Health.Status}}", container_name],
        timeout=10,
    )
    if rc != 0:
        return "none"
    val = out.strip()
    return val if val else "none"


# Returns dict: service → ("running"|"down", health_status)
def check_services() -> dict[str, tuple[str, str]]:
    running = _running_containers()
    result: dict[str, tuple[str, str]] = {}
    for svc in ALWAYS_ON:
        cname = _container_name(svc)
        if cname in running:
            result[svc] = ("running", _health_status(cname))
        else:
            result[svc] = ("down", "none")
    return result


# ── Telegram helpers ──────────────────────────────────────────────────────────

def api(method: str, payload: dict | None = None) -> dict:
    url = f"{BOT_API}/{method}"
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(
        url, data=data, headers=headers,
        method="POST" if payload else "GET"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def send(chat_id: int, text: str) -> None:
    while len(text) > 3800:
        api("sendMessage", {
            "chat_id": chat_id,
            "text": text[:3800],
            "disable_web_page_preview": True,
        })
        text = text[3800:]
    api("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    })


def is_allowed(user_id: int) -> bool:
    return user_id in ALLOWED_USERS


def notify_owners(text: str) -> None:
    for chat_id in OWNER_CHAT_IDS:
        try:
            send(chat_id, text)
        except Exception:
            pass


# ── Status ────────────────────────────────────────────────────────────────────

def _health_icon(state: str, health: str) -> str:
    if state != "running":
        return "❌"
    if health == "healthy":
        return "✅"
    if health == "unhealthy":
        return "🔴"
    if health == "starting":
        return "🟡"
    return "🟢"  # running, no healthcheck defined


def status_text() -> str:
    statuses = check_services()
    ts = datetime.now().strftime("%H:%M:%S")
    lines = [f"📊 AIMS service status — {ts}\n"]

    down = [s for s, (st, _) in statuses.items() if st != "running"]
    unhealthy = [s for s, (st, h) in statuses.items() if st == "running" and h == "unhealthy"]

    for svc, (state, health) in statuses.items():
        icon = _health_icon(state, health)
        health_label = f" ({health})" if health not in ("none", "healthy") else ""
        lines.append(f"{icon} {svc}{health_label}")

    if not down and not unhealthy:
        lines.append("\n🟢 All services UP")
    else:
        if down:
            lines.append(f"\n❌ Not running ({len(down)}): {', '.join(down)}")
        if unhealthy:
            lines.append(f"\n🔴 Unhealthy ({len(unhealthy)}): {', '.join(unhealthy)}")
    return "\n".join(lines)


# ── Rebuild / Up ──────────────────────────────────────────────────────────────

def _do_rebuild_all(chat_id: int) -> None:
    if not _op_lock.acquire(blocking=False):
        send(chat_id, "⚠️ Another operation is already in progress.")
        return
    try:
        send(chat_id, "🔨 Full rebuild started. Building all images…")

        rc1, out1 = _run(_base_compose() + ["build"], timeout=1200)
        build_tail = out1[-600:] if out1 else "(no output)"
        if rc1 != 0:
            send(chat_id, f"❌ Build failed (exit {rc1}):\n{build_tail}")
            return
        send(chat_id, f"✅ Build done.\n{build_tail}")

        send(chat_id, "⬆️ Starting all services…")
        rc2, out2 = _run(_base_compose() + ["up", "-d"], timeout=300)
        up_tail = out2[-800:] if out2 else "(no output)"
        if rc2 != 0:
            send(chat_id, f"⚠️ docker compose up exit {rc2}:\n{up_tail}")
        else:
            send(chat_id, f"✅ docker compose up -d done.\n{up_tail}")

        send(chat_id, "⏳ Waiting 30s for containers to stabilise…")
        time.sleep(30)

        statuses = check_services()
        down = [s for s, (st, _) in statuses.items() if st != "running"]
        unhealthy = [s for s, (st, h) in statuses.items() if st == "running" and h == "unhealthy"]
        up_count = len(statuses) - len(down)

        if not down and not unhealthy:
            send(chat_id, f"✅ All {up_count} always-on services are UP. Project is running.")
        else:
            problems = [f"  • {s} (not running)" for s in down] + \
                       [f"  • {s} (unhealthy)" for s in unhealthy]
            send(
                chat_id,
                f"⚠️ Rebuild done — issues:\n" + "\n".join(problems) +
                "\n\nUse /logs <service> to inspect or /restart <service> to retry.",
            )
    except Exception:
        send(chat_id, "💥 Watchdog error during rebuild:\n" + traceback.format_exc()[-2000:])
    finally:
        _op_lock.release()


def _do_up(chat_id: int) -> None:
    if not _op_lock.acquire(blocking=False):
        send(chat_id, "⚠️ Another operation is already in progress.")
        return
    try:
        send(chat_id, "⬆️ Running docker compose up -d (no build)…")
        rc, out = _run(_base_compose() + ["up", "-d"], timeout=300)
        tail = out[-800:] if out else "(no output)"
        if rc == 0:
            send(chat_id, f"✅ Up done.\n{tail}")
        else:
            send(chat_id, f"⚠️ Exit {rc}:\n{tail}")
        time.sleep(15)
        send(chat_id, status_text())
    finally:
        _op_lock.release()


# ── Automatic Startup Sequence ────────────────────────────────────────────────

def _wait_for_service_healthy(service: str, timeout: int = 60) -> bool:
    """Wait for a service to become healthy or running.

    Returns True if service is up and healthy/running within timeout.
    """
    cname = _container_name(service)
    start = time.time()

    while time.time() - start < timeout:
        running = _running_containers()
        if cname not in running:
            time.sleep(2)
            continue

        health = _health_status(cname)
        if health in ("healthy", "none"):  # none = no healthcheck, assume ok if running
            return True

        time.sleep(2)

    return False


def _start_tier(tier: list[str], tier_name: str) -> tuple[list[str], list[str]]:
    """Start a tier of services and wait for them to be healthy.

    Returns (successful_services, failed_services).
    """
    print(f"Starting tier: {tier_name}")

    # Start all services in tier
    for svc in tier:
        cmd = _base_compose() + ["up", "-d", svc]
        rc, out = _run(cmd, timeout=120)
        if rc != 0:
            print(f"Failed to start {svc}: {out[:200]}")

    # Wait for all services in tier to be healthy
    successful = []
    failed = []

    for svc in tier:
        if _wait_for_service_healthy(svc, timeout=60):
            successful.append(svc)
            print(f"✓ {svc} is up")
        else:
            failed.append(svc)
            print(f"✗ {svc} failed to start")

    return successful, failed


def _do_auto_startup(chat_id: int | None = None) -> None:
    """Execute automatic startup sequence with dependency-aware ordering.

    If chat_id is provided, sends progress updates to Telegram.
    """
    if not _op_lock.acquire(blocking=False):
        if chat_id:
            send(chat_id, "⚠️ Another operation is already in progress.")
        return

    try:
        start_time = time.time()

        if chat_id:
            send(chat_id, "🚀 Automatic startup sequence initiated\n\nStarting services in dependency order…")

        print(f"=== AIMS Automatic Startup Sequence Started — {datetime.now().isoformat()} ===")

        all_successful = []
        all_failed = []

        tier_names = [
            "Tier 1: Infrastructure (Redis, Qdrant)",
            "Tier 2: Core Services",
            "Tier 3: Agents",
            "Tier 4: Bots & Workers",
        ]

        for tier, tier_name in zip(STARTUP_SEQUENCE, tier_names):
            if chat_id:
                send(chat_id, f"⏳ {tier_name}…")

            successful, failed = _start_tier(tier, tier_name)
            all_successful.extend(successful)
            all_failed.extend(failed)

            if failed:
                if chat_id:
                    send(chat_id, f"⚠️ {tier_name} — {len(failed)} failed: {', '.join(failed)}")
            else:
                if chat_id:
                    send(chat_id, f"✅ {tier_name} — all services up")

            # Wait between tiers for stabilization
            time.sleep(5)

        elapsed = round(time.time() - start_time, 1)

        # Final health check
        if chat_id:
            send(chat_id, "⏳ Running final health validation…")

        time.sleep(10)
        statuses = check_services()
        down = [s for s, (st, _) in statuses.items() if st != "running"]
        unhealthy = [s for s, (st, h) in statuses.items() if st == "running" and h == "unhealthy"]

        # Build report
        report_lines = [
            f"🏁 Automatic startup completed in {elapsed}s\n",
            f"✅ Started: {len(all_successful)}",
            f"❌ Failed: {len(all_failed)}",
        ]

        if not down and not unhealthy:
            report_lines.append("\n🟢 All services are UP and healthy")
            report_lines.append("\n✅ System ready for operation")
        else:
            if down:
                report_lines.append(f"\n❌ Not running ({len(down)}): {', '.join(down)}")
            if unhealthy:
                report_lines.append(f"\n🔴 Unhealthy ({len(unhealthy)}): {', '.join(unhealthy)}")
            report_lines.append("\n⚠️ Manual intervention may be required")
            report_lines.append("Use /logs <service> to inspect or /restart <service> to retry")

        report = "\n".join(report_lines)

        print(f"=== Startup Report ===\n{report}")

        if chat_id:
            send(chat_id, report)

        # Notify all owners
        notify_owners(report)

        # Check if ArgusAgent is running for ongoing monitoring
        argus_status = statuses.get("argus-bot", ("down", "none"))
        if argus_status[0] == "running":
            print("ArgusAgent is running — ongoing monitoring active")
        else:
            print("WARNING: ArgusAgent is not running — no ongoing monitoring")
            if chat_id:
                send(chat_id, "⚠️ ArgusAgent is not running. Use /restart argus-bot to enable monitoring.")

    except Exception:
        error_msg = "💥 Automatic startup error:\n" + traceback.format_exc()[-2000:]
        print(error_msg)
        if chat_id:
            send(chat_id, error_msg)
        notify_owners(error_msg)
    finally:
        _op_lock.release()


def _do_up(chat_id: int) -> None:
    if not _op_lock.acquire(blocking=False):
        send(chat_id, "⚠️ Another operation is already in progress.")
        return
    try:
        send(chat_id, "⬆️ Running docker compose up -d (no build)…")
        rc, out = _run(_base_compose() + ["up", "-d"], timeout=300)
        tail = out[-800:] if out else "(no output)"
        if rc == 0:
            send(chat_id, f"✅ Up done.\n{tail}")
        else:
            send(chat_id, f"⚠️ Exit {rc}:\n{tail}")
        time.sleep(15)
        send(chat_id, status_text())
    finally:
        _op_lock.release()


# ── Restart / Logs ────────────────────────────────────────────────────────────

def _do_restart(chat_id: int, service: str) -> None:
    service = service.lower().strip()
    if not service:
        send(chat_id, "Usage: /restart <service>")
        return
    send(chat_id, f"🔄 Restarting {service}…")

    # Try compose restart first, then direct docker restart
    compose_cmd = ["docker", "compose", "-f", COMPOSE_FILE, "-p", COMPOSE_PROJECT,
                   "restart", service]
    rc, out = _run(compose_cmd, timeout=90)
    if rc == 0:
        send(chat_id, f"✅ {service} restarted.")
        return

    cname = _container_name(service)
    rc2, out2 = _run(["docker", "restart", cname], timeout=60)
    if rc2 == 0:
        send(chat_id, f"✅ {service} restarted (direct container).")
    else:
        send(chat_id, f"❌ Failed to restart {service}:\ncompose: {out}\ndocker: {out2}")


def _do_logs(chat_id: int, service: str) -> None:
    service = service.lower().strip()
    if not service:
        send(chat_id, "Usage: /logs <service>")
        return
    rc, out = _run(
        ["docker", "compose", "-f", COMPOSE_FILE, "-p", COMPOSE_PROJECT,
         "logs", "--no-color", "--tail", "40", service],
        timeout=30,
    )
    if not out:
        out = "(no output)"
    send(chat_id, f"📋 Logs for {service}:\n{out[-3500:]}")


# ── Message handler ───────────────────────────────────────────────────────────

def handle_message(msg: dict) -> None:
    chat_id = msg["chat"]["id"]
    user_id = int(msg.get("from", {}).get("id", 0))
    text = (msg.get("text") or "").strip()

    if text.startswith("/whoami"):
        send(chat_id, f"Your Telegram user id: {user_id}")
        return

    if not is_allowed(user_id):
        send(chat_id, f"Access denied. Your Telegram user id: {user_id}")
        return

    if text.startswith(("/start", "/help")):
        send(chat_id, (
            "AIMS Watchdog Bot\n\n"
            "/status          — show all always-on services\n"
            "/rebuild_all     — build + up + health check (~5 min)\n"
            "/up              — docker compose up -d (no build)\n"
            "/auto_startup    — automatic startup sequence with dependency order\n"
            "/restart <svc>   — restart one service\n"
            "/logs <svc>      — last 40 log lines for a service\n"
            "/whoami          — show your Telegram user id\n"
        ))
        return

    if text.startswith("/status"):
        send(chat_id, status_text())
        return

    if text.startswith("/rebuild_all"):
        threading.Thread(target=_do_rebuild_all, args=(chat_id,), daemon=True).start()
        return

    if text.startswith("/up"):
        threading.Thread(target=_do_up, args=(chat_id,), daemon=True).start()
        return

    if text.startswith("/auto_startup"):
        threading.Thread(target=_do_auto_startup, args=(chat_id,), daemon=True).start()
        return

    if text.startswith("/restart"):
        svc = text[len("/restart"):].strip()
        threading.Thread(target=_do_restart, args=(chat_id, svc), daemon=True).start()
        return

    if text.startswith("/logs"):
        svc = text[len("/logs"):].strip()
        threading.Thread(target=_do_logs, args=(chat_id, svc), daemon=True).start()
        return

    send(chat_id, "Unknown command. Use /help")


# ── Polling loop ──────────────────────────────────────────────────────────────

def main() -> None:
    print(f"AIMS Watchdog Bot started — {datetime.now().isoformat()}")
    print(f"Compose file: {COMPOSE_FILE}")
    print(f"Allowed users: {sorted(ALLOWED_USERS) if ALLOWED_USERS else 'NONE'}")
    print(f"Owner chats: {OWNER_CHAT_IDS}")
    print(f"Monitoring {len(ALWAYS_ON)} always-on services")
    print(f"Auto-startup enabled: {AUTO_STARTUP}")

    # Run automatic startup sequence on boot if enabled
    if AUTO_STARTUP:
        print("Auto-startup is enabled. Checking if startup is needed…")
        time.sleep(5)  # Wait for Docker daemon to be ready

        statuses = check_services()
        down_count = sum(1 for _, (st, _) in statuses.items() if st != "running")

        if down_count > len(ALWAYS_ON) * 0.3:  # More than 30% services down
            print(f"{down_count}/{len(ALWAYS_ON)} services are down. Triggering automatic startup…")
            _do_auto_startup(chat_id=None)
        else:
            print(f"Only {down_count}/{len(ALWAYS_ON)} services down. Skipping automatic startup.")
            notify_owners(f"👀 AIMS Watchdog started — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{down_count}/{len(ALWAYS_ON)} services down. No automatic startup needed.\n/status for details.")
    else:
        notify_owners(f"👀 AIMS Watchdog started — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nAuto-startup disabled. Monitoring {len(ALWAYS_ON)} services. /status for details.")

    offset = 0
    while True:
        try:
            params = urllib.parse.urlencode({"timeout": 30, "offset": offset})
            url = f"{BOT_API}/getUpdates?{params}"
            with urllib.request.urlopen(url, timeout=40) as resp:
                data = json.loads(resp.read().decode())
            for update in data.get("result", []):
                offset = max(offset, update["update_id"] + 1)
                if "message" in update:
                    handle_message(update["message"])
        except KeyboardInterrupt:
            raise
        except Exception:
            print(traceback.format_exc())
            time.sleep(5)


if __name__ == "__main__":
    main()
