import { expect, test, type Page } from "@playwright/test";

const endpoint = "**/api/chart/window?*";
const isWindow = (url: string) => url.includes("/api/chart/window?");
const coverage = (page: Page) => page.getByTestId("continuous-coverage");
const status = (page: Page) => page.getByTestId("intraday-history");

async function pan(page: Page, direction: "older" | "newer") {
  const box = (await page.getByTestId("market-chart").boundingBox())!;
  const x = box.x + box.width * 0.45;
  const y = box.y + box.height * 0.45;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + (direction === "older" ? 1 : -1) * box.width * 0.16, y, { steps: 12 });
  await page.mouse.up();
}

async function openRaw(page: Page) {
  await page.goto("/");
  await page.getByLabel("Contract", { exact: true }).selectOption("NQ1! Raw");
  await page.getByLabel("Continuous history").selectOption("1");
  await page.getByLabel("Session date", { exact: true }).selectOption("2026-03-16");
  await expect(coverage(page)).toContainText("2026-03-16 → 2026-03-16");
  await expect(status(page)).toContainText("Pan at either edge");
}

test.describe("constructed intraday fixture", () => {
  test.skip(process.env.NQ_BROWSER_FIXTURE !== "1", "Requires the formula-only terminal fixture");

  test("pans in both directions, preserving annotations and exposing unresolved roll gaps", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await openRaw(page);
    const chart = page.getByTestId("market-chart");
    await page.getByLabel("Drawing tool", { exact: true }).selectOption("horizontal");
    const box = (await chart.boundingBox())!;
    await page.mouse.click(box.x + box.width * 0.25, box.y + box.height * 0.35);
    await expect(page.locator(".drawing-toolbar summary")).toHaveText("Objects (1)");
    const drawings = () => page.evaluate(() => localStorage.getItem(
      Object.keys(localStorage).find(key => key.startsWith("nq:v3:drawings:") && key.includes("NQ1! Raw"))!));
    const beforeDrawings = await drawings();
    expect(beforeDrawings).toBeTruthy();

    let releaseResponse!: () => void;
    const responseGate = new Promise<void>(resolve => { releaseResponse = resolve; });
    await page.route(endpoint, async route => {
      const response = await route.fetch();
      const json = await response.json();
      json.bars.push(json.bars[0]);
      await responseGate;
      await route.fulfill({ response, json });
    }, { times: 1 });
    const older = page.waitForRequest(request => isWindow(request.url()) &&
      new URL(request.url()).searchParams.has("cursor"));
    await pan(page, "older");
    const query = new URL((await older).url()).searchParams;
    expect(query.get("cursor")).toBeTruthy();
    expect(query.get("contract")).toBe("NQ1! Raw");
    const view = () => page.evaluate(() => JSON.parse(localStorage.getItem(
      Object.keys(localStorage).find(key => key.startsWith("nq:v3:view:") &&
        key.includes("NQ1! Raw") && key.includes("2026-03-16") && key.endsWith("/1m"))!) || "null"));
    const before = await view();
    releaseResponse();
    await expect(coverage(page)).toContainText("2026-03-12 → 2026-03-16");
    await expect(status(page)).toContainText("Earliest session reached");
    const after = await view();
    expect(after.to).toBe(before.to);
    expect(await drawings()).toBe(beforeDrawings);
    await expect(page.locator(".drawing-toolbar summary")).toHaveText("Objects (1)");

    await page.getByRole("button", { name: "Fit history" }).click();
    await page.getByLabel("Show rollovers").check();
    await expect(page.getByTestId("roll-marker").locator("title")).toContainText("overlap unresolved");
    const newer = page.waitForResponse(response => isWindow(response.url()) &&
      new URL(response.url()).searchParams.has("cursor"));
    await pan(page, "newer");
    const pageData = await (await newer).json();
    expect(pageData.session_dates).toEqual(["2026-03-17", "2026-03-18", "2026-03-19"]);
    expect(pageData.bars.some((bar: { trading_date: string }) => bar.trading_date === "2026-03-18")).toBe(false);
    await expect(coverage(page)).toContainText("2026-03-12 → 2026-03-19");
    await expect(status(page)).toContainText("All available history edges reached");
    expect(await drawings()).toBe(beforeDrawings);
    expect(errors).toEqual([]);
  });

  test("recovers from a failed window and isolates stale history from mode changes and replay", async ({ page }) => {
    await openRaw(page);
    await page.route(endpoint, route => route.abort("failed"), { times: 1 });
    await pan(page, "older");
    await expect(status(page)).toContainText("Could not load older sessions");
    await expect(coverage(page)).toContainText("2026-03-16 → 2026-03-16");
    await page.getByRole("button", { name: "Retry history" }).click();
    await expect(coverage(page)).toContainText("2026-03-12 → 2026-03-16");
    await page.getByRole("button", { name: "Fit history" }).click();

    let releaseResponse!: () => void;
    const responseGate = new Promise<void>(resolve => { releaseResponse = resolve; });
    let stopped!: () => void;
    const routeDone = new Promise<void>(resolve => { stopped = resolve; });
    await page.route(endpoint, async route => {
      try {
        const response = await route.fetch();
        await responseGate;
        await route.fulfill({ response });
      } catch {
        // Chromium may cancel the route once the client aborts fetch.
      } finally {
        stopped();
      }
    }, { times: 1 });
    const pending = page.waitForRequest(request => isWindow(request.url()) && new URL(request.url()).searchParams.has("cursor"));
    await pan(page, "newer");
    expect(new URL((await pending).url()).searchParams.get("contract")).toBe("NQ1! Raw");
    await page.getByLabel("Contract", { exact: true }).selectOption("NQ1! Adjusted");
    releaseResponse();
    await routeDone;
    await expect(page.locator(".chart-symbol")).toContainText("NQ1! Adjusted");
    await expect(coverage(page)).toContainText("1 sessions");
    await expect(page.getByRole("button", { name: "Start replay" })).toBeDisabled();

    await page.getByLabel("Contract", { exact: true }).selectOption("NQ1! Raw");
    await expect(page.locator(".chart-symbol")).toContainText("NQ1! Raw");
    const requests: string[] = [];
    page.on("request", request => { if (isWindow(request.url())) requests.push(request.url()); });
    await page.getByRole("button", { name: "Start replay" }).click();
    await expect(page.getByTestId("replay-cursor")).toContainText("1 /");
    await expect(status(page)).toHaveCount(0);
    await pan(page, "older");
    await pan(page, "newer");
    expect(requests).toEqual([]);
  });
});

test("release-backed intraday pans load adjacent windows without changing the selected session", async ({ page, request }) => {
  test.skip(process.env.NQ_BROWSER_RELEASE !== "1", "Requires the existing external continuous release");
  const response = await request.get("/api/sessions?contract=NQ1%21%20Raw&limit=30");
  expect(response.ok()).toBe(true);
  const sessions = await response.json();
  const anchor = sessions.slice(10, 20).find((session: { minutes: number }) => session.minutes > 1000).trading_date;
  await page.goto("/");
  await page.getByLabel("Contract", { exact: true }).selectOption("NQ1! Raw");
  await page.getByLabel("Continuous history").selectOption("1");
  const selection = page.getByLabel("Session date", { exact: true });
  await selection.selectOption(anchor);
  await expect(coverage(page)).toContainText(`${anchor} → ${anchor}`);

  for (const direction of ["older", "newer"] as const) {
    await page.getByRole("button", { name: "Fit history" }).click();
    const pending = page.waitForResponse(response => isWindow(response.url()) &&
      new URL(response.url()).searchParams.has("cursor"));
    await pan(page, direction);
    const windowResponse = await pending;
    expect(windowResponse.ok()).toBe(true);
    const window = await windowResponse.json();
    expect(window.session_dates.length).toBeGreaterThan(0);
    expect(window.bars.length).toBeLessThanOrEqual(2500);
    expect(window.session_dates.every((date: string) => direction === "older" ? date < anchor : date > anchor)).toBe(true);
    await expect(coverage(page)).toContainText(direction === "older" ? window.session_dates[0] : window.session_dates.at(-1));
    await expect(selection).toHaveValue(anchor);
  }
});

test("release-backed repeated history loads stay within the chart budget", async ({ page, request }) => {
  test.skip(process.env.NQ_BROWSER_RELEASE !== "1" || process.env.NQ_BROWSER_BENCHMARK !== "1",
    "Requires the sealed continuous release and explicit benchmark opt-in");
  test.setTimeout(90_000);
  const response = await request.get("/api/sessions?contract=NQ1%21%20Raw&limit=120");
  const sessions = await response.json();
  const session = sessions.slice(45, 75).find((entry: { minutes: number }) => entry.minutes > 1000).trading_date;
  const chart = page.getByTestId("market-chart");
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Performance.enable");
  const heap = async () => {
    await cdp.send("HeapProfiler.collectGarbage");
    const metrics = await cdp.send("Performance.getMetrics");
    return Math.round((metrics.metrics.find(metric => metric.name === "JSHeapUsedSize")?.value ?? 0) / 2**20);
  };
  await page.goto("/");
  await page.getByLabel("Contract", { exact: true }).selectOption("NQ1! Raw");
  const started = performance.now();
  await page.getByLabel("Session date", { exact: true }).selectOption(session);
  await expect(coverage(page)).toContainText("20 sessions", { timeout: 30_000 });
  const startup = performance.now() - started;
  const initialHeap = await heap();
  const latencies: number[] = [];
  const updates: number[] = [];
  let peakCandles = 0;
  for (const direction of ["older", "newer"] as const) {
    for (let i = 0; i < 4; i++) {
      await page.getByRole("button", { name: "Fit history" }).click();
      const before = await chart.getAttribute("data-set-data-count");
      const next = page.waitForResponse(res => isWindow(res.url()) && new URL(res.url()).searchParams.has("cursor"));
      const start = performance.now();
      await pan(page, direction);
      expect((await next).ok()).toBe(true);
      await expect(chart).not.toHaveAttribute("data-set-data-count", before!);
      latencies.push(performance.now() - start);
      updates.push(Number(await chart.getAttribute("data-set-data-ms")));
      peakCandles = Math.max(peakCandles, Number(await chart.getAttribute("data-candles")));
    }
  }
  expect(peakCandles).toBeGreaterThan(20_000);
  expect(peakCandles).toBeLessThanOrEqual(30_000);
  const finalHeap = await heap();
  console.log(JSON.stringify({
    startup_ms: Math.round(startup), pan_samples: latencies.length,
    max_pan_ms: Math.round(Math.max(...latencies)), max_set_data_ms: Math.max(...updates),
    initial_heap_mib: initialHeap, final_heap_mib: finalHeap, peak_candles: peakCandles,
  }));
});
