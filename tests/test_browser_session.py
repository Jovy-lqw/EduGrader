import json
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from backend.app.services.browser_session import BrowserSession


class BrowserSessionStateTests(IsolatedAsyncioTestCase):
    async def test_persists_and_restores_session_state(self) -> None:
        state = {
            "cookies": [{"name": "session", "value": "token"}],
            "origins": [
                {
                    "origin": "https://example.com",
                    "localStorage": [{"name": "user", "value": "teacher"}],
                }
            ],
        }

        class Context:
            def __init__(self) -> None:
                self.cookies = []
                self.script = ""

            async def storage_state(self):
                return state

            async def add_cookies(self, cookies):
                self.cookies = cookies

            async def add_init_script(self, script):
                self.script = script

        with TemporaryDirectory() as directory:
            path = Path(directory) / "browser-session.json"
            context = Context()
            session = BrowserSession()
            session._context = context
            with patch(
                "backend.app.services.browser_session.SESSION_STATE_PATH",
                path,
            ):
                await session.persist_state()
                self.assertEqual(json.loads(path.read_text()), state)
                self.assertEqual(
                    stat.S_IMODE(path.stat().st_mode),
                    0o600,
                )

                restored = Context()
                await session._restore_state(restored)
                self.assertEqual(restored.cookies, state["cookies"])
                self.assertIn("https://example.com", restored.script)
