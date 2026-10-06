import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_hardening import fixture

ROOT = Path(__file__).parent
RESOURCES = ROOT / "macos/Sources/TeslaDecryptGUI/Resources"
BRIDGE = RESOURCES / "gui_bridge.py"

def load_bridge(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, BRIDGE)
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    return bridge

class GUIBridgeTests(unittest.TestCase):
    def test_bundled_engine_is_identical(self):
        self.assertEqual((RESOURCES / "tesla_dashcam_decrypt.py").read_bytes(),
                         (ROOT / "tesla_dashcam_decrypt.py").read_bytes())

    def test_offline_scan_json_and_no_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source"
            source.mkdir()
            fixture(source / "clip.mp4")
            result = subprocess.run([sys.executable, str(BRIDGE), str(source), str(root / "output"), "--scan"],
                                    input="", capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            events = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(events[0]["kind"], "scan")
            self.assertEqual(events[0]["counts"]["pending"], 1)
            self.assertFalse((root / "output").exists())

    def test_invalid_token_never_echoed(self):
        secret = "sensitive token not valid"
        result = subprocess.run([sys.executable, str(BRIDGE), "/invalid", "/another"],
                                input=json.dumps({"token": secret}) + "\n", capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["kind"], "error")

    def test_valid_token_only_reaches_engine_in_memory(self):
        bridge = load_bridge("gui_bridge_test")
        token = "dummy-secret-for-test"
        import io
        stdin = io.TextIOWrapper(io.BytesIO((json.dumps({"token": token}) + "\n").encode()))
        output = io.StringIO()
        def engine_main(argv):
            self.assertEqual(bridge.engine.prompt_token(), token)
            print("Results: {'decrypted': 1, 'failed': 0}")
            return 0
        with patch.object(bridge.sys, "stdin", stdin), patch.object(bridge.sys, "stdout", output), patch.object(bridge.sys, "__stdout__", output), patch.object(bridge.sys, "argv", ["bridge", "input", "output"]), patch.object(bridge.engine, "main", side_effect=engine_main), patch.object(bridge.engine, "prompt_token"), patch.object(bridge.signal, "signal"):
            self.assertEqual(bridge.main(), 0)
        self.assertNotIn(token, output.getvalue())
        self.assertEqual(json.loads(output.getvalue().splitlines()[0])["kind"], "summary")

    def test_cancel_signal_raises_cleanup_exception(self):
        bridge = load_bridge("gui_bridge_cancel")
        with self.assertRaises(KeyboardInterrupt):
            bridge.interrupt(None, None)

if __name__ == "__main__":
    unittest.main()
