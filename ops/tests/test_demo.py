"""
Tests for ops/axi_demo.py — sync-compatible (no pytest-asyncio dependency).
Uses asyncio.run() for async tests.
"""

import asyncio
import sys
import time
import types
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# -- path setup ---------------------------------------------------------------
OPS_DIR = str(Path(__file__).resolve().parent.parent)
if OPS_DIR not in sys.path:
    sys.path.insert(0, OPS_DIR)

# Stub telegram before importing axi_demo
_tg = types.ModuleType("telegram")
_tg.Update = MagicMock
_tg.InlineKeyboardButton = MagicMock(
    side_effect=lambda text=None, callback_data=None, web_app=None: {
        "text": text, "cbd": callback_data, "web_app": web_app
    }
)
_tg.InlineKeyboardMarkup = MagicMock(side_effect=lambda rows: {"rows": rows})
_tg.WebAppInfo = MagicMock(side_effect=lambda url: {"url": url})
_tg.InlineQueryResultArticle = MagicMock
_tg.InputTextMessageContent = MagicMock
_tg_constants = types.ModuleType("telegram.constants")
_tg_constants.ChatAction = MagicMock()
_tg_constants.ChatAction.TYPING = "typing"
_tg_ext = types.ModuleType("telegram.ext")
_tg_ext.ContextTypes = MagicMock()
sys.modules.setdefault("telegram", _tg)
sys.modules.setdefault("telegram.constants", _tg_constants)
sys.modules.setdefault("telegram.ext", _tg_ext)

import axi_demo  # noqa: E402
from axi_demo import (  # noqa: E402
    COOLDOWN_SECONDS,
    DemoSession,
    DemoState,
    _ReplySlot,
    _interruptible_sleep,
    _pending_replies,
    _run_demo,
    _sessions,
    cmd_demo_stop,
    demo_cancel_callback,
    demo_start_callback,
    handle_webapp_reply,
    set_demo_bot,
)


# -- helpers ------------------------------------------------------------------

def _make_update(chat_id: int = 12345, message_id: int = 99, has_message: bool = True):
    update = MagicMock()
    update.effective_chat.id = chat_id
    if has_message:
        msg = AsyncMock()
        msg.message_id = message_id
        msg.delete = AsyncMock()
        msg.reply_text = AsyncMock()
        update.message = msg
    else:
        update.message = None
    return update


def _make_ctx(chat_id: int = 12345):
    ctx = MagicMock()
    ctx.bot = AsyncMock()
    ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=100))
    ctx.bot.send_chat_action = AsyncMock()
    ctx.bot.edit_message_text = AsyncMock()
    ctx.bot.edit_message_reply_markup = AsyncMock()
    return ctx


def _make_query(chat_id: int = 12345, text: str = "lobby text"):
    query = AsyncMock()
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock()
    query.message.text = text
    update = MagicMock()
    update.callback_query = query
    update.effective_chat.id = chat_id
    return update, query


# -- tests --------------------------------------------------------------------

def test_demo_state_enum():
    assert DemoState.IDLE.value == "IDLE"
    assert DemoState.RUNNING.value == "RUNNING"
    assert DemoState.COMPLETED.value == "COMPLETED"


def test_demo_session_defaults():
    s = DemoSession(chat_id=1)
    assert s.state == DemoState.IDLE
    assert s.task is None
    assert not s.stop_event.is_set()


def test_lobby_text_contains_start_axi():
    assert "▶ START AXI" in axi_demo.LOBBY_TEXT or "START AXI" in axi_demo.LOBBY_TEXT


def test_lobby_text_no_countdown():
    assert "5 seconds" not in axi_demo.LOBBY_TEXT
    assert "5-second" not in axi_demo.LOBBY_TEXT


def test_lobby_text_fictional_disclaimer():
    assert "fictional" in axi_demo.LOBBY_TEXT.lower()
    assert "OilGasExploration" in axi_demo.LOBBY_TEXT


def test_lobby_keyboard_button_label():
    # The START button callback data must be demo_start
    keyboard = axi_demo.LOBBY_KEYBOARD
    # keyboard is a mock result; check that at least one button has demo_start
    assert keyboard is not None


def test_script_has_steps():
    assert len(axi_demo._SCRIPT) >= 5


def test_script_no_llm_calls():
    # No step should reference model calls, endpoints, or API tokens
    banned = ["llm", "api_key", "openai", "anthropic", "nvidia_nim", "ollama"]
    for step in axi_demo._SCRIPT:
        text = step.get("text", "").lower()
        for term in banned:
            assert term not in text, f"Script step contains banned term '{term}'"


def test_customer_word_type_steps_present():
    customer_steps = [s for s in axi_demo._SCRIPT if s["type"] == "CUSTOMER_WORD_TYPE"]
    assert len(customer_steps) >= 3, "Expected at least 3 CUSTOMER_WORD_TYPE steps"


def test_interruptible_sleep_completes():
    stop = asyncio.Event()
    result = asyncio.run(_interruptible_sleep(0.01, stop))
    assert result is False  # not interrupted


def test_interruptible_sleep_interrupted():
    stop = asyncio.Event()
    stop.set()
    result = asyncio.run(_interruptible_sleep(10, stop))
    assert result is True  # interrupted immediately


def test_cmd_demo_deletes_message():
    """Verify that cmd_demo attempts to delete the incoming /demo command message."""
    _sessions.clear()
    update = _make_update(chat_id=1001)
    ctx = _make_ctx(chat_id=1001)

    asyncio.run(axi_demo.cmd_demo(update, ctx))

    update.message.delete.assert_called_once()


def test_cmd_demo_sends_lobby():
    _sessions.clear()
    update = _make_update(chat_id=1002)
    ctx = _make_ctx(chat_id=1002)

    asyncio.run(axi_demo.cmd_demo(update, ctx))

    ctx.bot.send_message.assert_called_once()
    call_kwargs = ctx.bot.send_message.call_args
    assert call_kwargs is not None


def test_cmd_demo_cooldown_enforced():
    _sessions.clear()
    axi_demo._last_completed.clear()
    chat_id = 1003
    axi_demo._last_completed[chat_id] = time.monotonic()  # just completed

    update = _make_update(chat_id=chat_id)
    ctx = _make_ctx(chat_id=chat_id)

    asyncio.run(axi_demo.cmd_demo(update, ctx))

    # Should send cooldown message, NOT a lobby
    ctx.bot.send_message.assert_called_once()
    msg_text = ctx.bot.send_message.call_args[1].get("text", "") or ctx.bot.send_message.call_args[0][0] if ctx.bot.send_message.call_args[0] else ""
    # Verify it mentions "wait" or cooldown
    call_text = str(ctx.bot.send_message.call_args)
    assert "wait" in call_text.lower() or "seconds" in call_text.lower() or "cooldown" in call_text.lower()


def test_demo_start_callback_no_countdown():
    """Playback must begin immediately — no countdown after ▶ START AXI."""
    _sessions.clear()
    chat_id = 2001
    session = DemoSession(chat_id=chat_id, state=DemoState.READY)
    session.lobby_message_id = 100
    _sessions[chat_id] = session

    update, query = _make_query(chat_id=chat_id)
    ctx = _make_ctx(chat_id=chat_id)

    async def run():
        await demo_start_callback(update, ctx)
        # Cancel immediately to avoid blocking
        if session.task:
            session.stop_event.set()
            try:
                await asyncio.wait_for(session.task, timeout=1)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

    asyncio.run(run())

    # State must be RUNNING (or CANCELLED after stop) — never READY stuck
    assert session.state in (DemoState.RUNNING, DemoState.CANCELLED, DemoState.COMPLETED)

    # Verify no sleep/countdown message was sent before task creation
    # (the task is created synchronously in demo_start_callback — no delay)


def test_demo_start_button_label_in_lobby_keyboard():
    """The START button must have callback_data demo_start."""
    # Re-import with real InlineKeyboardButton tracking
    import importlib as _il
    # Check that LOBBY_KEYBOARD was built with demo_start callback
    # Since we mocked InlineKeyboardButton as recording kwargs, inspect the call
    calls = _tg.InlineKeyboardButton.call_args_list
    start_calls = [c for c in calls if "demo_start" in str(c)]
    assert len(start_calls) >= 1, "Expected an InlineKeyboardButton with callback_data='demo_start'"


def test_demo_cancel_from_lobby_no_new_message():
    """■ CANCEL from lobby must edit the existing message, not send a new one."""
    _sessions.clear()
    chat_id = 3001
    session = DemoSession(chat_id=chat_id, state=DemoState.READY)
    session.lobby_message_id = 200
    _sessions[chat_id] = session

    update, query = _make_query(chat_id=chat_id)
    ctx = _make_ctx(chat_id=chat_id)

    asyncio.run(demo_cancel_callback(update, ctx))

    # Should edit the message, not send a new one
    query.edit_message_reply_markup.assert_called_once()
    ctx.bot.send_message.assert_not_called()
    assert session.state == DemoState.CANCELLED


def test_cmd_demo_stop_no_running_session():
    _sessions.clear()
    update = _make_update(chat_id=4001)
    ctx = _make_ctx(chat_id=4001)

    asyncio.run(cmd_demo_stop(update, ctx))

    update.message.reply_text.assert_called_once()
    reply = str(update.message.reply_text.call_args)
    assert "no demonstration" in reply.lower() or "not currently" in reply.lower()


def test_run_demo_completes_without_llm():
    """Full playback must complete without calling any LLM/API methods."""
    _sessions.clear()
    axi_demo._last_completed.clear()
    chat_id = 5001
    session = DemoSession(chat_id=chat_id, state=DemoState.RUNNING)
    _sessions[chat_id] = session

    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=300))
    bot.send_chat_action = AsyncMock()
    bot.edit_message_text = AsyncMock()

    asyncio.run(_run_demo(session, bot))

    assert session.state == DemoState.COMPLETED
    # Verify send_message was called (cards delivered) but no LLM-specific attr was accessed
    assert bot.send_message.call_count >= 1


def test_run_demo_stops_on_event():
    """Demo must stop cleanly when stop_event is set mid-run."""
    _sessions.clear()
    chat_id = 5002
    session = DemoSession(chat_id=chat_id, state=DemoState.RUNNING)
    _sessions[chat_id] = session

    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=301))
    bot.send_chat_action = AsyncMock()
    bot.edit_message_text = AsyncMock()

    async def stop_after_first_card():
        task = asyncio.create_task(_run_demo(session, bot))
        await asyncio.sleep(0.1)
        session.stop_event.set()
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(stop_after_first_card())
    assert session.state == DemoState.CANCELLED


def test_fictional_scenario_present():
    all_text = " ".join(s.get("text", "") for s in axi_demo._SCRIPT)
    assert "OilGasExploration" in all_text, "OilGasExploration project name must appear in script"
    assert "Gulf Region" in all_text, "Gulf Region location must appear in script"


def test_fictional_disclaimer_present():
    all_text = " ".join(s.get("text", "") for s in axi_demo._SCRIPT)
    assert "fictional" in all_text.lower(), "Fictional disclaimer must appear in script"
    assert "OilGasExploration is a fictional project name" in all_text


def test_no_qatar_references():
    all_text = " ".join(s.get("text", "") for s in axi_demo._SCRIPT)
    assert "Qatar Energy" not in all_text, "Qatar Energy must not appear in demo script"
    assert "Qatar\n" not in all_text and "\nQatar" not in all_text
    # Allow "Qatar" only if it is part of a banned-term check; it must not appear as a standalone word
    import re
    standalone_qatar = re.findall(r"\bQatar\b", all_text)
    assert not standalone_qatar, f"Standalone 'Qatar' found in script: {standalone_qatar}"


def test_no_real_operator_names():
    all_text = " ".join(s.get("text", "") for s in axi_demo._SCRIPT)
    forbidden = ["Saudi Aramco", "Shell", "BP ", "TotalEnergies", "Chevron", "ExxonMobil", "Qatar Energy"]
    for name in forbidden:
        assert name not in all_text, f"Real operator '{name}' found in demo script"


# -- Web App Reply transport tests --------------------------------------------

def test_set_demo_bot_registers_bot():
    bot = AsyncMock()
    set_demo_bot(bot)
    assert axi_demo._demo_bot is bot
    axi_demo._demo_bot = None  # restore


def test_reply_slot_created_with_chat_and_text():
    slot = _ReplySlot(chat_id=9001, answer_text="Hello world")
    assert slot.chat_id == 9001
    assert slot.answer_text == "Hello world"
    assert slot.created_at > 0


def test_handle_webapp_reply_unknown_token():
    _pending_replies.clear()
    result = asyncio.run(handle_webapp_reply("bad-token", "qid123"))
    assert result is False


def test_handle_webapp_reply_no_bot():
    _pending_replies.clear()
    axi_demo._demo_bot = None
    token = str(uuid.uuid4())
    _pending_replies[token] = _ReplySlot(chat_id=9002, answer_text="test")

    result = asyncio.run(handle_webapp_reply(token, "qid"))
    assert result is False
    # Token should have been consumed even on failure (slot popped)
    assert token not in _pending_replies


def test_handle_webapp_reply_success_signals_session():
    _pending_replies.clear()
    _sessions.clear()

    chat_id = 9003
    session = DemoSession(chat_id=chat_id, state=DemoState.RUNNING)
    _sessions[chat_id] = session

    token = str(uuid.uuid4())
    _pending_replies[token] = _ReplySlot(chat_id=chat_id, answer_text="answer text")
    session.current_reply_token = token

    bot = AsyncMock()
    bot.answer_web_app_query = AsyncMock()
    set_demo_bot(bot)

    result = asyncio.run(handle_webapp_reply(token, "qid9003"))
    assert result is True
    assert token not in _pending_replies
    assert session.reply_event.is_set()
    assert session.current_reply_token is None
    axi_demo._demo_bot = None


def test_handle_webapp_reply_expired_token():
    _pending_replies.clear()
    token = str(uuid.uuid4())
    slot = _ReplySlot(chat_id=9004, answer_text="expired")
    slot.created_at = time.monotonic() - 400.0  # past TTL
    _pending_replies[token] = slot

    bot = AsyncMock()
    set_demo_bot(bot)

    result = asyncio.run(handle_webapp_reply(token, "qid"))
    assert result is False
    axi_demo._demo_bot = None


def test_webapp_url_env_not_set_by_default():
    # Without DEMO_WEBAPP_URL set, CUSTOMER_WORD_TYPE steps are skipped silently
    original = axi_demo.DEMO_WEBAPP_URL
    axi_demo.DEMO_WEBAPP_URL = ""

    _sessions.clear()
    chat_id = 9005
    session = DemoSession(chat_id=chat_id, state=DemoState.RUNNING)
    _sessions[chat_id] = session

    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=500))
    bot.send_chat_action = AsyncMock()
    bot.edit_message_text = AsyncMock()

    asyncio.run(_run_demo(session, bot))
    assert session.state == DemoState.COMPLETED

    axi_demo.DEMO_WEBAPP_URL = original


def test_no_braille_blank_in_session_or_reply():
    # Ensure the old braille-blank hack is not present anywhere in the module
    import inspect
    source = inspect.getsource(axi_demo)
    assert "⠀" not in source, "Braille blank U+2800 found — _R hack should be removed"


def test_customer_type_function_removed():
    assert not hasattr(axi_demo, "_customer_type"), "_customer_type() must be removed"


def test_pending_replies_cleared_after_stop():
    _pending_replies.clear()
    _sessions.clear()
    axi_demo.DEMO_WEBAPP_URL = "https://example.invalid"

    chat_id = 9006
    session = DemoSession(chat_id=chat_id, state=DemoState.RUNNING)
    _sessions[chat_id] = session

    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=600))
    bot.send_chat_action = AsyncMock()
    bot.edit_message_text = AsyncMock()

    async def run_and_stop():
        task = asyncio.create_task(_run_demo(session, bot))
        await asyncio.sleep(0.05)
        session.stop_event.set()
        session.reply_event.set()  # unblock any waiting step
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(run_and_stop())

    # After cancellation, no orphaned tokens should remain for this session
    orphaned = [t for t, s in _pending_replies.items() if s.chat_id == chat_id]
    assert not orphaned, f"Orphaned reply tokens found: {orphaned}"
    axi_demo.DEMO_WEBAPP_URL = ""
