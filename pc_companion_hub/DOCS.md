# PC-Companion Hub

Zeigt die Live-Werte deines Gaming-PCs (vom [PC-Companion-Agenten](https://github.com/Cyborg11/PCCompanion)) als Dashboard an und weckt den PC per Wake-on-LAN, wenn er aus ist.

## Optionen

| Option | Bedeutung |
|---|---|
| `pcs` | **Liste der PCs** (empfohlen, auch für nur einen PC). Je Eintrag: `name` (z. B. „Gaming-PC“), `host` (IP oder Name, feste IP im Router empfohlen), `port` (Standard `8765`), `token` (aus der `config.yaml` des Agenten), `mac` (MAC-Adresse für Wake-on-LAN, `ipconfig /all`), optional `broadcast_ip` |
| `agent_host`, `agent_port`, `agent_token`, `pc_mac` | Alte Einstellung für **einen** PC. Gilt nur, solange `pcs` leer ist. |
| `broadcast_ip` | Broadcast-Adresse des Heimnetzes, z. B. `192.168.178.255` (Standard `255.255.255.255`) |
| `wake_mode` | Wie der PC ausgeschaltet wird: `standby` (Energiesparmodus, Standard) oder `cold` (heruntergefahren, Kaltstart mit Autologin). Bestimmt Wartezeiten und Hinweise beim Aufwecken, siehe „Aufwecken und starten“. Je PC in `pcs` überschreibbar. |
| `wake_timeout_s`, `launch_delay_s` | Optional: wie lange (Sekunden, 30–900) der Hub auf den Agenten wartet, und wie lange (0–180) er nach „online“ wartet, bevor er ein vorgemerktes Spiel startet. Standard je nach `wake_mode`. Je PC überschreibbar. |
| `pin` | Kurze PIN für die Anmeldung am Handy, z. B. 6–8 Ziffern. Empfohlen. Nach 5 Fehlversuchen wird die Anmeldung gesperrt. |
| `ui_token` | Langes Token als Notzugang (Anmeldefeld „Stattdessen Token eingeben“, ältere Geräte). Mindestens eines von `pin` und `ui_token` muss gesetzt sein, sonst lehnt der Hub alles ab. |
| `public_url` | Optional: Adresse, unter der das Handy den Hub erreicht, z. B. `https://pi.<tailnet>.ts.net`. Wird für die QR-Kopplung vorgeschlagen, wenn du die Oberfläche über Home Assistant öffnest. |

## Zusatzfunktionen des Agenten

Mit einem Agenten ab Phase 8 (PCCompanion, `GET /health` meldet `features`) erscheinen im Dashboard zusätzliche Bereiche. Die Einrichtung dazu steht in der `config.yaml` des Agenten (Beispiele in `config.example.yaml`):

| Bereich | Voraussetzung am Agenten |
|---|---|
| Energie-Plan, Prozesse, Zwischenablage senden, Bildschirm aus | keine |
| Programme | `programs:` mit den erlaubten Programmen |
| Galerie | `gallery.folders:` mit Ausgabeordnern; Vorschaubilder brauchen `Pillow` |
| Spiele (Steam) | wird automatisch erkannt (Steam installiert); Einstellungen unter `steam:` in der `config.yaml` des Agenten. Für „Bilder ändern“ (Cover, Header, Hero, Logo) dort `steam.griddb_key` eintragen: kostenloser API-Schlüssel von steamgriddb.com (Profil → Preferences → API). Ohne Schlüssel lässt sich ein eigenes Bild nur zurücksetzen. Eigene Verknüpfungen („Nicht-Steam-Spiele“) werden ebenfalls angezeigt (`steam.shortcuts: false` schaltet sie ab). |
| Screenshot | `Pillow` |
| Dateien am PC (Tab „Dateien“) | `browse.folders:` mit den freigegebenen Ordnern; nur ansehen und herunterladen (bis 100 MB), versteckte Dateien und Verknüpfungen nach außen bleiben unsichtbar; nur mit Vollzugriff, Downloads im Protokoll |
| Gesundheit & Statistik | keine (Agent mit Feature `health`); `lhm.enabled` für die Prüfung von LibreHardwareMonitor |
| Anzeige (Erweitern/Duplizieren/Nur …) | keine (Windows) |
| Fernbedienung light | `remote_input.enabled: true` am Agenten **und** `confirm_pin` im Add-on, siehe „Fernbedienung“ |
| Zwischenablage vom PC holen | `clipboard.allow_read: true` |
| Job-Abbruch | die Tools (SIG, MediaAI) über `ai-core` mit `aicore.pcc` |

Nur-Ansicht-Geräte sehen davon nur die Galerie, die Spiele-Bibliothek, den Job-Verlauf und den Energie-Plan (lesend); alles andere verlangt Vollzugriff.

## Benachrichtigungen

Der Hub kann dir über die Home-Assistant-Companion-App Nachrichten schicken. Einrichtung:

1. In Home Assistant den Namen deines Handy-Dienstes ermitteln: Entwicklerwerkzeuge → Aktionen → „notify.mobile_app_“ eingeben, z. B. `notify.mobile_app_pixel_8`.
2. Im Add-on `notify_service` auf diesen Namen setzen und speichern.
3. Im Tab „Steuerung“ → „Benachrichtigungen“ auf „Testbenachrichtigung senden“ tippen.

Gemeldet wird: **KI-Job fertig/fehlgeschlagen** (`notify_jobs`), **PC online/offline** (`notify_pc_state`; der Zustand muss 20 s stabil sein, nach einem Herunterfahren oder Ruhezustand über den Hub gibt es keine Offline-Meldung) und **GPU zu heiß** (`notify_temp_c`, Standard 85 °C, 0 schaltet ab; nach 60 s über der Grenze, höchstens alle 30 Minuten). Beim Start des Hubs werden bestehende Zustände und alte Jobs nicht gemeldet.

Überwachung (Phase 10.7): **KI-Job hängt vielleicht** (`notify_hang_min`, Standard 20, 0 schaltet ab): der Job meldet „läuft“, sein Fortschritt steht so lange still und die GPU bleibt unter 5 % Last; arbeitet die GPU noch, wird nicht gemeldet. **Gesundheit** (Agent mit Feature `health`): alle 5 Minuten werden Laufwerke (fast voll, SMART), ausstehender Neustart und LibreHardwareMonitor geprüft; neue Auffälligkeiten kommen als Meldung (dieselbe frühestens nach einem Tag erneut). Beides steht auch in der Karte **Gesundheit & Statistik** auf dem Dashboard, dort mit Spielzeit pro Woche, Job-Dauer im Trend und Auslastung pro Tag (nur Läufe ab etwa 0,2 Wh Strom; Auslastung aus dem 14-Tage-Verlauf).

## Verlauf

Die Karte „Verlauf“ unten im Dashboard zeigt Kennzahlen über Stunden bis 7 Tage. Der Hub sammelt sie selbst (alle 30 s je PC, 14 Tage lang, `/data/history.db`); es ist keine Änderung am Agenten nötig. Der Verlauf beginnt, sobald das Add-on 0.10.0 läuft. Er überlebt Neustarts und Updates des Add-ons, wird aber mit dem Add-on gelöscht, wenn du es deinstallierst.

## Rechte und Protokoll

Jedes gekoppelte Gerät hat eine Rolle: **Vollzugriff** oder **Nur ansehen**. Letzteres eignet sich für ein Wanddisplay oder für Familie: Es zeigt Dashboard und KI-Tools, aber keine Steuerung, keinen Dateitransfer und kein Aufwecken. Die Rolle legst du beim QR-Koppeln fest („Rechte des neuen Geräts“) oder änderst sie in der Geräteliste. Die Anmeldung per PIN und `ui_token` sowie der HA-Zugang haben immer Vollzugriff.

Das **Protokoll** („Steuerung“ → „Protokoll“) listet die letzten Aktionen: wer, wann, welcher PC, Ergebnis. Es ist nur mit Vollzugriff sichtbar.

## Mehrere PCs

Jeder PC bekommt einen eigenen Agenten (eigener Token) und einen Eintrag in `pcs`:

```yaml
pcs:
  - name: Gaming-PC
    host: 192.168.1.20
    token: "<Token aus agent/config.yaml>"
    mac: "AA:BB:CC:DD:EE:01"
  - name: KI-PC
    host: 100.64.0.7        # z. B. per Tailscale
    port: 8765
    token: "<anderer Token>"
    mac: "AA:BB:CC:DD:EE:02"
```

Bei mehreren PCs zeigt die Leiste oben je PC einen Knopf mit Statuspunkt, dazu „Alle“: eine Übersicht mit einer Karte je PC (GPU, Temperatur, VRAM, CPU, RAM, laufender Job; ausgeschaltete PCs lassen sich dort aufwecken). Steuerung, Dateien und KI-Tools gelten für den gewählten PC. Die `tools`-Kacheln sind für alle PCs gleich. Den Kopplungs-QR und die Geräteverwaltung gibt es nur einmal, sie gelten für den ganzen Hub.

## Benutzung

Die Oberfläche liegt auf Port **8099**: `http://<pi-ip>:8099/`. Beim ersten Öffnen die `pin` eingeben (oder das `ui_token`). Das Add-on läuft mit `host_network`, damit das Wake-on-LAN-Paket ins LAN gelangt; der Port lässt sich daher nicht umlegen.

Zustände: **online** (Live-Daten), **offline** (Knopf „PC aufwecken“, zuletzt gesehen, letzte Werte, Verlauf), **startet** (Balken und Countdown bis 120 s).
Reiter: **Dashboard**, **KI-Tools** (Web-Oberflächen aus `tools`, Programme des Agenten, Job-Verlauf), **Steuerung** (Unterreiter Steuern · Werkzeuge · Geräte & Protokoll), **Galerie**, **Spiele** (nur wenn der Agent Steam findet) und **Dateien**.
Das Sonnen-Symbol hält den Bildschirm an (Wake Lock) – für ein altes Handy als Dauer-Display im Querformat.

## Anmeldung am Handy

1. **PIN:** Einmal die `pin` eingeben. Das Gerät bleibt danach angemeldet (eigenes Gerätetoken, die PIN wird nicht gespeichert).
2. **QR-Code:** Auf einem schon angemeldeten Gerät (oder in der HA-Oberfläche) Tab „Steuerung“ → „Geräte & Anmeldung“ → „Gerät per QR koppeln“. Mit der Kamera des Handys scannen und den Link öffnen: Das Handy ist ohne Eingabe angemeldet. Der Code gilt 5 Minuten und nur einmal. Im Feld „Adresse des Hubs für das Handy“ muss die Adresse stehen, unter der das Handy den Hub erreicht (`http://<pi-ip>:8099` im Heimnetz oder die Tailscale-Adresse); bei Zugriff über HA setzt `public_url` den Vorschlag.
3. **Home Assistant (Ingress):** In der HA-Seitenleiste „PC-Companion“ oder im Add-on „Benutzeroberfläche öffnen“. Dort meldet HA dich an, PIN und Token entfallen. Fragt die Oberfläche trotzdem nach der PIN, steht im Add-on-Log eine Warnung mit der Quelladresse. Das Teilen-Menü (Android) und die PWA-Installation brauchen weiterhin den direkten Zugang.

Gekoppelte Geräte siehst und entfernst du unter „Geräte & Anmeldung“. Wer die PIN ändert, meldet damit keine Geräte ab; ein einzelnes Gerät entfernst du in der Liste.

## HTTPS / PWA-Installation

Service Worker und „Zur Startseite hinzufügen“ funktionieren in Chrome nur über HTTPS. Empfohlen: Tailscale (`tailscale serve --bg 8099` auf dem Pi, dann `https://<pi>.<tailnet>.ts.net`). Über reines HTTP im LAN funktioniert das Dashboard, aber ohne PWA-Installation.

## Dateitransfer

Im Bereich „Datei senden“ Ziel wählen und Dateien aussuchen; der Fortschritt wird pro Datei angezeigt. Die Zielordner stehen in der `config.yaml` des Agenten unter `upload.targets` (auch NAS-Freigaben, z. B. `//nas/freigabe/Handy`). Der PC muss online sein.

**Teilen-Menü (Android):** Die PWA über HTTPS installieren (Tailscale, siehe oben), dann erscheint „PC-Companion“ im Teilen-Menü von Chrome-Apps/Galerie/Dateien. Die geteilten Dateien werden hochgeladen, sobald die App offen und der PC online ist; ist er aus, warten sie im Browser-Speicher.

## KI-Tools und Job-Status

**Job-Karte:** Meldet ein Programm (SIG, MediaAI) seinen Status per `report_job` an den Agenten, erscheint oben im Dashboard eine Karte mit Fortschritt, Restzeit und Vorschaubild; fertige und fehlgeschlagene Jobs bleiben 2 Minuten sichtbar. Einbindung in die Programme: `docs/sig-integration.md` im PCCompanion-Repo.

**Tab „KI-Tools“:** Kacheln, die in einem neuen Tab öffnen. Einrichtung über die Option `tools`:

```yaml
tools:
  - name: Master Dashboard
    url: "http://<pc-tailscale-ip-oder-name>:7880"
  - name: Smart Image Generator
    url: "http://<pc-tailscale-ip-oder-name>:7871"
```

Das Master-Dashboard aus ai-core lauscht laut `master.json` auf der Tailscale-Adresse des PCs (Port 7880). Öffne die Links über **dieselbe Adresse**, die du in `tools` einträgst: Die Einmalanmeldung (SSO) von ai-core hängt am Cookie dieser Adresse. Das Handy muss im Tailscale-VPN sein. Eine Einbettung in die Seite selbst (iframe) funktioniert wegen der Cookie-Regeln (`SameSite=Strict`) nicht, daher öffnen die Kacheln die Seiten direkt.

## Wake-on-LAN-Checkliste

BIOS „Wake on LAN“ aktivieren · Netzwerkadapter: „Nur Magic Packet“ · Windows-Schnellstart aus · LAN-Kabel · MAC notieren.

## Strom und Kosten

Auf dem Dashboard zeigt die Karte „Strom & Kosten“, wie viel Energie der PC verbraucht hat. Der Hub rechnet die Leistung von GPU und CPU (Letzteres braucht `lhm.enabled` am Agenten) in kWh um und ordnet sie dem Tag, dem laufenden KI-Job und dem laufenden Spiel zu.
Mit `strompreis_ct_kwh` (ein fester Preis, z. B. `32`) kommen Kosten dazu. **Die Werte sind eine Untergrenze**, keine Zählermessung: Mainboard, Lüfter, Netzteil-Verluste und Peripherie fehlen. Für genaue Zahlen taugt eine Steckdose mit Messung in Home Assistant besser; die kWh-Sensoren des Hubs ergänzen sie.
Mit Home-Assistant-Anbindung schreibt der Hub jede Minute `sensor.pc_companion_<pc>_kwh_heute` und `…_kosten_heute` (abschaltbar mit `energy_sensors: false`).

## Zeitpläne

Unter **Steuerung → Automatik** legst du zeitgesteuerte Aktionen an (höchstens 30): Wochentage und Uhrzeit, dann *PC aufwecken*, *Szene ausführen* oder *PC ausschalten, wenn nichts läuft*.
Der Hub führt sie aus, auch bei ausgeschaltetem PC. Die Uhrzeit gilt in der Zeitzone aus der Option `timezone` (z. B. `Europe/Berlin`); ohne Angabe nimmt der Hub die Zeitzone des Add-ons.
Ein Zeitplan löst nur in den ersten Minuten ab seiner Uhrzeit aus: Wer den Hub um 07:30 nicht laufen hatte, bekommt den Lauf **nicht** nachträglich. „Nächsten Lauf überspringen“ gilt genau einmal.
„Ausschalten, wenn nichts läuft“ wartet bis zu *Zeitfenster* Minuten auf eine Ruhezeit (kein KI-Job, Spiel oder Szene, GPU < 15 %, CPU < 40 %) und schaltet dann per Energiesparmodus, Ruhezustand oder Herunterfahren aus.
Jeder Lauf und jede Auslassung steht im Protokoll („Zeitplan: …“).

## Sicherheits-PIN

Mit `confirm_pin` im Add-on verlangen kritische Aktionen eine zusätzliche PIN: Herunterfahren, Neustart, Ruhezustand, Energiesparmodus, Prozess beenden, Programm beenden, Spiel beenden und Szenen mit solchen Schritten.
Die PWA fragt die PIN ab; der Hub prüft sie (der Browser könnte sie nicht umgehen). Die PIN steht nur im Hub und im Gedächtnis der Seite für 60 Sekunden; sie ist unabhängig von `pin` (Anmeldung) und `ui_token`.
Nach 5 falschen Eingaben ist die Aktion 5 Minuten gesperrt. Aufwecken, Starten und Lautstärke brauchen keine PIN.

## Benachrichtigungen mit Aktionen

Ist `public_url` gesetzt (die Adresse, unter der du die PWA am Handy öffnest), tragen die Meldungen Knöpfe. Sie öffnen die PWA mit einem Befehl im Link (`#do=standby`, `wake`, `cancel-job:<id>`, `tab:<name>`, `scene:<id>`) und `&pc=<PC>`.
Die PWA fragt vor jeder Aktion einmal bestätigend nach. Sie meldet dich dafür nicht neu an: Das Handy muss bei der PWA angemeldet sein. Auf iOS zeigt Home Assistant keine URI-Knöpfe; dort öffnet das Tippen auf die Meldung die PWA.

## Fernbedienung

Maus und Tastatur des PCs vom Handy (Tab „Steuerung“, Panel „Fernbedienung“): Touchpad (ziehen bewegt, tippen klickt), Klicks, Scrollen, Pfeile/Enter/Esc/Tab und Texteingabe. Bewusst mehrfach abgesichert: am PC standardmäßig **aus** (`remote_input.enabled: true` in der `config.yaml` des Agenten), im Add-on nur mit gesetzter **`confirm_pin`**; jede Sitzung verlangt die PIN, dauert höchstens 15 Minuten (Standard 5) und endet von selbst. Nur Vollzugriff. Öffnen und Beenden stehen im Protokoll (einzelne Eingaben und der getippte Text nicht). Es gibt keine Alt-/Windows-Tasten, Text höchstens 200 Zeichen. Wichtig: Wer das Handy mit offener Sitzung in der Hand hat, steuert den PC.

## Szenen

Unter **Steuerung → Automatik** legst du Abfolgen an („Zocken“, „Über Nacht rendern“). Jeder Schritt ist ein fester Baustein: Programm/Spiel starten oder beenden, PC-Aktion, Energie-Plan,
Home-Assistant-Szene (`scene.<name>`, braucht die Home-Assistant-Anbindung des Add-ons), Warten (bis 300 s), Nachricht senden. Die Szenen liegen im Hub (`/data/scenes.json`), höchstens 20 mit je 30 Schritten.
Beim Ausführen zeigt eine Karte den Fortschritt; schlägt ein Schritt fehl, stoppt die Szene (die übrigen Schritte werden übersprungen). „PC bei Bedarf aufwecken“ sendet das Magic Packet und wartet auf den Agenten
(Zeiten wie bei „Aufwecken und starten“). Nur Geräte mit Vollzugriff dürfen Szenen sehen und ausführen; Nur-Ansicht-Geräte sehen sie nicht auf dem Dashboard.

## Update laden und danach starten (Steam)

Im Spielblatt eines Spiels mit verfügbarem Update startet „Update laden und danach starten“ das Update (Steam prüft dabei die Dateien) und startet das Spiel selbst, sobald es fertig ist; ein erneutes Tippen bricht den Start ab, das Update läuft weiter. Der Zustand liegt im Hub: ein Neustart des Add-ons vergisst den Auftrag. „Zufallsspiel“ über der Liste öffnet ein zufälliges installiertes Spiel (bevorzugt unter 2 Stunden Spielzeit).

## Aufwecken und starten (Steam)

Ist der PC aus, zeigt die Offline-Seite unter dem Aufwecken-Knopf die zuletzt gespielten Spiele (die Liste merkt sich der Browser, sobald der Tab „Spiele“ einmal geöffnet war). Antippen weckt den PC und merkt das Spiel vor; sobald der Agent antwortet und Steam meldet, wartet der Hub kurz (`launch_delay_s`) und startet es. Auf der Warte-Seite steht „Startet danach: …“ mit Abbrechen, am Ende kommt eine Meldung (und ein Protokolleintrag). Schlägt der Start fehl oder meldet sich der PC nicht rechtzeitig, steht der Grund dort. Das setzt `mac` (Wake-on-LAN) voraus.

Zwei Varianten, über `wake_mode` einstellbar (je PC):

| | `standby` (Energiesparmodus) | `cold` (heruntergefahren) |
|---|---|---|
| Ausschalten | Knopf **Energiesparmodus** in „Steuerung“ (oder Energie-Plan-Modus „Energiesparmodus“, MQTT-Button) | Herunterfahren |
| Danach | Sitzung, Agent und Steam laufen sofort weiter, Wecken dauert wenige Sekunden | Windows bootet, meldet sich an, startet Agent und Steam: 1–3 Minuten |
| Standard-Zeiten | Wartezeit 120 s, Pause vor dem Start 5 s | Wartezeit 300 s, Pause 25 s |
| Voraussetzung am PC | Netzwerkadapter darf den PC aufwecken („Gerät kann den Computer aus dem Ruhezustand aktivieren“ + „Nur Magic Packet“); Einstellungen → Konten → Anmeldeoptionen → „Wann soll Windows eine erneute Anmeldung verlangen?“ = **Nie** | **Automatische Anmeldung**, sonst läuft nach dem Start kein Agent |

*Autologin einrichten:* Sysinternals **Autologon** (Passwort wird als LSA-Secret gespeichert; bei Microsoft-Konto E-Mail und Kontopasswort, nicht die Hello-PIN). Alternativ `netplwiz`; der Haken „Benutzer müssen Benutzernamen und Kennwort eingeben“ erscheint unter Windows 11 erst, wenn „Nur Windows Hello-Anmeldung zulassen“ aus ist. Kein Klartext-Passwort in der Registry. Wer das nicht möchte, kann die Sitzung nach der Anmeldung per Aufgabe sperren (Agent, Steam und Spiele laufen hinter dem Sperrbildschirm weiter).

Wichtig: Der **Ruhezustand** (Knopf „Ruhezustand“, `shutdown /h`) ist etwas anderes als der Energiesparmodus. Wecken per Magic Packet aus dem Ruhezustand (S4) unterstützen nicht alle Mainboards und Netzwerkadapter; probiere es einmal aus. Läuft der PC nach dem Wecken, aber der Agent nicht (z. B. Neustart ohne Anmeldung), kann der Hub nichts starten und meldet das.
