"""
Experiment 26: the real capture firmware (audio_pipe pdm_rx.asm) on TI's pru-simulator, fed with a scene's PDM bits.
One mic, a short clip. Its PCM is compared sample for sample with pdm.frontend_fw() (exp24/exp25's Python copy) and
with audio_pipe's own reference model. A difference of 0 means the firmware outputs exactly what exp25 predicted.
See rOBO docs/PLAN_FW_MODEL_AND_8MIC.md, step C.

How the bits get in: the simulator's SD channel normally makes its own test signal. audio_pipe's test rig (tests/
test_pdm_rx.py, class Rig) wraps that channel's bit source to record every bit; here the bit source is replaced by the
scene's bits for one mic. The PRU player is NOT in the loop (the simulator's SD input has no pin to wire it to), so
this tests the firmware, not the player-to-capture wiring.

Run from the robot-audio folder:
    python experiments/exp26_firmware_on_simulator.py [pdm_stream.bin] [mic 1-8] [start_s] [pcm_samples]
    default: the exp25 stream of robot_acoustic_custom, mic 1, start 1.0 s, 800 samples (50 ms)
Results: results/exp26_firmware_on_simulator_mic<N>/
Needs: the pru-simulator (PRU_SIM or Downloads) and audio_pipe (AUDIO_PIPE, default Downloads/PRU/audio_pipe_src/audio_pipe).
"""
import importlib.util
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "hil"))
import numpy as np  # noqa: E402

import pdm  # noqa: E402
import pru_player  # noqa: E402
import toolkit as tk  # noqa: E402

DEFAULT_STREAM = os.path.join(ROOT, "results", "exp25_firmware_8mic_robot_acoustic_custom", "pdm_stream.bin")
STREAM = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] not in ("", "-") else DEFAULT_STREAM
MIC = int(sys.argv[2]) if len(sys.argv) > 2 else 1
START_S = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
N_PCM = int(sys.argv[4]) if len(sys.argv) > 4 else 800
NAME = f"exp26_firmware_on_simulator_mic{MIC}_{N_PCM}samples_from{START_S:g}s"    # one folder per setting: no overwriting
AUDIO_PIPE = os.environ.get("AUDIO_PIPE", os.path.join(os.path.expanduser("~"), "Downloads", "PRU", "audio_pipe_src", "audio_pipe"))


def load_rig_module():
    """audio_pipe's test module (it has the Rig class and the exact reference model)."""
    path = os.path.join(AUDIO_PIPE, "tests", "test_pdm_rx.py")
    if not os.path.isfile(path):
        raise SystemExit(f"audio_pipe not found at {AUDIO_PIPE} (set AUDIO_PIPE)")
    os.environ["PRU_SIM_PATH"] = pru_player.PRU_SIM
    spec = importlib.util.spec_from_file_location("audio_pipe_test_pdm_rx", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    if not pru_player.available():
        raise SystemExit("SKIPPED: " + pru_player.NOT_FOUND)
    if not os.path.isfile(STREAM):
        raise SystemExit(f"PDM stream not found: {STREAM} (run exp25 first, or pass a pdm_stream.bin)")
    folder = tk.result_dir(NAME)
    rows = []

    # 1. One mic's bits for the clip (a little more than the firmware will consume)
    stream = np.fromfile(STREAM, np.uint8)
    first = int(START_S * pdm.FS_PDM)
    need = (2 * (N_PCM + 140) + 12) * pdm.CIC_R + 2000          # + room for the last chunk to run past the target
    if first + need > len(stream):
        raise SystemExit(f"stream too short: {len(stream)} bytes, need {first + need}")
    bits = pdm.unpack(stream[first:first + need])[MIC - 1]
    rows.append(["input", f"{os.path.basename(os.path.dirname(STREAM))}, mic {MIC}, from {START_S:.2f} s, "
                          f"{N_PCM} PCM samples = {N_PCM / pdm.FS * 1000:.0f} ms"])

    # 2. The firmware on the simulator, with the scene's bits as the SD channel's input
    t = time.time()
    m = load_rig_module()
    rig = m.Rig(0, signal=m.SINE)
    sd_mod = rig.core.io_port.sd_filter.modulators[0]
    feed = iter(bits.tolist())

    def scene_bit():
        try:
            b = next(feed)
        except StopIteration:
            raise RuntimeError("ran out of scene bits: the firmware consumed more than prepared")
        rig.bits.append(b)                      # the rig's reference model reads rig.bits
        return b

    sd_mod.next_bit = scene_bit
    # The firmware's PCM output is a ring of BUF samples (256), so a long clip must be read while it runs:
    # run in chunks of 64 samples and copy what was written. A sample is stored before PCM_COUNT passes it.
    BUF, CHUNK = 256, 64
    got = []
    while len(got) < N_PCM:
        rig.run_pcm(CHUNK)
        count = rig.pcm_count()
        assert count - len(got) <= BUF, "ring overrun: chunk too large"
        ring = rig.pcm(BUF)
        got += [ring[k % BUF] for k in range(len(got), count)]
    n = N_PCM
    fw = np.array(got[:n], np.int64)
    sim_s = time.time() - t
    start = rig.reinits[0]
    rows.append(["simulator run", f"{n} PCM samples in {sim_s:.0f} s wall time, {rig.cycles():,} PRU cycles; "
                                  f"PCM_COUNT {n}, SAMPLE_COUNT {rig.sample_count()}"])
    rows.append(["firmware start phase", f"SD reinit after {start} bits (the firmware's filters start at bit {start} of the clip)"])
    assert rig.bits == bits[:len(rig.bits)].tolist(), "the firmware did not read the scene's bits in order"

    # 3. What exp25's Python copy and audio_pipe's own model predict for the same bits
    py = pdm.frontend_fw(bits[start:len(rig.bits)])[:n]
    ref = np.array(m.reference(rig)[:n], np.int64)
    for label, other in (("pdm.frontend_fw (exp24/25)", py), ("audio_pipe's reference model", ref)):
        d = fw - other
        rows.append([f"firmware vs {label}", f"{int(np.count_nonzero(d))} of {n} samples different, max |diff| {int(np.abs(d).max())} LSB"])
    rows.append(["samples compared", f"{n}, {np.count_nonzero(fw)} of them non-zero; peak {int(np.abs(fw).max()):,} of 8,388,607"])
    rows.append(["first 6 samples: firmware | Python", " ".join(f"{a}" for a in fw[:6]) + "  |  " + " ".join(f"{a}" for a in py[:6])])

    fw.astype(np.int32).tofile(os.path.join(folder, "firmware_sim_pcm_int32.bin"))
    py.astype(np.int32).tofile(os.path.join(folder, "python_frontend_fw_pcm_int32.bin"))
    bits.tofile(os.path.join(folder, "clip_bits.bin"))

    notes = ["Firmware: audio_pipe pdm_rx.asm, unchanged, run on TI's pru-simulator (200 MHz core, SD channel 0).",
             "The SD channel's input is the scene's bits for one mic; the PRU player is not involved (the simulator has no pin wiring to the SD input).",
             f"Same build options as audio_pipe's tests (DC blocker on). Only mic {MIC} of 8, one short clip, one scene.",
             "A match here shows the firmware equals the Python copy on these bits. It does not test the right-hand mics' clock edge, 8 channels, clpru, or a board."]
    tk.save_table(NAME, "Does the capture firmware on the simulator give exactly the numbers Python predicts?",
                  ["check", "result"], rows, "\n".join(notes))


if __name__ == "__main__":
    main()
