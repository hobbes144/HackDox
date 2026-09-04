"""_TWMessage, TypewriterLog, ChatPanel."""

from __future__ import annotations

from typing import ClassVar

from textual.events import Key
from textual.message import Message
from textual.widgets import Static

from gameengine import config
from gameengine.core.models import Candidate


class _TWMessage:
    """One queued TypewriterLog message. Plain class (no dataclass import)."""

    __slots__ = ("color", "icon", "lines", "prefix", "speaker", "style", "triggers")

    def __init__(self, speaker, lines, color, icon, style, triggers, prefix):
        self.speaker = speaker
        self.lines = lines
        self.color = color
        self.icon = icon
        self.style = style
        self.triggers = triggers
        self.prefix = prefix   # verbatim markup rendered before the typed text


class TypewriterLog(Static):
    """Character-by-character message log (#3).

    Reused by the Overseer panel, the candidate Chat panel, and the between-day
    Overseer region. Messages are queued and typed one line at a time.

    **Space advances only while this widget has focus.** The first press
    fast-completes the line being typed; the next steps to the following line
    within the same message. Once every queued line has played, `is_idle`
    becomes True and Space is *not* consumed — so a host screen's own Space
    binding (buy in the shop, begin/continue on the briefing/EOD screens, stamp
    on the stego page) still fires. This is the focus-scoped advance the issue's
    own comment asked for, instead of a screen-level Space binding that would
    collide with those three hosts.

    A message auto-finalizes the instant its LAST line is fully revealed (so a
    side effect never waits on an extra keypress): it posts
    `TypewriterLog.Finished`, carrying that message's `triggers` payload, which
    is exactly the hook #34's tool-unlock beat rides. One-way: the widget never
    accepts text input.
    """

    can_focus = True
    DEFAULT_CHAR_DELAY = 0.02

    class Finished(Message):
        """Posted when a queued message's last line finishes. `triggers` is
        whatever the caller handed to `post(...)` (None if it had none)."""

        def __init__(self, log: TypewriterLog, triggers) -> None:
            super().__init__()
            self.log = log
            self.triggers = triggers

    def __init__(self, *, id=None, classes="", char_delay=DEFAULT_CHAR_DELAY):
        # Seed with a space, never "" — an empty Static renders a None visual
        # and crashes layout in current Textual.
        super().__init__(" ", id=id, classes=classes)
        self._char_delay = char_delay
        self._queue: list[_TWMessage] = []
        self._done_lines: list[str] = []      # fully-revealed lines (markup)
        self._active: _TWMessage | None = None
        self._msg_lines: list[str] = []       # remaining lines of _active
        self._is_last_line = False
        self._cur_prefix = ""                 # speaker/icon markup for current line
        self._cur_full = ""                   # plain text of the line being typed
        self._shown = 0                       # chars of _cur_full revealed
        self._cur_color = "#c8d4e1"
        self._cur_style = ""
        self._line_complete = False
        self._timer = None
        self._unread = False

    # ── Public API ────────────────────────────────────────────────
    def post(self, speaker, lines, *, color="#c8d4e1", icon="", style="",
             triggers=None, prefix="") -> None:
        """Queue a message. `lines` may be a str or a list of str.

        `lines` must be PLAIN text — it is revealed one character at a time, so
        embedded markup would tear mid-reveal. Per-line rich decoration goes in
        `prefix` (rendered verbatim, not typed); the typed text is wrapped in
        `color`/`style` as a whole.
        """
        if isinstance(lines, str):
            lines = [lines]
        self._queue.append(_TWMessage(speaker, list(lines), color, icon, style,
                                      triggers, prefix))
        if not self.has_focus:
            self._set_unread(True)
        # Kick playback only when fully idle; otherwise it chains automatically.
        if self._active is None and self._timer is None:
            self._begin_next_message()

    def clear_log(self) -> None:
        self._stop_timer()
        self._queue.clear()
        self._done_lines.clear()
        self._active = None
        self._msg_lines = []
        self._cur_full = ""
        self._shown = 0
        self._line_complete = False
        self._set_unread(False)
        self._repaint()

    @property
    def is_idle(self) -> bool:
        """True when nothing is typing and nothing is queued."""
        return (self._active is None and not self._queue
                and self._timer is None and not self._line_complete)

    def advance(self) -> None:
        """Space handler: fast-complete the current line, else step forward."""
        if self._timer is not None:
            self._on_line_revealed()          # fast-complete
        elif self._line_complete:
            self._commit_current_line()
            self._begin_line_or_finish()

    # ── Internal ──────────────────────────────────────────────────
    def _begin_next_message(self) -> None:
        if not self._queue:
            self._active = None
            return
        self._active = self._queue.pop(0)
        self._cur_color = self._active.color
        self._cur_style = self._active.style
        self._msg_lines = list(self._active.lines)
        self._begin_line_or_finish()

    def _begin_line_or_finish(self) -> None:
        if self._msg_lines:
            line = self._msg_lines.pop(0)
            self._is_last_line = not self._msg_lines
            self._begin_line(line)
        else:
            self._finish_message()

    def _begin_line(self, text: str) -> None:
        icon = (self._active.icon + " ") if (self._active and self._active.icon) else ""
        spk = self._active.speaker if self._active else ""
        explicit_prefix = self._active.prefix if self._active else ""
        if explicit_prefix:
            self._cur_prefix = explicit_prefix
        elif spk:
            self._cur_prefix = f"[{self._cur_color}][b]{icon}{spk}:[/][/]  "
        else:
            self._cur_prefix = icon
        self._cur_full = text
        self._shown = 0
        self._line_complete = False
        self._repaint()
        # A blank line has nothing to type — reveal it immediately.
        if not text:
            self._on_line_revealed()
        else:
            self._timer = self.set_interval(self._char_delay, self._tick)

    def _tick(self) -> None:
        self._shown += 1
        if self._shown >= len(self._cur_full):
            self._on_line_revealed()
        else:
            self._repaint()

    def _on_line_revealed(self) -> None:
        """The current line is fully shown (typed out or fast-completed)."""
        self._stop_timer()
        self._shown = len(self._cur_full)
        if self._is_last_line:
            self._repaint()
            self._finish_message()            # auto-finalize — no extra keypress
        else:
            self._line_complete = True
            self._repaint()

    def _commit_current_line(self) -> None:
        col, sty = self._cur_color, self._cur_style
        body = (f"[{col} {sty}]{self._cur_full}[/]" if sty
                else f"[{col}]{self._cur_full}[/]")
        self._done_lines.append(self._cur_prefix + body)
        self._cur_full = ""
        self._shown = 0
        self._cur_prefix = ""
        self._line_complete = False

    def _finish_message(self) -> None:
        if self._cur_full:
            self._commit_current_line()
        triggers = self._active.triggers if self._active else None
        self._active = None
        self._line_complete = False
        self._repaint()
        self.post_message(TypewriterLog.Finished(self, triggers))
        self._begin_next_message()            # chain any queued message

    def _repaint(self) -> None:
        lines = list(self._done_lines)
        if self._cur_full:
            partial = self._cur_full[:self._shown]
            col, sty = self._cur_color, self._cur_style
            body = (f"[{col} {sty}]{partial}[/]" if sty else f"[{col}]{partial}[/]")
            caret = "" if self._line_complete else "[dim]▌[/]"
            lines.append(self._cur_prefix + body + caret)
        # TypewriterLog is a Static leaf — render straight into its own content.
        # Never push "" (empty renders a None visual and crashes layout).
        self.update("\n".join(lines) or " ")

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _set_unread(self, val: bool) -> None:
        self._unread = val
        base = (self.border_title or "").rstrip(" ●")
        if base:
            self.border_title = f"{base} ●" if val else base

    def on_focus(self) -> None:
        self._set_unread(False)

    def on_key(self, event: Key) -> None:
        # Focus-scoped advance: consume Space only while there's dialogue left
        # to play; once idle, let it bubble so the host screen's Space fires.
        if event.key == "space" and not self.is_idle:
            self.advance()
            event.stop()


class ChatPanel(TypewriterLog):
    """One-way candidate dialogue, played through the TypewriterLog (#3).

    The whole script is posted as a single message so Space steps line-by-line
    within it (per the widget contract); the player never types back.
    """

    def __init__(self) -> None:
        super().__init__(id="chat")
        self.classes = "panel"
        self.border_title = " Chat "
        self.upgrades: set = set()   # Sentiment Scanner upgrade (issue #23)

    _TAG_STYLE: ClassVar[dict[str, tuple[str, str]]] = {
        "neutral":  ("#c8d4e1", ""),
        "warm":     ("#7dd3c0", ""),
        "hostile":  ("#ff5470", "bold"),
        "flippant": ("#c084fc", "italic"),
        "earnest":  ("#7dd3c0", ""),
        "intro":    ("#c8d4e1", "italic"),
    }

    def set_candidate(self, candidate: Candidate) -> None:
        self.clear_log()
        first = candidate.display_name.split()[0]
        _has_sentiment = config.UPGRADE_CHAT_HOSTILE in self.upgrades
        for line in candidate.chat_script:
            tag = line.tag
            if tag.startswith("hint:"):
                col, sty = "#ff8c42", "italic"
            elif tag == "hostile" and not _has_sentiment:
                # Sentiment Scanner upgrade (issue #23) gates the red/bold
                # marking itself, not just the ⚠ icon (batch-3 task #4) —
                # without it, hostile lines read the same as neutral chat.
                col, sty = self._TAG_STYLE["neutral"]
            else:
                col, sty = self._TAG_STYLE.get(tag, ("#c8d4e1", ""))
            warn = "[#ff5470][b]⚠ [/][/]" if tag == "hostile" and _has_sentiment else ""
            prefix = f"[#6b7785]{line.timestamp}[/]  [b]{first}:[/]  {warn}"
            # Each chat line is its own message: the timestamp/name go in the
            # verbatim prefix, the plain line text is what types out (wrapped in
            # the tag colour). Messages auto-chain, so the script streams in.
            self.post("", line.text, color=col, style=sty, prefix=prefix)
