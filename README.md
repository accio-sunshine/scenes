# Robot Acoustic — 8-mic robot audition prototype

Simulated 8-microphone robot-head array for studying speech capture on a robot: sound source localization,
beamforming, dereverberation (WPE), robot ego-noise, and speech-recognition scoring. HARK (via PyHARK) is used
as a comparison. Everything runs on simulated rooms (pyroomacoustics) before moving to hardware, and `hil/`
carries a simulated scene onto the AM243x capture chain.

**Run every script from this folder**, because they read and write paths relative to it.

## Setup

Requires Python 3.10+.

```
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # Windows PowerShell
source .venv/bin/activate           # Mac / Linux
pip install -r requirements.txt
python check_setup.py               # checks libraries, files and internet, then runs the three simulations once
```

## Layout

```
sim_8mic_room.py          core room simulation, used by experiments 01-06 and 23
sim_8mic_robot_noise.py   adds robot ego-noise
sim_conversation.py       two talkers + baby crying, with/without robot noise
toolkit.py                smaller building blocks used by experiments 07 and later
score_whisper.py          Whisper transcription + word error rate
make_hark_xml.py          mic/source geometry for HARKTOOL5
pyhark_localize.py        HARK localization + separation
check_setup.py            Phase 0 environment check
experiments/              one file per experiment (exp01-exp23)
hil/                      scene -> microphone PDM -> PRU player for the AM243x (see hil/README.md)
web/                      robot_acoustic.html (robot's-eye listening lab) and array_bench.html
voices/                   male.wav, female.wav, baby.wav (inputs for sim_conversation.py)
hark/                     mic_positions.xml, source_positions.xml
speech_cache/             CMU Arctic clips downloaded on first run          (not committed)
results/                  one folder per experiment, each with summary.txt (not committed)
sim_noise_out/            robot-noise scenes + motor_state.csv               (not committed)
sim_conversation_out/     conversation scenes                                (not committed)
```

Generated audio is not committed. Re-create it by running the scripts and experiments.

## Scripts

| Script | What it does | Output |
|---|---|---|
| `sim_8mic_room.py` | Reverberant room, 8-mic circular array (r = 5 cm), MUSIC / SRP-PHAT localization, delay-and-sum and MVDR (MPDR) beamforming, WPE dereverberation. Experiments call its `run_experiment()`. Run directly, it reproduces exp01. | `results/<experiment>/` |
| `sim_8mic_robot_noise.py` | Synthetic robot ego-noise (fan, neck/shoulder servos, footsteps, brake clicks, 50 Hz hum); also writes `motor_state.csv` (fan RPM, joint velocities, walking) for ego-noise prediction. | `sim_noise_out/` |
| `sim_conversation.py` | Male at 40° and female at 150° (1.5 m), baby crying at 250° (2.5 m); scenes: baby only, + fan, + all robot noise. | `sim_conversation_out/` |
| `score_whisper.py` | Transcribes conversation outputs with faster-whisper and computes WER. | `results/wer_results.csv`, `results/transcripts.txt` |
| `make_hark_xml.py` | Mic and candidate-source positions (every 5°) for a geometric transfer function in HARKTOOL5. | `hark/` |
| `pyhark_localize.py` | HARK offline: MultiFFT → LocalizeMUSIC → SourceTracker → GHDSS. Needs `hark/tf_8mic.zip` built in HARKTOOL5-GUI. | `hark_out/` |

Angle convention everywhere: 0° = mic 1 (+x), 90° = +y, counter-clockwise.

## Experiments

Each file in `experiments/` changes one thing and saves into its own `results/<experiment>/`, so experiments never
overwrite each other. Default scene: RT60 0.5 s, radius 5 cm, SNR 15 dB, talker A at 40°, talker B at 150°, 1.5 m,
6×5×3 m room. Run from this folder, e.g. `python experiments/exp07_doa_after_wpe.py`.

| # | Phase | File | Question |
|---|---|---|---|
| 01 | 1 Simulated room | `exp01_echo_levels.py` | What does room echo do? |
| 02 | 1 | `exp02_array_size.py` | What does array size do? |
| 03 | 1 | `exp03_background_noise.py` | What does background noise do? |
| 04 | 1 | `exp04_talker_spacing.py` | How close can two talkers be? |
| 05 | 1 | `exp05_test_set.py` | Fixed test set used by later phases. **Don't change it**; add a new experiment instead |
| 06 | 2 Direction finding | `exp06_doa_frequency_band.py` | Does the frequency band fix MUSIC's echo peak? |
| 07 | 2 | `exp07_doa_after_wpe.py` | Does removing echo first help direction finding? |
| 08 | 2 | `exp08_doa_tracking.py` | Direction over time, raw vs smoothed |
| 09 | 2 (optional) | `exp09_hark_compare.py` | HARK's MUSIC on the test set *(needs PyHARK + hark/tf_8mic.zip)* |
| 10 | 3 Beamforming | `exp10_steer_estimated.py` | Beam steered at the estimated direction |
| 11 | 3 | `exp11_steering_error.py` | Sensitivity to aiming errors |
| 12 | 3 | `exp12_block_mvdr.py` | MVDR updated in short blocks (live-like) |
| 13 | 4 Echo removal | `exp13_wpe_taps.py` | Fewest WPE taps that still work |
| 14 | 4 | `exp14_wpe_online.py` | Offline vs online (frame-by-frame) WPE |
| 15 | 4 | `exp15_wpe_then_beam.py` | WPE before the beamformer, overall |
| 16 | 5 Speech recognition | `exp16_whisper_test_set.py` | Whisper WER on the test set *(needs 05 first)* |
| 17 | 6 Masks | `exp17_oracle_mask_mvdr.py` | Upper bound: MVDR with a perfect mask |
| 18 | 7 Ego-noise | `exp18_robot_noise_scenes.py` | Robot noise scenes |
| 19 | 7 | `exp19_conversation_scenes.py` | Conversation + baby + robot noise scenes |
| 20 | 7 | `exp20_ego_noise_postfilter.py` | Learned-noise MVDR and Wiener post-filter |
| 21 | 5 + 7 | `exp21_whisper_conversation.py` | Whisper WER on the conversation *(needs 19 first)* |
| 22 | 8 Hardware in the loop | `exp22_frontend_in_loop.py` | Does a scene survive mic PDM + the AM243x front end, and does the PRU player reproduce it? *(takes a WAV or the web page zip)* |
| 23 | 1 | `exp23_talker_distance.py` | How far away can the talkers be? *(was exp06 in the GitHub repo)* |

Order dependencies: 05 → 09 and 16; 19 → 21. Everything else is independent.
Experiments 01-06 and 23 save, per scene, the 8-channel mix, mic-1 input, delay-and-sum, MVDR, WPE and
WPE→MVDR outputs, clean references for scoring, and a DOA spectrum plot.

## Baseline results

Talker A vs everything else, in dB (higher = cleaner). DAS = delay-and-sum. From `results/exp05_test_set/summary.txt`:

| Scene | True ° | MUSIC ° | SRP-PHAT ° | Mic 1 dB | DAS dB | MVDR dB |
|---|---|---|---|---|---|---|
| one_talker | 40 | 28 | 38 | 15.0 | 23.1 | 8.9 |
| two_far | 40, 150 | 41, 332 | 37, 155 | 2.3 | 3.2 | 4.9 |
| two_close | 40, 70 | 42, 53 | 46, 162 | 0.8 | 1.1 | 2.3 |
| dry_room | 40, 150 | 20, 32 | 40, 147 | 2.2 | 3.7 | 6.4 |
| echoey_room | 40, 150 | 39, 323 | 32, 161 | 2.2 | 3.0 | 3.3 |

What the baseline shows:
- SRP-PHAT finds talker A within about 8° in every scene; MUSIC often puts the second source in the wrong place (e.g. 332° instead of 150°).
- MVDR beats delay-and-sum whenever there are two talkers; its gain drops from 6.4 to 3.3 dB as echo goes from 0.2 to 0.8 s.
- Talkers 30° apart are hard to separate with a 5 cm array (MVDR only 2.3 dB).
- With a single talker, MVDR (8.9 dB) is far below delay-and-sum (23.1 dB), which points to self-cancellation in the MPDR form.

### Experiment 23: talker distance

| Scene | MUSIC ° | SRP-PHAT ° | Mic 1 dB | DAS dB | MVDR dB |
|---|---|---|---|---|---|
| d075_close (0.75 m) | 33, 41 | 40, 147 | 3.7 | 4.3 | 6.3 |
| d150_medium (1.5 m) | 41, 332 | 37, 155 | 2.3 | 3.2 | 4.9 |
| d225_far (2.25 m) | 43, 335 | 38, 147 | 0.1 | 0.6 | 4.3 |

Moving the talkers away costs mic 1 and delay-and-sum about 3.6 dB from 0.75 m to 2.25 m. MVDR loses only 2 dB.
SRP-PHAT stays accurate at every distance.

## Scores used

- **dB (talker A vs rest):** power of the target after processing divided by everything else
  (other talker, noise, robot noise), computed on separately simulated components. Higher = cleaner.
- **SI-SDR:** similarity to the clean dry voice; penalises other talkers, noise *and* echo.
  Used where processing isn't a fixed linear filter (WPE).
- **WER:** Whisper word error rate. Short sentences, so one word ≈ 10–15 %.

## Web pages

Both pages are single HTML files that run entirely in the browser. Open them locally with a small web server:

```
python -m http.server 8000
```

then browse to `http://localhost:8000/web/robot_acoustic.html` or `http://localhost:8000/web/array_bench.html`.
Opening the file directly (double-click) works too, but then the Python recordings can't be loaded.
The published copy is at https://accio-sunshine.github.io/robot_acoustics/ (served from the GitHub repo).

**`web/robot_acoustic.html`** is the conversation scene from the robot's point of view. The robot's head is in the
middle with its 8 mics, the man, woman and baby can be dragged around it, and every robot noise (fan, neck servo,
shoulder servos, brake clicks, 50 Hz hum, footsteps) has an on/off switch and a loudness knob, along with the baby,
room echo, noise floor and mic ring size. Each change re-renders all 8 microphones in the browser. You can listen to
any mics (stereo for headphones), to delay-and-sum, MVDR and learned-robot-noise beamformers aimed at each speaker,
and to each sound alone, with a timeline, waveform and spectrogram. The Python recordings from
`sim_conversation_out/` and `sim_noise_out/` play alongside once you have run `sim_conversation.py` and
`sim_8mic_robot_noise.py`. **Download all audio + scores (.zip)** gives every mic plus `settings.json`, which
exp22 takes directly (see below).

The page uses the same voices, noise recipes, levels and beamformers as the scripts. The room is lighter (exact
reflections up to 3 bounces plus a statistical late echo). Beamformer scores land within about 0.5 dB of Python in
the baby and fan scenes. Footsteps are approximate and start switched off.

**`web/array_bench.html`** is a browser version of `sim_8mic_room.py` with every scene setting as a slider: RT60,
SNR, room size, array radius, talker directions and distance, plus page-only knobs for the number of mics and the
DOA frequency band. Results update instantly, you can click the room plan to move a talker, and each experiment
scene is a preset that shows the Python result next to the page's estimate. It also builds the `dict(...)` line to
paste into a new experiment. Its room model is lighter (exact reflections up to 2 bounces): mic-1 and
delay-and-sum land within about 0.5 dB of Python in most scenes, MVDR within about 1.5 dB, SRP-PHAT within a few
degrees. Use it to choose scenes, then confirm in Python.

To change the Robot Acoustic page, edit `web/src/engine.js` or `web/src/robot_acoustic.template.html`, then run
`python web/build.py` (it embeds the voices from `voices/`).

## Hardware in the loop: from a scene to the processor pins

`hil/` turns a scene into what the 8 PDM microphones would put on the wire (3.072 MHz, 1 bit per mic), runs it
through a Python model of the AM243x capture chain (CIC3 /96, 63-tap FIR /2, DC block), and plays it with a
generated PRU program on TI's cycle-accurate [pru-simulator](https://github.com/TexasInstruments/pru-simulator).
The capture firmware then gets input that is identical every run, with a known right answer.

Set up a scene on the Robot Acoustic page, press **Download all audio + scores (.zip)**, and pass the zip in:

```
python experiments/exp22_frontend_in_loop.py robot_acoustic_custom.zip 4   # or any 8-ch 16 kHz WAV
python -m pytest hil/tests -q                                             # 17 tests
```

Results go to `results/exp22_frontend_in_loop_<scene>/`. Details, limits and what is not proven yet: `hil/README.md`.

## Typical workflow

```
python experiments/exp05_test_set.py   # fixed test set
python sim_conversation.py             # conversation scenes
python score_whisper.py                # WER (base.en; pass small.en for more accuracy)

# Optional HARK comparison
python make_hark_xml.py                # then build hark/tf_8mic.zip in HARKTOOL5-GUI
python pyhark_localize.py
```

## Not yet verified end-to-end

- Experiment 09 (PyHARK): written from HARK's PyHARK tutorial; the source-tracker output parsing may need adjusting.
- Experiments 16 and 21 (Whisper): scoring logic tested with stand-in transcripts; Whisper itself not run in the build environment.
- Online WPE (14) uses nara_wpe's `OnlineWPE` with default start-up settings.
- The `hil/` PRU player has only run on TI's simulator, not on a board.

Simulated robot noises are point sources with synthetic signals; real robot recordings will differ.
