FROM nginx:alpine
COPY index.html /usr/share/nginx/html/index.html
COPY hungu.png /usr/share/nginx/html/hungu.png
COPY manifest.json /usr/share/nginx/html/manifest.json
# Ensure the app is served at / with proper MIME types for PWA
RUN echo 'types { application/manifest+json webmanifest; }' > /etc/nginx/conf.d/manifest.conf