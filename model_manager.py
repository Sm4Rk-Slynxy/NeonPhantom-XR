"""Install optional cutout engines into separate, app-local Python environments."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
from model_runtime import runtime_environment
from secure_download import download_https

ROOT = Path(__file__).resolve().parent
MODELS = {
    'legacy': ('Classic cutout', None, None),
    'matanyone2': ('MatAnyone 2 · people', 'matanyone2', None),
    'wevisone-2b': ('WeVisOne 2B · experimental', 'wevisone', 'tencent/WeVisOne-VL-2B'),
    'wevisone-4b': ('WeVisOne 4B · experimental', 'wevisone', 'tencent/WeVisOne-VL-4B'),
}
REVISIONS = {
    'matanyone2': '0079197acd6d16a741f71558809c06c586c579e0',
    'wevisone': '9a6bcd85404505df0d05cfb5d97512ccacf35dee',
}
MATANYONE_SHA256 = '5e9821e4087231427376b437c85bb6e072b41e582314f06fd524f75bc4af5914'
WEVISONE_REVISIONS = {
    'wevisone-2b': 'fcf8c8ca7fa481b514005ef591c8b72bed39618a',
    'wevisone-4b': '6b44a45873b4bbc7dca383922504430dc60eca23',
}


def python_for(model):
    family = MODELS[model][1]
    return ROOT / f'.venv-{family}' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def model_path(model):
    return ROOT / '.models' / model


def status():
    items = []
    for key, (label, family, _) in MODELS.items():
        ready = (model_path(key) / 'ready.json').is_file() and python_for(key).is_file() if family else importlib.util.find_spec('rembg') is not None
        items.append({'id': key, 'label': label, 'installed': ready,
                      'experimental': key.startswith('wevisone'), 'installable': bool(family)})
    return items


def emit(**event):
    print(json.dumps(event), flush=True)


def command(args, phase):
    emit(progress=0.15, phase=phase)
    # Keep third-party output off stdout: it is reserved for the job JSON protocol.
    result = subprocess.run([str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, env=runtime_environment(args[0]))
    if result.returncode:
        raise RuntimeError(f'{phase} failed: {result.stdout[-3500:]}')


def install_matanyone_source(python):
    """Repair an upstream wheel-packaging duplicate, retaining pinned inference code."""
    url = f'https://github.com/pq-yang/MatAnyone2/archive/{REVISIONS["matanyone2"]}.zip'
    with tempfile.TemporaryDirectory(prefix='deskdance-engine-') as directory:
        archive = Path(directory) / 'source.zip'
        download_https(url, archive)
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                target = (Path(directory) / member.filename).resolve()
                if not target.is_relative_to(Path(directory).resolve()):
                    raise RuntimeError('Invalid path in model source archive')
            source.extractall(directory)
        project = next(Path(directory).glob('MatAnyone2-*'))
        metadata = project / 'pyproject.toml'
        text = metadata.read_text()
        duplicate = '[tool.hatch.build.targets.wheel.force-include]\n"matanyone2/config" = "matanyone2/config"\n'
        if duplicate not in text:
            raise RuntimeError('Pinned MatAnyone packaging changed unexpectedly')
        metadata.write_text(text.replace(duplicate, ''))
        command([python, '-m', 'pip', 'install', '--no-deps', project], 'Installing pinned MatAnyone inference source')


def install(model):
    if model not in MODELS or model == 'legacy':
        raise ValueError('Choose MatAnyone 2 or WeVisOne to install.')
    if not (3, 11) <= sys.version_info[:2] <= (3, 13):
        raise RuntimeError('Model installation needs Python 3.11–3.13. Set DESKDANCE_PYTHON to a compatible interpreter and restart.')
    _, family, repo = MODELS[model]
    python = python_for(model)
    destination = model_path(model)
    destination.mkdir(parents=True, exist_ok=True)
    marker = destination / 'ready.json'
    # A failed repair cannot continue advertising this model as ready.
    marker.unlink(missing_ok=True)
    if not python.is_file():
        command([sys.executable, '-m', 'venv', python.parent.parent], 'Creating isolated model environment')
    command([python, '-m', 'pip', 'install', '--upgrade', 'pip'], 'Preparing package installer')
    emit(progress=0.2, phase='Installing engine dependencies (several GB; this can take a while)')
    if family == 'matanyone2':
        # Upstream's full training dependencies include platform-specific GUI/build
        # packages. Install the inference subset and the pinned package without them.
        packages = ['torch', 'torchvision', 'kornia', 'hydra-core', 'einops', 'opencv-python',
                    'Pillow>=13.0.0', 'certifi>=2026.10.23', 'huggingface-hub', 'safetensors', 'tqdm', 'scipy', 'imageio',
                    'rembg[cpu]==2.0.86', 'onnxruntime', 'requests']
        command([python, '-m', 'pip', 'install', *packages], 'Installing MatAnyone inference dependencies')
        install_matanyone_source(python)
        script = '''
from pathlib import Path
import sys, torch
from secure_download import download_https
from model_manager import MATANYONE_SHA256
from rembg import new_session
from matanyone2.inference.inference_core import InferenceCore
from matanyone2.utils.get_default_model import get_matanyone2_model
path = Path(sys.argv[1]) / 'matanyone2.pth'
download_https('https://github.com/pq-yang/MatAnyone2/releases/download/v1.0.0/matanyone2.pth', path, MATANYONE_SHA256)
new_session('u2net_human_seg', providers=['CPUExecutionProvider'])
model = get_matanyone2_model(str(path), 'cpu')
'''
    else:
        url = f'https://github.com/Tencent/WeVisOne-VL/archive/{REVISIONS[family]}.zip'
        command([python, '-m', 'pip', 'install', 'Pillow>=13.0.0', 'certifi>=2026.10.23', url], 'Installing pinned WeVisOne source and dependencies')
        script = '''
import sys
from huggingface_hub import snapshot_download
from wevisone_vl import WeVisOneVL
snapshot_download(repo_id=sys.argv[2], revision=sys.argv[3], local_dir=sys.argv[1], ignore_patterns=['*.md', '*.png', '*.jpg'])
'''
    emit(progress=0.65, phase='Downloading and checking model files')
    env = {**runtime_environment(python), 'U2NET_HOME': str(ROOT / '.models')}
    result = subprocess.run([str(python), '-c', script, str(destination), repo or '', WEVISONE_REVISIONS.get(model, '')],
                            env=env, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode:
        raise RuntimeError(f'Model download or validation failed: {result.stdout[-3500:]}')
    temporary = marker.with_suffix('.tmp')
    temporary.write_text(json.dumps({'model': model, 'source_revision': REVISIONS[family],
                                    'weights_revision': WEVISONE_REVISIONS.get(model),
                                    'weights_sha256': MATANYONE_SHA256 if family == 'matanyone2' else None}))
    temporary.replace(marker)
    emit(progress=1.0, phase='Model installed', result={'model': model, 'installed': True})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['list', 'install'])
    parser.add_argument('model', nargs='?', choices=MODELS)
    args = parser.parse_args()
    try:
        if args.action == 'list':
            print(json.dumps(status()))
        else:
            install(args.model)
    except Exception as exc:
        emit(error=str(exc))
        sys.exit(1)
