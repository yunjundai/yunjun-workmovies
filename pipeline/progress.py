#!/usr/bin/env python3
"""山獅霸進度表：看 voices → h3 跑到哪。
用法（另開一個終端機視窗，不影響正在跑的那個）：
  python3 ~/AI/repo/pipeline/progress.py toilet toilet_human          # 看一次
  python3 ~/AI/repo/pipeline/progress.py toilet toilet_human --watch  # 每 30 秒更新，Control+C 離開
"""
import json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def bar(p, w=24):
    n = int(round(p * w))
    return "█" * n + "░" * (w - n) + f" {p * 100:5.1f}%"


def status(name):
    d = ROOT / name; out = d / "out"
    cfg = json.loads((d / "film.json").read_text(encoding="utf-8"))
    shots = cfg["shots"]; lines = [s for s in shots if s.get("line")]
    nL, nS, nC = len(lines), len(shots), len(cfg["chars"])
    v = out / "voice"
    # 1 Breeze：角色聲音＋每句參考音
    breeze = sum(1 for f in v.glob("tw_*.wav") if f.stat().st_size > 0) + sum(1 for k in cfg["chars"] if (v / f"ref_{k}.wav").exists())
    p1 = min(breeze / (nL + nC), 1.0)
    # 2 BreezyVoice：每句 8 個候選
    cands = len(list((v / "bv" / "cand").glob("line*_s*.wav"))) if (v / "bv" / "cand").exists() else 0
    p2 = min(cands / (nL * 8), 1.0)
    # 3 自動挑音
    p3 = 1.0 if (out / "voice_picks.json").exists() else (0.5 if (v / "bv" / "picks.json").exists() else 0.0)
    # 4 H3 影片
    clips = sum(1 for s in shots if (out / "h3" / s["id"] / "clip.mp4").exists())
    specs = sum(1 for s in shots if (out / "h3" / s["id"] / "spec.json").exists())
    p4 = clips / nS
    total = 0.10 * p1 + 0.55 * p2 + 0.05 * p3 + 0.30 * p4
    if p4 >= 1:
        now = "H3 完成，請看 out/review/clips_*.jpg（關卡 2）"
    elif specs:
        now = f"H3：Colab 生成中（{clips}/{nS} 鏡完成）"
    elif p3 >= 1:
        now = "配音完成，準備送 H3"
    elif p2 > 0:
        now = f"BreezyVoice 配音候選 {cands}/{nL * 8}"
    elif p1 > 0:
        now = f"Breeze 設計聲音／參考音 {breeze}/{nL + nC}"
    else:
        now = "尚未開始"
    return [f"【{name}】{cfg.get('title', '')}",
            f"  整體      {bar(total)}",
            f"  1 聲音設計 {bar(p1)}",
            f"  2 配音候選 {bar(p2)}",
            f"  3 自動挑音 {bar(p3)}",
            f"  4 H3 影片  {bar(p4)}",
            f"  目前：{now}"]


if __name__ == "__main__":
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or ["toilet"]
    watch = "--watch" in sys.argv
    while True:
        rows = [time.strftime("%H:%M:%S 更新")]
        for n in names:
            try:
                rows += status(n)
            except Exception as e:
                rows.append(f"【{n}】讀不到：{e}")
        if watch:
            print("\033[2J\033[H", end="")
        print("\n".join(rows), flush=True)
        if not watch:
            break
        time.sleep(30)
