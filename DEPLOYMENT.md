# Deployment Guide - KubeRay Batch Inference

## Architecture

```
┌─────────────┐
│   User      │
└──────┬──────┘
       │ HTTP POST /v1/batches
       │ X-API-Key: sk-demo-key-12345
       ▼
┌──────────────────────────────┐
│  Batch Inference API (Go)    │
│  - API Key Auth              │
│  - Job submission            │
│  - Status/Results retrieval  │
└──────────┬───────────────────┘
           │ Ray Jobs API
           ▼
┌──────────────────────────────┐
│   Ray Cluster (KubeRay)      │
│                              │
│  ┌────────────────┐          │
│  │  Ray Head Node │          │
│  │  - Scheduling  │          │
│  │  - Dashboard   │          │
│  └────────┬───────┘          │
│           │                  │
│  ┌────────▼───────┐          │
│  │  GPU Worker 1  │          │
│  │  - 1x GPU      │          │
│  │  - vLLM        │          │
│  └────────────────┘          │
│  ┌────────────────┐          │
│  │  GPU Worker 2  │          │
│  │  - 1x GPU      │          │
│  │  - vLLM        │          │
│  └────────────────┘          │
└──────────────────────────────┘
```

## Prerequisites

- ✅ K3s cluster with 2 GPU nodes
- ✅ KubeRay operator installed
- ✅ ArgoCD installed
- ✅ GitHub Container Registry access

---

## Step 1: Build and Push Docker Image

### Option A: GitHub Actions (Automated)

Commit and push to GitHub - the workflow will automatically build and push:

```bash
git add -A
git commit -m "Add batch inference API"
git push
```

The image will be available at: `ghcr.io/munhq/batch-inference-api:latest`

### Option B: Manual Build and Push

```bash
cd batch-inference-api

# Build
docker build -t ghcr.io/munhq/batch-inference-api:latest .

# Login to GitHub Container Registry
echo $GITHUB_TOKEN | docker login ghcr.io -u munhq --password-stdin

# Push
docker push ghcr.io/munhq/batch-inference-api:latest
```

---

## Step 2: Deploy Infrastructure via ArgoCD

```bash
cd ansible

# Deploy all ApplicationSets (Prometheus, metrics-server, dcgm-exporter, kuberay-operator, batch-inference)
ansible-playbook plays/argocd.yml
```

This will deploy:
- ✅ KubeRay operator
- ✅ Prometheus + Grafana
- ✅ DCGM Exporter (GPU metrics)
- ✅ metrics-server
- ✅ RayCluster (1 head + 2 GPU workers)
- ✅ Batch Inference API

---

## Step 3: Verify Deployment

```bash
# Check RayCluster
kubectl get raycluster
kubectl get pods -l ray.io/cluster=raycluster-batch-inference

# Check Batch API
kubectl get pods -l app=batch-inference-api
kubectl get svc batch-inference-api

# Get NodePort
kubectl get svc batch-inference-api -o jsonpath='{.spec.ports[0].nodePort}'
```

Expected output:
```
NAME                           READY   STATUS    RESTARTS   AGE
raycluster-batch-inference-head-xxxxx   1/1     Running   0          2m
raycluster-batch-inference-worker-0     1/1     Running   0          2m
raycluster-batch-inference-worker-1     1/1     Running   0          2m
batch-inference-api-xxxxx               1/1     Running   0          2m

NAME                      TYPE       CLUSTER-IP      EXTERNAL-IP   PORT(S)          AGE
batch-inference-api       NodePort   10.43.x.x       <none>        8000:30800/TCP   2m
```

---

## Step 4: Test the API

### Get the API endpoint

```bash
# Get node IP
NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}')

# Or use specific node
NODE_IP=203.0.113.10  # Your utility server IP

# NodePort is 30800 (defined in manifest)
API_URL="http://${NODE_IP}:30800"
```

### Submit a batch job

```bash
curl -X POST ${API_URL}/v1/batches \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk-demo-key-12345" \
  -d '{
    "model": "Qwen/Qwen2.5-0.5B-Instruct",
    "input": [
      {"prompt": "What is 2+2?"},
      {"prompt": "Explain quantum computing in one sentence"}
    ],
    "max_tokens": 50
  }'
```

Response:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "submitted"
}
```

### Check job status

```bash
JOB_ID="550e8400-e29b-41d4-a716-446655440000"

curl -X GET ${API_URL}/v1/batches/${JOB_ID} \
  -H "X-API-Key: sk-demo-key-12345"
```

Response (running):
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running"
}
```

Response (completed):
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "results": [
    {
      "prompt": "What is 2+2?",
      "output": "2+2 equals 4."
    },
    {
      "prompt": "Explain quantum computing in one sentence",
      "output": "Quantum computing leverages quantum mechanical phenomena..."
    }
  ]
}
```

### Test authentication

```bash
# Missing API key (should return 401)
curl -X POST ${API_URL}/v1/batches \
  -H "Content-Type: application/json" \
  -d '{"model": "test", "input": [], "max_tokens": 10}'

# Invalid API key (should return 401)
curl -X POST ${API_URL}/v1/batches \
  -H "Content-Type: application/json" \
  -H "X-API-Key: wrong-key" \
  -d '{"model": "test", "input": [], "max_tokens": 10}'
```

---

## Step 5: Monitor with Grafana

```bash
# Get Grafana NodePort
kubectl get svc -n monitoring prometheus-grafana -o jsonpath='{.spec.ports[0].nodePort}'

# Access Grafana
# URL: http://203.0.113.10:<nodeport>
# Default credentials: admin/admin (from monitoring ApplicationSet)
```

**Key Metrics to Monitor:**
- GPU utilization (DCGM Exporter)
- Ray worker CPU/memory
- API response times
- Job completion rates
- Failed job count

---

## Troubleshooting

### API not responding

```bash
# Check API logs
kubectl logs -l app=batch-inference-api --tail=50

# Check if Ray head is accessible
kubectl exec -it deployment/batch-inference-api -- curl http://raycluster-batch-inference-head-svc:8265/api/health
```

### Ray workers not starting

```bash
# Check worker logs
kubectl logs -l ray.io/node-type=worker --tail=50

# Check GPU availability
kubectl describe nodes | grep -A 10 "nvidia.com/gpu"
```

### Jobs stuck in "running"

```bash
# Check Ray dashboard
kubectl port-forward svc/raycluster-batch-inference-head-svc 8265:8265

# Open browser: http://localhost:8265
```

---

## Production Considerations

### 1. **Output Storage**
Current: `/tmp/batch-results` (ephemeral)

**Production options:**
- PersistentVolume (NFS/Ceph)
- S3-compatible storage (MinIO/AWS S3)
- PostgreSQL (for small results + metadata)

### 2. **Load Balancing**
Current: 2 GPU workers

**Ray's distribution:**
- Automatic work distribution across workers
- Gang scheduling for multi-GPU jobs
- Dynamic resource allocation

**Bottlenecks:**
- Model loading time (each worker loads model separately)
- Network bandwidth for large results
- Shared storage I/O

**Solutions:**
- Model caching in shared volume
- Result streaming instead of batch return
- Increase worker replicas

### 3. **KPIs for Production**

| Metric | Target | Source |
|--------|--------|--------|
| API latency (p95) | < 100ms | Prometheus (API metrics) |
| Job completion time | < 5 min | Ray Dashboard |
| GPU utilization | > 80% | DCGM Exporter |
| Failed job rate | < 1% | Application logs |
| Queue depth | < 10 | Ray Dashboard |

### 4. **KubeRay Integration**

**Strengths:**
- ✅ Native K8s CRDs (RayCluster, RayJob)
- ✅ Auto-scaling workers based on load
- ✅ Resource isolation (GPU, CPU, memory)
- ✅ Namespace-based multi-tenancy
- ✅ Prometheus metrics out-of-the-box

**Limitations:**
- ❌ No built-in API gateway (had to build custom)
- ❌ Results storage not included (ephemeral by default)
- ❌ No built-in authentication
- ❌ Limited multi-cluster support (need MultiKueue)

### 5. **Scaling Strategy**

**Horizontal scaling:**
```yaml
workerGroupSpecs:
- replicas: 5  # Scale to 5 GPU workers
  maxReplicas: 10  # Auto-scale up to 10
```

**Vertical scaling:**
```yaml
resources:
  limits:
    nvidia.com/gpu: 2  # Use 2 GPUs per worker
```

---

## Next Steps

1. ✅ Deploy base infrastructure
2. ✅ Build and push Docker image
3. ✅ Test API end-to-end
4. 📊 Set up Grafana dashboards
5. 📝 Prepare technical report
6. 🎤 Practice demo presentation

**Estimated timeline:**
- Infrastructure deployment: 30 min
- API testing: 1 hour
- Monitoring setup: 1 hour
- Documentation: 2 hours
- Presentation prep: 2 hours

**Total: ~7 hours of focused work**
