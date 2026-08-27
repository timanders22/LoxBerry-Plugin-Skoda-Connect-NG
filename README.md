# LoxBerry-Plugin: Skoda Connect

Bindet **Skoda-Fahrzeuge** über das MySkoda-Konto an Loxone an: Ladezustand,
Tankfüllstand, Reichweite, Kilometerstand, Verriegelung, Türen und Fenster,
Klimatisierung, Standort, Warnleuchten sowie Inspektions- und
Ölservice-Fristen. Auf Wunsch lassen sich Klimatisierung, Ladevorgang,
Ladegrenze und Scheibenheizung schalten.

> **Fassung 0.9.13 — ungeprüft.** Das Plugin wurde ohne Skoda-Konto und ohne
> Fahrzeug gebaut. Aufbau, Oberfläche, Endpunkt, Absicherung und Sprachdateien
> sind geprüft; ob die Anmeldung an der Skoda-Cloud gelingt, ob ein Fahrzeug
> alle abgefragten Endpunkte beantwortet und ob die schreibenden Befehle die
> erwartete Wirkung haben, ist es **nicht**. Deshalb 0.9.x und nicht 1.0.0,
> und deshalb sind schreibende Befehle ab Werk gesperrt. Die
> Selbstaktualisierung zeigt auf dieses Repository; bei gleicher Fassung wird
> niemandem ein Update angeboten.

## Was 0.9.13 ändert

Eine zeilenweise Durchsicht der ganzen Linie. Sieben Befunde sind an einem
LoxBerry-Nachbau mit echtem PHP 7.4 und 8.4 **gemessen** worden, nicht
gelesen; dazu kommen elf Funktionen, die es vorher nicht gab. Alle Messungen
sind gegen die Fassung 0.9.12 gefahren und danach gegen diese wiederholt.

### Der Rückspielknopf zeigte danach den alten Stand — und ein Druck auf Speichern machte ihn wieder gültig

Der schwerste Befund. Die beiden Sicherungs-Handler standen **hinter** dem
Laden der Anzeigewerte, was der eigene Kopfkommentar der `index.php`
ausdrücklich verbietet. Gemessen unter PHP 8.4 an 0.9.12:

```
Meldung       "Einstellungen zurückgespielt: 12 Werte übernommen."
Feld Takt     300    (in der Datei stand 600)
Feld Thema    skoda  (in der Datei stand neuesthema)
Aktionstoken  altes  (in der Datei stand das neue)
Kasten        "Schreibende Befehle gesperrt", obwohl freigegeben
```

Zwei Folgen. Wer danach auf **Speichern** drückte, schrieb die angezeigten
alten Werte zurück — **sieben von zwölf Werten** waren wieder auf dem Stand
vor dem Zurückspielen. Und die Seite zeigte das alte Token, während die im
selben Zug heruntergeladene Loxone-Vorlage das neue trug; wer eine Adresse
von der Seite abschrieb, bekam dauerhaft HTTP 403, und ein virtueller Eingang
wertet den nicht aus.

### Das Zurückspielen prüfte den Schlüssel, nicht den Wert

Eine von Hand gebaute Datei ging vollständig durch: `intervall: "abc"`,
`takt_stamm: -99`, `temp_min 99` bei `temp_max -5`, ein **Feld** im
Verlaufsfeld, ein **Objekt** im Sitzungsfeld und ein Themenpräfix mit
Leerzeichen. Letzteres zerlegt die Zeile am UDP-Eingang des Gateways: aus
`publish a b;c/soc 55` wird das Thema `a` mit dem Wert `b;c/soc 55`.

Der schärfste Fall war `"steuerung_ein": "0"` — über das Formular nicht
erzeugbar, über eine Datei sehr wohl:

```
PHP    empty("0")           -> true    Oberfläche zeigt „gesperrt"
Python not cfg.get(...)     -> False   Dienst führt den Befehl aus
```

Die Oberfläche meldete also „Schreibende Befehle gesperrt", und ein Knopf im
Reiter *Test* klimatisierte das Auto trotzdem. Es gibt jetzt `sk_regeln()` mit
einer Zulässigkeitsregel je Einstellung; sie gilt für das Formular, für das
Zurückspielen **und** für das Lesen der Datei. Abgewiesen wird, nicht gekappt:
bei einer Datei sähe niemand, dass aus 99999 eine 3600 wurde.

### Es gab keinen Schutz gegen fremde Formulare — der Kommentar behauptete einen

`webfrontend/htmlauth/index.php` schrieb seit jeher, wer ohne gültiges
Formularmerkmal messe, werde „vom Wachposten abgewiesen". Im ganzen Plugin
stand kein `hash_equals`. Gemessen an 0.9.12, ein POST von einer beliebigen
fremden Seite:

```
token_neu=1    -> das Aktionstoken wurde neu gewürfelt
log_leeren=1   -> das Protokoll wurde überschrieben
```

Danach bekommen sämtliche virtuellen Eingänge im Miniserver HTTP 403 — die
Überwachung ist tot, ohne jede Rückmeldung —, und die Spur ist gleich mit weg.
`htmlauth/` schützt gegen den unangemeldeten Aufruf, nicht gegen ein Formular
auf einer fremden Seite: die Anmeldung schickt der Browser automatisch mit.
Es gibt jetzt **eine** Prüfung am Eingang, vor allen Handlern, und alle vier
Fälle sind unter beiden PHP-Fassungen gemessen — auch der vierte, den man
vergisst: ein **leeres** Merkmal, denn `hash_equals('', '')` ist in PHP `true`.

### Der Warntext versprach Zugangsdaten, die nicht in der Datei standen

„Die Datei enthält Ihre Zugangsdaten" stand am Sicherungsknopf — gemessen am
erzeugten Download stimmte es nicht: die Sicherung enthielt nur `skoda.json`,
und Benutzername und Passwort wohnen in `zugang.json`. Damit war der erklärte
Zweck, der Umzug auf einen zweiten LoxBerry, nicht erfüllbar. Es gibt jetzt
einen **Haken**, ab Werk aus, und der Dateiname sagt es mit
(`_mit_zugang`). Dazu ein lesbarer Kopf mit Datum und Fassung, und nach dem
Zurückspielen die Auskunft, was mit dem Dienst geschehen ist.

### Eine fremde VIN startete die Klimatisierung im falschen Auto

`vin_waehlen()` fiel still auf Fahrzeug 1 zurück, sobald die Eingabe weder
Nummer noch bekannte VIN war. Gemessen an einem Konto mit zwei Fahrzeugen:

```
fahrzeug=TMBBBBBBBBBBBBBB2   -> TMBBBBBBBBBBBBBB2   richtig
fahrzeug=TMBJJ7NE9J0123456   -> TMBAAAAAAAAAAAAA1   FALSCHES AUTO
```

Die Musterprüfung des Endpunkts lässt jede 17-stellige VIN durch. Der
Endpunkt verbietet das stille Zurechtbiegen drei Zeilen über seiner eigenen
Musterprüfung; hier stand das Gegenteil. Eine unbekannte VIN wird jetzt mit
**HTTP 404** abgewiesen.

### Die Neuanmeldung nach abgelaufenem Token lief praktisch nie an

Jeder Endpunktfehler wird in `endpunkt()` abgefangen und nur vermerkt — ein
abgelaufener Token äußert sich aber genau dort, an jedem einzelnen Endpunkt,
und erreichte das äußere `except` nie. Übrig blieb `list_vehicle_vins()`, und
das läuft bei gefüllter Liste nur alle `takt_stamm` Zyklen: **einmal pro
Stunde**. So lange scheiterte jeder Abruf. Die Neuanmeldung hängt jetzt an
einem Merker, den jede Stelle setzt, die einen Anmeldefehler sieht — auch die
Warteschlange.

### Ein falsches Passwort erzeugte 1440 Anmeldeversuche am Tag

Nach einer gescheiterten Anmeldung endete der Prozess. Der Sollmerker blieb
liegen, `cron.01min` holte den Dienst binnen 60 Sekunden zurück, und der
versuchte sofort wieder Benutzername und Passwort. Die vorhandene Bremse half
nicht — sie lebt nur innerhalb eines Prozesses. Der Dienst **bleibt** jetzt am
Leben und wartet ansteigend (1, 5, 15, 30, 60 Minuten).

### Weitere Berichtigungen

* **Die Warteschlange lief in Zufallsreihenfolge.** Der Dateiname war
  `bin2hex(random_bytes(8))`; zwei Befehle aus demselben Zyklus liefen mit
  halber Wahrscheinlichkeit verkehrt herum — `laden_start`, dann `laden_stop`
  wurde zu stop, dann start, und das Auto lud. Der Kennung geht jetzt die
  Zeit voran.
* **Befehle verfielen nie.** Ein `klima_start`, das bei gestopptem Dienst
  eingereiht wurde, heizte das Auto beim nächsten Start — auch am Folgetag.
  Sie tragen jetzt eine Frist, und `sk_befehl_absetzen()` prüft selbst, ob der
  Dienst läuft (der Reiter *Test* tat das vorher nicht).
* **Ein misslungenes `unlink` wurde verschluckt** und der Befehl trotzdem
  abgesetzt — die Datei blieb liegen, und die Schleife läuft im Sekundentakt.
  Aus einem `wecken` wurde damit Dauerbeschuss.
* **`ERREICH=1`, wenn niemand es wusste.** `0 if hole(vs,"unreachable") else 1`
  macht aus einem fehlenden Feld eine 1. Drei solche Stellen berichtigt.
* **Fachliche Ablehnungen kamen als HTTP 500.** „Zieltemperatur außerhalb der
  Grenzen" ist kein Serverfehler; jetzt 409.
* **`OK` und `ALTER` galten global.** Bei zwei Autos genügte eines, das
  antwortet: das ausgefallene meldete weiter `OK=1` mit kleinem `ALTER`. Jetzt
  je Fahrzeug, dazu `AUSFAELLE`.
* **`ALTER=-1`** für „noch nie abgerufen" unterlief jede Loxone-Regel der
  Bauart `ALTER > 900`. Jetzt 999999.
* **`kilometerstand_wartung`** wurde belegt und nirgends gelesen; fällt der
  Gesundheitsabruf aus, steht jetzt der Wert aus dem Wartungsabruf da.
* **Der Vorlagenknopf stand fest auf Fahrzeug 1**, obwohl die Tabelle darüber
  die Adressen aller Fahrzeuge zeigt.
* **Fünf von zwölf schaltenden Aktionen waren nirgends dokumentiert**
  (`zieltemperatur`, `scheibe_aus`, `lueftung_start`, `lueftung_stop`,
  `wecken`), drei davon im Reiter *Test* nicht auslösbar. Alle drei Stellen
  entstehen jetzt aus `sk_befehle()`.
* **Der Taktgeber driftete** um die Dauer des Abrufs: bei 300 s Vorgabe und
  20 s Abruf waren es 320 s, während die Oberfläche 300 nannte.
* **Die MQTT-Prüfzeile im Reiter *Test* war grün**, auch wenn der Haken aus
  war und das Plugin gar nichts sendete.
* **`--einmal` übersprang `ms.disconnect()`** — die Abmeldung unterblieb also
  genau in dem Aufruf, der zum Prüfen gedacht ist.
* **Das Stoppfenster in `dienst.sh` war zu klein.** Zehn Sekunden bei 30 s je
  hängendem Endpunkt: das harte Töten war der Normalfall, und ein `kill -9`
  mitten in der Warteschlange lässt einen Befehl spurlos verschwinden. Jetzt
  70 Sekunden.

### Neu

* **Lebenszeichen.** `status/ok`, `status/ts`, `status/zaehler` und
  `status/fehler_folge` gehen bei **jedem** Durchgang hinaus, auch bei einer
  Störung; `status/dienst` kommt vom Minutencron, nicht vom Dienst selbst.
  Über MQTT gab es bisher weder Zeitstempel noch Alter — ein reiner
  MQTT-Anwender konnte einen Ausfall grundsätzlich nicht erkennen.
* **`retain`** wahlweise statt `publish`, ab Werk aus. Das Befehlswort ist im
  Bestand dieses Hauses dreifach belegt, an einem laufenden Gateway aber nie
  nachgemessen — der Kasten am Haken sagt das.
* **Drei Bremsen** gegen HTTP 429: Mindestabstand zwischen Sofortabrufen,
  Höchstzahl schreibender Befehle je Stunde, Entprellung für denselben Befehl
  mit demselben Wert.
* **Heimatort und Geofence.** `ZUHAUSE` (1/0) und `HEIMENTF` (Meter) aus
  Position und eingetragenen Koordinaten. Ohne Eintrag bleiben beide leer.
* **Ladeprotokoll.** Je abgeschlossenem Ladevorgang eine Zeile — Beginn, Ende,
  Ladezustand von und bis, höchste Leistung, Ort. Sichtbar im Reiter
  *Einstellungen* und über `aktion=ladungen`. Die Energie in kWh wird bewusst
  **nicht** ausgewiesen: sie ließe sich nur hochrechnen und sähe dann aus wie
  ein Messwert.
* **Vorlagen für alle vier Endpunkte** und ein **Virtueller Ausgang** mit
  allen zwölf Befehlen. Die Statusvorlage heißt weiter `SKODA_1_SOC` und so
  fort — eine bestehende Einbindung bleibt gültig.
* **Mehrtagesverlauf.** Die Tagesdateien der Vortage lagen da und wurden nie
  angesehen.
* **Konfigurationslage im Reiter *Test*:** fremde Schlüssel, abgewiesene Werte,
  fehlende Schlüssel.
* **Protokollzeilen für Handgriffe.** Die Oberfläche schrieb bisher nie ins
  Protokoll; nach einem fremden Formular oder einem versehentlichen
  Zurückspielen gab es keine Spur.
* **Mithören fremder MQTT-Themen** — freiwillig, ab Werk aus, verlangt
  `paho-mqtt`: eine **Ladeempfehlung** aus Strompreis oder PV-Überschuss (das
  Plugin entscheidet nicht, es empfiehlt) und eine **Vorklimatisierung zur
  Abfahrtszeit**. Letztere ist der einzige Weg, auf dem dieses Plugin von sich
  aus etwas schaltet, und hängt deshalb an zwei Haken. **Beides ist hier nicht
  erprobt** — es gibt weder Broker noch Fahrzeug.

### Was an diesem Stand ungeprüft bleibt

Unverändert alles, wofür ein Konto und ein Fahrzeug nötig sind. Neu dazu:
`retain` am laufenden Gateway, und das Mithören fremder Themen am Broker.

## Was 0.9.11 ändert

Fünf Korrekturen. Die erste verlangt **einen Handgriff in Loxone Config**, die
zweite entfernt ein Geheimnis von der Platte, und eine weitere schließt eine
Lücke, in der bisher gar nicht geprüft wurde.

### Der Suchtext des Kilometerstands war zweideutig — bitte nachtragen

Der virtuelle Eingang für `KM` trug bisher den Suchtext `\iKM=\i\v`. Die
Antwort des Wartungs-Abrufs führt aber `INSPKM=` und `OELKM=` **vor** `KM=`,
und Loxone nimmt die erste Fundstelle. Der Kilometerstand las damit die
Inspektionsvorgabe. Beide Zahlen sehen aus wie ein Kilometerstand — der Fehler
meldet sich nicht.

Alle Suchtexte tragen jetzt das Semikolon: `\i;KM=\i\v`, und sie entstehen an
**einer** Stelle im Quelltext statt an fünf.

> **Was Sie tun müssen:** Wer die Importdatei neu erzeugt, bekommt die
> berichtigten Suchtexte automatisch. Wer die Eingänge behalten will, ändert in
> Loxone Config bei den **drei Eingängen mit `KM` im Namen** den Suchtext von
> `\iNAME=` auf `\i;NAME=`.

### Die S-PIN ist fort — samt dem gespeicherten Wert

Das Formular nahm eine vierstellige S-PIN an und legte sie in `zugang.json`
ab. Benutzt wurde sie **nie**: MySkoda verlangt sie nur für Ver- und
Entriegeln, und das bietet dieses Plugin nicht an. Der Hilfetext sagte das
selbst — „das Feld ist für eine spätere Fassung vorbereitet".

Diese Vorbereitung kostete die Ziffernfolge, mit der sich das Fahrzeug
aufschließen lässt: dauerhaft auf der Platte, und bei jedem Upgrade in eine
Zweitschrift daneben kopiert. Ein Geheimnis, das nichts bewirkt, ist reines
Risiko.

Das Feld ist deshalb fort, und der Installateur **entfernt einen vorhandenen
Wert** aus `zugang.json` und aus der Zweitschrift — überschreibend, und er sagt
in der Installationsmeldung, dass er es getan hat. Ein Feld zu entfernen und
den Wert liegen zu lassen wäre die schlechteste der Möglichkeiten gewesen: ein
Geheimnis, das niemand mehr sieht und niemand mehr verwaltet. Kommt die
Fassung, die Ver- und Entriegeln anbietet, kehrt das Feld zurück.

### Nach einer Aktualisierung läuft der Dienst wieder

`preupgrade.sh` hält den Dienst an. Ein Merker **neben** dem
Konfigurationsordner sagt dem `postinstall.sh`, dass er lief, und der startet
ihn wieder — sofort und ohne Umweg. Der Merker wird nur gesetzt, wenn der
Vorgang wirklich lief, und in jedem Fall wieder entfernt.

> **Was diese Korrektur NICHT ist, und das gehört hierher.** Ursprünglich stand
> hier, das Plugin habe nach jeder Aktualisierung stillgestanden, weil der
> Installateur `data/` ausräume. **Das war falsch und nie gemessen.** Nachgelesen
> in `sbin/plugininstall.pl`: beim Upgrade werden `config/` und `data/` des
> Plugins angelegt, falls sie fehlen, und der Archivinhalt wird darüber kopiert
> (`:891`, `:895`, `:996`, `:1000`); gelöscht werden sie nur in
> `purge_installation` (`:1604`, `:1606`), und die läuft ausschließlich beim
> **Deinstallieren** (`:233`). Der Sollmerker `soll_laufen` überlebt das Upgrade
> also, und der Cron-Wächter holt den Dienst binnen einer Minute von selbst
> zurück. Diese Korrektur verkürzt ein Fenster von bis zu 60 Sekunden und macht
> den Start unabhängig vom Wächter — sie behebt keinen Stillstand.

### Die Prozessprüfung war zu weich

`sk_dienst_pid()` fragte `strpos($cmd, 'skoda.py')`. `/proc/<pid>/cmdline`
enthält alle Argumente, durch Nullbytes getrennt — hatte die wiederverwendete
Nummer aus der PID-Datei einen Editor mit geöffneter `skoda.py` erwischt, galt
der als laufender Dienst. Die Oberfläche reihte dann Befehle ein, die niemand
abarbeitet, und meldete „eingereiht" statt „läuft nicht". Verglichen wird jetzt
**argumentweise** gegen den vollen Pfad, wie in der Schwesterlinie Volkswagen
seit 0.9.0.

### Die Reiter werden jetzt geprüft — vorher tat es niemand

Die Reiterleiste entsteht in einer Schleife über `$sk_reiter`. Das ist die
richtige Lösung: die Namen stehen nur einmal da. Nur sucht
`hausstandard_pruefen.py` die Reiter als wörtliche Zeichenketten im Quelltext
und findet in einer erzeugten Leiste keine — die Spalte `tab` blieb ein
**Strich**. Ein Strich liest sich wie „nichts zu beanstanden", er heißt aber
„nichts gemessen". Einen eigenen Test dafür gab es nicht.

Der Reiter *Test* prüft es jetzt selbst, am Quelltext der Oberfläche: eine
Fläche ohne Eintrag in der Liste (der Reiter ist unerreichbar und die Seite
springt nach jedem Absenden zurück) und ein Eintrag ohne Fläche (der Reiter
bleibt leer). Die Leiste selbst wird **nicht** verglichen, und das ist keine
Lücke: sie entsteht aus derselben Liste. Geeicht mit
`Werkzeuge/reiterpruefung_eichung.py` — beide Fälle werden rot, und zwar mit
dem richtigen Grund.

### Baustein #14 hatte vier Eingänge

Bei `UND` und `ODER` ist die Zahl der Eingänge eine Baustein-Eigenschaft, die
Loxone Config selbst setzt; ein dritter Eingang kostet beim nächsten Öffnen
alle Verbindungen, die daran hingen. #14 nennt jetzt zwei Eingänge mit je zwei
Quellen — an einem ODER dasselbe Ergebnis. Bei #30 (ein UND) bleibt es bei
einer Quelle je Eingang: dort verwandelte dieselbe Form das UND still in ein
ODER.

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

Ein S-PIN-Feld gibt es **seit 0.9.11 nicht mehr**: Ver- und Entriegeln bietet
dieses Plugin bewusst nicht an, und nur dafür verlangt MySkoda die S-PIN. Ein
Geheimnis, das nichts bewirkt, ist reines Risiko — es lag dauerhaft auf der
Platte und wanderte bei jedem Upgrade in eine Zweitschrift daneben. Ein noch
vorhandener Wert wird beim nächsten Speichern mit entfernt.

*(Bis 0.9.12 stand hier weiter „Ein S-PIN-Feld gibt es" — im Widerspruch zum
Abschnitt über 0.9.11 dreißig Zeilen weiter oben. Berichtigt mit 0.9.13.)*

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
`<LoxBerry-Wurzel>/bin/plugins/<name>` und enthält kein Leerzeichen. Alle vier
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
