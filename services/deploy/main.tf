# ─── HUNGU Deploy — Axxess VPS ────────────────────────────────────────────────
#
# No cloud provider needed — the VPS is a pre-existing static server.
# This config only manages the application deployment via null_resource.
#
# On every `terraform apply`:
#   1. Bootstraps the server (installs Docker, clones repo) if fresh
#   2. Writes the full .env to the server (all secrets from TF vars)
#   3. git pull --ff-only  (latest code via HTTPS with github_token)
#   4. Injects GMAPS_API_KEY and WORKER_API_KEY into index.html placeholders
#   5. docker compose up -d --build --remove-orphans
#   6. Syncs nginx.host.conf if host nginx is already installed
#
# The null_resource triggers on git_sha (every push) AND env_hash (any secret change).
#
# Backend: none (-backend=false). State is not persisted — every apply always runs.
# This is intentional: null_resource with no state is always "new" = always deploys.
# ─────────────────────────────────────────────────────────────────────────────

terraform {
  required_version = ">= 1.3"
}

# ─── Server ───────────────────────────────────────────────────────────────────

locals {
  server_ip   = var.server_ip
  server_user = "root"
  app_dir     = "/opt/hungu"
  db_url      = "postgresql://${var.db_username}:${var.db_password}@db:5432/hungu"

  env_file_content = join("\n", [
    "GEMINI_API_KEY=${var.gemini_api_key}",
    "GMAPS_API_KEY=${var.gmaps_api_key}",
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
    "DOMAIN=hungu.co.za",
    "JWT_SECRET=${var.jwt_secret}",
    "WORKER_API_KEY=${var.worker_api_key}",
    "ADMIN_SECRET=${var.admin_secret}",
    "SCRAPE_INTERVAL_SECS=3600",
    "API_BASE_URL=http://api:8000",
    "ENVIRONMENT=prod",
    "",
  ])
}

# ─── Deploy ───────────────────────────────────────────────────────────────────

resource "null_resource" "deploy" {
  # Re-runs on every push (git_sha changes) AND whenever any secret changes (env_hash)
  triggers = {
    git_sha  = var.git_sha
    env_hash = sha256(local.env_file_content)
  }

  connection {
    type        = "ssh"
    user        = local.server_user
    private_key = var.ssh_private_key
    host        = local.server_ip
  }

  provisioner "remote-exec" {
    inline = [
      # ── 1. Bootstrap (idempotent — safe to run on every deploy) ────────────
      # Install Docker via official script if not present
      "command -v docker &>/dev/null || (apt-get update -qq && apt-get install -y -qq ca-certificates curl && install -m 0755 -d /etc/apt/keyrings && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc && chmod a+r /etc/apt/keyrings/docker.asc && echo \"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable\" > /etc/apt/sources.list.d/docker.list && apt-get update -qq && apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin && systemctl enable --now docker)",
      # Clone the repo if it doesn't exist yet
      "[ -d ${local.app_dir}/.git ] || git clone 'https://x-access-token:${var.github_token}@github.com/Plengo/hungu.git' ${local.app_dir}",

      # ── 2. Deploy ──────────────────────────────────────────────────────────
      # Write .env via base64 (handles special chars safely)
      "echo '${base64encode(local.env_file_content)}' | base64 -d > ${local.app_dir}/.env",
      # Pull latest code via HTTPS with GitHub token
      "git -C ${local.app_dir} remote set-url origin 'https://x-access-token:${var.github_token}@github.com/Plengo/hungu.git'",
      "git -C ${local.app_dir} pull --ff-only",
      # Inject Google Maps API key into the frontend
      "sed -i 's|__GMAPS_API_KEY__|${var.gmaps_api_key}|g' ${local.app_dir}/services/web/index.html",
      # Inject Worker API key into the frontend (admin panel auth)
      "sed -i 's|__WORKER_API_KEY__|${var.worker_api_key}|g' ${local.app_dir}/services/web/index.html",
      # Rebuild and restart all containers
      "cd ${local.app_dir} && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --remove-orphans",

      # ── 3. Sync host nginx config (only if nginx is already set up) ────────
      # nginx is installed once via `make ssl` after DNS cutover. After that,
      # any change to nginx.host.conf in the repo is auto-applied on every deploy.
      "if command -v nginx &>/dev/null && [ -f /etc/nginx/sites-available/hungu.co.za ]; then cp ${local.app_dir}/services/web/nginx.host.conf /etc/nginx/sites-available/hungu.co.za && nginx -t && systemctl reload nginx; fi",
    ]
  }
}
