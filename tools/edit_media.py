#!/usr/bin/env python3
"""Bewerkt ruwe video/foto tot een afgewerkt Aysan-bestand (alleen ffmpeg nodig).

  python3 tools/edit_media.py clip  spec.json uit.mp4     # reel 9:16, 1080x1920
  python3 tools/edit_media.py photo spec.json uit.jpg     # post 4:5 of story 9:16
  python3 tools/edit_media.py sheet bestand.mp4 sheet.jpg # contactsheet om te beoordelen
  python3 tools/edit_media.py info  bestand               # duur, afmeting, audio

clip-spec (alle velden behalve src optioneel):
  {"src": "pad/naar/ruw.mp4",
   "cuts": [[2.0, 8.5], [12, 16]],      # stukken die blijven, in volgorde (anders start/end)
   "focus_x": 0.5,                       # 0..1: welk deel van een liggend beeld in beeld blijft
   "grade": {"brightness": 0.02, "contrast": 1.06, "saturation": 1.1},
   "title": "Max 6 woorden",             # eerste 3 s, binnen de veilige zone
   "subs": "ondertitels.srt",            # ingebrand, onder in de veilige zone
   "logo": true,                          # wit logo rechtsboven (veilige zone)
   "endcard": {"line": "Op = op.", "cta": "aysantruckparts.com"},
   "audio": "keep"|"mute"}                # keep: loudnorm -16 LUFS; mute: stil spoor
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


def cmd_clip(spec_path, out):
    s = json.load(open(spec_path))
    src = s['src']
    info = probe(src)
    cuts = s.get('cuts') or [[s.get('start', 0), s.get('end', info['dur'])]]
    mute = s.get('audio', 'keep') == 'mute' or not info['audio']
    tmp = tempfile.mkdtemp()
    cf = crop_expr(info['w'], info['h'], W, H, s.get('focus_x', 0.5), s.get('focus_y', 0.5))
    parts, vl, al = [], [], []
    for i, (a, b) in enumerate(cuts):
        parts.append('[0:v]trim=start=%s:end=%s,setpts=PTS-STARTPTS,%s,fps=%d[v%d]' % (a, b, cf, FPS, i))
        vl.append('[v%d]' % i)
        if not mute:
            parts.append('[0:a]atrim=start=%s:end=%s,asetpts=PTS-STARTPTS,aresample=44100[a%d]' % (a, b, i))
            al.append('[a%d]' % i)
    n = len(cuts)
    if mute:
        parts.append('%sconcat=n=%d:v=1:a=0[vc]' % (''.join(vl), n))
    else:
        parts.append(''.join(x for pair in zip(vl, al) for x in pair) + 'concat=n=%d:v=1:a=1[vc][ac]' % n)
    total = sum(b - a for a, b in cuts)
    chain = [grade_f(s.get('grade'))]
    if s.get('title'):
        tf = textfile(tmp, 'title.txt', wrap_text(s['title'].upper(), 18))
        chain.append(drawtext(tf, 74, '430', enable='between(t,0.4,3.4)'))
    cwd = None
    if s.get('subs'):
        shutil.copy(s['subs'], os.path.join(tmp, 'subs.srt'))
        chain.append("subtitles=subs.srt:force_style='FontName=Liberation Sans,FontSize=11,Bold=1,"
                     "PrimaryColour=&HFFFFFF&,OutlineColour=&H2E1F1D&,BorderStyle=1,Outline=1.6,"
                     "Alignment=2,MarginV=70'")
        cwd = tmp
    parts.append('[vc]%s[vg]' % ','.join(chain))
    inputs = ['-i', os.path.abspath(src)]
    last = '[vg]'
    if s.get('logo', True):
        inputs += ['-i', os.path.abspath(LOGO_WIT)]
        parts.append('[1:v]scale=190:-1[lg]')
        parts.append('%s[lg]overlay=W-w-60:260[vo]' % last)
        last = '[vo]'
    parts.append('%sformat=yuv420p[vf]' % last)
    main = os.path.join(tmp, 'main.mp4')
    cmd = ['ffmpeg', '-y', '-loglevel', 'error'] + inputs + ['-filter_complex', ';'.join(parts), '-map', '[vf]']
    if mute:
        cmd += ['-f', 'lavfi', '-t', '%.3f' % total, '-i', 'anullsrc=r=44100:cl=stereo', '-map', '%d:a' % (len(inputs) // 2)]
    else:
        parts[-1] = parts[-1]  # audio na concat nog normaliseren
        cmd = ['ffmpeg', '-y', '-loglevel', 'error'] + inputs + [
            '-filter_complex', ';'.join(parts[:-1] + [parts[-1], '[ac]loudnorm=I=-16:TP=-1.5:LRA=11,aformat=channel_layouts=stereo[af]']),
            '-map', '[vf]', '-map', '[af]']
    cmd += ['-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-r', str(FPS), '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '160k', '-ar', '44100', '-ac', '2', '-shortest', '-movflags', '+faststart', main]
    if cwd:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
        if r.returncode:
            sys.exit('ffmpeg faalde:\n' + r.stderr[-1500:])
    else:
        run(cmd)
    final, dur = main, total
    ec = s.get('endcard')
    if ec:
        end = os.path.join(tmp, 'end.mp4')
        lines = []
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
    shutil.copy(final, out)
    shutil.rmtree(tmp, ignore_errors=True)
    if not 8 <= dur <= 14:
        print('LET OP: lengte %.1f s valt buiten 8-14 s (Trial Reel).' % dur)
    print('klaar: %s (%.1f s, 1080x1920)' % (out, dur))


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


def main():
    a = sys.argv[1:]
    if len(a) >= 3 and a[0] == 'clip':
        cmd_clip(a[1], a[2])
    elif len(a) >= 3 and a[0] == 'photo':
        cmd_photo(a[1], a[2])
    elif len(a) >= 3 and a[0] == 'sheet':
        cmd_sheet(a[1], a[2])
    elif len(a) >= 2 and a[0] == 'info':
        print(json.dumps(probe(a[1])))
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
