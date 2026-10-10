# hil - play simulated microphone scenes into the AM243x

Hardware-in-the-loop with no microphones. The simulator already knows what each of the 8 mics hears
(each mic gets its own delay and level from the room simulation). This folder turns that into what the
mics would put on the wire and plays it into the AM243x pins, so the capture firmware, the link and the
DSP can be tested on input that is identical every run and has a known right answer.

## The chain

```
scene WAV (8 ch, 16 kHz)                  from sim_conversation.py, sim_8mic_robot_noise.py, exp scripts,
   |                                      or a download from the web page
   v   pdm.to_pdm        one 2nd-order 1-bit sigma-delta modulator per mic -> 3.072 Mbit/s each
   v   pdm.pack          1 byte per clock period: bits 0-3 = left mics of lines 0-3, bits 4-7 = right mics
pdm_stream.bin
   v   pru_player.py     generates PRU assembly; after the falling clock edge it drives the left mics on
   |                     R30[3:0], after the rising edge the right mics (as the IM73D122 L/R pin does)
   v   wires             R30[3:0] -> the capture side's 4 SD inputs; shared PDM clock
AM243x capture firmware  CIC3 /96 (PRU) -> 63-tap FIR /2 and DC block (R5F) -> 16 kHz PCM -> UDP
```

`pdm.frontend()` is a Python model of the same CIC3 + FIR + DC block. Its output is the right answer the
hardware is compared with. Mics 2k and 2k+1 share data line k (a placeholder pairing; the final PCB may
put one mic per pin).

## Files

| File | What it does |
|---|---|
| `pdm.py` | Mic model (audio to PDM), wire packing, Python model of the front-end (`frontend()` stand-in FIR; `frontend_fw()` firmware-exact integer maths), measuring helpers |
| `fir_coefs.inc` | Copy of audio_pipe's Q27 FIR table, read by `frontend_fw()` |
| `pru_player.py` | Generates the player assembly; runs it on TI's `pru-simulator`; checks the pins against the stream |
| `make_pdm.py` | Command line: a scene (8-ch 16 kHz WAV or the web page zip) to `pdm_stream.bin`, `player.asm`, `manifest.json` |
| `tests/test_hil.py` | 26 tests (9 for the firmware-exact chain, exp24). `python -m pytest hil/tests -q` (about 1-2 min) |
| `../experiments/exp22_frontend_in_loop.py` | The end-to-end experiment and its summary table |

## Setup

- `hil` needs only the packages in `requirements.txt`; the tests also need `pytest`.
- `pru_player.py` runs TI's simulator. Clone https://github.com/TexasInstruments/pru-simulator next to this repository
  (it looks in the folders above for one called `pru-simulator`), or set `PRU_SIM` to its path. It needs no other
  packages for this use. Without it, the player tests are skipped and exp22 stops at the player step.

## Use

```
python experiments/exp22_frontend_in_loop.py                          # the simulated two_far scene
python experiments/exp22_frontend_in_loop.py some_8ch.wav             # any 8-ch 16 kHz WAV
python hil/make_pdm.py some_8ch.wav out_dir --seconds 2               # just make the player files
```

### Scenes from the web page (no script editing)

1. Open https://accio-sunshine.github.io/robot_acoustics/ and set up the scene: drag the man, woman and baby,
   switch robot noises on or off, set their levels, the echo and the mic ring size.
2. Press **Download all audio + scores (.zip)**. The zip holds `mics/mic1.wav` ... `mic8.wav` (one per mic,
   16 kHz, all at the same scale) and `settings.json` (every knob you set).
3. Pass the zip straight in, without unzipping:

```
python experiments/exp22_frontend_in_loop.py Downloads/robot_acoustic_custom.zip 4
python hil/make_pdm.py Downloads/robot_acoustic_custom.zip my_scene --seconds 2
```

The knob settings are copied into the results, so each run records the scene it came from.
The page's room model is lighter than Python's (exact reflections up to 3 bounces, then an approximate tail);
its own note says scores land within about 0.5 dB of Python. Use the page to choose scenes; confirm important
ones with the Python scripts.

#### Scene Simulator v2 zips (schema 2) and the 8-mic requirement

The Scene Simulator's zip may now be a schema-2 zip: `settings.json` carries `schema: 2`, `scenario`,
`roomL/roomW/roomH`, `rt60`, `damping`, `micCount`, `arrayShape`, `radius` (cm), `speakers[]`, `noises[]`, and
`mics/` holds `micCount` files (4, 6, 8, 12 or 16). The PDM pipeline needs exactly 8 mics (4 data lines x 2), so
`make_pdm.py` / exp22 accept only zips with 8 mic WAVs and stop early otherwise, e.g. "has 16 microphones, but the
PDM pipeline needs exactly 8 ... Set Microphones = 8 in the Scene Simulator". Schema-1 zips (no `schema` key, flat
settings) still work unchanged. If `settings.json` `micCount` differs from the number of mic WAVs, a warning is
printed and the WAVs found decide. `radius` is still read from `settings.json` for the ring geometry; other
schema-2 fields are only copied into the results.

### Scenes from the Python scripts
`sim_conversation.py` writes `sim_conversation_out/conversation_baby_fan_8ch.wav` and `..._baby_robot_8ch.wav`;
`sim_8mic_robot_noise.py` writes `sim_noise_out/fan_8ch.wav`, `walking_8ch.wav`, `everything_8ch.wav` and so on.
Pass any of them to the commands above. Keep all 8 mics at one scale; `make_pdm` applies a single scale to all of
them, so level and timing differences between mics are untouched.

## What exp22 checks (results on the two_far scene, 2 s)

| Check | Result |
|---|---|
| Tones 0.5 to 6 kHz | SINAD 83-97 dB, gain within 0.02 dB |
| Front-end delay | 15.3 samples = 0.95 ms (firmware note says 1.0 ms) |
| Timing between mics | 0.0000 samples spread; level 0.001 dB spread |
| Directions (SRP-PHAT) | 37 and 154 degrees before and after |
| SI-SDR vs ideal front-end | 29.7 dB. Error is -35 dB at 4-7 kHz, about -52 dB below that; cause not found |
| Player pins vs stream | 0 wrong of 12,000 edges, ring wraps, 8 ns edge-to-data (mic allows 100 ns) |

## What is NOT proven

- **Not real hardware.** The player has only run on TI's simulator. Clock on GPI0, data on R30[3:0], mailbox in DRAM0,
  250 MHz core are assumptions, not yet checked against the AM243x TRM or the board schematic. They are constants at the top of `pru_player.py`.
- **The FIR is a stand-in.** `pdm.fir_taps()` is a Python design, not the firmware table. Use the capture firmware's coefficients for a bit-exact comparison.
- **The simulator is not the real world.** White background noise, point-source robot noise and no head model
  mean a pass here shows hardware equals simulator, not hardware equals a robot.
- **The modulator is cleaner than the real mic** (73 dB SNR, mismatch, -26 dBFS level). Add those in the simulator.
- **Scenes longer than a few seconds** need the R5F to stream from DDR or Ethernet; the ring is 4 KB (1.3 ms). Not written.
- Only 2 s scenes have been played; the player itself was checked on 6,000 bytes (0.002 s of PDM).

## Player mailbox (DRAM0, 32-bit words)

| Offset | Word | Owner |
|---|---|---|
| 0x00 | write index (bytes the host has put in the ring) | R5F |
| 0x04 | read index (bytes the PRU has consumed) | PRU |
| 0x08 | START (1 = go) | R5F |
| 0x0C | status: 0 running, 1 done, 2 underrun | PRU |
| 0x10 | total bytes to play (multiple of 4) | R5F |
| 0x100 | ring buffer, 4096 bytes | R5F fills |

On underrun the PRU stops and sets status 2, so a slow host shows up as a flag instead of silently wrong data.

## Next steps

1. TRM audit: confirm which pins carry clock and data, and whether ICSSG1 can see ICSSG0's clock.
2. Player and capture together on the simulator (L2), then on the EVM (L3).
3. Swap in the firmware FIR coefficients; find the cause of the 4-7 kHz error.
4. Add mic self-noise and mismatch to the simulator, then replay the conversation and fan scenes.
