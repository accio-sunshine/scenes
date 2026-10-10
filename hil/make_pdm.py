"""
make_pdm.py - turn a simulated scene into the files the PRU player plays.

    python hil/make_pdm.py scene_8ch.wav outdir [--seconds 2]
    python hil/make_pdm.py robot_acoustic_custom.zip outdir     # "Download all" zip from the web page

Writes outdir/pdm_stream.bin (one byte per PDM clock, see pdm.pack), outdir/player.asm (the generated PRU
player) and outdir/manifest.json. A scene is either an 8-channel 16 kHz WAV from the Python simulators
(e.g. sim_conversation_out/conversation_baby_fan_8ch.wav) or the web page's zip (mics/mic1.wav ... mic8.wav
plus settings.json; schema 1 or 2). A zip with a mic count other than 8 is refused.
"""
import argparse
import io
import json
import os
import re
import sys
import warnings
import zipfile

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdm  # noqa: E402
import pru_player  # noqa: E402

PEAK = 0.6          # scene peak as a fraction of full scale (modulator limit is 0.7)


def load_scene(path):
    """Returns (x8, settings): (8, n) audio at 16 kHz and the scene settings (dict, empty for a plain WAV).
    The web page's zip has one WAV per mic, all written with the same scale, so mic-to-mic levels are kept."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            settings = json.loads(z.read("settings.json")) if "settings.json" in names else {}
            found = sorted(int(m.group(1)) for m in (re.fullmatch(r"mics/mic(\d+)\.wav", n) for n in names) if m)
            declared = settings.get("micCount") if isinstance(settings, dict) else None
            if declared is not None and declared != len(found):
                warnings.warn(f"{os.path.basename(path)}: settings.json says micCount={declared} but the zip has "
                              f"{len(found)} mic WAVs; using the WAVs found")
            if not found:
                raise ValueError(f"{os.path.basename(path)} is not a web-page scene zip: missing "
                                 + ", ".join(f"mics/mic{m + 1}.wav" for m in range(pdm.N_MICS)))
            if len(found) != pdm.N_MICS:
                raise ValueError(f"{os.path.basename(path)} has {len(found)} microphones, but the PDM pipeline needs "
                                 f"exactly {pdm.N_MICS} (4 data lines x 2). Set Microphones = {pdm.N_MICS} in the "
                                 f"Scene Simulator and download the zip again.")
            missing = [f"mics/mic{m + 1}.wav" for m in range(pdm.N_MICS) if (m + 1) not in found]
            if missing:
                raise ValueError(f"{os.path.basename(path)} is not a valid scene zip: missing {', '.join(missing)}")
            chans = []
            for m in range(pdm.N_MICS):
                x, fs = sf.read(io.BytesIO(z.read(f"mics/mic{m + 1}.wav")))
                if fs != pdm.FS or x.ndim != 1:
                    raise ValueError(f"mics/mic{m + 1}.wav: need mono {pdm.FS} Hz, got {x.ndim} ch at {fs} Hz")
                chans.append(x)
        n = min(len(c) for c in chans)
        return np.stack([c[:n] for c in chans]), settings
    x, fs = sf.read(path, always_2d=True)
    if fs != pdm.FS or x.shape[1] != pdm.N_MICS:
        raise ValueError(f"need an 8-channel {pdm.FS} Hz WAV, got {x.shape[1]} channels at {fs} Hz")
    return x.T, {}


def scene_to_stream(x8, peak=PEAK):
    """(8, n) audio at 16 kHz -> (packed byte stream, scale applied). One scale for all mics, so the level
    and timing differences between mics (the whole point of the array) are untouched."""
    scale = peak / np.max(np.abs(x8))
    bits = np.stack([pdm.to_pdm(x8[m] * scale) for m in range(pdm.N_MICS)])
    return pdm.pack(bits), scale


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene", help="8-channel 16 kHz WAV, or the web page's zip")
    ap.add_argument("outdir")
    ap.add_argument("--seconds", type=float, default=2.0, help="length to convert (default 2 s)")
    a = ap.parse_args()
    try:
        x8, settings = load_scene(a.scene)
    except ValueError as e:
        sys.exit(str(e))
    x8 = x8[:, :int(a.seconds * pdm.FS)]
    os.makedirs(a.outdir, exist_ok=True)
    stream, scale = scene_to_stream(x8)
    stream.tofile(os.path.join(a.outdir, "pdm_stream.bin"))
    with open(os.path.join(a.outdir, "player.asm"), "w") as f:
        f.write(pru_player.generate_asm())
    with open(os.path.join(a.outdir, "manifest.json"), "w") as f:
        json.dump(dict(source=os.path.basename(a.scene), scene_settings=settings, pdm_rate_hz=pdm.FS_PDM, bytes=len(stream),
                       duration_s=len(stream) / pdm.FS_PDM, scale_applied=scale, peak_fraction=PEAK,
                       byte_layout="bits 0-3 left mics of lines 0-3, bits 4-7 right mics; mic 2k left, 2k+1 right"),
                  f, indent=2)
    print(f"{len(stream)} bytes ({len(stream) / pdm.FS_PDM:.2f} s) -> {a.outdir}")


if __name__ == "__main__":
    main()
