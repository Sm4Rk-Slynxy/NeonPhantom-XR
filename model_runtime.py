"""Build a child environment using the selected engine's CUDA libraries.

Classic's ONNX wrapper and a PyTorch engine can require different versions of
cuDNN. Its split libraries must all resolve from the same Python environment.
"""
import os
from pathlib import Path


def runtime_directories(interpreter):
    environment = Path(interpreter).absolute().parent.parent
    sites = [environment / 'Lib/site-packages'] if os.name == 'nt' else sorted(environment.glob('lib/python*/site-packages'))
    paths = []
    for site in sites:
        paths.extend(sorted(site.glob('nvidia/*/lib')))
        paths.extend(sorted(site.glob('nvidia/*/bin')))
        paths.append(site / 'torch/lib')
    return [str(path) for path in paths if path.is_dir()]


def is_python_runtime_directory(value):
    parts = value.replace('\\', '/').lower().split('/')
    # Remove only Python-distributed GPU runtimes. System driver locations and
    # unrelated user library paths remain available after the engine's own paths.
    for marker in ('site-packages', 'dist-packages'):
        if marker in parts:
            tail = parts[parts.index(marker) + 1:]
            return 'nvidia' in tail or ('torch' in tail and 'lib' in tail)
    return False


def runtime_environment(interpreter, inherited=None):
    result = dict(os.environ if inherited is None else inherited)
    own = runtime_directories(interpreter)
    key = 'PATH' if os.name == 'nt' else 'LD_LIBRARY_PATH'
    # Windows environment-variable names are case-insensitive, even when this
    # function receives a normal dict rather than os.environ.
    if os.name == 'nt':
        key = next((key for key in result if key.upper() == 'PATH'), 'PATH')
    keep = [path for path in result.get(key, '').split(os.pathsep)
            if path and not is_python_runtime_directory(path)]
    result[key] = os.pathsep.join(dict.fromkeys(own + keep))
    result['VIRTUAL_ENV'] = str(Path(interpreter).absolute().parent.parent)
    result.pop('PYTHONHOME', None)
    result.pop('PYTHONPATH', None)
    return result
