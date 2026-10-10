"""
Experiment 13 (Phase 4): how many WPE taps are needed?
Taps = how far back WPE looks to predict echo. More taps = more memory and
compute on the robot (see the implementation note), so we want the fewest that work.
One talker only, so the score measures echo removal: SI-SDR of mic 1 against
talker A's dry voice (higher = closer to the clean voice).

Run from the robot-audio folder:  python experiments/exp13_wpe_taps.py
Results: results/exp13_wpe_taps/ (summary.txt and a WAV per setting)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import toolkit as tk  # noqa: E402
import numpy as np  # noqa: E402

NAME = "exp13_wpe_taps"
rows = []
for label, s in [("medium_echo", dict(angle_b=None, rt60=0.5)), ("echoey_room", dict(angle_b=None, rt60=0.8))]:
    print(f"  {label} ...", flush=True)
    sc = tk.build_scene(**s)
    rows.append([label, "no WPE", "-", tk.si_sdr(tk.to_time(sc.X[0]), sc.sA), "-"])
    for taps in (5, 10, 15):
        with tk.Timer() as t:
            Xd = tk.wpe_offline(sc.X, taps=taps, delay=3)
        y = tk.to_time(Xd[0])
        rows.append([label, f"{taps} taps", 3, tk.si_sdr(y, sc.sA), f"{t.s:.1f}"])
        tk.save_wav(os.path.join(tk.result_dir(NAME, label), f"wpe_{taps}taps_mic1.wav"), y, sc.scale)

tk.save_table(NAME, "What is the smallest number of WPE taps that still removes most of the echo?",
              ["scene", "WPE", "delay", "SI-SDR dB", "time s (PC)"], rows,
              "SI-SDR vs talker A's dry voice; higher = less echo. Time is on this PC, offline, for comparison only.")
