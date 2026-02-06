 PLAYBOOKS (Execution Order)

  1. plays/all.yml (Master Playbook)

  Runs everything in order:
  - → infrastructure.yml
  - → platform.yml
  - → argocd.yml

  2. plays/infrastructure.yml (System Prerequisites)

  Purpose: Bare-metal system setup BEFORE K8s
  Runs:
  - base role → ALL nodes
  - netbird role → ALL nodes
  - nvidia_runtime role → GPU nodes only

  3. plays/platform.yml (K8s Installation)

  Purpose: Install K3s cluster
  Runs:
  - k3s_server role → k3s_server (utility-server)
  - k3s_agent role → gpu_nodes
  - argocd role → k3s_server

  4. plays/argocd.yml (GitOps Deployment)

  Purpose: Deploy ArgoCD projects and ApplicationSets
  Does: Applies manifests from manifests/projects/ and manifests/applicationsets/generated/

  5. plays/generate-applicationsets.yml (Local Generator)

  Purpose: Generate ApplicationSet YAMLs from Jinja2 templates
  Runs locally to create manifests for KubeRay, monitoring, DCGM exporter, metrics server

  ---
  ROLES (What Each Does)

  base (System Hardening)

  - Set timezone
  - Check disk space (fail if < min required)
  - Install common packages
  - Disable swap
  - Load kernel modules (overlay, br_netfilter)
  - Apply sysctl settings (networking, file limits)
  - Set ulimits (nofile, memlock, nproc)
  - Configure journald log limits
  - Enable NTP time sync
  - Enable NVIDIA persistence mode (GPU nodes)

  netbird (VPN Networking)

  - Add Netbird GPG key and repository
  - Install Netbird
  - Connect to Netbird network with setup key
  - Enable Netbird systemd service with restart policy
  - Wait for connection and get VPN IP
  - Store VPN IP as Ansible fact

  nvidia_runtime (GPU Support)

  - Check if NVIDIA GPU present
  - Auto-install NVIDIA drivers (ubuntu-drivers autoinstall)
  - Install NVIDIA Container Toolkit
  - Configure K3s containerd to use NVIDIA runtime
  - Create /var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl
  - Verify nvidia-container-runtime installed

  k3s_server (K8s Control Plane)

  - Install K3s server (v1.29.2+k3s1)
  - Disable traefik, servicelb, local-storage
  - Wait for cluster ready
  - Install Helm
  - Install NVIDIA device plugin DaemonSet
  - Create namespaces (argocd)
  - Apply node labels (control-plane, workload-type: utilities)
  - Store K3s token and server URL (uses Netbird VPN IP!)
  - Create kubeconfig at /etc/rancher/k3s/k3s.yaml

  k3s_agent (K8s Worker Nodes)

  - Get server URL and token from k3s_server host
  - Install K3s agent
  - Connect to server via Netbird VPN
  - Wait for node registration
  - Apply node labels (node-role, GPU labels)
  - Apply node taints (GPU taint for workload isolation)

  argocd (GitOps Bootstrap)

  - Add ArgoCD Helm repo
  - Install ArgoCD via Helm (NodePort on 32443)
  - Wait for ArgoCD ready
  - Get admin password
  - Display access URL and credentials

