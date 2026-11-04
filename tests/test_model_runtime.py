import os
from pathlib import Path
import tempfile
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model_runtime import runtime_environment, is_python_runtime_directory


class RuntimeIsolationTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'POSIX loader-path behavior')
    def test_own_split_libraries_precede_system_paths_and_remove_foreign_runtimes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            own = root/'engine/lib/python3.12/site-packages/nvidia/cudnn/lib'
            own.mkdir(parents=True)
            torch = root/'engine/lib/python3.12/site-packages/torch/lib'
            torch.mkdir(parents=True)
            interpreter = root/'engine/bin/python'
            foreign = '/classic/lib/python3.12/site-packages/nvidia/cudnn/lib'
            other = '/other/lib/python3.11/site-packages/torch/lib'
            inherited = {'LD_LIBRARY_PATH':os.pathsep.join([foreign,other,'/usr/lib/nvidia','/opt/custom/lib']),
                         'PYTHONPATH':'/foreign/python','PYTHONHOME':'/foreign', 'KEEP_SETTING':'value'}
            result = runtime_environment(interpreter, inherited)
            paths = result['LD_LIBRARY_PATH'].split(os.pathsep)
            self.assertEqual(paths[:2],[str(own),str(torch)])
            self.assertEqual(paths[2:],['/usr/lib/nvidia','/opt/custom/lib'])
            self.assertNotIn('PYTHONHOME',result)
            self.assertNotIn('PYTHONPATH',result)
            self.assertEqual(result['KEEP_SETTING'],'value')
            self.assertEqual(result['VIRTUAL_ENV'],str(root/'engine'))
            self.assertIn('PYTHONPATH',inherited)  # parent environment is not mutated

    @unittest.skipIf(os.name == 'nt', 'POSIX loader-path behavior')
    def test_foreign_runtime_is_removed_even_for_cpu_only_environment(self):
        result=runtime_environment('/tmp/cpu-only/bin/python',{'LD_LIBRARY_PATH':'/classic/lib/python3.12/site-packages/nvidia/cudnn/lib'})
        self.assertEqual(result['LD_LIBRARY_PATH'],'')

    def test_windows_style_runtime_paths_are_recognized(self):
        self.assertTrue(is_python_runtime_directory(r'C:\Classic\Lib\site-packages\nvidia\cudnn\bin'))
        self.assertTrue(is_python_runtime_directory(r'C:\Classic\Lib\site-packages\torch\lib'))
        self.assertFalse(is_python_runtime_directory(r'C:\Windows\System32'))


if __name__=='__main__':unittest.main()
