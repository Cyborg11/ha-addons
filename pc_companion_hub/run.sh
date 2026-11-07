#!/usr/bin/with-contenv bashio
# Optionen werden vom Hub selbst aus /data/options.json gelesen.
bashio::log.info "Starte PC-Companion Hub auf Port 8099"
cd /app
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8099
