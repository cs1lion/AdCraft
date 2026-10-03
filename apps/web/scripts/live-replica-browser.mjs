import { chromium } from '@playwright/test';
import { readFile,writeFile } from 'node:fs/promises';
const output=new URL('../e2e_output/live-acceptance/',import.meta.url);
const setup=JSON.parse(await readFile(new URL('setup.json',output),'utf8'));
const browser=await chromium.launch({channel:'chrome',headless:true});
const evidence={workflowId:setup.workflowId,events:[],errors:[]};
try {
 const page=await browser.newPage({viewport:{width:1600,height:1000}});
 page.on('pageerror',err=>evidence.errors.push(err.message));
 page.on('response',response=>{
  const url=response.url();
  if(/generate-film|assemble-film|final-composition.*render/.test(url)) evidence.events.push({url: url.split('?')[0],status:response.status()});
 });
 await page.goto('http://127.0.0.1:5189/workflow/proj_01c0f83902e0e0b8',{waitUntil:'domcontentloaded'});
 await page.waitForTimeout(5000);
 console.log('PREVIEW '+JSON.stringify({url:page.url(),text:(await page.locator('body').innerText()).slice(0,8000),errors:evidence.errors}));
 await page.getByRole('button',{name:'🎬 生成复刻成片',exact:true}).waitFor({timeout:15000});
 if(process.argv.includes('--generate')) {
   await page.getByRole('button',{name:'🎬 生成复刻成片',exact:true}).click();
   const outcome = page.locator('.replica-workbench').getByText(/生成失败：|渲染失败|成片已完成|渲染完成|下载成片/).first();
   try { await outcome.waitFor({timeout:20*60*1000}); }
   catch { evidence.timeout=true; }
   evidence.videos=await page.locator('.replica-workbench video').evaluateAll(els=>els.map(el=>({src:el.currentSrc || el.src,readyState:el.readyState,duration:el.duration,width:el.videoWidth,height:el.videoHeight,error:el.error?.message})));
   await page.waitForTimeout(1500);
 }
 await page.waitForTimeout(1500);
 evidence.text=await page.locator('body').innerText();
 evidence.buttons=await page.getByRole('button').evaluateAll(els=>els.map(el=>({text:el.textContent,aria:el.getAttribute('aria-label'),disabled:el.disabled})));
 evidence.url=page.url();
 await page.screenshot({path:new URL('replica-before.png',output).pathname.replace(/^\/(?=[A-Za-z]:)/,''),fullPage:true});
 await writeFile(new URL('replica-browser.json',output),JSON.stringify(evidence,null,2));
 console.log(JSON.stringify(evidence,null,2));
} finally {await browser.close();}
