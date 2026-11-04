// Requires Playwright, Chrome and `npm ci` in quest/app. Uses only synthetic video.
import { readFileSync, writeFileSync, mkdtempSync, mkdirSync, rmSync, copyFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn, spawnSync } from 'node:child_process';
import assert from 'node:assert/strict';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const folder=mkdtempSync(join(tmpdir(),'quest-browser-'));
mkdirSync(join(folder,'media'));
const frame=Buffer.alloc(96*64*4);
for(let i=0;i<96*64;i++){frame[i*4]=240;frame[i*4+1]=30;frame[i*4+2]=20;frame[i*4+3]=(i%96)<32?0:(i%96)<64?128:255;}
const encoded=spawnSync('ffmpeg',['-v','error','-y','-f','rawvideo','-pix_fmt','rgba','-s','96x64','-r','12','-i','-','-c:v','libvpx-vp9','-lossless','1','-pix_fmt','yuva420p',join(folder,'media/alpha.webm')],{input:Buffer.concat(Array(24).fill(frame))});
assert.equal(encoded.status,0,encoded.stderr.toString());
if(process.env.QUEST_TEST_MODEL){mkdirSync(join(folder,'data/models'),{recursive:true});copyFileSync(process.env.QUEST_TEST_MODEL,join(folder,'data/models/depth-anything-v2-small-q8.onnx'));}
const stereoFrame=Buffer.alloc(320*90*4);for(let i=0;i<320*90;i++){stereoFrame[i*4]=(i%320)<160?240:20;stereoFrame[i*4+1]=20;stereoFrame[i*4+2]=(i%320)<160?20:240;stereoFrame[i*4+3]=255;}
const stereoEncoded=spawnSync('ffmpeg',['-v','error','-y','-f','rawvideo','-pix_fmt','rgba','-s','320x90','-r','12','-i','-','-c:v','libx264',join(folder,'media/stereo.mp4')],{input:Buffer.concat(Array(24).fill(stereoFrame))});assert.equal(stereoEncoded.status,0,stereoEncoded.stderr.toString());
writeFileSync(join(folder,'state.json'),JSON.stringify({cards:[{id:'demo',file:'alpha.webm',name:'Synthetic alpha test'},{id:'eyes',file:'stereo.mp4',name:'Different eye colors'}]}));
const server=spawn(process.env.QUEST_PYTHON||'python3',[join(root,'quest/companion.py'),'--host','127.0.0.1','--port','18443','--state',join(folder,'state.json'),'--media',join(folder,'media'),'--data',join(folder,'data'),'--site',join(root,'quest/site')]);
let logs='';server.stdout.on('data',data=>logs+=data);server.stderr.on('data',data=>logs+=data);
let browser;
try{
  for(let i=0;i<100&&!logs.includes('Pairing code:');i++)await new Promise(r=>setTimeout(r,100));
  const code=logs.match(/Pairing code: (\d+)/)?.[1];assert.ok(code,logs);
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/usr/bin/google-chrome',headless:true,args:['--no-sandbox','--ignore-certificate-errors','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1440,height:1000}});
  const errors=[];
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript({path:join(root,'quest/app/node_modules/iwer/build/iwer.js')});
  await page.addInitScript(()=>{
    const config={...IWER.metaQuest3,supportedFeatures:IWER.metaQuest3.supportedFeatures.filter(feature=>feature!=='dom-overlay')};
    window.testXR=new IWER.XRDevice(config,{stereoEnabled:true});window.testXR.installRuntime({forceInstall:true});
    const request=navigator.xr.requestSession.bind(navigator.xr);
    navigator.xr.requestSession=async(...args)=>{
      window.testRequest=args;const session=await request(...args);window.testSession=session;
      session.addEventListener('select',()=>window.testSelects=(window.testSelects||0)+1);return session;
    };
  });
  async function triggerAt(x,y,z){
    await page.evaluate(({x,y,z})=>{
      const controller=window.testXR.controllers.right;controller.connected=true;controller.position.set(0,1.6,0);
      const dx=x,dy=y-1.6,dz=z,length=Math.hypot(dx,dy,dz);
      const qx=dy/length,qy=-dx/length,qw=1-dz/length,norm=Math.hypot(qx,qy,qw);
      controller.quaternion.set(qx/norm,qy/norm,0,qw/norm);
      controller.updateButtonValue('trigger',1);
    },{x,y,z});
    await page.waitForTimeout(120);await page.evaluate(()=>window.testXR.controllers.right.updateButtonValue('trigger',0));await page.waitForTimeout(120);
  }
  await page.goto('https://127.0.0.1:18443/');
  await page.locator('#pair-code').fill(code);await page.getByRole('button',{name:'Pair headset'}).click();
  await page.getByRole('button',{name:'Synthetic alpha test'}).click({timeout:20000});
  await page.waitForFunction(()=>document.querySelector('#source-video').videoWidth===192);
  await page.locator('#play').click();await page.waitForFunction(()=>document.querySelector('#source-video').currentTime>.2);
  await page.screenshot({path:'/tmp/deskdance-quest-preview.png',fullPage:true});
  assert.equal(await page.locator('#packed').isChecked(),true);
  const canvasAlpha=await page.locator('canvas').evaluate(canvas=>new Promise(resolve=>requestAnimationFrame(()=>{
    const gl=canvas.getContext('webgl2');const data=new Uint8Array(canvas.width*canvas.height*4);
    gl.readPixels(0,0,canvas.width,canvas.height,gl.RGBA,gl.UNSIGNED_BYTE,data);
    let transparent=0,soft=0,opaque=0;
    for(let i=3;i<data.length;i+=4){if(data[i]===0)transparent++;if(data[i]>110&&data[i]<145)soft++;if(data[i]>250)opaque++;}
    resolve({transparent,soft,opaque});
  })));
  assert.ok(canvasAlpha.transparent>1000,'Background must remain transparent');
  assert.ok(canvasAlpha.soft>1000,'Soft alpha must survive video decoding and shader rendering');
  assert.ok(canvasAlpha.opaque>1000,'Opaque foreground must be rendered');
  await page.locator('#enter-ar').click();await page.waitForFunction(()=>document.body.classList.contains('xr-active'));
  assert.equal(await page.evaluate(()=>window.testRequest[0]),'immersive-ar');
  assert.equal(await page.evaluate(()=>window.testRequest[1].optionalFeatures.includes('dom-overlay')),false,'DOM overlay must not intercept scene controller clicks');
  assert.equal(await page.evaluate(()=>window.testSession.environmentBlendMode),'alpha-blend');
  await page.waitForTimeout(250);
  assert.equal(await page.locator('#message').isVisible(),false,await page.locator('#message').textContent());
  assert.equal(await page.evaluate(()=>document.body.classList.contains('xr-controls-visible')),true);
  assert.equal(await page.locator('#viewer').isVisible(),false,'Desktop panels should not obscure immersive playback');
  await page.waitForFunction(()=>!document.body.classList.contains('xr-controls-visible'),{},{timeout:7000});
  await triggerAt(-.032,1.3,-2);
  await page.waitForFunction(()=>document.body.classList.contains('xr-controls-visible'));
  await page.screenshot({path:'/tmp/deskdance-vr-playback-controls.png',fullPage:true});
  // Click the scene toolbar's Pause button using the XR controller ray.
  await triggerAt(-.616,.897,-1.975);
  await page.waitForFunction(()=>document.querySelector('#source-video').paused);
  await triggerAt(-.616,.897,-1.975);
  await page.waitForFunction(()=>!document.querySelector('#source-video').paused);
  // Hide, then B/Y recovers the controls even if the video is out of reach.
  await triggerAt(.552,.767,-1.975);
  await page.waitForFunction(()=>!document.body.classList.contains('xr-controls-visible'));
  await page.evaluate(()=>window.testXR.controllers.right.updateButtonValue('b-button',1));await page.waitForTimeout(120);
  await page.evaluate(()=>window.testXR.controllers.right.updateButtonValue('b-button',0));
  await page.waitForFunction(()=>document.body.classList.contains('xr-controls-visible'));
  // Exit through the in-scene button; no DOM-overlay support is installed.
  await triggerAt(.552,.897,-1.975);
  await page.waitForFunction(()=>!document.body.classList.contains('xr-active'));
  // Re-entry catches WebGL/session teardown failures.
  await page.locator('#enter-ar').click();await page.waitForFunction(()=>document.body.classList.contains('xr-active'));
  await page.locator('#exit-ar').evaluate(button=>button.click());await page.waitForFunction(()=>!document.body.classList.contains('xr-active'));
  await page.getByRole('button',{name:'Different eye colors'}).click();
  await page.waitForFunction(()=>document.querySelector('#source-video').videoWidth===640);
  await page.locator('#layout').selectOption('sbs-full');await page.locator('#play').click();
  await page.waitForFunction(()=>document.querySelector('#source-video').currentTime>.2);
  const centerColor=()=>page.locator('#canvas-host canvas').evaluate(canvas=>new Promise(resolve=>requestAnimationFrame(()=>{
    const gl=canvas.getContext('webgl2'),pixel=new Uint8Array(4);gl.readPixels(Math.floor(canvas.width/2),Math.floor(canvas.height/2),1,1,gl.RGBA,gl.UNSIGNED_BYTE,pixel);resolve([...pixel]);
  })));
  let color=await centerColor();assert.ok(color[0]>180&&color[2]<70,'Left eye should see the red half');
  await page.locator('#preview-eye').selectOption('right');color=await centerColor();assert.ok(color[2]>180&&color[0]<70,'Right eye should see the blue half');
  await page.locator('#swap-eyes').check();color=await centerColor();assert.ok(color[0]>180&&color[2]<70,'Swapping eyes must change the source half');
  await page.locator('#swap-eyes').uncheck();await page.locator('#preview-eye').selectOption('left');
  await page.locator('#enter-vr').click();await page.waitForFunction(()=>document.body.classList.contains('xr-active'));
  assert.equal(await page.evaluate(()=>window.testRequest[0]),'immersive-vr');
  assert.equal(await page.evaluate(()=>window.testSession.environmentBlendMode),'opaque');
  await page.waitForTimeout(300);
  const eyePixels=await page.evaluate(async()=>{
    const reference=await window.testSession.requestReferenceSpace('local-floor');
    return new Promise(resolve=>window.testSession.requestAnimationFrame((time,frame)=>{
      const gl=document.querySelector('canvas').getContext('webgl2');
      const layer=window.testSession.renderState.baseLayer;
      if(!layer){resolve({error:'No base layer exposed by emulator'});return;}
      const pose=frame.getViewerPose(reference),pixels=[];
      for(const view of pose.views){const viewport=layer.getViewport(view),pixel=new Uint8Array(4);gl.readPixels(Math.floor(viewport.x+viewport.width/2),Math.floor(viewport.y+viewport.height/2),1,1,gl.RGBA,gl.UNSIGNED_BYTE,pixel);pixels.push([...pixel]);}
      resolve(pixels);
    }));
  });
  assert.ok(Array.isArray(eyePixels),JSON.stringify(eyePixels));
  assert.ok(eyePixels[0][0]>180&&eyePixels[0][2]<70,'XR left eye did not render left view: '+JSON.stringify(eyePixels));
  assert.ok(eyePixels[1][2]>180&&eyePixels[1][0]<70,'XR right eye did not render right view: '+JSON.stringify(eyePixels));
  await page.locator('#exit-ar').evaluate(button=>button.click());await page.waitForFunction(()=>!document.body.classList.contains('xr-active'));
  // Equirectangular VR180 uses the original SBS views on a front hemisphere.
  await page.locator('#projection').selectOption('vr180-sbs');
  assert.equal(await page.locator('#convert').isDisabled(),true,'Captured stereo must not be converted from mono again');
  await page.locator('#enter-ar').click();await page.waitForFunction(()=>document.body.classList.contains('xr-active'));
  async function xrCenterPixels(){
    return page.evaluate(async()=>{
      const session=window.testSession,space=await session.requestReferenceSpace('local-floor');
      return new Promise(resolve=>session.requestAnimationFrame((time,frame)=>{
        const gl=document.querySelector('canvas').getContext('webgl2'),layer=session.renderState.baseLayer;
        resolve(frame.getViewerPose(space).views.map(view=>{const v=layer.getViewport(view),pixel=new Uint8Array(4);gl.readPixels(Math.floor(v.x+v.width/2),Math.floor(v.y+v.height/2),1,1,gl.RGBA,gl.UNSIGNED_BYTE,pixel);return [...pixel];}));
      }));
    });
  }
  await page.waitForTimeout(300);let vr180Pixels=await xrCenterPixels();
  assert.ok(vr180Pixels[0][0]>180&&vr180Pixels[1][2]>180,'VR180 eye mapping failed: '+JSON.stringify(vr180Pixels));
  await page.evaluate(()=>window.testXR.quaternion.set(0,1,0,0));await page.waitForTimeout(250);vr180Pixels=await xrCenterPixels();
  assert.ok(vr180Pixels.every(pixel=>pixel[3]===0),'Behind the VR180 hemisphere should remain passthrough: '+JSON.stringify(vr180Pixels));
  await page.evaluate(()=>window.testXR.quaternion.set(0,0,0,1));await page.waitForTimeout(200);
  await page.locator('#exit-ar').evaluate(button=>button.click());await page.waitForFunction(()=>!document.body.classList.contains('xr-active'));
  await page.locator('#projection').selectOption('flat');
  if(process.env.QUEST_TEST_MODEL){
    await page.getByRole('button',{name:'Synthetic alpha test'}).click();
    await page.waitForFunction(()=>document.querySelector('#source-video').videoWidth===192);
    await page.locator('#convert').click();await page.locator('#play-converted').waitFor({state:'visible',timeout:60000});
    const download=await page.locator('#download-sbs').getAttribute('href');
    const response=await context.request.get('https://127.0.0.1:18443'+download);assert.equal(response.status(),200);
    assert.ok(response.headers()['content-disposition'].includes('attachment'));
    await page.locator('#play-converted').click();
    await page.waitForFunction(()=>document.querySelector('#source-video').videoWidth===384);
    assert.equal(await page.locator('#layout').inputValue(),'sbs-full');assert.equal(await page.locator('#packed').isChecked(),true);
  }
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'Mobile layout overflows');
  await page.screenshot({path:'/tmp/deskdance-quest-mobile.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: in-scene controls without DOM overlay, idle hide, click-to-show, controller Pause/Play/Hide/Exit, B/Y recovery; HTTPS pairing, alpha pixels, AR entry/re-entry, per-eye SBS colors, swap eyes, immersive VR eye framebuffers, conversion/download when model supplied, mobile layout.');
}finally{await browser?.close();server.kill('SIGINT');await new Promise(resolve=>server.once('exit',resolve));rmSync(folder,{recursive:true,force:true});}
