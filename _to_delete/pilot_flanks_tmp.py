import asyncio
from gameengine.ui.tui.app import HackDoxApp
from gameengine.ui.tui.screens.intro import IntroScreen
from gameengine.ui.tui.screens.settings import SettingsScreen
from gameengine.ui.tui.screens.credits import CreditsScreen
from gameengine.ui.tui.screens.credit_reveal import CreditRevealScreen
from gameengine.ui.tui.widgets.menu_glitch import AmbientGlitchPanel
from gameengine.core.content_loader import load_day
from gameengine.core import candidate_gen

async def check(screen_factory, name):
    app = HackDoxApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await app.push_screen(screen_factory())
        await pilot.pause()
        panels = app.screen.query(AmbientGlitchPanel)
        sizes = [(p.id or p.styles.get_rule("width"), p.size) for p in panels]
        print(name, "panel count:", len(panels))
        for p in panels:
            cls = " ".join(p.classes)
            print("  ", cls, p.size)
        app.pop_screen()

async def main():
    await check(IntroScreen, "Intro")
    await check(SettingsScreen, "Settings")
    await check(CreditsScreen, "Credits")

    day = load_day(1)
    candidate = candidate_gen.generate(0xC0FFEE, day, 0)
    await check(lambda: CreditRevealScreen(candidate, credits_left=3), "CreditReveal")

asyncio.run(main())
