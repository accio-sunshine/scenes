"""
Experiment 5 (Phase 1): the fixed test set.
These scenes are reused by every later phase (WPE, Whisper scoring, HARK, masks),
so improvements are always measured on the same audio. Don't change them once
you start comparing results - add a new experiment instead.

Each folder also has clean_A_dry.wav and clean_A_at_mic1.wav for scoring.

Run from the robot-audio folder:  python experiments/exp05_test_set.py
Results: results/exp05_test_set/
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim_8mic_room import run_experiment  # noqa: E402

run_experiment(
    "exp05_test_set",
    "Fixed scenes that every later phase is measured on.",
    [
        ("one_talker", dict(angle_b=None)),
        ("two_far", dict(angle_b=150)),
        ("two_close", dict(angle_b=70)),
        ("dry_room", dict(rt60=0.2)),
        ("echoey_room", dict(rt60=0.8)),
    ],
)
