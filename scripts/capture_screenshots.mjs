// Capture only the synthetic fixture from generate_demo.py; never the live app.
import {spawn} from 'node:child_process';
import {readFileSync,mkdirSync} from 'node:fs';
import {resolve,dirname,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const demo=resolve(process.argv[2]||'/tmp/neonphantom-demo');
const state=JSON.parse(readFileSync(join(demo,'state.json')));
assert.deepEqual(state.cards.map(c=>c.id),['demo1','demo2','demo3'],'Use generated demo data only');
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const children=[];let browser;
try{
  children.push(spawn(process.env.NEONPHANTOM_TEST_BINARY||join(root,'deskdanced/target/release/deskdanced'),[],{env:{...process.env,DESKDANCE_ROOT:root,DESKDANCE_STATE:join(demo,'state.json'),DESKDANCE_MEDIA_DIR:join(demo,'media'),DESKDANCE_PORT:'18431',DESKDANCE_PYTHON:process.env.QUEST_PYTHON||'python3'},stdio:['ignore','pipe','inherit']}));
  const companion=spawn(process.env.QUEST_PYTHON||'python3',[join(root,'quest/companion.py'),'--host','127.0.0.1','--port','18444','--state',join(demo,'state.json'),'--media',join(demo,'media'),'--data',join(demo,'quest')],{stdio:['ignore','pipe','inherit']});children.push(companion);
  let output='';companion.stdout.on('data',data=>output+=data.toString());
  for(let n=0;n<100;n++){
    try{if((await fetch('http://127.0.0.1:18431/api/health')).ok&&/Pairing code: (\d{6})/.test(output))break;}catch{}
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/usr/bin/google-chrome',headless:true,args:['--no-sandbox','--ignore-certificate-errors','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1512,height:1200},deviceScaleFactor:1});
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  // Invented playback status for the demo's output monitor; no desktop process launched.
  await page.route('**/api/stage',route=>route.fulfill({json:{playing:true,card_id:'demo1',height_px:600,corner:'br'}}));
  await page.goto('http://127.0.0.1:18431/');await page.getByRole('heading',{name:'Motion study / 01',exact:true}).first().waitFor();
  await page.waitForFunction(()=>document.querySelector('.connection i.online'));
  const destination=join(root,'docs/screenshots');mkdirSync(destination,{recursive:true});
  await page.screenshot({path:join(destination,'studio.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Studio mobile overflow');
  await page.screenshot({path:join(destination,'studio-mobile.png'),fullPage:false});
  await page.setViewportSize({width:1512,height:1100});
  const quest=await context.newPage();quest.on('pageerror',e=>errors.push(e.message));
  await quest.addInitScript({path:join(root,'quest/app/node_modules/iwer/build/iwer.js')});
  await quest.addInitScript(()=>{window.demoXR=new IWER.XRDevice(IWER.metaQuest3,{stereoEnabled:true});window.demoXR.installRuntime({forceInstall:true});});
  await quest.goto('https://127.0.0.1:18444/');
  await quest.locator('#pair-code').fill(output.match(/Pairing code: (\d{6})/)[1]);await quest.getByRole('button',{name:'Pair headset'}).click();
  await quest.getByRole('button',{name:'Motion study / 01',exact:false}).waitFor({timeout:60000});
  await quest.getByRole('button',{name:'Motion study / 01',exact:false}).click();
  await quest.waitForFunction(()=>document.querySelector('#source-video').videoWidth>0);await quest.locator('#play').click();
  await quest.waitForFunction(()=>document.querySelector('#source-video').currentTime>.1);await quest.locator('#play').click();
  await quest.screenshot({path:join(destination,'quest-viewer.png'),fullPage:true});
  await quest.setViewportSize({width:390,height:844});assert.ok(await quest.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Quest mobile overflow');
  assert.deepEqual(errors,[],'Browser errors');console.log('Captured synthetic studio, mobile, and paired Quest screenshots; no browser errors or mobile overflow.');
}finally{if(browser)await browser.close();for(const child of children)child.kill('SIGINT');}
