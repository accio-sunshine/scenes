"""
score_whisper.py  -  Phase 5: score every output with speech recognition.

Transcribes the WAV files from sim_conversation_out/ with Whisper (running locally
on your CPU) and computes word error rate (WER) against what was actually said.
Lower WER = better. 0% = perfect, 100% = nothing right (it can exceed 100%
when the recognizer adds extra words, e.g. from the other speaker leaking in).

Install once:  pip install faster-whisper jiwer
Run:           python score_whisper.py            (base.en model, ~150 MB download on first run)
               python score_whisper.py small.en   (bigger, slower, more accurate)
Output:        results/wer_results.csv and results/transcripts.txt
"""
import csv
import os
import re
import sys

import jiwer

MODEL = sys.argv[1] if len(sys.argv) > 1 else "base.en"
FOLDER = "sim_conversation_out"
OUTDIR = "results"            # where wer_results.csv and transcripts.txt go
MALE = "Hi there, how are you doing today?"
FEMALE = "I'm good. What is the plan for the day?"
BOTH = f"{MALE} {FEMALE}"

SCENES = [("conversation_baby", "Baby crying"),
          ("conversation_baby_fan", "Baby + fan"),
          ("conversation_baby_robot", "Baby + robot moving")]

# (file suffix, row label, what the output *should* contain)
OUTPUTS = [("_mic1.wav", "Mic 1 alone (both speakers)", BOTH),
           ("_beam_male.wav", "Beam at man", MALE),
           ("_beam_female.wav", "Beam at woman", FEMALE),
           ("_beam_male_learned.wav", "Beam at man, learned robot noise", MALE),
           ("_beam_female_learned.wav", "Beam at woman, learned robot noise", FEMALE)]


CONTRACTIONS = {"i'm": "i am", "what's": "what is", "it's": "it is", "you're": "you are",
                "how's": "how is", "that's": "that is", "we're": "we are", "let's": "let us"}


def normalise(text):
    """Lower-case, expand common contractions, drop punctuation, so 'What's' == 'What is'."""
    text = text.lower().replace("’", "'")
    for short, full in CONTRACTIONS.items():
        text = re.sub(rf"\b{re.escape(short)}\b", full, text)
    text = re.sub(r"[^a-z0-9 ]+", "", text.replace("-", " "))
    return re.sub(r"\s+", " ", text).strip()


def load_model():
    from faster_whisper import WhisperModel
    print(f"Loading Whisper '{MODEL}' (first run downloads it)...")
    return WhisperModel(MODEL, device="cpu", compute_type="int8")


def transcribe(model, path):
    segments, _ = model.transcribe(path, language="en", beam_size=5,
                                   vad_filter=False, condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segments).strip()


def main():
    if not os.path.isdir(FOLDER):
        sys.exit(f"Can't find {FOLDER}/ - run python sim_conversation.py first.")
    model = load_model()
    os.makedirs(OUTDIR, exist_ok=True)
    rows = []

    # Baseline: the clean voices, before the room. If these aren't near 0%,
    # the recognizer struggles with the voices themselves (e.g. text-to-speech).
    jobs = [("Clean (no room)", "Man, clean", "clean_male.wav", MALE),
            ("Clean (no room)", "Woman, clean", "clean_female.wav", FEMALE)]
    for scene, scene_label in SCENES:
        for suffix, label, ref in OUTPUTS:
            jobs.append((scene_label, label, scene + suffix, ref))

    with open(os.path.join(OUTDIR, "transcripts.txt"), "w", encoding="utf-8") as log:
        for scene_label, label, fname, ref in jobs:
            path = os.path.join(FOLDER, fname)
            if not os.path.exists(path):
                continue
            hyp = transcribe(model, path)
            wer = 100 * jiwer.wer(normalise(ref), normalise(hyp) or "<nothing>")
            rows.append((scene_label, label, round(wer, 1), hyp))
            log.write(f"[{scene_label}] {label}\n  said:  {ref}\n  heard: {hyp}\n  WER:   {wer:.0f}%\n\n")
            print(f"  {scene_label:20s} | {label:36s} | WER {wer:5.0f}% | {hyp}")

    with open(os.path.join(OUTDIR, "wer_results.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["scene", "output", "wer_percent", "transcript"])
        w.writerows(rows)

    print(f"\nSaved {OUTDIR}/wer_results.csv and {OUTDIR}/transcripts.txt")
    print("Note: these sentences are short (7-9 words), so one wrong word moves WER by 10-15%.")


if __name__ == "__main__":
    main()
