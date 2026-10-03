import { chromium } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
const output = new URL('../e2e_output/live-acceptance/', import.meta.url);
await mkdir(output, {recursive:true});
const browser = await chromium.launch({channel:'chrome', headless:true});
try {
  const page = await browser.newPage({viewport:{width:1440,height:960}});
  const errors=[];
  page.on('pageerror', e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:5189/', {waitUntil:'networkidle'});
  if (process.argv.includes('--new-project')) {
    await page.getByRole('button', {name:'Create Your Project', exact:true}).click();
    await page.waitForTimeout(3000);
  }
  await page.screenshot({path:new URL(process.argv.includes('--new-project') ? 'new-project-ui.png' : 'initial-ui.png',output).pathname.replace(/^\/(?=[A-Za-z]:)/,''),fullPage:true});
  const links = await page.getByRole('link').evaluateAll(elements=>elements.map(el=>({text:el.textContent,href:el.getAttribute('href')})));
  const buttons = await page.getByRole('button').allTextContents();
  const summary = {url:page.url(),title:await page.title(),text:(await page.locator('body').innerText()).slice(0,7000),links,buttons,errors};
  await writeFile(new URL('initial-ui.json',output),JSON.stringify(summary,null,2));
  console.log(JSON.stringify(summary,null,2));
} finally {await browser.close();}
