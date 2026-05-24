"""
Recordable scripted Telegram AIMS walkthrough demo for AxiOMSphere bot.
Scenario: OilGasExploration — Maintenance Management Philosophy.

Safety constraints:
  - Zero LLM / model / evaluator calls
  - Zero external service calls
  - Zero operational / training / evidence writes
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
    awaiting_manual_input: bool = False
    manual_input_event: asyncio.Event = field(default_factory=asyncio.Event)
    started_at: float = field(default_factory=time.monotonic)


_sessions: dict[int, DemoSession] = {}
_last_completed: dict[int, float] = {}

COOLDOWN_SECONDS = 60

# ── Static content ─────────────────────────────────────────────────────────────

LOBBY_TEXT = (
    "*AxiOMSphere — AIMS Platform Demo*\n\n"
    "This demonstration walks through a live scenario:\n"
    "_Creating a Maintenance Management Philosophy for a new gas processing project._\n\n"
    "_Scripted fictional demonstration. OilGasExploration is a fictional project name. "
    "No real customer or project data is used._\n\n"
    "Press *▶ START AXI* to begin."
)

LOBBY_KEYBOARD = InlineKeyboardMarkup([[
    InlineKeyboardButton("▶ START AXI", callback_data="demo_start"),
    InlineKeyboardButton("About",       callback_data="demo_about"),
    InlineKeyboardButton("■ CANCEL",    callback_data="demo_cancel"),
]])

ABOUT_TEXT = (
    "*About this demonstration*\n\n"
    "AxiOMSphere coordinates specialised AI agents on private GPU infrastructure "
    "to build, synchronise and continuously improve the AIMS operating framework "
    "for industrial projects, structured in accordance with ISO 55001 / ISO 55002.\n\n"
    "All outputs are recommendations. Qualified human review is required before "
    "operational use."
)

DEMO_HELP_TEXT = (
    "*Demo commands*\n\n"
    "/demo — launch demonstration\n"
    "/demo\\_stop — stop a running demonstration\n"
    "/demo\\_help — show this message"
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _kb(*rows):
    """Build InlineKeyboardMarkup from row lists of (label, callback_data) tuples."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=cb) for label, cb in row]
        for row in rows
    ])


async def _interruptible_sleep(seconds: float, stop: asyncio.Event) -> bool:
    """Sleep for `seconds`; return True if interrupted by stop event."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
        return True
    except asyncio.TimeoutError:
        return False


async def _send_typing(bot, chat_id: int, stop: asyncio.Event, duration: float = 1.2) -> bool:
    """Send typing indicator, then sleep. Returns True if interrupted."""
    try:
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception:
        pass
    return await _interruptible_sleep(duration, stop)


def is_demo_active(chat_id: int) -> bool:
    """Return True if chat_id currently has a live demo session."""
    return chat_id in _sessions


def handle_demo_message(chat_id: int, text: str) -> bool:
    """
    Offer an incoming text message to the demo state machine.

    Returns True if the message is non-empty and the demo step has been
    advanced.  Returns False if no demo is awaiting input, or if text is
    empty/whitespace-only (caller sends a safe prompt).
    """
    session = _sessions.get(chat_id)
    if session is None or not session.awaiting_manual_input:
        return False
    if not text.strip():
        return False
    session.manual_input_event.set()
    return True


async def _wait_for_manual_input(session: DemoSession) -> bool:
    """Wait for manual founder input or stop signal. Returns True if stopped/cancelled."""
    session.manual_input_event.clear()
    done, _ = await asyncio.wait(
        [
            asyncio.ensure_future(session.stop_event.wait()),
            asyncio.ensure_future(session.manual_input_event.wait()),
        ],
        return_when=asyncio.FIRST_COMPLETED,
    )
    return session.stop_event.is_set()


# ── Script ─────────────────────────────────────────────────────────────────────
#
# Step types:
#   BOT_MESSAGE              — send Markdown message from the bot
#   BOT_MESSAGE_WITH_BUTTONS — send Markdown message + inline keyboard; stores msg_id in refs[ref]
#   BOT_EDIT_BUTTONS         — edit refs[ref] with updated text / buttons
#   CUSTOMER_WORD_TYPE       — pause and wait for founder to paste the scripted answer manually
#                              (no button; answer checked with whitespace normalisation)
#   TYPING_INDICATOR         — send typing action then pause
#
# delay_before / delay_after: float seconds (0 = skip)

_SCRIPT: list[dict] = [

    # ── Greeting ───────────────────────────────────────────────────────────────
    {
        "type": "BOT_MESSAGE",
        "text": "Hi, What is your name?",
        "delay_after": 0.6,
    },
    {
        "type": "CUSTOMER_WORD_TYPE",
        "text": "Evgeny",
        "delay_after": 0.8,
    },
    {
        "type": "TYPING_INDICATOR",
        "duration": 1.2,
        "delay_after": 0.2,
    },
    {
        "type": "BOT_MESSAGE",
        "text": (
            "Hi Evgeny, I am ready — starting from a new project description?\n\n"
            "Project Name —\n"
            "Country Location —\n"
            "Period of Area License —\n"
            "Date of Start —"
        ),
        "delay_after": 0.6,
    },
    {
        "type": "CUSTOMER_WORD_TYPE",
        "text": "OilGasExploration\nGulf Region — fictional scenario\n15 years\n01.01.2028",
        "delay_after": 0.8,
    },

    # ── Task definition ────────────────────────────────────────────────────────
    {
        "type": "TYPING_INDICATOR",
        "duration": 1.0,
        "delay_after": 0.2,
    },
    {
        "type": "BOT_MESSAGE",
        "text": "Define AIMS scope — tell me your task:",
        "delay_after": 0.6,
    },
    {
        "type": "CUSTOMER_WORD_TYPE",
        "text": "Axi, Create Maintenance Management Philosophy.",
        "delay_after": 0.8,
    },

    # ── Document / questions choice ────────────────────────────────────────────
    {
        "type": "TYPING_INDICATOR",
        "duration": 1.4,
        "delay_after": 0.2,
    },
    {
        "type": "BOT_MESSAGE_WITH_BUTTONS",
        "text": (
            "Please upload the Technical Economical Justification "
            "or any licence approval documents from the package…\n\n"
            "Tell me and I'll upload — or reply to my questions:"
        ),
        "buttons": [[("📎 Upload", "demo_noop"), ("💬 Questions reply", "demo_noop")]],
        "ref": "upload_msg",
        "delay_after": 2.0,
    },
    {
        "type": "BOT_EDIT_BUTTONS",
        "ref": "upload_msg",
        "text": (
            "Please upload the Technical Economical Justification "
            "or any licence approval documents from the package…\n\n"
            "Tell me and I'll upload — or reply to my questions:\n\n"
            "✅ *Questions reply*"
        ),
        "buttons": None,
        "delay_after": 0.8,
    },

    # ── 1. Business & Strategic Context — Q1.1 ────────────────────────────────
    {
        "type": "TYPING_INDICATOR",
        "duration": 1.2,
        "delay_after": 0.2,
    },
    {
        "type": "BOT_MESSAGE",
        "text": (
            "*Business & Strategic Context*\n\n"
            "1.1  What are the organization's overall business objectives "
            "and drivers for this project?"
        ),
        "delay_after": 0.6,
    },
    {
        "type": "CUSTOMER_WORD_TYPE",
        "text": (
            "Develop a gas processing facility concept with a safe, reliable and "
            "maintainable operating organisation before full-field investment approval. "
            "Key drivers include maximising long-term asset value, ensuring safe and "
            "reliable operations, and establishing robust asset integrity from day one."
        ),
        "delay_after": 0.8,
    },

    # ── Q1.2 with value buttons ────────────────────────────────────────────────
    {
        "type": "TYPING_INDICATOR",
        "duration": 1.0,
        "delay_after": 0.2,
    },
    {
        "type": "BOT_MESSAGE_WITH_BUTTONS",
        "text": (
            "*Business & Strategic Context*\n"
            "1.1  What are the organization's overall business objectives and drivers for this project?\n"
            "1.2  What are the key value expectations from the assets "
            "(production, safety, reliability, cost)?"
        ),
        "buttons": [[
            ("Production", "demo_noop"),
            ("Safety",     "demo_noop"),
            ("Reliability","demo_noop"),
            ("Cost",       "demo_noop"),
        ]],
        "ref": "value_buttons",
        "delay_after": 1.5,
    },
    # — Production —
    {
        "type": "BOT_EDIT_BUTTONS",
        "ref": "value_buttons",
        "text": (
            "*Business & Strategic Context*\n"
            "1.2  Key value expectations:\n\n"
            "✅ Production"
        ),
        "buttons": [[
            ("Safety",     "demo_noop"),
            ("Reliability","demo_noop"),
            ("Cost",       "demo_noop"),
        ]],
        "delay_after": 0.3,
    },
    {
        "type": "CUSTOMER_WORD_TYPE",
        "text": "Production: Achieve plateau production of ~X MMSCFD with minimal unplanned downtime.",
        "delay_after": 0.8,
    },
    # — Safety —
    {
        "type": "TYPING_INDICATOR",
        "duration": 0.5,
        "delay_after": 0.1,
    },
    {
        "type": "BOT_EDIT_BUTTONS",
        "ref": "value_buttons",
        "text": (
            "*Business & Strategic Context*\n"
            "1.2  Key value expectations:\n\n"
            "✅ Production\n✅ Safety"
        ),
        "buttons": [[
            ("Reliability","demo_noop"),
            ("Cost",       "demo_noop"),
        ]],
        "delay_after": 0.3,
    },
    {
        "type": "CUSTOMER_WORD_TYPE",
        "text": "Safety: Zero fatalities and no major process safety events (Tier 1/2).",
        "delay_after": 0.8,
    },
    # — Reliability —
    {
        "type": "TYPING_INDICATOR",
        "duration": 0.5,
        "delay_after": 0.1,
    },
    {
        "type": "BOT_EDIT_BUTTONS",
        "ref": "value_buttons",
        "text": (
            "*Business & Strategic Context*\n"
            "1.2  Key value expectations:\n\n"
            "✅ Production\n✅ Safety\n✅ Reliability"
        ),
        "buttons": [[("Cost", "demo_noop")]],
        "delay_after": 0.3,
    },
    {
        "type": "CUSTOMER_WORD_TYPE",
        "text": "Reliability: Target >98% plant availability.",
        "delay_after": 0.8,
    },
    # — Cost —
    {
        "type": "TYPING_INDICATOR",
        "duration": 0.5,
        "delay_after": 0.1,
    },
    {
        "type": "BOT_EDIT_BUTTONS",
        "ref": "value_buttons",
        "text": (
            "*Business & Strategic Context*\n"
            "1.2  Key value expectations:\n\n"
            "✅ Production\n✅ Safety\n✅ Reliability\n✅ Cost"
        ),
        "buttons": None,
        "delay_after": 0.3,
    },
    {
        "type": "CUSTOMER_WORD_TYPE",
        "text": (
            "Cost: Optimize lifecycle cost (CAPEX + OPEX) "
            "while maintaining integrity and compliance."
        ),
        "delay_after": 0.8,
    },

    # ── Q1.3 ──────────────────────────────────────────────────────────────────
    {
        "type": "TYPING_INDICATOR",
        "duration": 1.0,
        "delay_after": 0.2,
    },
    {
        "type": "BOT_MESSAGE",
        "text": "1.3  What are the critical success factors for the project?",
        "delay_after": 0.6,
    },
    {
        "type": "CUSTOMER_WORD_TYPE",
        "text": (
            "Robust design aligned with operating conditions (high temperature, corrosive environment).\n"
            "Effective commissioning and startup with minimal defects.\n"
            "Strong asset integrity and maintenance strategy from day one.\n"
            "Skilled workforce and clear accountability structure.\n"
            "Integration of digital systems (EAM/CMMS) for data-driven decision making."
        ),
        "delay_after": 0.8,
    },

    # ── 2. Scope of Assets — Q2.1 ─────────────────────────────────────────────
    {
        "type": "TYPING_INDICATOR",
        "duration": 1.2,
        "delay_after": 0.2,
    },
    {
        "type": "BOT_MESSAGE",
        "text": (
            "*2.  Scope of Assets*\n\n"
            "2.1  What assets are included in the scope of the "
            "Asset Integrity Management system?"
        ),
        "delay_after": 0.6,
    },
    {
        "type": "CUSTOMER_WORD_TYPE",
        "text": (
            "Process equipment: separators, compressors, heat exchangers, pipelines.\n"
            "Static equipment: pressure vessels, tanks, piping systems.\n"
            "Rotating equipment: gas turbines, pumps, compressors.\n"
            "Safety systems: ESD, fire & gas detection, relief systems.\n"
            "Utilities: power generation, water systems, instrument air.\n"
            "Supporting infrastructure: control systems, buildings, export pipelines."
        ),
        "delay_after": 0.8,
    },

    # ── Q2.2 ──────────────────────────────────────────────────────────────────
    {
        "type": "TYPING_INDICATOR",
        "duration": 1.0,
        "delay_after": 0.2,
    },
    {
        "type": "BOT_MESSAGE",
        "text": (
            "2.2  What is the lifecycle stage of the assets "
            "(design, construction, commissioning, operation)?"
        ),
        "delay_after": 0.6,
    },
    {
        "type": "CUSTOMER_WORD_TYPE",
        "text": (
            "The project is currently in late construction and pre-commissioning phase. "
            "Asset Integrity Management requirements are being embedded to ensure smooth "
            "transition into operation. "
            "Lifecycle approach covers design → construction → commissioning → "
            "operation → eventual decommissioning."
        ),
        "delay_after": 0.8,
    },

    # ── Q2.3 ──────────────────────────────────────────────────────────────────
    {
        "type": "TYPING_INDICATOR",
        "duration": 1.0,
        "delay_after": 0.2,
    },
    {
        "type": "BOT_MESSAGE",
        "text": "2.3  What are the boundaries and interfaces with other systems or facilities?",
        "delay_after": 0.6,
    },
    {
        "type": "CUSTOMER_WORD_TYPE",
        "text": (
            "Upstream interface: wellheads and gathering system supplying raw gas.\n"
            "Downstream interface: LNG plant/export pipeline network.\n"
            "Utilities interface: shared power grid and water supply systems.\n"
            "External stakeholders: contractors, regulators, and joint venture partners."
        ),
        "delay_after": 0.8,
    },

    # ── 3. Risk & Criticality — Q3.1 ──────────────────────────────────────────
    {
        "type": "TYPING_INDICATOR",
        "duration": 1.2,
        "delay_after": 0.2,
    },
    {
        "type": "BOT_MESSAGE",
        "text": (
            "*3.  Risk & Criticality*\n\n"
            "3.1  What are the major risks associated with asset failure "
            "(HSE, financial, operational)?"
        ),
        "delay_after": 0.6,
    },
    {
        "type": "CUSTOMER_WORD_TYPE",
        "text": (
            "HSE: hydrocarbon release, fire/explosion, toxic gas exposure (H₂S).\n"
            "Financial: production loss, contractual penalties, repair/replacement costs.\n"
            "Operational: plant shutdown, reduced throughput, equipment degradation.\n"
            "Reputational: impact on national energy supply commitments."
        ),
        "delay_after": 0.8,
    },

    # ── Q3.2 ──────────────────────────────────────────────────────────────────
    {
        "type": "TYPING_INDICATOR",
        "duration": 1.0,
        "delay_after": 0.2,
    },
    {
        "type": "BOT_MESSAGE",
        "text": "3.2  Which assets are considered critical and why?",
        "delay_after": 0.6,
    },
    {
        "type": "CUSTOMER_WORD_TYPE",
        "text": (
            "High-pressure gas pipelines → risk of major release and explosion.\n"
            "Compressors and turbines → directly impact production continuity.\n"
            "Pressure vessels and separators → contain hazardous hydrocarbons.\n"
            "Safety systems (ESD, F&G) → essential for risk mitigation and emergency response.\n"
            "Critical assets are defined based on the consequence of failure and likelihood."
        ),
        "delay_after": 0.8,
    },

    # ── Q3.3 ──────────────────────────────────────────────────────────────────
    {
        "type": "TYPING_INDICATOR",
        "duration": 1.0,
        "delay_after": 0.2,
    },
    {
        "type": "BOT_MESSAGE",
        "text": "3.3  What risk assessment methodologies will be applied?",
        "delay_after": 0.6,
    },
    {
        "type": "CUSTOMER_WORD_TYPE",
        "text": (
            "HAZID / HAZOP for design and process hazard identification.\n"
            "RBI (Risk-Based Inspection) for static equipment.\n"
            "RCM (Reliability-Centered Maintenance) for maintenance strategy.\n"
            "SIL assessment for safety instrumented systems.\n"
            "Bow-Tie analysis for major accident hazards.\n"
            "Risk matrix aligned with corporate and regulatory requirements."
        ),
        "delay_after": 1.0,
    },

    # ── Document generation & approval ────────────────────────────────────────
    {
        "type": "TYPING_INDICATOR",
        "duration": 2.5,
        "delay_after": 0.4,
    },
    {
        "type": "BOT_MESSAGE_WITH_BUTTONS",
        "text": (
            "📄 *Please approve \"AIMS Philosophy\"*\n\n"
            "_[Generating: Maintenance\\_Management\\_Philosophy.docx …]_\n\n"
            "Review the draft and confirm:"
        ),
        "buttons": [[("✅ Approval", "demo_noop"), ("💬 Comment", "demo_noop")]],
        "ref": "approval_msg",
        "delay_after": 2.5,
    },
    {
        "type": "BOT_EDIT_BUTTONS",
        "ref": "approval_msg",
        "text": (
            "📄 *AIMS Philosophy — Approved*\n\n"
            "_Maintenance\\_Management\\_Philosophy.docx registered._"
        ),
        "buttons": None,
        "delay_after": 1.0,
    },

    # ── Continue dialogue offer ────────────────────────────────────────────────
    {
        "type": "TYPING_INDICATOR",
        "duration": 1.0,
        "delay_after": 0.2,
    },
    {
        "type": "BOT_MESSAGE_WITH_BUTTONS",
        "text": (
            "We need to go through details in AIMS Philosophy.\n"
            "I will initiate the dialogue with related questions for your reply.\n\n"
            "*Business & Strategic Context*\n"
            "1.1  …\n\n"
            "Would you like to continue?\n\n"
            "I also support:\n"
            "Org Chart · Milestone Plan · Procedures · Strategy · Guidelines · Instructions"
        ),
        "buttons": [[
            ("Y — right now",           "demo_noop"),
            ("N — pause, next task",    "demo_noop"),
        ]],
        "ref": "continue_msg",
        "delay_after": 1.5,
    },
    {
        "type": "BOT_MESSAGE",
        "text": (
            "_Scripted fictional demonstration. OilGasExploration is a fictional project name. "
            "No real customer or project data is used._"
        ),
        "delay_after": 0,
    },
]

# ── Playback engine ────────────────────────────────────────────────────────────

async def _run_demo(session: DemoSession, bot) -> None:
    chat_id = session.chat_id
    stop = session.stop_event
    refs: dict[str, int] = {}   # ref_name → message_id

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

            if stype == "BOT_MESSAGE":
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=step["text"],
                        parse_mode="Markdown",
                    )
                except Exception as exc:
                    log.warning("demo BOT_MESSAGE failed: %s", exc)

            elif stype == "BOT_MESSAGE_WITH_BUTTONS":
                buttons = step.get("buttons")
                keyboard = _kb(*buttons) if buttons else None
                try:
                    msg = await bot.send_message(
                        chat_id=chat_id,
                        text=step["text"],
                        parse_mode="Markdown",
                        reply_markup=keyboard,
                    )
                    ref = step.get("ref")
                    if ref:
                        refs[ref] = msg.message_id
                except Exception as exc:
                    log.warning("demo BOT_MESSAGE_WITH_BUTTONS failed: %s", exc)

            elif stype == "BOT_EDIT_BUTTONS":
                ref = step.get("ref")
                msg_id = refs.get(ref) if ref else None
                if msg_id:
                    buttons = step.get("buttons")
                    keyboard = _kb(*buttons) if buttons else None
                    try:
                        await bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=msg_id,
                            text=step["text"],
                            parse_mode="Markdown",
                            reply_markup=keyboard,
                        )
                    except Exception as exc:
                        log.warning("demo BOT_EDIT_BUTTONS failed: %s", exc)

            elif stype == "CUSTOMER_WORD_TYPE":
                # Pause and wait for founder to send any non-empty text message.
                session.awaiting_manual_input = True
                interrupted = await _wait_for_manual_input(session)
                session.awaiting_manual_input = False
                if interrupted:
                    break

            elif stype == "TYPING_INDICATOR":
                duration = step.get("duration", 1.2)
                if await _send_typing(bot, chat_id, stop, duration):
                    break

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

    try:
        await update.message.delete()
    except Exception:
        pass

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

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    if update.effective_user:
        session.initiating_user_id = update.effective_user.id
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
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text=ABOUT_TEXT,
        parse_mode="Markdown",
    )


async def demo_noop_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Acknowledge taps on scripted demo buttons silently."""
    query = update.callback_query
    if query:
        await query.answer()
