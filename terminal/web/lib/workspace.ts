export type Indicator = { visible: boolean; color: string; style: 0 | 1 | 2 };
export type Indicators = Record<
  "vwap" | "levels" | "opening" | "bands" | "boundaries",
  Indicator
> & { openingMinutes: number; deviations: number };
export const defaultIndicators: Indicators = {
  vwap: { visible: true, color: "#356bff", style: 0 },
  levels: { visible: true, color: "#b4d6f4", style: 0 },
  opening: { visible: true, color: "#93bde5", style: 0 },
  bands: { visible: false, color: "#65a89a", style: 2 },
  boundaries: { visible: true, color: "#465675", style: 2 },
  openingMinutes: 30,
  deviations: 1,
};
export type Workspace = {
  contract: string;
  session: string;
  frame: string;
  display: "Globex" | "RTH";
  width: number;
  height: number;
  bottom: number;
  analytics: boolean;
  explorer: boolean;
  fullscreen: boolean;
  historySessions: number;
  indicators: Indicators;
};
export const defaultWorkspace: Workspace = {
  contract: "",
  session: "",
  frame: "1m",
  display: "Globex",
  width: 290,
  height: 620,
  bottom: 300,
  analytics: true,
  explorer: true,
  fullscreen: false,
  historySessions: 20,
  indicators: defaultIndicators,
};
export function readLocal<T>(key: string, fallback: T): T {
  try {
    return JSON.parse(localStorage.getItem(key) || "null") ?? fallback;
  } catch {
    return fallback;
  }
}
export function writeLocal(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}
export type Anchor = { time: number; price: number };
export type Drawing = {
  id: string;
  type:
    | "horizontal"
    | "ray"
    | "trendline"
    | "rectangle"
    | "fibonacci"
    | "range";
  points: [Anchor, Anchor];
  createdAt: number;
  adjustmentBlock?: number;
  visible: boolean;
  color: string;
};
export function validDrawing(d: Drawing) {
  return (
    d &&
    typeof d.id === "string" &&
    [
      "horizontal",
      "ray",
      "trendline",
      "rectangle",
      "fibonacci",
      "range",
    ].includes(d.type) &&
    Array.isArray(d.points) &&
    d.points.length === 2 &&
    d.points.every(
      (p) => p && Number.isFinite(p.time) && Math.abs(p.time) <= 8.64e12 && Number.isFinite(p.price),
    ) &&
    Number.isFinite(d.createdAt) && typeof d.visible === "boolean" &&
    typeof d.color === "string" && /^#[\da-f]{6}$/i.test(d.color) &&
    (d.adjustmentBlock === undefined || Number.isInteger(d.adjustmentBlock))
  );
}
export function visibleDrawings(drawings: Drawing[], asOf: number) {
  return drawings.filter(
    (d) =>
      validDrawing(d) &&
      d.createdAt <= asOf &&
      d.points.every((p) => p.time <= asOf),
  );
}
export function project(
  d: Drawing,
  time: (t: number) => number | null,
  price: (p: number) => number | null,
) {
  return d.points.map((p) => ({ x: time(p.time), y: price(p.price) }));
}

export function normalizeWorkspace(input: unknown): Workspace {
  const raw = (
    input && typeof input === "object" ? input : {}
  ) as Partial<Workspace>;
  const number = (
    value: unknown,
    fallback: number,
    min: number,
    max: number,
  ) =>
    typeof value === "number" && Number.isFinite(value)
      ? Math.max(min, Math.min(max, value))
      : fallback;
  const indicators = { ...defaultIndicators };
  for (const key of [
    "vwap",
    "levels",
    "opening",
    "bands",
    "boundaries",
  ] as const) {
    const v = raw.indicators?.[key];
    indicators[key] = {
      visible:
        typeof v?.visible === "boolean"
          ? v.visible
          : defaultIndicators[key].visible,
      color:
        typeof v?.color === "string" && /^#[\da-f]{6}$/i.test(v.color)
          ? v.color
          : defaultIndicators[key].color,
      style:
        v && [0, 1, 2].includes(v.style)
          ? v.style
          : defaultIndicators[key].style,
    };
  }
  // Recognize the old stock palette as a group so saved custom palettes survive.
  if (indicators.vwap.color === "#deb568" && indicators.levels.color === "#657793" &&
      indicators.opening.color === "#779bea") {
    indicators.vwap.color = defaultIndicators.vwap.color;
    indicators.levels.color = defaultIndicators.levels.color;
    indicators.opening.color = defaultIndicators.opening.color;
    if (indicators.levels.style === 2) indicators.levels.style = defaultIndicators.levels.style;
  }
  indicators.openingMinutes = Math.round(
    number(raw.indicators?.openingMinutes, 30, 1, 120),
  );
  indicators.deviations = number(raw.indicators?.deviations, 1, 0.25, 5);
  return {
    ...defaultWorkspace,
    contract: typeof raw.contract === "string" ? raw.contract : "",
    session: typeof raw.session === "string" ? raw.session : "",
    frame: ["1m", "5m", "15m", "30m", "1h", "daily"].includes(raw.frame || "")
      ? raw.frame!
      : "1m",
    display: raw.display === "RTH" ? "RTH" : "Globex",
    width: number(raw.width, 290, 240, 600),
    height: number(raw.height, defaultWorkspace.height, 260, 1000),
    bottom: number(raw.bottom, 300, 180, 900),
    analytics: typeof raw.analytics === "boolean" ? raw.analytics : true,
    explorer: typeof raw.explorer === "boolean" ? raw.explorer : true,
    fullscreen: raw.fullscreen === true,
    historySessions: [1, 20, 120, 5000].includes(raw.historySessions ?? 0) ? raw.historySessions! : 20,
    indicators,
  };
}

export function readWorkspace() {
  const saved = readLocal<{ version: number; workspace: unknown } | null>("nq:v3:workspace", null);
  return normalizeWorkspace(saved?.version === 3 ? saved.workspace : readLocal("nq:v2:workspace", null));
}

export function writeWorkspace(workspace: Workspace) {
  return writeLocal("nq:v3:workspace", { version: 3, workspace });
}

export function readDrawings(key: string, legacyPrefix: string | null, display: string): Drawing[] {
  const stored = readLocal<{ version: number; drawings: unknown } | null>(key, null);
  if (stored?.version === 3)
    return Array.isArray(stored.drawings) ? stored.drawings.filter(validDrawing) : [];
  if (!legacyPrefix) return [];
  try {
    const drawings = new Map<string, Drawing>();
    for (const name of Object.keys(localStorage)) {
      if (!name.startsWith(legacyPrefix) || !name.endsWith(":" + display)) continue;
      const old = readLocal<Drawing[]>(name, []);
      if (Array.isArray(old)) for (const drawing of old.filter(validDrawing)) drawings.set(drawing.id, drawing);
    }
    const migrated = [...drawings.values()];
    if (migrated.length) writeDrawings(key, migrated);
    return migrated;
  } catch {
    return [];
  }
}

export function writeDrawings(key: string, drawings: Drawing[]) {
  return writeLocal(key, { version: 3, drawings });
}
