import re, struct, zlib
from array import array
from math import cos, pi, sqrt


class ImageError(ValueError):
    pass


def read(path):
    with open(path, 'rb') as f:
        data = f.read()
    return decode(data)


def decode(data):
    for check, decoder in _FORMATS:
        if check(data):
            try:
                return decoder(data)
            except (IndexError, KeyError, struct.error, zlib.error) as e:
                raise ImageError('corrupt or truncated image data') from e
    raise ImageError('unsupported image format')


def _blank(w, h):
    if w < 1 or h < 1 or w * h > 1 << 28:
        raise ImageError('invalid image dimensions')
    return bytearray(w * h * 4)


_ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
_PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _is_png(d):
    return d.startswith(b'\x89PNG\r\n\x1a\n')


def _png_unfilter(raw, pos, stride, bpp, rows):
    prev = bytearray(stride)
    out = []
    for _ in range(rows):
        ft = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        if len(line) != stride:
            raise ImageError('truncated PNG data')
        pos += 1 + stride
        if ft == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif ft == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        elif ft != 0:
            raise ImageError('invalid PNG filter')
        out.append(line)
        prev = line
    return out, pos


def _png_samples(line, count, depth):
    if depth == 8:
        return line[:count]
    if depth == 16:
        return line[0:count * 2:2]
    per = 8 // depth
    mask = (1 << depth) - 1
    return [(line[i // per] >> (8 - depth * (i % per + 1))) & mask for i in range(count)]


def _png(data):
    pos = 8
    idat = []
    plte = b''
    trns = b''
    hdr = None
    while pos + 8 <= len(data):
        n, kind = struct.unpack('>I4s', data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if kind == b'IHDR':
            hdr = struct.unpack('>IIBBBBB', body)
        elif kind == b'PLTE':
            plte = body
        elif kind == b'tRNS':
            trns = body
        elif kind == b'IDAT':
            idat.append(body)
        elif kind == b'IEND':
            break
    if hdr is None or not idat:
        raise ImageError('corrupt PNG')
    w, h, depth, ctype, _, _, interlace = hdr
    if ctype not in _PNG_CHANNELS or depth not in (1, 2, 4, 8, 16):
        raise ImageError('invalid PNG header')
    channels = _PNG_CHANNELS[ctype]
    raw = zlib.decompress(b''.join(idat))
    out = _blank(w, h)
    sdepth = 8 if depth == 16 else depth
    maxv = (1 << sdepth) - 1
    keyed = None
    if ctype == 0 and len(trns) >= 2:
        keyed = int.from_bytes(trns[:2], 'big') >> (8 if depth == 16 else 0)
    elif ctype == 2 and len(trns) >= 6:
        keyed = tuple(int.from_bytes(trns[i:i + 2], 'big') >> (8 if depth == 16 else 0) for i in (0, 2, 4))
    pal = [(plte[i], plte[i + 1], plte[i + 2], trns[i // 3] if i // 3 < len(trns) else 255)
           for i in range(0, len(plte) - 2, 3)]
    bpp = max(1, channels * depth // 8)
    pos = 0
    for x0, y0, dx, dy in (_ADAM7 if interlace else ((0, 0, 1, 1),)):
        pw = (w - x0 + dx - 1) // dx
        ph = (h - y0 + dy - 1) // dy
        if pw <= 0 or ph <= 0:
            continue
        stride = (pw * channels * depth + 7) // 8
        rows, pos = _png_unfilter(raw, pos, stride, bpp, ph)
        for j, line in enumerate(rows):
            s = _png_samples(line, pw * channels, depth)
            base = (y0 + j * dy) * w + x0
            for i in range(pw):
                if ctype == 0:
                    v = s[i]
                    g = v * 255 // maxv
                    px = (g, g, g, 0 if v == keyed else 255)
                elif ctype == 2:
                    t = (s[i * 3], s[i * 3 + 1], s[i * 3 + 2])
                    px = (t[0], t[1], t[2], 0 if t == keyed else 255)
                elif ctype == 3:
                    px = pal[s[i]]
                elif ctype == 4:
                    px = (s[i * 2], s[i * 2], s[i * 2], s[i * 2 + 1])
                else:
                    px = (s[i * 4], s[i * 4 + 1], s[i * 4 + 2], s[i * 4 + 3])
                o = (base + i * dx) * 4
                out[o:o + 4] = bytes(px)
    return w, h, out


def _is_bmp(d):
    return d.startswith(b'BM')


def _bmp_channel(v, mask):
    if not mask:
        return 255
    shift = (mask & -mask).bit_length() - 1
    return ((v & mask) >> shift) * 255 // (mask >> shift)


def _bmp(data):
    off = struct.unpack_from('<I', data, 10)[0]
    size = struct.unpack_from('<I', data, 14)[0]
    if size == 12:
        w, h, _, bpp = struct.unpack_from('<HHHH', data, 18)
        comp, used, entry = 0, 0, 3
    else:
        w, h, _, bpp, comp, _, _, _, used, _ = struct.unpack_from('<iiHHIIiiII', data, 18)
        entry = 4
    topdown = h < 0
    h = abs(h)
    if comp not in (0, 3, 6):
        raise ImageError('compressed BMP is not supported')
    if bpp not in (1, 4, 8, 16, 24, 32):
        raise ImageError('unsupported BMP bit depth')
    out = _blank(w, h)
    pal = []
    if bpp <= 8:
        start = 14 + size
        for i in range(used or (1 << bpp)):
            p = start + i * entry
            if p + 3 > len(data):
                break
            pal.append((data[p + 2], data[p + 1], data[p], 255))
    masks = (0, 0, 0, 0)
    if bpp in (16, 32):
        if comp in (3, 6) and size >= 52:
            masks = struct.unpack_from('<III', data, 54) + (struct.unpack_from('<I', data, 66)[0] if size >= 56 else 0,)
        elif comp in (3, 6):
            masks = struct.unpack_from('<III', data, 14 + size) + (0,)
        elif bpp == 16:
            masks = (0x7C00, 0x03E0, 0x001F, 0)
        else:
            masks = (0xFF0000, 0xFF00, 0xFF, 0)
    stride = ((w * bpp + 31) // 32) * 4
    for row in range(h):
        y = row if topdown else h - 1 - row
        line = data[off + row * stride:off + row * stride + stride]
        if len(line) < stride:
            raise ImageError('truncated BMP data')
        for x in range(w):
            if bpp == 24:
                px = (line[x * 3 + 2], line[x * 3 + 1], line[x * 3], 255)
            elif bpp == 32:
                v = line[x * 4] | line[x * 4 + 1] << 8 | line[x * 4 + 2] << 16 | line[x * 4 + 3] << 24
                px = tuple(_bmp_channel(v, m) for m in masks)
            elif bpp == 16:
                v = line[x * 2] | line[x * 2 + 1] << 8
                px = tuple(_bmp_channel(v, m) for m in masks)
            else:
                per = 8 // bpp
                idx = (line[x // per] >> (8 - bpp * (x % per + 1))) & ((1 << bpp) - 1)
                px = pal[idx] if idx < len(pal) else (0, 0, 0, 255)
            o = (y * w + x) * 4
            out[o:o + 4] = bytes(px)
    return w, h, out


def _is_pnm(d):
    return len(d) > 2 and d[0:1] == b'P' and d[1:2] in b'123456' and d[2:3].isspace()


def _pnm(data):
    kind = data[1:2]
    pos = 2

    def token():
        nonlocal pos
        while True:
            while pos < len(data) and data[pos:pos + 1].isspace():
                pos += 1
            if data[pos:pos + 1] == b'#':
                while pos < len(data) and data[pos] not in b'\r\n':
                    pos += 1
            else:
                break
        start = pos
        while pos < len(data) and not data[pos:pos + 1].isspace():
            pos += 1
        return data[start:pos]

    w = int(token())
    h = int(token())
    bitmap = kind in (b'1', b'4')
    maxv = 1 if bitmap else int(token())
    if maxv < 1 or maxv > 65535:
        raise ImageError('invalid PNM maximum value')
    channels = 3 if kind in (b'3', b'6') else 1
    count = w * h * channels
    out = _blank(w, h)
    if kind == b'1':
        vals = [0 if c == 49 else 1 for c in re.sub(rb'#[^\r\n]*', b'', data[pos:]) if c in b'01']
    elif kind == b'4':
        pos += 1
        stride = (w + 7) // 8
        vals = []
        for y in range(h):
            line = data[pos + y * stride:pos + (y + 1) * stride]
            if len(line) < stride:
                raise ImageError('truncated PNM data')
            vals.extend(0 if (line[x // 8] >> (7 - x % 8)) & 1 else 1 for x in range(w))
    elif kind in (b'2', b'3'):
        vals = [int(t) for t in re.sub(rb'#[^\r\n]*', b'', data[pos:]).split()]
    else:
        pos += 1
        if maxv < 256:
            vals = data[pos:pos + count]
        else:
            vals = [(data[i] << 8) | data[i + 1] for i in range(pos, pos + count * 2 - 1, 2)]
    if len(vals) < count:
        raise ImageError('truncated PNM data')
    scale = 1 if bitmap else maxv
    for i in range(w * h):
        if channels == 3:
            px = (vals[i * 3] * 255 // scale, vals[i * 3 + 1] * 255 // scale, vals[i * 3 + 2] * 255 // scale, 255)
        else:
            g = vals[i] * 255 // scale
            px = (g, g, g, 255)
        out[i * 4:i * 4 + 4] = bytes(px)
    return w, h, out


def _is_gif(d):
    return d[:6] in (b'GIF87a', b'GIF89a')


def _gif_lzw(data, minbits):
    clear = 1 << minbits
    end = clear + 1
    base = [bytes((i,)) for i in range(clear)] + [b'', b'']
    table = list(base)
    size = minbits + 1
    prev = None
    out = bytearray()
    buf = 0
    nbits = 0
    for byte in data:
        buf |= byte << nbits
        nbits += 8
        while nbits >= size:
            code = buf & ((1 << size) - 1)
            buf >>= size
            nbits -= size
            if code == clear:
                table = list(base)
                size = minbits + 1
                prev = None
                continue
            if code == end:
                return out
            if prev is None:
                entry = table[code]
            else:
                if code > len(table):
                    raise ImageError('corrupt GIF data')
                entry = table[code] if code < len(table) else prev + prev[:1]
                if len(table) < 4096:
                    table.append(prev + entry[:1])
                    if len(table) == (1 << size) and size < 12:
                        size += 1
            out += entry
            prev = entry
    return out


def _gif(data):
    sw, sh, flags = struct.unpack_from('<HHB', data, 6)
    pos = 13
    gct = b''
    if flags & 0x80:
        n = 3 * (2 << (flags & 7))
        gct = data[pos:pos + n]
        pos += n
    transparent = None
    out = _blank(sw, sh)
    while pos < len(data):
        block = data[pos]
        pos += 1
        if block == 0x21:
            label = data[pos]
            pos += 1
            if label == 0xF9 and data[pos] >= 4:
                if data[pos + 1] & 1:
                    transparent = data[pos + 4]
            while data[pos]:
                pos += data[pos] + 1
            pos += 1
        elif block == 0x2C:
            left, top, fw, fh, fflags = struct.unpack_from('<HHHHB', data, pos)
            pos += 9
            table = gct
            if fflags & 0x80:
                n = 3 * (2 << (fflags & 7))
                table = data[pos:pos + n]
                pos += n
            minbits = data[pos]
            pos += 1
            chunks = []
            while data[pos]:
                chunks.append(data[pos + 1:pos + 1 + data[pos]])
                pos += data[pos] + 1
            idx = _gif_lzw(b''.join(chunks), minbits)
            if len(idx) < fw * fh:
                idx += bytes(fw * fh - len(idx))
            if fflags & 0x40:
                order = [y for start, step in ((0, 8), (4, 8), (2, 4), (1, 2)) for y in range(start, fh, step)]
            else:
                order = range(fh)
            for src, y in enumerate(order):
                oy = top + y
                if oy >= sh:
                    continue
                for x in range(fw):
                    ox = left + x
                    if ox >= sw:
                        break
                    i = idx[src * fw + x]
                    o = (oy * sw + ox) * 4
                    if i == transparent or i * 3 + 2 >= len(table):
                        continue
                    out[o:o + 4] = bytes((table[i * 3], table[i * 3 + 1], table[i * 3 + 2], 255))
            return sw, sh, out
        else:
            break
    raise ImageError('GIF contains no image')


_ZIGZAG = (
    0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5,
    12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
)
_IDCT = [[(1 / sqrt(2) if u == 0 else 1.0) / 2 * cos((2 * x + 1) * u * pi / 16) for u in range(8)] for x in range(8)]
_CLIP = bytes(400) + bytes(range(256)) + b'\xff' * 400
_CR_R = [int(round(1.402 * (i - 128))) for i in range(256)]
_CB_B = [int(round(1.772 * (i - 128))) for i in range(256)]
_CR_G = [-0.714136 * (i - 128) for i in range(256)]
_CB_G = [-0.344136 * (i - 128) for i in range(256)]
_JPEG_RST = re.compile(rb'\xff[\xd0-\xd7]')
_JPEG_END = re.compile(rb'\xff[\x01-\xcf\xd8-\xfe]')


def _is_jpeg(d):
    return d.startswith(b'\xff\xd8')


class _Bits:
    __slots__ = ('d', 'p', 'buf', 'n')

    def __init__(self, d):
        self.d = d
        self.p = 0
        self.buf = 0
        self.n = 0

    def huff(self, lut):
        while self.n < 16:
            self.buf = (self.buf << 8) | (self.d[self.p] if self.p < len(self.d) else 0)
            self.p += 1
            self.n += 8
        v = lut[(self.buf >> (self.n - 16)) & 0xFFFF]
        if not v:
            raise ImageError('corrupt JPEG data')
        self.n -= v >> 8
        self.buf &= (1 << self.n) - 1
        return v & 255

    def bits(self, k):
        if not k:
            return 0
        while self.n < k:
            self.buf = (self.buf << 8) | (self.d[self.p] if self.p < len(self.d) else 0)
            self.p += 1
            self.n += 8
        self.n -= k
        v = self.buf >> self.n
        self.buf &= (1 << self.n) - 1
        return v

    def signed(self, t):
        v = self.bits(t)
        return v if v >= (1 << (t - 1)) else v - (1 << t) + 1


def _jpeg_lut(counts, symbols):
    lut = [0] * 65536
    code = 0
    k = 0
    for length in range(1, 17):
        for _ in range(counts[length - 1]):
            start = code << (16 - length)
            span = 1 << (16 - length)
            lut[start:start + span] = [(length << 8) | symbols[k]] * span
            code += 1
            k += 1
        code <<= 1
    return lut


def _jpeg_ac_refine(bits, lut, coef, base, ss, se, al, eobrun):
    p1 = 1 << al
    m1 = -1 << al
    k = ss
    if eobrun == 0:
        while k <= se:
            rs = bits.huff(lut)
            r = rs >> 4
            s = rs & 15
            if s:
                s = p1 if bits.bits(1) else m1
            elif r != 15:
                eobrun = 1 << r
                if r:
                    eobrun += bits.bits(r)
                break
            while k <= se:
                idx = base + _ZIGZAG[k]
                c = coef[idx]
                if c:
                    if bits.bits(1) and not c & p1:
                        coef[idx] = c + p1 if c >= 0 else c + m1
                else:
                    r -= 1
                    if r < 0:
                        break
                k += 1
            if s and k <= 63:
                coef[base + _ZIGZAG[k]] = s
            k += 1
    if eobrun > 0:
        while k <= se:
            idx = base + _ZIGZAG[k]
            c = coef[idx]
            if c and bits.bits(1) and not c & p1:
                coef[idx] = c + p1 if c >= 0 else c + m1
            k += 1
        eobrun -= 1
    return eobrun


def _jpeg_block(bits, coef, base, state, comp, dc, ac, ss, se, ah, al, progressive):
    if not progressive:
        t = bits.huff(dc)
        comp['pred'] += bits.signed(t) if t else 0
        coef[base] = comp['pred']
        k = 1
        while k < 64:
            rs = bits.huff(ac)
            r = rs >> 4
            s = rs & 15
            if s == 0:
                if r != 15:
                    break
                k += 16
                continue
            k += r
            if k > 63:
                break
            coef[base + _ZIGZAG[k]] = bits.signed(s)
            k += 1
        return
    if ss == 0:
        if ah == 0:
            t = bits.huff(dc)
            comp['pred'] += bits.signed(t) if t else 0
            coef[base] = comp['pred'] << al
        elif bits.bits(1):
            coef[base] |= 1 << al
        return
    if ah:
        state[0] = _jpeg_ac_refine(bits, ac, coef, base, ss, se, al, state[0])
        return
    if state[0] > 0:
        state[0] -= 1
        return
    k = ss
    while k <= se:
        rs = bits.huff(ac)
        r = rs >> 4
        s = rs & 15
        if s == 0:
            if r < 15:
                state[0] = (1 << r) - 1
                if r:
                    state[0] += bits.bits(r)
                break
            k += 16
            continue
        k += r
        if k > 63:
            break
        coef[base + _ZIGZAG[k]] = bits.signed(s) * (1 << al)
        k += 1


def _jpeg_scan(entropy, scan, comps, frame, restart, progressive):
    ss, se, ah, al = scan['ss'], scan['se'], scan['ah'], scan['al']
    segments = [s.replace(b'\xff\x00', b'\xff') for s in _JPEG_RST.split(entropy)]
    sel = scan['comps']
    if len(sel) == 1:
        c = sel[0][0]
        cw = -(-frame['w'] * c['h'] // frame['hmax'])
        ch = -(-frame['h'] * c['v'] // frame['vmax'])
        cols = -(-cw // 8)
        total = cols * -(-ch // 8)
    else:
        total = frame['mcux'] * frame['mcuy']
    state = [0]
    seg = 0
    bits = _Bits(segments[0])
    for c, _, _ in sel:
        c['pred'] = 0
    for m in range(total):
        if restart and m and m % restart == 0:
            seg += 1
            bits = _Bits(segments[seg] if seg < len(segments) else b'')
            state[0] = 0
            for c, _, _ in sel:
                c['pred'] = 0
        if len(sel) == 1:
            c, dc, ac = sel[0]
            by, bx = divmod(m, cols)
            _jpeg_block(bits, c['coef'], (by * c['bw'] + bx) * 64, state, c, dc, ac, ss, se, ah, al, progressive)
        else:
            my, mx = divmod(m, frame['mcux'])
            for c, dc, ac in sel:
                for v in range(c['v']):
                    for h in range(c['h']):
                        by = my * c['v'] + v
                        bx = mx * c['h'] + h
                        _jpeg_block(bits, c['coef'], (by * c['bw'] + bx) * 64, state, c, dc, ac, ss, se, ah, al, progressive)


def _jpeg_plane(c):
    bw, bh = c['bw'], c['bh']
    pw = bw * 8
    plane = bytearray(pw * bh * 8)
    q = c['q']
    coef = c['coef']
    zeros = [0.0] * 8
    for by in range(bh):
        for bx in range(bw):
            base = (by * bw + bx) * 64
            blk = coef[base:base + 64]
            if not any(blk[1:]):
                v = min(255, max(0, int(blk[0] * q[0] / 8 + 128.5)))
                for y in range(8):
                    o = (by * 8 + y) * pw + bx * 8
                    plane[o:o + 8] = bytes((v,)) * 8
                continue
            blk = [a * b for a, b in zip(blk, q)]
            tmp = []
            for v in range(8):
                r = blk[v * 8:v * 8 + 8]
                tmp.append([sum(m * f for m, f in zip(row, r)) for row in _IDCT] if any(r) else zeros)
            cols = [[sum(m * tmp[v][x] for v, m in enumerate(row)) for x in range(8)] for row in _IDCT]
            for y in range(8):
                o = (by * 8 + y) * pw + bx * 8
                plane[o:o + 8] = bytes(min(255, max(0, int(s + 128.5))) for s in cols[y])
    return plane, pw


def _jpeg(data):
    qts = {}
    dcs = {}
    acs = {}
    frame = None
    comps = []
    restart = 0
    progressive = False
    adobe = None
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker == 0xFF:
            pos += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        if marker == 0xD9:
            break
        length = struct.unpack_from('>H', data, pos + 2)[0]
        seg = data[pos + 4:pos + 2 + length]
        pos += 2 + length
        if marker == 0xDB:
            i = 0
            while i < len(seg):
                pq, tq = seg[i] >> 4, seg[i] & 15
                i += 1
                if pq:
                    vals = struct.unpack_from('>64H', seg, i)
                    i += 128
                else:
                    vals = seg[i:i + 64]
                    i += 64
                q = [0] * 64
                for k in range(64):
                    q[_ZIGZAG[k]] = vals[k]
                qts[tq] = q
        elif marker == 0xC4:
            i = 0
            while i < len(seg):
                tc, th = seg[i] >> 4, seg[i] & 15
                counts = seg[i + 1:i + 17]
                n = sum(counts)
                lut = _jpeg_lut(counts, seg[i + 17:i + 17 + n])
                (acs if tc else dcs)[th] = lut
                i += 17 + n
        elif marker in (0xC0, 0xC1, 0xC2):
            progressive = marker == 0xC2
            if seg[0] != 8:
                raise ImageError('unsupported JPEG precision')
            h, w, n = struct.unpack_from('>HHB', seg, 1)
            if n not in (1, 3):
                raise ImageError('unsupported JPEG color space')
            comps = []
            for k in range(n):
                cid, hv, tq = seg[6 + k * 3:9 + k * 3]
                comps.append({'id': cid, 'h': hv >> 4, 'v': hv & 15, 'tq': tq})
            hmax = max(c['h'] for c in comps)
            vmax = max(c['v'] for c in comps)
            mcux = -(-w // (8 * hmax))
            mcuy = -(-h // (8 * vmax))
            frame = {'w': w, 'h': h, 'hmax': hmax, 'vmax': vmax, 'mcux': mcux, 'mcuy': mcuy}
            for c in comps:
                c['bw'] = mcux * c['h']
                c['bh'] = mcuy * c['v']
                c['coef'] = array('h', bytes(2 * c['bw'] * c['bh'] * 64))
        elif marker in (0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            raise ImageError('unsupported JPEG encoding')
        elif marker == 0xDD:
            restart = struct.unpack_from('>H', seg)[0]
        elif marker == 0xEE and seg[:5] == b'Adobe':
            adobe = seg[11]
        elif marker == 0xDA:
            if frame is None:
                raise ImageError('corrupt JPEG')
            ns = seg[0]
            sel = []
            for k in range(ns):
                cid, t = seg[1 + k * 2], seg[2 + k * 2]
                c = next(c for c in comps if c['id'] == cid)
                sel.append((c, dcs.get(t >> 4), acs.get(t & 15)))
            ss, se, a = seg[1 + ns * 2:4 + ns * 2]
            scan = {'comps': sel, 'ss': ss, 'se': se, 'ah': a >> 4, 'al': a & 15}
            m = _JPEG_END.search(data, pos)
            end = m.start() if m else len(data)
            _jpeg_scan(data[pos:end], scan, comps, frame, restart, progressive)
            pos = end
    if frame is None:
        raise ImageError('corrupt JPEG')
    w, h = frame['w'], frame['h']
    planes = []
    for c in comps:
        c['q'] = qts[c['tq']]
        plane, pw = _jpeg_plane(c)
        xmap = [x * c['h'] // frame['hmax'] for x in range(w)]
        planes.append((plane, pw, xmap, c['v']))
        c['coef'] = None
    out = _blank(w, h)
    rgb = len(comps) == 3 and (adobe == 0 or [c['id'] for c in comps] == [82, 71, 66])
    alpha = b'\xff' * w
    for y in range(h):
        rows = []
        for plane, pw, xmap, v in planes:
            o = (y * v // frame['vmax']) * pw
            row = plane[o:o + pw]
            rows.append([row[x] for x in xmap])
        if len(rows) == 1:
            r = g = b = bytes(rows[0])
        elif rgb:
            r, g, b = bytes(rows[0]), bytes(rows[1]), bytes(rows[2])
        else:
            yy, cb, cr = rows
            r = bytes(_CLIP[400 + a + _CR_R[c]] for a, c in zip(yy, cr))
            g = bytes(_CLIP[400 + int(a + _CB_G[b_] + _CR_G[c] + 0.5)] for a, b_, c in zip(yy, cb, cr))
            b = bytes(_CLIP[400 + a + _CB_B[c]] for a, c in zip(yy, cb))
        o = y * w * 4
        out[o:o + w * 4:4] = r
        out[o + 1:o + w * 4:4] = g
        out[o + 2:o + w * 4:4] = b
        out[o + 3:o + w * 4:4] = alpha
    return w, h, out


_FORMATS = (
    (_is_png, _png),
    (_is_jpeg, _jpeg),
    (_is_gif, _gif),
    (_is_bmp, _bmp),
    (_is_pnm, _pnm),
)
