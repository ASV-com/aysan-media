#!/usr/bin/env python3
"""Maakt een pakkende 9:16-reel (MP4, ~10 s) voor Aysan uit 1-4 productfoto's. Versie 2.
Gebruik: python3 tools/make_reel.py spec.json uitvoer.mp4

spec.json (alleen images verplicht):
  {"images": ["https://cdn.shopify.com/...jpg" of lokaal pad, 1-4],
   "hook":  "Zijlamp kapot?",          # frame 0, max 6 woorden; leeg = afgeleid uit title (deel t/m '?')
   "kicker": "OUTLET",                 # optioneel label boven de producttitel
   "title": "Ovale markeringslamp",    # productnaam, verschijnt na de haak
   "price": "€ 14 excl. btw",          # exact uit Shopify
   "line":  "Op = op.",                # optioneel, onder de prijs
   "cta":   "aysantruckparts.com",
   "music": "drive" | "werk" | "rustig"}   # eigen muziek uit brand/music (default drive)

Opbouw (waarom: Instagram rankt op kijktijd/skip rate in de eerste 3 s):
- Frame 0 = product groot + haak in beeld, direct beweging. Geen logo-intro.
- Harde cuts op de maat (elke 2 tellen): volle foto en automatische detail-uitsnedes.
- Prijs 'slaat' in beeld; laatste shot = eerste shot (naadloze loop), CTA onderin.
- Geluid: eigen muziek (geen licentie nodig) + whoosh/klap, -16 LUFS.
Uitvoer 1080x1920, 30 fps, H.264 + AAC, plus cover-JPEG naast de mp4.
Tekst blijft binnen de Reels-veilige zone (y 250-1500).
"""
import io, json, os, subprocess, sys, tempfile, urllib.request, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS, SR = 1080, 1920, 30, 44100
NAVY = (29, 31, 46); ORANGE = (255, 107, 0); WHITE = (255, 255, 255)
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
LOGO = os.path.join(ROOT, 'brand', 'logo_op_navy.png')
BPM = {'drive': 118, 'werk': 102, 'rustig': 88}
SHOT_BEATS, N_SHOTS = 2, 10          # 10 shots van 2 tellen: ~10 s bij 118 bpm
PHOTO_BOX = (0, 470, W, 1550)        # fotovlak (vol breedte)


# ---------- tekst ----------
def font(size, bold=True):
    for p in ['/usr/share/fonts/truetype/liberation/LiberationSans-%s.ttf' % ('Bold' if bold else 'Regular'),
              '/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf' % ('-Bold' if bold else '')]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def wrap(d, text, f, maxw):
    lines, cur = [], ''
    for w in text.split():
        t = (cur + ' ' + w).strip()
        if d.textlength(t, font=f) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    return lines + ([cur] if cur else [])


def text_layer(lines_spec):
    """lines_spec: lijst van (tekst, size, fg, bg, y). Geeft RGBA-laag + onderkant."""
    lay = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    for txt, size, fg, bg, y in lines_spec:
        f = font(size)
        for ln in wrap(d, txt, f, W - 150):
            tw = d.textlength(ln, font=f); x = (W - tw) / 2
            pad = int(size * 0.28)
            d.rounded_rectangle([x - pad, y - pad * 0.6, x + tw + pad, y + size * 1.08 + pad * 0.6],
                                radius=int(size * 0.3), fill=bg)
            d.text((x, y), ln, font=f, fill=fg)
            y += int(size * 1.32)
    return lay, y


def badge(txt, size):
    f = font(size); d0 = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    tw = int(d0.textlength(txt, font=f)); bw, bh = tw + size, int(size * 1.6)
    im = Image.new('RGBA', (bw + 20, bh + 20), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([12, 14, bw + 12, bh + 14], radius=bh // 2, fill=(0, 0, 0, 90))  # schaduw
    d.rounded_rectangle([6, 6, bw + 6, bh + 6], radius=bh // 2, fill=ORANGE + (255,))
    d.text((6 + size / 2, 6 + (bh - size * 1.15) / 2), txt, font=f, fill=WHITE)
    return im


# ---------- beeld ----------
def load(src):
    if src.startswith('http'):
        req = urllib.request.Request(src, headers={'User-Agent': 'Mozilla/5.0 aysan-media'})
        return Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=60).read())).convert('RGB')
    return Image.open(src).convert('RGB')


def bg_color(photo):
    """Achtergrondkleur van de productfoto (mediaan van de randpixels)."""
    a = np.asarray(photo.resize((100, 100)))
    rand = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    return tuple(int(v) for v in np.median(rand, 0))


def bbox(photo):
    """Kader rond het product (alles wat duidelijk afwijkt van de achtergrond); anders hele foto."""
    sm = photo.resize((200, max(1, int(200 * photo.height / photo.width))))
    a = np.asarray(sm).astype(int); bgc = np.array(bg_color(photo))
    ys, xs = np.where(np.abs(a - bgc).sum(2) > 60)
    sx, sy = photo.width / a.shape[1], photo.height / a.shape[0]
    if len(xs) < 50:
        return (0, 0, photo.width, photo.height)
    return (xs.min() * sx, ys.min() * sy, (xs.max() + 1) * sx, (ys.max() + 1) * sy)


def crops(photo):
    """Uitsnedes (cx, cy, schaal t.o.v. 'product vult vlak'): vol, detail midden, detail hoeken."""
    x0, y0, x1, y1 = bbox(photo); cx, cy = (x0 + x1) / 2, (y0 + y1) / 2; bw, bh = x1 - x0, y1 - y0
    return [('vol', cx, cy, 1.0), ('detail', cx, cy, 1.7),
            ('detail', cx - bw * 0.22, cy - bh * 0.18, 2.1), ('detail', cx + bw * 0.22, cy + bh * 0.18, 2.1)]


def fit_scale(photo):
    """Schaal waarbij het product ~88% van het fotovlak vult."""
    x0, y0, x1, y1 = bbox(photo); bw, bh = PHOTO_BOX[2] - PHOTO_BOX[0], PHOTO_BOX[3] - PHOTO_BOX[1]
    return min(bw * 0.88 / max(x1 - x0, 1), bh * 0.80 / max(y1 - y0, 1))


def background(photo):
    """Wazige, donkere versie van de foto over het hele scherm."""
    s = max(W / photo.width, H / photo.height) * 1.1
    bg = photo.resize((int(photo.width * s), int(photo.height * s)), Image.BILINEAR)
    bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
    bg = bg.filter(ImageFilter.GaussianBlur(40))
    return Image.blend(bg, Image.new('RGB', (W, H), NAVY), 0.72)


def place_photo(canvas, photo, cx, cy, scale):
    """Zet de foto in het fotovlak met (cx, cy) van de foto in het midden van het vlak."""
    bx0, by0, bx1, by1 = PHOTO_BOX; vw, vh = bx1 - bx0, by1 - by0
    # alleen het zichtbare stuk schalen (snel)
    sw, sh = vw / scale, vh / scale
    l, t = cx - sw / 2, cy - sh / 2
    l = min(max(l, -sw * 0.25), photo.width - sw * 0.75); t = min(max(t, -sh * 0.25), photo.height - sh * 0.75)
    src = Image.new('RGB', (max(1, int(sw)), max(1, int(sh))), bg_color_cached(photo))
    ix0, iy0 = int(max(l, 0)), int(max(t, 0)); ix1, iy1 = int(min(l + sw, photo.width)), int(min(t + sh, photo.height))
    if ix1 > ix0 and iy1 > iy0:
        src.paste(photo.crop((ix0, iy0, ix1, iy1)), (int(ix0 - l), int(iy0 - t)))
    canvas.paste(src.resize((vw, vh), Image.BILINEAR), (bx0, by0))


_BG = {}


def bg_color_cached(photo):
    k = id(photo)
    if k not in _BG:
        _BG[k] = bg_color(photo)
    return _BG[k]


def ease(t):
    return 1 - (1 - t) ** 3


# ---------- geluid ----------
def sfx_whoosh(rng):
    n = int(0.28 * SR); t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    env = np.sin(np.pi * np.minimum(t / 0.28, 1)) ** 2
    out = np.convolve(noise, np.ones(6) / 6, 'same') * env * 0.25
    return np.stack([out, out], 1)


def sfx_hit(rng):
    n = int(0.4 * SR); t = np.arange(n) / SR
    body = np.sin(2 * np.pi * (60 + 90 * np.exp(-t / 0.03)) * t) * np.exp(-t / 0.12)
    out = body * 0.6 + rng.standard_normal(n) * np.exp(-t / 0.01) * 0.2
    return np.stack([out, out], 1)


def build_audio(style, dur, cut_times, hit_time, wav_out):
    bpm = BPM[style]; beat = 60.0 / bpm
    mp3 = os.path.join(ROOT, 'brand', 'music', 'aysan-%s.mp3' % style)
    start = 8 * beat  # sla de 2 intromaten zonder kick over: vanaf frame 0 energie
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', '%.3f' % start, '-t', '%.3f' % dur, '-i', mp3,
                          '-f', 's16le', '-ac', '2', '-ar', str(SR), '-'], capture_output=True, check=True).stdout
    mus = np.frombuffer(raw, np.int16).reshape(-1, 2).astype(np.float64) / 32768
    n = int(dur * SR); mix = np.zeros((n, 2)); mix[:len(mus)] = mus[:n] * 0.8
    rng = np.random.default_rng(3)
    for tc in cut_times:
        w = sfx_whoosh(rng); i = max(0, int((tc - 0.14) * SR)); k = min(len(w), n - i); mix[i:i + k] += w[:k]
    h = sfx_hit(rng); i = int(hit_time * SR); k = min(len(h), n - i); mix[i:i + k] += h[:k]
    fade = int(0.35 * SR); mix[-fade:] *= np.linspace(1, 0, fade)[:, None]
    mix /= max(np.abs(mix).max(), 1e-6) / 0.9
    with wave.open(wav_out, 'wb') as wf:
        wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(SR)
        wf.writeframes((mix * 32767).astype(np.int16).tobytes())


def loudnorm_args(wav):
    """Twee-pass loudnorm naar -16 LUFS, true peak -1,5 dB."""
    r = subprocess.run(['ffmpeg', '-hide_banner', '-i', wav, '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json',
                        '-f', 'null', '-'], capture_output=True, text=True).stderr
    m = json.loads(r[r.rfind('{'):r.rfind('}') + 1])
    return ('loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=%s:measured_TP=%s:measured_LRA=%s:measured_thresh=%s:'
            'offset=%s:linear=true' % (m['input_i'], m['input_tp'], m['input_lra'], m['input_thresh'], m['target_offset']))


# ---------- reel ----------
def derive_hook(s):
    if s.get('hook'):
        return s['hook']
    t = s.get('title', '')
    return t[:t.index('?') + 1] if '?' in t else t


def product_title(s, hook):
    t = s.get('title', '')
    rest = t[len(hook):].strip() if t.startswith(hook) and hook != t else t
    return rest or t


def main(spec, out):
    s = json.load(open(spec))
    imgs = s.get('images') or []
    if not 1 <= len(imgs) <= 4:
        sys.exit("images: 1 tot 4 foto's nodig")
    style = s.get('music', 'drive') if s.get('music', 'drive') in BPM else 'drive'
    hook = derive_hook(s); title = product_title(s, hook)
    for naam, t in (('hook', hook), ('title', title)):
        if len(t.split()) > 6:
            print('LET OP: %s heeft meer dan 6 woorden: %s' % (naam, t))

    photos = [load(u) for u in imgs]
    info = [(p, crops(p), fit_scale(p), background(p)) for p in photos]
    beat = 60.0 / BPM[style]; shot_len = SHOT_BEATS * beat
    dur = N_SHOTS * shot_len; nfr = int(round(dur * FPS))

    # shotlijst: eerste en laatste = foto 1 vol (loop); daartussen afwisselend foto's en uitsnedes
    mid = []
    for k in range(N_SHOTS - 2):
        pi = k % len(photos); vi = (k // len(photos) + (1 if len(photos) == 1 else 0)) % 4
        mid.append((pi, vi))
    shots = [(0, 0)] + mid + [(0, 0)]
    cut_times = [i * shot_len for i in range(1, N_SHOTS)]
    t_title, t_price, t_cta = 3 * shot_len, 5 * shot_len, dur - 2 * shot_len

    hook_lay, _ = text_layer([(hook, 92, WHITE, NAVY + (225,), 265)])
    title_spec = ([(s['kicker'].upper(), 40, WHITE, ORANGE + (255,), 270)] if s.get('kicker') else []) + \
                 [(title, 70, WHITE, NAVY + (225,), 340 if s.get('kicker') else 280)]
    title_lay, _ = text_layer(title_spec)
    cta_lay, _ = text_layer([('Voor 17:00 besteld, vandaag verzonden', 46, WHITE, NAVY + (235,), 1395)])
    url_lay, _ = text_layer([(s.get('cta') or 'aysantruckparts.com', 50, WHITE, ORANGE + (255,), 1470)])
    pb = badge(s['price'], 72) if s.get('price') else None
    line_lay = text_layer([(s['line'], 48, WHITE, NAVY + (225,), 1300)])[0] if s.get('line') else None
    lg = Image.open(LOGO).convert('RGBA'); lg = lg.resize((230, int(lg.height * 230 / lg.width)), Image.LANCZOS)

    def frame(i):
        t = i / FPS; si = min(int(t / shot_len), N_SHOTS - 1); ts = (t - si * shot_len) / shot_len
        pi, vi = shots[si]; p, cr, fs, bg = info[pi]
        _, cx, cy, z = cr[vi]
        punch = 1.0 + 0.10 * (1 - ease(min(ts * 4, 1)))              # klap-in bij elke cut
        drift = 1.0 + 0.06 * ts                                         # langzame zoom binnen shot
        if si == 0:
            punch = 1.0 + 0.18 * (1 - ease(min(t / 0.5, 1)))          # sterke inzoom vanaf frame 0
        if si == N_SHOTS - 1:
            drift = 1.0 + 0.06 * ts                                     # eindigt zoals shot 1 begint (loop)
        im = bg.copy()
        place_photo(im, p, cx, cy, fs * z * punch * drift)
        im = im.convert('RGBA')
        im.alpha_composite(lg, (W - lg.width - 60, 150))
        # haak 0..t_title, daarna producttitel
        if t < t_title:
            a = 1.0 if t < t_title - 0.15 else (t_title - t) / 0.15
            l2 = hook_lay if a >= 1 else Image.blend(Image.new('RGBA', (W, H)), hook_lay, a)
            if t < 0.25:  # tekst schuift in van boven
                l2 = l2.transform(l2.size, Image.AFFINE, (1, 0, 0, 0, 1, -int(60 * (1 - t / 0.25))))
            im.alpha_composite(l2)
        else:
            im.alpha_composite(title_lay)
        if pb is not None and t >= t_price:
            k = min((t - t_price) / 0.25, 1); sc = 1.0 + 0.35 * (1 - ease(k)) if k < 1 else 1.0
            b = pb.resize((int(pb.width * sc), int(pb.height * sc)), Image.BILINEAR)
            im.alpha_composite(b, ((W - b.width) // 2, 1180 - (b.height - pb.height) // 2))
        if line_lay is not None and t >= t_price:
            im.alpha_composite(line_lay)
        if t >= t_cta:
            im.alpha_composite(cta_lay); im.alpha_composite(url_lay)
        return im.convert('RGB')

    tmp = tempfile.mkdtemp()
    wav = os.path.join(tmp, 'a.wav')
    build_audio(style, dur, cut_times, t_price, wav)
    frame(int(t_price * FPS) + 12).save(os.path.splitext(out)[0] + '.jpg', quality=92)  # cover: product + prijs

    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H),
           '-r', str(FPS), '-i', '-', '-i', wav, '-af', loudnorm_args(wav), '-ar', str(SR),
           '-c:v', 'libx264', '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-preset', 'medium', '-crf', '20',
           '-c:a', 'aac', '-b:a', '160k', '-shortest', '-movflags', '+faststart', out]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(nfr):
        ff.stdin.write(frame(i).tobytes())
    ff.stdin.close(); ff.wait()
    if ff.returncode:
        sys.exit('ffmpeg faalde')
    print(out, '%.1fs' % (nfr / FPS), W, H, 'muziek=%s' % style, 'haak="%s"' % hook)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
