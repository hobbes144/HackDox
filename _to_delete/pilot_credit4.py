import asyncio
from gameengine.ui.tui.app import HackDoxApp
from gameengine.ui.tui.screens.credit_reveal import CreditRevealScreen
from gameengine.ui.tui.widgets.menu_glitch import AmbientGlitchPanel
from gameengine.core.content_loader import load_day
from gameengine.core import candidate_gen

async def check(size):
    app = HackDoxApp()
    async with app.run_test(size=size) as pilot:
        day = load_day(1)
        candidate = candidate_gen.generate(0xC0FFEE, day, 0)
        await app.push_screen(CreditRevealScreen(candidate, credits_left=3))
        await pilot.pause()
        screen = app.screen
        row = screen.query_one(".menu-frame-row")
        modal = screen.query_one("#credit-modal")
        panels = list(screen.query(AmbientGlitchPanel))
        print(f"--- size {size} ---")
        print("row:", row.region)
        print("modal:", modal.region)
        for p in panels:
            print("panel", " ".join(p.classes), p.region)
        # check for gaps: sum of covered y-ranges in modal column should equal row height
        await pilot.press("escape")
        await pilot.pause()
        print("after escape:", type(app.screen).__name__)

async def main():
    await check((100, 32))
    await check((80, 24))
    await check((120, 45))

asyncio.run(main())
