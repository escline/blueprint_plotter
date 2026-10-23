import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  compose,
  exportSvg,
  listSamples,
  loadSample,
  uploadModel,
  type ComposeResponse,
  type ModelInfo,
  type Orientation,
  type SheetRequest,
} from "./api";
import { fmt, type Vec } from "./geometry";
import { SheetCanvas } from "./SheetCanvas";
import {
  DEFAULT_ORIENTATION,
  loadSettings,
  saveSettings,
  type Settings,
} from "./settings";
import { Sidebar } from "./Sidebar";

const PAGE_SIZES: Record<string, Vec> = {
  a2: [594, 420],
  a3: [420, 297],
  a4: [297, 210],
  letter: [279.4, 215.9],
  tabloid: [431.8, 279.4],
};

const SAMPLE_LABEL: Record<string, string> = {
  plate: "Plate with holes",
  stepped_cylinder: "Stepped cylinder",
  torus: "Torus",
};

type Placements = Record<string, Vec> | null;

export default function App() {
  const [settings, setSettingsState] = useState<Settings>(loadSettings);
  const [orientation, setOrientationState] = useState<Orientation>(DEFAULT_ORIENTATION);
  const [model, setModel] = useState<ModelInfo | null>(null);
  const [title, setTitle] = useState("");
  const [result, setResult] = useState<ComposeResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [placements, setPlacements] = useState<Placements>(null); // null = automatic layout
  const [selected, setSelected] = useState<string | null>(null);
  const [fitSignal, setFitSignal] = useState(0);
  const [samples, setSamples] = useState<string[]>([]);
  const [dropping, setDropping] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => saveSettings(settings), [settings]);
  useEffect(() => {
    listSamples().then(setSamples).catch(() => setSamples([]));
  }, []);

  const setSettings = useCallback((patch: Partial<Settings>) => {
    setSettingsState((s) => ({ ...s, ...patch }));
    if ("page" in patch) setPlacements(null); // different sheet: start from the automatic layout
  }, []);

  const setOrientation = useCallback((o: Orientation) => {
    setOrientationState(o);
    setPlacements(null);
  }, []);

  // ---- model loading -----------------------------------------------------------------------
  const adopt = useCallback((m: ModelInfo) => {
    setModel(m);
    setOrientationState(DEFAULT_ORIENTATION);
    setPlacements(null);
    setSelected(null);
    setTitle("");
    setError("");
    setStatus("");
  }, []);

  const openFile = useCallback(
    async (file: File) => {
      setBusy(true);
      setStatus(`Reading ${file.name}…`);
      try {
        adopt(await uploadModel(file));
      } catch (e) {
        setStatus("");
        setError(e instanceof ApiError ? e.message : `Couldn’t reach the server: ${(e as Error).message}`);
      } finally {
        setBusy(false);
      }
    },
    [adopt],
  );

  const openSample = useCallback(
    async (name: string) => {
      setBusy(true);
      try {
        adopt(await loadSample(name));
      } catch (e) {
        setError(e instanceof ApiError ? e.message : (e as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [adopt],
  );

  // ---- compose loop: recompute only when something the server needs changes --------------------
  const request: SheetRequest | null = useMemo(
    () =>
      model
        ? {
            model_id: model.id,
            orientation,
            views: settings.views,
            angle: settings.angle,
            resolution: settings.resolution,
            hidden: settings.hidden,
            hidden_silhouettes: settings.hiddenSilhouettes,
            dims: settings.dims,
            page: settings.page,
            margin: settings.margin,
            title,
            scale: settings.scale,
          }
        : null,
    [model, orientation, settings, title],
  );
  const requestKey = request ? JSON.stringify(request) : "";

  useEffect(() => {
    if (!request) {
      setResult(null);
      return;
    }
    const ctrl = new AbortController();
    const timer = setTimeout(async () => {
      setBusy(true);
      try {
        const res = await compose(request, ctrl.signal);
        setResult(res);
        setError("");
        setStatus("");
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        setError(e instanceof ApiError ? e.message : `Couldn’t reach the server: ${(e as Error).message}`);
      } finally {
        if (!ctrl.signal.aborted) setBusy(false);
      }
    }, 150);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey]);

  // ---- layout ----------------------------------------------------------------------------------
  const centers: Record<string, Vec> = useMemo(() => {
    const c: Record<string, Vec> = {};
    if (result) for (const [n, v] of Object.entries(result.views)) c[n] = placements?.[n] ?? v.center;
    return c;
  }, [result, placements]);

  const moveView = useCallback(
    (name: string, center: Vec) => {
      setPlacements((prev) => {
        const base: Record<string, Vec> = prev ? { ...prev } : {};
        if (!prev && result) for (const [n, v] of Object.entries(result.views)) base[n] = v.center;
        base[name] = center;
        return base;
      });
    },
    [result],
  );

  const autoLayout = () => {
    setPlacements(null);
    setSelected(null);
    setFitSignal((n) => n + 1);
  };

  // ---- export ----------------------------------------------------------------------------------
  const doExport = async () => {
    if (!request || !result) return;
    setBusy(true);
    setStatus("Building SVG…");
    try {
      const r = await exportSvg({ ...request, placements: centers });
      setStatus(`Saved ${r.filename} · ${fmt(r.total_mm / 1000, 2)} m pen-down · ${r.scale_label}`);
      setError("");
    } catch (e) {
      setStatus("");
      setError(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // ---- drag a file anywhere onto the window ------------------------------------------------------
  const onDragOver = (e: React.DragEvent) => {
    if (Array.from(e.dataTransfer.types).includes("Files")) {
      e.preventDefault();
      setDropping(true);
    }
  };
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDropping(false);
    const f = e.dataTransfer.files?.[0];
    if (f) void openFile(f);
  };

  const pageSize = PAGE_SIZES[settings.page] ?? PAGE_SIZES.a3;
  const selectedCenter = selected && centers[selected] ? centers[selected] : null;

  return (
    <div className={`app${dropping ? " dropping" : ""}`} onDragOver={onDragOver} onDragLeave={() => setDropping(false)} onDrop={onDrop}>
      <input
        ref={fileInput}
        type="file"
        hidden
        accept=".stl,.obj,.ply,.3mf,.off,.glb,.gltf,.step,.stp"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void openFile(f);
          e.target.value = "";
        }}
      />

      <header className="topbar">
        <h1>Blueprint plotter</h1>
        <p className="topbar-model num" aria-live="polite">
          {model ? model.name : "No model open"}
        </p>
        <p className="topbar-status" role="status">
          {busy ? "Working…" : status}
        </p>
        <button className="btn bar" onClick={autoLayout} disabled={!result}>
          Auto layout
        </button>
        <button className="btn bar primary" onClick={doExport} disabled={!result || busy}>
          Export SVG
        </button>
      </header>

      <aside className="sidebar" aria-label="Settings">
        <Sidebar
          model={model}
          result={result}
          settings={settings}
          setSettings={setSettings}
          orientation={orientation}
          setOrientation={setOrientation}
          title={title}
          setTitle={setTitle}
          selected={selected}
          selectedCenter={selectedCenter}
          onMoveSelected={(c) => selected && moveView(selected, c)}
          onOpenFile={() => fileInput.current?.click()}
        />
      </aside>

      <main className="stage">
        <SheetCanvas
          result={result}
          pageSize={pageSize}
          centers={centers}
          pens={settings.pens}
          selected={selected}
          fitSignal={fitSignal}
          onSelect={setSelected}
          onMove={moveView}
        />
        {busy && <div className="busy" aria-hidden="true" />}

        {error && (
          <div className="banner" role="alert">
            <span>{error}</span>
            <button className="btn small" onClick={() => setError("")}>
              Dismiss
            </button>
          </div>
        )}

        {!model && (
          <div className="empty">
            <div className="empty-inner">
              <h2>Drop a model on the mat</h2>
              <p>
                STL, OBJ, PLY, 3MF or STEP. Views are laid out on {settings.page.toUpperCase()} paper, ready to drag into place.
              </p>
              <div className="empty-actions">
                <button className="btn bar primary" onClick={() => fileInput.current?.click()}>
                  Choose a file…
                </button>
              </div>
              {samples.length > 0 && (
                <p className="empty-samples">
                  Or try{" "}
                  {samples.map((s, i) => (
                    <span key={s}>
                      <button className="link" onClick={() => openSample(s)}>
                        {SAMPLE_LABEL[s] ?? s}
                      </button>
                      {i < samples.length - 1 ? ", " : ""}
                    </span>
                  ))}
                  .
                </p>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
