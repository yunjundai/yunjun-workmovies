#!/usr/bin/env bash
# Colab VM 只有 113GB（原作者測到 236GB）裝不下完整版 → 分階段只裝當下要用的模型。（2026-10-13，Mac 版）
# 用法：bash phase_mac.sh img|music
set -u
AI=/content/AI; REPO=/content/repo; C=$AI/H3/ComfyUI-0.36.0; export UV_HTTP_TIMEOUT=300
log() { echo "[phase] $*"; }
dl() { for m in "$@"; do AI_ROOT=$AI python $REPO/setup/download.py $m > /content/dl_$(basename $m).log 2>&1 && log "model $(basename $m) OK" || { log "model $(basename $m) FAILED"; tail -3 /content/dl_$(basename $m).log; }; done; }
comfy_install() {
  if [ ! -f $C/main.py ]; then
    rm -rf /content/ComfyUI_src $C/custom_nodes/ComfyUI-FlashVSR_Ultra_Fast
    git clone -q --depth 1 --branch v0.37.0 https://github.com/comfyanonymous/ComfyUI /content/ComfyUI_src && mkdir -p $C && cp -rn /content/ComfyUI_src/. $C/ && rm -rf /content/ComfyUI_src
    grep -viE '^(torch|torchvision|torchaudio)([=<> ]|$)' $C/requirements.txt > /content/req_comfy.txt
    uv pip install --system -q -r /content/req_comfy.txt comfy-kitchen==0.2.35 && log "comfy OK" || log "comfy FAILED"
    sed "s#C:/AI/H3/models#$AI/H3/models#" $REPO/setup/extra_model_paths.yaml > $C/extra_model_paths.yaml
  fi
}
comfy_start() {
  pkill -f 'main.py --listen'; sleep 2
  (cd $C && nohup python main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch --preview-method none --fast fp16_accumulation > /content/comfy_0.log 2>&1 &)
  for t in $(seq 1 300); do curl -s -o /dev/null http://127.0.0.1:8188/system_stats && { log "comfy ready"; return; }; sleep 1; done; log "comfy start FAILED"; tail -20 /content/comfy_0.log
}
case "$1" in
  img)
    rm -f $AI/H3/models/diffusion_models/minimax_h3_* $AI/H3/models/text_encoders/qwen3vl_32b_* $AI/H3/models/vae/minimax_h3_* $C/models/loras/dmad_raw/*
    rm -rf $AI/BreezyVoice /content/repo.tgz /content/film.zip; uv cache clean -q 2>/dev/null; rm -rf /root/.cache/uv
    df -h /content | tail -1
    comfy_install
    dl $REPO/setup/downloads_qwen_image.json $REPO/setup/downloads_qwen_image_edit.json
    comfy_start ;;
  music)
    comfy_install
    rm -f $AI/H3/models/diffusion_models/minimax_h3_* $AI/H3/models/text_encoders/qwen3vl_32b_* $C/models/loras/dmad_*
    dl $REPO/setup/downloads_music3.json
    comfy_start ;;
esac
df -h /content | tail -1
echo PHASE_DONE
