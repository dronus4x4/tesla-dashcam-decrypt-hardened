"""Synthetic protocol fixtures only; no real vehicle metadata or footage."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from test_hardening import fixture, KEY, MP4
root = Path(sys.argv[1]).resolve()
root.mkdir(parents=True, exist_ok=True)
source = root / 'input'
source.mkdir(exist_ok=True)
fixture(source / 'clip.mp4')
fixture(source / 'second.mp4', key_id=2)
(source / '._clip.mp4').write_bytes(b'AppleDouble metadata')
(root / 'plain.bin').write_bytes(MP4)
(root / 'key.bin').write_bytes(KEY)
