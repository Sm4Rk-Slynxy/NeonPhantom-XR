"""Generate synthetic footage and invented library data for UI screenshots.

Usage: python scripts/generate_demo.py --output /tmp/neonphantom-demo
Never point this at your real library. Requires Pillow and FFmpeg.
"""
import argparse
import json
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw


def figure(color,variant=0):
    image=Image.new('RGBA',(480,640));d=ImageDraw.Draw(image)
    skin='#dcb191';dark='#222b29'
    # Deliberately geometric mannequin: no person's likeness or downloaded media.
    d.ellipse((197,52,283,138),fill=skin)
    d.polygon([(206,135),(274,135),(306,310),(173,310)],fill=color)
    d.line([(209,161),(153,218),(100,150 if variant else 244)],fill=skin,width=25)
    d.line([(271,161),(321,230),(375,145 if variant else 258)],fill=skin,width=25)
    d.polygon([(180,303),(239,303),(228,453),(201,570),(166,570),(190,442)],fill=dark)
    d.polygon([(239,303),(301,303),(291,440),(330,567),(293,579),(247,452)],fill=dark)
    d.rounded_rectangle((151,562,204,591),radius=8,fill='#e1e8db')
    d.rounded_rectangle((287,562,347,591),radius=8,fill='#e1e8db')
    d.rectangle((196,202,283,208),fill='#eff3e7')
    return image


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.output
    root.mkdir(parents=True,exist_ok=True)
    if any(root.iterdir()):raise SystemExit('Use a new empty demo directory')
    media=root/'media';media.mkdir();cards=[]
    for index,(name,color) in enumerate([('Motion study / 01','#d1f378'),('Chromakey study / 02','#dca27d'),('VR180 stereo / 03','#92c2bd')]):
        identifier=f'demo{index+1}';image=figure(color,index%2)
        if index==2:
            stereo=Image.new('RGBA',(1280,640));left=image.resize((400,534));stereo.alpha_composite(left,(120,66));stereo.alpha_composite(left,(760,66));image=stereo
        png=media/f'thumb_{identifier}.png';image.save(png)
        subprocess.run(['ffmpeg','-v','error','-y','-loop','1','-i',str(png),'-t','2','-r','12','-c:v','libvpx-vp9','-b:v','0','-crf','20','-pix_fmt','yuva420p','-an',str(media/f'{identifier}.webm')],check=True)
        if index==2:figure(color,1).save(png)
        cards.append(dict(id=identifier,file=f'{identifier}.webm',thumb=f'/media/{png.name}',name=name,duration_s=2,has_alpha=True,matted=True,projection='vr180-sbs' if index==2 else 'flat',model='',preview=False))
    state=dict(cards=cards,playlists={'Demo collection':[c['id'] for c in cards]},favorites=['demo1'],jobs=[],overlay_height=600,overlay_corner='br')
    (root/'state.json').write_text(json.dumps(state,indent=2))
    print('Generated synthetic demo in',root)


if __name__=='__main__':main()
