import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import tesla_dashcam_decrypt as d
from test_hardening import MP4, fixture

class OrganizeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / 'TeslaCam'
        self.event = self.root / 'EncryptedClips' / 'SavedClips' / '2026-08-15_12-00-00'
        self.event.mkdir(parents=True)
        (self.event / 'front.mp4').write_bytes(MP4)
        (self.event / 'event.json').write_bytes(b'{"event":"saved"}')
        self.target = self.root / 'SavedClips' / self.event.name
    def tearDown(self):
        self.tmp.cleanup()
    def organize(self, root=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return d.organize_decrypted_events(root or self.root)
    def test_complete_event_moves_with_metadata_and_timestamp(self):
        before = (self.event / 'front.mp4').stat().st_mtime_ns
        self.assertEqual(self.organize(self.root.parent), (1, 0, 0))
        self.assertFalse(self.event.exists())
        self.assertEqual((self.target / 'front.mp4').read_bytes(), MP4)
        self.assertEqual((self.target / 'front.mp4').stat().st_mtime_ns, before)
        self.assertEqual((self.target / 'event.json').read_bytes(), b'{"event":"saved"}')
        self.assertEqual(self.organize(), (0, 0, 0))
    def test_mixed_event_stays_until_all_videos_decrypted(self):
        fixture(self.event / 'back.mp4')
        self.assertEqual(self.organize(), (0, 1, 0))
        self.assertTrue(self.event.exists())
        self.assertFalse(self.target.exists())
    def test_invalid_plain_mp4_stays(self):
        (self.event / 'front.mp4').write_bytes(MP4[:24])
        self.assertEqual(self.organize(), (0, 1, 0))
    def test_collision_never_overwritten_even_empty_directory(self):
        self.target.mkdir(parents=True)
        self.assertEqual(self.organize(), (0, 0, 1))
        with self.assertRaises(OSError):
            d.rename_directory_exclusive(self.event, self.target)
        self.assertTrue(self.event.exists())
        self.assertEqual(list(self.target.iterdir()), [])
    def test_symlink_event_retained(self):
        (self.event / 'linked.mp4').symlink_to(self.event / 'front.mp4')
        self.assertEqual(self.organize(), (0, 1, 0))
    def test_cancel_validation_never_moves_event(self):
        with patch.object(d, 'validate_mp4', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.organize()
        self.assertTrue(self.event.exists())
        self.assertFalse(self.target.exists())
    def test_offline_command_needs_no_token(self):
        with patch.object(d, 'prompt_token', side_effect=AssertionError('no token')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(d.main([str(self.root), '--organize-decrypted']), 0)
        self.assertTrue(self.target.exists())
    def test_changed_video_is_retained(self):
        original = d.validate_mp4
        def change(path):
            original(path)
            path.write_bytes(MP4 + b'changed')
        with patch.object(d, 'validate_mp4', side_effect=change):
            self.assertEqual(self.organize(), (0, 1, 0))

if __name__ == '__main__':
    unittest.main()
