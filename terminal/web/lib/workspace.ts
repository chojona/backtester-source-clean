export type Indicator = { visible: boolean; color: string; style: 0 | 1 | 2 };
export type Indicators = Record<
  "vwap" | "levels" | "opening" | "bands" | "boundaries",
  Indicator
> & { openingMinutes: number; deviations: number };
export const defaultIndicators: Indicators = {
  vwap: { visible: true, color: "#deb568", style: 0 },
  levels: { visible: true, color: "#657793", style: 2 },
  opening: { visible: true, color: "#779bea", style: 0 },
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
  indicators: Indicators;
};
export const defaultWorkspace: Workspace = {
  contract: "",
  session: "",
  frame: "1m",
  display: "Globex",
  width: 290,
  height: 480,
  bottom: 300,
  analytics: true,
  explorer: true,
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
      (p) => p && Number.isFinite(p.time) && Number.isFinite(p.price),
    ) &&
    Number.isFinite(d.createdAt)
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
    height: number(raw.height, 480, 260, 1000),
    bottom: number(raw.bottom, 300, 180, 900),
    analytics: typeof raw.analytics === "boolean" ? raw.analytics : true,
    explorer: typeof raw.explorer === "boolean" ? raw.explorer : true,
    indicators,
  };
}
