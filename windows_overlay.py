"""Native transparent Windows player: FFmpeg RGBA decoding into a translucent Qt window.

The backend controls this child over an authenticated loopback-only JSON socket.
Can also run on Linux for offscreen rendering and protocol tests.
"""
import argparse
import hmac
import json
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import Qt, QProcess, QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtNetwork import QHostAddress, QTcpServer
from PySide6.QtWidgets import QApplication, QWidget


class Overlay(QWidget):
    def __init__(self, path, height, corner):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle('NeonPhantom XR overlay')
        self.frame = QImage()
        self.buffer = bytearray()
        self.log = ''
        self.height_px, self.corner = height, corner
        self.path = None
        self.decoder = QProcess(self)
        self.decoder.readyReadStandardOutput.connect(self.read_frame)
        self.decoder.readyReadStandardError.connect(self.read_error)
        self.decoder.finished.connect(self.decoder_stopped)
        self.decoder.errorOccurred.connect(self.decoder_error)
        self.closing = False
        self.load(path)

    def load(self, path):
        path = str(Path(path).resolve(strict=True))
        info = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                               '-show_entries', 'stream=width,height', '-of', 'json', path],
                              capture_output=True, text=True, check=True, creationflags=0x08000000 if sys.platform == 'win32' else 0)
        stream = json.loads(info.stdout)['streams'][0]
        work = QApplication.primaryScreen().availableGeometry()
        ratio = stream['width'] / stream['height']
        h = min(self.height_px, work.height()-48)
        w = min(round(h*ratio), work.width()-48)
        h = round(w/ratio)
        self.closing = True
        self.decoder.kill()
        self.decoder.waitForFinished(1500)
        self.closing = False
        self.buffer.clear()
        self.frame = QImage()
        self.log = ''
        self.path = path
        self.resize(max(2, w), max(2, h))
        self.move(work.right()-w-24 if self.corner.endswith('r') else work.left()+24,
                  work.bottom()-h-24 if self.corner.startswith('b') else work.top()+24)
        args = ['-v', 'error', '-nostdin', '-re', '-stream_loop', '-1', '-c:v', 'libvpx-vp9',
                '-i', path, '-an', '-vf', f'scale={self.width()}:{self.height()},fps=30',
                '-f', 'rawvideo', '-pix_fmt', 'rgba', 'pipe:1']
        self.decoder.start('ffmpeg', args)
        if not self.decoder.waitForStarted(3000):
            raise RuntimeError('Cannot start FFmpeg for desktop playback')
        self.show()

    def read_frame(self):
        self.buffer.extend(bytes(self.decoder.readAllStandardOutput()))
        size = self.width()*self.height()*4
        count = len(self.buffer)//size
        if count:
            # Detach from the mutable byte buffer and discard only superseded frames.
            data = bytes(self.buffer[(count-1)*size:count*size])
            del self.buffer[:count*size]
            self.frame = QImage(data, self.width(), self.height(), self.width()*4, QImage.Format.Format_RGBA8888).copy()
            self.update()

    def read_error(self):
        self.log = (self.log + bytes(self.decoder.readAllStandardError()).decode(errors='replace'))[-2500:]

    def decoder_error(self, error):
        if not self.closing:
            print(f'Desktop decoder failed: {self.decoder.errorString()}', file=sys.stderr, flush=True)
            QApplication.exit(1)

    def decoder_stopped(self, code, status):
        if not self.closing:
            self.read_error()
            print(f'Desktop decoder stopped ({code}): {self.log}', file=sys.stderr, flush=True)
            QApplication.exit(1)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        if not self.frame.isNull():
            painter.drawImage(0, 0, self.frame)

    def closeEvent(self, event):
        self.closing = True
        self.decoder.kill()
        self.decoder.waitForFinished(1500)
        event.accept()


class ControlServer(QTcpServer):
    def __init__(self, overlay, port, token):
        super().__init__(overlay)
        self.overlay, self.token = overlay, token
        self.newConnection.connect(self.accept)
        if not self.listen(QHostAddress.SpecialAddress.LocalHost, port):
            raise RuntimeError(f'Cannot bind desktop control port {port}')

    def accept(self):
        while self.hasPendingConnections():
            client = self.nextPendingConnection()
            client.setReadBufferSize(16385)
            client.readyRead.connect(lambda c=client: self.read(c))
            client.disconnected.connect(client.deleteLater)

    def read(self, client):
        if client.bytesAvailable() > 16384:
            client.abort()
            return
        if not client.canReadLine():
            return
        quitting = False
        try:
            request = json.loads(bytes(client.readLine()).decode())
            if not hmac.compare_digest(str(request.get('token', '')), self.token):
                raise ValueError('Unauthorized player command')
            args = request['command']
            if args == ['quit']:
                quitting = True
            elif args[:1] == ['loadfile'] and len(args) >= 2:
                self.overlay.load(args[1])
            elif args != ['get_property', 'path']:
                raise ValueError('Unsupported player command')
            reply = {'error': 'success', 'data': self.overlay.path}
        except Exception as exc:
            reply = {'error': str(exc)}
        client.write((json.dumps(reply)+'\n').encode())
        client.disconnectFromHost()
        if quitting:
            # Closing the last window ends Qt's event loop. Give the socket time
            # to flush its acknowledgement before that happens.
            QTimer.singleShot(50, self.stop)

    def stop(self):
        self.overlay.close()
        QApplication.quit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('video')
    parser.add_argument('height', type=int)
    parser.add_argument('corner', choices=['bl', 'br', 'tl', 'tr'])
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--token', required=True)
    args = parser.parse_args()
    if not 160 <= args.height <= 1600 or not 1 <= args.port <= 65535 or len(args.token) < 32:
        parser.error('Invalid geometry or control settings')
    app = QApplication(sys.argv)
    overlay = Overlay(args.video, args.height, args.corner)
    control = ControlServer(overlay, args.port, args.token)
    code = app.exec()
    overlay.close()
    return code


if __name__ == '__main__':
    sys.exit(main())
