"""
Experiment 3 (Phase 1): what background noise does.
Echo and array fixed; only the background noise level changes.
SNR = how far the noise is below the talkers: 25 dB quiet, 5 dB loud.
Listen to 1_mic0_input.wav and 3_mvdr_A.wav in each folder.

Run from the robot-audio folder:  python experiments/exp03_background_noise.py
Results: results/exp03_background_noise/
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim_8mic_room import run_experiment  # noqa: E402

run_experiment(
    "exp03_background_noise",
    "How does background noise level affect direction finding and beamforming?",
    [
        ("snr25_quiet", dict(snr_db=25)),
        ("snr15_medium", dict(snr_db=15)),
        ("snr05_loud", dict(snr_db=5)),
    ],
)
