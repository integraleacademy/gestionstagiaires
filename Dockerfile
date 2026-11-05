FROM caddy:2.10.2-alpine
# Render runs the process without the file capability from the upstream image.
# A fresh copy works on the unprivileged port provided in PORT.
RUN cp /usr/bin/caddy /tmp/caddy && mv /tmp/caddy /usr/bin/caddy
COPY Caddyfile /etc/caddy/Caddyfile
COPY index.html /srv/waiting/index.html
