# AGENTS.md — the contract for this repo's drawings

You are editing vector drawings in a human-in-the-loop sketching setup. A
human sketches rough shapes and drops numbered pins in a local viewer
(`viewer.html`, served by `serve.py`); you do the geometry by editing files.
The viewer watches the files and reloads whatever you write.

## The loop

When asked to "check pins" (or given a `*.svg.pins.json` path):

1. Read the drawing (`<drawing>.svg`) and its pin sidecar
   (`<drawing>.svg.pins.json`, sitting next to it).
2. Make the edit each pin asks for, directly in the SVG.
3. Address **every** pin, then write the sidecar back with `"pins": []` to
   clear the ones you handled.
4. Stop. The human sees the viewer reload, drags dots, drops more pins, and
   sends you around again.

## Coordinates

- SVG **user units, 2 units = 1 mm** by default (the sidecar's `pxPerMm`
  says if not), origin at the viewBox top-left, **y down**.
- Each pin carries `user` (SVG units), `mm`, and a free-text `note`. The
  pin's coordinates are where the human pointed — treat them as ground
  truth for *where*; the note says *what*.

## The data-vs model rules

- Shapes the human can point-edit are marked `data-vs="1"` —
  `<polygon>`/`<polyline>` with clean coordinates.
- A shape with corner radii is a `<path data-vs>` whose **model** rides in
  `data-vs-pts` (vertex list) + `data-vs-fillets` (`index:radius`, user
  units) + `data-vs-closed`; its `d` is derived. **Edit the model, not
  `d`** — the viewer re-derives `d` on load, so a stale `d` after your
  edit is fine.
- Mark any outline the human should keep point-editing with `data-vs="1"`.
  Freeform curves you author (tangent arcs, beziers) can be plain
  `<path>`s — they render fine but won't get drag dots.

## One editor at a time

One editor at a time per file. The viewer pauses its own writes while a
line is mid-draw and announces external changes with a "new updates"
button; last writer wins. Edit the file in place, don't sit on unsaved
changes, and don't rewrite geometry no pin points at.

## Division of labor

The human's side is what needs hands: pointing, rough outlines, dragging
dots, truing a length or a radius. Your side is what needs math or
judgment: tangency, dimensioning, arrays, booleans, styling. Do what the
pins ask; don't restyle or "clean up" unrequested parts of the drawing.
