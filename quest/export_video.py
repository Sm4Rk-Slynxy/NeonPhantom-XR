"""Encode RGB and alpha into one synchronized, hardware-decodable H.264 video."""
import json
from pathlib import Path
import subprocess
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from media_security import local_media_command

EXPORT_VERSION = 1


def probe(path):
    command = ['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]
    result = subprocess.run(local_media_command(command), capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-1500:] or 'Cannot inspect video')
    data = json.loads(result.stdout)
    stream = next((s for s in data['streams'] if s.get('codec_type') == 'video'), None)
    if not stream:
        raise ValueError('No video stream')
    return data, stream


def export_video(source, output):
    source, output = Path(source), Path(output)
    data, stream = probe(source)
    alpha = stream.get('pix_fmt', '').startswith(('yuva', 'gbrap', 'rgba', 'bgra')) or any(
        key.lower() == 'alpha_mode' and str(value) == '1' for key, value in stream.get('tags', {}).items())
    # Imported NeonPhantom XR WebM uses VP9's separate alpha bitstream. Force libvpx
    # decoding so FFmpeg exposes the alpha plane rather than silently dropping it.
    decoder = ['-c:v', 'libvpx-vp9'] if stream.get('codec_name') == 'vp9' else []
    factor = min(1, 1920 / stream['width'], 1080 / stream['height'])
    width = max(2, int(stream['width'] * factor / 2) * 2)
    height = max(2, int(stream['height'] * factor / 2) * 2)
    # Always create alpha, including an opaque mask for videos without alpha.
    filters = (f'[0:v:0]scale={width}:{height},format=rgba,split=2[color][alpha];'
               '[color]format=rgb24[rgb];[alpha]alphaextract,format=gray[mask];'
               '[rgb][mask]hstack=inputs=2,format=yuv420p[packed]')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='quest-export-', dir=output.parent) as temp:
        destination = Path(temp) / 'video.mp4'
        result = subprocess.run(local_media_command(['ffmpeg', '-v', 'error', '-xerror', '-y', *decoder, '-i', str(source),
                                 '-filter_complex', filters, '-map', '[packed]', '-an', '-c:v', 'libx264',
                                 '-preset', 'fast', '-crf', '19', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                                 '-map_metadata', '-1', str(destination)]), capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr[-2500:] or 'Quest video conversion failed')
        converted, _ = probe(destination)
        original_duration = float(data.get('format', {}).get('duration', 0))
        duration = float(converted.get('format', {}).get('duration', 0))
        if duration + 0.05 < original_duration:
            raise RuntimeError('Quest export would shorten the video; source retained')
        destination.replace(output)
    return {'width': width, 'height': height, 'duration_s': duration,
            'has_alpha': alpha, 'format': 'rgb-alpha-horizontal-v1'}
