# KubeRay Batch Inference

Distributed batch inference system using KubeRay, vLLM, and K3s on GPU workers.

## Quick Start

```bash
# Submit batch inference job
curl -X POST http://localhost:8000/v1/batches \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "model": "Qwen/Qwen2.5-0.5B-Instruct",
    "input": [
      {"prompt": "What is 2+2?"},
      {"prompt": "Hello world"}
    ],
    "max_tokens": 50
  }'

# Check job status
curl http://localhost:8000/v1/batches/{job_id} \
  -H "X-API-Key: your-api-key"
```

## Architecture

- **Control Plane**: K3s server on Hetzner (utility-server)
- **GPU Workers**: 2x RunPod instances (4 GPUs total, RTX 4060 Ti / 5060 Ti)
- **Networking**: Netbird VPN overlay for pod-to-pod communication
- **GitOps**: ArgoCD with App of Apps pattern
- **Model**: Qwen/Qwen2.5-0.5B-Instruct via Ray Serve + vLLM
- **API**: Go service with priority queue, API key authentication, and Prometheus metrics

## Components

| Component | Purpose | Location |
|-----------|---------|----------|
| **gpu-api** | REST API for batch job submission | `gpu-api/` |
| **RayService** | Persistent vLLM inference cluster | `argocd/charts/raycluster/` |
| **Ansible** | Infrastructure provisioning | `ansible/` |
| **ArgoCD** | GitOps application deployment | `argocd/` |
| **Monitoring** | Prometheus, Grafana, DCGM | Deployed via ArgoCD |

## Documentation

- **[SETUP.md](SETUP.md)** - Step-by-step deployment instructions
- **[questions.md](questions.md)** - Technical Q&A addressing architecture decisions
- **[DECISIONS.md](DECISIONS.md)** - Architecture evolution and trade-offs
- **[architecture.md](architecture.md)** - System architecture overview
- **[gpu-api/README.md](gpu-api/README.md)** - API reference and configuration
- **[ansible/README.md](ansible/README.md)** - Ansible playbook reference

## Key Features

✅ **API Key Authentication** - X-API-Key header validation
✅ **Priority Queue** - High/medium/low priority job ordering
✅ **Persistent vLLM** - No cold starts, model stays warm
✅ **Job Persistence** - Redis/Dragonfly for job state across API restarts
✅ **Prometheus Metrics** - 8 metrics for monitoring queue depth, latency, GPU utilization
✅ **GitOps** - Full declarative infrastructure via ArgoCD
✅ **GPU Monitoring** - DCGM exporter + Grafana dashboards

## Repository Structure

```
.
├── gpu-api/              # Go REST API
│   ├── main.go
│   ├── handlers.go       # API endpoints
│   ├── queue.go          # Priority queue + job dispatcher
│   ├── store.go          # Redis persistence
│   └── Dockerfile
├── ansible/              # Infrastructure as Code
│   ├── plays/            # Playbooks (infrastructure → platform → argocd)
│   ├── roles/            # Ansible roles (base, k3s, netbird, nvidia)
│   └── inventory/        # Server IPs, credentials (vault)
├── argocd/
│   ├── applicationsets/  # ArgoCD ApplicationSet definitions
│   ├── charts/           # Helm charts (raycluster, dragonfly, kueue-setup)
│   └── config/           # Helm values per application
├── questions.md          # Technical architecture Q&A
├── DECISIONS.md          # Why we chose this architecture
└── SETUP.md              # Deployment guide
```

## Tech Stack

- **K3s** (v1.35) - Lightweight Kubernetes
- **KubeRay** (v1.2.2) - Ray on Kubernetes
- **vLLM** (via ray-llm:2.53.0-py311-cu128) - LLM inference engine
- **Go** (1.22) - API service
- **Dragonfly** (v1.35) - Redis-compatible in-memory store
- **Prometheus + Grafana** - Monitoring stack
- **ArgoCD** (v2.13) - GitOps deployment
- **Ansible** - Infrastructure automation
- **Netbird** - VPN overlay network

## Metrics

Exposed at `GET /metrics`:

- `gpu_api_queue_depth` - Jobs waiting in queue
- `gpu_api_gpus_active` - Concurrent inference slots in use
- `gpu_api_job_duration_seconds` - End-to-end inference time
- `gpu_api_jobs_by_status_total` - Success/failure counts
- `gpu_api_queue_wait_seconds` - Time from enqueue to dispatch

See [questions.md](questions.md) for complete KPI analysis.

## License

MIT
