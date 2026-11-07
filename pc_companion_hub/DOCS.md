# PC-Companion Hub

Zeigt die Live-Werte deines Gaming-PCs (vom [PC-Companion-Agenten](https://github.com/Cyborg11/PCCompanion)) als Dashboard an und weckt den PC per Wake-on-LAN, wenn er aus ist.

## Optionen

| Option | Bedeutung |
|---|---|
| `agent_host` | IP oder Name des PCs (feste IP im Router empfohlen) |
| `agent_port` | Port des Agenten (Standard `8765`) |
| `agent_token` | Token aus der `config.yaml` des Agenten |
| `pc_mac` | MAC-Adresse des PCs für Wake-on-LAN (`ipconfig /all`) |
| `broadcast_ip` | Broadcast-Adresse des Heimnetzes, z. B. `192.168.178.255` (Standard `255.255.255.255`) |
| `ui_token` | Frei gewähltes, langes Token für die Weboberfläche. **Pflicht** – ohne Token lehnt der Hub alles ab. |
| `public_url` | Optional: Tailscale-Adresse, z. B. `https://pi.<tailnet>.ts.net` (nur informativ) |

## Benutzung

Die Oberfläche liegt auf Port **8099**: `http://<pi-ip>:8099/`. Beim ersten Öffnen das `ui_token` eingeben. Das Add-on läuft mit `host_network`, damit das Wake-on-LAN-Paket ins LAN gelangt; der Port lässt sich daher nicht umlegen.

Zustände: **online** (Live-Daten), **offline** (Knopf „PC aufwecken“), **startet** (Countdown bis 120 s).
Das Sonnen-Symbol hält den Bildschirm an (Wake Lock) – für ein altes Handy als Dauer-Display im Querformat.

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
