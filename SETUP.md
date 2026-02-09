# Setup Guide - KubeRay Batch Inference

Step-by-step instructions to deploy the complete system from scratch.

## Prerequisites

- **Control plane server**: 1x Hetzner server (utility-server, 203.0.113.10)
- **GPU workers**: 2x RunPod GPU instances (203.0.113.20, different SSH ports)
- **Local machine**: Ubuntu 22.04+ with Ansible installed
- **GitHub**: Repository access + Personal Access Token (classic) with `repo` scope

## Phase 1: Local Setup

### 1.1 Add Servers to /etc/hosts

```bash
sudo tee -a /etc/hosts <<EOF
203.0.113.10    utility-server
203.0.113.20  gpu-node-01
203.0.113.20  gpu-node-02
EOF
```

### 1.2 Configure SSH Keys

```bash
# Place server SSH key
cp your_server_key ~/.ssh/id_server_access
chmod 600 ~/.ssh/id_server_access

# Place RunPod SSH key
cp your_runpod_key ~/.ssh/runpod_ed25519
chmod 600 ~/.ssh/runpod_ed25519

# Test connectivity
ssh -i ~/.ssh/id_server_access root@utility-server "hostname"
ssh -p 43508 -i ~/.ssh/runpod_ed25519 root@gpu-node-01 "hostname"
ssh -p 59715 -i ~/.ssh/runpod_ed25519 root@gpu-node-02 "hostname"
```

### 1.3 Clone Repository

```bash
git clone https://github.com/munhq/kubernetes_gpu.git
cd k3s-gpu/ansible
```

### 1.4 Create Ansible Vault Password File

```bash
# Create vault password file (gitignored)
echo "your-vault-password" > .vault_pass
chmod 600 .vault_pass
```

## Phase 2: Configure Secrets

### 2.1 Edit Netbird Setup Keys

```bash
ansible-vault edit inventory/main/group_vars/all/vault.yml --vault-password-file .vault_pass
```

Set:
```yaml
vault_netbird_setup_key: "your-netbird-setup-key-here"
```

### 2.2 Configure GitHub App for ArgoCD

ArgoCD needs a GitHub App to access the private repository.

**Create GitHub App:**
1. Go to: https://github.com/settings/apps/new
2. **GitHub App name**: `k3s-gpu-argocd`
3. **Homepage URL**: `https://argocd.yourdomain.com` (or any placeholder)
4. **Webhook**: Uncheck "Active"
5. **Repository permissions**:
   - Contents: Read-only
   - Metadata: Read-only
6. **Where can this GitHub App be installed?**: Only on this account
7. Click "Create GitHub App"
8. **Generate private key**: Click "Generate a private key" at bottom of page
9. Save the downloaded `.pem` file
10. Note the **App ID** from the app settings page
11. Go to "Install App" → Install on your account → Select "Only select repositories" → Choose `k3s-gpu`

**Configure in Ansible Vault:**

```bash
ansible-vault edit inventory/main/group_vars/all/argocd_vault.yml --vault-password-file .vault_pass
```

Set:
```yaml
argocd_github_app_id: "123456"  # Your GitHub App ID
argocd_github_app_installation_id: "12345678"  # From installation URL
argocd_github_app_private_key: |
  -----BEGIN RSA PRIVATE KEY-----
  Your private key content here (entire .pem file contents)
  -----END RSA PRIVATE KEY-----
```

### 2.3 Configure GitHub Container Registry Token

For pulling the gpu-api Docker image.

**Create Personal Access Token:**
1. Go to: https://github.com/settings/tokens
2. Generate new token (classic)
3. Scopes: `read:packages`
4. Note the token

**Configure in Ansible Vault:**

```bash
ansible-vault edit inventory/main/group_vars/all/argocd_vault.yml --vault-password-file .vault_pass
```

Add:
```yaml
argocd_ghcr_token: "ghp_yourPersonalAccessTokenHere"
```

### 2.4 Configure GPU API Key

```bash
ansible-vault edit inventory/main/group_vars/all/argocd_vault.yml --vault-password-file .vault_pass
```

Add:
```yaml
gpu_api_key: "sk-your-api-key-here"  # Used for X-API-Key header
```

## Phase 3: Deploy Infrastructure

### 3.1 Deploy Base System + VPN + NVIDIA Runtime

```bash
cd k3s-gpu/ansible
ansible-playbook plays/infrastructure.yml --vault-password-file .vault_pass
```

This installs:
- Base system packages, sysctl tuning, swap disable
- Netbird VPN (connects all nodes via overlay network)
- NVIDIA drivers + container runtime (GPU nodes only)

**Expected duration**: ~10 minutes

### 3.2 Deploy K3s Cluster

```bash
ansible-playbook plays/platform.yml --vault-password-file .vault_pass
```

This installs:
- K3s server on utility-server (control plane)
- K3s agents on GPU nodes (workers)
- ArgoCD (GitOps)

**Expected duration**: ~5 minutes

### 3.3 Verify K3s Cluster

```bash
# Get kubeconfig from server
scp -i ~/.ssh/id_server_access root@utility-server:/etc/rancher/k3s/k3s.yaml ~/.kube/config

# Replace server IP with actual IP
sed -i 's/127.0.0.1/203.0.113.10/g' ~/.kube/config

# Test access
kubectl get nodes
```

Expected output:
```
NAME             STATUS   ROLES                  AGE   VERSION
gpu-node-01      Ready    worker                 5m    v1.35.0+k3s3
gpu-node-02      Ready    worker                 5m    v1.35.0+k3s3
utility-server   Ready    control-plane,etcd     5m    v1.35.0+k3s3
```

### 3.4 Verify GPU Detection

```bash
kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, gpus: .status.capacity["nvidia.com/gpu"]}'
```

Expected output:
```json
{"name": "gpu-node-01", "gpus": "2"}
{"name": "gpu-node-02", "gpus": "2"}
{"name": "utility-server", "gpus": null}
```

## Phase 4: Deploy Applications via ArgoCD

### 4.1 Deploy ArgoCD ApplicationSets

```bash
ansible-playbook plays/argocd.yml --vault-password-file .vault_pass
```

This deploys ApplicationSets which create Applications for:
- KubeRay operator
- Node Feature Discovery
- NVIDIA device plugin
- DCGM exporter (GPU metrics)
- Prometheus + Grafana
- metrics-server
- Dragonfly (Redis-compatible store)
- RayCluster (persistent vLLM)
- GPU API

**Expected duration**: ~15 minutes (includes image pulls)

### 4.2 Monitor Deployment

```bash
# Watch ArgoCD applications sync
kubectl get applications -n argocd -w

# Check all pods
kubectl get pods -A
```

Wait until all Applications show `Healthy` and `Synced`.

### 4.3 Verify Ray Cluster

```bash
# Check RayService
kubectl get rayservice -n gpu-workloads

# Check Ray pods
kubectl get pods -n gpu-workloads -l ray.io/cluster=raycluster-batch-inference

# Check Ray Serve status
kubectl exec -n gpu-workloads -it \
  $(kubectl get pod -n gpu-workloads -l ray.io/node-type=head -o name) \
  -- serve status
```

Expected output shows vLLM application as `RUNNING`.

### 4.4 Verify GPU API

```bash
# Check API pod
kubectl get pods -n gpu-workloads -l app=gpu-api

# Check API logs
kubectl logs -n gpu-workloads -l app=gpu-api --tail=50

# Port-forward to test locally
kubectl port-forward -n gpu-workloads svc/gpu-api 8000:8000
```

## Phase 5: Test the System

### 5.1 Submit Test Job

```bash
# Get API key from vault
API_KEY=$(ansible-vault view inventory/main/group_vars/all/argocd_vault.yml --vault-password-file .vault_pass | grep gpu_api_key | awk '{print $2}' | tr -d '"')

# Submit batch job
curl -X POST http://localhost:8000/v1/batches \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
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

Expected response:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "QUEUED",
  "priority": "high"
}
```

### 5.2 Check Job Status

```bash
JOB_ID="550e8400-e29b-41d4-a716-446655440000"  # Use actual job_id from above

curl http://localhost:8000/v1/batches/$JOB_ID \
  -H "X-API-Key: $API_KEY"
```

Response (completed):
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "SUCCEEDED",
  "priority": "high",
  "results": [
    {"prompt": "What is 2+2?", "output": "2+2 equals 4."},
    {"prompt": "Explain quantum computing in one sentence", "output": "Quantum computing..."}
  ]
}
```

### 5.3 Test Authentication

```bash
# Missing API key - should return 401
curl -X POST http://localhost:8000/v1/batches \
  -H "Content-Type: application/json" \
  -d '{"input": [{"prompt": "test"}]}'

# Invalid API key - should return 401
curl -X POST http://localhost:8000/v1/batches \
  -H "Content-Type: application/json" \
  -H "X-API-Key: wrong-key" \
  -d '{"input": [{"prompt": "test"}]}'
```

### 5.4 Check Queue Status

```bash
curl http://localhost:8000/v1/queue -H "X-API-Key: $API_KEY"
```

Response:
```json
{
  "queue_depth": 2,
  "active_gpus": 1,
  "max_gpus": 4
}
```

## Phase 6: Access Dashboards

### 6.1 Grafana

```bash
# Port-forward Grafana
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80

# Access: http://localhost:3000
# Username: admin
# Password: admin (change on first login)
```

**Import Dragonfly Dashboard:**
1. Go to Dashboards → Import
2. Enter dashboard ID: `11692`
3. Select Prometheus datasource
4. Click Import

### 6.2 ArgoCD

```bash
# Get ArgoCD password
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d

# Port-forward ArgoCD
kubectl port-forward -n argocd svc/argocd-server 8080:443

# Access: https://localhost:8080
# Username: admin
# Password: (from above command)
```

### 6.3 Ray Dashboard

```bash
# Port-forward Ray dashboard
kubectl port-forward -n gpu-workloads \
  svc/raycluster-batch-inference-head-svc 8265:8265

# Access: http://localhost:8265
```

## Troubleshooting

### API Not Responding

```bash
# Check API logs
kubectl logs -n gpu-workloads -l app=gpu-api --tail=100

# Check if Ray Serve is ready
kubectl exec -n gpu-workloads -it \
  $(kubectl get pod -n gpu-workloads -l ray.io/node-type=head -o name) \
  -- curl http://localhost:8000/-/healthz
```

### Ray Serve Not Starting

```bash
# Check vLLM deployment logs
kubectl logs -n gpu-workloads -l ray.io/node-type=head --tail=100

# Check for GPU availability
kubectl describe nodes | grep -A 5 "nvidia.com/gpu"
```

### Netbird VPN Issues

```bash
# Check Netbird status on nodes
ansible all -i inventory/main/hosts -m shell -a "netbird status"

# Verify VPN connectivity
ansible all -i inventory/main/hosts -m ping
```

### ArgoCD Applications Not Syncing

```bash
# Check ArgoCD logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller

# Force sync
kubectl patch application -n argocd <app-name> --type merge \
  -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}'
```

## Next Steps

- [ ] Review [questions.md](questions.md) for architecture Q&A
- [ ] Review [DECISIONS.md](DECISIONS.md) for design choices
- [ ] Set up alerts in Grafana
- [ ] Test failure scenarios
- [ ] Prepare presentation demo
