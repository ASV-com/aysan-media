#!/usr/bin/env python3
"""Eigen achtergrondmuziek voor reels (geen licentie nodig: zelf gegenereerd, eigendom van Aysan).

  python3 tools/make_music.py <stijl> uit.mp3 [seconden] [seed]
  stijlen: drive (118 bpm, energiek), werk (102 bpm, strak), rustig (88 bpm, zacht)

Opbouw: kick, clap, hihat, bas, akkoordpad en pluck-arpeggio; intro zonder kick, daarna vol.
Bedoeld als ondergrond (edit_media.py clip "music" duikt hem onder spraak).
Vereist numpy, scipy en ffmpeg.
"""
import os, subprocess, sys, tempfile, wave
import numpy as np
from scipy.signal import butter, lfilter

SR = 44100
STIJL = {
    'drive':  {'bpm': 118, 'prog': [('A', 'min'), ('F', 'maj'), ('C', 'maj'), ('G', 'maj')], 'hat16': True,  'arp': True,  'gain': 1.0},
    'werk':   {'bpm': 102, 'prog': [('D', 'min'), ('B', 'maj'), ('F', 'maj'), ('C', 'maj')], 'hat16': False, 'arp': True,  'gain': 0.95},
    'rustig': {'bpm': 88,  'prog': [('C', 'maj'), ('A', 'min'), ('F', 'maj'), ('G', 'maj')], 'hat16': False, 'arp': False, 'gain': 0.85},
}
NOOT = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 10}  # B = Bes (mooier in d-mineur)


def hz(semi_from_a4):
    return 440.0 * 2 ** (semi_from_a4 / 12.0)


def akkoord(root, kind, octave=4):
    base = NOOT[root] - 9 + (octave - 4) * 12  # t.o.v. A4
    return [base, base + (3 if kind == 'min' else 4), base + 7]


def lp(x, fc):
    b, a = butter(2, min(fc / (SR / 2), 0.99))
    return lfilter(b, a, x)


def hp(x, fc):
    b, a = butter(2, min(fc / (SR / 2), 0.99), 'high')
    return lfilter(b, a, x)


def env(n, a=0.005, d=0.2, s=0.0, sustain_len=0.0):
    t = np.arange(n) / SR
    e = np.minimum(t / max(a, 1e-4), 1.0)
    rel = np.exp(-np.maximum(t - a - sustain_len, 0) / max(d, 1e-4))
    return e * np.where(t < a + sustain_len, 1.0, rel) * (1 - s) + s * e


def kick(rng):
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    f = 45 + 75 * np.exp(-t / 0.045)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t / 0.16) * 0.45 + 0.08 * rng.standard_normal(n) * np.exp(-t / 0.004)


def clap(rng):
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    noise = hp(lp(rng.standard_normal(n), 6000), 900)
    bursts = sum(np.exp(-np.maximum(t - o, 0) / 0.012) * (t >= o) for o in (0, 0.011, 0.022))
    return noise * (0.35 * bursts + 0.6 * np.exp(-t / 0.09)) * 0.5


def hat(rng, open_=False):
    n = int((0.18 if open_ else 0.05) * SR)
    t = np.arange(n) / SR
    return lp(hp(rng.standard_normal(n), 7000), 12000) * np.exp(-t / (0.06 if open_ else 0.012)) * 0.11


def saw(f, n, detune=0.0):
    """Bandbegrensde zaagtand (additief, harmonischen tot 8 kHz): geen aliasing/digitale schittering."""
    t = np.arange(n) / SR
    out = 0
    for d in (-detune, 0, detune) if detune else (0,):
        ff = f * (1 + d)
        kmax = max(int(8000 / ff), 1)
        k = np.arange(1, min(kmax, 40) + 1)[:, None]
        out = out + (np.sin(2 * np.pi * k * ff * t[None, :]) / k).sum(0) * (2 / np.pi)
    return out / (3 if detune else 1)


def place(buf, sig, start):
    s = int(start)
    if s >= len(buf):
        return
    e = min(s + len(sig), len(buf))
    buf[s:e] += sig[:e - s]


def maak(stijl, secs, seed=7):
    st = STIJL[stijl]
    rng = np.random.default_rng(seed)
    beat = 60.0 / st['bpm']
    bar = 4 * beat
    nbars = int(np.ceil(secs / bar)) + 1
    N = int(nbars * bar * SR)
    L, R = np.zeros(N), np.zeros(N)
    K, C = kick(rng), clap(rng)
    for b in range(nbars):
        t0 = b * bar * SR
        chord = akkoord(*st['prog'][b % len(st['prog'])])
        intro = b < 2
        # drums
        for q in range(4):
            if not intro:
                place(L, K, t0 + q * beat * SR); place(R, K, t0 + q * beat * SR)
            if q in (1, 3) and (not intro or b == 1):
                place(L, C * 0.9, t0 + q * beat * SR); place(R, C, t0 + q * beat * SR)
        steps = 16 if st['hat16'] else 8
        for i in range(steps):
            h = hat(rng, open_=(i % (steps // 2) == steps // 2 - 1)) * (1.0 if i % 2 == 0 else 0.6)
            pos = t0 + i * (bar / steps) * SR + (0.012 * SR if i % 2 else 0)  # lichte swing
            place(L, h * 0.9, pos); place(R, h * 1.1, pos)
        # bas: 8sten op de grondtoon, octaafsprong
        root = chord[0] - 24
        for i in range(8):
            if intro and i % 2:
                continue
            n = int(beat / 2 * SR * 0.9)
            f = hz(root + (12 if i in (3, 7) else 0))
            sig = lp(saw(f, n), 420) * env(n, 0.004, 0.12, 0.3, beat / 4) * 0.17
            place(L, sig, t0 + i * beat / 2 * SR); place(R, sig, t0 + i * beat / 2 * SR)
        # pad: zachte akkoorden, licht stereo
        n = int(bar * SR)
        pad = sum(lp(saw(hz(p + 12), n, 0.004), 2400) for p in chord) / 3
        pad *= env(n, 0.25, 0.4, 0.75, bar - 0.6) * (0.6 if not intro else 0.6)
        place(L, pad, t0); place(R, np.roll(pad, int(0.011 * SR)), t0)
        # pluck-arpeggio
        if st['arp'] and not intro:
            notes = chord + [chord[0] + 12]
            for i in range(8):
                n2 = int(beat / 2 * SR)
                f = hz(notes[[0, 1, 2, 3, 2, 1, 2, 3][i]] + 12)
                sig = lp(saw(f, n2), 2600) * env(n2, 0.002, 0.12) * 0.32
                pan = 0.35 if i % 2 else -0.35
                place(L, sig * (1 - pan), t0 + i * beat / 2 * SR); place(R, sig * (1 + pan), t0 + i * beat / 2 * SR)
    mix = np.stack([L, R], 1)[:int(secs * SR)] * st['gain']
    mix /= max(np.abs(mix).max(), 1e-6) / 0.85
    return mix


def main():
    a = sys.argv[1:]
    if len(a) < 2 or a[0] not in STIJL:
        sys.exit(__doc__)
    secs = float(a[2]) if len(a) > 2 else 30.0
    seed = int(a[3]) if len(a) > 3 else 7
    mix = maak(a[0], secs, seed)
    tmp = tempfile.mkdtemp()
    w = os.path.join(tmp, 'm.wav')
    with wave.open(w, 'wb') as f:
        f.setnchannels(2); f.setsampwidth(2); f.setframerate(SR)
        f.writeframes((mix * 32767).astype('<i2').tobytes())
    r = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', w, '-af',
                        'acompressor=threshold=-18dB:ratio=3:attack=10:release=120,loudnorm=I=-16:TP=-1.5:LRA=9,'
                        'afade=t=out:st=%.2f:d=1.5' % max(secs - 1.5, 0),
                        '-c:a', 'libmp3lame', '-b:a', '192k', a[1]], capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr[-800:])
    print('klaar: %s (%s, %.0f s, eigen compositie)' % (a[1], a[0], secs))


if __name__ == '__main__':
    main()
