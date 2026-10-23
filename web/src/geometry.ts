// Pure helpers for the sheet editor. Sheet space is millimetres, origin bottom-left, y up
// (the same space the server uses). Screen space is CSS pixels, y down.

export type Vec = [number, number];
export type Box = [number, number, number, number]; // x0, y0, x1, y1

export interface Viewport {
  z: number; // pixels per mm
  ox: number; // screen x of sheet x = 0
  oy: number; // screen y of the sheet's TOP edge (sheet y = pageH)
}

export const sheetToScreen = (vp: Viewport, pageH: number, p: Vec): Vec => [
  vp.ox + p[0] * vp.z,
  vp.oy + (pageH - p[1]) * vp.z,
];

export const screenToSheet = (vp: Viewport, pageH: number, p: Vec): Vec => [
  (p[0] - vp.ox) / vp.z,
  pageH - (p[1] - vp.oy) / vp.z,
];

/** Fit the page inside an area, leaving `inset` px on each side (room for rulers). */
export function fitViewport(
  area: { w: number; h: number },
  page: Vec,
  inset: { left: number; top: number; right: number; bottom: number },
  pad = 24,
): Viewport {
  const availW = Math.max(area.w - inset.left - inset.right - 2 * pad, 50);
  const availH = Math.max(area.h - inset.top - inset.bottom - 2 * pad, 50);
  const z = Math.min(availW / page[0], availH / page[1]);
  const ox = inset.left + pad + (availW - page[0] * z) / 2;
  const oy = inset.top + pad + (availH - page[1] * z) / 2;
  return { z, ox, oy };
}

/** Zoom keeping the sheet point under `anchor` (screen px) fixed. */
export function zoomAt(vp: Viewport, anchor: Vec, factor: number, min = 0.4, max = 60): Viewport {
  const z = Math.min(Math.max(vp.z * factor, min), max);
  const k = z / vp.z;
  return { z, ox: anchor[0] - (anchor[0] - vp.ox) * k, oy: anchor[1] - (anchor[1] - vp.oy) * k };
}

export interface Placed {
  name: string;
  center: Vec;
  box: Box; // extent of the view's drawing relative to its centre
}

export const worldBox = (p: Placed): Box => [
  p.center[0] + p.box[0],
  p.center[1] + p.box[1],
  p.center[0] + p.box[2],
  p.center[1] + p.box[3],
];

/** Topmost view under a sheet point; among overlapping boxes prefers the smallest. */
export function hitTest(views: Placed[], pt: Vec): string | null {
  let best: { name: string; area: number } | null = null;
  for (const v of views) {
    const [x0, y0, x1, y1] = worldBox(v);
    if (pt[0] >= x0 && pt[0] <= x1 && pt[1] >= y0 && pt[1] <= y1) {
      const area = (x1 - x0) * (y1 - y0);
      if (!best || area <= best.area) best = { name: v.name, area };
    }
  }
  return best ? best.name : null;
}

export interface Snap {
  center: Vec;
  guideX: number | null; // sheet x of a vertical alignment guide
  guideY: number | null;
}

/** Snap a dragged view's centre to other views' centres (aligns top over front, right beside front…). */
export function snapCenter(moving: string, wanted: Vec, views: Placed[], thresholdMm: number): Snap {
  let [x, y] = wanted;
  let guideX: number | null = null;
  let guideY: number | null = null;
  let bestDx = thresholdMm;
  let bestDy = thresholdMm;
  for (const v of views) {
    if (v.name === moving) continue;
    const dx = Math.abs(wanted[0] - v.center[0]);
    const dy = Math.abs(wanted[1] - v.center[1]);
    if (dx < bestDx) {
      bestDx = dx;
      x = v.center[0];
      guideX = v.center[0];
    }
    if (dy < bestDy) {
      bestDy = dy;
      y = v.center[1];
      guideY = v.center[1];
    }
  }
  return { center: [x, y], guideX, guideY };
}

/** Tick spacing (mm) giving roughly `targetPx` between labelled ticks. */
export function niceTick(pxPerMm: number, targetPx = 70): number {
  const raw = targetPx / pxPerMm;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const m of [1, 2, 5, 10]) if (m * pow >= raw) return m * pow;
  return 10 * pow;
}

export const fmt = (v: number, places = 1): string => {
  const s = v.toFixed(places);
  return s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s;
};
