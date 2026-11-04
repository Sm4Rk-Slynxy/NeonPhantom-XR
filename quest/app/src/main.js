import * as THREE from 'three';
import './style.css';
import {XRPlaybackControls} from './xr-playback-controls.js';

const $ = id => document.getElementById(id);
const video = $('source-video');
const state = {paired:false, cards:[], selected:null, session:null, texture:null, objectURL:null, needsPlacement:false, size:1.4, distance:2, lift:-0.4, rotation:0, lastTime:0, buttons:new Map(), selectedCard:null, selectedJob:null, activeStereoJob:null, submittingStereo:false, controlAnchorVersion:-1};
const supported={'immersive-ar':false,'immersive-vr':false};
let timer, renderer, scene, camera, mesh, material, materials, observer, playbackControls, controlAnchor;
const notices = text => { $('message').textContent=text; $('message').hidden=!text; };

const fragmentShader = `
  precision highp float;
  uniform sampler2D movie;
  uniform float packedAlpha;
  uniform float videoWidth;
  uniform float eyeOffset;
  uniform float eyeScale;
  uniform float opacity;
  uniform float cutoff;
  varying vec2 vUv;
  void main() {
    float edge = 0.5 / max(videoWidth, 2.0);
    float packedScale = packedAlpha > 0.5 ? 0.5 : 1.0;
    float start = eyeOffset * packedScale;
    float end = (eyeOffset + eyeScale) * packedScale;
    vec2 colorUv = vec2(clamp((eyeOffset + vUv.x * eyeScale) * packedScale, start+edge, end-edge), vUv.y);
    vec4 color = texture2D(movie, colorUv);
    float alpha = packedAlpha > 0.5 ? texture2D(movie, colorUv + vec2(0.5, 0.0)).r : 1.0;
    if (alpha < cutoff) discard;
    gl_FragColor = vec4(color.rgb, alpha * opacity);
  }
`;

function initRenderer() {
  renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,premultipliedAlpha:true,preserveDrawingBuffer:false});
  renderer.setClearColor(0x000000,0);renderer.setPixelRatio(Math.min(devicePixelRatio,2));
  renderer.xr.enabled=true;renderer.xr.setReferenceSpaceType('local-floor');
  $('canvas-host').append(renderer.domElement);
  scene=new THREE.Scene();camera=new THREE.PerspectiveCamera(45,1,0.05,50);camera.position.set(0,1.6,3);camera.layers.enable(1);scene.add(camera);
  material=new THREE.ShaderMaterial({uniforms:{movie:{value:null},packedAlpha:{value:1},videoWidth:{value:2},eyeOffset:{value:0},eyeScale:{value:1},opacity:{value:1},cutoff:{value:0.02}},vertexShader:'varying vec2 vUv; void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',fragmentShader,transparent:true,depthWrite:false,side:THREE.DoubleSide,toneMapped:false});
  materials=[material,material.clone()];mesh=new THREE.Group();
  const geometry=new THREE.PlaneGeometry(1,1);
  for(let eye=0;eye<2;eye++){const plane=new THREE.Mesh(geometry,materials[eye]);plane.layers.set(eye+1);mesh.add(plane);}
  mesh.visible=false;scene.add(mesh);controlAnchor=new THREE.Object3D();controlAnchor.visible=true;controlAnchor.scale.set(1.5,1,1);
  playbackControls=new XRPlaybackControls(scene,video,handleXRAction,visible=>document.body.classList.toggle('xr-controls-visible',visible));
  observer=new ResizeObserver(()=>{
    if(state.session)return;
    const {width,height}=$('canvas-host').getBoundingClientRect();if(width<=0||height<=0)return;renderer.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix();placeInFront();
  });observer.observe($('canvas-host'));
  for(let i=0;i<2;i++){
    const controller=renderer.xr.getController(i);scene.add(controller);
    const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(),new THREE.Vector3(0,0,-1)]),new THREE.LineBasicMaterial({color:0xc2aaff,transparent:true,opacity:0.6}));line.scale.z=state.distance;controller.add(line);
    playbackControls.attach(controller,line);
    controller.addEventListener('select',()=>{
      if(state.session&&mesh.visible)playbackControls.select(controller,mesh);
    });
  }
  renderer.setAnimationLoop(time=>{
    const delta=Math.min(0.1,(time-state.lastTime)/1000||0);state.lastTime=time;
    if(state.session){
      if(state.needsPlacement){placeInFront();state.needsPlacement=false;playbackControls.show();}
      for(const source of state.session.inputSources){
        const gamepad=source.gamepad;if(!gamepad)continue;
        const axis=gamepad.axes.length>=4?gamepad.axes[3]:gamepad.axes[1]||0;
        if(Math.abs(axis)>0.25&&$('projection').value==='flat'){
          if(source.handedness==='left'){state.size=THREE.MathUtils.clamp(state.size-axis*delta,0.2,3);$('size').value=state.size;scaleVideo();}
          else {state.distance=THREE.MathUtils.clamp(state.distance+axis*delta*1.5,0.5,6);$('distance').value=state.distance;placeInFront();}
          labels();playbackControls.show();
        }
        const previous=state.buttons.get(source)||[];
        if(gamepad.buttons[4]?.pressed&&!previous[4]){togglePlay();playbackControls.show();}
        if(gamepad.buttons[5]?.pressed&&!previous[5]){placeInFront();playbackControls.show();}
        state.buttons.set(source,gamepad.buttons.map(button=>button.pressed));
      }
    }
    if(state.session){
      const immersive=$('projection').value==='vr180-sbs';
      if(immersive)mesh.position.copy(activeCamera().getWorldPosition(new THREE.Vector3()));
      playbackControls.immersiveVideo=immersive;
      playbackControls.update(time,immersive?vr180ControlAnchor():mesh);
    }
    renderer.render(scene,camera);
  });
  renderer.domElement.addEventListener('webglcontextlost',event=>{event.preventDefault();notices('Graphics context lost. Leave passthrough and reload this viewer.');});
}

function handleXRAction(action,ray){
  if(action==='exit'){state.session?.end().catch(error=>notices(error.message));return;}
  if(action==='play')togglePlay();
  else if(action==='mute'){video.muted=!video.muted;$('mute').checked=video.muted;}
  else if(action==='back'||action==='forward'){
    if(Number.isFinite(video.duration))video.currentTime=THREE.MathUtils.clamp(video.currentTime+(action==='back'?-10:10),0,Math.max(0,video.duration-.05));
  }else if(action==='recenter')placeInFront();
  else if(action==='smaller'||action==='bigger'){
    state.size=THREE.MathUtils.clamp(state.size+(action==='smaller'?-.1:.1),.2,3);$('size').value=state.size;scaleVideo();labels();
  }else if(action==='place'){
    mesh.position.copy(ray.origin).addScaledVector(ray.direction,state.distance);faceViewer();
  }
  playbackControls.show();
}

function vr180ControlAnchor(){
  if(state.controlAnchorVersion!==playbackControls.anchorVersion){
    state.controlAnchorVersion=playbackControls.anchorVersion;
    const view=activeCamera(),eye=view.getWorldPosition(new THREE.Vector3()),direction=view.getWorldDirection(new THREE.Vector3());
    direction.y=0;if(direction.lengthSq()<.01)direction.set(0,0,-1);direction.normalize();
    controlAnchor.position.copy(eye).addScaledVector(direction,2);controlAnchor.position.y=eye.y-.2;
    controlAnchor.lookAt(eye.x,controlAnchor.position.y,eye.z);controlAnchor.updateMatrixWorld(true);
  }
  return controlAnchor;
}
function updateProjection(){
  const immersive=$('projection').value==='vr180-sbs';
  const geometry=immersive?new THREE.SphereGeometry(20,96,64,0,Math.PI):new THREE.PlaneGeometry(1,1);
  if(immersive)geometry.scale(1,1,-1);
  const old=mesh.children[0].geometry;for(const child of mesh.children)child.geometry=geometry;old.dispose();
  if(immersive)$('layout').value='sbs-full';
  state.controlAnchorVersion=-1;updateLayout();placeInFront();
  if(state.session)playbackControls.show();
}
function activeCamera(){return state.session?renderer.xr.getCamera():camera;}
function faceViewer(){if($('projection').value==='vr180-sbs'){placeInFront();return;}const eye=activeCamera().getWorldPosition(new THREE.Vector3());mesh.lookAt(eye.x,mesh.position.y,eye.z);mesh.rotateY(THREE.MathUtils.degToRad(state.rotation));}
function placeInFront(){
  if(!renderer||!mesh.visible)return;
  if($('projection').value==='vr180-sbs'){
    if(!state.session){camera.position.set(0,0,0);camera.quaternion.identity();camera.updateMatrixWorld();}
    const view=activeCamera(),direction=view.getWorldDirection(new THREE.Vector3());
    mesh.position.copy(view.getWorldPosition(new THREE.Vector3()));
    mesh.rotation.set(0,Math.atan2(-direction.x,-direction.z)+THREE.MathUtils.degToRad(state.rotation),0);
    return;
  }
  if(!state.session){
    camera.position.set(0,0,0);camera.quaternion.identity();camera.updateMatrixWorld();
    const halfFov=Math.tan(THREE.MathUtils.degToRad(camera.fov/2));
    const fit=Math.max(mesh.scale.y/(2*halfFov),mesh.scale.x/(2*halfFov*camera.aspect))*1.12;
    mesh.position.set(0,0,-Math.max(state.distance,fit));faceViewer();return;
  }
  const view=activeCamera();const eye=view.getWorldPosition(new THREE.Vector3());
  const direction=view.getWorldDirection(new THREE.Vector3());direction.y=0;
  if(direction.lengthSq()<0.01)direction.set(0,0,-1);direction.normalize();
  mesh.position.copy(eye).addScaledVector(direction,state.distance);mesh.position.y=eye.y+state.lift;faceViewer();
}
function scaleVideo(){
  if(!mesh||!video.videoHeight)return;
  if($('projection').value==='vr180-sbs'){mesh.scale.setScalar(1);if(!state.session)placeInFront();return;}
  let ratio=video.videoWidth/($('packed').checked?2:1)/video.videoHeight;
  if($('layout').value==='sbs-full')ratio/=2;
  mesh.scale.set(state.size*ratio,state.size,1);if(!state.session)placeInFront();
}
function labels(){
  for(const name of ['size','distance','lift'])$(name+'-value').textContent=state[name].toFixed(1)+' m';
  $('rotation-value').textContent=Math.round(state.rotation)+'°';
}
function textureReady(){
  state.texture?.dispose();state.texture=new THREE.VideoTexture(video);state.texture.colorSpace=THREE.NoColorSpace;
  for(const item of materials){item.uniforms.movie.value=state.texture;item.uniforms.videoWidth.value=video.videoWidth;}
  mesh.visible=true;updateLayout();
  if(state.session)state.needsPlacement=true;else placeInFront();
  $('duration').textContent=Number.isFinite(video.duration)?`${Math.round(video.duration)} seconds`:'';
  $('play').disabled=false;updateEntryButtons();
}
function loadVideo(url,name,packed,card=null){
  notices('');video.pause();$('play').textContent='▶ Play';$('video-title').textContent=name;
  $('packed').checked=packed;$('layout').value=card?.stereo_layout||'mono';$('projection').value=card?.projection||'flat';$('swap-eyes').checked=false;
  state.selectedCard=card;state.selected=url;mesh.visible=false;$('play').disabled=true;updateEntryButtons();
  video.src=url;video.load();updateProjection();
  document.querySelectorAll('.card').forEach(button=>button.classList.toggle('selected',button.dataset.url===url));
}
async function togglePlay(){
  try{if(video.paused){await video.play();$('play').textContent='Ⅱ Pause';}else{video.pause();$('play').textContent='▶ Play';}}
  catch(error){notices('Cannot play this video: '+error.message);}
}
function updateEntryButtons(){
  $('enter-ar').disabled=!supported['immersive-ar']||!mesh?.visible;
  $('enter-vr').disabled=!supported['immersive-vr']||!mesh?.visible;
}
function updateLayout(){
  if(!materials)return;
  const stereo=$('layout').value!=='mono';
  for(let eye=0;eye<2;eye++){
    const sourceEye=$('swap-eyes').checked?1-eye:eye;
    materials[eye].uniforms.eyeScale.value=stereo?.5:1;
    materials[eye].uniforms.eyeOffset.value=stereo?sourceEye*.5:0;
    materials[eye].uniforms.packedAlpha.value=$('packed').checked?1:0;
  }
  camera.layers.disable(1);camera.layers.disable(2);camera.layers.enable($('preview-eye').value==='right'?2:1);
  scaleVideo();
  updateConvertAvailability();
  $('layout-hint').textContent=stereo?'Each eye receives its own view. Use Swap eyes if depth appears reversed.':'Ordinary 2D video. Convert to 3D SBS below to generate depth.';
}
async function enterXR(mode){
  if(!supported[mode]||!mesh.visible||state.session)return;
  notices('');const playing=video.play();playing.catch(()=>{});
  try{
    const session=await navigator.xr.requestSession(mode,{requiredFeatures:['local-floor'],optionalFeatures:['hand-tracking']});
    if(mode==='immersive-ar'&&session.environmentBlendMode!=='alpha-blend'){
      await session.end();throw Error('This browser does not expose passthrough alpha blending.');
    }
    state.session=session;
    renderer.setClearColor(mode==='immersive-vr'?0x080a10:0x000000,mode==='immersive-vr'?1:0);
    session.addEventListener('end',()=>{
      state.session=null;state.buttons.clear();playbackControls.hide();renderer.setClearColor(0x000000,0);
      document.body.classList.remove('xr-active');$('exit-ar').hidden=true;$('enter-ar').hidden=false;$('enter-vr').hidden=false;
      observer.unobserve($('canvas-host'));observer.observe($('canvas-host'));updateLayout();placeInFront();detectXR();
    });
    await renderer.xr.setSession(session);await playing;state.needsPlacement=true;
    document.body.classList.add('xr-active');$('exit-ar').hidden=false;$('exit-ar').textContent=mode==='immersive-vr'?'Leave VR':'Leave passthrough';
    $('enter-ar').hidden=true;$('enter-vr').hidden=true;$('play').textContent='Ⅱ Pause';playbackControls.show();
    $('xr-status').textContent=(mode==='immersive-vr'?'VR cinema':'Passthrough')+' active. Click the video for playback controls and Exit VR. Controls hide after five seconds. B/Y recenters and shows controls.';
  }catch(error){await playing.catch(()=>{});if(state.session)await state.session.end().catch(()=>{});notices('Could not enter headset mode: '+error.message);}
}
async function detectXR(){
  if(!window.isSecureContext){$('xr-status').textContent='Headset playback needs HTTPS trusted by this browser. Use the HTTPS address printed on the PC.';return;}
  if(!navigator.xr){$('xr-status').textContent='Desktop preview is ready. Open this HTTPS address in Quest Browser for VR or passthrough.';return;}
  await Promise.all(Object.keys(supported).map(async mode=>{try{supported[mode]=await navigator.xr.isSessionSupported(mode);}catch{supported[mode]=false;}}));
  const modes=[supported['immersive-vr']?'VR cinema':null,supported['immersive-ar']?'passthrough':null].filter(Boolean);
  $('xr-status').textContent=modes.length?'Available: '+modes.join(' and ')+'. Select a video, then enter your headset mode.':'This browser does not offer immersive VR or AR. Open this viewer in Quest Browser.';
  updateEntryButtons();
}
function updateConvertAvailability(){
  let reason='';
  if(state.submittingStereo)reason='Starting the conversion on your PC…';
  else if(state.activeStereoJob)reason='A conversion is running. Wait for it to finish, or choose Cancel conversion.';
  else if(!state.selectedCard)reason=state.selected?.startsWith('blob:')
    ?'This file is open for playback only. Add it in the NeonPhantom XR studio on your PC, then select it from Your videos here to convert it.'
    :'Select an original 2D clip from Your videos to enable conversion.';
  else if($('projection').value==='vr180-sbs')reason='VR180 already has captured stereo depth. Use AI cutout during import, then play it directly in passthrough.';
  else if(state.selectedCard.source_id)reason='This video is already a 3D SBS conversion. Select its original 2D clip from Your videos to convert again.';
  else if($('layout').value!=='mono')reason='The source is marked as SBS. For an ordinary 2D video, set Source format to 2D / mono to enable conversion.';
  $('convert').disabled=!!reason;
  $('convert').title=reason||'Generate depth and separate left/right views from this 2D video.';
  $('convert-availability').textContent=reason||'Ready to convert the selected 2D video.';
}
function renderStereoJobs(jobs){
  const latest=jobs.find(job=>job.id===state.selectedJob)||jobs.at(-1);
  const active=jobs.find(job=>job.state==='running');
  state.activeStereoJob=active||null;updateConvertAvailability();
  $('cancel-convert').hidden=!active;$('cancel-convert').dataset.job=active?.id||'';
  if(!latest){$('convert-status').textContent='Depth runs on your PC. Auto prefers an available GPU and falls back to CPU. Models download once.';return;}
  $('convert-status').textContent=latest.name+' · '+latest.phase+(latest.card?.processing_device?' · '+latest.card.processing_device.toUpperCase():'')+(latest.card?.fallback_reason?' · '+latest.card.fallback_reason:'');
  $('convert-progress').hidden=latest.state!=='running';$('convert-progress').value=latest.progress;
  $('play-converted').hidden=latest.state!=='done';$('download-sbs').hidden=latest.state!=='done';
  if(latest.state==='done'){
    $('play-converted').onclick=()=>loadVideo(latest.card.url,latest.card.name,true,latest.card);
    $('download-sbs').href=latest.download_url;
  }
}
async function stereoRequest(path,body){
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json();if(!response.ok)throw Error(result.error||'Stereo conversion failed');return result;
}
async function convertStereo(){
  if(!state.selectedCard)return;
  if($('convert').disabled)return;
  state.submittingStereo=true;updateConvertAvailability();notices('');
  try{const job=await stereoRequest('/api/stereo',{card_id:state.selectedCard.id,strength:Number($('depth-strength').value)/100,device:$('processing-device').value});state.selectedJob=job.id;await refreshLibrary();}
  catch(error){notices(error.message);}
  finally{state.submittingStereo=false;updateConvertAvailability();}
}

async function refreshLibrary(){
  try{
    const response=await fetch('/api/library');
    if(response.status===401){state.paired=false;$('pairing').hidden=false;$('viewer').hidden=true;return;}
    if(!response.ok)throw Error('Cannot read the PC library');
    const data=await response.json();state.paired=true;$('pairing').hidden=true;$('viewer').hidden=false;
    $('library-status').textContent=data.phase;
    const fingerprint=JSON.stringify(data.cards.map(card=>[card.id,card.url,card.name,card.stereo_layout]));
    if(fingerprint!==state.cardsFingerprint){
      state.cardsFingerprint=fingerprint;state.cards=data.cards;$('cards').replaceChildren();
      for(const card of data.cards){
        const button=document.createElement('button');button.className='card';button.dataset.url=card.url;
        const title=document.createElement('strong');title.textContent=card.name;
        const detail=document.createElement('span');detail.textContent=`${Math.round(card.duration_s)}s · ${card.projection==='vr180-sbs'?'VR180 SBS':card.stereo_layout?'3D SBS':card.has_alpha?'Cutout':'Full video'}`;
        button.append(title,detail);button.onclick=()=>{if(state.objectURL){URL.revokeObjectURL(state.objectURL);state.objectURL=null;}loadVideo(card.url,card.name,card.packed_alpha!==false,card);};
        if(state.selected===card.url)button.classList.add('selected');$('cards').append(button);
      }
    }
    renderStereoJobs(data.stereo_jobs||[]);
    if(data.errors?.length)notices('Some clips could not be prepared: '+data.errors.join(' · '));
  }catch(error){$('library-status').textContent=error.message;}
}
async function pair(payload){
  const response=await fetch('/api/pair',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const result=await response.json();if(!response.ok)throw Error(result.error||'Pairing failed');
  notices('');await refreshLibrary();
}

$('pair-form').addEventListener('submit',async event=>{event.preventDefault();try{await pair({code:$('pair-code').value});}catch(error){notices(error.message);}});
$('play').onclick=togglePlay;$('enter-ar').onclick=()=>enterXR('immersive-ar');$('enter-vr').onclick=()=>enterXR('immersive-vr');$('exit-ar').onclick=()=>state.session?.end();$('recenter').onclick=placeInFront;
$('loop').onchange=()=>video.loop=$('loop').checked;
$('mute').onchange=()=>{video.muted=$('mute').checked;};
$('projection').onchange=updateProjection;
for(const name of ['packed','layout','swap-eyes','preview-eye'])$(name).onchange=updateLayout;
$('convert').onclick=convertStereo;
$('depth-strength').oninput=()=>{$('depth-strength-value').textContent=Number($('depth-strength').value).toFixed(1)+'%';};
$('cancel-convert').onclick=async()=>{try{await stereoRequest('/api/stereo/'+$('cancel-convert').dataset.job+'/cancel',{});await refreshLibrary();}catch(error){notices(error.message);}};
for(const name of ['size','distance','lift','rotation'])$(name).oninput=()=>{
  state[name]=Number($(name).value);labels();if(name==='size')scaleVideo();else if(name==='rotation')faceViewer();else placeInFront();
};
$('opacity').oninput=()=>{for(const item of materials)item.uniforms.opacity.value=Number($('opacity').value);$('opacity-value').textContent=Math.round(Number($('opacity').value)*100)+'%';};
$('cutoff').oninput=()=>{for(const item of materials)item.uniforms.cutoff.value=Number($('cutoff').value);$('cutoff-value').textContent=Number($('cutoff').value).toFixed(2);};
$('local-file').onchange=()=>{
  const file=$('local-file').files[0];if(!file)return;
  if(state.objectURL)URL.revokeObjectURL(state.objectURL);state.objectURL=URL.createObjectURL(file);loadVideo(state.objectURL,file.name,false);
};
video.addEventListener('loadedmetadata',textureReady);
video.addEventListener('error',()=>notices('Video decoding failed. Use a prepared NeonPhantom XR Quest MP4 or another video supported by this headset.'));
window.addEventListener('pagehide',()=>{clearInterval(timer);video.pause();state.session?.end();state.texture?.dispose();for(const item of materials||[])item.dispose();playbackControls?.dispose();renderer?.dispose();});

async function start(){
try{initRenderer();await detectXR();}catch(error){notices('Cannot initialize the video renderer: '+error.message);}
const token=new URLSearchParams(location.hash.slice(1)).get('pair');
if(token){history.replaceState(null,'',location.pathname);try{await pair({token});}catch(error){notices(error.message);}}
else await refreshLibrary();
timer=setInterval(refreshLibrary,4000);

}
start();
