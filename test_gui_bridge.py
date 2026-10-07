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
            scan = next(event for event in events if event["kind"] == "scan")
            self.assertEqual(scan["counts"]["pending"], 1)
            self.assertTrue(any(event["kind"] == "scan_progress" and event["completed"] == 1 and event["total"] == 1 for event in events))
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

    def test_completed_scan_passes_separately_from_token_and_reports_work(self):
        bridge = load_bridge("gui_bridge_scan_plan")
        import io
        token = "dummy-secret-for-plan-test"
        plan = {"version": 1, "items": [{"relative": "clip.mp4"}]}
        payload = json.dumps({"token":token}) + "\n" + json.dumps(plan) + "\n"
        stdin = io.TextIOWrapper(io.BytesIO(payload.encode()))
        output = io.StringIO()
        def run(argv, *, scan_plan):
            self.assertEqual(scan_plan, plan)
            self.assertEqual(bridge.engine.prompt_token(),token)
            print("Work: {'processed': 1, 'total': 2, 'pending': 1, 'failed': 0}")
            return 0
        with patch.object(bridge.sys, "stdin", stdin), patch.object(bridge.sys,"stdout", output), patch.object(bridge.sys,"__stdout__", output), patch.object(bridge.sys,"argv", ['bridge','input','--replace-originals']), patch.object(bridge.engine,'main',side_effect=run), patch.object(bridge.engine,'prompt_token'), patch.object(bridge.signal,'signal'):
            self.assertEqual(bridge.main(),0)
        self.assertNotIn(token,output.getvalue())
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        work = next(event for event in events if event['kind'] == 'work')
        self.assertEqual(work['counts']['pending'],1)
        self.assertEqual(work['counts']['processed'],1)

    def test_cancel_signal_raises_cleanup_exception(self):
        bridge = load_bridge("gui_bridge_cancel")
        with self.assertRaises(KeyboardInterrupt):
            bridge.interrupt(None, None)

if __name__ == "__main__":
    unittest.main()
