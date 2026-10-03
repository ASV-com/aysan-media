#!/usr/bin/env python3
"""Maakt een korte 9:16-reel (MP4) voor Aysan uit 1-4 productfoto's.
Gebruik: python3 tools/make_reel.py spec.json uitvoer.mp4
spec.json: {"images": ["https://cdn.shopify.com/...jpg" of lokaal pad, max 4],
            "kicker": "OUTLET" (optioneel), "title": "Max 6 woorden",
            "price": "€ 389 excl. btw" (optioneel, exact uit Shopify),
            "line": "Op = op." (optioneel), "cta": "aysantruckparts.com"}
Uitvoer: 1080x1920, 30 fps, H.264 + stille AAC, 8-14 s. Plus cover-JPEG naast de mp4.
Tekst blijft binnen de Reels-veilige zone (y 250-1500).
"""
import json, os, subprocess, sys, urllib.request, io
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30
NAVY = (29, 31, 46); ORANGE = (255, 107, 0); WHITE = (255, 255, 255); GREY = (170, 175, 195)
HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(HERE, '..', 'brand', 'logo_op_navy.png')
INTRO, OUTRO, FADE = 1.6, 2.4, 0.3
MAX_PER_IMG, MAX_TOTAL = 4.4, 13.5  # totaal blijft zo tussen 8 en 14 s bij 1-4 foto's


def font(bold, size):
    for p in ['/usr/share/fonts/truetype/liberation/LiberationSans-%s.ttf' % ('Bold' if bold else 'Regular'),
              '/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf' % ('-Bold' if bold else '')]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def wrap(d, text, f, maxw):
    words = text.split(); lines = []; cur = ''
    for w in words:
        t = (cur + ' ' + w).strip()
        if d.textlength(t, font=f) <= maxw:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def load(src):
    if src.startswith('http'):
        req = urllib.request.Request(src, headers={'User-Agent': 'Mozilla/5.0 aysan-media'})
        data = urllib.request.urlopen(req, timeout=60).read()
        return Image.open(io.BytesIO(data)).convert('RGB')
    return Image.open(src).convert('RGB')


def centered(d, t, f, col, y):
    d.text(((W - d.textlength(t, font=f)) / 2, y), t, font=f, fill=col)


def logo(w):
    lg = Image.open(LOGO).convert('RGBA')
    return lg.resize((w, int(lg.height * w / lg.width)), Image.LANCZOS)


def title_block(d, s, y, size=72):
    """Kicker + titel, geeft nieuwe y terug."""
    if s.get('kicker'):
        f = font(True, 36); t = s['kicker'].upper(); tw = d.textlength(t, font=f)
        d.rounded_rectangle([(W - tw) / 2 - 24, y - 8, (W + tw) / 2 + 24, y + 50], radius=28, fill=ORANGE)
        centered(d, t, f, WHITE, y); y += 92
    f = font(True, size)
    for ln in wrap(d, s.get('title', ''), f, W - 160):
        centered(d, ln, f, WHITE, y); y += int(size * 1.2)
    return y


def intro(s):
    im = Image.new('RGB', (W, H), NAVY); d = ImageDraw.Draw(im)
    lg = logo(640); im.paste(lg, ((W - lg.width) // 2, 420), lg)
    y = title_block(d, s, 420 + lg.height + 90, 80)
    if s.get('line'):
        centered(d, s['line'], font(True, 50), ORANGE, y + 20)
    return im


def product_base(s):
    """Achtergrond + tekst voor productslides; foto wordt per frame ingevoegd."""
    im = Image.new('RGB', (W, H), NAVY); d = ImageDraw.Draw(im)
    lg = logo(360); im.paste(lg, ((W - lg.width) // 2, 270), lg)
    y = title_block(d, dict(s, kicker=None), 270 + lg.height + 40, 58)
    box = (90, y + 20, W - 90, 1280)  # wit paneel voor de foto
    d.rounded_rectangle(box, radius=36, fill=WHITE)
    by = 1310
    if s.get('price'):
        f = font(True, 64); t = s['price']; tw = d.textlength(t, font=f)
        d.rounded_rectangle([(W - tw) / 2 - 36, by - 10, (W + tw) / 2 + 36, by + 82], radius=44, fill=ORANGE)
        centered(d, t, f, WHITE, by + 2); by += 112
    if s.get('line'):
        centered(d, s['line'], font(True, 44), WHITE, by)
    return im, box


def product_frame(base, box, photo, t):
    """t = 0..1 binnen de slide: langzame zoom 1.00 -> 1.07."""
    im = base.copy()
    bx0, by0, bx1, by1 = box; pad = 40
    bw, bh = bx1 - bx0 - 2 * pad, by1 - by0 - 2 * pad
    sc = min(bw / photo.width, bh / photo.height) * (1.0 + 0.07 * t)
    pw, ph = int(photo.width * sc), int(photo.height * sc)
    ph_img = photo.resize((pw, ph), Image.BILINEAR)
    # uitsnede binnen het paneel houden
    cx, cy = (bx0 + bx1) // 2, (by0 + by1) // 2
    left, top = cx - pw // 2, cy - ph // 2
    crop = (max(0, bx0 + pad - left), max(0, by0 + pad - top),
            min(pw, bx1 - pad - left), min(ph, by1 - pad - top))
    im.paste(ph_img.crop(crop), (left + crop[0], top + crop[1]))
    return im


def outro(s):
    im = Image.new('RGB', (W, H), NAVY); d = ImageDraw.Draw(im)
    lg = logo(640); im.paste(lg, ((W - lg.width) // 2, 460), lg); y = 460 + lg.height + 110
    centered(d, 'Voor 17:00 besteld,', font(True, 60), WHITE, y); y += 76
    centered(d, 'vandaag verzonden.', font(True, 60), WHITE, y); y += 130
    centered(d, s.get('cta', 'aysantruckparts.com'), font(True, 56), ORANGE, y); y += 90
    centered(d, '085 - 401 10 32', font(False, 44), GREY, y)
    return im


def main(spec, out):
    s = json.load(open(spec))
    imgs = s.get('images') or []
    if not 1 <= len(imgs) <= 4:
        sys.exit('images: 1 tot 4 foto\'s nodig')
    if len((s.get('title') or '').split()) > 6:
        print('LET OP: titel heeft meer dan 6 woorden')
    photos = [load(u) for u in imgs]
    base, box = product_base(s)
    per_img = min(MAX_PER_IMG, (MAX_TOTAL - INTRO - OUTRO) / len(photos))
    scenes = [('static', intro(s), INTRO)] + [('photo', p, per_img) for p in photos] + [('static', outro(s), OUTRO)]

    cover = product_frame(base, box, photos[0], 0.0)
    cover.save(os.path.splitext(out)[0] + '.jpg', quality=92)

    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}',
           '-r', str(FPS), '-i', '-', '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',
           '-shortest', '-c:v', 'libx264', '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-preset', 'medium',
           '-crf', '20', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', out]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    prev_last = None; total = 0
    for kind, src, dur in scenes:
        n = int(dur * FPS)
        for i in range(n):
            fr = src if kind == 'static' else product_frame(base, box, src, i / max(1, n - 1))
            nf = int(FADE * FPS)
            if prev_last is not None and i < nf:
                fr = Image.blend(prev_last, fr, (i + 1) / (nf + 1))
            ff.stdin.write(fr.tobytes()); total += 1
            last = fr
        prev_last = last
    ff.stdin.close(); ff.wait()
    if ff.returncode:
        sys.exit('ffmpeg faalde')
    print(out, f'{total / FPS:.1f}s', W, H)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
