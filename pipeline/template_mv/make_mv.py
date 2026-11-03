"""MV 範本（2026-10-30，由〈把青春唱成光〉整理成通用版）。一首歌＝一個 film.json；成片音軌＝原曲，畫面照歌曲時間軸接。
完整流程與規則見同資料夾 README.md。在片子資料夾用 H3 venv 執行：$PY_H3 make_mv.py <stage ...>

前置（一次）：python ../../tools/mv_song.py assets/song.mp3 --lyrics assets/lyrics.txt   → 人聲、歌詞時間、鏡表草稿
stage：
  storyboard  依 shots 的 panel 寫 16 宮格分鏡草圖提示詞 → preview/sb_prompt_<k>.txt（交給 ChatGPT 畫成 preview/storyboard_<k>.png）
  preview     疊鏡號＋依歌曲時間軸做動態分鏡試映 preview/試映.mp4（原曲＋歌詞字幕）
  prompts     寫 ChatGPT 生圖提示詞：out/chatgpt/char_prompts.txt、master_prompts.txt、first_prompts_<段>.txt
  fit         把 out/chatgpt/in/ 裡 ChatGPT 生的原圖裁成流程尺寸（char_*→out/chars、master_*→out/masters、first_*→out/first）
  check       送 H3 前檢查（有 ERROR 不准送）
  guides      每鏡 H3 固定音軌：kind 唱＝原曲人聲從 t0 切一段（嘴型照它動）；其他＝靜音
  h3          每鏡 spec.json → H3（本機 NVIDIA 或 Colab，Colab 每批 H3_CHUNK=10 鏡、只裝 H3）；ONLY="A05 B12" 只跑指定鏡
  clips       out/review/clips_<鏡>.jpg（每鏡 6 格，只看會用到的秒數）＋ _all.jpg
  cut         每鏡取前 (t1−t0) 秒 → 1080p → 照原曲時間接 → 原曲音軌 → 片名＋歌詞字幕 → out/cut/mv_1080p.mp4、mv_720p_phone.mp4
重拍某鏡：把 out/h3/<鏡>/clip.mp4 移到 out/h3_bad_<時間>/，seeds 加 "h3_<鏡>": 新數字，ONLY=<鏡> 跑 h3。
每鏡可選欄位：camera、extra_constraints、pin_last（最後一幀也釘成首幀，治「後段自己換景／加人」）、
              src_max（不對嘴的鏡只取前 N 秒、放慢填滿，治「後段壞掉」）、panel（分鏡草圖用的一句英文）。
"""
import json, os, re, subprocess, sys, time, wave
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "film.json").read_text(encoding="utf-8"))
OUT = HERE / "out"; OUT.mkdir(exist_ok=True)
REPO = (HERE / CFG.get("repo_dir", "../..")).resolve()
T = Path(os.environ.get("AI_TOOLS", str(REPO / "tools")))
PYH3 = os.environ.get("PY_H3", sys.executable)
SR, FPS = 48000, 24
CHARS, SHOTS = CFG["chars"], CFG["shots"]
UPSCALE = os.environ.get("UPSCALE", "lanczos")      # lanczos｜flashvsr
sys.path.insert(0, str(REPO / "tools"))
try:
    from fonts import SUB_FONT_NAME  # noqa: E402
except Exception:
    SUB_FONT_NAME = "PingFang TC"


def local_h3_ok():
    try:
        v = int(subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=20).stdout.split()[0]) / 1024
        return v >= 15
    except Exception:
        return False


H3_BACKEND = os.environ.get("H3_BACKEND") or ("local" if local_h3_ok() else "colab")


def run(cmd, cwd=OUT, check=True):
    print("$", " ".join(map(str, cmd))[:200], flush=True)
    r = subprocess.run([str(c) for c in cmd], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}, stdin=subprocess.DEVNULL)
    if check and r.returncode != 0:
        raise SystemExit(f"FAILED: {' '.join(map(str, cmd))[:200]}\n{(r.stdout + r.stderr)[-2500:]}")
    return r


def dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return float(r.stdout)


def frames_for(d):
    n = 0
    while 17 * n + 5 < d * FPS:
        n += 1
    return 17 * n + 5


def seed(key, default):
    return int(CFG.get("seeds", {}).get(key, default))


def only():
    o = os.environ.get("ONLY", "").split()
    return [s for s in SHOTS if not o or s["id"] in o]


def instruments():
    """{角色 key: 樂器英文描述}。film.json 用 "instruments": {"boy": {"desc": ..., "ref": "refs/x.jpg"}}；舊欄位 "guitars" 也吃。"""
    ins = {k: (v["desc"] if isinstance(v, dict) else v) for k, v in CFG.get("instruments", {}).items()}
    for k, v in CFG.get("guitars", {}).items():
        ins.setdefault(k, v)
    for k in list(ins):                              # 同一人的另一套服裝（boy_uni）沿用同一把樂器
        for c in CHARS:
            if c.startswith(k + "_"):
                ins.setdefault(c, ins[k])
    return ins


def hq(s):
    """不加速（14 步）？每鏡 "hq": true/false 優先；否則看全片 "h3_quality"：
    "fast"＝全部加速｜"hq"＝全部不加速｜"faces"＝唱的鏡＋有人臉的近景不加速、其他加速。開工前要先問使用者選哪個。"""
    if "hq" in s:
        return bool(s["hq"])
    q = CFG.get("h3_quality", "fast")
    return q == "hq" or (q == "faces" and s["kind"] == "唱")


def gen_secs(s):
    """H3 至少生 4 秒（太短不穩）；比實際用到的長 0.3 秒當餘裕。"""
    return frames_for(max(4.0, s["dur"] + 0.3)) / FPS


def singer(s):
    """唱的鏡頭由誰當 dialogue 的主唱（雙人鏡取第一位，動作裡寫兩人一起唱）。"""
    return s["refs"][0] if s["kind"] == "唱" and s["refs"] else None


def lyric_text(s):
    t = re.sub(r"[（(].*?[）)]", "", s.get("lyric", "")).replace("／", " ").replace("！", "").strip()
    return re.sub(r"\s+", " ", t)


# ------------------------------------------------------------------------------------------------ guides
def guides():
    import numpy as np
    pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(HERE / CFG["vocals"]), "-ar", str(SR), "-ac", "1", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    voc = np.frombuffer(pcm, np.int16)
    for s in only():
        od = OUT / "h3" / s["id"]; od.mkdir(parents=True, exist_ok=True)
        n = int(round(gen_secs(s) * SR)); buf = np.zeros(n, np.int16)
        if s["kind"] == "唱":
            a = int(s["t0"] * SR); seg = voc[a:a + n].copy()
            # 鏡頭用到的時間 (t1−t0) 之後 0.25 秒淡出，免得下一句的嘴型跑進來
            k = int((s["dur"]) * SR); f = int(0.25 * SR)
            if k < len(seg):
                seg[k:k + f] = (seg[k:k + f] * np.linspace(1, 0, len(seg[k:k + f]))).astype(np.int16); seg[k + f:] = 0
            buf[:len(seg)] = seg
        with wave.open(str(od / "guide.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(buf.tobytes())
    print(f"[guides] {len(only())} 鏡（唱 {sum(s['kind'] == '唱' for s in only())}）→ out/h3/<鏡>/guide.wav", flush=True)


# ------------------------------------------------------------------------------------------------ h3
def spec_of(s):
    h = CFG["h3"]; g = instruments()
    subs = []
    for k in s["refs"]:
        c = CHARS[k]; d = c["look"]
        if s["kind"] in ("唱", "奏", "手") and k in g:
            d += f", playing {g[k]}"
        subs.append(dict(key=k, desc=d, voice=c.get("h3_voice")))
    dlg = []
    if singer(s):
        others = [k for k in s["refs"] if k != singer(s)]
        dlg = [dict(subject=singer(s), line=lyric_text(s) or "啦啦啦", lang="Chinese", verb="sing together" if others else "sings",
                    after="When the singing stops the lips close and the performers keep playing.")]
        if others:
            dlg[0]["with"] = others                  # 合唱：tools/h3_shot.py 2026-10-29 起支援 "with"
    return dict(duration=round(gen_secs(s) - 0.02, 3), size=[1344, 768], seed=seed("h3_" + s["id"], h.get("default_seed", 20261029)),
                steps=14, draft=not hq(s),
                style=h["style"], setting=h["setting"], first_frame=str(OUT / "first" / f"{s['id']}.png"),
                subjects=subs, shots=[dict(camera=s.get("camera", h["camera"]), action=s["action"], dialogue=dlg)],
                constraints=h.get("constraints", []) + s.get("extra_constraints", []),
                soundscape=h["soundscape_sing"] if dlg else h["soundscape_silent"], music="N/A",
                audio={"fixed": {"file": str(OUT / "h3" / s["id"] / "guide.wav")}},
                **({"last_frame": str(OUT / "first" / f"{s['id']}.png")} if s.get("pin_last") else {}))   # 2026-10-30：H3 後段一直換景的鏡，把最後一幀也釘成首幀


def render_h3(dirs):
    if not dirs:
        return
    if H3_BACKEND == "colab":
        print(f"[h3] {len(dirs)} 鏡送到 Colab（cloud/colab_h3.py batch）", flush=True)
        # 一次上傳太大（65 鏡 108 MB）Colab 會回 500 → 每批 10 鏡（約 17 MB）分次送，同一台 VM 沿用（2026-10-29）
        n = int(os.environ.get("H3_CHUNK", "10"))
        for k in range(0, len(dirs), n):
            part = dirs[k:k + n]
            print(f"[h3] 第 {k // n + 1}/{(len(dirs) + n - 1) // n} 批：{' '.join(d.name for d in part)}", flush=True)
            # G4 配不到（Service Unavailable／開機失敗）時自動每 H3_RETRY_MIN 分鐘重試，最多 H3_RETRY_HOURS 小時；開不到不扣單元（2026-10-30）
            t_start = time.time(); tries = 0
            while True:
                tries += 1
                r = run([sys.executable, REPO / "cloud" / "colab_h3.py", "batch", "--h3-only", "--gpu", os.environ.get("COLAB_GPU", "G4")]
                        + [d / "spec.json" for d in part], check=False)
                out = r.stdout + r.stderr
                print(out[-1500:], flush=True)
                busy = r.returncode != 0 and ("Service Unavailable" in out or "開機失敗" in out)
                wait = float(os.environ.get("H3_RETRY_MIN", "10")); limit = float(os.environ.get("H3_RETRY_HOURS", "8"))
                if not busy or time.time() - t_start + wait * 60 > limit * 3600:
                    break
                print(f"[h3] {time.strftime('%H:%M')} G4 還沒有空（第 {tries} 次），{wait:.0f} 分鐘後自動重試；要停按 Ctrl+C", flush=True)
                time.sleep(wait * 60)
            if r.returncode != 0:
                sys.exit(f"[h3] 第 {k // n + 1} 批失敗（已完成的鏡頭會保留，重跑同一指令會從沒做的鏡頭繼續）")
    else:
        for d in dirs:
            run([PYH3, T / "h3_shot.py", d / "spec.json", "--out", d])


def h3():
    todo = []
    for s in only():
        od = OUT / "h3" / s["id"]
        if (od / "clip.mp4").exists():
            continue
        if not (OUT / "first" / f"{s['id']}.png").exists():
            sys.exit(f"[h3] {s['id']} 沒有首幀 out/first/{s['id']}.png")
        if not (od / "guide.wav").exists():
            sys.exit(f"[h3] {s['id']} 沒有 guide.wav：先跑 guides")
        (od / "spec.json").write_text(json.dumps(spec_of(s), ensure_ascii=False, indent=1), encoding="utf-8")
        todo.append(od)
    print(f"[h3] H3_BACKEND={H3_BACKEND}，要做 {len(todo)} 鏡：{' '.join(d.name for d in todo)}", flush=True)
    render_h3(todo)
    clips()


# ------------------------------------------------------------------------------------------------ 審片
def clips():
    from PIL import Image, ImageDraw
    rv = OUT / "review"; rv.mkdir(exist_ok=True); rows = []
    for s in SHOTS:
        c = OUT / "h3" / s["id"] / "clip.mp4"
        if not c.exists():
            continue
        d = min(dur(c), s["dur"]); tiles = []
        for q in (0.05, 0.25, 0.45, 0.65, 0.85, 0.98):
            raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{d * q:.2f}", "-i", str(c), "-frames:v", "1", "-vf", "scale=336:192",
                                  "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
            if len(raw) == 336 * 192 * 3:
                tiles.append(Image.frombytes("RGB", (336, 192), raw))
        im = Image.new("RGB", (336 * 6, 192))
        for i, t in enumerate(tiles):
            im.paste(t, (336 * i, 0))
        ImageDraw.Draw(im).text((6, 4), f"{s['id']} {s['kind']} {s['dur']}s", fill="yellow")
        im.save(rv / f"clips_{s['id']}.jpg", quality=82); rows.append(im)
    if rows:
        sh = Image.new("RGB", (336 * 6, 192 * len(rows)))
        for i, r in enumerate(rows):
            sh.paste(r, (0, 192 * i))
        sh.save(rv / "_all.jpg", quality=80)
    print("→ 人工檢查 out/review/clips_*.jpg：臉像不像、對嘴、手指、吉他琴頸、多出來的人", flush=True)


# ------------------------------------------------------------------------------------------------ 剪接
def ass_time(t):
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def cut():
    post = OUT / "post"; seg = post / "seg"; seg.mkdir(parents=True, exist_ok=True); parts = []
    miss = [s["id"] for s in SHOTS if not (OUT / "h3" / s["id"] / "clip.mp4").exists()]
    if miss:
        sys.exit(f"[cut] 還沒有 H3：{' '.join(miss)}")
    for s in SHOTS:
        src = OUT / "h3" / s["id"] / "clip.mp4"
        if UPSCALE == "flashvsr":
            fv = post / "vsr" / s["id"]
            if not (fv / "clip.mp4").exists() or (fv / "clip.mp4").stat().st_mtime < src.stat().st_mtime:
                run([PYH3, T / "flashvsr_cli.py", src, fv])
            src = fv / "clip.mp4"
        p = seg / f"{s['id']}.mp4"; nf = round(s["t1"] * FPS) - round(s["t0"] * FPS)   # 用累積幀數，接起來不漂移
        if not p.exists() or p.stat().st_mtime < max(src.stat().st_mtime, (HERE / "film.json").stat().st_mtime):
            slow = ""
            if s.get("src_max") and s["kind"] != "唱":   # 後段壞掉的鏡：只取前 src_max 秒，放慢填滿（2026-10-30）
                slow = f"trim=0:{s['src_max']},setpts=PTS*{nf / FPS / s['src_max']:.4f},"
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-an", "-vf",
                 f"{slow}scale=1920:1080:flags=lanczos,fps={FPS},tpad=stop_mode=clone:stop_duration=2,format=yuv420p",
                 "-frames:v", str(nf), "-c:v", "libx264", "-crf", "14", "-preset", "medium", p])
        parts.append(p)
    (post / "list.txt").write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", post / "list.txt", "-c", "copy", post / "video.mp4"])
    # 歌詞字幕：每鏡的 lyric；有「／」的兩句平分該鏡時間；括號（前奏、間奏）不上字幕
    hdr = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n\n[V4+ Styles]\n"
           "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
           "Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
           f"Style: lyr,{SUB_FONT_NAME},60,&H00FFFFFF,&H000000FF,&H00202020,&H80000000,-1,0,0,0,100,100,2,0,1,4,1,2,60,60,70,1\n"
           f"Style: title,{SUB_FONT_NAME},120,&H00FFFFFF,&H000000FF,&H00202020,&H80000000,-1,0,0,0,100,100,8,0,1,5,2,5,60,60,60,1\n")
    ev = "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    ev += f"Dialogue: 0,{ass_time(0.6)},{ass_time(4.0)},title,,0,0,0,,{{\\fad(600,500)}}{CFG['title']}\n"
    for s in SHOTS:
        txt = s.get("lyric", "")
        if not txt or txt.startswith("（"):
            continue
        ps = [x.strip() for x in txt.split("／")]; step = (s["t1"] - s["t0"]) / len(ps)
        for i, x in enumerate(ps):
            a = s["t0"] + i * step + 0.05; b = s["t0"] + (i + 1) * step - 0.08
            ev += f"Dialogue: 0,{ass_time(a)},{ass_time(b)},lyr,,0,0,0,,{x}\n"
    (post / "subs.ass").write_text(hdr + ev, encoding="utf-8")
    (OUT / "cut").mkdir(exist_ok=True)
    vt = dur(post / "video.mp4")
    if abs(vt - SHOTS[-1]["t1"]) > 0.2:              # 2026-10-30：有一鏡沒重剪，整段後面對不上歌
        sys.exit(f"[cut] 畫面 {vt:.2f} 秒 ≠ 鏡表 {SHOTS[-1]['t1']} 秒：有鏡頭長度不對（看 out/post/seg/），先修再剪")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", "post/video.mp4", "-i", HERE / CFG["song"],
         "-vf", f"subtitles=post/subs.ass,fade=t=in:st=0:d=0.6,fade=t=out:st={vt - 1.5:.2f}:d=1.5", "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-crf", "16", "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart",
         "-shortest", "cut/mv_1080p.mp4"])
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", OUT / "cut" / "mv_1080p.mp4", "-vf", "scale=1280:720", "-c:v", "libx264", "-crf", "26",
         "-c:a", "aac", "-b:a", "160k", OUT / "cut" / "mv_720p_phone.mp4"])
    print(f"成片 out/cut/mv_1080p.mp4（畫面 {vt:.2f} 秒，原曲 {dur(HERE / CFG['song']):.2f} 秒）", flush=True)


# ------------------------------------------------------------------------------------------------ 試映（分鏡草圖＋動態分鏡）
def storyboard():
    """每 16 鏡一張 16 宮格草圖的提示詞。shots 沒寫 panel 的用 note（中文）或 frame 前 25 字。"""
    pv = HERE / "preview"; pv.mkdir(exist_ok=True)
    cast = CFG.get("storyboard_cast", "")
    for k in range(0, len(SHOTS), 16):
        grp = SHOTS[k:k + 16]; rows = (len(grp) + 3) // 4; n = k // 16 + 1
        txt = (f"請用圖片生成工具畫一張橫式圖（〈{CFG['title']}〉MV 分鏡草圖第 {n} 張）：A film storyboard sheet: exactly 4 columns and {rows} rows "
               "of equal-sized horizontal 16:9 panels, separated by thin white gutters, read left to right, top to bottom. Rough pencil sketch with "
               "light watercolor tint, simple and clear staging, cinematic framing. Absolutely NO text, letters, numbers, logos or captions anywhere. "
               + (f"Exactly {len(grp)} panels; leave the remaining cells plain white. " if len(grp) % 4 else "") + cast + "\n"
               + "\n".join(f"Panel {i + 1} (row {i // 4 + 1}, column {i % 4 + 1}): {s.get('panel') or s.get('note') or s['frame'][:160]}" for i, s in enumerate(grp))
               + f"\n原檔存成 `{HERE.name}/preview/storyboard_{n}.png`（PNG），存完回報完整路徑。")
        (pv / f"sb_prompt_{n}.txt").write_text(txt, encoding="utf-8")
    print(f"→ preview/sb_prompt_1..{(len(SHOTS) + 15) // 16}.txt：請 ChatGPT 逐檔畫成 storyboard_<k>.png，再跑 preview", flush=True)


def preview():
    """草圖疊鏡號 → 每鏡一格 → 依原曲時間軸接成 preview/試映.mp4（原曲＋歌詞字幕）。"""
    import math
    from PIL import Image, ImageDraw, ImageFont
    pv = HERE / "preview"; (pv / "panels").mkdir(parents=True, exist_ok=True); fr = pv / "frames"; fr.mkdir(exist_ok=True)
    fonts = ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc", r"C:\Windows\Fonts\msjhbd.ttc",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]
    font = lambda z: next((ImageFont.truetype(f, z) for f in fonts if os.path.exists(f)), ImageFont.load_default())

    def tag(d, xy, t, f, fg=(255, 220, 0)):
        x0, y0, x1, y1 = d.textbbox(xy, t, font=f); p = max(4, (y1 - y0) // 4)
        d.rectangle((x0 - p, y0 - p, x1 + p, y1 + p), fill=(0, 0, 0)); d.text(xy, t, font=f, fill=fg)
    for k in range(math.ceil(len(SHOTS) / 16)):
        src = pv / f"storyboard_{k + 1}.png"
        if not src.exists():
            print("缺", src.name); continue
        grp = SHOTS[k * 16:(k + 1) * 16]; rows = math.ceil(len(grp) / 4)
        im = Image.open(src).convert("RGB"); cw, ch = im.width / 4, im.height / rows; lab = im.copy(); d = ImageDraw.Draw(lab)
        for i, s in enumerate(grp):
            x, y = (i % 4) * cw, (i // 4) * ch
            im.crop((int(x + cw * .025), int(y + ch * .025), int(x + cw * .975), int(y + ch * .975))).save(pv / "panels" / f"{s['id']}.png")
            tag(d, (int(x + cw * .04), int(y + ch * .04)), s["id"], font(max(14, im.width // 28)))
        lab.save(pv / f"storyboard_{k + 1}_label.png")
    W, H = 960, 540; lst = []
    for s in SHOTS:
        base = Image.new("RGB", (W, H), (20, 20, 20)); p = pv / "panels" / f"{s['id']}.png"
        if p.exists():
            im = Image.open(p).convert("RGB"); r = min(W / im.width, H / im.height)
            im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS); base.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
        d = ImageDraw.Draw(base); tag(d, (16, 14), f"{s['id']}  {s['dur']:.1f}s  {s['kind']}", font(34))
        cap = s.get("lyric", "")
        if cap:
            f = font(30); bw = d.textlength(cap, font=f); tag(d, (int((W - bw) / 2), H - 60), cap, f, (255, 255, 255))
        o = fr / f"{s['id']}.png"; base.save(o); lst.append(f"file '{o.as_posix()}'\nduration {s['t1'] - s['t0']:.3f}\n")
    lst.append(f"file '{(fr / (SHOTS[-1]['id'] + '.png')).as_posix()}'\n"); (fr / "list.txt").write_text("".join(lst), encoding="utf-8")
    run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", fr / "list.txt", "-i", HERE / CFG["song"], "-vf", "fps=24,format=yuv420p",
         "-c:v", "libx264", "-crf", "23", "-preset", "veryfast", "-c:a", "aac", "-shortest", pv / "試映.mp4"])
    print(f"→ preview/試映.mp4、storyboard_<k>_label.png（{len(SHOTS)} 鏡，最短 {min(s['dur'] for s in SHOTS)} 秒）", flush=True)


# ------------------------------------------------------------------------------------------------ ChatGPT 生圖提示詞與裁切
def prompts():
    """寫給 ChatGPT（工作模式、山獅霸生圖專案、綁 ~/AI/repo/pipeline）的提示詞檔。路徑都以片子資料夾名開頭。"""
    F = HERE.name; d = OUT / "chatgpt"; (d / "in").mkdir(parents=True, exist_ok=True)
    ins = CFG.get("instruments", {}); age = CFG.get("age_note", ""); ori = CFG.get("instrument_note", "")
    L = [f"〈{CFG['title']}〉MV 定妝照（寫實照片，逐張生成，每張都用圖片生成工具）。共同要求：Studio character reference photo, single person only, "
         "one image (not a collage), full-body standing front view, plain light grey seamless background, soft even studio light, realistic photograph, "
         "natural skin texture. No text, no letters, no logos, no watermark. Square 1:1 image.", ""]
    for i, (k, c) in enumerate(CHARS.items(), 1):
        ref = f"以 {F}/{c['ref']} 為臉部參考，臉型、五官、膚色、髮型與年紀要完全一樣（像同一個人）。外觀與服裝：" if c.get("ref") else "（無參考照）"
        L.append(f"{i}. {k}：{ref}{c['look']}。原檔存成 {F}/out/chatgpt/in/char_{k}.png")
    L.append("\n全部存完再一起回報完整路徑。不要修改任何其他檔案。")
    (d / "char_prompts.txt").write_text("\n".join(L), encoding="utf-8")
    M = [f"〈{CFG['title']}〉MV 場景母版（寫實照片，逐張生成；Wide landscape 16:9 image, no people, no text, no letters, no logos, no watermark）。", ""]
    M += [f"{i}. {k}：{p} 原檔存成 {F}/out/chatgpt/in/master_{k}.png" for i, (k, p) in enumerate(CFG["masters"].items(), 1)]
    M.append("\n全部存完再一起回報完整路徑。不要修改任何其他檔案。")
    (d / "master_prompts.txt").write_text("\n".join(M), encoding="utf-8")
    segs = {}
    for s in SHOTS:
        refs = [(f"{F}/out/chars/{k}.png", f"{CHARS[k]['name']}的定妝照（臉、髮型、服裝完全照這張）") for k in s["refs"]]
        if s["kind"] in ("唱", "奏", "手"):
            refs += [(f"{F}/{ins[k]['ref']}", f"{CHARS[k]['name']}的樂器外型（照這張；不要任何字或商標）")
                     for k in s["refs"] if isinstance(ins.get(k), dict) and ins[k].get("ref")]
        refs.append((f"{F}/out/masters/{s['scene'][0]}.png", "場景母版（只當場景與光線，不要沿用其中人物）"))
        if (HERE / "preview" / "panels" / f"{s['id']}.png").exists():
            refs.append((f"{F}/preview/panels/{s['id']}.png", "分鏡草圖（只參考構圖、站位與樂器方向）"))
        fr = s["frame"]
        for i, k in enumerate(s["refs"], 1):
            fr = fr.replace(f"<image{i}>", f"reference ({CHARS[k]['name']})")
        extra = ""
        if s["kind"] == "唱":
            extra += " The singer's mouth is clearly visible and slightly open, not covered by the microphone, hands or instrument."
        if s["kind"] in ("唱", "奏", "手") and any(k in instruments() for k in s["refs"]):
            extra += " " + ori
        if s["refs"]:
            extra += " " + age
        segs.setdefault(s["id"][0], []).extend([
            f"## {s['id']}（{s['kind']}，{s['dur']} 秒）", "參考圖：" + "；".join(f"{p} ＝ {t}" for p, t in refs),
            "提示詞：" + CFG["cine"] + fr + CFG.get("frame_suffix", "") + extra + " Wide landscape 16:9 photorealistic still, no letterbox bars.",
            f"存檔：{F}/out/chatgpt/in/first_{s['id']}.png", ""])
    for k, v in segs.items():
        head = (f"〈{CFG['title']}〉MV 首幀（段落 {k}）。逐鏡生成寫實照片，每鏡一張，都用圖片生成工具。每鏡都要先打開該鏡列出的參考圖：人物的臉、髮型、服裝、"
                "年紀要和定妝照完全一致；樂器照樂器參考圖；場景照場景母版。畫面不要有任何文字。全部存完再一起回報完整路徑，不要修改其他檔案。\n")
        (d / f"first_prompts_{k}.txt").write_text(head + "\n".join(v), encoding="utf-8")
    print(f"→ out/chatgpt/char_prompts.txt、master_prompts.txt、first_prompts_{'/'.join(segs)}.txt", flush=True)


def fit():
    """out/chatgpt/in/ 的原圖（比目標新才處理）→ 裁成流程尺寸；masters 有更新就重做 crops。"""
    inn = OUT / "chatgpt" / "in"; n = 0; mast = False
    for f in sorted(inn.glob("*.png")):
        m = re.match(r"(char|master|first)_(.+)\.png$", f.name)
        if not m:
            continue
        kind, name = m.groups(); dst = OUT / {"char": "chars", "master": "masters", "first": "first"}[kind] / f"{name}.png"
        if dst.exists() and dst.stat().st_mtime >= f.stat().st_mtime:
            continue
        run([sys.executable, REPO / "pipeline" / "chatgpt_img.py", "fit", f, f"{kind}:{name}"], cwd=HERE); n += 1; mast |= kind == "master"
    if mast:
        run([sys.executable, REPO / "pipeline" / "chatgpt_img.py", "crops"], cwd=HERE)
    if (OUT / "first").exists():
        run([sys.executable, REPO / "pipeline" / "chatgpt_img.py", "sheet"], cwd=HERE)
    print(f"[fit] 裁了 {n} 張；首幀總覽 out/first/_sheet.jpg", flush=True)


def check():
    """MV 版 preflight（../preflight.py 是給 make_film 用的）：有 ERROR 不准送 H3。"""
    from PIL import Image
    err, warn, short = [], [], []
    glob = json.dumps({k: CFG["h3"].get(k) for k in ("style", "setting", "camera", "constraints")}, ensure_ascii=False).lower()
    for k in CHARS:
        if k in glob or CHARS[k]["name"] in glob:
            err.append(f"h3 整片設定提到角色 {k}")
    prev = 0.0
    for s in SHOTS:
        i = s["id"]
        if abs(s["t0"] - prev) > 0.01: err.append(f"{i} 時間不連續（上一鏡結束 {prev}，本鏡開始 {s['t0']}）")
        prev = s["t1"]
        for k in s["refs"]:
            if k not in CHARS: err.append(f"{i} refs 有未定義角色 {k}")
        if s["scene"][0] not in CFG["masters"]: err.append(f"{i} 場景 {s['scene'][0]} 沒有母版")
        if s["kind"] == "唱" and not s["refs"]: err.append(f"{i} 是唱的鏡頭但沒有人")
        if s["dur"] > 12: err.append(f"{i} 超過 12 秒")
        if s["kind"] == "唱" and s["dur"] < 1.5: warn.append(f"{i} 唱的鏡只有 {s['dur']} 秒，對嘴看不出來，考慮併鏡")
        if s.get("src_max") and s["kind"] == "唱": err.append(f"{i} 唱的鏡不能用 src_max（放慢會對不上嘴）")
        if len(s["action"].split()) < 50:
            short.append(i)
        neg = re.findall(r"\b(backpacks?|bags?|phones?|hats?)\b", s["action"], re.I)
        if neg: warn.append(f"{i} 動作描述提到 {neg}：H3 會把它畫出來；不想要的東西別寫進 action")

        f = OUT / "first" / f"{i}.png"
        if not f.exists(): warn.append(f"{i} 沒有首幀")
        elif Image.open(f).size != (1344, 768): err.append(f"{i} 首幀尺寸 {Image.open(f).size} 不是 1344×768（用 chatgpt_img.py fit）")
    if "h3_quality" not in CFG:
        warn.append("film.json 沒寫 h3_quality（fast／faces／hq）：送 H3 前要先問使用者要加速還是不加速")
    if short:
        warn.append(f"{len(short)} 鏡 action 少於 50 字（{' '.join(short[:8])}…）：照官方寫法寫 50–120 字「Starting from <Picture 1>, …」，動作量約 2.7 倍")
    if instruments() and not CFG.get("instrument_note"):
        warn.append("有樂器但 film.json 沒寫 instrument_note（樂器方向），背對背、側身構圖容易被畫成左右顛倒")
    if abs(prev - dur(HERE / CFG["song"])) > 0.5: warn.append(f"鏡表總長 {prev} 秒 ≠ 原曲 {dur(HERE / CFG['song']):.2f} 秒")
    print("\n".join(["ERROR："] + [f"  ✗ {e}" for e in err] + ["WARN："] + [f"  ! {w}" for w in warn]))
    nh = sum(hq(s) for s in SHOTS); print(f"H3 品質：{CFG.get('h3_quality', 'fast')}（不加速 {nh} 鏡、加速 {len(SHOTS) - nh} 鏡）")
    print(f"{len(SHOTS)} 鏡；唱 {sum(s['kind'] == '唱' for s in SHOTS)}／奏 {sum(s['kind'] == '奏' for s in SHOTS)}／手 {sum(s['kind'] == '手' for s in SHOTS)}／景 {sum(s['kind'] == '景' for s in SHOTS)}")
    if err:
        sys.exit(1)


STAGES = dict(storyboard=storyboard, preview=preview, prompts=prompts, fit=fit, check=check, guides=guides, h3=h3, clips=clips, cut=cut)
if __name__ == "__main__":
    names = [a for a in sys.argv[1:] if a in STAGES]
    if not names:
        sys.exit(__doc__)
    print(f"[make_mv] H3_BACKEND={H3_BACKEND} UPSCALE={UPSCALE} ONLY={os.environ.get('ONLY', '')}", flush=True)
    for n in names:
        t0 = time.time(); STAGES[n](); print(f"[stage] {n} {time.time() - t0:.1f}s", flush=True)
