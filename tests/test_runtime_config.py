import tempfile
from pathlib import Path
from unittest import TestCase

from backend.app.runtime_config import RuntimeConfigStore, RuntimeConfigUpdate


class RuntimeConfigStoreTests(TestCase):
    def test_saves_secret_without_returning_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RuntimeConfigStore(Path(directory))
            public = store.save(
                RuntimeConfigUpdate(
                    llm_api_key="secret-value",
                    adapter_mode="mock",
                )
            )

            self.assertTrue(public.llm_api_key_configured)
            self.assertEqual(public.adapter_mode, "mock")
            self.assertFalse(hasattr(public, "llm_api_key"))
            self.assertEqual(store.get_api_key(), "secret-value")
            mode = (Path(directory) / "secrets.json").stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)
