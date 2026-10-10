"""
Experiment 16 (Phase 5): speech recognition score for the test set.
Transcribes the outputs of experiment 5 with Whisper and computes word error
rate (WER, lower = better). The reference is Whisper's own transcript of
talker A's clean, dry voice, so the score measures what the room and the
processing cost - check that reference line looks right.

Needs: pip install faster-whisper jiwer   (model downloads on first run)
Run experiment 5 first, then from the robot-audio folder:
    python experiments/exp16_whisper_test_set.py          (base.en)
    python experiments/exp16_whisper_test_set.py small.en (bigger model)
Results: results/exp16_whisper_test_set/summary.txt and transcripts.txt
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import jiwer  # noqa: E402
import score_whisper as sw  # noqa: E402
import toolkit as tk  # noqa: E402

NAME = "exp16_whisper_test_set"
SRC = os.path.join("results", "exp05_test_set")
OUTPUTS = [("1_mic0_input.wav", "mic 1"), ("2_delay_and_sum_A.wav", "delay-and-sum"),
           ("3_mvdr_A.wav", "MVDR"), ("5_wpe_then_mvdr_A.wav", "WPE + MVDR")]
if not os.path.isdir(SRC):
    sys.exit("Run experiments/exp05_test_set.py first.")

model = sw.load_model()
ref = sw.transcribe(model, os.path.join(SRC, "one_talker", "clean_A_dry.wav"))
print(f"Reference (Whisper on talker A's clean voice): {ref}")
rows, log = [], [f"Reference: {ref}\n"]
for scene, _ in tk.TEST_SET:
    r = [scene]
    for f, label in OUTPUTS:
        hyp = sw.transcribe(model, os.path.join(SRC, scene, f))
        wer = 100 * jiwer.wer(sw.normalise(ref), sw.normalise(hyp) or "<nothing>")
        r.append(f"{wer:.0f}%")
        log.append(f"[{scene}] {label}: {hyp}  (WER {wer:.0f}%)")
        print(f"  {scene:12s} {label:14s} WER {wer:4.0f}%  {hyp}")
    rows.append(r)
with open(os.path.join(tk.result_dir(NAME), "transcripts.txt"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(log) + "\n")
tk.save_table(NAME, "Which processing makes talker A easiest for speech recognition?",
              ["scene"] + [label + " WER" for _, label in OUTPUTS], rows,
              f"Model {sw.MODEL}. Reference = Whisper on the clean dry voice: \"{ref}\". "
              "One sentence only (~8 words), so one word = ~12%.")
