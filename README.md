# kubernetes_gpu

kubernetes_gpu deploys an LLM inference API on your own GPUs. The API service itself lives in [munhq/gpu-api-ray](https://github.com/munhq/gpu-api-ray); this repo is the Kubernetes setup that deploys it. Submit a job over HTTP and fetch the result. A dashboard, per-GPU metrics and autoscaling are included.

Put your hosts in `ansible/inventory/main/hosts`, copy
`group_vars/all/vault.yml.example` to `vault.yml`, fill it in and encrypt it.
Then, from `ansible/`:

```bash
cd ansible
ansible-playbook plays/all.yml --vault-password-file .vault_pass
```

`all.yml` imports the two stages, and either runs on its own:

```bash
ansible-playbook plays/infrastructure.yml   # hosts → K3s + NVIDIA runtime + Netbird
ansible-playbook plays/platform.yml         # cluster services, then ArgoCD takes over
```

Then:

```bash
curl -X POST http://<host>:8000/v1/batches \
  -H "Content-Type: application/json" -H "X-API-Key: $KEY" \
  -d '{"model":"Qwen/Qwen2.5-0.5B-Instruct","input":[{"prompt":"What is 2+2?"}],"max_tokens":50}'

curl http://<host>:8000/v1/batches/{job_id} -H "X-API-Key: $KEY"
```

Jobs run against a model that is already resident in GPU memory — no queue and no cold start. Results persist in Dragonfly for 7 days.

## What the playbooks install

- **An OpenAI-shaped batch API** with API-key auth, on port 8000, with a dashboard UI.
- **A warm vLLM cluster** — the model stays loaded, so submitted work starts immediately.
- **Per-GPU metrics** — DCGM exporter gives memory, utilisation and temperature per card; the API exposes 10 Prometheus metrics of its own; Grafana dashboards ship with it.
- **Autoscaling** — Ray Serve holds each model between `minReplicas` and `maxReplicas` and scales it on `targetOngoingRequests`.
- **GitOps** — ArgoCD with an app-of-apps and 11 ApplicationSets. The cluster converges on the repo.
- **A private overlay** — all K3s traffic runs over a WireGuard mesh, so nodes can sit in different clouds.

## Architecture

- **Control plane**: K3s on Hetzner (utility-server) — runs ArgoCD, GPU API, Dragonfly, monitoring
- **GPU workers**: 2x RunPod instances, 2x RTX 5060 Ti each (4 GPUs total)
- **Networking**: Netbird VPN overlay — all K3s traffic goes through encrypted WireGuard tunnel
- **Model**: Qwen/Qwen2.5-0.5B-Instruct, kept loaded in GPU memory
- **GitOps**: ArgoCD with App of Apps pattern, 11 ApplicationSets

See [ARCHITECTURE.md](ARCHITECTURE.md) for diagrams.

## Components

| Component | What | Where |
|---|---|---|
| GPU API | Go REST API — auth, Prometheus metrics, sends jobs to Ray Serve | [munhq/gpu-api-ray](https://github.com/munhq/gpu-api-ray) |
| RayService | Persistent vLLM cluster via KubeRay operator | `ansible/argocd/charts/raycluster/` |
| Dragonfly | Job persistence (DB 1) + Ray GCS fault tolerance (DB 0) | `ansible/argocd/charts/dragonfly/` |
| Ansible | Infrastructure provisioning — base, VPN, NVIDIA, K3s, ArgoCD | `ansible/roles/` |
| Monitoring | Prometheus, Grafana, DCGM exporter, node-exporter | Deployed via ArgoCD |

## Docs

- [DEPLOYMENT.md](DEPLOYMENT.md) — deploy from scratch
- [ARCHITECTURE.md](ARCHITECTURE.md) — current system + future multi-datacenter vision
- [munhq/gpu-api-ray](https://github.com/munhq/gpu-api-ray) — the API service and its reference
- [ansible/README.md](ansible/README.md) — playbook reference

## Repo structure

```
ansible/
  plays/                  # all.yml → infrastructure.yml → platform.yml
  roles/                  # base, netbird, nvidia_runtime, k3s_server, k3s_agent, argocd
  inventory/              # hosts + group_vars; vault.yml.example to fill in
  argocd/
    applicationsets/      # 11 ArgoCD ApplicationSet manifests
    charts/               # Custom Helm charts (gpu-api, raycluster, dragonfly)
    config/               # Helm values overrides per app
```

## Tech stack

K3s v1.35 / KubeRay v1.5.1 / vLLM via ray-llm:2.53.0 / Go 1.22 / Dragonfly v1.35 / Prometheus + Grafana / ArgoCD v2.13 / Ansible / Netbird VPN

## Metrics

`GET /metrics` exposes 10 Prometheus metrics: active jobs, job duration, inference duration, job status counts, HTTP latency, submission throughput, submissions by priority, token counts, tokens per request, batch size. Plus DCGM exporter for per-GPU memory/utilization/temperature.
