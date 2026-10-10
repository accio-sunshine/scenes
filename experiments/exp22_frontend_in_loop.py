"""
Experiment 22: front-end in the loop.
Does a simulated scene survive being turned into what 8 PDM microphones put on the wire, going through the
AM243x front-end chain (CIC3 /96 -> 63-tap FIR /2 -> DC block), and does the PRU player reproduce that wire
signal exactly?  See hil/README.md.

Run from the robot-audio folder:
    python experiments/exp22_frontend_in_loop.py                        # simulated two_far scene
    python experiments/exp22_frontend_in_loop.py path/to/scene_8ch.wav [seconds]   # any 8-ch 16 kHz WAV
    python experiments/exp22_frontend_in_loop.py robot_acoustic_custom.zip [seconds]  # web page "Download all" zip
Results: results/exp22_frontend_in_loop/ (summary.txt, pdm_stream.bin, player.asm, WAVs)
"""
import json
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
import pru_player  # noqa: E402
import toolkit as tk  # noqa: E402

NAME = "exp22_frontend_in_loop"
if len(sys.argv) > 1:           # one results folder per scene, so runs never overwrite each other
    NAME += "_" + os.path.splitext(os.path.basename(sys.argv[1]))[0]
DUR = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0      # seconds of the scene converted
SKIP = 400                      # samples dropped at each end (filter start-up)
PLAYER_BYTES = 6000             # more than the 4096-byte ring, so the ring wraps
TDV_NS = 100                    # IM73D122: data valid within 100 ns of the clock edge


def ideal_frontend(x, hi=7000):
    """What the front-end should do to the original: pass up to 7 kHz, remove DC with the same blocker.
    Comparing with the raw original instead would score the DC blocker's phase shift near 20 Hz (~22 dB)."""
    X = np.fft.rfft(x)
    X[np.fft.rfftfreq(len(x), 1 / pdm.FS) > hi] = 0
    return pdm.dc_block(np.fft.irfft(X, len(x)))


def load(argv):
    """Returns (mix, label, settings). settings is the web page's knob values (empty for a WAV)."""
    if len(argv) > 1:
        try:
            mix, settings = make_pdm.load_scene(argv[1])
        except ValueError as e:
            raise SystemExit(str(e))
        return mix, os.path.basename(argv[1]), settings
    mix = tk.build_scene(**dict(tk.TEST_SET)["two_far"]).mix
    return mix, "simulated two_far (talkers 40 and 150 deg, RT60 0.5)", {}


def main():
    folder = tk.result_dir(NAME)
    rows = []

    # 1. Tones: is the chain itself flat and clean?
    t = np.arange(8000) / 16000
    for f0 in (500, 1000, 3000, 6000):
        x = 0.5 * np.sin(2 * np.pi * f0 * t)
        y = pdm.frontend(pdm.to_pdm(x))
        gain = 20 * np.log10(np.std(y[2000:]) / np.std(x[2000:]))
        rows.append([f"tone {f0} Hz", f"SINAD {pdm.sinad_db(y, f0):.1f} dB, gain {gain:+.2f} dB"])

    # 2. The scene through PDM and the front-end
    mix, label, settings = load(sys.argv)
    x8 = mix[:, :int(DUR * pdm.FS)]
    stream, scale = make_pdm.scene_to_stream(x8)
    ref = x8 * scale
    rec = np.stack([pdm.frontend(b) for b in pdm.unpack(stream)])
    d = pdm.delay_samples(rec[0], ref[0], band=(1000, 3400))                       # chain delay, same for every mic
    rec = np.stack([pdm.shift(r, -d) for r in rec])[:, SKIP:-SKIP]
    ref_bl = np.stack([ideal_frontend(r) for r in ref])[:, SKIP:-SKIP]
    si = [tk.si_sdr(rec[m], ref_bl[m]) for m in range(pdm.N_MICS)]
    rows.append(["front-end delay", f"{d:.2f} samples = {d / 16:.2f} ms (whole chain, incl. FIR)"])
    rows.append(["SI-SDR per mic vs ideal front-end (min / median)", f"{min(si):.1f} / {np.median(si):.1f} dB"])

    # 3. Different mics hear different things: are the differences between mics kept?
    delays = np.array([pdm.delay_samples(rec[m], ref_bl[m]) for m in range(pdm.N_MICS)])
    rows.append(["timing error between mics (max - min)", f"{np.ptp(delays):.4f} samples"])
    levels = 10 * np.log10(np.mean(rec ** 2, axis=1) / np.mean(ref_bl ** 2, axis=1))
    rows.append(["level change per mic (max - min)", f"{np.ptp(levels):.3f} dB"])

    # 4. Direction finding before and after
    radius = settings.get("radius", 5) / 100                     # web page gives cm; Python scenes use 5 cm
    rel = pra.circular_2D_array([0, 0], pdm.N_MICS, 0, radius)   # mic 1 at 0 deg, counter-clockwise, both tools
    d0 = tk.find_directions(tk.to_stft(ref_bl), rel)[0]
    d1 = tk.find_directions(tk.to_stft(rec), rel)[0]
    rows.append(["SRP-PHAT directions original -> after PDM (deg)", f"{tk.fmt_angles(d0)} -> {tk.fmt_angles(d1)}"])

    # 5. The player on TI's pru-simulator: do the pins show exactly the stream?
    if pru_player.available():
        print("running the PRU player on pru-simulator ...", flush=True)
        part = stream[:PLAYER_BYTES]
        log, info = pru_player.play(part)
        chk = pru_player.check(part, log, info)
        rows.append(["PRU player, pins vs stream", f"{chk['wrong']} wrong of {chk['edges_checked']} edges "
                     f"(ring wraps: {PLAYER_BYTES} > {pru_player.RING_SIZE} bytes), status {info['status']} (1 = done)"])
        rows.append(["PRU player, edge -> data valid", f"{chk['max_latency_ns']:.0f} ns worst case (mic allows {TDV_NS} ns)"])
    else:
        print("SKIPPED the PRU player step: " + pru_player.NOT_FOUND, flush=True)
        rows.append(["PRU player", "SKIPPED: TI pru-simulator not found (set PRU_SIM)"])

    stream.tofile(os.path.join(folder, "pdm_stream.bin"))
    with open(os.path.join(folder, "player.asm"), "w") as f:
        f.write(pru_player.generate_asm())
    if settings:
        with open(os.path.join(folder, "scene_settings.json"), "w") as f:
            json.dump(settings, f, indent=2)
    sf.write(os.path.join(folder, "original_inband_8ch.wav"), ref_bl.T, pdm.FS, subtype="FLOAT")
    sf.write(os.path.join(folder, "recovered_8ch.wav"), rec.T, pdm.FS, subtype="FLOAT")

    notes = [f"Scene: {label}; first {DUR:.0f} s, scaled by {scale:.3f} so the peak is {make_pdm.PEAK} of full scale.",
             "SI-SDR is against the original low-passed at 7 kHz and run through the same DC blocker (vs the raw original: ~22 dB, that is the blocker's phase shift near 20 Hz).",
             "The FIR is a Python stand-in, not the firmware table; swap in the firmware's coefficients for a bit-exact check.",
             "Not modelled: mic self-noise, gain/phase mismatch, the real mic level of -26 dBFS.",
             "Player timing assumes a 250 MHz PRU core, GPI0 clock, R30[3:0] data, not yet checked against the TRM or schematic."]
    tk.save_table(NAME, "Does a simulated scene survive PDM + the AM243x front-end, and does the player reproduce it?",
                  ["check", "result"], rows, "\n".join(notes))


if __name__ == "__main__":
    main()
