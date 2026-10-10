"""
pru_player.py - generates the PRU assembly for the PDM "player" and runs it on TI's cycle-accurate
pru-simulator (https://github.com/TexasInstruments/pru-simulator, AM243x PRU_ICSSG, V4 ISA).

The player stands in for the 8 microphones. It watches the PDM clock from the capture side and, after
every edge, puts the next bit of each of the 4 data lines on R30[3:0]: left mics after the falling edge,
right mics after the rising edge. One byte per clock period (see pdm.pack). The R5F keeps a ring buffer
filled and sets START; the mailbox layout is in README.md.

Nothing here is checked against silicon: the clock pin, data pins, RAM addresses and core clock below are
assumptions, not yet checked against the AM243x TRM or the board schematic.
"""
import os
import sys

def _find_pru_sim():
    """$PRU_SIM if set; else a 'pru-simulator' folder next to this checkout, in any folder above it, or in
    ~/Downloads. Returns None if none is found."""
    if os.environ.get("PRU_SIM"):
        return os.environ["PRU_SIM"]
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isdir(os.path.join(d, "pru-simulator")):
            return os.path.join(d, "pru-simulator")
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    dl = os.path.join(os.path.expanduser("~"), "Downloads", "pru-simulator")
    return dl if os.path.isdir(dl) else None


PRU_SIM = _find_pru_sim()
NOT_FOUND = ("TI pru-simulator not found. Clone https://github.com/TexasInstruments/pru-simulator next to this "
             "repository (or into Downloads), or set PRU_SIM to its folder, e.g. in PowerShell: "
             '$env:PRU_SIM = "C:\\path\\to\\pru-simulator"')


def available():
    """True if the TI simulator folder exists, so the player can run."""
    return PRU_SIM is not None and os.path.isfile(os.path.join(PRU_SIM, "simulator.py"))

CLK_PIN = 0                 # R31 bit the PDM clock arrives on (GPI0)
MAILBOX = 0x0000            # DRAM0 words (host <-> PRU), byte offsets below
WRITE_IDX, READ_IDX, START, STATUS, TOTAL = 0, 4, 8, 12, 16
RING = 0x0100
RING_SIZE = 0x1000          # 4 KB = 1.3 ms of PDM; power of two
STATUS_RUNNING, STATUS_DONE, STATUS_UNDERRUN = 0, 1, 2


def generate_asm():
    """PRU assembly text. r4 mailbox, r5 ring, r6 bytes played, r7 host write index, r8 current word,
    r9 ring mask, r10 total bytes, r0 scratch. Per byte: 2 waits + 2 output writes."""
    L = ["; PDM player: 4 data lines, one byte per clock period (bits 3:0 left mics, 7:4 right mics)",
         f"; CLK on R31.t{CLK_PIN}; data lines on R30[3:0]",
         "start:",
         f"    ldi   r4, {MAILBOX}",
         f"    ldi   r5, {RING}",
         f"    ldi   r9, {RING_SIZE - 1}",
         "    ldi   r6, 0",
         f"    lbbo  &r10, r4, {TOTAL}, 4",
         "wait_host:",
         f"    lbbo  &r0, r4, {START}, 4",
         "    qbeq  wait_host, r0, 0",
         f"    wbs   r31.t{CLK_PIN}                 ; begin on a known clock phase",
         "fetch:",
         "    qbeq  done, r6, r10",
         f"    lbbo  &r7, r4, {WRITE_IDX}, 4",
         "    qbeq  underrun, r7, r6",
         "    and   r0, r6, r9",
         "    add   r0, r0, r5",
         "    lbbo  &r8, r0, 0, 4",
         "    add   r6, r6, 4",
         f"    sbbo  &r6, r4, {READ_IDX}, 4"]
    for b in range(4):
        L += [f"    wbc   r31.t{CLK_PIN}                 ; falling edge -> left mics",
              f"    and   r30.b0, r8.b{b}, 0x0F",
              f"    wbs   r31.t{CLK_PIN}                 ; rising edge -> right mics",
              f"    lsr   r30.b0, r8.b{b}, 4"]
    L += ["    qba   fetch",
          "done:",
          f"    ldi   r0, {STATUS_DONE}",
          f"    sbbo  &r0, r4, {STATUS}, 4",
          "    halt",
          "underrun:",
          f"    ldi   r0, {STATUS_UNDERRUN}",
          f"    sbbo  &r0, r4, {STATUS}, 4",
          "    halt"]
    return "\n".join(L) + "\n"


def _simulator():
    if not available():
        raise FileNotFoundError(NOT_FOUND + (f" (looked at {PRU_SIM})" if PRU_SIM else ""))
    if PRU_SIM not in sys.path:
        sys.path.insert(0, PRU_SIM)
    cwd = os.getcwd()
    os.chdir(PRU_SIM)                       # the simulator reads memory.cfg and config/ relative to here
    try:
        from simulator import Simulator
        return Simulator(os.path.join(PRU_SIM, "memory.cfg"))
    finally:
        os.chdir(cwd)


def play(stream, pru_mhz=250.0, core="pru0", input_sync=2, max_cycles=None, feed_limit=None):
    """Run the generated player on the TI simulator against a 3.072 MHz clock.

    stream: uint8 array from pdm.pack (length a multiple of 4). The R5F is stood in for by this function:
    it pre-fills the ring, then tops it up every 64 cycles. Returns (log, info):
      log  = [(cycle, value)] every time R30[3:0] changed
      info = edges [(cycle, 'fall'|'rise')], status, period_cycles, cycles"""
    sim = _simulator()
    errs = sim.load(core, generate_asm())
    if errs:
        raise RuntimeError(f"player asm failed to assemble: {errs}")
    pru = sim.cores[core]
    period = pru_mhz * 1e6 / 3_072_000                      # core cycles per PDM clock period
    half = period / 2
    total = len(stream) - len(stream) % 4
    avail = total if feed_limit is None else min(total, feed_limit)   # feed_limit: test an empty ring
    wr = lambda addr, v: sim.memory.write(addr, int(v).to_bytes(4, "little"))
    rd = lambda addr: int.from_bytes(sim.memory.read(addr, 4)[0], "little")
    wr(MAILBOX + TOTAL, total)
    fed = 0

    def refill():
        nonlocal fed
        room = RING_SIZE - (fed - rd(MAILBOX + READ_IDX))
        chunk = min(room, avail - fed) // 4 * 4
        if chunk <= 0:
            return
        for i in range(0, chunk, 4):
            sim.memory.write(RING + (fed + i) % RING_SIZE, bytes(stream[fed + i:fed + i + 4]))
        fed += chunk
        wr(MAILBOX + WRITE_IDX, fed)

    refill()
    wr(MAILBOX + START, 1)
    sim.set_input(core, CLK_PIN, True)
    log, edges, level, last = [], [], 1, None
    limit = max_cycles or int((total + 8) * period * 2)
    while not pru.halted and pru.counters.cycles < limit:
        cyc = pru.counters.cycles
        k = int((cyc - input_sync) // half)
        want = 0 if k >= 0 and k % 2 == 1 else 1              # clock starts high, first fall at `half`
        if want != level:
            level = want
            sim.set_input(core, CLK_PIN, bool(level))
            edges.append((cyc, "fall" if level == 0 else "rise"))
        sim.step(core, 1)
        if cyc % 64 == 0:
            refill()
        pins = sim.io(core)["gpo_pins"]
        v = sum(b << i for i, b in enumerate(pins[:4]))
        if v != last:
            log.append((pru.counters.cycles, v))
            last = v
    return log, dict(edges=edges, status=rd(MAILBOX + STATUS), period_cycles=period,
                     cycles=pru.counters.cycles, pru_mhz=pru_mhz)


def check(stream, log, info):
    """Compare what the pins did with what the stream says they should do.
    Edge k (first fall = 0) must leave the data lines on nibble k before edge k+1: left mics after a fall,
    right mics after a rise. Returns dict(edges_checked, wrong, max_latency_ns); latency is the time from
    the edge to the pins changing (only counted when the value changed)."""
    ns = 1e3 / info["pru_mhz"]
    want = []
    for byte in stream[:len(stream) - len(stream) % 4].tolist():
        want += [byte & 0xF, byte >> 4]
    edges = info["edges"]
    wrong, worst = 0, 0.0
    for k in range(min(len(edges), len(want))):
        cyc = edges[k][0]
        nxt = edges[k + 1][0] if k + 1 < len(edges) else info["cycles"]
        seen = [(c, v) for c, v in log if cyc < c <= nxt]
        settled = seen[-1][1] if seen else next((v for c, v in reversed(log) if c <= cyc), None)
        if settled != want[k]:
            wrong += 1
        elif seen:
            worst = max(worst, (seen[0][0] - cyc) * ns)
    return dict(edges_checked=min(len(edges), len(want)), wrong=wrong, max_latency_ns=worst)
