"""Isolated GPU/CPU depth worker with JSON progress on stdout."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def worker_python(device):
    if device!='cpu':
        override=os.environ.get('DESKDANCE_STEREO_GPU_PYTHON')
        if override:
            if not Path(override).is_file():raise ValueError('Configured stereo GPU Python does not exist')
            return Path(override)
        for name in ('.venv-quest-gpu','.venv-cuda'):
            candidate=ROOT/name/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
            if candidate.is_file():return candidate
    return Path(sys.executable)


def run_in_worker(source,folder,models,strength,device,progress,cancelled):
    sys.path.insert(0,str(ROOT))
    from model_runtime import runtime_environment
    interpreter=worker_python(device)
    command=[str(interpreter),str(Path(__file__).resolve()),str(source),str(folder),str(models),str(strength),device]
    result=None;failure=None
    with tempfile.TemporaryFile(mode='w+t') as errors:
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=errors,text=True,env=runtime_environment(interpreter))
        try:
            for line in process.stdout:
                if cancelled.is_set():raise RuntimeError('Conversion cancelled')
                try:event=json.loads(line)
                except ValueError:continue
                if 'progress' in event:progress(event['progress'],event.get('phase','Processing'))
                if 'result' in event:result=event['result']
                if 'error' in event:failure=event['error']
            if process.wait()!=0 or result is None:
                errors.seek(0);detail=errors.read()[-1500:]
                raise RuntimeError(failure or 'Depth worker failed: '+detail)
            return result
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            process.stdout.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('folder',type=Path)
    parser.add_argument('models',type=Path);parser.add_argument('strength',type=float)
    parser.add_argument('device',choices=['auto','gpu','cpu']);args=parser.parse_args()
    from stereo_depth import convert_video
    def cancelled(signum,frame):raise RuntimeError('Conversion cancelled')
    signal.signal(signal.SIGTERM,cancelled)
    def emit(**event):print(json.dumps(event),flush=True)
    try:
        result=convert_video(args.source,args.folder,args.models,args.strength,
                             lambda amount,phase:emit(progress=amount,phase=phase),device=args.device)
        emit(result=result)
    except Exception as error:
        emit(error=str(error));return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
