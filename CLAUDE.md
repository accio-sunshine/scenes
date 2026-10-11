# CLAUDE.md — Scene Simulator v2 (Personal Claude)

This is the 8-mic humanoid robot acoustic front-end project. The Scene Simulator is the web-based acoustic scene builder at `web/robot_acoustic.html`.

## Project Structure

This repo holds only the Scene Simulator. The rest of the robot-audio project (Python simulator, experiments,
HARK, `hil/` PDM pipeline) lives elsewhere; it was removed from this repo on 2026-10-10 (still in git history).

```
scenes/
├── web/
│   ├── robot_acoustic.html       # Built page (do NOT edit; built by python build.py)
│   ├── build.py                  # Concatenates engine.js + scenarios.js into template
│   ├── src/
│   │   ├── engine.js             # Audio engine (rooms, sources, mics, beamforming)
│   │   ├── scenarios.js          # Home, Factory, Hospital, Automobile + noise generators
│   │   └── robot_acoustic.template.html  # UI template
│   └── tests/                    # engine_regression.js (+ fixtures/engine_v1.js), scenarios_test.js, ui_headless.py
├── voices/                       # male.wav, female.wav, baby.wav (base64'd into page)
├── python/                       # score_scene.py (Python cross-check), make_python_scores.py
├── python_out/<scene>/           # Python audio of the 4 scenarios (make_python_scores.py), played by the page
└── sim_conversation_out/, sim_noise_out/   # Python-sim reference WAVs played by the page (build.py asserts them)
```

## Scene Simulator v2 Features

| Feature | Detail |
|---|---|
| **Title** | "Scene Simulator" |
| **Scenarios** | Home, Factory, Hospital, Automobile + Custom (classic tests) |
| **Room** | Length, Width, Height, Echo (RT60), Damping (0 = legacy), noise floor |
| **Speakers** | Up to 5, each with voice, azimuth 0-359°, elevation -60..+90°, distance, loudness, start time, target on/off |
| **Noise sources** | Per-scenario list, on/off, level, position; moving sources tagged |
| **Microphones** | 4/6/8/12/16, ring or dual-ring, radius, array height/position. **Warning shown when count ≠ 8** (PDM pipeline needs 8) |
| **Views** | Top view (drag/keyboard) + elevation sliders (side view not implemented) |
| **Output** | Zip with `mics/mic1..micN.wav`, `settings.json` (schema 2), `scores.csv` (long format) |

## Key Files for Continuing

| Task | Where |
|---|---|
| Add a new scenario | `web/src/scenarios.js` — add to `SCENARIOS` and `SCENARIO_ORDER` |
| Add a noise generator | `web/src/scenarios.js` — add to `NOISE_GEN` (prefix helpers `sc`) |
| Change beamforming / scoring | `web/src/engine.js` — `render()`, `mpdr()`, `steer()`, SRP |
| Change UI layout / controls | `web/src/robot_acoustic.template.html` — wrapped in a function, no global clashes |
| Downstream 8-mic handling | not in this repo (`hil/make_pdm.py` in the robot-audio project reads schema 1 or 2, refuses ≠8 mics) |

## Known Gaps (as of 2026-10-10)

- **Side view** for elevation: not built. Elevation set via sliders or Page Up/Down on a marker only. **Next step.**
- **Python comparison column** and zip contents in "Custom" not checked.
- **All ambience is synthesised**: no recorded rooms/machines/cars. Realism is qualitative only.
- **SRP elevation**: a planar ring reports `el: null` (it can't resolve elevation). Dual ring estimates it in 15° steps;
  coarse, and a gap well above ~5 cm aliases at 3.5 kHz (one miss seen at 20 cm).

### Python cross-check (2026-10-10)
- `python/score_scene.py` rebuilds a scene from the page's dry sources + placements (zip or `web/tools/export_scene.js`
  folder) with pyroomacoustics and the original Python STFT/MPDR code. Reproduces sim_conversation.py's Baby crying /
  Baby + fan scores within 0.1 dB. `python/make_python_scores.py` -> `web/src/python_scores.json` -> page "Python" column
  (green < 1 dB from the page, yellow 1-2, red > 2) and `python_out/<scene>/*.wav` -> Python recordings for the 4 scenarios.
- Agreement (MVDR, default scenes): classic tests and Factory within ~0.6 dB, Hospital ~0.9, Automobile ~1.2,
  **Home: page 1.3-2.7 dB below Python** (systematic; not damping, not the ambient sources; small-room tail model).
- Page MVDR scores also depend on the random draw of the statistical tail: changing only the RIR seed moved Home
  (no ambient noise) MVDR by up to 2.5 dB. Not shown on the page yet.
- Fixed: engine clamped room W/H to >= 2 m, so the 1.6 x 1.2 m car cabin was simulated as 2.7 x 2 x 2 m.

### Resolved 2026-10-10
- **Engine v1 regression now confirmed passing.** The test used `git show HEAD:web/src/engine.js` as "v1", but HEAD
  was already v2 (it compared v2 to itself). The real v1 engine (accio-sunshine/robot_acoustics @ e655ff9) is vendored at
  `web/tests/fixtures/engine_v1.js`. Scores and mic 1 are bit-exact vs v1; SRP azimuths match v1 too.
- **Damping didn't work**: the 2-pole time-domain crossover leaked the slow low-band tail into the high band, so HF decay
  barely changed (0.28 -> 0.29 s). Now a frequency-domain raised-cosine split (1.5-2.5 kHz): HF 20 dB decay
  0.266 -> 0.111 s at d=0.8 (theory 0.267 -> 0.107), LF unchanged. The test also started too late (measured the floor).
- **SRP regression**: v2 took max over elevation before picking azimuths. On the planar ring, diffuse energy went
  to high elevations and the flat zenith row gave fake peaks (e.g. truth 40/150/250 -> 0/15/30 "90° up"). Planar now
  picks on el = 0 (as v1); dual ring uses max over el, and zenith duplicates are merged.
- **Dual-ring mic order verified**: engine and page agree (mics 1..M/2 lower ring at i·360/(M/2), upper ring offset by half
  a step), tested for 4-16 mics. `settings.json` now also carries `micPositions` (m from array centre, mic 1 first).
- Published `robot_acoustic.html` was still the v1 build; rebuilt.

## Push to GitHub

The GitHub remote is `https://github.com/accio-sunshine/scenes`.
