# Setup Guide

How to deploy the whole thing from scratch.

## Prerequisites

- 1x Hetzner server (utility-server, 203.0.113.10) — control plane, no GPU
- 2x RunPod GPU instances (203.0.113.20, ports 43508 and 59715) — 2x RTX 5060 Ti each
- Ansible installed locally
- GitHub repo access + Personal Access Token (classic) with `repo` scope

## Phase 1: Local Setup

Add servers to /etc/hosts:

```bash
sudo tee -a /etc/hosts <<EOF
203.0.113.10    utility-server
203.0.113.20  gpu-node-01
203.0.113.20  gpu-node-02
EOF
```

SSH keys:

```bash
cp your_server_key ~/.ssh/id_server_access
cp your_runpod_key ~/.ssh/runpod_ed25519
chmod 600 ~/.ssh/id_server_access ~/.ssh/runpod_ed25519

# Verify
ssh -i ~/.ssh/id_server_access root@utility-server "hostname"
ssh -p 43508 -i ~/.ssh/runpod_ed25519 root@gpu-node-01 "hostname"
ssh -p 59715 -i ~/.ssh/runpod_ed25519 root@gpu-node-02 "hostname"
```

Clone and set up vault:

```bash
git clone https://github.com/munhq/kubernetes_gpu.git
cd k3s-gpu/ansible
echo "your-vault-password" > .vault_pass
chmod 600 .vault_pass
```

## Phase 2: Secrets

Three vault files need populating.

### Netbird VPN

```bash
ansible-vault edit inventory/main/group_vars/all/vault.yml --vault-password-file .vault_pass
```

```yaml
vault_netbird_setup_key: "your-netbird-setup-key"
```

### ArgoCD GitHub App

ArgoCD needs a GitHub App to pull from the private repo. Create one at https://github.com/settings/apps/new with Contents: Read-only, Metadata: Read-only. Install it on the repo. Generate a private key.

```bash
ansible-vault edit inventory/main/group_vars/all/argocd_vault.yml --vault-password-file .vault_pass
```

```yaml
argocd_github_app_id: "123456"
argocd_github_app_installation_id: "12345678"
argocd_github_app_private_key: |
  -----BEGIN RSA PRIVATE KEY-----
  (entire .pem contents)
  -----END RSA PRIVATE KEY-----
argocd_ghcr_token: "ghp_..."  # PAT with read:packages scope, for pulling gpu-api image
gpu_api_key: "sk-your-api-key"  # X-API-Key header value
```

## Phase 3: Deploy

Everything runs from `k3s-gpu/ansible/`.

### Infrastructure (base system + VPN + NVIDIA drivers)

```bash
ansible-playbook plays/infrastructure.yml --vault-password-file .vault_pass
```

~10 minutes. Installs base packages, Netbird VPN on all nodes, NVIDIA drivers + container toolkit on GPU nodes.

### Platform (K3s + ArgoCD)

```bash
ansible-playbook plays/platform.yml --vault-password-file .vault_pass
```

~5 minutes. K3s server on utility-server, agents on GPU nodes, ArgoCD installed and configured.

### Verify the cluster

```bash
scp -i ~/.ssh/id_server_access root@utility-server:/etc/rancher/k3s/k3s.yaml ~/.kube/config
sed -i 's/127.0.0.1/203.0.113.10/g' ~/.kube/config
kubectl get nodes
```

Should show 3 nodes Ready. Check GPUs:

```bash
kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, gpus: .status.capacity["nvidia.com/gpu"]}'
```

gpu-node-01 and gpu-node-02 should each report 2 GPUs.

### Applications (via ArgoCD)

```bash
ansible-playbook plays/argocd.yml --vault-password-file .vault_pass
```

~15 minutes (image pulls). This deploys ApplicationSets which create all the apps: KubeRay operator, NFD, NVIDIA device plugin, DCGM exporter, Prometheus + Grafana, metrics-server, Dragonfly, RayCluster, GPU API.

Watch it sync:

```bash
kubectl get applications -n argocd -w
```

Wait until everything shows Healthy + Synced.

## Phase 4: Verify

### Ray cluster

```bash
kubectl get rayservice -n gpu-workloads
kubectl get pods -n gpu-workloads -l ray.io/cluster=raycluster-batch-inference
kubectl exec -n gpu-workloads $(kubectl get pod -n gpu-workloads -l ray.io/node-type=head -o name) -- serve status
```

Should show the vLLM application as RUNNING.

### GPU API

```bash
kubectl port-forward -n gpu-workloads svc/gpu-api 8000:8000
```

### Submit a test job

```bash
curl -X POST http://localhost:8000/v1/batches \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk-your-api-key" \
  -d '{
    "model": "Qwen/Qwen2.5-0.5B-Instruct",
    "input": [
      {"prompt": "What is 2+2?"},
      {"prompt": "Explain quantum computing in one sentence"}
    ],
    "max_tokens": 50,
    "priority": "high"
  }'
```

Returns `{"job_id": "...", "status": "RUNNING", "priority": "high"}`. Poll with:

```bash
curl http://localhost:8000/v1/batches/{job_id} -H "X-API-Key: sk-your-api-key"
```

### Auth test

```bash
# No key — 401
curl -s http://localhost:8000/v1/batches -X POST -H "Content-Type: application/json" -d '{"input":[{"prompt":"test"}]}'

# Wrong key — 401
curl -s http://localhost:8000/v1/batches -X POST -H "Content-Type: application/json" -H "X-API-Key: wrong" -d '{"input":[{"prompt":"test"}]}'
```

## Dashboards

### Grafana
```bash
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80
# http://localhost:3000 — admin / admin
```

### ArgoCD
```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
kubectl port-forward -n argocd svc/argocd-server 8080:443
# https://localhost:8080 — admin / (password from above)
```

### Ray Dashboard
```bash
kubectl port-forward -n gpu-workloads svc/raycluster-batch-inference-head-svc 8265:8265
# http://localhost:8265
```

## Troubleshooting

**API not responding**: Check `kubectl logs -n gpu-workloads -l app=gpu-api --tail=100`. Usually means Ray Serve isn't ready yet — vLLM takes a minute to load the model.

**Ray Serve not starting**: Check head pod logs. Usually a GPU scheduling issue — verify `kubectl describe nodes | grep -A5 nvidia.com/gpu` shows available GPUs.

**VPN issues**: `ansible all -i inventory/main/hosts -m shell -a "netbird status"`. If a node dropped off the VPN, the K3s agent loses contact with the server.

**ArgoCD not syncing**: Check `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller`. Usually a GitHub App auth issue — verify the private key and installation ID in the vault.

**Or just run everything from scratch**:
```bash
ansible-playbook plays/all.yml --vault-password-file .vault_pass
```

This runs infrastructure → platform → argocd in order. Takes about 30 minutes total.
