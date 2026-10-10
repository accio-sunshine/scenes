"""
Experiment 14 (Phase 4): offline WPE vs online (frame-by-frame) WPE.
The robot can't wait for the whole recording, so it must run online WPE.
Online WPE needs several seconds to learn the room, so each one-talker scene
is played 4 times in a row and only the LAST repetition is scored (after ~12 s
of learning), plus the first repetition to show the start-up cost.
Score: SI-SDR of mic 1 against the dry voice (higher = less echo).

Run from the robot-audio folder:  python experiments/exp14_wpe_online.py
Results: results/exp14_wpe_online/ (summary.txt and WAVs)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import toolkit as tk  # noqa: E402
import numpy as np  # noqa: E402

NAME = "exp14_wpe_online"
REPEATS = 4
rows = []
for label, s in [("medium_echo", dict(angle_b=None, rt60=0.5)), ("echoey_room", dict(angle_b=None, rt60=0.8))]:
    print(f"  {label} ...", flush=True)
    sc = tk.build_scene(**s)
    L = sc.mix.shape[1]
    ref = np.tile(np.pad(sc.sA, (0, max(0, L - len(sc.sA))))[:L], REPEATS)
    X = tk.to_stft(np.tile(sc.mix, (1, REPEATS)))

    def score(y, k):
        y = np.pad(y, (0, max(0, REPEATS * L - len(y))))
        return tk.si_sdr(y[k * L:(k + 1) * L], ref[k * L:(k + 1) * L])

    y = tk.to_time(X[0])
    rows.append([label, "no WPE", score(y, 0), score(y, REPEATS - 1), "-"])
    with tk.Timer() as t:
        y = tk.to_time(tk.wpe_offline(X, taps=10, delay=3)[0])
    rows.append([label, "offline, 10 taps", score(y, 0), score(y, REPEATS - 1), f"{t.s:.1f}"])
    for alpha in (0.99, 0.999, 0.9999):
        with tk.Timer() as t:
            y = tk.to_time(tk.wpe_online(X, taps=10, delay=3, alpha=alpha)[0])
        rows.append([label, f"online, 10 taps, alpha {alpha}", score(y, 0), score(y, REPEATS - 1), f"{t.s:.1f}"])
        tk.save_wav(os.path.join(tk.result_dir(NAME, label), f"online_alpha{alpha}_mic1.wav"), y, sc.scale)

tk.save_table(NAME, "How much does WPE lose when it runs frame by frame, like on the robot?",
              ["scene", "WPE", "SI-SDR first rep dB", "SI-SDR last rep dB", "time s (PC)"], rows,
              "First rep = while online WPE is still learning; last rep = after ~12 s. "
              "alpha = how slowly online WPE forgets (closer to 1 = longer memory, slower to adapt). "
              "Online WPE here is nara_wpe's OnlineWPE with its default start-up settings.")
