"""A small QR code encoder for the TV (the address of the web page, to scan with a phone): byte mode, error
correction level M, versions 1-6 (up to 106 bytes) - enough for an address, and no package to install on the Pi.
Follows ISO/IEC 18004 like Project Nayuki's reference implementation; the test compares it module by module with
the "qrcode" package."""

# version -> (EC codewords per block, number of blocks, data codewords per block) for level M
BLOCKS = {1: (10, 1, 16), 2: (16, 1, 28), 3: (26, 1, 44), 4: (18, 2, 32), 5: (24, 2, 43), 6: (16, 4, 27)}
ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34]}
ECL_M = 0                                         # format bits of level M

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs(data, n):
    """Reed-Solomon: the n error correction codewords of data"""
    gen = [1]
    for i in range(n):                            # (x - a^0)(x - a^1)...(x - a^(n-1))
        gen = [a ^ _mul(b, _EXP[i]) for a, b in zip(gen + [0], [0] + gen)]
    rem = [0] * n
    for d in data:
        f = d ^ rem[0]
        rem = rem[1:] + [0]
        for i in range(n):
            rem[i] ^= _mul(gen[i + 1], f)
    return rem


def _codewords(data, ver):
    ec, nb, nd = BLOCKS[ver]
    cap = nb * nd
    bits = []

    def put(v, n):
        bits.extend((v >> i) & 1 for i in range(n - 1, -1, -1))
    put(4, 4)                                     # byte mode
    put(len(data), 8)
    for b in data:
        put(b, 8)
    put(0, min(4, cap * 8 - len(bits)))           # terminator
    put(0, -len(bits) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < cap:
        words.append(pad)
        pad ^= 0xEC ^ 0x11
    blocks = [words[i * nd:(i + 1) * nd] for i in range(nb)]
    ecs = [_rs(b, ec) for b in blocks]
    return [b[i] for i in range(nd) for b in blocks] + [e[i] for i in range(ec) for e in ecs]


def _format_bits(mask):
    data = (ECL_M << 3) | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return ((data << 10) | rem) ^ 0x5412


MASKS = [
    lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0, lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0, lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0, lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
]


class _Grid:
    def __init__(self, ver):
        self.n = n = ver * 4 + 17
        self.m = [[False] * n for _ in range(n)]
        self.fn = [[False] * n for _ in range(n)]
        self._functions(ver)

    def set_fn(self, x, y, dark):
        self.m[y][x] = dark
        self.fn[y][x] = True

    def _functions(self, ver):
        n = self.n
        for i in range(n):                        # timing
            self.set_fn(6, i, i % 2 == 0)
            self.set_fn(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):         # finders with separators
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        d = max(abs(dx), abs(dy))
                        self.set_fn(x, y, d not in (2, 4))
        al = ALIGN[ver]
        for i, ax in enumerate(al):
            for j, ay in enumerate(al):
                if (i == 0 and j == 0) or (i == 0 and j == len(al) - 1) or (i == len(al) - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_fn(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.format(0)                            # reserve the format areas (real bits later)
        self.set_fn(8, n - 8, True)               # the dark module

    def format(self, mask):
        bits, n = _format_bits(mask), self.n
        b = lambda i: (bits >> i) & 1 == 1        # noqa: E731
        for i in range(6):
            self.set_fn(8, i, b(i))
        self.set_fn(8, 7, b(6))
        self.set_fn(8, 8, b(7))
        self.set_fn(7, 8, b(8))
        for i in range(9, 15):
            self.set_fn(14 - i, 8, b(i))
        for i in range(8):
            self.set_fn(n - 1 - i, 8, b(i))
        for i in range(8, 15):
            self.set_fn(8, n - 15 + i, b(i))
        self.set_fn(8, n - 8, True)

    def place(self, words):
        n, i = self.n, 0
        total = len(words) * 8
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = n - 1 - vert if upward else vert
                    if not self.fn[y][x] and i < total:
                        self.m[y][x] = (words[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply(self, mask):
        f = MASKS[mask]
        for y in range(self.n):
            for x in range(self.n):
                if not self.fn[y][x] and f(x, y):
                    self.m[y][x] = not self.m[y][x]

    def penalty(self):
        n, m, p = self.n, self.m, 0
        for lines in (m, [list(c) for c in zip(*m)]):
            for row in lines:
                run, last = 0, None
                for v in row:
                    run = run + 1 if v == last else 1
                    last = v
                    if run == 5:
                        p += 3
                    elif run > 5:
                        p += 1
                s = "".join("1" if v else "0" for v in row)
                for pat in ("10111010000", "00001011101"):
                    p += 40 * sum(1 for k in range(len(s) - 10) if s[k:k + 11] == pat)
        for y in range(n - 1):
            for x in range(n - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    p += 3
        dark = sum(v for row in m for v in row)
        k = (abs(dark * 20 - n * n * 10) + n * n - 1) // (n * n) - 1
        return p + max(0, k) * 10


def encode(text, mask=None):
    """text -> square list of rows (True = dark), without the quiet zone"""
    data = text.encode("utf-8")
    ver = next((v for v in BLOCKS if len(data) <= BLOCKS[v][1] * BLOCKS[v][2] - 2), None)
    if ver is None:
        raise ValueError("zu lang für einen QR-Code der Version 1-6")
    words = _codewords(data, ver)
    best = None
    for k in ([mask] if mask is not None else range(8)):
        g = _Grid(ver)
        g.place(words)
        g.apply(k)
        g.format(k)
        score = g.penalty()
        if best is None or score < best[0]:
            best = (score, g)
    return best[1].m
