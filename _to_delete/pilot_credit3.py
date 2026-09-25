import asyncio
from gameengine.ui.tui.app import HackDoxApp
from gameengine.ui.tui.screens.credit_reveal import CreditRevealScreen
from gameengine.core.content_loader import load_day
from gameengine.core import candidate_gen

async def main():
    app = HackDoxApp()
    async with app.run_test(size=(100, 32)) as pilot:
        day = load_day(1)
        candidate = candidate_gen.generate(0xC0FFEE, day, 0)
        await app.push_screen(CreditRevealScreen(candidate, credits_left=3))
        await pilot.pause()
        assert isinstance(app.screen, CreditRevealScreen)
        await pilot.press("escape")
        await pilot.pause()
        print("after escape, screen is:", type(app.screen).__name__)

asyncio.run(main())
