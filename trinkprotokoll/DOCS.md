# Trinkprotokoll

Trinkprotokoll fürs Baby mit Statistik, Wachstumskurven und Benutzerverwaltung. Jede Person meldet sich mit eigenem Namen und Passwort an, alle sehen dieselben Einträge.

## Einrichten

1. Auf dem Reiter **Konfiguration** unter `admin_password` ein eigenes Passwort setzen (mindestens 8 Zeichen) und speichern.
2. Das Add-on starten.
3. Mit **Web-Oberfläche öffnen** oder unter `http://<Adresse-von-Home-Assistant>:3000` aufrufen und mit dem Admin-Namen und dem Passwort anmelden.
4. In der App oben auf **Konto** tippen und weitere Personen anlegen.

Das Admin-Passwort gilt nur für den allerersten Start. Danach verwaltest du Benutzer und Passwörter in der App unter **Konto**.

## Optionen

| Option | Bedeutung |
|---|---|
| `admin_user` | Name des ersten Admins. Standard: `admin`. |
| `admin_password` | Passwort des ersten Admins. Ist keines angegeben, erzeugt das Add-on eines und schreibt es einmalig ins Protokoll. |
| `benutzer_zuruecksetzen` | Notfall bei vergessenem Admin-Passwort: Beim nächsten Start werden alle Benutzer gelöscht und der Admin aus der Konfiguration neu angelegt. Die Einträge bleiben. Danach wieder ausschalten. |
| `im_dashboard_einbetten` | Erlaubt, die App in einer Karte vom Typ „Webseite“ im Home-Assistant-Dashboard anzuzeigen. Standardmäßig aus. |

## Mehrere Babys und Vergleich

Der Admin legt unter **Konto → Babys** weitere Babys an oder importiert Einträge aus einer Importdatei (`.json`) unter **Konto → Daten importieren**. Bei mehr als einem Baby erscheint oben in der App ein Umschalter, und unter **Statistik** vergleicht eine Grafik die Flaschenmenge pro Lebenstag. Beim ersten Start nach dem Update wird die bestehende Datei automatisch umgestellt und vorher als `umstellung-v1-data.json` im Ordner `backups` gesichert.

## Schlaf und Beikost

Neben Mahlzeiten, Windeln und Messwerten erfasst die App Schlaf (Nickerchen/Nachtschlaf mit Wachzeit, optional mit Timer) und Beikost. Bei Babys ohne aktuelle Einträge zeigt die Statistik die letzten Tage bis zum letzten Eintrag.

## Einträge bearbeiten

Im Verlauf einen Eintrag antippen, Werte ändern (zum Beispiel die Trinkmenge oder die Uhrzeit) und mit „Änderung speichern“ sichern. Direkt danach lässt sich die Änderung mit „Rückgängig“ zurücknehmen. Wer den Eintrag ursprünglich angelegt hat, bleibt erhalten. Betrachter können nichts bearbeiten.

## Umzug von einer anderen Installation

Auf dem alten Server als Admin unter **Konto → Sicherung herunterladen** die Datei holen. Im neuen Add-on unter **Konto → Daten importieren** einlesen. Alle Babys mit ihren Einträgen und Namen werden angelegt, Benutzer und Passwörter werden nicht übertragen. Als Ersteller steht bei diesen Einträgen „Import“.

## Gesundheit

Temperatur (mit Messort) und Medikamente (Name, Menge als Text) lassen sich wie alle anderen Einträge erfassen. Die Statistik zeigt den Temperaturverlauf mit Fieberlinie bei 38,0 °C und den Medikamentengaben. Die App ersetzt keine ärztliche Beratung und gibt keine Dosierungen vor.

## Daten und Sicherung

Alle Daten liegen im Speicher des Add-ons und sind in den normalen Home-Assistant-Backups enthalten. Zusätzlich legt die App selbst täglich eine Kopie an und behält die letzten 30 Tage.

## Von unterwegs

Die App spricht kein HTTPS. Ruf sie von außen nicht über eine Portfreigabe im Router auf, sondern über Tailscale.
