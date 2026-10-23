import { useEffect, useId, useState, type ReactNode } from "react";
import { ALL_VIEWS, type ComposeResponse, type ModelInfo, type Orientation, type ViewName } from "./api";
import { fmt } from "./geometry";
import { PAGES, PEN_WIDTHS, SCALE_PRESETS, UNITS, type Pen, type Settings } from "./settings";

const VIEW_LABEL: Record<ViewName, string> = {
  front: "Front",
  top: "Top",
  right: "Right",
  left: "Left",
  back: "Back",
  bottom: "Bottom",
  iso: "Isometric",
};

const r2 = (v: number) => Math.round(v * 100) / 100;

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="section">
      <h2>{title}</h2>
      {hint && <p className="hint">{hint}</p>}
      {children}
    </section>
  );
}

function Check({
  label,
  checked,
  onChange,
  disabled,
  note,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  note?: string;
}) {
  return (
    <label className={`check${disabled ? " is-disabled" : ""}`}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>
        {label}
        {note && <span className="note"> {note}</span>}
      </span>
    </label>
  );
}

/** Slider that only commits on release, because every new crease angle re-runs hidden-line removal. */
function CommitSlider({
  label,
  value,
  min,
  max,
  unit,
  onCommit,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  unit: string;
  onCommit: (v: number) => void;
}) {
  const id = useId();
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => draft !== value && onCommit(draft);
  return (
    <div className="field">
      <label htmlFor={id}>
        {label} <span className="num">{draft}{unit}</span>
      </label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        value={draft}
        onChange={(e) => setDraft(Number(e.target.value))}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
      />
    </div>
  );
}

const SCALE_RE = /^(auto|fit|\d+(\.\d+)?(:\d+(\.\d+)?)?)$/i;

function ScaleField({ value, onCommit }: { value: string; onCommit: (v: string) => void }) {
  const id = useId();
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const valid = SCALE_RE.test(draft.trim());
  const commit = (v: string) => {
    if (SCALE_RE.test(v.trim()) && v.trim().toLowerCase() !== value) onCommit(v.trim().toLowerCase());
  };
  return (
    <div className="field">
      <label htmlFor={id}>Scale</label>
      <input
        id={id}
        list={`${id}-presets`}
        value={draft}
        aria-invalid={!valid}
        onFocus={(e) => e.target.select()}
        onChange={(e) => {
          setDraft(e.target.value);
          if (SCALE_PRESETS.includes(e.target.value)) commit(e.target.value); // picked from the list
        }}
        onBlur={() => (valid ? commit(draft) : setDraft(value))}
        onKeyDown={(e) => e.key === "Enter" && commit(draft)}
      />
      <datalist id={`${id}-presets`}>
        {SCALE_PRESETS.map((p) => (
          <option key={p} value={p} />
        ))}
      </datalist>
    </div>
  );
}

function PenRow({
  index,
  pen,
  stat,
  onChange,
}: {
  index: number;
  pen: Pen;
  stat?: { strokes: number | null; length_mm: number };
  onChange: (p: Pen) => void;
}) {
  const wid = useId();
  const cid = useId();
  const dashed = index === 1;
  const metres = stat ? fmt(stat.length_mm / 1000, 2) : "–";
  return (
    <li className="pen">
      <svg className="nib" viewBox="0 0 64 16" width="64" height="16" aria-hidden="true">
        <line
          x1="4"
          y1="8"
          x2="60"
          y2="8"
          stroke={pen.color}
          strokeWidth={Math.max(pen.width * 8, 1)}
          strokeLinecap="round"
          strokeDasharray={dashed ? `${2.5 * 3.2} ${1.2 * 3.2}` : undefined}
        />
      </svg>
      <div className="pen-main">
        <div className="pen-title">
          <strong>{pen.name}</strong> <span className="note">{pen.role}</span>
        </div>
        <div className="pen-stat num">
          {stat?.strokes != null ? `${stat.strokes.toLocaleString()} strokes · ` : ""}
          {stat ? `${metres} m${index === 1 ? " (dashed)" : ""}` : "–"}
        </div>
      </div>
      <div className="pen-ctl">
        <label className="sr-only" htmlFor={wid}>{`${pen.name} width`}</label>
        <select id={wid} value={pen.width} onChange={(e) => onChange({ ...pen, width: Number(e.target.value) })}>
          {PEN_WIDTHS.map((w) => (
            <option key={w} value={w}>
              {w.toFixed(1)} mm
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor={cid}>{`${pen.name} colour`}</label>
        <input id={cid} type="color" value={pen.color} onChange={(e) => onChange({ ...pen, color: e.target.value })} />
      </div>
    </li>
  );
}

export interface SidebarProps {
  model: ModelInfo | null;
  result: ComposeResponse | null;
  settings: Settings;
  setSettings: (patch: Partial<Settings>) => void;
  orientation: Orientation;
  setOrientation: (o: Orientation) => void;
  title: string;
  setTitle: (t: string) => void;
  selected: string | null;
  selectedCenter: [number, number] | null;
  onMoveSelected: (center: [number, number]) => void;
  onOpenFile: () => void;
}

export function Sidebar(p: SidebarProps) {
  const { settings: s, orientation: o, result } = p;
  const rotate = (axis: "x" | "y" | "z", deg: number) => p.setOrientation({ ...o, steps: [...o.steps, [axis, deg]] });
  const pageH = result?.page[1] ?? 297;
  const hasModel = !!p.model;

  const toggleView = (v: ViewName) => {
    const has = s.views.includes(v);
    if (has && s.views.length === 1) return; // always keep one view
    p.setSettings({ views: has ? s.views.filter((x) => x !== v) : ALL_VIEWS.filter((x) => x === v || s.views.includes(x)) });
  };

  return (
    <div className="sidebar-inner">
      <Section title="Model">
        {p.model ? (
          <>
            <p className="model-name">{p.model.name}</p>
            <p className="num detail">
              {result ? result.extents.map((e) => fmt(e)).join(" × ") : p.model.extents.map((e) => fmt(e)).join(" × ")} mm
              <span className="note"> (X × Y × Z)</span>
            </p>
            <p className="detail num">{p.model.triangles.toLocaleString()} triangles</p>
          </>
        ) : (
          <p className="hint">No model yet.</p>
        )}
        <button className="btn" onClick={p.onOpenFile}>
          {p.model ? "Replace model…" : "Open model…"}
        </button>
      </Section>

      <Section title="Orientation" hint="Models from the web are often lying on their side or in inches. The Front view looks along +Y with Z up.">
        <div className="field">
          <span className="label" id="up-label">Up axis in the file</span>
          <div className="seg" role="radiogroup" aria-labelledby="up-label">
            {(["z", "y"] as const).map((u) => (
              <button
                key={u}
                role="radio"
                aria-checked={o.up === u}
                className={o.up === u ? "on" : ""}
                disabled={!hasModel}
                onClick={() => p.setOrientation({ ...o, up: u })}
              >
                {u.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        <div className="rot">
          {(["x", "y", "z"] as const).map((a) => (
            <div className="rot-row" key={a}>
              <span className="rot-axis">Turn about {a.toUpperCase()}</span>
              <button className="btn small" disabled={!hasModel} onClick={() => rotate(a, -90)} aria-label={`Rotate -90 degrees about ${a.toUpperCase()}`}>
                −90°
              </button>
              <button className="btn small" disabled={!hasModel} onClick={() => rotate(a, 90)} aria-label={`Rotate +90 degrees about ${a.toUpperCase()}`}>
                +90°
              </button>
            </div>
          ))}
        </div>
        <div className="row-gap">
          <button className="btn small" disabled={!hasModel || o.steps.length === 0} onClick={() => p.setOrientation({ ...o, steps: o.steps.slice(0, -1) })}>
            Undo last turn
          </button>
          <button className="btn small" disabled={!hasModel || (o.steps.length === 0 && o.up === "z")} onClick={() => p.setOrientation({ ...o, up: "z", steps: [] })}>
            Reset
          </button>
        </div>
        <div className="field">
          <label htmlFor="units">File units</label>
          <select id="units" value={o.model_scale} disabled={!hasModel} onChange={(e) => p.setOrientation({ ...o, model_scale: Number(e.target.value) })}>
            {UNITS.map((u) => (
              <option key={u.value} value={u.value}>
                {u.label}
              </option>
            ))}
          </select>
        </div>
      </Section>

      <Section title="Views">
        <div className="views-grid">
          {ALL_VIEWS.map((v) => (
            <Check key={v} label={VIEW_LABEL[v]} checked={s.views.includes(v)} disabled={!hasModel} onChange={() => toggleView(v)} />
          ))}
        </div>
        {p.selected && p.selectedCenter ? (
          <div className="selected">
            <p className="selected-title">
              {VIEW_LABEL[p.selected as ViewName] ?? p.selected} view <span className="note">position of its centre, from the sheet’s top-left</span>
            </p>
            <div className="xy">
              <label>
                X
                <input
                  type="number"
                  step="0.5"
                  value={r2(p.selectedCenter[0])}
                  onChange={(e) => !Number.isNaN(e.target.valueAsNumber) && p.onMoveSelected([e.target.valueAsNumber, p.selectedCenter![1]])}
                />
              </label>
              <label>
                Y
                <input
                  type="number"
                  step="0.5"
                  value={r2(pageH - p.selectedCenter[1])}
                  onChange={(e) => !Number.isNaN(e.target.valueAsNumber) && p.onMoveSelected([p.selectedCenter![0], pageH - e.target.valueAsNumber])}
                />
              </label>
              <span className="note">mm</span>
            </div>
          </div>
        ) : (
          <p className="hint">Drag a view on the sheet to move it. It snaps to line up with the others; hold Alt to move freely.</p>
        )}
      </Section>

      <Section title="Sheet">
        <div className="field">
          <label htmlFor="page">Paper</label>
          <select id="page" value={s.page} onChange={(e) => p.setSettings({ page: e.target.value })}>
            {PAGES.map((pg) => (
              <option key={pg.value} value={pg.value}>
                {pg.label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="margin">Border inset (mm)</label>
          <input
            id="margin"
            type="number"
            min={0}
            max={80}
            step={1}
            value={s.margin}
            onChange={(e) => {
              const v = e.target.valueAsNumber;
              if (!Number.isNaN(v)) p.setSettings({ margin: Math.min(Math.max(v, 0), 80) });
            }}
          />
        </div>
        <ScaleField value={s.scale} onCommit={(v) => p.setSettings({ scale: v })} />
        {result && (
          <p className={`scale-note num${result.overflow ? " warn" : ""}`}>
            {result.overflow
              ? `At ${result.scale_label} the views run past the sheet. Largest that fits: ${result.fit_label}.`
              : s.scale === "auto"
                ? `Drawing at ${result.scale_label}, the largest standard scale that fits.`
                : `Drawing at ${result.scale_label}. Largest that fits: ${result.fit_label}.`}
          </p>
        )}
        <div className="field">
          <label htmlFor="title">Title block</label>
          <input id="title" value={p.title} placeholder={p.model?.name.replace(/\.[^.]+$/, "") ?? ""} maxLength={80} onChange={(e) => p.setTitle(e.target.value)} />
        </div>
      </Section>

      <Section title="Linework">
        <Check label="Hidden lines" checked={s.hidden} onChange={(v) => p.setSettings({ hidden: v })} />
        <Check
          label="Hidden outlines of curved surfaces"
          note="Keep for bores and holes; turn off for organic shapes."
          checked={s.hiddenSilhouettes}
          disabled={!s.hidden}
          onChange={(v) => p.setSettings({ hiddenSilhouettes: v })}
        />
        <Check label="Overall dimensions" checked={s.dims} onChange={(v) => p.setSettings({ dims: v })} />
        <CommitSlider label="Edge sharpness threshold" value={s.angle} min={5} max={80} unit="°" onCommit={(v) => p.setSettings({ angle: v })} />
        <p className="hint">Edges where faces meet at more than this angle are drawn. Lower it to pick up detail on faceted meshes.</p>
        <div className="field">
          <label htmlFor="res">Hidden-line precision</label>
          <select id="res" value={s.resolution} onChange={(e) => p.setSettings({ resolution: Number(e.target.value) })}>
            <option value={1000}>Draft</option>
            <option value={2000}>Standard</option>
            <option value={4000}>Fine (slower)</option>
          </select>
        </div>
      </Section>

      <Section title="Pens" hint="Each layer in the exported SVG is one pen, so you swap pens between layers. Width and colour change this preview only.">
        <ul className="pens">
          {s.pens.map((pen, i) => (
            <PenRow
              key={i}
              index={i}
              pen={pen}
              stat={result?.layers[String(i + 1) as "1" | "2" | "3"]}
              onChange={(np) => p.setSettings({ pens: s.pens.map((q, j) => (j === i ? np : q)) as Settings["pens"] })}
            />
          ))}
        </ul>
      </Section>
    </div>
  );
}
