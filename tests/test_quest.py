"""Quest export and paired HTTPS tests. Run: python -m unittest discover -s tests -p test_quest.py"""
import http.client
import json
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'quest'))
from companion import Library, CompanionServer, ensure_certificate
from export_video import export_video, probe


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class ExportTest(unittest.TestCase):
    def test_transparency_soft_edges_and_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            frame = bytearray()
            for y in range(64):
                for x in range(96):
                    frame.extend((240, 30, 20, 0 if x < 32 else 128 if x < 64 else 255))
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgba',
                            '-s', '96x64', '-r', '12', '-i', '-', '-c:v', 'libvpx-vp9',
                            '-lossless', '1', '-pix_fmt', 'yuva420p', str(root/'alpha.webm')],
                           input=bytes(frame)*24, check=True, capture_output=True)
            result = export_video(root/'alpha.webm', root/'packed.mp4')
            self.assertTrue(result['has_alpha'])
            self.assertAlmostEqual(result['duration_s'], 2, delta=.05)
            _, stream = probe(root/'packed.mp4')
            self.assertEqual((stream['width'], stream['height']), (192, 64))
            pixels = subprocess.run(['ffmpeg','-v','error','-i',str(root/'packed.mp4'),'-frames:v','1',
                                     '-f','rawvideo','-pix_fmt','rgb24','-'],check=True,capture_output=True).stdout
            def pixel(x, y=32): return tuple(pixels[(y*192+x)*3:(y*192+x)*3+3])
            self.assertLess(pixel(112)[0], 5)
            self.assertAlmostEqual(pixel(144)[0], 128, delta=5)
            self.assertGreater(pixel(176)[0], 250)
            self.assertGreater(pixel(80)[0], 220)
            self.assertLess(pixel(80)[1], 50)

    def test_opaque_has_white_mask(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=blue:s=80x60:r=10:d=1',
                            '-c:v','libx264',str(root/'opaque.mp4')],check=True,capture_output=True)
            result = export_video(root/'opaque.mp4', root/'packed.mp4')
            self.assertFalse(result['has_alpha'])
            pixels = subprocess.run(['ffmpeg','-v','error','-i',str(root/'packed.mp4'),'-frames:v','1',
                                     '-f','rawvideo','-pix_fmt','rgb24','-'],check=True,capture_output=True).stdout
            self.assertGreater(pixels[(30*160+120)*3], 250)


class LibraryTest(unittest.TestCase):
    def test_cache_refresh_removal_and_source_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); media=root/'media';media.mkdir()
            (media/'clip.webm').write_bytes(b'original')
            (root/'outside.webm').write_bytes(b'private')
            state=root/'state.json'
            state.write_text(json.dumps({'cards':[{'id':'clip','file':'clip.webm','name':'Example'},
                                                  {'id':'outside','file':'../outside.webm'},
                                                  {'id':'../../secret','file':'clip.webm'}]}))
            library=Library(state,media,root/'exports')
            calls=[]
            def convert(source, output):
                calls.append(source); output.write_bytes(b'export')
                return dict(width=80,height=60,duration_s=1,has_alpha=True,format='rgb-alpha-horizontal-v1')
            with patch('companion.export_video',convert):
                library.refresh();library.refresh()
                self.assertEqual(len(calls),1)
                self.assertEqual([c['id'] for c in library.snapshot()['cards']],['clip'])
                (media/'clip.webm').write_bytes(b'new content')
                library.refresh();self.assertEqual(len(calls),2)
                state.write_text('{"cards":[]}');library.refresh()
                self.assertEqual(library.snapshot()['cards'],[])


class HTTPSTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        site=self.root/'site';site.mkdir();(site/'index.html').write_text('<h1>Viewer</h1>');(site/'app.js').write_text('export const ready=true;')
        library=Library(self.root/'state.json',self.root/'media',self.root/'exports')
        library.cards=[{'id':'clip'}];(library.exports/'clip.mp4').write_bytes(b'0123456789')
        self.server=CompanionServer(('127.0.0.1',0),library,site,max_connections=2)
        cert,key=ensure_certificate(self.root/'tls','127.0.0.1')
        if __import__('os').name != 'nt':
            self.assertEqual(key.stat().st_mode & 0o777,0o600)
            self.assertEqual(key.parent.stat().st_mode & 0o777,0o700)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
        self.server.socket=context.wrap_socket(self.server.socket,server_side=True,do_handshake_on_connect=False)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def request(self,method,path,body=None,headers=None):
        conn=http.client.HTTPSConnection('127.0.0.1',self.server.server_port,context=ssl._create_unverified_context())
        conn.request(method,path,body,headers or {});response=conn.getresponse()
        result=response.status,dict(response.getheaders()),response.read();conn.close();return result
    def test_pairing_and_read_only_range_streaming(self):
        self.assertEqual(self.request('GET','/')[0],200)
        self.assertEqual(self.request('HEAD','/app.js')[1]['Content-Type'],'text/javascript')
        self.assertEqual(self.request('GET','/api/library')[0],401)
        self.assertEqual(self.request('GET','/media/clip.mp4')[0],401)
        self.assertEqual(self.request('POST','/api/pair',json.dumps({'code':self.server.pair_code}),{'Origin':'https://evil.example'})[0],403)
        status,headers,_=self.request('POST','/api/pair',json.dumps({'code':self.server.pair_code}))
        self.assertEqual(status,200);self.assertIn('HttpOnly; Secure; SameSite=Strict',headers['Set-Cookie'])
        auth={'Cookie':headers['Set-Cookie'].split(';')[0]}
        self.assertEqual(self.request('GET','/api/library',headers=auth)[0],200)
        status,headers,data=self.request('GET','/media/clip.mp4',headers={**auth,'Range':'bytes=2-5'})
        self.assertEqual((status,data),(206,b'2345'));self.assertEqual(headers['Content-Range'],'bytes 2-5/10')
        self.assertEqual(self.request('GET','/media/clip.mp4',headers={**auth,'Range':'bytes=-3'})[2],b'789')
        self.assertEqual(self.request('GET','/media/clip.mp4',headers={**auth,'Range':'bytes=99-'})[0],416)
        self.assertEqual(self.request('GET','/media/clip.mp4',headers={**auth,'Range':'bytes=-0'})[0],416)
        self.assertEqual(self.request('GET','/media/deleted.mp4',headers=auth)[0],404)
        self.assertEqual(self.request('HEAD','/media/clip.mp4',headers=auth)[2],b'')
        self.assertEqual(self.request('POST','/api/import','{}',auth)[0],405)
        self.assertEqual(self.request('GET','/../tls/server.key',headers=auth)[0],404)
    def test_conversion_requires_pairing_valid_source_and_same_origin(self):
        self.assertEqual(self.request('POST','/api/stereo','{}')[0],401)
        self.assertEqual(self.request('GET','/downloads/sbs_012345abcdef.mp4')[0],401)
        _,headers,_=self.request('POST','/api/pair',json.dumps({'code':self.server.pair_code}))
        auth={'Cookie':headers['Set-Cookie'].split(';')[0]}
        self.assertEqual(self.request('POST','/api/stereo','{}',{**auth,'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('POST','/api/stereo',json.dumps({'card_id':'../secret'}),auth)[0],400)
        self.assertEqual(self.request('POST','/api/stereo',json.dumps({'card_id':'clip','strength':float('nan')}),auth)[0],400)
        self.assertEqual(self.request('GET','/downloads/sbs_012345abcdef.mp4',headers=auth)[0],404)

    def test_bad_requests_and_rate_limit(self):
        for body in ['[]','null','{"code":"wrong"}','{','{}']:
            self.assertEqual(self.request('POST','/api/pair',body)[0],403)
        self.assertEqual(self.request('POST','/api/pair','{}')[0],429)

    def test_stalled_connections_are_bounded_and_slots_recover(self):
        import time
        clients=[]
        try:
            for _ in range(2):
                conn=http.client.HTTPSConnection('127.0.0.1',self.server.server_port,timeout=2,context=ssl._create_unverified_context())
                conn.connect();clients.append(conn)  # TLS complete, headers deliberately stalled.
            with self.assertRaises((OSError,http.client.RemoteDisconnected)):
                self.request('GET','/')
        finally:
            for client in clients:client.close()
        until=time.monotonic()+3
        while True:
            try:
                self.assertEqual(self.request('GET','/')[0],200)
                break
            except (OSError,http.client.RemoteDisconnected):
                if time.monotonic()>until:raise
                time.sleep(.02)


if __name__=='__main__':unittest.main()
