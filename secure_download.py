"""HTTPS-only, atomic downloads with optional SHA-256 integrity verification."""
import hashlib
from pathlib import Path
import tempfile
import urllib.request
from urllib.parse import urlsplit


def require_https(url):
    if not isinstance(url, str) or any(ord(char) <= 32 for char in url):
        raise ValueError('Download URL must use HTTPS')
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.port not in (None, 443)):
        raise ValueError('Download URL must use HTTPS without embedded credentials')
    return url


class HTTPSRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        require_https(newurl)
        return super().redirect_request(request, response, code, message, headers, newurl)


def verify_sha256(path, expected):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise RuntimeError('Model failed SHA-256 verification; download it again from the trusted release')


def download_https(url, destination, expected_sha256=None, timeout=60):
    require_https(url)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(HTTPSRedirects())
    partial = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix='.download', delete=False) as target:
            partial = Path(target.name)
            with opener.open(url, timeout=timeout) as response:
                while chunk := response.read(1024 * 1024):
                    target.write(chunk)
        if expected_sha256 is not None:
            verify_sha256(partial, expected_sha256)
        partial.replace(destination)
        return destination
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)
