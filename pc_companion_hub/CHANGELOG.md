# Changelog

## 0.5.0
- Job-Karte im Dashboard: Fortschritt, ETA, Titel, Vorschaubild und Status (läuft/fertig/Fehler) laufender KI-Jobs von SIG/MediaAI. Benötigt Agent mit Phase-6-Stand.
- Neuer Tab „KI-Tools“: Kacheln zu eigenen Tools, z. B. dem Master-Dashboard aus ai-core (neue Option `tools`: Liste aus `name` und `url`).

## 0.4.0
- Dashboard neu gestaltet: Glas-Panels, Ringe mit Farbwarnung (grün/gelb/rot), Verlaufsgrafiken pro Karte (GPU, CPU, RAM, Netzwerk, 2 min), Kernauslastung, Leistungs- und Laufwerksbalken, Uptime in der Kopfzeile.
- Navigation per Tab-Leiste (Dashboard / Steuerung / Dateien), Vollbild-Knopf, verbessertes Querformat für den Dauerbetrieb am Handy, größere Bedienelemente mit Symbolen.

## 0.3.0
- Dateitransfer: Bereich „Datei senden“ (Zielwahl, Mehrfachauswahl, Fortschritt); der Hub streamt den Upload direkt an den Agenten.
- Android-„Teilen“-Ziel (`share_target`): Dateien aus dem Teilen-Menü landen im Zielordner (nur als installierte PWA über HTTPS). Benötigt Agent mit Phase-5-Stand.

## 0.2.2
- Button „Benutzeroberfläche öffnen“ auf der Add-on-Übersicht (`webui`, Port 8099).

## 0.2.1
- Fix: Bei falschem oder fehlendem Token blieb die PWA bei „Hub getrennt“ hängen. Jetzt erscheint die Token-Eingabe mit Hinweis; Tippen auf die Status-Anzeige öffnet sie jederzeit.

## 0.2.0
- Aktionen in der PWA: Sperren, Ruhezustand, Herunterfahren, Neustart (mit Bestätigung), Lautstärke, Stumm, Medientasten, Link am PC öffnen. Hub leitet an `POST /api/action/{name}` des Agenten weiter. Benötigt Agent mit Phase-4-Stand.

## 0.1.0
- Erste Version: PWA-Dashboard (Ringe, 60-s-Verlauf, Querformat, Wake Lock), Online-/Offline-/Startet-Erkennung, Wake-on-LAN, WebSocket-Relay mit Agent-Token im Hub, API-Versionsprüfung.
