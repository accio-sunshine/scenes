"""
Experiment 18 (Phase 7): the robot's own noise (fan, servos, footsteps, clicks, hum).
Runs sim_8mic_robot_noise.py and saves its scenes here instead of sim_noise_out/.

Run from the robot-audio folder:  python experiments/exp18_robot_noise_scenes.py
Results: results/exp18_robot_noise_scenes/
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import sim_8mic_robot_noise as rn  # noqa: E402

rn.OUT = os.path.join(ROOT, "results", "exp18_robot_noise_scenes")
os.makedirs(rn.OUT, exist_ok=True)
rn.main()
