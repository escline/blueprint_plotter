import type { Orientation, ViewName } from "./api";

export interface Pen {
  name: string;
  role: string;
  width: number; // mm, preview only
  color: string; // preview only
}

export interface Settings {
  views: ViewName[];
  angle: number;
  resolution: number;
  hidden: boolean;
  hiddenSilhouettes: boolean;
  dims: boolean;
  page: string;
  margin: number;
  scale: string;
  pens: [Pen, Pen, Pen];
}

export const DEFAULT_PENS: Settings["pens"] = [
  { name: "Pen 1", role: "Outlines", width: 0.5, color: "#14181b" },
  { name: "Pen 2", role: "Hidden lines", width: 0.3, color: "#2b6cb0" },
  { name: "Pen 3", role: "Dimensions and title", width: 0.3, color: "#b8322a" },
];

export const DEFAULT_SETTINGS: Settings = {
  views: ["front", "top", "right", "iso"],
  angle: 30,
  resolution: 2000,
  hidden: true,
  hiddenSilhouettes: true,
  dims: true,
  page: "a3",
  margin: 10,
  scale: "auto",
  pens: DEFAULT_PENS,
};

export const DEFAULT_ORIENTATION: Orientation = { up: "z", steps: [], model_scale: 1 };

export const PAGES: { value: string; label: string }[] = [
  { value: "a3", label: "A3 (420 × 297 mm)" },
  { value: "a4", label: "A4 (297 × 210 mm)" },
  { value: "a2", label: "A2 (594 × 420 mm)" },
  { value: "tabloid", label: "Tabloid (432 × 279 mm)" },
  { value: "letter", label: "Letter (279 × 216 mm)" },
];

export const SCALE_PRESETS = ["auto", "fit", "1:1", "1:2", "1:5", "1:10", "2:1", "5:1"];

export const UNITS: { value: number; label: string }[] = [
  { value: 1, label: "Millimetres" },
  { value: 10, label: "Centimetres" },
  { value: 25.4, label: "Inches" },
  { value: 1000, label: "Metres" },
];

export const PEN_WIDTHS = [0.2, 0.3, 0.4, 0.5, 0.7, 1.0];

const KEY = "blueprint-plotter.settings.v1";

export function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const saved = JSON.parse(raw) as Partial<Settings>;
    return { ...DEFAULT_SETTINGS, ...saved, pens: saved.pens?.length === 3 ? saved.pens : DEFAULT_PENS } as Settings;
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(s: Settings): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* storage can be unavailable; settings just won't persist */
  }
}
