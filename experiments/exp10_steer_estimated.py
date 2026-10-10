"""
Experiment 10 (Phase 3): beamforming with the ESTIMATED direction.
Earlier tables steered at the true angle, which the robot doesn't know.
Here the beam is steered at SRP-PHAT's estimate (the estimated peak nearest
talker A, i.e. the person the robot is following).

Run from the robot-audio folder:  python experiments/exp10_steer_estimated.py
Results: results/exp10_steer_estimated/summary.txt
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import toolkit as tk  # noqa: E402
import numpy as np  # noqa: E402

NAME = "exp10_steer_estimated"
rows = []
for label, s in tk.TEST_SET:
    print(f"  {label} ...", flush=True)
    sc = tk.build_scene(**s)
    est, _ = tk.find_directions(sc.X, sc.rel_xy, "SRP", num_src=2 if sc.two else 1)
    a_est = min(est, key=lambda a: tk.angle_error(a, sc.cfg["angle_a"]))
    r = [label, sc.cfg["angle_a"], round(float(a_est)), round(float(tk.angle_error(a_est, sc.cfg["angle_a"])))]
    for ang in (sc.cfg["angle_a"], a_est):
        d = tk.steering(sc.rel_xy, ang)
        r += [tk.component_db(d / tk.N_MICS, sc.XA, sc.XI), tk.component_db(tk.mpdr_weights(sc.X, d), sc.XA, sc.XI)]
    rows.append(r)

tk.save_table(NAME, "How much is lost when the beam uses the estimated direction instead of the true one?",
              ["scene", "true A", "estimated A", "error deg", "DAS true dB", "MVDR true dB",
               "DAS est dB", "MVDR est dB"], rows,
              "dB = talker A vs everything else. DAS = delay-and-sum.")
