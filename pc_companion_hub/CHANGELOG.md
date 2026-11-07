# Changelog

## 0.2.2
- Button „Benutzeroberfläche öffnen“ auf der Add-on-Übersicht (`webui`, Port 8099).

## 0.2.1
- Fix: Bei falschem oder fehlendem Token blieb die PWA bei „Hub getrennt“ hängen. Jetzt erscheint die Token-Eingabe mit Hinweis; Tippen auf die Status-Anzeige öffnet sie jederzeit.

## 0.2.0
- Aktionen in der PWA: Sperren, Ruhezustand, Herunterfahren, Neustart (mit Bestätigung), Lautstärke, Stumm, Medientasten, Link am PC öffnen. Hub leitet an `POST /api/action/{name}` des Agenten weiter. Benötigt Agent mit Phase-4-Stand.

## 0.1.0
- Erste Version: PWA-Dashboard (Ringe, 60-s-Verlauf, Querformat, Wake Lock), Online-/Offline-/Startet-Erkennung, Wake-on-LAN, WebSocket-Relay mit Agent-Token im Hub, API-Versionsprüfung.
