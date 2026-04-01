#!/usr/bin/env bash
# Apply contrib/garuda-low-ram-llm tweaks (run from repo root or pass REPO=...).
set -euo pipefail
REPO="${REPO:-$(cd "$(dirname "$0")" && pwd)}"
MERGE="$REPO/merge_kernel_cmdline.py"
echo "Using REPO=$REPO"

if [[ ! -f "$MERGE" ]]; then
  echo "missing $MERGE" >&2
  exit 1
fi

if [[ ! -f /etc/dracut.conf.d/dracut-custom.conf ]]; then
  echo "No /etc/dracut.conf.d/dracut-custom.conf — install Garuda dracut config first" >&2
  echo "See dracut-custom.conf.example in this folder." >&2
  exit 1
fi

if [[ ! -f /etc/default/grub ]]; then
  echo "No /etc/default/grub — not a GRUB system?" >&2
  exit 1
fi

sudo cp -a /etc/dracut.conf.d/dracut-custom.conf \
  "/etc/dracut.conf.d/dracut-custom.conf.bak.$(date +%Y%m%d%H%M%S)"
sudo cp -a /etc/default/grub "/etc/default/grub.bak.$(date +%Y%m%d%H%M%S)"

sudo python3 "$MERGE" --repo "$REPO" \
  --dracut /etc/dracut.conf.d/dracut-custom.conf \
  --grub /etc/default/grub

sudo install -d /etc/systemd/system/ollama.service.d
sudo cp "$REPO/systemd/ollama.service.d/50-memory-ceiling.conf" /etc/systemd/system/ollama.service.d/
sudo cp "$REPO/sysctl.d/zz-studyplan-lowram.conf" /etc/sysctl.d/
sudo sysctl --system
sudo systemctl daemon-reload
sudo systemctl restart ollama || true

echo ""
echo "Merged low-RAM kernel tokens from kernel-cmdline-studyplan-tuning.txt into:"
echo "  /etc/dracut.conf.d/dracut-custom.conf"
echo "  /etc/default/grub"
echo ""
echo "Rebuild initramfs and GRUB (Garuda):"
echo "  sudo dracut-rebuild"
echo "  sudo grub-mkconfig -o /boot/grub/grub.cfg"
echo "Then reboot."
echo ""
echo "Optional: sudo pacman -S --needed earlyoom && sudo systemctl enable --now earlyoom"
echo "Dry-run merged cmdline:"
echo "  sudo python3 \"$MERGE\" --repo \"$REPO\" --dry-run \\"
echo "    --dracut /etc/dracut.conf.d/dracut-custom.conf --grub /etc/default/grub"
