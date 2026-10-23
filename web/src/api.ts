// Typed client for the local blueprint-plotter server.

export type ViewName = "front" | "back" | "left" | "right" | "top" | "bottom" | "iso";
export const ALL_VIEWS: ViewName[] = ["front", "top", "right", "left", "back", "bottom", "iso"];

export interface ModelInfo {
  id: string;
  name: string;
  triangles: number;
  extents: [number, number, number];
}

export type RotationStep = ["x" | "y" | "z", number];

export interface Orientation {
  up: "z" | "y";
  steps: RotationStep[];
  model_scale: number;
}

export interface SheetRequest {
  model_id: string;
  orientation: Orientation;
  views: ViewName[];
  angle: number;
  resolution: number;
  hidden: boolean;
  hidden_silhouettes: boolean;
  dims: boolean;
  page: string;
  margin: number;
  title: string;
  scale: string;
  placements?: Record<string, [number, number]> | null;
}

/** Each polyline is a flat [x0, y0, x1, y1, …] array. */
export type Polylines = number[][];

export interface ViewGeometry {
  center: [number, number];
  size: [number, number];
  box: [number, number, number, number];
  extents: [number, number];
  visible: Polylines; // relative to the view centre
  hidden: Polylines;
  notes: Polylines;
}

export interface LayerStat {
  strokes: number | null;
  length_mm: number;
}

export interface ComposeResponse {
  page: [number, number];
  scale: number;
  scale_label: string;
  fit_scale: number;
  fit_label: string;
  overflow: boolean;
  extents: [number, number, number];
  dash: [number, number];
  frame: Polylines;
  views: Record<string, ViewGeometry>;
  layers: Record<"1" | "2" | "3", LayerStat>;
}

export interface ExportResult {
  filename: string;
  total_mm: number;
  scale_label: string;
}

export class ApiError extends Error {}

async function fail(res: Response): Promise<never> {
  let detail = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    if (typeof body.detail === "string") detail = body.detail;
    else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
  } catch {
    /* keep status text */
  }
  throw new ApiError(detail);
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export async function uploadModel(file: File): Promise<ModelInfo> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/models", { method: "POST", body: form });
  if (!res.ok) await fail(res);
  return res.json();
}

export async function listSamples(): Promise<string[]> {
  const res = await fetch("/api/samples");
  return res.ok ? res.json() : [];
}

export async function loadSample(name: string): Promise<ModelInfo> {
  const res = await fetch(`/api/samples/${encodeURIComponent(name)}`, { method: "POST" });
  if (!res.ok) await fail(res);
  return res.json();
}

export async function compose(req: SheetRequest, signal?: AbortSignal): Promise<ComposeResponse> {
  const { placements: _ignored, ...body } = req; // layout is client-side; the server needn't see it
  void _ignored;
  const res = await fetch("/api/compose", { ...json(body), signal });
  if (!res.ok) await fail(res);
  return res.json();
}

export async function exportSvg(req: SheetRequest): Promise<ExportResult> {
  const res = await fetch("/api/export", json(req));
  if (!res.ok) await fail(res);
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(cd)?.[1] ?? "blueprint.svg";
  const stats = JSON.parse(res.headers.get("X-Blueprint-Stats") ?? "{}");

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
  return { filename, total_mm: stats.total_mm ?? 0, scale_label: stats.scale_label ?? "" };
}
