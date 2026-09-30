#!/usr/bin/env python3
"""Maakt een merk-afbeelding (JPEG) voor Aysan social media.
Gebruik: python3 tools/make_post.py spec.json uitvoer.jpg
spec.json: {"format": "post"|"story", "kicker": "optioneel klein label",
            "title": "Grote kop", "line1": "wit", "line2": "oranje",
            "bullets": ["max 4"], "cta": "aysantruckparts.com", "footer": "optioneel"}
Kleuren navy #1D1F2E / oranje #FF6B00 / wit. Liberation Sans (in de meeste Linux-images aanwezig).
"""
import json, sys, os
from PIL import Image, ImageDraw, ImageFont
NAVY=(29,31,46); ORANGE=(255,107,0); WHITE=(255,255,255); GREY=(170,175,195)
HERE=os.path.dirname(os.path.abspath(__file__))
LOGO=os.path.join(HERE,'..','brand','logo_op_navy.png')
def font(bold,size):
    for p in ['/usr/share/fonts/truetype/liberation/LiberationSans-%s.ttf'%('Bold' if bold else 'Regular'),
              '/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf'%('-Bold' if bold else '')]:
        if os.path.exists(p): return ImageFont.truetype(p,size)
    return ImageFont.load_default()
def wrap(d,text,f,maxw):
    words=text.split(); lines=[]; cur=''
    for w in words:
        t=(cur+' '+w).strip()
        if d.textlength(t,font=f)<=maxw: cur=t
        else: lines.append(cur); cur=w
    if cur: lines.append(cur)
    return lines
def main(spec,out):
    s=json.load(open(spec)); W,H=(1080,1920) if s.get('format')=='story' else (1080,1350)
    im=Image.new('RGB',(W,H),NAVY); d=ImageDraw.Draw(im)
    logo=Image.open(LOGO); lw=620; lh=int(logo.height*lw/logo.width)
    y=150 if H==1350 else 260
    im.paste(logo.resize((lw,lh),Image.LANCZOS),((W-lw)//2,y)); y+=lh+70
    def c(t,f,col,yy):
        d.text(((W-d.textlength(t,font=f))/2,yy),t,font=f,fill=col)
    if s.get('kicker'):
        f=font(True,34); t=s['kicker'].upper(); tw=d.textlength(t,font=f)
        d.rounded_rectangle([(W-tw)/2-22,y-8,(W+tw)/2+22,y+48],radius=26,fill=ORANGE); c(t,f,WHITE,y); y+=90
    for ln in wrap(d,s.get('title',''),font(True,72),W-160): c(ln,font(True,72),WHITE,y); y+=86
    y+=10
    if s.get('line1'): c(s['line1'],font(True,46),WHITE,y); y+=60
    if s.get('line2'): c(s['line2'],font(True,46),ORANGE,y); y+=60
    if s.get('bullets'):
        y+=30; d.rectangle([140,y,W-140,y+4],fill=ORANGE); y+=45; f=font(False,40)
        for b in s['bullets'][:4]:
            for i,ln in enumerate(wrap(d,b,f,W-240)):
                tw=d.textlength(ln,font=f); x=(W-tw)/2
                if i==0: d.ellipse([x-34,y+14,x-18,y+30],fill=ORANGE)
                d.text((x,y),ln,font=f,fill=WHITE); y+=54
            y+=12
    if s.get('cta'): y+=40; c(s['cta'],font(True,48),ORANGE,y)
    c(s.get('footer','DAF · MAN · Mercedes-Benz · Scania · Volvo · Iveco · Renault'),font(False,30),GREY,H-80)
    im.save(out,quality=92); print(out, W, H, 'y_end', y)
if __name__=='__main__': main(sys.argv[1],sys.argv[2])
