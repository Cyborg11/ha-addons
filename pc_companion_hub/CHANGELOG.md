# Changelog

## 0.14.0
Überarbeitete Oberfläche nach einem Rundgang als Nutzer.
- **Steuerung in Unterreitern:** „Steuern“ (Energie, Medien, Agent, Energie-Plan, Link), „Werkzeuge“ (Prozesse, Zwischenablage), „Geräte & Protokoll“. Der Reiter merkt sich die Auswahl; „Werkzeuge“ erscheint nur, wenn der Agent Prozesse oder Zwischenablage kann.
- **KI-Tools:** Die freigegebenen Programme des Agenten (z. B. ComfyUI starten/beenden) stehen jetzt hier statt unter „Steuerung“.
- **Offline-Seite:** „Zuletzt online vor …“ (bleibt auch nach einem Neustart des Hubs erhalten), die letzten Werte vor dem Ausfall, ein Hinweis, dass Aufwecken nichts hilft, wenn nur der Agent nicht läuft, und der **Verlauf** ist auch ohne PC ansehbar. Beim Aufwecken zeigt ein Balken den Fortschritt.
- **Galerie:** Vor/Zurück im Vollbild (Pfeile, Tastatur ←/→, Wischen) mit Zähler „3 / 64“, Nachbarbilder werden vorgeladen; Dateinamen unter den Kacheln; bei wenigen Ordnern Schalter statt Auswahlliste.
- **Dashboard:** Laufwerke zeigen frei/gesamt in GB bzw. TB (braucht den neuen Agenten; ältere zeigen nur Prozent), Diagramme haben Achsenwerte, die Leuchtränder der Ringe sind nicht mehr abgeschnitten, das Raster hat keine Lücke mehr.
- **Top 5:** Drehende Ladeanzeige während der Messung.
- **Dateien:** Ablagefläche (Ziehen und Ablegen bzw. Antippen) und die Liste „Zuletzt gesendet“ (nur in diesem Browser gemerkt, 20 Einträge).

## 0.13.2
- **Sicherheit:** Das Ausprobieren des `ui_token` direkt an der API (ohne den Anmeldedialog) war unbegrenzt möglich; nur die PIN-Anmeldung hatte eine Sperre. Jetzt sperren 20 falsche Token je Adresse für 15 Minuten (HTTP 429; in der Sperre zählt auch ein richtiges Token nicht), insgesamt 300 pro Stunde. Gilt auch für die Live-Verbindung. Anfragen ganz ohne Token zählen nicht.
- Antworten tragen jetzt `X-Content-Type-Options: nosniff` und `Referrer-Policy: no-referrer`.
- Warnung im Protokoll, wenn der `ui_token` kürzer als 16 Zeichen ist.

## 0.13.1
- **Sicherheit:** Das Anmelde-Token stand bei jeder Live-Verbindung im Klartext im Add-on-Protokoll (`/ws?token=...` im Zugriffsprotokoll von uvicorn). Es wird jetzt durch `***` ersetzt. Wer Protokolle geteilt hat oder dem Protokoll nicht traut: Geräte unter „Geräte“ neu koppeln bzw. die PIN ändern.

## 0.13.0
- **Top 5 Programme** (Dashboard, aufklappbar): nach GPU, CPU, RAM, Festplatte und Netzwerk. Gleichnamige Prozesse (z. B. Browser) sind zusammengefasst. Braucht den neuen Agenten (`top5` in `features`); auch für Nur-Ansicht-Geräte.
- **Netzwerk:** Den Datenverkehr je Programm liefert Windows nur mit Administratorrechten, der Agent läuft bewusst ohne. Die Liste zeigt deshalb die Programme mit den meisten aktiven Verbindungen ins Netz und darunter den Gesamtdurchsatz der Netzwerkkarte. GPU, CPU, RAM und Festplatte sind je Programm gemessen.

## 0.12.0
Neue Bereiche für die Zusatzfunktionen des Agenten (Phase 8). Sie erscheinen nur, wenn der Agent sie meldet (`features` in `/health`); mit einem älteren Agenten bleibt alles wie bisher.
- **Energie-Plan** (Steuerung): „In 30 Min. / 1 / 2 / 4 Std.“ oder „Nach dem letzten KI-Job“ herunterfahren bzw. in den Ruhezustand, mit Anzeige und Abbrechen.
- **Programme** (Steuerung): in der `config.yaml` des Agenten freigegebene Programme starten und beenden.
- **Prozesse** (Steuerung): Liste nach CPU, RAM oder VRAM, einzelne Prozesse beenden.
- **Zwischenablage** (Steuerung): Text an den PC senden, optional die Zwischenablage des PCs holen. Der Text kommt nie ins Protokoll.
- **Screenshot** und **Bildschirm aus** (Steuerung).
- **Galerie** (neuer Tab): neueste Bilder aus den Ausgabeordnern des Agenten, Vollbild-Ansicht, Speichern aufs Handy. Auch für Nur-Ansicht-Geräte.
- **Job-Karte:** „Abbrechen“ für laufende KI-Jobs; im Tab KI-Tools der **Job-Verlauf**.
- Alle neuen Aufrufe laufen über den Hub (Agent-Token bleibt dort), respektieren die Rechte je Gerät und erscheinen im Protokoll.
## 0.11.0
- **Benachrichtigungen aufs Handy** über die Home-Assistant-App: KI-Job fertig oder fehlgeschlagen, PC online/offline (nach 20 s stabil; nach Herunterfahren über den Hub keine Offline-Meldung), GPU länger als 1 Minute über der Grenztemperatur. Einrichtung: Option `notify_service` (z. B. `notify.mobile_app_pixel_8`), dazu `notify_jobs`, `notify_pc_state`, `notify_temp_c` (0 = aus). Im Tab „Steuerung“ gibt es „Testbenachrichtigung senden“. Das Add-on bekommt dafür Zugriff auf die Home-Assistant-API (`homeassistant_api`).

## 0.10.0
- **Langzeitverlauf:** Neue Karte „Verlauf“ im Dashboard mit GPU-Last, GPU-Temperatur, GPU-Leistung, VRAM, CPU und RAM über 1 Std., 6 Std., 24 Std. oder 7 Tage, mit Mittel-, Höchst- und Tiefstwert. Der Hub speichert dafür alle 30 s je PC einen Messwert (Temperatur und Leistung als Spitzenwert) in `/data/history.db`, 14 Tage lang. Der Verlauf beginnt mit dem Update; Zeiten, in denen der PC aus war, erscheinen als Lücke.

## 0.9.0
- **Rechte je Gerät:** „Vollzugriff“ oder „Nur ansehen“ (z. B. für ein Wanddisplay oder Familienmitglieder). Nur-Ansicht-Geräte sehen Dashboard und KI-Tools, aber keine Steuerung, keinen Dateitransfer und kein Aufwecken; der Hub lehnt solche Aufrufe auch direkt ab (403). Die Rolle wählst du beim QR-Koppeln oder änderst sie in der Geräteliste. PIN-Anmeldungen und bestehende Geräte behalten Vollzugriff.
- **Protokoll:** Tab „Steuerung“ → „Protokoll“ zeigt die letzten Aktionen mit Zeit, Gerät, PC und Ergebnis (Aktionen, Aufwecken, Dateitransfer, Kopplungen, Rollenwechsel, fehlgeschlagene Anmeldungen). Gespeichert in `/data/audit.log`, begrenzt auf die letzten ca. 1000 Einträge; PINs und Codes werden nie protokolliert.

## 0.8.0
- **Mehrere PCs:** Neue Option `pcs` (Liste mit `name`, `host`, `port`, `token`, `mac`). Oben erscheint eine PC-Auswahl mit Statuspunkten und die Ansicht „Alle“ mit einer Karte je PC (Auslastung, Temperaturen, laufender Job, „Aufwecken“). Aktionen, Dateitransfer und Aufwecken gelten für den gewählten PC; die Auswahl wird gemerkt.
- Die bisherigen Optionen `agent_host`, `agent_port`, `agent_token` und `pc_mac` funktionieren unverändert (ein PC). Ist `pcs` gesetzt, haben diese keine Wirkung mehr.
- Die Agenten brauchen keine Änderung. Jeder PC braucht seinen eigenen Agenten mit eigenem Token.

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
