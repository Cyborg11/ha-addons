# Changelog

## 0.38.1
- Galerie: Spielfilter auch für die Screenshots auf dem Steam-Profil (Spieleliste von der Profilseite, je Spiel die neuesten bis 300). Braucht die neue Agent-Version.

## 0.38.0
- Bildbetrachter: **Zoomen** (Zwei-Finger-Pinch, Doppeltippen, Mausrad, Knöpfe +/−, Verschieben per Ziehen) und **Vollbild** (Knopf ⛶ oder Taste F; Leisten ausgeblendet, Tippen blendet sie wieder ein). Blättern per Wischen nur bei 1×. Gilt für Galerie und Screenshot.

## 0.37.1
- Fix: Ohne eingerichteten `notify_service` brach die Gesundheitsprüfung (und jede Meldung mit Knöpfen) mit „_no_send() takes from 2 to 3 positional arguments“ ab. Der Platzhalter für „nicht eingerichtet“ nimmt jetzt auch die Aktions-Knöpfe an.

## 0.37.0
- **HTTPS per Tailscale direkt im Hub-Add-on** (optional): mit `tailscale_authkey` startet der Hub einen eigenen Tailscale-Knoten im Userspace-Modus (kein Eingriff in das Netzwerk des Hosts) und stellt sich unter `https://pc-companion.<tailnet>.ts.net` mit echtem Zertifikat bereit. Damit lässt sich die PWA ohne Chrome-Schalter und ohne Adressleiste installieren. `public_url` wird daraus automatisch vorbelegt, wenn nicht gesetzt. Ohne Schlüssel ändert sich nichts.

## 0.36.0
- Neuer Reiter **Claude**: Übersicht der Claude-Code-Sitzungen am PC (Name, Projekt, Zweig, arbeitet/wartet), was sie gerade tun (letztes Werkzeug, Anfang der letzten Antwort), ihre Aufgabenliste und die Unter-Agenten (laufend/fertig). Aktualisiert sich alle 5 Sekunden; nur Vollzugriff, nur Anzeige. Braucht die neue Agent-Version (Feature `claude_code`).

## 0.35.0
- Galerie: **Wolke** unten links auf Steam-Screenshots, die schon auf dem öffentlichen Steam-Profil liegen, und ein neuer Ordner **steam-profile** mit allen öffentlichen Profil-Screenshots (nur ansehen). Der Agent gleicht im Hintergrund per Bild-Fingerabdruck ab; Voraussetzung: neue Agent-Version, Screenshots öffentlich.

## 0.34.0
- Galerie: **Spielfilter** für die Steam-Screenshots (Auswahl „Alle Spiele“ oder ein Spiel, mit Anzahl), Spielname auf den Vorschaubildern.
- Großansicht zeigt Spielname, Datum und Größe über dem Bild (Tippen auf ein Vorschaubild öffnet sie wie bisher; Wischen blättert). Braucht am Agenten die neue Version.

## 0.33.0
- Fernbedienung: optional **Bildschirm als Hintergrund** des Touchpads (alle 2 Sekunden ein Screenshot, nur während einer offenen Sitzung und nur mit Screenshot-Funktion am Agenten). Die Live-Bilder werden nicht einzeln protokolliert; das Öffnen der Sitzung steht im Protokoll.

## 0.32.1
- Gesundheitsmeldungen: beim ersten Check nach dem Start des Hubs werden schon bestehende Hinweise (z. B. „Neustart ausstehend“) nicht mehr gemeldet, nur Dringendes. Vorher kam dieselbe Meldung nach jedem Neustart des Add-ons.
- DOCS: Abschnitt „Fernbedienung“ und die neuen Bereiche (Dateien am PC, Gesundheit, Anzeige) in der Voraussetzungs-Tabelle.

## 0.32.0
Phase 10.10 (Teil 2): **Fernbedienung light** – Maus und Tastatur des PCs vom Handy.
- Tab „Steuerung“: Panel **Fernbedienung** mit Touchpad (ziehen = Maus, tippen = Klick), Klick-/Scroll-/Pfeil-/Enter-Knöpfen und Texteingabe.
- **Mehrfach abgesichert:** am PC standardmäßig aus (Agent: `remote_input.enabled: true`), im Add-on nur mit gesetzter **`confirm_pin`**, Sitzung nur mit PIN, höchstens 15 Minuten (Standard 5, endet von selbst), nur Vollzugriff, Öffnen und Beenden stehen im Protokoll. Keine Alt-/Windows-Tasten, Text höchstens 200 Zeichen, höchstens 60 Eingaben pro Sekunde.
- Benötigt den Agenten mit Feature `remote_input`.

## 0.31.0
Phase 10.10 (Teil 1): Anzeigeprofile.
- Tab „Steuerung“: Panel **Anzeige** mit Erweitern, Duplizieren, Nur PC-Bildschirm, Nur Zweitbildschirm (`DisplaySwitch.exe`, wie Win+P). Die beiden „Nur …“-Modi fragen nach, weil ein Bildschirm dunkel wird.
- In Szenen als Aktion **Anzeigeprofil** wählbar (z. B. „Zocken“: Nur Zweitbildschirm).
- Benötigt den Agenten mit Feature `display` (nur Windows).

## 0.30.0
Phase 10.7: Überwachung.
- Meldung **KI-Job hängt vielleicht**: Fortschritt steht länger als `notify_hang_min` Minuten (Standard 20) still und die GPU ist untätig; mit Knopf „Job abbrechen“. Arbeitet die GPU noch, bleibt es still.
- **Gesundheit** (Agent mit `health`): Laufwerk fast voll, SMART-Zustand, Neustart ausstehend, LibreHardwareMonitor nicht erreichbar – als Meldung (einmal je Auffälligkeit, nach einem Tag erneut) und in der neuen Dashboard-Karte.
- **Statistik** in derselben Karte: Spielzeit pro Woche (8 Wochen, mit meistgespieltem Spiel), Dauer der letzten KI-Jobs mit Trend je Werkzeug und Auslastung pro Tag (14 Tage). Aus den vorhandenen Strom- und Verlaufsdaten.

## 0.29.0
Phase 10.9: Dateibrowser (nur lesen).
- Im Tab „Dateien“ erscheint **Dateien am PC**, sobald der Agent Ordner freigibt (`browse.folders` in dessen `config.yaml`). Ordner durchsuchen, Bilder/PDF/Text ansehen, alles andere und größere Dateien (bis 100 MB) herunterladen.
- Nur mit Vollzugriff (Nur-Ansicht-Geräte sehen es nicht); jeder Download steht im Protokoll. Löschen, Umbenennen und Hochladen gibt es hier bewusst nicht (Hochladen: „Datei senden“).
- Benötigt den Agenten mit Feature `browse`.

## 0.28.0
Phase 10.8: Steam-Reste.
- **Update laden und danach starten:** im Spielblatt eines Spiels mit verfügbarem Update. Der Hub stößt das Update an, fragt alle 10 Sekunden den Stand ab und startet das Spiel einmal, sobald Steam fertig ist (jederzeit abbrechbar; das Update läuft dann weiter). Scheitert es (Steam beginnt nicht, anderes Spiel läuft, über 6 Stunden), steht der Grund in der Meldung.
- **Zufallsspiel:** Knopf über der Spieleliste öffnet ein zufälliges installiertes Spiel, bevorzugt eines mit unter 2 Stunden Spielzeit; gestartet wird erst nach dem Tippen auf „Starten“.
- Agent (separat): Steam-Screenshots erscheinen automatisch als Galerie-Ordner `steam-screenshots`.

## 0.27.0
Phase 10.6: Strom und Kosten.
- Neue Karte **Strom & Kosten** auf dem Dashboard: kWh (und Euro) für heute, die letzten 7 Tage und den Monat, ein Balkenverlauf der letzten 14 Tage und die Verbräuche der letzten **KI-Jobs** und **Spielsitzungen**.
- Der Hub summiert die Leistung von GPU (NVML) und CPU (LibreHardwareMonitor, mit `lhm.enabled` am Agenten) über die Zeit. **Das ist eine Untergrenze:** Mainboard, Lüfter, Netzteil-Verluste, Laufwerke und Peripherie werden nicht gemessen. Ohne CPU-Leistung steht „nur GPU“ dabei. Lücken (PC aus, Hub neu gestartet) werden nicht hochgerechnet.
- Neue Optionen: `strompreis_ct_kwh` (ein fester Preis je kWh, z. B. 32; ohne Preis keine Euro-Werte) und `energy_sensors` (Standard an).
- **Home-Assistant-Sensoren** (nur im Add-on): `sensor.pc_companion_<pc>_kwh_heute` und `sensor.pc_companion_<pc>_kosten_heute` werden jede Minute aktualisiert (Energie-Dashboard-tauglich). Sie sind nicht dauerhaft: Nach einem Neustart von Home Assistant erscheinen sie wieder, sobald der Hub schreibt.
- Daten liegen in `/data/energy.db` (Tage 400, Jobs/Spiele 90 Tage).

## 0.26.0
Phase 10.5: Zeitpläne.
- Unter **Steuerung → Automatik** (vorher „Szenen“) legst du Zeitpläne an: Wochentage und Uhrzeit, dazu eine Aktion – **PC aufwecken**, **Szene ausführen** oder **PC ausschalten, wenn nichts läuft** (Energiesparmodus, Ruhezustand oder Herunterfahren).
- Die Ausführung macht der Hub, auch wenn der PC aus ist. „Wenn nichts läuft“ bedeutet: kein KI-Job, kein Spiel, keine Szene, GPU unter 15 % und CPU unter 40 % für die eingestellte Ruhezeit; läuft innerhalb des Zeitfensters etwas, wird nicht ausgeschaltet und das steht im Protokoll.
- „Nächsten Lauf überspringen“ (für „heute nicht“), An/Aus je Zeitplan, Anzeige des nächsten Laufs. **Verpasste Läufe werden nicht nachgeholt**, auch nicht nach einem Neustart des Hubs; derselbe Zeitplan läuft nie zweimal am Tag.
- Zeitzone aus der neuen Option `timezone` (z. B. `Europe/Berlin`), sonst aus der Umgebung des Add-ons bzw. des Rechners.
- Mit gesetzter `confirm_pin` brauchen Zeitpläne, die den PC ausschalten, die PIN beim Anlegen und Ändern.

## 0.25.0
Phase 10.4: Sicherheits-PIN und App-Verknüpfungen.
- **Sicherheits-PIN** (neue Add-on-Option `confirm_pin`): Kritische Aktionen verlangen eine PIN – Herunterfahren, Neustart, Ruhezustand, Energiesparmodus, Prozess beenden, Programm beenden, Spiel beenden und Szenen mit solchen Schritten (auch Energie-Plan-Schritte). Die PWA fragt sie ab (maskierte Eingabe), der Hub prüft sie. Die PIN wird nie gespeichert und nur 60 Sekunden im Speicher gehalten. Nach 5 falschen Eingaben 5 Minuten Sperre; falsche PINs stehen im Protokoll. Schützt vor versehentlichem Tippen und vor einem entsperrten, fremd benutzten Handy. Ohne die Option ändert sich nichts.
- **App-Verknüpfungen:** Langes Drücken auf das App-Symbol (Android/Chrome) bietet „PC aufwecken“, „Energiesparmodus“ und „Spiele“. Sie nutzen die Deep-Links aus 0.24.0, also mit Rückfrage und – falls gesetzt – PIN.

## 0.24.0
Phase 10.3: Benachrichtigungen mit Aktionen.
- Die Home-Assistant-Meldungen bekommen **Knöpfe** (Android zeigt sie unter der Meldung; Tippen auf die Meldung öffnet die PWA): *KI-Job fertig* → „Energiesparmodus“ und „Galerie“, *GPU sehr heiß* → „Job abbrechen“ (wenn ein Job läuft) und „Dashboard“, *PC ist offline* → „Aufwecken“, *PC ist online* → „Dashboard“.
- Die Knöpfe sind Deep-Links in die PWA (`<public_url>/#do=…`). Die PWA fragt **vor jeder Aktion einmal nach** („Energiesparmodus jetzt starten?“) und führt sie nur mit Vollzugriff aus; Nur-Ansicht-Geräte können nur Reiter öffnen. Keine Home-Assistant-Automationen nötig.
- Voraussetzung: Die Add-on-Option `public_url` ist gesetzt (sie wird schon für die Kopplungslinks genutzt). Ohne sie bleiben die Meldungen reiner Text wie bisher.

## 0.23.0
Phase 10.2: Szenen.
- **Szenen** führen mehrere Schritte nacheinander aus, z. B. „Zocken“: ComfyUI beenden → Spiel starten → Home-Assistant-Szene → Lautstärke setzen. Schritt-Typen: Programm starten/beenden, Spiel starten/beenden, PC-Aktion (Sperren, Energiesparmodus, Bildschirm aus, Lautstärke …), Energie-Plan, Home-Assistant-Szene, Warten, Nachricht senden.
- **Bearbeiten in der Oberfläche:** Steuerung → Szenen mit Editor (Schritte per Auswahl hinzufügen, verschieben, löschen). Gespeichert im Hub.
- **Schnellstart** als Knöpfe auf dem Dashboard; während der Ausführung zeigt eine Karte jeden Schritt („Schritt 2 von 4“) mit Abbrechen. Ein Fehler stoppt die Szene und zeigt, welcher Schritt scheiterte.
- Ist der PC aus, weckt die Szene ihn zuerst (abschaltbar je Szene) und wartet wie bei „Aufwecken und starten“, bis Agent und Steam bereit sind.
- Nur mit Vollzugriff; jede Ausführung und jede Änderung steht im Protokoll. Die Schritte nutzen feste Bausteine, keine freien Befehle.

## 0.22.1
- Der Knopf heißt jetzt „Update laden (prüft Dateien)“. Steam bietet keinen Befehl, der nur das Update lädt (am echten PC mit `steam://validate` und `steam://install` ausprobiert: nur `validate` startet etwas); es prüft zuerst alle Dateien. Bei Spielen ab 20 GB steht dazu ein Hinweis, dass das einige Minuten dauern kann.
- Wer das Prüfen vermeiden will: in Steam unter Eigenschaften → Updates „Dieses Spiel immer aktuell halten“ wählen.

## 0.22.0
Phase 10.1: GPU-Konflikt-Wächter (braucht den Agenten mit Feature `guard`).
- Vor dem **Start eines Spiels** und vor dem **Start eines Programms** (z. B. ComfyUI) prüft die Oberfläche, ob die GPU belegt ist: laufender KI-Job, laufendes Spiel, ein laufendes Programm, hohe GPU-Last oder viel belegter VRAM. Bei einem Konflikt erscheint ein Dialog mit dem Grund (z. B. „ComfyUI – 13,4 GB VRAM, 97 % Last“).
- Je Konflikt gibt es „Beenden“ bzw. „Job abbrechen“ (danach wird neu geprüft und der Start läuft weiter, wenn nichts mehr im Weg ist) und immer **„Trotzdem starten“** und „Abbrechen“. Der Wächter verhindert nichts.
- Ohne Konflikt keine zusätzliche Rückfrage. Schwellen, Abschalten und das Merkmal `gpu: true` für GPU-lastige Programme stehen in der `config.yaml` des Agenten (`guard:`).

## 0.21.0
Updates anstoßen (braucht den Agenten mit Phase „Update laden“, Feature `steam_update`).
- **Update laden:** In der Detailansicht eines Spiels mit „Update“-Schild startet der Knopf „Update laden“ die Dateiprüfung und das Update in Steam, ohne das Spiel zu starten. Am echten PC getestet: ein Update von rund 300 MB war nach etwa 30 Sekunden fertig, ohne Dialog.
- **Downloads am PC öffnen:** Knopf unter „Downloads & Speicher“ öffnet am PC die Downloads-Seite von Steam.
- Während Steam ein Spiel prüft oder aktualisiert, steht es jetzt als „Lädt“ da (der Agent liest dafür das Steam-Flag in der Registry).

## 0.20.1
- **Fix:** Ein getauschtes Cover (Bilder ändern, zurücksetzen) erscheint sofort in der Spiele-Liste und im Detailblatt. Bisher hielt der Browser das alte Bild bis zu 24 Stunden fest, weil die Bildadresse keine Version trug.

## 0.20.0
Steam-Fernsteuerung, Teil 5: Nicht-Steam-Spiele (braucht den Agenten mit Phase 9.5).
- Eigene Verknüpfungen aus Steam („Nicht-Steam-Spiel hinzufügen“) erscheinen im Tab „Spiele“ (Schild „Eigenes“) und lassen sich starten und, sofern sie ein eigenes Programm sind, beenden. Shells und Skript-Interpreter lassen sich bewusst nicht gezielt beenden.
- Für sie gibt es keine SteamGridDB-Vorschläge (die Oberfläche sagt das); eigene Bilder im `grid`-Ordner werden angezeigt.

## 0.19.0
Steam-Fernsteuerung, Teil 2: Bilder ändern (braucht den Agenten mit Phase 9.2; Vorschläge nur mit `steam.griddb_key` in der `config.yaml` des Agenten).
- **Bilder ändern** in der Detailansicht eines Spiels: Reiter Cover, Header, Hero und Logo, Vorschläge von SteamGridDB als Raster (mit „Mehr laden“), Antippen zeigt eine Vorschau, „Übernehmen“ speichert das Bild beim Spiel auf dem PC. „Auf Standard zurücksetzen“ entfernt das eigene Bild (geht auch ohne Schlüssel).
- Der Hub lädt nie Bilder von außen: Vorschauen und das gewählte Bild holt der Agent (nur von steamgriddb.com) und der Hub reicht sie durch; Vorschauen bleiben im Browser eine Stunde gecacht.
- Hinweis, dass Steam neue eigene Bilder meist erst nach einem Neustart des Clients zeigt, mit Knopf „Steam jetzt beenden“ (mit Rückfrage).
- **Animierte Cover** (APNG, animiertes WebP) werden unverändert übernommen, die Vorschau zeigt das erste Bild. Abschaltbar mit `steam.allow_animated: false` in der `config.yaml` des Agenten.
- **NSFW-Bilder** lassen sich mit dem Schalter „Auch NSFW-Bilder anzeigen“ zusätzlich einblenden (Standard: aus, wird pro Gerät gemerkt); sie tragen ein rotes Schild „NSFW“.
- Ohne Schlüssel zeigt die Oberfläche statt der Vorschläge eine Anleitung zum Eintragen. Alle Änderungen stehen im Protokoll („Cover geändert“, „Cover zurückgesetzt“).

## 0.18.0
Steam-Fernsteuerung, Teil 3: „Aufwecken und starten“ (braucht für den Energiesparmodus den Agenten mit Phase 9.3).
- **Aufwecken und starten:** Ist der PC aus, zeigt die Offline-Seite die zuletzt gespielten Spiele. Antippen weckt den PC und startet das Spiel, sobald der Agent und Steam bereit sind. Die Warte-Seite zeigt „Startet danach: …“ mit Abbrechen, danach kommt eine Meldung über Erfolg oder den Grund des Scheiterns; alles steht im Protokoll.
- **Zwei Varianten, einstellbar:** Option `wake_mode` (je PC überschreibbar): `standby` = Energiesparmodus (schnell, Standard) oder `cold` = Kaltstart nach Herunterfahren mit Autologin (längere Wartezeiten). Feinjustierung mit `wake_timeout_s` und `launch_delay_s`. Beschreibung beider Varianten in der Doku.
- **Neuer Knopf „Energiesparmodus“** (Steuerung) und Energie-Plan-Modus „Energiesparmodus“, wenn der Agent ihn kann (Feature `standby`).
- Die Warte-Seite passt Wartezeit und Hinweis an den Modus an.

## 0.17.0
Steam-Fernsteuerung, Teil 4 (braucht den Agenten mit Phase 9.4).
- **Downloads & Speicher** (einklappbar im Tab „Spiele“): laufende, geladene und angehaltene Updates mit Fortschrittsbalken und Größe, die Zahl der Spiele, die auf ein Update warten, und je Steam-Bibliothek frei/gesamt und die Größe der Steam-Spiele darauf. Aktualisiert sich alle 10 s, solange der Bereich offen ist. Steam schreibt den Fortschritt nur gelegentlich auf die Platte, die Anzeige ist grob.
- Detailansicht eines Spiels etwas kompakter (Knöpfe „Beenden“ und „Schließen“ stehen auf dem Handy nebeneinander).

## 0.16.0
Steam-Fernsteuerung, Teil 1 (braucht den Agenten mit Phase 9.1; ältere Agenten zeigen den Tab nicht).
- **Neuer Tab „Spiele“:** installierte Steam-Spiele als Kachelraster mit Cover (Cover bleiben im Browser zwischengespeichert), Suche, Sortierung nach „Zuletzt gespielt“, Name oder Größe, Hinweis-Schilder „Update“ und „Lädt 42 %“.
- **Läuft gerade:** Karte mit Spielname und Laufzeit (live), Knopf „Beenden“ mit Rückfrage.
- **Detailansicht:** Antippen zeigt Cover, Spielzeit, zuletzt gespielt, Größe und Status; „Starten“ und „Beenden“. Läuft schon ein anderes Spiel, fragt die Oberfläche vor dem Start nach.
- Nur-Ansicht-Geräte sehen Raster und Details, aber keine Knöpfe. Starten und Beenden stehen im Protokoll (mit Spielname).
- Hub-Relays unter `/api/steam/...`; Steam-Bilder dürfen 24 Stunden gecacht werden (ETag).

## 0.15.0
Mehr Messwerte aus LibreHardwareMonitor (braucht den neuen Agenten und `lhm.enabled: true`).
- **CPU:** Leistungsaufnahme in W.
- **GPU:** Lüfterdrehzahl (U/min) und Speichertemperatur.
- **RAM:** Temperatur der Module.
- **Laufwerke:** Temperatur je Festplatte/SSD. Felder, die die Hardware nicht meldet, bleiben ausgeblendet.

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
