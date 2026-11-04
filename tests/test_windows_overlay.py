"""Qt RGBA and authenticated-control smoke tests; native Windows QA is separate."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Native player tests need PySide6')
class WindowsOverlayTests(unittest.TestCase):
    def test_rgba_decode_and_control_authentication(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        from windows_overlay import Overlay
        from video_pipeline import process
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root/'source.mov'; video = root/'alpha.webm'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',
                            'color=c=0x00ff00:s=96x128:r=12:d=0.5','-vf',
                            'drawbox=x=24:y=24:w=48:h=80:color=red:t=fill','-c:v','png',str(source)], check=True)
            with contextlib.redirect_stdout(io.StringIO()):
                process(source, video, 'green')
            app = QApplication.instance() or QApplication([])
            overlay = Overlay(video, 160, 'br')
            try:
                until = time.monotonic()+5
                while overlay.frame.isNull() and time.monotonic()<until:
                    app.processEvents(); time.sleep(.01)
                self.assertFalse(overlay.frame.isNull(), overlay.log)
                self.assertEqual(overlay.frame.pixelColor(0,0).alpha(),0)
                center = overlay.frame.pixelColor(overlay.width()//2,overlay.height()//2)
                self.assertGreater(center.alpha(),250)
                self.assertGreater(center.red(),230)
                overlay.load(video)
                app.processEvents()
            finally:
                overlay.close(); app.processEvents()
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1',0)); port=reserve.getsockname()[1]
            token = 'a'*64
            child = subprocess.Popen([sys.executable,str(Path(__file__).resolve().parents[1]/'windows_overlay.py'),
                                      str(video),'160','bl','--port',str(port),'--token',token],
                                     stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={**os.environ,'QT_QPA_PLATFORM':'offscreen'})
            def send(command, supplied):
                with socket.create_connection(('127.0.0.1',port),timeout=2) as client:
                    client.sendall((json.dumps({'command':command,'token':supplied})+'\n').encode())
                    return json.loads(client.makefile().readline())
            try:
                for _ in range(100):
                    try:
                        reply=send(['get_property','path'],token);break
                    except OSError:
                        if child.poll() is not None: self.fail(child.stderr.read().decode())
                        time.sleep(.05)
                else: self.fail('Desktop control did not become ready')
                self.assertEqual(reply['error'],'success')
                self.assertEqual(send(['quit'],'wrong')['error'],'Unauthorized player command')
                self.assertIsNone(child.poll())
                self.assertEqual(send(['loadfile',str(video),'replace'],token)['error'],'success')
                self.assertEqual(send(['quit'],token)['error'],'success')
                self.assertEqual(child.wait(timeout=5),0)
            finally:
                if child.poll() is None: child.kill();child.wait()
                child.stdout.close();child.stderr.close()


if __name__ == '__main__':
    unittest.main()
