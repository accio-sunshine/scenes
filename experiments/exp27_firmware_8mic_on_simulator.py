"""
Experiment 27: the real capture firmware (audio_pipe pdm_rx.asm) on TI's pru-simulator, for all 8 mics of a scene.
exp26 did mic 1. This runs the same experiment for the other mics (as parallel exp26 processes, each in its own
results folder) and collects one 8-mic table: per mic, how many of the firmware's samples differ from the Python copy
(pdm.frontend_fw) and from audio_pipe's reference model. See rOBO docs/PLAN_FW_MODEL_AND_8MIC.md, step D.

What this does NOT test: the right-hand mics are sampled on the other clock edge on the real wire (CLK_INV). The
simulator's SD channel takes a bit stream directly, so it never sees an edge; each mic's bits go in as that mic's
own stream. The edge choice and 2 mics per data line are board questions (D-8).

Run from the robot-audio folder (about 5-10 minutes with 7 processes):
    python experiments/exp27_firmware_8mic_on_simulator.py [pdm_stream.bin] [start_s] [pcm_samples]
    default: the exp25 stream of robot_acoustic_custom, start 1.0 s, 800 samples
Results: results/exp27_firmware_8mic_on_simulator/ (summary.txt). Each mic's own files: results/exp26_..._mic<N>_...
"""
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "hil"))
import numpy as np  # noqa: E402

import toolkit as tk  # noqa: E402

STREAM = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] not in ("", "-") else "-"
START_S = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
N_PCM = int(sys.argv[3]) if len(sys.argv) > 3 else 800
NAME = f"exp27_firmware_8mic_on_simulator_{N_PCM}samples_from{START_S:g}s"
EXP26 = os.path.join(ROOT, "experiments", "exp26_firmware_on_simulator.py")


def mic_folder(m):
    return os.path.join(ROOT, "results", f"exp26_firmware_on_simulator_mic{m}_{N_PCM}samples_from{START_S:g}s")


def main():
    t0 = time.time()
    todo = [m for m in range(1, 9) if not os.path.isfile(os.path.join(mic_folder(m), "firmware_sim_pcm_int32.bin"))]
    print(f"mics to run: {todo or 'none (all already done)'}", flush=True)
    procs = {m: subprocess.Popen([sys.executable, EXP26, STREAM, str(m), f"{START_S:g}", str(N_PCM)], cwd=ROOT,
                                 stdout=open(os.path.join(ROOT, "results", f"_exp27_log_mic{m}.txt"), "w"),
                                 stderr=subprocess.STDOUT) for m in todo}
    for m, p in procs.items():
        p.wait()
        print(f"mic {m}: exit code {p.returncode}  ({time.time() - t0:.0f} s)", flush=True)

    folder = tk.result_dir(NAME)
    rows, total_bad, ok = [], 0, True
    for m in range(1, 9):
        f = mic_folder(m)
        try:
            fw = np.fromfile(os.path.join(f, "firmware_sim_pcm_int32.bin"), np.int32).astype(np.int64)
            py = np.fromfile(os.path.join(f, "python_frontend_fw_pcm_int32.bin"), np.int32).astype(np.int64)
            summary = open(os.path.join(f, "summary.txt"), encoding="utf-8").read()
        except OSError:
            rows.append([f"mic {m}", "NO RESULT (the run failed; see results/_exp27_log_mic%d.txt)" % m])
            ok = False
            continue
        bad = int(np.count_nonzero(fw != py))
        total_bad += bad
        ref_line = re.search(r"audio_pipe's reference model \|\s+(\d+) of (\d+) samples different", summary)
        start = re.search(r"SD reinit after (\d+) bits", summary)
        rows.append([f"mic {m}" + (" (L)" if m % 2 else " (R)") + f", data line {(m - 1) // 2 + 1}",
                     f"{bad} of {len(fw)} different from Python; vs audio_pipe's model: "
                     f"{ref_line.group(1) if ref_line else '?'}; start bit {start.group(1) if start else '?'}; "
                     f"peak {int(np.abs(fw).max()):,}"])
    rows.append(["ALL MICS", ("every sample identical" if total_bad == 0 and ok else f"{total_bad} samples different") +
                 f" (8 mics x {N_PCM} samples = {8 * N_PCM})" + ("" if ok else "; some mics have no result")])
    rows.append(["wall time", f"{time.time() - t0:.0f} s"])
    notes = [f"Same clip for every mic: from {START_S:g} s, {N_PCM} PCM samples; firmware unchanged, SD channel 0, one mic per run.",
             "Mic 1 is exp26's result; mics 2-8 were run by this experiment (as exp26 processes).",
             "The right-hand mics' CLK_INV edge is not exercised (the simulator takes a bit stream, not a pin); one SD channel per run, not 8 at once (exp28).",
             "Not covered: clpru build, the player wired to capture, a board, other scenes or clips."]
    tk.save_table(NAME, "Real capture firmware on the simulator, all 8 mics, vs Python", ["mic", "result"], rows, "\n".join(notes))


if __name__ == "__main__":
    main()
