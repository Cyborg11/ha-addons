# Changelog

## 0.2.0
- Aktionen in der PWA: Sperren, Ruhezustand, Herunterfahren, Neustart (mit Bestätigung), Lautstärke, Stumm, Medientasten, Link am PC öffnen. Hub leitet an `POST /api/action/{name}` des Agenten weiter. Benötigt Agent mit Phase-4-Stand.

## 0.1.0
- Erste Version: PWA-Dashboard (Ringe, 60-s-Verlauf, Querformat, Wake Lock), Online-/Offline-/Startet-Erkennung, Wake-on-LAN, WebSocket-Relay mit Agent-Token im Hub, API-Versionsprüfung.
