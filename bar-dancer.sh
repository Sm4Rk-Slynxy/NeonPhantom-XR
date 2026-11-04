#!/usr/bin/env bash
# Transparent desktop overlay. The script execs mpv so the server owns its real PID.
set -euo pipefail
FILE="${1:?usage: bar-dancer.sh <video.webm> [height_px] [bl|br|tl|tr]}"
H="${2:-480}"
CORNER="${3:-br}"
[[ "$H" =~ ^[0-9]+$ ]] && (( H >= 160 && H <= 1600 )) || { echo 'Height must be 160–1600 px.' >&2; exit 1; }
case "$CORNER" in br|bl|tr|tl) ;; *) echo 'Invalid corner.' >&2; exit 1;; esac
command -v mpv >/dev/null || { echo 'Install mpv to play desktop videos.' >&2; exit 1; }
[[ -f "$FILE" ]] || { echo 'Video file does not exist.' >&2; exit 1; }
[[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] || { echo 'No desktop session. Start deskdanced from a terminal on your desktop.' >&2; exit 1; }
umask 077
BUNDLE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PLAYER_DIR="${XDG_RUNTIME_DIR:+$XDG_RUNTIME_DIR/neonphantom-xr}"
PLAYER_DIR="${PLAYER_DIR:-$BUNDLE_DIR/.runtime}"
mkdir -p -- "$PLAYER_DIR"
chmod 700 -- "$PLAYER_DIR"
IPC="${DESKDANCE_IPC:-$PLAYER_DIR/player.sock}"
# Preserve the clip aspect ratio rather than forcing every video into 9:16.
W=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$FILE" | python3 -c 'import sys; w,h=map(int,sys.stdin.read().strip().split("x")); print(max(2,round(w*int(sys.argv[1])/h)))' "$H")
case "$CORNER" in
  br) GEOMETRY="${W}x${H}-24-80";; bl) GEOMETRY="${W}x${H}+24-80";;
  tr) GEOMETRY="${W}x${H}-24+24";; tl) GEOMETRY="${W}x${H}+24+24";;
esac
EXTRA_ARGS=()
if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] && command -v hyprctl >/dev/null; then
  # Monitor coordinates are logical pixels; account for scaling and monitor origins.
  read -r SW SH MX MY < <(hyprctl monitors -j | python3 -c 'import json,sys; ms=json.load(sys.stdin); m=next((m for m in ms if m.get("focused")),ms[0]); print(round(m["width"]/m.get("scale",1)),round(m["height"]/m.get("scale",1)),m.get("x",0),m.get("y",0))')
  read -r W H < <(python3 -c 'import sys; w,h,sw,sh=map(int,sys.argv[1:]); fit=min(1,(sw-48)/w,(sh-100)/h); print(max(2,round(w*fit)),max(2,round(h*fit)))' "$W" "$H" "$SW" "$SH")
  X=24; Y=24
  [[ "$CORNER" == *r ]] && X=$((SW-W-24))
  [[ "$CORNER" == b* ]] && Y=$((SH-H-80))
  X=$((X+MX)); Y=$((Y+MY))
  GEOMETRY="${W}x${H}+${X}+${Y}"
  # Support the legacy windowrulev2 and newer match:title syntax.
  rule() {
    local legacy="$1" modern="$2" response
    response=$(hyprctl keyword windowrulev2 "$legacy,title:^(mpv-dancer)$" 2>&1) || true
    if [[ "$response" != "ok" ]]; then
      response=$(hyprctl keyword windowrule "$modern, match:title ^(mpv-dancer)$" 2>&1) || true
      [[ "$response" == "ok" ]] || { echo "Hyprland could not install overlay rules: $response. See BUNDLE-README.md." >&2; exit 1; }
    fi
  }
  rule float 'float on'
  rule pin 'pin on'
  rule noborder 'border_size 0'
  rule noinitialfocus 'no_initial_focus on'
  rule "size $W $H" "size $W $H"
  rule "move $X $Y" "move $X $Y"
elif [[ -n "${WAYLAND_DISPLAY:-}" && -z "${DISPLAY:-}" ]]; then
  echo 'This Wayland compositor needs its own overlay window rules; Hyprland and composited X11 are supported by this launcher.' >&2
  exit 1
elif [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
  # GNOME/KDE Wayland cannot position arbitrary native windows. Use XWayland.
  EXTRA_ARGS=(--vo=gpu --gpu-context=x11egl --gpu-api=opengl)
fi
exec mpv --no-config --title=mpv-dancer --loop-file=inf --no-border --no-osc \
  --ontop --no-audio --background=none --background-color='#00000000' --vd=libvpx-vp9 --hwdec=no \
  --input-ipc-server="$IPC" --geometry="$GEOMETRY" "${EXTRA_ARGS[@]}" "$FILE"
