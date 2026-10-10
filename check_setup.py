"""
check_setup.py - Phase 0 check. Run from your robot-audio folder:  python check_setup.py
Checks Python, libraries, files and internet access, then runs the three
simulation scripts once. Each line says OK or what to fix.
"""
import importlib
import os
import subprocess
import sys
import urllib.request

ok = True


def report(passed, msg, fix=""):
    global ok
    print(("  OK    " if passed else "  FIX   ") + msg + ("" if passed or not fix else f"\n        -> {fix}"))
    ok &= passed


print("1. Python")
v = sys.version_info
report(v >= (3, 10), f"Python {v.major}.{v.minor}", "Install Python 3.10 or newer from python.org")

print("2. Libraries")
for mod, pipname in [("numpy", "numpy"), ("scipy", "scipy"), ("soundfile", "soundfile"),
                     ("matplotlib", "matplotlib"), ("pyroomacoustics", "pyroomacoustics"),
                     ("nara_wpe", "nara_wpe")]:
    try:
        importlib.import_module(mod)
        report(True, mod)
    except Exception as e:
        report(False, f"{mod} ({e.__class__.__name__})", "pip install -r requirements.txt")

print("3. Files in this folder")
for f in ["sim_8mic_room.py", "sim_8mic_robot_noise.py", "sim_conversation.py"]:
    report(os.path.exists(f), f, "Download it from the chat and put it in this folder")
for f in ["voices/male.wav", "voices/female.wav", "voices/baby.wav"]:
    report(os.path.exists(f), f, "Make a 'voices' folder here and put the three WAVs from the chat in it")

print("4. Internet (first run downloads two speech clips)")
try:
    urllib.request.urlopen("https://raw.githubusercontent.com", timeout=10)
    report(True, "raw.githubusercontent.com reachable")
except Exception:
    report(False, "cannot reach raw.githubusercontent.com", "Check your network or proxy")

if not ok:
    print("\nFix the items marked FIX, then run this again.")
    sys.exit(1)

print("5. Running the simulations (a minute or two)")
for script, out in [("sim_8mic_room.py", "results/exp01_echo_levels"), ("sim_8mic_robot_noise.py", "sim_noise_out"),
                    ("sim_conversation.py", "sim_conversation_out")]:
    r = subprocess.run([sys.executable, script], capture_output=True, text=True)
    report(r.returncode == 0 and os.path.isdir(out), f"{script} -> {out}/",
           "Error:\n" + (r.stderr.strip().splitlines() or ["(no message)"])[-1])

print("\nPhase 0 done. Open sim_conversation_out/ and play the WAV files." if ok
      else "\nSomething failed above - copy the error into the chat.")
