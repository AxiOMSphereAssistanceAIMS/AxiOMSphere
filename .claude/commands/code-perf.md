# AIMS — Code Performance (VRAM · GPU · Throughput · Bottleneck)

Profile target: **$ARGUMENTS**

---

## Phase 0 — Parse request

From `$ARGUMENTS` determine:
- **target**: service name, script path, or "system" (full stack)
- **focus**: `vram` | `gpu` | `cpu` | `latency` | `throughput` | `all` (default)
- **mode**: `snapshot` (current state) | `profile` (run under profiler) | `benchmark`

---

## Phase 1 — VRAM / GPU snapshot

```bash
# GPU utilisation and VRAM
nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.free,memory.total \
  --format=csv,noheader,nounits 2>/dev/null

# Models currently loaded in Ollama (VRAM consumers)
curl -s http://localhost:11434/api/ps 2>/dev/null | python3 -m json.tool

# Total VRAM budget check (max 107.5 GB usable on DGX Spark)
nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | \
  awk '{s+=$1} END {print "Total VRAM: " s " MiB (" s/1024 " GiB)"}'
```

---

## Phase 2 — Process / CPU profiling

```bash
# CPU and memory by process
ps aux --sort=-%cpu | grep -E "python|ollama|uvicorn" | grep -v grep | head -15

# I/O wait (detect DB or disk bottleneck)
iostat -x 1 3 2>/dev/null | tail -20

# Python profiling (wrap target script)
# python3 -m cProfile -s cumulative ops/<script>.py 2>&1 | head -40
```

---

## Phase 3 — Latency profiling (DocAgent pipeline)

```bash
cd /home/axi_omi_sphere/aims-workspace

# Time a test generation request end-to-end
time curl -sf -X POST http://localhost:8082/v1/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer aims-local-repair-token" \
  -d '{"model":"aims-repairman-nemotron","max_tokens":100,"messages":[{"role":"user","content":"ping"}]}' \
  2>&1 | python3 -m json.tool | head -20

# Gateway request timing histogram (from logs)
docker logs aims-gateway --since 1h 2>/dev/null | grep "duration" | tail -20
```

---

## Phase 4 — Throughput benchmark

```bash
# Ollama generate tokens/s
curl -s -X POST http://localhost:11434/api/generate \
  -d '{"model":"axi_omi_sphere","prompt":"Hello","stream":false}' \
  2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
tps = d.get('eval_count',0) / max(d.get('eval_duration',1) / 1e9, 0.001)
print(f'Tokens/s: {tps:.1f}')
print(f'Total tokens: {d.get(\"eval_count\",0)}')
print(f'Load time: {d.get(\"load_duration\",0)/1e9:.2f}s')
"
```

---

## Phase 5 — Bottleneck classification and recommendations

| Bottleneck | Symptoms | Recommendation |
|------------|----------|----------------|
| VRAM OOM | OOMKilled, model unload | Unload slot 120 before slot 32; check VRAM budget |
| GPU underutilised | util <30% during generation | Check batch size, concurrent requests |
| CPU bottleneck | python CPU 100%, GPU idle | Pre-tokenise offline; use streaming |
| I/O bottleneck | high iowait, slow DB | WAL mode on SQLite; Qdrant on SSD |
| Network latency | slow PC Andrei fallback | Check 10GbE cable; use local first |
| Model cold start | first request always slow | Keep model warm via periodic ping |

---

## Phase 6 — Output contract

```json
{
  "target": "$ARGUMENTS",
  "focus": "vram|gpu|cpu|latency|throughput|all",
  "vram_used_gb": 0.0,
  "vram_free_gb": 0.0,
  "gpu_util_pct": 0.0,
  "tokens_per_sec": null,
  "p50_latency_ms": null,
  "bottleneck": "<vram|gpu|cpu|io|network|none>",
  "recommendations": ["<action>"],
  "slot_used": "32"
}
```
