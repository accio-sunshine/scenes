"""
Experiment 2 (Phase 1): what array size does.
Echo fixed at 0.5 s; only the array radius changes (3, 5 and 10 cm).
Listen to 2_delay_and_sum_A.wav in each folder.

Run from the robot-audio folder:  python experiments/exp02_array_size.py
Results: results/exp02_array_size/
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim_8mic_room import run_experiment  # noqa: E402

run_experiment(
    "exp02_array_size",
    "How does the array size change direction finding and beamforming?",
    [
        ("r3cm", dict(radius=0.03)),
        ("r5cm", dict(radius=0.05)),
        ("r10cm", dict(radius=0.10)),
    ],
)
