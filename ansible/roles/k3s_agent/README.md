K3s Agent
=========

Installs and configures K3s agent nodes to join an existing K3s cluster over NetBird VPN.

Description
-----------

This role deploys K3s agent nodes that connect to an existing K3s server cluster. It includes:

- NetBird VPN connectivity verification and management
- K3s agent installation and configuration
- Node registration with custom labels and taints
- VPN-based networking with Flannel CNI
- Automatic cleanup of stale node entries
- Node health verification and monitoring

The role is specifically designed for GPU clusters where agents connect over NetBird VPN and use VPN IPs for cluster communication.

Requirements
------------

- Target hosts must have NetBird VPN client installed and configured
- K3s server must be running and accessible via NetBird VPN
- Inventory must include a `k3s_server` group with at least one host
- Server host must have `k3s_server_url` and `k3s_token` facts available

Role Variables
--------------

### Default Variables (defaults/main.yml)

```yaml
k3s_version: "v1.29.2+k3s1"    # K3s version to install
```

### Required Variables

These variables are automatically retrieved from the K3s server host:

```yaml
k3s_server_url: "https://SERVER_IP:6443"    # Obtained from server host facts
k3s_token: "K3S_TOKEN_VALUE"                # Obtained from server host facts
```

### Optional Variables

```yaml
# Node labels to apply after registration
k3s_node_labels:
  node.kubernetes.io/instance-type: "gpu-node"
  cluster.local/gpu: "true"
  topology.kubernetes.io/zone: "zone-a"

# Node taints to apply after registration
k3s_node_taints:
  - "nvidia.com/gpu=true:NoSchedule"
  - "node.kubernetes.io/instance-type=gpu:NoSchedule"
```

### Automatic Variables

The role automatically detects and manages:

```yaml
netbird_vpn_ip: "100.x.x.x"                # Detected NetBird VPN IP
netbird_vpn_ip_changed: false              # Whether VPN IP changed since last run
```

Dependencies
------------

- NetBird VPN client installed and running on agent hosts
- K3s server role must be executed first on server nodes
- Ansible collections:
  - `ansible.builtin`

Features
--------

### NetBird VPN Management
- Automatically detects current NetBird VPN IP
- Restarts NetBird service if IP changed
- Verifies connectivity to K3s server via VPN
- Uses VPN interface (`wt0`) for Flannel networking

### K3s Agent Installation
- Downloads and installs specified K3s version
- Configures agent with VPN-specific network settings
- Sets node name to inventory hostname
- Uses NetBird IP for both internal and external node IP

### Node Registration & Configuration
- Automatically registers with K3s server
- Applies custom node labels for workload scheduling
- Applies node taints for specialized workloads
- Handles cleanup of stale node entries from previous installations

### Health Verification
- Waits for CNI network initialization
- Verifies K3s agent service is active
- Confirms node registration with server
- Validates connectivity throughout the process

Installation Process
--------------------

1. **VPN Verification**: Checks NetBird status and connectivity
2. **Cleanup**: Removes any stale node entries from previous installations
3. **Download**: Fetches K3s installation script
4. **Install**: Installs K3s agent with VPN-specific configuration
5. **Service**: Enables and starts K3s agent service
6. **Wait**: Waits for CNI and service initialization
7. **Register**: Verifies node registration with server
8. **Configure**: Applies labels and taints
9. **Verify**: Confirms successful installation

Example Playbook
----------------

### Basic Usage

```yaml
- hosts: k3s_agents
  roles:
    - k3s_agent
```

### With Node Labels and Taints

```yaml
- hosts: k3s_agents
  vars:
    k3s_node_labels:
      node.kubernetes.io/instance-type: "gpu-worker"
      cluster.local/gpu: "true"
      hardware.local/gpu-count: "2"
    k3s_node_taints:
      - "nvidia.com/gpu=true:NoSchedule"
  roles:
    - k3s_agent
```

### GPU Node Configuration

```yaml
- hosts: gpu_workers
  vars:
    k3s_version: "v1.29.2+k3s1"
    k3s_node_labels:
      node.kubernetes.io/instance-type: "gpu-node"
      cluster.local/gpu: "nvidia-rtx-4090"
      cluster.local/gpu-memory: "24GB"
    k3s_node_taints:
      - "nvidia.com/gpu=true:NoSchedule"
      - "cluster.local/gpu-exclusive=true:NoExecute"
  roles:
    - k3s_agent
```

Network Configuration
---------------------

The role configures K3s agent with specific network settings for VPN operation:

```bash
--node-ip={{ netbird_vpn_ip }}           # Use VPN IP for cluster communication
--node-external-ip={{ netbird_vpn_ip }}  # Use VPN IP for external access
--flannel-iface=wt0                      # Use NetBird interface for Flannel
```

This ensures all cluster traffic flows over the secure NetBird VPN tunnel.

Handlers
--------

- `restart k3s-agent`: Restarts the K3s agent service

Troubleshooting
---------------

### Common Issues

1. **NetBird connectivity**: Verify NetBird service is running and connected
2. **Server unreachable**: Check NetBird VPN connectivity between agent and server
3. **Node not joining**: Verify K3s token and server URL are correct
4. **CNI timeout**: Network initialization may take longer on some systems

### Manual Verification

```bash
# Check NetBird status
netbird status

# Verify K3s agent service
systemctl status k3s-agent

# Check node registration (from server)
kubectl get nodes

# View K3s agent logs
journalctl -u k3s-agent -f

# Test connectivity to server
ping SERVER_VPN_IP
```

### Recovery Commands

```bash
# Restart NetBird if connectivity issues
sudo systemctl restart netbird

# Restart K3s agent
sudo systemctl restart k3s-agent

# Clean reinstall (removes node completely)
sudo /usr/local/bin/k3s-agent-uninstall.sh
```

File Structure
--------------

```
roles/k3s_agent/
├── README.md
├── defaults/main.yml          # Default K3s version
├── handlers/main.yml          # Service restart handler
└── tasks/main.yml            # Main installation and configuration tasks
```

Post-Installation
------------------

After successful installation:

1. Node appears in `kubectl get nodes` on the server
2. K3s agent service runs continuously
3. Node is ready to schedule workloads (unless tainted)
4. VPN connectivity is maintained for cluster communication

The role provides detailed output about the installation status and node configuration.

License
-------

MIT

Author Information
------------------

Part of the K3s GPU cluster automation project for deploying agent nodes with NetBird VPN networking and GPU workload support.
