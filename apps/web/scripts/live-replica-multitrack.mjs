import { chromium } from '@playwright/test';
import { readFile, writeFile } from 'node:fs/promises';
const output = new URL('../e2e_output/live-acceptance/', import.meta.url);
const setup = JSON.parse(await readFile(new URL('setup.json', output), 'utf8'));
const evidence = { workflowId: setup.workflowId, errors: [], requests: [], renders: [] };
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1050 } });
  page.on('pageerror', error => evidence.errors.push(error.message));
  page.on('request', request => {
    if (/generate-film|assemble-film/.test(request.url())) evidence.requests.push({ url: request.url(), body: request.postDataJSON() });
  });
  await page.goto(`http://127.0.0.1:5189/workflow/${setup.projectId || 'proj_01c0f83902e0e0b8'}`, { waitUntil: 'domcontentloaded' });
  const button = page.getByRole('button', { name: /重新合成现有镜头/ });
  await button.waitFor({ timeout: 20000 });
  for (let index = 0; index < 2; index++) {
    await button.waitFor({ state: 'visible' });
    const assembled = page.waitForResponse(response => response.url().includes('/assemble-film') && response.request().method() === 'POST');
    await button.click();
    const response = await assembled;
    const body = await response.json();
    evidence.renders.push({ index, status: response.status(), body });
    if (!response.ok() || !body.render_id || !body.success) throw new Error(`Assembly failed: ${JSON.stringify(body)}`);
    const deadline = Date.now() + 180000;
    let state;
    while (Date.now() < deadline) {
      state = await (await page.request.get(`http://127.0.0.1:5189/api/v2/workflows/${setup.workflowId}/final-composition/renders/${body.render_id}`)).json();
      if (['completed', 'failed', 'cancelled'].includes(state.status)) break;
      await page.waitForTimeout(1000);
    }
    evidence.renders[index].state = state;
    if (state.status !== 'completed') throw new Error(`Render failed: ${JSON.stringify(state)}`);
    const video = page.locator('.replica-workbench video');
    await video.waitFor({ timeout: 15000 });
    await page.waitForFunction(() => document.querySelector('.replica-workbench video')?.readyState >= 2, {}, { timeout: 15000 });
    const media = await video.evaluate(async video => {
      await video.play(); await new Promise(resolve => setTimeout(resolve, 450)); video.pause();
      return { src: video.currentSrc, readyState: video.readyState, duration: video.duration, width: video.videoWidth, height: video.videoHeight, currentTime: video.currentTime, error: video.error?.message || null };
    });
    evidence.renders[index].media = media;
    if (Math.abs(media.duration - 8) > .1 || media.currentTime <= 0 || media.error) throw new Error(`Program clock or playback mismatch: ${JSON.stringify(media)}`);
    await page.waitForTimeout(1500);
  }
  evidence.timeline = await (await page.request.get(`http://127.0.0.1:5189/api/v2/workflows/${setup.workflowId}/timeline`)).json();
  evidence.canonical = await (await page.request.get(`http://127.0.0.1:5189/api/v2/workflows/${setup.workflowId}/final-composition/timeline`)).json();
  evidence.text = await page.locator('body').innerText();
  evidence.generatedRequests = evidence.requests.filter(request => request.url.includes('generate-film')).length;
  if (evidence.generatedRequests) throw new Error('Reassembly unexpectedly submitted video generation');
  await page.screenshot({ path: new URL('replica-multitrack.png', output).pathname.replace(/^\/(?=[A-Za-z]:)/, ''), fullPage: true });
} catch (error) { evidence.failure = error.message; process.exitCode = 1; }
finally { await writeFile(new URL('replica-multitrack.json', output), JSON.stringify(evidence, null, 2)); console.log(JSON.stringify(evidence, null, 2)); await browser.close(); }
