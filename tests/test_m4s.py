import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video_pipeline import process, probe


def make_dash(root):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'testsrc2=size=96x128:rate=12:duration=2.25', '-c:v', 'libx264',
                    '-g', '12', '-keyint_min', '12', '-sc_threshold', '0', '-bf', '0',
                    '-an', '-f', 'dash', '-seg_duration', '1', '-init_seg_name', 'init.mp4',
                    '-media_seg_name', 'chunk-$Number%05d$.m4s', str(root / 'video.mpd')], check=True)
    return root / 'init.mp4', sorted(root.glob('chunk-*.m4s'))


class M4STests(unittest.TestCase):
    def test_segments_preserve_whole_video_and_normalize_late_start(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            init, chunks = make_dash(root)
            self.assertEqual(len(chunks), 3)
            with contextlib.redirect_stdout(io.StringIO()):
                process(chunks[0], root / 'full.webm', 'keep', init, chunks[1:])
                process(chunks[-1], root / 'last.webm', 'keep', init)
            whole = float(probe(root / 'full.webm')[0]['format']['duration'])
            last = float(probe(root / 'last.webm')[0]['format']['duration'])
            self.assertGreaterEqual(whole + 0.001, 2.25)
            self.assertLess(whole, 2.34)
            self.assertGreaterEqual(last + 0.001, 0.25)
            self.assertLess(last, 0.34)  # no two-second freeze from the original timestamp

    def test_incomplete_or_reordered_segments_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            init, chunks = make_dash(root)
            with self.assertRaisesRegex(RuntimeError, 'initialization'):
                process(chunks[0], root / 'missing-init.webm', 'keep')
            with self.assertRaisesRegex(ValueError, 'out of order'):
                process(chunks[1], root / 'backwards.webm', 'keep', init, [chunks[0]])
            with self.assertRaisesRegex(ValueError, 'timeline gap'):
                process(chunks[0], root / 'gap.webm', 'keep', init, [chunks[2]])
            with self.assertRaisesRegex(ValueError, 'Missing or empty'):
                process(chunks[0], root / 'missing.webm', 'keep', root / 'absent.mp4')

    def test_self_contained_m4s_works_without_init(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'standalone.m4s'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'testsrc2=size=96x128:rate=12:duration=0.5', '-c:v', 'libx264',
                            '-movflags', '+frag_keyframe+empty_moov', '-f', 'mp4', str(source)], check=True)
            with contextlib.redirect_stdout(io.StringIO()):
                process(source, root / 'converted.webm', 'keep')
            self.assertGreaterEqual(float(probe(root / 'converted.webm')[0]['format']['duration']) + 0.001, 0.5)


if __name__ == '__main__':
    unittest.main()
