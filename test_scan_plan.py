import contextlib
import copy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import tesla_dashcam_decrypt as d
from test_hardening import fixture, KEY, MP4


class Session:
    def __init__(self): self.headers = {}
    def close(self): pass


class ScanPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source'
        self.source.mkdir()
        self.src = self.source / 'encrypted.mp4'
        fixture(self.src)
        self.original = self.src.read_bytes()
        self.plain = self.source / 'readable.mp4'
        self.plain.write_bytes(MP4)
        self.args = [str(self.source), '--replace-originals']
        plans = []
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(d.main(self.args + ['--scan'], on_scan=plans.append), 0)
        self.plan = plans[0]

    def tearDown(self): self.temp.cleanup()

    def run_plan(self, plan=None, args=None, keys=True):
        with patch.object(d, 'find_encrypted_files', side_effect=AssertionError('must not traverse again')), patch.object(d, 'prompt_token', return_value='dummy'), patch.object(d, 'get_session', return_value=Session()), patch.object(d, 'fetch_keys_batch', return_value={self.plan['items'][0]['header']['id']:KEY} if keys else {}), contextlib.redirect_stdout(io.StringIO()) as output:
            code = d.main(args or self.args, scan_plan=plan or self.plan)
        return code, output.getvalue()

    def test_reuses_scan_without_traversal_or_readable_file_validation(self):
        validate = d.validate_mp4
        def verify(path):
            self.assertNotEqual(path, self.plain, 'readable files must not be rechecked')
            return validate(path)
        with patch.object(d, 'validate_mp4', side_effect=verify):
            code, log = self.run_plan()
        self.assertEqual(code, 0)
        self.assertEqual(self.src.read_bytes(), MP4)
        self.assertEqual(self.plain.read_bytes(), MP4)
        self.assertIn("'processed': 1", log)
        self.assertIn("'pending': 0", log)
        self.assertNotIn('Checking clips:', log)

    def test_changed_source_not_replaced(self):
        fixture(self.src, key_id=2)
        changed = self.src.read_bytes()
        self.assertEqual(self.run_plan()[0], 1)
        self.assertEqual(self.src.read_bytes(), changed)
        self.assertEqual(sorted(p.name for p in self.source.iterdir()), ['encrypted.mp4','readable.mp4'])

    def test_new_file_added_after_scan_waits_for_next_scan(self):
        extra = self.source / 'new.mp4'
        fixture(extra, key_id=2)
        original = extra.read_bytes()
        self.assertEqual(self.run_plan()[0], 0)
        self.assertEqual(extra.read_bytes(), original)

    def test_deleted_source_fails_safely(self):
        self.src.unlink()
        self.assertEqual(self.run_plan()[0], 1)
        self.assertEqual(list(self.source.iterdir()), [self.plain])

    def test_changed_root_or_mode_rejected_before_network(self):
        for field, value in [('root', '/different'), ('replace', False), ('root_identity', [-1,-1])]:
            plan = copy.deepcopy(self.plan)
            plan[field] = value
            with patch.object(d, 'get_session', side_effect=AssertionError('no network')), self.assertRaises(ValueError):
                self.run_plan(plan)

    def test_path_traversal_and_duplicate_items_rejected(self):
        plan = copy.deepcopy(self.plan)
        plan['items'][0]['relative'] = '../outside.mp4'
        with self.assertRaises(ValueError): self.run_plan(plan)
        plan = copy.deepcopy(self.plan)
        plan['items'] *= 2
        plan['counts']['pending'] = 2
        plan['counts']['encrypted'] = 2
        with self.assertRaises(ValueError): self.run_plan(plan)
        self.assertEqual(self.src.read_bytes(), self.original)

    def test_missing_key_counts_remaining_and_preserves_source(self):
        code, log = self.run_plan(keys=False)
        self.assertEqual(code, 1)
        self.assertIn("'processed': 1", log)
        self.assertIn("'pending': 0", log)
        self.assertEqual(self.src.read_bytes(), self.original)

    def test_failed_batch_advances_progress_without_writing(self):
        with patch.object(d, 'find_encrypted_files', side_effect=AssertionError('no rescan')), patch.object(d, 'prompt_token', return_value='dummy'), patch.object(d, 'get_session', return_value=Session()), patch.object(d, 'fetch_keys_batch', side_effect=RuntimeError('failure')), contextlib.redirect_stdout(io.StringIO()) as log:
            self.assertEqual(d.main(self.args, scan_plan=self.plan), 1)
        self.assertIn("'processed': 1", log.getvalue())
        self.assertIn("'pending': 0", log.getvalue())
        self.assertEqual(self.src.read_bytes(), self.original)

    def test_copy_mode_checks_scanned_source_and_keeps_original(self):
        output = self.root / 'output'
        args = [str(self.source),str(output)]
        plans = []
        with contextlib.redirect_stdout(io.StringIO()): d.main(args + ['--scan'], on_scan=plans.append)
        self.assertEqual(self.run_plan(plans[0],args)[0], 0)
        self.assertEqual((output / self.src.name).read_bytes(), MP4)
        self.assertEqual(self.src.read_bytes(), self.original)

    def test_expired_token_stops_further_batches(self):
        second = self.source / 'second.mp4'
        fixture(second, key_id=2)
        plans=[]
        with contextlib.redirect_stdout(io.StringIO()): d.main(self.args + ['--scan'], on_scan=plans.append)
        with patch.object(d, 'prompt_token', return_value='dummy'), patch.object(d, 'get_session', return_value=Session()), patch.object(d, 'fetch_keys_batch', side_effect=d.APIStatusError(401)) as fetch, contextlib.redirect_stdout(io.StringIO()) as log:
            self.assertEqual(d.main(self.args, scan_plan=plans[0]), 1)
        self.assertEqual(fetch.call_count,1)
        self.assertIn("'pending': 0",log.getvalue())
        self.assertEqual(self.src.read_bytes(),self.original)

    def test_duplicate_ids_fill_batches_without_ambiguity(self):
        items = [({'id':uid}, number, None) for uid in ['a','b','c'] for number in range(10)]
        batches=list(d.collision_safe_batches(items,20))
        self.assertEqual(len(batches),10)
        self.assertEqual(sum(map(len,batches)),30)
        self.assertTrue(all(len({i[0]['id'] for i in batch}) == len(batch) for batch in batches))
        self.assertEqual(sorted((i[0]['id'],i[1]) for batch in batches for i in batch),sorted((i[0]['id'],i[1]) for i in items))

    def test_nested_symlink_swap_refused(self):
        folder = self.source / 'nested'
        folder.mkdir()
        nested = folder / 'clip.mp4'
        fixture(nested, key_id=2)
        plans=[]
        with contextlib.redirect_stdout(io.StringIO()): d.main(self.args + ['--scan'], on_scan=plans.append)
        moved = self.root / 'moved'
        folder.rename(moved)
        folder.symlink_to(moved, target_is_directory=True)
        original = (moved / 'clip.mp4').read_bytes()
        self.assertEqual(self.run_plan(plans[0])[0],1)
        self.assertEqual((moved / 'clip.mp4').read_bytes(),original)

if __name__ == '__main__': unittest.main()
