"""
Experiment 11 (Phase 3): how sensitive is each beamformer to aiming errors?
The beam is deliberately aimed 0-30 deg away from talker A.
Includes the one-talker scene, where MVDR already suppressed the target (exp 4).

Run from the robot-audio folder:  python experiments/exp11_steering_error.py
Results: results/exp11_steering_error/summary.txt
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import toolkit as tk  # noqa: E402
import numpy as np  # noqa: E402

NAME = "exp11_steering_error"
OFFSETS = [0, 5, 10, 15, 20, 30]
rows = []
for label, s in [("one_talker", dict(angle_b=None)), ("two_far", dict(angle_b=150))]:
    print(f"  {label} ...", flush=True)
    sc = tk.build_scene(**s)
    for off in OFFSETS:
        d = tk.steering(sc.rel_xy, sc.cfg["angle_a"] + off)
        rows.append([label, off, tk.component_db(d / tk.N_MICS, sc.XA, sc.XI),
                     tk.component_db(tk.mpdr_weights(sc.X, d), sc.XA, sc.XI)])

tk.save_table(NAME, "What happens to each beamformer when it's aimed slightly wrong?",
              ["scene", "aim error deg", "DAS dB", "MVDR dB"], rows,
              "dB = talker A vs everything else.")
