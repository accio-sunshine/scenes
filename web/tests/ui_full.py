"""Full end-to-end test of the Scene Simulator page: every scene, knob, button, track, download and the Python check.

    python tests/ui_full.py [built.html]          (default: robot_acoustic.html next to this folder)

Serves the page with the repo's WAV folders under audio/ (as published), drives it with Playwright/Chromium and checks
the page state after every action. Set CHROMIUM=/path/to/chrome to use a specific browser (cloud containers:
/opt/pw-browsers/chromium). Prints PASS/FAIL per check and exits 1 on any failure. Takes several minutes (each change
re-renders the 8-mic scene).
"""
import functools
import http.server
import io
import json
import os
import shutil
import socketserver
import sys
import tempfile
import threading
import zipfile

import numpy as np
import soundfile as sf
from playwright.sync_api import sync_playwright

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(WEB)
PAGE = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(WEB, "robot_acoustic.html")
PY = json.load(open(os.path.join(WEB, "src", "python_scores.json")))["scenes"]

fails = []


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        fails.append(msg)


# ---------------------------------------------------------------- serve like the published artifact
site = tempfile.mkdtemp()
shutil.copy(PAGE, os.path.join(site, "index.html"))
os.makedirs(os.path.join(site, "audio"))
for d in ("sim_conversation_out", "sim_noise_out", "python_out"):
    shutil.copytree(os.path.join(ROOT, d), os.path.join(site, "audio", d))
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


H = functools.partial(Quiet, directory=site)
srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/index.html"

with sync_playwright() as p:
    launch = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    b = p.chromium.launch(**launch)
    pg = b.new_page(viewport={"width": 1300, "height": 900}, accept_downloads=True)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "fonts" not in m.text and "ERR_" not in m.text else None)
    pg.route("**/fonts.g*/**", lambda r: r.abort())
    pg.goto(URL)

    def settled(t=180000):
        """Wait until the latest settings have been rendered (RP == P) and the status says Rendered."""
        pg.wait_for_timeout(600)   # past the 450 ms debounce
        pg.wait_for_function("__ui.RP && JSON.stringify(__ui.RP) === JSON.stringify(__ui.P) && "
                             "document.querySelector('#status').textContent.startsWith('Rendered')", timeout=t)

    def ev(js):
        return pg.evaluate(js)

    def set_range(i, v):
        pg.evaluate(f"(() => {{ const e = document.getElementById({json.dumps(i)}); e.value = {v}; e.dispatchEvent(new Event('input', {{bubbles: true}})); }})()")

    def range_val(i):
        return float(ev(f"document.getElementById({json.dumps(i)}).value"))

    def scene(sid, pid=None):
        pg.click(f"#card_{sid}")
        if pid:
            pg.click(f'#presets button[data-id="{pid}"]')
        settled()

    def python_cells():
        return ev("""[...document.querySelectorAll('#scoreTable tbody tr')].map(tr => [...tr.querySelectorAll('td.pyc')].map(td => [td.className, td.querySelector('b') ? td.querySelector('b').textContent : null]))""")

    def fmt(v):
        return ("+" if v >= 0 else "−") + f"{abs(v):.1f}"

    settled()
    ok(pg.title() == "Scene Simulator" and pg.inner_text("h1") == "Scene Simulator", "title and heading")

    # ------------------------------------------------------------ 1. every scene: Python column values, colours, recordings
    for sid, pid in [("home", None), ("factory", None), ("hospital", None), ("automobile", None),
                     ("custom", "baby"), ("custom", "fan"), ("custom", "robot"), ("custom", "quiet")]:
        key = pid or sid
        scene(sid, pid)
        S, py = ev("__ui.RES.scores"), PY[key]
        # page scores at defaults must equal what the Python run recorded (else python_scores.json is stale)
        stale = [k for k, v in py["page_at_run"].items() if abs(S.get(k, 1e9) - v) > 0.02]
        ok(not stale, f"{key}: page scores match the scores recorded with the Python run" + (f" (differ: {stale})" if stale else ""))
        tg = [s for s in ev("__ui.RP.speakers") if s["target"]]
        cells = python_cells()
        cols = [c for c in ["mic", "das", "mvdr", "learned"] if any((f"mic_{s['id']}" if c == "mic" else f"{s['id']}_{c}") in S for s in tg)]
        good = True
        for r, s in enumerate(tg):
            for c, k in enumerate(cols):
                sk = f"mic_{s['id']}" if k == "mic" else f"{s['id']}_{k}"
                cls, txt = cells[r][c]
                d = abs(S[sk] - py["scores"][sk])
                want = "near" if d < 1 else "mid" if d <= 2 else "far"
                shown = float(txt.replace("−", "-").replace(" dB", "")) if txt else None   # JS rounds 3.25 up, Python to even
                if shown is None or abs(shown - py["scores"][sk]) > 0.051 or want not in cls:
                    good = False
                    print("   cell", key, sk, cls, txt, "want", fmt(py["scores"][sk]), want)
        ok(good and len(cells) == len(tg), f"{key}: Python column shows the stored values with the right colour ({len(tg)} speakers x {len(cols)} methods)")
        ok(pg.is_visible("#scoreKey"), f"{key}: colour key shown")
        vis = ev("[...document.querySelectorAll('#pyList details')].filter(d => d.offsetParent).map(d => d.dataset.scene)")
        want_groups = {key} | ({"custom"} if sid == "custom" else set())
        if key == "quiet":
            want_groups = {"custom"}
        ok(set(vis) == want_groups, f"{key}: Python recording groups shown {sorted(set(vis))}")
        keys = ev(f"[...document.querySelectorAll('#pyList details[data-scene=\"{key}\"] li')].map(li => li.dataset.key)")
        bad = 0
        for k in keys:
            pg.dispatch_event(f'#pyList li[data-key="{k}"] .tt', "click")
            pg.wait_for_function(f"__ui.view && __ui.view.key === {json.dumps(k)}", timeout=30000)
            a = np.array(ev("Array.from(__ui.view.arr)"))
            ref, _ = sf.read(os.path.join(ROOT, k[3:]))
            bad += not (len(a) == len(ref) and np.max(np.abs(a - ref)) < 1e-4)
        ok(bad == 0 and (keys or key == "quiet"), f"{key}: {len(keys)} Python recordings load and decode exactly")

    # ------------------------------------------------------------ 2. editing hides the Python column, reselecting restores it
    scene("factory")
    set_range("k_rt60", 1.0)
    settled()
    ok(not python_cells() or all(not r for r in python_cells()), "edited scene: Python column hidden")
    ok("hidden" in pg.inner_text("#scoreNote"), "edited scene: note explains why")
    scene("factory")
    ok(len(python_cells()) == 2 and all(len(r) == 4 for r in python_cells()), "reselecting the scene restores the Python column")

    # ------------------------------------------------------------ 3. room knobs
    scene("home")
    for i, v, k in [("k_roomL", 7.0, "L"), ("k_roomW", 6.0, "W"), ("k_roomH", 3.0, "H")]:
        set_range(i, v)
        settled()
        ok(abs(ev(f"__ui.RES.room.{k}") - v) < 1e-9 and abs(ev(f"__ui.P.room{k}") - v) < 1e-9, f"room {k} -> {v} m reaches the engine")
    ok(abs(ev("__ui.P.arrayX") - 3.5) < 1e-9 and abs(ev("__ui.P.arrayY") - 3.0) < 1e-9, "array re-centred with 'Put the array at the room centre' on")
    set_range("k_rt60", 0.9); settled()
    ok(abs(ev("__ui.RES.room.rt60") - 0.9) < 1e-9, "echo time reaches the engine")
    set_range("k_damping", 0.4); settled()
    ok(abs(ev("__ui.RES.room.damping") - 0.4) < 1e-9 and abs(ev("__ui.RES.room.rt60Hf") - 0.9 * 0.7) < 1e-9, "damping reaches the engine (rt60Hf)")
    m0 = ev("__ui.RES.scores.mic_s1")
    set_range("k_roomDb", 10); settled()
    ok(ev("__ui.RES.scores.mic_s1") < m0, f"noise floor up (-10 dB) lowers the mic-1 score ({m0:.1f} -> {ev('__ui.RES.scores.mic_s1'):.1f})")
    set_range("k_roomL", 1.0); settled()
    ok(ev("__ui.RES.room.L") == 1.0 and all(np.isfinite(ev("Object.values(__ui.RES.scores)"))), "1 m room: renders with finite scores")
    ok(pg.is_visible("#warns"), "1 m room: speakers moved inside are reported")

    # ------------------------------------------------------------ 4. microphones
    scene("home")
    for n in (4, 6, 12, 16, 8):
        pg.select_option("#k_micCount", str(n)); settled()
        drawn = ev("document.querySelectorAll('#head .mic').length")
        ok(ev("__ui.RES.mics.length") == n and drawn == n and ev("document.querySelectorAll('#micList li').length") == n
           and pg.is_visible("#micWarn") == (n != 8), f"{n} mics: rendered, drawn, listed; warning {'shown' if n != 8 else 'hidden'}")
    pg.select_option("#k_arrayShape", "dual_ring"); settled()
    z = [q[2] for q in ev("__ui.RES.micPositions")]
    ok(all(v < 0 for v in z[:4]) and all(v > 0 for v in z[4:]) and not ev("document.getElementById('k_ringGap').disabled"), "dual ring: lower/upper rings, gap knob enabled")
    set_range("k_ringGap", 12); settled()
    ok(abs(ev("__ui.RES.micPositions[4][2]") - 0.06) < 1e-6, "ring gap 12 cm reaches the engine")
    ok(all(q["el"] is not None for q in ev("__ui.RES.srp.peaks")), "dual ring: SRP reports elevations")
    pg.select_option("#k_arrayShape", "ring"); settled()
    ok(ev("document.getElementById('k_ringGap').disabled") and all(q["el"] is None for q in ev("__ui.RES.srp.peaks")), "ring: gap disabled, SRP elevation unknown")
    set_range("k_radius", 8); settled()
    ok(abs(ev("Math.hypot(__ui.RES.micPositions[0][0], __ui.RES.micPositions[0][1])") - 0.08) < 1e-6, "ring radius 8 cm reaches the engine")
    pg.uncheck("#k_arrayAuto"); set_range("k_arrayX", 1.5); settled()
    ok(abs(ev("__ui.RES.geometry.centre[0]") - 1.5) < 1e-9 and not ev("document.getElementById('k_arrayAuto').checked"), "array position knob moves the array")
    set_range("k_arrayH", 1.0); settled()
    ok(abs(ev("__ui.RES.geometry.centre[2]") - 1.0) < 1e-9, "array height knob")
    pg.check("#k_arrayAuto"); settled()
    ok(abs(ev("__ui.P.arrayX") - 2.5) < 1e-9, "re-ticking 'room centre' re-centres the array")

    # ------------------------------------------------------------ 5. speakers
    scene("home")
    for _ in range(5 - ev("__ui.P.speakers.length")):
        pg.click("#addSpk")
    settled()
    ok(ev("__ui.RES.sources.filter(s => s.kind === 'speaker').length") == 5 and ev("document.querySelectorAll('.spk').length") == 5, "add speakers up to 5")
    pg.dispatch_event("#addSpk", "click")   # marked aria-disabled at 5, but still announces why
    ok("Up to 5" in pg.inner_text("#status") and ev("__ui.P.speakers.length") == 5, "6th speaker refused")
    ok(len(ev("__ui.RES.srp.peaks")) == 5, "SRP looks for 5 sources")
    pg.select_option("#k_s3_voice", "baby"); settled()
    ok(ev("__ui.RES.sources.find(s => s.id === 's3').voice") == "baby", "voice select")
    pg.uncheck("#k_s3_target"); settled()
    ok("s3_mvdr" not in ev("__ui.RES.scores") and ev("document.querySelectorAll('#scoreTable tbody tr').length") == 4, "interferer is not scored (4 rows)")
    set_range("k_s2_az", 90); set_range("k_s2_el", 30); set_range("k_s2_dist", 1.2); set_range("k_s2_db", -6); set_range("k_s2_start", 1.0)
    settled()
    s2 = ev("__ui.RES.sources.find(s => s.id === 's2')")
    ok(abs(s2["az"] - 90) < 0.5 and abs(s2["el"] - 30) < 0.5 and abs(s2["dist"] - 1.2) < 0.01 and abs(ev("__ui.RES.talk.s2[0]") - 1.0) < 1e-9,
       "speaker 2 azimuth/elevation/distance/start reach the engine")
    ok(ev("document.getElementById('k_s1_db').disabled"), "speaker 1 loudness is the fixed reference")
    pg.click("#rm_s5"); pg.click("#rm_s4"); settled()
    ok(ev("__ui.P.speakers.length") == 3 and ev("__ui.P.speakers.map(s => s.id).join()") == "s1,s2,s3", "remove speakers, ids renumbered")

    # ------------------------------------------------------------ 6. ambient noise sources
    scene("factory")
    nids = ev("__ui.P.noises.map(n => n.id)")
    pg.uncheck(f"#k_{nids[0]}_on"); settled()
    ok(not any(s["id"] == nids[0] for s in ev("__ui.RES.sources")), "noise checkbox off removes the source")
    pg.check(f"#k_{nids[0]}_on"); set_range(f"k_{nids[0]}_db", -20); settled()
    ok(any(s["id"] == nids[0] for s in ev("__ui.RES.sources")) and ev(f"__ui.P.noises[0].db") == -20, "noise back on, level -20 dB")
    pg.click(f"#nsrc_{nids[1]} summary")
    set_range(f"k_{nids[1]}_az", 45); set_range(f"k_{nids[1]}_el", 0); set_range(f"k_{nids[1]}_dist", 3); settled()
    n2 = ev(f"__ui.RES.sources.find(s => s.id === '{nids[1]}')")
    ok(abs(n2["az"] - 45) < 0.5 and abs(n2["dist"] - 3) < 0.01, "noise position knobs reach the engine")
    moving = ev("__ui.P.noises.filter(n => n.path).map(n => n.id)")
    tags = ev("[...document.querySelectorAll('.nsrc')].filter(d => !d.querySelector('.tag:not(.clamp)').hidden).map(d => d.id.slice(5))")
    ok(sorted(tags) == sorted(moving), f"'moving' tags only on moving sources ({len(moving)})")
    pg.click(f'#head [data-fid="top:{nids[2]}"] .shape', force=True); settled()
    ok(ev("__ui.P.noises[2].on") is False, "clicking a noise diamond switches it off")

    # ------------------------------------------------------------ 7. robot noise
    scene("custom", "robot")
    pg.uncheck("#k_fanOn"); settled()
    ok("fan" not in ev("__ui.RES.solos") and not ev("__ui.P.fanOn"), "fan checkbox off")
    pg.click('#head [data-fid="chip:fan"]'); settled()
    ok("fan" in ev("__ui.RES.solos"), "fan chip on the head switches it back on")
    set_range("k_fanRpm", 3000); set_range("k_neckDb", -12); pg.check("#k_footstepsOn"); settled()
    ok(max(ev("__ui.RES.motor.fan")) == 3000 and "footsteps" in ev("__ui.RES.solos"), "fan top speed and footsteps reach the engine")

    # ------------------------------------------------------------ 8. top view: keyboard and drag
    scene("home")
    pg.focus('#head [data-fid="top:s1"]')
    az0, d0, e0 = ev("__ui.P.speakers[0].az"), ev("__ui.P.speakers[0].dist"), ev("__ui.P.speakers[0].el")
    pg.keyboard.press("ArrowLeft"); pg.keyboard.press("+"); pg.keyboard.press("PageUp")
    ok(ev("__ui.P.speakers[0].az") == (az0 + 5) % 360 and abs(ev("__ui.P.speakers[0].dist") - (d0 + 0.1)) < 1e-9 and ev("__ui.P.speakers[0].el") == e0 + 5,
       "keyboard: arrow turns, + moves out, Page Up raises")
    box = pg.locator('#head [data-fid="top:s1"]').bounding_box()
    hb = pg.locator("#head").bounding_box()
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2); pg.mouse.down()
    pg.mouse.move(hb["x"] + hb["width"] / 2, hb["y"] + hb["height"] * 0.15, steps=8); pg.mouse.up(); settled()
    ok(abs(ev("__ui.P.speakers[0].az") - 90) < 8 and abs(ev("__ui.RES.sources[0].az") - ev("__ui.P.speakers[0].az")) < 1, f"drag speaker 1 to the top -> az {ev('__ui.P.speakers[0].az')}")

    # ------------------------------------------------------------ 9. mics, playback, tracks, downloads
    pg.click('#head [data-fid="mic:2"]')
    ok(ev("document.querySelector('[data-fid=\"mic:2\"]').getAttribute('aria-checked')") == "false", "click a mic: excluded from the mix")
    pg.click("#oneOn")
    ok(ev("[...document.querySelectorAll('#head .mic')].filter(m => m.getAttribute('aria-checked') === 'true').length") == 1, "Mic 1 only")
    pg.click("#allOn")
    ok(ev("[...document.querySelectorAll('#head .mic')].filter(m => m.getAttribute('aria-checked') === 'true').length") == 8, "All mics")
    pg.click("#stereo")
    ok(pg.get_attribute("#stereo", "aria-pressed") == "true", "stereo toggle")
    pg.click("#playMics"); pg.wait_for_timeout(400)
    ok(pg.inner_text("#playMics") == "Stop" and ev("__ui.view.key") == "mics", "Play selected mics starts and shows the mix")
    pg.click("#playMics"); pg.wait_for_timeout(200)
    ok(pg.inner_text("#playMics") == "Play selected mics", "Stop")
    rows = ev("[...document.querySelectorAll('#beamList li[data-key], #micList li, #soloList li')].map(li => li.dataset.key)")
    bad = []
    for k in rows:
        pg.click(f'li[data-key="{k}"] .tt')
        pg.wait_for_function(f"__ui.view && __ui.view.key === {json.dumps(k)}", timeout=20000)
        a = ev("(() => { const a = __ui.view.arr; let m = 0; for (const v of a) m = Math.max(m, Math.abs(v)); return [a.length, m]; })()")
        if a[0] != 88000 or not (a[1] > 0):
            bad.append(k)
    ok(not bad, f"{len(rows)} tracks (beams, raw mics, sources) open with 5.5 s of non-silent audio" + (f" bad: {bad}" if bad else ""))
    pg.click('#beamList li[data-key="s1_mvdr"] .play'); pg.wait_for_timeout(400)
    ok(pg.inner_text("#vPlay") == "Stop", "track play button")
    pg.click("#vPlay"); pg.wait_for_timeout(200)
    ok(pg.inner_text("#vPlay") == "Play", "viewer stop")
    pg.click("#plots", position={"x": 600, "y": 100}); pg.wait_for_timeout(400)
    ok(pg.inner_text("#vPlay") == "Stop", "clicking the plot plays from that point")
    pg.click("#vPlay")
    with pg.expect_download() as dl:
        pg.click('#micList li[data-key="rawmic_3"] .dl')
    # outside the claude.ai viewer a single track is saved as a plain .wav (inside it, wrapped in a .zip)
    x, fs = sf.read(dl.value.path())
    ok(dl.value.suggested_filename == "mic4.wav" and fs == 16000 and len(x) == 88000 and np.allclose(x, ev("Array.from(__ui.RES.mics[3])"), atol=1e-4),
       "single-track download (mic 4) holds mic 4's audio")
    with pg.expect_download() as dl:
        pg.click("#dlAll")
    z = zipfile.ZipFile(dl.value.path())
    names = z.namelist()
    need = ["settings.json", "scene.json", "page_scores.json", "scores.csv", "mic1_original.wav"] + [f"mics/mic{i}.wav" for i in range(1, 9)]
    ok(all(n in names for n in need) and any(n.startswith("dry/") for n in names) and any(n.startswith("beams/") for n in names),
       f"download-all zip: {len(names)} files incl. mics, beams, dry sources, scene.json")
    st = json.loads(z.read("settings.json"))
    ok(st["schema"] == 2 and len(st["micPositions"]) == 8 and st["speakers"][0]["az"] == ev("__ui.P.speakers[0].az"), "settings.json matches the page settings")
    csv_lines = z.read("scores.csv").decode().strip().splitlines()
    ok(csv_lines[0] == "speaker,voice,processing,score_db,gain_db,python_db" and len(csv_lines) == 1 + 2 * 4, "scores.csv rows")

    # ------------------------------------------------------------ 10. sound check, dark mode, phone width
    pg.click("#soundCheck summary")
    for i in (1, 2, 3):
        pg.click(f"#beep{i}"); pg.wait_for_timeout(300)
    ok("Beep 3" in pg.inner_text("#beepOut"), "sound check buttons respond")
    ok(not errs, "no page errors so far" + (f": {errs[:3]}" if errs else ""))
    for scheme, w in (("dark", 1300), ("light", 400)):
        q = b.new_page(viewport={"width": w, "height": 900}, color_scheme=scheme)
        q.on("pageerror", lambda e: errs.append(str(e)))
        q.route("**/fonts.g*/**", lambda r: r.abort())
        q.goto(URL)
        q.wait_for_function("document.querySelector('#status').textContent.startsWith('Rendered')", timeout=180000)
        ok(q.evaluate("document.documentElement.scrollWidth - innerWidth") <= 0, f"{scheme} {w}px: no horizontal scroll")
        q.close()
    ok(not errs, "no page errors at the end" + (f": {errs[:3]}" if errs else ""))
    b.close()

shutil.rmtree(site, ignore_errors=True)
print(f"\n{'ALL PASSED' if not fails else f'{len(fails)} FAILED'}")
sys.exit(1 if fails else 0)
