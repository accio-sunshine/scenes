"""Live recording (Speech: Live recording) end to end, with Chromium's fake microphone (a test tone):
record, stop, Record again, auto-stop at the recording length, switching to Uploaded file, microphone refused.

    python tests/ui_record.py [built.html]      (CHROMIUM=/path/to/chrome to choose the browser; ~1 min)
"""
import sys, os, threading, http.server, socketserver, functools, shutil, tempfile
import numpy as np
from playwright.sync_api import sync_playwright
WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(WEB, "robot_acoustic.html"); D = tempfile.mkdtemp(); shutil.copy(PAGE, os.path.join(D, "index.html"))
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), functools.partial(Q, directory=D)); threading.Thread(target=srv.serve_forever, daemon=True).start()
fails = []
def ok(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)
    if not c: fails.append(m)
with sync_playwright() as p:
    # fake microphone (a test tone) and auto-allow, as a stand-in for a real mic
    b = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}), args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
    ctx = b.new_context(permissions=["microphone"]); pg = ctx.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html")
    settled = lambda: (pg.wait_for_timeout(700), pg.wait_for_function("__ui.RP && JSON.stringify(__ui.RP)===JSON.stringify(__ui.P) && /^Rendered/.test(document.querySelector('#status').textContent)", timeout=180000))
    settled()
    pg.select_option("#k_s1_speech", "record"); pg.wait_for_timeout(300)
    ok(pg.is_visible("#rec_s1") and pg.inner_text("#rec_s1") == "● Record" and "Nothing recorded" in pg.inner_text("#spk_s1"), "Live recording shows a Record button")
    ok(not pg.is_visible("#spk_s1 label.upbtn") and not pg.is_visible("#k_s1_text"), "no file picker or text box in Live recording")
    pg.click("#rec_s1"); pg.wait_for_timeout(2600)
    ok("Stop" in pg.inner_text("#rec_s1") and pg.get_attribute("#rec_s1", "aria-pressed") == "true", f"recording: button shows {pg.inner_text('#rec_s1')!r}")
    pg.click("#rec_s1"); settled()
    s1 = pg.evaluate("__ui.P.speakers[0]"); talk = pg.evaluate("__ui.RES.talk.s1")
    ok(s1["speech"] == "record" and s1["uploadName"].startswith("Live recording") and 1.5 < talk[1] - talk[0] < 3.2, f"recorded {talk[1]-talk[0]:.2f} s used as speaker 1's speech ({s1['uploadName']})")
    ok(not pg.evaluate("__ui.RES.warnings.length"), f"no warnings {pg.evaluate('__ui.RES.warnings')}")
    dry = np.array(pg.evaluate("Array.from(__ui.RES.dry.s1)")); st = int(talk[0] * 16000)
    ok(np.max(np.abs(dry[st:st + 16000])) > 0.5, "recorded audio is in the scene")
    ok(pg.inner_text("#rec_s1") == "● Record again", "button offers Record again")
    # switching to Uploaded file must not reuse the recording
    pg.select_option("#k_s1_speech", "upload"); pg.wait_for_timeout(300)
    ok(pg.evaluate("__ui.P.speakers[0].uploadId") == "" and "No file yet" in pg.inner_text("#spk_s1"), "switching to Uploaded file clears the recording")
    # auto-stop at the recording length (3 s)
    pg.select_option("#k_duration", "3"); pg.select_option("#k_s2_speech", "record"); settled()
    pg.click("#rec_s2"); pg.wait_for_timeout(4200); settled()
    t2 = pg.evaluate("__ui.RES.talk.s2"); n = pg.evaluate("__ui.RES.mics[0].length")
    ok(pg.inner_text("#rec_s2") == "● Record again" and n == 48000, f"3 s recording length: stopped by itself (speech {t2[1]-t2[0]:.2f} s)")
    ok(not errs, "no page errors" + (f": {errs[:3]}" if errs else ""))
    # microphone refused (as in the claude.ai viewer): clear message, nothing breaks
    ctx2 = b.new_context(); pg2 = ctx2.new_page(); pg2.on("pageerror", lambda e: errs.append(str(e)))
    pg2.add_init_script("navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('Permission denied', 'NotAllowedError'))")
    pg2.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html")
    pg2.wait_for_function("/^Rendered/.test(document.querySelector('#status').textContent)", timeout=180000)
    pg2.select_option("#k_s1_speech", "record"); pg2.wait_for_timeout(700); pg2.click("#rec_s1"); pg2.wait_for_timeout(500)
    pg2.wait_for_timeout(1500); msg = pg2.inner_text("#spk_s1 .upname")
    ok("Microphone not available (NotAllowedError)" in msg and pg2.inner_text("#rec_s1") == "● Record", f"mic refused: {msg[:90]}…")
    ok(not errs, "no page errors with the mic refused")
    b.close()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED"); sys.exit(1 if fails else 0)
