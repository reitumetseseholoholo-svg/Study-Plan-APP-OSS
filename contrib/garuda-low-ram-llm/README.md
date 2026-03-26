# Garuda / low-RAM host tuning (Ryzen APU + iGPU carve-out + Study Plan app)

This folder adds **optional** system-level guardrails so local LLM backends (Ollama, managed `llama-server`) are less likely to freeze Hyprland or trigger AMDGPU hard hangs on **~6 GiB usable RAM** laptops (e.g. 8 GiB soldered with ~2 GiB UMA for Vega).

The Study Plan app already picks **conservative `num_ctx`, batch, and thread hints** from `studyplan.ai.host_inference_profile` when RAM is tight. These host tweaks complement that.

## 1. Kernel command line (dracut + GRUB)

Garuda ships `/etc/dracut.conf.d/dracut-custom.conf` with an embedded `kernel_cmdline=...` used when images are built. Your **running** `/proc/cmdline` should stay **aligned** with that file after `sudo dracut-rebuild` (or Garuda’s equivalent), and with **`/etc/default/grub`** so the bootloader passes the same tuning after pivot.

Recommended goals for your class of machine:

| Parameter | Rationale |
|-----------|-----------|
| `amdgpu.noretry=0` | Fewer AMDGPU retry loops on allocation failure under RAM pressure (you already have this). |
| `amdgpu.gttsize=2048` | Matches a ~2 GiB GTT budget for Vega-class iGPU (already present). |
| `transparent_hugepage=madvise` | Lets the kernel use THP only when apps opt in; `always` can increase RAM churn on a small box. |
| `zswap.enabled=1 zswap.compressor=zstd zswap.max_pool_percent=20` | Compresses pages before they hit swap; **20%** is a bit gentler than **25%** on 8 GiB. |
| `split_lock_detect=off` | Avoids extra traps on misaligned atomics (common Zen-era advice for latency-sensitive workloads). |
| `sysrq_always_enabled=1` | Keeps **Alt+SysRq+REISUB** available if the desktop wedges. |

**Do not** duplicate conflicting values between dracut and GRUB—pick one source of truth and regenerate images + `grub-mkconfig`.

Garuda uses **`/etc/dracut.conf.d/dracut-custom.conf`** (there is no `custom.conf` by default). This repo does **not** ship a full replacement file (root UUID and Secure Boot paths are machine-specific).

Portable tuning tokens are in **`kernel-cmdline-studyplan-tuning.txt`**. The installer runs **`merge_kernel_cmdline.py`** to merge them into your **existing** `kernel_cmdline="..."` and **`GRUB_CMDLINE_LINUX_DEFAULT`**, replacing any conflicting `key=value` for the same key (for example `transparent_hugepage=always` becomes `madvise`).

See **`dracut-custom.conf.example`** for a minimal skeleton if you are building a drop-in from scratch.

### One-shot install (merge + sysctl + Ollama drop-in)

```bash
cd contrib/garuda-low-ram-llm
chmod +x install-garuda-host.sh merge_kernel_cmdline.py
./install-garuda-host.sh
sudo dracut-rebuild
sudo grub-mkconfig -o /boot/grub/grub.cfg
sudo reboot
```

### Dry-run (see merged cmdline without writing)

```bash
sudo python3 contrib/garuda-low-ram-llm/merge_kernel_cmdline.py \
  --repo contrib/garuda-low-ram-llm \
  --dry-run --dracut /etc/dracut.conf.d/dracut-custom.conf --grub /etc/default/grub
```

## 2. VM sysctl (must sort *after* Garuda’s `99-sysctl-garuda.conf`)

`systemd-sysctl` merges **all** `*.conf` files from `/usr/lib/sysctl.d/` and `/etc/sysctl.d/` sorted by **basename only**. Garuda sets `vm.swappiness=133` in `99-sysctl-garuda.conf`, which applies **after** any `99-studyplan-…` file. Use **`zz-studyplan-lowram.conf`** so your values win:

```bash
sudo cp contrib/garuda-low-ram-llm/sysctl.d/zz-studyplan-lowram.conf /etc/sysctl.d/
sudo sysctl --system
# verify:
sysctl vm.swappiness vm.min_free_kbytes vm.vfs_cache_pressure
```

## 3. Ollama memory ceiling (systemd)

`systemd/ollama.service.d/50-memory-ceiling.conf` sets **`MemoryHigh`** / **`MemoryMax`** on **`ollama.service`** so the daemon is **throttled or SIGKILL’d** before it takes the whole machine. Adjust `MemoryMax` if you need a little more headroom (e.g. 5–5.5 GiB for a 4 GiB GGUF + KV).

Install:

```bash
sudo install -d /etc/systemd/system/ollama.service.d
sudo cp contrib/garuda-low-ram-llm/systemd/ollama.service.d/50-memory-ceiling.conf /etc/systemd/system/ollama.service.d/
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

**Concurrency vs `MemoryMax`:** If the service exits when a load pushes RSS over the cgroup cap, that is expected—it protects the rest of the desktop from OOM. Prefer **smaller / fewer models**, lower **`num_ctx`**, and daemon limits over raising **`MemoryMax`**. The app defaults **parallel Ollama HTTP calls** from **host RAM pressure** (Preferences → *Max concurrent Ollama requests* `0` = automatic) and still honors **`STUDYPLAN_OLLAMA_MAX_CONCURRENT_REQUESTS`** / **`STUDYPLAN_OLLAMA_QUEUE_WAIT_SECONDS`** when set.

Optional Ollama env drop-in (one model in RAM, one parallel generation inside the daemon):

```bash
sudo cp contrib/garuda-low-ram-llm/systemd/ollama.service.d/60-ollama-concurrency.example.conf \
  /etc/systemd/system/ollama.service.d/60-ollama-concurrency.conf
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

Tune or add **`OLLAMA_KEEP_ALIVE`** there if you want weights unloaded sooner (shorter keep-alive → more churn but lower peak RSS).

The app can also request a shorter keep-alive per call via **`STUDYPLAN_OLLAMA_KEEP_ALIVE_SECONDS`** (0–3600). This is useful when you sometimes run **Ollama and managed `llama-server`** in the same session and want to reduce the chance both keep models resident.

## 4. earlyoom (kill heavy consumers before D-state wedges)

```bash
sudo pacman -S --needed earlyoom
sudo systemctl enable --now earlyoom
```

Optional: tune `/etc/default/earlyoom` (this repo ships an example in `earlyoom.default.snippet`).

## 5. CPU frequency governor (acpi-cpufreq / `amd_pstate=disable`)

With **`amd_pstate=disable`**, the driver is often **acpi-cpufreq**, which may **not** offer `schedutil` (only `performance`, `ondemand`, `userspace`). Pinning **`performance`** runs hotter and hits thermal limits faster on Ryzen **3700U**-class laptops.

- Prefer **`schedutil`** when `cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors` lists it.
- Otherwise use **`ondemand`** (ramps up for LLM bursts, idles cooler than `performance`).

Persistent **ondemand** (ships in this folder):

```bash
sudo cp contrib/garuda-low-ram-llm/systemd/system/set-cpufreq-ondemand.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now set-cpufreq-ondemand.service
```

If `schedutil` is available, `sudo pacman -S --needed cpupower` and `sudo cpupower frequency-set -g schedutil` (make persistent via `/etc/default/cpupower`) is fine too.

## 5b. IRQ balance (optional)

If `irqbalance` is installed but inactive, it can spread device interrupts across CPUs:

```bash
sudo systemctl enable --now irqbalance
```

On some Garuda images the unit is **masked** on purpose; leave it masked unless you know you want it (`systemctl is-masked irqbalance`).

## 6. BTRFS + large GGUF trees

For directories holding **multi-GB models**, disabling COW on that directory reduces metadata churn:

```bash
sudo mkdir -p /path/to/LLMs
sudo chattr +C /path/to/LLMs
```

(Ollama on Arch often uses `/var/lib/ollama`; for user mirrors under `$HOME`, run `chattr +C` on the **directory** before copying blobs.)

## 7. Hyprland (optional RAM shave)

```bash
hyprctl keyword decoration:blur:enabled false
```

## 8. Study Plan app env (optional)

- `OLLAMA_MODELS` – if your models live outside `~/.ollama/models`.
- `STUDYPLAN_OLLAMA_RAM_BUDGET_MB` – cap model auto-pick RAM (see `llama_runtime._get_ollama_ram_budget_bytes`).
- `STUDYPLAN_LLAMA_AUTO_HW_EXTRAS=0` – disable auto `--no-mmap` for `llama-server` if a given build misbehaves.

- RAM-pressure overrides (the app auto-tunes these defaults; set env vars to force a value):
  - `STUDYPLAN_LLAMA_SERVER_IDLE_SHUTDOWN_SECONDS` – stop managed `llama-server` sooner to free weights/KV under pressure.
  - `STUDYPLAN_PERFORMANCE_CACHE_MAX_SIZE` – smaller in-process perf cache when RAM is tight.
  - `STUDYPLAN_AI_TUTOR_RAG_MAX_SOURCES` and `STUDYPLAN_AI_TUTOR_RAG_MAX_PDF_MB` – fewer/smaller RAG snippets for tutor grounding.
  - `STUDYPLAN_AI_TUTOR_MAX_RESPONSE_CHARS` – cap streamed tutor response buffer to avoid large in-memory transcripts.

## 9. Managed `llama-server` from the GUI

The app starts `llama-server` as a **user** process; **`MemoryMax` on `ollama.service` does not apply** to it. Prefer smaller models, lower context in Preferences, or run heavy jobs from a TTY.

Optional hard cap (user session, transient scope):

```bash
systemd-run --user --scope -p MemoryHigh=3500M -p MemoryMax=4500M -- llama-server ...
```

The Study Plan app launches the server itself; there is no built-in `systemd-run` wrapper yet—set lower context in Preferences or use Ollama with the systemd drop-in above for the heaviest loads.

---

**Disclaimer:** Tuning is workload-specific. Keep a live USB handy; test after each change.
