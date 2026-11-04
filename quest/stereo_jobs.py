"""One-at-a-time local stereo conversion jobs; originals are never modified."""
import json
import math
from pathlib import Path
import secrets
import threading

from stereo_depth import convert_video
from stereo_worker import run_in_worker


class StereoJobs:
    def __init__(self, library):
        self.library = library
        self.folder = library.exports.parent/'stereo'
        self.folder.mkdir(parents=True,exist_ok=True)
        self.lock = threading.Lock()
        self.jobs = {}
        self.active = None
        self.cancelled = threading.Event()
        self.requests_path=self.folder/'requests.json'
        try:self.requests=json.loads(self.requests_path.read_text()) if self.requests_path.is_file() else {}
        except (ValueError,OSError):self.requests={}
        for path in sorted(self.folder.glob('sbs_*/result.json')):
            try:
                job = json.loads(path.read_text())
                if job['id'] != path.parent.name or not (path.parent/'quest.mp4').is_file() or not (path.parent/'sbs.mp4').is_file():continue
                self.jobs[job['id']] = job
            except (ValueError,KeyError,OSError):continue

    def snapshot(self):
        with self.lock:return [dict(job) for job in self.jobs.values()][-30:]

    def cards(self, base_ids):
        return [dict(job['card']) for job in self.snapshot() if job['state']=='done' and job['source_id'] in base_ids]

    def start(self, identifier, strength, device='cpu'):
        if isinstance(strength,bool) or not isinstance(strength,(int,float)) or not math.isfinite(strength) or not 0 < strength <= .03:
            raise ValueError('Depth strength must be above zero and at most 3 percent')
        if device not in ('auto','gpu','cpu'):raise ValueError('Choose Auto, GPU or CPU processing')
        if any(card['id']==identifier and card.get('projection')=='vr180-sbs' for card in self.library.snapshot()['cards']):
            raise ValueError('VR180 already contains stereo depth. Play it directly in passthrough.')
        source_id = identifier
        source,name = self.library.source(source_id)
        with self.lock:
            if self.active is not None:raise RuntimeError('A stereo conversion is already running. Wait for it or cancel it first.')
            identifier = 'sbs_'+secrets.token_hex(6)
            job = dict(id=identifier,source_id=source_id,name=name,state='running',progress=0,phase='Loading depth model',requested_device=device)
            self.jobs[identifier]=job;self.active=identifier;self.cancelled.clear()
        threading.Thread(target=self.run,args=(job,source,strength,device),daemon=True).start()
        return dict(job)

    def run(self, job, source, strength, device):
        folder = self.folder/job['id']
        try:
            def update(amount, phase):
                if self.cancelled.is_set():raise RuntimeError('Conversion cancelled')
                with self.lock:job.update(progress=amount,phase=phase)
            if device=='cpu':
                metadata = convert_video(source,folder,self.folder.parent/'models',strength,update)
            else:
                try:metadata=run_in_worker(source,folder,self.folder.parent/'models',strength,device,update,self.cancelled)
                except Exception:
                    if self.cancelled.is_set():raise
                    update(0,'GPU worker unavailable; retrying on CPU')
                    metadata=convert_video(source,folder,self.folder.parent/'models',strength,update)
                    metadata['fallback_reason']='GPU worker unavailable; used CPU'

            card = dict(metadata,id=job['id'],source_id=job['source_id'],name=job['name']+' · 3D SBS',url=f'/media/{job["id"]}.mp4')
            with self.lock:
                job.update(state='done',progress=1,phase='Ready',card=card,download_url=f'/downloads/{job["id"]}.mp4')
                partial=folder/'result.tmp';partial.write_text(json.dumps(job));partial.replace(folder/'result.json')
        except Exception as error:
            with self.lock:job.update(state='cancelled' if self.cancelled.is_set() else 'error',phase=str(error))
        finally:
            with self.lock:self.active=None

    def queue_requested_imports(self):
        if self.active is not None:return
        try:
            state=json.loads(self.library.state.read_text())
            jobs=state.get('jobs',[])
            # Defer automatic GPU work while imports/model installs use the GPU.
            if any(job.get('state') in ('queued','running') for job in jobs):return
            for job in jobs:
                request_id=job.get('job_id')
                if job.get('prepare_stereo') is not True or job.get('state')!='done' or not request_id or request_id in self.requests:continue
                source_id=job.get('card_id')
                if not source_id:continue
                try:result=self.start(source_id,.015,job.get('stereo_device','auto'))
                except ValueError:continue
                except RuntimeError:return
                self.requests[request_id]=result['id']
                temporary=self.requests_path.with_suffix('.tmp');temporary.write_text(json.dumps(self.requests));temporary.replace(self.requests_path)
                return
        except (OSError,ValueError):return

    def cancel(self, identifier):
        with self.lock:
            if identifier != self.active:raise ValueError('That conversion is not running')
            self.cancelled.set();self.jobs[identifier]['phase']='Cancelling…'

    def file(self, identifier, download=False):
        with self.lock:job = dict(self.jobs.get(identifier,{}))
        if job.get('state') != 'done':raise FileNotFoundError('Stereo video is not ready')
        self.library.source(job['source_id'])
        return self.folder/identifier/('sbs.mp4' if download else 'quest.mp4')
