"""3D view of the Scene Simulator page: drawing, presets, orbit, zoom, keyboard, and dragging a source's height.

    python tests/ui_3d.py [built.html]      (CHROMIUM=/path/to/chrome to choose the browser; ~1 min)
"""
import functools, http.server, os, shutil, socketserver, sys, tempfile, threading
from playwright.sync_api import sync_playwright

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(WEB, "robot_acoustic.html")
D = tempfile.mkdtemp(); shutil.copy(PAGE, os.path.join(D, "index.html"))


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=D))
threading.Thread(target=srv.serve_forever, daemon=True).start()
fails = []


def ok(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)
    if not c:
        fails.append(m)


with sync_playwright() as p:
    b = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    pg = b.new_page(viewport={"width": 1300, "height": 1000}); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/fonts.g*/**", lambda r: r.abort())
    pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html")

    def settled():
        pg.wait_for_timeout(700)
        pg.wait_for_function("__ui.RP && JSON.stringify(__ui.RP)===JSON.stringify(__ui.P) && /^Rendered/.test(document.querySelector('#status').textContent)", timeout=180000)

    settled()
    ok(pg.is_hidden("#v3") and pg.get_attribute("#v3toggle", "aria-expanded") == "false" and pg.inner_text("#v3toggle") == "Show 3D view",
       "3D view hidden at first; button says Show 3D view")
    pg.click("#v3toggle"); pg.wait_for_timeout(300)
    ok(pg.is_visible("#v3") and pg.get_attribute("#v3toggle", "aria-expanded") == "true" and pg.inner_text("#v3toggle") == "Hide 3D view",
       "clicking it expands the 3D view")
    ink = pg.evaluate("""(() => { const c = document.getElementById('v3'), g = c.getContext('2d'), d = g.getImageData(0, 0, c.width, c.height).data;
        const bg = [d[0], d[1], d[2]]; let n = 0; for (let i = 0; i < d.length; i += 16) if (Math.abs(d[i] - bg[0]) + Math.abs(d[i+1] - bg[1]) + Math.abs(d[i+2] - bg[2]) > 40) n++; return n; })()""")
    ok(ink > 500, f"3D view draws the scene ({ink} sampled pixels drawn)")
    lab = pg.get_attribute("#v3", "aria-label")
    ok("5 × 4 × 2.6 m room" in lab and "Speaker 1" in lab and "Robot head (array) 1.30 m" in lab, "description lists the room, robot head height and source heights")
    ok(pg.get_attribute('[data-v3="3d"]', "aria-pressed") == "true", "3D preset selected at start")
    for pr in ("top", "front", "side", "3d"):
        pg.click(f'[data-v3="{pr}"]')
        ok(pg.get_attribute(f'[data-v3="{pr}"]', "aria-pressed") == "true", f"preset {pr}")
    box = pg.locator("#v3").bounding_box()
    # orbit: drag on empty space (a corner of the canvas)
    y0 = pg.evaluate("__ui.v3.yaw")
    pg.mouse.move(box["x"] + 8, box["y"] + 8); pg.mouse.down(); pg.mouse.move(box["x"] + 108, box["y"] + 28, steps=5); pg.mouse.up()
    ok(abs(pg.evaluate("__ui.v3.yaw") - y0) > 0.3 and pg.evaluate("__ui.P.speakers[0].el") == 5, "drag on empty space turns the view (speakers unchanged)")
    z0 = pg.evaluate("__ui.v3.zoom"); pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2); pg.mouse.wheel(0, -300)
    ok(pg.evaluate("__ui.v3.zoom") > z0, "scroll zooms in")
    pg.focus("#v3"); y1 = pg.evaluate("__ui.v3.yaw"); pg.keyboard.press("ArrowLeft"); pg.keyboard.press("+")
    ok(pg.evaluate("__ui.v3.yaw") > y1, "keyboard turns the view")
    # lift speaker 1: drag its marker up in the 3D preset
    pg.click('[data-v3="3d"]')
    dpr = pg.evaluate("window.devicePixelRatio")
    it = pg.evaluate("(() => { const h = __ui.v3.items.find(h => h.it.kind === 'spk' && h.it.i === 0); return [h.x, h.y]; })()")
    az0, el0 = pg.evaluate("__ui.P.speakers[0].az"), pg.evaluate("__ui.P.speakers[0].el")
    sx, sy = box["x"] + it[0] / dpr, box["y"] + it[1] / dpr
    pg.mouse.move(sx, sy); pg.mouse.down(); pg.mouse.move(sx, sy - 60, steps=6); pg.mouse.up(); settled()
    s1 = pg.evaluate("__ui.P.speakers[0]"); src = pg.evaluate("__ui.RES.sources.find(s => s.id === 's1')")
    ok(s1["el"] > el0 + 5 and s1["az"] == az0, f"dragging speaker 1 up raises it: elevation {el0}° -> {s1['el']}°, direction kept {az0}°")
    ok(abs(src["el"] - s1["el"]) < 1, f"the new height reaches the render (engine el {src['el']:.1f}°)")
    ok(pg.input_value("#k_s1_el") == str(s1["el"]), "elevation slider follows")
    # top preset: height dragging is off (vertical motion has no height meaning from above)
    pg.click('[data-v3="top"]'); it = pg.evaluate("(() => { const h = __ui.v3.items.find(h => h.it.kind === 'spk' && h.it.i === 0); return [h.x, h.y]; })()")
    el1 = s1["el"]; sx, sy = box["x"] + it[0] / dpr, box["y"] + it[1] / dpr
    hint = pg.inner_text("#v3hint")
    pg.mouse.move(sx, sy); pg.mouse.down(); pg.mouse.move(sx, sy - 50, steps=5); pg.mouse.up(); pg.wait_for_timeout(300)
    ok(pg.evaluate("__ui.P.speakers[0].el") == el1 and "from above" in hint, "Top preset: dragging turns the view instead of changing height; hint says why")
    # editing in the 2D view / sliders updates the 3D view
    pg.click('[data-v3="3d"]'); before = pg.get_attribute("#v3", "aria-label")
    pg.evaluate("(() => { const e = document.getElementById('k_s2_el'); e.value = 40; e.dispatchEvent(new Event('input', {bubbles: true})); })()")
    ok(pg.get_attribute("#v3", "aria-label") != before, "changing a slider updates the 3D view at once")
    pg.reload(); pg.wait_for_function("/^Rendered/.test(document.querySelector('#status').textContent)", timeout=180000)
    ok(pg.is_visible("#v3"), "the choice is remembered after a reload")
    pg.click("#v3toggle"); pg.wait_for_timeout(200)
    ok(pg.is_hidden("#v3") and pg.inner_text("#v3toggle") == "Show 3D view" and pg.evaluate("document.documentElement.scrollWidth - innerWidth") <= 0,
       "Hide 3D view collapses it again")
    ok(not errs, "no page errors" + (f": {errs[:3]}" if errs else ""))
    b.close()

shutil.rmtree(D, ignore_errors=True)
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED")
sys.exit(1 if fails else 0)
