"""Against disposable data only:
DESKDANCE_STATE=/tmp/dd-test/state.json DESKDANCE_MEDIA_DIR=/tmp/dd-test/media ./deskdanced/target/debug/deskdanced
DESKDANCE_TEST_API=1 python3 -m unittest discover -s tests -v
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError


@unittest.skipUnless(os.environ.get('DESKDANCE_TEST_API') == '1', 'API integration requires a server with isolated test data')
class ApiTests(unittest.TestCase):
    def test_model_options_and_preview_metadata(self):
        from urllib.parse import urlencode
        status, models = self.json('/models')
        self.assertEqual(status, 200, models)
        self.assertEqual({m['id'] for m in models}, {'legacy','matanyone2','wevisone-2b','wevisone-4b'})
        self.assertEqual(self.json('/models/not-a-model/install', {}, 'POST')[0], 400)
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)/'model-options.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=red:s=96x128:r=30:d=4.2','-c:v','libx264',str(source)], check=True)
            self.assertEqual(self.json('/import', {'path':str(source),'model':'bogus'}, 'POST')[0], 400)
            self.assertEqual(self.json('/import', {'path':str(source),'subject_box':[.9,0,.1,1]}, 'POST')[0], 400)
            query = urlencode({'mode':'keep','model':'wevisone-2b','subject':'the penguin','subject_box':json.dumps([0,0,1,1]),'preview_seconds':3})
            job_id = self.multipart([('file',source)], query)
            job = self.wait_job(job_id)
            self.assertEqual(job['state'], 'done', job)
            self.assertEqual(job['model'], 'wevisone-2b')
            self.assertEqual(job['subject'], 'the penguin')
            self.assertEqual(job['subject_box'], [0,0,1,1])
            self.assertEqual(job['preview_seconds'], 3)
            card = next(c for c in self.json('/library')[1] if c['id'] == job_id)
            self.assertTrue(card['preview'])
            self.assertTrue(card['name'].startswith('Preview'))
            self.assertAlmostEqual(card['duration_s'],3,delta=.05)
            self.json('/cards/'+job_id,method='DELETE')
            self.json('/jobs/'+job_id,method='DELETE')

    def test_vr180_projection_and_automatic_stereo_import_options(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'vr-modes.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=green:s=192x64:r=12:d=1','-vf','drawbox=x=20:y=12:w=40:h=40:c=red:t=fill','-c:v','libx264',str(source)],check=True,capture_output=True)
            self.assertEqual(self.json('/import',dict(path=str(source),mode='keep',projection='unknown'),'POST')[0],400)
            self.assertEqual(self.json('/import',dict(path=str(source),mode='keep',projection='vr180-sbs',prepare_stereo=True),'POST')[0],400)
            status,result=self.json('/import',dict(path=str(source),mode='green',projection='vr180-sbs'),'POST')
            self.assertEqual(status,200,result);job=self.wait_job(result['job_id']);self.assertEqual(job['state'],'done',job)
            card=next(card for card in self.json('/library')[1] if card['id']==job['job_id'])
            self.assertEqual(card['projection'],'vr180-sbs');self.assertTrue(card['has_alpha'])
            self.json('/cards/'+card['id'],method='DELETE');self.json('/jobs/'+job['job_id'],method='DELETE')
            job_id=self.multipart([('file',source)],'mode=keep&prepare_stereo=true&stereo_device=cpu&projection=flat')
            job=self.wait_job(job_id);self.assertEqual(job['state'],'done',job)
            self.assertTrue(job['prepare_stereo']);self.assertEqual(job['stereo_device'],'cpu');self.assertEqual(job['projection'],'flat')
            self.json('/cards/'+job_id,method='DELETE');self.json('/jobs/'+job_id,method='DELETE')

    def request(self, path, data=None, method=None, headers=None):
        request = Request(os.environ.get('DESKDANCE_TEST_URL', 'http://127.0.0.1:8321') + path, data=data, method=method, headers=headers or {})
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except HTTPError as error:
            with error:
                return error.code, error.read()

    def json(self, path, body=None, method=None, headers=None):
        status, data = self.request('/api' + path, None if body is None else json.dumps(body).encode(), method, {'Content-Type': 'application/json', **(headers or {})})
        return status, json.loads(data)

    def multipart(self, fields, query):
        boundary = 'deskdance-multipart-test'
        pieces = []
        for field_name, path in fields:
            pieces.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field_name}"; filename="{path.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
            pieces.append(path.read_bytes()); pieces.append(b'\r\n')
        pieces.append(f'--{boundary}--\r\n'.encode())
        status, body = self.request('/api/upload?' + query, b''.join(pieces), 'POST', {'Content-Type': f'multipart/form-data; boundary={boundary}'})
        self.assertEqual(status, 200, body)
        return json.loads(body)['job_id']

    def wait_job(self, job_id):
        for _ in range(150):
            job = next(j for j in self.json('/jobs')[1] if j['job_id'] == job_id)
            if job['state'] in ('done', 'error'): return job
            time.sleep(0.1)
        self.fail('Import timed out')

    def test_m4s_upload_assembles_all_segments(self):
        from test_m4s import make_dash
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            init, chunks = make_dash(root)
            job_id = self.multipart([('init', init)] + [('file', p) for p in chunks], 'mode=keep&segments=true')
            job = self.wait_job(job_id)
            self.assertEqual(job['state'], 'done', job)
            card = next(c for c in self.json('/library')[1] if c['id'] == job['card_id'])
            self.assertGreaterEqual(card['duration_s'] + 0.001, 2.25)
            self.assertLess(card['duration_s'], 2.34)
            self.assertEqual(len(job['segments']), 2)
            for path in [job['input'], job['init_path'], *job['segments']]: self.assertFalse(Path(path).exists())
            self.json('/cards/' + card['id'], method='DELETE')
            self.json('/jobs/' + job_id, method='DELETE')
            # A failed standalone fragment retains its source and offers removal.
            missing = self.multipart([('file', chunks[0])], 'mode=keep')
            job = self.wait_job(missing)
            self.assertEqual(job['state'], 'error')
            self.assertTrue(job['can_retry']); self.assertTrue(Path(job['input']).exists())
            self.assertEqual(self.json('/jobs/' + missing, method='DELETE')[0], 200)
            self.assertFalse(Path(job['input']).exists())

    def test_failed_upload_can_retry_with_a_different_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'retry.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=green:s=96x128:r=30:d=0.2', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono:d=0.4', '-c:v', 'libx264', '-c:a', 'aac', str(source)], check=True)
            job_id = self.multipart([('file', source)], 'mode=alpha')
            failed = self.wait_job(job_id)
            self.assertEqual(failed['state'], 'error'); self.assertTrue(failed['can_retry'])
            self.assertTrue(Path(failed['input']).exists())
            self.assertEqual(self.json('/jobs/' + job_id + '/retry', {'mode': 'keep'}, 'POST')[0], 200)
            self.assertEqual(self.json('/jobs/' + job_id + '/retry', {'mode': 'keep'}, 'POST')[0], 409)
            done = self.wait_job(job_id)
            self.assertEqual(done['state'], 'done', done)
            card = next(c for c in self.json('/library')[1] if c['id'] == done['card_id'])
            self.assertGreaterEqual(card['duration_s'] + 0.001, 0.4)
            self.assertFalse(Path(done['input']).exists())
            self.json('/cards/' + card['id'], method='DELETE')
            self.json('/jobs/' + job_id, method='DELETE')

    def test_validation_and_browser_origin(self):
        self.assertEqual(self.json('/library', headers={'Host':'untrusted.example'})[0],403)
        self.assertEqual(self.json('/library', headers={'Sec-Fetch-Site':'cross-site'})[0],403)
        self.assertEqual(self.json('/stage/geometry', {'height_px': 620, 'corner': 'bl'}, 'POST')[0], 200)
        self.assertEqual(self.json('/stage')[1]['height_px'], 620)
        self.assertEqual(self.json('/stage')[1]['corner'], 'bl')
        self.assertEqual(self.json('/stage/geometry', {'height_px': 10, 'corner': 'bad'}, 'POST')[0], 400)
        self.assertEqual(self.json('/import', {'path': '/no/such/video.mp4'}, 'POST')[0], 400)
        self.assertEqual(self.json('/stage/play', {'card_id': 'missing'}, 'POST')[0], 404)
        self.assertEqual(self.json('/stage/shuffle', {'card_ids': []}, 'POST')[0], 400)
        self.assertEqual(self.json('/stage/shuffle', {'card_ids': ['missing']}, 'POST')[0], 400)
        self.assertEqual(self.json('/stage/stop', {}, 'POST', {'Origin': 'https://untrusted.example'})[0], 403)
        self.assertEqual(self.json('/stage/stop', {}, 'POST', {'Origin': os.environ.get('DESKDANCE_TEST_URL', 'http://127.0.0.1:8321')})[0], 200)

    def test_upload_conversion_and_library_actions(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'test.mov'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=green:s=96x128:r=12:d=0.5', '-vf', 'drawbox=x=24:y=24:w=48:h=80:color=red:t=fill', '-c:v', 'png', str(source)], check=True)
            boundary = 'deskdance-test-boundary'
            body = f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="test.mov"\r\nContent-Type: video/quicktime\r\n\r\n'.encode() + source.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
            card_ids = []
            for _ in range(2):
                status, response = self.request('/api/upload?mode=green', body, 'POST', {'Content-Type': f'multipart/form-data; boundary={boundary}'})
                self.assertEqual(status, 200, response)
                job_id = json.loads(response)['job_id']
                for attempt in range(100):
                    jobs = self.json('/jobs')[1]
                    job = next(j for j in jobs if j['job_id'] == job_id)
                    if job['state'] in ('done', 'error'):
                        break
                    time.sleep(0.1)
                self.assertEqual(job['state'], 'done', job)
                card = next(c for c in self.json('/library')[1] if c['id'] == job['card_id'])
                self.assertTrue(card['has_alpha']); self.assertEqual(card['name'], 'test.mov')
                self.assertEqual(self.request(card['thumb'])[0], 200)
                self.assertEqual(self.request('/media/' + card['file'])[0], 200)
                self.assertFalse(Path(job['input']).exists())
                card_ids.append(card['id'])
            self.assertNotEqual(*card_ids)  # identical upload headers must not overwrite one another
            card_id = card_ids[0]
            self.assertEqual(self.json('/playlists', {'name': 'integration-test'}, 'POST')[0], 200)
            self.json('/playlists/integration-test/add', {'card_id': card_id}, 'POST')
            self.json('/playlists/integration-test/add', {'card_id': card_id}, 'POST')
            playlist = next(p for p in self.json('/playlists')[1] if p['name'] == 'integration-test')
            self.assertEqual(playlist['cards'], [card_id])
            self.assertTrue(self.json('/favorites', {'card_id': card_id}, 'POST')[1]['favorited'])
            if not self.json('/health')[1]['tools']['mpv']:
                status, error = self.json('/stage/play', {'card_id': card_id}, 'POST')
                self.assertEqual(status, 503); self.assertIn('mpv', error['error'])
                self.assertFalse(self.json('/stage')[1]['playing'])
            for card_id in card_ids:
                self.assertEqual(self.json('/cards/' + card_id, method='DELETE')[0], 200)
            self.assertNotIn(card_ids[0], self.json('/favorites')[1])
            playlist = next(p for p in self.json('/playlists')[1] if p['name'] == 'integration-test')
            self.assertEqual(playlist['cards'], [])
            self.json('/playlists/integration-test', method='DELETE')


if __name__ == '__main__':
    unittest.main()
