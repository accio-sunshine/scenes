"""
make_hark_xml.py - writes the two XML files HARKTOOL5 needs to build a
geometric (calculated) transfer function for our simulated 8-mic array.

  hark/mic_positions.xml     - where each microphone is (metres, array centre = 0,0,0)
  hark/source_positions.xml  - candidate source directions HARK will search (every 5 deg)

Angles follow the same convention as the simulation scripts: 0 deg = mic 1
direction (+x), 90 deg = +y, counter-clockwise. So HARK's angles should be
directly comparable with the Python results.

Run: python make_hark_xml.py
"""
import math
import os

N_MICS, RADIUS = 8, 0.05        # must match the simulation scripts
SRC_RADIUS = 1.5                # metres; talkers in the sims are 1.5-2.5 m away
STEP_DEG = 5                    # HARK's supported-hardware files also use 5 deg

os.makedirs("hark", exist_ok=True)

mics = []
for i in range(N_MICS):
    a = 2 * math.pi * i / N_MICS
    mics.append(f'  <position x="{RADIUS*math.cos(a):.4f}" y="{RADIUS*math.sin(a):.4f}" z="0.0000" id="{i}" path=""/>')
with open("hark/mic_positions.xml", "w") as f:
    f.write('<hark_xml version="1.3">\n <positions type="microphone" frame="0" coordinate="cartesian">\n')
    f.write("\n".join(mics))
    f.write("\n </positions>\n</hark_xml>\n")

n_src = 360 // STEP_DEG
srcs, nbrs = [], []
for i in range(n_src):
    a = math.radians(i * STEP_DEG)
    srcs.append(f'  <position x="{SRC_RADIUS*math.cos(a):.4f}" y="{SRC_RADIUS*math.sin(a):.4f}" z="0.0000" id="{i}" path="/dummy"/>')
    nbrs.append(f'  <neighbor id="{i}" ids="{i};"/>')
with open("hark/source_positions.xml", "w") as f:
    f.write('<hark_xml version="1.3">\n <positions type="TSP" coordinate="cartesian">\n')
    f.write("\n".join(srcs))
    f.write('\n </positions>\n <neighbors algorithm="NearestNeighbor">\n')
    f.write("\n".join(nbrs))
    f.write("\n </neighbors>\n</hark_xml>\n")

print(f"Wrote hark/mic_positions.xml ({N_MICS} mics) and hark/source_positions.xml ({n_src} directions)")
