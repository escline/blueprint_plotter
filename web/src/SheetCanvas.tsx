import { useEffect, useMemo, useRef } from "react";
import type { ComposeResponse, Polylines } from "./api";
import {
  fitViewport,
  fmt,
  hitTest,
  niceTick,
  screenToSheet,
  snapCenter,
  worldBox,
  zoomAt,
  type Placed,
  type Vec,
  type Viewport,
} from "./geometry";
import type { Settings } from "./settings";

const RULER = 20; // px

// Palette lives in CSS variables; the canvas reads them once so the two never drift apart.
interface Palette {
  mat: string;
  matLine: string;
  matLineStrong: string;
  paper: string;
  chrome: string;
  rule: string;
  ink2: string;
  accent: string;
}

function readPalette(): Palette {
  const cs = getComputedStyle(document.documentElement);
  const v = (n: string) => cs.getPropertyValue(n).trim();
  return {
    mat: v("--mat"),
    matLine: v("--mat-line"),
    matLineStrong: v("--mat-line-strong"),
    paper: v("--paper"),
    chrome: v("--chrome"),
    rule: v("--rule"),
    ink2: v("--ink-2"),
    accent: v("--accent"),
  };
}

function toPath(polys: Polylines): Path2D {
  const p = new Path2D();
  for (const a of polys) {
    if (a.length < 4) continue;
    p.moveTo(a[0], a[1]);
    for (let i = 2; i < a.length; i += 2) p.lineTo(a[i], a[i + 1]);
  }
  return p;
}

interface ViewPaths {
  visible: Path2D;
  hidden: Path2D;
  notes: Path2D;
}

type Drag =
  | { kind: "view"; name: string; startSheet: Vec; startCenter: Vec }
  | { kind: "pan"; startPt: Vec; startVp: Viewport }
  | null;

export interface SheetCanvasProps {
  result: ComposeResponse | null;
  pageSize: Vec;
  centers: Record<string, Vec>;
  pens: Settings["pens"];
  selected: string | null;
  fitSignal: number;
  onSelect: (name: string | null) => void;
  onMove: (name: string, center: Vec) => void;
}

export function SheetCanvas(props: SheetCanvasProps) {
  const { result, pageSize, centers, pens, selected, fitSignal } = props;
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // mutable interaction state: kept out of React so pointer-move never re-renders the app
  const vpRef = useRef<Viewport>({ z: 2, ox: 60, oy: 60 });
  const sizeRef = useRef({ w: 800, h: 600 });
  const userMoved = useRef(false);
  const dragRef = useRef<Drag>(null);
  const hoverRef = useRef<string | null>(null);
  const pointerRef = useRef<Vec | null>(null);
  const guidesRef = useRef<{ x: number | null; y: number | null }>({ x: null, y: null });
  const paletteRef = useRef<Palette | null>(null);
  const rafRef = useRef(0);

  const propsRef = useRef(props);
  propsRef.current = props;

  const paths = useMemo(() => {
    const m = new Map<string, ViewPaths>();
    if (!result) return { views: m, frame: new Path2D() };
    for (const [name, v] of Object.entries(result.views)) {
      m.set(name, { visible: toPath(v.visible), hidden: toPath(v.hidden), notes: toPath(v.notes) });
    }
    return { views: m, frame: toPath(result.frame) };
  }, [result]);
  const pathsRef = useRef(paths);
  pathsRef.current = paths;

  const placed = (): Placed[] => {
    const r = propsRef.current.result;
    if (!r) return [];
    return Object.entries(r.views).map(([name, v]) => ({
      name,
      center: propsRef.current.centers[name] ?? v.center,
      box: v.box,
    }));
  };

  // ---------------------------------------------------------------------------------------------
  // drawing
  // ---------------------------------------------------------------------------------------------
  const draw = () => {
    rafRef.current = 0;
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const pal = (paletteRef.current ??= readPalette());
    const { result: res, pageSize: page, pens: pn, selected: sel } = propsRef.current;
    const { w, h } = sizeRef.current;
    const dpr = window.devicePixelRatio || 1;
    const vp = vpRef.current;
    const [PW, PH] = res?.page ?? page;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = pal.mat;
    ctx.fillRect(0, 0, w, h);

    // cutting-mat grid, anchored to the sheet origin so it lines up with the paper edge
    {
      const x0 = (0 - vp.ox) / vp.z;
      const x1 = (w - vp.ox) / vp.z;
      const yTop = PH - (0 - vp.oy) / vp.z;
      const yBot = PH - (h - vp.oy) / vp.z;
      const minor = vp.z >= 1.4;
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let x = Math.floor(x0 / 10) * 10; x <= x1; x += 10) {
        const strong = x % 50 === 0;
        if (!strong && !minor) continue;
        const sx = Math.round(vp.ox + x * vp.z) + 0.5;
        ctx.strokeStyle = strong ? pal.matLineStrong : pal.matLine;
        ctx.beginPath();
        ctx.moveTo(sx, 0);
        ctx.lineTo(sx, h);
        ctx.stroke();
      }
      for (let y = Math.floor(yBot / 10) * 10; y <= yTop; y += 10) {
        const strong = y % 50 === 0;
        if (!strong && !minor) continue;
        const sy = Math.round(vp.oy + (PH - y) * vp.z) + 0.5;
        ctx.strokeStyle = strong ? pal.matLineStrong : pal.matLine;
        ctx.beginPath();
        ctx.moveTo(0, sy);
        ctx.lineTo(w, sy);
        ctx.stroke();
      }
    }

    // paper
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,0.38)";
    ctx.shadowBlur = 20;
    ctx.shadowOffsetY = 5;
    ctx.fillStyle = pal.paper;
    ctx.fillRect(vp.ox, vp.oy, PW * vp.z, PH * vp.z);
    ctx.restore();

    ctx.save();
    ctx.beginPath();
    ctx.rect(vp.ox, vp.oy, PW * vp.z, PH * vp.z);
    ctx.clip();

    const px = 0.8 / vp.z; // never thinner than ~1 device-ish pixel, however far out we zoom
    const setSheet = (cx: number, cy: number) =>
      ctx.setTransform(dpr * vp.z, 0, 0, -dpr * vp.z, dpr * (vp.ox + cx * vp.z), dpr * (vp.oy + (PH - cy) * vp.z));
    const stroke = (p: Path2D, pen: { width: number; color: string }, dash?: number[]) => {
      ctx.lineWidth = Math.max(pen.width, px);
      ctx.strokeStyle = pen.color;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.setLineDash(dash ?? []);
      ctx.stroke(p);
    };

    if (res) {
      setSheet(0, 0);
      stroke(pathsRef.current.frame, pn[2]);
      for (const [name, v] of Object.entries(res.views)) {
        const c = propsRef.current.centers[name] ?? v.center;
        const vpaths = pathsRef.current.views.get(name);
        if (!vpaths) continue;
        setSheet(c[0], c[1]);
        stroke(vpaths.hidden, pn[1], res.dash);
        stroke(vpaths.visible, pn[0]);
        stroke(vpaths.notes, pn[2]);
      }
    }
    ctx.restore();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.setLineDash([]);

    // alignment guides while dragging
    const g = guidesRef.current;
    ctx.strokeStyle = pal.accent;
    ctx.lineWidth = 1;
    ctx.setLineDash([5, 4]);
    if (g.x !== null) {
      const sx = Math.round(vp.ox + g.x * vp.z) + 0.5;
      ctx.beginPath();
      ctx.moveTo(sx, vp.oy);
      ctx.lineTo(sx, vp.oy + PH * vp.z);
      ctx.stroke();
    }
    if (g.y !== null) {
      const sy = Math.round(vp.oy + (PH - g.y) * vp.z) + 0.5;
      ctx.beginPath();
      ctx.moveTo(vp.ox, sy);
      ctx.lineTo(vp.ox + PW * vp.z, sy);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    // selection / hover outline + view label
    const outline = (name: string, solid: boolean) => {
      const p = placed().find((q) => q.name === name);
      if (!p) return;
      const [bx0, by0, bx1, by1] = worldBox(p);
      const sx0 = vp.ox + bx0 * vp.z - 4;
      const sx1 = vp.ox + bx1 * vp.z + 4;
      const sy0 = vp.oy + (PH - by1) * vp.z - 4;
      const sy1 = vp.oy + (PH - by0) * vp.z + 4;
      ctx.strokeStyle = pal.accent;
      ctx.lineWidth = solid ? 1.5 : 1;
      ctx.setLineDash(solid ? [] : [4, 3]);
      ctx.strokeRect(sx0, sy0, sx1 - sx0, sy1 - sy0);
      ctx.setLineDash([]);
      const label = name[0].toUpperCase() + name.slice(1);
      ctx.font = "600 12px 'Barlow Semi Condensed', system-ui, sans-serif";
      const tw = ctx.measureText(label).width;
      ctx.fillStyle = pal.accent;
      ctx.fillRect(sx0, sy0 - 17, tw + 12, 17);
      ctx.fillStyle = "#fff";
      ctx.textBaseline = "middle";
      ctx.fillText(label, sx0 + 6, sy0 - 8.5);
    };
    if (hoverRef.current && hoverRef.current !== sel && !dragRef.current) outline(hoverRef.current, false);
    if (sel) outline(sel, true);

    drawRulers(ctx, pal, vp, PW, PH, w, h, pointerRef.current);
  };

  const schedule = () => {
    if (!rafRef.current) rafRef.current = requestAnimationFrame(draw);
  };

  // ---------------------------------------------------------------------------------------------
  // sizing + fit
  // ---------------------------------------------------------------------------------------------
  const fit = () => {
    const { w, h } = sizeRef.current;
    const page = propsRef.current.result?.page ?? propsRef.current.pageSize;
    vpRef.current = fitViewport({ w, h }, page, { left: RULER, top: RULER, right: 0, bottom: 0 });
    userMoved.current = false;
    schedule();
  };

  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas) return;
    const resize = () => {
      const r = wrap.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      sizeRef.current = { w: r.width, h: r.height };
      canvas.width = Math.max(1, Math.round(r.width * dpr));
      canvas.height = Math.max(1, Math.round(r.height * dpr));
      canvas.style.width = `${r.width}px`;
      canvas.style.height = `${r.height}px`;
      if (!userMoved.current) fit();
      else schedule();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);
    resize();
    document.fonts?.ready.then(schedule);
    return () => {
      ro.disconnect();
      cancelAnimationFrame(rafRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // wheel needs a non-passive listener to stop the page from scrolling
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = canvas.getBoundingClientRect();
      const anchor: Vec = [e.clientX - r.left, e.clientY - r.top];
      const factor = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015));
      vpRef.current = zoomAt(vpRef.current, anchor, factor);
      userMoved.current = true;
      schedule();
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, []);

  // refit when the page changes or the parent asks; redraw on any data change
  const pageKey = (result?.page ?? pageSize).join("x");
  useEffect(fit, [pageKey, fitSignal]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(schedule, [result, centers, pens, selected, paths]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------------------------------------
  // pointer + keyboard
  // ---------------------------------------------------------------------------------------------
  const local = (e: React.PointerEvent | React.MouseEvent): Vec => {
    const r = canvasRef.current!.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  };
  const pageH = () => propsRef.current.result?.page[1] ?? propsRef.current.pageSize[1];

  const onPointerDown = (e: React.PointerEvent) => {
    const pt = local(e);
    if (pt[0] < RULER || pt[1] < RULER) return;
    try {
      canvasRef.current!.setPointerCapture(e.pointerId);
    } catch {
      /* capture can be refused for synthetic/inactive pointers; dragging still works without it */
    }
    canvasRef.current!.focus();
    const sheet = screenToSheet(vpRef.current, pageH(), pt);
    const hit = e.button === 0 && !e.shiftKey ? hitTest(placed(), sheet) : null;
    if (hit) {
      propsRef.current.onSelect(hit);
      const c = propsRef.current.centers[hit] ?? propsRef.current.result!.views[hit].center;
      dragRef.current = { kind: "view", name: hit, startSheet: sheet, startCenter: [c[0], c[1]] };
    } else {
      if (e.button === 0) propsRef.current.onSelect(null);
      dragRef.current = { kind: "pan", startPt: pt, startVp: { ...vpRef.current } };
    }
    schedule();
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const pt = local(e);
    pointerRef.current = pt;
    const d = dragRef.current;
    const canvas = canvasRef.current!;
    if (d?.kind === "view") {
      const sheet = screenToSheet(vpRef.current, pageH(), pt);
      const wanted: Vec = [d.startCenter[0] + sheet[0] - d.startSheet[0], d.startCenter[1] + sheet[1] - d.startSheet[1]];
      if (e.altKey) {
        guidesRef.current = { x: null, y: null };
        propsRef.current.onMove(d.name, wanted);
      } else {
        const s = snapCenter(d.name, wanted, placed(), 7 / vpRef.current.z);
        guidesRef.current = { x: s.guideX, y: s.guideY };
        propsRef.current.onMove(d.name, s.center);
      }
      canvas.style.cursor = "grabbing";
    } else if (d?.kind === "pan") {
      vpRef.current = { ...d.startVp, ox: d.startVp.ox + pt[0] - d.startPt[0], oy: d.startVp.oy + pt[1] - d.startPt[1] };
      userMoved.current = true;
      canvas.style.cursor = "grabbing";
    } else {
      const hit = pt[0] < RULER || pt[1] < RULER ? null : hitTest(placed(), screenToSheet(vpRef.current, pageH(), pt));
      if (hit !== hoverRef.current) hoverRef.current = hit;
      canvas.style.cursor = hit ? "grab" : "default";
    }
    schedule();
  };

  const endDrag = () => {
    dragRef.current = null;
    guidesRef.current = { x: null, y: null };
    schedule();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const sel = propsRef.current.selected;
    const arrows: Record<string, Vec> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] };
    if (sel && arrows[e.key]) {
      e.preventDefault();
      const step = e.shiftKey ? 10 : 1;
      const c = propsRef.current.centers[sel] ?? propsRef.current.result!.views[sel].center;
      propsRef.current.onMove(sel, [c[0] + arrows[e.key][0] * step, c[1] + arrows[e.key][1] * step]);
    } else if (e.key === "Escape") {
      propsRef.current.onSelect(null);
    } else if (e.key === "f" || e.key === "0") {
      fit();
    } else if (e.key === "+" || e.key === "=" || e.key === "-") {
      const { w, h } = sizeRef.current;
      vpRef.current = zoomAt(vpRef.current, [w / 2, h / 2], e.key === "-" ? 1 / 1.25 : 1.25);
      userMoved.current = true;
      schedule();
    }
  };

  return (
    <div className="canvas-wrap" ref={wrapRef}>
      <canvas
        ref={canvasRef}
        tabIndex={0}
        role="application"
        aria-label="Sheet preview. Drag a view to move it, or select it and use the arrow keys. Scroll to zoom, drag the background to pan, press F to fit."
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onPointerLeave={() => {
          pointerRef.current = null;
          hoverRef.current = null;
          schedule();
        }}
        onDoubleClick={(e) => {
          const pt = local(e);
          if (!hitTest(placed(), screenToSheet(vpRef.current, pageH(), pt))) fit();
        }}
        onKeyDown={onKeyDown}
      />
      <Readout pointerRef={pointerRef} vpRef={vpRef} pageH={pageH} />
    </div>
  );
}

// Live "x / y mm" readout in machine coordinates (origin top-left, y down) - the numbers you
// need when registering paper on the plotter bed.
function Readout({
  pointerRef,
  vpRef,
  pageH,
}: {
  pointerRef: React.MutableRefObject<Vec | null>;
  vpRef: React.MutableRefObject<Viewport>;
  pageH: () => number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const p = pointerRef.current;
      if (ref.current) {
        if (p) {
          const s = screenToSheet(vpRef.current, pageH(), p);
          ref.current.textContent = `${fmt(s[0])}, ${fmt(pageH() - s[1])} mm`;
        } else ref.current.textContent = "";
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [pointerRef, vpRef, pageH]);
  return <div className="readout" ref={ref} aria-hidden="true" />;
}

function drawRulers(
  ctx: CanvasRenderingContext2D,
  pal: Palette,
  vp: Viewport,
  PW: number,
  PH: number,
  w: number,
  h: number,
  pointer: Vec | null,
) {
  ctx.font = "500 10px 'Barlow Semi Condensed', system-ui, sans-serif";
  ctx.textBaseline = "alphabetic";
  const step = niceTick(vp.z, 64);
  const mant = step / Math.pow(10, Math.floor(Math.log10(step)));
  const minor = step / (Math.round(mant) === 2 ? 4 : 5);

  ctx.fillStyle = pal.chrome;
  ctx.fillRect(0, 0, w, RULER);
  ctx.fillRect(0, 0, RULER, h);
  ctx.strokeStyle = pal.rule;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, RULER + 0.5);
  ctx.lineTo(w, RULER + 0.5);
  ctx.moveTo(RULER + 0.5, 0);
  ctx.lineTo(RULER + 0.5, h);
  ctx.stroke();

  ctx.fillStyle = pal.ink2;
  ctx.strokeStyle = pal.ink2;
  // horizontal ruler: mm from the sheet's left edge
  ctx.beginPath();
  const xa = Math.floor((RULER - vp.ox) / vp.z / minor) * minor;
  for (let mm = Math.max(0, xa); mm <= PW + 0.001; mm += minor) {
    const sx = Math.round(vp.ox + mm * vp.z) + 0.5;
    if (sx > w) break;
    if (sx < RULER) continue;
    const major = Math.abs(mm / step - Math.round(mm / step)) < 1e-6;
    ctx.moveTo(sx, RULER);
    ctx.lineTo(sx, RULER - (major ? 9 : 4));
  }
  ctx.stroke();
  for (let mm = 0; mm <= PW + 0.001; mm += step) {
    const sx = vp.ox + mm * vp.z;
    if (sx > RULER + 8 && sx < w) ctx.fillText(fmt(mm, 2), sx + 3, 10);
  }
  // vertical ruler: mm from the sheet's top edge (AxiDraw's y runs downward)
  ctx.beginPath();
  const ya = Math.floor((RULER - vp.oy) / vp.z / minor) * minor;
  for (let mm = Math.max(0, ya); mm <= PH + 0.001; mm += minor) {
    const sy = Math.round(vp.oy + mm * vp.z) + 0.5;
    if (sy > h) break;
    if (sy < RULER) continue;
    const major = Math.abs(mm / step - Math.round(mm / step)) < 1e-6;
    ctx.moveTo(RULER, sy);
    ctx.lineTo(RULER - (major ? 9 : 4), sy);
  }
  ctx.stroke();
  for (let mm = 0; mm <= PH + 0.001; mm += step) {
    const sy = vp.oy + mm * vp.z;
    if (sy > RULER + 8 && sy < h) {
      ctx.save();
      ctx.translate(10, sy + 3);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText(fmt(mm, 2), 0, 0);
      ctx.restore();
    }
  }
  if (pointer && pointer[0] > RULER && pointer[1] > RULER) {
    ctx.strokeStyle = pal.accent;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(pointer[0], 0);
    ctx.lineTo(pointer[0], RULER);
    ctx.moveTo(0, pointer[1]);
    ctx.lineTo(RULER, pointer[1]);
    ctx.stroke();
  }
}
