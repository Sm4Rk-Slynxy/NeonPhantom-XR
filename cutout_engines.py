"""Frame streaming adapters. Optional imports stay inside their selected engine."""
import os
from pathlib import Path


def validate_options(model, subject, box):
    if model not in ('legacy', 'matanyone2', 'wevisone-2b', 'wevisone-4b'):
        raise ValueError('Unsupported cutout model')
    if not isinstance(subject, str) or not 1 <= len(subject.strip()) <= 200:
        raise ValueError('Subject must contain 1–200 characters')
    if box is not None:
        import math
        if len(box) != 4 or not all(math.isfinite(v) and 0 <= v <= 1 for v in box) or box[0] >= box[2] or box[1] >= box[3]:
            raise ValueError('Subject box must be normalized x1,y1,x2,y2 coordinates within the frame')


def as_alpha(mask, size):
    import numpy as np
    from PIL import Image
    array = np.asarray(mask, dtype=np.float32).squeeze()
    if array.ndim != 2 or not np.isfinite(array).all():
        raise RuntimeError('Model returned an invalid alpha matte')
    return Image.fromarray(np.rint(np.clip(array, 0, 1) * 255).astype('uint8')).resize(size, Image.Resampling.BILINEAR)


class ClassicEngine:
    def __init__(self, fast=False):
        import onnxruntime as ort
        from rembg import new_session
        os.environ.setdefault('U2NET_HOME', str(Path(__file__).resolve().parent / '.models'))
        if 'CUDAExecutionProvider' in ort.get_available_providers() and hasattr(ort, 'preload_dlls'):
            ort.preload_dlls(directory='')
        providers = [p for p in ('CUDAExecutionProvider', 'MIGraphXExecutionProvider', 'ROCMExecutionProvider', 'CPUExecutionProvider') if p in ort.get_available_providers()]
        self.session = new_session('u2netp' if fast else 'u2net_human_seg', providers=providers)
        self.provider = self.session.inner_session.get_providers()[0]

    def matte(self, image):
        from rembg import remove
        return remove(image, session=self.session, only_mask=True).convert('L')


class MatAnyoneEngine:
    def __init__(self, box=None):
        from model_manager import model_path, MATANYONE_SHA256
        from secure_download import verify_sha256
        # Verify the published release before the third-party checkpoint loader.
        verify_sha256(model_path('matanyone2') / 'matanyone2.pth', MATANYONE_SHA256)
        import torch
        from matanyone2.inference.inference_core import InferenceCore
        from matanyone2.utils.get_default_model import get_matanyone2_model
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.provider = self.device.upper()
        self.processor = InferenceCore(get_matanyone2_model(str(model_path('matanyone2') / 'matanyone2.pth'), self.device), device=self.device)
        self.box = box
        self.started = False

    def matte(self, image):
        import numpy as np
        import torch
        from contextlib import nullcontext
        tensor = torch.from_numpy(np.array(image, dtype=np.float32) / 255).permute(2, 0, 1).to(self.device)
        context = torch.autocast('cuda', dtype=torch.float16) if self.device == 'cuda' else nullcontext()
        with torch.inference_mode(), context:
            if not self.started:
                # Match upstream's 0..255 first-frame alpha convention. A region
                # constrains the automatic person seed; it is never a solid-box matte.
                seed_engine = ClassicEngine()
                seed = np.array(seed_engine.matte(image), dtype=np.float32)
                del seed_engine
                if self.box:
                    w, h = image.size
                    x1, y1, x2, y2 = self.box
                    region = np.zeros(seed.shape, dtype=bool)
                    region[int(y1*h):int(y2*h), int(x1*w):int(x2*w)] = True
                    seed[~region] = 0
                if seed.max() < 128:
                    raise RuntimeError('No person found in the first frame. Adjust the region or use WeVisOne for other subjects.')
                self.processor.step(tensor, torch.from_numpy(seed).to(self.device), objects=[1])
                for _ in range(10):
                    output = self.processor.step(tensor, first_frame_pred=True)
                self.started = True
            else:
                output = self.processor.step(tensor)
            alpha = self.processor.output_prob_to_mask(output).float().cpu().numpy()
        return as_alpha(alpha, image.size)


class WeVisOneEngine:
    def __init__(self, model, subject):
        import torch
        from wevisone_vl import WeVisOneVL
        from model_manager import model_path
        self.provider = 'CUDA' if torch.cuda.is_available() else 'CPU'
        dtype = 'bfloat16' if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else 'float16'
        self.engine = WeVisOneVL(str(model_path(model)), device='auto', dtype=dtype, max_pixels=768*768)
        self.subject = subject

    def matte(self, image):
        import numpy as np
        from PIL import Image
        result = self.engine.predict(image, task='matting', query=self.subject, temperature=0.0, max_new_tokens=256)
        # An absent target is transparent, never a fallback to an unrelated object.
        if not result.masks:
            return Image.new('L', image.size, 0)
        return as_alpha(np.maximum.reduce(result.masks), image.size)


def load_engine(model, quality='detailed', subject='person', box=None):
    validate_options(model, subject, box)
    try:
        if model == 'legacy':
            return ClassicEngine(quality == 'fast')
        if model == 'matanyone2':
            return MatAnyoneEngine(box)
        return WeVisOneEngine(model, subject)
    except ImportError as exc:
        raise RuntimeError(f'{model} dependencies are missing. Install the selected model in the studio first. {exc}') from exc
