"""Compare bulk decryption with independently encrypted CBC pages."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from Crypto.Cipher import AES
import tesla_dashcam_decrypt as d
from test_hardening import KEY, MP4, fixture


class BulkDecryptTests(unittest.TestCase):
    def test_page_and_io_batch_boundaries(self):
        for size in (len(MP4), 4095, 4096, 4097, d.IO_BATCH_SIZE, d.IO_BATCH_SIZE + 123, 2*d.IO_BATCH_SIZE+17):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as folder:
                src, dst = Path(folder)/'input.mp4', Path(folder)/'output.mp4'
                media = (MP4 + bytes(range(256)) * ((size // 256) + 1))[:size]
                fixture(src, media=media)
                self.assertEqual(d._decrypt_real_file(src, dst, KEY), size)
                self.assertEqual(dst.read_bytes(), media)

    def test_only_one_cipher_setup_for_many_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            src, dst = Path(folder)/'input.mp4', Path(folder)/'output.mp4'
            media = MP4 + b'x' * (d.IO_BATCH_SIZE * 2)
            fixture(src, media=media)
            original = AES.new
            with patch.object(d.AES, 'new', wraps=original) as cipher:
                d._decrypt_real_file(src, dst, KEY)
                self.assertEqual(cipher.call_count, 1)
            self.assertEqual(dst.read_bytes(), media)

    def test_truncated_final_page_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            src, dst = Path(folder)/'input.mp4', Path(folder)/'output.mp4'
            fixture(src, media=MP4 + b'x'*d.IO_BATCH_SIZE)
            src.write_bytes(src.read_bytes()[:-1])
            with self.assertRaises(ValueError):
                d._decrypt_real_file(src, dst, KEY)

    def test_timing_counts_failed_stage_without_swallowing_error(self):
        metrics = {}
        with self.assertRaises(ValueError):
            with d.timed_stage(metrics, 'flush'):
                raise ValueError('test')
        self.assertGreaterEqual(metrics['flush'], 0)

class FastScanTests(unittest.TestCase):
    def test_plain_inputs_are_classified_without_full_validation_or_network(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            clip = root/'plain.mp4'
            clip.write_bytes(MP4)
            with patch.object(d, 'validate_mp4', side_effect=AssertionError('no full plain scan')), patch.object(d, 'get_session', side_effect=AssertionError('offline')), contextlib.redirect_stdout(io.StringIO()) as log:
                self.assertEqual(d.main([str(root),'--replace-originals','--scan']),0)
            self.assertIn("'plaintext': 1",log.getvalue())
            self.assertEqual(clip.read_bytes(),MP4)

    def test_malformed_ftyp_is_reported_and_left_untouched(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            clip = root/'bad.mp4'
            contents = b'\x00\x00\xff\xffftyp'+b'x'*20
            clip.write_bytes(contents)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(d.main([str(root),'--replace-originals','--scan']),1)
            self.assertEqual(clip.read_bytes(),contents)

    def test_directory_symlinks_and_hidden_entries_not_traversed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            real = root/'clips'
            real.mkdir()
            (real/'plain.mp4').write_bytes(MP4)
            (root/'alias').symlink_to(real,target_is_directory=True)
            hidden = root/'.hidden'
            hidden.mkdir()
            (hidden/'plain.mp4').write_bytes(MP4)
            (root/'._plain.mp4').write_bytes(MP4)
            self.assertEqual(d.find_encrypted_files(root),[real/'plain.mp4'])
