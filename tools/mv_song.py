"""MV 歌曲分析（2026-10-30，由〈把青春唱成光〉整理）：分離人聲 → 聽寫歌詞時間 → 找間奏 → 依歌詞檔對齊 → 產生鏡表草稿。

在片子資料夾執行（需要 demucs、faster-whisper、librosa、soundfile；CPU 即可，4 分半的歌約 5–8 分鐘）：
  python ../../tools/mv_song.py assets/song.mp3 --lyrics assets/lyrics.txt [--model small] [--max-shot 4.5]

輸出：
  assets/vocals_48k.wav        對嘴用的乾淨人聲（48 kHz mono）→ film.json 的 "vocals"
  assets/song_analysis.json    全曲長度、BPM、人聲段落（whisper）、間奏（人聲空白 ≥1 秒）、對齊後的每句歌詞起訖
  preview/shots_draft.json     鏡表草稿：每句歌詞一鏡（太長自動拆）、間奏切成 ≤max-shot 秒的「景／奏／手」鏡
  preview/shots_draft.md       同上的表格，給人看

歌詞檔格式：一行一句；方括號行是段落標記，可寫唱者，例如
  [Verse 1 - Male Vocal]   [Female Vocal]   [Both Vocals]   [Instrumental Break]
標記裡有 Male → 男、Female → 女、Both／Duet → 男女，會帶到草稿的「唱者」欄（之後再改成角色 key）。
注意：whisper 對歌聲常聽錯同音字，這裡只用它的「時間」，文字一律用歌詞檔的。
"""
import argparse, difflib, json, re, subprocess, sys
from pathlib import Path


def sh(cmd):
    print("$", " ".join(map(str, cmd))[:160], flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


def norm(t):
    return re.sub(r"[^\w]", "", t.lower())


def parse_lyrics(p):
    lines, who, sect = [], "", ""
    for raw in Path(p).read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^\[(.*)\]$", s)
        if m:
            tag = m.group(1)
            if re.search(r"both|duet|choir", tag, re.I): who = "男女"
            elif re.search(r"female", tag, re.I): who = "女"
            elif re.search(r"male", tag, re.I): who = "男"
            elif re.search(r"instrument|intro|outro|break|solo|end", tag, re.I): who = ""
            if not re.match(r"^(male|female|both)", tag, re.I):
                sect = tag.split(" - ")[0]
            continue
        lines.append(dict(text=s, who=who, section=sect))
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("song"); ap.add_argument("--lyrics")
    ap.add_argument("--model", default="small"); ap.add_argument("--max-shot", type=float, default=4.5)
    ap.add_argument("--skip-sep", action="store_true", help="已經有 assets/vocals_48k.wav 就不重分離")
    a = ap.parse_args()
    song = Path(a.song).resolve(); here = Path.cwd(); assets = here / "assets"; pv = here / "preview"
    assets.mkdir(exist_ok=True); pv.mkdir(exist_ok=True)
    voc48 = assets / "vocals_48k.wav"

    # 1 分離人聲（demucs htdemucs，兩軌）
    if not (a.skip_sep and voc48.exists()):
        sh([sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", "htdemucs", "-o", assets / "sep", song])
        v = next((assets / "sep" / "htdemucs").glob("*/vocals.wav"))
        sh(["ffmpeg", "-loglevel", "error", "-y", "-i", v, "-ar", "48000", "-ac", "1", voc48])

    import librosa, numpy as np
    y, sr = librosa.load(str(song), sr=22050, mono=True)
    total = len(y) / sr
    tempo = float(np.atleast_1d(librosa.beat.beat_track(y=y, sr=sr)[0])[0])
    vy, _ = librosa.load(str(voc48), sr=16000, mono=True)
    # 2 間奏：人聲 RMS 低於門檻連續 ≥1 秒
    r = librosa.feature.rms(y=vy, frame_length=4000, hop_length=4000)[0]; act = r > 0.02; gaps = []; s0 = None
    for i, x in enumerate(list(act) + [True]):
        if not x and s0 is None: s0 = i
        if x and s0 is not None:
            if (i - s0) * 0.25 >= 1.0: gaps.append([s0 * 0.25, min(total, i * 0.25)])
            s0 = None
    # 3 聽寫時間（文字只參考）
    from faster_whisper import WhisperModel
    lyr = parse_lyrics(a.lyrics) if a.lyrics else []
    prompt = "繁體中文歌詞。"          # 不要把整段歌詞塞進 prompt：whisper 會照抄、時間亂掉（2026-10-30 實測）
    m = WhisperModel(a.model, device="cpu", compute_type="int8")
    segs = [dict(start=round(s.start, 2), end=round(s.end, 2), text=s.text.strip())
            for s in m.transcribe(vy, language="zh", vad_filter=True, initial_prompt=prompt, condition_on_previous_text=False)[0]]
    print(f"whisper {len(segs)} 段", flush=True)
    # 4 對齊（動態規劃，保持順序；歌詞與聽寫都去掉 oh/啊 等語助詞再比）。配不到的句子依字數在前後兩個已知時間之間分配
    def clean(t):
        return norm(re.sub(r"(?i)\boh\b|啊|喔|哦", "", t))
    n, m = len(lyr), len(segs)
    sim = [[difflib.SequenceMatcher(None, clean(l["text"]), clean(g["text"])).ratio() for g in segs] for l in lyr]
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]; bk = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        for j in range(m + 1):
            if i == 0 and j == 0: continue
            c = []
            if i: c.append((dp[i - 1][j], "L"))
            if j: c.append((dp[i][j - 1], "S"))
            if i and j and sim[i - 1][j - 1] >= 0.3: c.append((dp[i - 1][j - 1] + sim[i - 1][j - 1], "M"))
            dp[i][j], bk[i][j] = max(c)
    i, j = n, m
    while i or j:
        mv = bk[i][j]
        if mv == "M":
            l = lyr[i - 1]; l.update(t0=segs[j - 1]["start"], t1=segs[j - 1]["end"], match=round(sim[i - 1][j - 1], 2)); i, j = i - 1, j - 1
        elif mv == "L": i -= 1
        else: j -= 1
    k = 0
    while k < n:                                     # 連續一串沒配到的：依字數分配
        if lyr[k].get("t0") is not None:
            k += 1; continue
        e = k
        while e < n and lyr[e].get("t0") is None: e += 1
        a0 = lyr[k - 1]["t1"] if k else (gaps[0][1] if gaps and gaps[0][0] < 0.5 else 0.0)   # 開頭沒配到：從前奏結束開始
        b0 = lyr[e]["t0"] if e < n else total
        if b0 - a0 < 1.2 * (e - k) and k:            # 沒空間（whisper 把兩句聽成一段）：連前一句一起按字數重分
            k -= 1; a0 = lyr[k]["t0"]
        w = [max(1, len(clean(x["text"]))) for x in lyr[k:e]]; t = a0
        for x, ww in zip(lyr[k:e], w):
            d = (b0 - a0) * ww / sum(w); x.update(t0=round(t, 2), t1=round(t + d, 2), match=0, guess=True); t += d
        k = e
    # 5 鏡表草稿：歌詞鏡＝這句開始到下一句開始；中間空白 >1.5 秒的部分切成「景」鏡（≤max-shot 秒）；歌詞鏡 >6 秒拆成「唱＋景」
    shots = []

    def fill(t0, t1, sect):
        n = max(1, round((t1 - t0) / a.max_shot))
        for k in range(n):
            x0 = round(t0 + (t1 - t0) * k / n, 2); x1 = round(t0 + (t1 - t0) * (k + 1) / n, 2)
            shots.append(dict(t0=x0, t1=x1, dur=round(x1 - x0, 2), kind="景", who="", lyric="（間奏）", section=sect, guess=False))
    if lyr and lyr[0]["t0"] > 0.3:
        fill(0.0, lyr[0]["t0"], "Intro")
    for i, l in enumerate(lyr):
        nxt = lyr[i + 1]["t0"] if i + 1 < len(lyr) else total
        end = nxt if nxt - l["t1"] <= 1.5 else round(l["t1"] + 0.3, 2)
        n = max(1, round((end - l["t0"]) / 6.0))
        for k in range(n):
            x0 = round(l["t0"] + (end - l["t0"]) * k / n, 2); x1 = round(l["t0"] + (end - l["t0"]) * (k + 1) / n, 2)
            shots.append(dict(t0=x0, t1=x1, dur=round(x1 - x0, 2), kind="唱" if k == 0 else "景", who=l["who"] if k == 0 else "",
                              lyric=l["text"] if k == 0 else "（同上）", section=l["section"], guess=bool(l.get("guess"))))
        if end < nxt:
            fill(end, nxt, l["section"])
    shots = [x for x in shots if x["dur"] >= 0.3]
    for i, s in enumerate(shots, 1):
        s["id"] = f"S{i:02d}"
    json.dump(dict(song=str(song.name), duration=round(total, 2), bpm=round(tempo, 1), gaps=gaps, whisper=segs, lyrics=lyr),
              open(assets / "song_analysis.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(shots, open(pv / "shots_draft.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    f = lambda t: f"{int(t // 60)}:{t % 60:04.1f}"
    md = [f"# 鏡表草稿（{song.name}，{f(total)}，約 {tempo:.0f} BPM）", "",
          "間奏（人聲空白）：" + "、".join(f"{f(g[0])}–{f(g[1])}" for g in gaps), "",
          "| 鏡 | 時間 | 秒 | 類型 | 唱者 | 段落 | 歌詞 | 備註 |", "|---|---|---|---|---|---|---|---|"]
    md += [f"| {s['id']} | {f(s['t0'])}–{f(s['t1'])} | {s['dur']} | {s['kind']} | {s['who']} | {s['section']} | {s['lyric']} | {'⚠ 時間是推估，請聽過再定' if s['guess'] else ''}{' ⚠ 太短，建議併鏡' if s['dur'] < 1.5 else ''} |" for s in shots]
    (pv / "shots_draft.md").write_text("\n".join(md), encoding="utf-8")
    print(f"→ assets/vocals_48k.wav、assets/song_analysis.json、preview/shots_draft.md（{len(shots)} 鏡，{sum(l.get('guess', False) for l in lyr)} 句時間是推估）")


if __name__ == "__main__":
    main()
