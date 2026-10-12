"""Headless UI check: python tests/ui_headless.py <built.html>  (run with the repo .venv python)."""
import sys, os, threading, http.server, socketserver, functools, json
from playwright.sync_api import sync_playwright
path = os.path.abspath(sys.argv[1]); d, f = os.path.split(path)
out = os.path.join(os.path.dirname(__file__), "out"); os.makedirs(out, exist_ok=True)
H = functools.partial(http.server.SimpleHTTPRequestHandler, directory=d)
H.log_message = lambda *a, **k: None
srv = socketserver.TCPServer(("127.0.0.1", 0), H); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
res = {}
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1400, "height": 900})
    errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "fonts" not in m.text and "ERR_" not in m.text else None)
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/fonts.g*/**", lambda r: r.abort())
    pg.goto(f"http://127.0.0.1:{port}/{f}", wait_until="domcontentloaded")
    def rendered(t=120000):
        pg.wait_for_function("document.querySelector('#status').textContent.startsWith('Rendered') || document.querySelector('#status').textContent.startsWith('Rendering failed')", timeout=t)
        return pg.inner_text("#status")
    res["title"] = pg.title(); res["h1"] = pg.inner_text("h1")
    res["cards"] = pg.eval_on_selector_all(".card", "e=>e.map(x=>[x.dataset.id,x.disabled])")
    for sid in ["home", "factory", "hospital", "automobile", "custom"]:
        pg.click(f"#card_{sid}"); res["scene_" + sid] = rendered()
        res["spk_" + sid] = pg.eval_on_selector_all(".spk", "e=>e.length")
        res["noi_" + sid] = pg.eval_on_selector_all(".nsrc", "e=>e.length")
    pg.click("#card_home"); rendered()
    for _ in range(6): pg.dispatch_event("#addSpk", "click")
    res["speakers_after_6_adds"] = pg.eval_on_selector_all(".spk", "e=>e.length"); res["refusal"] = pg.inner_text("#status")
    pg.select_option("#k_micCount", "16"); res["warn16"] = pg.inner_text("#micWarn") if pg.is_visible("#micWarn") else None
    res["mics_drawn"] = pg.eval_on_selector_all("#head .mic", "e=>e.length")
    rendered(); res["mics_in_res"] = pg.evaluate("__ui.RES.mics.length"); res["micPositions_in_res"] = pg.evaluate("__ui.RES.micPositions.length")
    res["hears"] = pg.inner_text("#hears")
    pg.select_option("#k_micCount", "8"); res["warn8_visible"] = pg.is_visible("#micWarn")
    pg.screenshot(path=os.path.join(out, "ui_1400.png"), full_page=True)
    pg.focus("#k_roomL"); pg.keyboard.press("ArrowRight"); res["kbd_roomL"] = pg.evaluate("__ui.P.roomL")
    pg.focus("#head .ent"); pg.keyboard.press("ArrowLeft"); res["marker_focus_kept"] = pg.evaluate("document.activeElement.getAttribute('data-fid')")
    res["overflow_1400"] = pg.evaluate("document.documentElement.scrollWidth - innerWidth")
    pg.set_viewport_size({"width": 400, "height": 800}); pg.wait_for_timeout(300)
    res["overflow_400"] = pg.evaluate("document.documentElement.scrollWidth - innerWidth")
    pg.screenshot(path=os.path.join(out, "ui_400.png"), full_page=True)
    res["errors"] = errs
    b.close()
print(json.dumps(res, indent=1))
