"""
Experiment 1 (Phase 1): what room echo does.
Same two talkers, same array; only the echo time (RT60) changes.
Listen to 1_mic0_input.wav in each folder, in order.

Run from the robot-audio folder:  python experiments/exp01_echo_levels.py
Results: results/exp01_echo_levels/
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim_8mic_room import run_experiment  # noqa: E402

run_experiment(
    "exp01_echo_levels",
    "What does room echo do to speech and to the processing?",
    [
        ("rt02_dry", dict(rt60=0.2)),
        ("rt05_medium", dict(rt60=0.5)),
        ("rt08_echoey", dict(rt60=0.8)),
    ],
)
