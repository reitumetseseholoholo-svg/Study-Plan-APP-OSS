# Optional systemd user unit for fixed `llama-server`

## When you do **not** need this

The Study Plan app’s **managed** `llama-server` (`studyplan.ai.llama_server`) already:

- picks a GGUF from discovery,
- swaps models,
- can idle-stop to free RAM.

In that mode, **do not** run a parallel user service on the **same host/port** — disable managed server in Preferences or point the app at a **different** port if you insist on both.

## When this **is** useful

- You want **`llama-server` always running** with one known GGUF (e.g. for other clients or debugging).
- You want **`MemoryMax` / `MemoryHigh`** on the cgroup (similar idea to the Ollama system unit).
- You are OK maintaining **paths and flags** in an env file instead of the GUI.

## Install

```bash
mkdir -p ~/.config/studyplan
cp contrib/studyplan-llm-systemd/llama-server.env.example ~/.config/studyplan/llama-server.env
# Edit GGUF path, port, threads, ctx, etc.

cp contrib/studyplan-llm-systemd/user/llama-server-fixed.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now llama-server-fixed.service
```

Check: `curl -s http://127.0.0.1:8090/health` (or whatever `PORT` you set).

## App alignment

If this unit listens on **8090**, set the app to use **external** llama.cpp endpoint `http://127.0.0.1:8090/v1/chat/completions` and turn **off** managed `llama-server` in Preferences so only one process owns the port.

## Launching the app (system Python vs `.venv`)

The deployment script (`scripts/studyplan-update.sh`) generates a wrapper that **defaults to system `python3`**. This makes distro-packaged ML deps (for example `python-sentence-transformers` on Arch/AUR) work without recreating a `.venv`.

- Default: system Python
- Opt-in `.venv`: set `STUDYPLAN_USE_VENV=1` in the environment when launching

Examples:

```bash
studyplan-update            # wrapper uses system python3 by default
STUDYPLAN_USE_VENV=1 studyplan-update  # force .venv if present
```

### Fish helper (`studyupdate`)

If you use the Fish function `studyupdate` (commonly defined as a wrapper around `~/.local/bin/studyplan-update`), it supports a convenience flag:

- default: `studyupdate` (system Python default)
- opt-in `.venv`: `studyupdate --venv`

### Cloud-first behavior (internet-hosted endpoints)
When `STUDYPLAN_LLAMA_CPP_ENDPOINT` points to a non-local host, the app can try that endpoint *before* the managed `llama-server` + Ollama paths.
- `STUDYPLAN_CLOUD_LLAMACPP_PREFER_EXTERNAL` (default `1`)
- `STUDYPLAN_CLOUD_LLAMACPP_REQUEST_TIMEOUT_SECONDS` (default `8.0`)
- optional `STUDYPLAN_CLOUD_LLAMACPP_AUTH_BEARER` if your endpoint requires auth.

## Memory limits

Adjust `MemoryHigh` / `MemoryMax` in the unit for your RAM (same idea as `contrib/garuda-low-ram-llm/systemd/ollama.service.d/50-memory-ceiling.conf` for Ollama).
