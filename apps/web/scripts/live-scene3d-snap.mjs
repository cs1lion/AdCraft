import { chromium } from '@playwright/test';
import {writeFile} from 'node:fs/promises';
const wf='adwf_v2_01c0f83902e0e0b8',id='node_45e6847ebe02438087564008537efca4';
const evidence={errors:[],requests:[]};const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{const page=await browser.newPage({viewport:{width:1800,height:1200}});page.on('pageerror',e=>evidence.errors.push(e.message));page.on('response',async r=>{if(r.url().includes('/layout')&&r.request().method()==='PATCH')evidence.requests.push({status:r.status(),request:r.request().postDataJSON(),response:await r.json()});});
 await page.goto('http://127.0.0.1:5189/workflow/proj_01c0f83902e0e0b8',{waitUntil:'domcontentloaded'});await page.waitForTimeout(1500);const fit=page.getByRole('button',{name:/fit view/i});if(await fit.count())await fit.click();
 const w=await(await fetch(`http://127.0.0.1:8000/api/v2/workflows/${wf}`)).json();const videos=w.nodes.filter(n=>n.node_type==='video');
 await page.locator(`.react-flow__node[data-id="${id}"]`).waitFor({timeout:20000});
 if(await fit.count())await fit.click();await page.waitForTimeout(700);
 const boxes=[];for(const n of videos){const locator=page.locator(`.react-flow__node[data-id="${n.node_id}"]`);if(await locator.count()){const b=await locator.boundingBox();if(b)boxes.push({node:n,box:b});}}
 if(!boxes.length)throw new Error('No video sibling visible');
 const anchor=boxes.sort((a,b)=>(b.node.position.x)-(a.node.position.x))[0];evidence.anchor={id:anchor.node.node_id,position:anchor.node.position,box:anchor.box};
 const node=page.locator(`.react-flow__node[data-id="${id}"]`);await node.waitFor();const b=await node.boundingBox();const zoom=await page.locator('.react-flow__viewport').evaluate(el=>Number(el.style.transform.match(/scale\(([^)]+)\)/)?.[1]));
 evidence.zoom=zoom;evidence.before=w.nodes.find(n=>n.node_id===id).position;
 // Drop to the right with 45flow px gap and +8flow px vertical drift: both within semantic snap engagement.
 const desiredX=anchor.box.x+anchor.box.width+45*zoom;
 const desiredY=anchor.box.y+8*zoom;
 const start={x:b.x+b.width*.55,y:b.y+8};const target={x:start.x+desiredX-b.x,y:start.y+desiredY-b.y};evidence.gesture={start,target};
 await page.mouse.move(start.x,start.y);await page.mouse.down();await page.mouse.move(target.x,target.y,{steps:30});await page.mouse.up();await page.waitForTimeout(5000);
 const after=await(await fetch(`http://127.0.0.1:8000/api/v2/workflows/${wf}`)).json();evidence.after=after.nodes.find(n=>n.node_id===id).position;
 evidence.pass=Math.abs(evidence.after.y-anchor.node.position.y)<.01&&evidence.after.x>anchor.node.position.x&&evidence.requests.some(r=>r.status===200);
 console.log(JSON.stringify(evidence,null,2));if(!evidence.pass)process.exitCode=1;
}catch(e){evidence.failure=e.message;console.error(e);process.exitCode=1;}finally{await writeFile(new URL('../e2e_output/live-acceptance/scene3d-snap.json',import.meta.url),JSON.stringify(evidence,null,2));await browser.close();}
