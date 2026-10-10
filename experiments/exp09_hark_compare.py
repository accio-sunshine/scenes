"""
Experiment 9 (Phase 2, optional): HARK's MUSIC on the same test set.
Runs pyhark_localize.py on every scene of experiment 5 and saves HARK's output.
Needs: HARK/PyHARK installed, and hark/tf_8mic.zip made in HARKTOOL5-GUI
(see pyhark_localize.py). Run experiment 5 first.

Run from the robot-audio folder:  python experiments/exp09_hark_compare.py
Results: results/exp09_hark_compare/hark_log.txt
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
OUT = os.path.join("results", "exp09_hark_compare")
TF = os.path.join("hark", "tf_8mic.zip")
SCENES = ["one_talker", "two_far", "two_close", "dry_room", "echoey_room"]

try:
    import hark  # noqa: F401
except ImportError:
    sys.exit("PyHARK isn't installed in this Python environment - run this on the PC with HARK.")
if not os.path.exists(TF):
    sys.exit(f"Missing {TF}: make it in HARKTOOL5-GUI first (see pyhark_localize.py).")

os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "hark_log.txt"), "w") as log:
    for s in SCENES:
        wav = os.path.join("results", "exp05_test_set", s, "mix_8ch.wav")
        if not os.path.exists(wav):
            sys.exit(f"Missing {wav}: run experiments/exp05_test_set.py first.")
        n = "1" if s == "one_talker" else "2"
        print(f"=== {s} ===", flush=True)
        r = subprocess.run([sys.executable, "pyhark_localize.py", wav, TF, n], capture_output=True, text=True)
        text = f"=== {s} ===\n{r.stdout}\n{r.stderr}\n"
        print(r.stdout[-1500:], r.stderr[-800:])
        log.write(text)
print(f"Saved {OUT}/hark_log.txt - compare the angles with results/exp05_test_set/summary.txt")
