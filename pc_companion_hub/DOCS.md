# PC-Companion Hub

Zeigt die Live-Werte deines Gaming-PCs (vom [PC-Companion-Agenten](https://github.com/Cyborg11/PCCompanion)) als Dashboard an und weckt den PC per Wake-on-LAN, wenn er aus ist.

## Optionen

| Option | Bedeutung |
|---|---|
| `pcs` | **Liste der PCs** (empfohlen, auch für nur einen PC). Je Eintrag: `name` (z. B. „Gaming-PC“), `host` (IP oder Name, feste IP im Router empfohlen), `port` (Standard `8765`), `token` (aus der `config.yaml` des Agenten), `mac` (MAC-Adresse für Wake-on-LAN, `ipconfig /all`), optional `broadcast_ip` |
| `agent_host`, `agent_port`, `agent_token`, `pc_mac` | Alte Einstellung für **einen** PC. Gilt nur, solange `pcs` leer ist. |
| `broadcast_ip` | Broadcast-Adresse des Heimnetzes, z. B. `192.168.178.255` (Standard `255.255.255.255`) |
| `pin` | Kurze PIN für die Anmeldung am Handy, z. B. 6–8 Ziffern. Empfohlen. Nach 5 Fehlversuchen wird die Anmeldung gesperrt. |
| `ui_token` | Langes Token als Notzugang (Anmeldefeld „Stattdessen Token eingeben“, ältere Geräte). Mindestens eines von `pin` und `ui_token` muss gesetzt sein, sonst lehnt der Hub alles ab. |
| `public_url` | Optional: Adresse, unter der das Handy den Hub erreicht, z. B. `https://pi.<tailnet>.ts.net`. Wird für die QR-Kopplung vorgeschlagen, wenn du die Oberfläche über Home Assistant öffnest. |

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

Zustände: **online** (Live-Daten), **offline** (Knopf „PC aufwecken“), **startet** (Countdown bis 120 s).
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
