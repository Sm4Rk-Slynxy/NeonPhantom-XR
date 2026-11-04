import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from video_pipeline import probe, process
from media_security import local_media_command


class MediaSecurityTests(unittest.TestCase):
    def test_each_input_gets_local_protocol_policy(self):
        args = local_media_command(['ffmpeg', '-i', 'pipe:0', '-i', 'sound.mp4', 'out.mp4'])
        self.assertEqual(args.count('-protocol_whitelist'), 2)
        self.assertEqual(args.count('-format_whitelist'), 2)

    def test_uploaded_playlist_cannot_open_other_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'pretend-video.mp4'
            source.write_text('ffconcat version 1.0\nfile private.mp4\n')
            with self.assertRaisesRegex(RuntimeError, 'whitelist|decode'):
                probe(source)
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                process(source, root / 'result.webm', 'keep')
            self.assertFalse((root / 'result.webm').exists())

    def test_network_protocol_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'whitelist|decode'):
            probe('http://127.0.0.1:9/private.mp4')
