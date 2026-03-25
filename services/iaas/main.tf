# ═══════════════════════════════════════════════════════════════════════════════
# HUNGU — Huawei Cloud Free Tier Infrastructure
# Region:  af-south-1 (Johannesburg, South Africa)
# Stack:   ECS (Docker host) + EIP + VPC/Subnet/SG
#
# FREE TIER ELIGIBILITY (verify at https://www.huaweicloud.com/intl/en-us/free):
#   ECS   s6.small.1          1 vCPU · 1 GB RAM  — 12 months free
#   ECS System Disk  40 GB SSD (GPSSD)            — included
#   EIP   5 Mbps pay-by-traffic                   — ~free while bound to ECS
#   VPC / Subnets / Security Groups               — always free
#
# NOTE: PostgreSQL runs inside Docker alongside the app containers.
#       Data is persisted to a named Docker volume on the ECS disk.
#       Free tier specs change — check the Huawei Cloud Free Package page.
#
# USAGE:
#   1. cp terraform.tfvars.example terraform.tfvars   (fill in all values)
#   2. terraform init
#   3. terraform plan
#   4. terraform apply
#   5. Copy outputs and run:  bash deploy.sh
# ═══════════════════════════════════════════════════════════════════════════════

terraform {
  required_providers {
    huaweicloud = {
      source  = "huaweicloud/huaweicloud"
      version = ">= 1.36.0"
    }
    null = {
      source  = "hashicorp/null"
      version = ">= 3.0"
    }
  }
  # Remote state stored in Huawei OBS (S3-compatible).
  # Config is passed via -backend-config flags — never hardcoded here.
  # Local:         terraform init -backend-config=backend.hcl  (see backend.hcl.example)
  # GitHub Actions: flags are set in .github/workflows/terraform.yml automatically.
  backend "s3" {}
}

# ─── Credentials & Config Variables ──────────────────────────────────────────

variable "hw_access_key" {
  description = "Huawei Cloud IAM Access Key (AK)"
  type        = string
  sensitive   = true
}

variable "hw_secret_key" {
  description = "Huawei Cloud IAM Secret Key (SK)"
  type        = string
  sensitive   = true
}

variable "ssh_public_key" {
  description = "Your SSH public key content (e.g. contents of ~/.ssh/id_rsa.pub)"
  type        = string
}

variable "db_password" {
  description = "PostgreSQL password for the Docker database container."
  type        = string
  sensitive   = true
}

variable "admin_secret" {
  description = "Admin dashboard secret key (X-Admin-Key header)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "db_username" {
  description = "PostgreSQL master username"
  type        = string
  default     = "hungu"
}

variable "gemini_api_key" {
  description = "Google Gemini API key for the AI worker"
  type        = string
  sensitive   = true
  default     = ""
}

variable "jwt_secret" {
  description = "Secret string used to sign JWT tokens in the API"
  type        = string
  sensitive   = true
  default     = "change_me_a_long_random_secret"
}

variable "worker_api_key" {
  description = "Shared secret between worker and API (X-Worker-Key header)"
  type        = string
  sensitive   = true
  default     = "change_me_worker_key"
}

variable "domain_name" {
  description = "Primary domain for the HUNGU app (used in nginx config and .env)"
  type        = string
  default     = "hungu.co.za"
}

variable "deepseek_api_key" {
  description = "DeepSeek API key for the AI worker"
  type        = string
  sensitive   = true
  default     = ""
}

variable "groq_api_key" {
  description = "Groq API key for the AI worker"
  type        = string
  sensitive   = true
  default     = ""
}

variable "mistral_api_key" {
  description = "Mistral API key for the AI worker"
  type        = string
  sensitive   = true
  default     = ""
}

variable "openrouter_api_key" {
  description = "OpenRouter API key for the AI worker"
  type        = string
  sensitive   = true
  default     = ""
}

variable "cerebras_api_key" {
  description = "Cerebras API key for the AI worker"
  type        = string
  sensitive   = true
  default     = ""
}

variable "sambanova_api_key" {
  description = "SambaNova API key for the AI worker"
  type        = string
  sensitive   = true
  default     = ""
}

variable "kimi_api_key" {
  description = "Kimi (Moonshot) API key for the AI worker"
  type        = string
  sensitive   = true
  default     = ""
}

variable "google_client_id" {
  description = "Google OAuth Client ID for the app"
  type        = string
  sensitive   = true
  default     = ""
}

variable "ssh_private_key_path" {
  description = "Absolute path to the SSH private key used to connect to the server (e.g. ~/.ssh/hungu_rsa)"
  type        = string
  default     = "~/.ssh/hungu_rsa"
}

variable "region" {
  description = "Huawei Cloud region"
  type        = string
  default     = "af-south-1"
}

variable "availability_zone" {
  description = "Availability zone inside the region"
  type        = string
  default     = "af-south-1a"
}

# ─── Provider ─────────────────────────────────────────────────────────────────

provider "huaweicloud" {
  region     = var.region
  access_key = var.hw_access_key
  secret_key = var.hw_secret_key
}

# ─── 1. Networking ────────────────────────────────────────────────────────────

resource "huaweicloud_vpc" "hungu_vpc" {
  name = "hungu-vpc"
  cidr = "10.0.0.0/16"
}

# App subnet — ECS lives here (has internet access via EIP)
resource "huaweicloud_vpc_subnet" "app_subnet" {
  name       = "hungu-app-subnet"
  cidr       = "10.0.1.0/24"
  gateway_ip = "10.0.1.1"
  vpc_id     = huaweicloud_vpc.hungu_vpc.id
}

# ─── 2. Security Groups ───────────────────────────────────────────────────────

# App security group: HTTP(S) + SSH from internet
resource "huaweicloud_networking_secgroup" "app_sg" {
  name        = "hungu-app-sg"
  description = "HUNGU app server — HTTP, HTTPS, SSH"
}

resource "huaweicloud_networking_secgroup_rule" "allow_http" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 80
  port_range_max    = 80
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = huaweicloud_networking_secgroup.app_sg.id
}

resource "huaweicloud_networking_secgroup_rule" "allow_https" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 443
  port_range_max    = 443
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = huaweicloud_networking_secgroup.app_sg.id
}

# SSH — restrict to your own IP in production (replace 0.0.0.0/0)
resource "huaweicloud_networking_secgroup_rule" "allow_ssh" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = "0.0.0.0/0" # TODO: replace with your IP/32 in production
  security_group_id = huaweicloud_networking_secgroup.app_sg.id
}

# ─── 3. SSH Key Pair ──────────────────────────────────────────────────────────

resource "huaweicloud_compute_keypair" "hungu_keypair" {
  name       = "hungu-keypair"
  public_key = var.ssh_public_key
}

# ─── 4. ECS Instance — Free Tier ─────────────────────────────────────────────
#
# s6.small.1 = 1 vCPU · 1 GB RAM (free tier 12 months in af-south-1)
# Runs four Docker containers: web (nginx) + api (FastAPI) + worker + db (PostgreSQL)
# PostgreSQL data is persisted in a Docker named volume on the system disk.

locals {
  # DB connection string uses Docker internal networking
  db_url = "postgresql://${var.db_username}:${var.db_password}@db:5432/hungu"

  # Full .env content — written to the server by null_resource on every apply when keys change
  env_file_content = join("\n", [
    "GEMINI_API_KEY=${var.gemini_api_key}",
    "DEEPSEEK_API_KEY=${var.deepseek_api_key}",
    "GROQ_API_KEY=${var.groq_api_key}",
    "MISTRAL_API_KEY=${var.mistral_api_key}",
    "OPENROUTER_API_KEY=${var.openrouter_api_key}",
    "CEREBRAS_API_KEY=${var.cerebras_api_key}",
    "SAMBANOVA_API_KEY=${var.sambanova_api_key}",
    "KIMI_API_KEY=${var.kimi_api_key}",
    "GOOGLE_CLIENT_ID=${var.google_client_id}",
    "DB_URL=${local.db_url}",
    "DB_USERNAME=${var.db_username}",
    "DB_PASSWORD=${var.db_password}",
    "DOMAIN=${var.domain_name}",
    "JWT_SECRET=${var.jwt_secret}",
    "WORKER_API_KEY=${var.worker_api_key}",
    "ADMIN_SECRET=${var.admin_secret}",
    "SCRAPE_INTERVAL_SECS=3600",
    "API_BASE_URL=http://api:8000",
    "",
  ])

  # cloud-init user_data script
  startup_script = <<-SCRIPT
    #!/bin/bash
    set -euo pipefail
    export DEBIAN_FRONTEND=noninteractive

    echo "==> HUNGU: Installing Docker..."
    apt-get update -qq
    apt-get install -y -qq apt-transport-https ca-certificates curl gnupg lsb-release git

    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
      | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin

    systemctl enable docker
    systemctl start docker
    usermod -aG docker ubuntu

    echo "==> HUNGU: Creating project directory..."
    mkdir -p /opt/hungu
    chown ubuntu:ubuntu /opt/hungu

    echo "==> HUNGU: Writing .env..."
    cat > /opt/hungu/.env <<ENV
    GEMINI_API_KEY=${var.gemini_api_key}
    DEEPSEEK_API_KEY=${var.deepseek_api_key}
    GROQ_API_KEY=${var.groq_api_key}
    MISTRAL_API_KEY=${var.mistral_api_key}
    OPENROUTER_API_KEY=${var.openrouter_api_key}
    CEREBRAS_API_KEY=${var.cerebras_api_key}
    SAMBANOVA_API_KEY=${var.sambanova_api_key}
    KIMI_API_KEY=${var.kimi_api_key}
    GOOGLE_CLIENT_ID=${var.google_client_id}
    DB_URL=${local.db_url}
    DB_PASSWORD=${var.db_password}
    DB_USERNAME=${var.db_username}
    DOMAIN=${var.domain_name}
    JWT_SECRET=${var.jwt_secret}
    WORKER_API_KEY=${var.worker_api_key}
    ADMIN_SECRET=${var.admin_secret}
    SCRAPE_INTERVAL_SECS=3600
    API_BASE_URL=http://api:8000
    ENV

    echo "==> HUNGU: Writing production docker-compose override..."
    cat > /opt/hungu/docker-compose.prod.yml <<COMPOSE
    version: '3.8'
    services:
      web:
        restart: always
        ports:
          - "80:80"
      api:
        restart: always
        environment:
          - DB_URL=${local.db_url}
          - JWT_SECRET=${var.jwt_secret}
          - GEMINI_API_KEY=${var.gemini_api_key}
          - WORKER_API_KEY=${var.worker_api_key}
          - ADMIN_SECRET=${var.admin_secret}
      worker:
        restart: always
        environment:
          - GEMINI_API_KEY=${var.gemini_api_key}
          - DEEPSEEK_API_KEY=${var.deepseek_api_key}
          - GROQ_API_KEY=${var.groq_api_key}
          - MISTRAL_API_KEY=${var.mistral_api_key}
          - OPENROUTER_API_KEY=${var.openrouter_api_key}
          - CEREBRAS_API_KEY=${var.cerebras_api_key}
          - SAMBANOVA_API_KEY=${var.sambanova_api_key}
          - KIMI_API_KEY=${var.kimi_api_key}
          - API_BASE_URL=http://api:8000
          - WORKER_API_KEY=${var.worker_api_key}
          - SCRAPE_INTERVAL_SECS=3600
      db:
        restart: always
    COMPOSE

    echo "==> HUNGU: Writing deploy helper..."
    cat > /opt/hungu/deploy.sh <<DEPLOY
    #!/bin/bash
    set -euo pipefail
    cd /opt/hungu
    echo "Pulling latest images and starting HUNGU..."
    docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
    echo "HUNGU is running! Check: docker compose ps"
    DEPLOY
    chmod +x /opt/hungu/deploy.sh

    chown -R ubuntu:ubuntu /opt/hungu
    echo "==> HUNGU bootstrap complete. SSH in and run: bash /opt/hungu/deploy.sh"
  SCRIPT
}

resource "huaweicloud_compute_instance" "hungu_server" {
  name               = "hungu-server"
  image_name         = "Ubuntu 22.04 server 64bit"
  flavor_id          = "s6.small.1" # 1 vCPU · 1 GB — free tier eligible
  key_pair           = huaweicloud_compute_keypair.hungu_keypair.name
  security_group_ids = [huaweicloud_networking_secgroup.app_sg.id]
  availability_zone  = var.availability_zone

  network {
    uuid = huaweicloud_vpc_subnet.app_subnet.id
  }

  system_disk_type = "GPSSD" # General Purpose SSD — free tier eligible
  system_disk_size = 40      # 40 GB — free tier threshold

  user_data = base64encode(local.startup_script)

  tags = {
    project = "hungu"
    env     = "production"
  }
}

# ─── 5. Elastic IP (EIP) ──────────────────────────────────────────────────────

resource "huaweicloud_vpc_eip" "hungu_eip" {
  publicip {
    type = "5_bgp" # Standard BGP — available in af-south-1
  }
  bandwidth {
    name        = "hungu-bandwidth"
    size        = 5            # 5 Mbps — within free tier bandwidth
    share_type  = "PER"
    charge_mode = "traffic"    # Pay-by-traffic (usually needed for free tier)
  }
  tags = {
    project = "hungu"
    env     = "production"
  }
}

resource "huaweicloud_compute_eip_associate" "hungu_eip_bind" {
  public_ip   = huaweicloud_vpc_eip.hungu_eip.address
  instance_id = huaweicloud_compute_instance.hungu_server.id
}

# ─── 6. Deployment — handled by GitHub Actions ───────────────────────────────
# App code deployment (git pull + docker compose up) is done by the
# GitHub Actions workflow in .github/workflows/terraform.yml.
# Terraform only manages infrastructure — not application code.

# ─── 7. Live env update — re-runs whenever any API key or secret changes ──────
# Writes the full .env to the running server and redeploys the containers.
# Requires ssh_private_key_path to point to the key that can SSH as root.

resource "null_resource" "update_env" {
  triggers = {
    env_hash = sha256(local.env_file_content)
  }

  connection {
    type        = "ssh"
    user        = "root"
    private_key = file(pathexpand(var.ssh_private_key_path))
    host        = huaweicloud_vpc_eip.hungu_eip.address
  }

  provisioner "remote-exec" {
    inline = [
      # Write .env via base64 to safely handle any special characters in key values
      "echo '${base64encode(local.env_file_content)}' | base64 -d > /opt/hungu/.env",
      # Ensure git remote uses SSH (survives git checkout --) 
      "git -C /opt/hungu remote set-url origin git@github.com:Plengo/hungu.git",
      # Pull latest code and redeploy
      "cd /opt/hungu && git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build",
    ]
  }

  depends_on = [huaweicloud_compute_eip_associate.hungu_eip_bind]
}

# ─── Outputs ──────────────────────────────────────────────────────────────────

output "public_ip" {
  value       = huaweicloud_vpc_eip.hungu_eip.address
  description = "ECS public IP — point your DNS A record here."
}

output "ssh_command" {
  value       = "ssh ubuntu@${huaweicloud_vpc_eip.hungu_eip.address}"
  description = "SSH command to connect to your HUNGU server."
}

output "dns_instruction" {
  value       = "Point an A record for ${var.domain_name} → ${huaweicloud_vpc_eip.hungu_eip.address}"
  description = "DNS record to create at your registrar (e.g. Axxess)."
}

output "deploy_instructions" {
  value = <<-INSTRUCTIONS
    ════════════════════════════════════════════════════
     HUNGU infrastructure ready!
    ════════════════════════════════════════════════════
    Domain  : ${var.domain_name}
    Server  : ${huaweicloud_vpc_eip.hungu_eip.address}
    SSH     : ssh ubuntu@${huaweicloud_vpc_eip.hungu_eip.address}

    ── DNS (Axxess) ──────────────────────────────────
    Add an A record:
      Name: @   Type: A   Value: ${huaweicloud_vpc_eip.hungu_eip.address}
      Name: www Type: A   Value: ${huaweicloud_vpc_eip.hungu_eip.address}

    ── After first terraform apply ───────────────────
    The .env is already written on the server by cloud-init.
    Push to main → GitHub Actions deploys the app automatically.
    ════════════════════════════════════════════════════
  INSTRUCTIONS
  description = "Post-deployment steps."
}