"""
pyhark_localize.py - run HARK (via PyHARK) on our simulated 8-mic recordings.

Offline processing, following HARK's own PyHARK tutorial (Practice 3-3):
  WAV -> MultiFFT -> LocalizeMUSIC -> SourceTracker -> GHDSS -> Synthesize -> SaveWavePCM

It prints where HARK finds sound sources (to compare with the Python results)
and saves one separated WAV per tracked source into hark_out/, which you can
listen to and score with Whisper like the beamformer outputs.

Before running: make the transfer function in HARKTOOL5-GUI from
hark/mic_positions.xml + hark/source_positions.xml (Use Geometric Calculation,
FFT length 512, sampling rate 16000) and save it as hark/tf_8mic.zip.

Run (from the robot-audio folder):
  python pyhark_localize.py
  python pyhark_localize.py sim_conversation_out/conversation_baby_robot_8ch.wav
  python pyhark_localize.py <wav> <tf.zip> <num_sources> <thresh>
"""
import math
import os
import sys
from collections import defaultdict

import numpy as np
import soundfile as sf
from numpy.lib.stride_tricks import sliding_window_view

import hark

WAV = sys.argv[1] if len(sys.argv) > 1 else "sim_conversation_out/conversation_baby_8ch.wav"
TF = sys.argv[2] if len(sys.argv) > 2 else "hark/tf_8mic.zip"
NUM_SOURCE = int(sys.argv[3]) if len(sys.argv) > 3 else 3
THRESH = float(sys.argv[4]) if len(sys.argv) > 4 else 26.0   # lower = more sources found
LENGTH, ADVANCE = 512, 160                                   # HARK's usual framing at 16 kHz
OUT = "hark_out"
EXPECTED = "man ~40, woman ~150, baby ~250 deg (robot fan, if present, ~180)"


def iter_sources(tracker_output):
    """Yield (frame, source_id, azimuth_deg) from SourceTracker output.
    PyHARK's exact return structure isn't documented in the tutorial, so this
    tries the likely shapes; if none fit, it prints one raw item for us to inspect."""
    shown = False
    for t, frame in enumerate(tracker_output):
        if frame is None or (hasattr(frame, "__len__") and len(frame) == 0):
            continue
        items = frame.values() if isinstance(frame, dict) else frame
        for s in items:
            def get(k):
                return s.get(k) if isinstance(s, dict) else getattr(s, k, None)
            az = get("azimuth")
            if az is None:
                pos = get("x") if get("x") is not None else get("pos")
                if pos is not None and len(pos) >= 2:
                    az = math.degrees(math.atan2(pos[1], pos[0]))
            if az is None and not shown:
                print("\n[debug] couldn't read an azimuth from this item - please paste this into the chat:")
                print("        type:", type(s), "\n        value:", repr(s)[:500])
                shown = True
            if az is not None:
                yield t, get("id"), float(az) % 360


def main():
    if not os.path.exists(TF):
        sys.exit(f"Transfer function not found: {TF}  (make it in HARKTOOL5-GUI first)")
    os.makedirs(OUT, exist_ok=True)

    # HARK expects integer-scale samples; read as int16 and convert to float.
    audio, rate = sf.read(WAV, dtype="int16")
    audio = audio.astype(np.float32)
    nch = audio.shape[1]
    print(f"{WAV}: {nch} channels, {rate} Hz, {len(audio)/rate:.1f} s")
    if rate != 16000 or nch != 8:
        print("  warning: expected 8 channels at 16 kHz")
    frames = sliding_window_view(audio, LENGTH, axis=0)[::ADVANCE, :, :]

    spec = hark.node.MultiFFT()(INPUT=frames)

    # Identity noise correlation matrix (= plain SEVD MUSIC, no noise whitening).
    noise_cm = np.broadcast_to(np.eye(nch, dtype=np.complex64).flatten(),
                               (frames.shape[0], LENGTH // 2 + 1, nch * nch))
    music = hark.node.LocalizeMUSIC()(
        INPUT=spec.OUTPUT,
        A_MATRIX=TF,
        MUSIC_ALGORITHM="SEVD",
        NOISECM=noise_cm,
        WINDOW_TYPE="PAST",
        NUM_SOURCE=NUM_SOURCE,
        LOWER_BOUND_FREQUENCY=300,
        UPPER_BOUND_FREQUENCY=3500,
        ENABLE_OUTPUT_SPECTRUM=True)

    tracks = hark.node.SourceTracker()(
        INPUT=music.OUTPUT, THRESH=THRESH, PAUSE_LENGTH=1200.0, MIN_SRC_INTERVAL=20.0)

    # ---- localization summary
    by_id = defaultdict(list)
    for t, sid, az in iter_sources(tracks.OUTPUT):
        by_id[sid].append((t, az))
    print(f"\nHARK tracked {len(by_id)} source(s)   (expected: {EXPECTED})")
    for sid, pts in sorted(by_id.items(), key=lambda kv: kv[1][0][0]):
        azs = np.array([a for _, a in pts])
        # circular mean, so 355 and 5 average to 0, not 180
        mean = math.degrees(math.atan2(np.sin(np.radians(azs)).mean(), np.cos(np.radians(azs)).mean())) % 360
        t0, t1 = pts[0][0] * ADVANCE / rate, pts[-1][0] * ADVANCE / rate
        print(f"  id {sid}: about {mean:5.0f} deg, active {t0:.1f}-{t1:.1f} s ({len(pts)} frames)")
    if not by_id:
        print("  none - try a lower THRESH, e.g.: python pyhark_localize.py", WAV, TF, NUM_SOURCE, THRESH - 4)

    # ---- separation (GHDSS) and saving one WAV per source
    sep = hark.node.GHDSS()(INPUT_FRAMES=spec.OUTPUT, INPUT_SOURCES=tracks.OUTPUT,
                            TF_CONJ_FILENAME=TF)
    wave = hark.node.Synthesize()(INPUT=sep.OUTPUT)
    base = os.path.join(OUT, os.path.splitext(os.path.basename(WAV))[0] + "_sep_")
    hark.node.SaveWavePCM()(INPUT=wave.OUTPUT, BASENAME=base)
    print(f"\nSeparated audio saved as {base}<id>.wav - listen and compare with the beamformer outputs.")


if __name__ == "__main__":
    main()
