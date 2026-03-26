#!/usr/bin/env bash
# Copy model trees into fresh +C directories so existing files get NODATACOW extents (Btrfs).
# Requires enough free space (~1x tree size) during the copy phase.
set -euo pipefail

RSYNC=(rsync -aHAX --numeric-ids)

repack_owned_dir() {
  local SRC="$1"
  [[ -d "$SRC" ]] || { echo "Skip (missing): $SRC"; return 0; }
  if [[ -z "$(find "$SRC" -mindepth 1 -print -quit 2>/dev/null)" ]]; then
    chattr +C "$SRC" 2>/dev/null || true
    echo "Skip (empty): $SRC"
    return 0
  fi

  local parent STAGE NEWDIR BAK
  parent=$(dirname -- "$SRC")
  STAGE=$(mktemp -d "${parent}/.repack_stage_XXXXXX")
  NEWDIR="${STAGE}/newroot"
  mkdir -p "$NEWDIR"
  chattr +C "$NEWDIR"
  echo "Repacking (this may take a while): $SRC"
  "${RSYNC[@]}" --info=progress2 "$SRC/" "$NEWDIR/"
  BAK="${SRC}.bak.$$"
  mv "$SRC" "$BAK"
  mv "$NEWDIR" "$SRC"
  chattr +C "$SRC"
  rm -rf "$BAK"
  rmdir "$STAGE" 2>/dev/null || rm -rf "$STAGE"
  echo "Finished: $SRC"
  lsattr -d "$SRC"
}

repack_root_dir() {
  local SRC="$1"
  sudo test -d "$SRC" || { echo "Skip (missing): $SRC"; return 0; }
  if ! sudo find "$SRC" -mindepth 1 -print -quit 2>/dev/null | grep -q .; then
    sudo chattr +C "$SRC" 2>/dev/null || true
    echo "Skip (empty): $SRC"
    return 0
  fi
  local parent STAGE
  parent=$(dirname -- "$SRC")
  STAGE=$(sudo mktemp -d "${parent}/.repack_stage_XXXXXX")
  local NEWDIR="${STAGE}/newroot"
  sudo mkdir -p "$NEWDIR"
  sudo chattr +C "$NEWDIR"
  echo "Repacking (sudo): $SRC"
  sudo "${RSYNC[@]}" --info=progress2 "$SRC/" "$NEWDIR/"
  local BAK="${SRC}.bak.$$"
  sudo mv "$SRC" "$BAK"
  sudo mv "$NEWDIR" "$SRC"
  sudo chattr +C "$SRC"
  sudo rm -rf "$BAK"
  sudo rmdir "$STAGE" 2>/dev/null || sudo rm -rf "$STAGE"
  echo "Finished: $SRC"
  sudo lsattr -d "$SRC"
}

echo "Stopping ollama / llama-server (if any)…"
systemctl stop ollama 2>/dev/null || true
sleep 1
pkill -x llama-server 2>/dev/null || true
pkill -x ollama 2>/dev/null || true
sleep 1
if pidof ollama >/dev/null 2>&1 || pidof llama-server >/dev/null 2>&1; then
  echo "Refusing: ollama or llama-server still running. Close the Study Plan app / stop services and retry." >&2
  exit 1
fi

repack_owned_dir "${HOME}/.ollama/models"
repack_owned_dir "${HOME}/.local/share/nomic.ai/GPT4All"
repack_root_dir "/var/lib/ollama"

echo "All repacks complete."
