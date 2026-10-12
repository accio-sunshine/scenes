# Scene Simulator

Web-based acoustic scene builder for an 8-microphone humanoid robot head. Pick a scenario (Home, Factory, Hospital,
Automobile, or Custom), place up to 5 talkers and the scenario's noise sources in 3D, set the room (size, RT60,
damping, noise floor) and the mic array (4/6/8/12/16 mics, ring or dual ring), then listen to the mics and the
beamformer outputs and download the scene as a zip.

Open `web/robot_acoustic.html` in a browser. It is a single self-contained page (engine and voices embedded).

## Layout

```
web/
  robot_acoustic.html             built page (do not edit; run python build.py)
  build.py                        engine.js + scenarios.js + voices -> template -> robot_acoustic.html
  src/engine.js                   audio engine: rooms, sources, mics, beamforming, SRP-PHAT
  src/scenarios.js                Home / Factory / Hospital / Automobile + noise generators
  src/robot_acoustic.template.html  UI
  tests/                          engine regression, scenario tests, headless UI check
voices/                           male.wav, female.wav, baby.wav (embedded into the page)
  tools/export_scene.js           writes a scene's dry sources + geometry for the Python check
python/
  score_scene.py                  independent Python check of a scene (pyroomacoustics room + original MPDR code)
  make_python_scores.py           runs it on every scene's defaults -> web/src/python_scores.json (the page's "Python" lines)
python_out/<scene>/               Python audio of the four scenarios (make_python_scores.py), played by the page
sim_conversation_out/, sim_noise_out/   reference WAVs from the Python simulator, played in the
                                  page's "compare with Python" section (build.py checks they exist)
```

## Python cross-check

The page uses a light room model so it can run in a browser. `python/score_scene.py` rebuilds a scene from the page's
own dry sources and placements with pyroomacoustics (image sources up to the Sabine order) and scores it with the
original Python STFT and MPDR code. Close page and Python scores mean the page's quick answers hold for that scene.
It reproduces the original `sim_conversation.py` scores for the Baby crying and Baby + fan tests to within 0.1 dB.

```
pip install numpy scipy soundfile pyroomacoustics
python python/score_scene.py scene_simulator_factory.zip     # any zip from "Download all audio + scores"
python python/make_python_scores.py && (cd web && python build.py)   # refresh the page's Python lines
```

## Build and test

```
cd web
python build.py                                   # rebuild robot_acoustic.html
node tests/engine_regression.js                   # v1 regression + v2 features
node tests/scenarios_test.js                      # 4 scenarios, all noise generators
python tests/ui_headless.py robot_acoustic.html   # needs: pip install playwright
```

## Download zip

`mics/mic1..micN.wav`, `beams/*.wav`, `alone/*.wav`, `scores.csv` (long format), `settings.json`
(schema 2, including `micPositions` in metres from the array centre), and for the Python check `scene.json`
(resolved geometry and levels), `dry/*.wav` (each source before the room, 32-bit float) and `page_scores.json`.
