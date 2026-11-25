#!/usr/bin/env python3
"""Maakt een professionele 9:16-reel (MP4, ~10,5 s) voor Aysan uit 1-4 productfoto's. Versie 3.
Gebruik: python3 tools/make_reel.py spec.json uitvoer.mp4

spec.json (alleen images verplicht):
  {"images": ["https://cdn.shopify.com/...jpg" of lokaal pad, 1-4],
   "hook":  "Zijlamp kapot?",          # frame 0, max 6 woorden; leeg = afgeleid uit title (deel t/m '?')
   "kicker": "OUTLET",                 # optioneel label boven de producttitel
   "title": "Ovale markeringslamp",    # productnaam, max 6 woorden
   "price": "€ 14 excl. btw",          # exact uit Shopify
   "line":  "Op = op.",                # optioneel, boven de prijs
   "cta":   "aysantruckparts.com",
   "music": "werk" | "drive" | "rustig"}   # eigen muziek uit brand/music (default werk)

Opbouw v3 (onderbouwing: rapport 'Pakkende product reels formats', nov 2026):
- Product vrijgesteld (rembg isnet-general-use, Apache-2.0) op een lichte studio-achtergrond met
  contactschaduw; lukt vrijstaand niet, dan een fotokaart met afgeronde hoeken.
- Rustig tempo, 5-6 shots: hero met haak (0-1,5 s), hero met titel, detail via CONTINUE zoom
  (1 foto) of andere foto's via push/slide met bewegingsonscherpte (10 f, easeInOutCubic),
  terug naar de hero voor de prijs, CTA-balk onderin (product wijkt omhoog, prijs blijft vrij).
- Tekst staat stil tijdens lezen (in 7 f, uit 5 f), binnen de veilige zone (y 270-1250, x 65-1015).
- Geluid: eigen muziek, gemixt (filters, compressie, ruimte, limiter) + 2 zachte accenten, -16 LUFS (eis van edit_media check).
Uitvoer 1080x1920, 30 fps, H.264 + AAC 48 kHz, plus cover-JPEG naast de mp4.
Vereist: pillow, numpy, rembg[cpu], pedalboard (zonder rembg/pedalboard: fotokaart / ongemixte muziek).
"""
import io, json, os, subprocess, sys, tempfile, urllib.request, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS, SR = 1080, 1920, 30, 48000
NAVY = (29, 31, 46); ORANGE = (255, 107, 0); WHITE = (255, 255, 255)
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, '..')
LOGO = os.path.join(ROOT, 'brand', 'logo_op_navy.png')
STYLES = {'werk': 102, 'drive': 118, 'rustig': 88}
PROD_C = (540, 870)            # middelpunt productvlak
PROD_MAX = (900, 560)          # max afmeting product bij schaal 1.0
T_PUSH = 10                    # frames per push/slide


# ---------- hulp ----------
def font(size):
    for p in ['/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def clamp(t):
    return min(max(t, 0.0), 1.0)


def ease_io(t):  # easeInOutCubic
    t = clamp(t)
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out(t):
    return 1 - (1 - clamp(t)) ** 3


def ease_sine(t):
    return float(-(np.cos(np.pi * clamp(t)) - 1) / 2)


def wrap(d, text, f, maxw):
    lines, cur = [], ''
    for w in text.split():
        t = (cur + ' ' + w).strip()
        if d.textlength(t, font=f) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    return lines + ([cur] if cur else [])


def text_block(text, size, color, maxw=930):
    """Gecentreerd tekstblok over de volle breedte (RGBA, transparant)."""
    f = font(size); d0 = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    lines = wrap(d0, text, f, maxw); lh = int(size * 1.15)
    im = Image.new('RGBA', (W, lh * len(lines) + 10), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for i, ln in enumerate(lines):
        d.text(((W - d.textlength(ln, font=f)) / 2, i * lh), ln, font=f, fill=color)
    return im


def text_fit(text, sizes, color):
    """Grootste lettergrootte waarbij de tekst op 1 regel past; anders de kleinste (2 regels)."""
    d0 = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    for sz in sizes:
        if len(wrap(d0, text, font(sz), 930)) == 1:
            return text_block(text, sz, color)
    return text_block(text, sizes[-1], color)


def pill(txt, size, bg, fg=WHITE):
    f = font(size); d0 = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    tw = int(d0.textlength(txt, font=f)); bw, bh = tw + int(size * 1.1), int(size * 1.55)
    im = Image.new('RGBA', (bw, bh), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=bh // 2, fill=bg + (255,))
    d.text(((bw - tw) / 2, (bh - size * 1.16) / 2), txt, font=f, fill=fg)
    return im


def fade(layer, a):
    if a >= 1:
        return layer
    out = layer.copy(); out.putalpha(out.getchannel('A').point(lambda v: int(v * max(a, 0.0))))
    return out


# ---------- beeld ----------
def load(src):
    if src.startswith('http'):
        req = urllib.request.Request(src, headers={'User-Agent': 'Mozilla/5.0 aysan-media'})
        return Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=60).read())).convert('RGB')
    return Image.open(src).convert('RGB')


_SESSION = None


def cutout(photo):
    """Vrijstaand product (RGBA, bijgesneden); anders fotokaart met afgeronde hoeken."""
    global _SESSION
    sm = photo.copy(); sm.thumbnail((1600, 1600))
    try:
        from rembg import new_session, remove
        if _SESSION is None:
            _SESSION = new_session('isnet-general-use')
        cut = remove(sm, session=_SESSION).convert('RGBA')
        cover = (np.asarray(cut.getchannel('A')) > 128).mean()
        box = cut.getchannel('A').point(lambda v: 255 if v > 20 else 0).getbbox()
        if 0.05 < cover < 0.92 and box:
            return cut.crop(box), True
        print('vrijstaand onbetrouwbaar (dekking %.2f): fotokaart' % cover)
    except Exception as e:
        print('vrijstaand niet gelukt, fotokaart:', e)
    card = sm.convert('RGBA')
    m = Image.new('L', card.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, card.width - 1, card.height - 1], radius=int(card.width * 0.03), fill=255)
    card.putalpha(m)
    return card, False


def studio_bg():
    """Lichte studio-achtergrond: radiaal verloop + fijne korrel tegen banding."""
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((x - 540) / 900) ** 2 + ((y - 820) / 1100) ** 2)
    c0, c1 = np.array([246, 247, 250], np.float32), np.array([200, 205, 216], np.float32)
    k = np.clip(r, 0, 1)[..., None] ** 1.4
    img = c0 * (1 - k) + c1 * k + np.random.default_rng(1).normal(0, 1.6, (H, W, 1))
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), 'RGB')


BG_PAD = 60  # achtergrond iets groter: langzame drift zodat het beeld nooit 'bevriest'


class Product:
    def __init__(self, photo):
        self.cut, self.free = cutout(photo)
        cw, ch = self.cut.size
        self.base = min(PROD_MAX[0] / cw, PROD_MAX[1] / ch)
        # detailpunt voor de continue zoom: drukste zone (meeste randen) binnen het product
        g = np.asarray(self.cut.convert('L').filter(ImageFilter.FIND_EDGES).resize((60, 60))).astype(float)
        g *= np.asarray(self.cut.getchannel('A').resize((60, 60))) > 128
        k = np.ones(15) / 15
        sm = np.apply_along_axis(lambda r: np.convolve(r, k, 'same'), 1, g)
        sm = np.apply_along_axis(lambda r: np.convolve(r, k, 'same'), 0, sm)
        iy, ix = np.unravel_index(sm.argmax(), sm.shape)
        self.focus = (float(np.clip((ix + 0.5) / 60 - 0.5, -0.3, 0.3)), float(np.clip((iy + 0.5) / 60 - 0.5, -0.3, 0.3)))
        # schaduw (eenmalig)
        sw = int(cw * 0.85); sh = max(40, int(cw * 0.10))
        m = Image.new('L', (sw + 200, sh + 200), 0)
        ImageDraw.Draw(m).ellipse([100, 100, 100 + sw, 100 + sh], fill=105)
        self.shadow = Image.new('RGBA', m.size, (20, 24, 40, 255)); self.shadow.putalpha(m.filter(ImageFilter.GaussianBlur(40)))

    def layer(self, scale, dx=0.0, dy=0.0, focus=0.0):
        """Volledige framelaag (RGBA): product subpixel geschaald rond PROD_C; focus 0..1 = naar detailpunt."""
        s = self.base * scale; cw, ch = self.cut.size
        fx, fy = self.focus[0] * cw * focus, self.focus[1] * ch * focus
        cx, cy = PROD_C[0] + dx, PROD_C[1] + dy
        a = 1 / s
        lay = self.cut.transform((W, H), Image.AFFINE, (a, 0, cw / 2 + fx - cx * a, 0, a, ch / 2 + fy - cy * a),
                                 resample=Image.BICUBIC)
        base = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        if self.free:
            if focus < 0.5:
                sc = s * (1 - focus)
                shd = self.shadow.resize((max(1, int(self.shadow.width * sc)), max(1, int(self.shadow.height * sc))))
                shd = fade(shd, 1 - focus * 2)
                base.alpha_composite(shd, (int(cx - fx * s - shd.width / 2), int(cy - fy * s + s * ch / 2 - shd.height / 2)))
        else:
            m = lay.getchannel('A').filter(ImageFilter.GaussianBlur(26)).point(lambda v: int(v * 0.35))
            sh_ = Image.new('RGBA', (W, H), (20, 24, 40, 255)); sh_.putalpha(m)
            base.alpha_composite(sh_, (0, 18))
        base.alpha_composite(lay)
        return base


def hblur(layer, px):
    """Horizontale bewegingsonscherpte: gemiddelde van verschoven kopieen."""
    if px < 2:
        return layer
    a = np.asarray(layer).astype(np.float32); acc = np.zeros_like(a); n = 7
    for i in range(n):
        acc += np.roll(a, int((i / (n - 1) - 0.5) * px), axis=1)
    return Image.fromarray((acc / n).astype(np.uint8), 'RGBA')


# ---------- geluid ----------
def read_mp3(path, start, dur):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', '%.3f' % start, '-t', '%.3f' % dur, '-i', path,
                          '-f', 'f32le', '-ac', '2', '-ar', str(SR), '-'], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).copy()


def whoosh(rng, n_sec=0.38, level=0.16):
    """Zachte luchtverplaatsing: ruis door een meeschuivend laagdoorlaatfilter, zonder scherpe hoogte."""
    n = int(n_sec * SR); t = np.linspace(0, 1, n); x = rng.standard_normal(n)
    fc = 250 + 2000 * np.sin(np.pi * t) ** 2
    al = 1 - np.exp(-2 * np.pi * fc / SR); y = np.zeros(n); acc = 0.0
    for i in range(n):
        acc += al[i] * (x[i] - acc); y[i] = acc
    y = y - np.convolve(y, np.ones(200) / 200, 'same')        # laag weg
    y *= np.sin(np.pi * t) ** 2; y /= max(np.abs(y).max(), 1e-6)
    return np.stack([y * level, np.roll(y, 60) * level], 1).astype(np.float32)


def thump(level=0.30):
    """Lage, korte impact (geen synth-klap)."""
    n = int(0.5 * SR); t = np.arange(n) / SR
    s = np.sin(2 * np.pi * (46 + 34 * np.exp(-t / 0.045)) * t) * np.exp(-t / 0.18)
    return np.stack([s * level, s * level], 1).astype(np.float32)


def build_audio(style, dur, accents, wav_out):
    mp3 = os.path.join(ROOT, 'brand', 'music', 'aysan-%s.mp3' % style)
    mus = read_mp3(mp3, 8 * 60.0 / STYLES[style], dur + 0.5)
    try:
        from pedalboard import (Pedalboard, HighpassFilter, LowpassFilter, PeakFilter, HighShelfFilter,
                                Compressor, Reverb, Gain)
        chain = Pedalboard([HighpassFilter(35), PeakFilter(3800, -5.0, 1.0), PeakFilter(250, -2.0, 0.8),
                            HighShelfFilter(9000, -4.0), LowpassFilter(13500),
                            Reverb(room_size=0.30, damping=0.6, wet_level=0.10, dry_level=0.92, width=0.9),
                            Compressor(threshold_db=-16, ratio=2.0, attack_ms=15, release_ms=160), Gain(-3)])
        mus = chain(mus.T.copy(), SR).T
    except ImportError:
        print('pedalboard ontbreekt: muziek ongemixt')
    n = int(dur * SR); mix = np.zeros((n, 2), np.float32); m = min(n, len(mus)); mix[:m] = mus[:m]
    rng = np.random.default_rng(5)
    for kind, tc in accents:
        s = whoosh(rng) if kind == 'whoosh' else thump()
        i = max(0, int((tc - (0.25 if kind == 'whoosh' else 0.0)) * SR)); k = min(len(s), n - i)
        mix[i:i + k] += s[:k]
    fi, fo = int(0.03 * SR), int(0.45 * SR)
    mix[:fi] *= np.linspace(0, 1, fi)[:, None]; mix[-fo:] *= np.linspace(1, 0, fo)[:, None]
    try:
        from pedalboard import Pedalboard, Limiter
        mix = Pedalboard([Limiter(threshold_db=-2.0, release_ms=120)])(mix.T.copy(), SR).T
    except ImportError:
        mix /= max(np.abs(mix).max(), 1e-6) / 0.9
    with wave.open(wav_out, 'wb') as wf:
        wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(SR)
        wf.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())


def loudnorm_args(wav, I=-16, TP=-1.5):
    r = subprocess.run(['ffmpeg', '-hide_banner', '-i', wav, '-af', 'loudnorm=I=%d:TP=%.1f:LRA=7:print_format=json' % (I, TP),
                        '-f', 'null', '-'], capture_output=True, text=True).stderr
    m = json.loads(r[r.rfind('{'):r.rfind('}') + 1])
    return ('loudnorm=I=%d:TP=%.1f:LRA=7:measured_I=%s:measured_TP=%s:measured_LRA=%s:measured_thresh=%s:'
            'offset=%s:linear=true' % (I, TP, m['input_i'], m['input_tp'], m['input_lra'], m['input_thresh'], m['target_offset']))


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


def plan(n):
    """Shotlijst (start_s, eind_s, soort, foto-index)."""
    if n == 1:
        return [(0.0, 1.5, 'hook', 0), (1.5, 4.0, 'hero', 0), (4.0, 6.6, 'detail', 0),
                (6.6, 8.8, 'price', 0), (8.8, 10.4, 'cta', 0)]
    step = 4.4 / (n - 1); sh = [(0.0, 1.5, 'hook', 0), (1.5, 3.4, 'hero', 0)]; t = 3.4
    for i in range(1, n):
        sh.append((t, t + step, 'other', i)); t += step
    return sh + [(t, t + 1.9, 'price', 0), (t + 1.9, t + 3.5, 'cta', 0)]


def main(spec, out):
    s = json.load(open(spec))
    imgs = s.get('images') or []
    if not 1 <= len(imgs) <= 4:
        sys.exit("images: 1 tot 4 foto's nodig")
    style = s.get('music') if s.get('music') in STYLES else 'werk'
    hook = derive_hook(s); title = product_title(s, hook)
    for naam, t in (('hook', hook), ('title', title)):
        if len(t.split()) > 6:
            print('LET OP: %s heeft meer dan 6 woorden: %s' % (naam, t))

    prods = [Product(load(u)) for u in imgs]
    shots = plan(len(prods)); dur = shots[-1][1]; nfr = int(round(dur * FPS))
    bg = studio_bg().convert('RGBA').resize((W + BG_PAD, H + BG_PAD), Image.BICUBIC)
    t_hook_end, t_price, t_cta = shots[0][1], shots[-2][0], shots[-1][0]

    hook_img = text_fit(hook, (104, 96, 88, 80), NAVY)
    kicker_img = pill(s['kicker'].upper(), 34, ORANGE) if s.get('kicker') else None
    title_img = text_fit(title, (68, 62, 56), NAVY)
    price_img = pill(s['price'], 74, ORANGE) if s.get('price') else None
    line_img = text_block(s['line'], 46, NAVY) if s.get('line') else None
    lg = Image.open(LOGO).convert('RGBA'); lg = lg.resize((300, int(lg.height * 300 / lg.width)), Image.LANCZOS)
    cta1 = text_block('Voor 17:00 besteld, vandaag verzonden', 40, WHITE)
    cta2 = text_block(s.get('cta') or 'aysantruckparts.com', 48, ORANGE)

    def shot_index(t):
        for i, sh in enumerate(shots):
            if t < sh[1]:
                return i
        return len(shots) - 1

    def prod_state(i, t):
        st, en, kind, pi = shots[i]; u = (t - st) / (en - st)
        bob = 9 * np.sin(2 * np.pi * t / 2.6)
        if kind == 'hook':
            return pi, 1.12 + 0.03 * ease_sine(u), 0, bob, 0.0
        if kind == 'hero':
            return pi, 1.15 - 0.15 * ease_io(u / 0.35) - 0.03 * ease_sine(u), 0, bob, 0.0
        if kind == 'detail':
            z = ease_io(u / 0.22) - ease_io((u - 0.80) / 0.20)
            return pi, 1.0 + 0.65 * z + 0.04 * ease_sine(u), 0, bob * (1 - z), z
        if kind == 'other':
            return pi, 1.0 + 0.09 * ease_sine(u), 0, bob, 0.0
        if kind == 'price':
            return pi, 0.94 + 0.07 * ease_sine(u), 0, bob - 20, 0.0
        return pi, 0.96 - 0.16 * ease_io(u * 2), 0, bob - 20 - 110 * ease_io(u * 2), 0.0   # cta: product kleiner en omhoog, prijs eronder

    def frame(fi):
        t = fi / FPS; i = shot_index(t); st, en, kind, pi = shots[i]
        ox = BG_PAD / 2 + 26 * np.sin(2 * np.pi * t / 7.0); oy = BG_PAD / 2 + 26 * np.cos(2 * np.pi * t / 9.0)
        im = bg.crop((int(ox), int(oy), int(ox) + W, int(oy) + H)); k = (t - st) * FPS
        if i > 0 and shots[i - 1][3] != pi and k < T_PUSH:                    # push/slide met onscherpte
            p = ease_io(k / T_PUSH); blur = 70 * np.sin(np.pi * p)
            a = prod_state(i - 1, st - 1e-3); b = prod_state(i, t)
            comb = Image.new('RGBA', (W, H), (0, 0, 0, 0))
            comb.alpha_composite(prods[a[0]].layer(a[1], a[2] - W * p, a[3], a[4]))
            comb.alpha_composite(prods[b[0]].layer(b[1], b[2] + W * (1 - p), b[3], b[4]))
            im.alpha_composite(hblur(comb, blur))
        else:
            q, sc, dx, dy, f = prod_state(i, t)
            im.alpha_composite(prods[q].layer(sc, dx, dy, f))

        # haak: vanaf frame 0 volledig zichtbaar (kleine settle), fade-out aan het eind van het hook-shot
        if t < t_hook_end:
            a = 1 - ease_io((t - (t_hook_end - 0.17)) * FPS / 5)
            im.alpha_composite(fade(hook_img, a), (0, 300 + int(12 * (1 - ease_out(t * FPS / 8)))))
        # titel (+kicker) tot de CTA
        if t_hook_end <= t < t_cta:
            a = min(ease_out((t - t_hook_end) * FPS / 7), 1 - ease_io((t - (t_cta - 0.17)) * FPS / 5))
            det = [sh for sh in shots if sh[2] == 'detail']
            if det and t >= det[0][0]:  # titel wijkt tijdens de detail-zoom, daarna terug
                d0, d1 = det[0][0], det[0][1]
                a = min(a, max(1 - ease_io((t - d0) * FPS / 5), ease_out((t - d1) * FPS / 7)))
            dy = int(30 * (1 - ease_out((t - t_hook_end) * FPS / 7))); y = 300
            if kicker_img is not None:
                im.alpha_composite(fade(kicker_img, a), ((W - kicker_img.width) // 2, y + dy)); y += kicker_img.height + 18
            im.alpha_composite(fade(title_img, a), (0, y + dy))
        # regel (bv. Op = op.) en prijs
        if line_img is not None and t_price + 0.3 <= t < t_cta:
            a = min(ease_out((t - t_price - 0.3) * FPS / 7), 1 - ease_io((t - (t_cta - 0.17)) * FPS / 5))
            im.alpha_composite(fade(line_img, a), (0, 1030))
        if price_img is not None and t >= t_price + 0.15:
            k2 = (t - t_price - 0.15) * FPS / 9
            sc = 1.0 + 0.08 * np.sin(np.pi * min(k2, 1.0)) if k2 < 1 else 1.0
            pimg = price_img if sc == 1.0 else price_img.resize((int(price_img.width * sc), int(price_img.height * sc)), Image.BICUBIC)
            py = 1120 if t < t_cta else int(1120 - 100 * ease_io((t - t_cta) * 2 / (dur - t_cta)))
            im.alpha_composite(fade(pimg, min(1.0, k2 * 1.5)), ((W - pimg.width) // 2, py - (pimg.height - price_img.height) // 2))
        # CTA-balk schuift van onder in
        if t >= t_cta:
            k3 = ease_out((t - t_cta) * FPS / 9); bar_y = int(H - (H - 1150) * k3)
            im.alpha_composite(Image.new('RGBA', (W, H - bar_y), NAVY + (255,)), (0, bar_y))
            if k3 > 0.6:
                a = (k3 - 0.6) / 0.4
                im.alpha_composite(fade(lg, a), ((W - lg.width) // 2, bar_y + 40))
                im.alpha_composite(fade(cta1, a), (0, bar_y + 60 + lg.height))
                im.alpha_composite(fade(cta2, a), (0, bar_y + 120 + lg.height))
        return im.convert('RGB')

    tmp = tempfile.mkdtemp(); wav = os.path.join(tmp, 'a.wav')
    build_audio(style, dur, [('thump', shots[1][0]), ('whoosh', t_price)], wav)
    frame(int((t_price + 0.8) * FPS)).save(os.path.splitext(out)[0] + '.jpg', quality=92)   # cover: product + prijs

    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H),
           '-r', str(FPS), '-i', '-', '-i', wav, '-af', loudnorm_args(wav), '-ar', str(SR),
           '-c:v', 'libx264', '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-preset', 'medium', '-crf', '19',
           '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', out]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fi in range(nfr):
        ff.stdin.write(frame(fi).tobytes())
    ff.stdin.close(); ff.wait()
    if ff.returncode:
        sys.exit('ffmpeg faalde')
    print(out, '%.1fs' % (nfr / FPS), 'muziek=%s' % style, 'haak="%s"' % hook,
          'vrijstaand=%s' % ','.join('ja' if p.free else 'nee' for p in prods))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
