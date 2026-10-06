import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import tesla_dashcam_decrypt as d
from test_hardening import fixture, KEY, MP4


class ReplacementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.src = self.root / 'clip.mp4'
        fixture(self.src)
        self.original = self.src.read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def test_replaces_same_path_without_hardlinks_or_directory_chmod(self):
        mode = self.root.stat().st_mode
        mtime = self.src.stat().st_mtime_ns
        with patch.object(d.os, 'link', side_effect=AssertionError('no hardlinks')):
            self.assertEqual(d.safe_replace(self.src, KEY), len(MP4))
        self.assertEqual(self.src.read_bytes(), MP4)
        self.assertEqual(self.root.stat().st_mode, mode)
        self.assertEqual(self.src.stat().st_mtime_ns, mtime)
        self.assertEqual(list(self.root.iterdir()), [self.src])

    def test_wrong_key_keeps_original(self):
        with self.assertRaises(ValueError):
            d.safe_replace(self.src, b'wrongkey12345678')
        self.assertEqual(self.src.read_bytes(), self.original)
        self.assertEqual(list(self.root.iterdir()), [self.src])

    def test_no_space_keeps_original(self):
        from collections import namedtuple
        Usage = namedtuple('Usage', 'total used free')
        with patch.object(d.shutil, 'disk_usage', return_value=Usage(100,100,0)), self.assertRaises(ValueError):
            d.safe_replace(self.src, KEY)
        self.assertEqual(self.src.read_bytes(), self.original)
        self.assertEqual(list(self.root.iterdir()), [self.src])

    def test_rename_failure_keeps_original(self):
        with patch.object(d.os, 'replace', side_effect=OSError('rename failed')), self.assertRaises(OSError):
            d.safe_replace(self.src, KEY)
        self.assertEqual(self.src.read_bytes(), self.original)
        self.assertEqual(list(self.root.iterdir()), [self.src])

    def test_cancel_cleans_temp_and_keeps_original(self):
        with patch.object(d, '_decrypt_real_file', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            d.safe_replace(self.src, KEY)
        self.assertEqual(self.src.read_bytes(), self.original)
        self.assertEqual(list(self.root.iterdir()), [self.src])

    def test_changed_header_is_not_replaced(self):
        header = d.read_file_header(self.src)
        fixture(self.src, key_id=2)
        changed = self.src.read_bytes()
        with self.assertRaises(ValueError):
            d.safe_replace(self.src, KEY, expected_header=header)
        self.assertEqual(self.src.read_bytes(), changed)

    def test_changed_file_during_decryption_is_not_replaced(self):
        original_validate = d.validate_mp4
        def validate_and_change(path):
            original_validate(path)
            self.src.write_bytes(self.original + b'changed')
        with patch.object(d, 'validate_mp4', side_effect=validate_and_change), self.assertRaises(ValueError):
            d.safe_replace(self.src, KEY)
        self.assertEqual(self.src.read_bytes(), self.original + b'changed')
        self.assertEqual(list(self.root.iterdir()), [self.src])

    def test_offline_scan_does_not_replace(self):
        with patch.object(d, 'get_session', side_effect=AssertionError('no network')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(d.main([str(self.root), '--replace-originals', '--scan']), 0)
        self.assertEqual(self.src.read_bytes(), self.original)

    def test_replace_roundtrip_and_resume(self):
        header = d.read_file_header(self.src)
        class Session:
            headers = {}
            def close(self): pass
        with patch.object(d, 'prompt_token', return_value='dummy'), patch.object(d, 'get_session', return_value=Session()), patch.object(d, 'fetch_keys_batch', return_value={header['id']:KEY}), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(d.main([str(self.root), '--replace-originals']), 0)
        self.assertEqual(self.src.read_bytes(), MP4)
        self.assertIn("'replaced': 1", out.getvalue())
        with patch.object(d, 'prompt_token', side_effect=AssertionError('no token needed')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(d.main([str(self.root), '--replace-originals']), 0)


if __name__ == '__main__':
    unittest.main()
