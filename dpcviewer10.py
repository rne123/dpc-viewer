# chart_viewer_complete.py
# 실행: python chart_viewer_complete.py
# 필요: pygame, tkinter

import os
import sys
import time
import math
import xml.etree.ElementTree as ET
from collections import defaultdict
import tkinter as tk
from tkinter import filedialog, messagebox
import pygame

# ---------------- CONFIG ----------------
FPS = 60

# 판정 윈도우 (ms)
J_WINDOWS = [("Perfect", 42), ("Great", 80), ("Good", 150), ("Bad", 200)]
MISS_THRESHOLD_MS = 200

# 기본 속도/두께 (mm/s, mm)
NOTE_SPEED_MM_PER_S = 300.0
SPEED_STEP_MM = 20.0
BTN_THICKNESS_MM = 5.0
THICKNESS_STEP_MM = 0.5

PIXELS_PER_MM = 96.0 / 25.4
JUDGE_LINE_THICKNESS_PX = int(9 * 3)  # 판정선 두께(요구: 3배)

DEFAULT_AUDIO_NAME = "audio.ogg"

# 트랙 인덱스 상수
LS_TRACK = 2
RS_TRACK = 9
TL_TRACK = 10
TR_TRACK = 11

# 판정별 색상
JUDGE_COLORS = {
    "Perfect": (0, 255, 100),
    "Great": (80, 200, 255),
    "Good": (255, 220, 80),
    "Bad": (255, 140, 60),
    "Miss": (255, 60, 60)
}

# ---------------- UI: 모드 선택 및 파일 열기 ----------------
def choose_mode_and_file():
    root = tk.Tk()
    root.title("채보 뷰어 - 모드 선택 및 파일 열기")
    choice = {"mode": None, "file": None}

    tk.Label(root, text="모드를 선택하세요 (4 / 5 / 6 / 8):").pack(padx=12, pady=6)
    var = tk.IntVar(value=8)
    for m in (4, 5, 6, 8):
        tk.Radiobutton(root, text=f"{m}키", variable=var, value=m).pack(anchor="w", padx=20)

    file_label = tk.StringVar(value="선택된 파일 없음")
    tk.Label(root, textvariable=file_label).pack(pady=(6, 0))

    def pick_file():
        p = filedialog.askopenfilename(filetypes=[("XML files", "*.xml")])
        if p:
            file_label.set(os.path.basename(p))
            choice["file"] = p

    def do_ok():
        choice["mode"] = var.get()
        if not choice["file"]:
            messagebox.showwarning("파일 선택", "XML 파일을 선택해주세요.")
            return
        root.destroy()

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=8)
    tk.Button(btn_frame, text="파일 선택", command=pick_file).pack(side="left", padx=6)
    tk.Button(btn_frame, text="불러오기", command=do_ok).pack(side="left", padx=6)
    tk.Button(btn_frame, text="취소", command=root.destroy).pack(side="left", padx=6)

    root.mainloop()
    return choice["mode"], choice["file"]

# ---------------- XML 파싱 ----------------
def load_notes_from_xml(path):
    notes_by_track = defaultdict(list)
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception as e:
        print("XML 파싱 실패:", e)
        return notes_by_track

    tps = 480.0
    header = root.find("header")
    if header is not None:
        si = header.find("songinfo")
        if si is not None and si.get("tps"):
            try:
                tps = float(si.get("tps"))
            except:
                pass

    def tick_to_sec(tick):
        return tick / tps

    note_list = root.find("note_list")
    if note_list is None:
        return notes_by_track

    for tr in note_list.findall("track"):
        idx = int(tr.get("idx"))
        for n in tr.findall("note"):
            tick = int(n.get("tick"))
            dur = int(n.get("dur") or 0)
            s = tick_to_sec(tick)
            e = tick_to_sec(tick + dur)
            notes_by_track[idx].append({
                "s": s,
                "e": e,
                "hold": dur > 0,
                "hit": False,
                "missed": False,
                "holding": False,       # currently pressing
                "held_success": False   # successfully held (for scoring)
            })
    for k in notes_by_track:
        notes_by_track[k].sort(key=lambda x: x["s"])
    return notes_by_track

# ---------------- 모드 매핑 ----------------
def build_mode_mapping(mode):
    """
    반환:
      lane_tracks (left->right),
      key_to_track (pygame key -> track idx),
      side_len_lanes (사이드 트랙이 차지하는 라인 길이, lane 단위),
      MISS_TRACKS (set)
    """
    if mode == 4:
        lane_tracks = [3, 4, 5, 6]
        key_to_track = {
            pygame.K_s: 3,
            pygame.K_d: 4,
            pygame.K_l: 5,
            pygame.K_SEMICOLON: 6
        }
        side_len_lanes = 2.0
    elif mode == 5:
        lane_tracks = [3, 4, 5, 6, 7]
        # 3번째 라인(=track 5)에 d와 l 모두 매핑
        key_to_track = {
            pygame.K_a: 3,
            pygame.K_s: 4,
            pygame.K_d: 5,
            pygame.K_l: 5,
            pygame.K_SEMICOLON: 6,
            pygame.K_QUOTE: 7
        }
        side_len_lanes = 2.5
    elif mode == 6:
        lane_tracks = [3, 4, 5, 6, 7, 8]
        key_to_track = {
            pygame.K_a: 3,
            pygame.K_s: 4,
            pygame.K_d: 5,
            pygame.K_k: 6,
            pygame.K_l: 7,
            pygame.K_SEMICOLON: 8
        }
        side_len_lanes = 3.0
    else:  # 8키: 요청대로 버튼부 asdl;'
        lane_tracks = [3, 4, 5, 6, 7, 8]
        key_to_track = {
            pygame.K_a: 3, pygame.K_s: 4, pygame.K_d: 5,
            pygame.K_KP4: 6, pygame.K_KP5: 7, pygame.K_KP6: 8
        }
        side_len_lanes = 3.0

    # 공통: 트리거 / 사이드
    # 트리거: L 트리거 = SPACE, R 트리거 = KP0
    # 사이드: LSHIFT, KP_PLUS
    key_to_track.update({
        pygame.K_SPACE: TL_TRACK,
        pygame.K_KP0: TR_TRACK,
        pygame.K_LSHIFT: LS_TRACK,
        pygame.K_KP_PLUS: RS_TRACK
    })

    MISS_TRACKS = set(lane_tracks) | {LS_TRACK, RS_TRACK, TL_TRACK, TR_TRACK}
    return lane_tracks, key_to_track, side_len_lanes, MISS_TRACKS

# ---------------- 유틸 ----------------
def mm_to_px(mm):
    return mm * PIXELS_PER_MM

def clamp(v, a, b):
    return max(a, min(b, v))

# ---------------- 메인 뷰어 ----------------
def run_viewer(xml_path, mode):
    notes_by_track = load_notes_from_xml(xml_path)
    lane_tracks, KEY_TO_TRACK, side_len_lanes, MISS_TRACKS = build_mode_mapping(mode)

    pygame.init()
    SCREEN_W, SCREEN_H = 1280, 820
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.RESIZABLE)
    pygame.display.set_caption(f"Chart Viewer - {mode}키 - {os.path.basename(xml_path)}")
    clock = pygame.time.Clock()

    # 오디오 시도 로드 (xml 폴더의 audio.ogg)
    audio_loaded = False
    audio_path = os.path.join(os.path.dirname(xml_path), DEFAULT_AUDIO_NAME)
    try:
        if os.path.exists(audio_path):
            pygame.mixer.init()
            pygame.mixer.music.load(audio_path)
            audio_loaded = True
    except Exception as e:
        print("오디오 로드 실패:", e)
        audio_loaded = False

    # 색상/폰트
    WHITE = (255, 255, 255)
    BLUE = (60, 130, 220)
    TEAL = (0, 200, 200)
    RED = (220, 40, 40)
    GREEN = (0, 200, 0)
    BG = (18, 18, 18)
    LANE_BG = (30, 30, 30)
    TEXT = (230, 230, 230)
    GRAY = (70, 70, 70)

    font_small = pygame.font.SysFont(None, 18)
    font_mid = pygame.font.SysFont(None, 28)
    font_large = pygame.font.SysFont(None, 64)

    MARGIN_X, MARGIN_BOTTOM, LANE_GAP = 60, 140, 8

    def compute_layout(w, h):
        usable = int((w - 2 * MARGIN_X) * 0.7)
        left = MARGIN_X + (w - 2 * MARGIN_X - usable) // 2
        lane_w = max(28, (usable - (len(lane_tracks) - 1) * LANE_GAP) // len(lane_tracks))
        lanes = [(left + i * (lane_w + LANE_GAP), lane_w) for i in range(len(lane_tracks))]
        target_y = h - MARGIN_BOTTOM
        return lanes, target_y

    lanes, TARGET_Y = compute_layout(SCREEN_W, SCREEN_H)

    # 게임 상태
    judgement_counts = {k: 0 for k, _ in J_WINDOWS}
    judgement_counts["Miss"] = 0
    combo = 0
    last_judgement = None
    last_judgement_time = 0.0

    pressed_tracks = set()  # 현재 눌린 트랙 인덱스 (keybeam 표시)
    pressed_physical_keys = set()  # 눌린 실제 키코드(매핑표 표시용)

    paused = True
    start_time = 0.0
    pause_time = 0.0

    note_speed_mm = NOTE_SPEED_MM_PER_S
    btn_thickness_mm = BTN_THICKNESS_MM

    # time helper
    def now_seconds():
        if paused:
            return pause_time
        else:
            return time.time() - start_time

    # 초기화
    def reset_all_notes():
        for notes in notes_by_track.values():
            for n in notes:
                n.update({"hit": False, "missed": False, "holding": False, "held_success": False})

    def reset_game():
        nonlocal combo, last_judgement, last_judgement_time, pressed_tracks, pressed_physical_keys, paused, start_time, pause_time, note_speed_mm, btn_thickness_mm
        reset_all_notes()
        for k in judgement_counts:
            judgement_counts[k] = 0
        combo = 0
        last_judgement = None
        last_judgement_time = 0.0
        pressed_tracks.clear()
        pressed_physical_keys.clear()
        paused = True
        start_time = 0.0
        pause_time = 0.0
        note_speed_mm = NOTE_SPEED_MM_PER_S
        btn_thickness_mm = BTN_THICKNESS_MM
        if audio_loaded:
            try:
                pygame.mixer.music.stop()
            except:
                pass

    reset_game()

    # thickness helpers
    def normal_th_px():
        return max(1, int(btn_thickness_mm * PIXELS_PER_MM))

    def trigger_th_px():
        return max(1, int((btn_thickness_mm - 0.5) * PIXELS_PER_MM))

    # judgement helpers
    def apply_judgement(name):
        nonlocal combo, last_judgement, last_judgement_time
        if name == "Miss":
            combo = 0
        else:
            combo += 1
        last_judgement = name
        last_judgement_time = time.time()

    def time_error_ms(note, t):
        return (t - note["s"]) * 1000.0

    # 안정적으로 가장 가까운 아직 판정되지 않은 non-hold 노트 찾기
    def find_nearest_nonhold(track, t):
        best = None
        best_d = None
        notes = notes_by_track.get(track, [])
        # 검색: 현재 시간 기준으로 전후로 가까운 노트 선택
        for n in notes:
            if n["hold"] or n["hit"] or n["missed"]:
                continue
            d = abs(time_error_ms(n, t))
            if best_d is None or d < best_d:
                best_d = d
                best = n
        return best, best_d

    def do_judge(track, t):
        n, d = find_nearest_nonhold(track, t)
        if not n:
            return None
        # 판정
        for name, ms in J_WINDOWS:
            if d <= ms:
                n["hit"] = True
                judgement_counts[name] += 1
                apply_judgement(name)
                return name
        if d <= MISS_THRESHOLD_MS:
            n["hit"] = True
            judgement_counts["Bad"] += 1
            apply_judgement("Bad")
            return "Bad"
        return None

    # auto miss checker for allowed MISS_TRACKS only
    def auto_miss_check(t):
        for tr in MISS_TRACKS:
            for n in notes_by_track.get(tr, []):
                if n["hit"] or n["missed"]:
                    continue
                if not n["hold"]:
                    # non-hold: 지나가면 miss
                    if t - n["s"] > MISS_THRESHOLD_MS / 1000.0:
                        n["missed"] = True
                        judgement_counts["Miss"] += 1
                        apply_judgement("Miss")
                else:
                    # hold: 만약 끝나고 일정 시간 지났으면 finalize
                    if t - n["e"] > MISS_THRESHOLD_MS / 1000.0:
                        if n.get("held_success", False) or n.get("holding", False):
                            if not n["hit"]:
                                judgement_counts["Perfect"] += 1
                                apply_judgement("Perfect")
                                n["hit"] = True
                                n["holding"] = False
                        else:
                            # not held correctly
                            judgement_counts["Miss"] += 1
                            apply_judgement("Miss")
                            n["hit"] = True
                            n["missed"] = True
                            n["holding"] = False

    # 노트 보이기 규칙: hold이면 end까지 + buffer로 보여줘야 함
    def should_show(n, t):
        if n["hold"]:
            return t <= n["e"] + 1.0  # buffer 1s
        return not n["hit"] and not n["missed"]

    # 노트 그리기
    def draw_notes(t):
        # side/trigger 넓이 계산 (lane 단위로)
        if lanes:
            lane_w = lanes[0][1]
            gap = LANE_GAP
            side_width_px = int(side_len_lanes * (lane_w + gap) - gap)
        else:
            side_width_px = 0

        # 사이드/트리거 먼저
        for tr, color, left_side in [(LS_TRACK, TEAL, True), (RS_TRACK, TEAL, False), (TL_TRACK, RED, True), (TR_TRACK, RED, False)]:
            for n in notes_by_track.get(tr, []):
                if not should_show(n, t): continue
                if left_side:
                    x_start = lanes[0][0]
                    x_end = x_start + side_width_px
                else:
                    x_end = lanes[-1][0] + lanes[-1][1]
                    x_start = x_end - side_width_px
                y1 = TARGET_Y - (n["s"] - t) * note_speed_mm * PIXELS_PER_MM
                y2 = TARGET_Y - (n["e"] - t) * note_speed_mm * PIXELS_PER_MM
                rect = pygame.Rect(x_start, min(y1, y2), x_end - x_start, max(trigger_th_px(), abs(int(y2 - y1))))
                pygame.draw.rect(screen, color, rect)

        # 버튼 레인 노트
        for i, tr in enumerate(lane_tracks):
            x, w = lanes[i]
            for n in notes_by_track.get(tr, []):
                if not should_show(n, t): continue
                y = TARGET_Y - (n["s"] - t) * note_speed_mm * PIXELS_PER_MM
                # 요청: 2번과 5번 레인을 파란색으로 (index 기준: lane_tracks index 1 and 4)
                color = BLUE if i in (1, 4) and len(lane_tracks) >= 5 else WHITE
                if n["hold"]:
                    y2 = TARGET_Y - (n["e"] - t) * note_speed_mm * PIXELS_PER_MM
                    rect = pygame.Rect(x + int(w * 0.05), min(y, y2), int(w * 0.9), max(normal_th_px(), abs(int(y2 - y))))
                    pygame.draw.rect(screen, color, rect)
                else:
                    th = normal_th_px()
                    rect = pygame.Rect(x + int(w * 0.05), int(y - th / 2), int(w * 0.9), th)
                    pygame.draw.rect(screen, color, rect)

    # 키빔 그리기: 판정선 아래 전체 채우기 + 판정선 위 5cm까지 페이드
    def draw_keybeams():
        surf = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        beam_height_px = int(mm_to_px(50))  # 50mm = 5cm
        for tr in pressed_tracks:
            # x range
            if tr in lane_tracks:
                try:
                    idx = lane_tracks.index(tr)
                    x1 = lanes[idx][0]
                    x2 = x1 + lanes[idx][1]
                except ValueError:
                    continue
            elif tr in (LS_TRACK, TL_TRACK):
                x1 = lanes[0][0]
                x2 = x1 + int(side_len_lanes * (lanes[0][1] + LANE_GAP) - LANE_GAP)
            elif tr in (RS_TRACK, TR_TRACK):
                x2 = lanes[-1][0] + lanes[-1][1]
                x1 = x2 - int(side_len_lanes * (lanes[0][1] + LANE_GAP) - LANE_GAP)
            else:
                continue

            # 아래 전체 반투명 흰색
            for y in range(TARGET_Y, SCREEN_H):
                pygame.draw.line(surf, (255, 255, 255, 48), (x1, y), (x2, y))

            # 위로 올라가는 부분: fade out
            for i in range(beam_height_px):
                y = TARGET_Y - i
                alpha = int(200 * (1 - (i / max(1, beam_height_px))))
                if alpha < 0: alpha = 0
                pygame.draw.line(surf, (255, 255, 255, alpha), (x1, y), (x2, y))

        screen.blit(surf, (0, 0))

    # 매핑 텍스트 생성
    def get_keymap_lines():
        inv = defaultdict(list)
        for k, tr in KEY_TO_TRACK.items():
            inv[tr].append(pygame.key.name(k).upper())
        lines = []
        # lanes labels (left->right)
        lane_labels = []
        for i, tr in enumerate(lane_tracks, start=1):
            keys = inv.get(tr, [])
            lane_labels.append(f"L{i}({tr}):{'/'.join(keys) if keys else '-'}")
        lines.append("  ".join(lane_labels))
        # special tracks
        lines.append(f"TL({TL_TRACK}):{('/'.join(inv.get(TL_TRACK,[])) or '-')}  TR({TR_TRACK}):{('/'.join(inv.get(TR_TRACK,[])) or '-')}")
        lines.append(f"LS({LS_TRACK}):{('/'.join(inv.get(LS_TRACK,[])) or '-')}  RS({RS_TRACK}):{('/'.join(inv.get(RS_TRACK,[])) or '-')}")
        lines.append("Controls: P Start/Pause  1/- Speed  2/+ Speed  3/- Thick  4/+ Thick  9 Restart")
        return lines

    # lane label rendering
    def draw_lane_labels():
        inv = defaultdict(list)
        for k, tr in KEY_TO_TRACK.items():
            inv[tr].append(pygame.key.name(k).upper())
        for i, tr in enumerate(lane_tracks):
            x, w = lanes[i]
            label = "/".join(inv.get(tr, [])) or "-"
            screen.blit(font_small.render(label, True, TEXT), (x + w // 2 - 20, TARGET_Y + 18))
        # special
        screen.blit(font_small.render("TL " + ("/".join(inv.get(TL_TRACK, [])) or "-"), True, TEXT), (lanes[0][0], TARGET_Y + 40))
        screen.blit(font_small.render("TR " + ("/".join(inv.get(TR_TRACK, [])) or "-"), True, TEXT), (lanes[-1][0] + lanes[-1][1] - 80, TARGET_Y + 40))
        screen.blit(font_small.render("LS " + ("/".join(inv.get(LS_TRACK, [])) or "-"), True, TEXT), (lanes[0][0], TARGET_Y + 58))
        screen.blit(font_small.render("RS " + ("/".join(inv.get(RS_TRACK, [])) or "-"), True, TEXT), (lanes[-1][0] + lanes[-1][1] - 80, TARGET_Y + 58))

    # HUD draw
    def draw_hud(t):
        # top-left
        lines = [
            f"Time: {t:.2f}s   Speed: {note_speed_mm:.1f} mm/s   Thick: {btn_thickness_mm:.2f} mm",
            f"Mode: {mode}키   File: {os.path.basename(xml_path)}  Audio: {'Yes' if audio_loaded else 'No'}"
        ]
        y = 6
        for ln in lines:
            screen.blit(font_small.render(ln, True, TEXT), (10, y))
            y += 18

        # keymap
        for ln in get_keymap_lines():
            screen.blit(font_small.render(ln, True, TEXT), (10, y))
            y += 16

        # judgement counts to the right
        x_right = SCREEN_W - 200
        yy = 8
        for name in ["Perfect", "Great", "Good", "Bad", "Miss"]:
            c = judgement_counts.get(name, 0)
            screen.blit(font_small.render(f"{name}: {c}", True, JUDGE_COLORS.get(name, TEXT)), (x_right, yy))
            yy += 18

        # combo big
        if combo > 0:
            txt = font_large.render(str(combo), True, WHITE)
            screen.blit(txt, txt.get_rect(center=(SCREEN_W // 2, SCREEN_H // 3)))

        # last judgement pop
        if last_judgement and (time.time() - last_judgement_time < 0.9):
            color = JUDGE_COLORS.get(last_judgement, WHITE)
            txt = font_large.render(last_judgement, True, color)
            screen.blit(txt, txt.get_rect(center=(SCREEN_W // 2, SCREEN_H // 2 + 80)))

    # ---------------- 메인 루프 ----------------
    running = True
    note_speed_px = note_speed_mm * PIXELS_PER_MM

    while running:
        dt = clock.tick(FPS) / 1000.0

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.VIDEORESIZE:
                SCREEN_W, SCREEN_H = ev.w, ev.h
                screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.RESIZABLE)
                lanes, TARGET_Y = compute_layout(SCREEN_W, SCREEN_H)
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    running = False
                elif ev.key == pygame.K_p:
                    # start/resume/pause handling: start only when pressing p the first time
                    if paused:
                        if start_time == 0.0:
                            # fresh start
                            start_time = time.time()
                            pause_time = 0.0
                            if audio_loaded:
                                try:
                                    pygame.mixer.music.play()
                                except:
                                    pass
                        else:
                            # resume from pause
                            start_time = time.time() - pause_time
                            if audio_loaded:
                                try:
                                    pygame.mixer.music.unpause()
                                except:
                                    pass
                        paused = False
                    else:
                        # pause
                        pause_time = now_seconds()
                        paused = True
                        if audio_loaded:
                            try:
                                pygame.mixer.music.pause()
                            except:
                                pass
                elif ev.key == pygame.K_9:
                    reset_game()
                elif ev.key == pygame.K_2:
                    note_speed_mm += SPEED_STEP_MM
                elif ev.key == pygame.K_1:
                    note_speed_mm = max(20.0, note_speed_mm - SPEED_STEP_MM)
                elif ev.key == pygame.K_4:
                    btn_thickness_mm += THICKNESS_STEP_MM
                elif ev.key == pygame.K_3:
                    btn_thickness_mm = max(0.1, btn_thickness_mm - THICKNESS_STEP_MM)

                # mapped keys handling
                if ev.key in KEY_TO_TRACK:
                    tr = KEY_TO_TRACK[ev.key]
                    pressed_physical_keys.add(ev.key)
                    pressed_tracks.add(tr)
                    t = now_seconds()
                    # First, try to find matching hold note to start holding.
                    started_hold = False
                    for n in notes_by_track.get(tr, []):
                        if n["hold"] and not n["hit"] and not n["missed"] and not n["holding"]:
                            # allow leeway: within MISS_THRESHOLD_MS before/after start
                            if abs(time_error_ms(n, t)) <= MISS_THRESHOLD_MS:
                                n["holding"] = True
                                started_hold = True
                                # mark as not yet hit - final judgement done on release or end
                                break
                    if not started_hold:
                        # judge instantaneous note
                        do_judge(tr, t)

            elif ev.type == pygame.KEYUP:
                if ev.key in KEY_TO_TRACK:
                    tr = KEY_TO_TRACK[ev.key]
                    pressed_physical_keys.discard(ev.key)
                    if tr in pressed_tracks:
                        pressed_tracks.discard(tr)
                    t = now_seconds()
                    # evaluate hold release
                    for n in notes_by_track.get(tr, []):
                        if n["hold"] and n.get("holding", False) and not n["hit"] and not n["missed"]:
                            # if released within 0.5s before end => success (Perfect)
                            # i.e., if end - t <= 0.5 -> Perfect
                            if n["e"] - t <= 0.5:
                                judgement_counts["Perfect"] += 1
                                apply_judgement("Perfect")
                                n["hit"] = True
                                n["held_success"] = True
                                n["holding"] = False
                            else:
                                # too early release -> Miss (추가)
                                judgement_counts["Miss"] += 1
                                apply_judgement("Miss")
                                n["missed"] = True
                                n["holding"] = False
                            break

        # time, update
        t = now_seconds()
        note_speed_px = note_speed_mm * PIXELS_PER_MM
        auto_miss_check(t)

        # draw
        screen.fill(BG)
        # lanes background
        for x, w in lanes:
            pygame.draw.rect(screen, LANE_BG, (x, 0, w, SCREEN_H))
            pygame.draw.line(screen, GRAY, (x, 0), (x, SCREEN_H), 1)

        # draw notes
        draw_notes(t)

        # draw keybeams under/above judge line
        draw_keybeams()

        # judge line always on top: thick green
        x1 = lanes[0][0] - 4
        x2 = lanes[-1][0] + lanes[-1][1] + 4
        pygame.draw.line(screen, GREEN, (x1, TARGET_Y), (x2, TARGET_Y), JUDGE_LINE_THICKNESS_PX)

        # lane labels and HUD
        draw_lane_labels()
        draw_hud(t)

        pygame.display.flip()

    pygame.quit()

# ---------------- 엔트리 ----------------
if __name__ == "__main__":
    mode, xml_file = choose_mode_and_file()
    if not mode or not xml_file:
        print("모드 선택 또는 파일 선택이 취소되었습니다.")
        sys.exit(0)
    # pre-build mapping to check
    lane_tracks_tmp, key_to_track_tmp, side_len_lanes_tmp, MISS_TRACKS_tmp = build_mode_mapping(mode)
    run_viewer(xml_file, mode)