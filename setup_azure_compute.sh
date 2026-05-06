#!/bin/bash
# =============================================================================
# Azure ML Compute Setup Script
# Run once on a new compute to configure git, git-lfs, and credentials.
# =============================================================================


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

info()    { echo -e "${GREEN}[✓]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
err()     { echo -e "${RED}[✗]${NC} $1"; }
section() { echo -e "\n${YELLOW}--- $1 ---${NC}"; }

# -----------------------------------------------------------------------------
# 1. Git identity
# -----------------------------------------------------------------------------

section "Git Identity"

# Use environment variables if set, otherwise prompt
GIT_USER_NAME="${GIT_USER_NAME:-}"
GIT_USER_EMAIL="${GIT_USER_EMAIL:-}"

if [ -z "$GIT_USER_NAME" ]; then
    read -rp "  Git username (e.g. Jane Smith): " GIT_USER_NAME
fi

if [ -z "$GIT_USER_EMAIL" ]; then
    read -rp "  Git email (e.g. jane@example.com): " GIT_USER_EMAIL
fi

git config --global user.name  "$GIT_USER_NAME"
git config --global user.email "$GIT_USER_EMAIL"
info "Identity set: $GIT_USER_NAME <$GIT_USER_EMAIL>"

# -----------------------------------------------------------------------------
# 2. Credential persistence
# -----------------------------------------------------------------------------

section "Credential Persistence"

git config --global credential.helper store
info "Credential helper set to 'store' (persists to ~/.git-credentials)"
warn "Credentials are stored in plaintext — fine for a private compute instance"

# If credentials are already stored, report that, otherwise prompt for a PAT
if [ -f "$HOME/.git-credentials" ] && [ -s "$HOME/.git-credentials" ]; then
    info "~/.git-credentials already exists and is non-empty, skipping PAT entry"
else
    warn "No stored credentials found."
    read -rp "  Enter your Azure DevOps PAT (leave blank to skip and enter on first push): " ADO_PAT
    if [ -n "$ADO_PAT" ]; then
        # todo: support other Azure DevOps org names if needed
        read -rp "  Azure DevOps org name (e.g. myorg from dev.azure.com/myorg): " ADO_ORG
        echo "https://${ADO_ORG}:${ADO_PAT}@dev.azure.com" >> "$HOME/.git-credentials"
        chmod 600 "$HOME/.git-credentials"
        info "PAT stored in ~/.git-credentials"
    else
        warn "Skipped — you will be prompted for credentials on your first push/pull"
    fi
fi

# -----------------------------------------------------------------------------
# 3. HTTP version (force HTTP/1.1 for git's libcurl layer)
# -----------------------------------------------------------------------------

section "HTTP Version (git / libcurl)"

git config --global http.version HTTP/1.1
info "git http.version set to HTTP/1.1"

# -----------------------------------------------------------------------------
# 4. Disable HTTP/2 in Go runtime (fixes git-lfs 413 on Azure DevOps)
#
# Root cause: git-lfs uses Go's net/http which auto-upgrades to HTTP/2,
# then sends Transfer-Encoding: chunked which is invalid in HTTP/2.
# Azure Front Door rejects this with 413 Request Entity Too Large.
# GODEBUG=http2client=0 forces Go's HTTP client to use HTTP/1.1.
# -----------------------------------------------------------------------------

section "Git LFS — Disable HTTP/2 in Go Runtime"

GODEBUG_LINE='export GODEBUG=http2client=0'

add_to_profile() {
    local profile_file="$1"
    if [ -f "$profile_file" ]; then
        if grep -qF "GODEBUG=http2client=0" "$profile_file"; then
            info "GODEBUG already set in $profile_file"
        else
            echo "" >> "$profile_file"
            echo "# Disable HTTP/2 in Go runtime — required for git-lfs pushes to Azure DevOps" >> "$profile_file"
            echo "$GODEBUG_LINE" >> "$profile_file"
            info "Added GODEBUG=http2client=0 to $profile_file"
        fi
    fi
}

# Add to all relevant profile files so it applies in interactive, login, and non-interactive shells
add_to_profile "$HOME/.bashrc"
add_to_profile "$HOME/.bash_profile"
add_to_profile "$HOME/.profile"

# Also export in the current session so this script's caller gets it immediately
export GODEBUG=http2client=0
info "GODEBUG=http2client=0 exported in current session"

# -----------------------------------------------------------------------------
# 5. Git LFS config
# -----------------------------------------------------------------------------

section "Git LFS Config"

sudo apt install git-lfs
# Ensure lfs is installed (sets up filters in ~/.gitconfig)
git lfs install --skip-repo 2>/dev/null && info "git lfs install: OK" || warn "git lfs install failed — is git-lfs installed?"

git config --global lfs.concurrenttransfers 1
info "lfs.concurrenttransfers set to 1 (avoids race conditions on Azure)"

# -----------------------------------------------------------------------------
# 6. HTTP tuning (belt-and-suspenders for large uploads)
# -----------------------------------------------------------------------------

section "HTTP Tuning"

git config --global http.postBuffer    524288000   # 500 MB
git config --global http.lowSpeedLimit 0
git config --global http.lowSpeedTime  999999
info "http.postBuffer set to 500MB"
info "http.lowSpeedLimit/Time: disabled (prevents timeout on large uploads)"

# -----------------------------------------------------------------------------
# 7. Summary
# -----------------------------------------------------------------------------

section "Done — Current Config"
echo ""
git config --global --list | grep -E "user\.|credential\.|http\.|lfs\." | sort
echo ""
info "All done! You may need to open a new shell (or run 'source ~/.bashrc') for GODEBUG to take effect in other sessions."