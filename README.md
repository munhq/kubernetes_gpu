# kubernetes_gpu

kubernetes_gpu deploys an LLM inference API on your own GPUs. The API service itself lives in [munhq/gpu-api-ray](https://github.com/munhq/gpu-api-ray); this repo is the Kubernetes setup that deploys it. Submit a job over HTTP and fetch the result. A dashboard, per-GPU metrics and autoscaling are included. One variable selects where the GPUs come from.

```bash
ansible-playbook ansible/plays/infrastructure.yml     # bare metal / cloud hosts → K3s + NVIDIA runtime
ansible-playbook ansible/plays/platform.yml           # cluster services
ansible-playbook ansible/plays/argocd.yml             # everything else, via GitOps
```

Then:

```bash
curl -X POST http://<host>:8000/v1/batches \
  -H "Content-Type: application/json" -H "X-API-Key: $KEY" \
  -d '{"model":"Qwen/Qwen2.5-0.5B-Instruct","input":[{"prompt":"What is 2+2?"}],"max_tokens":50}'

curl http://<host>:8000/v1/batches/{job_id} -H "X-API-Key: $KEY"
```

Jobs run against a model that is already resident in GPU memory — no queue and no cold start. Results persist in Dragonfly for 7 days.

## Execution paths

```bash
ansible-playbook ansible/plays/argocd.yml -e gpu_execution_path=gpuscale
```

| `gpu_execution_path` | GPUs come from | Shape |
|---|---|---|
| `ray` | Nodes you already own, joined to the cluster | KubeRay operator + RayCluster hold vLLM warm in-cluster |
| `gpuscale` | Bought on demand from seven providers — AWS, Azure, GCP, RunPod, Vast.ai, TensorDock, Verda | Each GPU runs an agent and vLLM directly. No K3s on the node, no Ray. Scales to zero |
| `both` *(default)* | Both at once | For comparing them side by side |

It works by setting `directory.exclude` on the ArgoCD ApplicationSets bootstrap, so the path you did not pick is never rendered. Switching later is a re-run — ArgoCD prunes what left the set.

## What the three playbooks install

- **An OpenAI-shaped batch API** with API-key auth, on port 8000, with a dashboard UI.
- **A warm vLLM cluster** — the model stays loaded, so submitted work starts immediately.
- **Per-GPU metrics** — DCGM exporter gives memory, utilisation and temperature per card; the API exposes 10 Prometheus metrics of its own; Grafana dashboards ship with it.
- **Autoscaling** — KEDA on the Ray path, gpuscale buying spot capacity on the other.
- **GitOps** — ArgoCD with an app-of-apps and 13 ApplicationSets. The cluster converges on the repo.
- **A private overlay** — all K3s traffic runs over a WireGuard mesh, so nodes can sit in different clouds.

The GPU autoscaler is a separate project: **[munhq/gpuscale](https://github.com/munhq/gpuscale)**.

## Architecture

- **Control plane**: K3s on Hetzner (utility-server) — runs ArgoCD, GPU API, Dragonfly, monitoring
- **GPU workers**: 2x RunPod instances, 2x RTX 5060 Ti each (4 GPUs total)
- **Networking**: Netbird VPN overlay — all K3s traffic goes through encrypted WireGuard tunnel
- **Model**: Qwen/Qwen2.5-0.5B-Instruct, kept loaded in GPU memory
- **GitOps**: ArgoCD with App of Apps pattern, 13 ApplicationSets

See [ARCHITECTURE.md](ARCHITECTURE.md) for diagrams.

## Components

| Component | What | Where |
|---|---|---|
| GPU API | Go REST API — auth, Prometheus metrics, sends jobs to Ray Serve | [munhq/gpu-api-ray](https://github.com/munhq/gpu-api-ray) |
| RayService | Persistent vLLM cluster via KubeRay operator | `ansible/argocd/charts/raycluster/` |
| Dragonfly | Job persistence (DB 1) + Ray GCS fault tolerance (DB 0) | `ansible/argocd/charts/dragonfly/` |
| gpuscale | GPU node autoscaler — provisions GPU workers from spot providers, drains them when idle | `ansible/argocd/charts/gpuscale/` |
| Ansible | Infrastructure provisioning — base, VPN, NVIDIA, K3s, ArgoCD | `ansible/roles/` |
| Monitoring | Prometheus, Grafana, DCGM exporter, node-exporter | Deployed via ArgoCD |

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
- [munhq/gpu-api-ray](https://github.com/munhq/gpu-api-ray) — the API service and its reference
- [ansible/README.md](ansible/README.md) — playbook reference

## Repo structure

```
ansible/
  plays/                  # infrastructure.yml → platform.yml → argocd.yml
  roles/                  # base, netbird, nvidia_runtime, k3s_server, k3s_agent, argocd
  inventory/              # hosts, vault-encrypted secrets
  argocd/
    applicationsets/      # 13 ArgoCD ApplicationSet manifests
    charts/               # Custom Helm charts (gpu-api, raycluster, dragonfly)
    config/               # Helm values overrides per app
```

## Tech stack

K3s v1.35 / KubeRay v1.5.1 / vLLM via ray-llm:2.53.0 / Go 1.22 / Dragonfly v1.35 / Prometheus + Grafana / ArgoCD v2.13 / Ansible / Netbird VPN

## Metrics

`GET /metrics` exposes 10 Prometheus metrics: active jobs, job duration, inference duration, job status counts, HTTP latency, submission throughput, submissions by priority, token counts, tokens per request, batch size. Plus DCGM exporter for per-GPU memory/utilization/temperature.
