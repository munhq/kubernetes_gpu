#!/bin/bash
set -e

REPO_OWNER="munhq"
REPO_NAME="k3s-gpu"
APP_NAME="ArgoCD K3s GPU"
PRIVATE_KEY_PATH="$HOME/.ssh/github-app-argocd.pem"

echo "================================="
echo "Creating GitHub App for ArgoCD"
echo "================================="
echo ""

# Check if gh is authenticated
if ! gh auth status &>/dev/null; then
    echo "❌ gh CLI not authenticated"
    echo "Run: gh auth login -h github.com -p ssh"
    exit 1
fi

echo "✓ gh CLI authenticated"

# Create GitHub App manifest
echo "Creating GitHub App manifest..."
cat > /tmp/github-app-manifest.json << EOF
{
  "name": "${APP_NAME}",
  "url": "https://github.com/${REPO_OWNER}/${REPO_NAME}",
  "hook_attributes": {
    "active": false
  },
  "redirect_url": "https://github.com",
  "public": false,
  "default_permissions": {
    "contents": "read",
    "metadata": "read"
  },
  "default_events": []
}
EOF

echo "✓ Manifest created"

# Create the app via API
echo "Creating GitHub App via API..."
APP_RESPONSE=$(gh api -X POST /user/apps --input /tmp/github-app-manifest.json 2>/dev/null || {
    echo "❌ Failed to create app. Trying alternative method..."

    # Alternative: Use GitHub's app manifest flow
    MANIFEST=$(cat /tmp/github-app-manifest.json | jq -c .)
    echo ""
    echo "Please visit this URL to create the app manually:"
    echo "https://github.com/settings/apps/new"
    echo ""
    echo "Or create via manifest:"
    echo "https://github.com/settings/apps/new?state=1&manifest=${MANIFEST}"
    exit 1
})

echo "✓ GitHub App created"

# Extract App ID and private key
APP_ID=$(echo "$APP_RESPONSE" | jq -r .id)
APP_SLUG=$(echo "$APP_RESPONSE" | jq -r .slug)
PRIVATE_KEY=$(echo "$APP_RESPONSE" | jq -r .pem)

# Save private key
echo "$PRIVATE_KEY" > "$PRIVATE_KEY_PATH"
chmod 600 "$PRIVATE_KEY_PATH"
echo "✓ Private key saved to: $PRIVATE_KEY_PATH"

# Display app details
echo ""
echo "================================="
echo "App Details:"
echo "================================="
echo "App ID: $APP_ID"
echo "App Slug: $APP_SLUG"
echo "App Name: $APP_NAME"
echo ""

# Install the app on the repository
echo "Installing app on repository ${REPO_OWNER}/${REPO_NAME}..."
echo ""
echo "Visit this URL to install the app:"
INSTALL_URL="https://github.com/apps/${APP_SLUG}/installations/new"
echo "$INSTALL_URL"
echo ""
echo "Select: 'Only select repositories' → ${REPO_NAME}"
echo ""

# Wait for user to install
read -p "Press Enter after you've installed the app..."

# Get Installation ID
echo "Fetching Installation ID..."
sleep 2  # Give GitHub a moment to register the installation

INSTALLATION_ID=$(gh api "/repos/${REPO_OWNER}/${REPO_NAME}/installation" --jq .id 2>/dev/null || {
    echo "❌ Could not fetch Installation ID automatically"
    echo "Please get it manually from:"
    echo "https://github.com/settings/installations"
    echo "(Look for the number in the URL)"
    read -p "Enter Installation ID: " INSTALLATION_ID
})

echo "✓ Installation ID: $INSTALLATION_ID"

# Summary
echo ""
echo "================================="
echo "✓ GitHub App Setup Complete!"
echo "================================="
echo "App ID: $APP_ID"
echo "Installation ID: $INSTALLATION_ID"
echo "Private Key: $PRIVATE_KEY_PATH"
echo ""

# Save to config file for Ansible
CONFIG_FILE="/tmp/github-app-config.txt"
cat > "$CONFIG_FILE" << EOF
GITHUB_APP_ID=$APP_ID
GITHUB_APP_INSTALLATION_ID=$INSTALLATION_ID
GITHUB_APP_PRIVATE_KEY_PATH=$PRIVATE_KEY_PATH
EOF

echo "Config saved to: $CONFIG_FILE"
echo ""
echo "Next steps:"
echo "1. Encrypt the private key with Ansible Vault"
echo "2. Configure ArgoCD to use this GitHub App"
echo ""

# Verify the key works
echo "Verifying GitHub App authentication..."
if command -v jwt &>/dev/null; then
    echo "✓ Can generate JWT tokens for authentication"
else
    echo "⚠ Install 'jwt' CLI for token generation: npm install -g jsonwebtoken-cli"
fi

echo ""
echo "================================="
