"""Paired HTTPS playback and derived-video conversion companion for Quest Browser on the local network."""
import argparse
from collections import defaultdict, deque
import hashlib
import hmac
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
from urllib.parse import unquote, urlsplit

from export_video import EXPORT_VERSION, export_video
from stereo_jobs import StereoJobs

ROOT = Path(__file__).resolve().parents[1]
IDENTIFIER = re.compile(r'^[a-zA-Z0-9_-]{1,80}$')


def local_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            # Connecting a UDP socket selects a local route; no data is sent.
            route.connect(('192.0.2.1', 9))
            return route.getsockname()[0]
    except OSError:
        return '127.0.0.1'


def ensure_certificate(folder, address):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt':
        folder.chmod(0o700)
    cert, key = folder/'server.crt', folder/'server.key'
    identity = folder/'address.txt'
    if cert.is_file() and key.is_file() and identity.is_file() and identity.read_text() == address:
        if os.name != 'nt':
            key.chmod(0o600)
        return cert, key
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        from datetime import datetime, timedelta, timezone
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'NeonPhantom XR local Quest viewer')])
        now = datetime.now(timezone.utc)
        names = [x509.DNSName('localhost'), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]
        if address != '127.0.0.1':
            names.append(x509.IPAddress(ipaddress.ip_address(address)))
        public = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private.public_key())
                  .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
                  .not_valid_after(now+timedelta(days=365)).add_extension(x509.SubjectAlternativeName(names), False)
                  .sign(private, hashes.SHA256()))
        # Private from creation; avoid the world-readable interval before chmod.
        with os.fdopen(os.open(key, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'wb') as stream:
            stream.write(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        cert.write_bytes(public.public_bytes(serialization.Encoding.PEM))
    except ImportError:
        if not shutil.which('openssl'):
            raise RuntimeError('HTTPS setup needs cryptography or OpenSSL. Install requirements-quest.txt, or supply --cert and --key.')
        san = f'IP:127.0.0.1,DNS:localhost' + (f',IP:{address}' if address != '127.0.0.1' else '')
        result = subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','365',
                                 '-keyout',str(key),'-out',str(cert),'-subj','/CN=NeonPhantom XR local Quest viewer',
                                 '-addext',f'subjectAltName={san}'],capture_output=True,text=True)
        if result.returncode:
            raise RuntimeError(f'Cannot create local HTTPS certificate: {result.stderr[-1500:]}')
    if os.name != 'nt':
        key.chmod(0o600)
    identity.write_text(address)
    return cert, key


class Library:
    def __init__(self, state, media, exports):
        self.state, self.media, self.exports = Path(state), Path(media).resolve(), Path(exports)
        self.exports.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.cards, self.failures, self.phase = [], [], 'Preparing library'
        self.stopping = threading.Event()

    def snapshot(self):
        with self.lock:
            return {'cards': list(self.cards), 'errors': list(self.failures), 'phase': self.phase}

    def refresh(self):
        try:
            records = json.loads(self.state.read_text()).get('cards', []) if self.state.exists() else []
        except (OSError, ValueError) as exc:
            with self.lock:
                self.phase = 'Cannot read NeonPhantom XR library'
                self.failures = [str(exc)]
            return
        published, failures = [], []
        for record in records:
            if self.stopping.is_set():
                break
            identifier = str(record.get('id', ''))
            if not IDENTIFIER.fullmatch(identifier):
                continue
            source = (self.media / str(record.get('file', ''))).resolve()
            if not source.is_relative_to(self.media) or not source.is_file():
                continue
            output, metadata = self.exports/f'{identifier}.mp4', self.exports/f'{identifier}.json'
            try:
                info = source.stat()
                signature = hashlib.sha256(f'{source}:{info.st_size}:{info.st_mtime_ns}:{EXPORT_VERSION}'.encode()).hexdigest()
                saved = json.loads(metadata.read_text()) if metadata.is_file() else {}
                if saved.get('signature') != signature or not output.is_file():
                    with self.lock:
                        self.phase = 'Preparing ' + str(record.get('name') or source.name)
                    saved = {**export_video(source, output), 'signature': signature}
                    temp = metadata.with_suffix('.tmp')
                    temp.write_text(json.dumps(saved)); temp.replace(metadata)
                card = {key: saved[key] for key in ('width','height','duration_s','has_alpha','format')}
                card.update(id=identifier, name=record.get('name') or source.name,
                            url=f'/media/{identifier}.mp4?v={signature[:12]}')
                card['projection']=record.get('projection','flat')
                if card['projection']=='vr180-sbs':card['stereo_layout']='sbs-full'
                published.append(card)
                with self.lock:
                    self.cards = [current for current in self.cards if current['id'] != identifier] + [card]
            except Exception as exc:
                failures.append(f'{record.get("name") or source.name}: {exc}')
        with self.lock:
            self.cards, self.failures = published, failures
            self.phase = 'Ready' if published else 'Add a video in NeonPhantom XR to begin'

    def source(self, identifier):
        if not isinstance(identifier,str) or not IDENTIFIER.fullmatch(identifier):
            raise ValueError('Select a video from the NeonPhantom XR library')
        records = json.loads(self.state.read_text()).get('cards',[])
        record = next((card for card in records if card.get('id')==identifier),None)
        if record is None:raise ValueError('Source is no longer in the NeonPhantom XR library')
        source = (self.media/str(record.get('file',''))).resolve()
        if not source.is_relative_to(self.media) or not source.is_file():
            raise ValueError('Source video is unavailable')
        return source,str(record.get('name') or source.name)

    def watch(self):
        while not self.stopping.is_set():
            self.refresh()
            self.stopping.wait(15)


class CompanionServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, library, site, max_connections=32):
        self.library, self.site = library, Path(site).resolve()
        self.token = secrets.token_urlsafe(32)
        self.pair_code = f'{secrets.randbelow(1000000):06}'
        self.attempts = defaultdict(deque)
        self.auth_lock = threading.Lock()
        self.stereo = StereoJobs(library)
        # Bound workers before TLS handshakes/headers so stalled LAN connections
        # cannot create an unbounded number of threads. Normal streaming stays concurrent.
        self.request_slots = threading.BoundedSemaphore(max_connections)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.request_slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = 'NeonPhantomXR/0.1'

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, format, *args):
        # Pairing material and personal filenames must never enter HTTP access logs.
        pass

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Permissions-Policy', 'xr-spatial-tracking=(self), camera=(), microphone=()')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'")
        super().end_headers()

    def json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def authorized(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie',''))
            value = cookie.get('deskdance_quest')
            return value is not None and hmac.compare_digest(value.value, self.server.token)
        except (ValueError, TypeError, CookieError):
            return False

    def catalogue(self):
        data = self.server.library.snapshot()
        base_ids = {card['id'] for card in data['cards']}
        data['cards'] += self.server.stereo.cards(base_ids)
        data['stereo_jobs'] = [job for job in self.server.stereo.snapshot() if job['source_id'] in base_ids or job['state']=='running']
        return data

    def do_POST(self):
        path = urlsplit(self.path).path
        origin = self.headers.get('Origin')
        if origin and origin != f'https://{self.headers.get("Host", "")}':
            return self.json(403, {'error':'Use the viewer on this server'})
        if path == '/api/stereo' or re.fullmatch(r'/api/stereo/sbs_[a-f0-9]{12}/cancel',path):
            if not self.authorized():return self.json(401,{'error':'Pair this browser with the PC first'})
            try:
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 1024:raise ValueError('Invalid conversion request')
                request = json.loads(self.rfile.read(size))
                if not isinstance(request,dict):raise ValueError('Invalid conversion request')
                if path.endswith('/cancel'):
                    self.server.stereo.cancel(path.split('/')[3]);return self.json(200,{'cancelled':True})
                job = self.server.stereo.start(request.get('card_id'),request.get('strength',.015),request.get('device','auto'))
                return self.json(202,job)
            except (ValueError,TypeError,FileNotFoundError) as error:return self.json(400,{'error':str(error)})
            except RuntimeError as error:return self.json(409,{'error':str(error)})
        if path != '/api/pair':
            return self.json(405, {'error':'This viewer accepts pairing and stereo conversion requests'})
        with self.server.auth_lock:
            attempts = self.server.attempts[self.client_address[0]]
            now = time.monotonic()
            while attempts and attempts[0] < now-60:
                attempts.popleft()
            if len(attempts) >= 5:
                return self.json(429, {'error':'Too many pairing attempts. Wait one minute.'})
            attempts.append(now)
        try:
            size = int(self.headers.get('Content-Length','0'))
            if not 0 < size <= 1024:
                raise ValueError('Invalid pairing request')
            request = json.loads(self.rfile.read(size))
            if not isinstance(request, dict):
                raise ValueError('Invalid pairing request')
            valid = hmac.compare_digest(str(request.get('code','')),self.server.pair_code) or hmac.compare_digest(str(request.get('token','')),self.server.token)
        except (ValueError, TypeError):
            valid = False
        if not valid:
            return self.json(403, {'error':'Pairing code did not match. Read the code on the PC.'})
        self.send_response(200)
        self.send_header('Set-Cookie',f'deskdance_quest={self.server.token}; HttpOnly; Secure; SameSite=Strict; Path=/')
        body=b'{"paired":true}'
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.end_headers();self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if path == '/api/library':
            if not self.authorized():
                return self.json(401, {'error':'Pair this browser with the PC first'})
            return self.json(200, self.catalogue())
        if path.startswith('/api/'):
            return self.json(404, {'error':'Unknown viewer endpoint'})
        if path.startswith('/downloads/'):
            if not self.authorized():return self.json(401,{'error':'Pair this browser with the PC first'})
            match = re.fullmatch(r'/downloads/(sbs_[a-f0-9]{12})\.mp4',path)
            try:
                if not match:raise ValueError('Invalid stereo video')
                return self.file(self.server.stereo.file(match[1],download=True),'video/mp4',download=True)
            except (ValueError,FileNotFoundError):return self.json(404,{'error':'Stereo video unavailable'})
        if path.startswith('/media/'):
            if not self.authorized():
                return self.json(401, {'error':'Pair this browser with the PC first'})
            match = re.fullmatch(r'/media/([a-zA-Z0-9_-]{1,80})\.mp4',path)
            if not match or not any(card['id']==match[1] for card in self.catalogue()['cards']):
                return self.json(404, {'error':'Video unavailable'})
            if match[1].startswith('sbs_'):
                try:return self.file(self.server.stereo.file(match[1]),'video/mp4')
                except (ValueError,FileNotFoundError):return self.json(404,{'error':'Stereo video unavailable'})
            return self.file(self.server.library.exports/f'{match[1]}.mp4', 'video/mp4')
        relative = 'index.html' if path == '/' else path.lstrip('/')
        target = (self.server.site/relative).resolve()
        if not target.is_relative_to(self.server.site) or not target.is_file():
            return self.json(404, {'error':'File not found'})
        mime = {'.js':'text/javascript', '.mjs':'text/javascript', '.css':'text/css'}.get(target.suffix.lower())
        return self.file(target, mime or mimetypes.guess_type(target.name)[0] or 'application/octet-stream')

    def file(self, path, mime, download=False):
        size = path.stat().st_size
        start, end, status = 0, size-1, 200
        header = self.headers.get('Range')
        if header:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)',header)
            try:
                if not match or not any(match.groups()):
                    raise ValueError()
                if match[1]:
                    start = int(match[1]);end = min(int(match[2]),size-1) if match[2] else size-1
                else:
                    start = max(0,size-int(match[2]))
                if start > end or start >= size or (not match[1] and int(match[2]) == 0):
                    raise ValueError()
                status = 206
            except ValueError:
                self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return
        self.send_response(status)
        self.send_header('Content-Type',mime)
        if download:self.send_header('Content-Disposition','attachment; filename="NeonPhantom-XR-3D-SBS.mp4"')
        self.send_header('Content-Length',str(end-start+1))
        self.send_header('Accept-Ranges','bytes')
        self.send_header('Cache-Control','private, no-cache')
        if status == 206:
            self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        if self.command == 'HEAD':
            return
        try:
            with path.open('rb') as source:
                source.seek(start);left=end-start+1
                while left:
                    data=source.read(min(left,256*1024))
                    if not data:break
                    self.wfile.write(data);left-=len(data)
        except (BrokenPipeError,ConnectionResetError):
            pass


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='0.0.0.0')
    parser.add_argument('--port',type=int,default=8443)
    parser.add_argument('--state',type=Path,default=Path(os.environ.get('DESKDANCE_STATE',ROOT/'deskdanced/state.json')))
    parser.add_argument('--media',type=Path,default=Path(os.environ.get('DESKDANCE_MEDIA_DIR',ROOT/'samples')))
    parser.add_argument('--data',type=Path,default=ROOT/'.quest')
    parser.add_argument('--site',type=Path,default=ROOT/'quest/site')
    parser.add_argument('--cert',type=Path)
    parser.add_argument('--key',type=Path)
    args=parser.parse_args()
    if not (args.site/'index.html').is_file():
        parser.error('Built Quest viewer missing. Use the release package or build quest/app.')
    if bool(args.cert) != bool(args.key):
        parser.error('Supply both --cert and --key')
    address=local_address() if args.host=='0.0.0.0' else args.host
    cert,key=(args.cert,args.key) if args.cert else ensure_certificate(args.data/'tls',address)
    library=Library(args.state,args.media,args.data/'exports')
    server=CompanionServer((args.host,args.port),library,args.site)
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.minimum_version=ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(cert,key);server.socket=tls.wrap_socket(server.socket,server_side=True,do_handshake_on_connect=False)
    def watch():
        while not library.stopping.is_set():
            library.refresh();server.stereo.queue_requested_imports();library.stopping.wait(5)
    worker=threading.Thread(target=watch,daemon=True);worker.start()
    print(f'Quest viewer: https://{address}:{args.port}/',flush=True)
    print(f'Pairing code: {server.pair_code}',flush=True)
    print(f'PC quick-open: https://localhost:{args.port}/#pair={server.token}',flush=True)
    print('Keep this terminal open. Ctrl+C stops local-network sharing. Use the local certificate exception in Quest Browser if prompted.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        library.stopping.set();server.stereo.cancelled.set();server.server_close()


if __name__=='__main__':main()
