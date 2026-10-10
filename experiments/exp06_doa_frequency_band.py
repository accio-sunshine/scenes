"""
Experiment 6 (Phase 2): can a different frequency band stop echo fooling MUSIC?
The direction finders only look at part of the spectrum (the "DOA band").
Low frequencies carry most speech energy but see the array as very small;
high frequencies give sharper peaks but start to alias above ~4.5 kHz on a
5 cm array. Run in the echoey room (RT60 0.8 s), where MUSIC showed a false
peak near 320-330 deg.

Compare doa_spectrum.png across the folders. (Only the direction finding
changes here; the beamformer columns stay the same.)

Run from the robot-audio folder:  python experiments/exp06_doa_frequency_band.py
Results: results/exp06_doa_frequency_band/
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim_8mic_room import run_experiment  # noqa: E402

run_experiment(
    "exp06_doa_frequency_band",
    "Does changing the frequency band remove MUSIC's false echo peak?",
    [
        ("band_300_3500", dict(rt60=0.8, doa_band=(300, 3500))),
        ("band_500_4000", dict(rt60=0.8, doa_band=(500, 4000))),
        ("band_1000_4000", dict(rt60=0.8, doa_band=(1000, 4000))),
        ("band_1500_4500", dict(rt60=0.8, doa_band=(1500, 4500))),
    ],
)
