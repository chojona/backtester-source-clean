import { expect, test } from "@playwright/test";

test("constructed workspace migrates legacy settings and drawings, then hides future anchors in replay", async ({ page, request }) => {
  test.skip(process.env.NQ_BROWSER_FIXTURE !== "1", "Requires the formula-only terminal fixture");
  const contract = "NQH26", session = "2026-03-13";
  const response = await request.get("/api/snapshot", { params: { contract, session } });
  const bars = (await response.json()).bars;
  const point = { time: bars[30].time, price: bars[30].close };
  await page.addInitScript(({ contract, session, point }) => {
    if (localStorage.getItem("nq:v3:workspace")) return;
    localStorage.setItem("nq:v2:workspace", JSON.stringify({
      contract, session, frame: "1m", display: "Globex", width: 340, height: 560,
      indicators: { vwap: { visible: false, color: "#ffff00", style: 2 } },
    }));
    localStorage.setItem("nq:v2:drawings:" + contract + ":" + session + ":Globex", JSON.stringify([
      { id: "legacy", type: "horizontal", points: [point, point], createdAt: point.time + 60,
        visible: true, color: "#8bb8f4" },
      { id: "invalid", type: "ray", points: [null, point], createdAt: 0, visible: true, color: "#8bb8f4" },
    ]));
  }, { contract, session, point });
  await page.goto("/");
  const start = page.getByRole("button", { name: "Start replay", exact: true });
  await expect(start).toBeEnabled();
  await expect(page.locator(".drawing-toolbar summary")).toHaveText("Objects (1)");
  await expect(page.locator(".drawing-object")).toHaveCount(1);
  const plot = page.getByTestId("market-chart");
  const before = await plot.getAttribute("data-set-data-count");
  await page.getByRole("button", { name: "Chart fullscreen", exact: true }).click();
  await expect(page.locator(".workspace-fullscreen")).toBeVisible();
  await expect(plot).toHaveAttribute("data-set-data-count", before!);
  await page.reload();
  await expect(page.locator(".workspace-fullscreen")).toBeVisible();
  await page.getByRole("button", { name: "Chart fullscreen", exact: true }).click();
  await expect(page.locator(".workspace-fullscreen")).toHaveCount(0);
  await expect(start).toBeEnabled();
  await page.getByRole("button", { name: "5m", exact: true }).click();
  await expect(page.locator(".chart-symbol")).toContainText("5m");
  await expect(page.locator(".drawing-toolbar summary")).toHaveText("Objects (1)");
  await expect(page.locator(".drawing-object")).toHaveCount(1);
  await expect(start).toBeEnabled();
  await start.click();
  await expect(page.getByTestId("replay-cursor")).toContainText("1 /");
  await expect(plot).toHaveAttribute("data-candles", "1");
  await expect(page.locator(".drawing-toolbar summary")).toHaveText("Objects (0)");
  await expect(page.locator(".drawing-object")).toHaveCount(0);
});

test("constructed workspace starts and remains usable when local storage is denied", async ({ page }) => {
  test.skip(process.env.NQ_BROWSER_FIXTURE !== "1", "Requires the formula-only terminal fixture");
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", { get() { throw new DOMException("Denied", "SecurityError"); } });
  });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Start replay" })).toBeEnabled();
  await expect(page.getByText("Local storage unavailable; settings last for this visit.")).toBeVisible();
  await page.getByRole("button", { name: "5m", exact: true }).click();
  await expect(page.locator(".chart-symbol")).toContainText("5m");
});

test("chart undo groups a drawing drag and restores a deletion without intercepting text input", async ({ page }) => {
  test.skip(process.env.NQ_BROWSER_FIXTURE !== "1", "Requires the formula-only terminal fixture");
  await page.goto("/");
  await page.getByLabel("Contract", { exact: true }).selectOption("NQH26");
  await page.getByLabel("Session date", { exact: true }).selectOption("2026-03-13");
  await expect(page.getByTestId("chart-history-coverage")).toContainText("2 sessions");
  const chart = page.getByTestId("market-chart");
  const drawing = page.locator(".drawing-object");
  const stored = () => page.evaluate(() => {
    const key = Object.keys(localStorage).find(name => name.startsWith('nq:v3:drawings:["NQH26"'));
    return key ? localStorage.getItem(key) : null;
  });

  await page.getByRole("button", { name: "Horizontal level", exact: true }).click();
  const box = (await chart.boundingBox())!;
  await page.mouse.click(box.x + box.width * .35, box.y + box.height * .35);
  await expect(drawing).toHaveCount(1);
  const original = await stored();
  expect(original).toBeTruthy();

  const handle = (await drawing.locator("circle").last().boundingBox())!;
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
  await page.mouse.down();
  await page.mouse.move(handle.x + 22, handle.y + 52, { steps: 8 });
  await page.mouse.up();
  await expect.poll(stored).not.toBe(original);
  await page.keyboard.press("Control+z");
  await expect.poll(stored).toBe(original);

  await page.getByRole("button", { name: "Chart details" }).click();
  await page.locator(".drawing-toolbar summary").click();
  await page.getByRole("button", { name: "horizontal", exact: true }).click();
  await page.getByLabel("Anchor 1 price", { exact: true }).focus();
  await page.keyboard.press("Control+z");
  await expect(drawing).toHaveCount(1);
  await expect.poll(stored).toBe(original);

  await page.getByRole("button", { name: "Delete horizontal", exact: true }).click();
  await expect(drawing).toHaveCount(0);
  await page.keyboard.press("Meta+z");
  await expect(drawing).toHaveCount(1);
  await expect.poll(stored).toBe(original);

  await page.keyboard.press("Control+z");
  await expect(drawing).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("button", { name: "Start replay" })).toBeEnabled();
  await expect(page.locator(".drawing-toolbar summary")).toHaveText("Objects (0)");
});
