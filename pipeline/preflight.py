#!/usr/bin/env python3
"""山獅霸：送 H3／整批製作前的檢查（2026-10-23，《我弄髒廁所了》事故後新增）。
在片子資料夾執行：python3 ../preflight.py
檢查 film.json 的「元素」是否清楚、是否符合流程前提，並建議先試跑的 3 鏡。
有 ERROR 就不要整批跑。
"""
import json, re, sys
from pathlib import Path

HERE = Path.cwd(); OUT = HERE / "out"
CFG = json.loads((HERE / "film.json").read_text(encoding="utf-8"))
CH, SH = CFG["chars"], CFG["shots"]
err, warn, ok = [], [], []
CREATURE = re.compile(r"\b(sprite|fairy|creature|mascot|monster|robot|animal|cartoon|animated)\b", re.I)


def kind(k):  # live＝真人；animated＝動畫／非人角色合成；voice＝只有聲音
    c = CH[k]
    if c.get("kind"):
        return c["kind"]
    return "animated" if CREATURE.search(c.get("look", "")) else "live"


def words(k):
    c = CH[k]; w = {k, c.get("name", "")}
    m = re.match(r"\s*([A-Z][a-z]+)", c.get("look", ""))
    if m: w.add(m.group(1))
    return {x for x in w if x}


# 0 元素清單
print(f"《{CFG.get('title', HERE.name)}》元素清單")
for k in CH:
    on = [s["id"] for s in SH if k in s["refs"]]
    talk = [s["id"] for s in SH if (s.get("line") or {}).get("who") == k]
    vo = [s for s in talk if s not in on]
    print(f"  角色 {k}（{CH[k].get('name', '')}）類型={kind(k)}｜入鏡 {len(on)} 鏡｜說話 {len(talk)} 句" + (f"｜旁白 {vo}" if vo else ""))
print(f"  場景 {list(CFG.get('masters', {}))}｜鏡頭 {len(SH)}｜有台詞 {sum(1 for s in SH if s.get('line'))}")

# 1 整片共用文字（每鏡都會讀）不能提到任何角色
glob = json.dumps({k: CFG.get("h3", {}).get(k) for k in ("style", "setting", "soundscape", "constraints", "camera")}, ensure_ascii=False)
for k in CH:
    hit = [w for w in words(k) if re.search(re.escape(w), glob, re.I)]
    if hit:
        err.append(f"h3 整片設定提到角色 {k}：{hit} → 會讓 H3 每鏡都畫出這個角色，改放到有他的鏡頭的 extra_constraints")
if CREATURE.search(glob):
    err.append(f"h3 整片設定出現非人角色字眼「{CREATURE.search(glob).group(0)}」→ 移到該角色入鏡的鏡頭")
for k in ("cine", "frame_suffix"):
    if CREATURE.search(CFG.get(k, "")):
        warn.append(f"{k} 出現「{CREATURE.search(CFG[k]).group(0)}」，會套到每張首幀")

# 2 每鏡元素一致
mf = (HERE / "make_film.py").read_text(encoding="utf-8") if (HERE / "make_film.py").exists() else ""
vo_ok = 'ln["who"] in s["refs"]' in mf
for s in SH:
    sid = s["id"]
    for k in s["refs"]:
        if k not in CH: err.append(f"{sid} refs 有未定義角色 {k}")
    if s.get("scene") and s["scene"][0] not in CFG.get("masters", {}):
        err.append(f"{sid} 場景 {s['scene'][0]} 沒有母版")
    ln = s.get("line")
    if ln:
        if ln["who"] not in CH:
            err.append(f"{sid} 說話者 {ln['who']} 未定義")
        elif ln["who"] not in s["refs"]:
            (ok if vo_ok else err).append(f"{sid} 是旁白（{ln['who']} 不在畫面）" + ("，make_film 已支援" if vo_ok else " → make_film.py 不支援，H3 會 KeyError"))
    absent = [k for k in CH if kind(k) != "live" and k not in s["refs"]]
    ex = " ".join(s.get("extra_constraints", []))
    if absent and not re.search(r"\bno\b.*(sprite|fairy|creature|character)", ex, re.I):
        warn.append(f"{sid} 沒有 {absent} 但沒寫「不准出現」限制，H3 可能自己加進來")
    f = OUT / "first" / f"{sid}.png"
    if not f.exists():
        warn.append(f"{sid} 還沒有首幀 out/first/{sid}.png")

# 3 程式本身
if not mf:
    err.append("片子資料夾沒有 make_film.py；不要用 make-film 快捷指令（它固定跑 template_local），請用 $PY_H3 make_film.py")
else:
    ok.append("請用 `$PY_H3 make_film.py …` 執行（make-film 快捷指令固定指向 template_local）")

# 4 建議試跑 3 鏡：非人角色入鏡／完全沒有非人角色／旁白
def first(pred):
    return next((s["id"] for s in SH if pred(s)), None)
nonlive = [k for k in CH if kind(k) != "live"]
pilot = [x for x in dict.fromkeys([
    first(lambda s: any(k in s["refs"] for k in nonlive) and s.get("line")),
    first(lambda s: s["refs"] and not any(k in s["refs"] for k in nonlive) and s.get("line")),
    first(lambda s: s.get("line") and s["line"]["who"] not in s["refs"]),
]) if x]

print("\n".join(["", "ERROR（要先修）："] + [f"  ✗ {e}" for e in err] + ["WARN（請確認）："] + [f"  ! {w}" for w in warn] + ["OK："] + [f"  ✓ {o}" for o in ok]))
print(f"\n建議先試跑：ONLY=\"{' '.join(pilot)}\" $PY_H3 make_film.py h3   → 看 out/review/clips_*.jpg 沒問題再整批")
sys.exit(1 if err else 0)
