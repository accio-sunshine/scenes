"""
Experiment 20 (Phase 7): simple ways to remove the robot's own noise.
Scene: two talkers (40 and 150 deg) with every robot noise on.
Compares
  - MVDR alone
  - MVDR that also learns from a separate robot-only recording
  - a Wiener post-filter that subtracts the robot noise spectrum after the beam
    (noise spectrum also learned from the robot-only recording)

Run from the robot-audio folder:  python experiments/exp20_ego_noise_postfilter.py
Results: results/exp20_ego_noise_postfilter/ (summary.txt and WAVs)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import toolkit as tk  # noqa: E402
import numpy as np  # noqa: E402
import sim_8mic_robot_noise as rn  # noqa: E402

NAME = "exp20_ego_noise_postfilter"
KEYS = ["fan", "hum", "neck", "shoulders", "footsteps", "clicks"]


def robot_noise(sc, ref_power, seed):
    """All robot noises at the levels of sim_8mic_robot_noise.py, for this scene's array."""
    keep, rn.rng = rn.rng, np.random.default_rng(seed)
    ms = rn.motor_state()
    at = lambda ang, dist, dz: sc.centre + np.array([dist * np.cos(np.radians(ang)), dist * np.sin(np.radians(ang)), dz])
    src = {"fan": (rn.make_fan(ms), at(180, 0.07, -0.03)),
           "neck": (rn.make_servo(ms["neck_vel"], 600, 2400), at(0, 0.0, -0.10)),
           "shoulders": (rn.make_servo(ms["shoulder_vel"], 450, 1800), at(90, 0.18, -0.30)),
           "footsteps": (rn.make_footsteps(ms), at(0, 0.10, -1.40)),
           "clicks": (rn.make_clicks(ms), at(0, 0.0, -0.10))}
    L = sc.mix.shape[1]
    total = np.zeros((tk.N_MICS, L))
    for k in KEYS:
        if k == "hum":
            y = np.tile(rn.make_hum(), (tk.N_MICS, 1))
        else:
            y = rn.simulate([(src[k][1], src[k][0])], sc.centre, sc.mic_xy)
        y = np.pad(y, ((0, 0), (0, max(0, L - y.shape[1]))))[:, :L]
        total += y * np.sqrt(ref_power / (tk.power(y[0]) + 1e-20) * 10 ** (rn.LEVEL_DB[k] / 10))
    rn.rng = keep
    return total


def wiener_gain(Y, noise_psd, floor):
    return np.maximum(1 - noise_psd[:, None] / (np.abs(Y) ** 2 + 1e-12), floor)


print("  building scene ...", flush=True)
sc = tk.build_scene(angle_b=150)
ref_p = tk.power(sc.yA[0])
robot = robot_noise(sc, ref_p, seed=1)
take = robot_noise(sc, ref_p, seed=99)               # separate recording: robot moving, nobody talking
XR, XT = tk.to_stft(robot), tk.to_stft(take)
X = sc.X + XR
XI = sc.XI + XR
mix = sc.mix + robot
scale = 0.9 / np.max(np.abs(mix))
folder = tk.result_dir(NAME)
tk.save_wav(os.path.join(folder, "mix_8ch_mic1.wav"), mix[0], scale)
d = tk.steering(sc.rel_xy, sc.cfg["angle_a"])
rows = [["mic 1", tk.ratio_db(sc.XA[0], XI[0])]]

for name, w in [("MVDR", tk.mpdr_weights(X, d)),
                ("MVDR + learned robot noise", tk.mpdr_weights(np.concatenate([X, 3 * XT], axis=2), d))]:
    rows.append([name, tk.component_db(w, sc.XA, XI)])
    Y = tk.apply(w, X)
    tk.save_wav(os.path.join(folder, name.replace(" + ", "_").replace(" ", "_") + ".wav"), tk.to_time(Y), scale)
    noise_psd = np.mean(np.abs(tk.apply(w, XT)) ** 2, axis=1)
    for floor in (0.3, 0.1):
        G = wiener_gain(Y, noise_psd, floor)
        rows.append([f"{name} + post-filter (floor {floor})",
                     tk.ratio_db(G * tk.apply(w, sc.XA), G * tk.apply(w, XI))])
        tk.save_wav(os.path.join(folder, f"{name.replace(' + ', '_').replace(' ', '_')}_postfilter_{floor}.wav"),
                    tk.to_time(G * Y), scale)

tk.save_table(NAME, "Which simple method removes the most robot noise?",
              ["method", "talker A vs rest dB"], rows,
              "Rest = talker B + room noise + all robot noise. Floor = the least a post-filter lets through "
              "(lower floor removes more noise but can sound 'watery'); listen as well as reading the numbers.")
