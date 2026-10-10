"""
Experiment 19 (Phase 7): the conversation with a crying baby, fan and robot movement.
Runs sim_conversation.py and saves its scenes here instead of sim_conversation_out/.
Uses the voices/ folder.

Run from the robot-audio folder:  python experiments/exp19_conversation_scenes.py
Results: results/exp19_conversation_scenes/
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import sim_conversation as conv  # noqa: E402

conv.OUT = os.path.join(ROOT, "results", "exp19_conversation_scenes")
conv.main()
