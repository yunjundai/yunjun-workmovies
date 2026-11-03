#!/usr/bin/env python3
"""山獅霸：ChatGPT 生圖輔助（不需 ComfyUI）。在片子資料夾（有 film.json 的那層）執行。
  plan [S1 S2 ...]        產生 out/plan/plan.md：每鏡一張規劃卡（主體定義／摘要／保留度／詳細描述／分鏡）
  prompts [S1 S2 ...]     產生 out/chatgpt/prompts.md：每張圖要貼給 ChatGPT 的提示詞＋要附的參考圖
  fit <原圖> <目標>        裁成目標比例再縮放，存到正確位置。目標：char:<角色> | master:<場景> | first:<鏡>
                          可加 --y 0.0~1.0（直向裁切位置，預設 0.4 偏上，避免切到頭）
  crops                   依 film.json 的 scene 框，從場景母版裁出 out/masters/crop_<鏡>.png
  sheet                   重做 out/first/_sheet.jpg（人工關卡 1）
"""
import json, sys, shutil, time
from pathlib import Path

HERE = Path.cwd(); OUT = HERE / "out"
CFG = json.loads((HERE / "film.json").read_text(encoding="utf-8"))
CHARS, SHOTS = CFG["chars"], CFG["shots"]
SIZE = {"char": (1024, 1024), "master": (2688, 1536), "first": (1344, 768)}
DIR = {"char": "chars", "master": "masters", "first": "first"}


def refs_of(s):
    """回傳 [(Picture 編號, 檔案, 說明, 保留什麼)]，順序＝要附給生圖工具的順序。"""
    R = []
    for k in s["refs"]:
        c = CHARS[k]
        R.append((f"out/chars/{k}.png", f"{c.get('name', k)}的定妝照",
                  f"完全保留臉型、髮型、服裝與年紀（{c['look']}）；只換姿勢、表情與位置"))
    if s.get("scene"):
        R.append((f"out/masters/crop_{s['id']}.png", f"場景「{s['scene'][0]}」本鏡景別的裁切",
                  "只當場景：保留建築、擺設、窗戶方向與光線；不要沿用圖中任何人物或文字"))
    return [(i, *r) for i, r in enumerate(R, 1)]


def card(s, for_gpt=False):
    """一鏡一張規劃卡：主體定義／摘要／保留度分析／詳細描述／分鏡。for_gpt＝直接貼給 ChatGPT 的版本。"""
    R = refs_of(s); ln = s.get("line") or {}
    who = CHARS.get(ln.get("who"), {}).get("name", ln.get("who", ""))
    desc = s["frame"]
    for i in range(9, 0, -1):
        desc = desc.replace(f"<image{i}>", f"<Picture {i}>")
    L = ["主體定義 (subject_definitions):"]
    L += [f"<Picture {i}> 是{d}。" + ("" if for_gpt else f"（{f}）") for i, f, d, _ in R] or ["（無參考圖）"]
    L += ["", "摘要 (summary):",
          f"{s['id']}，本鏡 {s.get('dur', '?')} 秒影片的「首幀」靜態畫面，16:9 橫幅。"
          + (f"{who}說：「{ln.get('text', '')}」" if ln else "無台詞。"),
          "", "保留度分析 (retention_analysis):"]
    L += [f"<Picture {i}>：{k}" for i, _, _, k in R] or ["（無）"]
    L += ["", "詳細描述 (detailed_description):", CFG["cine"].strip(), desc,
          CFG.get("frame_suffix", "No text, no watermark, no captions.").strip(),
          "Wide landscape 16:9 photorealistic still; keep every person fully inside the frame with headroom; "
          "no letterbox bars; no text anywhere."]
    if not for_gpt:
        L += ["", "分鏡 (shots，給 H3 動態用):", f"[Shot 1] 00:00–00:{float(s.get('dur', 0)):04.1f}　{s.get('action', '')}"]
        if ln: L += [f"台詞 @{ln.get('at', 0)}s（{who}）：{ln.get('text', '')}" + (f" / {ln['en']}" if ln.get("en") else "")]
    return "\n".join(L)


def plan(ids):
    L = [f"# {CFG.get('title', '')}：規劃卡（關卡 0，確認後才生圖）\n"]
    for s in SHOTS:
        if ids and s["id"] not in ids: continue
        L += [f"\n## {s['id']}\n\n```\n{card(s)}\n```\n"]
    d = OUT / "plan"; d.mkdir(parents=True, exist_ok=True)
    (d / "plan.md").write_text("".join(L), encoding="utf-8"); print("→", d / "plan.md")


def prompts(ids):
    L = [f"# {CFG.get('title', '')}：ChatGPT 生圖提示詞\n",
         "每張圖：開新對話 → 依 Picture 編號順序附上參考圖 → 貼整段提示詞 → 下載原圖 → `fit` 進流程。\n"]
    for k, c in CHARS.items():
        if ids and k not in ids: continue
        L += [f"\n## char:{k}（{c.get('name', k)}）→ out/chars/{k}.png　方形 1:1\n\n附圖：無\n\n```\n"
              "Studio character reference photo, single person only, one image (not a collage), medium close-up bust portrait facing the camera, "
              "plain light grey seamless background, soft even studio light, sharp focus, realistic photograph. " + c["look"] +
              ", gentle natural expression. No text, no watermark. Square 1:1 image.\n```\n"]
    for k, p in CFG.get("masters", {}).items():
        if ids and k not in ids: continue
        L += [f"\n## master:{k} → out/masters/{k}.png　橫幅 16:9\n\n附圖：無\n\n```\n{p} Wide landscape 16:9 image, no people.\n```\n"]
    for s in SHOTS:
        if ids and s["id"] not in ids: continue
        att = "、".join(f"Picture {i} = {f}" for i, f, _, _ in refs_of(s)) or "無"
        L += [f"\n## first:{s['id']} → out/first/{s['id']}.png　橫幅 16:9\n\n附圖（依序）：{att}\n\n```\n{card(s, True)}\n```\n"]
    d = OUT / "chatgpt"; d.mkdir(parents=True, exist_ok=True)
    (d / "prompts.md").write_text("".join(L), encoding="utf-8"); print("→", d / "prompts.md")


def fit(src, target, y=0.4):
    from PIL import Image
    kind, name = target.split(":", 1); W, H = SIZE[kind]
    im = Image.open(src).convert("RGB"); w, h = im.size; r = W / H
    if w / h > r:  # 太寬：左右置中裁
        nw = int(h * r); x0 = (w - nw) // 2; im = im.crop((x0, 0, x0 + nw, h))
    else:          # 太高：依 y 裁上下
        nh = int(w / r); y0 = int((h - nh) * y); im = im.crop((0, y0, w, y0 + nh))
    im = im.resize((W, H), Image.LANCZOS)
    dst = OUT / DIR[kind] / f"{name}.png"; dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():  # 舊圖備份，不覆蓋掉
        bk = OUT / f"{DIR[kind]}_bak"; bk.mkdir(exist_ok=True)
        shutil.move(str(dst), bk / f"{name}_{time.strftime('%m%d%H%M%S')}.png")
    im.save(dst); raw = OUT / "chatgpt" / "raw"; raw.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, raw / f"{kind}_{name}{Path(src).suffix}"); print("→", dst, im.size)


def crops():
    from PIL import Image
    for s in SHOTS:
        if not s.get("scene"): continue
        m, b = s["scene"]; im = Image.open(OUT / "masters" / f"{m}.png").convert("RGB"); W, H = im.size
        c = im.crop((int(b[0] * W), int(b[1] * H), int(b[2] * W), int(b[3] * H))); c.thumbnail((1344, 1344))
        c.save(OUT / "masters" / f"crop_{s['id']}.png")
    print("→ crops done")


def sheet(cols=3):
    from PIL import Image, ImageDraw
    fs = [(s["id"], OUT / "first" / f"{s['id']}.png") for s in SHOTS]; fs = [(i, p) for i, p in fs if p.exists()]
    tw, th = 448, 256; rows = (len(fs) + cols - 1) // cols
    sh = Image.new("RGB", (cols * tw, rows * th), "black"); d = ImageDraw.Draw(sh)
    for n, (i, p) in enumerate(fs):
        x, y = (n % cols) * tw, (n // cols) * th
        sh.paste(Image.open(p).convert("RGB").resize((tw, th)), (x, y)); d.text((x + 6, y + 4), i, fill="yellow")
    sh.save(OUT / "first" / "_sheet.jpg", quality=88); print("→", OUT / "first" / "_sheet.jpg", f"{len(fs)}/{len(SHOTS)} 鏡")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: sys.exit(__doc__)
    if a[0] == "plan": plan(a[1:])
    elif a[0] == "prompts": prompts(a[1:])
    elif a[0] == "fit":
        y = float(a[a.index("--y") + 1]) if "--y" in a else 0.4; fit(a[1], a[2], y)
    elif a[0] == "crops": crops()
    elif a[0] == "sheet": sheet()
    else: sys.exit(__doc__)
