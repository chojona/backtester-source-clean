import { expect, test } from "@playwright/test";

const profileEndpoint = "**/api/amt/profile?*";

test("auction controls persist, use the existing chart, and hide future anchors in replay", async ({ page }) => {
  test.skip(process.env.NQ_BROWSER_FIXTURE !== "1", "Requires the formula-only terminal fixture");
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(() => {
    window.addEventListener("DOMContentLoaded", () => {
      document.documentElement.dataset.amtBenchmark = "1";
    }, { once: true });
    if (!localStorage.getItem("nq:v3:workspace")) localStorage.setItem("nq:v3:workspace", JSON.stringify({
      version: 3, workspace: { contract: "NQH26", session: "2026-03-13", frame: "1m", display: "Globex" },
    }));
  });
  await page.goto("/");
  await expect(page.getByTestId("chart-history-coverage")).toContainText("2 sessions");
  const chart = page.getByTestId("market-chart");
  const stableCanvas = await chart.locator("canvas").first().elementHandle();
  const toggle = page.getByRole("button", { name: "Auction analytics", exact: true });
  const open = () => toggle.click();
  const close = () => page.getByRole("button", { name: "Close auction analytics" }).click();
  await open();
  await page.getByLabel("Volume Profile", { exact: true }).check();
  await page.getByLabel("Volume allocation").selectOption("uniform");
  await expect(page.getByTestId("auction-profile")).toContainText("allocated");
  await page.getByLabel("TPO display").selectOption("letters");
  await expect(page.getByTestId("auction-tpo")).toContainText("IB");
  await page.getByLabel("Advanced VWAP").selectOption("manual");
  await page.getByRole("button", { name: "Select anchor on chart" }).click();
  const box = (await chart.boundingBox())!;
  await page.mouse.click(box.x + box.width * .68, box.y + box.height * .46);
  await expect(page.getByTestId("auction-anchor")).toBeVisible();
  await expect(page.getByTestId("auction-vwap")).toContainText("HLC3 estimate");
  const originalTime = await page.getByLabel("Anchor UTC").inputValue();
  await page.getByLabel("Anchor price").fill("114.25");
  await page.getByRole("button", { name: "Save anchor" }).click();
  await expect(page.getByTestId("auction-anchor")).toContainText("114.25");
  expect(await stableCanvas?.evaluate(canvas => canvas.isConnected)).toBe(true);
  await close();
  await page.getByRole("button", { name: "5m", exact: true }).click();
  await expect(page.locator(".chart-symbol")).toContainText("5m");
  await open();
  await expect(page.getByLabel("Anchor UTC")).toHaveValue(originalTime);
  await page.reload();
  await open();
  await expect(page.getByLabel("Volume allocation")).toHaveValue("uniform");
  await expect(page.getByLabel("Anchor price")).toHaveValue("114.25");
  await expect(page.getByTestId("auction-profile")).toContainText("allocated");
  if (process.env.NQ_AMT_SCREENSHOT)
    await page.screenshot({ path: process.env.NQ_AMT_SCREENSHOT });
  await close();

  const replayProfile = page.waitForResponse(response => {
    const url = new URL(response.url());
    return url.pathname === "/api/amt/profile" && url.searchParams.has("as_of");
  });
  await page.getByRole("button", { name: "Start replay", exact: true }).click();
  await expect(page.getByTestId("replay-cursor")).toContainText("1 /");
  await open();
  const reply = await (await replayProfile).json();
  expect(reply.coverage.observed_minutes).toBe(1);
  expect(reply.profile.total_volume).toBe(10);
  await expect(page.getByTestId("auction-profile")).toContainText("10 allocated");
  await expect(page.getByTestId("auction-anchor")).toHaveCount(0);
  await expect(page.getByTestId("auction-vwap")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("a delayed profile cannot contaminate another session or replace the chart", async ({ page }) => {
  test.skip(process.env.NQ_BROWSER_FIXTURE !== "1", "Requires the formula-only terminal fixture");
  await page.goto("/");
  const select = page.getByLabel("Session date", { exact: true });
  await select.selectOption("2026-03-19");
  await page.getByRole("button", { name: "Auction analytics", exact: true }).click();
  await expect(page.getByLabel("Volume Profile", { exact: true })).toBeVisible();
  let unblock!: () => void;
  const gate = new Promise<void>(resolve => { unblock = resolve; });
  let settle!: () => void;
  const settled = new Promise<void>(resolve => { settle = resolve; });
  await page.route(profileEndpoint, async route => {
    try {
      const response = await route.fetch();
      const json = await response.json();
      json.profile.total_volume = 987654321;
      await gate;
      await route.fulfill({ response, json });
    } catch {
      // Chromium can cancel the intercepted fetch after the scope changes.
    } finally {
      settle();
    }
  }, { times: 1 });
  const first = page.waitForRequest(r => r.url().includes("/api/amt/profile?"));
  await page.getByLabel("Volume Profile", { exact: true }).check();
  expect(new URL((await first).url()).searchParams.get("session")).toBe("2026-03-19");
  await select.selectOption("2026-03-17");
  unblock();
  await settled;
  await expect(page.getByTestId("auction-profile")).toContainText("allocated");
  await expect(page.getByTestId("auction-profile")).not.toContainText("987,654,321");
});

test("release auction overlays use bounded render work and keep chart history intact", async ({ page, request }) => {
  test.skip(process.env.NQ_BROWSER_RELEASE !== "1", "Requires the verified historical release");
  const contracts = await (await request.get("/api/contracts")).json();
  const exact = contracts.find((c: { contract: string; sessions: number }) => c.sessions >= 20);
  await page.addInitScript(() => {
    window.addEventListener("DOMContentLoaded", () => {
      document.documentElement.dataset.amtBenchmark = "1";
    }, { once: true });
  });
  await page.goto("/");
  await page.getByLabel("Contract", { exact: true }).selectOption(exact.contract);
  await page.getByLabel("Session date", { exact: true }).selectOption(exact.last_session);
  await expect(page.getByTestId("chart-history-coverage")).toContainText("20 sessions", { timeout: 30_000 });
  const chart = page.getByTestId("market-chart");
  const before = await chart.getAttribute("data-set-data-count");
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Performance.enable");
  const heap = async () => {
    await cdp.send("HeapProfiler.collectGarbage");
    return Math.round((await cdp.send("Performance.getMetrics")).metrics
      .find(metric => metric.name === "JSHeapUsedSize")!.value / 2**20);
  };
  const initialHeap = await heap();
  await page.getByRole("button", { name: "Auction analytics", exact: true }).click();
  const started = performance.now();
  await page.getByLabel("Volume Profile", { exact: true }).check();
  await expect(page.getByTestId("auction-profile")).toContainText("POC");
  const profileMs = Math.round(performance.now() - started);
  await page.getByLabel("TPO display").selectOption("blocks");
  await page.getByLabel("Advanced VWAP").selectOption("week");
  await expect(page.getByTestId("auction-tpo")).toContainText("TPO periods");
  await expect(page.getByTestId("auction-vwap")).toContainText("HLC3 estimate");
  await expect(chart).toHaveAttribute("data-set-data-count", before!);
  await page.getByRole("button", { name: "Close auction analytics" }).click();
  const box = (await chart.boundingBox())!;
  await page.mouse.move(box.x + box.width * .7, box.y + box.height * .5);
  await page.evaluate(() => performance.clearMeasures("nq-amt-primitives"));
  const zoomStart = performance.now();
  await page.mouse.wheel(0, -220);
  await expect.poll(() => page.evaluate(() => performance.getEntriesByName("nq-amt-primitives")
    .some(entry => (entry as PerformanceMeasure).detail.work > 0))).toBe(true);
  const zoomMs = Math.round(performance.now() - zoomStart);
  const rendering = await page.evaluate(() => {
    const entries = performance.getEntriesByName("nq-amt-primitives") as PerformanceMeasure[];
    return { draws: entries.length, max_draw_ms: Math.max(...entries.map(e => e.duration)),
      max_work: Math.max(...entries.map(e => e.detail.work)) };
  });
  expect(rendering.max_work).toBeGreaterThan(0);
  expect(rendering.max_work).toBeLessThan(20_000);
  console.log(JSON.stringify({ profile_ms: profileMs, zoom_probe_ms: zoomMs, initial_heap_mib: initialHeap,
    enabled_heap_mib: await heap(), candles: Number(await chart.getAttribute("data-candles")), ...rendering }));
});
