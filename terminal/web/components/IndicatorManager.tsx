"use client";
import { Indicators } from "@/lib/workspace";
export default function IndicatorManager({
  value,
  onChange,
}: {
  value: Indicators;
  onChange: (v: Indicators) => void;
}) {
  return (
    <details className="indicator-manager">
      <summary>Indicator manager</summary>
      {(["vwap", "levels", "opening", "bands", "boundaries"] as const).map(
        (key, i) => (
          <div key={key} className="indicator-row">
            <label>
              <input
                type="checkbox"
                checked={value[key].visible}
                onChange={(e) =>
                  onChange({
                    ...value,
                    [key]: { ...value[key], visible: e.target.checked },
                  })
                }
              />
              {
                [
                  "Session VWAP",
                  "Previous session H/L",
                  "Opening range",
                  "VWAP deviations",
                  "Session boundaries",
                ][i]
              }
            </label>
            <input
              type="color"
              aria-label={key + " color"}
              value={value[key].color}
              onChange={(e) =>
                onChange({
                  ...value,
                  [key]: { ...value[key], color: e.target.value },
                })
              }
            />
            <select
              aria-label={key + " line style"}
              value={value[key].style}
              onChange={(e) =>
                onChange({
                  ...value,
                  [key]: { ...value[key], style: Number(e.target.value) },
                })
              }
            >
              <option value="0">Solid</option>
              <option value="1">Dotted</option>
              <option value="2">Dashed</option>
            </select>
          </div>
        ),
      )}
      <label>
        Opening range minutes{" "}
        <input
          aria-label="Opening range minutes"
          type="number"
          min="1"
          max="120"
          value={value.openingMinutes}
          onChange={(e) =>
            onChange({
              ...value,
              openingMinutes: Math.min(
                120,
                Math.max(1, Math.round(+e.target.value || 30)),
              ),
            })
          }
        />
      </label>
      <label>
        Band deviations{" "}
        <input
          aria-label="Band deviations"
          type="number"
          min=".25"
          max="5"
          step=".25"
          value={value.deviations}
          onChange={(e) =>
            onChange({
              ...value,
              deviations: Math.min(5, Math.max(0.25, +e.target.value || 1)),
            })
          }
        />
      </label>
    </details>
  );
}
