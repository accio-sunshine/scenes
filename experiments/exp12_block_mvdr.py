"""
Experiment 12 (Phase 3): MVDR updated in short blocks, like a live robot.
Earlier MVDR used the whole recording at once. Here it re-learns every
1.0 / 0.5 / 0.25 s from that block only.

Run from the robot-audio folder:  python experiments/exp12_block_mvdr.py
Results: results/exp12_block_mvdr/ (summary.txt and one WAV per setting)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import toolkit as tk  # noqa: E402
import numpy as np  # noqa: E402

NAME = "exp12_block_mvdr"
rows = []
for label, s in [("two_far", dict(angle_b=150)), ("two_close", dict(angle_b=70))]:
    print(f"  {label} ...", flush=True)
    sc = tk.build_scene(**s)
    d = tk.steering(sc.rel_xy, sc.cfg["angle_a"])
    w = tk.mpdr_weights(sc.X, d)
    rows.append([label, "whole file", tk.component_db(w, sc.XA, sc.XI)])
    for sec in (1.0, 0.5, 0.25):
        W = tk.blockwise_mpdr(sc.X, d, int(sec * tk.FS / tk.HOP))
        db = tk.ratio_db(tk.apply_framewise(W, sc.XA), tk.apply_framewise(W, sc.XI))
        rows.append([label, f"every {sec} s", db])
        tk.save_wav(os.path.join(tk.result_dir(NAME, label), f"mvdr_every_{sec}s.wav"),
                    tk.to_time(tk.apply_framewise(W, sc.X)), sc.scale)

tk.save_table(NAME, "How much does MVDR lose when it can only learn from recent audio?",
              ["scene", "MVDR updated", "MVDR dB"], rows, "dB = talker A vs everything else.")
