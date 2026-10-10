"""
sim_conversation.py  -  a short conversation with a baby crying in the background.

  Male   (at 40 deg, 1.5 m):  "Hi there, how are you doing today?"
  Female (at 150 deg, 1.5 m): "I'm good. What is the plan for the day?"
  Baby crying (at 250 deg, 2.5 m away) the whole time.
  Three scenes: baby only; baby + robot fan; baby + all robot noise
  (fan, neck servo during head turns, shoulder servos during a gesture,
  footsteps while walking, brake clicks, 50 Hz electrical hum).

Needs sim_8mic_robot_noise.py in the same folder (it reuses its room and beamformer code).

Voices - the script looks for these files first, so you can use your own recordings:
  voices/male.wav   voices/female.wav   voices/baby.wav
If missing, it makes them:
  speech: espeak-ng with MBROLA voices (Linux), otherwise pyttsx3 (Windows/Mac system voices)
  baby:   a synthetic cry (a real recording will sound more natural)

Install: pip install pyroomacoustics soundfile scipy numpy pyttsx3
Run:     python sim_conversation.py
Output:  ./sim_conversation_out/
"""
import os
import shutil
import subprocess
import tempfile

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

import sim_8mic_robot_noise as base

FS, N = base.FS, base.N
OUT = "sim_conversation_out"
MALE_TEXT = "Hi there, how are you doing today?"
FEMALE_TEXT = "I'm good. What is the plan for the day?"
ANGLE_MALE, ANGLE_FEMALE, ANGLE_BABY = 40, 150, 250
DIST_TALK, DIST_BABY = 1.5, 2.5
BABY_DB = -6        # baby level vs the male voice at mic 1; raise for a louder baby
# robot noise levels vs the male voice at mic 1 (dB), same as sim_8mic_robot_noise.py
ROBOT_DB = dict(base.LEVEL_DB)
MALE_START, FEMALE_START = 0.3, 2.6   # seconds


# ---------------------------------------------------------------- voices
def _read(path, trim=True):
    x, fs = sf.read(path)
    x = x.mean(axis=1) if x.ndim > 1 else x
    if fs != FS:
        x = resample_poly(x, FS, fs)
    x = x / (np.max(np.abs(x)) + 1e-12)
    if trim:                                   # drop leading/trailing silence
        idx = np.flatnonzero(np.abs(x) > 0.02)
        if len(idx):
            x = x[max(0, idx[0] - 160): idx[-1] + 160]
    return x


def _espeak(text, voice, path):
    if not shutil.which("espeak-ng"):
        return False
    r = subprocess.run(["espeak-ng", "-v", voice, "-s", "150", "-w", path, text], capture_output=True)
    return r.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 1000


def _pyttsx3(text, want, path):
    try:
        import pyttsx3
    except ImportError:
        return False
    eng = pyttsx3.init()
    voices = eng.getProperty("voices")
    female_names = ("zira", "hazel", "susan", "samantha", "victoria", "karen", "female")
    male_names = ("david", "mark", "george", "alex", "daniel", "fred", "male")

    def is_female(v):
        info = f"{v.name} {v.id} {getattr(v, 'gender', '')}".lower()
        return any(n in info for n in female_names)

    def is_male(v):
        info = f"{v.name} {v.id} {getattr(v, 'gender', '')}".lower()
        return any(n in info for n in male_names) and not is_female(v)

    pick = [v for v in voices if (is_female(v) if want == "female" else is_male(v))]
    if not pick:
        pick = voices[1:2] if want == "female" and len(voices) > 1 else voices[:1]
    eng.setProperty("voice", pick[0].id)
    eng.setProperty("rate", 160)
    eng.save_to_file(text, path)
    eng.runAndWait()
    return os.path.exists(path) and os.path.getsize(path) > 1000


def get_voice(kind, text):
    own = os.path.join("voices", f"{kind}.wav")
    if os.path.exists(own):
        print(f"  {kind}: using {own}")
        return _read(own)
    path = os.path.join(tempfile.gettempdir(), f"robot_{kind}.wav")
    mb = "mb-us2" if kind == "male" else "mb-us1"            # MBROLA US male / female
    if _espeak(text, mb, path) or _espeak(text, "en-us+m3" if kind == "male" else "en-us+f3", path):
        print(f"  {kind}: espeak-ng")
    elif _pyttsx3(text, kind, path):
        print(f"  {kind}: pyttsx3 system voice")
    else:
        raise RuntimeError(f"No text-to-speech found. Record yourself saying \"{text}\" "
                           f"and save it as {own}.")
    return _read(path)


def baby_cry(dur, seed=3):
    """Synthetic infant cry: ~380-580 Hz wails with vibrato, formants, and inhale squeaks."""
    rng = np.random.default_rng(seed)
    n_total = int(dur * FS)
    out = np.zeros(n_total)
    t = 0.1
    while t < dur - 0.3:
        L = rng.uniform(0.7, 1.3)
        n = int(L * FS)
        tau = np.linspace(0, 1, n)
        f0 = rng.uniform(380, 480) * (1 + 0.22 * np.sin(np.pi * tau ** 0.8))
        f0 *= 1 + 0.012 * np.sin(2 * np.pi * 7 * tau * L)                 # vibrato
        f0 *= 1 + 0.004 * rng.standard_normal(n).cumsum() / np.sqrt(n)    # wobble
        F1 = 700 + 500 * np.minimum(1, tau * 6)                           # "w" -> "aa"
        F2 = 1700 + 1100 * np.minimum(1, tau * 6)
        phase = 2 * np.pi * np.cumsum(f0) / FS
        sig = np.zeros(n)
        for k in range(1, 20):
            fk = k * f0
            amp = (np.exp(-((fk - F1) / 350) ** 2) + 0.8 * np.exp(-((fk - F2) / 500) ** 2)
                   + 0.4 * np.exp(-((fk - 4000) / 700) ** 2) + 0.05) / k ** 0.3
            sig += amp * (fk < 7500) * np.sin(k * phase)
        breath = np.convolve(rng.standard_normal(n), np.ones(4) / 4, "same") * 0.15
        env = np.minimum(1, tau / 0.08) * np.minimum(1, (1 - tau) / 0.15) ** 1.5
        env *= 1 + 0.15 * np.sin(2 * np.pi * 3 * tau)
        s0 = int(t * FS)
        e = min(n_total, s0 + n)
        out[s0:e] += ((sig + breath) * env)[: e - s0]
        t += L
        il = rng.uniform(0.18, 0.35)                                      # inhale squeak
        m = int(il * FS)
        sq = (0.12 * np.sin(2 * np.pi * rng.uniform(800, 1100) * np.arange(m) / FS)
              + 0.03 * rng.standard_normal(m)) * np.sin(np.pi * np.arange(m) / m)
        s0 = int((t + 0.03) * FS)
        e = min(n_total, s0 + m)
        if e > s0:
            out[s0:e] += sq[: e - s0]
        t += il + 0.05
    return out / np.max(np.abs(out))


def get_baby():
    own = os.path.join("voices", "baby.wav")
    if os.path.exists(own):
        print(f"  baby: using {own}")
        x = _read(own, trim=False)
        return np.tile(x, int(np.ceil(N / len(x))))[:N]
    print("  baby: synthetic cry")
    return baby_cry(N / FS)


def place(sig, start):
    out = np.zeros(N)
    s = int(start * FS)
    out[s:s + len(sig)] = sig[: N - s]
    return out


# ---------------------------------------------------------------- main
def main():
    os.makedirs(OUT, exist_ok=True)
    print("Getting voices:")
    male = place(get_voice("male", MALE_TEXT), MALE_START)
    female = place(get_voice("female", FEMALE_TEXT), FEMALE_START)
    baby = get_baby()
    for name, x in (("male", male), ("female", female), ("baby", baby)):
        sf.write(f"{OUT}/clean_{name}.wav", 0.8 * x / np.max(np.abs(x)), FS)

    centre = np.array([base.ROOM[0] / 2, base.ROOM[1] / 2, 1.5])
    mic_xy = base.pra.circular_2D_array(centre[:2], base.N_MICS, 0, base.RADIUS)
    rel = mic_xy - centre[:2, None]

    def at(angle, dist, dz=0.0):
        a = np.radians(angle)
        return centre + np.array([dist * np.cos(a), dist * np.sin(a), dz])

    yM = base.simulate([(at(ANGLE_MALE, DIST_TALK), male)], centre, mic_xy)
    yF = base.simulate([(at(ANGLE_FEMALE, DIST_TALK), female)], centre, mic_xy)
    yF *= np.sqrt(base.power(yM[0]) / base.power(yF[0]))                 # equal loudness
    yBaby = base.simulate([(at(ANGLE_BABY, DIST_BABY, -0.7), baby)], centre, mic_xy)  # on a bed/cot
    ref = base.power(yM[0])
    yBaby *= np.sqrt(ref / base.power(yBaby[0]) * 10 ** (BABY_DB / 10))
    # ---- robot noises (same sources and positions as sim_8mic_robot_noise.py)
    robot_pos = {"fan": at(180, 0.07, -0.03), "neck": at(0, 0.0, -0.10),
                 "shoulders": at(90, 0.18, -0.30), "footsteps": at(0, 0.10, -1.40),
                 "clicks": at(0, 0.0, -0.10)}

    def robot_noise(keys, seed):
        """Simulate the chosen robot noises; a new seed gives a fresh 'take'."""
        keep, base.rng = base.rng, np.random.default_rng(seed)
        ms = base.motor_state()
        makers = {"fan": lambda: base.make_fan(ms),
                  "neck": lambda: base.make_servo(ms["neck_vel"], 600, 2400),
                  "shoulders": lambda: base.make_servo(ms["shoulder_vel"], 450, 1800),
                  "footsteps": lambda: base.make_footsteps(ms),
                  "clicks": lambda: base.make_clicks(ms)}
        total = np.zeros((base.N_MICS, N))
        for k in keys:
            if k == "hum":
                h = base.make_hum()
                y = np.tile(h, (base.N_MICS, 1))                 # electrical: same on every channel
            else:
                y = base.simulate([(robot_pos[k], makers[k]())], centre, mic_xy)
            total += y * np.sqrt(ref / (base.power(y[0]) + 1e-20) * 10 ** (ROBOT_DB[k] / 10))
        base.rng = keep
        return total

    room_noise = base.rng.standard_normal(yM.shape) * np.sqrt(ref / 10 ** 2.5)
    ALL_ROBOT = ["fan", "hum", "neck", "shoulders", "footsteps", "clicks"]
    scenes = {"conversation_baby": [],
              "conversation_baby_fan": ["fan", "hum"],
              "conversation_baby_robot": ALL_ROBOT}

    for scene, keys in scenes.items():
        robot = robot_noise(keys, seed=1) if keys else 0
        bg = yBaby + robot + room_noise
        mix = yM + yF + bg
        scale = 0.9 / np.max(np.abs(mix))
        sf.write(f"{OUT}/{scene}_8ch.wav", (mix * scale).T, FS)
        sf.write(f"{OUT}/{scene}_mic1.wav", mix[0] * scale, FS)
        if keys:
            sf.write(f"{OUT}/{scene}_robot_only_8ch.wav", (robot * scale).T, FS)
        X = base.to_stft(mix)
        # a separate recording of the robot moving with nobody talking (what you'd capture on the real robot)
        Xrobot = base.to_stft(robot_noise(keys, seed=99) + room_noise[:, ::-1]) if keys else None

        grid = np.linspace(0, 2 * np.pi, 360, endpoint=False)
        doa = base.pra.doa.algorithms["SRP"](rel, FS, base.NFFT, c=base.C, num_src=3, azimuth=grid)
        doa.locate_sources(X, freq_range=[300, 3500])
        print(f"\n{scene}: SRP-PHAT finds sources at {np.sort(np.degrees(doa.azimuth_recon)).round()} deg "
              f"(true: male {ANGLE_MALE}, female {ANGLE_FEMALE}, baby {ANGLE_BABY})")
        print(f"  {'aimed at':8s} | {'mic 1':>6s} | {'beamformer':>10s} | {'+ learned robot noise':>21s}   (target vs everything else, dB)")
        for who, y_target, y_other, angle in (("male", yM, yF, ANGLE_MALE), ("female", yF, yM, ANGLE_FEMALE)):
            d = base.steering(rel, angle)
            XT, XR = base.to_stft(y_target), base.to_stft(y_other + bg)
            w1 = base.mvdr(X, d)
            r0 = base.db(XT[0], XR[0])
            r1 = base.db(base.apply(w1, XT), base.apply(w1, XR))
            sf.write(f"{OUT}/{scene}_beam_{who}.wav", base.to_time(base.apply(w1, X)) * scale, FS)
            if keys:
                w2 = base.mvdr(np.concatenate([X, 3 * Xrobot], axis=2), d)
                r2 = base.db(base.apply(w2, XT), base.apply(w2, XR))
                sf.write(f"{OUT}/{scene}_beam_{who}_learned.wav", base.to_time(base.apply(w2, X)) * scale, FS)
                print(f"  {who:8s} | {r0:6.1f} | {r1:10.1f} | {r2:21.1f}")
            else:
                print(f"  {who:8s} | {r0:6.1f} | {r1:10.1f} | {'-':>21s}")

    print(f"\nFiles written to {OUT}")


if __name__ == "__main__":
    main()
