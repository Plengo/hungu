#!/bin/bash
# setup-ssl.sh — Run ONCE on the server AFTER DNS A record points here.
#
# What this does:
#   1. Installs nginx on the host (manages ports 80/443 for ALL sites on this IP)
#   2. Gets a Let's Encrypt cert for hungu.co.za via certbot
#   3. Deploys the reverse-proxy config from the repo
#   4. Reloads nginx — hungu.co.za is now live on HTTPS
#
# To add a second site later, just drop a new config into
# /etc/nginx/sites-available/ and symlink it — no changes needed here.
#
# Usage (from your laptop):  make ssl
# Usage (on server directly): bash /opt/hungu/scripts/setup-ssl.sh

set -euo pipefail

DOMAIN="hungu.co.za"
EMAIL="admin@hungu.co.za"
APP_DIR="/opt/hungu"

echo "==> Installing host nginx and certbot..."
apt-get update -qq
apt-get install -y -qq nginx certbot

# Disable the default nginx site
rm -f /etc/nginx/sites-enabled/default

# Create ACME challenge webroot
mkdir -p /var/www/certbot

# Write a minimal HTTP-only config so certbot can complete the ACME challenge
cat > /etc/nginx/sites-available/hungu.co.za <<EOF
server {
    listen 80;
    server_name ${DOMAIN} www.${DOMAIN};
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://\$host\$request_uri; }
}
EOF

ln -sf /etc/nginx/sites-available/hungu.co.za /etc/nginx/sites-enabled/hungu.co.za
nginx -t && systemctl reload nginx

echo "==> Obtaining SSL certificate for ${DOMAIN}..."
certbot certonly \
  --webroot -w /var/www/certbot \
  -d "${DOMAIN}" -d "www.${DOMAIN}" \
  --non-interactive --agree-tos -m "${EMAIL}"

# Deploy the full reverse-proxy config (SSL + proxy to localhost:3000)
echo "==> Deploying reverse-proxy config..."
cp "${APP_DIR}/services/web/nginx.host.conf" /etc/nginx/sites-available/hungu.co.za
nginx -t && systemctl reload nginx

# Auto-renew: certbot timer (systemd) or cron fallback
if systemctl list-timers certbot.timer &>/dev/null; then
  systemctl enable --now certbot.timer
else
  (crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet && nginx -s reload") \
    | sort -u | crontab -
fi

echo ""
echo "✓ Done! https://${DOMAIN} is live."
echo ""
echo "To add a second site later:"
echo "  1. Create /etc/nginx/sites-available/<newsite>.conf"
echo "  2. ln -s /etc/nginx/sites-available/<newsite>.conf /etc/nginx/sites-enabled/"
echo "  3. certbot certonly --webroot -w /var/www/certbot -d <newsite>"
echo "  4. nginx -t && systemctl reload nginx"
