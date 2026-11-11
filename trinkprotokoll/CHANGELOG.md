# Changelog

Format: neueste Version oben. Bei jeder neuen Version `version` in `config.yaml` erhöhen und hier einen Abschnitt ergänzen. Home Assistant zeigt diese Datei auf der Add-on-Seite im Reiter „Änderungsprotokoll“.

## Unveröffentlicht

- (hier neue Änderungen sammeln)

## 1.4.0

- Neu: Einträge im Verlauf lassen sich bearbeiten. Eintrag antippen, Werte ändern (zum Beispiel die Trinkmenge oder die Uhrzeit), „Änderung speichern“. Es gibt „Rückgängig“ im Hinweis nach dem Speichern. Der ursprüngliche Ersteller des Eintrags bleibt erhalten. Betrachter können nichts bearbeiten.
- Neu: Konto → „Sicherung herunterladen“ (nur Admin) lädt alle Einträge aller Babys als Datei herunter.
- Neu: Konto → „Daten importieren“ liest auch eine solche komplette Sicherung ein, auch mit mehreren Babys. Vorhandene Einträge werden nicht doppelt angelegt. Damit lassen sich Daten auf einen anderen Server oder in dieses Add-on aus dem Repository übernehmen.
- Das Add-on liegt jetzt im Repository `ha-addons` und wird darüber installiert und aktualisiert.
- Entfernt: Die Option `startdaten_uebernehmen` und die mitgelieferten Startdaten. Ein neuer Start ist immer leer.

## 1.3.0

- Neu: Temperatur erfassen (34 bis 43 °C, Messort rektal/Ohr/Stirn/Achsel). Ab 38,0 °C erscheint ein Fieberhinweis, bei Babys unter 3 Monaten mit der Aufforderung, umgehend ärztlich abklären zu lassen.
- Neu: Medikamente erfassen (Name, Menge als Freitext, Notiz). Schnellauswahl der bisherigen Medikamente und Hinweis, wann das Medikament zuletzt gegeben wurde. Die App gibt keine Dosierungsempfehlungen.
- Neu: Karte „Gesundheit“ in der Statistik mit Temperaturverlauf, Fieberlinie bei 38,0 °C, Markierungen für Medikamentengaben und einer Liste der Medikamente im Zeitraum.
- Neu: Verlauf, CSV-Export und Import kennen die neuen Eintragsarten (CSV-Spalten „Temperatur (°C)“ und „Medikament“).
- Import: Temperaturmessungen lassen sich aus Importdateien einlesen. Bereits importierte Daten werden beim erneuten Einlesen nicht doppelt angelegt.

## 1.2.0

- Neu: Schlaf erfassen (Nickerchen/Nachtschlaf, Wachzeit, Anzahl Wachphasen) mit Timer.
- Neu: Beikost erfassen (Gramm optional).
- Neu: Karte „Schlaf pro Tag“, Schlaf-Kennzahlen, Schlafbalken im Tagesrhythmus, Schlaf-Spalte in Tabelle und CSV.
- Neu: Archivansicht für Babys ohne aktuelle Einträge (Statistik und Verlauf bis zum letzten Eintrag).
- Behoben: Altersanzeige rechnet in Kalendermonaten (zum ersten Geburtstag stand „11 Monate“).
- Behoben: Beschriftung der Lebenstage im Vergleichsdiagramm überlappte bei langen Zeiträumen.
- Import: Importdateien können jetzt auch Schlaf und Beikost enthalten.

## 1.1.0

- Neu: Mehrere Babys mit Umschalter, Verwaltung unter Konto → Babys.
- Neu: Vergleich der Flaschenmengen pro Lebenstag.
- Neu: Daten importieren (JSON), auch als neues Baby; doppelte Einträge werden erkannt.
- Neu: Option `im_dashboard_einbetten` für die Einbettung ins Home-Assistant-Dashboard.
- Die Datendatei wird beim ersten Start automatisch umgestellt, vorher entsteht eine Kopie in `backups`.

## 1.0.0

- Erste Version als Home-Assistant-Add-on: Mahlzeiten (Stillen, Flasche), Windeln, Gewicht, Länge, Kopfumfang, Spucken, Vitamin D.
- Statistiken und Grafiken, Verlauf, CSV-Export.
- Benutzerverwaltung mit Rollen (Admin, Mitglied, Betrachter).
- Zugriff von unterwegs über das Tailscale-Add-on.
