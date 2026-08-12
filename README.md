# KubeRay Batch Inference

Distributed batch inference for Qwen2.5-0.5B using KubeRay, vLLM, and K3s across GPU workers.

## What it does

```bash
# Submit a batch job
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

# Poll for results
curl http://localhost:8000/v1/batches/{job_id} -H "X-API-Key: your-api-key"
```

Jobs fire immediately to vLLM via Ray Serve — no queuing, no cold starts. The model stays loaded in GPU memory. Results are persisted in Dragonfly (Redis-compatible) for 7 days.

## Architecture

- **Control plane**: K3s on Hetzner (utility-server) — runs ArgoCD, GPU API, Dragonfly, monitoring
- **GPU workers**: 2x RunPod instances, 2x RTX 5060 Ti each (4 GPUs total)
- **Networking**: Netbird VPN overlay — all K3s traffic goes through encrypted WireGuard tunnel
- **Model**: Qwen/Qwen2.5-0.5B-Instruct, always loaded in GPU memory (no cold starts)
- **GitOps**: ArgoCD with App of Apps pattern, 11 ApplicationSets

See [ARCHITECTURE.md](ARCHITECTURE.md) for diagrams.

## Components

| Component | What | Where |
|---|---|---|
| GPU API | Go REST API — auth, Prometheus metrics, fires jobs to Ray Serve | `gpu-api/` |
| RayService | Persistent vLLM cluster via KubeRay operator | `ansible/argocd/charts/raycluster/` |
| Dragonfly | Job persistence (DB 1) + Ray GCS fault tolerance (DB 0) | `ansible/argocd/charts/dragonfly/` |
| gpuscale | GPU node autoscaler — provisions GPU workers from spot providers, drains them when idle | `ansible/argocd/charts/gpuscale/` |
| Ansible | Infrastructure provisioning — base, VPN, NVIDIA, K3s, ArgoCD | `ansible/roles/` |
| Monitoring | Prometheus, Grafana, DCGM exporter, node-exporter | Deployed via ArgoCD |

## Choosing an execution path

The platform ships two ways to run inference, and they are independent:

| `gpu_execution_path` | What deploys | Shape |
|---|---|---|
| `ray` | KubeRay operator + RayCluster + the batch API | Ray Serve holds vLLM warm inside the cluster |
| `gpuscale` | the gpuscale controller | GPU nodes run an agent and vLLM directly, no Ray, no K3s on the node |
| `both` (default) | everything | side by side, for comparing them |

Set it in inventory or on the command line:

```bash
ansible-playbook ansible/plays/argocd.yml -e gpu_execution_path=gpuscale
```

It works by setting `directory.exclude` on the ApplicationSets bootstrap Application, so ArgoCD
simply never renders the manifests for the path you did not pick. Switching later is a re-run:
ArgoCD prunes what left the set and syncs what entered it.

## GPU autoscaling with gpuscale

`gpuscale` is deployed as part of this platform through ArgoCD. It watches for pending GPU
workloads, searches the configured providers for the cheapest offer that meets the requirement,
provisions the instance, waits for it to serve, and destroys it when demand goes.

```
ansible/argocd/applicationsets/gpuscale.yaml   ApplicationSet
ansible/argocd/charts/gpuscale/                Helm chart — CRDs, RBAC, controller Deployment
ansible/argocd/config/gpuscale/values.yaml     enabled providers and the node pools
```

Enable a provider in `config/gpuscale/values.yaml` and supply its credentials through
`existingSecret`. The chart renders two CRDs (`GPUNodePool`, `GPUNodeClaim`), a ClusterRole and
binding, a ServiceAccount and the controller Deployment.

The controller source and a standalone chart live in a separate repository:
**https://github.com/munhq/gpuscale**

## Docs

- [DEPLOYMENT.md](DEPLOYMENT.md) — deploy from scratch
- [ARCHITECTURE.md](ARCHITECTURE.md) — current system + future multi-datacenter vision
- [questions.md](questions.md) — technical Q&A (output format, storage, load balancing, KPIs, KubeRay integration)
- [decissions.md](decissions.md) — why K3s, why Ansible, why not Kueue, etc.
- [future.md](future.md) — scaling thoughts (Kueue, NATS, multi-cluster)
- [REQUIREMENTS_VALIDATION.md](REQUIREMENTS_VALIDATION.md) — how requirements map to implementation
- [gpu-api/README.md](gpu-api/README.md) — API reference
- [ansible/README.md](ansible/README.md) — playbook reference

## Repo structure

```
gpu-api/                  # Go REST API
  main.go, handlers.go, queue.go, store.go, metrics.go, rayclient.go, dashboard.html, Dockerfile

ansible/
  plays/                  # infrastructure.yml → platform.yml → argocd.yml
  roles/                  # base, netbird, nvidia_runtime, k3s_server, k3s_agent, argocd
  inventory/              # hosts, vault-encrypted secrets
  argocd/
    applicationsets/      # 11 ArgoCD ApplicationSet manifests
    charts/               # Custom Helm charts (gpu-api, raycluster, dragonfly)
    config/               # Helm values overrides per app
```

## Tech stack

K3s v1.35 / KubeRay v1.5.1 / vLLM via ray-llm:2.53.0 / Go 1.22 / Dragonfly v1.35 / Prometheus + Grafana / ArgoCD v2.13 / Ansible / Netbird VPN

## Metrics

`GET /metrics` exposes 10 Prometheus metrics: active jobs, job duration, inference duration, job status counts, HTTP latency, submission throughput, submissions by priority, token counts, tokens per request, batch size. Plus DCGM exporter for per-GPU memory/utilization/temperature.
