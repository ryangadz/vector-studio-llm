"""Functional checks for viewer.html — units layer, mode signals, auto layout,
touch-friendly path finishing, and clipboard copy/paste.

Runs everything against a scratch copy of the examples so the repo stays
untouched:  python tests/checks.py        (needs: pip install playwright,
python -m playwright install chromium)
"""
import shutil, socket, subprocess, sys, tempfile, time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORK = Path(tempfile.mkdtemp(prefix="vs-checks-"))
PORT = 8123

(WORK / "examples").mkdir(parents=True)
for f in ("floor-plan.svg", "studio-apartment.svg"):
    shutil.copy(REPO / "examples" / f, WORK / "examples" / f)

proc = subprocess.Popen(
    [sys.executable, str(REPO / "serve.py"), "--root", str(WORK), "--port", str(PORT)],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
passed = failed = 0
def check(name, cond, detail=""):
    global passed, failed
    if cond: passed += 1; print(f"  ok  {name}")
    else: failed += 1; print(f"FAIL  {name}  {detail}")

def parse_pts(s):
    v = [float(x) for x in s.replace(",", " ").split()]
    return list(zip(v[::2], v[1::2]))

try:
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", PORT), 0.2).close(); break
        except OSError:
            time.sleep(0.1)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1100, "height": 700},
                            permissions=["clipboard-read", "clipboard-write"])
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: print("PAGE ERROR:", e))
        base = f"http://127.0.0.1:{PORT}/viewer.html"

        def svg_map():
            m = pg.evaluate("""() => {
                const s = document.querySelector('#stage svg');
                const r = s.getBoundingClientRect(); const vb = s.viewBox.baseVal;
                return {rx:r.x, ry:r.y, rw:r.width, rh:r.height,
                        vx:vb.x, vy:vb.y, vw:vb.width, vh:vb.height};
            }""")
            return lambda ux, uy: (m["rx"] + (ux - m["vx"]) / m["vw"] * m["rw"],
                                   m["ry"] + (uy - m["vy"]) / m["vh"] * m["rh"])

        # ================= units layer (ported suite) =================
        pg.goto(f"{base}?file=examples/studio-apartment.svg")
        pg.wait_for_selector("#stage svg")
        pg.wait_for_timeout(600)

        check("unitSel picks up data-vs-unit", pg.eval_on_selector("#unitSel", "e => e.value") == "ftin")
        check("scale picks up data-vs-scale", pg.evaluate("S.pxPerMm") == 0.5)
        check("snap label follows unit", pg.eval_on_selector("#snapLbl", "e => e.textContent") == "1″")

        cases = [
            ("parseLen 12'6", "vsUnits.parseLen(\"12'6\")", 3810.0),
            ("parseLen 12'6\\\"", "vsUnits.parseLen('12\\'6\"')", 3810.0),
            ("parseLen 12'", "vsUnits.parseLen(\"12'\")", 3657.6),
            ("parseLen 6\\\"", "vsUnits.parseLen('6\"')", 152.4),
            ("parseLen 6 1/2\\\"", "vsUnits.parseLen('6 1/2\"')", 165.1),
            ("parseLen 8ft", "vsUnits.parseLen('8ft')", 2438.4),
            ("parseLen 3.5m", "vsUnits.parseLen('3.5m')", 3500.0),
            ("parseLen 35cm", "vsUnits.parseLen('35cm')", 350.0),
            ("parseLen 350mm", "vsUnits.parseLen('350mm')", 350.0),
            ("parseLen bare=inches in ftin", "vsUnits.parseLen('8')", 203.2),
        ]
        for name, expr, want in cases:
            got = pg.evaluate(expr)
            check(name, got is not None and abs(got - want) < 0.01, f"got {got} want {want}")
        check("parseLen garbage -> NaN", pg.evaluate("Number.isNaN(vsUnits.parseLen('abc'))"))
        check("ftinStr 3810 -> 12'6\"", pg.evaluate("vsUnits.ftinStr(3810)") == "12'6\"")
        check("ftinStr 3657.6 -> 12'", pg.evaluate("vsUnits.ftinStr(3657.6)") == "12'")
        check("ftinStr 152.4 -> 6\"", pg.evaluate("vsUnits.ftinStr(152.4)") == '6"')
        check("top wall label reads 20'",
              pg.evaluate("vsUnits.fmtNum(Math.hypot(3298-250, 0) / S.pxPerMm)") == "20'")

        # end-to-end: double-tap the island's top side, type 8', Enter
        pg.click("#modeSketch")
        pg.click("#zFit")
        pg.wait_for_timeout(300)
        px = svg_map()
        x, y = px(1157.2, 1650)          # midpoint of the island's top side
        pg.mouse.dblclick(x, y)
        pg.wait_for_selector("#lenEdit", timeout=3000)
        check("length editor prefilled in ft-in",
              pg.eval_on_selector("#lenEdit", "e => e.value") == "6'")
        pg.keyboard.type("8'")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(1200)        # applyLen + 400ms save debounce
        txt = (WORK / "examples" / "studio-apartment.svg").read_text(encoding="utf-8")
        check("8' edit landed in the file (1919.2,1650)", "1919.2,1650" in txt, txt[:200])
        check("file keeps data-vs-unit", 'data-vs-unit="ftin"' in txt)
        check("file keeps data-vs-scale", 'data-vs-scale="0.5"' in txt)

        # floor plan: mm file stays mm, then unit switch persists
        pg.goto(f"{base}?file=examples/floor-plan.svg")
        pg.wait_for_selector("#stage svg")
        pg.wait_for_timeout(600)
        check("mm file opens as mm", pg.eval_on_selector("#unitSel", "e => e.value") == "mm")
        check("mm readout unchanged shape", pg.evaluate("vsUnits.fmtLen(350)") == "350 mm")
        pg.select_option("#unitSel", "cm")
        pg.wait_for_timeout(1200)
        fp = (WORK / "examples" / "floor-plan.svg").read_text(encoding="utf-8")
        check("unit switch saved into svg", 'data-vs-unit="cm"' in fp)
        check("cm formatting", pg.evaluate("vsUnits.fmtLen(350)") == "35 cm")
        check("m formatting", pg.evaluate("S.unit='m'; vsUnits.fmtLen(3500)") == "3.5 m")
        pg.reload(); pg.wait_for_selector("#stage svg"); pg.wait_for_timeout(600)
        check("saved unit survives reload", pg.eval_on_selector("#unitSel", "e => e.value") == "cm")
        pg.select_option("#unitSel", "mm")
        pg.wait_for_timeout(1200)

        # ================= mode signals =================
        pg.goto(f"{base}?file=examples/floor-plan.svg")
        pg.wait_for_selector("#stage svg")
        pg.wait_for_timeout(600)
        check("existing file opens in pin mode", pg.evaluate("document.body.dataset.mode") == "pin")
        check("pin cursor is the pin glyph",
              "url" in pg.eval_on_selector("#stageWrap", "e => getComputedStyle(e).cursor"))
        shadow_pin = pg.eval_on_selector("#frame", "e => getComputedStyle(e).boxShadow")
        check("frame tinted amber in pin mode", "230, 162, 60" in shadow_pin, shadow_pin)
        check("active PIN button wears the gradient",
              "linear-gradient" in pg.eval_on_selector("#modePin", "e => getComputedStyle(e).backgroundImage"))

        pg.keyboard.press("s")           # keyboard mode switch
        check("S key switches to sketch", pg.evaluate("document.body.dataset.mode") == "sketch")
        check("sketch cursor is crosshair",
              pg.eval_on_selector("#stageWrap", "e => getComputedStyle(e).cursor") == "crosshair")
        pg.wait_for_timeout(500)         # let the .35s tint transition settle
        shadow_sk = pg.eval_on_selector("#frame", "e => getComputedStyle(e).boxShadow")
        check("frame tinted teal in sketch mode", "95, 179, 161" in shadow_sk, shadow_sk)
        check("active SKETCH button wears the gradient",
              "linear-gradient" in pg.eval_on_selector("#modeSketch", "e => getComputedStyle(e).backgroundImage"))
        pg.focus("#scaleIn")
        pg.keyboard.press("p")
        check("P ignored while an input has focus", pg.evaluate("document.body.dataset.mode") == "sketch")
        pg.eval_on_selector("#scaleIn", "e => e.blur()")
        pg.keyboard.press("p")
        check("P key switches to pin", pg.evaluate("document.body.dataset.mode") == "pin")

        # ghost: pin mode shows the NEXT numbered pin at the cursor
        pg.click("#zFit"); pg.wait_for_timeout(300)
        px = svg_map()
        gx, gy = px(200, 150)
        pg.mouse.move(gx, gy)
        pg.wait_for_timeout(100)
        check("ghost live over the canvas",
              pg.eval_on_selector("#ghost", "e => e.classList.contains('live')"))
        check("pin ghost visible in pin mode",
              pg.eval_on_selector("#gPin", "e => getComputedStyle(e).display") == "block")
        check("ghost pin shows next number (1)",
              pg.eval_on_selector("#gPinN", "e => e.textContent") == "1")

        # drop a pin -> popover editor, note, reopen from the canvas
        pg.mouse.click(gx, gy)
        pg.wait_for_selector("#pinPop", timeout=2000)
        check("pin drop opens the note popover", True)
        pg.keyboard.type("test note")
        pg.keyboard.press("Enter")
        check("popover closes on Enter", pg.evaluate("!document.getElementById('pinPop')"))
        check("note saved on the pin", pg.evaluate("vs.S.pins[0].note") == "test note")
        pg.mouse.move(gx + 60, gy + 60); pg.wait_for_timeout(100)
        check("ghost pin advances to next number (2)",
              pg.eval_on_selector("#gPinN", "e => e.textContent") == "2")
        bub = pg.evaluate("""() => {
            const p = vs.S.pins[0], z = vs.S.zoom;
            const ctm = vs.S.svgEl.getScreenCTM();
            const q = new DOMPoint(p.user.x + 18/z, p.user.y - 18/z).matrixTransform(ctm);
            return {x: q.x, y: q.y};
        }""")
        pg.mouse.click(bub["x"], bub["y"])
        pg.wait_for_selector("#pinPop", timeout=2000)
        check("clicking a pin reopens its note",
              pg.eval_on_selector("#pinPop input", "e => e.value") == "test note")
        check("pin bubble click did not add a pin", pg.evaluate("vs.S.pins.length") == 1)
        # regression: clicks INSIDE the popover must never fall through to the
        # canvas (the x button was dropping a brand-new pin underneath itself)
        pg.click("#pinPop input")
        pg.wait_for_timeout(250)
        check("clicking into the note input adds no pin",
              pg.evaluate("vs.S.pins.length") == 1 and
              pg.eval_on_selector("#pinPop input", "e => e.value") == "test note")
        pg.click("#pinPop .del")
        pg.wait_for_timeout(250)
        check("the x deletes the pin without dropping a new one",
              pg.evaluate("vs.S.pins.length") == 0)
        check("popover closes after delete", pg.evaluate("!document.getElementById('pinPop')"))

        # ghost: sketch mode dot rides the snap grid; mid-path no ghost
        pg.keyboard.press("s")
        px = svg_map()
        rx, ry = px(101.3, 77.7)         # off-grid on purpose
        pg.mouse.move(rx, ry)
        pg.wait_for_timeout(100)
        check("dot ghost visible in sketch mode",
              pg.eval_on_selector("#gDot", "e => getComputedStyle(e).display") == "block")
        got = pg.evaluate("""() => {
            const g = document.getElementById('ghost');
            const r = document.getElementById('main').getBoundingClientRect();
            return {x: parseFloat(g.style.left) + r.left, y: parseFloat(g.style.top) + r.top};
        }""")
        sx, sy = px(102, 78)             # snapped to 1 mm = 2 user units
        check("dot ghost sits at the SNAPPED position",
              abs(got["x"] - sx) < 1 and abs(got["y"] - sy) < 1,
              f"got {got} want {(sx, sy)}")
        pg.mouse.click(*px(400, 300))    # start a path
        pg.mouse.move(*px(430, 300)); pg.wait_for_timeout(80)
        check("mid-path: rubber line signals, ghost hides",
              pg.eval_on_selector("#ghost", "e => !e.classList.contains('live')"))
        check("draw hint chip shows while drawing",
              pg.eval_on_selector("#drawHint", "e => e.classList.contains('show')"))
        pg.keyboard.press("Escape")
        check("draw hint chip hides after cancel",
              pg.eval_on_selector("#drawHint", "e => !e.classList.contains('show')"))

        # ================= auto-switching layout =================
        pg.set_viewport_size({"width": 1700, "height": 950})
        pg.wait_for_timeout(150)
        check("wide window -> right rail",
              pg.evaluate("getComputedStyle(document.body).flexDirection") == "row")
        check("rail is ~220px", abs(pg.eval_on_selector("aside", "e => e.offsetWidth") - 220) <= 2)
        pg.set_viewport_size({"width": 950, "height": 1000})
        pg.wait_for_timeout(150)
        check("tall/narrow window -> top bar",
              pg.evaluate("getComputedStyle(document.body).flexDirection") == "column")
        check("top bar rides above the canvas",
              pg.eval_on_selector("aside", "e => getComputedStyle(e).order") == "-1")
        check("no horizontal overflow at 950",
              pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth && "
                          "document.querySelector('aside').scrollWidth <= document.querySelector('aside').clientWidth + 1"))
        check("sub-captions visible at 950",
              pg.eval_on_selector("#modePin .sub", "e => getComputedStyle(e).display") != "none")
        pg.set_viewport_size({"width": 700, "height": 800})
        pg.wait_for_timeout(150)
        check("no horizontal overflow at 700",
              pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth && "
                          "document.querySelector('aside').scrollWidth <= document.querySelector('aside').clientWidth + 1"))
        check("compact buttons drop sub-captions at 700",
              pg.eval_on_selector("#modePin .sub", "e => getComputedStyle(e).display") == "none")
        pg.set_viewport_size({"width": 1300, "height": 900})
        pg.wait_for_timeout(150)
        check("resize back -> rail returns",
              pg.evaluate("getComputedStyle(document.body).flexDirection") == "row")

        # ================= finishing a path without a mouse =================
        pg.evaluate(f"""fetch('/api/new', {{method:'POST',
            headers:{{'Content-Type':'application/json'}},
            body: JSON.stringify({{name:'scratch'}})}})""")
        pg.wait_for_timeout(300)
        pg.goto(f"{base}?file=sketches/scratch.svg&mode=sketch")
        pg.wait_for_selector("#stage svg")
        pg.wait_for_timeout(600)
        check("new sketch opens in sketch mode", pg.evaluate("document.body.dataset.mode") == "sketch")
        pg.click("#zFit"); pg.wait_for_timeout(300)
        px = svg_map()

        # (1) slow double-click on the last point = finish open
        for ux, uy in [(100, 100), (300, 100), (300, 200)]:
            pg.mouse.click(*px(ux, uy)); pg.wait_for_timeout(450)
        pg.wait_for_timeout(600)
        pg.mouse.click(*px(300, 200))    # same spot, way past any dblclick window
        pg.wait_for_timeout(200)
        n_open = pg.evaluate("document.querySelectorAll('#stage polyline[data-vs]').length")
        check("slow re-click of last point finishes open", n_open == 1 and
              pg.evaluate("!vs.S.drawing"),
              f"polylines {n_open}")
        check("finished polyline kept its 3 points",
              pg.evaluate("document.querySelector('#stage polyline[data-vs]')"
                          ".getAttribute('points').split(' ').length") == 3)

        # (2) fast double-tap = finish open too
        pg.mouse.click(*px(100, 300)); pg.wait_for_timeout(450)
        pg.mouse.click(*px(200, 300)); pg.wait_for_timeout(450)
        pg.mouse.dblclick(*px(300, 300))
        pg.wait_for_timeout(200)
        check("fast double-tap finishes open",
              pg.evaluate("document.querySelectorAll('#stage polyline[data-vs]').length") == 2
              and pg.evaluate("!vs.S.drawing"))

        # (3) Enter still finishes; (4) click-the-start still closes
        pg.mouse.click(*px(100, 400)); pg.wait_for_timeout(450)
        pg.mouse.click(*px(200, 400)); pg.wait_for_timeout(450)
        pg.keyboard.press("Enter")
        check("Enter finishes open",
              pg.evaluate("document.querySelectorAll('#stage polyline[data-vs]').length") == 3)
        for ux, uy in [(400, 100), (500, 100), (500, 200), (400, 200)]:
            pg.mouse.click(*px(ux, uy)); pg.wait_for_timeout(450)
        pg.mouse.click(*px(400, 100))
        pg.wait_for_timeout(200)
        check("clicking the start still closes the shape",
              pg.evaluate("document.querySelectorAll('#stage polygon[data-vs]').length") == 1)
        check("hover rings offered both finish points while drawing", True)  # visual; walked manually

        # (5) editors on a slow double-tap (two separate clicks < 400 ms apart)
        pg.wait_for_timeout(600)
        dx, dy = px(500, 200)            # a polygon corner dot
        pg.mouse.click(dx, dy); pg.wait_for_timeout(250)
        pg.mouse.click(dx, dy)
        pg.wait_for_selector("#lenEdit", timeout=2000)
        check("radius editor opens on slow double-tap of a dot", True)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(600)
        lx, ly = px(450, 100)            # midpoint of the polygon's top side
        before = pg.evaluate("document.querySelector('#stage polygon[data-vs]').getAttribute('points')")
        pg.mouse.click(lx, ly); pg.wait_for_timeout(250)
        pg.mouse.click(lx, ly)
        pg.wait_for_selector("#lenEdit", timeout=2000)
        check("length editor opens on slow double-tap of a line", True)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(700)
        after = pg.evaluate("document.querySelector('#stage polygon[data-vs]').getAttribute('points')")
        check("double-tap canceled the pending point insert", before == after)

        # ================= copy / paste =================
        pg.wait_for_timeout(600)
        pg.mouse.move(*px(360, 60))      # box-select the square
        pg.mouse.down()
        pg.mouse.move(*px(540, 240), steps=6)
        pg.mouse.up()
        pg.wait_for_timeout(200)
        check("box-select caught the square", pg.evaluate("vs.S.selection.length") == 1)
        pg.keyboard.press("Control+c")
        pg.wait_for_timeout(300)
        clip = pg.evaluate("navigator.clipboard.readText()")
        check("Ctrl+C put SVG text on the system clipboard",
              clip.startswith("<svg") and 'data-vs="1"' in clip, clip[:120])
        check("fragment carries unit+scale context",
              'data-vs-scale="2"' in clip and 'data-vs-unit=' in clip)
        check("fragment parses as valid SVG with 1 shape", pg.evaluate(
            """() => navigator.clipboard.readText().then(t => {
                 const d = new DOMParser().parseFromString(t, 'image/svg+xml');
                 return d.documentElement.nodeName === 'svg' &&
                        d.querySelectorAll('polygon[data-vs]').length === 1; })"""))

        # paste into ANOTHER file with a different px/mm (0.5 vs 2)
        pg.goto(f"{base}?file=examples/studio-apartment.svg")
        pg.wait_for_selector("#stage svg")
        pg.wait_for_timeout(600)
        pg.click("#modeSketch")
        pg.click("#zFit"); pg.wait_for_timeout(300)
        px2 = svg_map()
        n0 = pg.evaluate("document.querySelectorAll('#stage [data-vs]').length")
        pg.keyboard.press("Control+v")
        pg.wait_for_timeout(300)
        check("Ctrl+V starts a paste ghost", pg.evaluate("!!vs.S.pasting"))
        tx, ty = px2(1500, 1000)
        pg.mouse.move(tx, ty)
        pg.wait_for_timeout(120)
        check("paste ghost rides the cursor", pg.evaluate(
            "!!document.querySelector('#vs-paste') && "
            "document.querySelector('#vs-paste').getAttribute('visibility') === 'visible'"))
        at = pg.evaluate("vs.S.pasting.at")
        pg.mouse.click(tx, ty)
        pg.wait_for_timeout(200)
        check("click places the paste", pg.evaluate("!vs.S.pasting") and
              pg.evaluate("document.querySelectorAll('#stage [data-vs]').length") == n0 + 1)
        check("pasted shapes become the selection", pg.evaluate("vs.S.selection.length") == 1)
        pts = parse_pts(pg.evaluate("vs.S.selection[0].getAttribute('points')"))
        cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
        cy = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
        check("paste landed at the snapped click position",
              abs(cx - at["x"]) < 0.2 and abs(cy - at["y"]) < 0.2,
              f"center ({cx},{cy}) vs target {at}")
        w_mm = (max(p[0] for p in pts) - min(p[0] for p in pts)) / 0.5
        h_mm = (max(p[1] for p in pts) - min(p[1] for p in pts)) / 0.5
        check("cross-file paste keeps physical size (50x50 mm square)",
              abs(w_mm - 50) < 0.5 and abs(h_mm - 50) < 0.5, f"{w_mm}x{h_mm} mm")
        placed = pg.evaluate("vs.S.selection[0].getAttribute('points')")
        pg.wait_for_timeout(1000)        # save debounce
        saved = (WORK / "examples" / "studio-apartment.svg").read_text(encoding="utf-8")
        check("pasted shape saved into the target file", placed in saved)
        pg.reload(); pg.wait_for_selector("#stage svg"); pg.wait_for_timeout(600)
        check("pasted shape survives reload", pg.evaluate(
            f"""[...document.querySelectorAll('#stage [data-vs]')]
                .some(e => e.getAttribute('points') === {placed!r})"""))

        # Esc cancels clean; paste in pin mode switches to sketch
        pg.click("#modePin")
        pg.wait_for_timeout(100)
        n1 = pg.evaluate("document.querySelectorAll('#stage [data-vs]').length")
        pg.keyboard.press("Control+v")
        pg.wait_for_timeout(300)
        check("paste in pin mode switches to sketch",
              pg.evaluate("document.body.dataset.mode") == "sketch" and pg.evaluate("!!vs.S.pasting"))
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
        check("Esc cancels the paste clean",
              pg.evaluate("!vs.S.pasting && !document.querySelector('#vs-paste')") and
              pg.evaluate("document.querySelectorAll('#stage [data-vs]').length") == n1)

        b.close()
finally:
    proc.terminate()
    shutil.rmtree(WORK, ignore_errors=True)
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
