#!REPLACELBPBINDIR/venv/bin/python3
"""Skoda Connect - Abrufdienst fuer LoxBerry.

Holt die Werte der Skoda-Cloud ueber die freie Bibliothek "myskoda", legt sie
als JSON-Zwischenspeicher ab, gibt sie auf Wunsch ueber das LoxBerry-MQTT-
Gateway weiter und arbeitet Schreibbefehle aus einer Warteschlange ab, die der
Loxone-Endpunkt fuellt.

Warum myskoda und nicht skodaconnect: Die alte Bibliothek "skodaconnect" ist
vom selben Projekt ausdruecklich als DEPRECATED gekennzeichnet worden, ebenso
die darauf aufbauende HomeAssistant-Einbindung. Skoda hat die Schnittstelle
umgestellt; der Nachfolger heisst "myskoda" und spricht die heutige API.

Drei Aufgaben, drei Dateien - dieses Skript ist der Dienst. Die Oberflaeche
(webfrontend/htmlauth/index.php) und der Miniserver-Endpunkt
(webfrontend/html/index.php) rufen es nie direkt auf, sondern lesen den
Zwischenspeicher beziehungsweise legen Befehle ab.

Aufrufe:
    skoda.py                 Dienst (Dauerbetrieb)
    skoda.py --einmal        ein einzelner Abruf, dann Ende
    skoda.py --selbsttest    Pruefungen ohne Netz, Ausgabe als Klartext
    skoda.py --wachzeichen   ein MQTT-Thema: laeuft der Dienst? (Minutencron)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import signal
import socket
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path


def lb_wurzel_ermitteln():
    """Den LoxBerry-Wurzelordner ohne festen Systempfad bestimmen.

    Vom eigenen Ablageort aufwaerts, bis ein Verzeichnis gefunden ist, das
    config/plugins UND webfrontend enthaelt. Trifft die uebliche
    Installation genauso wie eine an einem anderen Ort.
    """
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.isdir(os.path.join(d, "config", "plugins")) \
                and os.path.isdir(os.path.join(d, "webfrontend")):
            return d
        eltern = os.path.dirname(d)
        if eltern == d:
            break
        d = eltern
    return ""


def mqtt_wert_saeubern(wert):
    """Einen Wert fuer den UDP-Eingang des MQTT-Gateways unschaedlich machen.

    Das Gateway liest zeilenweise. Ein Zeilenumbruch im Wert zerlegt die
    Uebertragung, und aus den Bruchstuecken bildet das Gateway erfundene
    Themen. Ein Tabulator schadet ebenso, weil Leerzeichen Thema und Wert
    trennt.
    """
    text = str(wert)
    for zeichen in ("\r\n", "\r", "\n", "\t"):
        text = text.replace(zeichen, " ")
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip()


# ---------------------------------------------------------------------------
# Pfade aus dem EIGENEN Ablageort ableiten.
#
# Nicht ueber LoxBerry::System: das leitet den Pluginordner aus dem Aufrufort
# ab und liefert bei einem Start aus postinstall.sh oder aus dem Cron ueberall
# Leerstring. Sichtbare Folge waere ein Dienst, der gegen /-Pfade werkelt und
# trotzdem Erfolg meldet.
# ---------------------------------------------------------------------------
SELF = Path(__file__).resolve().parent            # <home>/bin/plugins/<ordner>
PNAME = SELF.name


def _lb_wurzel():
    """Den LoxBerry-Wurzelordner bestimmen - und zwar nachgesehen.

    GEPRUEFT WIRD DIE PLAUSIBILITAET, NICHT DIE TIEFE. Berichtigt 31.08.2026.

    Bis 0.9.14 stand hier "if len(SELF.parents) >= 3: LBHOME = SELF.parents[2]".
    Das ist keine Wache, sondern eine Zaehlung: drei Ebenen ueber sich hat fast
    jeder Pfad. Nachgerechnet:

      <home>/bin/plugins/skodaconnect/         ->  <home>            richtig
      /home/x/LoxBerry-Plugin-Skoda-.../bin/   ->  /home             falsch
      /srv/repo/bin/                           ->  /                 falsch

    In den beiden unteren Faellen wurde PNAME zu "bin" und PDATA zu
    "/home/data/plugins/bin" - also genau der Dienst, der "gegen /-Pfade
    werkelt und trotzdem Erfolg meldet", vor dem der Kommentar darueber warnt.
    Und lb_wurzel_ermitteln(), die Funktion, die wirklich nachsieht, wurde
    dabei nie erreicht.
    """
    kandidat = SELF.parents[2] if len(SELF.parents) >= 3 else None
    if kandidat is not None and (kandidat / "config" / "plugins").is_dir() \
            and (kandidat / "webfrontend").is_dir():
        return kandidat
    umgebung = os.environ.get("LBHOMEDIR") or ""
    if umgebung and os.path.isdir(os.path.join(umgebung, "config", "plugins")):
        return Path(umgebung)
    gesucht = lb_wurzel_ermitteln()
    if gesucht:
        return Path(gesucht)
    # Nichts davon hat getragen. Geraten wird nicht - main() bricht mit einer
    # Meldung ab. Der Rueckfall haelt nur den Modulimport am Leben, den die
    # Pruefstaende brauchen.
    return kandidat if kandidat is not None else SELF


LBHOME = _lb_wurzel()
LBHOME_ECHT = ((LBHOME / "config" / "plugins").is_dir()
               and (LBHOME / "webfrontend").is_dir())
PDATA = LBHOME / "data" / "plugins" / PNAME
PLOG = LBHOME / "log" / "plugins" / PNAME
PCONFIG = LBHOME / "config" / "plugins" / PNAME

DATEI_CONFIG = PCONFIG / "skoda.json"
DATEI_ZUGANG = PCONFIG / "zugang.json"
# Die Zweitschriften liegen NEBEN dem Konfigordner, nicht darin - der
# Installateur raeumt config/plugins/<ordner>/ bei jedem Upgrade ab. Sie
# werden hier nur GELESEN; geschrieben werden sie von der Oberflaeche.
DATEI_CONFIG_ZWEIT = LBHOME / "config" / "plugins" / (PNAME + ".backup.skoda.json")
DATEI_ZUGANG_ZWEIT = LBHOME / "config" / "plugins" / (PNAME + ".backup.zugang.json")
DATEI_CACHE = PDATA / "cache.json"
DATEI_LOXONE = PDATA / "loxone.json"
DATEI_ZUSTAND = PDATA / "zustand.json"
DATEI_MARKE = PDATA / "sitzung.json"          # zwischengespeicherter Refresh-Token
ORDNER_BEFEHLE = PDATA / "befehle"
ORDNER_ANTWORTEN = PDATA / "antworten"
DATEI_LOG = PLOG / "skoda.log"

# ---------------------------------------------------------------------------
# Zeitgrenzen
#
# aiohttp haengt NICHT unbegrenzt - nachgemessen mit aiohttp 3.14 gegen ein
# Gegenstueck, das die Verbindung annimmt und danach schweigt:
#   Vorgabe der Bibliothek: ClientTimeout(total=300, sock_connect=30)
# Die verbreitete Sorge "friert auf unbestimmte Zeit ein" trifft also nicht zu.
# Fuenf Minuten sind hier trotzdem unbrauchbar: ein Fahrzeug wird ueber NEUN
# Endpunkte abgefragt, macht im schlechtesten Fall 45 Minuten fuer einen
# Durchgang - bei einem Takt von fuenf Minuten. Der Dienst waere dann nicht
# abgestuerzt, sondern einfach weg, und die Warteschlange (die im selben
# Ablauf haengt) nimmt in dieser Zeit keinen Befehl mehr an.
#
# Deshalb zwei Netze:
#   1. asyncio.wait_for je Aufruf - greift auch bei Haengern, die nichts mit
#      dem Netz zu tun haben, etwa einer Sperre in der Bibliothek.
#   2. ClientTimeout auf der Sitzung als Auffanglinie darunter.
# Nachgemessen: 120 abgebrochene Abrufe hinterlassen 0 belegte Verbindungen -
# wait_for raeumt die Verbindung ordentlich ab, der Vorrat laeuft nicht leer.
GRENZE_ABRUF = 30      # ein Lese-Endpunkt
GRENZE_BEFEHL = 60     # ein Schreibbefehl - ein schlafendes Fahrzeug braucht laenger
GRENZE_ANMELDUNG = 60  # der Anmeldeweg umfasst mehrere Abrufe hintereinander
GRENZE_SITZUNG = 90    # Auffanglinie je einzelnem HTTP-Abruf
# Hoechstzahl der Befehle, die EIN Lauf der Warteschlange abarbeitet.
GRENZE_BEFEHLE_JE_LAUF = 12
# Wie lange ein eingereihter Befehl gueltig bleibt, wenn die Oberflaeche
# nichts anderes sagt. Der Endpunkt setzt 'gueltig_bis' selbst; dieser Wert
# faengt nur Dateien aus einer aelteren Fassung ab.
VERFALL_BEFEHL = 300

# Muessen zu sk_vorgaben() in webfrontend/html/sk_lib.php passen.
VORGABEN = {
    "intervall": 300,
    "takt_stamm": 12,
    "takt_wartung": 24,
    "mqtt_ein": 0,
    "mqtt_topic": "skoda",
    "mqtt_retain": 0,
    "steuerung_ein": 0,
    "temp_min": 16,
    "temp_max": 29,
    "verlauf_tage": 8,
    "sitzung_merken": 1,
    "abstand_abruf": 60,
    "befehle_stunde": 30,
    "entprellung": 20,
    "heim_breite": "",
    "heim_laenge": "",
    "heim_radius": 150,
    "empf_thema": "",
    "empf_grenze": "",
    "empf_kleiner": 1,
    # Hoechstalter des empfangenen Wertes in Sekunden, 0 = ohne Grenze.
    #
    # Das ist eine EINSTELLUNG und keine Messung: 10800 s (drei Stunden) ist
    # eine gewaehlte Schranke, kein Wert, den jemand ermittelt haette. Sie
    # steht deshalb im Formular und nicht als Zahl im Code. Der Gedanke
    # dahinter: ein Thema, das einen Strompreis oder einen PV-Ueberschuss
    # fuehrt, meldet sich weit oefter als alle drei Stunden; schweigt es
    # laenger, sagt sein letzter Wert nichts mehr ueber jetzt.
    "empf_alter": 10800,
    "abfahrt_ein": 0,
    "abfahrt_thema": "",
    "abfahrt_vorlauf": 20,
    "abfahrt_temp": 21,
}

# Die Ja/Nein-Einstellungen. Sie werden in config() auf 0 oder 1 GEZWUNGEN,
# und das ist keine Kosmetik:
#
#   PHP    empty("0")            -> true     Oberflaeche zeigt "gesperrt"
#   Python not cfg.get("...")    -> False    Dienst fuehrt den Befehl aus
#
# Die Zeichenkette "0" ist in PHP leer und in Python wahr. Eine Konfiguration
# mit "steuerung_ein": "0" - ueber das Formular nicht erzeugbar, ueber eine
# zurueckgespielte Sicherungsdatei bis 0.9.12 sehr wohl - zeigte in der
# Oberflaeche "Schreibende Befehle gesperrt", und ein Knopf im Reiter Test
# klimatisierte das Auto trotzdem. Gemessen am 27.08.2026.
SCHALTER = ("mqtt_ein", "mqtt_retain", "steuerung_ein", "sitzung_merken",
            "empf_kleiner", "abfahrt_ein")

# Zustaende, die Loxone als Zahl braucht. Ein unbekannter Zustand wird zu None
# (am Endpunkt ein Strich), NICHT zu 0 - eine 0 waere eine stille
# Falschaussage: "Tueren zu", obwohl niemand es weiss.
OFFEN_ZU = {"CLOSED": 0, "OPEN": 1}
AN_AUS = {"OFF": 0, "ON": 1}
# DoorLockedState der Bibliothek: LOCKED = "YES", UNLOCKED = "NO".
VERRIEGELT = {"YES": 1, "NO": 0, "LOCKED": 1, "UNLOCKED": 0,
              "OPENED": 0, "TRUNK_OPENED": 0}
# AirConditioningState -> 1, wenn irgendetwas laeuft.
KLIMA_AN = {"COOLING": 1, "HEATING": 1, "HEATING_AUXILIARY": 1,
            "VENTILATION": 1, "ON": 1, "OFF": 0}
# ChargingState -> laedt gerade?
LADEN_AN = {"CHARGING": 1, "CONSERVING": 0, "READY_FOR_CHARGING": 0,
            "CONNECT_CABLE": 0, "CHARGING_INTERRUPTED": 0, "ERROR": 0}
# Steckt das Kabel? (ConnectionState aus der Klimaantwort)
KABEL = {"CONNECTED": 1, "DISCONNECTED": 0}

_LAUF = True
_LOG = logging.getLogger("skoda")
_LETZTE_MELDUNG: dict[str, float] = {}
# Setzt jede Stelle, die einen Anmeldefehler SIEHT. Ausgewertet wird er in der
# Hauptschleife. Warum ein Merker und nicht das aeussere except: jeder
# Endpunktfehler wird schon in endpunkt() abgefangen und nur in 'ausfaelle'
# vermerkt - ein abgelaufener Token aeussert sich aber genau dort, an jedem
# einzelnen Endpunkt. Bis 0.9.12 erreichte er das aeussere except nie. Uebrig
# blieb list_vehicle_vins(), und das laeuft bei gefuellter Liste nur alle
# takt_stamm Zyklen: bei Vorgabe einmal pro Stunde. So lange scheiterte jeder
# Abruf, ohne dass sich der Dienst neu anmeldete.
_NEU_ANMELDEN = False


# ---------------------------------------------------------------------------
# Protokollierung
#
# Ausschliesslich in die Datei. Das Startskript leitet die Ausgabe des Dienstes
# ohnehin in dieselbe Datei um - ein zweiter Kanal nach stdout schriebe jede
# Zeile doppelt hinein.
# ---------------------------------------------------------------------------
def log_einrichten(dauerlaeufer: bool = False) -> None:
    """Den Protokollkanal einrichten.

    NUR DER DAUERLAEUFER LAESST DIE DATEI UMLAUFEN. Berichtigt 01.09.2026.

    Bis dahin bekam JEDER Lauf einen RotatingFileHandler - auch der
    Minutencron ("--wachzeichen") und der Selbsttest. Gemessen in der
    installierten Lage: eine 600 023 Byte grosse skoda.log, ein einziger
    Cron-Lauf, und danach lag skoda.log.1 mit 600 023 Byte daneben.

    Der Umlauf benennt um. Linux laesst das an einer Datei zu, die ein
    anderer Vorgang offen haelt - und der Dauerlaeufer schreibt danach in
    die verwaiste Inode weiter. Seine Zeilen erscheinen in skoda.log nie
    wieder und sind beim naechsten Umlauf fort. Ein Cron, der jede Minute
    laeuft, kann das jederzeit ausloesen; der Dauerlaeufer bemerkt es nicht.

    (Die Folge selbst ist hier nicht messbar - Windows verweigert das
    Umbenennen einer offenen Datei. Gemessen ist der Ausloeser.)

    Wer nur anhaengt, kann nichts verlieren. Die Oberflaeche haelt es
    genauso: sk_log_zeile() kappt seit 0.9.15 IN DER DATEI statt umzubenennen.
    """
    PLOG.mkdir(parents=True, exist_ok=True)
    _LOG.setLevel(logging.INFO)
    try:
        h = (RotatingFileHandler(DATEI_LOG, maxBytes=512000, backupCount=1,
                                 encoding="utf-8")
             if dauerlaeufer
             else logging.FileHandler(DATEI_LOG, encoding="utf-8"))
    except OSError as err:
        # Scheitert die Datei, nach stderr - nicht nach stdout.
        h = logging.StreamHandler(sys.stderr)
        print(f"Logdatei nicht beschreibbar ({err}) - schreibe nach stderr.", file=sys.stderr)
    h.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    _LOG.handlers = [h]
    _LOG.propagate = False
    # Die Bibliothek protokolliert selbst reichlich; auf WARNING drosseln,
    # damit die Logdatei lesbar bleibt.
    for fremd in ("myskoda", "aiohttp", "asyncio", "urllib3"):
        logging.getLogger(fremd).setLevel(logging.WARNING)


DATEI_BREMSE = PDATA / "meldebremse.json"


def melde_gebremst(schluessel: str, text: str, sekunden: int = 3600) -> None:
    """Dieselbe Meldung hoechstens einmal je Zeitfenster - sonst wird die
    Logdatei durch eine Dauerstoerung unlesbar.

    DIE BREMSE LIEGT SEIT 31.08.2026 AUF DER PLATTE, nicht nur im Prozess.

    _LETZTE_MELDUNG ist ein Prozessfeld. Der Dauerlaeufer ueberlebt damit
    Stunden - cron.01min aber startet jede Minute einen NEUEN Python-Prozess
    ("dienst.sh wachzeichen"), und dessen Feld ist leer. Steht mqtt_ein auf 1,
    waehrend das Gateway nicht auf Autostart steht - genau der Zustand, den
    das Plugin melden will -, schrieb mqtt_senden() deshalb bei JEDEM
    Cron-Lauf eine WARNING: rund 1440 gleiche Zeilen am Tag.

    Was das kostet: der RotatingFileHandler fasst 512000 Byte mit einer
    Sicherung, also knapp 1 MB. Bei ~160 Byte je Zeile ist nach gut vier Tagen
    jede echte Meldung des Dienstes von dieser einen Warnung verdraengt. Eine
    Bremse, die den Prozess nicht ueberlebt, ist bei einem Minutencron keine.

    Die Datei ist bewusst schlicht und ihr Fehlschlagen bewusst folgenlos:
    laesst sie sich nicht lesen oder schreiben, wird gemeldet statt
    geschwiegen. Eine Bremse darf keine Meldung verhindern, die sonst
    herausginge.
    """
    jetzt = time.time()
    marken = _LETZTE_MELDUNG
    try:
        if DATEI_BREMSE.is_file():
            gelesen = json.loads(DATEI_BREMSE.read_text(encoding="utf-8"))
            if isinstance(gelesen, dict):
                # Der spaetere von beiden gilt: der Dauerlaeufer weiss von
                # seinen eigenen Meldungen mehr als die Datei, und umgekehrt.
                for k, v in gelesen.items():
                    if isinstance(v, (int, float)) and v > marken.get(k, 0):
                        marken[k] = float(v)
    except (OSError, ValueError):
        pass
    if jetzt - marken.get(schluessel, 0) < sekunden:
        return
    marken[schluessel] = jetzt
    _LOG.warning(text)
    try:
        PDATA.mkdir(parents=True, exist_ok=True)
        # Nur Marken behalten, die noch bremsen koennen - sonst waechst die
        # Datei mit jedem neuen Schluessel und wird nie kuerzer.
        frisch = {k: v for k, v in marken.items() if jetzt - v < 86400}
        json_schreiben(DATEI_BREMSE, frisch)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
def json_lage(pfad: Path):
    """Wie json_lesen(), sagt aber, WARUM nichts herauskam.

    ANGELEGT 31.08.2026, aus demselben Anlass wie sk_json_lage() in
    webfrontend/html/sk_lib.php. Bis 0.9.14 gab json_lesen() bei kaputtem
    JSON stumm {} zurueck - eine beschaedigte skoda.json war damit von einer
    fehlenden nicht zu unterscheiden, und der Dienst fuhr lautlos auf
    Werkseinstellung: steuerung_ein 0, mqtt_ein 0, Takt 300. In Loxone sieht
    das aus wie ein Haus, an dem alles in Ordnung ist.

    Rueckgabe: (daten, lage) mit lage aus 'fehlt', 'leer', 'ok', 'kaputt'.
    """
    try:
        roh = pfad.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ({}, "fehlt")
    except OSError:
        return ({}, "kaputt")
    if roh.strip() in ("", "{}"):
        return ({}, "leer")
    try:
        d = json.loads(roh)
    except ValueError:
        return ({}, "kaputt")
    return (d, "ok") if isinstance(d, dict) else ({}, "kaputt")


def json_lesen(pfad: Path) -> dict:
    daten, _ = json_lage(pfad)
    return daten


def json_schreiben(pfad: Path, daten, rechte: int | None = None) -> bool:
    """Erst in eine Nebendatei, dann umbenennen. So liest die Oberflaeche nie
    eine halb geschriebene Datei."""
    try:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        # Die Nebendatei traegt die PROZESSNUMMER. Berichtigt 01.09.2026.
        #
        # Sie hiess "<ziel>.tmp" - fuer alle Schreiber derselbe Name. Der
        # Dauerlaeufer und der Minutencron schreiben beide meldebremse.json;
        # treffen sie zusammen, truncatet der eine die Nebendatei, waehrend
        # der andere hineinschreibt, und das rename veroeffentlicht einen
        # halben Inhalt. Die Hausregel sagt es woertlich: "<ziel>.tmp.<pid>,
        # nicht <ziel>.tmp - sonst zerlegen zwei gleichzeitige Schreiber
        # einander."
        tmp = pfad.with_suffix(pfad.suffix + ".tmp." + str(os.getpid()))
        if rechte is None:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(daten, f, ensure_ascii=False, indent=1, default=str)
        else:
            # Die Rechte gelten AB DEM ERSTEN BYTE.
            #
            # Bis 0.9.12 wurde die Nebendatei mit den Vorgaberechten angelegt
            # (ueblich 0644), der Inhalt hineingeschrieben und erst danach
            # chmod gerufen. Fuer die Dauer des Schreibens lag der
            # Sitzungsschluessel damit fuer jeden lesbar da. Das Fenster ist
            # winzig, und der Selbsttest prueft die ZIELdatei und meldete
            # nichts - eine Luecke, die keine Messung sieht, ist die
            # unangenehmste Sorte.
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, rechte)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(daten, f, ensure_ascii=False, indent=1, default=str)
            os.chmod(tmp, rechte)
        os.replace(tmp, pfad)
        return True
    except (OSError, TypeError, ValueError) as err:
        _LOG.error("Datei %s konnte nicht geschrieben werden: %s", pfad, err)
        return False


def in_grenzen(wert, unten: int, oben: int, vorgabe: int) -> int:
    """Eine ganze Zahl in Grenzen - oder die VORGABE. Nichts wird gekappt.

    EINGEFUEHRT 31.08.2026, und das ist eine Verhaltensaenderung mit Grund.
    Bis 0.9.13 stand hier ueberall max(unten, min(oben, ganz(...))), also
    Kappen. Die Oberflaeche liest DIESELBE Datei und macht seit 0.9.13 etwas
    anderes: sk_wert_pruefen() in webfrontend/html/sk_lib.php weist einen
    unzulaessigen Wert AB und nimmt die Vorgabe, mit ausgeschriebener
    Begruendung:

        "Es wird nichts gekappt und nichts zurechtgebogen. Beim Speichern
         ueber das Formular waere Kappen vertretbar, denn der Bediener sieht
         das Ergebnis sofort - bei einer Datei saehe niemand, dass aus 99999
         eine 3600 wurde."

    Gemessen an einer von Hand geschriebenen skoda.json mit "intervall": 5
    zeigte die Oberflaeche deshalb 300 und der Dienst fuhr 60. Zwei Wahrheiten
    ueber dieselbe Datei, und kein Prueflauf verglich die beiden Seiten -
    skoda_funktionstest.py forderte das Kappen sogar als Soll ein. Beides ist
    am 31.08.2026 berichtigt worden; massgeblich ist die Fassung mit der
    Begruendung.
    """
    try:
        n = int(str(wert).strip())
    except (TypeError, ValueError):
        return vorgabe
    return n if unten <= n <= oben else vorgabe


def _mit_zweitschrift(datei: Path, zweit: Path, was: str) -> dict:
    """Eine Konfigurationsdatei lesen - und bei Schaden die Zweitschrift.

    ANGELEGT 31.08.2026. Der Dienst kannte die Zweitschriften bis 0.9.14
    NICHT (null Treffer im ganzen Modul), obwohl die Oberflaeche sie bei
    jedem Speichern schreibt. Nach einem Schaden an skoda.json lief er also
    stumm auf Werkseinstellung weiter, waehrend eine gute Fassung danebenlag.

    GELESEN, NICHT KOPIERT: der Dienst laeuft als Dauerlaeufer und schreibt
    hier nichts zurueck. Das Wiederherstellen ist Sache der Oberflaeche
    (sk_config_heilen), die dabei auch die kaputte Datei als .kaputt
    beiseitelegt. Ein Dienst, der viermal die Minute liest, wuerde sonst
    viermal die Minute heilen und protokollieren.
    """
    daten, lage = json_lage(datei)
    if lage != "kaputt":
        return daten
    gut, zlage = json_lage(zweit)
    if zlage == "ok" and gut:
        melde_gebremst(
            "kaputt_" + was,
            f"{datei.name} ist beschaedigt (kein gueltiges JSON) - es gilt die "
            f"Zweitschrift {zweit.name}. Die Oberflaeche einmal oeffnen, dann "
            f"wird sie zurueckgeschrieben.", 3600)
        return gut
    melde_gebremst(
        "kaputt_" + was,
        f"{datei.name} ist beschaedigt (kein gueltiges JSON), und eine "
        f"brauchbare Zweitschrift gibt es nicht. Es gelten die "
        f"Voreinstellungen.", 3600)
    return {}


def config() -> dict:
    c = dict(VORGABEN)
    c.update(_mit_zweitschrift(DATEI_CONFIG, DATEI_CONFIG_ZWEIT, "config"))
    c["intervall"] = in_grenzen(c.get("intervall"), 60, 3600, 300)
    c["takt_stamm"] = in_grenzen(c.get("takt_stamm"), 1, 240, 12)
    c["takt_wartung"] = in_grenzen(c.get("takt_wartung"), 1, 240, 24)
    c["empf_alter"] = in_grenzen(c.get("empf_alter"), 0, 86400, VORGABEN["empf_alter"])
    c["temp_min"] = in_grenzen(c.get("temp_min"), 10, 30, 16)
    c["temp_max"] = in_grenzen(c.get("temp_max"), 10, 30, 29)
    if c["temp_min"] > c["temp_max"]:
        # Getauscht wurde hier bis 0.9.13 stillschweigend. Auch das ist
        # Zurechtbiegen: eine Datei mit temp_min 28 / temp_max 17 ist nicht
        # "verdreht gemeint", sie ist unzulaessig. Beide fallen auf ihre
        # Vorgabe zurueck, und der Reiter Test nennt sie unter 'abgewiesen'.
        c["temp_min"], c["temp_max"] = VORGABEN["temp_min"], VORGABEN["temp_max"]
    c["verlauf_tage"] = in_grenzen(c.get("verlauf_tage"), 1, 90, 8)
    c["abstand_abruf"] = in_grenzen(c.get("abstand_abruf"), 0, 3600, 60)
    c["befehle_stunde"] = in_grenzen(c.get("befehle_stunde"), 1, 240, 30)
    c["entprellung"] = in_grenzen(c.get("entprellung"), 0, 600, 20)
    c["heim_radius"] = in_grenzen(c.get("heim_radius"), 10, 5000, 150)
    c["heim_breite"] = kommazahl(c.get("heim_breite"), -90, 90)
    c["heim_laenge"] = kommazahl(c.get("heim_laenge"), -180, 180)
    c["empf_grenze"] = kommazahl(c.get("empf_grenze"), -1000000, 1000000)
    c["abfahrt_vorlauf"] = in_grenzen(c.get("abfahrt_vorlauf"), 5, 180, 20)
    c["abfahrt_temp"] = in_grenzen(c.get("abfahrt_temp"), 10, 30, 21)
    for feld in ("empf_thema", "abfahrt_thema"):
        # Dieselbe Baendigung wie beim eigenen Praefix: ein Thema mit
        # Leerzeichen oder Zeilenumbruch hat in keiner MQTT-Zeile etwas
        # verloren. Leer heisst "nicht benutzt".
        s = str(c.get(feld) or "").strip().strip("/")
        c[feld] = s if re.match(r"^[A-Za-z0-9_/+#-]{0,128}$", s) else ""
    for s in SCHALTER:
        # Genau "0" oder "1", sonst die Vorgabe - dieselbe Regel wie im Zweig
        # 'schalt' von sk_wert_pruefen(). Bis 0.9.13 wurde hier auf 0 gezwungen,
        # was fuer sitzung_merken (Vorgabe 1) eine dritte Bedeutung ergab: die
        # Oberflaeche zeigte 1, der Dienst fuhr 0.
        roh = c.get(s)
        c[s] = int(roh) if str(roh).strip() in ("0", "1") else VORGABEN[s]
    # Der Themenpraefix wird hier gebaendigt, nicht erst beim Senden.
    # mqtt_wert_saeubern() nahm bis 0.9.12 nur den WERT vor - der Praefix lief
    # ungeprueft in dieselbe Zeile. Bei mqtt_topic = "meine autos" entstand
    #     publish meine autos/fahrzeug1/soc 55
    # und das Gateway trennt Thema und Wert am ersten Leerzeichen: alle
    # Felder landeten unter dem Thema "meine" und ueberschrieben sich
    # gegenseitig. Ein Zeilenumbruch erlaubte darueber hinaus das Einschleusen
    # beliebiger publish-Zeilen. Die Oberflaeche prueft das Muster; ein von
    # Hand bearbeitetes skoda.json oder eine aeltere Fassung tut es nicht.
    c["mqtt_topic"] = thema_saeubern(c.get("mqtt_topic"))
    return c


def kommazahl(wert, min_wert, max_wert):
    """Kommazahl in Grenzen, oder Leerstring - kein Zurechtbiegen."""
    s = str(wert if wert is not None else "").strip().replace(",", ".")
    if s == "":
        return ""
    try:
        f = float(s)
    except (TypeError, ValueError):
        return ""
    return f if min_wert <= f <= max_wert else ""


def thema_saeubern(wert) -> str:
    """Ein MQTT-Themenpraefix, der eine Gateway-Zeile nicht zerlegen kann."""
    t = str(wert if wert is not None else "").strip().strip("/")
    if not re.match(r"^[A-Za-z0-9_/-]{1,64}$", t):
        return "skoda"
    return t


def ganz(wert, ersatz: int) -> int:
    try:
        return int(wert)
    except (TypeError, ValueError):
        return ersatz


def zugang() -> dict:
    z = _mit_zweitschrift(DATEI_ZUGANG, DATEI_ZUGANG_ZWEIT, "zugang")
    return {
        "email": str(z.get("email") or "").strip(),
        "passwort": str(z.get("passwort") or ""),
    }


# ---------------------------------------------------------------------------
# MQTT ueber das LoxBerry-Gateway
#
# Das MQTT-Gateway ist seit LoxBerry 3 Bestandteil des Systems, kein Plugin.
# Es wird nicht nachinstalliert, sondern unter System -> MQTT Gateway
# eingeschaltet.
#
# Achtung: Mqtt.Brokerhost ist ab Werk gesetzt ("localhost"). Eine Pruefung
# darauf beantwortet also NICHT die Frage, ob Nachrichten ankommen koennen.
# Massgeblich ist Gatewayautostart.
# ---------------------------------------------------------------------------
def mqtt_zustand() -> dict:
    gen = json_lesen(LBHOME / "config" / "system" / "general.json")
    m = gen.get("Mqtt") or gen.get("mqtt") or {}
    autostart = m.get("Gatewayautostart", m.get("gatewayautostart"))
    udp = m.get("Udpinport", m.get("udpinport"))
    try:
        udp = int(udp)
    except (TypeError, ValueError):
        udp = 0
    return {
        "gefunden": bool(m),
        "autostart": 1 if str(autostart) in ("1", "true", "True") else 0,
        "udpport": udp,
        "broker": str(m.get("Brokerhost", m.get("brokerhost", ""))),
        "brokerport": str(m.get("Brokerport", m.get("brokerport", ""))),
    }


def mqtt_senden(paare: dict, praefix: str, retain: int = 0) -> tuple[int, int]:
    """Veroeffentlicht die Paare ueber den UDP-Eingang des Gateways.

    Rueckgabe: (versucht, misslungen). Bis 0.9.12 gab die Funktion nichts
    zurueck und meldete nur gebremst ins Protokoll - eine Zahl in der
    Oberflaeche beantwortet dagegen die Frage, ob ueberhaupt etwas hinausgeht,
    auch dann, wenn das Gateway gar nicht eingerichtet ist.

    'retain' laesst das Gateway die Werte behalten. Es ist AB WERK AUS: das
    Befehlswort ist im Bestand dieses Hauses dreifach belegt (Gardena,
    Intercom, WOLF ISM NG), an einem laufenden Gateway aber nie nachgemessen
    worden. Kennt ein Gateway das Wort nicht, verwirft es die Zeile - dann
    kaeme gar nichts mehr an. Der Kasten am Haken sagt das.
    """
    z = mqtt_zustand()
    if not z["udpport"]:
        melde_gebremst("mqtt_kein_port",
                       "MQTT: kein UDP-Eingangsport in general.json gefunden - nichts gesendet.")
        return (0, 0)
    if not z["autostart"]:
        melde_gebremst(
            "mqtt_aus",
            "MQTT: das Gateway ist nicht auf Autostart gestellt (System -> MQTT Gateway). "
            "Es wird gesendet, aber vermutlich hoert niemand zu.",
        )
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError as err:
        melde_gebremst("mqtt_socket", f"MQTT: Socket nicht moeglich ({err}).")
        return (0, 0)
    befehl = "retain" if retain else "publish"
    praefix = thema_saeubern(praefix)
    versucht = 0
    schlecht = 0
    try:
        for k, v in paare.items():
            if v is None:
                continue
            text = mqtt_wert_saeubern(v)
            # Eine LEERE Nutzlast loescht mit 'retain' ein behaltenes Thema.
            # Ein Wert, der nach dem Saeubern nichts uebrig laesst, ist kein
            # Wert - er wird uebersprungen wie None.
            if text == "":
                continue
            versucht += 1
            try:
                s.sendto(f"{befehl} {praefix}/{k} {text}".encode("utf-8"),
                         ("127.0.0.1", z["udpport"]))
            except OSError:
                schlecht += 1
    except OSError as err:
        melde_gebremst("mqtt_senden", f"MQTT: Senden fehlgeschlagen ({err}).")
    finally:
        s.close()
    if schlecht:
        melde_gebremst("mqtt_teil",
                       f"MQTT: {schlecht} von {versucht} Meldungen sind nicht hinausgegangen.")
    return (versucht, schlecht)


# ---------------------------------------------------------------------------
# Hilfsfunktionen zum Auslesen der Antworten
#
# Jedes Feld wird ueber getattr() geholt und ein fehlender Wert bleibt None
# statt 0 zu werden: eine 0 waere eine stille Falschaussage - in Loxone sieht
# ein ausgefallener Wert dann aus wie ein echter Nullwert.
# ---------------------------------------------------------------------------
def zahl(wert, nachkomma: int = 0):
    if wert is None or wert == "":
        return None
    try:
        f = float(str(wert).replace(",", "."))
    except (TypeError, ValueError):
        return None
    # BEHOBEN 31.08.2026. int(round(f)) stand AUSSERHALB des try, und float()
    # nimmt drei Zeichenketten an, die int() nicht annimmt:
    #
    #     zahl("nan")   -> ValueError: cannot convert float NaN to integer
    #     zahl("inf")   -> OverflowError: cannot convert float infinity
    #     zahl("1e400") -> OverflowError
    #
    # Erreicht wurde das mit der ROHEN Nutzlast eines fremden MQTT-Themas
    # ueber Horcher.abfahrt_faellig(). Die Ausnahme verliess die Hauptschleife,
    # main() beendete den Dienst mit 1, soll_laufen blieb liegen, und
    # cron.01min holte ihn binnen 60 Sekunden in denselben Absturz zurueck -
    # mit einer neuen Anmeldung an der Skoda-Cloud je Runde. ESPHome
    # veroeffentlicht "nan" fuer einen Sensor ohne Wert; das ist kein Randfall.
    #
    # nan faellt auch mit nachkomma durch: round(nan, 3) ist nan, und
    # "nan > grenze" ist False - die Ladeempfehlung haette daraus ein
    # stilles "nicht empfohlen" gemacht statt "unbekannt".
    if not math.isfinite(f):
        return None
    return round(f, nachkomma) if nachkomma else int(round(f))


def hole(obj, *pfad):
    """Folgt einer Attributkette und gibt None zurueck, sobald ein Glied fehlt."""
    for name in pfad:
        if obj is None:
            return None
        obj = getattr(obj, name, None)
    return obj


def text(wert) -> str:
    """Ein Enum-Wert als Zeichenkette, ohne den Klassennamen davor."""
    if wert is None:
        return ""
    return str(getattr(wert, "value", wert))


def kennzahl(wert, tabelle: dict):
    """Zustand in eine Zahl fuer Loxone. Unbekannt bleibt None, nicht 0."""
    t = text(wert).upper()
    return tabelle.get(t)


def zeitstempel(wert):
    """datetime -> Unix-Zeit in Sekunden, sonst None."""
    if wert is None:
        return None
    try:
        return int(wert.timestamp())
    except (AttributeError, OSError, OverflowError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Fehlermeldungen, die sagen, wer geantwortet hat
#
# Der nackte Fehlertext einer Bibliothek hilft niemandem. ECONNREFUSED
# (erreichbar, aber nichts lauscht) bedeutet etwas voellig anderes als ein
# Zeitueberlauf (nichts antwortet) oder EHOSTUNREACH (kein Weg dorthin).
# ---------------------------------------------------------------------------
# Die Fehler, nach denen eine Neuanmeldung sinnvoll ist. AuthorizationFailedError
# gehoert dazu, obwohl er meist ein falsches Passwort bedeutet: die Bibliothek
# wirft ihn auch, wenn der Refresh-Weg abgewiesen wurde. Ein Versuch mit
# Benutzername und Passwort klaert das - und wenn der auch scheitert, steht der
# richtige Grund im Protokoll.
ANMELDEFEHLER = ("TokenExpiredError", "NotAuthorizedError",
                 "AuthorizationFailedError", "InvalidUrlError")


def ist_anmeldefehler(err: Exception) -> bool:
    if type(err).__name__ in ANMELDEFEHLER:
        return True
    status = getattr(err, "status", None)
    return status in (401, 403)


def anmeldung_vormerken(err: Exception) -> None:
    global _NEU_ANMELDEN
    if ist_anmeldefehler(err):
        _NEU_ANMELDEN = True


def fehlertext(err: Exception) -> str:
    name = type(err).__name__
    inhalt = str(err) or name
    klein = inhalt.lower()

    if isinstance(err, asyncio.TimeoutError) or name == "TimeoutError":
        return ("Zeitueberlauf: die Skoda-Cloud hat nicht geantwortet. Meist eine gestoerte "
                "Internetverbindung oder eine Stoerung beim Anbieter.")
    if name in ("TermsAndConditionsError",):
        return ("Skoda verlangt die Zustimmung zu neuen Nutzungsbedingungen. Einmal in der "
                "MySkoda-App anmelden und dort zustimmen, danach geht es hier weiter.")
    if name in ("MarketingConsentError",):
        return ("Skoda verlangt eine Angabe zur Werbeeinwilligung. Einmal in der MySkoda-App "
                "anmelden und die Abfrage beantworten.")
    if name in ("AuthorizationFailedError", "NotAuthorizedError"):
        return ("Anmeldung abgewiesen: Skoda-Benutzername oder Passwort stimmen nicht. Es sind "
                "die Zugangsdaten des MySkoda-Kontos, nicht die eines Haendlerportals.")
    if name == "TokenExpiredError":
        return ("Die gespeicherte Sitzung ist abgelaufen. Der Dienst meldet sich beim naechsten "
                "Versuch neu mit Benutzername und Passwort an.")
    if name == "BrandError":
        return "Das Konto gehoert nicht zur Marke Skoda."
    if name == "CSRFError":
        return ("Die Anmeldeseite von Skoda sah anders aus als erwartet. Das passiert, wenn "
                "Skoda den Anmeldevorgang umbaut - dann hilft nur eine neuere Fassung von myskoda.")

    grund = getattr(err, "os_error", None)
    errno = getattr(grund, "errno", None) if grund is not None else getattr(err, "errno", None)
    if errno == 111:
        return ("Verbindung abgewiesen (ECONNREFUSED): der Gegenstelle ist der Port bekannt, "
                "aber es lauscht nichts.")
    if errno == 113:
        return "Kein Weg zum Ziel (EHOSTUNREACH): Netzwerk und Standardroute des LoxBerry pruefen."
    if errno in (-2, -3):
        return "Namensaufloesung fehlgeschlagen: der DNS-Server des LoxBerry antwortet nicht."

    status = getattr(err, "status", None)
    if status == 429 or "429" in inhalt or "too many requests" in klein:
        return ("Die Skoda-Cloud hat wegen zu vieler Anfragen abgewiesen (429). Den Takt in den "
                "Einstellungen vergroessern; unter 5 Minuten ist erfahrungsgemaess zu dicht.")
    if status in (401, 403) or "401" in inhalt:
        return ("Die Skoda-Cloud hat die Anfrage nicht angenommen (nicht angemeldet oder keine "
                "Berechtigung). Zugangsdaten pruefen; bei S-PIN-pflichtigen Befehlen die S-PIN.")
    if status == 404:
        return ("Die Skoda-Cloud kennt diesen Abruf fuer dieses Fahrzeug nicht (404). Meist "
                "beherrscht das Fahrzeug die Funktion nicht.")
    if status and 500 <= int(status) < 600:
        return f"Die Skoda-Cloud meldet einen eigenen Fehler (HTTP {status}). Das liegt nicht am LoxBerry."
    if "<html" in klein or "<!doctype" in klein:
        return ("Es kam HTML statt JSON zurueck - geantwortet hat also ein vorgelagerter Dienst "
                "(Proxy, Portal, Fehlerseite), nicht die Skoda-Schnittstelle. Die Anmeldung "
                "selbst ist damit nicht der Fehler.")
    return f"{name}: {inhalt}"


# ---------------------------------------------------------------------------
# Abbilden der Antworten auf flache Felder
#
# Ein eigener Abschnitt je Endpunkt. Faellt ein Endpunkt aus, bleiben genau
# seine Felder leer - die uebrigen stehen weiter zur Verfuegung.
# ---------------------------------------------------------------------------
def abbild_info(info) -> dict:
    spec = hole(info, "specification")
    return {
        "name": str(hole(info, "name") or ""),
        "modell": str(hole(spec, "model") or ""),
        "modellname": info.get_model_name() if hasattr(info, "get_model_name") else "",
        "titel": str(hole(spec, "title") or ""),
        "baujahr": str(hole(spec, "model_year") or ""),
        "karosserie": text(hole(spec, "body")),
        "motorart": text(hole(spec, "engine", "type")),
        "leistung_kw": zahl(hole(spec, "engine", "power")),
        "hubraum_l": zahl(hole(spec, "engine", "capacity_in_liters"), 1),
        "getriebe": str(hole(spec, "gearbox", "type") or ""),
        "batterie_kwh": zahl(hole(spec, "battery", "capacity")),
        "ladeleistung_max_kw": zahl(hole(spec, "max_charging_power")),
        "kennzeichen": str(hole(info, "license_plate") or ""),
        "software": str(hole(info, "software_version") or ""),
        "zustand": text(hole(info, "state")),
    }


def abbild_reichweite(dr) -> dict:
    prim = hole(dr, "primary_engine_range")
    sek = hole(dr, "secondary_engine_range")
    return {
        "reichweite_km": zahl(hole(dr, "total_range_in_km")),
        "antrieb": text(hole(dr, "car_type")),
        "motorart_primaer": text(hole(prim, "engine_type")),
        "soc": zahl(hole(prim, "current_soc_in_percent")),
        "tank_prozent": zahl(hole(prim, "current_fuel_level_in_percent")),
        "reichweite_primaer_km": zahl(hole(prim, "remaining_range_in_km")),
        "motorart_sekundaer": text(hole(sek, "engine_type")),
        "soc_sekundaer": zahl(hole(sek, "current_soc_in_percent")),
        "tank_sekundaer_prozent": zahl(hole(sek, "current_fuel_level_in_percent")),
        "reichweite_sekundaer_km": zahl(hole(sek, "remaining_range_in_km")),
        "adblue_km": zahl(hole(dr, "ad_blue_range")),
    }


def abbild_laden(ch) -> dict:
    st = hole(ch, "status")
    se = hole(ch, "settings")
    return {
        "soc": zahl(hole(st, "battery", "state_of_charge_in_percent")),
        # Die Reichweite kommt hier in METERN. Sie wird in fahrzeug_abrufen()
        # umgerechnet, damit die Umrechnung an einer Stelle steht.
        "reichweite_batterie_km": None,
        "ladezustand": text(hole(st, "state")),
        "laedt": kennzahl(hole(st, "state"), LADEN_AN),
        "ladeleistung_kw": zahl(hole(st, "charge_power_in_kw"), 1),
        "ladetempo_kmh": zahl(hole(st, "charging_rate_in_kilometers_per_hour"), 1),
        "ladeart": text(hole(st, "charge_type")),
        "restzeit_min": zahl(hole(st, "remaining_time_to_fully_charged_in_minutes")),
        "ladegrenze": zahl(hole(se, "target_state_of_charge_in_percent")),
        "lademodus": text(hole(se, "preferred_charge_mode")),
        "strom_ac": text(hole(se, "max_charge_current_ac")),
        "schonladen": text(hole(se, "charging_care_mode")),
        "stecker_entriegeln": text(hole(se, "auto_unlock_plug_when_charged")),
        "am_gespeicherten_ort": ja_nein(hole(ch, "is_vehicle_in_saved_location")),
    }


def abbild_status(st) -> dict:
    ue = hole(st, "overall")
    de = hole(st, "detail")
    d = {
        "verriegelt": kennzahl(hole(ue, "locked"), VERRIEGELT),
        "tueren_verriegelt": kennzahl(hole(ue, "doors_locked"), VERRIEGELT),
        "tueren_offen": kennzahl(hole(ue, "doors"), OFFEN_ZU),
        "fenster_offen": kennzahl(hole(ue, "windows"), OFFEN_ZU),
        "licht_an": kennzahl(hole(ue, "lights"), AN_AUS),
        "motorhaube_offen": kennzahl(hole(de, "bonnet"), OFFEN_ZU),
        "kofferraum_offen": kennzahl(hole(de, "trunk"), OFFEN_ZU),
        "schiebedach_offen": kennzahl(hole(de, "sunroof"), OFFEN_ZU),
        "verriegelung_text": text(hole(ue, "locked")),
        "tueren_text": text(hole(ue, "doors")),
        "fenster_text": text(hole(ue, "windows")),
    }
    # Die Einzeltueren leitet die Bibliothek aus der Bildadresse ab. Das kann
    # scheitern; dann bleiben die Felder leer statt falsch.
    for feld, name in (("tuer_vorn_links", "left_front_door"),
                       ("tuer_vorn_rechts", "right_front_door"),
                       ("tuer_hinten_links", "left_back_door"),
                       ("tuer_hinten_rechts", "right_back_door")):
        try:
            wert = getattr(st, name)
            # 'int(...) or None' stand hier bis 0.9.12 - und 0 or None ergibt
            # None. Der Wert 0, also 'Tuer geschlossen', konnte damit nie
            # herauskommen; getroffen wurde der Normalzustand statt eines
            # Fehlwertes.
            d[feld] = int(getattr(wert, "value", wert))
        except Exception:  # noqa: BLE001 - eine unlesbare Bildadresse ist kein Grund abzubrechen
            d[feld] = None
    return d


def abbild_klima(ac) -> dict:
    return {
        "klima_zustand": text(hole(ac, "state")),
        "klima_an": kennzahl(hole(ac, "state"), KLIMA_AN),
        "zieltemperatur": zahl(hole(ac, "target_temperature", "temperature_value"), 1),
        "aussentemperatur": zahl(hole(ac, "outside_temperature", "temperature_value"), 1),
        "scheibe_vorn": kennzahl(hole(ac, "window_heating_state", "front"), AN_AUS),
        "scheibe_hinten": kennzahl(hole(ac, "window_heating_state", "rear"), AN_AUS),
        "kabel_verbunden": kennzahl(hole(ac, "charger_connection_state"), KABEL),
        "stecker_verriegelt": text(hole(ac, "charger_lock_state")),
        "waermequelle": text(hole(ac, "heater_source")),
        "sitzheizung_vorn_links": ja_nein(hole(ac, "seat_heating_activated", "front_left")),
        "sitzheizung_vorn_rechts": ja_nein(hole(ac, "seat_heating_activated", "front_right")),
        "ziel_erreicht_um": zeitstempel(hole(ac, "estimated_date_time_to_reach_target_temperature")),
    }


def abbild_position(pos) -> dict:
    d = {"breite": None, "laenge": None, "ort": "", "strasse": "", "adresse": ""}
    for p in (hole(pos, "positions") or []):
        if text(hole(p, "type")).upper() != "VEHICLE":
            continue
        d["breite"] = zahl(hole(p, "gps_coordinates", "latitude"), 6)
        d["laenge"] = zahl(hole(p, "gps_coordinates", "longitude"), 6)
        adr = hole(p, "address")
        if adr is not None:
            d["ort"] = str(hole(adr, "city") or "")
            d["strasse"] = " ".join(x for x in (str(hole(adr, "street") or ""),
                                                str(hole(adr, "house_number") or "")) if x)
            d["adresse"] = ", ".join(x for x in (d["strasse"], d["ort"]) if x)
        break
    return d


def abbild_gesundheit(he) -> dict:
    lampen = hole(he, "warning_lights") or []
    kategorien = []
    for w in lampen:
        k = text(hole(w, "category"))
        if k:
            kategorien.append(k)
    return {
        "kilometerstand": zahl(hole(he, "mileage_in_km")),
        "warnleuchten": len(lampen),
        "warnleuchten_text": ", ".join(kategorien),
    }


def abbild_wartung(ma) -> dict:
    r = hole(ma, "maintenance_report")
    return {
        "inspektion_tage": zahl(hole(r, "inspection_due_in_days")),
        "inspektion_km": zahl(hole(r, "inspection_due_in_km")),
        "oelservice_tage": zahl(hole(r, "oil_service_due_in_days")),
        "oelservice_km": zahl(hole(r, "oil_service_due_in_km")),
        "kilometerstand_wartung": zahl(hole(r, "mileage_in_km")),
    }


def ja_nein(wert):
    """Wahrheitswert als 1/0 - und ein fehlendes Feld als None.

    Bis 0.9.12 stand in abbild_verbindung() zweimal die kurze Form
    '1 if hole(...) else 0'. Fehlt das Feld in der Antwort, liefert hole()
    None, und daraus wurde eine 0 beziehungsweise - bei 'unreachable' mit
    umgedrehter Frage - eine 1: 'Fahrzeug erreichbar', obwohl es niemand
    wusste. Genau davor warnt dieses Skript an fuenf anderen Stellen. Dass
    'zuendung_an' drei Zeilen weiter sorgfaeltig behandelt war, zeigt, dass
    es ein Versehen war und keine Absicht.
    """
    if wert is None:
        return None
    return 1 if wert else 0


def abbild_verbindung(vs) -> dict:
    unerreichbar = hole(vs, "unreachable")
    return {
        "erreichbar": None if unerreichbar is None else (0 if unerreichbar else 1),
        "in_bewegung": ja_nein(hole(vs, "in_motion")),
        "zuendung_an": ja_nein(hole(vs, "ignition_on")),
    }


# ---------------------------------------------------------------------------
# Verlauf (Ladezustand beziehungsweise Tankfuellstand ueber den Tag)
# ---------------------------------------------------------------------------
def verlauf_anhaengen(nummer: int, soc, reichweite, tage: int, tank=None) -> None:
    """Eine Zeile je Messpunkt: ts;soc;reichweite;tank

    Die VIERTE Spalte ist mit 0.9.13 dazugekommen, und sie behebt einen
    Befund: bis dahin schrieb der Aufrufer 'soc, ersatzweise tank_prozent' in
    DIESELBE Spalte. Bei einem Hybrid, dessen Ladeabruf gelegentlich ausfaellt,
    standen Batterie- und Tankfuellstand damit in einer Spalte derselben Datei,
    und das Diagramm zeichnete beides als eine Linie.

    Aeltere Dateien mit drei Spalten bleiben lesbar; sk_verlauf_lesen() faengt
    die fehlende vierte ab.
    """
    if soc is None and tank is None:
        return
    ordner = PDATA / "verlauf"
    ordner.mkdir(parents=True, exist_ok=True)
    datei = ordner / f"fahrzeug{nummer}_{time.strftime('%Y%m%d')}.csv"
    marke = PDATA / f".verlauf_ts_{nummer}"
    letzte = 0
    try:
        letzte = int(marke.read_text())
    except (OSError, ValueError):
        pass
    if time.time() - letzte < 240:
        return
    try:
        with datei.open("a", encoding="utf-8") as f:
            f.write("%d;%s;%s;%s\n" % (
                int(time.time()),
                "" if soc is None else soc,
                "" if reichweite is None else reichweite,
                "" if tank is None else tank))
        marke.write_text(str(int(time.time())))
    except OSError:
        return
    verlauf_aufraeumen(tage)


def verlauf_aufraeumen(tage: int) -> None:
    """Alte Tagesdateien entfernen.

    Eigene Funktion, weil der Aufraeumlauf bis 0.9.12 am ENDE von
    verlauf_anhaengen() stand - hinter dem return fuer einen fehlenden
    Messwert. Ein Fahrzeug, das weder Ladezustand noch Tankfuellstand liefert,
    hinterliess damit Altdateien, die nie verschwanden.
    """
    ordner = PDATA / "verlauf"
    grenze = time.time() - tage * 86400
    for alt in ordner.glob("fahrzeug*_*.csv"):
        try:
            if alt.stat().st_mtime < grenze:
                alt.unlink()
        except OSError:
            pass
    # Die Markendateien der 240-Sekunden-Sperre wurden nie aufgeraeumt. Sie
    # sind winzig, aber sie bleiben fuer jede Fahrzeugnummer liegen, die es
    # einmal gab.
    for alt in PDATA.glob(".verlauf_ts_*"):
        try:
            if alt.stat().st_mtime < grenze:
                alt.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Horcher auf fremde MQTT-Themen
#
# Zwei Verwendungen, beide freiwillig und ab Werk aus:
#
#   Ladeempfehlung   Ein Thema mit einem Zahlenwert - Strompreis oder
#                    PV-Ueberschuss - wird gegen eine Grenze gehalten. Das
#                    Ergebnis ist ein 1/0-Feld EMPFEHLUNG. Das Plugin
#                    entscheidet NICHT, es empfiehlt: wer daraus eine
#                    Ladefreigabe macht, tut das in Loxone und sieht es dort.
#                    Ein Plugin, das von sich aus zu laden beginnt, weil ein
#                    fremdes Thema einen Wert getragen hat, waere eine
#                    Ueberraschung mit Stromrechnung.
#
#   Abfahrtszeit     Das Thema eines Abfahrts-Assistenten, Inhalt: Restminuten
#                    bis zur Abfahrt. Faellt der Wert unter den Vorlauf, wird
#                    die Klimatisierung EINMAL je Abfahrt angefordert. Das ist
#                    der einzige Weg, auf dem dieses Plugin von sich aus etwas
#                    schaltet - deshalb haengt er an einem eigenen Haken UND
#                    an 'steuerung_ein', und der Kasten in der Oberflaeche
#                    sagt es.
#
# NICHT AM GERAET ERPROBT. Hier gibt es weder Broker noch Fahrzeug; gemessen
# ist nur, dass ohne paho alles uebrige weiterlaeuft und der Selbsttest es
# sagt. Das steht auch in der Oberflaeche.
#
# paho-mqtt ist eine zusaetzliche Abhaengigkeit. Fehlt sie, laeuft alles
# uebrige unveraendert und der Selbsttest SAGT es - ein Bedienelement, dessen
# Wert nirgends ankommt, ist schlimmer als ein fehlendes.
# ---------------------------------------------------------------------------
class Horcher:
    """Haelt eine MQTT-Verbindung und merkt sich die letzten Werte."""

    def __init__(self):
        self.werte: dict[str, str] = {}
        self.klient = None
        self.themen: tuple = ()
        self.grund = ""
        self.verbunden = False
        self.abfahrt_erledigt = 0.0
        # Wann kam der Wert? ERGAENZT 31.08.2026.
        #
        # self.werte kannte bis dahin kein Alter. Ein einmal empfangener Wert
        # blieb fuer immer stehen und ging in jedem Takt als frische
        # EMPFEHLUNG nach Loxone - genau die Falle, gegen die
        # abbild_schreiben() beim Abruf ausdruecklich verteidigt ("Wuerde man
        # den Zeitstempel auffrischen, bliebe ALTER klein"). Und ohne Alter
        # laesst sich eine Flanke nicht von einem Pegel unterscheiden.
        self.empfangen: dict[str, float] = {}

    def moeglich(self) -> tuple[bool, str]:
        try:
            import paho.mqtt.client  # noqa: F401
            return (True, "")
        except ImportError:
            return (False, "Die Bibliothek paho-mqtt fehlt in der virtuellen Umgebung. "
                           "Ohne sie gibt es weder Ladeempfehlung noch Vorklimatisierung "
                           "zur Abfahrtszeit; alles uebrige arbeitet unveraendert.")

    def gewuenscht(self, cfg: dict) -> tuple:
        t = []
        if cfg.get("empf_thema"):
            t.append(str(cfg["empf_thema"]))
        if cfg.get("abfahrt_ein") and cfg.get("abfahrt_thema"):
            t.append(str(cfg["abfahrt_thema"]))
        return tuple(sorted(set(t)))

    def schliessen(self) -> None:
        if self.klient is not None:
            try:
                self.klient.loop_stop()
                self.klient.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self.klient = None
        self.themen = ()
        self.verbunden = False

    def pflegen(self, cfg: dict) -> None:
        """Verbindung auf- oder abbauen, je nach Konfiguration.

        Wird bei jedem Takt gerufen. Aendern sich die Themen, wird neu
        abonniert - Einstellungen sollen ohne Neustart wirken.
        """
        soll = self.gewuenscht(cfg)
        if not soll:
            self.schliessen()
            self.grund = ""
            return
        # Nicht nur "sind es dieselben Themen?", sondern auch "steht die
        # Verbindung noch?". Ohne die zweite Frage blieb ein Klient, der die
        # Verbindung verloren hatte, bis zum Dienstneustart liegen.
        if self.klient is not None and soll == self.themen and self.verbunden:
            return
        self.schliessen()
        ok, grund = self.moeglich()
        if not ok:
            self.grund = grund
            melde_gebremst("horcher_paho", grund, 86400)
            return
        import paho.mqtt.client as mq
        z = mqtt_zustand()
        broker = z.get("broker") or "127.0.0.1"
        try:
            port = int(z.get("brokerport") or 1883)
        except (TypeError, ValueError):
            port = 1883
        try:
            k = mq.Client()

            def merken(_c, _u, m):
                self.werte[m.topic] = m.payload.decode("utf-8", "replace").strip()
                self.empfangen[m.topic] = time.time()

            def verbunden(_c, _u, _f, _rc, *_a):
                # DER RUECKGABECODE WIRD GELESEN. Ergaenzt 31.08.2026.
                #
                # Bis 0.9.14 nahm dieser Rueckruf _rc entgegen und sah ihn nie
                # an: self.verbunden ging auf True, auch wenn der Broker die
                # Anmeldung gerade abgewiesen hatte (CONNACK 5, "nicht
                # autorisiert"). pflegen() benutzt genau dieses Merkmal als
                # Gesundheitspruefung - der Horcher galt also als gesund und
                # war auf nichts abonniert.
                #
                # "Laeuft" ist nicht "erreichbar", und "erreichbar" ist nicht
                # "angemeldet". Am Broker dieser Anlage ist das NICHT
                # nachgemessen; gemessen ist nur, dass der Code den Wert
                # bisher verwarf.
                if _rc:
                    self.verbunden = False
                    self.grund = (f"Der Broker {broker}:{port} hat die Anmeldung "
                                  f"abgewiesen (CONNACK {_rc}).")
                    melde_gebremst("horcher_connack", self.grund, 1800)
                    return
                # ABONNIERT WIRD HIER, NICHT NACH connect(). Behoben
                # 31.08.2026: paho baut die Verbindung ueber loop_start()
                # selbst wieder auf, fuehrt aber KEINEN Abonnementspeicher
                # (nachgelesen in paho-mqtt 2.1.0, Client.reconnect leert
                # _out_packet und sendet nur CONNECT). Nach einem
                # Broker-Neustart war der Klient deshalb verbunden und auf
                # nichts abonniert - schweigend, denn pflegen() prueft nur die
                # Themenliste, nie den Zustand. Ladeempfehlung und
                # Vorklimatisierung waren bis zum naechsten Dienstneustart tot.
                self.verbunden = True
                for th in self.themen or soll:
                    k.subscribe(th)

            k.on_message = merken
            k.on_connect = verbunden
            k.on_disconnect = lambda *_a, **_k: setattr(self, "verbunden", False)
            k.connect(broker, port, 30)
            k.loop_start()
        except Exception as err:  # noqa: BLE001
            self.grund = (f"Der Broker {broker}:{port} liess sich nicht erreichen "
                          f"({fehlertext(err)}).")
            melde_gebremst("horcher_verbindung", self.grund, 1800)
            self.klient = None
            return
        self.klient = k
        self.themen = soll
        self.grund = ""
        _LOG.info("Horcher: %s abonniert (%s:%d).", ", ".join(soll), broker, port)

    def empfehlung(self, cfg: dict):
        """1, 0 oder None - None heisst: es gibt hier keine Aussage.

        DAS ALTER ZAEHLT MIT. Ergaenzt 31.08.2026, und es ist die zweite
        Haelfte einer Korrektur, die halb liegengeblieben war: self.empfangen
        wurde am selben Tag eingefuehrt, ausdruecklich weil "ein einmal
        empfangener Wert fuer immer stehen blieb und in jedem Takt als frische
        EMPFEHLUNG nach Loxone ging" - benutzt hat ihn dann nur
        abfahrt_faellig(). Die EMPFEHLUNG, die im Kommentar als Opfer steht,
        rechnete weiter mit einem Wert von vorgestern.

        UND SIE VERSTUMMT NICHT, SIE SAGT 0. Ein virtueller Eingang behaelt
        seinen letzten Wert: bliebe die Empfehlung bei veraltetem Preis leer,
        stuende in Loxone weiter die 1, und die Anlage lade weiter, weil
        niemand mehr widersprochen hat. Nur wenn die Funktion gar nicht
        eingerichtet ist, gibt es keine Aussage (None).
        """
        thema = str(cfg.get("empf_thema") or "")
        if not thema or cfg.get("empf_grenze") == "":
            return None
        roh = self.werte.get(thema)
        if roh is None:
            return None
        grenze_alter = ganz(cfg.get("empf_alter"), VORGABEN["empf_alter"])
        if grenze_alter > 0:
            seit = time.time() - self.empfangen.get(thema, 0.0)
            if seit > grenze_alter:
                melde_gebremst(
                    "empf_alt",
                    f"Der letzte Wert auf '{thema}' ist {int(seit)} s alt "
                    f"(Grenze {grenze_alter} s). Die Ladeempfehlung geht als 0 "
                    f"hinaus, nicht als der alte Stand.", 3600)
                return 0
        wert = zahl(roh, 3)
        if wert is None:
            return None
        grenze = float(cfg["empf_grenze"])
        return 1 if ((wert < grenze) if cfg.get("empf_kleiner") else (wert > grenze)) else 0

    def abfahrt_faellig(self, cfg: dict) -> bool:
        """Ist es Zeit fuer die Vorklimatisierung? Hoechstens EINMAL je Abfahrt."""
        if not cfg.get("abfahrt_ein") or not cfg.get("abfahrt_thema"):
            return False
        thema = str(cfg["abfahrt_thema"])
        roh = self.werte.get(thema)
        if roh is None:
            return False
        rest = zahl(roh)
        if rest is None:
            return False
        vorlauf = ganz(cfg.get("abfahrt_vorlauf"), 20)
        if rest < 0 or rest > vorlauf:
            return False
        # EINE FLANKE, KEIN PEGEL. Behoben 31.08.2026.
        #
        # Bis hierher fiel abfahrt_erledigt nur zurueck, wenn der Wert das
        # Fenster wieder VERLIESS. Bleibt er darin stehen - bei 'retain' der
        # Normalfall, sobald der Abfahrtsassistent zuletzt eine 0 gesendet
        # hat -, griff nur noch die Stundensperre: gemessen fuenf Ausloesungen
        # in fuenf Stunden, also eine Klimatisierungsanforderung pro Stunde,
        # Tag und Nacht, ohne dass jemand abfaehrt.
        #
        # Massgeblich ist deshalb, ob seit der letzten Ausloesung ein NEUER
        # Wert eingetroffen ist. Ein behaltener Wert kommt beim Abonnieren
        # genau einmal an; danach schweigt das Thema, und es passiert nichts
        # mehr. Das ist dieselbe Lehre wie bei der DisSp-Falle in der
        # Beschattung: ein Pegel, der wie eine Flanke behandelt wird,
        # wiederholt sich fuer immer.
        if self.empfangen.get(thema, 0.0) <= self.abfahrt_erledigt:
            return False
        # Die Stundensperre bleibt als zweite Bremse stehen: sendet die
        # Gegenstelle im Minutentakt, waere jede Nachricht sonst eine Flanke.
        if time.time() - self.abfahrt_erledigt < 3600:
            return False
        self.abfahrt_erledigt = time.time()
        return True


_HORCHER = Horcher()


# ---------------------------------------------------------------------------
# Ladeprotokoll
#
# Je abgeschlossenem Ladevorgang eine Zeile. Der Dienst sieht 'laedt' und den
# Ladezustand ohnehin in jedem Takt; was fehlte, war das Buchfuehren. Ohne das
# beantwortet weder die Oberflaeche noch Loxone die einfachste Frage
# ueberhaupt: wann und wie lange hat das Auto zuletzt geladen.
#
# ERFASST WIRD NUR, WAS GEMESSEN IST. Die Energie wird NICHT aus SOC und
# Batteriekapazitaet hochgerechnet - eine solche Zahl saehe aus wie ein
# Messwert und waere geraten (Ladeverluste, Temperatur, tatsaechlich nutzbarer
# Anteil). Notiert werden Beginn, Ende, SOC von und bis, die hoechste
# beobachtete Ladeleistung und der Ort. Wer kWh braucht, rechnet selbst und
# weiss dann, dass er rechnet.
# ---------------------------------------------------------------------------
DATEI_LADUNGEN = PDATA / "ladungen.csv"
_LADEN_OFFEN: dict[str, dict] = {}


def ladung_buchen(nummer: str, f: dict) -> None:
    """Bei jedem Durchgang je Fahrzeug aufgerufen."""
    laedt = f.get("laedt")
    soc = f.get("soc")
    offen = _LADEN_OFFEN.get(nummer)

    if laedt == 1:
        if offen is None:
            _LADEN_OFFEN[nummer] = {
                "beginn": int(time.time()), "soc_von": soc, "kw_max": 0.0,
                "ort": f.get("adresse") or "", "vin": f.get("vin") or "",
            }
            offen = _LADEN_OFFEN[nummer]
        kw = f.get("ladeleistung_kw")
        if isinstance(kw, (int, float)) and kw > offen["kw_max"]:
            offen["kw_max"] = float(kw)
        if offen.get("soc_von") is None:
            offen["soc_von"] = soc
        return

    # laedt ist 0 oder None. None heisst UNBEKANNT - dann wird nichts
    # abgeschlossen: ein ausgefallener Ladeabruf ist kein Ladeende.
    if laedt != 0 or offen is None:
        return
    del _LADEN_OFFEN[nummer]
    dauer = int(time.time()) - offen["beginn"]
    if dauer < 120:
        # Zu kurz, um ein Ladevorgang zu sein. Meist ein Flackern im
        # Zustandsfeld zwischen zwei Abrufen.
        return
    try:
        DATEI_LADUNGEN.parent.mkdir(parents=True, exist_ok=True)
        neu = not DATEI_LADUNGEN.exists()
        with DATEI_LADUNGEN.open("a", encoding="utf-8") as h:
            if neu:
                h.write("beginn;ende;fahrzeug;vin;soc_von;soc_bis;dauer_min;kw_max;ort\n")
            h.write("%d;%d;%s;%s;%s;%s;%d;%s;%s\n" % (
                offen["beginn"], int(time.time()), nummer, offen["vin"],
                "" if offen["soc_von"] is None else offen["soc_von"],
                "" if soc is None else soc,
                dauer // 60,
                ("%.1f" % offen["kw_max"]) if offen["kw_max"] else "",
                str(offen["ort"]).replace(";", " ").replace("\n", " ")[:120]))
    except OSError as err:
        melde_gebremst("ladungen", f"Ladeprotokoll nicht schreibbar: {err}", 3600)


# ---------------------------------------------------------------------------
# Schreibbefehle aus der Warteschlange
#
# Der Loxone-Endpunkt legt hier eine JSON-Datei ab, der Dienst arbeitet sie ab
# und legt die Antwort daneben. Der Endpunkt selbst spricht NIE mit der Cloud.
# ---------------------------------------------------------------------------
def antwort_schreiben(kennung: str, ok: int, meldung: str, zusatz: dict | None = None) -> None:
    ORDNER_ANTWORTEN.mkdir(parents=True, exist_ok=True)
    d = {"ok": ok, "meldung": meldung, "ts": int(time.time())}
    if zusatz:
        d.update(zusatz)
    json_schreiben(ORDNER_ANTWORTEN / f"{kennung}.json", d)
    grenze = time.time() - 900
    # *.json UND *.json.tmp: json_schreiben() legt die Nebendatei unter
    # <kennung>.json.tmp an. Bricht der Dienst mitten im Schreiben ab, faengt
    # ein Muster auf "*.json" sie NIE ein, und sie bleibt fuer immer liegen.
    for alt in list(ORDNER_ANTWORTEN.glob("*.json")) + \
               list(ORDNER_ANTWORTEN.glob("*.json.tmp")):
        try:
            if alt.stat().st_mtime < grenze:
                alt.unlink()
        except OSError:
            pass
    # Und die Befehlsdateien, die niemand abgeholt hat. Der Endpunkt weigert
    # sich zwar einzureihen, wenn der Dienst nicht laeuft - aber zwischen
    # seiner PID-Pruefung und dem Ablegen liegt ein Augenblick, in dem der
    # Dienst anhalten kann.
    for alt in ORDNER_BEFEHLE.glob("*.json*"):
        try:
            if alt.stat().st_mtime < time.time() - 86400:
                alt.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Drei Bremsen gegen die Sperre der Skoda-Cloud
#
# Skoda weist zu haeufige Anfragen mit HTTP 429 ab, und wer im gleichen Takt
# weiter anklopft, verlaengert die Sperre. Bis 0.9.12 gab es keine einzige
# Bremse:
#
#   - 'abruf' umgeht die Steuerungssperre absichtlich und unterbricht die
#     Wartezeit. Eine Loxone-Logik mit einem Impuls je Sekunde erzeugte damit
#     3600 vollstaendige Cloud-Durchgaenge in der Stunde.
#   - 'wecken' sagt in der eigenen Antwort "Skoda erlaubt hoechstens dreimal
#     am Tag" - und zaehlte nicht mit.
#   - Beim Ueberschussladen liefert Loxone denselben Sollwert im Sekundentakt.
#
# Ein gebremster Befehl wird ABGEWIESEN und gemeldet, nicht stillschweigend
# verschluckt: ein Knopf, der wortlos nichts tut, schickt den Anwender auf die
# Suche nach einem Fehler, den es nicht gibt.
# ---------------------------------------------------------------------------
class Bremse:
    """Fuehrt Buch ueber abgesetzte Befehle. Lebt im Dienstprozess."""

    def __init__(self):
        self.letzte: dict[str, tuple[float, str]] = {}
        self.stunde: list[float] = []
        self.letzter_abruf = 0.0

    def _aufraeumen(self, jetzt: float) -> None:
        self.stunde = [t for t in self.stunde if t >= jetzt - 3600]

    def abruf_erlaubt(self, cfg: dict) -> tuple[bool, str]:
        abstand = ganz(cfg.get("abstand_abruf"), 60)
        if abstand <= 0:
            return (True, "")
        jetzt = time.time()
        rest = int(self.letzter_abruf + abstand - jetzt)
        if rest > 0:
            return (False, f"Der letzte Sofortabruf ist keine {abstand} s her - noch {rest} s. "
                           f"Die Wartezeit steht im Reiter Einstellungen; zu haeufige "
                           f"Anfragen weist Skoda mit HTTP 429 ab.")
        self.letzter_abruf = jetzt
        return (True, "")

    def befehl_erlaubt(self, cfg: dict, schluessel: str, wert_text: str) -> tuple[bool, str]:
        """Nur fragen, nichts buchen."""
        jetzt = time.time()
        self._aufraeumen(jetzt)
        entprellung = ganz(cfg.get("entprellung"), 20)
        if entprellung > 0 and schluessel in self.letzte:
            zeit, alt = self.letzte[schluessel]
            if alt == wert_text and jetzt - zeit < entprellung:
                return (False, f"Derselbe Befehl mit demselben Wert liegt weniger als "
                               f"{entprellung} s zurueck. Er wird nicht noch einmal gesendet.")
        hoechst = ganz(cfg.get("befehle_stunde"), 30)
        if hoechst > 0 and len(self.stunde) >= hoechst:
            return (False, f"In der letzten Stunde sind bereits {len(self.stunde)} Befehle "
                           f"abgesetzt worden - das ist die eingestellte Obergrenze. "
                           f"Skoda sperrt ein Konto, das zu oft schreibt.")
        return (True, "")

    def befehl_buchen(self, schluessel: str, wert_text: str) -> None:
        """Erst buchen, wenn der Befehl WIRKLICH hinausgegangen ist.

        Getrennt von befehl_erlaubt(), weil ein Befehl zwischen Frage und
        Absetzen noch an der Wertpruefung scheitern kann - "Zieltemperatur 35
        Grad liegt ausserhalb der Grenzen" darf kein Kontingent verbrauchen.
        """
        jetzt = time.time()
        self._aufraeumen(jetzt)
        self.stunde.append(jetzt)
        self.letzte[schluessel] = (jetzt, wert_text)


_BREMSE = Bremse()


def vin_waehlen(vins: list[str], nummer_oder_vin) -> str | None:
    """Nimmt entweder die laufende Nummer (1-basiert) oder die VIN selbst."""
    s = str(nummer_oder_vin or "").strip()
    if s.upper() in [v.upper() for v in vins]:
        for v in vins:
            if v.upper() == s.upper():
                return v
    try:
        n = int(s)
    except (TypeError, ValueError):
        # KEIN Rueckfall auf 1. Bis 0.9.12 stand hier n = 1, und damit landete
        # jede Eingabe, die weder Nummer noch bekannte VIN ist, bei Fahrzeug 1.
        # Gemessen an einem Konto mit zwei Fahrzeugen: eine fremde, aber
        # formal gueltige VIN passiert das Muster des Endpunkts und startete
        # dann die Klimatisierung im ERSTEN Auto. Der Endpunkt verbietet das
        # stille Zurechtbiegen drei Zeilen ueber seiner eigenen Musterpruefung
        # ausdruecklich; hier stand das Gegenteil.
        n = 0
    return vins[n - 1] if 1 <= n <= len(vins) else None


async def befehl_ausfuehren(ms, vins: list[str], cfg: dict, b: dict) -> tuple[int, str, dict]:
    """Rueckgabe: (ok, Meldung, Zusatzfelder).

    ok = 1 angenommen, 0 abgelehnt.

    Wichtig zur Wahrheit dieser Antwort: der Dienst laeuft ohne die
    Ereignisleitung (MQTT) der Bibliothek, weil die eine Firebase-Anmeldung
    braucht. Die Bibliothek wartet dann NICHT auf die Bestaetigung des
    Fahrzeugs. "Angenommen" heisst also: die Skoda-Cloud hat den Auftrag
    entgegengenommen - ob das Fahrzeug ihn ausfuehrt, zeigt erst der naechste
    Abruf. Deshalb steht das auch so in der Meldung.
    """
    aktion = str(b.get("aktion") or "")

    # DIE SPERRE STEHT VOR ALLEM, AUCH VOR 'abruf'. Berichtigt 31.08.2026.
    #
    # Bis 0.9.14 stand der abruf-Zweig DAVOR. Drei Stellen, zwei Wahrheiten:
    # der Miniserver-Endpunkt weist 'abruf' seit 0.9.13 ausdruecklich ab
    # (webfrontend/html/index.php), der Dienst liess ihn durch - und der
    # Reiter Test, der ueber sk_befehl_absetzen() einreiht, kam damit an der
    # Sperre vorbei, waehrend im selben Bild stand: "Die Knoepfe geben
    # deshalb eine Ablehnung zurueck."
    #
    # Es ist der Weg, ueber den laut dem Kommentar zur Bremse in 0.9.12 3600
    # vollstaendige Cloud-Durchgaenge in der Stunde entstanden sind. Wer den
    # Haken ausschaltet, will genau das nicht mehr.
    if not cfg.get("steuerung_ein"):
        return (0, "Die Steuerung ist ausgeschaltet. Reiter Einstellungen, "
                   "Haken 'Schreibende Befehle zulassen'.", {})

    if aktion == "abruf":
        erlaubt, grund = _BREMSE.abruf_erlaubt(cfg)
        if not erlaubt:
            return (0, grund, {})
        return (1, "Sofortabruf eingeplant.", {})

    if not vins:
        return (0, "Es ist noch kein Fahrzeug bekannt. Erst einen Abruf abwarten.", {})

    vin = vin_waehlen(vins, b.get("fahrzeug"))
    if vin is None:
        return (0, f"Fahrzeug '{b.get('fahrzeug')}' gibt es nicht. Bekannt sind {len(vins)} Fahrzeuge.", {})

    # Entprellung und Stundengrenze, EINMAL fuer alle schreibenden Befehle.
    # Der Schluessel traegt die VIN mit: derselbe Befehl an zwei Fahrzeuge ist
    # nicht derselbe Befehl.
    wert_text = f"{b.get('temp', '')}|{b.get('prozent', '')}"
    erlaubt, grund = _BREMSE.befehl_erlaubt(cfg, f"{aktion}@{vin}", wert_text)
    if not erlaubt:
        return (0, grund, {"vin": vin})

    nachsatz = " Die Cloud hat den Auftrag angenommen; ob das Fahrzeug ihn ausfuehrt, zeigt der naechste Abruf."

    if aktion == "klima_start":
        temp = zahl(b.get("temp"), 1)
        if temp is None:
            return (0, "Die Zieltemperatur fehlt oder ist keine Zahl.", {})
        lo, hi = cfg["temp_min"], cfg["temp_max"]
        if temp < lo or temp > hi:
            # Abweisen, nicht zurechtbiegen: ein still gekappter Sollwert
            # fuehrt zu einem Fahrzeug, das etwas anderes tut als angezeigt.
            return (0, f"Zieltemperatur {temp} Grad liegt ausserhalb der eingestellten Grenzen "
                       f"({lo} bis {hi} Grad). Grenzen im Reiter Einstellungen anpassen.", {})
        await ms.start_air_conditioning(vin, float(temp))
        return (1, f"Klimatisierung mit {temp} Grad angefordert." + nachsatz, {"temp": temp, "vin": vin})

    if aktion == "klima_stop":
        await ms.stop_air_conditioning(vin)
        return (1, "Klimatisierung aus angefordert." + nachsatz, {"vin": vin})

    if aktion == "zieltemperatur":
        temp = zahl(b.get("temp"), 1)
        if temp is None:
            return (0, "Die Zieltemperatur fehlt oder ist keine Zahl.", {})
        lo, hi = cfg["temp_min"], cfg["temp_max"]
        if temp < lo or temp > hi:
            return (0, f"Zieltemperatur {temp} Grad liegt ausserhalb der eingestellten Grenzen "
                       f"({lo} bis {hi} Grad).", {})
        await ms.set_target_temperature(vin, float(temp))
        return (1, f"Zieltemperatur {temp} Grad gesetzt." + nachsatz, {"temp": temp, "vin": vin})

    if aktion == "laden_start":
        await ms.start_charging(vin)
        return (1, "Laden starten angefordert." + nachsatz, {"vin": vin})

    if aktion == "laden_stop":
        await ms.stop_charging(vin)
        return (1, "Laden anhalten angefordert." + nachsatz, {"vin": vin})

    if aktion == "ladegrenze":
        p = zahl(b.get("prozent"))
        if p is None:
            return (0, "Der Prozentwert fuer die Ladegrenze fehlt oder ist keine Zahl.", {})
        if p < 50 or p > 100:
            # 50 bis 100 ist der Bereich, den die MySkoda-App anbietet.
            return (0, f"{p} % ist keine zulaessige Ladegrenze. Zulaessig sind 50 bis 100 %.", {})
        await ms.set_charge_limit(vin, int(p))
        return (1, f"Ladegrenze {p} % gesetzt." + nachsatz, {"prozent": p, "vin": vin})

    if aktion == "scheibe_ein":
        await ms.start_window_heating(vin)
        return (1, "Scheibenheizung ein angefordert." + nachsatz, {"vin": vin})

    if aktion == "scheibe_aus":
        await ms.stop_window_heating(vin)
        return (1, "Scheibenheizung aus angefordert." + nachsatz, {"vin": vin})

    if aktion == "lueftung_start":
        await ms.start_ventilation(vin)
        return (1, "Standlueftung ein angefordert." + nachsatz, {"vin": vin})

    if aktion == "lueftung_stop":
        await ms.stop_ventilation(vin)
        return (1, "Standlueftung aus angefordert." + nachsatz, {"vin": vin})

    if aktion == "wecken":
        # Skoda begrenzt das ausdruecklich; die Bibliothek schreibt "maximum
        # three times a day". Deshalb steht der Hinweis in der Antwort.
        await ms.wakeup(vin)
        return (1, "Weckruf gesendet (Skoda erlaubt hoechstens dreimal am Tag)." + nachsatz,
                {"vin": vin})

    return (0, f"Unbekannte Aktion '{aktion}'.", {})


async def warteschlange(ms, vins: list[str], cfg: dict) -> bool:
    """Arbeitet alle vorliegenden Befehle ab. True, wenn ein Sofortabruf
    angefordert wurde."""
    ORDNER_BEFEHLE.mkdir(parents=True, exist_ok=True)
    sofort = False
    # sorted() ueber die Dateinamen ist erst seit 0.9.13 eine Reihenfolge.
    # Bis dahin hiess die Datei nur nach bin2hex(random_bytes(8)) - reiner
    # Zufall. Zwei Befehle aus demselben Zyklus liefen mit halber
    # Wahrscheinlichkeit verkehrt herum: Loxone sendet laden_start, zwei
    # Sekunden spaeter laden_stop, ausgefuehrt wurde stop und dann start -
    # das Auto lud. sk_befehl_absetzen() stellt der Kennung jetzt die Zeit
    # voran (%d.%06d-), damit die Namensfolge die Zeitfolge ist.
    # EINE HARTE OBERGRENZE. Ergaenzt 31.08.2026.
    #
    # Diese Schleife hatte keine, und jeder Durchgang darf bis GRENZE_BEFEHL
    # dauern. Wer den Ordner - versehentlich oder nicht - mit tausend Dateien
    # fuellt, haelt den Dienst damit beliebig lange von seinem Abruf ab; die
    # Warteschlange laeuft im Sekundentakt, der Rest wartet also hoechstens
    # eine Sekunde. Die Zahl ist eine gewaehlte Schranke, keine Messung: mehr
    # als zwoelf Befehle auf einmal erzeugt keine Bedienung dieses Plugins -
    # es hat zwoelf Knoepfe.
    offen = sorted(ORDNER_BEFEHLE.glob("*.json"))
    if len(offen) > GRENZE_BEFEHLE_JE_LAUF:
        melde_gebremst("befehlsstau",
                       f"{len(offen)} Befehle liegen in der Warteschlange. Es werden "
                       f"{GRENZE_BEFEHLE_JE_LAUF} je Sekunde abgearbeitet, der Rest "
                       f"in den naechsten Laeufen.", 600)
    for datei in offen[:GRENZE_BEFEHLE_JE_LAUF]:
        b = json_lesen(datei)
        kennung = datei.stem
        try:
            datei.unlink()
        except OSError as err:
            # NICHT ausfuehren. Bis 0.9.12 wurde ein misslungenes unlink
            # verschluckt und der Befehl trotzdem abgesetzt - die Datei blieb
            # liegen, und diese Schleife laeuft im Sekundentakt. Aus einem
            # 'wecken' (Skoda erlaubt dreimal am Tag) wurde damit ein
            # Dauerbeschuss bis zum Handeingriff.
            melde_gebremst(f"unlink_{kennung}",
                           f"Befehlsdatei {datei.name} liess sich nicht entfernen ({err}) - "
                           f"der Befehl wird NICHT ausgefuehrt. Rechte auf "
                           f"{ORDNER_BEFEHLE} pruefen.", 300)
            continue
        if not b:
            antwort_schreiben(kennung, 0, "Befehlsdatei war leer oder unlesbar.")
            continue
        # Verfall. Ein Befehl, der lange genug liegt, ist kein Auftrag mehr,
        # sondern eine Ueberraschung: bis 0.9.12 gab es weder eine
        # Altersgrenze noch ein Aufraeumen, und ein klima_start, das bei
        # gestopptem Dienst eingereiht wurde, heizte das Auto beim naechsten
        # Start - auch am Folgetag.
        gueltig = b.get("gueltig_bis")
        if gueltig is None:
            # Aeltere Datei ohne das Feld: hilfsweise ueber das Alter der Datei.
            gueltig = ganz(b.get("ts"), 0) + VERFALL_BEFEHL
        if time.time() > ganz(gueltig, 0):
            alter = int(time.time() - ganz(b.get("ts"), 0))
            antwort_schreiben(kennung, 0,
                              f"Der Befehl ist verfallen - er lag {alter} s in der "
                              f"Warteschlange und wird nicht mehr ausgefuehrt.")
            _LOG.info("Befehl %s (%s) verfallen, Alter %s s.", kennung, b.get("aktion"), alter)
            continue
        try:
            # Mit Grenze: diese Schleife laeuft im Sekundentakt zwischen zwei
            # Abrufen. Ein haengender Befehl wuerde nicht nur sich selbst
            # aufhalten, sondern den ganzen Dienst - auch den naechsten Abruf.
            ok, meldung, zusatz = await asyncio.wait_for(
                befehl_ausfuehren(ms, vins, cfg, b), timeout=GRENZE_BEFEHL)
        except Exception as err:  # noqa: BLE001 - jeder Fehler gehoert gemeldet, nicht verschluckt
            # Auch hier vormerken: bis 0.9.12 meldete ein 401 auf einen
            # Schreibbefehl nur den Fehlschlag, ohne je eine Neuanmeldung
            # auszuloesen. Schreibbefehle scheiterten damit bis zum naechsten
            # Zufallstreffer der Stammdatenabfrage.
            anmeldung_vormerken(err)
            ok, meldung, zusatz = 0, fehlertext(err), {}
        # Gebucht wird genau hier: nach dem Absetzen, nur bei Erfolg, und nur
        # fuer die schreibenden Befehle - 'abruf' hat seine eigene Bremse.
        if ok == 1 and zusatz.get("vin"):
            _BREMSE.befehl_buchen(f"{b.get('aktion')}@{zusatz['vin']}",
                                  f"{b.get('temp', '')}|{b.get('prozent', '')}")
        antwort_schreiben(kennung, ok, meldung, zusatz)
        _LOG.info("Befehl %s (%s): ok=%s %s", kennung, b.get("aktion"), ok, meldung)
        if b.get("aktion") == "abruf" and ok:
            sofort = True
    return sofort


# ---------------------------------------------------------------------------
# Abruf eines Fahrzeugs
#
# Jeder Endpunkt einzeln abgesichert: faellt einer aus, bleiben die uebrigen
# Werte gueltig. Was ausgefallen ist, steht in "ausfaelle" - schweigend eine
# leere Antwort zu liefern waere schlimmer als ein benannter Fehler.
# ---------------------------------------------------------------------------
async def endpunkt(ausfaelle: dict, name: str, koro, grenze: int = GRENZE_ABRUF):
    try:
        return await asyncio.wait_for(koro, timeout=grenze)
    except Exception as err:  # noqa: BLE001
        ausfaelle[name] = fehlertext(err)
        anmeldung_vormerken(err)
        melde_gebremst(f"ep_{name}", f"Abruf '{name}' fehlgeschlagen: {ausfaelle[name]}", 900)
        return None


def kann(stamm: dict, kennung: str) -> bool:
    """Beherrscht das Fahrzeug diese Funktion?

    Ist die Faehigkeitsliste (noch) nicht bekannt, wird True zurueckgegeben -
    dann wird der Abruf versucht und ein Fehlschlag benannt. Andersherum
    (stillschweigend nichts abrufen) waere ein leeres Ergebnis ohne Grund.
    """
    liste = stamm.get("faehigkeiten")
    if not liste:
        return True
    return kennung in liste


async def fahrzeug_abrufen(ms, vin: str, stamm: dict, cfg: dict, zyklus: int) -> dict:
    ausfaelle: dict[str, str] = {}
    d: dict = {"vin": vin}

    if zyklus % cfg["takt_stamm"] == 0 or not stamm:
        info = await endpunkt(ausfaelle, "info", ms.get_info(vin))
        if info is not None:
            stamm.update(abbild_info(info))
            try:
                stamm["faehigkeiten"] = [text(c.id) for c in info.capabilities.capabilities]
            except AttributeError:
                stamm["faehigkeiten"] = []
    d.update(stamm)

    dr = await endpunkt(ausfaelle, "reichweite", ms.get_driving_range(vin))
    if dr is not None:
        d.update(abbild_reichweite(dr))

    st = await endpunkt(ausfaelle, "status", ms.get_status(vin))
    if st is not None:
        d.update(abbild_status(st))

    if kann(stamm, "CHARGING") or kann(stamm, "CHARGING_MEB") or kann(stamm, "CHARGING_MQB"):
        ch = await endpunkt(ausfaelle, "laden", ms.get_charging(vin))
        if ch is not None:
            laden = abbild_laden(ch)
            meter = hole(ch, "status", "battery", "remaining_cruising_range_in_meters")
            laden["reichweite_batterie_km"] = None if meter is None else zahl(int(meter) / 1000)
            # NUR gefuellte Felder uebernehmen. Behoben 31.08.2026:
            # abbild_laden() liefert den Schluessel "soc" IMMER, notfalls mit
            # None. Fehlt der Batteriezweig einer sonst gelungenen Ladeantwort,
            # loeschte d.update(laden) damit einen gueltigen Ladezustand aus
            # abbild_reichweite() - gemessen: soc fiel von 62 auf None. In
            # Loxone wurde daraus ein Strich, im Verlauf eine Luecke.
            # Dieselbe Form benutzen die beiden Zeilen fuer inspektion/
            # oelservice weiter unten schon.
            d.update({k: v for k, v in laden.items() if v is not None})

    if kann(stamm, "AIR_CONDITIONING"):
        ac = await endpunkt(ausfaelle, "klima", ms.get_air_conditioning(vin))
        if ac is not None:
            d.update(abbild_klima(ac))

    if kann(stamm, "PARKING_POSITION"):
        po = await endpunkt(ausfaelle, "position", ms.get_positions(vin))
        if po is not None:
            d.update(abbild_position(po))

    if kann(stamm, "VEHICLE_HEALTH_WARNINGS") or kann(stamm, "WARNING_LIGHTS"):
        he = await endpunkt(ausfaelle, "gesundheit", ms.get_health(vin))
        if he is not None:
            d.update(abbild_gesundheit(he))

    if zyklus % cfg["takt_wartung"] == 0:
        ma = await endpunkt(ausfaelle, "wartung", ms.get_maintenance(vin))
        if ma is not None:
            d.update(abbild_wartung(ma))
            stamm.update(abbild_wartung(ma))
        else:
            d.update({k: v for k, v in stamm.items() if k.startswith(("inspektion", "oelservice"))})
    else:
        d.update({k: v for k, v in stamm.items() if k.startswith(("inspektion", "oelservice"))})

    vs = await endpunkt(ausfaelle, "verbindung", ms.get_connection_status(vin))
    if vs is not None:
        d.update(abbild_verbindung(vs))

    # Steht das Auto zu Hause? Die Position wird ohnehin abgerufen; die
    # Entfernung selbst auszurechnen ist der Schritt, den sonst jeder in
    # Loxone von Hand nachbauen muss - und dort ist die Kugelrechnung
    # muehsam. Ohne eingetragene Heimkoordinaten bleiben beide Felder None
    # und damit am Endpunkt ein Strich; es wird nichts behauptet.
    d["heim_entfernung_m"] = entfernung_m(
        d.get("breite"), d.get("laenge"), cfg.get("heim_breite"), cfg.get("heim_laenge"))
    d["zuhause"] = (None if d["heim_entfernung_m"] is None
                    else (1 if d["heim_entfernung_m"] <= ganz(cfg.get("heim_radius"), 150) else 0))

    # Der Kilometerstand kommt aus dem Gesundheitsabruf. Beherrscht das
    # Fahrzeug den nicht - dann greift kann() weiter oben - oder faellt er aus,
    # stand bis 0.9.12 im Wartungs-Endpunkt und im MQTT-Thema ein Strich,
    # obwohl der Wert vorlag: der Wartungsabruf liefert ihn als
    # 'kilometerstand_wartung' mit, und das Feld wurde NIRGENDS gelesen.
    if d.get("kilometerstand") is None and d.get("kilometerstand_wartung") is not None:
        d["kilometerstand"] = d["kilometerstand_wartung"]

    d["ausfaelle"] = ausfaelle
    # Bis 0.9.12 stand hier eine absolute Schwelle: 'drei oder mehr Ausfaelle
    # heisst nicht ok'. Sie zaehlte, ohne zu wiegen. Ein Fahrzeug, das drei
    # Endpunkte dauerhaft mit 404 beantwortet, weil es sie nicht beherrscht,
    # machte damit das ganze Plugin unbrauchbar: ok=0 haelt den Zeitstempel an
    # (ALTER waechst unbegrenzt), unterdrueckt den Verlauf und schickt ueber
    # MQTT nur noch ok=0 - obwohl Ladezustand, Reichweite und Verriegelung
    # sauber ankamen.
    #
    # Massgeblich sind die beiden Endpunkte, die die Werte tragen, an denen
    # Loxone haengt, und die als einzige IMMER versucht werden (kann() schuetzt
    # sie nicht): 'reichweite' und 'status'. Fallen beide aus, ist nichts da,
    # was der Rede wert waere. Faellt nur einer aus, bleibt der andere gueltig.
    kern = [n for n in ("reichweite", "status") if n in ausfaelle]
    d["ok"] = 0 if len(kern) == 2 else 1
    d["ausfaelle_n"] = len(ausfaelle)
    return d


# ---------------------------------------------------------------------------
# Abbild schreiben
# ---------------------------------------------------------------------------
MQTT_FELDER = (
    "soc", "reichweite_km", "tank_prozent", "kilometerstand", "verriegelt",
    "tueren_offen", "fenster_offen", "licht_an", "kofferraum_offen",
    "motorhaube_offen", "klima_an", "zieltemperatur", "aussentemperatur",
    "scheibe_vorn", "scheibe_hinten", "laedt", "ladeleistung_kw", "restzeit_min",
    "ladegrenze", "kabel_verbunden", "breite", "laenge", "warnleuchten",
    "inspektion_tage", "inspektion_km", "oelservice_tage", "oelservice_km",
    "erreichbar", "in_bewegung", "zuendung_an",
    # Ergaenzt 0.9.13. Beide gibt der Lade-Endpunkt aus (TEMPO, REICHWBAT);
    # ueber MQTT waren sie bis dahin nicht zu bekommen - wer den MQTT-Weg
    # statt des Endpunkts nutzt, bekam sie also gar nicht.
    "ladetempo_kmh", "reichweite_batterie_km",
    # Und der Geofence, sofern eingerichtet.
    "zuhause", "heim_entfernung_m",
)

# Textthemen. Sie stehen getrennt, weil eine LEERE Nutzlast mit 'retain' ein
# behaltenes Thema loescht - ein leerer Text wird deshalb gar nicht gesendet.
MQTT_TEXTFELDER = (
    "modell", "kennzeichen", "ladezustand", "klima_zustand", "adresse",
    "warnleuchten_text",
)


def zaehler_naechster() -> int:
    """Eine Zahl, die bei jedem Durchgang um eins waechst und bei 1000 umlaeuft.

    Sie ueberlebt einen Neustart, weil sie in der Zustandsdatei steht - sonst
    saehe der Miniserver nach jedem Neustart des Dienstes eine 0 und koennte
    Stillstand nicht von Neubeginn unterscheiden.
    """
    z = ganz(json_lesen(DATEI_ZUSTAND).get("zaehler"), -1)
    return (z + 1) % 1000


def entfernung_m(b1, l1, b2, l2):
    """Luftlinie zwischen zwei Koordinaten in Metern, oder None.

    Haversine auf der Kugel mit 6371 km. Fuer die Frage "steht das Auto zu
    Hause" ist der Unterschied zum Ellipsoid bedeutungslos - er liegt bei
    wenigen Metern auf hundert Kilometern.
    """
    for w in (b1, l1, b2, l2):
        if w is None or w == "":
            return None
    try:
        # math steht im Kopf dieser Datei; der zweite Import hier war ein
        # Rest und hat nichts bewirkt.
        p1, p2 = math.radians(float(b1)), math.radians(float(b2))
        dp = p2 - p1
        dl = math.radians(float(l2) - float(l1))
        a = (math.sin(dp / 2) ** 2
             + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
        return int(round(2 * 6371000 * math.asin(min(1.0, math.sqrt(a)))))
    except (TypeError, ValueError, OverflowError):
        return None


def abbild_schreiben(stand: dict, cfg: dict, ok: int, fehler: str = "",
                     fehler_folge: int = 0, zaehler: int = 0, empfehlung=None) -> dict:
    """Schreibt den Zwischenspeicher.

    Wichtig: bei einem fehlgeschlagenen Abruf bleiben die zuletzt gueltigen
    Werte stehen, und der Zeitstempel wird NICHT aufgefrischt. Beides mit
    Absicht.

    Wuerde man die Werte loeschen, meldete der Endpunkt ploetzlich
    FAHRZEUG_UNBEKANNT, obwohl nur eine Anfrage schiefgegangen ist. Wuerde man
    den Zeitstempel auffrischen, bliebe ALTER klein - und genau daran haengt
    die Ausfallerkennung in Loxone. So waechst ALTER bei einer Stoerung
    weiter, und der Miniserver merkt sie.
    """
    fahrzeuge = stand.get("fahrzeuge") or {}
    lox = {
        "ok": ok,
        "fehler": fehler,
        "fehler_folge": int(fehler_folge),
        "zaehler": int(zaehler),
        "empfehlung": empfehlung,
        "letzter_versuch": int(time.time()),
        "anzahl_fahrzeuge": len(fahrzeuge),
        "fahrzeuge": fahrzeuge,
    }
    if stand.get("ts"):
        lox["ts"] = int(stand["ts"])
    json_schreiben(DATEI_LOXONE, lox)

    # Vollstaendiges Abbild fuer die Fehlersuche. Zugangsdaten stehen hier
    # nicht drin - die fuehrt die Bibliothek getrennt.
    # DER ZEITSTEMPEL IST DER DES STANDES, nicht der der Schreibung.
    # Bis 0.9.14 bekam cache.json in JEDEM Lauf ein frisches "ts" - auch bei
    # ok=0 und mit den ALTEN Fahrzeugwerten daneben. Drei Zeilen weiter oben
    # steht die Begruendung, warum genau das nicht sein darf. Wer die Datei
    # zur Fehlersuche aufschlaegt, liest sonst ein Alter, das es nicht gibt.
    json_schreiben(DATEI_CACHE, {"ts": int(stand.get("ts") or 0), "ok": ok,
                                 "geschrieben": int(time.time()),
                                 "fehler": fehler, "fahrzeuge": fahrzeuge})

    praefix = thema_saeubern(cfg.get("mqtt_topic"))
    retain = 1 if cfg.get("mqtt_retain") else 0

    # DAS LEBENSZEICHEN - immer, auch bei einer Stoerung.
    #
    # Ein virtueller Eingang behaelt seinen letzten Wert, mit Retain sogar
    # ueber jeden Neustart des Miniservers hinweg. Bis 0.9.12 ging bei einer
    # Stoerung nur "ok" hinaus, und ueber MQTT gab es weder Zeitstempel noch
    # Alter: ein reiner MQTT-Anwender konnte einen Ausfall grundsaetzlich
    # nicht erkennen. Auf dem HTTP-Weg leistet das ALTER; hier braucht es ts.
    #
    # Der ZAEHLER beantwortet, was der Zeitstempel nicht kann: ein Raspberry
    # ohne Echtzeituhr springt beim ersten Zeitabgleich, ein Alter kann danach
    # negativ oder stundenlang sein, obwohl alles laeuft. Eine umlaufende Zahl
    # nicht.
    #
    # status/dienst steht bewusst NICHT hier: ob der Dauerlaeufer laeuft, misst
    # der Cron-Lauf (skoda.py --wachzeichen). Ein Dienst, der seinen eigenen
    # Tod melden soll, ist der falsche Zeuge.
    lebenszeichen = {
        "status/ok": ok,
        "status/ts": int(stand.get("ts") or 0),
        "status/zaehler": int(zaehler),
        "status/fehler_folge": int(fehler_folge),
        "status/fehlertext": fehler if fehler else "-",
        # Die beiden alten Themen bleiben stehen: auf ihnen liegen in
        # bestehenden Anlagen virtuelle Eingaenge. Sie wegzunehmen waere eine
        # stille Aenderung an einer fremden Loxone-Konfiguration.
        "ok": ok,
        "fahrzeuge": len(fahrzeuge),
    }
    if empfehlung is not None:
        lebenszeichen["empfehlung"] = empfehlung
    if not ok:
        # Bei einer Stoerung nur das Lebenszeichen senden. Die alten Messwerte
        # erneut zu veroeffentlichen liesse sie frisch aussehen.
        if cfg.get("mqtt_ein"):
            versucht, schlecht = mqtt_senden(lebenszeichen, praefix, retain)
            lox["mqtt_versucht"], lox["mqtt_schlecht"] = versucht, schlecht
            json_schreiben(DATEI_LOXONE, lox)
        return lox

    try:
        verlauf_aufraeumen(cfg["verlauf_tage"])
    except (OSError, TypeError, ValueError):
        pass

    for nummer, f in fahrzeuge.items():
        try:
            ladung_buchen(str(nummer), f)
        except (TypeError, ValueError, KeyError) as err:
            melde_gebremst("ladung_buchen", f"Ladeprotokoll: {err}", 3600)
        try:
            verlauf_anhaengen(int(nummer), f.get("soc"), f.get("reichweite_km"),
                              cfg["verlauf_tage"], f.get("tank_prozent"))
        except (TypeError, ValueError):
            pass

    if cfg.get("mqtt_ein"):
        paare = dict(lebenszeichen)
        for nummer, f in fahrzeuge.items():
            for feld in MQTT_FELDER:
                paare[f"fahrzeug{nummer}/{feld}"] = f.get(feld)
            for feld in MQTT_TEXTFELDER:
                w = f.get(feld)
                if w is not None and str(w).strip() != "":
                    paare[f"fahrzeug{nummer}/{feld}"] = w
        versucht, schlecht = mqtt_senden(paare, praefix, retain)
        lox["mqtt_versucht"], lox["mqtt_schlecht"] = versucht, schlecht
        json_schreiben(DATEI_LOXONE, lox)

    return lox


def nummern_zuordnen(vins: list) -> dict:
    """Welche Fahrzeugnummer gehoert zu welcher VIN?

    ANGELEGT 01.09.2026. Bis dahin entstand die Nummer aus der POSITION in
    sorted(vins) - "fuer i, vin in enumerate(vins, start=1)". Das ist keine
    Adresse, sondern eine Reihenfolge: laesst die Skoda-Cloud voruebergehend
    die erste VIN weg (Wartung, Teilausfall, ein Wagen kurz aus dem Konto),
    rutscht das zweite Auto auf fahrzeug1. Es bekommt dann dieselben
    MQTT-Themen und dieselben virtuellen Eingaenge wie vorher der erste -
    und in Loxone steht der Ladezustand des einen Wagens unter dem Namen des
    anderen. Nichts daran meldet sich; die Zahlen sehen plausibel aus.

    Die Zuordnung liegt deshalb in zustand.json und ueberlebt einen Neustart
    wie ein Upgrade (preupgrade.sh rettet die Datei seit 0.9.15 neben den
    Ordner). Sie waechst nur: eine einmal vergebene Nummer wird nie neu
    vergeben, ein verschwundenes Fahrzeug behaelt seine.

    KEIN BRUCH FUER BESTEHENDE ANLAGEN: ist noch keine Zuordnung da, entsteht
    sie aus derselben sortierten Reihenfolge, die bisher galt. Der erste Lauf
    nach dem Update vergibt also genau die Nummern, die schon im Miniserver
    stehen.
    """
    z = json_lesen(DATEI_ZUSTAND)
    karte = z.get("vin_nummern")
    karte = {str(k): int(v) for k, v in karte.items()
             if isinstance(v, int) or (isinstance(v, str) and str(v).isdigit())} \
        if isinstance(karte, dict) else {}
    vergeben = set(karte.values())
    neu = False
    for vin in sorted(vins):
        if str(vin) in karte:
            continue
        n = 1
        while n in vergeben:
            n += 1
        karte[str(vin)] = n
        vergeben.add(n)
        neu = True
    if neu:
        zustand_schreiben(vin_nummern=karte)
    return karte


def zustand_schreiben(**felder) -> None:
    z = json_lesen(DATEI_ZUSTAND)
    z.update(felder)
    z["ts"] = int(time.time())
    json_schreiben(DATEI_ZUSTAND, z)


# ---------------------------------------------------------------------------
# Sitzung merken
#
# Skoda drosselt wiederholte Anmeldungen mit Benutzername und Passwort. Der
# Refresh-Token wird deshalb - nur auf Wunsch - in einer eigenen Datei mit
# Rechten 0600 abgelegt und beim naechsten Start zuerst versucht. Scheitert
# er, wird der normale Weg gegangen UND das gemeldet, damit aus dem Ersatzweg
# nicht unbemerkt der Normalfall wird.
# ---------------------------------------------------------------------------
def sitzung_lesen() -> str:
    d = json_lesen(DATEI_MARKE)
    return str(d.get("refresh_token") or "")


def sitzung_schreiben(token: str) -> None:
    json_schreiben(DATEI_MARKE, {"refresh_token": token, "ts": int(time.time())}, rechte=0o600)


def sitzung_loeschen() -> None:
    try:
        DATEI_MARKE.unlink()
    except OSError:
        pass


async def anmelden(ms, z: dict, cfg: dict) -> str:
    """Meldet an und gibt zurueck, welcher Weg gegangen wurde."""
    if cfg.get("sitzung_merken"):
        token = sitzung_lesen()
        if token:
            try:
                await asyncio.wait_for(ms.connect(refresh_token=token),
                                       timeout=GRENZE_ANMELDUNG)
            except Exception as err:  # noqa: BLE001
                _LOG.info("Gemerkte Sitzung nicht mehr gueltig (%s) - Anmeldung mit "
                          "Benutzername und Passwort.", fehlertext(err))
                sitzung_loeschen()
            else:
                # Den Schluessel ZURUECKSCHREIBEN, nicht nur benutzen.
                #
                # Bis 0.9.12 wurde sitzung_schreiben() ausschliesslich im Weg
                # ueber Benutzername und Passwort gerufen. Vergibt Skoda
                # einmalige Refresh-Token - UNGEMESSEN, hier gibt es kein
                # Konto -, taugte die gemerkte Sitzung dann nur fuer genau
                # einen Neustart, und der Dienst fiel danach immer auf das
                # Passwort zurueck. Womit die Drosselung, gegen die die
                # Funktion gebaut wurde, wieder greift.
                #
                # Der Rueckschreibversuch kostet einen Abruf und schadet auch
                # dann nicht, wenn der Token derselbe geblieben ist.
                try:
                    neuer = await asyncio.wait_for(ms.get_refresh_token(),
                                                   timeout=GRENZE_ABRUF)
                    if neuer and neuer != token:
                        sitzung_schreiben(neuer)
                        _LOG.info("Der Sitzungsschluessel wurde erneuert und gesichert.")
                except Exception as err:  # noqa: BLE001
                    _LOG.info("Sitzungsschluessel nicht erneuerbar: %s", fehlertext(err))
                return "gemerkte Sitzung"
    await asyncio.wait_for(ms.connect(email=z["email"], password=z["passwort"]),
                           timeout=GRENZE_ANMELDUNG)
    if cfg.get("sitzung_merken"):
        try:
            sitzung_schreiben(await asyncio.wait_for(ms.get_refresh_token(), timeout=GRENZE_ABRUF))
        except Exception as err:  # noqa: BLE001
            _LOG.info("Sitzung liess sich nicht merken: %s", fehlertext(err))
    return "Benutzername und Passwort"


# ---------------------------------------------------------------------------
# Dienst
# ---------------------------------------------------------------------------
def signal_behandeln(*_):
    global _LAUF
    _LAUF = False
    _LOG.info("Beendigungssignal erhalten - Dienst haelt an.")


async def dienst(einmal: bool = False) -> int:
    from aiohttp import ClientSession, ClientTimeout
    from myskoda import MySkoda

    cfg = config()
    z = zugang()

    _LOG.info("Dienst startet (Takt %s s, Steuerung %s).",
              cfg["intervall"], "ein" if cfg.get("steuerung_ein") else "aus")

    # Wartezeiten nach einer abgewiesenen Anmeldung, in Sekunden.
    #
    # WARUM DAS HIER STEHT UND NICHT IM WAECHTER: Bis 0.9.12 gab dienst() nach
    # einer gescheiterten Anmeldung 1 zurueck und der Prozess endete. Der
    # Sollmerker blieb liegen, cron.01min holte den Dienst binnen 60 Sekunden
    # zurueck, und der versuchte sofort wieder Benutzername und Passwort:
    # 1440 abgewiesene Anmeldeversuche am Tag, mit demselben falschen Passwort.
    # Die vorhandene Bremse "fehler_folge" half nicht - sie lebt nur innerhalb
    # eines Prozesses und stand nach jedem Neustart wieder auf 0.
    #
    # Der Dienst BLEIBT jetzt am Leben und wartet ansteigend. Damit sieht der
    # Waechter einen laufenden Prozess und startet nichts nach, die Oberflaeche
    # zeigt den Grund, und die Wartezeit ueberlebt, weil der Prozess sie
    # ueberlebt.
    ANMELDEWARTEN = (60, 300, 900, 1800, 3600)

    async with ClientSession(timeout=ClientTimeout(total=GRENZE_SITZUNG, connect=15)) as sitzung:
        # mqtt_enabled=False mit Absicht: die Ereignisleitung der Bibliothek
        # laeuft ueber Firebase Cloud Messaging und meldet dazu ein Geraet beim
        # Anbieter an. Fuer einen Dienst, der ohnehin im Takt abruft, ist das
        # unnoetig. Folge: Schreibbefehle warten nicht auf die Bestaetigung des
        # Fahrzeugs - das steht so in jeder Antwort.
        ms = MySkoda(sitzung, mqtt_enabled=False)

        async def anmelden_mit_geduld() -> bool:
            """Meldet an und wartet nach einem Fehlschlag ansteigend.

            Rueckgabe: True, wenn angemeldet. False nur, wenn der Dienst
            waehrend des Wartens beendet werden soll oder --einmal laeuft.
            """
            versuch = 0
            while _LAUF:
                # DER ZUGANG WIRD VOR JEDEM VERSUCH NEU GELESEN. Behoben
                # 31.08.2026. Bis 0.9.14 stand "z = zugang()" ein einziges
                # Mal vor der Schleife, und diese Funktion arbeitete mit der
                # geschlossenen Kopie weiter. Zusammen mit der ansteigenden
                # Wartezeit bis 3600 s hiess das: wer nach "Anmeldung
                # abgewiesen" das Passwort in der Oberflaeche berichtigte,
                # aenderte nichts - der Dienst klopfte bis zum naechsten
                # Neustart mit dem alten an. Die Konfiguration daneben wurde
                # laengst in jedem Takt neu gelesen, ausdruecklich damit
                # Aenderungen ohne Neustart ankommen; die Zugangsdaten sind
                # der Fall, in dem das am dringendsten gebraucht wird.
                z = zugang()
                if not z["email"] or not z["passwort"]:
                    # KEIN Abbruch mehr. Bis 0.9.14 gab dienst() hier 1
                    # zurueck, der Prozess endete, der Sollmerker blieb
                    # liegen - und cron.01min startete ihn binnen 60 Sekunden
                    # in denselben Abbruch: 1440 Starts am Tag, jeder mit
                    # einer Zeile im Protokoll. Das ist genau die Schleife,
                    # die der Kommentar oben fuer die ABGEWIESENE Anmeldung
                    # als behoben beschreibt; der FEHLENDE Zugang war
                    # uebersehen worden.
                    zustand_schreiben(ok=0, fehler="Zugangsdaten fehlen.")
                    melde_gebremst("zugang_fehlt",
                                   "Zugangsdaten fehlen. Reiter Einstellungen der "
                                   "Plugin-Oberflaeche oeffnen.", 3600)
                    if einmal:
                        return False
                    warten = ANMELDEWARTEN[min(versuch, len(ANMELDEWARTEN) - 1)]
                    versuch += 1
                    for _ in range(warten):
                        if not _LAUF:
                            return False
                        await asyncio.sleep(1)
                    continue
                try:
                    weg = await anmelden(ms, z, cfg)
                except Exception as err:  # noqa: BLE001
                    meldung = fehlertext(err)
                    zustand_schreiben(ok=0, fehler=meldung)
                    if einmal:
                        _LOG.error("Anmeldung fehlgeschlagen: %s", meldung)
                        return False
                    warten = ANMELDEWARTEN[min(versuch, len(ANMELDEWARTEN) - 1)]
                    versuch += 1
                    _LOG.error("Anmeldung fehlgeschlagen (%d. Versuch): %s "
                               "Naechster Versuch in %d s.", versuch, meldung, warten)
                    rest = warten
                    while rest > 0 and _LAUF:
                        await asyncio.sleep(1)
                        rest -= 1
                    continue
                _LOG.info("Angemeldet ueber %s.", weg)
                return True
            return False

        if not await anmelden_mit_geduld():
            return 1

        stammdaten: dict[str, dict] = {}
        vins: list[str] = []
        # Letzter gueltiger Stand. Bleibt bei einer Stoerung stehen, damit der
        # Endpunkt nicht ploetzlich "Fahrzeug unbekannt" meldet und damit ALTER
        # weiterwaechst - daran haengt die Ausfallerkennung in Loxone.
        stand: dict = {"ts": 0, "fahrzeuge": {}}
        zyklus = 0
        fehler_folge = 0
        # VOR der Schleife gesetzt, nicht nur darin. Trifft SIGTERM den
        # Dienst, waehrend die Anmeldung noch laeuft, wird der Rumpf der
        # Schleife nie betreten - und das abschliessende
        # 'return 0 if ok else 1' des --einmal-Laufs griff dann auf einen
        # ungebundenen Namen zu. Heraus kam ein UnboundLocalError, den
        # main() als 'Dienst abgebrochen' meldete: eine Fehlermeldung
        # ueber die falsche Ursache.
        ok = 0

        global _NEU_ANMELDEN
        while _LAUF:
            cfg = config()  # Aenderungen aus der Oberflaeche ohne Neustart uebernehmen
            beginn = time.time()
            ok = 0
            fehler = ""
            fahrzeuge: dict[str, dict] = {}
            _NEU_ANMELDEN = False
            try:
                if not vins or zyklus % cfg["takt_stamm"] == 0:
                    vins = sorted(await asyncio.wait_for(
                        ms.list_vehicle_vins(), timeout=GRENZE_ABRUF))
                nummern = nummern_zuordnen(vins)
                for vin in sorted(vins):
                    i = nummern.get(str(vin), 0)
                    if not i:
                        # Kann nur eintreten, wenn zustand.json nicht
                        # beschreibbar ist. Dann lieber gar keine Nummer als
                        # eine geratene: eine falsche Zuordnung schiebt die
                        # Werte des einen Wagens unter den Namen des anderen.
                        melde_gebremst("nummer_fehlt",
                                       f"Fuer {vin[-6:]} liess sich keine feste "
                                       f"Fahrzeugnummer vergeben (zustand.json nicht "
                                       f"beschreibbar?) - das Fahrzeug wird "
                                       f"uebersprungen.", 3600)
                        continue
                    # ANHALTEN WIRKT ZWISCHEN DEN FAHRZEUGEN. Ergaenzt
                    # 31.08.2026. Ein Fahrzeug kostet bis zu neun Endpunkte
                    # a GRENZE_ABRUF (30 s); bei zwei Wagen sind das im
                    # Stoerfall ueber acht Minuten. bin/dienst.sh wartet beim
                    # Anhalten 70 Sekunden und greift danach zu kill -9 -
                    # genau dem, was es vermeiden will, weil ein Befehl dabei
                    # spurlos verschwindet. Zwischen den Fahrzeugen
                    # auszusteigen kostet nichts und bringt die schlimmste
                    # Wartezeit auf die eines einzelnen Endpunkts herunter.
                    if not _LAUF:
                        break
                    stammdaten.setdefault(vin, {})
                    try:
                        fahrzeuge[str(i)] = await fahrzeug_abrufen(
                            ms, vin, stammdaten[vin], cfg, zyklus)
                    except Exception as err:  # noqa: BLE001
                        # Eigene Absicherung je Fahrzeug. Faellt eines mit
                        # einer Ausnahme AUSSERHALB von endpunkt() aus, verwarf
                        # das aeussere except bis 0.9.12 den ganzen Zyklus -
                        # auch die bereits erfolgreich abgerufenen Fahrzeuge.
                        anmeldung_vormerken(err)
                        _LOG.error("Fahrzeug %d (%s) uebersprungen: %s",
                                   i, vin[-6:], fehlertext(err))
                ok = 1 if fahrzeuge and any(f.get("ok") for f in fahrzeuge.values()) else 0
                if not vins:
                    fehler = "Das Konto fuehrt kein Fahrzeug."
                fehler_folge = 0 if ok else fehler_folge + 1
            except Exception as err:  # noqa: BLE001
                fehler = fehlertext(err)
                fehler_folge += 1
                melde_gebremst("abruf", f"Abruf fehlgeschlagen: {fehler}", 900)
                anmeldung_vormerken(err)

            # Die Neuanmeldung haengt jetzt am Merker, nicht am aeusseren
            # except - sie wird also auch ausgeloest, wenn der 401 an einem
            # einzelnen Endpunkt oder an einem Schreibbefehl aufgetreten ist.
            if _NEU_ANMELDEN and _LAUF:
                _NEU_ANMELDEN = False
                sitzung_loeschen()
                try:
                    weg = await anmelden(ms, z, cfg)
                    _LOG.info("Neu angemeldet ueber %s.", weg)
                except Exception as err2:  # noqa: BLE001
                    # Der Grund der NEUANMELDUNG ist der aussagekraeftige.
                    # Bis 0.9.1 blieb hier der alte Text stehen, und der
                    # Zustand meldete weiter "Sitzung abgelaufen", obwohl
                    # in Wahrheit das Passwort nicht mehr stimmte - man
                    # sucht dann an der falschen Stelle.
                    fehler = fehlertext(err2)
                    _LOG.error("Neuanmeldung fehlgeschlagen: %s", fehler)

            # DER STAND WIRD JE FAHRZEUG ZUSAMMENGEFUEHRT. Behoben 31.08.2026.
            #
            # Bis 0.9.14 stand hier "stand = {ts, fahrzeuge}" - der ganze Satz
            # wurde ersetzt. Zwei Folgen, beide still:
            #
            #  1. Faellt ein Fahrzeug mit einer Ausnahme AUSSERHALB von
            #     endpunkt() aus, wird sein Eintrag gar nicht erst gesetzt.
            #     Genuegte ein anderes Fahrzeug fuer ok=1, verschwand das
            #     ausgefallene aus loxone.json: anzahl_fahrzeuge sank, und der
            #     Endpunkt antwortete FAHRZEUG_UNBEKANNT statt OK=0.
            #  2. Liefert ein Fahrzeug nur sein eigenes ok=0 mit lauter
            #     Strichen, ueberschrieb dieser duenne Satz die zuletzt
            #     gemessenen Werte - genau das, was abbild_schreiben() drei
            #     Zeilen weiter als ausgeschlossen beschreibt.
            #
            # Und jedes Fahrzeug traegt jetzt seinen EIGENEN Zeitstempel. Das
            # 'ok' ist seit 0.9.12 je Fahrzeug; das Alter war es nicht, und
            # damit sah ein ausgefallenes Fahrzeug neben einem gesunden
            # weiterhin frisch aus.
            alt_f = dict(stand.get("fahrzeuge") or {})
            zusammen: dict[str, dict] = {}
            jetzt = int(time.time())
            for nr in sorted(set(list(alt_f.keys()) + list(fahrzeuge.keys())),
                             key=lambda s: (len(s), s)):
                neu = fahrzeuge.get(nr)
                if neu is not None and neu.get("ok"):
                    neu["ts"] = jetzt
                    zusammen[nr] = neu
                    continue
                # Kein Erfolg fuer dieses Fahrzeug: die zuletzt gueltigen
                # Werte bleiben stehen, aber sein ok geht auf 0 und sein
                # Zeitstempel wird NICHT aufgefrischt. Genau daran haengt die
                # Ausfallerkennung in Loxone.
                behalten = dict(alt_f.get(nr) or {})
                if not behalten:
                    behalten = dict(neu or {})
                if neu is not None:
                    # Was der Lauf ueber den Ausfall weiss, gehoert dazu.
                    for schluessel in ("ausfaelle", "ausfaelle_n", "vin"):
                        if schluessel in neu:
                            behalten[schluessel] = neu[schluessel]
                behalten["ok"] = 0
                zusammen[nr] = behalten
            if zusammen:
                stand = {"ts": jetzt if ok else stand.get("ts"),
                         "fahrzeuge": zusammen}
                if stand["ts"] is None:
                    stand.pop("ts")

            # Wurde der Durchgang durch ein Beendigungssignal abgebrochen,
            # wird NICHTS geschrieben. Ein halber Zyklus haette sonst ok=0
            # und damit in Loxone eine Stoerung gemeldet, wo nur jemand den
            # Dienst angehalten hat.
            if not _LAUF:
                break
            _HORCHER.pflegen(cfg)
            empfehlung = _HORCHER.empfehlung(cfg)
            zaehler = zaehler_naechster()
            abbild_schreiben(stand, cfg, ok, fehler, fehler_folge, zaehler, empfehlung)
            zustand_schreiben(ok=ok, fehler=fehler, zyklus=zyklus, fehler_folge=fehler_folge,
                              zaehler=zaehler, empfehlung=empfehlung,
                              horcher=_HORCHER.grund if _HORCHER.grund else "",
                              pid=os.getpid(), intervall=cfg["intervall"],
                              anzahl_fahrzeuge=len(stand["fahrzeuge"]))

            # Vorklimatisierung zur Abfahrtszeit. Der einzige Weg, auf dem
            # dieses Plugin von sich aus etwas schaltet - deshalb haengt er an
            # zwei Haken: dem eigenen UND der allgemeinen Steuerungsfreigabe.
            if (cfg.get("steuerung_ein") and vins
                    and _HORCHER.abfahrt_faellig(cfg)):
                try:
                    ok2, meldung2, _z2 = await asyncio.wait_for(
                        befehl_ausfuehren(ms, vins, cfg,
                                          {"aktion": "klima_start", "fahrzeug": "1",
                                           "temp": cfg.get("abfahrt_temp")}),
                        timeout=GRENZE_BEFEHL)
                    _LOG.info("Abfahrtszeit: Vorklimatisierung angefordert, ok=%s %s",
                              ok2, meldung2)
                except Exception as err:  # noqa: BLE001
                    _LOG.error("Abfahrtszeit: %s", fehlertext(err))
            zyklus += 1
            if einmal:
                # Nicht mit return heraus: bis 0.9.12 wurde damit
                # ms.disconnect() am Ende der Funktion uebersprungen, die
                # Abmeldung bei Skoda unterblieb also genau in dem Aufruf,
                # der zum Pruefen gedacht ist.
                break

            # Der Takt wird am BEGINN des Abrufs ausgerichtet, nicht an
            # seinem Ende. Bis 0.9.12 wurde "rest" erst nach dem Abruf gesetzt
            # und heruntergezaehlt; die tatsaechliche Zyklusdauer war Intervall
            # PLUS Abrufdauer plus die Dauer aller nebenher bearbeiteten
            # Befehle. Bei 300 s Vorgabe und 20 s Abruf waren es 320 s, bei
            # gestoerter Cloud auch 600 - waehrend Oberflaeche und Selbsttest
            # 300 nannten.
            rest = max(1, int(cfg["intervall"] - (time.time() - beginn)))
            if fehler_folge >= 3:
                rest = min(3600, cfg["intervall"] * min(8, fehler_folge))
                melde_gebremst("bremse",
                               f"{fehler_folge} Fehlversuche - naechster Abruf erst in {rest} s.",
                               1800)
            while rest > 0 and _LAUF:
                try:
                    if await warteschlange(ms, vins, cfg):
                        break  # Sofortabruf angefordert
                except Exception as err:  # noqa: BLE001
                    _LOG.error("Warteschlange: %s", fehlertext(err))
                await asyncio.sleep(1)
                rest -= 1

        _HORCHER.schliessen()
        try:
            await asyncio.wait_for(ms.disconnect(), timeout=GRENZE_ABRUF)
        except Exception:  # noqa: BLE001
            pass
    _LOG.info("Dienst beendet.")
    if einmal:
        return 0 if ok else 1
    return 0


# ---------------------------------------------------------------------------
# Wachzeichen - aufgerufen vom Minutencron, NICHT vom Dienst
#
# Der Hausstandard verlangt vier Lebenszeichen-Themen. Drei davon schickt der
# Dienst selbst (status/ok, status/ts, status/zaehler). Das vierte darf er
# nicht schicken: ob der Dauerlaeufer laeuft, MISST der Cron-Lauf - ein
# Dienst, der seinen eigenen Tod melden soll, ist der falsche Zeuge. Es gibt
# ueber den UDP-Eingang des Gateways auch keinen letzten Willen.
#
# Deshalb dieser eigene Aufruf. Er redet nicht mit der Cloud, meldet sich
# nirgends an und braucht keine Zugangsdaten - er liest die PID-Datei, prueft
# sie so streng wie dienst.sh und schickt eine einzige Zeile.
# ---------------------------------------------------------------------------
def dienst_laeuft() -> int:
    """1, wenn der Abrufdienst laeuft. Argumentweise geprueft wie in dienst.sh."""
    try:
        pid = int((PDATA / "dienst.pid").read_text().strip())
    except (OSError, ValueError):
        return 0
    if pid <= 0:
        return 0
    try:
        argv = (Path("/proc") / str(pid) / "cmdline").read_bytes().decode(
            "utf-8", "replace").split("\0")
    except OSError:
        return 0
    # Zwei Bedingungen, nicht eine: argv[1] ist genau unser Skript UND argv[0]
    # ist ein Python. Sonst gilt auch ein Editor mit geoeffneter skoda.py als
    # laufender Dienst.
    return 1 if (len(argv) > 1 and argv[1] == str(SELF / "skoda.py")
                 and re.search(r"(^|/)python[0-9.]*$", argv[0])) else 0


def wachzeichen() -> int:
    cfg = config()
    if not cfg.get("mqtt_ein"):
        return 0
    laeuft = dienst_laeuft()
    mqtt_senden({"status/dienst": laeuft},
                thema_saeubern(cfg.get("mqtt_topic")),
                1 if cfg.get("mqtt_retain") else 0)
    return 0


# ---------------------------------------------------------------------------
# Selbsttest - beantwortet ohne Netz und ohne Loxone, ob die Einrichtung traegt
# ---------------------------------------------------------------------------
def selbsttest() -> int:
    zeilen = []
    fehler = 0

    v = sys.version_info
    if v >= (3, 13):
        zeilen.append(f"[OK]   Python {v.major}.{v.minor}.{v.micro} (myskoda verlangt 3.13 oder neuer)")
    else:
        fehler += 1
        zeilen.append(f"[FEHL] Python {v.major}.{v.minor}.{v.micro} ist zu alt - "
                      f"myskoda ab 2.0.0 verlangt 3.13 oder neuer")

    venv = SELF / "venv" / "bin" / "python3"
    zeilen.append(f"[{'OK]  ' if venv.exists() else 'FEHL]'} Virtuelle Umgebung: {venv}")
    if not venv.exists():
        fehler += 1

    try:
        import importlib.metadata as md
        from myskoda import MySkoda  # noqa: F401
        try:
            fassung = md.version("myskoda")
        except Exception:  # noqa: BLE001
            fassung = "unbekannt"
        zeilen.append(f"[OK]   Bibliothek myskoda geladen, Fassung {fassung}")
    except Exception as err:  # noqa: BLE001
        fehler += 1
        zeilen.append(f"[FEHL] Bibliothek myskoda laesst sich nicht laden: {err}")

    for name, pfad in (("Konfiguration", PCONFIG), ("Daten", PDATA), ("Log", PLOG)):
        schreibbar = os.access(pfad, os.W_OK) if pfad.exists() else False
        zeilen.append(f"[{'OK]  ' if schreibbar else 'FEHL]'} Ordner {name} beschreibbar: {pfad}")
        if not schreibbar:
            fehler += 1

    z = zugang()
    # Ein Pruefknopf darf die FORM eines Geheimnisses beurteilen, nie seinen Wert zeigen.
    if z["email"] and "@" in z["email"]:
        zeilen.append(f"[OK]   Skoda-Benutzername hinterlegt ({z['email'][:2]}...@..., "
                      f"{len(z['email'])} Zeichen)")
    elif z["email"]:
        fehler += 1
        zeilen.append("[FEHL] Der Skoda-Benutzername sieht nicht wie eine E-Mail-Adresse aus")
    else:
        fehler += 1
        zeilen.append("[FEHL] Kein Skoda-Benutzername hinterlegt")
    if z["passwort"]:
        zeilen.append(f"[OK]   Passwort hinterlegt ({len(z['passwort'])} Zeichen, "
                      f"Inhalt wird nicht angezeigt)")
    else:
        fehler += 1
        zeilen.append("[FEHL] Kein Passwort hinterlegt")
    # Die Zeile ueber die S-PIN ist mit 0.9.11 entfallen: das Plugin hat
    # sie nie benutzt, und ein Selbsttest, der ueber ein unbenutztes
    # Geheimnis Auskunft gibt, laesst es wichtig aussehen.
    try:
        rechte = oct(DATEI_ZUGANG.stat().st_mode & 0o777)
        passt = (DATEI_ZUGANG.stat().st_mode & 0o077) == 0
        zeilen.append(f"[{'OK]  ' if passt else 'FEHL]'} Rechte der Zugangsdatei: {rechte} "
                      f"(erwartet 0o600)")
        if not passt:
            fehler += 1
    except OSError:
        fehler += 1
        zeilen.append(f"[FEHL] Zugangsdatei fehlt: {DATEI_ZUGANG}")

    if DATEI_MARKE.exists():
        try:
            r = DATEI_MARKE.stat().st_mode & 0o777
            passt = (r & 0o077) == 0
            zeilen.append(f"[{'OK]  ' if passt else 'FEHL]'} Rechte der gemerkten Sitzung: "
                          f"{oct(r)} (erwartet 0o600)")
            if not passt:
                fehler += 1
        except OSError:
            pass

    c = config()
    zeilen.append(f"[INFO] Takt {c['intervall']} s, Stammdaten alle {c['takt_stamm']} Takte, "
                  f"Wartung alle {c['takt_wartung']} Takte")
    zeilen.append(f"[INFO] Schreibende Befehle: "
                  f"{'zugelassen' if c.get('steuerung_ein') else 'gesperrt'}, "
                  f"Zieltemperatur erlaubt von {c['temp_min']} bis {c['temp_max']} Grad")
    zeilen.append(f"[INFO] Bremsen: Sofortabruf hoechstens alle {c['abstand_abruf']} s, "
                  f"{c['befehle_stunde']} schreibende Befehle je Stunde, "
                  f"Entprellung {c['entprellung']} s")
    if c.get("heim_breite") == "" or c.get("heim_laenge") == "":
        zeilen.append("[INFO] Kein Heimatort eingetragen - die Felder ZUHAUSE und "
                      "HEIMENTF bleiben leer")
    else:
        zeilen.append(f"[OK]   Heimatort {c['heim_breite']}, {c['heim_laenge']}, "
                      f"Radius {c['heim_radius']} m")
    # Ein Takt, der die Sperre der Gegenstelle herausfordert, gehoert benannt.
    if c["intervall"] < 300 or c["takt_stamm"] < 4:
        zeilen.append(f"[FEHL] Takt {c['intervall']} s bei Stammdaten alle {c['takt_stamm']} "
                      f"Takte: neun Endpunkte je Fahrzeug in dieser Dichte fuehren zu "
                      f"HTTP 429. Unter 5 Minuten ist erfahrungsgemaess zu dicht.")
        fehler += 1

    # ZUERST der eigene Haken. Bis 0.9.12 pruefte diese Stelle ausschliesslich
    # das LoxBerry-Gateway; cfg['mqtt_ein'] - der Schalter, der bestimmt, ob
    # DIESES Plugin ueberhaupt sendet - wurde nirgends abgefragt. Bei
    # ausgeschaltetem Haken stand hier eine gruene MQTT-Zeile mit Broker und
    # UDP-Port, obwohl kein einziges Thema veroeffentlicht wurde. Ein Haken,
    # der etwas bestaetigt, das nicht geschieht, ist schlimmer als keiner.
    if c.get("mqtt_ein"):
        zeilen.append(f"[OK]   Dieses Plugin sendet ueber MQTT, Themenpraefix "
                      f"'{c.get('mqtt_topic')}'"
                      + (", Werte werden behalten (retain)" if c.get("mqtt_retain")
                         else ", ohne retain"))
    else:
        zeilen.append("[INFO] Dieses Plugin sendet NICHT ueber MQTT - der Haken im Reiter "
                      "MQTT ist aus. Die folgende Zeile beschreibt nur das Gateway.")

    m = mqtt_zustand()
    if not m["gefunden"]:
        zeilen.append("[FEHL] Im general.json des LoxBerry ist kein MQTT-Abschnitt zu finden")
        fehler += 1
    elif m["autostart"]:
        zeilen.append(f"[OK]   MQTT-Gateway auf Autostart, Broker {m['broker']}:{m['brokerport']}, "
                      f"UDP-Eingang {m['udpport']}")
    else:
        zeilen.append("[FEHL] Das MQTT-Gateway ist nicht auf Autostart gestellt "
                      "(System -> MQTT Gateway). Ohne das kommt am Miniserver nichts an.")
        fehler += 1

    if c.get("empf_thema") or (c.get("abfahrt_ein") and c.get("abfahrt_thema")):
        moeglich, grund = _HORCHER.moeglich()
        if moeglich:
            zeilen.append("[OK]   paho-mqtt ist vorhanden - der Horcher kann sich mit dem "
                          "Broker verbinden")
        else:
            zeilen.append("[FEHL] " + grund)
            fehler += 1
        if c.get("empf_thema"):
            zeilen.append(f"[INFO] Ladeempfehlung: Thema '{c['empf_thema']}', empfohlen wenn "
                          f"der Wert {'kleiner' if c.get('empf_kleiner') else 'groesser'} "
                          f"{c.get('empf_grenze')} ist")
        if c.get("abfahrt_ein"):
            zeilen.append(f"[INFO] Abfahrtszeit: Thema '{c.get('abfahrt_thema')}', "
                          f"{c['abfahrt_vorlauf']} min Vorlauf, {c['abfahrt_temp']} Grad"
                          + ("" if c.get("steuerung_ein")
                             else " - WIRKUNGSLOS, solange schreibende Befehle gesperrt sind"))
    else:
        zeilen.append("[INFO] Kein fremdes MQTT-Thema abonniert (Ladeempfehlung und "
                      "Abfahrtszeit sind aus)")

    if DATEI_LADUNGEN.exists():
        try:
            n = max(0, sum(1 for _ in DATEI_LADUNGEN.open(encoding="utf-8")) - 1)
        except OSError:
            n = 0
        zeilen.append(f"[INFO] Ladeprotokoll: {n} abgeschlossene Ladevorgaenge in "
                      f"{DATEI_LADUNGEN}")
    else:
        zeilen.append("[INFO] Ladeprotokoll: noch kein abgeschlossener Ladevorgang")

    lox = json_lesen(DATEI_LOXONE)
    if lox:
        alter = int(time.time()) - ganz(lox.get("ts"), 0)
        zeilen.append(f"[INFO] Letzter Abruf vor {alter} s, ok={lox.get('ok')}, "
                      f"{lox.get('anzahl_fahrzeuge')} Fahrzeug(e)")
        for nummer, f in (lox.get("fahrzeuge") or {}).items():
            aus = f.get("ausfaelle") or {}
            zeilen.append(f"[INFO] Fahrzeug {nummer}: {f.get('modell') or 'ohne Namen'}, "
                          f"{len(aus)} ausgefallene Abrufe"
                          + (": " + ", ".join(sorted(aus)) if aus else ""))
    else:
        zeilen.append("[INFO] Es hat noch kein Abruf stattgefunden")

    zeilen.append("")
    zeilen.append("Nicht geprueft, weil dafuer ein Skoda-Konto und ein Fahrzeug noetig sind:")
    zeilen.append("  - ob die Anmeldung an der Skoda-Cloud gelingt")
    zeilen.append("  - ob dieses Fahrzeug die abgefragten Endpunkte ueberhaupt beantwortet")
    zeilen.append("  - ob die schreibenden Befehle am Fahrzeug die erwartete Wirkung haben")
    zeilen.append("  - ob Ladeempfehlung und Abfahrtszeit am Broker wirklich ankommen")
    print("\n".join(zeilen))
    return 1 if fehler else 0


def main() -> int:
    # Der Umlauf gehoert dem Dauerlaeufer allein - siehe log_einrichten().
    # Selbsttest und Minutencron haengen nur an.
    kurzlaeufer = "--selbsttest" in sys.argv or "--wachzeichen" in sys.argv
    log_einrichten(dauerlaeufer=not kurzlaeufer)
    if "--selbsttest" in sys.argv:
        return selbsttest()
    if "--wachzeichen" in sys.argv:
        return wachzeichen()
    signal.signal(signal.SIGTERM, signal_behandeln)
    signal.signal(signal.SIGINT, signal_behandeln)
    try:
        return asyncio.run(dienst(einmal="--einmal" in sys.argv))
    except KeyboardInterrupt:
        return 0
    except Exception as err:  # noqa: BLE001
        _LOG.error("Dienst abgebrochen: %s", fehlertext(err))
        zustand_schreiben(ok=0, fehler=fehlertext(err))
        return 1


if __name__ == "__main__":
    sys.exit(main())
