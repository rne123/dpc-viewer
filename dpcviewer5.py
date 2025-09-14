import xml.etree.ElementTree as ET
import pygame, time, os, sys
from collections import defaultdict

# ---------- CONFIG ----------
XML_PATH = "zerobreak_nirne_8b.xml"
AUDIO_PATH = "audio.ogg"

J_WINDOWS=[("Perfect",42),("Great",80),("Good",150),("Bad",200)]
MISS_THRESHOLD_MS=200
NOTE_SPEED_MM_PER_S=300.0; SPEED_STEP_MM=20.0
btn_thickness_mm=5.0; THICKNESS_STEP_MM=0.5
FPS=60; PIXELS_PER_MM=96.0/25.4

# ---------- LOAD NOTES ----------
def load_notes(path):
    root=ET.parse(path).getroot()
    tps=float(root.find("header").find("songinfo").get("tps"))
    to_sec=lambda t:t/tps
    notes=defaultdict(list)
    for tr in root.find("note_list").findall("track"):
        idx=int(tr.get("idx"))
        for n in tr.findall("note"):
            tick=int(n.get("tick")); dur=int(n.get("dur") or 0)
            s,e=to_sec(tick),to_sec(tick+dur)
            notes[idx].append({"s":s,"e":e,"hold":dur>0,"hit":False,"missed":False,"holding":False})
    for k in notes:notes[k].sort(key=lambda x:x["s"])
    return notes
notes_by_track=load_notes(XML_PATH)

# ---------- TRACKS ----------
TRACK_TO_LANE={3:0,4:1,5:2,6:3,7:4,8:5}
LANE_TO_TRACK={v:k for k,v in TRACK_TO_LANE.items()}
LS_TRACK,RS_TRACK,TL_TRACK,TR_TRACK=2,9,10,11
LANE_COUNT=6; MISS_TRACKS=set(range(3,9))|{2,9,10,11}

# ---------- PYGAME ----------
pygame.init()
SCREEN_W,SCREEN_H=1200,800
screen=pygame.display.set_mode((SCREEN_W,SCREEN_H),pygame.RESIZABLE)
clock=pygame.time.Clock()
note_speed_mm=NOTE_SPEED_MM_PER_S
note_speed_px=note_speed_mm*PIXELS_PER_MM

def normal_th_px():return int(btn_thickness_mm*PIXELS_PER_MM)
def trig_th_px():return int((btn_thickness_mm-0.5)*PIXELS_PER_MM)

WHITE=(255,255,255);BLUE=(60,130,220);CYAN=(0,200,200);RED=(220,40,40)
GREEN=(0,220,0);BG=(18,18,18);LANE_BG=(30,30,30);TEXT=(230,230,230);GRAY=(80,80,80)
font_small=pygame.font.SysFont(None,18);font_large=pygame.font.SysFont(None,64)

MARGIN_X,MARGIN_BOTTOM,LANE_GAP=60,140,8
def layout(w,h):
    usable=int((w-2*MARGIN_X)*0.7); left=MARGIN_X+(w-2*MARGIN_X-usable)//2
    lane_w=(usable-(LANE_COUNT-1)*LANE_GAP)//LANE_COUNT
    return [(left+i*(lane_w+LANE_GAP),lane_w) for i in range(LANE_COUNT)],h-MARGIN_BOTTOM
lanes,TARGET_Y=layout(SCREEN_W,SCREEN_H)

# ---------- KEYS ----------
KEY_TO_TRACK={
    pygame.K_a:3, pygame.K_s:4, pygame.K_d:5,              # L1 L2 L3
    pygame.K_KP4:6, pygame.K_KP5:7, pygame.K_KP6:8,        # R1 R2 R3
    pygame.K_SPACE:TL_TRACK, pygame.K_KP0:TR_TRACK,        # Triggers
    pygame.K_LSHIFT:LS_TRACK, pygame.K_KP_PLUS:RS_TRACK    # Sides
}

# ---------- AUDIO ----------
audio_loaded=False
if os.path.exists(AUDIO_PATH):
    try:pygame.mixer.init();pygame.mixer.music.load(AUDIO_PATH);audio_loaded=True
    except:pass

# ---------- STATE ----------
judgement_counts={k:0 for k in["Perfect","Great","Good","Bad","Miss"]}
combo=0;last_judgement=None;last_time=0
pressed=set();paused=True;start_time=0;pause_time=0

def now():return pause_time if paused else time.time()-start_time
def apply_judge(name):
    global combo,last_judgement,last_time
    combo=0 if name=="Miss" else combo+1
    last_judgement,last_time=name,time.time()

def judge_err(n,t):return (n["s"]-t)*1000
def do_judge(tr,t):
    cands=[(abs(judge_err(n,t)),n) for n in notes_by_track[tr] if not n["hit"]and not n["missed"]and not n["hold"]]
    if not cands:return
    d,n=min(cands,key=lambda x:x[0])
    for name,ms in J_WINDOWS:
        if d<=ms:n["hit"]=True;judgement_counts[name]+=1;apply_judge(name);return
    if d<=MISS_THRESHOLD_MS:n["hit"]=True;judgement_counts["Bad"]+=1;apply_judge("Bad")

def auto_miss_check(t):
    for tr,notes in notes_by_track.items():
        if tr not in MISS_TRACKS:continue
        for n in notes:
            if n["hit"]or n["missed"]:continue
            if not n["hold"] and t-n["s"]>MISS_THRESHOLD_MS/1000:n["missed"]=True;judgement_counts["Miss"]+=1;apply_judge("Miss")
            if n["hold"] and t-n["e"]>MISS_THRESHOLD_MS/1000:
                judgement_counts["Perfect" if n["holding"] else "Miss"]+=1
                apply_judge("Perfect" if n["holding"] else "Miss");n["hit"]=True;n["holding"]=False

def reset():
    global combo,last_judgement,last_time,pressed,paused,start_time,pause_time
    for notes in notes_by_track.values():
        for n in notes:n.update({"hit":False,"missed":False,"holding":False})
    judgement_counts.update({k:0 for k in judgement_counts});combo=0;last_judgement=None;last_time=0
    pressed.clear();paused=True;pause_time=0;start_time=0
    if audio_loaded:pygame.mixer.music.stop()

# ---------- RENDER ----------
def draw_notes(surf,t):
    def draw_wide(n,l,r,c,th):
        y1,y2=TARGET_Y-(n["s"]-t)*note_speed_px,TARGET_Y-(n["e"]-t)*note_speed_px
        rect=pygame.Rect(lanes[l][0],min(y1,y2),lanes[r][0]+lanes[r][1]-lanes[l][0],max(th,abs(int(y2-y1))))
        pygame.draw.rect(surf,c,rect)
    def show(n):return (n["hold"] and t<=n["e"]+1) or (not n["hit"] and not n["missed"])
    for tr,c in [(LS_TRACK,CYAN),(RS_TRACK,CYAN),(TL_TRACK,RED),(TR_TRACK,RED)]:
        for n in notes_by_track.get(tr,[]):
            if show(n):draw_wide(n,0 if tr in(LS_TRACK,TL_TRACK)else 3,2 if tr in(LS_TRACK,TL_TRACK)else 5,c,trig_th_px())
    for lane in range(LANE_COUNT):
        tr=LANE_TO_TRACK[lane];x,w=lanes[lane]
        for n in notes_by_track.get(tr,[]):
            if not show(n):continue
            y=TARGET_Y-(n["s"]-t)*note_speed_px;c=BLUE if lane in(1,4)else WHITE
            if n["hold"]:
                y2=TARGET_Y-(n["e"]-t)*note_speed_px
                rect=pygame.Rect(x+int(w*0.05),min(y,y2),int(w*0.9),max(normal_th_px(),abs(int(y2-y))))
            else:
                th=normal_th_px();rect=pygame.Rect(x+int(w*0.05),int(y-th/2),int(w*0.9),th)
            pygame.draw.rect(surf,c,rect)

def draw_beams(surf):
    beam=pygame.Surface((SCREEN_W,SCREEN_H),pygame.SRCALPHA);h=int(50*PIXELS_PER_MM)
    for tr in pressed:
        if tr in TRACK_TO_LANE:x1=lanes[TRACK_TO_LANE[tr]][0];x2=x1+lanes[TRACK_TO_LANE[tr]][1]
        elif tr in(LS_TRACK,TL_TRACK):x1=lanes[0][0];x2=lanes[2][0]+lanes[2][1]
        else:x1=lanes[3][0];x2=lanes[5][0]+lanes[5][1]
        for i in range(h):
            y=TARGET_Y-i;a=int(140*(1-i/h));pygame.draw.line(beam,(255,255,255,a),(x1,y),(x2,y))
        for y in range(TARGET_Y,SCREEN_H):pygame.draw.line(beam,(255,255,255,80),(x1,y),(x2,y))
    surf.blit(beam,(0,0))

def draw_hud(surf,t):
    surf.blit(font_small.render(f"{t:.2f}s Speed {note_speed_mm:.1f}mm/s Thick {btn_thickness_mm:.1f}mm",True,TEXT),(10,8))
    y=28
    for k in judgement_counts:surf.blit(font_small.render(f"{k}:{judgement_counts[k]}",True,TEXT),(10,y));y+=16
    if combo:surf.blit(font_large.render(str(combo),True,WHITE), (SCREEN_W//2-20,SCREEN_H//3))

def draw_labels(surf):
    for i,(x,w) in enumerate(lanes):
        surf.blit(font_small.render(["A","S","D","NUM4","NUM5","NUM6"][i],True,TEXT),(x+w//2-10,TARGET_Y+20))
    surf.blit(font_small.render("SPACE=LTrig NUM0=RTrig LSHIFT=LSide NUM+=RSide",True,TEXT),(10,SCREEN_H-50))
    surf.blit(font_small.render("P=Start/Pause 1/2=Speed 3/4=Thick 9=Restart",True,TEXT),(10,SCREEN_H-30))

# ---------- MAIN ----------
running=True;reset()
while running:
    dt=clock.tick(FPS)/1000
    for e in pygame.event.get():
        if e.type==pygame.QUIT:running=False
        elif e.type==pygame.VIDEORESIZE:SCREEN_W,SCREEN_H=e.w,e.h;screen=pygame.display.set_mode((SCREEN_W,SCREEN_H),pygame.RESIZABLE);lanes,TARGET_Y=layout(SCREEN_W,SCREEN_H)
        elif e.type==pygame.KEYDOWN:
            if e.key==pygame.K_ESCAPE:running=False
            elif e.key==pygame.K_p:
                if paused:paused=False;start_time=time.time()
                else:paused=True;pause_time=now()
                if audio_loaded: (pygame.mixer.music.play(start=now()) if not paused else pygame.mixer.music.pause())
            elif e.key in (pygame.K_1,pygame.K_2):note_speed_mm=max(20,note_speed_mm+(SPEED_STEP_MM if e.key==pygame.K_2 else -SPEED_STEP_MM))
            elif e.key in (pygame.K_3,pygame.K_4):btn_thickness_mm=max(0.5,btn_thickness_mm+(THICKNESS_STEP_MM if e.key==pygame.K_4 else -THICKNESS_STEP_MM))
            elif e.key==pygame.K_9:reset()
            elif e.key in KEY_TO_TRACK:
                tr=KEY_TO_TRACK[e.key];pressed.add(tr);t=now()
                for n in notes_by_track[tr]:
                    if not(n["hit"]or n["missed"])and n["hold"]and not n["holding"]and abs(judge_err(n,t))<=MISS_THRESHOLD_MS:n["holding"]=True;break
                else:do_judge(tr,t)
        elif e.type==pygame.KEYUP and e.key in KEY_TO_TRACK:
            tr=KEY_TO_TRACK[e.key];pressed.discard(tr);t=now()
            for n in notes_by_track.get(tr,[]):
                if n["hold"]and n["holding"]and not n["hit"]:
                    if n["e"]-t<=0.5:judgement_counts["Perfect"]+=1;apply_judge("Perfect")
                    else:judgement_counts["Miss"]+=1;apply_judge("Miss")
                    n["hit"]=True;n["holding"]=False;break
    t=now();note_speed_px=note_speed_mm*PIXELS_PER_MM;auto_miss_check(t)
    screen.fill(BG)
    for x,w in lanes:pygame.draw.rect(screen,LANE_BG,(x,0,w,SCREEN_H));pygame.draw.line(screen,GRAY,(x,0),(x,SCREEN_H),1)
    draw_notes(screen,t);draw_beams(screen)
    pygame.draw.line(screen,GREEN,(lanes[0][0]-4,TARGET_Y),(lanes[-1][0]+lanes[-1][1]+4,TARGET_Y),27)
    draw_hud(screen,t);draw_labels(screen);pygame.display.flip()
pygame.quit();sys.exit()