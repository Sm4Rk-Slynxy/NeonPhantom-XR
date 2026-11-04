"""Preserve headset-ready VR180 SBS stereo while matting each eye separately."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def process_vr180(source,output,mode='auto',quality='detailed',model='legacy',subject='person',box=None):
    import video_pipeline as pipeline
    info,stream=pipeline.probe(source)
    source,output=Path(source),Path(output)
    if stream['width']%4 or stream['height']%2:
        raise ValueError('VR180 SBS needs two equal, even-sized eye images')
    if model!='legacy' and mode in ('auto','ai') and not (mode=='auto' and pipeline.has_alpha(stream)):
        from model_manager import python_for,model_path
        interpreter=python_for(model)
        if not interpreter.is_file() or not (model_path(model)/'ready.json').is_file():
            raise RuntimeError(f'{model} is not installed. Install it in the model picker first.')
        if Path(sys.executable).absolute()!=interpreter.absolute():
            from model_runtime import runtime_environment
            args=[str(interpreter),str(Path(pipeline.__file__).resolve()),str(source),str(output),
                  '--projection','vr180-sbs','--mode',mode,'--quality',quality,'--model',model,'--subject',subject]
            if box is not None:args+=['--box',json.dumps(box)]
            child=subprocess.Popen(args,stdout=subprocess.PIPE,text=True,env=runtime_environment(interpreter))
            error=None
            for line in child.stdout:
                print(line,end='',flush=True)
                try:error=json.loads(line).get('error') or error
                except ValueError:pass
            if child.wait():raise RuntimeError(error or 'VR180 person cutout failed')
            return
    output.parent.mkdir(parents=True,exist_ok=True)
    emit=pipeline.emit
    try:
        with tempfile.TemporaryDirectory(prefix='vr180-eyes-',dir=output.parent) as temporary:
            temporary=Path(temporary);eyes=[]
            for eye in range(2):
                label='Left' if eye==0 else 'Right'
                raw=temporary/f'eye-{eye}.mkv';matted=temporary/f'eye-{eye}.webm'
                decoder=['-c:v','libvpx-vp9'] if stream.get('codec_name')=='vp9' and pipeline.has_alpha(stream) else []
                emit(progress=.02+eye*.45,phase=f'{label} eye · preparing VR180 view')
                pipeline.run(['ffmpeg','-v','error','-y',*decoder,'-i',str(source),'-vf',
                    f'crop={stream["width"]//2}:{stream["height"]}:{eye*(stream["width"]//2)}:0',
                    '-c:v','ffv1','-pix_fmt','bgra' if pipeline.has_alpha(stream) else 'bgr0','-an',str(raw)])
                def eye_progress(**event):
                    event.pop('result',None)
                    if 'progress' in event:event['progress']=.04+eye*.43+event['progress']*.42
                    if 'phase' in event:event['phase']=label+' eye · '+event['phase']
                    emit(**event)
                pipeline.emit=eye_progress
                try:pipeline._process_video(raw,matted,mode,quality,model,subject,box)
                finally:pipeline.emit=emit
                eyes.append(matted)
                raw.unlink()
            alpha=mode!='keep'
            emit(progress=.92,phase='Combining original stereo views with their alpha masks')
            pipeline.run(['ffmpeg','-v','error','-y','-c:v','libvpx-vp9','-i',str(eyes[0]),
                '-c:v','libvpx-vp9','-i',str(eyes[1]),'-filter_complex',
                '[0:v:0][1:v:0]hstack=inputs=2[stereo]','-map','[stereo]','-c:v','libvpx-vp9',
                '-pix_fmt','yuva420p' if alpha else 'yuv420p','-b:v','0','-crf','25','-deadline','good',
                '-cpu-used','4','-map_metadata','-1','-an',str(output)])
            converted,_=pipeline.probe(output)
            duration=float(converted['format']['duration'])
            source_duration=float(info.get('format',{}).get('duration',duration))
            if duration+.01<source_duration:raise RuntimeError('VR180 output would shorten the source')
            shutil.copy2(temporary/'thumb_eye-0.png',output.with_name('thumb_'+output.stem+'.png'))
            emit(progress=1,phase='VR180 stereo cutout ready',result=dict(duration_s=duration,source_duration_s=source_duration,
                has_alpha=alpha,matted=mode not in ('keep','alpha'),model=model if mode in ('auto','ai') else None,
                projection='vr180-sbs',stereo_layout='sbs-full'))
    except Exception:
        pipeline.emit=emit;output.unlink(missing_ok=True)
        output.with_name('thumb_'+output.stem+'.png').unlink(missing_ok=True)
        raise
