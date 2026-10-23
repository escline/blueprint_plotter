# blueprint-plotter

Turn a 3D model (STL/OBJ/PLY/3MF, or STEP) into a multi-view **blueprint sheet** as a layered SVG, ready for an AxiDraw A3.

```
model → project (front/top/right/iso…) → hidden-line removal → sheet layout + dims + title block
      → vpype (merge strokes, simplify, sort for min pen-up travel) → layered SVG → nextdraw
```

## Install

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .
pip install -e ".[web]"      # the browser UI (FastAPI + uvicorn)
pip install -e ".[step]"     # optional: read .step/.stp via cascadio
```

### Windows notes

Use the python.org CPython (`py -3.10`), not an MSYS/MinGW Python: numpy and numba have no wheels for MSYS. 3.10 is also where the NextDraw installer puts its library.

```powershell
py -3.10 -m venv .venv
.venv\Scripts\python -m pip install -e ".[web,dev,step]"
.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

AxiDraw control is separate. Install Bantam Tools' NextDraw CLI/API (https://bantam.tools/nd_cli/), then check `nextdraw --version`. The older `axicli` also works; `blueprint plot` uses whichever it finds, preferring `nextdraw`. When calling `nextdraw` directly, always pass `--model 2` (A3; it defaults to a NextDraw model) and `--penlift 3` if your AxiDraw has the brushless pen-lift servo. Without the right pen-lift code the plot runs with the pen up.

## Use

```bash
blueprint part.stl                                   # → part.svg  (front, top, right, iso on A3)
blueprint part.stl --title "Bracket" --scale 1:2
blueprint part.stl --views front,top --no-hidden --page a4
blueprint downloaded.stl --up y --model-scale 25.4   # Y-up file authored in inches
blueprint plot part.svg --preview                    # see below; always preview first
```

Useful flags

| flag | what it does |
|---|---|
| `--views` | any of `front back left right top bottom iso` (third-angle arrangement) |
| `--scale` | `auto` (largest standard scale that fits), `fit` (exact fit), `1:2`, `2:1`, `0.5` |
| `--angle` | crease angle in degrees (default 30). Lower = more edges on faceted/organic meshes |
| `--no-hidden` | drop dashed hidden lines entirely |
| `--no-hidden-silhouettes` | keep hidden *creases* but drop hidden outlines of smooth surfaces (cleaner on organic meshes; keep it off for bores/holes) |
| `--resolution` | depth-buffer size; raise (e.g. 4000) if hidden-line boundaries look rough |
| `--up y`, `--rotate X,Y,Z`, `--model-scale` | fix orientation/units of models from the internet |

## Web UI

```bash
blueprint serve              # opens http://127.0.0.1:8765
```

Drop a model on the page (or try a bundled sample), then:

* **Move views:** drag them on the sheet. They snap to line up with each other (hold **Alt** to move freely). Select a view and use the arrow keys (1 mm, **Shift** = 10 mm) or type exact X/Y in the sidebar. **Auto layout** resets.
* **Fix orientation:** turn the model ±90° about any axis (with undo), switch the file's up axis, set file units.
* **Zoom/pan:** scroll to zoom, drag the background to pan, `F` or double-click the mat to fit. Rulers use AxiDraw coordinates (origin top-left), and the readout bottom-left shows the pointer position in mm, handy for registering paper.
* **Pens panel:** shows each layer at a real pen width with stroke count and ink length. Widths/colours change the preview only.
* **Export SVG:** same pipeline as the CLI, including your dragged positions.

The server binds to localhost only. Models are held in memory (last 8) and nothing is written to disk.

Developing the front end (Node 18+ only needed for this):

```bash
cd web && npm install
npm run dev                  # Vite dev server, proxies /api to a running `blueprint serve`
npm test                     # geometry unit tests
npm run build                # writes into blueprint/web/static, which `blueprint serve` ships
```

Layout is computed client-side: the server returns each view's geometry relative to its own centre, so dragging never needs a round trip. Changing scale, orientation, paper or linework asks the server to recompute (hidden-line results are cached per view and setting).

## Layers = pens

| layer | content | suggested pen |
|---|---|---|
| 1 | visible outlines | your boldest pen |
| 2 | hidden lines (dashed) | thin pen |
| 3 | dimensions, text, border, title block | thin pen |

```bash
nextdraw part.svg --model 2 --penlift 3 --mode layers --layer 1  # swap pen, then --layer 2, --layer 3
# or:   blueprint plot part.svg --layer 1
```

Line weight is simulated by pen choice per layer; a pen plotter has no variable width.

## Plotting notes (AxiDraw A3)

* Default border sits 10 mm inside A3 (420×297). The A3 travel area is slightly larger than the sheet, so keep the paper registered to the home corner and use `--margin` if your pen drifts at the edges.
* `blueprint plot` just shells out to `nextdraw` (or `axicli`). It defaults to `--model 2 --penlift 3` (A3, brushless pen lift); use `--penlift 1` for a standard servo. Tested on an A3: use `--preview` for the time estimate, then plot each layer with a pen swap in between.

## How the hidden-line removal works (mesh-based)

1. Candidate edges per view: creases (dihedral angle > `--angle`), silhouettes (one face towards the camera, one away) and open boundaries.
2. A numba z-buffer renders the whole mesh from that view.
3. Each edge is cut into ~3-pixel pieces; each piece's depth is compared with the buffer. Smooth-surface silhouettes use a neighbourhood test because the surface falls away steeply at the outline.
4. Hidden pieces that sit exactly under a visible stroke are dropped (no dashes over solid lines).

## Known limits

* Works on tessellated meshes, so circles are polylines (fine at plotter resolution; 96+ segments looks smooth).
* Smooth organic meshes only get silhouettes (no creases to draw). A shaded/hatched mode would suit them better (see roadmap).
* STEP files are tessellated first via cascadio; true B-rep hidden-line removal (exact arcs, center marks) is a possible later upgrade.
* Dimensions are overall width/height per view only. Narrow spans get outside arrows, as in drafting practice.
* Edges with identical projected endpoints are drawn once (e.g. top and bottom rim of a through-hole), but partially overlapping collinear edges can still be doubled.
* STEP loading, dragging a file onto the window, and the `plot` command are untested in development (no sample STEP / no hardware available). The UI was exercised in headless Chromium: select, drag, nudge, export, scale, rotation, bad-file and upload flows.

## Roadmap ideas

* 3D orientation preview in the UI, and per-view scale (e.g. a larger iso)
* "Plot this pen" buttons in the UI (needs hardware testing first)
* Hatching/stipple shading for organic models; cross-section views with hatch fill
* Center marks and hole callouts from detected circles
* Per-feature dimensions; configurable title block fields
* Custom view angles (`--views az30el20`)

## Dev

```bash
python tests/make_samples.py   # writes samples/*.stl
pytest -q                      # core + API tests (needs `.[web,dev]`)
cd web && npm test             # front-end geometry tests
```
