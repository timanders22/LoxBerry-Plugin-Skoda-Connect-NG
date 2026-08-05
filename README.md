# LoxBerry-Plugin: Skoda Connect

Bindet **Skoda-Fahrzeuge** über das MySkoda-Konto an Loxone an: Ladezustand,
Tankfüllstand, Reichweite, Kilometerstand, Verriegelung, Türen und Fenster,
Klimatisierung, Standort, Warnleuchten sowie Inspektions- und
Ölservice-Fristen. Auf Wunsch lassen sich Klimatisierung, Ladevorgang,
Ladegrenze und Scheibenheizung schalten.

> **Fassung 0.9.0 — ungeprüft.** Das Plugin wurde ohne Skoda-Konto und ohne
> Fahrzeug gebaut. Aufbau, Oberfläche, Endpunkt, Absicherung und Sprachdateien
> sind geprüft; ob die Anmeldung an der Skoda-Cloud gelingt, ob ein Fahrzeug
> alle abgefragten Endpunkte beantwortet und ob die schreibenden Befehle die
> erwartete Wirkung haben, ist es **nicht**. Deshalb 0.9.0 und nicht 1.0.0,
> und deshalb sind schreibende Befehle ab Werk gesperrt. Die
> Selbstaktualisierung zeigt auf dieses Repository; bei gleicher Fassung wird
> niemandem ein Update angeboten.

## Nachfolger eines eingestellten Plugins

Das frühere Plugin [SkodaConnect von M.
Schlenstedt](https://github.com/mschlenstedt/LoxBerry-Plugin-SkodaConnect) steht
auf Fassung 0.2.0 und ist im LoxBerry-Wiki als **EOL** gekennzeichnet. Skoda hat
die Schnittstelle umgestellt; die zugrunde liegende Bibliothek
[`skodaconnect`](https://github.com/skodaconnect/skodaconnect) trägt im eigenen
Repository den Vermerk *DEPRECATED*, ebenso die HomeAssistant-Einbindung
darauf.

Dieses Plugin ist **kein Update**, sondern ein Neubau auf der freien
Nachfolgebibliothek [`myskoda`](https://github.com/skodaconnect/myskoda) —
genau die Umstellung, die in
[Issue #5](https://github.com/mschlenstedt/LoxBerry-Plugin-SkodaConnect/issues/5)
des alten Repositories gefordert war. Aus dem alten Plugin wurde **kein Code
übernommen**: er ist in Perl geschrieben und spricht eine Schnittstelle an, die
es nicht mehr gibt.

Der als Zwischenlösung empfohlene Umweg über eine HomeAssistant-Integration
plus MQTT-Gateway entfällt damit.

## Voraussetzung, die stolpern lässt: Python 3.13

`myskoda` verlangt ab Fassung 2.0.0 **Python 3.13 oder neuer**
(`requires-python = ">=3.13.0"`).

| Debian | Python | Ergebnis |
|---|---|---|
| 12 (Bookworm) | 3.11 | **läuft nicht** |
| 13 (Trixie) | 3.13 | läuft |

Auch die letzte ältere `myskoda`-Fassung (1.2.3 vom Mai 2025) hilft auf
Debian 12 nicht — sie verlangt 3.12. `postinstall.sh` bricht deshalb mit einer
benannten Meldung ab, statt stillschweigend ein totes Plugin zu hinterlassen.

**Vor dem Ausprobieren klären:** `python3 -V` auf dem LoxBerry.

## Aufbau

    bin/skoda.py              Abrufdienst (Python, eigene venv)
    bin/dienst.sh             Start, Stopp, Wächter
    cron/cron.01min           minütlicher Wächter
    webfrontend/htmlauth/     Bedienoberfläche (fünf Reiter)
    webfrontend/html/         Endpunkt für den Miniserver + gemeinsame Bibliothek

Drei Aufgaben, drei Dateien: Die Oberfläche bedient, der Dienst ruft ab, der
Endpunkt bedient den Miniserver. Weder Oberfläche noch Endpunkt sprechen je
selbst mit der Skoda-Cloud — sie lesen den Zwischenspeicher und legen Befehle
in einer Warteschlange ab, die der Dienst im Sekundentakt abarbeitet.

## Weitere Voraussetzungen

* **Internetverbindung bei der Installation.** `myskoda` wird von PyPI geholt
  (festgenagelt auf 2.16.1; schlägt das fehl, wird die neueste genommen und das
  ausdrücklich gemeldet).
* **`python3-venv`.** Systemweites `pip3 install` scheitert auf Debian 12/13 an
  PEP 668 (`externally-managed-environment`); deshalb eine eigene venv unter
  `bin/plugins/skodaconnect/venv`.
* MQTT-Gateway eingeschaltet, wenn die Werte per MQTT kommen sollen. Es ist seit
  LoxBerry 3 Bestandteil des Systems und wird unter *System → MQTT Gateway*
  aktiviert, nicht nachinstalliert.

## Zugangsdaten

Es sind die Zugangsdaten des **MySkoda-Kontos** — dieselben wie in der
MySkoda-App, nicht die eines Händlerportals. Sie liegen in
`config/plugins/skodaconnect/zugang.json` mit den Rechten 0600, nicht in der
Konfiguration, die die Oberfläche anzeigt, und nie in der Loxone-Projektdatei.

Auf Wunsch merkt sich der Dienst nach der ersten Anmeldung einen
Sitzungsschlüssel (ebenfalls 0600) und meldet sich damit an, statt jedes Mal
das Passwort zu senden. Das schont die Anmeldeschnittstelle, die wiederholte
Anmeldungen drosselt.

Ein S-PIN-Feld gibt es, es wird aber **nicht gebraucht**: Ver- und Entriegeln
bietet dieses Plugin bewusst nicht an.

## Endpunkte für Loxone

Alle Aufrufe brauchen das Token aus dem Reiter *Einbindung in Loxone*.
Statt der laufenden Nummer darf überall auch die Fahrgestellnummer stehen
(`fahrzeug=TMB…`).

| Aufruf | Zweck |
|---|---|
| `?token=T&aktion=status&fahrzeug=N` | `SKODA;OK=..;SOC=..;TANK=..;REICHW=..;KM=..;VERR=..;TUEREN=..;FENSTER=..;KOFFER=..;HAUBE=..;LICHT=..;KLIMA=..;ZIELTEMP=..;AUSSEN=..;WARN=..;ERREICH=..;BEWEG=..;ZUEND=..;ALTER=..` |
| `?token=T&aktion=laden&fahrzeug=N` | `LADEN;OK=..;SOC=..;LAEDT=..;LADEKW=..;TEMPO=..;RESTMIN=..;LADEGR=..;KABEL=..;REICHWBAT=..;ALTER=..` |
| `?token=T&aktion=wartung&fahrzeug=N` | `WARTUNG;OK=..;INSPTAGE=..;INSPKM=..;OELTAGE=..;OELKM=..;KM=..;WARN=..;ALTER=..` |
| `?token=T&aktion=position&fahrzeug=N` | `POSITION;OK=..;BREITE=..;LAENGE=..;ALTER=..` plus Anschrift in einer zweiten Zeile |
| `?token=T&aktion=fahrzeuge` | Liste der erkannten Fahrzeuge |
| `?token=T&aktion=roh` | vollständiges Abbild als JSON |
| `?token=T&aktion=klima_start&temp=21` | Klimatisierung starten |
| `?token=T&aktion=klima_stop` | Klimatisierung anhalten |
| `?token=T&aktion=zieltemperatur&temp=21` | Zieltemperatur setzen |
| `?token=T&aktion=laden_start` / `laden_stop` | Ladevorgang starten/anhalten |
| `?token=T&aktion=ladegrenze&prozent=80` | Ladegrenze setzen (50–100) |
| `?token=T&aktion=scheibe_ein` / `scheibe_aus` | Scheibenheizung |
| `?token=T&aktion=lueftung_start` / `lueftung_stop` | Standlüftung |
| `?token=T&aktion=wecken` | Weckruf (Skoda erlaubt höchstens dreimal am Tag) |
| `?token=T&aktion=abruf` | sofort abrufen statt auf den Takt zu warten |

**Ein Strich als Wert** heißt: dieser Wert liegt nicht vor. Es wird bewusst
keine 0 gesendet — eine 0 wäre eine stille Falschaussage. Loxone behält dann
den letzten gültigen Wert; deshalb gehören `ALTER` und `OK` immer mit
ausgewertet.

Schaltende Aufrufe antworten mit `SET;OK=…`: `1` angenommen, `0` abgelehnt (mit
Grund), `2` eingereiht, aber innerhalb der Wartezeit ohne Antwort — also
Ergebnis unbekannt.

**Was `OK=1` nicht heißt.** Der Dienst läuft ohne die Ereignisleitung der
Bibliothek (die verlangt eine Firebase-Anmeldung) und wartet deshalb nicht auf
die Bestätigung des Fahrzeugs. `OK=1` bedeutet: die Skoda-Cloud hat den Auftrag
angenommen. Ob das Fahrzeug ihn ausgeführt hat, zeigt erst der nächste Abruf.
Wer sicher sein will, wertet den zurückgelesenen Zustand aus und nicht die
Antwort auf den Befehl.

## Was das Plugin nicht kann

* **Ver- und Entriegeln.** Bewusst nicht eingebaut. Es verlangt die S-PIN und
  lässt sich ohne Fahrzeug nicht verantwortungsvoll erproben.
* **Reifendruck.** Die Bibliothek liefert ihn nicht — es gibt nur die
  Warnleuchten-Kategorie `TIRE`, keinen Zahlenwert. Ein erfundener Wert wäre
  schlimmer als keiner.
* **Hupe und Lichthupe.** Aus demselben Grund weggelassen wie das Verriegeln.

## Datenschutz

Es sind keine persönlichen Daten im Plugin enthalten. Zugangsdaten und alle
Einstellungen liegen ausschließlich in der lokalen Konfiguration. Verbindungen
gibt es nur zur Skoda-Cloud und, bei der Installation, zu PyPI.

## Lizenz

MIT — siehe [LICENSE](LICENSE). Die Cloud-Anbindung nutzt
[myskoda](https://github.com/skodaconnect/myskoda) (ebenfalls MIT). Das ist
keine amtliche Skoda-Schnittstelle: Skoda kann sie ohne Ankündigung ändern,
womit dieses Plugin unbrauchbar würde. Das Projekt ist weder mit Škoda Auto
verbunden noch von dort unterstützt.
