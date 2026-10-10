"""
pdm.py - the microphone's PDM output, the wire format, and a reference model of the
AM243x capture chain. Everything the player and exp22 share lives here.

    16 kHz audio --to_pdm--> 1-bit PDM at 3.072 MHz --pack--> wire bytes
    wire bytes --unpack--> PDM bits --frontend--> 16 kHz audio (what the AM243x should output)

frontend() uses a Python stand-in FIR. frontend_fw() is the firmware-exact chain: the same integer maths as
audio_pipe pdm_rx.asm (Q27 table from fir_coefs.inc, 64-bit accumulator, Q32 DC blocker, 24-bit saturation),
ported from audio_pipe's tests/test_pdm_rx.py reference model, which the firmware matches sample for sample.
"""
import os
import re

import numpy as np
from scipy.signal import firwin2, lfilter, resample_poly

FS = 16000                      # audio rate out of the front-end
FS_PDM = 3_072_000              # PDM clock
UP = FS_PDM // FS               # 192
CIC_R = 96                      # 3.072 MHz -> 32 kHz
N_MICS, N_LINES = 8, 4          # two mics per data line
DC_K = 2 ** -7                  # DC blocker pole a = 1 - 2^-7 (corner ~20 Hz)
MAX_INPUT = 0.7                 # 2nd-order 1-bit modulator overloads above ~0.7 of full scale


# ---------------------------------------------------------------- the mic: audio -> PDM
def sigma_delta2(x):
    """2nd-order 1-bit sigma-delta modulator. x at the PDM rate, |x| <= MAX_INPUT. Returns 0/1 bits."""
    out = np.zeros(len(x), np.uint8)
    i1 = i2 = 0.0
    for n, v in enumerate(x.tolist()):
        fb = 1.0 if i2 > 0 else -1.0
        i1 += v - fb
        i2 += i1 - fb
        if fb > 0:
            out[n] = 1
    return out


def to_pdm(x):
    """One channel of 16 kHz audio (full-scale = 1.0) -> PDM bits at 3.072 MHz."""
    if np.max(np.abs(x)) > MAX_INPUT:
        raise ValueError(f"input peak {np.max(np.abs(x)):.2f} > {MAX_INPUT}: modulator would overload; scale it down")
    # A proper interpolation filter matters: a zero-order hold puts images at multiples of
    # 16 kHz that the decimator folds straight back on top of the signal.
    return sigma_delta2(resample_poly(x, UP, 1))


# ---------------------------------------------------------------- the wire: 8 mics -> 1 byte per clock
def pack(bits):
    """bits: (8, n) PDM bits, mic 1..8. Returns n bytes, one per PDM clock period.
    Mic 2k is the LEFT mic on data line k (driven after the falling edge, L/R pin low);
    mic 2k+1 is the RIGHT mic (driven after the rising edge, L/R pin high).
    byte bits 0-3 = left mics of lines 0-3, bits 4-7 = right mics of lines 0-3.
    The mic-to-line pairing is a placeholder; the final board may put one mic per pin."""
    b = bits.astype(np.uint8)
    out = np.zeros(bits.shape[1], np.uint8)
    for k in range(N_LINES):
        out |= b[2 * k] << k
        out |= b[2 * k + 1] << (4 + k)
    return out


def unpack(stream):
    """Inverse of pack(): n bytes -> (8, n) PDM bits."""
    bits = np.zeros((N_MICS, len(stream)), np.uint8)
    for k in range(N_LINES):
        bits[2 * k] = (stream >> k) & 1
        bits[2 * k + 1] = (stream >> (4 + k)) & 1
    return bits


def wire_events(stream, n=None):
    """What the pins do, edge by edge: [(edge, 4-bit value on the data lines)], first n clock periods.
    The player drives the LEFT nibble after each falling edge and the RIGHT nibble after each rising edge."""
    s = stream if n is None else stream[:n]
    ev = []
    for byte in s.tolist():
        ev.append(("fall", byte & 0xF))
        ev.append(("rise", byte >> 4))
    return ev


def capture_from_wire(events):
    """The capture side: sample the lines once per edge, assign to left/right mics. Returns bytes."""
    out = np.zeros(len(events) // 2, np.uint8)
    for i in range(len(out)):
        (e0, left), (e1, right) = events[2 * i], events[2 * i + 1]
        assert e0 == "fall" and e1 == "rise", "edges out of order"
        out[i] = left | (right << 4)
    return out


# ---------------------------------------------------------------- the AM243x chain: PDM -> 16 kHz
def cic3(bits):
    """CIC3 /96 on +-1 input, unity DC gain. The int64 wrap-around in the integrators is harmless
    because the final output (|y| <= 96^3) fits."""
    v = np.cumsum(np.cumsum(np.cumsum(bits.astype(np.int64) * 2 - 1)))
    v = v[CIC_R - 1::CIC_R]
    for _ in range(3):
        v = np.diff(v, prepend=0)
    return v.astype(np.float64) / CIC_R ** 3


def fir_taps():
    """63-tap low-pass at 32 kHz, flat to 7 kHz with the CIC3 droop compensated, stopband from 9 kHz."""
    f = np.arange(0, 7001, 1000)
    droop = (np.sin(np.pi * f * CIC_R / FS_PDM) / (CIC_R * np.sin(np.pi * np.maximum(f, 1) / FS_PDM))) ** 3
    droop[0] = 1.0
    return firwin2(63, np.r_[f, 9000, 16000], np.r_[1 / droop, 0, 0], fs=32000)


def dc_block(x):
    """y = x - e, e += (x - e) * 2^-7   ->   H = a (1 - z^-1) / (1 - a z^-1), a = 1 - 2^-7."""
    a = 1 - DC_K
    return lfilter([a, -a], [1, -a], x)


def frontend(bits):
    """One channel of PDM bits -> 16 kHz audio. Decimation phase 1 is chosen so the FIR delay is a whole
    number of output samples (15); the real firmware's phase may add a constant half sample to all mics."""
    y32 = lfilter(fir_taps(), [1.0], cic3(bits))
    return dc_block(y32[1::2])


# ---------------------------------------------------------------- the AM243x chain, firmware-exact (integers)
FIR_COEFS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fir_coefs.inc")
FW_HALF_SCALE = CIC_R ** 3 // 2  # 442368: SINC3 output for all-1s PDM, minus the midpoint
FW_WARMUP = 3                   # comb outputs the firmware drops after reinit
FW_PCM_MAX = (1 << 23) - 1      # firmware saturates to +-8,388,607 (full scale = 2^23)
MASK28 = (1 << 28) - 1


def fir_table_q27(path=FIR_COEFS):
    """T[0..63], Q27 int, oldest input first (T[0] = 0), as the firmware loads it into DRAM0 0x800."""
    with open(path) as f:
        t = [int(v) for v in re.findall(r"; T\[\d+\] = (-?\d+)", f.read())]
    assert len(t) == 64, f"{path}: expected 64 coefficients, found {len(t)}"
    return np.array(t, np.int64)


def cic3_fw(bits):
    """SD hardware SINC3 + firmware comb: integrate 0/1 bits, latch every 96, comb modulo 2^28, minus
    442,368, first 3 dropped. Signed 32 kHz ints, +-442,368 at full scale. Latch phase: bit 95 of the stream
    (the firmware's phase depends on when it reinits; that offset is measured in the simulator step)."""
    v = bits.astype(np.int64)
    for _ in range(3):          # mod 2^28 at every stage keeps int64 from overflowing on long scenes
        v = np.cumsum(v) & MASK28
    v = v[CIC_R - 1::CIC_R]
    for _ in range(3):
        v = np.diff(v, prepend=0)
    return ((v & MASK28) - FW_HALF_SCALE)[FW_WARMUP:]


def fir_fw(x32, table=None):
    """64-tap integer FIR on every 2nd sample (k = 1, 3, ...): (sum T[j] * x[k - 63 + j] + 2^26) >> 27."""
    t = fir_table_q27() if table is None else table
    acc = np.convolve(x32.astype(np.int64), t[::-1])[:len(x32)]     # integer convolve: exact
    return (acc[1::2] + (1 << 26)) >> 27


def dc_block_fw(y):
    """e += (y * 2^32 - e) >> 7 (int64 Q32, floor shift), out = y - round(e / 2^32). Python ints, exact."""
    out = np.empty(len(y), np.int64)
    e = 0
    for n, v in enumerate(y.tolist()):
        e += ((v << 32) - e) >> 7
        out[n] = v - ((e + (1 << 31)) >> 32)
    return out


def frontend_fw(bits):
    """One channel of PDM bits -> 16 kHz int PCM exactly as pdm_rx.asm computes it (full scale 2^23).
    Divide by 2^23 to compare with frontend()."""
    return np.clip(dc_block_fw(fir_fw(cic3_fw(bits))), -FW_PCM_MAX, FW_PCM_MAX)


# ---------------------------------------------------------------- measurement helpers
def delay_samples(a, b, band=(300, 3400)):
    """How many samples later a is than b (fractional), from the cross-spectrum phase slope."""
    n = min(len(a), len(b))
    w = np.hanning(n)
    S = np.fft.rfft(a[:n] * w) * np.conj(np.fft.rfft(b[:n] * w))
    f = np.fft.rfftfreq(n, 1 / FS)
    sel = (f >= band[0]) & (f <= band[1])
    slope = np.polyfit(2 * np.pi * f[sel] / FS, np.unwrap(np.angle(S[sel])), 1, w=np.sqrt(np.abs(S[sel])))[0]
    return -slope


def shift(x, d):
    """Delay x by d samples (fractional, circular) with an FFT phase ramp."""
    f = np.fft.rfftfreq(len(x), 1 / FS)
    return np.fft.irfft(np.fft.rfft(x) * np.exp(-2j * np.pi * f * d / FS), len(x))


def sinad_db(x, f0, band=(100, 7000)):
    """Signal-to-noise-and-distortion of a tone in the band, skipping the first quarter (settling)."""
    x = x[len(x) // 4:]
    P = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / FS)
    inb, sig = (f >= band[0]) & (f <= band[1]), np.abs(f - f0) < 60
    return 10 * np.log10(P[sig & inb].sum() / P[~sig & inb].sum())
