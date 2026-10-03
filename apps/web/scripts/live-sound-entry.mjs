import { chromium } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
const output = new URL('../e2e_output/live-acceptance/sound-entry.json', import.meta.url);
const evidence = { errors: [], submissions: [] };
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
 const page = await browser.newPage({ viewport: { width:1600,height:1050 } });
 page.on('pageerror', error => evidence.errors.push(error.message));
 page.on('request', request => { if (request.method()==='POST' && /generate-film|assemble-film|build-from-outline/.test(request.url())) evidence.submissions.push(request.url()); });
 await page.goto('http://127.0.0.1:5189/workflow/proj_01c0f83902e0e0b8', {waitUntil:'domcontentloaded'});
 const details = page.locator('.replica-workbench__composition-details');
 await details.waitFor({timeout:20000});
 evidence.initiallyCollapsed = !(await details.getAttribute('open'));
 await details.locator(':scope > summary').click();
 const button = page.getByRole('button', {name:'选择或上传声音素材'});
 await button.waitFor({timeout:10000}); await button.click();
 const dialog = page.getByRole('dialog', {name:'Project assets'});
 await dialog.waitFor({timeout:10000});
 evidence.dialogOpen = true;
 evidence.audioUploadAccepted = await dialog.locator('input[type=file]').getAttribute('accept');
 evidence.dialogText = (await dialog.innerText()).slice(0,3000);
 if(evidence.submissions.length || evidence.errors.length) throw new Error('Sound entry unexpectedly submitted production or caused page error');
} catch(error) { evidence.failure=error.message; process.exitCode=1; }
finally { await writeFile(output,JSON.stringify(evidence,null,2));console.log(JSON.stringify(evidence,null,2));await browser.close(); }
