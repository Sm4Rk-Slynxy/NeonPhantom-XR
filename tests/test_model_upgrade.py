import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cutout_engines import validate_options, as_alpha, WeVisOneEngine
from video_pipeline import process, probe


class ModelUpgradeTests(unittest.TestCase):
    def test_bad_subject_regions_and_unknown_models_are_rejected(self):
        for box in ([.6, 0, .4, 1], [0, 0, 1, float('nan')], [-1, 0, 1, 1]):
            with self.assertRaises(ValueError):
                validate_options('matanyone2', 'person', box)
        with self.assertRaises(ValueError):
            validate_options('unknown', 'person', None)
        with self.assertRaises(ValueError):
            validate_options('wevisone-2b', ' ', None)

    def test_wevisone_absent_target_and_soft_alpha(self):
        from types import SimpleNamespace
        import numpy as np
        from PIL import Image
        engine = WeVisOneEngine.__new__(WeVisOneEngine)
        engine.subject = 'penguin'
        engine.engine = SimpleNamespace(predict=lambda *a, **kw: SimpleNamespace(masks=[]))
        self.assertEqual(engine.matte(Image.new('RGB', (8, 8))).getextrema(), (0, 0))
        engine.engine.predict = lambda *a, **kw: SimpleNamespace(masks=[np.full((8, 8), .25), np.full((8, 8), .5)])
        self.assertEqual(engine.matte(Image.new('RGB', (8, 8))).getextrema(), (128, 128))
        with self.assertRaisesRegex(RuntimeError, 'invalid alpha'):
            as_alpha(np.full((8, 8), np.nan), (8, 8))

    def test_explicit_preview_and_full_import_keep_distinct_lengths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root/'source.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'testsrc2=size=96x128:rate=30:duration=4.2', '-c:v', 'libx264', str(source)], check=True)
            with contextlib.redirect_stdout(io.StringIO()):
                process(source, root/'preview.webm', 'keep', preview_seconds=3)
                process(source, root/'full.webm', 'keep')
            self.assertAlmostEqual(float(probe(root/'preview.webm')[0]['format']['duration']), 3, delta=.05)
            self.assertGreaterEqual(float(probe(root/'full.webm')[0]['format']['duration'])+.001, 4.2)

    def test_model_alpha_is_composited_onto_original_rgb_and_duration_preserved(self):
        from PIL import Image
        class FakeEngine:
            provider = 'test'
            def matte(self, image):
                matte = Image.new('L', image.size, 0)
                matte.paste(128, (24, 24, 72, 104))
                return matte
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root/'red.mp4'; out = root/'cutout.webm'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'color=red:size=96x128:rate=30:duration=0.2', '-c:v', 'libx264', str(source)], check=True)
            with patch('cutout_engines.load_engine', return_value=FakeEngine()), contextlib.redirect_stdout(io.StringIO()):
                process(source, out, 'ai')
            pixels = subprocess.run(['ffmpeg', '-v', 'error', '-c:v', 'libvpx-vp9', '-i', str(out),
                                     '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-'], capture_output=True, check=True).stdout
            center = (60*96+48)*4
            self.assertGreater(pixels[center], 230)
            self.assertLess(pixels[center+1], 20)
            self.assertAlmostEqual(pixels[center+3], 128, delta=2)
            self.assertEqual(pixels[3], 0)
            self.assertGreaterEqual(float(probe(out)[0]['format']['duration'])+.001, .2)

    def test_optional_model_missing_fails_without_silent_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root/'source.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'color=red:size=96x128:rate=30:duration=0.2', '-c:v', 'libx264', str(source)], check=True)
            with patch('model_manager.python_for', return_value=root/'missing-python'):
                with self.assertRaisesRegex(RuntimeError, 'not installed'):
                    process(source, root/'bad.webm', 'ai', model='matanyone2')
            self.assertFalse((root/'bad.webm').exists())


if __name__ == '__main__':
    unittest.main()
