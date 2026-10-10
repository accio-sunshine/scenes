# Robot Acoustic — project handoff (as of 2 Oct 2026)

Context for a Claude agent picking up this project. Written at the end of a long
claude.ai conversation. The user is MK, a TI field application engineer in Bengaluru.

## 1. How to work with MK

- **One step at a time.** MK explicitly asked not to skip steps: give one task, wait for results, discuss, then the next. Don't dump several phases at once.
- **Experiments are separate files** in `experiments/`, each saving to its own `results/<name>/` folder with a `summary.txt`. MK doesn't want to edit settings and lose earlier results — add a new experiment file instead of changing an old one.
- **Accuracy over confidence.** MK checks outputs. Say what was tested vs. not, and report results that look wrong rather than smoothing them over.
- MK's home PC is Windows (PowerShell, `.venv`, run as `.\.venv\Scripts\Activate.ps1`). MK sometimes runs scripts from inside `experiments/`; all experiments use absolute paths so that works.
- HARK is installed on MK's **work PC** and works with **PyHARK** (not tested through HARK Designer).
- The code is going into MK's Bitbucket (README and `.gitignore` included).

## 2. Goal

Prototype, on a PC, the voice-capture pipeline for an 8-mic humanoid robot head before building hardware.
Target design comes from MK's implementation note "rev B" (8 × Infineon IM73D122 PDM MEMS mics, 3.072 MHz PDM,
CIC3 ↓96 + 63-tap FIR ↓2 → 16 kHz, STFT N=512 hop=128 (257 bins, 8 ms frames), pipeline:
ego-noise NMF suppression → online WPE (RLS, K=10, Δ=3) → MUSIC/SRP-PHAT localization + tracking + active audition →
neural mask (causal GRU/TCN on a 2 TOPS NPU) → mask-based MVDR/GEV → Wiener post-filter → iSTFT → ASR),
on an ARM big.LITTLE + NPU SoC.

Review issues already raised on rev B (not yet fixed by MK): §14 says WPE compute is cubic in K (RLS form is quadratic, §5 is right);
§14 bandwidth mixes the 13 MB full-matrix size with the Hermitian 1.6 GB/s figure (full read+write ≈ 3.3 GB/s);
memory table uses C=4 sources while §8 uses C=3; CIC bit growth for R=96 is ≈20 bits not 23; "per channel ≈16 kB/frame" is all 8 channels;
ego-noise Wiener gain placed before WPE may hurt WPE and Φee from NMF magnitude is unspecified; head motion disturbs WPE/beamformer state;
GRU support on the NPU needs checking; ASR load isn't budgeted; mic AOP 122 dB SPL exceeds the 120 dB SPL digital full scale.

## 3. Where things live

| Item | Location |
|---|---|
| Step-by-step build guide (phases 0–9, checklists) | Claude Doc: https://claude.ai/code/artifact/5f3d345d-7460-43bd-853c-11c0590eb635 (private to MK's claude.ai account) |
| MK's own interactive page with knobs (scenes, levels, draggable talkers, scores vs Python) | https://accio-sunshine.github.io/robot_acoustics/ |
| Listening pages (claude.ai, private) | Robot acoustic (conversation + baby + robot): https://claude.ai/artifact/8c4UmsDoqRuhjgdhC88pgS · Robot noise: https://claude.ai/artifact/C5nqnCYg9YBSBiw91kDWc1 · First room: https://claude.ai/artifact/RNFM4jFN2w6MMSjRFEKbom |
| Code | this `robot-audio/` folder (see README.md) |

## 4. Code overview

- `sim_8mic_room.py` — room (6×5×3 m, pyroomacoustics image method), 8-mic circle (default 5 cm radius, mic 1 at 0°, counter-clockwise),
  two CMU Arctic speech clips (talker A 40°, B 150°, 1.5 m), white noise at SNR, STFT 512/128. `run_scene()` + `run_experiment()` power exps 01–06.
  Settings: `rt60, radius, snr_db, angle_a, angle_b (None = one talker), dist, room, doa_band`.
- `toolkit.py` — building blocks for exps 07+: `build_scene()` (keeps every component separately; `b_start` delays talker B),
  `find_directions()`, `component_db()`, `blockwise_mpdr()`, `mask_mvdr_weights()` (Souden), `wpe_offline()`, `wpe_online()` (nara_wpe OnlineWPE),
  `si_sdr()` (with alignment), `save_table()`. `TEST_SET` = the 5 fixed scenes of exp05.
- `sim_8mic_robot_noise.py` — synthetic ego-noise: fan (7-blade BPF hum + air, RPM ramp), neck servo (whine follows joint speed + gear grind),
  shoulder servos, footsteps, brake clicks, 50 Hz hum (identical on all channels). Writes `motor_state.csv`. Levels in `LEVEL_DB`.
- `sim_conversation.py` — man (40°) "Hi there, how are you doing today?", woman (150°) "I'm good. What is the plan for the day?",
  baby crying (250°, 2.5 m, -0.7 m height); scenes: baby only / + fan / + all robot noise. Voices from `voices/` (MBROLA TTS + synthetic cry).
- `score_whisper.py` — faster-whisper (base.en, CPU int8) + jiwer WER, contraction-normalised.
- `pyhark_localize.py` — PyHARK offline chain (MultiFFT → LocalizeMUSIC SEVD → SourceTracker → GHDSS → Synthesize → SaveWavePCM),
  following HARK's PyHARK tutorial Practice 3-3. Needs `hark/tf_8mic.zip` made in HARKTOOL5-GUI from `hark/mic_positions.xml` +
  `hark/source_positions.xml` (Use Geometric Calculation, FFT 512, 16 kHz). Same angle convention as the Python sims.
- MPDR = MVDR using the mixture covariance (diagonal loading 1e-3). Scores "dB" = target power / everything-else power after the same
  linear filter, computed on separately simulated components.

## 5. Guide status

| Phase | Status |
|---|---|
| 0 Set up PC | Done (incl. optional WSL2 and git, ticked by MK) |
| 1 Simulated room & test set | Done (exps 01–05). Pending: real head geometry — revisit when designing the hardware board; 5 cm circle until then |
| 2 Direction finding | Tasks done: look at spectra, run on every scene, note failures. Open: frequency band (exp06 — MK hasn't reported results yet), smoothing (exp08), HARK compare (exp09) |
| 3 Beamforming | Exps 10–12 written and tested here; MK hasn't run them yet |
| 4 WPE | Exps 13–15 written; 13 and 15 tested; 14 rewritten, see §7 |
| 5 Whisper scoring | Exps 16, 21 written; not run anywhere yet |
| 6 Masks | Exp 17 (oracle upper bound) tested |
| 7 Ego-noise | Exps 18–20; 20 tested; 18/19 wrap scripts MK already ran |
| 8 Real mics, 9 Port to SoC | Not started |

The next step in the agreed one-by-one flow: MK runs **exp06** and reports, then exp07, exp08, …

## 6. Results so far (deterministic; MK's runs matched exactly)

dB = talker A vs everything else (higher = cleaner). True angles 40° / 150° unless noted.

- **Exp01 echo (5 cm):** RT60 0.2/0.5/0.8 → MVDR 6.4/4.9/3.3 dB; DAS 3.7/3.2/3.0; SRP-PHAT always near truth; MUSIC wrong (0.2: 20,32 split A and missed B; 0.5: 41,332; 0.8: 39,323 — false wall-reflection peak).
- **Exp02 array size (RT60 0.5):** 3 cm MUSIC 18,51 / DAS 2.7 / MVDR 5.1; 5 cm 41,332 / 3.2 / 4.9; 10 cm 41,148 / 4.4 / 4.4. Bigger array fixes MUSIC and helps DAS; MVDR slightly worse.
- **Exp03 noise:** SNR 25/15/5 → MVDR 6.1/4.9/2.8; SRP robust even at 5 dB; MUSIC's ~332° peak present at every SNR → caused by echo, not noise.
- **Exp04 spacing:** 110° apart MVDR 4.9; 50° apart DAS −1.7 but MVDR 5.0 (SRP failed: 77,274; MUSIC 56,87); 30° apart MVDR 2.3. **One talker: DAS 23.1 vs MVDR 8.9** — MPDR target self-cancellation (echo/steering mismatch).
- **Exp05 test set:** one_talker, two_far, two_close (70°), dry_room (0.2), echoey_room (0.8); each folder has `clean_A_dry.wav` and `clean_A_at_mic1.wav`.
- **Exp06 DOA band (RT60 0.8, my run):** 300–3500 Hz MUSIC 39,323; 500–4000 42,179; 1000–4000 25,156; 1500–4500 30,156. SRP 32–34 / 161–165. Raising the band removes the false peak but no band gets both talkers right.
- **Exp07 DOA after WPE:** two_far MUSIC 41,332 → 37,151 and SRP 37,155 → 41,150; echoey MUSIC 39,323 → 33,153; two_close got worse (MUSIC 47,335; SRP only one source).
- **Exp08 tracking (0.25 s blocks, B starts 1.5 s later):** correct within 15° of the louder talker: RT60 0.5 72% raw → 78% smoothed; 0.8 63% → 79%.
- **Exp10 estimated steering:** estimate errors 0–8°, cost ≤0.3 dB vs true angle.
- **Exp11 aiming error (two_far):** MVDR 4.9 → 4.4 (10°) → 3.5 (20°) → 2.4 (30°); DAS ~flat (3.2 → 3.0). One talker: MVDR 8.9 → 7.0.
- **Exp12 block MVDR:** two_far whole 4.9, 1 s 4.7, 0.5 s 4.3, 0.25 s 4.0; two_close 2.3 → 2.5–2.6 (blocks slightly better).
- **Exp13 WPE taps (one talker, SI-SDR vs dry):** RT60 0.5: none −4.2, 5 taps −1.9, 10 −1.2, 15 −0.9; RT60 0.8: −7.1, −5.1, −3.9, −3.3. Cost roughly doubles 5→15 taps.
- **Exp15 WPE before beam (SI-SDR):** echoey MVDR −3.4 → WPE+MVDR −1.8; two_far −0.9 → 0.0; dry_room 2.4 → 1.5 (WPE hurts in dry room).
- **Exp17 oracle-mask MVDR (upper bound):** one_talker 8.9 → 25.1; two_far 4.9 → 10.6; two_close 2.3 → 8.6; dry 6.4 → 16.2; echoey 3.3 → 8.4. → a mask network (Phase 6) is worth building.
- **Exp20 ego-noise (two_far + all robot noise):** mic 1 −3.3; MVDR 2.5; MVDR + Wiener post-filter 3.6; MVDR + learned robot noise 3.0; + post-filter 3.6–3.7.
- **Robot-noise scenes (sim_8mic_robot_noise):** mic1 / MPDR / MPDR+learned: speech_only 2.6/6.4/6.4; fan 1.0/6.2/7.0; fan_neck −1.1/6.2/7.0; walking −2.3/4.9/6.0; everything −3.2/4.9/6.0. Learning only from robot-only audio (without the mixture) made results worse — it must be combined with the mixture.
- **Conversation scenes:** mic1 / beam man / beam woman / learned man / learned woman: baby −1.0/4.7/5.3/–/–; baby+fan −1.8/4.5/4.9/4.9/4.7; baby+robot −4.5/3.8/3.2/4.3/2.9. SRP found 19°,176°,248° (true 40,150,250) with baby only; with fan on, only the fan (180°).

## 7. Known issues / caveats

- **Exp14 online WPE:** first version scored a 4 s clip and showed online WPE *worse* than none (didn't converge). Rewritten to repeat the scene 4× and score the last repetition; a manual test of that approach gave RT60 0.8: raw −7.2, offline −4.0, online −5.9/−5.1/−5.0 (alpha 0.99/0.999/0.9999). The final script wasn't run to completion in the build environment (slow).
- **Exps 18, 19** are thin wrappers (redirect output folders) around scripts MK already ran; not run as wrappers in the build environment.
- **Exps 09, 16, 21 and `pyhark_localize.py`** were never run (no HARK/Whisper model in the build environment). PyHARK SourceTracker output parsing is a guess — it prints a `[debug]` line if the format differs. It feeds int16-scale samples (default THRESH 26 assumes that).
- Exp16's WER reference is Whisper's own transcript of the clean dry voice (CMU Arctic transcripts weren't verified).
- Voices are MBROLA TTS; baby cry and robot noises are synthetic point sources; no head scattering. Geometric HARK transfer functions assume free field.
- Old output folders (`sim_out*`, `sim_noise_out`, `sim_conversation_out`) may exist on MK's PC from before the experiments structure; they're git-ignored.

## 8. Suggested next steps (in order, one at a time)

1. MK runs exp06 → discuss; then exp07 (WPE before DOA looks like the real fix for MUSIC), exp08, optionally exp09 on the work PC.
2. Phase 3: exps 10–12. Phase 4: 13–15 (confirm 14 on MK's PC).
3. Phase 5: install faster-whisper + jiwer, run exp16, then 19 → 21. Check the clean reference rows first.
4. Phase 6: exp17 shows large headroom → next build a non-oracle mask (pretrained causal enhancement/separation model) for mask-based MVDR; it also fixes the one-talker MPDR self-cancellation.
5. Phase 7: try ego-noise placement before vs after WPE; multichannel ego-noise covariance.
6. Later: real head geometry (pending hardware board), real recordings, measured transfer functions, port to SoC.
