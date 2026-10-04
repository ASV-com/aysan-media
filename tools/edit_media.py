#!/usr/bin/env python3
"""Bewerkt ruwe video/foto tot een afgewerkt Aysan-bestand (alleen ffmpeg nodig).

  python3 tools/edit_media.py clip  spec.json uit.mp4     # reel 9:16, 1080x1920
  python3 tools/edit_media.py photo spec.json uit.jpg     # post 4:5 of story 9:16
  python3 tools/edit_media.py sheet bestand.mp4 sheet.jpg # contactsheet om te beoordelen
  python3 tools/edit_media.py info  bestand               # duur, afmeting, audio
  python3 tools/edit_media.py scenes bestand.mp4 [0.3]    # scenewissels -> shots (JSON), basis voor cuts
  python3 tools/edit_media.py stabilize ruw.mp4 uit.mp4   # trillend beeld stabiliseren (vidstab, 2 passes)
  python3 tools/edit_media.py denoise ruw.mp4 uit.mp4     # ruis uit geluid (wind, magazijn); beeld ongewijzigd
  python3 tools/edit_media.py audio ruw.mp4 uit.opus      # compact spraakspoor (16 kHz mono) voor transcriptie
  python3 tools/edit_media.py anonymize ruw.mp4 uit.mp4 [spec.json]  # gezichten auto + kentekens/vlakken vervagen (OpenCV)
  python3 tools/edit_media.py reframe ruw.mp4 uit.mp4     # liggend -> 9:16 die het onderwerp volgt (OpenCV)
  python3 tools/edit_media.py check eind.mp4|eind.jpg [ondertitels.srt]
        # technische keuring van het EINDBESTAND; exit 1 bij AFGEKEURD (dan niet naar V/posts)
  python3 tools/edit_media.py transcribe ruw.mp4|.opus uit.srt [nl|tr]
        # spraak -> ondertitels (.srt, max 32 tekens per regel). Lokaal alleen als faster-whisper +
        # model beschikbaar zijn; anders via de Action 'transcribe' in de PRIVE-repo ASV-com/ASV.

clip-spec (alle velden behalve src optioneel):
  {"src": "pad/naar/ruw.mp4",
   "cuts": [[2.0, 8.5], [12, 16]],      # stukken die blijven, in volgorde (anders start/end)
   "focus_x": 0.5,                       # 0..1: welk deel van een liggend beeld in beeld blijft
   "grade": {"brightness": 0.02, "contrast": 1.06, "saturation": 1.1},
   "title": "Max 6 woorden",             # eerste 3 s, binnen de veilige zone
   "subs": "ondertitels.srt",            # ingebrand, onder in de veilige zone
   "logo": true,                          # wit logo rechtsboven (veilige zone)
   "endcard": {"line": "Op = op.", "cta": "aysantruckparts.com"},
   "audio": "keep"|"mute",                # keep: loudnorm -16 LUFS; mute: stil spoor
   "captions": "x.words.json",           # woord-voor-woord ondertitels (uit transcribe; brontijden, cuts worden verrekend)
   "music": {"track": "muziek.mp3", "volume": 0.22, "start": 0},  # rechtenvrij; duikt automatisch onder spraak
   "insert": {"src": "product.jpg", "start": 1.0, "end": 4.0}}    # productfoto als kaart in beeld
  cuts mag per stuk opties hebben: [2.0, 5.0, {"zoom": 1.15}] (langzaam inzoomen; "dir": "out" = uitzoomen)
photo-spec: {"src": "pad.jpg", "format": "post"|"story", "focus_x": 0.5, "focus_y": 0.5,
             "grade": {...}, "title": "...", "logo": true}
Veilige zone Reels/Stories: tekst en logo tussen y 250 en 1500 (Instagram-interface eroverheen).
Uitvoer clip: H.264 + AAC 44,1 kHz, 30 fps, yuv420p; waarschuwt als de lengte buiten 8-14 s valt.
"""
import json, os, shutil, subprocess, sys, tempfile

W, H, FPS = 1080, 1920, 30
HERE = os.path.dirname(os.path.abspath(__file__))
LOGO_WIT = os.path.join(HERE, '..', 'brand', 'logo_op_wit.png')
FONT_B = next((p for p in ['/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
                           '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'] if os.path.exists(p)), None)
NAVY, ORANGE = '0x1D1F2E', '0xFF6B00'


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit('ffmpeg faalde:\n' + ' '.join(cmd) + '\n' + r.stderr[-1500:])
    return r.stdout


def probe(path):
    out = run(['ffprobe', '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', path])
    j = json.loads(out)
    v = next((s for s in j['streams'] if s['codec_type'] == 'video'), None)
    if not v:
        sys.exit('geen videospoor in ' + path)
    rot = 0
    for sd in v.get('side_data_list', []):
        rot = int(sd.get('rotation', rot))
    w, h = int(v['width']), int(v['height'])
    if abs(rot) in (90, 270):
        w, h = h, w
    return {'w': w, 'h': h, 'dur': float(j['format']['duration']),
            'audio': any(s['codec_type'] == 'audio' for s in j['streams'])}


def even(x):
    return int(x) // 2 * 2


def crop_expr(w, h, tw, th, fx, fy=0.5):
    """crop=... dat de verhouding tw:th uit w x h haalt; focus fx/fy in 0..1."""
    if w * th > h * tw:           # bron te breed -> breedte afsnijden
        cw, ch = even(h * tw / th), h
    else:                         # bron te hoog -> hoogte afsnijden
        cw, ch = w, even(w * th / tw)
    x, y = even((w - cw) * fx), even((h - ch) * fy)
    return 'crop=%d:%d:%d:%d,scale=%d:%d:flags=lanczos,setsar=1' % (cw, ch, x, y, tw, th)


def grade_f(g):
    g = g or {}
    return 'eq=brightness=%s:contrast=%s:saturation=%s' % (
        g.get('brightness', 0.0), g.get('contrast', 1.04), g.get('saturation', 1.08))


def textfile(tmp, name, text):
    p = os.path.join(tmp, name)
    open(p, 'w', encoding='utf-8').write(text)
    return p


def wrap_text(text, n):
    words, lines, cur = text.split(), [], ''
    for w in words:
        if len((cur + ' ' + w).strip()) <= n:
            cur = (cur + ' ' + w).strip()
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return '\n'.join(lines)


def drawtext(tf, size, y, enable=None, color='white', box=True):
    f = ("drawtext=fontfile=%s:textfile=%s:fontsize=%d:fontcolor=%s:x=(w-text_w)/2:y=%s:line_spacing=12"
         % (FONT_B, tf, size, color, y))
    if box:
        f += ":box=1:boxcolor=%s@0.78:boxborderw=28" % NAVY
    if enable:
        f += ":enable='%s'" % enable
    return f


def cut_list(s, dur):
    """cuts -> [(a, b, opties)]; derde element optioneel, bv. {"zoom": 1.15}."""
    raw = s.get('cuts') or [[s.get('start', 0), s.get('end', dur)]]
    return [(float(c[0]), float(c[1]), (c[2] if len(c) > 2 else {}) or {}) for c in raw]


def remap_time(t, cuts):
    """brontijd -> tijd in de montage (None als het stuk eruit geknipt is)."""
    off = 0.0
    for a, b, _ in cuts:
        if a <= t < b:
            return off + t - a
        off += b - a
    return None


def ass_color(hexrgb):
    r, g, b = hexrgb[0:2], hexrgb[2:4], hexrgb[4:6]
    return '&H00%s%s%s&' % (b, g, r)


def captions_ass(words_json, cuts, out_path):
    """Woord-voor-woord ondertitels: hele regel wit, het gesproken woord oranje en iets groter."""
    words = [(float(w[0]), float(w[1]), str(w[2]).strip()) for w in json.load(open(words_json, encoding='utf-8'))]
    mapped = []
    for a, b, t in words:
        ma, mb = remap_time(a, cuts), remap_time(max(a, b - 0.01), cuts)
        if ma is None:
            continue
        mapped.append((ma, mb if mb is not None and mb > ma else ma + 0.25, t))
    head = ('[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 2\n\n'
            '[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, '
            'Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, '
            'Alignment, MarginL, MarginR, MarginV, Encoding\n'
            'Style: Cap,Liberation Sans,64,&H00FFFFFF&,&H00FFFFFF&,%s,&H64000000&,1,0,0,0,100,100,0,0,1,5,2,2,60,60,440,1\n\n'
            '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
            % (W, H, ass_color(NAVY[2:])))

    def ts(t):
        cs = int(round(t * 100))
        return '%d:%02d:%02d.%02d' % (cs // 360000, cs // 6000 % 60, cs // 100 % 60, cs % 100)

    lines = []
    for cue in group_words(mapped):
        for i, (a, b, _) in enumerate(cue):
            end = cue[i + 1][0] if i + 1 < len(cue) else b + 0.15
            txt = ' '.join(('{\\c%s\\fscx112\\fscy112}%s{\\r}' % (ass_color(ORANGE[2:]), w[2])) if j == i else w[2]
                           for j, w in enumerate(cue))
            lines.append('Dialogue: 0,%s,%s,Cap,,0,0,0,,%s' % (ts(a), ts(end), txt))
    open(out_path, 'w', encoding='utf-8').write(head + '\n'.join(lines) + '\n')
    return len(mapped)


def cmd_clip(spec_path, out):
    s = json.load(open(spec_path))
    src = s['src']
    info = probe(src)
    cuts = cut_list(s, info['dur'])
    mute = s.get('audio', 'keep') == 'mute' or not info['audio']
    tmp = tempfile.mkdtemp()
    cf = crop_expr(info['w'], info['h'], W, H, s.get('focus_x', 0.5), s.get('focus_y', 0.5))
    parts, vl, al = [], [], []
    for i, (a, b, opt) in enumerate(cuts):
        zf = ''
        if opt.get('zoom'):
            # langzame push-in (of uitzoomen met "dir": "out") over het hele shot
            n = max(int(round((b - a) * FPS)), 1)
            z0, z1 = (1.0, float(opt['zoom'])) if opt.get('dir', 'in') == 'in' else (float(opt['zoom']), 1.0)
            zf = (",zoompan=z='%s+(%s)*on/%d':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=%dx%d:fps=%d"
                  % (z0, z1 - z0, n, W, H, FPS))
        parts.append('[0:v]trim=start=%s:end=%s,setpts=PTS-STARTPTS,%s,fps=%d%s,setsar=1[v%d]' % (a, b, cf, FPS, zf, i))
        vl.append('[v%d]' % i)
        if not mute:
            parts.append('[0:a]atrim=start=%s:end=%s,asetpts=PTS-STARTPTS,aresample=44100[a%d]' % (a, b, i))
            al.append('[a%d]' % i)
    n = len(cuts)
    if mute:
        parts.append('%sconcat=n=%d:v=1:a=0[vc]' % (''.join(vl), n))
    else:
        parts.append(''.join(x for pair in zip(vl, al) for x in pair) + 'concat=n=%d:v=1:a=1[vc][ac]' % n)
    total = sum(b - a for a, b, _ in cuts)
    chain = [grade_f(s.get('grade'))]
    if s.get('title'):
        tf = textfile(tmp, 'title.txt', wrap_text(s['title'].upper(), 18))
        chain.append(drawtext(tf, 74, '430', enable='between(t,0.4,3.4)'))
    cwd = None
    if s.get('captions'):
        nw = captions_ass(s['captions'], cuts, os.path.join(tmp, 'cap.ass'))
        print('ondertitels: %d woorden (woord voor woord)' % nw)
        chain.append('subtitles=cap.ass')
        cwd = tmp
    elif s.get('subs'):
        shutil.copy(s['subs'], os.path.join(tmp, 'subs.srt'))
        chain.append("subtitles=subs.srt:force_style='FontName=Liberation Sans,FontSize=11,Bold=1,"
                     "PrimaryColour=&HFFFFFF&,OutlineColour=&H2E1F1D&,BorderStyle=1,Outline=1.6,"
                     "Alignment=2,MarginV=70'")
        cwd = tmp
    parts.append('[vc]%s[vg]' % ','.join(chain))
    inputs = ['-i', os.path.abspath(src)]
    last = '[vg]'
    if s.get('logo', True):
        idx = len(inputs) // 2
        inputs += ['-i', os.path.abspath(LOGO_WIT)]
        parts.append('[%d:v]scale=190:-1[lg]' % idx)
        parts.append('%s[lg]overlay=W-w-60:260[vo]' % last)
        last = '[vo]'
    ins = s.get('insert')
    if ins:
        # productfoto als kaart in beeld (bv. Shopify-foto), met witte rand en korte fade
        idx = len(inputs) // 2
        inputs += ['-loop', '1', '-t', '%.3f' % total, '-i', os.path.abspath(ins['src'])]
        st, en = float(ins.get('start', 0.8)), float(ins.get('end', min(total, 3.8)))
        parts.append("[%d:v]scale=%d:-1,pad=iw+24:ih+24:12:12:white,format=rgba,"
                     "fade=in:st=%s:d=0.25:alpha=1,fade=out:st=%s:d=0.25:alpha=1[ins]"
                     % (idx, int(ins.get('width', 600)), st, max(en - 0.25, st)))
        parts.append("%s[ins]overlay=(W-w)/2:%s:enable='between(t,%s,%s)'[vi]" % (last, ins.get('y', 600), st, en))
        last = '[vi]'
    parts.append('%sformat=yuv420p[vf]' % last)
    main = os.path.join(tmp, 'main.mp4')
    if mute:
        cmd = ['ffmpeg', '-y', '-loglevel', 'error'] + inputs + ['-filter_complex', ';'.join(parts), '-map', '[vf]',
               '-f', 'lavfi', '-t', '%.3f' % total, '-i', 'anullsrc=r=44100:cl=stereo']
        cmd += ['-map', '%d:a' % (cmd.count('-i') - 1)]
    else:
        cmd = ['ffmpeg', '-y', '-loglevel', 'error'] + inputs + [
            '-filter_complex', ';'.join(parts + ['[ac]loudnorm=I=-16:TP=-1.5:LRA=11,aformat=channel_layouts=stereo[af]']),
            '-map', '[vf]', '-map', '[af]']
    cmd += ['-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-r', str(FPS), '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '160k', '-ar', '44100', '-ac', '2', '-shortest', '-movflags', '+faststart', main]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if r.returncode:
        sys.exit('ffmpeg faalde:\n' + r.stderr[-1500:])
    final, dur = main, total
    ec = s.get('endcard')
    if ec:
        end = os.path.join(tmp, 'end.mp4')
        tf1 = textfile(tmp, 'e1.txt', wrap_text(ec.get('line', ''), 20)) if ec.get('line') else None
        tf2 = textfile(tmp, 'e2.txt', ec.get('cta', 'aysantruckparts.com'))
        vf = []
        if tf1:
            vf.append(drawtext(tf1, 84, '(h/2)-260', box=False))
        vf.append(drawtext(tf2, 58, '(h/2)+170', color=ORANGE, box=False))
        fc = ('color=c=%s:s=%dx%d:d=2.4:r=%d[bg];[1:v]scale=420:-1[lg];[bg][lg]overlay=(W-w)/2:(H/2)-520[o];[o]%s,format=yuv420p[v]'
              % (NAVY, W, H, FPS, ','.join(vf)))
        run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo', '-i', os.path.abspath(LOGO_WIT),
             '-filter_complex', fc, '-map', '[v]', '-map', '0:a', '-t', '2.4', '-c:v', 'libx264', '-crf', '18', '-r', str(FPS),
             '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '44100', '-ac', '2', end])
        final = os.path.join(tmp, 'all.mp4')
        run(['ffmpeg', '-y', '-loglevel', 'error', '-i', main, '-i', end, '-filter_complex',
             '[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]', '-map', '[v]', '-map', '[a]',
             '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '44100',
             '-movflags', '+faststart', final])
        dur += 2.4
    mu = s.get('music')
    if mu:
        # muziek onder de hele reel (ook eindkaart); bij spraak automatisch zachter (ducking)
        mixed = os.path.join(tmp, 'mix.mp4')
        vol = float(mu.get('volume', 0.22))
        fo = max(dur - 1.2, 0)
        mus = ('[1:a]atrim=start=%s,asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,'
               'volume=%s,afade=t=in:d=0.4,afade=t=out:st=%.2f:d=1.2,atrim=0:%.3f[m]' % (float(mu.get('start', 0)), vol, fo, dur))
        if mute:
            fc = mus + ';[m]loudnorm=I=-16:TP=-1.5:LRA=11[a]'
        else:
            fc = (mus + ';[0:a]asplit=2[sp][sc];[m][sc]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400[md];'
                  '[sp][md]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[a]')
        run(['ffmpeg', '-y', '-loglevel', 'error', '-i', final, '-stream_loop', '-1', '-i', os.path.abspath(mu['track']),
             '-filter_complex', fc, '-map', '0:v', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k',
             '-ar', '44100', '-ac', '2', '-t', '%.3f' % dur, '-movflags', '+faststart', mixed])
        final = mixed
    final = level_final(final, tmp)
    shutil.copy(final, out)
    shutil.rmtree(tmp, ignore_errors=True)
    if not 8 <= dur <= 14:
        print('LET OP: lengte %.1f s valt buiten 8-14 s (Trial Reel).' % dur)
    print('klaar: %s (%.1f s, 1080x1920)' % (out, dur))


def level_final(path, tmp):
    """Meet de luidheid van het eindbestand en corrigeert exact naar -16 LUFS (true peak <= -1,5 dB).
    Eén-pass loudnorm zit bij korte clips er soms 2-3 LU naast; dit is de nauwkeurige tweede pass."""
    import re
    r = subprocess.run(['ffmpeg', '-hide_banner', '-i', path, '-af', 'loudnorm=print_format=json', '-f', 'null', '-'],
                       capture_output=True, text=True)
    m = re.search(r'"input_i"\s*:\s*"(-?[0-9.]+)"', r.stderr)
    if not m or float(m.group(1)) < -60:
        return path  # stil spoor: niets doen
    gain = -16.0 - float(m.group(1))
    if abs(gain) < 0.3:
        return path
    outp = os.path.join(tmp, 'level.mp4')
    run(['ffmpeg', '-y', '-loglevel', 'error', '-i', path, '-af',
         'volume=%.2fdB,alimiter=limit=0.84:attack=5:release=50:level=disabled' % gain, '-c:v', 'copy',
         '-c:a', 'aac', '-b:a', '160k', '-ar', '44100', '-ac', '2', '-movflags', '+faststart', outp])
    return outp


def need_cv2():
    try:
        import cv2
        import numpy
        return cv2, numpy
    except ImportError:
        sys.exit('OpenCV ontbreekt: pip install --break-system-packages "opencv-python-headless<5" numpy')


def frame_writer(src, out, w, h, fps):
    """ffmpeg-pijp: ruwe frames erin, H.264 + origineel geluid eruit."""
    return subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24',
                             '-s', '%dx%d' % (w, h), '-r', '%.3f' % fps, '-i', '-', '-i', src, '-map', '0:v',
                             '-map', '1:a?', '-c:v', 'libx264', '-preset', 'medium', '-crf', '17', '-pix_fmt', 'yuv420p',
                             '-c:a', 'copy', '-shortest', '-movflags', '+faststart', out], stdin=subprocess.PIPE)


def pixelate(cv2, img, x, y, w, h, pad=0.15):
    H_, W_ = img.shape[:2]
    px, py = int(w * pad), int(h * pad)
    x0, y0, x1, y1 = max(x - px, 0), max(y - py, 0), min(x + w + px, W_), min(y + h + py, H_)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return
    roi = img[y0:y1, x0:x1]
    blk = max(min(x1 - x0, y1 - y0) // 4, 8)  # grote blokken: tekst/gezicht niet te reconstrueren
    sm = cv2.resize(roi, (max((x1 - x0) // blk, 1), max((y1 - y0) // blk, 1)), interpolation=cv2.INTER_AREA)
    img[y0:y1, x0:x1] = cv2.GaussianBlur(cv2.resize(sm, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST), (0, 0), blk / 3)


def cmd_anonymize(src, out, spec_path=None):
    """Vervaagt gezichten (automatisch) en vaste/meebewegende vlakken zoals kentekens.
    spec (optioneel): {"faces": true, "regions": [{"start": 1.0, "end": 4.0, "box": [x, y, w, h], "track": true}]}
    box in fracties 0..1 van het beeld op tijdstip start; track = meebewegen (sjabloon-matching);
    of "box_end": [x, y, w, h] = handmatig lineair van box naar box_end. Altijd controleren met sheet."""
    cv2, np = need_cv2()
    s = json.load(open(spec_path)) if spec_path else {}
    faces_on = s.get('faces', True)
    regions = s.get('regions', [])
    cap = cv2.VideoCapture(src)
    fps = cap.get(cv2.CAP_PROP_FPS) or FPS
    ok, fr = cap.read()
    if not ok:
        sys.exit('kan video niet lezen: ' + src)
    h, w = fr.shape[:2]
    casc = [cv2.CascadeClassifier(cv2.data.haarcascades + n)
            for n in ('haarcascade_frontalface_default.xml', 'haarcascade_profileface.xml')]
    wr = frame_writer(src, out, w, h, fps)
    held, nfaces, idx = [], 0, 0
    trackers = {}
    while ok:
        t = idx / fps
        if faces_on and idx % 2 == 0:
            sc = 480.0 / max(w, h)
            g = cv2.equalizeHist(cv2.cvtColor(cv2.resize(fr, None, fx=sc, fy=sc), cv2.COLOR_BGR2GRAY))
            found = []
            for c in casc:
                for (x, y, ww, hh) in c.detectMultiScale(g, 1.1, 5, minSize=(18, 18)):
                    found.append([int(x / sc), int(y / sc), int(ww / sc), int(hh / sc), 8])
                for (x, y, ww, hh) in c.detectMultiScale(cv2.flip(g, 1), 1.1, 5, minSize=(18, 18)):
                    found.append([int((g.shape[1] - x - ww) / sc), int(y / sc), int(ww / sc), int(hh / sc), 8])
            nfaces += len(found)
            held = [b for b in held if b[4] > 0] + found
        for b in held:
            pixelate(cv2, fr, b[0], b[1], b[2], b[3], pad=0.3)
            b[4] -= 1
        for k, r in enumerate(regions):
            if not (r['start'] <= t <= r['end']):
                continue
            bx = r['box']
            box = (int(bx[0] * w), int(bx[1] * h), int(bx[2] * w), int(bx[3] * h))
            if r.get('box_end'):
                # handmatig: lineair van box (op start) naar box_end (op end)
                e = r['box_end']
                f = (t - r['start']) / max(r['end'] - r['start'], 0.001)
                box = tuple(int(((1 - f) * bx[i] + f * e[i]) * (w if i % 2 == 0 else h)) for i in range(4))
            elif r.get('track'):
                # sjabloon-matching in een zoekvenster rond de vorige plek (robuust voor kentekens/borden)
                gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
                if k not in trackers:
                    x, y, ww, hh = box
                    trackers[k] = [gray[y:y + hh, x:x + ww].copy(), box]
                else:
                    tpl, (x, y, ww, hh) = trackers[k]
                    mx, my = max(ww, 40), max(hh, 40)
                    x0, y0 = max(x - mx, 0), max(y - my, 0)
                    win = gray[y0:min(y + hh + my, h), x0:min(x + ww + mx, w)]
                    if win.shape[0] >= hh and win.shape[1] >= ww:
                        res = cv2.matchTemplate(win, tpl, cv2.TM_CCOEFF_NORMED)
                        _, score, _, loc = cv2.minMaxLoc(res)
                        if score > 0.4:
                            nx, ny = x0 + loc[0], y0 + loc[1]
                            trackers[k][1] = (nx, ny, ww, hh)
                            if score > 0.7:  # sjabloon langzaam bijwerken (licht/hoek verandert)
                                cur = gray[ny:ny + hh, nx:nx + ww]
                                if cur.shape == tpl.shape:
                                    trackers[k][0] = cv2.addWeighted(tpl, 0.8, cur, 0.2, 0)
                box = trackers[k][1]
            pixelate(cv2, fr, *box)
        wr.stdin.write(fr.tobytes())
        ok, fr = cap.read()
        idx += 1
    wr.stdin.close()
    wr.wait()
    print('klaar: %s (%d frames, gezichtsdetecties %d, vlakken %d) - CONTROLEER met sheet: '
          'automatische detectie mist soms een gezicht.' % (out, idx, nfaces, len(regions)))


def cmd_reframe(src, out):
    """Slim 9:16 uitsnijden dat het onderwerp volgt (gezicht > beweging > beeldmidden), rustig afgevlakt."""
    cv2, np = need_cv2()
    cap = cv2.VideoCapture(src)
    fps = cap.get(cv2.CAP_PROP_FPS) or FPS
    frames_x, prev, ok = [], None, True
    fc = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    ok, fr = cap.read()
    if not ok:
        sys.exit('kan video niet lezen: ' + src)
    h, w = fr.shape[:2]
    cw = even(h * 9 / 16)
    if cw >= w:
        sys.exit('bron is al staand of smaller dan 9:16; reframe niet nodig')
    while ok:
        sc = 320.0 / w
        g = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(fr, None, fx=sc, fy=sc), cv2.COLOR_BGR2GRAY), (5, 5), 0)
        cx = None
        fs = fc.detectMultiScale(g, 1.1, 5, minSize=(14, 14))
        if len(fs):
            x, y, ww, hh = max(fs, key=lambda f: f[2] * f[3])
            cx = (x + ww / 2) / sc
        elif prev is not None:
            # grootste bewegende vlek = onderwerp (ruis en kleine spikkels vallen weg)
            d = cv2.threshold(cv2.absdiff(g, prev), 10, 255, cv2.THRESH_BINARY)[1]
            d = cv2.dilate(cv2.morphologyEx(d, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), np.ones((9, 9), np.uint8))
            cs, _ = cv2.findContours(d, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if cs:
                c = max(cs, key=cv2.contourArea)
                if cv2.contourArea(c) > 60:
                    x, y, ww, hh = cv2.boundingRect(c)
                    cx = (x + ww / 2) / sc
        frames_x.append(cx)
        prev = g
        ok, fr = cap.read()
    # gaten opvullen en afvlakken (camera-operator-gevoel: geen schokken)
    first = next((v for v in frames_x if v is not None), w / 2)
    last = first
    filled = []
    for v in frames_x:
        last = v if v is not None else last
        filled.append(last)
    sm, cur = [], filled[0]
    for v in filled:
        if abs(v - cur) > cw * 0.08:
            cur += (v - cur) * 0.06
        sm.append(cur)
    xs = [int(min(max(v - cw / 2, 0), w - cw)) for v in sm]
    cap = cv2.VideoCapture(src)
    wr = frame_writer(src, out, W, H, fps)
    for x in xs:
        ok, fr = cap.read()
        if not ok:
            break
        wr.stdin.write(cv2.resize(fr[:, x:x + cw], (W, H), interpolation=cv2.INTER_LANCZOS4).tobytes())
    wr.stdin.close()
    wr.wait()
    span = (min(xs) / w, (max(xs) + cw) / w)
    print('klaar: %s (1080x1920, uitsnede beweegt tussen %.0f%% en %.0f%% van de breedte)' % (out, span[0] * 100, span[1] * 100))


def cmd_photo(spec_path, out):
    s = json.load(open(spec_path))
    info = probe(s['src'])
    tw, th = (W, 1350) if s.get('format', 'post') == 'post' else (W, H)
    tmp = tempfile.mkdtemp()
    chain = [crop_expr(info['w'], info['h'], tw, th, s.get('focus_x', 0.5), s.get('focus_y', 0.5)), grade_f(s.get('grade')),
             'unsharp=5:5:0.6']
    if s.get('title'):
        tf = textfile(tmp, 't.txt', wrap_text(s['title'].upper(), 20))
        y = '300' if th == H else '120'
        chain.append(drawtext(tf, 66, y))
    parts = '[0:v]%s[v]' % ','.join(chain)
    inputs = ['-i', os.path.abspath(s['src'])]
    last = '[v]'
    if s.get('logo', True):
        inputs += ['-i', os.path.abspath(LOGO_WIT)]
        parts += ';[1:v]scale=190:-1[lg];[v][lg]overlay=W-w-50:%s[o]' % ('260' if th == H else str(th - 140))
        last = '[o]'
    run(['ffmpeg', '-y', '-loglevel', 'error'] + inputs + ['-filter_complex', parts, '-map', last, '-frames:v', '1',
                                                           '-q:v', '2', out])
    shutil.rmtree(tmp, ignore_errors=True)
    print('klaar: %s (%dx%d)' % (out, tw, th))


def cmd_sheet(src, out, n=12, cols=4):
    info = probe(src)
    rows = -(-n // cols)
    run(['ffmpeg', '-y', '-loglevel', 'error', '-i', src, '-vf',
         'fps=%f,scale=270:-1,tile=%dx%d:padding=6:color=black' % (n / max(info['dur'], 0.1) * 0.999, cols, rows),
         '-frames:v', '1', '-q:v', '3', out])
    print('klaar: %s (%d frames over %.1f s)' % (out, n, info['dur']))


def cmd_scenes(src, thr=0.3):
    """Scenewissels via ffmpeg-scorewaarde; geeft shots met begin/eind/lengte."""
    info = probe(src)
    r = subprocess.run(['ffmpeg', '-hide_banner', '-i', src, '-vf', "select='gt(scene,%s)',showinfo" % thr,
                        '-an', '-f', 'null', '-'], capture_output=True, text=True)
    import re
    cuts = sorted({round(float(m), 2) for m in re.findall(r'pts_time:([0-9.]+)', r.stderr)})
    edges = [0.0] + [c for c in cuts if 0.3 < c < info['dur'] - 0.3] + [round(info['dur'], 2)]
    shots = [{'start': a, 'end': b, 'len': round(b - a, 2)} for a, b in zip(edges, edges[1:]) if b - a >= 0.2]
    print(json.dumps({'dur': round(info['dur'], 2), 'drempel': thr, 'shots': shots}, indent=1))


def has_filter(name):
    r = subprocess.run(['ffmpeg', '-hide_banner', '-filters'], capture_output=True, text=True)
    return (' %s ' % name) in r.stdout


def cmd_stabilize(src, out):
    """2-pass vidstab (lichte zoom tegen zwarte randen); valt terug op deshake."""
    tmp = tempfile.mkdtemp()
    trf = os.path.join(tmp, 't.trf')
    enc = ['-c:v', 'libx264', '-preset', 'medium', '-crf', '17', '-pix_fmt', 'yuv420p', '-c:a', 'copy',
           '-movflags', '+faststart']
    if has_filter('vidstabdetect'):
        run(['ffmpeg', '-y', '-loglevel', 'error', '-i', src, '-vf',
             'vidstabdetect=shakiness=6:accuracy=15:result=%s' % trf, '-f', 'null', '-'])
        vf = 'vidstabtransform=input=%s:smoothing=15:optzoom=1:zoomspeed=0.25:interpol=bicubic,unsharp=5:5:0.5' % trf
        how = 'vidstab'
    else:
        vf, how = 'deshake', 'deshake'
    run(['ffmpeg', '-y', '-loglevel', 'error', '-i', src, '-vf', vf] + enc + [out])
    shutil.rmtree(tmp, ignore_errors=True)
    print('klaar: %s (gestabiliseerd met %s)' % (out, how))


def cmd_denoise(src, out):
    """Spraakvriendelijke ruisonderdrukking; beeld wordt alleen gekopieerd."""
    if not probe(src)['audio']:
        sys.exit('geen geluidsspoor in ' + src)
    af = 'highpass=f=80,lowpass=f=12000,afftdn=nr=14:nf=-30:tn=1,loudnorm=I=-16:TP=-1.5:LRA=11'
    run(['ffmpeg', '-y', '-loglevel', 'error', '-i', src, '-af', af, '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k',
         '-ar', '44100', '-movflags', '+faststart', out])
    print('klaar: %s (ruis verminderd, -16 LUFS)' % out)


def cmd_audio(src, out):
    """Alleen spraak, klein bestand (ca. 3 kB/s) voor de transcriptie-Action."""
    run(['ffmpeg', '-y', '-loglevel', 'error', '-i', src, '-vn', '-ac', '1', '-ar', '16000',
         '-af', 'highpass=f=80,afftdn=nr=10', '-c:a', 'libopus', '-b:a', '24k', out])
    print('klaar: %s' % out)


def srt_time(t):
    ms = int(round(t * 1000))
    return '%02d:%02d:%02d,%03d' % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def group_words(words, maxlen=32, maxdur=3.2):
    """words: [(start, end, tekst)] -> cues (lijsten woorden), 1 regel, max maxlen tekens."""
    cues, cur = [], []
    for w in words:
        txt = ' '.join(x[2].strip() for x in cur + [w])
        if cur and (len(txt) > maxlen or w[1] - cur[0][0] > maxdur or cur[-1][2].rstrip().endswith(('.', '?', '!'))
                    or (cur[-1][2].rstrip().endswith((',', ';', ':')) and len(' '.join(x[2].strip() for x in cur)) >= 14)):
            cues.append(cur)
            cur = []
        cur.append(w)
    if cur:
        cues.append(cur)
    return cues


def words_to_srt(words, maxlen=32, maxdur=3.2):
    """words: [(start, end, tekst)] -> srt-tekst, 1 regel per cue, max maxlen tekens."""
    out = []
    for i, c in enumerate(group_words(words, maxlen, maxdur), 1):
        out.append('%d\n%s --> %s\n%s\n' % (i, srt_time(c[0][0]), srt_time(c[-1][1]),
                                              ' '.join(x[2].strip() for x in c)))
    return '\n'.join(out)


def cmd_transcribe(src, out, lang='nl', model=None):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit('faster-whisper niet geinstalleerd. In de sandbox: gebruik de Action "transcribe" in ASV-com/ASV '
                 '(zie skill media-studio).')
    model = model or os.environ.get('WHISPER_MODEL', 'small')
    try:
        m = WhisperModel(model, device='cpu', compute_type='int8')
    except Exception as e:
        sys.exit('Whisper-model "%s" niet te laden (%s). In de sandbox: gebruik de Action "transcribe".' % (model, e))
    # vaktermen sturen de herkenning (merken, onderdelen) zonder ze af te dwingen
    hint = {'nl': 'Aysan Truckparts. DAF, MAN, Scania, Volvo, Mercedes-Benz, Iveco, Renault. Spiegel, bumper, '
                  'spatbord, NOx-sensor, OEM-nummer, excl. btw, Zoetermeer.',
            'tr': 'Aysan Truckparts. DAF, MAN, Scania, Volvo, Mercedes-Benz, Iveco, Renault. Ayna, tampon, '
                  'çamurluk, NOx sensörü, OEM numarası.'}.get(lang)
    segs, _ = m.transcribe(src, language=lang, word_timestamps=True, vad_filter=True, beam_size=5,
                           initial_prompt=hint)
    words = [(w.start, w.end, w.word) for sg in segs for w in (sg.words or [])]
    if not words:
        sys.exit('geen spraak gevonden in ' + src)
    open(out, 'w', encoding='utf-8').write(words_to_srt(words))
    # woorden met tijden (brontijd) voor woord-voor-woord ondertitels: clip-spec "captions"
    json.dump([[round(a, 2), round(b, 2), t.strip()] for a, b, t in words],
              open(os.path.splitext(out)[0] + '.words.json', 'w', encoding='utf-8'), ensure_ascii=False)
    print('klaar: %s (%d woorden, taal %s, model %s)' % (out, len(words), lang, model))


ENDCARD = 2.4  # statische eindkaart: niet als 'bevroren' rekenen


def cmd_check(path, srt=None):
    """Harde eisen voor een eindbestand. Print per eis OK/FOUT; exit 1 bij een FOUT."""
    import re
    res = []

    def eis(ok, naam, detail=''):
        res.append((ok, naam, detail))

    if path.lower().endswith(('.jpg', '.jpeg', '.png')):
        j = json.loads(run(['ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams', path]))
        st = j['streams'][0]
        w, h = int(st['width']), int(st['height'])
        eis((w, h) in [(1080, 1350), (1080, 1920)], 'afmeting 1080x1350 (post) of 1080x1920 (story)', '%dx%d' % (w, h))
        eis(os.path.getsize(path) < 8_000_000, 'bestand < 8 MB', '%.1f MB' % (os.path.getsize(path) / 1e6))
    else:
        j = json.loads(run(['ffprobe', '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', path]))
        v = next((x for x in j['streams'] if x['codec_type'] == 'video'), None)
        a = next((x for x in j['streams'] if x['codec_type'] == 'audio'), None)
        dur = float(j['format']['duration'])
        num, den = (v['r_frame_rate'].split('/') + ['1'])[:2]
        fps = float(num) / float(den or 1)
        eis((int(v['width']), int(v['height'])) == (W, H), 'afmeting 1080x1920 (9:16)', '%sx%s' % (v['width'], v['height']))
        eis(abs(fps - FPS) < 0.5, '30 fps', '%.2f' % fps)
        eis(v['codec_name'] == 'h264' and v.get('pix_fmt') == 'yuv420p', 'H.264 yuv420p', '%s %s' % (v['codec_name'], v.get('pix_fmt')))
        eis(8.0 <= dur <= 14.0, 'lengte 8-14 s', '%.1f s' % dur)
        eis(a is not None and a['codec_name'] == 'aac', 'geluidsspoor AAC aanwezig', a['codec_name'] if a else 'geen')
        eis(os.path.getsize(path) < 100_000_000, 'bestand < 100 MB', '%.1f MB' % (os.path.getsize(path) / 1e6))
        if a:
            r = subprocess.run(['ffmpeg', '-hide_banner', '-i', path, '-af', 'loudnorm=print_format=json', '-f', 'null', '-'],
                               capture_output=True, text=True)
            mi = re.search(r'"input_i"\s*:\s*"(-?[0-9.inf]+)"', r.stderr)
            li = float(mi.group(1)) if mi and 'inf' not in mi.group(1) else -99.0
            mp = re.search(r'"input_tp"\s*:\s*"(-?[0-9.inf]+)"', r.stderr)
            tp = float(mp.group(1)) if mp and 'inf' not in mp.group(1) else -99.0
            if li < -60:
                eis(True, 'geluid stil (mute) of -16 LUFS', 'stil')
            else:
                eis(-17.5 <= li <= -14.5, 'luidheid -16 LUFS (+/-1,5)', '%.1f LUFS' % li)
                eis(tp <= -0.5, 'geen oversturing (true peak <= -0,5 dB)', '%.1f dB' % tp)
        r = subprocess.run(['ffmpeg', '-hide_banner', '-i', path, '-vf', 'blackdetect=d=0.4:pix_th=0.06', '-an', '-f', 'null', '-'],
                           capture_output=True, text=True)
        zwart = re.findall(r'black_duration:([0-9.]+)', r.stderr)
        eis(not zwart, 'geen zwart beeld (>= 0,4 s)', ', '.join(zwart) + ' s' if zwart else '')
        r = subprocess.run(['ffmpeg', '-hide_banner', '-t', '%.2f' % max(dur - ENDCARD - 0.2, 0.5), '-i', path,
                            '-vf', 'freezedetect=n=0.002:d=1.2', '-an', '-f', 'null', '-'], capture_output=True, text=True)
        bev = re.findall(r'freeze_duration: ([0-9.]+)', r.stderr)
        eis(not bev, 'geen bevroren beeld (>= 1,2 s, eindkaart uitgezonderd)', ', '.join(bev) + ' s' if bev else '')
        r = subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-i', path, '-f', 'null', '-'], capture_output=True, text=True)
        eis(not r.stderr.strip(), 'decodeert zonder fouten', r.stderr.strip()[:80])
        mv = subprocess.run(['ffprobe', '-v', 'trace', '-i', path], capture_output=True, text=True).stderr
        mo, md = mv.find("type:'moov'"), mv.find("type:'mdat'")
        eis(0 <= mo < md, 'faststart (moov voor mdat)', '')
    if srt:
        txt = open(srt, encoding='utf-8').read()
        regels = [l for l in txt.splitlines() if l.strip() and not l.strip().isdigit() and '-->' not in l]
        te_lang = [l for l in regels if len(l) > 32]
        eis(not te_lang, 'ondertitels max. 32 tekens per regel', '; '.join(te_lang[:2]))
        eis(all(len(b.strip().splitlines()) <= 3 for b in txt.strip().split('\n\n')), 'max. 1 tekstregel per ondertitel', '')
    fouten = [r for r in res if not r[0]]
    for ok, naam, det in res:
        print('%-4s %s%s' % ('OK' if ok else 'FOUT', naam, (' (%s)' % det) if det else ''))
    print('KEURING: %s (%d/%d eisen)' % ('GOEDGEKEURD' if not fouten else 'AFGEKEURD', len(res) - len(fouten), len(res)))
    if fouten:
        sys.exit(1)


def main():
    a = sys.argv[1:]
    if len(a) >= 3 and a[0] == 'clip':
        cmd_clip(a[1], a[2])
    elif len(a) >= 3 and a[0] == 'photo':
        cmd_photo(a[1], a[2])
    elif len(a) >= 3 and a[0] == 'sheet':
        cmd_sheet(a[1], a[2])
    elif len(a) >= 2 and a[0] == 'scenes':
        cmd_scenes(a[1], float(a[2]) if len(a) > 2 else 0.3)
    elif len(a) >= 3 and a[0] == 'stabilize':
        cmd_stabilize(a[1], a[2])
    elif len(a) >= 3 and a[0] == 'denoise':
        cmd_denoise(a[1], a[2])
    elif len(a) >= 3 and a[0] == 'audio':
        cmd_audio(a[1], a[2])
    elif len(a) >= 3 and a[0] == 'anonymize':
        cmd_anonymize(a[1], a[2], a[3] if len(a) > 3 else None)
    elif len(a) >= 3 and a[0] == 'reframe':
        cmd_reframe(a[1], a[2])
    elif len(a) >= 2 and a[0] == 'check':
        cmd_check(a[1], a[2] if len(a) > 2 else None)
    elif len(a) >= 3 and a[0] == 'transcribe':
        cmd_transcribe(a[1], a[2], a[3] if len(a) > 3 else 'nl')
    elif len(a) >= 2 and a[0] == 'info':
        print(json.dumps(probe(a[1])))
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
