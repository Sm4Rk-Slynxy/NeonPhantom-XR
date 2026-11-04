import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video_pipeline import process, has_alpha, frame_rate, probe


class PipelineTests(unittest.TestCase):
    def test_alpha_detection(self):
        for stream in ({'pix_fmt': 'yuva420p'}, {'pix_fmt': 'yuv420p', 'tags': {'alpha_mode': '1'}}, {'pix_fmt': 'gbrap10le'}, {'pix_fmt': 'rgba'}):
            self.assertTrue(has_alpha(stream))
        self.assertFalse(has_alpha({'pix_fmt': 'yuv420p'}))

    def test_invalid_frame_rates(self):
        for rate in ('0/0', 'nan/1', '0/1', 'garbage'):
            self.assertEqual(frame_rate({'avg_frame_rate': rate}), 30)
        self.assertAlmostEqual(frame_rate({'avg_frame_rate': '24000/1001'}), 23.976023976)

    def test_duration_padding_with_source_and_output_on_different_drives(self):
        # The application stores videos on a separate mounted drive. Atomic replace
        # must use a temporary file on that destination filesystem, not /tmp.
        destination = Path(__file__).resolve().parents[1] / 'samples'
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory(dir=destination) as library:
            source = Path(temp) / 'audio-tail.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0x00FF00:s=96x128:r=30:d=0.2', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono:d=0.4', '-c:v', 'libx264', '-c:a', 'aac', str(source)], check=True)
            original = float(probe(source)[0]['format']['duration'])
            out = Path(library) / 'full.webm'
            with contextlib.redirect_stdout(io.StringIO()) as events:
                process(source, out, 'keep')
            self.assertIn('Preserving full video duration', events.getvalue())
            self.assertGreaterEqual(float(probe(out)[0]['format']['duration']) + 0.001, original)
            self.assertTrue(out.with_name('thumb_full.png').exists())

    def test_full_duration_at_high_frame_rate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / '60fps.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0x00FF00:s=96x128:r=60:d=1.017', '-c:v', 'libx264', str(source)], check=True)
            original = float(probe(source)[0]['format']['duration'])
            # The old fps-to-frame sequence could round this ending down to 1 second.
            for mode in ('green', 'keep'):
                with contextlib.redirect_stdout(io.StringIO()):
                    process(source, root / f'{mode}.webm', mode)
                converted = float(probe(root / f'{mode}.webm')[0]['format']['duration'])
                self.assertGreaterEqual(converted + 0.001, original)
                self.assertLess(converted - original, 0.075)

    @unittest.skipUnless(__import__('os').environ.get('DESKDANCE_TEST_AI') == '1', 'AI duration test requires rembg and a downloaded model')
    def test_fast_ai_preserves_duration_and_reports_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'fast.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=96x128:rate=60:duration=0.217', '-c:v', 'libx264', str(source)], check=True)
            original = float(probe(source)[0]['format']['duration'])
            with contextlib.redirect_stdout(io.StringIO()) as events:
                process(source, root / 'fast.webm', 'ai', quality='fast')
            result = json.loads(events.getvalue().splitlines()[-1])['result']
            self.assertEqual(result['quality'], 'fast')
            self.assertGreaterEqual(result['duration_s'] + 0.001, original)
            self.assertLess(result['duration_s'] - original, 0.1)
            self.assertEqual(frame_rate(probe(root / 'fast.webm')[1]), 12)

    @unittest.skipUnless(__import__('os').environ.get('DESKDANCE_TEST_AI') == '1', 'AI duration test requires rembg and a downloaded model')
    def test_ai_preserves_full_duration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'short.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0x00FF00:s=96x128:r=60:d=0.117', '-c:v', 'libx264', str(source)], check=True)
            original = float(probe(source)[0]['format']['duration'])
            with contextlib.redirect_stdout(io.StringIO()):
                process(source, root / 'ai.webm', 'ai')
            converted = float(probe(root / 'ai.webm')[0]['format']['duration'])
            self.assertGreaterEqual(converted + 0.001, original)
            self.assertLess(converted - original, 0.075)

    def test_conversion_alpha_and_invalid_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Real green video with an opaque red foreground, not a mocked encoder.
            source = root / 'source.mov'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=green:s=96x128:r=12:d=0.5', '-vf', 'drawbox=x=24:y=24:w=48:h=80:color=red:t=fill', '-c:v', 'png', str(source)], check=True)
            for mode in ('green', 'keep'):
                out = root / f'{mode}.webm'
                with contextlib.redirect_stdout(io.StringIO()) as events:
                    process(source, out, mode)
                result = json.loads(events.getvalue().splitlines()[-1])['result']
                self.assertEqual(result['has_alpha'], mode == 'green')
                self.assertTrue(out.with_name(f'thumb_{mode}.png').exists())
                _, stream = probe(out)
                self.assertEqual(has_alpha(stream), mode == 'green')
                if mode == 'green':
                    pixels = subprocess.run(['ffmpeg', '-v', 'error', '-c:v', 'libvpx-vp9', '-i', str(out), '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-'], capture_output=True, check=True).stdout
                    self.assertEqual(pixels[3], 0)  # actual background alpha
                    self.assertEqual(pixels[(10 * 96 + 10) * 4 + 3], 0)
                    self.assertEqual(pixels[(60 * 96 + 48) * 4 + 3], 255)  # subject stays opaque
            with contextlib.redirect_stdout(io.StringIO()):
                process(root / 'green.webm', root / 'preserved.webm', 'auto')
            self.assertTrue(has_alpha(probe(root / 'preserved.webm')[1]))
            alpha = subprocess.run(['ffmpeg', '-v', 'error', '-c:v', 'libvpx-vp9', '-i', str(root / 'preserved.webm'), '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-'], capture_output=True, check=True).stdout
            self.assertEqual(alpha[3], 0)
            self.assertEqual(alpha[(60 * 96 + 48) * 4 + 3], 255)
            with self.assertRaisesRegex(ValueError, 'no alpha'):
                process(source, root / 'invalid.webm', 'alpha')
            self.assertFalse((root / 'invalid.webm').exists())
            broken = root / 'broken.m4s'; broken.write_text('not a video')
            with self.assertRaises(RuntimeError):
                process(broken, root / 'bad.webm')


if __name__ == '__main__':
    unittest.main()
