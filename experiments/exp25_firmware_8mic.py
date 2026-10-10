"""
Experiment 25: all 8 mics through the firmware-exact front-end.
exp24 compared the firmware chain (pdm.frontend_fw) with the Python stand-in on mic 1. Here every mic of a scene goes
through both chains from the same PDM bits. Do the differences between mics survive (they are what direction finding
uses), and does the SI-SDR per mic match exp22? See rOBO docs/PLAN_FW_MODEL_AND_8MIC.md, step B. Python only: no
simulator, no player.

Run from the robot-audio folder:
    python experiments/exp25_firmware_8mic.py                              # simulated two_far scene
    python experiments/exp25_firmware_8mic.py robot_acoustic_custom.zip 4  # web page zip or 8-ch WAV, seconds
Results: results/exp25_firmware_8mic[_<scene>]/ (summary.txt, per_mic.csv, recovered_fw_8ch.wav, ...)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "hil"))
import numpy as np  # noqa: E402
import pyroomacoustics as pra  # noqa: E402
import soundfile as sf  # noqa: E402

import make_pdm  # noqa: E402
import pdm  # noqa: E402
import toolkit as tk  # noqa: E402

NAME = "exp25_firmware_8mic"
if len(sys.argv) > 1:           # one results folder per scene, so runs never overwrite each other
    NAME += "_" + os.path.splitext(os.path.basename(sys.argv[1]))[0]
DUR = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
SKIP = 400                      # samples dropped at each end (filter start-up), as in exp22 and exp24
FW_SCALE = 2 ** 23


def ideal_frontend(x, hi=7000):
    """Same reference as exp22/exp24: pass up to 7 kHz, then the same (float) DC blocker."""
    X = np.fft.rfft(x)
    X[np.fft.rfftfreq(len(x), 1 / pdm.FS) > hi] = 0
    return pdm.dc_block(np.fft.irfft(X, len(x)))


def fw_float(bits, n):
    """Firmware PCM as float (full scale 1.0), zero-padded at the end to n samples (it is 1-2 samples shorter)."""
    y = pdm.frontend_fw(bits) / FW_SCALE
    return np.r_[y, np.zeros(n - len(y))]


def main():
    folder = tk.result_dir(NAME)
    rows = []

    if len(sys.argv) > 1:
        try:
            mix, settings = make_pdm.load_scene(sys.argv[1])
        except ValueError as e:
            raise SystemExit(str(e))
        label = os.path.basename(sys.argv[1])
    else:
        mix, settings, label = tk.build_scene(**dict(tk.TEST_SET)["two_far"]).mix, {}, "simulated two_far"
    x8 = mix[:, :int(DUR * pdm.FS)]
    n = x8.shape[1]
    stream, scale = make_pdm.scene_to_stream(x8)
    ref = x8 * scale
    bits = pdm.unpack(stream)

    # Same bits, two chains
    chains = {"stand-in": np.stack([pdm.frontend(b) for b in bits]),
              "firmware": np.stack([fw_float(b, n) for b in bits])}
    ref_bl = np.stack([ideal_frontend(r) for r in ref])[:, SKIP:-SKIP]
    out, per_mic = {}, {}
    for k, rec in chains.items():
        d = pdm.delay_samples(rec[0], ref[0], band=(1000, 3400))          # chain delay, same for every mic
        rec = np.stack([pdm.shift(r, -d) for r in rec])[:, SKIP:-SKIP]
        out[k] = rec
        si = np.array([tk.si_sdr(rec[m], ref_bl[m]) for m in range(pdm.N_MICS)])
        delays = np.array([pdm.delay_samples(rec[m], ref_bl[m]) for m in range(pdm.N_MICS)])
        levels = 10 * np.log10(np.mean(rec ** 2, axis=1) / np.mean(ref_bl ** 2, axis=1))
        per_mic[k] = (si, delays, levels)
        rows.append([f"{k}: chain delay", f"{d:.2f} samples = {d / 16:.3f} ms"])
        rows.append([f"{k}: SI-SDR per mic (min / median / max)", f"{si.min():.1f} / {np.median(si):.1f} / {si.max():.1f} dB"])
        rows.append([f"{k}: timing error between mics (max - min)", f"{np.ptp(delays):.4f} samples"])
        rows.append([f"{k}: level change per mic (max - min)", f"{np.ptp(levels):.3f} dB"])

    # Firmware vs stand-in, directly: how far apart are their outputs on each mic?
    diff = out["firmware"] - out["stand-in"]
    rel_db = 10 * np.log10(np.mean(diff ** 2, axis=1) / np.mean(out["stand-in"] ** 2, axis=1))
    rows.append(["firmware - stand-in, per mic (max)", f"{rel_db.max():.1f} dB below the signal"])

    # Direction finding before and after, both chains
    radius = settings.get("radius", 5) / 100 if settings else 0.05            # web page gives cm
    rel = pra.circular_2D_array([0, 0], pdm.N_MICS, 0, radius)                # mic 1 at 0 deg, counter-clockwise
    d0 = tk.find_directions(tk.to_stft(ref_bl), rel)[0]
    rows.append(["SRP-PHAT directions, original (deg)", tk.fmt_angles(d0)])
    for k, rec in out.items():
        rows.append([f"SRP-PHAT directions after {k} (deg)", tk.fmt_angles(tk.find_directions(tk.to_stft(rec), rel)[0])])

    # Files
    si_f, dl_f, lv_f = per_mic["firmware"]
    si_s, dl_s, lv_s = per_mic["stand-in"]
    np.savetxt(os.path.join(folder, "per_mic.csv"),
               np.c_[np.arange(1, pdm.N_MICS + 1), si_s, si_f, dl_s, dl_f, lv_s, lv_f, rel_db], delimiter=",", fmt="%.4f",
               header="mic,sisdr_standin,sisdr_firmware,delay_standin,delay_firmware,level_standin_db,level_firmware_db,"
                      "fw_minus_standin_db", comments="")
    np.stack([pdm.frontend_fw(b) for b in bits]).astype(np.int32).tofile(os.path.join(folder, "firmware_pcm_8ch_int32.bin"))
    stream.tofile(os.path.join(folder, "pdm_stream.bin"))
    sf.write(os.path.join(folder, "recovered_fw_8ch.wav"), out["firmware"].T, pdm.FS, subtype="FLOAT")
    sf.write(os.path.join(folder, "original_inband_8ch.wav"), ref_bl.T, pdm.FS, subtype="FLOAT")

    notes = [f"Scene: {label}; first {DUR:.0f} s, scaled by {scale:.3f} (peak {make_pdm.PEAK} of full scale); all 8 mics.",
             "Both chains get the same PDM bits. SI-SDR reference, 7 kHz cut and trimming are the same as exp22 and exp24.",
             "firmware_pcm_8ch_int32.bin: firmware-exact PCM, shape (8, samples), little-endian int32, full scale 2^23. For exp26-27.",
             "Mic pairing on the wire (mic 2k left, 2k+1 right of data line k) is the player's placeholder; the Python chain does not depend on it.",
             "Not run: simulator, PRU player, real firmware. Start phase of the firmware vs the stream is not known yet (step C)."]
    tk.save_table(NAME, "All 8 mics through the firmware-exact front-end", ["check", "result"], rows, "\n".join(notes))


if __name__ == "__main__":
    main()
