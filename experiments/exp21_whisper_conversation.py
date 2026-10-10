"""
Experiment 21 (Phase 5 + 7): speech recognition on the conversation scenes.
Runs score_whisper.py on the outputs of experiment 19.

Needs: pip install faster-whisper jiwer. Run experiment 19 first, then:
    python experiments/exp21_whisper_conversation.py
Results: results/exp21_whisper_conversation/wer_results.csv and transcripts.txt
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import score_whisper as sw  # noqa: E402

sw.FOLDER = os.path.join("results", "exp19_conversation_scenes")
sw.OUTDIR = os.path.join("results", "exp21_whisper_conversation")
if not os.path.isdir(sw.FOLDER):
    sys.exit("Run experiments/exp19_conversation_scenes.py first.")
sw.main()
