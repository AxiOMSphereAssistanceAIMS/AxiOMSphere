"""
Tests for ops/axi_demo.py — sync-compatible (no pytest-asyncio dependency).
Uses asyncio.run() for async tests.
"""

import asyncio
import sys
import time
import types
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
    _interruptible_sleep,
    _run_demo,
    _sessions,
    cmd_demo_stop,
    demo_cancel_callback,
    demo_start_callback,
    handle_demo_message,
    is_demo_active,
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


# -- basic module tests -------------------------------------------------------

def test_demo_state_enum():
    assert DemoState.IDLE.value == "IDLE"
    assert DemoState.RUNNING.value == "RUNNING"
    assert DemoState.COMPLETED.value == "COMPLETED"


def test_demo_session_defaults():
    s = DemoSession(chat_id=1)
    assert s.state == DemoState.IDLE
    assert s.task is None
    assert not s.stop_event.is_set()
    assert s.awaiting_manual_input is False
    assert s.expected_answer == ""


def test_script_has_steps():
    assert len(axi_demo._SCRIPT) >= 5


def test_script_no_llm_calls():
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
    assert result is False


def test_interruptible_sleep_interrupted():
    stop = asyncio.Event()
    stop.set()
    result = asyncio.run(_interruptible_sleep(10, stop))
    assert result is True


# -- launch card --------------------------------------------------------------

def test_lobby_text_contains_start_axi():
    assert "▶ START AXI" in axi_demo.LOBBY_TEXT or "START AXI" in axi_demo.LOBBY_TEXT


def test_lobby_text_fictional_disclaimer():
    assert "fictional" in axi_demo.LOBBY_TEXT.lower()
    assert "OilGasExploration" in axi_demo.LOBBY_TEXT


def test_lobby_keyboard_present():
    assert axi_demo.LOBBY_KEYBOARD is not None


def test_demo_start_button_callback_data():
    calls = _tg.InlineKeyboardButton.call_args_list
    start_calls = [c for c in calls if "demo_start" in str(c)]
    assert len(start_calls) >= 1, "Expected an InlineKeyboardButton with callback_data='demo_start'"


# -- no Web App Reply button anywhere -----------------------------------------

def test_no_web_app_reply_button_in_script():
    """No CUSTOMER_WORD_TYPE step should carry a web_app field."""
    for step in axi_demo._SCRIPT:
        assert "web_app" not in step, (
            f"Step contains web_app key: {step.get('type')} / {step.get('text', '')[:40]}"
        )


def test_no_webapp_url_attribute():
    """DEMO_WEBAPP_URL must not exist on the module after transport removal."""
    assert not hasattr(axi_demo, "DEMO_WEBAPP_URL"), (
        "DEMO_WEBAPP_URL still present — Mini App transport not fully removed"
    )


def test_no_answer_web_app_query_in_source():
    import inspect
    source = inspect.getsource(axi_demo)
    assert "answerWebAppQuery" not in source
    assert "answer_web_app_query" not in source


def test_no_pending_replies_dict():
    assert not hasattr(axi_demo, "_pending_replies"), (
        "_pending_replies still present — Mini App transport not fully removed"
    )


def test_no_reply_slot_class():
    assert not hasattr(axi_demo, "_ReplySlot"), (
        "_ReplySlot still present — Mini App transport not fully removed"
    )


def test_no_handle_webapp_reply():
    assert not hasattr(axi_demo, "handle_webapp_reply"), (
        "handle_webapp_reply still present — Mini App transport not fully removed"
    )


def test_no_set_demo_bot():
    assert not hasattr(axi_demo, "set_demo_bot"), (
        "set_demo_bot still present — Mini App transport not fully removed"
    )


# -- manual input flow --------------------------------------------------------

def test_handle_demo_message_no_active_session():
    _sessions.clear()
    result = handle_demo_message(99999, "any text")
    assert result is False


def test_handle_demo_message_session_not_awaiting():
    _sessions.clear()
    session = DemoSession(chat_id=1, state=DemoState.RUNNING)
    session.awaiting_manual_input = False
    _sessions[1] = session
    result = handle_demo_message(1, "any text")
    assert result is False
    _sessions.clear()


def test_handle_demo_message_correct_answer_advances():
    _sessions.clear()
    session = DemoSession(chat_id=2, state=DemoState.RUNNING)
    session.awaiting_manual_input = True
    session.expected_answer = "I am the project manager."
    _sessions[2] = session

    result = handle_demo_message(2, "I am the project manager.")
    assert result is True
    assert session.manual_input_event.is_set()
    _sessions.clear()


def test_handle_demo_message_whitespace_normalised():
    """Extra spaces and leading/trailing whitespace must be accepted."""
    _sessions.clear()
    session = DemoSession(chat_id=3, state=DemoState.RUNNING)
    session.awaiting_manual_input = True
    session.expected_answer = "I am the project manager."
    _sessions[3] = session

    result = handle_demo_message(3, "  I  am  the  project  manager.  ")
    assert result is True
    _sessions.clear()


def test_handle_demo_message_wrong_answer_does_not_advance():
    _sessions.clear()
    session = DemoSession(chat_id=4, state=DemoState.RUNNING)
    session.awaiting_manual_input = True
    session.expected_answer = "I am the project manager."
    _sessions[4] = session

    result = handle_demo_message(4, "something completely different")
    assert result is False
    assert not session.manual_input_event.is_set()
    _sessions.clear()


def test_handle_demo_message_wrong_answer_keeps_session_active():
    """A wrong answer must not change awaiting_manual_input or clear the session."""
    _sessions.clear()
    session = DemoSession(chat_id=5, state=DemoState.RUNNING)
    session.awaiting_manual_input = True
    session.expected_answer = "I am the project manager."
    _sessions[5] = session

    handle_demo_message(5, "wrong answer")
    assert session.awaiting_manual_input is True
    assert 5 in _sessions
    _sessions.clear()


def test_run_demo_completes_with_manual_input():
    """Full playback completes when each CUSTOMER_WORD_TYPE step is manually answered."""
    _sessions.clear()
    axi_demo._last_completed.clear()
    chat_id = 5001
    session = DemoSession(chat_id=chat_id, state=DemoState.RUNNING)
    _sessions[chat_id] = session

    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=300))
    bot.send_chat_action = AsyncMock()
    bot.edit_message_text = AsyncMock()

    async def run_with_answers():
        demo_task = asyncio.create_task(_run_demo(session, bot))

        async def answer_feeder():
            while not demo_task.done():
                await asyncio.sleep(0.01)
                if session.awaiting_manual_input and session.expected_answer:
                    handle_demo_message(chat_id, session.expected_answer)

        feeder = asyncio.create_task(answer_feeder())
        try:
            await asyncio.wait_for(demo_task, timeout=120)
        finally:
            feeder.cancel()
            try:
                await feeder
            except asyncio.CancelledError:
                pass

    asyncio.run(run_with_answers())

    assert session.state == DemoState.COMPLETED
    assert bot.send_message.call_count >= 1


def test_run_demo_stops_on_event():
    """Demo stops cleanly when stop_event is set mid-run."""
    _sessions.clear()
    chat_id = 5002
    session = DemoSession(chat_id=chat_id, state=DemoState.RUNNING)
    _sessions[chat_id] = session

    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=301))
    bot.send_chat_action = AsyncMock()
    bot.edit_message_text = AsyncMock()

    async def stop_during_run():
        task = asyncio.create_task(_run_demo(session, bot))
        await asyncio.sleep(0.05)
        session.stop_event.set()
        # Also unblock any manual_input_event wait
        session.manual_input_event.set()
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(stop_during_run())
    assert session.state == DemoState.CANCELLED


def test_run_demo_no_reply_button_sent():
    """_run_demo must never send a message with a web_app button."""
    _sessions.clear()
    chat_id = 5003
    session = DemoSession(chat_id=chat_id, state=DemoState.RUNNING)
    _sessions[chat_id] = session

    bot = AsyncMock()
    sent_markups = []

    async def capture_send(*args, **kwargs):
        markup = kwargs.get("reply_markup")
        if markup is not None:
            sent_markups.append(markup)
        return MagicMock(message_id=302)

    bot.send_message = AsyncMock(side_effect=capture_send)
    bot.send_chat_action = AsyncMock()
    bot.edit_message_text = AsyncMock()

    async def run_and_stop():
        task = asyncio.create_task(_run_demo(session, bot))
        for _ in range(50):
            await asyncio.sleep(0.02)
            if session.awaiting_manual_input:
                handle_demo_message(chat_id, session.expected_answer)
            if session.state in (DemoState.COMPLETED, DemoState.CANCELLED, DemoState.FAILED):
                break
        session.stop_event.set()
        session.manual_input_event.set()
        try:
            await asyncio.wait_for(task, timeout=5)
        except asyncio.TimeoutError:
            pass

    asyncio.run(run_and_stop())

    for markup in sent_markups:
        markup_str = str(markup)
        assert "web_app" not in markup_str.lower(), (
            f"Reply button with web_app found in sent markup: {markup_str}"
        )


# -- demo routing / no fall-through to engineering ----------------------------

def test_is_demo_active_false_when_no_session():
    _sessions.clear()
    assert is_demo_active(99999) is False


def test_is_demo_active_true_when_session_present():
    _sessions.clear()
    try:
        _sessions[42] = DemoSession(chat_id=42)
        assert is_demo_active(42) is True
    finally:
        _sessions.clear()


def test_is_demo_active_false_after_session_removed():
    _sessions.clear()
    _sessions[42] = DemoSession(chat_id=42)
    _sessions.clear()
    assert is_demo_active(42) is False


# -- script content guards ----------------------------------------------------

def test_fictional_scenario_present():
    all_text = " ".join(s.get("text", "") for s in axi_demo._SCRIPT)
    assert "OilGasExploration" in all_text, "OilGasExploration project name must appear in script"


def test_fictional_disclaimer_present():
    all_text = " ".join(s.get("text", "") for s in axi_demo._SCRIPT)
    assert "fictional" in all_text.lower(), "Fictional disclaimer must appear in script"
    assert "OilGasExploration is a fictional project name" in all_text


def test_no_qatar_references():
    import re as _re
    all_text = " ".join(s.get("text", "") for s in axi_demo._SCRIPT)
    assert "Qatar Energy" not in all_text, "Qatar Energy must not appear in demo script"
    standalone_qatar = _re.findall(r"\bQatar\b", all_text)
    assert not standalone_qatar, f"Standalone 'Qatar' found in script: {standalone_qatar}"


def test_no_real_operator_names():
    all_text = " ".join(s.get("text", "") for s in axi_demo._SCRIPT)
    forbidden = ["Saudi Aramco", "Shell", "BP ", "TotalEnergies", "Chevron", "ExxonMobil", "Qatar Energy"]
    for name in forbidden:
        assert name not in all_text, f"Real operator '{name}' found in demo script"


_FORBIDDEN_DEMO_STRINGS = (
    "Engineering assist prepared",
    "Repairman",
    "axi_engineering_assist",
    "/data/engineering_assist",
    "repairman_task.json",
    "validation_plan.md",
)


def test_forbidden_strings_absent_from_demo_script():
    script_text = str(getattr(axi_demo, "_SCRIPT", []))
    for forbidden in _FORBIDDEN_DEMO_STRINGS:
        assert forbidden not in script_text, (
            f"Forbidden string '{forbidden}' found in _SCRIPT"
        )


# -- command handlers ---------------------------------------------------------

def test_cmd_demo_deletes_message():
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


def test_cmd_demo_cooldown_enforced():
    _sessions.clear()
    axi_demo._last_completed.clear()
    chat_id = 1003
    axi_demo._last_completed[chat_id] = time.monotonic()

    update = _make_update(chat_id=chat_id)
    ctx = _make_ctx(chat_id=chat_id)
    asyncio.run(axi_demo.cmd_demo(update, ctx))

    ctx.bot.send_message.assert_called_once()
    call_text = str(ctx.bot.send_message.call_args)
    assert "wait" in call_text.lower() or "seconds" in call_text.lower() or "cooldown" in call_text.lower()


def test_demo_start_callback_starts_session():
    _sessions.clear()
    chat_id = 2001
    session = DemoSession(chat_id=chat_id, state=DemoState.READY)
    session.lobby_message_id = 100
    _sessions[chat_id] = session

    update, query = _make_query(chat_id=chat_id)
    ctx = _make_ctx(chat_id=chat_id)

    async def run():
        await demo_start_callback(update, ctx)
        if session.task:
            session.stop_event.set()
            session.manual_input_event.set()
            try:
                await asyncio.wait_for(session.task, timeout=2)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

    asyncio.run(run())
    assert session.state in (DemoState.RUNNING, DemoState.CANCELLED, DemoState.COMPLETED)


def test_demo_cancel_from_lobby_no_new_message():
    _sessions.clear()
    chat_id = 3001
    session = DemoSession(chat_id=chat_id, state=DemoState.READY)
    session.lobby_message_id = 200
    _sessions[chat_id] = session

    update, query = _make_query(chat_id=chat_id)
    ctx = _make_ctx(chat_id=chat_id)

    asyncio.run(demo_cancel_callback(update, ctx))

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


# -- misc regressions ---------------------------------------------------------

def test_no_braille_blank_in_module():
    import inspect
    source = inspect.getsource(axi_demo)
    assert "⠀" not in source, "Braille blank U+2800 found — should not be present"


def test_customer_type_function_removed():
    assert not hasattr(axi_demo, "_customer_type"), "_customer_type() must be removed"


def test_demo_reply_api_file_deleted():
    api_path = Path(__file__).parent.parent / "demo_reply_api.py"
    assert not api_path.exists(), "demo_reply_api.py still exists — should be deleted"


def test_demo_webapp_dir_deleted():
    webapp_dir = Path(__file__).parent.parent / "demo_webapp"
    assert not webapp_dir.exists(), "demo_webapp/ directory still exists — should be deleted"
