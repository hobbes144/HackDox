import asyncio
from gameengine.ui.tui.app import HackDoxApp
from gameengine.ui.tui.screens.credit_reveal import CreditRevealScreen
from gameengine.ui.tui.widgets.menu_glitch import AmbientGlitchPanel
from gameengine.core.content_loader import load_day
from gameengine.core import candidate_gen
from textual.widgets import Static
from textual.containers import Container, Horizontal, Vertical

async def main():
    app = HackDoxApp()
    async with app.run_test(size=(100, 32)) as pilot:
        day = load_day(1)
        candidate = candidate_gen.generate(0xC0FFEE, day, 0)
        await app.push_screen(CreditRevealScreen(candidate, credits_left=3))
        await pilot.pause()
        screen = app.screen
        frame = screen.query_one(".menu-frame")
        row = screen.query_one(".menu-frame-row")
        modal = screen.query_one("#credit-modal")
        panels = list(screen.query(AmbientGlitchPanel))
        print("frame region:", frame.region, "size:", frame.size)
        print("row region:", row.region, "size:", row.size)
        print("modal region:", modal.region, "size:", modal.size)
        print("row align:", row.styles.align_horizontal, row.styles.align_vertical)
        print("row layout:", row.styles.layout)
        print("modal height style:", modal.styles.height)
        for child in row.children:
            print("child", child, child.region, child.styles.height)
        for p in panels:
            print("panel", " ".join(p.classes), p.region, p.size)
        app.pop_screen()

asyncio.run(main())
