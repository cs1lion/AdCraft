// @ts-check
import pw from 'playwright-core';
const { chromium } = pw;

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  await page.goto('http://localhost:5189/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(8000);
  await page.getByText('椰子复刻-叶子换花').first().click();
  await page.waitForTimeout(14000);
  await page.screenshot({ path: 'D:/project/myAdcraft/apps/web/e2e_output/l0-smoke/l3-29-canvas-replica.png' });
  console.log('canvas shot ok');

  const tabs = await page.getByRole('button', { name: /导演台|槽位替换/ }).count();
  console.log('replica tabs visible:', tabs);
  const slotTab = page.getByRole('button', { name: /槽位替换/ });
  if (await slotTab.count()) {
    await slotTab.first().click();
    await page.waitForTimeout(1500);
    await page.screenshot({ path: 'D:/project/myAdcraft/apps/web/e2e_output/l0-smoke/l3-30-replica-slots.png' });
    console.log('slots shot ok');
  }
  await browser.close();
})().catch((e) => { console.error('FAIL', e.message); process.exit(1); });
