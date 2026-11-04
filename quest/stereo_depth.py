"""Local depth inference and depth-aware, alpha-preserving stereo synthesis."""
import hashlib
import json
import math
import os
from fractions import Fraction
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from media_security import local_media_command
import tempfile
from secure_download import download_https

from export_video import probe

MODEL_REVISION = '4472b7362082ad9968fee890ca0f1e5aca36b93d'
MODEL_SHA256 = 'fcf51f1b230362b28690bb9d1809bf0431f29cad20534e3f589bd7285547f20d'
MODEL_URL = f'https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/{MODEL_REVISION}/onnx/model_quantized.onnx'
MODEL_NAME = 'depth-anything-v2-small-q8.onnx'
GPU_MODEL_NAME = 'depth-anything-v2-small.onnx'
GPU_MODEL_SHA256 = 'afb6a5c28f3b6bf1618c6e43f02073ef9dfdc70e937502d51603e57b0a1df10c'
GPU_MODEL_URL = f'https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/{MODEL_REVISION}/onnx/model.onnx'


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        while chunk := source.read(1024*1024):digest.update(chunk)
    return digest.hexdigest()


def ensure_model(folder, progress, gpu=False):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    path = folder / (GPU_MODEL_NAME if gpu else MODEL_NAME)
    expected = GPU_MODEL_SHA256 if gpu else MODEL_SHA256
    if path.is_file() and sha256(path) == expected:
        return path
    progress(0, 'Downloading GPU depth model (99 MB, once)' if gpu else 'Downloading CPU depth model (27 MB, once)')
    download_https(GPU_MODEL_URL if gpu else MODEL_URL, path, expected)
    return path


class DepthEstimator:
    def __init__(self, model, device='cpu'):
        import numpy as np
        import onnxruntime as ort
        self.np = np
        options = ort.SessionOptions(); options.intra_op_num_threads = 4
        providers=['CPUExecutionProvider']
        if device!='cpu' and os.name=='nt' and hasattr(ort,'preload_dlls'):ort.preload_dlls(directory='')
        if device!='cpu':providers=[('CUDAExecutionProvider',{'gpu_mem_limit':2147483648,'cudnn_conv_algo_search':'HEURISTIC','cudnn_conv_use_max_workspace':'0'}),'CPUExecutionProvider']
        self.session = ort.InferenceSession(str(model), sess_options=options, providers=providers)
        self.device_label='gpu' if 'CUDAExecutionProvider' in self.session.get_providers() else 'cpu'
        self.session.disable_fallback()
        self.input = self.session.get_inputs()[0].name
        self.previous_image = self.previous_depth = self.limits = None

    def __call__(self, rgba):
        from PIL import Image
        np = self.np
        height, width = rgba.shape[:2]
        rgb = rgba[:, :, :3].astype(np.float32) / 255
        alpha = rgba[:, :, 3:4].astype(np.float32) / 255
        # Neutral compositing avoids feeding arbitrary hidden source RGB to the model.
        visible = rgb * alpha + 0.45 * (1 - alpha)
        scale = 518 / max(width, height)
        size = (max(14, round(width * scale / 14) * 14), max(14, round(height * scale / 14) * 14))
        image = Image.fromarray(np.uint8(visible * 255)).resize(size, Image.Resampling.BICUBIC)
        inputs = np.asarray(image, dtype=np.float32) / 255
        inputs = (inputs - np.array([.485,.456,.406],dtype=np.float32)) / np.array([.229,.224,.225],dtype=np.float32)
        raw = self.session.run(None, {self.input:inputs.transpose(2,0,1)[None]})[0].squeeze()
        raw = np.asarray(Image.fromarray(raw).resize((width,height),Image.Resampling.BILINEAR))
        if not np.isfinite(raw).all():
            raise RuntimeError('Depth model returned invalid values')
        foreground = raw[alpha[:,:,0] > .5]
        low, high = np.percentile(foreground if foreground.size > 32 else raw, [2,98])
        cut = self.previous_image is None or float(np.mean(np.abs(visible-self.previous_image))) > .18
        if cut or self.limits is None:
            self.limits = (low, high)
        else:
            self.limits = tuple(.85*old+.15*new for old,new in zip(self.limits,(low,high)))
        low,high = self.limits
        depth = np.clip((raw-low)/max(float(high-low),1e-6),0,1).astype(np.float32)
        if not cut:
            stable = np.mean(np.abs(visible-self.previous_image),axis=2) < .04
            depth = np.where(stable,.35*self.previous_depth+.65*depth,depth)
        self.previous_image,self.previous_depth = visible,depth
        return depth


class ResilientDepthEstimator:
    def __init__(self, folder, device, progress):
        import onnxruntime as ort
        self.folder,self.progress = folder,progress
        self.fallback_reason = None
        self.estimator = None
        if device != 'cpu' and 'CUDAExecutionProvider' in ort.get_available_providers():
            try:
                self.estimator = DepthEstimator(ensure_model(folder,progress,gpu=True),'gpu')
                if self.estimator.device_label!='gpu':raise RuntimeError('CUDA provider did not initialize')
            except Exception:
                self.estimator = None
                self.fallback_reason = 'GPU initialization unavailable; using CPU'
        elif device!='cpu':
            self.fallback_reason = 'No CUDA runtime available; using CPU'
        if self.estimator is None:self.use_cpu()

    @property
    def device_label(self):return self.estimator.device_label

    def use_cpu(self):
        self.progress(0,self.fallback_reason or 'Loading CPU depth model')
        self.estimator = DepthEstimator(ensure_model(self.folder,self.progress))

    def __call__(self, rgba):
        try:return self.estimator(rgba)
        except Exception:
            if self.device_label!='gpu':raise
            self.fallback_reason='GPU inference unavailable; using CPU'
            self.estimator=None
            self.use_cpu()
            return self.estimator(rgba)


def synthesize_views(rgba, depth, strength):
    """Forward warp each eye, keeping the nearer depth at collisions."""
    import numpy as np
    height,width = depth.shape
    if not math.isfinite(strength) or not 0 <= strength <= .03:
        raise ValueError('Depth strength must be between 0 and 3 percent')
    yy,xx = np.indices((height,width))
    disparity = (depth-.5) * (strength*width)
    views = []
    for sign in (1,-1):
        target = np.rint(xx+sign*disparity/2).astype(np.int32)
        valid = (target>=0)&(target<width)&(rgba[:,:,3]>0)
        indices = (yy[valid]*width+target[valid]).ravel()
        z = np.full(height*width,-np.inf,dtype=np.float32)
        np.maximum.at(z,indices,depth[valid])
        winner = depth[valid] >= z[indices]
        view = np.zeros_like(rgba).reshape(-1,4)
        view[indices[winner]] = rgba[valid][winner]
        view = view.reshape(rgba.shape)
        # Interpolate disocclusion holes inside the source silhouette. Preserve
        # transparent space outside it, rather than stretching a cutout to edges.
        for y in range(height):
            known = np.flatnonzero(view[y,:,3]>0)
            missing = np.flatnonzero((view[y,:,3]==0)&(rgba[y,:,3]>128))
            if known.size and missing.size:
                for channel in range(4):
                    view[y,missing,channel] = np.interp(missing,known,view[y,known,channel])
        views.append(view)
    return tuple(views)


def convert_video(source, folder, model_folder, strength=.015, progress=None, estimator=None, device='cpu'):
    """Create ordinary full SBS plus packed-alpha SBS for the Quest viewer."""
    try:
        import numpy as np
        import PIL
        import onnxruntime
    except ImportError as error:
        raise RuntimeError('Depth conversion needs the Quest Python packages. Run setup-quest.sh (Linux) or setup-windows.cmd (Windows).') from error
    progress = progress or (lambda amount,phase: None)
    if not math.isfinite(strength) or not 0 < strength <= .03:
        raise ValueError('Choose a depth strength above zero and at most 3 percent')
    if device not in ('auto','gpu','cpu'):raise ValueError('Choose Auto, GPU or CPU processing')
    data,stream = probe(source)
    fps = Fraction(stream.get('avg_frame_rate') or stream.get('r_frame_rate') or '30')
    if fps <= 0 or fps > 240:
        raise ValueError('Unsupported video frame rate')
    duration = float(stream.get('duration') or data.get('format',{}).get('duration') or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Cannot determine source duration')
    scale = min(1,960/stream['width'],720/stream['height'])
    width,height = max(2,int(stream['width']*scale/2)*2),max(2,int(stream['height']*scale/2)*2)
    alpha = stream.get('pix_fmt','').startswith(('yuva','gbrap','rgba','bgra')) or any(key.lower()=='alpha_mode' and str(value)=='1' for key,value in stream.get('tags',{}).items())
    if estimator is None:
        estimator = ResilientDepthEstimator(model_folder,device,progress)
    decoder = ['-c:v','libvpx-vp9'] if stream.get('codec_name')=='vp9' else []
    folder = Path(folder); folder.mkdir(parents=True,exist_ok=True)
    outputs = ('sbs.mp4','quest.mp4')
    with tempfile.TemporaryDirectory(prefix='stereo-',dir=folder) as temporary:
        temporary = Path(temporary)
        processes, logs = [], []
        decoder_process = None
        frames = 0
        try:
            for name,frame_width in zip(outputs,(width*2,width*4)):
                log = (temporary/(name+'.log')).open('wb');logs.append(log)
                command = ['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{frame_width}x{height}',
                           '-r',str(fps),'-i','-']
                command += ['-i',str(source),'-map','0:v:0','-map','1:a:0?','-c:a','aac','-b:a','192k','-af','apad','-shortest']
                command += ['-c:v','libx264','-threads','2','-preset','fast','-crf','19','-pix_fmt','yuv420p',
                            '-movflags','+faststart','-map_metadata','-1',str(temporary/name)]
                processes.append(subprocess.Popen(local_media_command(command),stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log))
            decoder_log = (temporary/'decode.log').open('wb');logs.append(decoder_log)
            decoder_process = subprocess.Popen(local_media_command(['ffmpeg','-v','error','-xerror',*decoder,'-i',str(source),
                '-vf',f'fps={fps},scale={width}:{height}','-f','rawvideo','-pix_fmt','rgba','-']),
                stdout=subprocess.PIPE,stderr=decoder_log)
            while True:
                raw = decoder_process.stdout.read(width*height*4)
                if not raw:break
                if len(raw)!=width*height*4:
                    raise RuntimeError('Video ended inside a frame')
                rgba = np.frombuffer(raw,dtype=np.uint8).reshape(height,width,4)
                left,right = synthesize_views(rgba,estimator(rgba),strength)
                color = np.concatenate((left[:,:,:3],right[:,:,:3]),axis=1)
                mask = np.concatenate((left[:,:,3:4],right[:,:,3:4]),axis=1)
                opaque = np.uint8(color.astype(np.float32)*(mask.astype(np.float32)/255))
                packed = np.concatenate((color,np.repeat(mask,3,axis=2)),axis=1)
                processes[0].stdin.write(opaque.tobytes());processes[1].stdin.write(packed.tobytes())
                frames+=1
                progress(min(.98,frames/(duration*float(fps))),f'{getattr(estimator,"device_label","cpu").upper()} · stereo frame {frames} / about {round(duration*float(fps))}')
            decoder_process.stdout.close()
            if decoder_process.wait()!=0:
                raise RuntimeError('Video decode failed: '+(temporary/'decode.log').read_text()[-1200:])
            for process,name in zip(processes,outputs):
                process.stdin.close()
                if process.wait()!=0:
                    raise RuntimeError('Stereo encode failed: '+(temporary/(name+'.log')).read_text()[-1200:])
            if frames/float(fps)+1/float(fps)+.05 < duration:
                raise RuntimeError('Stereo output would shorten the source; conversion rejected')
            for name in outputs:
                converted,_=probe(temporary/name)
                if float(converted['format']['duration'])+.05 < frames/float(fps):
                    raise RuntimeError('Encoded stereo duration is shorter than the generated video')
            for name in outputs:(temporary/name).replace(folder/name)
        finally:
            if decoder_process is not None:
                if decoder_process.poll() is None:decoder_process.kill()
                decoder_process.wait()
                if decoder_process.stdout:decoder_process.stdout.close()
            for process in processes:
                if process.poll() is None:process.kill()
                process.wait()
                if process.stdin and not process.stdin.closed:
                    try:process.stdin.close()
                    except BrokenPipeError:pass
            for log in logs:log.close()
    progress(1,'Ready')
    return dict(width=width,height=height,duration_s=frames/float(fps),has_alpha=alpha,
                has_audio=any(item.get('codec_type')=='audio' for item in data['streams']),
                stereo_layout='sbs-full',packed_alpha=True,format='stereo-rgb-alpha-horizontal-v1',
                depth_model='Depth Anything V2 Small (ONNX)',depth_strength=strength,
                processing_device=getattr(estimator,'device_label','cpu'),fallback_reason=getattr(estimator,'fallback_reason',None))
