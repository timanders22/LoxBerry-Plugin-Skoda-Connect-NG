# LoxBerry-Plugin: Skoda Connect

Bindet **Skoda-Fahrzeuge** über das MySkoda-Konto an Loxone an: Ladezustand,
Tankfüllstand, Reichweite, Kilometerstand, Verriegelung, Türen und Fenster,
Klimatisierung, Standort, Warnleuchten sowie Inspektions- und
Ölservice-Fristen. Auf Wunsch lassen sich Klimatisierung, Ladevorgang,
Ladegrenze und Scheibenheizung schalten.

> **Fassung 0.9.4 — ungeprüft.** Das Plugin wurde ohne Skoda-Konto und ohne
> Fahrzeug gebaut. Aufbau, Oberfläche, Endpunkt, Absicherung und Sprachdateien
> sind geprüft; ob die Anmeldung an der Skoda-Cloud gelingt, ob ein Fahrzeug
> alle abgefragten Endpunkte beantwortet und ob die schreibenden Befehle die
> erwartete Wirkung haben, ist es **nicht**. Deshalb 0.9.x und nicht 1.0.0,
> und deshalb sind schreibende Befehle ab Werk gesperrt. Die
> Selbstaktualisierung zeigt auf dieses Repository; bei gleicher Fassung wird
> niemandem ein Update angeboten.

## Was 0.9.4 ändert

Nur eine Richtigstellung, kein Code. In 0.9.3 stand als Begründung für die
mitgezogenen Adressen, `raw.githubusercontent.com` folge einer Umbenennung
nicht. Das ist **falsch** — es folgt ihr; nachgeprüft am alten Repo-Namen.
Der Irrtum stammt aus einem anderen Fall, in dem eine Datei schlicht noch
nicht im Repository lag. Die Adressen bleiben trotzdem auf dem heutigen Namen,
aber aus dem richtigen Grund (siehe unten).

## Was 0.9.3 ändert

**Das Repository heißt jetzt `LoxBerry-Plugin-Skoda-Connect-NG`.** Damit ist
schon am Namen zu sehen, dass dies nicht das alte Plugin ist. `RELEASECFG`,
`PRERELEASECFG`, `ARCHIVEURL` und `INFOURL` sind mitgezogen. GitHub leitet nach
einer Umbenennung zwar weiter — `raw.githubusercontent.com` ebenso,
nachgeprüft —, aber auf ein Weiterleitungsziel sollte sich ein Auto-Update
nicht stützen: Es verschwindet in dem Augenblick, in dem jemand den alten Namen
neu vergibt.

**Der Plugin-Ordner bleibt `skodaconnect`** und damit auch die Adresse, die
Loxone aufruft. Im Miniserver muss nichts angefasst werden.

**Ein Rückfall zeigte in ein fremdes Plugin.** `sk_paths()` fiel auf den festen
Namen `skodaconnect` zurück, sobald `config/plugins/<ordner>` noch fehlte —
etwa im Augenblick der Installation. Genau diesen Ordnernamen trägt aber auch
das eingestellte Vorgängerplugin. Wer es noch installiert hat, bekommt dieses
hier von LoxBerry als `skodaconnect_01`; der Rückfall hätte dann in die
Konfiguration des *fremden* Plugins gezeigt, dort gelesen und geschrieben.
Maßgeblich ist jetzt `LBPPLUGINDIR`, die Auskunft von LoxBerry selbst; der
feste Name greift nur noch, wo der ermittelte nachweislich kein Plugin-Ordner
sein kann (aus dem ausgepackten Archiv heraus heißt er `html`).

**`bin/__pycache__/` ist aus dem Archiv geflogen** und steht jetzt in einer
`.gitignore`. Eine mitgelieferte `.pyc` passt spätestens nach der nächsten
Änderung an `skoda.py` nicht mehr zur Quelle und trägt den Pfad des Rechners
mit sich, auf dem sie entstanden ist.

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
    uninstall/uninstall       Deinstallation (Dienst beenden, Sicherungen löschen)
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

**Löschen** geht seit 0.9.2 über ein eigenes Häkchen im Reiter *Einstellungen*.
Ein leer gelassenes Passwortfeld löscht bewusst **nichts** — sonst stünde
irgendwann ein leeres Passwort in der Datei, ohne dass es jemand merkt. Genau
diese Vorsicht machte den umgekehrten Weg vorher unmöglich. Gelöscht wird
`zugang.json` **und** die Sicherung `config/plugins/skodaconnect.backup.zugang.json`
— sonst hätte `postinstall.sh` das Passwort bei der nächsten Neuinstallation
wieder eingespielt. Beide Dateien werden vor dem Entfernen überschrieben.

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

## Deinstallation

`uninstall/uninstall` erledigt die zwei Dinge, die LoxBerry **nicht** selbst
wegräumt:

* **Die beiden Sicherungsdateien** `config/plugins/<ordner>.backup.skoda.json`
  und `.backup.zugang.json`. Sie liegen absichtlich *neben* dem
  Plugin-Konfigordner, damit Einstellungen und Zugangsdaten ein Update und
  sogar eine Neuinstallation überstehen. Beim Deinstallieren ist genau das
  falsch: in `zugang.json` stehen Benutzername und Passwort des
  MySkoda-Kontos. Wer das Plugin entfernt, erwartet nicht, dass seine
  Zugangsdaten liegen bleiben.
* **Den laufenden Abrufdienst.** Er wurde mit `nohup` gestartet und hängt an
  keinem Elternprozess, den LoxBerry beenden würde — ohne dieses Skript liefe
  er nach der Deinstallation weiter und meldete sich weiter bei Škoda an.

Der Dienst wird dabei über die PID-Datei **und** über einen Vergleich der
Befehlszeile gefunden: `/proc/<pid>/cmdline`, zweites Argument, voller Pfad.
Nicht `pgrep -f` (findet die eigene Suche mit), nicht `ps -C`/`killall` (die
vergleichen den *comm*-Namen, der bei einem Skript mit Shebang `python3`
lautet — beide finden gar nichts) und keine Teilstringsuche (die träfe einen
Editor, in dem `skoda.py` offen ist, oder ein zweites Exemplar des Plugins).
`bin/dienst.sh` prüft seit 0.9.1 auf demselben Weg.

Im MQTT-Broker bleibt nichts stehen: der Dienst sendet mit `publish`, nicht
mit `retain`.

## Was in 0.9.2 nachgemessen und geändert wurde

Acht Beanstandungen aus einer Durchsicht wurden am Code nachgestellt, bevor
etwas geändert wurde. Fünf trafen zu, zwei teilweise, eine nicht.

**Zugangsdaten ließen sich nicht löschen** — trifft zu, siehe oben. Beim
Umsetzen fiel auf, dass ein Löschen von `zugang.json` allein nichts nützt,
solange die Sicherung daneben liegen bleibt.

**Zieltemperatur mit Komma** — **trifft nicht zu.** Beanstandet war, der
Test-Reiter weise `21,5` mit einem strengeren Muster ab als der Endpunkt.
Das Muster in `sk_test.php` erlaubt tatsächlich nur den Punkt — die Zeile
**darüber** ersetzt das Komma aber vorher durch einen Punkt. Nachgemessen mit
der ganzen Funktion:

| Eingabe | `sk_test_aktion('klima_start')` |
|---|---|
| `21,5` | eingereiht |
| `21.5` | eingereiht |
| `21,3` | abgewiesen — richtig, es sind nur halbe Grad erlaubt |

Dieselbe Umwandlung steht an zwei weiteren Stellen: im Endpunkt
(`html/index.php`, vor dem Einreihen) und in `zahl()` in `skoda.py`. Drei
unabhängige Schichten, keine davon lückenhaft.

**`file()` beim Anzeigen des Protokolls** — Befund richtig, vorgeschlagene
Abhilfe falsch. An einem 512 kB großen Protokoll (7521 Zeilen, 400 gewünscht),
in PHP 7.4 und 8.1 gleich:

| Verfahren | Zeit | Speicherspitze |
|---|---|---|
| `file()` + `array_reverse` (bisher) | 0,3 ms | 1503 kB |
| `exec("tail -n 400")` (Vorschlag) | 1,9 ms | 79 kB |
| rückwärts mit `fseek` (jetzt) | **0,1 ms** | 167 kB |

Der Speicherhinweis war berechtigt, `tail` aber der schlechteste der drei
Wege: ein Prozessstart kostet mehr, als das Einlesen je gespart hat. 1,5 MB
Spitze sind bei einem `memory_limit` von 128 MB ohnehin kein Engpass — die
Änderung erfolgte, weil rückwärts lesen in *beidem* besser ist und keine
Shell braucht, die man wieder absichern müsste.

**Kein Zeitlimit in `skoda.py`** — Befund richtig, Begründung falsch.
`aiohttp` hängt **nicht** unbegrenzt; nachgemessen gegen ein Gegenstück, das
die Verbindung annimmt und dann schweigt, lautet die Vorgabe der Bibliothek
`ClientTimeout(total=300, sock_connect=30)`. Fünf Minuten sind hier trotzdem
unbrauchbar: ein Fahrzeug wird über **neun Endpunkte nacheinander** abgefragt
(gemessen: neun stumme Endpunkte mit 1 s Grenze brauchen 9,0 s). Hochgerechnet
sind das 2700 s je Fahrzeug bei einem Takt von 300 s — der Dienst wäre nicht
abgestürzt, sondern einfach weg, und die Befehlswarteschlange, die im selben
Ablauf hängt, nähme in dieser Zeit nichts mehr an. Jetzt: 30 s je Abruf, 60 s
je Schreibbefehl und je Anmeldung, dazu `ClientTimeout(total=90)` auf der
Sitzung als Auffanglinie. Worst case damit 270 s statt 2700 s je Fahrzeug.
Gegenprobe auf Verbindungslecks: 120 abgebrochene Abrufe hinterlassen
**0 belegte Verbindungen**, der Vorrat läuft nicht leer.

**Leere Zahlenfelder** — trifft zu. Ein leeres Feld lief in dieselbe harte
Fehlermeldung wie `abc`. Zurückgefallen wird jetzt aber auf den **bisher
gespeicherten** Wert, nicht auf den Werkswert wie vorgeschlagen: Wer den Takt
auf 600 gestellt hat und das Feld versehentlich leert, bekäme sonst
stillschweigend wieder 300 — eine Änderung, die er nie eingegeben hat. Und es
wird gesagt, statt still getan. Unsinnige Eingaben werden weiterhin hart
abgewiesen.

**`escapeshellcmd()`** — Mechanismus bestätigt, im Betrieb nicht auslösbar.
Nachgestellt mit dem Pfad `/tmp/sk/mit ordner/venv/bin/python3`:
`escapeshellcmd` liefert Code 127 (`sh: 1: /tmp/sk/mit: not found`), weil es
Sonderzeichen entschärft, aber **keine** Anführungszeichen setzt;
`escapeshellarg` liefert Code 0. Der Pfad lautet im Betrieb
`/opt/loxberry/bin/plugins/<name>` und enthält kein Leerzeichen. Alle vier
Stellen wurden trotzdem umgestellt — `escapeshellarg` ist das richtige
Werkzeug und kostet nichts.

**Verlorene Fehlerdetails beim Re-Login** — trifft zu. Nachgestellt mit der
Schleife aus `skoda.py`: schlägt die Neuanmeldung fehl, stand im Zustand
weiterhin *„Die gespeicherte Sitzung ist abgelaufen"*, obwohl in Wahrheit
*„Anmeldung abgewiesen: Benutzername oder Passwort stimmen nicht"* zutraf —
man sucht dann an der falschen Stelle. Der Grund der Neuanmeldung überschreibt
jetzt den alten.

**Nebenbefund: die Reiter brauchten JavaScript.** Der Kommentar über der
Reiterleiste versprach, die Seite sei „weiterhin bedienbar", wenn das Skript
ausfällt. Nachgemessen: `sm-active` wurde ausschließlich vom Skript vergeben,
ohne JavaScript war **keine** der fünf Flächen sichtbar. Reihenfolge,
Beschriftung und Positivliste kommen jetzt aus einem einzigen Feld, und der
Server setzt `sm-active` selbst; alle fünf Reiter sind über `?form=…` ohne
JavaScript erreichbar, unbekannte Werte fallen auf *Einstellungen* zurück.
Zwei PHP-8-Warnungen (`Undefined array key "mqtt_topic"` und `"email"`)
wurden dabei ebenfalls beseitigt.

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
