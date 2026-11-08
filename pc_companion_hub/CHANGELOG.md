# Changelog

## 0.7.0
- **PIN-Anmeldung:** Neue Option `pin` (z. B. 6 Ziffern). Das Handy meldet sich einmal mit der PIN an und bekommt ein langes Gerätetoken, das im Add-on-Datenordner nur als Hash liegt. `ui_token` bleibt gültig (Notzugang, ältere Geräte), ist aber nicht mehr Pflicht, wenn eine PIN gesetzt ist.
- **Sperre:** Nach 5 Fehlversuchen sperrt der Hub die Anmeldung dieser Adresse 15 Minuten, bei sehr vielen Fehlversuchen insgesamt 1 Stunde für alle.
- **QR-Kopplung:** Tab „Steuerung“ → „Geräte & Anmeldung“ → „Gerät per QR koppeln“. Der Code gilt 5 Minuten und nur einmal; das Handy ist danach ohne Eingabe angemeldet.
- **Geräteverwaltung:** Liste der gekoppelten Geräte mit „Entfernen“ (sofort wirksam, auch für offene Verbindungen) und „Abmelden“.
- **Home-Assistant-Ingress:** Das Add-on erscheint in der HA-Seitenleiste („PC-Companion“) und der Knopf „Benutzeroberfläche öffnen“ nutzt den HA-Login, ohne PIN. Der direkte Zugang über Port 8099 (PWA, Tailscale) bleibt bestehen.
- Neue Abhängigkeit `segno` (QR-Code).

## 0.6.0
- Neuer Knopf „Agent neu starten“ im Tab „Steuerung“: startet nur den PC-Companion-Agenten neu, nicht den PC. Benötigt Agent mit Aktion `restart_agent` und die Aufgabe „PC-Companion Restart“ (`install_autostart.ps1` erneut ausführen).

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
