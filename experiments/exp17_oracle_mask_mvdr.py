"""
Experiment 17 (Phase 6): the best a mask could ever do ("oracle mask").
In the simulation we know exactly which sound is talker A, so we can build a
perfect time-frequency mask and use it to drive mask-based MVDR (no direction
needed). If this beats direction-based MVDR by a lot, a neural mask network
is worth building; if not, Phase 6 can be skipped.

Run from the robot-audio folder:  python experiments/exp17_oracle_mask_mvdr.py
Results: results/exp17_oracle_mask_mvdr/ (summary.txt and WAVs)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import toolkit as tk  # noqa: E402
import numpy as np  # noqa: E402

NAME = "exp17_oracle_mask_mvdr"
rows = []
for label, s in tk.TEST_SET:
    print(f"  {label} ...", flush=True)
    sc = tk.build_scene(**s)
    d = tk.steering(sc.rel_xy, sc.cfg["angle_a"])
    w_dir = tk.mpdr_weights(sc.X, d)
    pa, pi = np.abs(sc.XA[0]) ** 2, np.abs(sc.XI[0]) ** 2
    mask = pa / (pa + pi + 1e-12)                       # ideal ratio mask at mic 1
    w_mask = tk.mask_mvdr_weights(sc.X, mask)
    rows.append([label, tk.ratio_db(sc.XA[0], sc.XI[0]), tk.component_db(w_dir, sc.XA, sc.XI),
                 tk.component_db(w_mask, sc.XA, sc.XI)])
    folder = tk.result_dir(NAME, label)
    tk.save_wav(os.path.join(folder, "mvdr_direction.wav"), tk.to_time(tk.apply(w_dir, sc.X)), sc.scale)
    tk.save_wav(os.path.join(folder, "mvdr_oracle_mask.wav"), tk.to_time(tk.apply(w_mask, sc.X)), sc.scale)

tk.save_table(NAME, "How much better is MVDR when it knows which sound is the target (perfect mask)?",
              ["scene", "mic 1 dB", "MVDR direction dB", "MVDR oracle mask dB"], rows,
              "dB = talker A vs everything else. The oracle mask uses knowledge a real robot doesn't have; "
              "it is the upper bound a mask network could reach.")
