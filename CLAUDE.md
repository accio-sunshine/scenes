# CLAUDE.md — Scene Simulator v2 (Personal Claude)

This is the 8-mic humanoid robot acoustic front-end project. The Scene Simulator is the web-based acoustic scene builder at `web/robot_acoustic.html`.

## Project Structure

```
robot-audio/
├── web/                          # Scene Simulator (this repo's main deliverable)
│   ├── robot_acoustic.html       # Built page (do NOT edit; built by python build.py)
│   ├── build.py                  # Concatenates engine.js + scenarios.js into template
│   └── src/
│       ├── engine.js             # Audio engine (rooms, sources, mics, beamforming)
│       ├── scenarios.js          # Home, Factory, Hospital, Automobile + noise generators
│       └── robot_acoustic.template.html  # UI template
├── hil/                          # Downstream: PDM Frontend-in-the-Loop
│   ├── make_pdm.py               # Reads Scene Simulator zip -> pdm_stream.bin + player.asm
│   └── tests/test_hil.py         # 31 tests (schema-1/2 zips, 8-mic guard)
├── experiments/                  # Pipeline experiments (exp22 = Frontend-in-the-Loop)
├── voices/                       # male.wav, female.wav, baby.wav (base64'd into page)
└── sim_*.py                      # Legacy Python simulator (phases 0-7)
```

## Build & Test

```bash
cd web

# Build to a scratch file (doesn't overwrite published page)
python build.py --out "$TEMP/scene_sim_dev.html" --no-published-map

# Headless load check (Playwright). In a cloud container, launch with executable_path="/opt/pw-browsers/chromium"
python tests/ui_headless.py "$TEMP/scene_sim_dev.html"

# Run all web tests
node tests/engine_regression.js      # v1 regression (vs tests/fixtures/engine_v1.js) + new features
node tests/scenarios_test.js         # All 4 scenarios, 27 generators, ambience WAVs
python -m pytest ../hil/tests -q     # 31 hil tests
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
| Downstream 8-mic handling | `hil/make_pdm.py` — `load_scene()` reads schema 1 or 2, refuses ≠8 mics |

## Common Commands (from repo root)

```bash
# Rebuild published page
cd web && python build.py

# Run downstream pipeline (needs .venv)
cd .. && .venv/Scripts/python.exe experiments/exp22_frontend_in_loop.py scene.zip 4
.venv/Scripts/python.exe experiments/exp24_firmware_fir.py scene.zip 4
.venv/Scripts/python.exe experiments/exp25_firmware_8mic.py scene.zip 4
```

## Known Gaps (as of 2026-10-10)

- **Side view** for elevation: not built. Elevation set via sliders or Page Up/Down on a marker only. **Next step.**
- **Python comparison column** and zip contents in "Custom" not checked.
- **All ambience is synthesised**: no recorded rooms/machines/cars. Realism is qualitative only.
- **SRP elevation**: a planar ring reports `el: null` (it can't resolve elevation). Dual ring estimates it in 15° steps;
  coarse, and a gap well above ~5 cm aliases at 3.5 kHz (one miss seen at 20 cm).
- `hil` tests: 5 skip here (need `PRU_SIM` / `AUDIO_PIPE` on MK's PC).

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

```bash
# From repo root (robot-audio/)
git add -A
git commit -m "Scene Simulator v2: 4 scenarios, 3D sources, variable mics, damping, side view TODO"
git push origin main
```

The GitHub remote is `https://github.com/accio-sunshine/Scene_Simulator.git`.