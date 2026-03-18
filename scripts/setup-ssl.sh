#!/bin/bash
# Run this ONCE on the server AFTER DNS A records point to this server.
# Usage: bash scripts/setup-ssl.sh
set -e

DOMAIN="hungu.co.za"
EMAIL="admin@hungu.co.za"   # change to your real email

echo "==> Installing certbot..."
apt-get update -q && apt-get install -y certbot

echo "==> Creating webroot directory..."
mkdir -p /var/www/certbot

echo "==> Obtaining SSL certificate for $DOMAIN..."
certbot certonly \
  --webroot \
  --webroot-path /var/www/certbot \
  --email "$EMAIL" \
  --agree-tos \
  --no-eff-email \
  -d "$DOMAIN" \
  -d "www.$DOMAIN"

echo "==> Updating nginx config for HTTPS..."
cat > /opt/hungu/services/web/nginx.conf << 'EOF'
server {
    listen 80;
    server_name hungu.co.za www.hungu.co.za;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name hungu.co.za www.hungu.co.za;

    ssl_certificate     /etc/letsencrypt/live/hungu.co.za/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/hungu.co.za/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    root /usr/share/nginx/html;
    index index.html;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location /api/ {
        proxy_pass         http://api:8000/;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
EOF

echo "==> Rebuilding web container with HTTPS config..."
cd /opt/hungu
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build web

echo ""
echo "✅ Done! https://$DOMAIN should be live."
echo ""
echo "To auto-renew certs, add to crontab (crontab -e):"
echo "0 3 * * * certbot renew --quiet && docker compose -f /opt/hungu/docker-compose.yml -f /opt/hungu/docker-compose.prod.yml restart web"
