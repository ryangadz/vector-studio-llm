---
name: vector-studio
description: Work with Vector Studio LLM sketches. Use whenever the user mentions vector studio, sketches, pins, "check pins", arraying or mirroring shapes, or asks to edit, project, fill, or render an SVG that has data-vs elements or a .pins.json sidecar.
---

# vector-studio — closing the loop with Vector Studio LLM

Vector Studio LLM is a pointing-and-sketching vector tool: the human
sketches rough geometry and drops pins in a browser viewer; the LLM session
does the math and edits the SVG file directly. No screenshots — the SVG +
sidecar round-trip is plain text with exact coordinates.

**Tool vs project:** the tool is one cloned copy of the vector-studio-llm
repo; a "project" is just a folder of SVGs + sidecars — any folder the
user chooses. Never copy the tool into a project. If you don't know where
the tool is cloned, ask the user.

**Step zero, every invocation: make sure the viewer is up.** The user
saying "check pins" (or anything that fires this skill) means they are at
the bench — a running viewer is part of the deal, even when there are no
pins to address yet ("no pins" often means they're about to start
sketching). So before the pins work:

1. If you have the plugin's viewer tools — `viewer_status` /
   `start_viewer` from the **vector-studio-viewer** MCP server — use them
   and nothing else: `viewer_status` first; if nothing is running,
   `start_viewer` with `root` = wherever the user's sketches live (their
   call, often the folder you're working in; ask if unclear). The
   tool-permission prompt IS the ask. Tell the user the URL. If
   `viewer_status` says the running viewer is an OLDER build, ask the user
   before restarting (they may be mid-sketch), then `stop_viewer` +
   `start_viewer` with the same root; if it reports a newer build, leave
   it alone.
2. No viewer tools (skill copied without the plugin) but a real shell?
   Probe http://127.0.0.1:8103; if silent, run from the tool folder as a
   background command: `python serve.py --root <project folder>`
   (`--port <n>` runs several projects at once) — the shell permission
   prompt is the ask.
3. NEVER start the server by GUI automation or desktop control — not the
   OS Run dialog, not clicking a .bat, not driving a terminal window, not
   taking over the computer because your shell is sandboxed. A sandbox is
   a boundary, not a puzzle: if neither the viewer tools nor a shell can
   do it, hand the user the one command to run themselves and carry on
   with the pins work.

The server is for the human, not for you: your own work is plain file
edits, and the viewer auto-reloads on save. Needing to edit never requires
the server — but the human sketching always does, which is why starting it
is step zero rather than an afterthought.

## The agent contract (read before editing any sketch)

- Sketch geometry = elements marked `data-vs="1"` (`<polyline>`,
  `<polygon>`, or derived `<path>`). Coordinates are SVG user units,
  **2 units = 1 mm**, origin at viewBox top-left, y down. Divide by 2
  for mm.
- Pins live in a sidecar `<file>.svg.pins.json`: `pins[].user` (user
  units), `pins[].mm`, and a free-text `note`. Pins are the human pointing
  at the drawing — treat notes as instructions or scene descriptions.
- **After addressing every pin, write the sidecar back with `"pins": []`.**
  Exception: leave pins that are a scene *specification* (not edit
  requests) when the file they describe is a source document still in use.
- A shape with corner radii is a `data-vs` `<path>` whose model rides in
  `data-vs-pts` (vertex list) + `data-vs-fillets` (`index:radius`, user
  units) + `data-vs-closed`. **Edit the model attributes, never `d`** —
  the viewer re-derives `d` on load (self-healing). Fillet clamping:
  tangent offset ≤ half the shorter adjacent edge.
- Mark any outline the human should keep point-editing with
  `data-vs="1"` — that is what gives it drag handles in the viewer.
- The viewer polls mtime and auto-reloads after your write. Last writer
  wins; don't edit while the human is mid-draw.
- Keep coordinates clean (round to user units; the 1 mm grid = even
  values). The canvas grows by extending the viewBox and the `data-vs-bg`
  rect; negative coordinates are fine.

## Proven techniques (keep straight lines unless asked)

- **Radial array from a pinned origin:** the human sketches one
  tooth/arm/segment and pins the center. Symmetrize the element about its
  own axis (average paired radii and angles in polar form), check the
  angular width fits 360/N with a gap between copies, then array N× into
  ONE closed polygon so every vertex stays draggable.
- **Carry edits through:** after the human edits one section of an arrayed
  shape, de-rotate each section to a common frame, find the outlier
  against per-point medians, take it as the new template, re-array. Watch
  for added or removed points changing section lengths.
- **Plan → viewpoint projection:** a top-down plan plus descriptive pins
  ("viewpoint", "large tree", "bench"…) projects to a first-person,
  editable sketch: camera at the viewpoint pin, pick a world scale, eye
  ~1.7 m, screen_x = cx + f·x/z, ground_y = horizon + f·eye/z. Elements
  outside the view cone become cropped framing shapes at the frame edges —
  tell the user which. Keep each element its own data-vs polygon, layered
  far → near.
- **Fill pass (separate file — keep the sketch editable):** paint the same
  geometry with depth-graded colors mixed toward a fog color, gradients, a
  glow at the focal point, moss/texture as ribbon polygons, paving as
  clipped dash rows. Save as `<name>-filled.svg` plus a PNG render.
- **Parallax layers:** group the fill's paint order into depth bands,
  render each band as a transparent RGBA PNG with ~5% bleed, stack with
  per-layer shift factors. Scenes designed for parallax should hide ground
  contacts and use overlapping side-on bands, not a converging perspective
  floor.
- **External render handoff (image models):** export a clean raster (strip
  grid and origin markers). A filled silhouette makes the model follow the
  shape strictly; line art invites looser reinterpretation. Prompt it to
  treat the image as a locked composition or stencil.

## Verify

Render a preview (cairosvg, resvg, or similar) and look at it before
declaring done; check numeric invariants (point counts, radii, root gaps,
canvas bounds).
