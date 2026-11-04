const { test, expect } = require('@playwright/test');

test('screenshot index.html', async ({ page }) => {
  await page.goto('http://127.0.0.1:8000/index.html');
  await page.waitForTimeout(2000);
  await page.screenshot({ path: 'frontend_screenshot.png', fullPage: true });
});
