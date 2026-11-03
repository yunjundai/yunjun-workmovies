# template_mv：歌曲 MV 範本（做新 MV 從這裡開始）

一首歌一個 `film.json`。**成片音軌＝原曲，畫面照歌曲時間軸接**；唱歌的鏡頭用原曲分離出的人聲當 H3 固定音軌來對嘴，不用配音、不用配樂。
首幀用 ChatGPT 桌面版生（skill：shanshiba-image-chatgpt），H3 在 Colab（或本機 NVIDIA）跑。

範例：`examples/把青春唱成光_film.json`（2026-10-29～30，70 鏡、4:33，成片在 `pipeline/youth_mv/`）。`film.json` 是它的前 5 鏡，當欄位示範。

和劇情片範本（`template_local/make_film.py`）的差別：沒有台詞配音、配樂、片尾、旁白；多了「歌曲分析 → 鏡表草稿」「依歌曲時間軸剪接」「歌詞字幕」。

---

## 流程總覽（每一步後面是人工關卡）

| # | 做什麼 | 指令／工具 | 約多久 |
|---|---|---|---|
| 0 | 複製範本、放素材 | `cp -R template_mv <片名>`（Windows 見下方 PowerShell 對照）；`assets/song.mp3`、`assets/lyrics.txt`、`refs/` 人物與樂器照 | 1 分 |
| 1 | 歌曲分析＋鏡表草稿 | `python ../../tools/mv_song.py assets/song.mp3 --lyrics assets/lyrics.txt` | 5–8 分 |
| 2 | 寫鏡表、元素聖經 → **使用者確認** | 從 `preview/shots_draft.md` 改成 `film.json` 的 `shots` | — |
| 3 | 分鏡草圖＋試映 → **使用者說「通過」** | `make_mv.py storyboard` → ChatGPT 畫 → `make_mv.py preview` | 20 分 |
| 4 | 定妝照、場景母版、首幀 | `make_mv.py prompts` → ChatGPT 逐檔生成 → `make_mv.py fit` | 1.5–3 小時 |
| 5 | **關卡 1** 首幀總覽 | 看 `out/first/_sheet.jpg` | — |
| 6 | 送 H3 前檢查＋對嘴音軌 | `make_mv.py check guides` | 1 分 |
| 7 | 試跑 5 鏡 | `ONLY="…" $PY_H3 make_mv.py h3` | 10–15 分 |
| 8 | 整批 | `$PY_H3 make_mv.py h3` | 70 鏡約 1.5 小時 |
| 9 | **關卡 2** 審片、重做 | 看 `out/review/_all.jpg`，壞的移走重跑 | 每輪 15–20 分 |
| 10 | 剪接成片 → **關卡 3 使用者看片** | `make_mv.py cut` | 5 分 |

### Windows（PowerShell）指令對照
上表與下文的指令是 Mac 寫法。Windows 在 PowerShell 照這樣打（repo 預設放 `C:\AI\repo`，H3 環境在 `C:\AI\H3`，見 `docs/06_安裝.md`）：

```powershell
# 每次開 PowerShell 先設好（本機 H3 用 H3 環境的 Python；只用 Colab 的話設成 python 即可）
$env:PY_H3 = "C:\AI\H3\venv\Scripts\python.exe"

# 0. 開新片
cd C:\AI\repo\pipeline
Copy-Item -Recurse template_mv my_song
cd my_song
New-Item -ItemType Directory -Force assets, refs | Out-Null
Copy-Item <歌>.mp3 assets\song.mp3

# 1. 歌曲分析
python ..\..\tools\mv_song.py assets\song.mp3 --lyrics assets\lyrics.txt

# 3–4. 試映、生圖
python make_mv.py storyboard
python make_mv.py preview
python make_mv.py prompts
python make_mv.py fit

# 6. 檢查＋對嘴音軌
& $env:PY_H3 make_mv.py check guides

# 7. 試跑 5 鏡（ONLY 用完要清掉，不然之後整批也只跑這幾鏡）
$env:ONLY = "A01 B03 C05 D02 D09"
& $env:PY_H3 make_mv.py h3
Remove-Item Env:ONLY

# 8. 整批（加速或不加速由 film.json 每鏡的 hq／h3_quality 決定，和 Mac 相同）
& $env:PY_H3 make_mv.py h3

# 10. 剪接
python make_mv.py cut

# Colab 跑完才需要
& $env:PY_H3 ..\..\cloud\colab_h3.py stop
```

Windows 和 Mac 不一樣的地方：
- **H3 在哪跑會自動判斷**：有 16 GB 以上 NVIDIA 顯卡（`nvidia-smi` 抓得到）就在本機跑，要先開 ComfyUI（`C:\AI\tools\start_comfy.cmd`）；沒有就送 Colab。要強制指定：`$env:H3_BACKEND = "colab"` 或 `"local"`。
- 本機跑 H3 時整台電腦記憶體很緊（16 GB 顯卡＋32 GB 記憶體），生成時把瀏覽器、ChatGPT 都關掉；先生完首幀再跑 H3。
- 防止睡眠：設定 → 系統 → 電源 → 睡眠設成「永不」，或用 PowerToys Awake（Mac 的 `.command` 不能用）。
- 字幕字型自動用微軟正黑體；路徑 `/` 或 `\` 程式都接受。
- ChatGPT Windows 桌面版的專案要綁 `C:\AI\repo\pipeline`，提示詞檔裡的路徑才對得上。
- 環境變數用 `$env:名稱 = "值"` 設定，只在這個 PowerShell 視窗有效；關掉重開要重設。

### 0. 開新片
```
cd ~/AI/repo/pipeline && cp -R template_mv my_song && cd my_song
mkdir -p assets refs && cp <歌>.mp3 assets/song.mp3
```
歌詞存成 `assets/lyrics.txt`：一行一句，方括號行是段落與唱者標記（`[Verse 1 - Male Vocal]`、`[Female Vocal]`、`[Both Vocals]`、`[Instrumental Break]`）。從 Word 檔轉：`python3 -c "import zipfile,re;…"`（見 docs/08）。

### 1. 歌曲分析（`tools/mv_song.py`）
需要 `demucs faster-whisper librosa soundfile`（CPU 即可；Mac 沒裝就在雲端或任何有 Python 的機器跑，產出放回 `assets/`、`preview/`）。
產生：`assets/vocals_48k.wav`（對嘴用人聲）、`assets/song_analysis.json`（BPM、間奏、每句時間）、`preview/shots_draft.md/json`（鏡表草稿）。
- whisper 對歌聲常聽錯字，**只取時間，文字一律用歌詞檔**。
- 草稿裡「⚠ 時間是推估」的句子（whisper 漏聽，多半在橋段、和聲、Oh Oh Oh）要聽過再定；「⚠ 太短」的鏡建議併鏡。

### 2. 鏡表（`film.json` 的 `shots`）
每鏡：`id`（A01…，第一個字母＝段落，ChatGPT 提示詞按段落分檔）、`t0`、`t1`、`dur`、`kind`、`lyric`、`refs`、`scene`、`frame`、`action`；可選 `panel`、`camera`、`extra_constraints`、`pin_last`、`src_max`。
- `kind`：**唱**（對嘴，給原曲人聲）｜**奏**（彈奏不唱，靜音）｜**手**（手部特寫，靜音）｜**景**（回憶／空景，靜音）。
- 時間要首尾相接、總長＝原曲（`check` 會擋）。單鏡 ≤12 秒；唱的鏡 ≥1.5 秒（太短看不出對嘴）。
- `lyric` 裡用「／」分兩句時，字幕會平分該鏡時間；括號開頭（`（間奏）`）不上字幕。
- 同一個人換服裝（演出服／制服）＝另一個角色 key，命名 `<人>_<服裝>`（例 `boy_uni`），會自動沿用同一把樂器。

### 3. 試映
`storyboard` 寫 `preview/sb_prompt_<k>.txt`（每 16 鏡一張）→ ChatGPT 讀檔畫成 `preview/storyboard_<k>.png` → `preview` 疊鏡號、做 `preview/試映.mp4`（原曲＋歌詞字幕）。草圖格子之後也會當首幀的構圖參考（`preview/panels/<鏡>.png`）。

### 4. ChatGPT 生圖
`prompts` 寫三種提示詞檔（路徑都以片子資料夾名開頭，ChatGPT 專案綁 `~/AI/repo/pipeline`）：
`out/chatgpt/char_prompts.txt`（定妝照，附 refs 人物照）→ `master_prompts.txt`（場景，無人）→ `first_prompts_<段>.txt`（首幀，自動列出定妝照、樂器照、場景母版、分鏡格當參考）。
在 ChatGPT 每個檔開一個新工作，送一句「請讀取 <檔>，依照裡面的說明逐張生成，照『存檔』路徑存 PNG，全部存完再回報」。每張約 2 分鐘。
生完 `make_mv.py fit`（只處理比目標新的原圖、自動 crops、重做 `_sheet.jpg`）。重生某張：讓 ChatGPT 覆蓋 `out/chatgpt/in/first_<鏡>.png` 再 `fit`。

### 6–9. H3
- **開工前一定要先問使用者：加速還是不加速**（使用者 2026-10-30 指定），寫進 `film.json` 的 `h3_quality`：

  | 選項 | 內容 | 70 鏡約多久（Colab G4 兩台） |
  |---|---|---|
  | `fast` | 全部加速（DMAD 4 步），單鏡約 1 分鐘 | 約 40 分鐘 |
  | `faces` | 唱的鏡不加速（14 步，臉、眼睛較穩），其他加速 | 約 1 小時 |
  | `hq` | 全部不加速，單鏡約 2–2.5 分鐘 | 約 1.5 小時 |

  單鏡可用 `"hq": true/false` 覆寫（重做眼睛壞掉的鏡就設 true）。`check` 會印出各幾鏡。

- `$PY_H3 make_mv.py check guides`：ERROR 一定要先修。
- 試跑挑 5 鏡，每種風險一鏡：手部特寫、單人唱、最短的唱、合唱、多人動作。
- G4 配不到（Service Unavailable）時程式會自動每 10 分鐘重試、最多 8 小時（`H3_RETRY_MIN`、`H3_RETRY_HOURS`），開不到不扣單元；貼一次指令、開著「防止睡眠」放著就好。Colab 不能選機房，G4 只分到美國／荷蘭；台灣白天、週末較好排。
- Colab：每批 10 鏡上傳（`H3_CHUNK`），只裝 H3（約 4 分鐘）。做完一批會先存回，失敗重跑同一指令會接著做。閒置約 20 分鐘 VM 會被收回；整批跑完記得 `$PY_H3 ../../cloud/colab_h3.py stop`。
- 審片看 `out/review/_all.jpg`（每鏡 6 格，只抽會用到的秒數）。重做：`clip.mp4` 移到 `out/h3_bad_<時間>/`、`seeds` 加 `"h3_<鏡>"`、`ONLY="…"` 重跑。

### 10. 剪接
`make_mv.py cut` → `out/cut/mv_1080p.mp4`、`mv_720p_phone.mp4`。片名在開頭 0.6–4 秒，開頭淡入、結尾淡出。改了 `film.json`（例如 `src_max`）會自動重剪那一鏡。

---

## 一定要做的事（〈把青春唱成光〉踩過的雷）

**鏡表與描述**
1. `action` 不要寫不想出現的東西：寫了「背包晃動」H3 就會把背包加回來（A10）。
2. 有樂器一定要寫 `instrument_note`（琴頭朝畫面哪一邊、哪隻手按弦）。背對背、側身的構圖最容易被畫成左右顛倒（B06、D06）；首幀附分鏡格當參考。
3. 小孩角色加 `age_note`：ChatGPT 生回憶鏡時會把小學生畫成國中生（A07、A12）。
4. ChatGPT 會擋「小孩受傷＋大人碰觸」的畫面，改成不涉及受傷的動作（B16：跌倒被扶 → 老師比讚鼓勵）。
5. 舞台、屋頂這種背景空曠的近景，背景留越多空間 H3 越會自己加人；唱歌近景讓臉佔大部分畫面、背景虛化（C05）。

**H3**
5-1. `action` 寫 50–120 個英文字（上游 2026-10-23 規則）：「Starting from <Picture 1>, …」首幀定錨 → 動作開始 → 持續發展 → 結果，寫哪個身體部位動、幅度、次數（"strums down-up about twice per second"），不寫 energetic 這類抽象詞。一句話版動作量只有約 1/2.7——〈把青春唱成光〉solo 段「沒有 solo 的感覺」就是這個原因。限制條件盡量寫成正面描述（"the camera stays still" 比一串 no/never 好）。
6. H3 常在鏡頭後段自己換景、拉遠或有人從畫面邊緣進來（70 鏡中約 15 鏡）。`h3.constraints` 預設就有「一鏡到底、不准有東西從邊緣進來」。
7. 同一鏡重抽 2 次還壞：唱的鏡用 `"pin_last": true`（最後一幀也釘成首幀，C05 這樣才穩）；不唱的鏡用 `"src_max": 秒數`（只取前段乾淨的部分放慢填滿，B14、D09）。不要一直重抽。
8. 合唱鏡（`refs` 兩人、`kind` 唱）會用 `tools/h3_shot.py` 的 `with`，兩人嘴都會動，實測可用。
9. 手部特寫常在後段拉遠露臉：`extra_constraints` 寫「全程維持特寫、不拉遠、不露臉」。

**Colab／環境**
10. Colab 上傳一次超過約 100 MB 會回 500：程式包已排除 `pipeline/` 素材（`cloud/colab_h3.py`），H3 工作分批 10 鏡。
11. MV 不需要語音、配樂、放大模型：`--h3-only`。完整安裝在 Colab 曾失敗（breeze／comfy FAILED）。
12. Colab 會開在美國／歐盟機房（MiniMax H3 授權排除地區），程式會提示，要不要跑由使用者決定。

**ChatGPT 操作**（細節見 skill shanshiba-image-chatgpt）
13. 會碰到使用上限；額度用完先停，跟使用者說，不要一直重試。
14. 背景輸入常送不出去：用全螢幕控制打字＋Enter。生成中按「停止」常無效，要改指示用「引導」。
16. 運鏡途中模糊、眼睛變形：提高幀數（60 幀）沒用；要嘛不加速（`hq`）、要嘛讓臉在畫面裡大一點、加「鏡頭不動、不拉近」。〈把青春唱成光〉B01、B22、D15 就是這樣修。
15. 一次給一個提示詞檔、它會逐鏡做完；中途斷線要重送時明講「從 Cxx 開始，前面的不要重做」，不然它會從頭覆蓋。
