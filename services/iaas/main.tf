# ═══════════════════════════════════════════════════════════════════════════════
# HUNGU — Huawei Cloud Free Tier Infrastructure
# Region:  af-south-1 (Johannesburg, South Africa)
# Stack:   ECS (Docker host) + RDS PostgreSQL (free) + EIP + VPC/Subnets/SGs
#
# FREE TIER ELIGIBILITY (verify at https://www.huaweicloud.com/intl/en-us/free):
#   ECS   s6.small.1          1 vCPU · 1 GB RAM  — 12 months free
#   RDS   rds.pg.n1.small.2   1 vCPU · 2 GB RAM  — 6 months free
#   ECS System Disk  40 GB SSD (GPSSD)            — included
#   RDS Volume       40 GB ULTRAHIGH SSD           — free-tier threshold
#   EIP   5 Mbps pay-by-traffic                   — ~free while bound to ECS
#   VPC / Subnets / Security Groups               — always free
#
# NOTE: Free tier specs change — check the Huawei Cloud Free Package page
#       before deploying. No local PostgreSQL container is used; RDS handles
#       all data storage, freeing up RAM on the ECS for the app containers.
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
  description = "PostgreSQL master password for RDS. Min 8 chars, must include uppercase, lowercase, digit, and special char."
  type        = string
  sensitive   = true
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

# DB subnet — RDS lives here (no public internet access)
resource "huaweicloud_vpc_subnet" "db_subnet" {
  name       = "hungu-db-subnet"
  cidr       = "10.0.2.0/24"
  gateway_ip = "10.0.2.1"
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

# DB security group: PostgreSQL ONLY from the app subnet — no public access
resource "huaweicloud_networking_secgroup" "db_sg" {
  name        = "hungu-db-sg"
  description = "HUNGU RDS — PostgreSQL access from app subnet only"
}

resource "huaweicloud_networking_secgroup_rule" "allow_postgres" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 5432
  port_range_max    = 5432
  remote_ip_prefix  = "10.0.1.0/24" # only the app subnet — never the internet
  security_group_id = huaweicloud_networking_secgroup.db_sg.id
}

# ─── 3. SSH Key Pair ──────────────────────────────────────────────────────────

resource "huaweicloud_compute_keypair" "hungu_keypair" {
  name       = "hungu-keypair"
  public_key = var.ssh_public_key
}

# ─── 4. RDS PostgreSQL — Free Tier ───────────────────────────────────────────
#
# Replaces the local PostgreSQL Docker container.
# RDS manages backups, patching, and HA automatically.
# The ECS app containers connect via the private RDS endpoint — no DB port
# is ever exposed to the internet.
#
# Free-tier flavor: rds.pg.n1.small.2 (1 vCPU · 2GB · af-south-1)
# Check the current eligible flavor at:
#   https://www.huaweicloud.com/intl/en-us/free/rds.html

resource "huaweicloud_rds_instance" "hungu_db" {
  name              = "hungu-postgres"
  flavor            = "rds.pg.n1.small.2" # Free-tier eligible — verify on Huawei Free page
  availability_zone = [var.availability_zone]
  vpc_id            = huaweicloud_vpc.hungu_vpc.id
  subnet_id         = huaweicloud_vpc_subnet.db_subnet.id
  security_group_id = huaweicloud_networking_secgroup.db_sg.id

  db {
    type     = "PostgreSQL"
    version  = "15"
    password = var.db_password
    port     = 5432
  }

  volume {
    type = "ULTRAHIGH" # SSD — required for RDS free tier in most regions
    size = 40          # 40 GB — stays within free tier storage quota
  }

  # Automated daily backups — free storage up to the instance disk size
  backup_strategy {
    start_time = "02:00-03:00" # off-peak for South Africa (UTC+2)
    keep_days  = 3
  }

  # tags for cost tracking
  tags = {
    project = "hungu"
    env     = "production"
  }
}

# Create the application database inside the RDS instance
resource "huaweicloud_rds_database" "hungu_appdb" {
  instance_id   = huaweicloud_rds_instance.hungu_db.id
  name          = "hungu"
  character_set = "UTF8"
}

# Create an app-level DB user (separate from the master user)
resource "huaweicloud_rds_pg_database_privilege" "app_user_priv" {
  instance_id = huaweicloud_rds_instance.hungu_db.id
  db_name     = huaweicloud_rds_database.hungu_appdb.name
  users {
    name       = var.db_username
    readonly   = false
  }
  depends_on = [huaweicloud_rds_database.hungu_appdb]
}

# ─── 5. ECS Instance — Free Tier ─────────────────────────────────────────────
#
# s6.small.1 = 1 vCPU · 1 GB RAM (free tier 12 months in af-south-1)
# Runs three lightweight Docker containers: web (nginx) + api (FastAPI) + worker
# No PostgreSQL container = ~300 MB RAM saved for the app services.

locals {
  # Build the DB connection string using the RDS internal endpoint
  db_url = "postgresql://${var.db_username}:${var.db_password}@${huaweicloud_rds_instance.hungu_db.private_ips[0]}:5432/hungu"

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
    DB_URL=${local.db_url}
    DB_PASSWORD=${var.db_password}
    JWT_SECRET=${var.jwt_secret}
    WORKER_API_KEY=${var.worker_api_key}
    DOMAIN=${var.domain_name}
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
      worker:
        restart: always
        environment:
          - GEMINI_API_KEY=${var.gemini_api_key}
          - API_BASE_URL=http://api:8000
          - SCRAPE_INTERVAL_SECS=3600
      db:
        deploy:
          replicas: 0   # disable local DB — using RDS instead
    COMPOSE

    echo "==> HUNGU: Writing deploy helper..."
    cat > /opt/hungu/deploy.sh <<DEPLOY
    #!/bin/bash
    set -euo pipefail
    cd /opt/hungu
    echo "Pulling latest images and starting HUNGU..."
    docker compose -f docker-compose.yml -f docker-compose.prod.yml pull || true
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

  # RDS must exist before the ECS boots so the DB URL is valid
  depends_on = [
    huaweicloud_rds_instance.hungu_db,
    huaweicloud_rds_database.hungu_appdb,
  ]

  tags = {
    project = "hungu"
    env     = "production"
  }
}

# ─── 6. Elastic IP (EIP) ──────────────────────────────────────────────────────

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

# ─── 7. Deployment — handled by GitHub Actions ───────────────────────────────
# App code deployment (git pull + docker compose up) is done by the
# GitHub Actions workflow in .github/workflows/terraform.yml.
# Terraform only manages infrastructure — not application code.

# ─── Outputs ──────────────────────────────────────────────────────────────────

output "public_ip" {
  value       = huaweicloud_vpc_eip.hungu_eip.address
  description = "ECS public IP — point your DNS A record here."
}

output "ssh_command" {
  value       = "ssh ubuntu@${huaweicloud_vpc_eip.hungu_eip.address}"
  description = "SSH command to connect to your HUNGU server."
}

output "rds_private_endpoint" {
  value       = huaweicloud_rds_instance.hungu_db.private_ips[0]
  description = "RDS private IP (reachable only from the app subnet)."
  sensitive   = false
}

output "rds_port" {
  value       = 5432
  description = "PostgreSQL port."
}

output "db_connection_string" {
  value       = local.db_url
  description = "Full PostgreSQL connection string for the API .env file."
  sensitive   = true  # contains password — use: terraform output -raw db_connection_string
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

    ── GitHub Actions (first-time setup) ─────────────
    Add these secrets in:
    GitHub → Settings → Secrets and variables → Actions

      HW_ACCESS_KEY   = <Huawei Cloud AK>
      HW_SECRET_KEY   = <Huawei Cloud SK>
      DB_PASSWORD     = <your RDS password>
      DB_USERNAME     = hungu
      GEMINI_API_KEY  = <your Gemini key>
      JWT_SECRET      = <openssl rand -hex 32>
      SSH_PUBLIC_KEY  = <cat ~/.ssh/id_rsa.pub>
      SSH_PRIVATE_KEY = <cat ~/.ssh/id_rsa>

    ── After first terraform apply ───────────────────
    The .env is already written on the server by cloud-init.
    Push to main → GitHub Actions deploys the app automatically.

    ── Get DB connection string locally ──────────────
    terraform output -raw db_connection_string
    ════════════════════════════════════════════════════
  INSTRUCTIONS
  description = "Post-deployment steps."
}