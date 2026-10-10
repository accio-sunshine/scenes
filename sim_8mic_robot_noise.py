"""
sim_8mic_robot_noise.py  -  the 8-mic room, now with the robot's own noises.

Adds synthetic ego-noise sources placed inside / near the robot body:
  * cooling fan        - blade-pass hum + harmonics + broadband air noise, RPM ramps up
  * neck servo         - motor whine whose pitch follows joint speed, plus gear grind
  * shoulder servos    - two arm motors, bursts while "gesturing"
  * footsteps          - low thumps + clicks while walking
  * brake clicks       - short clicks when a joint starts / stops
  * electrical hum     - 50 Hz + harmonics picked up equally on every channel
It also writes motor_state.csv (what the robot's controller would know),
which Phase 7 uses to predict ego-noise.

Scenes written to ./sim_noise_out/ :
  speech_only, fan, fan_neck, walking, everything
For each: <scene>_8ch.wav, <scene>_mic1.wav, <scene>_mpdr.wav, <scene>_mvdr_ego.wav
  (_mvdr_ego = MPDR that also learned from a separate robot-noise-only recording)
Plus noise-only clips (noise_<type>_mic1.wav) and everything_egonoise_only_8ch.wav.

Install: pip install pyroomacoustics soundfile scipy numpy
Run:     python sim_8mic_robot_noise.py
"""
import os
import urllib.request

import numpy as np
import pyroomacoustics as pra
import soundfile as sf
from scipy.signal import butter, istft, lfilter, resample_poly, sosfilt, stft

FS = 16000
DUR = 5.5                 # seconds
N_MICS, RADIUS = 8, 0.05
ROOM, RT60 = [6.0, 5.0, 3.0], 0.5
ANGLE_A, ANGLE_B, DIST = 40, 150, 1.5
NFFT, HOP = 512, 128
C = 343.0
OUT = "sim_noise_out"
BASE = "https://raw.githubusercontent.com/LCAV/pyroomacoustics/master/examples/input_samples/"
SPEECH = ["cmu_arctic_us_aew_a0001.wav", "cmu_arctic_us_axb_a0004.wav"]

# Ego-noise levels relative to talker A at mic 1 (dB). Raise them to make it harder.
LEVEL_DB = {"fan": -6, "neck": -4, "shoulders": -8, "footsteps": -2, "clicks": -10, "hum": -25}

N = int(DUR * FS)
t = np.arange(N) / FS
rng = np.random.default_rng(1)


# ---------------------------------------------------------------- motor state
def motor_state():
    """Time series the robot controller would log (100 Hz in the CSV)."""
    fan_rpm = np.interp(t, [0, 2, DUR], [2400, 4200, 4200])            # fan spins up
    neck_vel = np.zeros(N)                                            # rad/s
    for t0, t1, v in [(0.8, 1.6, 1.2), (3.4, 4.0, -1.6)]:             # two head turns
        m = (t >= t0) & (t < t1)
        neck_vel[m] = v * np.sin(np.pi * (t[m] - t0) / (t1 - t0))     # smooth start/stop
    shoulder_vel = np.zeros(N)
    m = (t >= 1.8) & (t < 2.8)                                        # a gesture
    shoulder_vel[m] = 2.0 * np.sin(2 * np.pi * 1.5 * (t[m] - 1.8))
    walking = ((t >= 2.6) & (t < 4.8)).astype(float)
    return dict(fan_rpm=fan_rpm, neck_vel=neck_vel, shoulder_vel=shoulder_vel, walking=walking)


# ---------------------------------------------------------------- noise makers
def bandnoise(lo, hi, n=N):
    sos = butter(4, [lo, hi], btype="band", fs=FS, output="sos")
    return sosfilt(sos, rng.standard_normal(n))


def tone(freq_t, harmonics):
    """Sum of harmonics following a time-varying fundamental."""
    phase = 2 * np.pi * np.cumsum(freq_t) / FS
    return sum(a * np.sin(k * phase + rng.uniform(0, 2 * np.pi)) for k, a in harmonics)


def make_fan(ms):
    blades = 7
    bpf = ms["fan_rpm"] / 60 * blades                                  # ~280-490 Hz
    hum = tone(bpf, [(1, 1.0), (2, 0.5), (3, 0.25), (4, 0.1)])
    air = bandnoise(100, 6000)
    rot = 1 + 0.15 * np.sin(2 * np.pi * np.cumsum(ms["fan_rpm"] / 60) / FS)  # slight wobble
    return (0.6 * hum + 1.0 * air) * rot * (ms["fan_rpm"] / 4200)


def make_servo(vel, base_hz, span_hz):
    speed = np.abs(vel) / (np.abs(vel).max() + 1e-9)
    whine = tone(base_hz + span_hz * speed, [(1, 1.0), (2, 0.6), (3, 0.3), (5, 0.15)])
    grind = bandnoise(1500, 6000) * (0.5 + 0.5 * np.sin(2 * np.pi * 37 * t))  # gear mesh
    return (whine + 0.7 * grind) * speed


def make_footsteps(ms):
    out = np.zeros(N)
    walk_idx = np.flatnonzero(ms["walking"])
    if len(walk_idx) == 0:
        return out
    steps = np.arange(walk_idx[0], walk_idx[-1], int(0.55 * FS))
    k = np.arange(int(0.25 * FS)) / FS
    thump = np.sin(2 * np.pi * 70 * k) * np.exp(-k / 0.04)
    click = bandnoise(2000, 7000, len(k)) * np.exp(-k / 0.004)
    for s in steps:
        e = min(N, s + len(k))
        out[s:e] += (thump + 0.4 * click)[: e - s] * rng.uniform(0.8, 1.2)
    return out


def make_clicks(ms):
    out = np.zeros(N)
    k = np.arange(int(0.02 * FS)) / FS
    click = bandnoise(1000, 7000, len(k)) * np.exp(-k / 0.003)
    for v in (ms["neck_vel"], ms["shoulder_vel"]):
        moving = np.abs(v) > 1e-3
        for s in np.flatnonzero(np.diff(moving.astype(int)) != 0):     # start / stop
            e = min(N, s + len(k))
            out[s:e] += click[: e - s]
    return out


def make_hum():
    return tone(np.full(N, 50.0), [(1, 1.0), (2, 0.4), (3, 0.5), (5, 0.2)])


# ---------------------------------------------------------------- room helpers
def load_speech(name):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    if not os.path.exists(path):
        urllib.request.urlretrieve(BASE + name, path)
    x, fs = sf.read(path)
    x = x[:, 0] if x.ndim > 1 else x
    if fs != FS:
        x = resample_poly(x, FS, fs)
    return x / np.max(np.abs(x))


def simulate(sources, centre, mic_xy):
    e_abs, max_order = pra.inverse_sabine(RT60, ROOM)
    room = pra.ShoeBox(ROOM, fs=FS, materials=pra.Material(e_abs), max_order=max_order)
    for p, sig in sources:
        room.add_source(p, signal=sig)
    room.add_microphone_array(pra.MicrophoneArray(np.vstack([mic_xy, np.full(N_MICS, centre[2])]), FS))
    room.simulate()
    return room.mic_array.signals[:, :N]


def power(x):
    return np.mean(np.abs(x) ** 2)


def to_stft(x):
    return stft(x, fs=FS, window="hann", nperseg=NFFT, noverlap=NFFT - HOP)[2]


def to_time(X):
    return istft(X, fs=FS, window="hann", nperseg=NFFT, noverlap=NFFT - HOP)[1][:N]


def steering(rel_xy, deg):
    f = np.arange(NFFT // 2 + 1) * FS / NFFT
    u = np.array([np.cos(np.radians(deg)), np.sin(np.radians(deg))])
    return np.exp(2j * np.pi * f[:, None] * (rel_xy.T @ u)[None, :] / C)


def mvdr(R_frames, d, load=1e-3):
    """R_frames: (mics, freqs, frames) used to build the covariance per bin."""
    M = d.shape[1]
    w = np.zeros_like(d)
    for f in range(d.shape[0]):
        Xf = R_frames[:, f, :]
        R = Xf @ Xf.conj().T / Xf.shape[1]
        R += load * np.trace(R).real / M * np.eye(M) + 1e-12 * np.eye(M)
        Rd = np.linalg.solve(R, d[f])
        w[f] = Rd / (d[f].conj() @ Rd)
    return w


def apply(w, X):
    return np.einsum("fm,mft->ft", w.conj(), X)


def db(a, b):
    return 10 * np.log10(power(a) / power(b))


# ---------------------------------------------------------------- main
def main():
    os.makedirs(OUT, exist_ok=True)
    centre = np.array([ROOM[0] / 2, ROOM[1] / 2, 1.5])
    mic_xy = pra.circular_2D_array(centre[:2], N_MICS, 0, RADIUS)
    rel = mic_xy - centre[:2, None]

    def at(angle, dist, dz=0.0):
        a = np.radians(angle)
        return centre + np.array([dist * np.cos(a), dist * np.sin(a), dz])

    # Speech: A starts at 0.3 s, B at 2.0 s (they overlap).
    sA, sB = load_speech(SPEECH[0]), load_speech(SPEECH[1])
    a_sig, b_sig = np.zeros(N), np.zeros(N)
    a_sig[int(0.3 * FS):int(0.3 * FS) + len(sA)] = sA[: N - int(0.3 * FS)]
    b_sig[int(2.0 * FS):int(2.0 * FS) + len(sB)] = sB[: N - int(2.0 * FS)]
    yA = simulate([(at(ANGLE_A, DIST), a_sig)], centre, mic_xy)
    yB = simulate([(at(ANGLE_B, DIST), b_sig)], centre, mic_xy)
    ref = power(yA[0])

    ms = motor_state()
    # Where each noise sits relative to the array centre (metres).
    noises = {
        "fan":       (make_fan(ms),                      at(180, 0.07, -0.03)),   # back of head
        "neck":      (make_servo(ms["neck_vel"], 600, 2400), at(0, 0.0, -0.10)),  # below array
        "shoulders": (make_servo(ms["shoulder_vel"], 450, 1800), at(90, 0.18, -0.30)),
        "footsteps": (make_footsteps(ms),                at(0, 0.10, -1.40)),     # near floor
        "clicks":    (make_clicks(ms),                   at(0, 0.0, -0.10)),
    }
    ego = {}
    for name, (sig, p) in noises.items():
        y = simulate([(p, sig)], centre, mic_xy)
        y *= np.sqrt(ref / (power(y[0]) + 1e-20) * 10 ** (LEVEL_DB[name] / 10))
        ego[name] = y
    hum = make_hum()
    ego["hum"] = np.tile(hum, (N_MICS, 1)) * np.sqrt(ref / power(hum) * 10 ** (LEVEL_DB["hum"] / 10))

    diffuse = rng.standard_normal((N_MICS, N)) * np.sqrt(ref / 10 ** (25 / 10))  # room noise floor

    scenes = {
        "speech_only": [],
        "fan": ["fan", "hum"],
        "fan_neck": ["fan", "hum", "neck", "clicks"],
        "walking": ["fan", "hum", "footsteps", "shoulders", "clicks"],
        "everything": ["fan", "hum", "neck", "shoulders", "footsteps", "clicks"],
    }

    # A *separate* recording of the robot noise (new random seed) - what you'd
    # capture by running the motors with nobody talking. Used to learn the noise.
    def ego_take(keys, seed):
        global rng
        keep, rng = rng, np.random.default_rng(seed)
        msx = motor_state()
        makers = {"fan": make_fan(msx), "neck": make_servo(msx["neck_vel"], 600, 2400),
                  "shoulders": make_servo(msx["shoulder_vel"], 450, 1800),
                  "footsteps": make_footsteps(msx), "clicks": make_clicks(msx)}
        total = np.zeros((N_MICS, N))
        for k in keys:
            if k == "hum":
                total += ego["hum"]
                continue
            y = simulate([(noises[k][1], makers[k])], centre, mic_xy)
            y *= np.sqrt(ref / (power(y[0]) + 1e-20) * 10 ** (LEVEL_DB[k] / 10))
            total += y
        rng = keep
        return total

    d = steering(rel, ANGLE_A)
    print(f"{'scene':12s} | {'mic 1':>6s} | {'MPDR':>6s} | {'MPDR + learned robot noise':>26s}   (talker A vs everything else, dB)")
    for scene, keys in scenes.items():
        e = sum((ego[k] for k in keys), np.zeros((N_MICS, N)))
        interf = yB + e + diffuse
        mix = yA + interf
        scale = 0.9 / np.max(np.abs(mix))

        XA, XI, X = to_stft(yA), to_stft(interf), to_stft(mix)
        w1 = mvdr(X, d)                                           # from the mixture
        if keys:
            noise_rec = ego_take(keys, seed=99) + diffuse[:, ::-1]
            # mixture frames + robot-only frames: knows about talker B AND the robot noise
            w2 = mvdr(np.concatenate([X, 3 * to_stft(noise_rec)], axis=2), d)
        else:
            w2 = w1
        r0, r1, r2 = db(XA[0], XI[0]), db(apply(w1, XA), apply(w1, XI)), db(apply(w2, XA), apply(w2, XI))
        print(f"{scene:12s} | {r0:6.1f} | {r1:6.1f} | {r2:26.1f}")

        sf.write(f"{OUT}/{scene}_8ch.wav", (mix * scale).T, FS)
        sf.write(f"{OUT}/{scene}_mic1.wav", mix[0] * scale, FS)
        sf.write(f"{OUT}/{scene}_mpdr.wav", to_time(apply(w1, X)) * scale, FS)
        sf.write(f"{OUT}/{scene}_mvdr_ego.wav", to_time(apply(w2, X)) * scale, FS)
        if scene == "everything":
            sf.write(f"{OUT}/everything_egonoise_only_8ch.wav", (e * scale).T, FS)

    for k, y in ego.items():
        sf.write(f"{OUT}/noise_{k}_mic1.wav", y[0] / (np.max(np.abs(y[0])) + 1e-12) * 0.7, FS)

    idx = np.arange(0, N, FS // 100)
    np.savetxt(f"{OUT}/motor_state.csv",
               np.column_stack([t[idx], ms["fan_rpm"][idx], ms["neck_vel"][idx],
                                ms["shoulder_vel"][idx], ms["walking"][idx]]),
               delimiter=",", fmt="%.4f",
               header="time_s,fan_rpm,neck_vel_rad_s,shoulder_vel_rad_s,walking", comments="")
    print(f"\nFiles written to {OUT}")


if __name__ == "__main__":
    main()
