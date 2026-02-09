K3s Server
==========

Installs and configures a K3s server cluster with NetBird VPN networking, optimized for GPU workloads.

Description
-----------

This role deploys a K3s server that acts as the control plane for a Kubernetes cluster. It includes:

- NetBird VPN connectivity verification and management
- K3s server installation with VPN-specific networking
- Flannel CNI configuration for VPN tunneling
- Helm package manager installation
- Node labeling and tainting support
- Namespace creation
- GPU workload optimization
- Cluster credentials management for agent nodes

The role is specifically designed for GPU clusters where nodes communicate over NetBird VPN and uses VPN IPs for all cluster networking.

Requirements
------------

- Target host must have NetBird VPN client installed and configured
- NetBird must be connected to at least one peer for cluster networking
- Sufficient disk space for K3s data directory
- Ansible collections:
  - `kubernetes.core`
  - `ansible.builtin`

Role Variables
--------------

### Default Variables (defaults/main.yml)

```yaml
k3s_version: "v1.29.2+k3s1"             # K3s version to install
k3s_config_dir: /etc/rancher/k3s         # K3s configuration directory
k3s_data_dir: /var/lib/rancher/k3s       # K3s data directory

k3s_disable:                             # Components to disable
  - traefik                              # Use external ingress controller
  - servicelb                            # Use MetalLB instead
  - local-storage                        # Use external storage provisioner

cluster_name: kuberay-batch              # Cluster identifier

k3s_kubelet_args:                        # Additional kubelet arguments
  - "max-pods=250"                       # Increase pod limit for GPU nodes
```

### Optional Variables

```yaml
# Node labels to apply to the server node
k3s_node_labels:
  node.kubernetes.io/instance-type: "control-plane"
  cluster.local/role: "server"
  topology.kubernetes.io/zone: "zone-a"

# Node taints to apply to the server node
k3s_node_taints:
  - "node.kubernetes.io/control-plane=true:NoSchedule"
  - "cluster.local/server-only=true:NoExecute"

# Additional namespaces to create
namespaces:
  - gpu-workloads
  - monitoring
  - storage
```

### Automatic Variables

The role automatically detects and configures:

```yaml
netbird_vpn_ip: "100.x.x.x"             # Detected NetBird VPN IP
k3s_server_url: "https://VPN_IP:6443"   # Server URL for agent connection
k3s_token: "TOKEN_VALUE"                # Cluster join token
```

Dependencies
------------

- NetBird VPN client must be installed and running
- Sufficient network connectivity for NetBird peers
- Write access to K3s configuration and data directories

Features
--------

### NetBird VPN Integration
- Automatically detects current NetBird VPN IP
- Restarts NetBird service if IP changed
- Verifies connectivity to VPN peers
- Configures cluster networking over VPN tunnel

### K3s Server Configuration
- Installs specified K3s version as cluster server
- Generates dynamic configuration using NetBird VPN IP
- Configures Flannel CNI for VPN networking
- Enables cluster initialization mode
- Sets up TLS SAN certificates for multiple access methods

### Network Configuration
The role configures advanced networking for VPN operation:

```yaml
# Binds cluster traffic to VPN interface
node-ip: VPN_IP
advertise-address: VPN_IP
flannel-iface: wt0                       # NetBird interface
node-external-ip: VPN_IP
flannel-external-ip: true
```

### Component Management
- Disables default K3s components (Traefik, ServiceLB, Local Storage)
- Installs Helm for package management
- Creates kubeconfig for immediate access
- Supports custom kubelet arguments

### Node Configuration
- Applies custom labels for workload scheduling
- Applies taints for specialized node roles
- Creates additional namespaces
- Enables metrics exposure

Installation Process
--------------------

1. **VPN Verification**: Checks NetBird status and peer connectivity
2. **Configuration**: Creates K3s config directory and files
3. **Download**: Fetches K3s installation script
4. **Install**: Installs K3s server with generated configuration
5. **Wait**: Waits for cluster initialization and node readiness
6. **Helm**: Installs Helm package manager
7. **Kubeconfig**: Sets up kubectl access configuration
8. **Credentials**: Stores server URL and token for agent nodes
9. **Namespaces**: Creates additional namespaces if specified
10. **Node Config**: Applies labels and taints
11. **Verify**: Confirms successful installation

Example Playbook
----------------

### Basic Installation

```yaml
- hosts: k3s_servers
  roles:
    - k3s_server
```

### GPU Cluster Configuration

```yaml
- hosts: k3s_servers
  vars:
    k3s_version: "v1.29.2+k3s1"
    cluster_name: gpu-cluster
    k3s_node_labels:
      cluster.local/role: "control-plane"
      cluster.local/gpu-cluster: "true"
    k3s_node_taints:
      - "node.kubernetes.io/control-plane=true:NoSchedule"
    namespaces:
      - gpu-workloads
      - kuberay-system
      - monitoring
      - argocd
    k3s_kubelet_args:
      - "max-pods=250"
      - "serialize-image-pulls=false"
  roles:
    - k3s_server
```

### High Availability Setup (Future)

```yaml
- hosts: k3s_servers
  vars:
    k3s_disable:
      - traefik
      - servicelb
      - local-storage
    k3s_node_labels:
      cluster.local/role: "control-plane"
      topology.kubernetes.io/zone: "{{ ansible_hostname.split('-')[-1] }}"
  roles:
    - k3s_server
```

Template Configuration
----------------------

The role uses [config.yaml.j2](templates/config.yaml.j2) to generate K3s configuration:

### Key Configuration Elements:

- **VPN Networking**: Binds all cluster communication to NetBird VPN
- **Flannel Setup**: Configures VXLAN tunneling over VPN interface  
- **TLS Certificates**: Supports multiple access methods (hostname, VPN IP, localhost)
- **Component Disabling**: Removes default components for external replacements
- **GPU Optimization**: Kubelet tuning for GPU workloads

Handlers
--------

- `restart k3s`: Restarts the K3s server service with daemon reload

Post-Installation Access
------------------------

After successful installation:

### Kubectl Access
```bash
# On the server node
kubectl get nodes
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

# From remote machine (copy kubeconfig)
scp root@SERVER:/etc/rancher/k3s/k3s.yaml ~/.kube/config
# Edit server URL to use VPN IP
```

### Agent Connection
- **Server URL**: Available as `k3s_server_url` fact
- **Token**: Available as `k3s_token` fact
- Agent nodes can join using these credentials

### Helm Usage
```bash
helm version
helm repo add bitnami https://charts.bitnami.com/bitnami
```

Troubleshooting
---------------

### Common Issues

1. **NetBird connectivity**: Verify NetBird is running and connected to peers
2. **VPN IP detection**: Check NetBird status output format
3. **Cluster initialization timeout**: Network or resource constraints
4. **Node not ready**: CNI or kubelet startup issues

### Manual Verification

```bash
# Check NetBird status
netbird status --detail

# Verify K3s service
systemctl status k3s

# Check cluster status
kubectl get nodes -o wide
kubectl cluster-info

# View K3s logs
journalctl -u k3s -f

# Test API server
curl -k https://VPN_IP:6443/healthz
```

### Recovery Commands

```bash
# Restart K3s server
sudo systemctl restart k3s

# Complete K3s removal (destructive)
sudo /usr/local/bin/k3s-uninstall.sh

# Reset cluster (keeps data)
sudo k3s server --cluster-reset
```

Networking Details
------------------

### VPN-Based Cluster Architecture

```
┌─────────────────┐    NetBird VPN    ┌─────────────────┐
│   K3s Server    │◄──────────────────►│   K3s Agent     │
│   VPN IP: 100.x │                   │   VPN IP: 100.y │
│   Port: 6443    │                   │                 │
└─────────────────┘                   └─────────────────┘
        │                                      │
        └──────── Flannel VXLAN over VPN ─────┘
```

### Interface Configuration
- **wt0**: NetBird VPN interface for all cluster traffic
- **flannel.1**: VXLAN interface bound to wt0
- **eth0**: Host interface (not used for cluster traffic)

File Structure
--------------

```
roles/k3s_server/
├── README.md
├── defaults/main.yml          # Default variables and configuration
├── handlers/main.yml          # Service restart handlers
├── tasks/main.yml            # Main installation and configuration tasks
└── templates/
    └── config.yaml.j2        # Dynamic K3s configuration template
```

Security Considerations
-----------------------

- K3s API server accessible only via VPN
- All cluster traffic encrypted through NetBird tunnel
- Kubeconfig has restrictive permissions (600)
- TLS certificates include VPN IP for secure access

License
-------

MIT

Author Information
------------------

Part of the K3s GPU cluster automation project for deploying control plane nodes with NetBird VPN networking and GPU workload optimization.
