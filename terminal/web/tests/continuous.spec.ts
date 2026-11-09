import {test,expect} from '@playwright/test';
import {indicatorPoints} from '../lib/continuous';
import type {Bar} from '../lib/types';

test('indicator lines separate source-contract sessions',()=>{
  const bar=(time:number,contract:string,day:string)=>({time,available_at:time+60,source_contract:contract,trading_date:day,vwap:100} as Bar);
  const points=indicatorPoints([bar(100,'NQH26','2026-03-13'),bar(160,'NQH26','2026-03-13'),bar(1000,'NQM26','2026-03-16')],'vwap',true);
  expect(points).toEqual([{time:100,value:100},{time:160,value:100},{time:161},{time:1000,value:100}]);
});

test('continuous raw and adjusted symbols, full chart, metadata and replay guards',async({page,request})=>{
  test.setTimeout(90000);
  const manifest=await request.get('/api/continuous/manifest');
  test.skip(process.env.NQ_BROWSER_RELEASE !== '1' || !manifest.ok(),'Requires a built external continuous release');
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');
  await page.getByLabel('Contract',{exact:true}).selectOption('NQ1! Raw');
  await expect(page.locator('.chart-symbol')).toContainText('NQ1! Raw',{timeout:30000});
  await expect(page.getByTestId('continuous-readout')).toContainText('unadjusted');
  await page.getByLabel('Continuous history').selectOption('5000');
  await expect(page.locator('.chart-symbol')).toContainText('daily');
  await expect(page.getByTestId('continuous-coverage')).toContainText('4,262 sessions',{timeout:30000});
  await page.getByRole('tab',{name:'Strategy Research',exact:true}).click();
  await expect(page.locator('.inactive-panel')).toContainText('chart views');
  await page.getByRole('tab',{name:'Data Explorer',exact:true}).click();
  await page.getByLabel('Continuous history').selectOption('1');
  await page.getByRole('button',{name:'1m',exact:true}).click();
  await page.getByRole('button',{name:'Start replay',exact:true}).click();
  await expect(page.getByTestId('replay-cursor')).toContainText('1 /');
  await page.getByRole('button',{name:'Exit',exact:true}).click();
  await page.getByLabel('Contract',{exact:true}).selectOption('NQ1! Adjusted');
  await expect(page.locator('.chart-symbol')).toContainText('NQ1! Adjusted');
  await expect(page.getByRole('button',{name:'Start replay',exact:true})).toBeDisabled();
  await expect(page.getByTestId('continuous-readout')).toContainText('retrospective block');
  await page.getByLabel('Continuous history').selectOption('5000');
  await expect(page.getByTestId('continuous-coverage')).toContainText('4,262 sessions',{timeout:30000});
  await expect(page.getByTestId('market-chart').locator('canvas').first()).toBeVisible();
  await expect(page.getByTestId('roll-marker')).toHaveCount(0);
  await page.getByLabel('Show rollovers').check();
  await expect(page.getByTestId('roll-marker')).toHaveCount(66);
  await expect(page.getByTestId('roll-marker').locator('text')).toHaveCount(0);
  await page.getByLabel('Show rollovers').uncheck();
  await page.getByRole('button',{name:'Data quality',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'Continuous data quality'})).toBeVisible();
  await expect(page.locator('.quality-stats')).toContainText('66');
  await page.getByRole('tab',{name:'Excluded sessions',exact:true}).click();
  await expect(page.locator('.quality-table-scroll')).toContainText('Contract rollover');
  await page.getByRole('button',{name:'Close data quality'}).click();
  await page.screenshot({path:'/tmp/nq-continuous-chart.png',fullPage:true});
  expect(errors).toEqual([]);
});


test('chart labels and quality details do not overlap at desktop or mobile sizes',async({page,request})=>{
  test.setTimeout(90000);
  test.skip(process.env.NQ_BROWSER_RELEASE !== '1' || !(await request.get('/api/continuous/manifest')).ok(),'Requires external continuous release');
  await page.goto('/');
  await page.getByLabel('Contract',{exact:true}).selectOption('NQ1! Raw');
  await expect(page.getByTestId('continuous-readout')).toBeVisible();
  await page.getByLabel('Continuous history').selectOption('5000');
  await expect(page.getByTestId('continuous-coverage')).toContainText('4,262 sessions',{timeout:45000});
  for(const width of [1440,390]){
    await page.setViewportSize({width,height:1000});
    await page.getByRole('button',{name:'Fit history',exact:true}).click();
    const bounds=await page.locator('.chart-header').evaluate(header=>{
      const plot=header.nextElementSibling!.getBoundingClientRect();
      const head=header.getBoundingClientRect();
      const blocks=Array.from(header.children).filter(e=>e.getBoundingClientRect().height>0).map(e=>e.getBoundingClientRect());
      return {headerBottom:head.bottom,plotTop:plot.top,plotHeight:plot.height,plotBottom:plot.bottom,wrapperBottom:header.parentElement!.getBoundingClientRect().bottom,replayTop:document.querySelector(".replay-bar")!.getBoundingClientRect().top,
        overlap:blocks.some((b,i)=>i>0 && b.top<blocks[i-1].bottom-1),
        pageWidth:document.documentElement.scrollWidth};
    });
    expect(bounds.headerBottom).toBeLessThanOrEqual(bounds.plotTop+1);
    expect(bounds.plotHeight).toBeGreaterThanOrEqual(250);
    expect(bounds.overlap).toBe(false);
    expect(bounds.plotBottom).toBeLessThanOrEqual(bounds.wrapperBottom+1);
    expect(bounds.plotBottom).toBeLessThanOrEqual(bounds.replayTop+1);
    expect(bounds.pageWidth).toBeLessThanOrEqual(width);
    const before=await page.getByTestId('market-chart').boundingBox();
    await page.getByRole('button',{name:'Data quality',exact:true}).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    const modal=await page.getByRole('dialog').boundingBox();
    expect(modal!.x).toBeGreaterThanOrEqual(0);
    expect(modal!.x+modal!.width).toBeLessThanOrEqual(width);
    if(width===1440)await page.screenshot({path:'/tmp/nq-quality-dialog.png',fullPage:true});
    await page.getByRole('tab',{name:'Missing intervals',exact:true}).click();
    await expect(page.locator('.quality-table-scroll tbody tr').first()).toBeVisible();
    await expect(page.locator('.quality-table-scroll')).not.toContainText('Loading intervals');
    await page.getByRole('button',{name:'Next quality page'}).click();
    await expect(page.locator('.quality-footer')).toContainText('21–40');
    await page.getByRole('button',{name:'Close data quality'}).click();
    expect((await page.getByTestId('market-chart').boundingBox())?.height).toBe(before?.height);
    await page.screenshot({path:`/tmp/nq-clean-ui-${width}.png`,fullPage:true});
  }
});


test('full history switches to a usable intraday window and restores on daily',async({page,request})=>{
  test.setTimeout(60000);
  test.skip(process.env.NQ_BROWSER_RELEASE !== '1' || !(await request.get('/api/continuous/manifest')).ok(),'Requires external continuous release');
  const badRequests:string[]=[];
  page.on('response',response=>{if(response.url().includes('/api/snapshot')&&!response.ok())badRequests.push(response.url());});
  await page.goto('/');
  await page.getByLabel('Contract',{exact:true}).selectOption('NQ1! Raw');
  await expect(page.getByTestId('continuous-readout')).toBeVisible();
  await page.getByLabel('Continuous history').selectOption('5000');
  await expect(page.getByTestId('continuous-coverage')).toContainText('4,262 sessions',{timeout:45000});
  await page.getByRole('button',{name:'1m',exact:true}).click();
  await expect(page.getByLabel('Continuous history')).toHaveValue('20');
  await expect(page.locator('.chart-symbol')).toContainText('1m');
  await expect(page.getByTestId('continuous-coverage')).toContainText('20 sessions',{timeout:30000});
  await expect(page.getByText('Intraday · 20 sessions at startup.',{exact:false})).toBeVisible();
  await expect(page.locator('.error-message')).toHaveCount(0);
  await page.getByRole('button',{name:'D',exact:true}).click();
  await expect(page.getByLabel('Continuous history')).toHaveValue('5000');
  await expect(page.getByTestId('continuous-coverage')).toContainText('4,262 sessions',{timeout:45000});
  expect(badRequests).toEqual([]);
});
