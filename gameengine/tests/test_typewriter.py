"""Headless pilot tests for the TypewriterLog widget (#3).

Runs the widget inside a minimal Textual app via `App.run_test()` so the
character-by-character timer, the focus-scoped Space advance, and the
Finished/triggers hook are exercised for real — not just compiled. Uses
asyncio.run inside sync tests so no pytest-asyncio plugin is required.
"""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Static

from gameengine.core import candidate_gen
from gameengine.core.content_loader import load_day
from gameengine.ui.tui.app import BriefingScreen, ChatPanel, TypewriterLog


class _Harness(App):
    def __init__(self) -> None:
        super().__init__()
        self.finished: list = []

    def compose(self) -> ComposeResult:
        yield TypewriterLog(id="tw")

    def on_typewriter_log_finished(self, msg: TypewriterLog.Finished) -> None:
        self.finished.append(msg.triggers)


def _run(coro):
    return asyncio.run(coro)


def test_single_line_autofinishes_and_fires_triggers():
    async def go():
        app = _Harness()
        async with app.run_test() as pilot:
            tw = app.query_one(TypewriterLog)
            tw.post("Overseer", "the intruders are getting smarter",
                    triggers="unlock:ghostscan")
            await pilot.pause(1.2)
            # Last (only) line auto-finalizes with no keypress → triggers fire.
            assert app.finished == ["unlock:ghostscan"], app.finished
            assert tw.is_idle
    _run(go())


def test_multiline_waits_for_space_between_lines():
    async def go():
        app = _Harness()
        async with app.run_test() as pilot:
            tw = app.query_one(TypewriterLog)
            tw.focus()
            tw.post("Overseer", ["first line", "second line"], triggers="T")
            await pilot.pause(0.4)
            # First line done, but it's NOT the last → message not finished yet.
            assert app.finished == [], "must pause between lines, not auto-run"
            await pilot.press("space")          # advance to the second line
            await pilot.pause(0.4)
            assert app.finished == ["T"], app.finished
            assert tw.is_idle
    _run(go())


def test_space_fast_completes_then_bubbles_when_idle():
    async def go():
        app = _Harness()
        async with app.run_test() as pilot:
            tw = app.query_one(TypewriterLog)
            tw.focus()
            long_line = "x" * 200                # would take ~4s to type out
            tw.post("Overseer", long_line, triggers="done")
            await pilot.pause(0.05)              # only a few chars typed so far
            assert not tw.is_idle
            await pilot.press("space")           # fast-complete the single line
            await pilot.pause(0.05)
            # Single line = last line → fast-complete finalizes the message.
            assert app.finished == ["done"], app.finished
            assert tw.is_idle                    # now Space would bubble to host
    _run(go())


def test_triggers_default_none_and_is_one_way():
    async def go():
        app = _Harness()
        async with app.run_test() as pilot:
            tw = app.query_one(TypewriterLog)
            tw.post("Chat", "hi there")          # no triggers
            await pilot.pause(0.4)
            assert app.finished == [None]
            # One-way: the widget takes no text input — typing letters is inert
            # (no crash, no state change).
            tw.focus()
            await pilot.press("a", "b", "c")
            assert tw.is_idle
    _run(go())


def test_queued_messages_chain():
    async def go():
        app = _Harness()
        async with app.run_test() as pilot:
            tw = app.query_one(TypewriterLog)
            tw.post("Chat", "one", triggers=1)
            tw.post("Chat", "two", triggers=2)
            await pilot.pause(0.6)
            assert app.finished == [1, 2], app.finished
    _run(go())


class _ChatHarness(App):
    def __init__(self) -> None:
        super().__init__()
        self.finished = 0

    def compose(self) -> ComposeResult:
        yield ChatPanel()

    def on_typewriter_log_finished(self, msg) -> None:
        self.finished += 1


def test_chatpanel_streams_full_candidate_script():
    """ChatPanel (now a TypewriterLog) plays a real generated candidate's whole
    script, one auto-chaining message per line (#3 — 'reused as ChatPanel')."""
    async def go():
        cand = candidate_gen.generate(0xC0FFEE, load_day(1), 0)
        app = _ChatHarness()
        async with app.run_test() as pilot:
            cp = app.query_one(ChatPanel)
            cp.set_candidate(cand)
            await pilot.pause(8.0)   # let every line type out and chain
            assert cp.is_idle
            assert app.finished == len(cand.chat_script) > 0
    _run(go())


class _BriefingHost(App):
    def compose(self) -> ComposeResult:
        yield Static("root")


def test_hostile_chat_color_gated_behind_sentiment_scanner():
    """Batch-3 task #4: HOSTILE_CHAT lines must only render red/bold once the
    Sentiment Scanner upgrade (config.UPGRADE_CHAT_HOSTILE) is owned — before
    that they should read like any other neutral chat line. Only the ⚠ prefix
    icon was gated before this fix; the line color itself was not.
    """
    from gameengine import config

    day = load_day(20)
    hostile_cand = None
    for seed in range(300):
        c = candidate_gen.generate(seed, day, 0)
        if any(l.tag == "hostile" for l in c.chat_script):
            hostile_cand = c
            break
    assert hostile_cand is not None, "no hostile-chat candidate found in 300 seeds"

    calls: list[tuple] = []

    class _RecordingChatPanel(ChatPanel):
        def post(self, speaker, lines, *, color="#c8d4e1", icon="", style="",
                 triggers=None, prefix="") -> None:
            calls.append((color, style, prefix))

    ungated = _RecordingChatPanel()
    ungated.upgrades = set()
    ungated.set_candidate(hostile_cand)
    hostile_idx = [i for i, l in enumerate(hostile_cand.chat_script)
                   if l.tag == "hostile"]
    for i in hostile_idx:
        color, style, prefix = calls[i]
        assert color == "#c8d4e1" and style == "", (
            f"hostile line rendered {color!r}/{style!r} without the upgrade")
        assert "⚠" not in prefix

    calls.clear()
    gated = _RecordingChatPanel()
    gated.upgrades = {config.UPGRADE_CHAT_HOSTILE}
    gated.set_candidate(hostile_cand)
    for i in hostile_idx:
        color, style, prefix = calls[i]
        assert color == "#ff5470" and style == "bold"
        assert "⚠" in prefix


def test_briefing_screen_plays_overseer_beat():
    """The BriefingScreen Overseer region (a TypewriterLog host) auto-plays a
    multi-line beat to completion without a keypress (#3)."""
    async def go():
        from gameengine.core.models import GameState
        app = _BriefingHost()
        async with app.run_test() as pilot:
            # Day 1 unlocks no tool, so the beat is just the two narrative lines.
            await app.push_screen(
                BriefingScreen(load_day(1), "Line one.\nLine two.",
                               GameState(seed=0xC0FFEE)))
            await pilot.pause(1.5)
            log = app.screen.query_one("#briefing-overseer", TypewriterLog)
            assert log.is_idle          # both lines chained and finished
    _run(go())
