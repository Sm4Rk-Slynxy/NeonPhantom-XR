"""Regression checks for real depth parallax, alpha, encoding and job access."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'quest'))
import numpy as np
from companion import Library
from export_video import probe
from stereo_depth import synthesize_views, convert_video
from stereo_jobs import StereoJobs


class DepthStereoTest(unittest.TestCase):
    def test_depth_changes_eye_views_and_foreground_wins(self):
        image=np.zeros((20,200,4),np.uint8);image[:,:,3]=255;image[:,:,:3]=30
        image[:,90:100,:3]=240
        depth=np.full((20,200),.5,np.float32);depth[:,90:100]=1
        left,right=synthesize_views(image,depth,.03)
        self.assertFalse(np.array_equal(left,right))
        self.assertGreater(np.mean(np.where(left[10,:,0]>200)),np.mean(np.where(right[10,:,0]>200)))
        self.assertTrue(np.all(left[:,:,3]==255))
        flat=np.full_like(depth,.5)
        flat_left,flat_right=synthesize_views(image,flat,.03)
        np.testing.assert_array_equal(flat_left,image);np.testing.assert_array_equal(flat_left,flat_right)

    def test_alpha_moves_with_color_without_filling_transparent_background(self):
        image=np.zeros((20,200,4),np.uint8);image[:,70:130]=(230,20,10,255)
        depth=np.ones((20,200),np.float32)
        left,right=synthesize_views(image,depth,.03)
        self.assertEqual(int(left[10,0,3]),0);self.assertEqual(int(right[10,-1,3]),0)
        self.assertGreater(np.argmax(left[10,:,3]),np.argmax(right[10,:,3]))

    def test_full_duration_audio_and_different_sbs_halves(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=12:duration=1',
                            '-f','lavfi','-i','sine=frequency=440:duration=0.5','-c:v','libx264','-c:a','aac',str(source)],check=True,capture_output=True)
            metadata=convert_video(source,root/'result',root/'models',.03,estimator=lambda rgba:np.tile(np.linspace(0,1,rgba.shape[1],dtype=np.float32),(rgba.shape[0],1)))
            self.assertEqual(metadata['stereo_layout'],'sbs-full');self.assertAlmostEqual(metadata['duration_s'],1,delta=.01)
            data,stream=probe(root/'result/sbs.mp4');self.assertEqual(stream['width'],640)
            self.assertTrue(any(stream['codec_type']=='audio' for stream in data['streams']))
            self.assertAlmostEqual(float(data['format']['duration']),1,delta=.05)
            _,packed=probe(root/'result/quest.mp4');self.assertEqual(packed['width'],1280)
            raw=subprocess.run(['ffmpeg','-v','error','-i',str(root/'result/sbs.mp4'),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True).stdout
            image=np.frombuffer(raw,np.uint8).reshape(180,640,3)
            self.assertGreater(float(np.mean(np.abs(image[:,:320].astype(float)-image[:,320:].astype(float)))),1)

    def test_stereo_alpha_masks_preserve_soft_edges(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'alpha.webm'
            image=np.zeros((60,200,4),np.uint8);image[:,:,:3]=(230,40,20)
            image[:,70:110,3]=128;image[:,110:170,3]=255
            subprocess.run(['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgba','-s','200x60','-r','12','-i','-',
                            '-c:v','libvpx-vp9','-lossless','1','-pix_fmt','yuva420p',str(source)],input=image.tobytes()*12,check=True,capture_output=True)
            metadata=convert_video(source,root/'result',root/'models',.03,estimator=lambda rgba:np.tile(np.linspace(0,1,200,dtype=np.float32),(60,1)))
            self.assertTrue(metadata['has_alpha'])
            raw=subprocess.run(['ffmpeg','-v','error','-i',str(root/'result/quest.mp4'),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],check=True,capture_output=True).stdout
            packed=np.frombuffer(raw,np.uint8).reshape(60,800,3)
            for start in (400,600):
                self.assertLess(int(packed[30,start+10,0]),5)
                self.assertAlmostEqual(int(packed[30,start+85,0]),128,delta=6)
                self.assertGreater(int(packed[30,start+140,0]),249)

    def test_job_persistence_and_original_deletion_restricts_download(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);media=root/'media';media.mkdir();(media/'clip.webm').write_bytes(b'original')
            state=root/'state.json';state.write_text(json.dumps({'cards':[{'id':'source','file':'clip.webm','name':'Original'}]}))
            library=Library(state,media,root/'exports');manager=StereoJobs(library)
            def convert(source,folder,*args):
                folder.mkdir();(folder/'sbs.mp4').write_bytes(b'SBS');(folder/'quest.mp4').write_bytes(b'packed')
                return dict(width=100,height=100,duration_s=1,has_alpha=True,stereo_layout='sbs-full',packed_alpha=True)
            with patch('stereo_jobs.convert_video',convert):
                job=manager.start('source',.015)
                for _ in range(100):
                    if manager.snapshot()[0]['state']!='running':break
                    time.sleep(.01)
            self.assertEqual(manager.snapshot()[0]['state'],'done')
            self.assertEqual(manager.file(job['id'],True).read_bytes(),b'SBS')
            self.assertEqual(len(StereoJobs(library).cards({'source'})),1)
            self.assertEqual((media/'clip.webm').read_bytes(),b'original')
            state.write_text('{"cards":[]}')
            self.assertEqual(manager.cards(set()),[])
            with self.assertRaises(ValueError):manager.file(job['id'])
            with self.assertRaises(ValueError):manager.start('../secret',.015)
            with self.assertRaises(ValueError):manager.start('source',float('nan'))

    def test_auto_prepare_waits_for_imports_and_persists_each_request(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state=root/'state.json'
            job=dict(job_id='request',card_id='source',state='done',prepare_stereo=True,stereo_device='gpu')
            state.write_text(json.dumps({'cards':[],'jobs':[job,{'state':'running'}]}))
            library=Library(state,root/'media',root/'exports');manager=StereoJobs(library)
            with patch.object(manager,'start',return_value={'id':'sbs_012345abcdef'}) as start:
                manager.queue_requested_imports();start.assert_not_called()
                state.write_text(json.dumps({'cards':[],'jobs':[job]}))
                manager.queue_requested_imports();manager.queue_requested_imports()
                start.assert_called_once_with('source',.015,'gpu')
            reloaded=StereoJobs(library)
            with patch.object(reloaded,'start') as start:
                reloaded.queue_requested_imports();start.assert_not_called()



if __name__=='__main__':unittest.main()
