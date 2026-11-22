#!/usr/bin/with-contenv bashio
# Optionen werden vom Hub selbst aus /data/options.json gelesen.

# Optional: eigener Tailscale-Knoten nur für den Hub (HTTPS mit echtem Zertifikat unter https://<Name>.<tailnet>.ts.net).
# Nur aktiv mit gesetztem tailscale_authkey (oder gespeicherter Anmeldung). Userspace-Modus: kein Eingriff in das Netzwerk des Hosts,
# kein Konflikt mit dem Tailscale-Add-on. Ein Fehler hier verhindert den Start des Hubs nie.
start_tailscale() {
    local key host dir sock
    key="$(bashio::config 'tailscale_authkey')"
    host="$(bashio::config 'tailscale_hostname')"
    [ "$key" = "null" ] && key=""
    { [ -z "$host" ] || [ "$host" = "null" ]; } && host="pc-companion"
    dir=/data/tailscale
    sock=/var/run/tailscale/tailscaled.sock
    if [ -z "$key" ] && [ ! -f "$dir/tailscaled.state" ]; then
        return 0
    fi
    mkdir -p "$dir" /var/run/tailscale
    tailscaled --tun=userspace-networking --state="$dir/tailscaled.state" --socket="$sock" >/tmp/tailscaled.log 2>&1 &
    local i
    for i in $(seq 1 20); do
        [ -S "$sock" ] && break
        sleep 0.5
    done
    if [ ! -S "$sock" ]; then
        bashio::log.warning "Tailscale: tailscaled startet nicht (siehe /tmp/tailscaled.log)"
        return 0
    fi
    if [ -n "$key" ]; then
        tailscale --socket="$sock" up --authkey="$key" --hostname="$host" --accept-dns=false --accept-routes=false 2>&1 \
            | while read -r l; do bashio::log.info "Tailscale: $l"; done
    else
        tailscale --socket="$sock" up --hostname="$host" --accept-dns=false --accept-routes=false >/dev/null 2>&1
    fi
    if ! tailscale --socket="$sock" serve --bg --https=443 http://127.0.0.1:8099 2>&1 | while read -r l; do bashio::log.info "Tailscale: $l"; done; then
        :
    fi
    local dns
    dns="$(tailscale --socket="$sock" status --json 2>/dev/null | python3 -c 'import sys,json;print((json.load(sys.stdin).get("Self") or {}).get("DNSName","").rstrip("."))' 2>/dev/null)"
    if [ -n "$dns" ]; then
        export HUB_TS_URL="https://$dns"
        bashio::log.info "Tailscale: Hub per HTTPS erreichbar unter $HUB_TS_URL"
    else
        bashio::log.warning "Tailscale: keine Adresse erhalten (Schlüssel gültig? HTTPS-Zertifikate im Tailscale-Admin aktiviert?)"
    fi
}
start_tailscale || bashio::log.warning "Tailscale konnte nicht eingerichtet werden"

bashio::log.info "Starte PC-Companion Hub auf Port 8099"
cd /app
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8099
