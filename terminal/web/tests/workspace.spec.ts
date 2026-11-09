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
