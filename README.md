# Scene Simulator

Listening tests for a robot's microphone array. Build an acoustic scene around an 8-microphone humanoid robot head
(a room, up to five people and the noise of the place), hear it the way the microphones do, and measure how well
each beamformer picks out every speaker. Each scene's scores are checked against a fuller Python simulation
(pyroomacoustics) of the same scene.

- **Page:** `web/robot_acoustic.html`, a single self-contained file (engine and voices embedded). Open it in a
  browser. For the Python recordings and typed speech, serve the repo folder instead: `python -m http.server` from the
  repo root, then open `http://localhost:8000/web/robot_acoustic.html`.
- **Sample rate:** 16 kHz. **Recording length:** 3 s to 2 min (default 5.5 s).
- Every change re-renders the scene in the background; the status line under the play buttons shows progress.

---

## Contents

1. [Page layout](#1-page-layout)
2. [Scenes](#2-scenes)
3. [Array view](#3-array-view)
4. [Scene setup: Room](#4-scene-setup-room)
5. [Scene setup: Microphones](#5-scene-setup-microphones)
6. [Scene setup: Speakers](#6-scene-setup-speakers)
7. [Scene setup: Noise sources](#7-scene-setup-noise-sources)
8. [Scene setup: Robot's own noise](#8-scene-setup-robots-own-noise)
9. [Scores](#9-scores)
10. [Signal viewer and timeline](#10-signal-viewer-and-timeline)
11. [Tracks](#11-tracks)
12. [Python reference](#12-python-reference)
13. [Download (.zip)](#13-download-zip)
14. [How the sound is made](#14-how-the-sound-is-made)
15. [Python cross-check](#15-python-cross-check)
16. [Repository layout, build and tests](#16-repository-layout-build-and-tests)
17. [Known limits](#17-known-limits)

---

## 1. Page layout

From top to bottom:

| Section | What it is |
|---|---|
| Header | Name, subtitle and a two-sentence introduction. |
| Scene row | Scene tabs (Home, Factory, Hospital, Automobile, Custom) and the selected scene's description. |
| Array view | Top view of the robot head with microphones, speakers and noise sources; legend; where the robot thinks sound comes from; play controls. |
| Scene setup | All settings, in two columns: Room, Microphones, Speakers (left); Noise sources, Robot's own noise (right). |
| Scores | Target-vs-everything-else scores per speaker and method, with the Python check. Download button. |
| Signal viewer | Timeline of who is talking and what the robot is doing, plus the waveform and spectrogram of the selected track. |
| Tracks | Every track you can play: mic 1, beamformers per speaker, each raw microphone, each source alone. |
| Python reference | Recordings from the Python simulation of the selected scene. |
| Footnote | One line on the room model, synthesised noise, levels and credits. |

Coordinates used everywhere: **azimuth 0° = the robot's front**, counter-clockwise when seen from above
(90° = the robot's left). **Elevation** is up from the plane of the array (negative = below). **Distance** is from the
array centre, in metres.

---

## 2. Scenes

Choosing a scene loads a complete set of settings: room, array placement, speakers, noise sources and robot noise.
Anything you change afterwards is kept until you pick a scene again (re-selecting the same tab resets it).

| Scene | Room (L × W × H) | Echo (RT60) | Damping | Noise floor | Speakers | Ambient noise sources |
|---|---|---|---|---|---|---|
| **Home** | 5 × 4 × 2.6 m | 0.45 s | 0.5 | −30 dB | male 20°/5° up, 1.5 m; female 150°, 1.6 m | TV (talk + music), fridge, kitchen clatter + water, vacuum cleaner (moves), door knocks, air-conditioner |
| **Factory / Industry** | 20 × 15 × 7 m | 1.2 s | 0.1 | −18 dB | male 30°, 1.5 m; female 200°, 2.0 m | machine hum + drive whine, stamping press, compressed-air hiss, AGV reverse beeper (moves), two other robots (move), conveyor |
| **Hospital** | 6 × 5 × 3 m | 0.8 s | 0.15 | −28 dB | female 15°, 1.2 m; male 160°, 1.6 m | patient monitor, IV-pump alarm, ventilator, HVAC, PA chime + announcement, trolley (moves), distant chatter |
| **Automobile** | 2.7 × 1.6 × 1.2 m cabin | 0.12 s | 0.7 | −22 dB | driver 210°/11° up, 0.82 m; passenger 150°/11° up, 0.82 m (array on the dashboard) | engine (rpm ramp), road/tyre, wind, HVAC blower, indicator relay, road bumps, radio |
| **Custom (classic tests)** | 6 × 5 × 3 m | 0.5 s | 0 | −25 dB | man 40°, woman 150°, 1.5 m; baby 250°, 2.5 m, 0.7 m below the array | none (robot noise only) |

**Custom** offers the four original test scenes as buttons:

| Classic test | Robot noise |
|---|---|
| Baby crying | none (the robot is still) |
| Baby + fan | cooling fan and 50 Hz hum |
| Robot moving | fan, hum, head turns, arm gesture, brake clicks; footsteps off |
| Quiet room | none, and no baby: just the two people and the room noise floor |

All ambient noise is synthesised from simple models (no recordings). How realistic a scenario sounds is a qualitative
judgement.

---

## 3. Array view

The top view shows the robot head at the centre, its microphones on the rim, distance rings (1 m, 2 m, …), the room
outline as seen from the array, speakers (numbered circles), ambient noise sources (diamonds N1…), the robot's own
noise sources (chips on the head) and red arrows where the robot thinks sound comes from (SRP-PHAT direction finding).

| Action | Effect |
|---|---|
| Drag a speaker or noise source | Moves it (azimuth and distance; elevation is kept). |
| Click a noise source | Switches it on or off. |
| Click a speaker | Jumps to its settings card. |
| Click a microphone | Includes or excludes it from "Play selected mics". |
| Click a robot-noise chip (fan, neck, arm, brakes, hum, feet) | Switches that robot noise on or off. |
| Keyboard, with a marker focused | Arrow keys turn it by 5° (Shift: 1°); `+` / `−` change distance by 0.1 m; Page Up / Page Down change elevation by 5°; Enter on a noise source toggles it. |

A source that would sit outside the room is moved 0.2 m inside it; the marker shows a red "!", the real position is
drawn as a dashed red ring, and a "Heads up" note lists what moved.

**"Robot hears sound from"** lists the directions found by SRP-PHAT (one per speaker) next to the true speaker
directions. A flat ring cannot tell elevation, so it reports azimuth only; a dual ring also reports elevation
(15° steps).

| Button | Effect |
|---|---|
| Play selected mics | Plays the mix of the microphones that are switched on (the mic shapes on the head). Press again to stop. |
| All N mics / Mic 1 only | Quick microphone selections. |
| Stereo for headphones | Pans each microphone left/right by its position on the ring, so the array's spatial cues are audible on headphones. |
| Can't hear anything? Run the sound check | Three test beeps played three different ways (audio element, embedded file, Web Audio), for diagnosing playback problems. |

---

## 4. Scene setup: Room

The room is a rectangular box.

| Setting | Range | Default (Custom) | Meaning |
|---|---|---|---|
| **Recording length** | 3 s, 5.5 s, 10 s, 20 s, 30 s, 1 min, 1.5 min, 2 min | 5.5 s | Length of every recording. Robot head turns, arm gesture and walking repeat every 5.5 s; repeating scene noises (press, beeper, monitor, knocks, bumps, …) continue to the end. Speech plays once from its start time. Rendering time grows with length: about 2 min for Factory at 2 min with 8 mics (3 min with 16), using up to ~2 GB of memory. The Python column applies only at 5.5 s. |
| **Length / Width** | 1 – 30 m (0.1 m steps) | 6 / 5 m | Floor size. |
| **Height** | 1 – 8 m | 3 m | Ceiling height. |
| **Echo time (RT60)** | 0.05 – 1.5 s | 0.5 s | Time for the reverberation to decay by 60 dB. Sets the wall absorption (Sabine). |
| **Damping** | 0 – 1 | 0 | Extra high-frequency absorption. High frequencies decay with RT60 × (1 − 0.75 × damping), the low band keeps the full RT60 (crossover 1.5–2.5 kHz), and early reflections lose more amplitude. 0 = the original v1 room. |
| **Noise floor (below Speaker 1)** | 5 – 40 dB below Speaker 1 | 25 dB | Diffuse random noise on every microphone, at this level below Speaker 1's voice at mic 1. |

Changing the room size re-centres the array while "Put the array at the room centre" is ticked.

---

## 5. Scene setup: Microphones

| Setting | Range | Default | Meaning |
|---|---|---|---|
| **Number of mics** | 4, 6, 8, 12, 16 | 8 | Microphones in the array. A warning appears when it is not 8: the downstream PDM pipeline (`hil/make_pdm.py` in the robot-audio project) needs exactly 8 and rejects other zips. |
| **Layout** | Ring, Dual ring | Ring | **Ring:** all mics on one circle, mic 1 at 0°, counter-clockwise. **Dual ring:** half the mics on a lower ring, half on an upper ring, the upper ring rotated by half a step. Mics 1…N/2 are the lower ring (drawn filled), N/2+1…N the upper ring (drawn as outlines). |
| **Ring radius** | 3 – 10 cm | 5 cm | Radius of the ring(s). |
| **Gap between the two rings** | 2 – 20 cm | 8 cm | Vertical distance between the rings (dual ring only). Gaps much above ~5 cm alias at the top of the direction-finding band (3.5 kHz). |
| **Put the array at the room centre** | on / off | on | Keeps the array at the room's centre, at half the room height limited to 1.2–1.5 m. |
| **Array height above the floor** | 0.2 m to height − 0.2 m | 1.5 m | Moving it unticks "room centre". |
| **Array position along the length / across the width** | 0.2 m to size − 0.2 m | room centre | Moving it unticks "room centre". |

The mics are kept at least 0.2 m inside the room; the page says when it had to move the array.

---

## 6. Scene setup: Speakers

Up to **5 speakers**. "Add speaker" adds the next one (voice, direction and start time from a fixed list); "Remove"
deletes one (the others are renumbered). Each speaker has a colour used everywhere on the page.

| Setting | Range | Meaning |
|---|---|---|
| **Voice** | male, female, male low, female high, baby | Built-in voices are MBROLA text-to-speech recordings ("Hi there, how are you doing today?" / "I'm good. What is the plan for the day?"). Male low and female high are pitch-shifted copies of male and female. The baby is a looping synthetic cry. |
| **Target** | on / off | A **target** is beamformed and scored. An **interferer** (off) only adds sound to the scene; it is drawn as an outline and not scored. |
| **Speech** | Recording, Typed text, Uploaded file | What the speaker says (see below). |
| **Azimuth** | 0 – 359° | Direction around the robot. |
| **Elevation** | −60 to +90° | Up/down from the array plane. |
| **Distance** | 0.3 – 8 m | From the array centre. |
| **Loudness** | −30 to +10 dB | Level at mic 1 relative to Speaker 1. Speaker 1 is always the 0 dB reference. |
| **Starts at** | 0 s to the end of the recording − 1 s (at least 4.5 s) | When the speech starts. |

**Speech options**

- **Recording:** the built-in voice file for the selected voice.
- **Typed text:** type up to 500 characters; the page synthesises them with eSpeak (meSpeak, loaded on first use from
  `web/vendor/scene_tts.js`). Voice variants: male = m3 (pitch 40), male low = m1 (25), female = f2 (55),
  female high = f4 (75). Not available for the baby. Synthesis happens once per voice and text and is cached.
- **Uploaded file:** choose any audio file the browser can decode (WAV, MP3, FLAC, OGG, M4A; up to 60 MB). It is mixed
  to mono, resampled to 16 kHz, peak-normalised and trimmed like the built-in voices. The file stays in the page only
  (it is not uploaded anywhere); after a reload, choose it again.

If speech runs past the end of the recording, the page warns that it is cut. If typed text or a file is not ready,
the built-in recording is used and the page says so.

---

## 7. Scene setup: Noise sources

The ambient sources of the selected scenario (none in the Custom classic tests). Each has:

| Setting | Range | Meaning |
|---|---|---|
| **On/off** (checkbox) | | Include the source. Also toggled by clicking its diamond in the array view. |
| **Level** | −40 to +10 dB | Level at mic 1 relative to Speaker 1. |
| **Position** (expand) | azimuth 0–359°, elevation −60 to +90°, distance 0.3–20 m | Where the source is (the start of its path, for moving sources). |

Sources tagged **moving** travel along a path during the recording (drawn as a dashed line to a small circle at the end
point). The movement is approximated by four positions blended with raised-cosine weights. A **moved inside the room**
tag means the requested position was outside the room.

---

## 8. Scene setup: Robot's own noise

Noise from the robot's body, close to the microphones; available in every scene. Each has an on/off checkbox and a
level from −36 to +6 dB (at mic 1, relative to Speaker 1).

| Source | Where | Sound |
|---|---|---|
| **Cooling fan** | back of the head (7 cm behind, 3 cm below) | 7-blade blade-pass hum with harmonics plus air noise; spins up over the first 2 s. **Top speed** 2400–6000 rpm (default 4200). |
| **Neck servo** | under the mics (10 cm below) | Motor whine whose pitch follows the head-turn speed, plus gear grind. Head turns at 0.8–1.6 s and 3.4–4.0 s. |
| **Shoulder servos** | left shoulder (18 cm, 30 cm below) | Arm-gesture whine and grind, 1.8–2.8 s. |
| **Brake clicks** | joints | Short clicks when the neck or shoulder starts or stops. |
| **Electrical hum** | electronics | 50 Hz plus harmonics, identical on every microphone (not acoustic). |
| **Footsteps** | feet (1.4 m below) | Thumps and clicks every 0.55 s while walking (2.6–4.8 s). Approximate, and off by default: the page's beamformer cancels the thump much less than the Python simulation does. |

Times repeat every 5.5 s for longer recordings. Defaults: fan −6 dB, neck −4 dB, shoulders −8 dB, clicks −10 dB,
hum −25 dB, footsteps −2 dB (off).

---

## 9. Scores

Each score is **target voice vs everything else**, in dB, measured in the short-time Fourier domain after the same
linear processing is applied to the target alone and to the rest. Higher is cleaner. One row per target speaker:

| Column | Meaning |
|---|---|
| **Mic 1 alone (the original)** | What one microphone hears with no processing. |
| **Delay-and-sum** | Lines up the microphones toward the speaker and averages them. |
| **MVDR beamformer** | MPDR/MVDR with the mixture covariance (diagonal loading 1e-3): also turns down sounds from other directions. |
| **MVDR, learned robot noise** | Same, with the covariance also learned from a separate recording of the robot moving with nobody talking (mixture + 3 × that take). Shown when any robot noise is on. |

**Gain** under each beamformer score is its improvement over mic 1 alone (+3 dB ≈ twice as strong relative to the
noise, +10 dB ≈ ten times).

**Python column.** While the scene is at its default settings (including the 5.5 s length and the built-in speech),
each method has a **Page** and a **Python** column. Python is the same scene rebuilt from the page's own sources and
positions with pyroomacoustics and the original Python beamformer code (section 15). The Python cell is coloured by
how close it is to the page:

| Colour | Difference between page and Python |
|---|---|
| Green | under 1 dB: the page's quick answer can be trusted |
| Yellow | 1 – 2 dB |
| Red | over 2 dB: trust the Python number more |

The note under the table names the largest difference. If you change any setting, the Python column hides (the stored
check is for the defaults); re-select the scene to restore it, or run the Python check on your zip.

Agreement at the defaults (MVDR): classic tests and Factory within ~0.6 dB, Hospital ~0.9 dB, Automobile ~1.2 dB;
**Home: the page is 1.3–2.7 dB below Python** (red/yellow), a known limit of the page's small-room echo model.

---

## 10. Signal viewer and timeline

- **Timeline:** when each speaker talks, which noise sources are on (dashed = moving), and the robot's fan speed, head
  turning, arm gesture and walking over the recording.
- **Waveform and spectrogram (0–8 kHz):** of the selected track. Click any track to view it; **Play** plays it; click
  the waveform or spectrogram to play from that moment. The playhead follows playback.

---

## 11. Tracks

| Group | Tracks |
|---|---|
| Mic 1 alone | The original, everything as one microphone hears it. |
| Aimed at each target speaker | Delay-and-sum, MVDR, MVDR + learned robot noise, with their scores (and Python scores when shown). |
| Raw microphones | Every microphone, with its angle (and ring, for a dual ring). |
| Each source alone, at mic 1 | Every speaker, noise source and robot noise on its own, normalised so its character is audible. |

Every track has a play button and a download button (a WAV, or a zip inside the claude.ai viewer).

---

## 12. Python reference

Recordings made by Python for the selected scene, for listening comparison with the page's version:

- **Home, Factory, Hospital, Automobile:** `python/score_scene.py` output (`python_out/<scene>/`): mic 1 and each
  beamformer per speaker.
- **Custom classic tests:** the original `sim_conversation.py` recordings for Baby crying, Baby + fan and Robot moving
  (Python's robot scene has footsteps on; the page's has them off), plus clean voices, robot noises one at a time, and
  the `sim_8mic_robot_noise.py` scenes (which use two CMU Arctic talkers, not this page's voices). Quiet room has no
  Python recording.

These play from files next to the page, so they work on the published page or when the repo folder is served over
HTTP, not when the HTML file is opened directly.

---

## 13. Download (.zip)

"Download .zip" in the Scores section saves the whole rendered scene:

| File | Contents |
|---|---|
| `mics/mic1.wav … micN.wav` | Every microphone, 16 kHz 16-bit, one common gain so mic-to-mic levels are kept. |
| `mic1_original.wav` | Mic 1 alone. |
| `beams/<speaker>_<method>.wav` | Each beamformer output (`s1_das`, `s1_mvdr`, `s1_learned`, …). |
| `alone/<source>.wav` | Each source alone at mic 1 (normalised). |
| `scores.csv` | Long format: `speaker, voice, processing, score_db, gain_db, python_db`. |
| `settings.json` | All page settings (schema 2), including recording length, speaker speech/text, and `micPositions` (m from the array centre, mic 1 first). |
| `scene.json` | Resolved geometry for the Python check: room, centre, absolute mic positions, every source's final position(s) and level, RT60/damping. |
| `dry/<source>.wav` | Every source before the room (32-bit float), including typed or uploaded speech. |
| `page_scores.json` | The page's scores, for comparison. |

---

## 14. How the sound is made

- **Room:** exact image sources up to 3 bounces plus a statistical late tail (decaying noise arriving from 24 random
  directions), per microphone. Damping splits the tail into a low band (RT60) and a high band (shorter RT60).
- **Levels:** each source is scaled so its energy at mic 1 is its level relative to Speaker 1.
- **Processing:** 512-point STFT, hop 128 (8 ms frames at 16 kHz). Delay-and-sum and MPDR weights per frequency bin;
  steering vectors use the true 3D direction of each target.
- **Direction finding:** SRP-PHAT over 300–3500 Hz on the mixture covariance.
- At 5.5 s and the classic-test settings the engine is bit-exact with the original v1 page
  (`web/tests/fixtures/engine_v1.js`).

---

## 15. Python cross-check

`python/score_scene.py` rebuilds a scene from the page's dry sources and placements with pyroomacoustics (image
sources up to the Sabine order; multi-band absorption when damping > 0) and scores it with the original Python STFT
and MPDR code. It reproduces the original `sim_conversation.py` scores for Baby crying and Baby + fan to within 0.1 dB.

```
pip install numpy scipy soundfile pyroomacoustics
python python/score_scene.py scene_simulator_factory.zip            # any zip from "Download .zip"
python python/score_scene.py scene.zip --json out.json --wav-dir out   # also save scores and Python audio
python python/make_python_scores.py && (cd web && python build.py)     # refresh the page's Python column and recordings
node web/tools/export_scene.js factory /tmp/factory --set '{"damping":0}'   # export a scene (optionally changed) without the page
```

---

## 16. Repository layout, build and tests

```
web/
  robot_acoustic.html             built page (do not edit; run python build.py)
  build.py                        engine.js + scenarios.js + voices + Python scores -> template -> robot_acoustic.html
  src/engine.js                   audio engine: rooms, sources, mics, beamforming, SRP-PHAT
  src/scenarios.js                Home / Factory / Hospital / Automobile + noise generators
  src/robot_acoustic.template.html  UI
  src/python_scores.json          Python check of each scene's defaults (make_python_scores.py)
  vendor/scene_tts.js             eSpeak text-to-speech bundle (meSpeak 2.0.2, GNU GPL); rebuild: tools/build_tts.sh
  tools/export_scene.js           writes a scene's dry sources + geometry for the Python check
  tests/                          engine_regression.js (+ fixtures/engine_v1.js), scenarios_test.js,
                                  ui_headless.py, ui_full.py (end-to-end, 103 checks), ui_speech.py (speech, 17 checks)
python/
  score_scene.py                  Python check of one scene
  make_python_scores.py           runs it on every scene's defaults
python_out/<scene>/               Python audio of the four scenarios
voices/                           male.wav, female.wav, baby.wav (embedded into the page)
sim_conversation_out/, sim_noise_out/   original Python-simulator recordings played by the page
```

```
cd web
python build.py                                   # rebuild robot_acoustic.html
node tests/engine_regression.js                   # v1 regression + engine features
node tests/scenarios_test.js                      # 4 scenarios, all noise generators
python tests/ui_headless.py robot_acoustic.html   # quick load check (pip install playwright)
python tests/ui_full.py                           # every control end to end (~10 min; CHROMIUM=/path/to/chrome if needed)
python tests/ui_speech.py                         # typed text, uploaded speech, voices, long speech (~2 min)
```

---

## 17. Known limits

- All ambient noise is synthesised; realism is qualitative.
- Home's MVDR scores are 1.3–2.7 dB below Python's (small-room echo model). Page MVDR scores also vary with the random
  draw of the echo tail (up to ~2.5 dB in a small room); this uncertainty is not shown on the page.
- A flat ring cannot resolve elevation; the dual ring estimates it coarsely.
- Footsteps are approximate (see section 8).
- No side view: elevation is set with sliders or Page Up/Down on a marker.
- Long recordings (over ~30 s) render slowly and use a lot of memory; every change re-renders the whole recording.
- The Python column and recordings cover only each scene's default settings at 5.5 s.
