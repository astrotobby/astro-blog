# Auto-thumbnail generator for the blog-to-video pipeline.
# Renders a catchy, varied 1280x720 thumbnail from the video title and sets it on
# the freshly-uploaded YouTube video. The design (font / layout / colour / background)
# rotates every time and is forced to differ from the previous upload (state in
# STATE/thumb_state.json, which survives across Action runs via actions/cache).
# Called by platforms.post_youtube right after upload; all failures are non-fatal.
import os, re, json, random
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from common import STATE, OUT, log

FONT_DIR = STATE / "fonts"
STATE_FILE = STATE / "thumb_state.json"
FURL = {
 "Anton": "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
 "BebasNeue": "https://github.com/google/fonts/raw/main/ofl/bebasneue/BebasNeue-Regular.ttf",
 "Oswald": "https://github.com/google/fonts/raw/main/ofl/oswald/Oswald%5Bwght%5D.ttf",
 "ArchivoBlack": "https://github.com/google/fonts/raw/main/ofl/archivoblack/ArchivoBlack-Regular.ttf",
 "Montserrat": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
 "Poppins": "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf",
}
PALS = [((8,78,66),(255,214,10),(210,45,45)), ((18,58,150),(255,255,255),(255,193,7)),
 ((150,40,30),(255,255,255),(255,214,10)), ((58,40,110),(255,214,10),(225,60,60)),
 ((16,16,20),(255,214,10),(210,45,45)), ((12,92,72),(255,255,255),(255,193,7)),
 ((190,60,20),(20,20,20),(255,255,255)), ((30,30,36),(0,220,170),(255,80,80))]
LAYS = ["left_slab","right_slab","diagonal","bottom_bar","top_strip","center_band"]
BGS = ["gradient","radial","stripes","particle","duotone"]
FONTS = ["Anton"]
_SYS = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

def _ensure_fonts():
    global FONTS
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    ok = []
    for n, u in FURL.items():
        p = FONT_DIR / (n + ".ttf")
        if not p.exists():
            try:
                r = requests.get(u, timeout=45)
                if r.status_code == 200 and len(r.content) > 10000:
                    p.write_bytes(r.content)
            except Exception:
                pass
        if p.exists():
            ok.append(n)
    FONTS = ok or (["__sys__"] if os.path.exists(_SYS) else ["__def__"])

def F(name, size):
    try:
        if name not in ("__sys__", "__def__"):
            return ImageFont.truetype(str(FONT_DIR / (name + ".ttf")), size)
    except Exception:
        pass
    if os.path.exists(_SYS):
        return ImageFont.truetype(_SYS, size)
    return ImageFont.load_default()

def tw(d, t, f):
    b = d.textbbox((0,0), t, font=f); return b[2]-b[0], b[3]-b[1]

def T(d, xy, t, f, fill, oc, ow=6):
    d.text(xy, t, font=f, fill=fill, stroke_width=ow, stroke_fill=oc)

def wrap(d, ws, f, mw):
    L=[]; c=""
    for w in ws:
        t=(c+" "+w).strip()
        if tw(d,t,f)[0]<=mw: c=t
        else:
            if c: L.append(c)
            c=w
    if c: L.append(c)
    return L

def fit(d, ph, fn, mw, mh, mx=132, mn=38):
    ws=ph.split()
    for s in range(mx, mn-1, -4):
        f=F(fn,s); L=wrap(d,ws,f,mw); lh=int(s*1.02)
        if lh*len(L)<=mh and all(tw(d,l,f)[0]<=mw for l in L): return f,L,lh
    f=F(fn,mn); return f, wrap(d,ph.split(),f,mw), int(mn*1.02)

def bg(style, seed, c1):
    W,H=1280,720; rnd=random.Random(seed); a=tuple(int(x*0.5) for x in c1); b=(6,7,10)
    im=Image.new("RGB",(W,H),b)
    if style=="gradient":
        top=Image.new("RGB",(W,H),a); m=Image.new("L",(W,H)); md=ImageDraw.Draw(m)
        for x in range(0,W,3): md.line([(x,0),(x,H)],fill=int(255*(1-x/W)))
        im=Image.composite(top,im,m)
    elif style=="radial":
        cx,cy=rnd.randint(500,900),rnd.randint(200,500)
        for r in range(700,0,-6):
            t=r/700; col=tuple(int(b[i]+(a[i]-b[i])*(1-t)) for i in range(3))
            ImageDraw.Draw(im).ellipse([cx-r,cy-r,cx+r,cy+r],fill=col)
    elif style=="stripes":
        top=Image.new("RGB",(W,H),a); m=Image.new("L",(W,H)); md=ImageDraw.Draw(m)
        for x in range(0,W,3): md.line([(x,0),(x,H)],fill=int(200*(1-x/W)))
        im=Image.composite(top,im,m); d=ImageDraw.Draw(im,"RGBA")
        for i in range(-H,W,54): d.line([(i,0),(i+H,H)],fill=(255,255,255,12),width=18)
    elif style=="duotone":
        im=Image.new("RGB",(W,H),b); d=ImageDraw.Draw(im)
        d.polygon([(0,0),(W,0),(W,H)],fill=a)
        d.polygon([(0,H),(W,H),(int(W*0.5),int(H*0.2))],fill=tuple(int(x*0.7) for x in c1))
    im=im.convert("RGBA")
    gl=Image.new("RGBA",(W,H),(0,0,0,0)); gd=ImageDraw.Draw(gl)
    for _ in range(4):
        cx,cy=rnd.randint(300,W),rnd.randint(0,H); rr=rnd.randint(120,240)
        gd.ellipse([cx-rr,cy-rr,cx+rr,cy+rr],fill=(255,255,255,18))
    im=Image.alpha_composite(im,gl.filter(ImageFilter.GaussianBlur(60)))
    if style=="particle":
        pt=Image.new("RGBA",(W,H),(0,0,0,0)); pd=ImageDraw.Draw(pt)
        pts=[(rnd.randint(300,W),rnd.randint(0,H)) for _ in range(26)]
        for i,(x,y) in enumerate(pts):
            for x2,y2 in pts[i+1:i+3]:
                if abs(x-x2)+abs(y-y2)<300: pd.line([(x,y),(x2,y2)],fill=(150,200,255,40),width=1)
            pd.ellipse([x,y,x+5,y+5],fill=(200,230,255,140))
        im=Image.alpha_composite(im,pt)
    return im

def badge(d, x, y, txt, acc, shape):
    f=F("ArchivoBlack",30); w,h=tw(d,txt,f)
    if shape=="pill": d.rounded_rectangle([x,y,x+w+40,y+h+26],radius=20,fill=acc)
    else: d.rectangle([x,y,x+w+36,y+h+24],fill=acc)
    fg=(20,20,20) if sum(acc)>380 else (255,255,255)
    d.text((x+18,y+9),txt,font=f,fill=fg)

def render(ph, bdg, combo):
    fn,pi,lay,st,sd=combo; col,txt,acc=PALS[pi]
    im=bg(st,sd,col).convert("RGBA"); d=ImageDraw.Draw(im,"RGBA"); bshape="pill" if sd%2 else "rect"
    if lay in ("left_slab","right_slab","diagonal"):
        ov=Image.new("RGBA",im.size,(0,0,0,0)); pd=ImageDraw.Draw(ov)
        if lay=="left_slab": pd.polygon([(0,0),(740,0),(600,720),(0,720)],fill=col+(232,)); tx,mw=56,540
        elif lay=="right_slab": pd.polygon([(1280,0),(560,0),(700,720),(1280,720)],fill=col+(232,)); tx,mw=700,510
        else: pd.polygon([(0,0),(560,0),(800,720),(0,720)],fill=col+(240,)); tx,mw=60,480
        im=Image.alpha_composite(im,ov); d=ImageDraw.Draw(im,"RGBA")
        badge(d,tx,58,bdg,acc,bshape); f,L,lh=fit(d,ph,fn,mw,370)
        for j,l in enumerate(L): T(d,(tx,180+j*lh),l,f,txt,(0,0,0),6)
        T(d,(tx,666),"ASTROSIGNAL",F("Oswald",26),(255,255,255),(0,0,0),3)
    elif lay=="bottom_bar":
        g=Image.new("RGBA",im.size,(0,0,0,0)); gd=ImageDraw.Draw(g)
        for y in range(280,720): gd.line([(0,y),(1280,y)],fill=col+(int(238*((y-280)/440)),))
        im=Image.alpha_composite(im,g); d=ImageDraw.Draw(im,"RGBA")
        badge(d,56,54,bdg,acc,bshape); f,L,lh=fit(d,ph,fn,1150,300,mx=118); y0=692-lh*len(L)
        for j,l in enumerate(L): T(d,(56,y0+j*lh),l,f,(255,255,255),(0,0,0),6)
    elif lay=="top_strip":
        d.rectangle([0,0,1280,150],fill=col+(255,))
        ov=Image.new("RGBA",im.size,(0,0,0,110)); im=Image.alpha_composite(im,ov); d=ImageDraw.Draw(im,"RGBA")
        d.rectangle([0,0,1280,150],fill=col+(255,)); badge(d,56,48,bdg,acc,bshape)
        f,L,lh=fit(d,ph,fn,1130,330,mx=120); y0=300
        for j,l in enumerate(L): T(d,(80,y0+j*lh),l,f,txt,(0,0,0),7)
        T(d,(80,668),"ASTROSIGNAL",F("Oswald",24),(255,255,255),(0,0,0),3)
    else:
        ov=Image.new("RGBA",im.size,(0,0,0,120)); im=Image.alpha_composite(im,ov); d=ImageDraw.Draw(im,"RGBA")
        f,L,lh=fit(d,ph,fn,1120,300,mx=120); total=lh*len(L); y0=(720-total)//2
        d.rectangle([0,y0-30,1280,y0+total+30],fill=col+(210,)); badge(d,56,y0-96,bdg,acc,bshape)
        for j,l in enumerate(L): T(d,(80,y0+j*lh),l,f,txt,(0,0,0),6)
    return im.convert("RGB")

_FILL={"TO","FROM","THE","AND","A","OF","IN","WITH","ITS","FOR","ON","IS","ARE","AN","AT"}
def _clean(s): return re.sub(r"[^A-Za-z0-9#'. ]"," ",s)
def _hook(title):
    t=re.sub(r"\s+"," ",title or "").strip(); cut=re.split(r"\s*[—–:|]\s+|\s+-\s+",t)[0]; low=cut.lower()
    if low.startswith("what is"): ph,bd="WHAT IS "+re.sub(r"\s+in 2026$","",cut[7:].strip().rstrip("?"),flags=re.I).upper(),"EXPLAINED"
    elif low.startswith("how to"): ph,bd="HOW TO "+cut[6:].strip().rstrip("?").upper(),"GUIDE"
    elif re.search(r"\bvs\.?\b",low): ph,bd=re.sub(r"\s+"," ",_clean(cut)).upper().strip(),"VS"
    else: ph,bd=" ".join(re.sub(r"\s+"," ",_clean(cut)).split()[:8]).upper(),"NEWS"
    ph=re.split(r"\?",ph)[0].strip(); w=ph.split()[:7]
    while w and w[-1] in _FILL: w.pop()
    return (" ".join(w) or "AI NEWS"), bd

def _pick(last, seed_key):
    rnd=random.Random(str(seed_key)); c=None
    for _ in range(80):
        c=(rnd.choice(FONTS), rnd.randrange(len(PALS)), rnd.choice(LAYS), rnd.choice(BGS), rnd.randrange(100000))
        if not last: return c
        if c[0]!=last[0] and c[2]!=last[2] and c[1]!=last[1] and c[3]!=last[3]: return c
    return c

def set_thumbnail_for(yt, video_id, title):
    # Generate a unique thumbnail and set it on video_id. Returns a small status dict.
    from googleapiclient.http import MediaFileUpload
    _ensure_fonts()
    ph, bdg = _hook(title)
    last=None
    try:
        if STATE_FILE.exists(): last=json.loads(STATE_FILE.read_text(encoding="utf-8")).get("last_design")
    except Exception: last=None
    combo=_pick(last, video_id)
    out_path=OUT / ("thumb_"+video_id+".png")
    render(ph, bdg, combo).save(str(out_path))
    yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(out_path), mimetype="image/png")).execute()
    try: STATE_FILE.write_text(json.dumps({"last_design": list(combo)}), encoding="utf-8")
    except Exception: pass
    return {"ok": True, "headline": ph, "badge": bdg, "font": combo[0], "layout": combo[2], "bg": combo[3], "palette": combo[1]}
