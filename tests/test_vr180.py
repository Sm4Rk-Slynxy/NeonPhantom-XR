import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
import video_pipeline


class VR180Test(unittest.TestCase):
    def test_person_masks_are_independent_and_original_eye_colors_survive(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'stereo.mp4';output=root/'cutout.webm'
            frame=np.zeros((64,192,3),np.uint8);frame[:,:96]=(230,20,20);frame[:,96:]=(20,20,230)
            subprocess.run(['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','192x64','-r','12','-i','-',
                            '-c:v','libx264',str(source)],input=frame.tobytes()*12,check=True,capture_output=True)
            engines=[]
            class Engine:
                provider='TEST'
                def __init__(self):self.frames=[];engines.append(self)
                def matte(self,image):
                    pixels=np.asarray(image);self.frames.append(tuple(pixels[32,48]))
                    mask=np.zeros((64,96),np.uint8);mask[12:50,20:75]=255;mask[12:50,20:25]=128
                    return Image.fromarray(mask)
            with patch('cutout_engines.load_engine',side_effect=lambda *args:Engine()),contextlib.redirect_stdout(io.StringIO()) as events:
                video_pipeline.process(source,output,mode='ai',projection='vr180-sbs')
            self.assertEqual(len(engines),2)
            self.assertEqual([len(engine.frames) for engine in engines],[12,12])
            self.assertGreater(engines[0].frames[0][0],engines[0].frames[0][2])
            self.assertGreater(engines[1].frames[0][2],engines[1].frames[0][0])
            final=json.loads(events.getvalue().splitlines()[-1])['result']
            self.assertEqual(final['projection'],'vr180-sbs');self.assertAlmostEqual(final['duration_s'],1,delta=.05)
            raw=subprocess.run(['ffmpeg','-v','error','-c:v','libvpx-vp9','-i',str(output),'-frames:v','1','-f','rawvideo','-pix_fmt','rgba','-'],check=True,capture_output=True).stdout
            pixels=np.frombuffer(raw,np.uint8).reshape(64,192,4)
            for x in [0,96]:
                self.assertEqual(int(pixels[0,x,3]),0)
                self.assertGreater(int(pixels[30,x+40,3]),250)
                self.assertAlmostEqual(int(pixels[30,x+22,3]),128,delta=20)
            self.assertGreater(int(pixels[30,40,0]),200);self.assertGreater(int(pixels[30,136,2]),200)
            self.assertTrue((root/'thumb_cutout.png').is_file())


if __name__=='__main__':unittest.main()
