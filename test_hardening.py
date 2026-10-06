import base64
import contextlib
import hashlib
import io
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

from Crypto.Cipher import AES
import tesla_dashcam_decrypt as d


def box(kind, data):
    return struct.pack('>I4s', len(data) + 8, kind) + data


MP4 = box(b'ftyp', b'isom\0\0\0\0isom') + box(b'moov', b'') + box(b'mdat', b'x' * 5000)
KEY = b'0123456789abcdef'


def fixture(path, key=KEY, key_id=1, media=MP4):
    header = bytearray(8192)
    struct.pack_into('>Q', header, 0, len(media))
    struct.pack_into('>I', header, 0x14, 4096)
    struct.pack_into('>I', header, d.KEY_ID_OFFSET, key_id)
    header[d.PUBLIC_KEY_OFFSET:d.PUBLIC_KEY_OFFSET + 65] = b'\x04' + b'p' * 64
    header[d.VIN_OFFSET:d.VIN_OFFSET + 17] = b'123456789ABCDEFGH'
    header[d.WRAPPED_KEY_OFFSET:d.WRAPPED_KEY_OFFSET + 44] = b'w' * 44
    payload = bytearray(header)
    for page, offset in enumerate(range(0, len(media), 4096)):
        material = hashlib.md5(key).digest() + str(page).encode()
        iv = hashlib.md5(material.ljust(32, b'\0')).digest()
        payload.extend(AES.new(key, AES.MODE_CBC, iv).encrypt(media[offset:offset + 4096].ljust(4096, b'\0')))
    path.write_bytes(payload)


class HardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        # macOS /var is a system symlink; use the canonical temp directory.
        self.root = Path(self.temp.name).resolve()
        self.src = self.root / 'src.mp4'
        self.dst = self.root / 'out' / 'result.mp4'
        fixture(self.src)

    def tearDown(self):
        self.temp.cleanup()

    def test_scan_ignores_mac_metadata_and_hidden_system_folders(self):
        (self.root / '._clip.mp4').write_bytes(b'AppleDouble')
        system = self.root / '.Spotlight-V100'
        system.mkdir()
        fixture(system / 'ignored.mp4')
        self.assertEqual(d.find_encrypted_files(self.root), [self.src])

    def test_real_page_roundtrip_and_permissions(self):
        original = self.src.read_bytes()
        self.assertEqual(d.safe_output(self.src, self.dst, KEY), len(MP4))
        self.assertEqual(self.dst.read_bytes(), MP4)
        self.assertEqual(self.src.read_bytes(), original)
        self.assertEqual(self.dst.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.dst.parent.stat().st_mode & 0o777, 0o700)

    def test_wrong_key_never_publishes(self):
        with self.assertRaises(ValueError):
            d.safe_output(self.src, self.dst, b'wrongkey12345678')
        self.assertFalse(self.dst.exists())
        self.assertEqual(list(self.dst.parent.iterdir()), [])

    def test_truncated_payload_never_publishes(self):
        self.src.write_bytes(self.src.read_bytes()[:-1])
        with self.assertRaises(ValueError):
            d.safe_output(self.src, self.dst, KEY)
        self.assertFalse(self.dst.exists())

    def test_existing_never_overwritten(self):
        self.dst.parent.mkdir()
        self.dst.write_bytes(b'keep this')
        with self.assertRaises(FileExistsError):
            d.safe_output(self.src, self.dst, KEY)
        self.assertEqual(self.dst.read_bytes(), b'keep this')

    def test_symlink_output_refused(self):
        other = self.root / 'other'
        other.mkdir()
        self.dst.parent.symlink_to(other, target_is_directory=True)
        with self.assertRaises(ValueError):
            d.safe_output(self.src, self.dst, KEY)
        self.assertEqual(list(other.iterdir()), [])

    def test_colliding_ids_get_separate_requests(self):
        second = self.root / 'second.mp4'
        fixture(second, key_id=2)
        items = [(d.read_file_header(p), p, self.dst) for p in (self.src, second)]
        self.assertEqual(items[0][0]['id'], items[1][0]['id'])
        batches = list(d.collision_safe_batches(items, 20))
        self.assertEqual([len(b) for b in batches], [1, 1])

    def api(self, results, status=200):
        session = Mock()
        response = Mock(status_code=status)
        response.json.return_value = {'results': results}
        session.post.return_value = response
        return session

    def test_api_rejects_unknown_id(self):
        session = self.api([dict(id='other', key=base64.b64encode(KEY).decode())])
        with self.assertRaises(ValueError):
            d.fetch_keys_batch(session, ['requested'])

    def test_api_rejects_duplicate_response_id(self):
        result = dict(id='requested', key=base64.b64encode(KEY).decode())
        with self.assertRaises(ValueError):
            d.fetch_keys_batch(self.api([result, result]), ['requested'])

    def test_invalid_key_rejected(self):
        with self.assertRaises(ValueError):
            d.fetch_keys_batch(self.api([dict(id='x', key='AA==')]), ['x'])

    def test_redirects_disabled(self):
        session = self.api([], 302)
        with self.assertRaises(RuntimeError):
            d.fetch_keys_batch(session, ['x'])
        self.assertFalse(session.post.call_args.kwargs['allow_redirects'])

    def test_session_ignores_proxy_environment(self):
        with d.get_session('dummy') as session:
            self.assertFalse(session.trust_env)

    def test_mp4_structure(self):
        self.dst.parent.mkdir()
        self.dst.write_bytes(MP4[:-2])
        with self.assertRaises(ValueError):
            d.validate_mp4(self.dst)

    def test_scan_is_offline_and_does_not_write(self):
        with patch.object(d, 'get_session', side_effect=AssertionError('network')), patch.object(d, 'prompt_token', side_effect=AssertionError('token')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(d.main([str(self.root), str(self.root.parent / (self.root.name + '-out')), '--scan']), 0)
        self.assertFalse((self.root.parent / (self.root.name + '-out')).exists())

    def test_missing_keys_count_as_failure(self):
        destination = self.root.parent / (self.root.name + '-out')
        with patch.object(d, 'get_session', return_value=self.api([])), patch.object(d, 'prompt_token', return_value='dummy'), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(d.main([str(self.root), str(destination)]), 1)
        self.assertIn("'failed': 1", out.getvalue())
        self.assertFalse(destination.exists())

    def test_overlap_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            d.main([str(self.root), str(self.root / 'out'), '--scan'])

    def test_plaintext_not_sent_for_keys(self):
        self.src.write_bytes(MP4)
        with patch.object(d, 'get_session', side_effect=AssertionError('network')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(d.main([str(self.root), str(self.root.parent / (self.root.name + '-out'))]), 0)

    def test_full_main_collision_roundtrip(self):
        second = self.root / 'second.mp4'
        fixture(second, b'anotherkey123456', key_id=2)
        destination = self.root.parent / (self.root.name + '-out')
        session = self.api([])
        def request(url, **kwargs):
            item = kwargs['json']['items'][0]
            key = KEY if item['key_id'] == 1 else b'anotherkey123456'
            response = Mock(status_code=200)
            response.json.return_value = {'results': [dict(id=item['id'], key=base64.b64encode(key).decode())]}
            return response
        session.post.side_effect = request
        try:
            with patch.object(d, 'get_session', return_value=session), patch.object(d, 'prompt_token', return_value='dummy'), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(d.main([str(self.root), str(destination)]), 0)
            self.assertEqual(session.post.call_count, 2)
            self.assertEqual((destination / 'src.mp4').read_bytes(), MP4)
            self.assertEqual((destination / 'second.mp4').read_bytes(), MP4)
            self.assertIn("'decrypted': 2", out.getvalue())
            with patch.object(d, 'get_session', side_effect=AssertionError('no request needed')), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(d.main([str(self.root), str(destination)]), 0)
        finally:
            import shutil
            shutil.rmtree(destination, ignore_errors=True)

    def test_rate_limit_retry_is_bounded(self):
        session = self.api([], 429)
        with patch.object(d.time, 'sleep') as sleep, self.assertRaises(RuntimeError):
            d.fetch_keys_batch(session, ['x'])
        self.assertEqual(session.post.call_count, 4)
        self.assertEqual(sleep.call_count, 3)

    def test_remux_temp_has_mp4_suffix(self):
        def fake_remux(src, dst):
            self.assertEqual(dst.suffix, '.mp4')
            dst.write_bytes(src.read_bytes())
        with patch.object(d, 'remux_mp4', side_effect=fake_remux):
            d.safe_output(self.src, self.dst, KEY, remux=True)
        self.assertEqual(self.dst.read_bytes(), MP4)
        self.assertEqual(list(self.dst.parent.iterdir()), [self.dst])


if __name__ == '__main__':
    unittest.main()
