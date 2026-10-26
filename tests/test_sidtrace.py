"""SID voices from the debug stream: writes picked out of the bus cycles, registers followed, notes, envelope,
lost packets, the processor's half only, the tune's chips only."""
import struct

import numpy as np

from c64jukebox.hdmi.sidtrace import FRAME, PAL_HZ, SidTrace, note_name, wave_name

A4 = round(440 * 16777216 / PAL_HZ)


def stream(writes, cycles, start_seq=0, drop=()):
    """writes: [(cycle, addr, data)] -> debug stream packets covering `cycles` bus cycles (packets in drop are lost)"""
    w = np.full(cycles + (-cycles) % 360, 0x8100E5D2, dtype="<u4")     # reads of the processor
    for c, a, d in writes:
        w[c] = 0x80000000 | d << 16 | a
    out = []
    for k in range(len(w) // 360):
        if k not in drop:
            out.append(struct.pack("<HH", (start_seq + k) & 0xFFFF, 0) + w[k * 360:(k + 1) * 360].tobytes())
    return out


def voice(frames, base=0xD400, v=0):
    return frames[-1][1][base][3][v]


def test_names():
    assert note_name(69) == "A-4" and note_name(60.2) == "C-4" and note_name(71) == "H-4"
    assert wave_name(0x41) == "Puls" and wave_name(0x51) == "Puls+Dreieck" and wave_name(0x01) == "–"


def test_note_envelope_and_release():
    t = SidTrace()
    ws = [(100, 0xD400, A4 & 255), (101, 0xD401, A4 >> 8), (102, 0xD405, 0x00), (103, 0xD406, 0xA0),
          (104, 0xD404, 0x41)]                                   # pulse, gate on; attack 2 ms, sustain 10/15
    t.feed(stream(ws, 5 * FRAME))
    midi, lvl, ctrl, pw = voice(t.frames)
    assert note_name(midi) == "A-4" and abs(midi - 69) < 0.01 and ctrl == 0x41
    assert abs(lvl - 10 / 15) < 0.02                               # decayed to the sustain level
    assert t.frames[-1][1][0xD400][0] == 15                        # volume never written: full
    t.feed(stream([(10, 0xD404, 0x40), (11, 0xD418, 0x05)], 3 * FRAME, start_seq=t.seq + 1))
    vol, cut, filt, vs = t.frames[-1][1][0xD400]
    assert vs[0][1] < 0.01 and vol == 5 and t.lost == 0            # gate off: released quickly


def test_test_bit_and_voice3_off_are_silent():
    t = SidTrace()
    ws = [(1, 0xD40B, 0x49), (2, 0xD412, 0x21), (3, 0xD418, 0x8F), (4, 0xD413, 0), (5, 0xD414, 0xF0)]
    t.feed(stream(ws, 3 * FRAME))
    vs = t.frames[-1][1][0xD400][3]
    assert vs[1][1] == 0.0 and vs[2][1] == 0.0                     # voice 2 test bit, voice 3 switched off


def test_lost_packets_keep_the_time_and_vic_cycles_do_not_count():
    t = SidTrace()
    t.feed(stream([(5, 0xD404, 0x11)], 360 * 10, drop=(3, 4)))
    assert t.lost == 2 and t.cycle == 3600 and t.pkts == 8
    w = np.full(720, 0x0100E5D2, dtype="<u4")                      # PHI2 low: the VIC's half
    w[7] = 0x00000000 | 0x41 << 16 | 0xD404                         # (a write there would be nonsense anyway)
    t.feed([struct.pack("<HH", t.seq + 1, 0) + w[:360].tobytes(), struct.pack("<HH", t.seq + 2, 0) + w[360:].tobytes()])
    assert t.cycle == 3600 and t.chips[0xD400].regs[4] == 0x11


def test_two_chips_and_the_tunes_addresses_only():
    t = SidTrace()
    ws = [(10, 0xD404, 0x21), (11, 0xD504, 0x11), (12, 0xD420, 0x41)]
    t.feed(stream(ws, 2 * FRAME))
    assert sorted(t.chips) == [0xD400, 0xD420, 0xD500]
    t.limit(["D400", "$D500"])
    assert sorted(t.chips) == [0xD400, 0xD500]
    t.feed(stream([(3, 0xD424, 0x41)], FRAME, start_seq=t.seq + 1))
    assert 0xD420 not in t.chips and sorted(t.frames[-1][1]) == [0xD400, 0xD500]


def test_a_quiet_chip_is_forgotten_after_3_s():
    t = SidTrace()
    t.feed(stream([(10, 0xD504, 0x21)], FRAME))
    t.feed(stream([(f * FRAME + 10, 0xD404, 0x21) for f in range(160)], 160 * FRAME, start_seq=t.seq + 1))
    assert sorted(t.chips) == [0xD400]


def test_receiver_batches_with_short_packets_and_losses():
    """the receiver's way in (rows of one buffer) gives the same as packet by packet"""
    ws = [(f * FRAME + 50, 0xD404, 0x21 if f % 2 else 0x20) for f in range(6)] + [(3 * FRAME, 0xD400, 0x99)]
    pk = stream(ws, 6 * FRAME)
    pk[5] = pk[5][:4 + 216 * 4]                                     # a short one (its missing cycles are not sent)
    ref = SidTrace()
    ref.feed(pk)
    for drop in ((), (9,)):
        t = SidTrace()
        rows = [p for i, p in enumerate(pk) if i not in drop]
        for k in range(0, len(rows), 64):
            batch = rows[k:k + 64]
            buf = np.zeros((64, 1504), np.uint8)
            for i, p in enumerate(batch):
                buf[i, :len(p)] = np.frombuffer(p, np.uint8)
            t.feed_rows(buf, [len(p) for p in batch])
        assert t.lost == len(drop) and t.chips[0xD400].regs[0] == 0x99
        if not drop:
            assert t.cycle == ref.cycle and t.writes == ref.writes and t.nframe == ref.nframe


def test_io2_only_for_a_tune_with_a_sid_there():
    ws = [(10, 0xDF00, 0x91), (11, 0xDE04, 0x21), (12, 0xD019, 0xFF), (13, 0xD404, 0x11)]
    t = SidTrace()
    t.feed(stream(ws, FRAME))
    assert sorted(t.chips) == [0xD400]                             # a REU at $DF00, the VIC at $D019: not SIDs
    t = SidTrace()
    t.limit(["D400", "DE00"])
    t.feed(stream(ws, FRAME))
    assert sorted(t.chips) == [0xD400, 0xDE00]
