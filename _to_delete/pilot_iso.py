import asyncio
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, Container
from textual.widgets import Static

class TestApp(App):
    CSS = """
    Screen { background: black; }
    .frame { height: 1fr; }
    .row { width: 100%; height: 1fr; align: center middle; }
    .flank { width: 1fr; height: 1fr; background: red; }
    #box { width: 40; height: auto; background: blue; }
    """
    def compose(self) -> ComposeResult:
        with Vertical(classes="frame"):
            yield Static("top", classes="flank")
            with Horizontal(classes="row"):
                yield Static("L", classes="flank")
                with Container(id="box"):
                    yield Static("hello\nworld")
                yield Static("R", classes="flank")
            yield Static("bottom", classes="flank")

async def main():
    app = TestApp()
    async with app.run_test(size=(60, 30)) as pilot:
        await pilot.pause()
        row = app.query_one(".row")
        box = app.query_one("#box")
        print("row:", row.region)
        print("box:", box.region)

asyncio.run(main())
