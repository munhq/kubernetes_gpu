# Architecture

## Current Architecture

### Physical Topology

3 nodes across 2 providers, connected by Netbird VPN.

```mermaid
graph LR
    subgraph Hetzner["Hetzner Cloud (Frankfurt)"]
        UTIL["utility-server<br/>203.0.113.10<br/>K3s server + control plane<br/>No GPU"]
    end

    subgraph RunPod["RunPod (EU)"]
        GPU1["gpu-node-01<br/>203.0.113.20:43508<br/>K3s agent<br/>2x RTX 5060 Ti 16GB"]
        GPU2["gpu-node-02<br/>203.0.113.20:59715<br/>K3s agent<br/>2x RTX 5060 Ti 16GB"]
    end

    UTIL <-->|"Netbird VPN (wt0)<br/>Encrypted WireGuard tunnel<br/>K3s flannel + control plane"| GPU1
    UTIL <-->|"Netbird VPN (wt0)"| GPU2
    GPU1 <-.->|"Pod-to-pod via flannel<br/>over VPN overlay"| GPU2

    style Hetzner fill:#1a1a2e,color:#fff
    style RunPod fill:#0f3460,color:#fff
```

### Application Architecture — Request Flow

How a batch inference job moves through the system.

```mermaid
graph TD
    USER["User"] -->|"curl POST /v1/batches<br/>-H X-API-Key: ***<br/>-d {model, input[], max_tokens}"| GPU_API

    subgraph gpu_workloads["Namespace: gpu-workloads"]
        GPU_API["GPU API (Go)<br/>NodePort 30800<br/>ghcr.io/munhq/gpu-api"]

        subgraph queue_box["In-Process Priority Queue"]
            QUEUE["Min-heap dispatcher<br/>high=1000 / medium=500 / low=100<br/>FIFO within same priority<br/>Max 120 concurrent slots"]
        end

        DRAGONFLY["Dragonfly v1.35.0<br/>Redis-compatible in-memory store<br/>1Gi max memory, 5Gi PVC<br/>RDB snapshots every minute"]

        subgraph ray_cluster["RayService: raycluster-batch-inference"]
            RAY_HEAD["Ray Head Pod<br/>ray-llm:2.53.0-py311-cu128<br/>Serve HTTP proxy :8000<br/>Dashboard :8265<br/>No GPU — scheduling only"]

            subgraph worker1["gpu-node-01"]
                VLLM_W1["Ray Worker Pod<br/>2x vLLM replicas<br/>2x RTX 5060 Ti<br/>Qwen2.5-0.5B-Instruct"]
            end

            subgraph worker2["gpu-node-02"]
                VLLM_W2["Ray Worker Pod<br/>2x vLLM replicas<br/>2x RTX 5060 Ti<br/>Qwen2.5-0.5B-Instruct"]
            end
        end
    end

    GPU_API -->|"1. Enqueue job"| QUEUE
    QUEUE -->|"2. Persist state<br/>(QUEUED → RUNNING → SUCCEEDED)<br/>DB 1, TTL 7 days"| DRAGONFLY
    QUEUE -->|"3. POST /v1/completions<br/>{model, prompt[], max_tokens}"| RAY_HEAD
    RAY_HEAD -->|"4. Route to replica<br/>(continuous batching)"| VLLM_W1
    RAY_HEAD -->|"4. Route to replica<br/>(continuous batching)"| VLLM_W2
    RAY_HEAD -->|"GCS fault tolerance<br/>DB 0 (head HA)"| DRAGONFLY

    USER -->|"curl GET /v1/batches/{id}"| GPU_API
    GPU_API -->|"5. Check memory first<br/>then fallback to Redis"| DRAGONFLY

    style GPU_API fill:#e94560,color:#fff
    style DRAGONFLY fill:#533483,color:#fff
    style RAY_HEAD fill:#16213e,color:#fff
    style QUEUE fill:#0f3460,color:#fff
```

### Dragonfly — Dual Purpose Store

Dragonfly serves two independent roles on separate Redis databases:

```mermaid
graph LR
    subgraph Clients
        GPU_API["GPU API (Go)"]
        RAY_HEAD["Ray Head (GCS)"]
    end

    subgraph Dragonfly["Dragonfly v1.35.0"]
        DB0["DB 0<br/>Ray GCS State<br/>Actor/task metadata<br/>Head node HA"]
        DB1["DB 1<br/>Job Persistence<br/>JSON job records<br/>TTL 7 days"]
        DISK["PVC 5Gi<br/>RDB snapshots<br/>every minute"]
    end

    RAY_HEAD -->|"redis://dragonfly:6379<br/>GCS fault tolerance"| DB0
    GPU_API -->|"dragonfly:6379<br/>Save/Load/ListRecent"| DB1
    DB0 --> DISK
    DB1 --> DISK

    style Dragonfly fill:#533483,color:#fff
```

### Operators & Platform Services

What runs on utility-server to support the application layer.

```mermaid
graph TD
    subgraph gitops["GitOps — ArgoCD (namespace: argocd)"]
        ARGOCD["ArgoCD v2.13<br/>GitHub App auth to private repo"]
        APPSETS["11 ApplicationSets<br/>App of Apps pattern"]
        ARGOCD --> APPSETS
    end

    subgraph operators["Operators (namespace: gpu-workloads)"]
        KUBERAY["KubeRay Operator v1.5.1<br/>Manages RayService CRD"]
        DFOP["Dragonfly Operator v1.3.1<br/>Manages Dragonfly CR"]
    end

    subgraph gpu_stack["GPU Stack"]
        NFD["Node Feature Discovery v0.18.3<br/>Detects NVIDIA GPUs (PCI vendor 10de)<br/>Labels: nvidia.com/gpu.present=true"]
        NDP["NVIDIA Device Plugin v0.18.2<br/>Advertises nvidia.com/gpu resource<br/>Runs on labeled GPU nodes only"]
        DCGM["DCGM Exporter v4.7.1<br/>GPU memory, utilization, temperature<br/>Per-GPU Prometheus metrics"]
    end

    subgraph storage["Storage"]
        LPP["Local Path Provisioner v0.0.30<br/>Dynamic PVs at /opt/kube/data<br/>Used by: Prometheus, Grafana,<br/>AlertManager, Dragonfly"]
    end

    subgraph metrics["Metrics"]
        MSRV["Metrics Server v3.13.0<br/>kubectl top, HPA support"]
    end

    APPSETS -->|"auto-sync"| operators
    APPSETS -->|"auto-sync"| gpu_stack
    APPSETS -->|"auto-sync"| storage
    APPSETS -->|"auto-sync"| metrics
    NFD -->|"labels nodes"| NDP

    style gitops fill:#1a1a2e,color:#fff
    style operators fill:#0f3460,color:#fff
```

### Monitoring & Observability

```mermaid
graph TD
    subgraph monitoring["Namespace: monitoring"]
        PROM["Prometheus<br/>30d retention, 50Gi PVC<br/>Discovers all ServiceMonitors"]
        GRAFANA["Grafana v12.3.1<br/>10Gi PVC, Infinity plugin<br/>Custom + Ray dashboard folders"]
        ALERT["AlertManager<br/>10Gi PVC"]
    end

    subgraph scrape_targets["Scrape Targets"]
        T1["GPU API :8000/metrics<br/>queue depth, latency, throughput,<br/>tokens, batch size, job status"]
        T2["DCGM Exporter :9400<br/>GPU memory, utilization,<br/>temperature (per GPU)"]
        T3["Ray Head :8080<br/>task count, object store,<br/>GCS stats"]
        T4["node-exporter :9100<br/>CPU, memory, disk, network"]
        T5["kube-state-metrics :8080<br/>pod/node/deployment states"]
        T6["Dragonfly (PodMonitor)<br/>memory, connections, ops/sec"]
    end

    PROM -->|"ServiceMonitor 30s"| T1
    PROM -->|"ServiceMonitor"| T2
    PROM -->|"ServiceMonitor"| T3
    PROM -->|"ServiceMonitor"| T4
    PROM -->|"ServiceMonitor"| T5
    PROM -->|"PodMonitor"| T6
    GRAFANA -->|"PromQL queries"| PROM
    GRAFANA -->|"Infinity plugin<br/>direct HTTP to GPU API"| T1
    PROM --> ALERT

    style monitoring fill:#1a1a2e,color:#fff
```

### Infrastructure Provisioning (Ansible)

Execution order matters. Each stage depends on the previous.

```mermaid
graph LR
    subgraph infra["plays/infrastructure.yml"]
        BASE["base role<br/>System hardening<br/>Kernel modules<br/>sysctl, ulimits<br/>NVIDIA persistence"]
        NETBIRD["netbird role<br/>Install VPN client<br/>Connect + get VPN IP<br/>Store as Ansible fact"]
        NVIDIA["nvidia_runtime role<br/>GPU nodes only<br/>NVIDIA drivers<br/>Container Toolkit<br/>containerd config"]
    end

    subgraph platform["plays/platform.yml"]
        K3S_S["k3s_server role<br/>K3s v1.35 on utility-server<br/>node-ip: VPN_IP<br/>flannel-iface: wt0<br/>Disable: traefik, servicelb"]
        K3S_A["k3s_agent role<br/>K3s agent on GPU nodes<br/>Retrieve token from server<br/>GPU taints + labels"]
        ARGOCD_R["argocd role<br/>Install ArgoCD v2.13<br/>GitHub App secret<br/>Bootstrap ApplicationSets"]
    end

    BASE --> NETBIRD --> NVIDIA
    NVIDIA --> K3S_S --> K3S_A --> ARGOCD_R

    style infra fill:#0f3460,color:#fff
    style platform fill:#1a1a2e,color:#fff
```

### Complete Component Inventory

Every component deployed in the cluster:

| Component | Namespace | Runs On | Purpose |
|---|---|---|---|
| **K3s server** | - | utility-server | Kubernetes control plane |
| **K3s agent** | - | gpu-node-01, gpu-node-02 | Worker nodes with GPU taint |
| **ArgoCD v2.13** | argocd | utility-server | GitOps, App of Apps, GitHub App auth |
| **GPU API (Go)** | gpu-workloads | utility-server | REST API, priority queue, auth |
| **Dragonfly v1.35** | gpu-workloads | utility-server | Job persistence (DB1) + Ray GCS (DB0) |
| **Dragonfly Operator v1.3.1** | dragonfly-system | utility-server | Manages Dragonfly CR lifecycle |
| **Ray Head** | gpu-workloads | gpu-node (tolerates taint) | Serve proxy, dashboard, GCS |
| **Ray Worker x2** | gpu-workloads | gpu-node-01, gpu-node-02 | vLLM inference (2 GPU each) |
| **KubeRay Operator v1.5.1** | gpu-workloads | utility-server | Manages RayService CRD |
| **NVIDIA Device Plugin v0.18.2** | gpu-workloads | gpu-node-01, gpu-node-02 | Exposes nvidia.com/gpu resource |
| **Node Feature Discovery v0.18.3** | kube-system | all nodes | Labels GPU nodes automatically |
| **DCGM Exporter v4.7.1** | monitoring | gpu-node-01, gpu-node-02 | GPU metrics for Prometheus |
| **Prometheus** | monitoring | utility-server | Metrics collection, 30d retention |
| **Grafana v12.3.1** | monitoring | utility-server | Dashboards, Infinity plugin |
| **AlertManager** | monitoring | utility-server | Alert routing |
| **kube-state-metrics** | monitoring | utility-server | K8s object metrics |
| **node-exporter** | monitoring | all nodes | Host-level metrics |
| **Metrics Server v3.13.0** | monitoring | utility-server | Resource metrics API |
| **Local Path Provisioner v0.0.30** | kube-system | utility-server | Dynamic PV provisioning |

---

## Future Architecture — Multi-Datacenter GPU Federation

Where this could scale: multiple clusters, heterogeneous GPUs, cost-aware routing.

```mermaid
graph TB
    subgraph clients["Clients"]
        U1["Batch API"]
        U2["Real-time API"]
        U3["Internal Services"]
    end

    subgraph global["Global Control Plane"]
        GATEWAY["API Gateway<br/>Multi-tenant auth<br/>Rate limiting<br/>Per-user quotas"]
        SCHEDULER["Global Scheduler<br/>GPU type matching<br/>Cost-aware routing<br/>Locality preference"]
        NATS["NATS JetStream<br/>Cross-cluster job bus<br/>Durable subscriptions"]
        PG["PostgreSQL<br/>Audit trail, billing<br/>Long-term job history"]
        S3["Model Registry (S3/MinIO)<br/>Model weights + versions"]
    end

    subgraph eu["EU Cluster — Hetzner (Frankfurt)"]
        EU_API["GPU API"]
        EU_DF["Dragonfly"]
        EU_MON["Prometheus + Grafana"]

        EU_RAY1["RayService: Qwen2.5-0.5B<br/>4x RTX 5060 Ti"]
        EU_RAY2["RayService: Llama 3.1 70B<br/>8x A100 80GB"]
    end

    subgraph us["US Cluster — Lambda Labs (Texas)"]
        US_API["GPU API"]
        US_DF["Dragonfly"]
        US_MON["Prometheus + Grafana"]

        US_RAY1["RayService: Qwen2.5-72B<br/>16x H100"]
        US_RAY2["RayService: Whisper Large v3<br/>2x A10G"]
    end

    subgraph spot["Spot Burst Cluster — RunPod"]
        SPOT_API["GPU API"]
        SPOT_RAY["RayService: Qwen2.5-0.5B<br/>6x RTX 4090 (preemptible)"]
    end

    U1 & U2 & U3 --> GATEWAY
    GATEWAY --> SCHEDULER
    SCHEDULER --> NATS
    GATEWAY --> PG

    NATS -->|"Small model jobs"| EU_API
    NATS -->|"Large model jobs"| US_API
    NATS -->|"Overflow / burst"| SPOT_API

    EU_API --> EU_DF
    EU_API --> EU_RAY1 & EU_RAY2
    US_API --> US_DF
    US_API --> US_RAY1 & US_RAY2
    SPOT_API --> SPOT_RAY

    EU_API & US_API & SPOT_API -->|"Results"| NATS
    NATS -->|"Results"| GATEWAY

    S3 -->|"Pull model weights"| EU_RAY1 & EU_RAY2 & US_RAY1 & US_RAY2 & SPOT_RAY
    EU_MON & US_MON -->|"Remote write"| PG

    style global fill:#1a1a2e,color:#fff
    style eu fill:#0f3460,color:#fff
    style us fill:#16213e,color:#fff
    style spot fill:#533483,color:#fff
```


### Current vs Future

| Concern | Current | Future |
|---|---|---|
| **Job routing** | Single GPU API, in-process priority heap | Global scheduler, cost-aware, GPU-type matching |
| **Cross-cluster** | N/A (single cluster) | NATS JetStream job bus |
| **Storage** | Dragonfly for jobs + Ray GCS | PostgreSQL (audit/billing) + Dragonfly per cluster |
| **Models** | Single model (Qwen2.5-0.5B), hostPath | Model registry (S3), multiple models per cluster |
| **GPU types** | 4x RTX 5060 Ti (homogeneous) | RTX, A100, H100, spot (heterogeneous) |
| **Scaling** | Fixed 2 workers, 4 replicas | Per-cluster autoscaling + spot burst |
| **Networking** | Netbird VPN (3 nodes) | WireGuard mesh between clusters, Netbird within |
| **Monitoring** | Single Prometheus + Grafana | Federated Prometheus via remote write |
| **Auth** | Single API key | Multi-tenant, per-user keys, rate limits, quotas |
| **HA** | Head is SPOF, single Dragonfly | Ray GCS FT, Dragonfly replication, multi-head |
| **Cost tracking** | None | Cost-per-token, GPU-hours per job, billing |
