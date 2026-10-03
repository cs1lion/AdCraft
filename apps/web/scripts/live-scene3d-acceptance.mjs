import { chromium } from '@playwright/test';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
const base='http://127.0.0.1:8000';
const wf='adwf_v2_01c0f83902e0e0b8';
const output=new URL('../e2e_output/live-acceptance/',import.meta.url);
await mkdir(output,{recursive:true});
const evidence={workflowId:wf,started:new Date().toISOString(),checks:[],errors:[],renderJobs:[]};
async function api(path,method='GET',body){
 for(let attempt=0;attempt<3;attempt++){
  const headers={'Content-Type':'application/json'};
  if(method==='PATCH'||path.endsWith('/nodes')){
   const res=await fetch(`${base}/api/v2/workflows/${wf}`);headers['If-Match']=res.headers.get('etag');
  }
  const res=await fetch(base+path,{method,headers,body:body===undefined?undefined:JSON.stringify(body)});
  const data=await res.json();if(res.status===412||res.status===409)continue;
  if(!res.ok)throw new Error(`${method} ${path} ${res.status} ${JSON.stringify(data).slice(0,1200)}`);
  return data;
 }
 throw new Error('ETag conflict after fresh retries');
}
async function save(){await writeFile(new URL('scene3d-acceptance.json',output),JSON.stringify(evidence,null,2));}
let browser;
try{
 evidence.capability=await api('/api/v1/scene-3d/capability');
 if(evidence.capability.state!=='ready')throw new Error('Blender unavailable');
 const template=await api('/api/v1/scene-3d/template','POST',{template_id:'establishing_shot',params:{scene_name:'验收场景 A',duration:2,frame_rate:12}});
 if(!template.success)throw new Error(template.error);
 let scene=template.scene_script;
 if(process.argv.includes('--resume')) scene=(await api(`/api/v2/workflows/${wf}`)).nodes.find(n=>n.title==='实机验收 · 3D 建立镜头')?.structured_content?.scene_script ?? scene;
 const w=await api(`/api/v2/workflows/${wf}`);
 let node=w.nodes.find(n=>n.title==='实机验收 · 3D 建立镜头');
 if(!node){await api(`/api/v2/workflows/${wf}/nodes`,'POST',{node_type:'scene-3d',creative_role:'scene_3d_previs',role_contract_version:'ad-media-role-v2',title:'实机验收 · 3D 建立镜头',position:{x:1100,y:500},structured_content:{scene_script:scene}});node=(await api(`/api/v2/workflows/${wf}`)).nodes.find(n=>n.title==='实机验收 · 3D 建立镜头');}
 evidence.nodeId=node.node_id; await save();
 browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1600,height:1050}});
 page.on('pageerror',e=>evidence.errors.push(e.message));
 page.on('response',async res=>{if(/scene-3d\/(director-motion|render\/async)/.test(res.url())){evidence.checks.push({kind:'response',url:res.url().split('?')[0],status:res.status()});}});
 await page.goto('http://127.0.0.1:5189/workflow/proj_01c0f83902e0e0b8',{waitUntil:'domcontentloaded'});
 await page.locator(`.react-flow__node[data-id="${node.node_id}"]`).waitFor({timeout:30000});
 await page.locator(`.react-flow__node[data-id="${node.node_id}"]`).click({force:true});
 await page.getByText('3D 场景草稿',{exact:true}).waitFor({timeout:20000});
 evidence.initialText=(await page.locator('body').innerText()).slice(0,15000);
 evidence.webgl=await page.locator('canvas').evaluateAll(canvases=>canvases.map(c=>({width:c.width,height:c.height,context:!!(c.getContext('webgl2')||c.getContext('webgl'))})));
 evidence.checks.push({kind:'editor-open',pass:true});await save();
 // Clean external regeneration: add distinct prop via API and wait for editor object list.
 const clean=structuredClone(scene);clean.scene.name='验收场景 B 干净更新';clean.props=clean.props.filter(p=>p.id!=='regen_clean_marker');clean.props.push({id:'regen_clean_marker',type:'vase',position:[2,0,0],scale:1,rotation_y:0});
 await api(`/api/v2/workflows/${wf}/nodes/${node.node_id}`,'PATCH',{structured_content:{scene_script:clean}});
 await page.getByText(/Frame .*验收场景 B 干净更新/).first().waitFor({timeout:20000});
 evidence.checks.push({kind:'clean-external-regeneration',pass:true});
 // Local unsaved addition survives subsequent persisted update.
 await page.locator('button[data-tray-kind="cup"]').click();
 await page.getByText('有未保存修改',{exact:true}).waitFor();
 const dirtyBaseline=await page.locator('.scene-script-3d-editor').innerText();
 const next=structuredClone(clean);next.scene.name='验收场景 C 脏更新';next.props=next.props.filter(p=>p.id!=='regen_dirty_marker');next.props.push({id:'regen_dirty_marker',type:'box',position:[-2,0,0],scale:1,rotation_y:0});
 await api(`/api/v2/workflows/${wf}/nodes/${node.node_id}`,'PATCH',{structured_content:{scene_script:next}});
 await page.waitForTimeout(6500);
 const dirtyText=await page.locator('.scene-script-3d-editor').innerText();
 evidence.checks.push({kind:'dirty-external-regeneration-preserved',pass:dirtyText.includes('有未保存修改')&&!dirtyText.includes('验收场景 C 脏更新'),before:dirtyBaseline.includes('cup'),after:dirtyText.includes('cup')});
 await page.getByRole('button',{name:'撤销修改',exact:true}).click();
 await page.getByText(/Frame .*验收场景 C 脏更新/).first().waitFor({timeout:10000});
 // Consecutive real deterministic director requests.
 await page.getByLabel('导演指令对象',{exact:true}).selectOption('cam_wide');
 const options=await page.getByLabel('导演指令',{exact:true}).locator('option').evaluateAll(els=>els.map(e=>({value:e.value,label:e.textContent})).filter(e=>e.value));
 evidence.directorOptions=options;
 for(const option of options.slice(0,2)){
  await page.getByLabel('导演指令',{exact:true}).selectOption(option.value);
  await page.getByLabel('导演指令时长 (s)',{exact:true}).fill('1');
  const response=page.waitForResponse(r=>r.url().includes('/scene-3d/director-motion'),{timeout:15000});
  await page.getByTestId('scene-script-3d-director-submit').click();
  const r=await response;const body=await r.json();
  evidence.checks.push({kind:'consecutive-director',preset:option.value,pass:r.ok()&&body.success,response:body.error??null});
 }
 const savedResponse=page.waitForResponse(r=>r.url().includes(`/nodes/${node.node_id}`)&&r.request().method()==='PATCH',{timeout:15000});
 await page.getByRole('button',{name:'保存场景',exact:true}).click();
 const saved=await savedResponse;evidence.saveResponse={status:saved.status(),body:await saved.json(),submitted:saved.request().postDataJSON()};
 evidence.saveText=await page.locator('.scene-script-3d-editor').innerText();await save();
 await page.getByText('已保存',{exact:true}).first().waitFor({timeout:10000});
 await page.screenshot({path:new URL('scene3d-after-director.png',output).pathname.replace(/^\/(?=[A-Za-z]:)/,''),fullPage:true});
 if(process.argv.includes('--render')){
  for(let index=0;index<2;index++){
   const response=page.waitForResponse(r=>r.url().includes('/scene-3d/render/async')&&r.request().method()==='POST',{timeout:15000});
   await page.getByRole('button',{name:/预览渲染/,exact:false}).first().click();
   const res=await response;const body=await res.json();evidence.renderJobs.push(body);await save();
   const jobId=body.job_id;if(!res.ok()||!jobId)throw new Error('Render submission failed '+JSON.stringify(body));
   const deadline=Date.now()+180000;
   let job;
   while(Date.now()<deadline){await new Promise(resolve=>setTimeout(resolve,2500));job=await api(`/api/v1/scene-3d/render/${jobId}`);if(['completed','failed','cancelled'].includes(job.status))break;}
   evidence.checks.push({kind:'blender-render',index,jobId,pass:job?.status==='completed',job});await save();
   if(job?.status!=='completed')throw new Error('Blender render did not complete '+JSON.stringify(job));
   await page.getByTestId('scene-3d-render-result').waitFor({timeout:10000});
   const video=page.getByTestId('scene-3d-render-result').locator('video');
   await video.waitFor();await page.waitForFunction(()=>{const v=document.querySelector('[data-testid="scene-3d-render-result"] video');return v&&v.readyState>=2;},{},{timeout:15000});
   const media=await video.evaluate(async v=>{await v.play();await new Promise(r=>setTimeout(r,500));v.pause();return {src:v.currentSrc,readyState:v.readyState,duration:v.duration,currentTime:v.currentTime,error:v.error?.message??null};});
   evidence.checks.push({kind:'browser-video-playback',jobId,pass:media.readyState>=2&&media.currentTime>0&&!media.error,media});await save();
  }
 }
 evidence.finished=new Date().toISOString();await save();console.log(JSON.stringify(evidence,null,2));
}catch(error){evidence.failure=error.message;await save();console.error(error);process.exitCode=1;}finally{await browser?.close();}
