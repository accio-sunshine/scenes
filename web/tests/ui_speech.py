"""Speech features of the Scene Simulator page: typed text (eSpeak), uploaded files, voices, long speech, zip contents.

    python tests/ui_speech.py [built.html]      (CHROMIUM=/path/to/chrome to choose the browser; ~2 min)
"""
import sys, os, threading, http.server, socketserver, functools, json, shutil, tempfile
import numpy as np, soundfile as sf
from playwright.sync_api import sync_playwright
WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); ROOT = os.path.dirname(WEB)
PAGE = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(WEB, "robot_acoustic.html")
D = tempfile.mkdtemp(); OUT = tempfile.mkdtemp()
shutil.copy(PAGE, os.path.join(D, "index.html")); shutil.copytree(os.path.join(WEB, "vendor"), os.path.join(D, "vendor"))
fails = []
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), functools.partial(Q, directory=D)); threading.Thread(target=srv.serve_forever, daemon=True).start()
with sync_playwright() as p:
    b = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {})); pg = b.new_page(accept_downloads=True); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/fonts.g*/**", lambda r: r.abort())
    pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html")
    settled = lambda: (pg.wait_for_timeout(700), pg.wait_for_function("__ui.RP && JSON.stringify(__ui.RP)===JSON.stringify(__ui.P) && /^Rendered/.test(document.querySelector('#status').textContent)", timeout=180000))
    settled()
    t0 = pg.evaluate("__ui.RES.talk.s1")
    print("Home default: Python cells", pg.evaluate("document.querySelectorAll('#scoreTable td.pyc').length"), "s1 talk", t0)
    def ok(c, m):
        print(("PASS " if c else "FAIL ") + m, flush=True)
        if not c: fails.append(m)
    # typed text
    pg.select_option("#k_s1_speech", "text")
    ok(pg.is_visible("#k_s1_text") and not pg.is_visible("#spk_s1 label.upbtn"), "Typed text shows the text box")
    ok(pg.is_visible("#k_s1_engine") and pg.input_value("#k_s1_engine") == "kokoro", "Typed text shows the engine choice, Kokoro by default")
    pg.select_option("#k_s1_engine", "espeak")
    pg.fill("#k_s1_text", "Robot, please bring me the red toolbox from the kitchen table."); settled()
    t1 = pg.evaluate("__ui.RES.talk.s1")
    ok(abs((t1[1]-t1[0]) - (t0[1]-t0[0])) > 0.3, f"speech length changed: recording {t0[1]-t0[0]:.2f} s -> typed {t1[1]-t1[0]:.2f} s")
    ok(not pg.evaluate("__ui.RES.warnings.length"), f"no warnings ({pg.evaluate('__ui.RES.warnings')})")
    ok(pg.evaluate("document.querySelectorAll('#scoreTable td.pyc').length") == 0, "Python column hides when the speech changes")
    dry = np.array(pg.evaluate("Array.from(__ui.RES.dry.s1)")); st = int(round(t1[0]*16000)); seg = dry[st:st+int((t1[1]-t1[0])*16000)]
    ok(np.max(np.abs(seg)) > 0.9 and np.mean(np.abs(seg) > 0.02) > 0.3, f"synthesised speech is in the scene (peak {np.max(np.abs(seg)):.2f}, active {np.mean(np.abs(seg) > 0.02):.0%})")
    sf.write(os.path.join(OUT, "typed_s1_dry.wav"), seg.astype(np.float32), 16000)
    # cached: retyping the same text does not resynthesise; editing it does
    # upload for speaker 2
    pg.select_option("#k_s2_speech", "upload")
    ok(pg.is_visible("#spk_s2 label.upbtn") and "No file" in pg.inner_text("#spk_s2"), "Uploaded file shows the file picker")
    pg.set_input_files("#k_s2_file", os.path.join(ROOT, "sim_conversation_out", "clean_male.wav")); settled()
    s2 = pg.evaluate("__ui.P.speakers[1]"); t2 = pg.evaluate("__ui.RES.talk.s2")
    ref = sf.read(os.path.join(ROOT, "sim_conversation_out", "clean_male.wav"))[0]; ref = ref / np.max(np.abs(ref)); a = np.flatnonzero(np.abs(ref) > 0.02); reflen = (a[-1] - a[0] + 320) / 16000
    ok(s2["speech"] == "upload" and s2["uploadName"] == "clean_male.wav" and abs((t2[1]-t2[0]) - reflen) < 0.01, f"uploaded clean_male.wav used: {t2[1]-t2[0]:.2f} s (file speech {reflen:.2f} s)")
    ok("clean_male.wav" in pg.inner_text("#spk_s2"), "file name shown on the card")
    # baby: no typed text option
    pg.select_option("#k_s2_voice", "baby"); pg.wait_for_timeout(200)
    ok(pg.evaluate("document.querySelector('#k_s2_speech option[value=text]').disabled"), "baby: Typed text option disabled")
    pg.select_option("#k_s2_voice", "female"); pg.select_option("#k_s2_speech", "recording"); settled()
    # long text past the end of the recording -> warning
    pg.fill("#k_s1_text", "This is a deliberately long sentence that keeps going and going so that it cannot possibly fit inside the remaining few seconds of this short recording."); settled()
    ok(any("runs past the end" in w for w in pg.evaluate("__ui.RES.warnings")), "long speech: warning that it is cut at the end")
    pg.select_option("#k_duration", "20"); settled()
    ok(not any("runs past" in w for w in pg.evaluate("__ui.RES.warnings")) and pg.evaluate("__ui.RES.mics[0].length") == 320000, "20 s recording: long speech fits, no warning")
    # each voice synthesises
    for v in ["male", "male_low", "female", "female_high"]:
        pg.select_option("#k_s1_voice", v); settled()
        ok(not pg.evaluate("__ui.RES.warnings.length"), f"voice {v}: typed text synthesised")
    # zip carries the typed speech and the text
    with pg.expect_download() as dl: pg.click("#dlAll")
    import zipfile; z = zipfile.ZipFile(dl.value.path()); st = json.loads(z.read("settings.json"))
    ok(st["speakers"][0]["speech"] == "text" and st["speakers"][0]["text"].startswith("This is a deliberately") and "dry/s1.wav" in z.namelist(), "zip: settings.json has the text; dry/s1.wav has the speech")
    # Kokoro (model from Hugging Face on first use: needs the network once)
    pg.select_option("#k_duration", "10"); pg.select_option("#k_s1_voice", "male")
    pg.select_option("#k_s1_engine", "kokoro"); pg.fill("#k_s1_text", "Hi there, how are you doing today?"); settled()
    t3 = pg.evaluate("__ui.RES.talk.s1"); dry = np.array(pg.evaluate("Array.from(__ui.RES.dry.s1)")); seg = dry[int(round(t3[0]*16000)):int(round(t3[1]*16000))]
    ok(not pg.evaluate("__ui.RES.warnings.length") and 1.0 < t3[1]-t3[0] < 4.0 and np.max(np.abs(seg)) > 0.9, f"Kokoro speech is in the scene ({t3[1]-t3[0]:.2f} s, warnings {pg.evaluate('__ui.RES.warnings')})")
    sf.write(os.path.join(OUT, "kokoro_s1_dry.wav"), seg.astype(np.float32), 16000)
    with pg.expect_download() as dl: pg.click("#dlAll")
    st = json.loads(zipfile.ZipFile(dl.value.path()).read("settings.json"))
    ok(st["speakers"][0]["engine"] == "kokoro" and st["speakers"][0]["text"] == "Hi there, how are you doing today?", "zip: settings.json has engine kokoro and the text")
    # the booth layout as a scene: press at 150 deg, four typed-text Kokoro talkers
    pg.click("#card_factory_booth"); settled()
    sp = pg.evaluate("__ui.P.speakers"); press = [n for n in pg.evaluate("__ui.P.noises") if n["id"] == "press"]
    ok(len(sp) == 4 and all(s["speech"] == "text" and s["engine"] == "kokoro" and s["text"] for s in sp) and [s["az"] for s in sp] == [30, 0, 210, 270],
       f"Factory (booth): 4 Kokoro talkers at 30/0/210/270 ({[(s['voice'], s['az'], s['speech']) for s in sp]})")
    ok(press and press[0]["az"] == 150 and not pg.evaluate("__ui.RES.warnings.length"), "Factory (booth): press at 150 deg, renders without warnings")
    ok(not errs, "no page errors" + (f": {errs[:3]}" if errs else ""))
    b.close()
print(f"\n{'ALL PASSED' if not fails else f'{len(fails)} FAILED'}")
sys.exit(1 if fails else 0)
