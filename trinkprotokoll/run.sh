#!/command/with-contenv bashio

export PORT=3000
export HOST=0.0.0.0
export DATA_DIR=/data

ADMIN_USER="$(bashio::config 'admin_user')"
ADMIN_PASSWORD="$(bashio::config 'admin_password')"
[ "${ADMIN_USER}" = "null" ] && ADMIN_USER="admin"
[ "${ADMIN_PASSWORD}" = "null" ] && ADMIN_PASSWORD=""
export TRINK_ADMIN_USER="${ADMIN_USER}"
export TRINK_ADMIN_PASSWORD="${ADMIN_PASSWORD}"

if bashio::config.true 'im_dashboard_einbetten'; then
  export TRINK_ALLOW_EMBED=1
  bashio::log.info "Einbetten in Dashboards ist erlaubt."
fi

mkdir -p "${DATA_DIR}"

if bashio::config.true 'benutzer_zuruecksetzen'; then
  rm -f "${DATA_DIR}/users.json"
  bashio::log.warning "Alle Benutzer wurden gelöscht. Der Admin wird mit den Angaben aus der Konfiguration neu angelegt. Stelle 'benutzer_zuruecksetzen' danach wieder aus."
fi

bashio::log.info "Starte Trinkprotokoll auf Port 3000."
cd /app
exec node server.js
