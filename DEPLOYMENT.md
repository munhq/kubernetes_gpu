# Deployment Guide

How to deploy and verify the KubeRay batch inference stack.

## Architecture

```
User → GPU API (Go, port 8000)
         │
         ├── POST /v1/batches → fire goroutine → HTTP to Ray Serve → vLLM → results
         ├── GET /v1/batches/{id} → read from memory (in-flight) or Dragonfly (completed)
         ├── GET / → embedded web dashboard
         └── GET /metrics → Prometheus metrics
         │
         ▼
   RayService (persistent, warm)
   Head: serve HTTP proxy :8000, dashboard :8265
   Workers: 2 GPU nodes × 2 GPUs each, vLLM continuous batching
   Model: Qwen/Qwen2.5-0.5B-Instruct (always loaded in GPU memory)
```

## Prerequisites

- K3s cluster with GPU nodes (deployed via `ansible-playbook plays/platform.yml`)
- ArgoCD installed and syncing (deployed via `ansible-playbook plays/argocd.yml`)
- All ApplicationSets healthy: `kubectl get applications -n argocd`

## Deploy

Everything deploys via ArgoCD from a single command:

```bash
cd ansible
ansible-playbook plays/all.yml --vault-password-file .vault_pass
```

This runs infrastructure → platform → argocd in order (~30 minutes total). ArgoCD then auto-syncs all applications.

## Verify

### Cluster

```bash
kubectl get nodes                     # 3 nodes Ready
kubectl get pods -n gpu-workloads     # Ray head, 2 workers, GPU API, Dragonfly
kubectl get rayservice -n gpu-workloads  # raycluster-batch-inference RUNNING
```

### GPU API

```bash
kubectl port-forward svc/gpu-api -n gpu-workloads 8000:8000

# Health check
curl http://localhost:8000/health/deep

# Dashboard
open http://localhost:8000/
```

### Submit a test job

```bash
curl -X POST http://localhost:8000/v1/batches \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "model": "Qwen/Qwen2.5-0.5B-Instruct",
    "input": [
      {"prompt": "What is 2+2?"},
      {"prompt": "Explain quantum computing in one sentence"}
    ],
    "max_tokens": 50
  }'
```

Returns: `{"job_id": "...", "status": "RUNNING", "priority": "medium"}`

Poll for results:

```bash
curl http://localhost:8000/v1/batches/{job_id} -H "X-API-Key: your-api-key"
```

### Auth test

```bash
# No key — 401
curl -s -X POST http://localhost:8000/v1/batches \
  -H "Content-Type: application/json" \
  -d '{"input":[{"prompt":"test"}]}'

# Wrong key — 401
curl -s -X POST http://localhost:8000/v1/batches \
  -H "Content-Type: application/json" \
  -H "X-API-Key: wrong" \
  -d '{"input":[{"prompt":"test"}]}'
```

### Load test

```bash
GPU_API_KEY=your-key python3 scripts/test_gpu_api_load.py
```

99 concurrent jobs, expects all to succeed.

## Dashboards

### GPU API Dashboard
```bash
kubectl port-forward svc/gpu-api -n gpu-workloads 8000:8000
# http://localhost:8000/
```

### Grafana
```bash
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80
# http://localhost:3000 — admin / admin
```

### Ray Dashboard
```bash
kubectl port-forward -n gpu-workloads svc/raycluster-batch-inference-head-svc 8265:8265
# http://localhost:8265
```

### ArgoCD
```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
kubectl port-forward -n argocd svc/argocd-server 8080:443
# https://localhost:8080 — admin / (password from above)
```

## Troubleshooting

**API not responding**: Check `kubectl logs -n gpu-workloads -l app=gpu-api --tail=100`. Usually means Ray Serve isn't ready yet — vLLM takes a minute to load the model.

**Ray Serve not starting**: Check head pod logs. Usually a GPU scheduling issue — verify `kubectl describe nodes | grep -A5 nvidia.com/gpu` shows available GPUs.

**VPN issues**: `ansible all -i inventory/main/hosts -m shell -a "netbird status"`. If a node dropped off the VPN, the K3s agent loses contact with the server.

**ArgoCD not syncing**: Check `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller`. Usually a GitHub App auth issue.

**Nuclear option**: `ansible-playbook plays/all.yml --vault-password-file .vault_pass`
