import asyncio
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, Container
from textual.widgets import Static

class TestApp(App):
    CSS = """
    Screen { background: black; }
    .row { width: 100%; height: 20; align: center middle; background: green;}
    .flank { width: 10; height: 1fr; background: red; }
    #box { width: 40; height: auto; background: blue; }
    """
    def compose(self) -> ComposeResult:
        with Horizontal(classes="row"):
            yield Static("L", classes="flank")
            with Container(id="box"):
                yield Static("hello\nworld")
            yield Static("R", classes="flank")

async def main():
    app = TestApp()
    async with app.run_test(size=(60, 30)) as pilot:
        await pilot.pause()
        row = app.query_one(".row")
        box = app.query_one("#box")
        print("row:", row.region)
        print("box:", box.region)

asyncio.run(main())
