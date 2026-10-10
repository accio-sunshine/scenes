"""
Experiment 24: the firmware's FIR instead of the stand-in.
The same PDM bits go through two copies of the AM243x front-end: pdm.frontend() (Python stand-in FIR, used in
exp22) and pdm.frontend_fw() (the firmware's integer maths: Q27 table from audio_pipe, 64-bit accumulator, Q32 DC
blocker, 24-bit saturation). How different are they, and how much of exp22's SI-SDR came from the stand-in?
1 mic (mic 1). The 8-mic run is exp25. See rOBO docs/PLAN_FW_MODEL_AND_8MIC.md, step A.

Run from the robot-audio folder:
    python experiments/exp24_firmware_fir.py                          # simulated two_far scene
    python experiments/exp24_firmware_fir.py robot_acoustic_custom.zip 4   # web page zip or 8-ch WAV, seconds
Results: results/exp24_firmware_fir[_<scene>]/ (summary.txt, fir_response.csv, mic1 WAVs and int PCM)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "hil"))
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

import make_pdm  # noqa: E402
import pdm  # noqa: E402
import toolkit as tk  # noqa: E402

NAME = "exp24_firmware_fir"
if len(sys.argv) > 1:           # one results folder per scene, so runs never overwrite each other
    NAME += "_" + os.path.splitext(os.path.basename(sys.argv[1]))[0]
DUR = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
SKIP = 400                      # samples dropped at each end (filter start-up), as in exp22
FW_SCALE = 2 ** 23              # firmware PCM full scale


def ideal_frontend(x, hi=7000):
    """Same reference as exp22: pass up to 7 kHz, then the same (float) DC blocker."""
    X = np.fft.rfft(x)
    X[np.fft.rfftfreq(len(x), 1 / pdm.FS) > hi] = 0
    return pdm.dc_block(np.fft.irfft(X, len(x)))


def fw_float(bits, n):
    """Firmware PCM as float (full scale 1.0), padded at the end to n samples (it is 1-2 samples shorter)."""
    y = pdm.frontend_fw(bits) / FW_SCALE
    return np.r_[y, np.zeros(n - len(y))]


def fir_firmware_float():
    """The firmware table back to a float FIR in the stand-in's units (newest input first, 63 taps)."""
    t = pdm.fir_table_q27()[::-1][:63].astype(np.float64)
    return t / 2 ** 27 / (FW_SCALE / pdm.FW_HALF_SCALE)


def response_db(h, f):
    """|H| of FIR h at 32 kHz times the CIC3 /96 droop, in dB."""
    w = 2 * np.pi * f / 32000
    H = np.abs(np.exp(-1j * np.outer(w, np.arange(len(h)))) @ h)
    cic = np.abs(np.sinc(f * pdm.CIC_R / pdm.FS_PDM) / np.sinc(f / pdm.FS_PDM)) ** 3
    return 20 * np.log10(np.maximum(H * cic, 1e-12))


def sinad_fit_db(y, f0, skip=2000):
    """SINAD by least-squares sine fit (IEEE 1057 style): fit DC + sine at f0, the rest is noise + distortion.
    Unlike pdm.sinad_db (Hann FFT), it doesn't depend on the tone landing on an FFT bin or on the length."""
    y = y[skip:]
    n = np.arange(len(y))
    A = np.c_[np.ones(len(y)), np.cos(2 * np.pi * f0 * n / pdm.FS), np.sin(2 * np.pi * f0 * n / pdm.FS)]
    c, *_ = np.linalg.lstsq(A, y, rcond=None)
    return 10 * np.log10(np.sum((A[:, 1:] @ c[1:]) ** 2) / np.sum((y - A @ c) ** 2))


def broadband(n, hi=7000, seed=1):
    x = np.fft.irfft(np.fft.rfft(np.random.default_rng(seed).standard_normal(n))
                     * (np.fft.rfftfreq(n, 1 / pdm.FS) < hi), n)
    return 0.5 * x / np.max(np.abs(x))


def main():
    folder = tk.result_dir(NAME)
    rows = []

    # 1. The two FIRs (each times the CIC3 droop): passband, 7 kHz edge, alias band
    taps = {"stand-in": pdm.fir_taps(), "firmware": fir_firmware_float()}
    f = np.arange(0, 16001, 10.0)
    resp = {k: response_db(h, f) for k, h in taps.items()}
    pb, sb = (f >= 100) & (f <= 6000), f >= 9000
    for k, r in resp.items():
        rows.append([f"{k} FIR x CIC3: passband 100 Hz-6 kHz",
                     f"{r[pb].min():+.3f} to {r[pb].max():+.3f} dB; at 7 kHz {r[f == 7000][0]:+.2f} dB; "
                     f"at 8 kHz {r[f == 8000][0]:+.1f} dB"])
        rows.append([f"{k} FIR x CIC3: worst in 9-16 kHz (folds onto 0-7 kHz)", f"{r[sb].max():.1f} dB"])
    rows.append(["firmware table: taps sum (DC gain of FIR alone)", f"{taps['firmware'].sum():.6f}"])
    np.savetxt(os.path.join(folder, "fir_response.csv"), np.c_[f, resp["stand-in"], resp["firmware"]],
               delimiter=",", header="freq_hz,standin_db,firmware_db", comments="", fmt="%.4f")

    # 2. Tones on 1 mic through both chains. Sine-fit SINAD over the whole 0-8 kHz output band.
    #    pdm.sinad_db (as in exp22) is shown too: it is leakage-limited when the tone is off an FFT bin
    #    (250 Hz here) or when the record is 2 samples shorter (the firmware's output).
    t = np.arange(8000) / pdm.FS
    for f0 in (250, 1000, 3000, 6000, 7000):
        x = 0.5 * np.sin(2 * np.pi * f0 * t)
        bits = pdm.to_pdm(x)
        a, b = pdm.frontend(bits), pdm.frontend_fw(bits) / FW_SCALE
        ga = 20 * np.log10(np.std(a[2000:]) / np.std(x[2000:]))
        gb = 20 * np.log10(np.std(b[2000:]) / np.std(x[2000:len(b)]))
        rows.append([f"tone {f0} Hz, SINAD (sine fit) / gain",
                     f"stand-in {sinad_fit_db(a, f0):.1f} dB / {ga:+.2f} dB;  firmware {sinad_fit_db(b, f0):.1f} dB / {gb:+.2f} dB"])
        rows.append([f"tone {f0} Hz, SINAD (exp22 FFT method)",
                     f"stand-in {pdm.sinad_db(a, f0):.1f} dB;  firmware {pdm.sinad_db(b, f0):.1f} dB (leakage-limited, see notes)"])

    # 3. Delay of each chain, broadband input (a single tone gives the delay estimate nothing to fit)
    x = broadband(16000)
    bits = pdm.to_pdm(x)
    da = pdm.delay_samples(pdm.frontend(bits), x)
    db = pdm.delay_samples(fw_float(bits, len(x)), x)
    rows.append(["delay vs input, stand-in / firmware",
                 f"{da:.2f} / {db:.2f} samples = {da / 16:.3f} / {db / 16:.3f} ms "
                 f"(firmware drops 3 warm-up 32 kHz samples: 1.5 samples earlier)"])

    # 4. The scene, mic 1, both chains vs the ideal front-end
    if len(sys.argv) > 1:
        mix, _ = make_pdm.load_scene(sys.argv[1])
        label = os.path.basename(sys.argv[1])
    else:
        mix, label = tk.build_scene(**dict(tk.TEST_SET)["two_far"]).mix, "simulated two_far"
    x8 = mix[:, :int(DUR * pdm.FS)]
    stream, scale = make_pdm.scene_to_stream(x8)
    ref = x8[0] * scale
    bits1 = pdm.unpack(stream)[0]
    ideal = ideal_frontend(ref)[SKIP:-SKIP]
    out = {"stand-in": pdm.frontend(bits1), "firmware": fw_float(bits1, len(ref))}
    for k, y in out.items():
        d = pdm.delay_samples(y, ref, band=(1000, 3400))
        y = pdm.shift(y, -d)[SKIP:-SKIP]
        rows.append([f"scene mic 1, {k}: SI-SDR vs ideal front-end", f"{tk.si_sdr(y, ideal):.1f} dB (delay {d:.2f} samples)"])
        sf.write(os.path.join(folder, f"mic1_{k.replace('-', '')}.wav"), y, pdm.FS, subtype="FLOAT")
    # Where the error sits: SI-SDR again with the reference and outputs band-limited to 4 kHz
    # (plain low-pass only: the outputs and the ideal reference have each been through the DC blocker once already)
    def lp(v, hi=4000):
        V = np.fft.rfft(v)
        V[np.fft.rfftfreq(len(v), 1 / pdm.FS) > hi] = 0
        return np.fft.irfft(V, len(v))
    ideal_full = ideal_frontend(ref)
    for k, y in out.items():
        d = pdm.delay_samples(y, ref, band=(1000, 3400))
        y = lp(pdm.shift(y, -d))[SKIP:-SKIP]
        rows.append([f"scene mic 1, {k}: SI-SDR, everything cut at 4 kHz", f"{tk.si_sdr(y, lp(ideal_full)[SKIP:-SKIP]):.1f} dB"])
    hi = np.fft.rfftfreq(len(ref), 1 / pdm.FS)
    R = np.abs(np.fft.rfft(ref)) ** 2
    rows.append(["scene mic 1: share of energy at 4-7 kHz", f"{100 * R[(hi >= 4000) & (hi <= 7000)].sum() / R.sum():.2f} %"])

    pcm = pdm.frontend_fw(bits1).astype(np.int32)
    pcm.tofile(os.path.join(folder, "mic1_firmware_pcm_int32.bin"))     # for exp26 (simulator vs this)
    bits1.tofile(os.path.join(folder, "mic1_pdm_bits.bin"))
    sf.write(os.path.join(folder, "mic1_ideal.wav"), ideal, pdm.FS, subtype="FLOAT")

    notes = [f"Scene: {label}; first {DUR:.0f} s, scaled by {scale:.3f} (peak {make_pdm.PEAK} of full scale); only mic 1.",
             "frontend_fw() matches audio_pipe's reference model exactly (hil/tests); audio_pipe's own test shows pdm_rx.asm matches that model on the simulator.",
             "Not run on the simulator here (that is exp26). The firmware's start phase vs the stream is not known yet; here it is the first bit.",
             "mic1_firmware_pcm_int32.bin: firmware-exact PCM (full scale 2^23), little-endian int32, for the exp26 comparison.",
             "SI-SDR reference and its 7 kHz cut are the same as exp22.",
             "exp22's FFT SINAD (pdm.sinad_db) floors at ~82-88 dB when the tone is off an FFT bin or the record is not 8000 samples; exp22's 500 Hz 82.6 dB is that floor, not the front-end. Sine-fit SINAD is the number to use."]
    tk.save_table(NAME, "Firmware FIR vs stand-in FIR on the same PDM bits (1 mic)", ["check", "result"], rows, "\n".join(notes))


if __name__ == "__main__":
    main()
