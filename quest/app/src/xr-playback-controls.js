import * as THREE from 'three';

const WIDTH=1280, HEIGHT=360, IDLE_MS=5000;
const BUTTONS=[
  ['play','Play'],['back','−10 s'],['forward','+10 s'],['mute','Unmute'],['exit','Exit VR'],
  ['smaller','Smaller'],['bigger','Bigger'],['recenter','Recenter'],['move','Move video'],['hide','Hide controls']
].map(([id,label],index)=>({id,label,x:24+(index%5)*249.2,y:index<5?96:206,width:235.2,height:88}));

// A real scene panel works in immersive VR even without DOM-overlay support.
export class XRPlaybackControls {
  constructor(scene,video,onAction,onVisibility){
    this.video=video;this.onAction=onAction;this.onVisibility=onVisibility;
    this.canvas=document.createElement('canvas');this.canvas.width=WIDTH;this.canvas.height=HEIGHT;
    this.context=this.canvas.getContext('2d');
    this.texture=new THREE.CanvasTexture(this.canvas);this.texture.colorSpace=THREE.SRGBColorSpace;
    this.panel=new THREE.Mesh(new THREE.PlaneGeometry(1,1),new THREE.MeshBasicMaterial({map:this.texture,transparent:true,depthTest:false,depthWrite:false,side:THREE.DoubleSide,toneMapped:false}));
    this.panel.name='VR playback controls';this.panel.visible=false;this.panel.renderOrder=1000;scene.add(this.panel);
    this.raycaster=new THREE.Raycaster();this.raycaster.layers.enable(1);this.raycaster.layers.enable(2);
    this.controllers=[];this.deadline=0;this.lastDraw=0;this.hover=null;this.moving=false;this.dirty=true;this.anchorVersion=0;
  }
  attach(controller,line){this.controllers.push({controller,line});}
  show(){this.anchorVersion++;this.panel.visible=true;this.deadline=performance.now()+IDLE_MS;this.dirty=true;this.onVisibility(true);}
  hide(){this.panel.visible=false;this.moving=false;this.hover=null;this.onVisibility(false);}
  ray(controller){
    controller.updateWorldMatrix(true,false);
    this.raycaster.set(controller.getWorldPosition(new THREE.Vector3()),new THREE.Vector3(0,0,-1).applyQuaternion(controller.getWorldQuaternion(new THREE.Quaternion())));
    return this.raycaster;
  }
  buttonAt(uv){
    const x=uv.x*WIDTH,y=(1-uv.y)*HEIGHT;
    return BUTTONS.find(button=>x>=button.x&&x<=button.x+button.width&&y>=button.y&&y<=button.y+button.height);
  }
  select(controller,videoMesh){
    const ray=this.ray(controller);
    if(this.panel.visible){
      const hit=ray.intersectObject(this.panel,false)[0];
      if(hit){
        const button=this.buttonAt(hit.uv);this.show();
        if(button&&!(this.immersiveVideo&&['move','smaller','bigger'].includes(button.id))){
          if(button.id==='hide')this.hide();
          else if(button.id==='move'){this.moving=!this.moving;this.dirty=true;}
          else this.onAction(button.id);
        }
        return;
      }
    }
    if(this.moving){
      this.moving=false;this.onAction('place',ray.ray.clone());this.show();return;
    }
    if(videoMesh.visible&&ray.intersectObject(videoMesh,true).length){this.show();return;}
    this.hide();
  }
  update(now,videoMesh){
    if(!videoMesh.visible){this.hide();return;}
    if(this.panel.visible&&now>=this.deadline)this.hide();
    const width=THREE.MathUtils.clamp(videoMesh.scale.x,.9,1.5);
    this.panel.scale.set(width,width*HEIGHT/WIDTH,1);
    this.panel.quaternion.copy(videoMesh.quaternion);
    this.panel.position.copy(videoMesh.position).add(new THREE.Vector3(0,-Math.min(videoMesh.scale.y*.25,.4),.025).applyQuaternion(videoMesh.quaternion));
    this.panel.updateMatrixWorld(true);
    let hovered=null;
    for(const {controller,line} of this.controllers){
      if(!controller.visible){line.visible=false;continue;}
      const ray=this.ray(controller);
      const panelHit=this.panel.visible?ray.intersectObject(this.panel,false)[0]:null;
      const hit=panelHit||(videoMesh.visible?ray.intersectObject(videoMesh,true)[0]:null);
      line.visible=!!hit||this.moving;
      line.scale.z=hit?hit.distance:3;
      if(panelHit)hovered=this.buttonAt(panelHit.uv)?.id||hovered;
    }
    if(hovered!==this.hover){this.hover=hovered;this.dirty=true;}
    if(this.panel.visible&&(this.dirty||now-this.lastDraw>250)){this.draw();this.lastDraw=now;this.dirty=false;}
  }
  draw(){
    const ctx=this.context;ctx.clearRect(0,0,WIDTH,HEIGHT);
    ctx.fillStyle='rgba(17,21,18,0.97)';ctx.beginPath();ctx.roundRect(0,0,WIDTH,HEIGHT,28);ctx.fill();
    const stamp=value=>{const seconds=Math.max(0,Math.floor(Number.isFinite(value)?value:0));return `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;};
    ctx.font='28px system-ui,sans-serif';ctx.fillStyle='#edf0e9';ctx.textAlign='left';
    ctx.fillText(this.moving?'Aim, then click to place your video':'Playback controls',28,47);
    ctx.textAlign='right';ctx.fillStyle='#a2aaa1';ctx.fillText(`${stamp(this.video.currentTime)} / ${stamp(this.video.duration)}`,WIDTH-28,47);
    ctx.fillStyle='#3a4438';ctx.fillRect(28,66,WIDTH-56,5);
    ctx.fillStyle='#c4f56b';ctx.fillRect(28,66,(WIDTH-56)*THREE.MathUtils.clamp(this.video.currentTime/(this.video.duration||1),0,1),5);
    ctx.textAlign='center';ctx.textBaseline='middle';ctx.font='29px system-ui,sans-serif';
    for(const button of BUTTONS){
      const selected=button.id===this.hover||(button.id==='move'&&this.moving);
      ctx.fillStyle=selected?'#506e32':button.id==='exit'?'#593543':'#2b3822';ctx.beginPath();ctx.roundRect(button.x,button.y,button.width,button.height,15);ctx.fill();
      let label=button.label;
      if(button.id==='play')label=this.video.paused?'Play':'Pause';
      if(button.id==='mute')label=this.video.muted?'Unmute':'Mute';
      if(button.id==='move'&&this.moving)label='Cancel move';
      ctx.fillStyle=this.immersiveVideo&&['move','smaller','bigger'].includes(button.id)?'#8f9c86':'#edf2e8';ctx.fillText(label,button.x+button.width/2,button.y+button.height/2);
    }
    ctx.textBaseline='alphabetic';ctx.font='23px system-ui,sans-serif';ctx.fillStyle='#a2aaa1';ctx.fillText('Click video to show controls · B/Y brings video and controls in front',WIDTH/2,337);
    this.texture.needsUpdate=true;
  }
  dispose(){this.panel.removeFromParent();this.panel.geometry.dispose();this.panel.material.dispose();this.texture.dispose();}
}
