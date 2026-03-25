# ─── Deployment variables ─────────────────────────────────────────────────────

variable "ssh_private_key" {
  description = "Private key for SSH access to server (PEM content)"
  type        = string
  sensitive   = true
}

variable "github_token" {
  description = "GitHub personal access token for pulling private repo via HTTPS"
  type        = string
  sensitive   = true
  default     = ""
}

variable "git_sha" {
  description = "Current git commit SHA — used to trigger deploy on every push"
  type        = string
  default     = ""
}

# ─── API keys ─────────────────────────────────────────────────────────────────

variable "gmaps_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "gemini_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "deepseek_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "groq_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "mistral_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "openrouter_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "cerebras_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "sambanova_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "kimi_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "google_client_id" {
  type      = string
  sensitive = true
  default   = ""
}

# ─── App secrets ──────────────────────────────────────────────────────────────

variable "db_username" {
  type    = string
  default = "hungu"
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "jwt_secret" {
  type      = string
  sensitive = true
}

variable "worker_api_key" {
  type      = string
  sensitive = true
}

variable "admin_secret" {
  type      = string
  sensitive = true
  default   = "hungu-admin-2026"
}
