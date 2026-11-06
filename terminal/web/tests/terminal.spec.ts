import { test, expect } from "@playwright/test";
test("real historical session, timeframes, replay, and explorer", async ({
  page,
  request,
}, testInfo) => {
  const health = await request.get("/api/health");
  expect(health.ok()).toBeTruthy();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Start replay" })).toBeEnabled({
    timeout: 60000,
  });
  await expect(
    page.getByTestId("market-chart").locator("canvas").first(),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("terminal-desktop.png"),
    fullPage: true,
  });
  const contract = await page
    .getByLabel("Contract", { exact: true })
    .inputValue();
  const session = await page
    .getByLabel("Session date", { exact: true })
    .inputValue();
  const original = await request.get(
    `/api/snapshot?contract=${contract}&session=${session}`,
  );
  const source = await original.json();
  await expect(page.getByTestId("replay-cursor")).toHaveText(
    `${source.total_minutes} / ${source.total_minutes} min`,
  );
  await page.getByRole("button", { name: "5m", exact: true }).click();
  await expect(page.locator(".chart-symbol")).toContainText("5m");
  await expect(page.locator("tbody tr").first()).toContainText(
    source.bars[0].open.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }),
  );
  await page.getByRole("button", { name: "Start replay" }).click();
  await expect(page.getByTestId("replay-cursor")).toHaveText(
    `1 / ${source.total_minutes} min`,
  );
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.locator("tbody")).toContainText("DEVELOPING");
  await page.getByRole("button", { name: "Step forward one minute" }).click();
  await expect(page.getByTestId("replay-cursor")).toHaveText(
    `2 / ${source.total_minutes} min`,
  );
  await page.getByRole("button", { name: "Play replay", exact: true }).click();
  await expect(page.getByTestId("replay-cursor")).not.toHaveText(
    `2 / ${source.total_minutes} min`,
    { timeout: 15000 },
  );
  await page.getByRole("button", { name: "Pause replay", exact: true }).click();
  // Let an in-flight query settle before asserting pause.
  await expect(
    page.getByRole("button", { name: "Play replay", exact: true }),
  ).toBeEnabled();
  const paused = await page.getByTestId("replay-cursor").textContent();
  await page.waitForTimeout(1600);
  expect(await page.getByTestId("replay-cursor").textContent()).toBe(paused);
  await page.getByRole("tab", { name: "Strategy Research" }).click();
  await expect(page.locator(".inactive-panel")).toContainText(
    "Inactive in v0.1",
  );
  await page.getByRole("tab", { name: "Data Explorer" }).click();
  await page.getByRole("button", { name: "Exit", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Start replay" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Previous eligible session" }).click();
  await expect(
    page.getByLabel("Session date", { exact: true }),
  ).not.toHaveValue(session);
  await expect(
    page.getByRole("button", { name: "Start replay" }),
  ).toBeEnabled();
  const chosenDate = await page
    .getByLabel("Session date", { exact: true })
    .inputValue();
  const refreshed = page.waitForResponse(
    (r) => r.url().includes("/api/snapshot?") && r.ok(),
  );
  await page.getByRole("button", { name: "Reload current view" }).click();
  await refreshed;
  await expect(page.getByLabel("Session date", { exact: true })).toHaveValue(
    chosenDate,
  );
  await page.getByLabel("Contract", { exact: true }).selectOption({ index: 1 });
  await expect(
    page.getByRole("button", { name: "Start replay" }),
  ).toBeEnabled();
  await expect(page.locator(".chart-symbol")).not.toContainText(contract);
  await page.getByRole("button", { name: "Dataset & provenance" }).click();
  await expect(page.getByRole("dialog")).toContainText("2,141,265");
  await page.getByRole("button", { name: "Close provenance" }).click();
  expect(errors).toEqual([]);
});
test("responsive layout and honest API error state", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Start replay" })).toBeEnabled({
    timeout: 60000,
  });
  await page.screenshot({
    path: testInfo.outputPath("terminal-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await page.route("**/api/snapshot?**", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Dataset unavailable for test" }),
    }),
  );
  await page.getByRole("button", { name: "15m", exact: true }).click();
  await expect(page.locator(".error-message[role=alert]")).toContainText(
    "Dataset unavailable for test",
  );
  await page.unroute("**/api/snapshot?**");
  await page.getByRole("button", { name: "Retry connection" }).click();
  await expect(
    page.getByRole("button", { name: "Start replay" }),
  ).toBeEnabled();
});
