"""Run API regressions against an ephemeral server and disposable library."""
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]


def main():
    binary=Path(os.environ.get('NEONPHANTOM_TEST_BINARY',ROOT/'deskdanced/target/release'/('deskdanced.exe' if os.name=='nt' else 'deskdanced')))
    with tempfile.TemporaryDirectory(prefix='neonphantom-api-') as folder:
        data=Path(folder)
        with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        url=f'http://127.0.0.1:{port}'
        env={**os.environ,'DESKDANCE_ROOT':str(ROOT),'DESKDANCE_PYTHON':sys.executable,
             'DESKDANCE_STATE':str(data/'state.json'),'DESKDANCE_MEDIA_DIR':str(data/'media'),
             'DESKDANCE_PORT':str(port),'DESKDANCE_TEST_API':'1','DESKDANCE_TEST_URL':url}
        process=subprocess.Popen([str(binary)],env=env,stdout=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if process.poll() is not None:raise RuntimeError('Isolated API server exited')
                try:
                    with urlopen(url+'/api/health',timeout=1):break
                except OSError:time.sleep(.1)
            else:raise RuntimeError('Isolated API server did not start')
            return subprocess.call([sys.executable,'-m','unittest','discover','-s','tests','-p','test_api.py','-v'],env=env,cwd=ROOT)
        finally:
            process.send_signal(signal.SIGINT) if os.name!='nt' else process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':sys.exit(main())
