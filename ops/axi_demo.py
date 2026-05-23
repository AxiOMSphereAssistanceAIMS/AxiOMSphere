"""
Recordable scripted Telegram AIMS walkthrough demo for AxiOMSphere bot.

Safety constraints:
  - Zero LLM / model / evaluator calls
  - Zero external service calls
  - Zero operational / training / evidence writes
  - All scenario content is fictional
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)

# ── Session state ──────────────────────────────────────────────────────────────

class DemoState(Enum):
    IDLE      = "IDLE"
    READY     = "READY"
    RUNNING   = "RUNNING"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    FAILED    = "FAILED"


@dataclass
class DemoSession:
    chat_id: int
    state: DemoState = DemoState.IDLE
    lobby_message_id: Optional[int] = None
    task: Optional[asyncio.Task] = None
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    started_at: float = field(default_factory=time.monotonic)


# in-memory session store; one session per chat
_sessions: dict[int, DemoSession] = {}
_last_completed: dict[int, float] = {}   # chat_id → monotonic time

COOLDOWN_SECONDS = 60

# ── Static content ─────────────────────────────────────────────────────────────

LOBBY_TEXT = (
    "*AxiOMSphere AIMS Walkthrough*\n\n"
    "This demonstration walks through a scripted internal development scenario.\n"
    "No real data is processed. All outputs are illustrative.\n\n"
    "_North Shore Gas Processing Development — Gulf Region_\n\n"
    "Press *▶ START AXI* to begin or *About* to learn more."
)

LOBBY_KEYBOARD = InlineKeyboardMarkup([[
    InlineKeyboardButton("▶ START AXI",  callback_data="demo_start"),
    InlineKeyboardButton("About",        callback_data="demo_about"),
    InlineKeyboardButton("■ CANCEL",     callback_data="demo_cancel"),
]])

ABOUT_TEXT = (
    "*About this demonstration*\n\n"
    "AxiOMSphere coordinates specialised AI agents on private GPU infrastructure "
    "to build, synchronise, restore and continuously improve the AIMS operating "
    "framework for industrial projects.\n\n"
    "This walkthrough is a scripted internal scenario. It makes no external calls "
    "and writes no operational data. All content is fictional.\n\n"
    "_Scenario: North Shore Gas Processing Development, Gulf Region_\n"
    "_Framework: ISO 55001 / ISO 55002_"
)

DEMO_HELP_TEXT = (
    "*Demo commands*\n\n"
    "/demo — launch demonstration lobby\n"
    "/demo\\_stop — stop a running demonstration\n"
    "/demo\\_help — show this message"
)

# ── Script ─────────────────────────────────────────────────────────────────────
# Each step is a dict with keys:
#   type: ENGINEER_PROGRESSIVE_TYPE | POST_AS_COMPLETED_CARD | PAUSE | TYPING_INDICATOR
#   text: message text (Markdown)
#   delay_before: seconds to wait before this step
#   delay_after: seconds to wait after this step (for PAUSE type, also the pause length)
#   chars_per_sec: typing speed (ENGINEER_PROGRESSIVE_TYPE only)

_SCRIPT: list[dict] = [
    # ── Scene 1: Project input ─────────────────────────────────────────────────
    {
        "type": "ENGINEER_PROGRESSIVE_TYPE",
        "text": "PROJECT INPUT: Begin AIMS scope definition for North Shore Gas Processing Development.",
        "delay_before": 0.5,
        "delay_after": 1.2,
        "chars_per_sec": 3,
    },
    {
        "type": "TYPING_INDICATOR",
        "delay_before": 0.4,
        "delay_after": 1.8,
        "text": "",
    },
    {
        "type": "POST_AS_COMPLETED_CARD",
        "text": (
            "*AXIOMSPHERE ASSISTANT*\n\n"
            "Scope definition initiated for *North Shore Gas Processing Development* "
            "(Gulf Region, pilot stage).\n\n"
            "Registering project under AIMS lifecycle stage *01 — Project Definition*.\n"
            "Applying ISO 55001 requirements baseline and ISO 55002 guidance structure.\n\n"
            "_Work products queued:_ Asset Strategy · Project Scope Register · "
            "Risk Register Baseline · Organisational Boundary Definition"
        ),
        "delay_before": 0.3,
        "delay_after": 1.5,
    },
    # ── Scene 2: Framework build ───────────────────────────────────────────────
    {
        "type": "TYPING_INDICATOR",
        "delay_before": 0.8,
        "delay_after": 2.0,
        "text": "",
    },
    {
        "type": "POST_AS_COMPLETED_CARD",
        "text": (
            "*AXIOMSPHERE ASSISTANT — AIMS Framework Build*\n\n"
            "Drafting functional framework across *Stage 03 — Functional Framework*.\n\n"
            "✦ *Processes registered:* 14 core processes mapped to ISO 55001 §8\n"
            "✦ *Interfaces identified:* Engineering ↔ Operations · Operations ↔ Maintenance · "
            "Maintenance ↔ HSE\n"
            "✦ *Gap scan:* 3 interface alignment items flagged for synchronisation\n\n"
            "All outputs are draft recommendations. Qualified human review required "
            "before operational use."
        ),
        "delay_before": 0.3,
        "delay_after": 1.5,
    },
    # ── Scene 3: Second engineer input ────────────────────────────────────────
    {
        "type": "ENGINEER_PROGRESSIVE_TYPE",
        "text": "PROJECT INPUT: Assess impact of revised flare system specification on AIMS framework.",
        "delay_before": 1.0,
        "delay_after": 1.2,
        "chars_per_sec": 3,
    },
    {
        "type": "TYPING_INDICATOR",
        "delay_before": 0.5,
        "delay_after": 2.2,
        "text": "",
    },
    {
        "type": "POST_AS_COMPLETED_CARD",
        "text": (
            "*AXIOMSPHERE ASSISTANT — Change Impact Assessment*\n\n"
            "Tracing downstream impact of *Flare System Specification Revision v3*.\n\n"
            "✦ *Directly affected work products:* 7\n"
            "  — Maintenance Strategy · Inspection Programme · Competence Framework\n"
            "  — Operating Philosophy · Risk Register · Procedure Index · Training Records\n\n"
            "✦ *Interface touchpoints requiring re-alignment:* 4\n"
            "✦ *Estimated review effort:* 2.1 workflow hours (planning estimate only)\n\n"
            "_Change propagation traced before downstream impact compounds._\n"
            "All outputs require qualified human review before operational action."
        ),
        "delay_before": 0.3,
        "delay_after": 1.5,
    },
    # ── Scene 4: Knowledge retention ──────────────────────────────────────────
    {
        "type": "TYPING_INDICATOR",
        "delay_before": 0.8,
        "delay_after": 1.8,
        "text": "",
    },
    {
        "type": "POST_AS_COMPLETED_CARD",
        "text": (
            "*AXIOMSPHERE ASSISTANT — Knowledge Retention*\n\n"
            "Validated outputs captured in the AIMS knowledge layer.\n\n"
            "✦ *Evidence records logged:* 11\n"
            "✦ *Traceable to:* ISO 55001 §6.1 · §7.2 · §8.1 · §8.2\n"
            "✦ *Continuous learning update:* framework consistency model updated with "
            "this change-impact trace\n\n"
            "Closed loop: Build → Synchronise → Assess Change → Retain Knowledge.\n"
            "Next cycle begins on next scope event."
        ),
        "delay_before": 0.3,
        "delay_after": 1.5,
    },
    # ── Scene 5: Completion ────────────────────────────────────────────────────
    {
        "type": "POST_AS_COMPLETED_CARD",
        "text": (
            "*AXIOMSPHERE ASSISTANT — Walkthrough Complete*\n\n"
            "This demonstration showed:\n\n"
            "① AIMS scope definition and work-product registration\n"
            "② Framework build across ISO 55001 / ISO 55002 lifecycle stages\n"
            "③ Change-impact tracing before downstream propagation\n"
            "④ Closed-loop knowledge retention\n\n"
            "_Scenario: North Shore Gas Processing Development, Gulf Region_\n"
            "_All content is fictional. No external calls were made. "
            "No operational data was written._\n\n"
            "For information: hello@axiomsphereai.com"
        ),
        "delay_before": 0.5,
        "delay_after": 0,
    },
]

# ── Utilities ──────────────────────────────────────────────────────────────────

async def _interruptible_sleep(seconds: float, stop: asyncio.Event) -> bool:
    """Sleep for `seconds`; return True if interrupted by stop event."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
        return True
    except asyncio.TimeoutError:
        return False


async def _type_progressively(
    text: str,
    chat_id: int,
    bot,
    chars_per_sec: float,
    stop: asyncio.Event,
) -> Optional[int]:
    """Send a message that appears to be typed character-by-character (3 chars/sec).
    Returns the message_id of the final message, or None if cancelled."""
    chunk = ""
    msg = None
    delay = 1.0 / chars_per_sec

    for char in text:
        if stop.is_set():
            return None
        chunk += char
        try:
            if msg is None:
                msg = await bot.send_message(chat_id=chat_id, text=chunk)
            else:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg.message_id,
                    text=chunk,
                )
        except Exception:
            pass
        if await _interruptible_sleep(delay, stop):
            return None

    return msg.message_id if msg else None


# ── Playback engine ────────────────────────────────────────────────────────────

async def _run_demo(session: DemoSession, bot) -> None:
    chat_id = session.chat_id
    stop = session.stop_event

    try:
        for step in _SCRIPT:
            if stop.is_set():
                break

            delay_before = step.get("delay_before", 0)
            if delay_before and await _interruptible_sleep(delay_before, stop):
                break

            if stop.is_set():
                break

            stype = step["type"]

            if stype == "ENGINEER_PROGRESSIVE_TYPE":
                await _type_progressively(
                    step["text"], chat_id, bot,
                    step.get("chars_per_sec", 3), stop,
                )

            elif stype == "TYPING_INDICATOR":
                try:
                    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                except Exception:
                    pass

            elif stype == "POST_AS_COMPLETED_CARD":
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=step["text"],
                        parse_mode="Markdown",
                    )
                except Exception as exc:
                    log.warning("demo card send failed: %s", exc)

            elif stype == "PAUSE":
                pass  # handled by delay_before / delay_after

            delay_after = step.get("delay_after", 0)
            if delay_after and await _interruptible_sleep(delay_after, stop):
                break

        if stop.is_set():
            session.state = DemoState.CANCELLED
        else:
            session.state = DemoState.COMPLETED
            _last_completed[chat_id] = time.monotonic()

    except Exception as exc:
        log.exception("demo playback error in chat %s: %s", chat_id, exc)
        session.state = DemoState.FAILED
        try:
            await bot.send_message(
                chat_id=chat_id,
                text="Demonstration stopped due to an internal error.",
            )
        except Exception:
            pass


# ── Command handlers ───────────────────────────────────────────────────────────

async def cmd_demo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    chat_id = update.effective_chat.id

    # Delete the incoming /demo command message immediately
    try:
        await update.message.delete()
    except Exception:
        pass

    # Enforce cooldown
    last = _last_completed.get(chat_id)
    if last is not None:
        elapsed = time.monotonic() - last
        if elapsed < COOLDOWN_SECONDS:
            remaining = int(COOLDOWN_SECONDS - elapsed)
            await ctx.bot.send_message(
                chat_id=chat_id,
                text=f"Please wait {remaining}s before starting another demonstration.",
            )
            return

    # Cancel any existing session
    existing = _sessions.get(chat_id)
    if existing and existing.state == DemoState.RUNNING:
        existing.stop_event.set()
        if existing.task:
            try:
                await asyncio.wait_for(existing.task, timeout=3)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

    session = DemoSession(chat_id=chat_id, state=DemoState.READY)
    _sessions[chat_id] = session

    lobby_msg = await ctx.bot.send_message(
        chat_id=chat_id,
        text=LOBBY_TEXT,
        parse_mode="Markdown",
        reply_markup=LOBBY_KEYBOARD,
    )
    session.lobby_message_id = lobby_msg.message_id


async def cmd_demo_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    chat_id = update.effective_chat.id
    session = _sessions.get(chat_id)

    if session and session.state == DemoState.RUNNING:
        session.stop_event.set()
        if session.task:
            try:
                await asyncio.wait_for(session.task, timeout=3)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        await update.message.reply_text("Demonstration stopped.")
    else:
        await update.message.reply_text("No demonstration is currently running.")


async def cmd_demo_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(DEMO_HELP_TEXT, parse_mode="Markdown")


# ── Callback handlers ──────────────────────────────────────────────────────────

async def demo_start_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    chat_id = update.effective_chat.id
    session = _sessions.get(chat_id)

    if session is None or session.state not in (DemoState.READY, DemoState.IDLE):
        await query.answer("No lobby active. Send /demo to begin.", show_alert=True)
        return

    # Remove lobby buttons
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    session.state = DemoState.RUNNING
    session.stop_event.clear()
    session.task = asyncio.create_task(_run_demo(session, ctx.bot))


async def demo_cancel_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    chat_id = update.effective_chat.id
    session = _sessions.get(chat_id)

    if session and session.state == DemoState.RUNNING:
        session.stop_event.set()
        if session.task:
            try:
                await asyncio.wait_for(session.task, timeout=3)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        try:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(
                query.message.text + "\n\n_Demonstration cancelled._",
                parse_mode="Markdown",
            )
        except Exception:
            pass
    elif session and session.state in (DemoState.READY, DemoState.IDLE):
        session.state = DemoState.CANCELLED
        try:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(
                query.message.text + "\n\n_Demonstration cancelled._",
                parse_mode="Markdown",
            )
        except Exception:
            pass
    else:
        await query.answer("Nothing to cancel.", show_alert=True)


async def demo_about_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    chat_id = update.effective_chat.id
    await ctx.bot.send_message(
        chat_id=chat_id,
        text=ABOUT_TEXT,
        parse_mode="Markdown",
    )
