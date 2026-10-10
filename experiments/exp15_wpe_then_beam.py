"""
Experiment 15 (Phase 4): does WPE before the beamformer help overall?
Scored with SI-SDR against talker A's dry voice, which penalises the other
talker, noise and echo together (higher = cleaner). Test set from experiment 5.

Run from the robot-audio folder:  python experiments/exp15_wpe_then_beam.py
Results: results/exp15_wpe_then_beam/ (summary.txt and WAVs)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import toolkit as tk  # noqa: E402
import numpy as np  # noqa: E402

NAME = "exp15_wpe_then_beam"
rows = []
for label, s in tk.TEST_SET:
    print(f"  {label} ...", flush=True)
    sc = tk.build_scene(**s)
    d = tk.steering(sc.rel_xy, sc.cfg["angle_a"])
    Xd = tk.wpe_offline(sc.X)
    outs = {"mic 1": sc.X[0],
            "MVDR": tk.apply(tk.mpdr_weights(sc.X, d), sc.X),
            "WPE + MVDR": tk.apply(tk.mpdr_weights(Xd, d), Xd),
            "WPE + DAS": tk.apply(d / tk.N_MICS, Xd)}
    r = [label]
    for k, Y in outs.items():
        y = tk.to_time(Y)
        r.append(tk.si_sdr(y, sc.sA))
        tk.save_wav(os.path.join(tk.result_dir(NAME, label), k.replace(" + ", "_").replace(" ", "") + ".wav"), y, sc.scale)
    rows.append(r)

tk.save_table(NAME, "Does removing echo before beamforming make talker A cleaner overall?",
              ["scene"] + [f"{k} SI-SDR dB" for k in ["mic 1", "MVDR", "WPE + MVDR", "WPE + DAS"]], rows,
              "SI-SDR vs talker A's dry voice; higher = cleaner. Penalises other talker, noise and echo.")
