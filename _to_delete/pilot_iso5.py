import asyncio
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, Container
from textual.widgets import Static

class TestApp(App):
    CSS = """
    Screen { background: black; }
    .row { width: 100%; height: 24; background: green;}
    .flank { width: 13; height: 1fr; background: red; }
    .wrap { width: auto; height: 1fr; }
    .modalflank { width: 100%; height: 1fr; background: yellow; }
    #box { width: 40; height: auto; background: blue; }
    """
    def compose(self) -> ComposeResult:
        with Horizontal(classes="row"):
            yield Static("L", classes="flank")
            with Vertical(classes="wrap"):
                yield Static("top", classes="modalflank")
                with Container(id="box"):
                    yield Static("hello\nworld\nthree\nfour")
                yield Static("bot", classes="modalflank")
            yield Static("R", classes="flank")

async def main():
    app = TestApp()
    async with app.run_test(size=(60, 30)) as pilot:
        await pilot.pause()
        row = app.query_one(".row")
        box = app.query_one("#box")
        flanks = list(app.query(".modalflank"))
        print("row:", row.region)
        print("box:", box.region)
        for f in flanks:
            print("modalflank:", f.region)

asyncio.run(main())
