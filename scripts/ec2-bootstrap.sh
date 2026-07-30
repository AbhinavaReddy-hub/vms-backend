#!/usr/bin/env bash
#
# One-time server setup for a fresh Ubuntu 24.04 EC2 instance.
# Installs swap + Docker + the compose plugin. Does NOT deploy the app - that's
# a separate step, after you've written .env.
#
# Run:  bash scripts/ec2-bootstrap.sh
#
# Safe to re-run: every step checks whether it already happened first.

set -euo pipefail

echo "==> [1/4] Updating packages"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq

# ---------------------------------------------------------------------------
# Swap. t3.micro has 1GB of RAM and this stack peaks around 750MB, which leaves
# no headroom for a traffic spike or a pip install. 2GB of swap is the cushion
# that keeps the kernel from OOM-killing the face service.
# ---------------------------------------------------------------------------
echo "==> [2/4] Setting up 2GB swap"
if [ -f /swapfile ]; then
  echo "    /swapfile already exists, skipping"
else
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  # fstab entry makes it survive reboots
  if ! grep -q '^/swapfile' /etc/fstab; then
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
  fi
  # Default swappiness of 60 swaps too eagerly for a server; 10 means "only
  # when actually under pressure", so normal operation stays in RAM.
  sudo sysctl -w vm.swappiness=10 >/dev/null
  echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-swappiness.conf >/dev/null
fi

# ---------------------------------------------------------------------------
# Docker, from Docker's own apt repo. Ubuntu's packaged docker.io is older and
# does not ship the `docker compose` plugin (only the deprecated
# docker-compose v1 binary), which this project's commands assume.
# ---------------------------------------------------------------------------
echo "==> [3/4] Installing Docker + compose plugin"
if command -v docker >/dev/null 2>&1; then
  echo "    docker already installed, skipping"
else
  sudo apt-get install -y -qq ca-certificates curl gnupg
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -qq
  sudo apt-get install -y -qq \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

# Docker log rotation. Without this, container logs grow unbounded and
# eventually fill a 20GB volume - a slow, confusing way to take down a server.
if [ ! -f /etc/docker/daemon.json ]; then
  sudo mkdir -p /etc/docker
  sudo tee /etc/docker/daemon.json >/dev/null <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
JSON
  sudo systemctl restart docker
fi

sudo systemctl enable docker >/dev/null 2>&1 || true

echo "==> [4/4] Adding $USER to the docker group"
sudo usermod -aG docker "$USER"

echo
echo "============================================================"
echo " Bootstrap complete."
echo
free -h | sed 's/^/   /'
echo
echo "   docker:  $(docker --version 2>/dev/null || echo 'needs re-login')"
echo
echo " IMPORTANT: log out and back in before running docker, so the"
echo " group change applies:"
echo
echo "     exit"
echo "     ssh -i <your-key.pem> ubuntu@<this-instance-ip>"
echo
echo " Then verify with:  docker compose version"
echo "============================================================"
