"""Shared visual primitives recovered from the approved 2026-09-20 capsule.
Brand, variable font weights, caption geometry, colors and easing are unchanged.
Only duration and footer chapter are parameterized.
"""
from pathlib import Path
from functools import lru_cache
import json, math, subprocess, sys
from PIL import Image, ImageDraw, ImageFont
import numpy as np

ROOT=Path(__file__).resolve().parent
ASSETS=ROOT/'assets'
S=2; W=1920; H=1080; FPS=25
DARK='#101619'; PANEL='#1A2327'; GOLD='#F2C461'; IVORY='#F4F1E9'; MUTED='#ABB6B9'; INK='#182024'
DURATION=1.0
CHAPTER='FORMATION APS'
def clamp(x):return max(0,min(1,x))
def ease(x):return 1-(1-clamp(x))**3
def px(x):return round(x*S)
def rgb(c):return tuple(int(c[i:i+2],16) for i in (1,3,5))
def mix(a,b,t):return tuple(round(x*(1-t)+y*t) for x,y in zip(rgb(a),rgb(b)))
@lru_cache(maxsize=100)
def font(size,weight=600):
    f=ImageFont.truetype(str(ASSETS/'Manrope.ttf'),px(size))
    f.set_variation_by_axes([weight]);return f
@lru_cache(maxsize=500)
def text_layer(text,size=40,weight=600,color=IVORY):
    f=font(size,weight);box=f.getbbox(text,anchor='lt')
    im=Image.new('RGBA',(max(1,box[2]+px(5)),max(1,box[3]+px(8))),(0,0,0,0))
    ImageDraw.Draw(im).text((0,0),text,font=f,fill=color,anchor='lt')
    return im

def txt(im,text,x,y,size=40,weight=600,color=IVORY,alpha=1,align='left'):
    a=text_layer(text,size,weight,color)
    if align=='center':x-=a.width/S/2
    if align=='right':x-=a.width/S
    if alpha<.999:
        if alpha<=0:return
        a=a.copy();a.putalpha(a.getchannel('A').point(lambda v:int(v*alpha)))
    im.paste(a,(px(x),px(y)),a)
def enter(im,text,x,y,t,delay=0,size=40,weight=600,color=IVORY,align='left'):
    q=ease((t-delay)/.65);txt(im,text,x,y+28*(1-q),size,weight,color,q,align)
def rect(im,box,fill,outline=None,width=1,r=0):
    d=ImageDraw.Draw(im);b=tuple(px(v) for v in box)
    if r:d.rounded_rectangle(b,radius=px(r),fill=fill,outline=outline,width=px(width))
    else:d.rectangle(b,fill=fill,outline=outline,width=px(width))
def line(im,p,fill,width=2):ImageDraw.Draw(im).line([tuple(px(v) for v in xy) for xy in p],fill=fill,width=px(width))
def circle(im,x,y,r,fill=None,outline=None,width=1):ImageDraw.Draw(im).ellipse((px(x-r),px(y-r),px(x+r),px(y+r)),fill=fill,outline=outline,width=px(width))
@lru_cache(maxsize=10)
def logo(size):return Image.open(ASSETS/'logo-integrale.png').convert('RGBA').resize((px(size),px(size)),Image.Resampling.LANCZOS)
def brand(im,light=False):
    lg=logo(88);im.paste(lg,(px(76),px(48)),lg)
    c=INK if light else IVORY
    txt(im,'INTÉGRALE ACADEMY',185,64,23,800,c)
    txt(im,'FORMATION APS',185,101,18,650,'#7B8588' if light else MUTED)
def footer(im,t,light=False):
    base='#DCDDD7' if light else '#354044'
    line(im,[(76,1032),(1844,1032)],base,2)
    line(im,[(76,1032),(76+1768*t/DURATION,1032)],'#B28A2C' if light else GOLD,3)
    txt(im,CHAPTER,76,1052,13,750,'#7B8588' if light else '#879499')
    txt(im,'INTÉGRALE ACADEMY',1844,1052,13,750,'#7B8588' if light else '#879499',align='right')
def label(im,text,light=False):txt(im,text,76,196,21,750,'#9B7522' if light else GOLD)

def poly(im,points,fill):
    ImageDraw.Draw(im).polygon([(px(x),px(y)) for x,y in points],fill=fill)

def bezier(a,b,c,d,n=30):
    return [((1-t)**3*a[0]+3*(1-t)**2*t*b[0]+3*(1-t)*t*t*c[0]+t**3*d[0],
             (1-t)**3*a[1]+3*(1-t)**2*t*b[1]+3*(1-t)*t*t*c[1]+t**3*d[1]) for t in np.linspace(0,1,n)]

def shield_points(cx,cy,k=1):
    p=bezier((0,-205),(58,-167),(130,-149),(186,-145))
    p.append((186,-13))
    p+=bezier((186,-13),(186,106),(114,193),(0,244))
    p+=bezier((0,244),(-114,193),(-186,106),(-186,-13))
    p.append((-186,-145))
    p+=bezier((-186,-145),(-130,-149),(-58,-167),(0,-205))
    return [(cx+x*k,cy+y*k) for x,y in p]

@lru_cache(maxsize=2)
def shield_art():
    size=(px(520),px(580));out=Image.new('RGBA',size,(0,0,0,0))
    mask=Image.new('L',size,0);poly(mask,shield_points(260,256,1.08),255)
    gold=np.zeros((size[1],1,4),dtype=np.uint8)
    for y in range(size[1]):
        u=y/size[1];c=mix('#F8DD94','#AB7B2B',u)
        gold[y,0]=(*c,255)
    layer=Image.fromarray(np.repeat(gold,size[0],axis=1));layer.putalpha(mask);out.alpha_composite(layer)
    poly(out,shield_points(260,254,1.035),'#131E23')
    ImageDraw.Draw(out).line([(px(x),px(y)) for x,y in shield_points(260,256,.93)],fill='#53615B',width=px(1),joint='curve')
    # A custom building symbol, drawn directly in 4K inside the protective outline.
    line(out,[(192,325),(192,170),(328,170),(328,325)],IVORY,5)
    line(out,[(176,325),(344,325)],GOLD,5)
    rect(out,(245,270,275,325),None,GOLD,4,r=2)
    for x in [217,260,303]:
        for y in [205,240]:rect(out,(x-6,y-6,x+6,y+6),GOLD,r=2)
    line(out,[(215,152),(305,152)],GOLD,4)
    return out

def soft_field(cx,cy):
    # Only the atmospheric background is softly shaded; all symbols remain native resolution.
    xx=np.arange(W,dtype=np.float32)[None,:];yy=np.arange(H,dtype=np.float32)[:,None]
    glow=np.exp(-(((xx-cx)/470)**2+((yy-cy)/390)**2))[:,:,None]
    lo=np.array(rgb(DARK),dtype=np.float32);hi=np.array(rgb('#263639'),dtype=np.float32)
    arr=(lo+(hi-lo)*glow).astype('uint8')
    return Image.fromarray(arr).resize((px(W),px(H)),Image.Resampling.BILINEAR)
@lru_cache(maxsize=8)
def background(kind):
    if kind=='intro':
        im=soft_field(1465,480)
        for r in [261,325,390]:circle(im,1465,497,r,outline='#304044',width=1)
        line(im,[(1038,208),(1038,863)],'#2D3D42',1)
        return im
    if kind=='badge':
        im=soft_field(570,480)
        line(im,[(1038,208),(1038,877)],'#2D3D42',1)
        return im
    if kind=='limits':return Image.new('RGB',(px(W),px(H)),IVORY)
    im=Image.new('RGB',(px(W),px(H)),DARK)
    # Architectural rules and a restrained warm glow form the visual system.
    for x in [76,650,1268,1844]:line(im,[(x,166),(x,875)],'#1E282B',1)
    if kind=='outro':
        for r in [290,375,465,558]:circle(im,960,480,r,outline='#273035',width=1)
    return im

def cue_index(s,t):
    v=0
    for i,c in enumerate(s['cues']):
        if t>=c['start']:v=i
    return v


def outro(im,s,lt,t):
    lg=logo(278);im.paste(lg,(px(821),px(260)),lg)
    enter(im,'INTÉGRALE ACADEMY',960,611,lt,.12,48,800,IVORY,align='center')
    enter(im,'Agir avec méthode.',960,699,lt,.32,39,550,GOLD,align='center')
    line(im,[(880,790),(1040,790)],GOLD,3)


@lru_cache(maxsize=256)
def split_caption(text,maxwidth=1650):
    words=text.split();rows=[];row=''
    for word in words:
        test=(row+' '+word).strip()
        if font(30,600).getlength(test)>px(maxwidth) and row:rows.append(row);row=word
        else:row=test
    if row:rows.append(row)
    return rows

def subtitle(im,s,t):
    for c in s['cues']:
        if c.get('pause') or not(c['start']<=t<c['end']):continue
        rows=split_caption(c['text']);y=938 if len(rows)==1 else 917
        widths=[text_layer(r,30,600,IVORY).width/S for r in rows]
        ww=max(widths)+68; hh=48 if len(rows)==1 else 88
        rect(im,(960-ww/2,y-13,960+ww/2,y-13+hh),'#080E11',r=11)
        for j,row in enumerate(rows):txt(im,row,960,y+j*40,30,600,IVORY,align='center')
        break
