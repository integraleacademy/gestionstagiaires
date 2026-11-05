FROM caddy:2.10.2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY index.html /srv/waiting/index.html
