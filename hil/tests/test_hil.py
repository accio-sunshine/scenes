"""Tests for the PDM player chain. Run from the robot-audio folder:  python -m pytest hil/tests -q"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import pdm  # noqa: E402
import pru_player  # noqa: E402

RNG = np.random.default_rng(0)
needs_sim = pytest.mark.skipif(not pru_player.available(), reason="pru-simulator not found (set PRU_SIM)")


# ---------------------------------------------------------------- wire format
def test_pack_unpack_roundtrip():
    bits = RNG.integers(0, 2, (8, 500)).astype(np.uint8)
    assert np.array_equal(pdm.unpack(pdm.pack(bits)), bits)


def test_each_mic_has_its_own_bit():
    for m in range(8):
        bits = np.zeros((8, 4), np.uint8)
        bits[m] = 1
        byte = pdm.pack(bits)[0]
        assert bin(byte).count("1") == 1
        left = m % 2 == 0
        assert (byte & 0x0F != 0) == left and (byte >> 4 != 0) == (not left)


def test_wire_events_capture_roundtrip():
    stream = RNG.integers(0, 256, 100).astype(np.uint8)
    assert np.array_equal(pdm.capture_from_wire(pdm.wire_events(stream)), stream)


# ---------------------------------------------------------------- mic model and front-end
def test_overloaded_input_is_refused():
    with pytest.raises(ValueError):
        pdm.to_pdm(np.full(100, 0.9))


@pytest.mark.parametrize("f0", [500, 1000, 3000, 6000])
def test_tone_is_clean_and_flat(f0):
    t = np.arange(8000) / pdm.FS
    x = 0.5 * np.sin(2 * np.pi * f0 * t)
    y = pdm.frontend(pdm.to_pdm(x))
    assert pdm.sinad_db(y, f0) > 75
    assert abs(20 * np.log10(np.std(y[2000:]) / np.std(x[2000:]))) < 0.1


def test_frontend_delay_is_about_one_millisecond():
    from scipy.signal import butter, lfilter
    x = lfilter(*butter(4, [300 / 8000, 3400 / 8000], "band"), RNG.standard_normal(16000))
    x *= 0.5 / np.max(np.abs(x))
    d = pdm.delay_samples(pdm.frontend(pdm.to_pdm(x)), x)
    assert 14.5 < d < 16.0


def test_delay_between_two_mics_is_kept():
    """The array works from tiny timing differences between mics; the chain must not blur them."""
    from scipy.signal import butter, lfilter
    x = lfilter(*butter(4, [300 / 8000, 3400 / 8000], "band"), RNG.standard_normal(16000))
    x *= 0.4 / np.max(np.abs(x))
    a, b = pdm.shift(x, 0.0), pdm.shift(x, 0.7)
    ya, yb = pdm.frontend(pdm.to_pdm(a)), pdm.frontend(pdm.to_pdm(b))
    assert abs(pdm.delay_samples(yb, ya) - 0.7) < 0.02


# ---------------------------------------------------------------- PRU player on TI's simulator
@needs_sim
def test_generated_asm_assembles():
    sim = pru_player._simulator()
    assert sim.load("pru0", pru_player.generate_asm()) == []


@needs_sim
def test_player_pins_match_stream_and_ring_wraps():
    stream = RNG.integers(0, 256, pru_player.RING_SIZE + 400).astype(np.uint8)   # longer than the ring
    log, info = pru_player.play(stream)
    chk = pru_player.check(stream, log, info)
    assert info["status"] == pru_player.STATUS_DONE
    assert chk["wrong"] == 0 and chk["edges_checked"] == 2 * len(stream)
    assert chk["max_latency_ns"] < 100          # IM73D122 tDV


@needs_sim
def test_player_meets_timing_at_200_mhz_too():
    stream = RNG.integers(0, 256, 200).astype(np.uint8)
    log, info = pru_player.play(stream, pru_mhz=200.0)
    assert pru_player.check(stream, log, info)["wrong"] == 0


@needs_sim
def test_player_reports_underrun_when_host_stops_feeding():
    stream = RNG.integers(0, 256, 400).astype(np.uint8)
    log, info = pru_player.play(stream, feed_limit=100)      # the host only ever provides 100 bytes
    assert info["status"] == pru_player.STATUS_UNDERRUN


# ---------------------------------------------------------------- scene input: Python WAV or web-page zip
def _web_zip(path, x8, settings):
    import io
    import json
    import zipfile
    import soundfile as sf
    with zipfile.ZipFile(path, "w") as z:
        for m in range(8):
            b = io.BytesIO()
            sf.write(b, x8[m], pdm.FS, subtype="PCM_16", format="WAV")
            z.writestr(f"mics/mic{m + 1}.wav", b.getvalue())
        z.writestr("settings.json", json.dumps(settings))


def test_web_zip_loads_all_8_mics_in_order(tmp_path):
    import make_pdm
    x8 = np.stack([np.full(1600, 0.01 * (m + 1)) for m in range(8)])      # mic m has level 0.01*(m+1)
    _web_zip(tmp_path / "scene.zip", x8, {"radius": 7, "fanOn": True})
    got, settings = make_pdm.load_scene(str(tmp_path / "scene.zip"))
    assert got.shape == (8, 1600)
    assert np.allclose(got[:, 0], x8[:, 0], atol=1e-4)                     # order and relative levels kept
    assert settings == {"radius": 7, "fanOn": True}


def test_zip_without_mics_is_refused(tmp_path):
    import zipfile
    import make_pdm
    with zipfile.ZipFile(tmp_path / "other.zip", "w") as z:
        z.writestr("readme.txt", "not a scene")
    with pytest.raises(ValueError, match="missing"):
        make_pdm.load_scene(str(tmp_path / "other.zip"))


def _zip_n(path, n, settings, n_samples=2000):
    """Fake scene zip with n mic WAVs (mic m has level 0.01*(m+1))."""
    _web_zip_n(path, np.stack([np.full(n_samples, 0.01 * (m + 1)) for m in range(n)]), settings)


def _web_zip_n(path, xs, settings):
    import io
    import json
    import zipfile
    import soundfile as sf
    with zipfile.ZipFile(path, "w") as z:
        for m in range(len(xs)):
            b = io.BytesIO()
            sf.write(b, xs[m], pdm.FS, subtype="PCM_16", format="WAV")
            z.writestr(f"mics/mic{m + 1}.wav", b.getvalue())
        z.writestr("settings.json", json.dumps(settings))


def test_schema1_zip_8_mics_unchanged(tmp_path):
    import make_pdm
    _zip_n(tmp_path / "s1.zip", 8, {"radius": 6, "rt60": 0.4})
    got, settings = make_pdm.load_scene(str(tmp_path / "s1.zip"))
    assert got.shape == (8, 2000) and settings["radius"] == 6 and "schema" not in settings


def test_schema2_zip_8_mics_loads_and_keeps_radius(tmp_path):
    import warnings
    import make_pdm
    st = {"schema": 2, "scenario": "home", "roomL": 5, "roomW": 4, "roomH": 2.6, "rt60": 0.45, "damping": 0.5,
          "micCount": 8, "arrayShape": "ring", "radius": 7, "speakers": [], "noises": []}
    _zip_n(tmp_path / "s2.zip", 8, st)
    with warnings.catch_warnings():
        warnings.simplefilter("error")                                     # no mismatch warning expected
        got, settings = make_pdm.load_scene(str(tmp_path / "s2.zip"))
    assert got.shape == (8, 2000) and settings["radius"] == 7 and settings["schema"] == 2


@pytest.mark.parametrize("n", [4, 16])
def test_schema2_zip_with_other_mic_count_is_refused(tmp_path, n):
    import make_pdm
    _zip_n(tmp_path / "s2.zip", n, {"schema": 2, "micCount": n, "radius": 5})
    with pytest.raises(ValueError) as e:
        make_pdm.load_scene(str(tmp_path / "s2.zip"))
    msg = str(e.value)
    assert f"has {n} microphones" in msg and "needs exactly 8" in msg and "Microphones = 8" in msg


def test_mic_count_mismatch_warns(tmp_path):
    import make_pdm
    _zip_n(tmp_path / "m.zip", 8, {"schema": 2, "micCount": 12})
    with pytest.warns(UserWarning, match="micCount=12"):
        got, _ = make_pdm.load_scene(str(tmp_path / "m.zip"))
    assert got.shape[0] == 8
    _zip_n(tmp_path / "m16.zip", 16, {"schema": 2, "micCount": 8})        # files win: refused naming 16
    with pytest.warns(UserWarning), pytest.raises(ValueError, match="16 microphones"):
        make_pdm.load_scene(str(tmp_path / "m16.zip"))


def test_wav_and_zip_give_the_same_scene(tmp_path):
    import soundfile as sf
    import make_pdm
    x8 = 0.3 * RNG.standard_normal((8, 1600))
    x8 = np.clip(x8, -0.9, 0.9)
    sf.write(tmp_path / "scene.wav", x8.T, pdm.FS, subtype="PCM_16")
    _web_zip(tmp_path / "scene.zip", x8, {})
    a, _ = make_pdm.load_scene(str(tmp_path / "scene.wav"))
    b, _ = make_pdm.load_scene(str(tmp_path / "scene.zip"))
    assert np.array_equal(a, b)


# ---------------------------------------------------------------- firmware-exact chain (exp24)
# Loop-based reference, copied unchanged from audio_pipe tests/test_pdm_rx.py (cic3_reference, fir_reference,
# dcblock_reference, saturate), start = 0. audio_pipe's test_pcm_matches_reference_exactly shows pdm_rx.asm
# matches it on the simulator, so matching it here means matching the firmware.
AUDIO_PIPE = os.environ.get("AUDIO_PIPE", os.path.join(os.path.expanduser("~"), "Downloads", "PRU",
                                                       "audio_pipe_src", "audio_pipe"))


def _ref_cic3(bits, osr=96):
    a1 = a2 = a3 = 0
    latched = []
    for i, b in enumerate(bits):
        a1 += b
        a2 += a1
        a3 += a2
        if (i + 1) % osr == 0:
            latched.append(a3 & pdm.MASK28)
    d1 = d3 = d5 = 0
    out = []
    for x in latched:
        c3 = x - d1
        d1 = x
        c4 = c3 - d3
        d3 = c3
        c5 = (c4 - d5) & pdm.MASK28
        d5 = c4
        out.append(c5 - osr ** 3 // 2)
    return out[3:]


def _ref_fir(x32, table):
    window = [0] * 64
    out = []
    for k, x in enumerate(x32):
        window = window[1:] + [x]
        if k % 2 == 1:
            acc = sum(t * d for t, d in zip(table, window))
            out.append((acc + (1 << 26)) >> 27)
    return out


def _ref_dcblock(ys):
    out, e = [], 0
    for y in ys:
        e += ((y << 32) - e) >> 7
        out.append(y - ((e + (1 << 31)) >> 32))
    return out


def _reference_fw(bits):
    ys = _ref_dcblock(_ref_fir(_ref_cic3([int(b) for b in bits]), pdm.fir_table_q27().tolist()))
    return [max(-pdm.FW_PCM_MAX, min(pdm.FW_PCM_MAX, y)) for y in ys]


def test_fw_table_is_symmetric_and_padded():
    t = pdm.fir_table_q27()
    assert t[0] == 0 and np.array_equal(t[1:], t[1:][::-1])


@pytest.mark.parametrize("kind", ["random", "tone", "ones", "zeros", "step"])
def test_frontend_fw_matches_firmware_reference(kind):
    n = 96 * 2 * 400                                         # 400 PCM samples
    if kind == "random":
        bits = RNG.integers(0, 2, n).astype(np.uint8)
    elif kind == "tone":
        bits = pdm.to_pdm(0.5 * np.sin(2 * np.pi * 1000 * np.arange(n // 192) / pdm.FS))
    elif kind == "step":                                     # full-scale step: saturation and DC blocker together
        bits = np.r_[np.zeros(n // 2), np.ones(n // 2)].astype(np.uint8)
    else:
        bits = np.full(n, kind == "ones", np.uint8)
    assert pdm.frontend_fw(bits).tolist() == _reference_fw(bits)


def test_frontend_fw_long_scene_no_overflow():
    """The int64 integrators would wrap after ~10 s of all-1s without the mod-2^28 masking."""
    bits = np.ones(pdm.FS_PDM * 12, np.uint8)               # 12 s full scale
    y = pdm.frontend_fw(bits)
    assert y[-1] == pytest.approx(0, abs=2)                  # DC blocked to zero after 12 s


def test_frontend_fw_close_to_standin():
    # Broadband input: a single tone gives the phase-slope delay estimate nothing to fit.
    x = np.fft.irfft(np.fft.rfft(RNG.standard_normal(16000)) * (np.fft.rfftfreq(16000, 1 / pdm.FS) < 6000), 16000)
    bits = pdm.to_pdm(0.5 * x / np.max(np.abs(x)))
    b = pdm.frontend_fw(bits) / 2 ** 23
    a = pdm.frontend(bits)[:len(b)]
    d = pdm.delay_samples(a, b)
    assert abs(d - 1.5) < 0.05                               # stand-in is 1.5 samples later (3 dropped warm-up 32 kHz samples)
    assert abs(20 * np.log10(np.std(b[2000:]) / np.std(a[2000:]))) < 0.1


@pytest.mark.skipif(not os.path.isfile(os.path.join(AUDIO_PIPE, "firmware", "fir_coefs.inc")),
                    reason="audio_pipe not on this PC (set AUDIO_PIPE)")
def test_fw_table_matches_audio_pipe():
    theirs = pdm.fir_table_q27(os.path.join(AUDIO_PIPE, "firmware", "fir_coefs.inc"))
    assert np.array_equal(pdm.fir_table_q27(), theirs)
