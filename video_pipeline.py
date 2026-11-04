#!/usr/bin/env python3
"""Decode local videos to browser/mpv-friendly VP9; emit JSON progress on stdout."""
import argparse
import json
import math
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
from media_security import local_media_command


def emit(**event):
    print(json.dumps(event), flush=True)


def run(args):
    args = local_media_command(args)
    if args[0] == 'ffmpeg':
        args = [args[0], '-xerror', *args[1:]]
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:] or f'{args[0]} failed')
    return result.stdout


def probe(path):
    try:
        info = json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))
    except RuntimeError as exc:
        raise RuntimeError(f'Cannot decode this video. Use a complete, unencrypted video file; M4S fragments need an initialization segment. {exc}') from exc
    stream = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')), None)
    if not stream:
        raise ValueError('No playable video stream. M4S fragments need their initialization segment; encrypted videos must first be exported as a playable file.')
    return info, stream


def has_alpha(stream):
    pix = stream.get('pix_fmt', '')
    return pix.startswith(('yuva', 'gbrap', 'rgba', 'bgra')) or pix in ('argb', 'abgr', 'ya8', 'ya16le', 'ya16be') or any(k.lower() == 'alpha_mode' and str(v) == '1' for k, v in stream.get('tags', {}).items())


def frame_rate(stream):
    try:
        a, b = stream.get('avg_frame_rate', '30/1').split('/')
        value = float(a) / float(b)
        return min(30.0, value) if math.isfinite(value) and value > 0 else 30.0
    except (ValueError, ZeroDivisionError):
        return 30.0


def _process_video(source, output, mode='auto', quality='detailed', model='legacy', subject='person', box=None):
    info, stream = probe(source)
    try:
        source_duration = float(info.get('format', {}).get('duration', stream.get('duration', '0')))
        if not math.isfinite(source_duration) or source_duration < 0:
            source_duration = 0.0
    except (TypeError, ValueError):
        source_duration = 0.0
    alpha = has_alpha(stream)
    if mode == 'auto':
        mode = 'alpha' if alpha else 'ai'
    if mode == 'alpha' and not alpha:
        raise ValueError('This video has no alpha channel. Choose AI cutout, green screen, or blue screen to remove its background.')
    if mode == 'ai' and model != 'legacy':
        from model_manager import python_for, model_path
        interpreter = python_for(model)
        if not interpreter.is_file() or not (model_path(model) / 'ready.json').is_file():
            raise RuntimeError(f'{model} is not installed. Use Download & install in the model picker first.')
        if Path(sys.executable).absolute() != interpreter.absolute():
            args = [str(interpreter), str(Path(__file__).resolve()), str(source), str(output),
                    '--mode', 'ai', '--quality', quality, '--model', model, '--subject', subject]
            if box is not None:
                args += ['--box', json.dumps(box)]
            from model_runtime import runtime_environment
            child = subprocess.Popen(args, stdout=subprocess.PIPE, text=True,
                                     env=runtime_environment(interpreter))
            error = None
            for line in child.stdout:
                print(line, end='', flush=True)
                try:
                    event = json.loads(line)
                    error = event.get('error') or error
                except ValueError:
                    pass
            if child.wait():
                raise RuntimeError(error or f'{model} conversion failed')
            return
    fast_ai = quality == 'fast' and mode == 'ai'
    emit(progress=0.05, phase='Inspecting video')
    decoder = ['-c:v', 'libvpx-vp9' if stream.get('codec_name') == 'vp9' else 'libvpx'] if alpha and stream.get('codec_name') in ('vp8', 'vp9') else []
    inputs = decoder + ['-i', str(source)]
    # Even dimensions and bounded resolution keep conversion practical for desktop clips.
    scale = "scale=w='trunc(iw*min(1,720/ih)/2)*2':h='trunc(ih*min(1,720/ih)/2)*2'"
    fps = min(frame_rate(stream), 12) if fast_ai else frame_rate(stream)
    if fast_ai:
        scale = scale.replace('720', '480')
    common = ['-c:v', 'libvpx-vp9', '-b:v', '0', '-crf', '32', '-deadline', 'good', '-cpu-used', '4', '-map_metadata', '-1', '-an']
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix='deskdance-', dir=output.parent) as temp:
            if mode == 'ai':
                from cutout_engines import load_engine
                emit(progress=0.08, phase=f'Loading {model}')
                engine = load_engine(model, quality, subject, box)
                emit(progress=0.09, phase=f'{model} · {engine.provider}')
                frames = Path(temp) / 'frames'
                mats = Path(temp) / 'mats'
                frames.mkdir(); mats.mkdir()
                emit(progress=0.1, phase='Extracting frames')
                run(['ffmpeg', '-v', 'error', '-y', *inputs, '-vf', f'{scale},fps={fps}:round=up', str(frames / '%06d.png')])
                files = sorted(frames.glob('*.png'))
                if not files:
                    raise RuntimeError('No frames decoded from video')
                for index, frame in enumerate(files):
                    from PIL import Image
                    with Image.open(frame) as decoded:
                        image = decoded.convert('RGB')
                    image.putalpha(engine.matte(image))
                    image.save(mats / frame.name)
                    frame.unlink()
                    emit(progress=0.15 + 0.65 * (index + 1) / len(files), phase=f'Removing background · {index + 1}/{len(files)} frames · {engine.provider}')
                emit(progress=0.82, phase='Encoding transparent video')
                run(['ffmpeg', '-v', 'error', '-y', '-framerate', str(fps), '-i', str(mats / '%06d.png'), *common, '-pix_fmt', 'yuva420p', str(output)])
            else:
                emit(progress=0.2, phase='Converting video')
                filters = scale
                if mode in ('green', 'blue'):
                    color = '0x00FF00' if mode == 'green' else '0x0000FF'
                    filters = f'format=rgba,chromakey={color}:0.25:0.05,{scale}'
                run(['ffmpeg', '-v', 'error', '-y', *inputs, '-map', '0:v:0', '-vf', filters, '-r', str(fps), *common, '-pix_fmt', 'yuv420p' if mode == 'keep' else 'yuva420p', str(output)])
            # Never trim the input. If frame-rate conversion rounds the final timestamp
            # down, hold the final frame long enough to retain the full source duration.
            converted, _ = probe(output)
            duration = float(converted.get('format', {}).get('duration', '0'))
            if source_duration > duration + 0.001:
                emit(progress=0.92, phase='Preserving full video duration')
                extra_frames = math.ceil((source_duration - duration) * fps)
                padded = Path(temp) / 'padded.webm'
                run(['ffmpeg', '-v', 'error', '-y', '-c:v', 'libvpx-vp9', '-i', str(output),
                     '-vf', f'tpad=stop_mode=clone:stop={extra_frames}', *common,
                     '-pix_fmt', 'yuv420p' if mode == 'keep' else 'yuva420p', str(padded)])
                padded.replace(output)
                converted, _ = probe(output)
                duration = float(converted.get('format', {}).get('duration', '0'))
            if duration + 0.001 < source_duration:
                raise RuntimeError('Converted video is shorter than the source; import was stopped to avoid losing its ending.')
            emit(progress=0.95, phase='Creating preview')
            thumb = output.with_name('thumb_' + output.stem + '.png')
            run(['ffmpeg', '-v', 'error', '-y', '-c:v', 'libvpx-vp9', '-i', str(output), '-frames:v', '1', str(thumb)])
            converted, _ = probe(output)
            duration = float(converted.get('format', {}).get('duration', '0'))
            emit(progress=1.0, phase='Ready', result={'duration_s': duration, 'source_duration_s': source_duration, 'quality': quality, 'model': model if mode == 'ai' else None, 'provider': engine.provider if mode == 'ai' else None, 'has_alpha': mode != 'keep', 'matted': mode in ('ai', 'green', 'blue')})
    except Exception:
        output.unlink(missing_ok=True)
        output.with_name('thumb_' + output.stem + '.png').unlink(missing_ok=True)
        raise


def process(source, output, mode='auto', init_path=None, segments=(), quality='detailed', model='legacy', subject='person', box=None, preview_seconds=None, projection='flat'):
    """Import a complete video, or one init segment + ordered fragments of one track."""
    from cutout_engines import validate_options
    validate_options(model, subject, box)
    if projection not in ('flat','vr180-sbs'):raise ValueError('Unsupported input projection')
    if projection=='vr180-sbs':
        from vr180_pipeline import process_vr180
        convert=process_vr180
    else:convert=_process_video
    if preview_seconds is not None and not 1 <= preview_seconds <= 10:
        raise ValueError('Preview length must be 1–10 seconds')
    source, output = Path(source), Path(output)
    if preview_seconds is not None:
        # Assemble fragmented input first; trim only explicitly requested previews.
        if init_path or segments:
            raise ValueError('Preview is available for complete video files; import segments in full.')
        with tempfile.TemporaryDirectory(prefix='deskdance-preview-') as temp:
            clip = Path(temp) / 'preview.mkv'
            _, stream = probe(source)
            alpha = has_alpha(stream)
            decoder = ['-c:v', 'libvpx-vp9'] if alpha and stream.get('codec_name') == 'vp9' else []
            run(['ffmpeg', '-v', 'error', '-y', *decoder, '-i', str(source), '-t', str(preview_seconds),
                 '-map', '0:v:0', '-c:v', 'ffv1', '-pix_fmt', 'bgra' if alpha else 'bgr0', '-an', str(clip)])
            return convert(clip, output, mode, quality, model, subject, box)
    if not init_path and not segments:
        return convert(source, output, mode, quality, model, subject, box)
    parts = ([Path(init_path)] if init_path else []) + [source] + [Path(p) for p in segments]
    for part in parts:
        if not part.is_file() or part.stat().st_size == 0:
            raise ValueError(f'Missing or empty M4S input: {part.name}')
    emit(progress=0.01, phase=f'Assembling {1 + len(segments)} M4S segment(s)')
    with tempfile.TemporaryDirectory(prefix='deskdance-m4s-') as temp:
        joined = Path(temp) / 'joined.mp4'
        with joined.open('wb') as dest:
            for part in parts:
                with part.open('rb') as src:
                    shutil.copyfileobj(src, dest, length=1024 * 1024)
        try:
            probe(joined)
            # Verify presentation continuity instead of silently importing a partial
            # or backwards sequence. Decode-order DTS also works with B-frames.
            packets = json.loads(run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-show_packets', '-show_entries', 'packet=dts_time,duration_time',
                '-of', 'json', str(joined)])).get('packets', [])
            previous, previous_duration = None, None
            for packet in packets:
                try:
                    timestamp = float(packet['dts_time'])
                    packet_duration = float(packet.get('duration_time', '0'))
                except (KeyError, ValueError):
                    continue
                if previous is not None:
                    if timestamp <= previous:
                        raise ValueError('M4S segments are out of order or duplicated. Select one video track in chronological order.')
                    if previous_duration and timestamp > previous + previous_duration + 0.05:
                        raise ValueError('M4S segments have a timeline gap. Include all consecutive video segments to preserve the full clip.')
                previous, previous_duration = timestamp, packet_duration
            # Normalize the segment timestamps. A segment taken from minute 10 must
            # not become a ten-minute freeze frame followed by a short video.
            normalized = Path(temp) / 'normalized.mp4'
            run(['ffmpeg', '-v', 'error', '-y', '-i', str(joined), '-map', '0:v:0',
                 '-c:v', 'copy', '-an', '-avoid_negative_ts', 'make_zero', str(normalized)])
        except RuntimeError as exc:
            raise RuntimeError(f'Cannot assemble M4S video. Use its matching initialization file and unencrypted video segments from the same stream. {exc}') from exc
        return convert(normalized, output, mode, quality, model, subject, box)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('input'); parser.add_argument('output')
    parser.add_argument('--mode', choices=['auto', 'ai', 'green', 'blue', 'alpha', 'keep'], default='auto')
    parser.add_argument('--projection',choices=['flat','vr180-sbs'],default='flat')
    parser.add_argument('--quality', choices=['detailed', 'fast'], default='detailed')
    parser.add_argument('--model', choices=['legacy', 'matanyone2', 'wevisone-2b', 'wevisone-4b'], default='legacy')
    parser.add_argument('--subject', default='person')
    parser.add_argument('--box', type=json.loads)
    parser.add_argument('--preview-seconds', type=int)
    parser.add_argument('--init', dest='init_path')
    parser.add_argument('--segment', action='append', default=[])
    args = parser.parse_args()
    try:
        process(Path(args.input).resolve(), Path(args.output).resolve(), args.mode, args.init_path, args.segment, args.quality, args.model, args.subject, args.box, args.preview_seconds, args.projection)
    except Exception as exc:
        emit(error=str(exc))
        sys.exit(1)
