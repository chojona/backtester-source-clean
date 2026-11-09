import { test, expect } from '@playwright/test';
// Requires API NQ_RESEARCH_DEMO=1; never opens licensed data or final holdout.
test('research execution, history, chart and replay', async ({ page }) => {
  const errors:string[]=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');
  await page.getByRole('tab',{name:'Strategy Research',exact:true}).click();
  const research=page.frameLocator('iframe[title="Strategy Research workspace"]');
  await expect(research.locator('#status')).toContainText('Ready');
  await expect(research.locator('#mode')).toContainText('SYNTHETIC');
  await research.getByRole('button',{name:'Run experiment',exact:true}).click();
  await expect(research.locator('#status')).toContainText('Completed',{timeout:60000});
  await expect(research.locator('#results')).toContainText('Sharpe / profit factor / equity curve: unavailable');
  await expect(research.locator('#results')).toContainText('$15 round trip');
  await expect(research.locator('#chart canvas').first()).toBeVisible();
  await expect(research.locator('#chartInfo')).toContainText('NQZ26');
  await expect(research.locator('#history button').first()).toBeVisible();
  await research.getByRole('button',{name:'Compare',exact:true}).click();
  await expect(research.locator('#comparison')).toContainText('specification_version');
  await research.getByRole('button',{name:'Start replay',exact:true}).click();
  await expect(research.locator('#results')).toContainText('Replay active');
  await expect(research.locator('#historyPanel')).toBeHidden();
  await expect(research.locator('#integrity')).toBeHidden();
  await expect(research.locator('#chartInfo')).toContainText('completed candles only');
  await research.getByRole('button',{name:'+1 bar',exact:true}).click();
  await expect(research.locator('#replay')).toHaveValue('1');
  await research.getByRole('button',{name:'End replay',exact:true}).click();
  await expect(research.locator('#historyPanel')).toBeVisible();
  await research.locator('#end').evaluate((node:HTMLInputElement)=>{node.max='2026-01-20';node.value='2026-01-20';});
  await research.getByRole('button',{name:'Run experiment',exact:true}).click();
  await expect(research.locator('#status')).toContainText('holdout',{timeout:60000});
  await page.screenshot({path:'/tmp/nq-terminal-v03-smoke.png',fullPage:true});
  expect(errors).toEqual([]);
});


test('research results fit a mobile viewport', async ({ page }) => {
  await page.setViewportSize({width:390,height:844});
  await page.goto('/research/');
  await page.locator('#history button').first().click();
  await expect(page.locator('#chartInfo')).toContainText('NQZ26');
  await expect(page.locator('#results')).toContainText('Mean hypothetical net / event');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({path:'/tmp/nq-terminal-v03-mobile.png',fullPage:true});
});
