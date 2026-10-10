"""
Experiment 4 (Phase 1): how far apart the talkers are.
Talker A stays at 40 deg; talker B moves closer to A (or is absent).
Listen to 3_mvdr_A.wav in each folder: B should leak more as it gets closer.

Run from the robot-audio folder:  python experiments/exp04_talker_spacing.py
Results: results/exp04_talker_spacing/
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim_8mic_room import run_experiment  # noqa: E402

run_experiment(
    "exp04_talker_spacing",
    "How close can two talkers be before the array can't tell them apart?",
    [
        ("one_talker", dict(angle_b=None)),
        ("b150_110deg_apart", dict(angle_b=150)),
        ("b90_50deg_apart", dict(angle_b=90)),
        ("b70_30deg_apart", dict(angle_b=70)),
    ],
)
