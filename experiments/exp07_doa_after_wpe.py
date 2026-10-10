"""
Experiment 7 (Phase 2): does removing echo first help direction finding?
Runs MUSIC and SRP-PHAT on the raw mics and on WPE-dereverberated mics.

Run from the robot-audio folder:  python experiments/exp07_doa_after_wpe.py
Results: results/exp07_doa_after_wpe/summary.txt
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import toolkit as tk  # noqa: E402
import numpy as np  # noqa: E402

NAME = "exp07_doa_after_wpe"
rows = []
for label, s in [("two_far", dict(angle_b=150)), ("echoey_room", dict(rt60=0.8)), ("two_close", dict(angle_b=70))]:
    print(f"  {label} ...", flush=True)
    sc = tk.build_scene(**s)
    truth = [sc.cfg["angle_a"], sc.cfg["angle_b"]]
    Xd = tk.wpe_offline(sc.X)
    for inp, X in (("raw", sc.X), ("after WPE", Xd)):
        mus, _ = tk.find_directions(X, sc.rel_xy, "MUSIC")
        srp, _ = tk.find_directions(X, sc.rel_xy, "SRP")
        rows.append([label, sc.cfg["rt60"], tk.fmt_angles(truth), inp, tk.fmt_angles(mus), tk.fmt_angles(srp)])

tk.save_table(NAME, "Does removing echo (WPE) before direction finding help?",
              ["scene", "RT60 s", "true deg", "input", "MUSIC deg", "SRP deg"], rows)
