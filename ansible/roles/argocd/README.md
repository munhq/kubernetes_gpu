ArgoCD
======

Installs and configures ArgoCD on a K3s cluster with GPU workloads support, GitHub App integration, and GitOps automation.

Description
-----------

This role deploys ArgoCD using Helm, configures it for GitOps operations, and sets up the necessary infrastructure for managing GPU workloads. It includes:

- ArgoCD installation via Helm chart
- GitHub App integration for private repository access
- Namespace and secret management for GPU workloads
- Application and ApplicationSet bootstrapping
- ArgoCD project configuration

Requirements
------------

- K3s cluster running on target hosts
- Helm installed on target hosts
- `kubernetes.core` collection installed
- GitHub App configured with repository access (for private repositories)
- Vault variables for sensitive data (GitHub tokens, API keys)

Role Variables
--------------

### Default Variables (defaults/main.yml)

```yaml
argocd_namespace: argocd                 # Namespace where ArgoCD will be installed
argocd_helm_version: "9.4.1"           # ArgoCD Helm chart version
argocd_nodeport: 30443                  # NodePort for ArgoCD server access
argocd_repo_url: ""                     # Repository URL (auto-configured)
argocd_repo_revision: main              # Git branch/tag to track
argocd_apps_path: argocd/apps           # Path to ArgoCD applications in repo
```

### Required Variables

These variables must be provided via vault or inventory:

```yaml
# GitHub App configuration (for private repositories)
argocd_github_app_id: "123456"                    # GitHub App ID
argocd_github_app_installation_id: "12345678"     # GitHub App Installation ID
argocd_github_app_private_key: |                  # GitHub App private key (PEM format)
  -----BEGIN RSA PRIVATE KEY-----
  ...
  -----END RSA PRIVATE KEY-----

# Container registry access
vault_ghcr_pull_token: "ghp_xxxxxxxxxxxx"         # GitHub token for GHCR access

# GPU API configuration
gpu_api_secret: "your-api-secret-key"              # Secret for GPU API authentication
```

### Host Variables

The role uses `ansible_host` to determine the ArgoCD access URL.

Dependencies
------------

- Ansible collections:
  - `kubernetes.core`
  - `ansible.builtin`

Features
--------

### Core Installation
- Installs ArgoCD via official Helm chart
- Configures NodePort access for web UI
- Enables insecure mode for development
- Disables Dex (uses built-in auth)

### GitHub Integration
- Installs ArgoCD CLI
- Configures GitHub App authentication
- Adds private repository access
- Verifies repository connectivity

### GPU Workloads Support
- Creates `gpu-workloads` namespace
- Configures GHCR pull secrets for container images
- Sets up GPU API authentication secrets

### GitOps Automation
- Applies ArgoCD projects from repository
- Bootstraps ApplicationSets for automatic application discovery
- Enables auto-sync with pruning and self-healing

Example Playbook
----------------

```yaml
- hosts: k3s_servers
  vars:
    # GitHub App configuration
    argocd_github_app_id: "123456"
    argocd_github_app_installation_id: "12345678"
    argocd_github_app_private_key: "{{ vault_github_app_private_key }}"
    
    # Container registry access
    vault_ghcr_pull_token: "{{ vault_ghcr_token }}"
    
    # GPU API configuration
    gpu_api_secret: "{{ vault_gpu_api_secret }}"
  roles:
    - argocd
```

### With custom configuration:

```yaml
- hosts: k3s_servers
  vars:
    argocd_namespace: my-argocd
    argocd_nodeport: 32443
    argocd_helm_version: "9.5.0"
    # ... other required vars
  roles:
    - argocd
```

Post-Installation Access
------------------------

After successful installation, ArgoCD will be accessible at:

- **URL**: `https://{{ ansible_host }}:{{ argocd_nodeport }}`
- **Username**: `admin`
- **Password**: Retrieved automatically and displayed during installation

The role will output the access credentials for immediate use.

File Structure
--------------

```
roles/argocd/
├── README.md
├── defaults/main.yml          # Default variables
├── handlers/main.yml          # Empty handlers file
└── tasks/
    ├── main.yml              # Primary installation tasks
    └── configure-github-app.yml  # GitHub App configuration tasks
```

Tags
----

- `configure-repo`: Runs only the GitHub App configuration tasks

Troubleshooting
---------------

### Common Issues

1. **ArgoCD server not ready**: The role waits up to 10 minutes for deployment
2. **GitHub App authentication fails**: Verify App ID, Installation ID, and private key
3. **Repository access denied**: Check GitHub App permissions and installation scope

### Manual Verification

```bash
# Check ArgoCD pods
kubectl get pods -n argocd

# Verify repository configuration
argocd repo list

# Check ApplicationSets
kubectl get applicationsets -n argocd
```

License
-------

MIT

Author Information
------------------

Part of the K3s GPU cluster automation project for managing GitOps deployments with GPU workloads support.
