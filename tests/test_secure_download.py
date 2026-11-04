import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request
from secure_download import HTTPSRedirects, download_https, require_https


class DownloadSecurityTests(unittest.TestCase):
    def test_initial_urls_require_https_and_no_embedded_credentials(self):
        for url in ('http://example.test/model','file:///secret','ftp://example.test/model',
                    'https://user:password@example.test/model','https://example.test:80/model',
                    'https:///missing-host','https://example.test/\nheader'):
            with self.subTest(url=url), self.assertRaises(ValueError):require_https(url)
        self.assertEqual(require_https('https://example.test/model?v=1'),'https://example.test/model?v=1')

    def test_redirects_cannot_downgrade_or_open_local_files(self):
        handler=HTTPSRedirects();request=Request('https://example.test/source')
        for url in ('http://example.test/target','file:///secret','ftp://example.test/target'):
            with self.assertRaises(ValueError):handler.redirect_request(request,None,302,'Found',{},url)
        redirect=handler.redirect_request(request,None,302,'Found',{},'https://cdn.example.test/target')
        self.assertEqual(redirect.full_url,'https://cdn.example.test/target')

    def test_verified_download_replaces_only_after_success(self):
        content=b'verified model';expected=hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'model';path.write_bytes(b'old model')
            with patch('secure_download.urllib.request.build_opener') as build:
                build.return_value.open.return_value=io.BytesIO(content)
                download_https('https://example.test/model',path,expected)
            self.assertEqual(path.read_bytes(),content)
            self.assertEqual(list(Path(folder).iterdir()),[path])

    def test_bad_digest_and_interrupted_transport_preserve_existing_model(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'model';path.write_bytes(b'good existing model')
            with patch('secure_download.urllib.request.build_opener') as build:
                build.return_value.open.return_value=io.BytesIO(b'corrupt')
                with self.assertRaisesRegex(RuntimeError,'SHA-256'):
                    download_https('https://example.test/model',path,'0'*64)
                build.return_value.open.side_effect=TimeoutError('interrupted')
                with self.assertRaises(TimeoutError):download_https('https://example.test/model',path)
            self.assertEqual(path.read_bytes(),b'good existing model')
            self.assertEqual(list(Path(folder).iterdir()),[path])

    def test_tampered_matanyone_checkpoint_is_rejected_before_loading(self):
        import model_manager
        from cutout_engines import MatAnyoneEngine
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'matanyone2.pth';path.write_bytes(b'untrusted checkpoint')
            with patch.object(model_manager,'model_path',return_value=Path(folder)):
                with self.assertRaisesRegex(RuntimeError,'SHA-256'):MatAnyoneEngine()
