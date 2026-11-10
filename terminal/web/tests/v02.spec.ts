import { test, expect } from "@playwright/test";
import {
  project,
  visibleDrawings,
  Drawing,
  normalizeWorkspace,
} from "../lib/workspace";

test("price/time projection and replay annotation availability", () => {
  const normalized = normalizeWorkspace({
    width: "bad",
    height: 99999,
    indicators: { vwap: null },
  });
  expect(normalized.width).toBe(290);
  expect(normalized.height).toBe(1000);
  expect(normalized.indicators.vwap.color).toBe("#356bff");
  const previousPalette = { vwap: { color: "#deb568" }, levels: { color: "#657793" },
    opening: { color: "#779bea" } };
  expect(normalizeWorkspace({ indicators: previousPalette }).indicators.vwap.color).toBe("#356bff");
  expect(normalizeWorkspace({ indicators: { ...previousPalette, vwap: { color: "#ffff00" } } })
    .indicators.vwap.color).toBe("#ffff00");
  for (const type of [
    "horizontal",
    "ray",
    "trendline",
    "rectangle",
    "fibonacci",
    "range",
  ] as const) {
    const d: Drawing = {
      id: type,
      type,
      points: [
        { time: 100, price: 200 },
        { time: 200, price: 250 },
      ],
      createdAt: 300,
      visible: true,
      color: "#ffffff",
    };
    const saved = JSON.stringify(d);
    expect(
      project(
        d,
        (t) => t * 2,
        (p) => 1000 - p,
      ),
    ).toEqual([
      { x: 200, y: 800 },
      { x: 400, y: 750 },
    ]);
    expect(
      project(
        d,
        (t) => t / 5,
        (p) => 500 - p * 2,
      ),
    ).toEqual([
      { x: 20, y: 100 },
      { x: 40, y: 0 },
    ]);
    expect(JSON.stringify(d)).toBe(saved);
    expect(visibleDrawings([d], 299)).toEqual([]);
    expect(visibleDrawings([d], 300)).toEqual([d]);
  }
});

test("v0.2 real-data workspace, drawings, persistence and causal replay", async ({
  page,
  request,
}, info) => {
  test.skip(process.env.NQ_BROWSER_RELEASE !== "1", "Requires the external sealed source release");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  const start = page.getByRole("button", { name: "Start replay", exact: true });
  await expect(start).toBeEnabled({ timeout: 60000 });
  await page.getByRole("button", { name: "Chart details" }).click();
  const contract = await page
      .getByLabel("Contract", { exact: true })
      .inputValue(),
    session = await page
      .getByLabel("Session date", { exact: true })
      .inputValue();
  const source = await (
    await request.get(`/api/snapshot?contract=${contract}&session=${session}`)
  ).json();
  for (const [label, value] of [
    ["Previous high", source.previous.high],
    ["Previous low", source.previous.low],
  ] as const) {
    await expect(
      page
        .locator(".analytics .metric")
        .filter({ has: page.getByText(label, { exact: true }) })
        .locator("b"),
    ).toHaveText(
      typeof value === "number"
        ? value.toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          })
        : "—",
    );
  }
  const chart = page.getByTestId("market-chart");
  for (const type of [
    "horizontal",
    "ray",
    "trendline",
    "rectangle",
    "fibonacci",
    "range",
  ]) {
    if (type === "horizontal")
      await page.getByRole("button", { name: "Horizontal level", exact: true }).click();
    else await page.getByLabel("Drawing tool", { exact: true }).selectOption(type);
    const b = (await chart.boundingBox())!;
    await page.mouse.click(b.x + b.width * .25, b.y + b.height * .32);
    if (!["horizontal", "ray"].includes(type))
      await page.mouse.click(b.x + b.width * .4, b.y + b.height * .48);
  }
  await expect(page.locator(".drawing-toolbar summary")).toHaveText(
    "Objects (6)",
  );
  const drawings = () =>
    page.evaluate(
      ({ contract }) =>
        JSON.parse(
          localStorage.getItem(Object.keys(localStorage).find(key =>
            key.startsWith("nq:v3:drawings:") && key.includes(contract) && key.includes("Globex"))!) || "{}",
        ).drawings ?? [],
      { contract },
    );
  const saved = await drawings();
  expect(saved).toHaveLength(6);
  await page.locator(".drawing-toolbar summary").click();
  await page.getByRole("button", { name: "trendline", exact: true }).click();
  const editor = page.getByLabel("Anchor 1 price", { exact: true });
  await editor.fill(
    String(
      saved.find((d: Drawing) => d.type === "trendline").points[0].price + 0.25,
    ),
  );
  await editor.blur();
  await page.getByRole("button", { name: "Toggle ray", exact: true }).click();
  await page
    .getByRole("button", { name: "Delete rectangle", exact: true })
    .click();
  const edited = await drawings();
  expect(edited).toHaveLength(5);
  expect(edited.find((d: Drawing) => d.type === "ray").visible).toBe(false);
  await page.locator(".drawing-toolbar summary").click();
  await page.getByRole("button", { name: "15m", exact: true }).click();
  await expect(page.locator(".chart-symbol")).toContainText("15m");
  expect(await drawings()).toEqual(edited);
  const b = (await chart.boundingBox())!;
  await page.mouse.move(b.x + b.width / 2, b.y + b.height * .32);
  await page.mouse.wheel(0, -200);
  await page.waitForTimeout(200);
  expect(await drawings()).toEqual(edited);
  const range = await page.evaluate(() =>
    localStorage.getItem(
      Object.keys(localStorage).find(
        (k) => k.startsWith("nq:v3:view:") && k.endsWith("/15m"),
      )!,
    ),
  );
  for (const [name, dx, dy] of [
    ["Resize analytics", -50, 0],
    ["Resize chart", 0, 55],
  ] as const) {
    const box = (await page.getByRole("separator", { name }).boundingBox())!;
    await page.mouse.move(box.x + 2, box.y + 2);
    await page.mouse.down();
    await page.mouse.move(box.x + 2 + dx, box.y + 2 + dy);
    await page.mouse.up();
  }
  expect(await drawings()).toEqual(edited);
  expect(
    await page.evaluate(() =>
      localStorage.getItem(
        Object.keys(localStorage).find(
          (k) => k.startsWith("nq:v3:view:") && k.endsWith("/15m"),
        )!,
      ),
    ),
  ).toBe(range);
  await page.getByRole("separator", { name: "Resize workspace" }).focus();
  await page.keyboard.press("ArrowDown");
  expect(
    await page
      .getByRole("button", { name: "15m", exact: true })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  await page.locator(".indicator-manager summary").click();
  await page.getByLabel("Band deviations", { exact: true }).fill("2");
  await page.getByLabel("Opening range minutes", { exact: true }).fill("15");
  await expect(start).toBeEnabled();
  await page.screenshot({
    path: info.outputPath("v02-workspace.png"),
    fullPage: true,
  });
  await page.reload();
  await expect(start).toBeEnabled();
  await page.getByRole("button", { name: "Chart details" }).click();
  await expect(page.getByLabel("Contract", { exact: true })).toHaveValue(
    contract,
  );
  await expect(page.getByLabel("Session date", { exact: true })).toHaveValue(
    session,
  );
  await expect(
    page.getByRole("button", { name: "15m", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".drawing-toolbar summary")).toHaveText(
    "Objects (5)",
  );
  await page.getByLabel("Session display", { exact: true }).selectOption("RTH");
  await expect(start).toBeEnabled();
  await expect(page.locator(".drawing-toolbar summary")).toHaveText(
    "Objects (0)",
  );
  await page.getByRole("button", { name: "D", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await page
    .getByLabel("Session display", { exact: true })
    .selectOption("Globex");
  await page.getByRole("button", { name: "5m", exact: true }).click();
  await expect(start).toBeEnabled();
  await start.click();
  await expect(page.getByTestId("replay-cursor")).toHaveText(
    `1 / ${source.total_minutes} min`,
  );
  await expect(page.locator(".drawing-toolbar summary")).toHaveText(
    "Objects (0)",
  );
  await page
    .getByRole("button", { name: "Step forward one bar", exact: true })
    .click();
  await expect(page.getByTestId("replay-cursor")).toHaveText(
    `6 / ${source.total_minutes} min`,
  );
  await page.getByLabel("Jump to session time", { exact: true }).fill("09:45");
  await page.getByRole("button", { name: "Jump", exact: true }).click();
  const jump = await (
    await request.get(
      `/api/replay-time?contract=${contract}&session=${session}&time=09:45`,
    )
  ).json();
  await expect(page.getByTestId("replay-cursor")).toHaveText(
    `${jump.cursor} / ${source.total_minutes} min`,
  );
  await expect(page.locator(".asof")).toContainText("09:45");
  await expect
    .poll(async () => {
      const raw = await page.evaluate(
        ({ contract, session }) =>
          localStorage.getItem(Object.keys(localStorage).find(key =>
            key.startsWith("nq:v3:view:") && key.includes(contract) && key.includes(session) &&
            key.includes('true,') && key.endsWith("/5m"))!),
        { contract, session },
      );
      if (!raw) return false;
      const range = JSON.parse(raw);
      return (
        range.to >= source.bars[jump.cursor - 1].time - 15 * 60 &&
        range.to <= source.bars[jump.cursor - 1].time &&
        range.from > source.bars[0].time
      );
    })
    .toBe(true);
  const cutoff = await (
    await request.get(
      `/api/snapshot?contract=${contract}&session=${session}&timeframe=5m&cursor=${jump.cursor}&opening_minutes=15&deviations=2`,
    )
  ).json();
  expect(
    cutoff.bars.every(
      (b: { available_at: number }) =>
        b.available_at <= Date.parse(cutoff.as_of) / 1000,
    ),
  ).toBe(true);
  const last = cutoff.bars.at(-1);
  await expect(page.locator("tbody tr").last()).toContainText(
    last.close.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }),
  );
  await page.getByLabel("Drawing tool").selectOption("horizontal");
  const rb = (await chart.boundingBox())!;
  await page.mouse.click(rb.x + rb.width * .25, rb.y + rb.height * .32);
  await expect(page.locator(".drawing-toolbar summary")).toHaveText(
    "Objects (1)",
  );
  await page.getByLabel("Jump to session time").fill("09:40");
  await page.getByRole("button", { name: "Jump", exact: true }).click();
  await expect(page.locator(".asof")).toContainText("09:40");
  await expect(page.locator(".drawing-toolbar summary")).toHaveText(
    "Objects (0)",
  );
  for (const speed of ["1", "2", "5", "10"])
    await page.getByLabel("Replay speed").selectOption(speed);
  await page.locator("h1").click();
  await page.keyboard.press("ArrowRight");
  await expect(page.locator(".asof")).toContainText("09:45");
  await page.keyboard.press("Space");
  await expect(
    page.getByRole("button", { name: "Pause replay" }),
  ).toBeVisible();
  await page.keyboard.press("Space");
  await page.screenshot({
    path: info.outputPath("v02-replay.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Chart fullscreen" }).click();
  await expect
    .poll(() => page.evaluate(() => document.fullscreenElement?.classList.contains("chart-panel")))
    .toBe(true);
  await page.screenshot({ path: info.outputPath("v02-fullscreen.png") });
  await page.getByRole("button", { name: "Chart fullscreen" }).click();
  await page.getByRole("button", { name: "Analytics", exact: true }).click();
  await page.getByRole("button", { name: "Workspace", exact: true }).click();
  await page.reload();
  await expect(start).toBeEnabled();
  await expect(page.locator(".analytics-container")).toBeHidden();
  await expect(page.locator(".bottom-workspace")).toBeHidden();
  expect(errors).toEqual([]);
});

test("unavailable local storage keeps real-data terminal usable", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Storage.prototype.setItem = function () {
      throw new Error("Storage disabled for verification");
    };
  });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Start replay", exact: true }),
  ).toBeEnabled({ timeout: 60000 });
  await expect(page.locator(".workspace-actions")).toContainText(
    "Local storage unavailable",
  );
  expect(errors).toEqual([]);
});
