"""
Experiment 23 (Phase 1): how far away can the talkers be?
Same room, array and directions; only the talker distance changes.
Farther talkers are quieter relative to the room echo (past the critical
distance the reverberant sound dominates), so direction finding and
beamforming should both get worse.

Run from the robot-audio folder:  python experiments/exp23_talker_distance.py
Results: results/exp23_talker_distance/
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim_8mic_room import run_experiment  # noqa: E402

run_experiment(
    "exp23_talker_distance",
    "How does talker distance affect direction finding and beamforming?",
    [
        ("d075_close", dict(dist=0.75)),
        ("d150_medium", dict(dist=1.5)),
        ("d225_far", dict(dist=2.25)),
    ],
)
