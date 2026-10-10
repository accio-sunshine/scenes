"""
Experiment 8 (Phase 2): direction over time, raw vs smoothed.
Talker B starts 1.5 s after A, so who is loudest changes during the clip.
Every 0.25 s block gets one direction estimate (SRP-PHAT); smoothing takes the
circular median of the last 5 estimates. A block counts as correct when it is
within 15 deg of whichever talker is louder in that block.

Run from the robot-audio folder:  python experiments/exp08_doa_tracking.py
Results: results/exp08_doa_tracking/ (summary.txt and tracking.png)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import toolkit as tk  # noqa: E402
import numpy as np  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

NAME = "exp08_doa_tracking"
BLOCK = int(0.25 * tk.FS / tk.HOP)          # frames per 0.25 s block
SMOOTH = 5


def circ_median(a):
    best = min(a, key=lambda c: sum(tk.angle_error(c, x) for x in a))
    return best


rows = []
fig, axes = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
for ax, (label, s) in zip(axes, [("medium_echo", dict(rt60=0.5)), ("echoey_room", dict(rt60=0.8))]):
    print(f"  {label} ...", flush=True)
    sc = tk.build_scene(b_start=1.5, **s)
    T = sc.X.shape[2]
    est, truth, times = [], [], []
    for b in range(0, T - BLOCK + 1, BLOCK):
        pA = np.mean(np.abs(sc.XA[0, :, b:b + BLOCK]) ** 2)
        pB = np.mean(np.abs(sc.XB[0, :, b:b + BLOCK]) ** 2)
        if max(pA, pB) < 1e-3 * np.mean(np.abs(sc.XA[0]) ** 2):
            continue                                   # nobody talking
        a, _ = tk.find_directions(sc.X[:, :, b:b + BLOCK], sc.rel_xy, "SRP", num_src=1)
        est.append(a[0])
        truth.append(sc.cfg["angle_a"] if pA >= pB else sc.cfg["angle_b"])
        times.append(b * tk.HOP / tk.FS)
    smooth = [circ_median(est[max(0, i - SMOOTH + 1): i + 1]) for i in range(len(est))]
    ok_raw = np.mean([tk.angle_error(e, t) <= 15 for e, t in zip(est, truth)]) * 100
    ok_smooth = np.mean([tk.angle_error(e, t) <= 15 for e, t in zip(smooth, truth)]) * 100
    rows.append([label, sc.cfg["rt60"], len(est), f"{ok_raw:.0f}%", f"{ok_smooth:.0f}%"])
    ax.plot(times, est, "o", ms=4, label="per block")
    ax.plot(times, smooth, "-", lw=2, label="smoothed")
    ax.plot(times, truth, "k--", lw=1, label="louder talker")
    ax.set(ylabel="direction (deg)", ylim=(0, 360), title=f"{label} (RT60 {sc.cfg['rt60']} s)")
    ax.legend(loc="upper right", fontsize=8)
axes[-1].set_xlabel("time (s)")
fig.tight_layout()
fig.savefig(os.path.join(tk.result_dir(NAME), "tracking.png"), dpi=120)

tk.save_table(NAME, "How steady is the direction estimate over time, and does smoothing help?",
              ["scene", "RT60 s", "blocks", "correct raw", "correct smoothed"], rows,
              "Correct = within 15 deg of the louder talker in that block. See tracking.png.")
