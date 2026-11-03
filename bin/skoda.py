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
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path


def lb_wurzel_ermitteln():
    """Den LoxBerry-Wurzelordner ohne festen Systempfad bestimmen.

    Vom eigenen (aufgeloesten) Ablageort aufwaerts, bis ein Verzeichnis
    gefunden ist, das config/plugins, data/plugins UND
    config/system/general.json enthaelt - dieselbe Suche wie in bin/dienst.sh.
    Bis 0.9.23 genuegten config/plugins und webfrontend; das trifft auf einem
    Pruefrechner auch Reste frueherer Pruefstaende (Regeln/06, der
    Raumklima-Vorfall: dort traf die Suche das Laufwerk selbst). Ein LoxBerry
    hat immer config/system/general.json.
    """
    d = os.path.dirname(os.path.realpath(__file__))
    for _ in range(8):
        if os.path.isdir(os.path.join(d, "config", "plugins")) \
                and os.path.isdir(os.path.join(d, "data", "plugins")) \
                and os.path.isfile(os.path.join(d, "config", "system", "general.json")):
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


def _pname_ermitteln() -> str:
    """Der Ordnername: $LBPPLUGINDIR, sonst der Ablageort.

    Bis 0.9.23 stand hier "PNAME = SELF.name" - aus einem Pruefarchiv unter
    <Wurzel>/pruefung/skodaconnect/bin heraus hiess der Ordner damit "bin",
    und PDATA zeigte auf data/plugins/bin der laufenden Anlage (in WSL
    gemessen, Pruefung-Skoda-Connect-NG-0.9.24, Fall Y3).
    Am Geraet steht $LBPPLUGINDIR in keiner Cron-Schale (Regeln/03); dann
    traegt der Ablageort, und bei einer regulaeren Installation ist das
    richtig. Dieselbe Abstufung wie in bin/dienst.sh.
    """
    p = (os.environ.get("LBPPLUGINDIR") or "").rstrip("/").rsplit("/", 1)[-1]
    return p or SELF.name


PNAME = _pname_ermitteln()


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

    GELESEN, NICHT GERATEN - berichtigt 24.09.2026 (0.9.24).

    Bis 0.9.23 stand der Ablageort (SELF.parents[2]) VOR der Umgebung: sah
    das Verzeichnis drei Ebenen hoeher wie eine Wurzel aus, wurde ein
    gesetztes $LBHOMEDIR uebergangen. Aus einem Pruefarchiv unter
    <Wurzel>/pruefung/skodaconnect/bin traf das die LAUFENDE Installation,
    zusammen mit PNAME = "bin"; "skoda.py --selbsttest" legte dort
    log/plugins/bin an (in WSL gemessen, Pruefung-Skoda-Connect-NG-0.9.24,
    Faelle Y1 und Y3; Bauart H1 aus Bestand-2026-09-18/klasse-H).

    Zwei Stufen, wie in bin/dienst.sh (Regeln/03, Stufe 1 ist die Umgebung):
      1. $LBHOMEDIR, wenn es config/plugins und data/plugins traegt,
      2. aufwaerts suchen (lb_wurzel_ermitteln(), drei Bedingungen).
    EINE DRITTE STUFE GIBT ES NICHT: der alte Rueckfall auf drei Ebenen ueber
    dem Ablageort machte in einem fremden Baum wieder eine Wurzel aus dem, was
    die Suche eben abgelehnt hatte (Stand-Protokolle/2026-09-18_Welle1, "Neue
    Lehre fuer alle H1-Linien"). Ohne Wurzel wird gemeldet und abgebrochen.
    """
    umgebung = os.environ.get("LBHOMEDIR") or ""
    if umgebung and os.path.isdir(os.path.join(umgebung, "config", "plugins")) \
            and os.path.isdir(os.path.join(umgebung, "data", "plugins")):
        # aufgeloest wie SELF, sonst stuenden fuer dieselbe Datei zwei
        # Schreibweisen nebeneinander (Wurzel als Verweis)
        return Path(umgebung).resolve()
    gesucht = lb_wurzel_ermitteln()
    if gesucht:
        return Path(gesucht)
    sys.stderr.write(
        "FEHLER: Es wurde kein LoxBerry-Wurzelverzeichnis gefunden. "
        "LBHOMEDIR bezeichnet keines, und oberhalb von %s traegt kein "
        "Verzeichnis config/plugins, data/plugins und "
        "config/system/general.json. Es wurde nichts angelegt.\n" % SELF)
    raise SystemExit(1)


LBHOME = _lb_wurzel()
# Liegt diese Datei im bin-Ordner der Anlage - oder ist <PNAME> dort
# wenigstens ein eingerichtetes Plugin? Sonst ist es ein Pruefaufruf aus einem
# ausgepackten Archiv oder einem Pruefordner, und angelegt wird nichts
# (log_einrichten()). Dieselbe Gegenprobe wie in bin/dienst.sh.
#
# Bis 0.9.23 stand hier LBHOME_ECHT - eine Groesse, die KEINE Zeile dieser
# Datei je gelesen hat, obwohl der Kommentar darueber versprach, main() breche
# damit ab. Gelesen 24.09.2026.
INSTALLIERT = (SELF == (LBHOME / "bin" / "plugins" / PNAME).resolve()
               or (LBHOME / "config" / "plugins" / PNAME).is_dir())
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
# Legt der Dauerlaeufer an, sobald die Bibliotheken geladen sind. bin/dienst.sh
# wartet beim Start darauf - siehe dort, starten().
DATEI_BEREIT = PDATA / "dienst.bereit"
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
    # Seit 0.9.21 ab Werk EIN - Hausstandard (Regeln/07): Zustaende werden
    # behalten. Welche Themen trotzdem fluechtig bleiben, entscheidet
    # MQTT_OHNE_RETAIN je Thema, nicht dieser Schalter.
    "mqtt_retain": 1,
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
    # Nr. 36 b (seit 0.9.30): Ansageanlaesse - dieselben Schluessel und Werte wie in
    # sk_vorgaben(). Der Block tts gehoert der Bruecke (bin/sk_ansage.php).
    "ansage_laden_fertig": 1,
    "ansage_laden_abbruch": 1,
    "ansage_offen": 1,
    "ansage_licht": 1,
    "ansage_klima": 1,
    "ansage_ausfall": 1,
    # --- Gruppe 41 (0.9.34): Hausform - dieselben Werte wie in sk_vorgaben(), alles ab Werk aus ---
    "befehle_mqtt_ein": 0,
    "endpunkt_ein": 0,
    # B5: Fahrzeug fuer die Vorklimatisierung (bis 0.9.33 fest "1").
    "abfahrt_fahrzeug": 1,
    # Haus-Themen (Regeln/07 Nr. 15) ueber die Dauerverbindung des Horchers.
    "haus_abfahrt_ein": 0,
    "vorklima_anwesend_ein": 0,
    "vorklima_wetter_ein": 0,
    "vorklima_kalt_unter": 5,
    "vorklima_heiss_ueber": 25,
    "ankunft_ein": 0,
    "ankunft_quelle": "",
    "haus_strompreis_ein": 0,
    # Zweite Quelle der Ladeempfehlung: "thema" (wie bisher) oder "haus" (haus/strompreis/aktuell).
    "ladeempf_quelle": "thema",
    # Meldungen an SignalBot (E9): Hauptschalter aus, je Ereignis abwaehlbar.
    "signal_ein": 0,
    "signal_praefix": "signalbot",
    "signal_laden_fertig": 1,
    "signal_laden_abbruch": 1,
    "signal_offen": 1,
    "signal_ausfall": 1,
    "signal_vorklima": 1,
    # Sammelthemen und Kabel-Warnung (0.9.36, Regeln/07): dieselben Werte wie die PHP-Vorgaben.
    "haus_fahrzeug_ein": 1,
    "kabel_soc": 30,
    "kabel_uhr": "20:00",
    "kabel_abfahrt_min": 60,
    "signal_kabel": 1,
    "vorklima_min_soc": 20,
    "vorklima_nur_kabel": 0,
    "ansage_kabel_vergessen": 1,
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
            "empf_kleiner", "abfahrt_ein",
            "ansage_laden_fertig", "ansage_laden_abbruch", "ansage_offen",
            "ansage_licht", "ansage_klima", "ansage_ausfall",
            # Gruppe 41 (0.9.34)
            "befehle_mqtt_ein", "endpunkt_ein", "haus_abfahrt_ein", "vorklima_anwesend_ein",
            "vorklima_wetter_ein", "ankunft_ein", "haus_strompreis_ein", "signal_ein",
            "signal_laden_fertig", "signal_laden_abbruch", "signal_offen", "signal_ausfall",
            "signal_vorklima",
            # 0.9.36
            "haus_fahrzeug_ein", "signal_kabel", "vorklima_nur_kabel", "ansage_kabel_vergessen")

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


class WachsameRotation(RotatingFileHandler):
    """Umlaufender Protokollhandler, der eine geloeschte Datei neu oeffnet.

    `log/plugins` liegt auf einer Ramdisk (zram). Wird sie geleert, raeumt
    LoxBerrys `log_maint` auf, oder loescht jemand die Datei von Hand, dann
    schreibt ein einmal geoeffneter Handler bis zum Prozessende in einen
    Inode, den es nicht mehr gibt - ohne Fehlermeldung, ohne Datei, ohne
    Hinweis. Am Geraet gemessen (06.09.2026, Python 3.13.5): FileHandler und
    RotatingFileHandler verlieren die Zeile, WatchedFileHandler nicht.

    Die Standardbibliothek hat den WatchedFileHandler, aber nicht zusammen
    mit dem Umlauf. Deshalb hier beides: vor jeder Zeile Geraetenummer und
    Inode vergleichen, bei Abweichung neu oeffnen, nach jedem Umlauf die
    Kennung nachfuehren.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._kennung = self._kennung_lesen()

    def _kennung_lesen(self):
        """(Geraetenummer, Inode) der Datei - None, wenn es sie nicht gibt."""
        try:
            s = os.stat(self.baseFilename)
        except OSError:
            return None
        return (s.st_dev, s.st_ino)

    def _nachfassen(self):
        """Neu oeffnen, wenn unter dem offenen Deskriptor eine andere (oder
        gar keine) Datei mehr liegt."""
        if self._kennung_lesen() == self._kennung:
            return
        if self.stream is not None:
            try:
                self.stream.flush()
            finally:
                self.stream.close()
                self.stream = None
        self.stream = self._open()
        self._kennung = self._kennung_lesen()

    def emit(self, record):
        try:
            self._nachfassen()
        except Exception:
            # Ein Fehlschlag beim Nachfassen darf die Zeile nicht kosten:
            # lieber in den alten Deskriptor schreiben als gar nicht.
            pass
        super().emit(record)

    def doRollover(self):
        super().doRollover()
        self._kennung = self._kennung_lesen()


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

    Angelegt wird der Protokollordner nur in der Anlage (INSTALLIERT). Aus
    einem Pruefarchiv heraus fehlt er dann, der FileHandler scheitert, und
    geschrieben wird nach stderr (Faelle Y1, Y2, Y4a).
    """
    if INSTALLIERT:
        PLOG.mkdir(parents=True, exist_ok=True)
    _LOG.setLevel(logging.INFO)
    try:
        h = (WachsameRotation(DATEI_LOG, maxBytes=512000, backupCount=1,
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
    # Gruppe 41 (0.9.34): dieselben Grenzen wie sk_regeln(); unzulaessig -> Vorgabe, nie gekappt.
    c["abfahrt_fahrzeug"] = in_grenzen(c.get("abfahrt_fahrzeug"), 1, 99, 1)
    c["vorklima_kalt_unter"] = in_grenzen(c.get("vorklima_kalt_unter"), -30, 45, 5)
    c["vorklima_heiss_ueber"] = in_grenzen(c.get("vorklima_heiss_ueber"), -30, 45, 25)
    # 0.9.36: Kabel-Warnung, Mindest-Akku
    c["kabel_soc"] = in_grenzen(c.get("kabel_soc"), 1, 100, 30)
    c["kabel_abfahrt_min"] = in_grenzen(c.get("kabel_abfahrt_min"), 0, 720, 60)
    c["vorklima_min_soc"] = in_grenzen(c.get("vorklima_min_soc"), 0, 100, 20)
    if c.get("ladeempf_quelle") not in ("thema", "haus"):
        c["ladeempf_quelle"] = "thema"
    if not re.match(r"^[A-Za-z0-9_-]{1,40}$", str(c.get("signal_praefix") or "")):
        c["signal_praefix"] = "signalbot"
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
        # Die Zugangsdaten des Brokers. Sie standen hier nie, und deshalb
        # konnte der Horcher sie auch nicht setzen.
        "brokeruser": str(m.get("Brokeruser", m.get("brokeruser", ""))),
        "brokerpass": str(m.get("Brokerpass", m.get("brokerpass", ""))),
    }


# Themen, die NIE behalten werden - entschieden ueber den Teil hinter dem
# letzten Schraegstrich, damit dieselbe Liste fuer status/..., die alten
# Themen oben und fahrzeugN/... gilt. Alles andere ist ein Zustand und geht
# bei eingeschaltetem Haken mit 'retain' hinaus. Muss zu sk_mqtt_ohne_retain()
# in webfrontend/html/sk_lib.php passen; der Reiter Test vergleicht beide.
#
# Hausstandard seit 03.09.2026 (Regeln/07), Einteilung wie VolkswagenID 0.9.20:
MQTT_OHNE_RETAIN = frozenset((
    # Lebenszeichen - nie. status/ok und das alte Thema ok sagen "der letzte
    # Durchgang hat gemessen", status/ts und status/zaehler wann und dass es
    # weitergeht, status/dienst kommt vom Minutencron.
    "ok", "ts", "zaehler", "dienst",
    # Messwerte mit Zeitbezug: Leistung, Tempo, Restzeit, Temperatur
    "ladeleistung_kw", "ladetempo_kmh", "restzeit_min", "aussentemperatur",
    # Aus einem mitgehoerten Preis oder Ueberschuss gerechnet - ein
    # behaltenes "1" empfaehle nach einem Ausfall mit dem Preis von gestern.
    "empfehlung",
    # Aussagen des Dienstes ueber sich selbst - nie (Regeln/07 Abschnitt 3,
    # Entscheidungen des Hausherrn 18./19.09.2026). Bis 0.9.23 gingen
    # status/fehler_folge und status/fehlertext bei "Werte behalten" retained
    # hinaus, auch im Stoerungszweig: stirbt der Dienst nach der Erholung,
    # stehen "0" und "-" fuer immer im Broker. Gemessen 24.09.2026,
    # Pruefung-Skoda-Connect-NG-0.9.24, messe_retain.sh, R1a/R1b/R4b. Der
    # Altwert wird einmal abgeraeumt - mqtt_altlast_abraeumen().
    "fehler_folge", "fehlertext",
    # Gruppe 41 (0.9.34): Zustand der Vorklimatisierung - eine Dienstaussage.
    "vorklima",
    # Nachtrag 4 (29.10.2026): Restminuten der Klimatisierung - eine Restzeit, nie behalten.
    "klima_restzeit_min",
))

# Die Themen OBERHALB von fahrzeugN/, die dieser Dienst sendet: der Block
# 'lebenszeichen' in abbild_schreiben(), 'empfehlung' dort, 'status/dienst'
# aus wachzeichen(). Zusammen mit fahrzeugN/<MQTT_FELDER, MQTT_TEXTFELDER>
# ist das alles, was mqtt_eigenes_thema() als eigen erkennt - und nur das
# raeumen der Dienst und die Deinstallation ab. Wer oben ein Thema dazunimmt,
# traegt es hier ein; sonst bleibt es nach der Deinstallation im Broker
# stehen (Pruefung-Skoda-Connect-NG-0.9.25, messe_nachlese.sh, Fall U1a).
MQTT_OBEN = (
    "status/ok", "status/ts", "status/zaehler", "status/fehler_folge",
    "status/fehlertext", "status/dienst", "ok", "fahrzeuge", "empfehlung",
)

# Die ALTLAST: jedes eigene Thema, das mqtt_ohne_retain() heute fluechtig
# nennt, das aber frueher behalten hinausging. Zwei Herkuenfte, beide gelesen:
#   - bis 0.9.20 galt der Haken "Werte behalten" fuer JEDES Thema
#     (LoxBerry-Plugin-Skoda-Connect-NG-0.9.20/bin/skoda.py:701,
#     befehl = "retain" if retain else "publish"): status/ok, ok, status/ts,
#     status/zaehler, status/dienst, empfehlung und die Messwerte mit
#     Zeitbezug. 0.9.21 stellte sie auf fluechtig und raeumte nie ab.
#   - bis 0.9.23 status/fehler_folge und status/fehlertext.
# Ein fluechtiges publish ersetzt einen behaltenen Wert nicht; fort ist er
# erst, wenn eine LEERE Nutzlast mit retain auf dasselbe Thema faellt.
# Abgeraeumt wird am Broker, nicht ueber den UDP-Eingang - siehe
# mqtt_altlast_abraeumen(). Der Merker 'retain_altlast' in zustand.json traegt
# diese Kennung, das Praefix und die Liste der fluechtigen Namen; den Merker
# 'retain_geraeumt' einer Vorfassung liest niemand mehr.
RETAIN_ALTLAST_KENNUNG = "am-broker-nachgelesen"


# Rueckgabecodes einer abgewiesenen MQTT-Verbindung. 1-5 aus MQTT 3.1.1,
# 132-136 die gleichbedeutenden Reason Codes aus MQTT 5.
CONNACK_KLARTEXT = {
    1: "der Broker kennt diese Protokollfassung nicht",
    2: "die Client-Kennung wurde abgelehnt",
    3: "der Broker steht gerade nicht zur Verfuegung",
    4: "Benutzername oder Passwort sind falsch - sie stehen unter System -> MQTT Gateway",
    5: "nicht berechtigt - Benutzer und Passwort unter System -> MQTT Gateway pruefen",
    132: "der Broker kennt diese Protokollfassung nicht",
    133: "die Client-Kennung wurde abgelehnt",
    134: "Benutzername oder Passwort sind falsch - sie stehen unter System -> MQTT Gateway",
    135: "nicht berechtigt - Benutzer und Passwort unter System -> MQTT Gateway pruefen",
    136: "der Broker steht gerade nicht zur Verfuegung",
}


def mqtt_ohne_retain(schluessel: str) -> bool:
    """Gehoert dieses Thema zu denen, die NICHT behalten werden?"""
    return str(schluessel).rsplit("/", 1)[-1] in MQTT_OHNE_RETAIN


def mqtt_senden(paare: dict, praefix: str, retain: int = 0) -> tuple[int, int]:
    """Veroeffentlicht die Paare ueber den UDP-Eingang des Gateways.

    Rueckgabe: (versucht, misslungen). Bis 0.9.12 gab die Funktion nichts
    zurueck und meldete nur gebremst ins Protokoll - eine Zahl in der
    Oberflaeche beantwortet dagegen die Frage, ob ueberhaupt etwas hinausgeht,
    auch dann, wenn das Gateway gar nicht eingerichtet ist.

    'retain' laesst das Gateway die Werte behalten. BERICHTIGT IN 0.9.21.
    Bis 0.9.20 stand hier, das Befehlswort sei an einem laufenden Gateway nie
    nachgemessen, und der Schalter galt fuer JEDES Thema - das Lebenszeichen
    eingeschlossen. Beides stimmt nicht mehr: der UDP-Eingang des Gateways V1
    nimmt 'retain' an (am Geraet dieses Hauses gemessen 13./14.09.2026,
    Regeln/07), und der Hausstandard verlangt die Entscheidung JE THEMA:
    Zustaende behalten, Messwerte mit Zeitbezug nicht, das Lebenszeichen nie.
    Ein behaltenes status/ts zeigte nach einem Ausfall "lebt", und eine
    behaltene Ladeleistung einen Ladevorgang, der laengst vorbei ist. Welche
    Themen fluechtig bleiben, steht in MQTT_OHNE_RETAIN.
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
            # Bis 0.9.24 ging hier fuer die Altwerte ein leeres "retain"
            # voraus, und der Aufrufer setzte seinen Merker, sobald sendto()
            # nicht scheiterte. Der UDP-Eingang verwirft aber in Stoessen
            # 17-70 % der Datagramme (Regeln/07, Nachtrag 19.09.2026, am
            # Geraet gemessen) - der Altwert blieb dann trotz Merker stehen
            # (in WSL gemessen 24.09.2026, Pruefung-Skoda-Connect-NG-0.9.25,
            # Fall A3). Abgeraeumt wird jetzt am Broker:
            # mqtt_altlast_abraeumen().
            # Je Thema entschieden, nicht je Aufruf: derselbe Aufruf traegt
            # Lebenszeichen und Zustand. Ist der Haken aus, geht alles ohne.
            befehl = "retain" if (retain and not mqtt_ohne_retain(k)) else "publish"
            try:
                s.sendto(f"{befehl} {praefix}/{k} {text}".encode("utf-8"),
                         ("127.0.0.1", z["udpport"]))
            except OSError:
                schlecht += 1
            # 5 ms ABSTAND (M7, Durchgang 01.10.2026). Der UDP-Eingang des
            # Gateways verwarf am Geraet ohne Pause bis zu 6 von 90 Datagrammen,
            # mit 5 ms keines (Regeln/07, Fensterbilanz 16.09.2026); gemessen
            # waren hier 87 Datagramme in 5,3 ms.
            time.sleep(0.005)
    except OSError as err:
        melde_gebremst("mqtt_senden", f"MQTT: Senden fehlgeschlagen ({err}).")
    finally:
        s.close()
    if schlecht:
        melde_gebremst("mqtt_teil",
                       f"MQTT: {schlecht} von {versucht} Meldungen sind nicht hinausgegangen.")
    return (versucht, schlecht)


def mqtt_eigenes_thema(praefix: str, thema: str) -> str:
    """Der Schluessel hinter dem Praefix, wenn DIESER Dienst das Thema sendet.

    Eigen sind MQTT_OBEN und fahrzeugN/<feld> mit <feld> aus MQTT_FELDER oder
    MQTT_TEXTFELDER (N ein- oder zweistellig, wie nummern_zuordnen() sie
    vergibt). Sonst "" - ein fremdes Thema unter demselben Praefix, etwa von
    einem zweiten Plugin, bleibt unberuehrt.
    """
    if not thema.startswith(praefix + "/"):
        return ""
    rest = thema[len(praefix) + 1:]
    if rest in MQTT_OBEN:
        return rest
    teile = rest.split("/")
    if (len(teile) == 2 and re.match(r"^fahrzeug[0-9]{1,2}$", teile[0])
            and teile[1] in MQTT_FELDER + MQTT_TEXTFELDER + MQTT_SIGNALFELDER):
        return rest
    return ""


def _broker_leeren(praefix: str, auswahl, warten: float = 3.0) -> dict:
    """Behaltene Themen unter <praefix>/ am Broker loeschen und NACHLESEN.

    Der Weg des Horchers (Klasse Horcher): paho mit Brokerhost, Brokerport,
    Brokeruser und Brokerpass aus general.json (mqtt_zustand()); am Broker
    dieser Anlage am 17.09.2026 mit paho-mqtt 2.1.0 gemessen. Bauart
    VolkswagenID 0.9.24 mqtt_altlast_abraeumen():
      1. geloescht wird nur, was WIRKLICH behalten im Broker liegt - gefunden
         ueber ein Abonnement - und was auswahl(thema) freigibt;
      2. danach ein zweites Abonnement: was dann noch behalten ankommt, ist
         stehengeblieben.
    Rueckgabe {"rc", "geleert", "rest", "grund", "ohne_paho"}: rc 0 = nichts
    (mehr) behalten, 1 = nach dem Loeschen stand noch etwas, 2 = nicht
    moeglich (keine Bibliothek, Broker fort, Anmeldung abgewiesen).
    """
    erg = {"rc": 2, "geleert": [], "rest": [], "grund": "", "ohne_paho": False}
    if not praefix or "#" in praefix or "+" in praefix:
        erg["grund"] = f"das Themenpraefix '{praefix}' taugt nicht fuer ein Abonnement"
        return erg
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        erg["grund"] = "die Bibliothek paho-mqtt fehlt in der virtuellen Umgebung"
        erg["ohne_paho"] = True
        return erg
    import threading
    z = mqtt_zustand()
    broker = z.get("broker") or "127.0.0.1"
    try:
        port = int(z.get("brokerport") or 1883)
    except (TypeError, ValueError):
        port = 1883
    gesehen: set = set()
    angemeldet = threading.Event()
    code = {"wert": None}

    def bei_verbindung(_k, _d, _f, *rest):
        # paho 1.x und CallbackAPIVersion.VERSION1: rc als Zahl; VERSION2:
        # ein ReasonCode mit .value.
        try:
            code["wert"] = int(getattr(rest[0], "value", rest[0]) or 0) if rest else 0
        except (TypeError, ValueError):
            code["wert"] = 0
        angemeldet.set()

    def bei_nachricht(_k, _d, n):
        # Nur BEHALTENES mit Inhalt. Ein live gesendeter Wert (retain=0) ist
        # keine Altlast, und ein leeres Thema ist schon geloescht.
        if n.retain and n.payload and auswahl(n.topic):
            gesehen.add(n.topic)

    try:
        k = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except (AttributeError, TypeError):
        k = mqtt.Client()
    k.on_connect = bei_verbindung
    k.on_message = bei_nachricht
    benutzer = z.get("brokeruser") or ""
    if benutzer:
        k.username_pw_set(benutzer, z.get("brokerpass") or None)
    try:
        k.connect(broker, port, 30)
    except Exception as err:  # noqa: BLE001
        erg["grund"] = f"der Broker {broker}:{port} ist nicht erreichbar ({fehlertext(err)})"
        return erg
    k.loop_start()
    try:
        if not angemeldet.wait(10):
            erg["grund"] = f"der Broker {broker}:{port} hat auf die Verbindung nicht geantwortet"
            return erg
        if code["wert"]:
            erg["grund"] = (f"der Broker {broker}:{port} hat die Anmeldung abgewiesen: "
                            f"{CONNACK_KLARTEXT.get(code['wert'], 'unbekannter Grund')} "
                            f"(CONNACK {code['wert']})")
            return erg
        k.subscribe(praefix + "/#")
        time.sleep(warten)
        k.unsubscribe(praefix + "/#")
        zu_leeren = sorted(gesehen)
        for thema in zu_leeren:
            info = k.publish(thema, b"", qos=1, retain=True)
            try:
                info.wait_for_publish(5)
            except TypeError:           # paho 1.x vor 1.6 kennt kein timeout
                info.wait_for_publish()
        # NACHLESEN: ein neues Abonnement bekommt alles, was noch behalten ist.
        gesehen.clear()
        k.subscribe(praefix + "/#")
        time.sleep(warten)
        erg["geleert"] = zu_leeren
        erg["rest"] = sorted(gesehen)
        erg["rc"] = 1 if erg["rest"] else 0
    except Exception as err:  # noqa: BLE001
        erg["rc"] = 2
        erg["grund"] = f"das Loeschen am Broker {broker}:{port} scheiterte ({fehlertext(err)})"
    finally:
        k.loop_stop()
        try:
            k.disconnect()
        except Exception:  # noqa: BLE001
            pass
    return erg


def mqtt_altlast_abraeumen(praefix: str, warten: float = 3.0) -> int:
    """Einmal je Praefix die zurueckbehaltenen Altwerte frueherer Fassungen
    am Broker loeschen (RETAIN_ALTLAST_KENNUNG) - Merker ERST nach dem
    Nachlesen.

    Solange es nicht nachweislich durch ist, laeuft es beim naechsten
    Durchgang wieder; die Meldung dazu ist gedrosselt (melde_gebremst, fehlt
    paho: einmal am Tag). Rueckgabe 0 erledigt oder nichts zu tun, 1 es blieb
    etwas stehen, 2 nicht moeglich. Ein Fehlschlag haelt den Durchgang nicht
    an: der gueltige Wert geht in jedem Fall hinterher (lebenszeichen_senden()).
    """
    kennung = "|".join((RETAIN_ALTLAST_KENNUNG, praefix,
                        ",".join(sorted(MQTT_OHNE_RETAIN))))
    if json_lesen(DATEI_ZUSTAND).get("retain_altlast") == kennung:
        return 0

    def altlast(thema: str) -> bool:
        s = mqtt_eigenes_thema(praefix, thema)
        return bool(s) and mqtt_ohne_retain(s)

    erg = _broker_leeren(praefix, altlast, warten)
    if erg["rc"] == 2:
        melde_gebremst("retain_altlast",
                       f"MQTT: zurueckbehaltene Altwerte frueherer Fassungen liessen sich "
                       f"nicht abraeumen - {erg['grund']}. Es wird bei jedem Durchgang "
                       f"erneut versucht.", 86400 if erg["ohne_paho"] else 3600)
        return 2
    if erg["rc"] == 1:
        melde_gebremst("retain_altlast",
                       f"MQTT: {len(erg['rest'])} von {len(erg['geleert'])} "
                       f"zurueckbehaltenen Altwerten stehen noch im Broker (zum Beispiel "
                       f"{erg['rest'][0]}) - es wird beim naechsten Durchgang erneut versucht.")
        return 1
    zustand_schreiben(retain_altlast=kennung)
    if erg["geleert"]:
        _LOG.info("MQTT: %d zurueckbehaltene Altwerte frueherer Fassungen geloescht und "
                  "nachgelesen (%s).", len(erg["geleert"]), ", ".join(erg["geleert"]))
    return 0


def _udp_leeren(praefix: str) -> int:
    """Rueckfall der Deinstallation, wenn der Broker nicht erreichbar ist
    oder paho fehlt: je eigenem Thema ein leeres 'retain' an den UDP-Eingang.
    Das ist der Weg bis 0.9.24 - UDP bestaetigt nichts, und die Ausgabe sagt
    es. Fahrzeugnummern aus dem letzten Abbild, sonst 1 bis 4 (ein
    Loeschbefehl fuer ein Thema, das es nie gab, ist folgenlos)."""
    z = mqtt_zustand()
    if not z["udpport"]:
        print("<INFO> MQTT: auch kein UDP-Eingang des Gateways in general.json - die "
              "behaltenen Themen bleiben stehen und sind im Broker von Hand zu loeschen.")
        return 2
    nummern = []
    lox = json_lesen(DATEI_LOXONE)
    for q in (lox.get("fahrzeuge"), json_lesen(DATEI_CACHE).get("fahrzeuge")):
        if isinstance(q, dict):
            for n in q:
                if re.match(r"^[0-9]{1,2}$", str(n)) and str(n) not in nummern:
                    nummern.append(str(n))
    if not nummern:
        nummern = [str(i) for i in range(1, max(ganz(lox.get("anzahl_fahrzeuge"), 0), 4) + 1)]
    themen = list(MQTT_OBEN)
    for n in nummern:
        themen += [f"fahrzeug{n}/{feld}" for feld in MQTT_FELDER + MQTT_TEXTFELDER]
    geschickt = 0
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError as err:
        print(f"<INFO> MQTT: kein Socket ({err}) - die behaltenen Themen bleiben stehen.")
        return 2
    try:
        for th in themen:
            try:
                s.sendto(f"retain {praefix}/{th} ".encode("utf-8"), ("127.0.0.1", z["udpport"]))
                geschickt += 1
            except OSError:
                pass
    finally:
        s.close()
    print(f"<INFO> MQTT: Rueckfall ueber den UDP-Eingang {z['udpport']} des Gateways: "
          f"{geschickt} Loeschbefehle unter '{praefix}/' geschickt (leere Nutzlast, 'retain').")
    print("<INFO> MQTT: UDP bestaetigt nichts. Stehen die Themen danach noch, sind sie im "
          "Broker von Hand zu loeschen.")
    return 2


def mqtt_leeren(warten: float = 3.0) -> int:
    """Fuer die Deinstallation (uninstall/uninstall, Abschnitt 1b): alle
    behaltenen EIGENEN Themen am Broker loeschen und nachmessen.

    Unabhaengig vom Haken "Werte behalten": der Altwert kann aus der Zeit
    stammen, als er gesetzt war, und geloescht wird ohnehin nur, was
    wirklich behalten liegt. Ausgabe im Format des Installers (<OK>,
    <INFO>, <WARNING>). Rueckgabe 0 geleert/nichts zu leeren, 1 es blieb
    etwas stehen, 2 nicht am Broker moeglich (dann der UDP-Rueckfall).
    """
    # ALLE PRAEFIXE, NICHT NUR DAS AKTUELLE (M5, Durchgang 01.10.2026): dazu
    # die vorgemerkten und das, unter dem zuletzt retained gesendet wurde
    # (mqtt_praefix_pflegen()). Gemessen bis 0.9.28: nach einem Praefixwechsel
    # 0 Loeschbefehle unter dem alten Praefix.
    z = json_lesen(DATEI_ZUSTAND)
    praefixe = [config()["mqtt_topic"]]
    for p in list(z.get("mqtt_vorgemerkt") or []) + [z.get("mqtt_retain_praefix")]:
        if isinstance(p, str) and p and thema_saeubern(p) == p and p not in praefixe:
            praefixe.append(p)
    rc_gesamt = 0
    for praefix in praefixe:
        rc_gesamt = max(rc_gesamt, _mqtt_leeren_eines(praefix, warten))
    return max(rc_gesamt, haus_fz_leeren(warten))     # 0.9.36: auch haus/fahrzeug/<name>/


def _mqtt_leeren_eines(praefix: str, warten: float) -> int:
    """mqtt_leeren() fuer EIN Praefix (Form bis 0.9.28)."""
    erg = _broker_leeren(praefix, lambda t: bool(mqtt_eigenes_thema(praefix, t)), warten)
    if erg["rc"] == 0:
        if erg["geleert"]:
            print(f"<OK> MQTT: {len(erg['geleert'])} behaltene Themen unter '{praefix}/' am "
                  f"Broker geloescht und nachgemessen.")
        else:
            print(f"<INFO> MQTT: unter '{praefix}/' war am Broker nichts von diesem Plugin "
                  f"behalten - nachgemessen, nichts zu loeschen.")
        return 0
    if erg["rc"] == 1:
        print(f"<WARNING> MQTT: {len(erg['rest'])} von {len(erg['geleert'])} behaltenen "
              f"Themen unter '{praefix}/' stehen nach dem Loeschen noch im Broker, zum "
              f"Beispiel {erg['rest'][0]} - bitte von Hand loeschen.")
        return 1
    print(f"<INFO> MQTT: am Broker nicht moeglich - {erg['grund']}.")
    return _udp_leeren(praefix)


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
        # Gruppe 41 (B2): abfahrt_erledigt (nur im Speicher) ist fort - der Merker der Vorklimatisierung
        # liegt in data/.../vorklima.json und uebersteht Neustart und Update.
        # Gruppe 41: haus/<quelle>/... mit Retain-Bit; Frische nur ueber den live gesehenen Zaehler.
        self.haus: dict = {}
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
        if cfg.get("empf_thema") and cfg.get("ladeempf_quelle") != "haus":
            t.append(str(cfg["empf_thema"]))
        if cfg.get("abfahrt_ein") and cfg.get("abfahrt_thema"):
            t.append(str(cfg["abfahrt_thema"]))
        # Gruppe 41: Haus-Themen - dieselbe Bedingung wie sk_haus_quellen() in sk_lib.php.
        t += haus_themen(cfg)
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
        self.haus = {}

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
            # ANMELDEN, nicht nur verbinden.
            #
            # Am Broker dieser Anlage am 06.09.2026 gemessen: eine anonyme
            # Verbindung wird mit CONNACK 5 ("nicht autorisiert") abgewiesen.
            # Der Rueckruf unten wertet diesen Code seit 0.9.14 richtig aus
            # und meldete also zuverlaessig, dass der Horcher nicht
            # hereinkam - nur meldete ihn niemand an. Ladeempfehlung und
            # Vorklimatisierung waren damit tot, und die Meldung im Protokoll
            # sah nach einem Fehler des Brokers aus.
            #
            # Ist kein Benutzer hinterlegt, bleibt es beim anonymen Versuch:
            # ein Broker ohne Anmeldung nimmt ihn an, und ein leerer Benutzer
            # waere dort eine Abweisung, wo es vorher ging.
            benutzer = z.get("brokeruser") or ""
            if benutzer:
                k.username_pw_set(benutzer, z.get("brokerpass") or None)

            def merken(_c, _u, m):
                wert = m.payload.decode("utf-8", "replace").strip()
                retained = bool(getattr(m, "retain", False))
                # Gruppe 41 (B3): Haus-Themen (Regeln/07 Nr. 15) werden auch retained angenommen - sie
                # gelten aber erst mit einem LIVE gesehenen Zaehlerwechsel ihrer Quelle.
                if str(m.topic).startswith("haus/"):
                    haus_merken(self.haus, m.topic, wert, retained, time.time())
                    return
                self.werte[m.topic] = wert
                # B3 (Gruppe 41, belegter Fehler, Regeln/07 :221): eine retained Nachricht kommt beim
                # Abonnieren mit beliebigem Alter an. Bis 0.9.33 galt sie als frisch zum Empfangszeitpunkt
                # - nach einem Neustart bis zu empf_alter (10 800 s) lang. Seit 0.9.34 hat sie kein Alter
                # (0 = nie frisch); erst eine live empfangene Nachricht zaehlt.
                self.empfangen[m.topic] = 0.0 if retained else time.time()

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
                # "angemeldet". NACHGEMESSEN am 17.09.2026 am Broker dieser
                # Anlage mit paho-mqtt 2.1.0 aus der Umgebung des Plugins: mit
                # erfundenem Benutzer kommt hier _rc = 5 an, mit den
                # Zugangsdaten des Gateways 0 - danach abonniert, einen
                # gesendeten Wert empfangen, Empfehlung gerechnet.
                #
                # SEIT 0.9.21 MIT KLARTEXT. Bis 0.9.20 stand in der Meldung nur
                # die Zahl. Regeln/07 verlangt den Grund in Worten, fuer die
                # Codes von MQTT 3.1.1 (1-5) wie fuer MQTT 5 (132-136).
                if _rc:
                    self.verbunden = False
                    try:
                        code = int(getattr(_rc, "value", _rc))
                    except (TypeError, ValueError):
                        code = -1
                    self.grund = (f"Der Broker {broker}:{port} hat die Anmeldung "
                                  f"abgewiesen: {CONNACK_KLARTEXT.get(code, 'unbekannter Grund')} "
                                  f"(CONNACK {_rc}).")
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
        if cfg.get("ladeempf_quelle") == "haus":
            # Gruppe 41 (E8b): Endpreis jetzt aus haus/strompreis/aktuell - nur bei frischer Quelle
            # (Zaehler live binnen 120 s). Schweigt sie oder kommt '-', geht wie beim eigenen Thema
            # eine 0 hinaus, nicht der alte Stand (M6 - in Loxone bliebe sonst die letzte 1 stehen).
            if cfg.get("empf_grenze") == "":
                return None
            if not haus_frisch(self.haus, "strompreis", time.time()):
                melde_gebremst("empf_haus_still", "Ladeempfehlung: haus/strompreis schweigt (kein "
                               "Zaehlerwechsel binnen 120 s). Sie geht als 0 hinaus.", 3600)
                return 0
            wert = zahl(haus_wert(self.haus, "strompreis", "haus/strompreis/aktuell"), 3)
            if wert is None:
                melde_gebremst("empf_haus_keine_zahl", "Ladeempfehlung: haus/strompreis/aktuell traegt "
                               "keine Zahl. Sie geht als 0 hinaus.", 3600)
                return 0
            grenze = float(cfg["empf_grenze"])
            return 1 if ((wert < grenze) if cfg.get("empf_kleiner") else (wert > grenze)) else 0
        thema = str(cfg.get("empf_thema") or "")
        if not thema or cfg.get("empf_grenze") == "":
            return None
        roh = self.werte.get(thema)
        if roh is None:
            return None
        grenze_alter = ganz(cfg.get("empf_alter"), VORGABEN["empf_alter"])
        if grenze_alter > 0:
            if not self.empfangen.get(thema):
                melde_gebremst("empf_retained", f"Auf '{thema}' liegt nur ein behaltener (retained) Wert - "
                               f"er gilt seit 0.9.34 nicht als frisch (B3). Die Ladeempfehlung geht als 0 "
                               f"hinaus, bis ein Wert live kommt.", 3600)
                return 0
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
            # VERSTUMMT HEISST 0, NICHT NICHTS (M6, Durchgang 01.10.2026).
            # Bis 0.9.28 lieferte eine Quelle, die nach Entscheidung 5 "keine
            # Aussage" als "-" meldet (oder leer), hier None - gesendet wurde
            # nichts, und in Loxone blieb die letzte 1 stehen (gemessen,
            # skoda_agenten/mqtt/_agent/messung_2.txt). Der Kopf dieser
            # Funktion verspricht es seit 31.08.2026.
            melde_gebremst("empf_keine_zahl",
                           f"Auf '{thema}' kam keine Zahl ('{str(roh)[:20]}'). Die "
                           f"Ladeempfehlung geht als 0 hinaus, nicht als der alte Stand.", 3600)
            return 0
        grenze = float(cfg["empf_grenze"])
        return 1 if ((wert < grenze) if cfg.get("empf_kleiner") else (wert > grenze)) else 0


_HORCHER = Horcher()


# ---------------------------------------------------------------------------
# Gruppe 41 (0.9.34): Hausform im Dienst - Haus-Themen (Regeln/07 Nr. 15),
# Vorklimatisierung nach MG-Regeln, Ankunft, Ladekosten, Ladeempfehlung aus
# haus/strompreis, Meldungen an SignalBot. Bauvorschrift
# Pruefung-Durchgang-2026-09-29/wz_bild/GRUPPE41_BAUVORSCHRIFT.md, G4-G8 und 2.2.
# Die Entscheidungslogik steht in reinen Funktionen (Uhr als Argument); der
# Wartetakt des Dienstes ruft sie (g41_takt()). Vorlage: AudiConnect 0.9.30
# (dort aus MGiSmart 1.1.28 und Renault NG 2.1.20 abgeschrieben).
# ---------------------------------------------------------------------------
HAUS_FRIST = 120                 # Nr. 15: ein Wert gilt, solange der Zaehler der Quelle binnen 120 s live wechselt
VORKLIMA_VERSUCHE = 3            # 1 senden, 2 Abruf statt senden, 3 senden - hoechstens zwei "Klima ein"
VORKLIMA_ABSTAND = 120           # Sekunden zwischen zwei Versuchen
VORKLIMA_FAHRZEUG_FRISCH = 3600  # Aussentemperatur des Fahrzeugs gilt aus einem Abbild bis 60 min
AUSSEN_LOXONE_FRISCH = 1800      # G39 E-E4: Aussentemperatur aus Loxone gilt 30 min
ANKUNFT_ABSTAND = 1800           # hoechstens ein Abruf je 30 min wegen einer Ankunft
ANKUNFT_STAND_ALT = 300          # nur, wenn der Fahrzeugstand aelter als 5 min ist
ABFAHRT_THEMA_FRISCH = 300       # B4: das bisherige Thema gilt nur, wenn es binnen 300 s LIVE kam (wie Audi)
DATEI_AUSSEN = PDATA / "aussentemp.json"      # schreibt die Bruecke (sk_aussentemp_merken())
DATEI_VORKLIMA = PDATA / "vorklima.json"      # B2: Merker der Vorklimatisierung und der Ankunft
DATEI_LADEKOSTEN = PDATA / "ladekosten.json"  # Kosten und Preis der letzten Ladung je Fahrzeug
_BROKER_SENDEN = None            # Nahtstelle fuer Proben: Funktion (thema, nutzlast) -> bool
# Die drei neuen Fahrzeugthemen kommen nicht aus dem Abbild (loxone.json), sondern von hier.
_G41 = {"vorklima": {}, "ladung": {}}


def g41_wert(nummer, feld: str, f: dict):
    """Wert eines Fahrzeugthemas fuer MQTT: vorklima, ladung_kosten, ladung_preis aus _G41, sonst aus dem Abbild."""
    nr = str(nummer)
    if feld == "vorklima":
        return _G41["vorklima"].get(nr, 0)
    if feld in ("ladung_kosten", "ladung_preis"):
        e = _G41["ladung"].get(nr) or {}
        w = e.get(feld[len("ladung_"):])
        return -1 if w is None else w
    return f.get(feld)


def haus_quelle(thema: str) -> str:
    """'haus/abfahrt/in_min' -> 'abfahrt'; haus/tag/<n>/da gehoert zum Anbieter der Anwesenheit (BLE-Scanner)."""
    teile = str(thema).split("/")
    if len(teile) < 3 or teile[0] != "haus":
        return ""
    return "anwesenheit" if teile[1] == "tag" else teile[1]


def haus_merken(stand: dict, thema: str, wert: str, retained: bool, jetzt: float) -> None:
    """Eine Nachricht unter haus/ einarbeiten (rein bis auf stand).

    B3 (Gruppe 41): ein Wert wird angenommen, auch retained - er gilt aber erst, wenn
    der Zaehler seiner Quelle LIVE wechselt. Ein retained Zaehler zaehlt nie; ein live
    gesehener Zaehler mit neuem Wert setzt 'seit' (Form mg_haus_merken())."""
    q = haus_quelle(thema)
    if not q:
        return
    e = stand.setdefault(q, {"werte": {}, "zaehler": None, "seit": 0})
    if str(thema).endswith("/zaehler"):
        if not retained and str(wert) != str(e.get("zaehler")):
            e["zaehler"] = str(wert)
            e["seit"] = int(jetzt)
    else:
        e.setdefault("werte", {})[thema] = str(wert)


def haus_frisch(stand: dict, q: str, jetzt: float) -> bool:
    """Frisch: 0 <= jetzt - seit <= HAUS_FRIST, seit gesetzt und nicht in der Zukunft (Uhr zurueck -> nicht frisch)."""
    seit = int((stand.get(q) or {}).get("seit") or 0)
    return 0 < seit <= int(jetzt) and int(jetzt) - seit <= HAUS_FRIST


def haus_wert(stand: dict, q: str, thema: str):
    return ((stand.get(q) or {}).get("werte") or {}).get(thema)


def ankunft_themen(quelle) -> list:
    """'tag:<name>,person:<name>' -> Themen; dieselbe Pruefung wie die Oberflaeche (reserviert jemand, zaehler)."""
    q = str(quelle or "").strip()
    if not re.fullmatch(r"(tag|person):[A-Za-z0-9_-]{1,40}(,(tag|person):[A-Za-z0-9_-]{1,40}){0,3}", q):
        return []
    if re.search(r"(^|,)person:(jemand|zaehler)(,|$)", q):
        return []
    aus = []
    for teil in q.split(","):
        art, name = teil.split(":", 1)
        aus.append("haus/tag/%s/da" % name if art == "tag" else "haus/anwesenheit/%s" % name)
    return aus


def haus_themen(cfg: dict) -> list:
    """Die Haus-Themen, die der Dienst abonniert - dieselbe Bedingung wie sk_haus_quellen() in sk_lib.php."""
    t = []
    if cfg.get("abfahrt_ein") and cfg.get("haus_abfahrt_ein"):
        t += ["haus/abfahrt/in_min", "haus/abfahrt/zaehler"]
    anw = False
    if cfg.get("abfahrt_ein") and cfg.get("vorklima_anwesend_ein"):
        t.append("haus/anwesenheit/jemand")
        anw = True
    if cfg.get("ankunft_ein"):
        for x in ankunft_themen(cfg.get("ankunft_quelle")):
            t.append(x)
            anw = True
    if anw:
        t.append("haus/anwesenheit/zaehler")
    if cfg.get("haus_strompreis_ein") or (cfg.get("ladeempf_quelle") == "haus" and cfg.get("empf_grenze") != ""):
        t += ["haus/strompreis/" + x for x in ("vorschau", "ab", "raster", "aktuell", "zaehler")]
    return t


def haus_zustand(stand: dict, jetzt: float) -> dict:
    """Fuer zustand.json (Reiter Test): je Quelle frisch, Alter, seit - nie Werte."""
    aus = {}
    for q, e in (stand or {}).items():
        seit = int((e or {}).get("seit") or 0)
        aus[q] = {"frisch": 1 if haus_frisch(stand, q, jetzt) else 0, "seit": seit,
                  "alter": int(jetzt) - seit if seit else -1}
    return aus


# ---- G5: Vorklimatisierung nach MG-Regeln (B1, B2, B4, B5) ----
def vorklima_kennung(jetzt: float, in_min: int) -> int:
    """Kennung einer Abfahrt: Abfahrtszeit auf 5 min gerundet (wie PHP round, halbe nach oben)."""
    return int(math.floor((int(jetzt) + int(in_min) * 60) / 300.0 + 0.5) * 300)


def vorklima_neu(k: int) -> dict:
    return {"kennung": int(k), "versuche": 0, "letzter": 0, "erfolg": 0, "abgerufen": 0,
            "aufgegeben": 0, "mild": 0}


def vorklima_schritt(m: dict, in_min, jetzt: float, vorlauf: int, letztes_ok=None):
    """Ein Schritt (rein; Abschrift mg_vorklima_schritt()). Rueckgabe (aktion, neuer_merker),
    aktion nichts | senden | abruf | aufgeben | erledigt.
    - Ausloesen nur bei 1 <= in_min <= vorlauf (0 = ueberfaellig und -1 nie).
    - Eine Kennung, die hoechstens 5 min von der gemerkten abweicht, ist dieselbe Abfahrt.
    - Hoechstens VORKLIMA_VERSUCHE Versuche, Abstand >= VORKLIMA_ABSTAND: 1 senden, 2 Abruf
      (gesendet wird in diesem Schritt nicht), 3 senden; danach aufgeben. Hoechstens zwei "Klima ein".
    - B1: erledigt erst nach einem Erfolg (letztes_ok is True), nie vorher."""
    m = dict(m or {})
    jetzt = int(jetzt)
    if letztes_ok is True and "kennung" in m:
        m["erfolg"] = 1
    try:
        n = int(str(in_min).strip())
    except (TypeError, ValueError):
        return ("nichts", m)
    if n < 1 or n > max(1, int(vorlauf)):
        return ("nichts", m)
    k = vorklima_kennung(jetzt, n)
    if "kennung" not in m or abs(k - int(m["kennung"])) > 300:
        m = vorklima_neu(k)
    for x, v in vorklima_neu(k).items():
        m.setdefault(x, v)
    if m["erfolg"] or m["mild"]:
        return ("erledigt", m)
    if m["aufgegeben"]:
        return ("nichts", m)
    if int(m["versuche"]) >= VORKLIMA_VERSUCHE:
        m["aufgegeben"] = 1
        return ("aufgeben", m)
    if int(m["versuche"]) >= 1:
        if jetzt < int(m["letzter"]):
            m["letzter"] = jetzt          # Uhr zurueck: neu zaehlen, nicht senden
            return ("nichts", m)
        if jetzt - int(m["letzter"]) < VORKLIMA_ABSTAND:
            return ("nichts", m)
    m["versuche"] = int(m["versuche"]) + 1
    m["letzter"] = jetzt
    if m["versuche"] == 2 and not m["abgerufen"]:
        m["abgerufen"] = 1
        return ("abruf", m)
    return ("senden", m)


def vorklima_wert(m, jetzt: float) -> int:
    """Thema fahrzeug<n>/vorklima: 0 nichts/aus, 1 gesendet, 2 mild, 3 wartet auf Wiederholung,
    4 wartet auf Anwesenheit, -1 gescheitert (rein, wie mg_vorklima_wert())."""
    if not isinstance(m, dict) or "kennung" not in m:
        return 0
    if int(m["kennung"]) + 1800 < int(jetzt):
        return 0
    if m.get("aufgegeben"):
        return -1
    if m.get("erfolg"):
        return 1
    if m.get("mild"):
        return 2
    if m.get("warten_anwesend"):
        return 4
    if m.get("sperre"):
        return 5 if m.get("sperre") == "akku" else 6
    if m.get("versuche"):
        return 3
    return 0


def vorklima_wetter(cfg: dict, aussen_lox, alter_lox, aussen_fz, alter_fz) -> str:
    """klimatisieren | mild | ohne_aussage (rein). Zuerst Loxone (<= AUSSEN_LOXONE_FRISCH s), sonst das
    Fahrzeug (Abbild <= VORKLIMA_FAHRZEUG_FRISCH s), sonst ohne_aussage - dann wird klimatisiert
    (nie "nicht klimatisiert" ohne Aussage). Haken aus -> klimatisieren."""
    if not cfg.get("vorklima_wetter_ein"):
        return "klimatisieren"
    wert = None
    for w, a, grenze in ((aussen_lox, alter_lox, AUSSEN_LOXONE_FRISCH),
                         (aussen_fz, alter_fz, VORKLIMA_FAHRZEUG_FRISCH)):
        z, al = zahl(w, 1), zahl(a)
        if z is not None and z > -99 and al is not None and 0 <= al <= grenze:
            wert = z
            break
    if wert is None:
        return "ohne_aussage"
    kalt = zahl(cfg.get("vorklima_kalt_unter"), 1)
    heiss = zahl(cfg.get("vorklima_heiss_ueber"), 1)
    kalt = 5.0 if kalt is None else kalt
    heiss = 25.0 if heiss is None else heiss
    return "mild" if kalt <= wert <= heiss else "klimatisieren"


def aussentemp_lesen(jetzt: float):
    """Die Aussentemperatur aus Loxone (Bruecke): (wert, alter_s) oder (None, -1)."""
    d = json_lesen(DATEI_AUSSEN)
    w, t = zahl(d.get("wert"), 1), zahl(d.get("t"))
    if w is None or t is None or t > jetzt:
        return (None, -1)
    return (w, int(jetzt - t))


def vorklima_minuten(horcher, cfg: dict, jetzt: float):
    """(in_min oder None, Herkunft). Haus-Thema bei frischer Quelle; sonst das bisherige freie Thema als
    Rueckfall (E6, entfaellt mit der naechsten Fassung) - B3/B4: nur ein LIVE empfangener Wert, hoechstens
    ABFAHRT_THEMA_FRISCH s alt (ein retained Wert gilt nie als frisch)."""
    if cfg.get("haus_abfahrt_ein") and haus_frisch(horcher.haus, "abfahrt", jetzt):
        v = str(haus_wert(horcher.haus, "abfahrt", "haus/abfahrt/in_min") or "").strip()
        try:
            return (int(float(v)), "haus")
        except ValueError:
            return (-1, "haus")            # '-' oder leer: keine Abfahrt bekannt
    thema = str(cfg.get("abfahrt_thema") or "")
    if not thema:
        return (None, "aus")
    roh = horcher.werte.get(thema)
    seit = jetzt - float(horcher.empfangen.get(thema, 0.0) or 0.0)
    if roh is None or seit < 0 or seit > ABFAHRT_THEMA_FRISCH:
        return (None, "still")
    z = zahl(roh)
    return (None, "thema") if z is None else (int(z), "thema")


def vorklima_takt(horcher, cfg: dict, merker: dict, stand: dict, jetzt: float):
    """Ein Schritt im Wartetakt. Rueckgabe: Auftrag fuer befehl_ausfuehren() oder None."""
    if not cfg.get("abfahrt_ein"):
        return None
    nr = str(max(1, ganz(cfg.get("abfahrt_fahrzeug"), 1)))
    vk = merker.setdefault("vorklima", {})
    m = dict(vk.get(nr) or {})
    in_min, herkunft = vorklima_minuten(horcher, cfg, jetzt)
    if in_min is None:
        if herkunft == "still" and cfg.get("haus_abfahrt_ein"):
            melde_gebremst("abfahrt_still",
                           "Vorklimatisierung: es kommt keine frische Abfahrtszeit an (haus/abfahrt schweigt "
                           "und das bisherige Thema ist still).", 3600)
        return None
    vorlauf = ganz(cfg.get("abfahrt_vorlauf"), 20)
    if not 1 <= in_min <= vorlauf:
        aktion, m = vorklima_schritt(m, in_min, jetzt, vorlauf, None)
        vk[nr] = m
        return None
    if not cfg.get("steuerung_ein"):
        melde_gebremst("vorklima_steuerung", "Vorklimatisierung: die Abfahrt liegt im Vorlauf, aber "
                       "'Schreibende Befehle zulassen' ist aus - es wird nichts gesendet.", 3600)
        return None
    # B5: das eingestellte Fahrzeug, nie still ein anderes. Fehlt es im Konto, kein Befehl.
    fz = stand.get("fahrzeuge") or {}
    if fz and nr not in fz:
        melde_gebremst("vorklima_fz_%s" % nr, "Vorklimatisierung: Fahrzeug %s gibt es im Konto nicht "
                       "(Reiter MQTT, 'Fahrzeug fuer die Vorklimatisierung') - es wird nichts gesendet." % nr, 3600)
        return None
    k = vorklima_kennung(jetzt, in_min)
    if "kennung" not in m or abs(k - int(m["kennung"])) > 300:
        m = vorklima_neu(k)
    # E7a: live 0 an haus/anwesenheit/jemand -> warten (kein Versuch verbraucht).
    if (cfg.get("vorklima_anwesend_ein") and haus_frisch(horcher.haus, "anwesenheit", jetzt)
            and str(haus_wert(horcher.haus, "anwesenheit", "haus/anwesenheit/jemand")).strip() == "0"
            and not m.get("erfolg") and not m.get("mild") and not m.get("aufgegeben")):
        if not m.get("warten_anwesend"):
            _LOG.info("Vorklimatisierung Fahrzeug %s: niemand zu Hause - sie wartet.", nr)
        m["warten_anwesend"] = 1
        vk[nr] = m
        return None
    m.pop("warten_anwesend", None)
    # 0.9.36 (Form MGiSmart 1.1.31): Mindest-Akku und "nur mit Kabel". Kein Versuch wird verbraucht, unbekannt sperrt nie.
    sperre = "" if (m.get("versuche") or m.get("erfolg") or m.get("mild")) else vorklima_sperre(cfg, fz.get(nr) or {})
    if sperre:
        if m.get("sperre") != sperre:
            _LOG.info("Vorklimatisierung Fahrzeug %s: ausgesetzt (%s).", nr,
                      "Akku unter der Grenze" if sperre == "akku" else "Kabel steckt nicht")
        m["sperre"] = sperre
        vk[nr] = m
        return None
    m.pop("sperre", None)
    aktion, m = vorklima_schritt(m, in_min, jetzt, vorlauf, None)
    if aktion in ("senden", "abruf") and int(m.get("versuche", 0)) == 1 and not m.get("wetter"):
        m["wetter"] = 1
        aw, al = aussentemp_lesen(jetzt)
        f = fz.get(nr) or {}
        fz_alter = int(jetzt - ganz(f.get("ts"), 0)) if ganz(f.get("ts"), 0) > 0 else -1
        w = vorklima_wetter(cfg, aw, al, f.get("aussentemperatur"), fz_alter)
        if w == "mild":
            lox = aw is not None and 0 <= al <= AUSSEN_LOXONE_FRISCH
            m.update({"mild": 1, "versuche": 0, "letzter": 0})
            vk[nr] = m
            _LOG.info("Vorklimatisierung Fahrzeug %s: mild (%s Grad, Quelle %s) - keine Klimatisierung.",
                      nr, aw if lox else f.get("aussentemperatur"), "Loxone" if lox else "Fahrzeug")
            return None
    vk[nr] = m
    if aktion == "senden":
        _LOG.info("Vorklimatisierung Fahrzeug %s: Abfahrt in %s min (Quelle %s), Versuch %s, Zieltemperatur %s Grad.",
                  nr, in_min, herkunft, m["versuche"], cfg.get("abfahrt_temp"))
        return {"aktion": "klima_start", "fahrzeug": nr, "temp": cfg.get("abfahrt_temp"), "anlass": "vorklima"}
    if aktion == "abruf":
        _LOG.info("Vorklimatisierung Fahrzeug %s: Versuch 2 ist ein Abruf (laeuft die Klimatisierung schon?).", nr)
        return {"aktion": "abruf", "anlass": "vorklima"}
    if aktion == "aufgeben":
        text = "Skoda Connect: die Vorklimatisierung fuer Fahrzeug %s ist gescheitert (zwei Versuche)." % nr
        melde_gebremst("vorklima_%s" % m.get("kennung"), text, 86400)
        signal_senden(cfg, "vorklima", nr, text)
    return None


def vorklima_ergebnis(merker: dict, auftrag: dict, ok) -> None:
    """B1: der Merker gilt als erledigt erst nach ok 1 von befehl_ausfuehren()."""
    if auftrag.get("aktion") != "klima_start":
        return
    m = (merker.get("vorklima") or {}).get(str(auftrag.get("fahrzeug")))
    if isinstance(m, dict) and ok == 1:
        m["erfolg"] = 1


def vorklima_nach_abruf(merker: dict, cfg: dict, fahrzeuge: dict) -> None:
    """Ein Abruf, der 'Klimatisierung laeuft' zeigt, erledigt die laufende Abfahrt."""
    nr = str(max(1, ganz(cfg.get("abfahrt_fahrzeug"), 1)))
    m = (merker.get("vorklima") or {}).get(nr)
    f = fahrzeuge.get(nr) or {}
    if isinstance(m, dict) and m.get("versuche") and not m.get("erfolg") and f.get("klima_an") == 1:
        m["erfolg"] = 1
        _LOG.info("Vorklimatisierung Fahrzeug %s: der Abruf zeigt, die Klimatisierung laeuft.", nr)


def vorklima_melden(cfg: dict, merker: dict, jetzt: float) -> None:
    """fahrzeug<n>/vorklima bei jedem Wechsel sofort senden (nicht erst mit dem naechsten Abruf)."""
    nr = str(max(1, ganz(cfg.get("abfahrt_fahrzeug"), 1)))
    w = vorklima_wert((merker.get("vorklima") or {}).get(nr), jetzt) if cfg.get("abfahrt_ein") else 0
    alt = dict(_G41["vorklima"])
    _G41["vorklima"] = {nr: w}
    if cfg.get("mqtt_ein") and alt.get(nr, 0) != w:
        mqtt_senden({"fahrzeug%s/vorklima" % nr: w}, thema_saeubern(cfg.get("mqtt_topic")), 0)


def vorklima_merker_lesen() -> dict:
    """B2: der Merker liegt in einer Datei und uebersteht Neustart und Update (preupgrade.sh rettet data/)."""
    d = json_lesen(DATEI_VORKLIMA)
    return d if isinstance(d, dict) else {}


# ---- G4/E7b: Abruf bei Ankunft ----
def ankunft_flanke(alt, wert, frisch: bool) -> dict:
    """Live-Flanke 0 -> 1 zaehlen (rein, wie mg_ankunft_flanke())."""
    wert = "" if wert is None else str(wert).strip()
    if not isinstance(alt, dict) or "wert" not in alt:
        return {"wert": wert, "frisch": bool(frisch), "nr": 0}
    nr = int(alt.get("nr") or 0)
    if alt.get("frisch") and frisch and str(alt.get("wert")) == "0" and wert == "1":
        nr += 1
    return {"wert": wert, "frisch": bool(frisch), "nr": nr}


def ankunft_entscheiden(flanke_nr, ausgefuehrt, letzte_abfrage, jetzt, stand_alter):
    """(aktion, neue_ausgefuehrt) mit aktion nichts | abfragen | gedrosselt | frisch (rein, wie
    mg_ankunft_entscheiden(); Alter in Sekunden). Jede Flanke genau einmal."""
    if int(flanke_nr) <= int(ausgefuehrt):
        return ("nichts", int(ausgefuehrt))
    neu = int(flanke_nr)
    if int(letzte_abfrage) > 0 and int(jetzt) >= int(letzte_abfrage) \
            and int(jetzt) - int(letzte_abfrage) < ANKUNFT_ABSTAND:
        return ("gedrosselt", neu)
    if stand_alter is not None and 0 <= int(stand_alter) <= ANKUNFT_STAND_ALT:
        return ("frisch", neu)
    return ("abfragen", neu)


def ankunft_takt(horcher, cfg: dict, merker: dict, stand: dict, jetzt: float) -> bool:
    """True, wenn wegen einer Ankunft abgefragt werden soll. Der Sofortabruf ist kontoweit (ein Durchgang
    fuer alle Fahrzeuge) - deshalb eine Quelle je Konto, wie bei Audi."""
    if not cfg.get("ankunft_ein"):
        return False
    a = merker.setdefault("ankunft", {})
    fl = a.setdefault("flanken", {})
    frisch = haus_frisch(horcher.haus, "anwesenheit", jetzt)
    soll = False
    stand_alter = int(jetzt - ganz(stand.get("ts"), 0)) if ganz(stand.get("ts"), 0) > 0 else None
    for t in ankunft_themen(cfg.get("ankunft_quelle")):
        fl[t] = ankunft_flanke(fl.get(t), haus_wert(horcher.haus, "anwesenheit", t), frisch)
        aktion, neu = ankunft_entscheiden(fl[t]["nr"], int((a.get("ausgefuehrt") or {}).get(t, 0)),
                                          int(a.get("letzte") or 0), jetzt, stand_alter)
        if aktion != "nichts":
            a.setdefault("ausgefuehrt", {})[t] = neu
            _LOG.info("Ankunft (%s): %s.", t, {"abfragen": "Abruf", "gedrosselt": "kein Abruf - der letzte "
                      "liegt keine 30 Minuten zurueck", "frisch": "kein Abruf - der Stand ist juenger als "
                      "5 Minuten"}[aktion])
        if aktion == "abfragen":
            soll = True
    if soll:
        a["letzte"] = int(jetzt)
    return soll


# --- LADEKOSTEN-KERN G41 (wortgleich in audi.py, skoda.py, vw.py) ---
LADUNG_TAKT_S = 60          # eine Probe je Minute; die erste steht fuer 60 s
LADUNG_LUECKE_S = 120       # ein groesserer Abstand ist eine Luecke ohne Energie
LADUNG_ABDECKUNG = 0.9      # fehlt der Preis fuer mehr als 10 % der Energie: Kosten -1, nie geschaetzt


def _ladung_zahl(w):
    if w is None or isinstance(w, bool):
        return None
    try:
        return float(str(w).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def preis_zum_zeitpunkt(vorschau, ab, raster, aktuell, frisch, t):
    """Endpreis in ct/kWh zum Zeitpunkt t (rein, wie mg_preis_zum_zeitpunkt()): vorschau[(t - ab) // raster]
    bei Raster 900/3600 und ab im Raster; sonst aktuell, aber nur bei frischer Quelle; sonst None."""
    import re
    v = vorschau.strip() if isinstance(vorschau, str) else ""
    if v and len(v) <= 4096 and re.fullmatch(r"-?\d{1,4}(\.\d{1,3})?(;-?\d{1,4}(\.\d{1,3})?)*", v):
        a, r = _ladung_zahl(ab), _ladung_zahl(raster)
        if a is not None and r is not None and int(r) in (900, 3600) and int(a) > 0 \
                and int(a) % int(r) == 0 and int(t) >= int(a):
            liste = v.split(";")
            i = (int(t) - int(a)) // int(r)
            if i < len(liste):
                return float(liste[i])
    if frisch:
        return _ladung_zahl(aktuell)
    return None


def ladung_kosten(proben, kwh_gemeldet=None):
    """Kosten einer Ladung aus Minutenproben [t, kw, preis] (rein).

    Jede Probe steht fuer die Zeit seit der vorigen (die erste fuer LADUNG_TAKT_S); ein Abstand ueber
    LADUNG_LUECKE_S ist eine Luecke. Gewicht = gemeldete Ladeleistung x Dauer; meldet keine Probe eine
    Leistung, wird nach Dauer verteilt (Renault 2.1.20, Abweichung 4b). Energie = kwh_gemeldet (Akkustand-
    Differenz x Kapazitaet), sonst die Summe der Leistungsgewichte. Abdeckung = Anteil des Gewichts mit
    Preis; unter LADUNG_ABDECKUNG Kosten und Preis -1 (nie geschaetzt).
    Rueckgabe (kwh, kosten_eur, preis_ct, abdeckung, grund)."""
    p = {}
    for x in proben or []:
        try:
            t = int(x[0])
        except (TypeError, ValueError, IndexError):
            continue
        p.setdefault(t, x)
    mit_kw = any((_ladung_zahl(x[1]) or 0) > 0 for x in p.values() if len(x) > 1)
    gesamt = mit = cent = 0.0
    vorher = None
    for t in sorted(p):
        x = p[t]
        dt = LADUNG_TAKT_S if vorher is None else t - vorher
        vorher = t
        if dt <= 0 or dt > LADUNG_LUECKE_S:
            continue
        kw = _ladung_zahl(x[1]) if len(x) > 1 else None
        if mit_kw and (kw is None or kw <= 0):
            continue
        g = (kw if mit_kw else 1.0) * dt / 3600.0
        gesamt += g
        pr = _ladung_zahl(x[2]) if len(x) > 2 else None
        if pr is not None:
            mit += g
            cent += pr * g
    kwh = _ladung_zahl(kwh_gemeldet)
    if kwh is None or kwh <= 0:
        kwh = gesamt if mit_kw else None
    if gesamt <= 0 or kwh is None or kwh <= 0:
        return (-1, -1, -1, 0, "leistung_fehlt")
    abd = mit / gesamt
    if abd < LADUNG_ABDECKUNG:
        return (round(kwh, 3), -1, -1, round(abd, 3), "preis_fehlt")
    preis = cent / mit
    return (round(kwh, 3), round(kwh * preis / 100.0, 2), round(preis, 1), round(abd, 3), "ok")


# Offene Mitschrift ueber einen Neustart retten (Zusatz VW 0.9.33, Hausherr 29.10.; danach wortgleich in
# audi.py und skoda.py zurueckzutragen). Datei je Linie, Inhalt {"fassung": 1, "t": <unix>, "offen":
# {<schluessel>: {..., "start": <unix>, "proben": [[t, kw, preis], ...]}}} - der Schluessel ist die
# Fahrzeugnummer der Linie, der Eintrag gehoert der Linie (nur start und proben prueft der Kern).
LADUNG_MITSCHRIFT_ALTER = 43200   # eine Mitschrift, deren letzte Probe aelter als 12 h ist, wird verworfen


def ladung_mitschrift_speichern(pfad, offen, jetzt) -> bool:
    """Die offenen Mitschriften atomar schreiben (Nebendatei, 0600, os.replace). False bei Fehler."""
    import json as _json
    import os as _os
    tmp = "%s.tmp.%d" % (pfad, _os.getpid())
    try:
        text = _json.dumps({"fassung": 1, "t": int(jetzt), "offen": offen}, ensure_ascii=False, sort_keys=True)
        fd = _os.open(tmp, _os.O_WRONLY | _os.O_CREAT | _os.O_TRUNC, 0o600)
        with _os.fdopen(fd, "w", encoding="utf-8") as h:
            h.write(text)
            h.flush()
            _os.fsync(h.fileno())
        _os.replace(tmp, str(pfad))
        return True
    except (OSError, TypeError, ValueError):
        try:
            _os.unlink(tmp)     # nur die eigene Nebendatei
        except OSError:
            pass
        return False


def ladung_mitschrift_laden(pfad, jetzt):
    """(offen, lage) mit lage keine | ok | teils_verworfen | beschaedigt. Verworfen wird ein Eintrag ohne
    gueltigen Beginn, mit Proben in der Zukunft (> 300 s, Uhr zurueck) oder dessen letzte Zeit aelter als
    LADUNG_MITSCHRIFT_ALTER ist; eine unlesbare Datei gilt als leer (beschaedigt - der Aufrufer meldet es)."""
    import json as _json
    import os as _os
    if not _os.path.exists(str(pfad)):
        return ({}, "keine")
    try:
        with open(str(pfad), encoding="utf-8") as h:
            d = _json.loads(h.read())
        roh = d["offen"]
        if not isinstance(roh, dict) or d.get("fassung") != 1:
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        return ({}, "beschaedigt")
    offen, weg = {}, 0
    for k, e in roh.items():
        try:
            start = int(e["start"])
            proben = [p for p in e.get("proben") or [] if isinstance(p, list) and len(p) >= 3]
            zuletzt = max([start] + [int(p[0]) for p in proben])
        except (TypeError, ValueError, KeyError, AttributeError):
            weg += 1
            continue
        if start <= 0 or zuletzt > int(jetzt) + 300 or int(jetzt) - zuletzt > LADUNG_MITSCHRIFT_ALTER:
            weg += 1
            continue
        e = dict(e)
        e["proben"] = proben[-2000:]
        offen[str(k)] = e
    return (offen, "teils_verworfen" if weg else "ok")
# --- ENDE LADEKOSTEN-KERN ---


# ---- G6-Zusatz (Ruecktragen aus VolkswagenID 0.9.33, 29.10.2026): die offene Ladung (_LADEN_OFFEN, mit
# Beginn, Ladestand, hoechster Leistung, Ort und den Minutenproben) steht in einer eigenen Datei und uebersteht
# einen Neustart des Dienstes. Bis dahin lag sie nur im Speicher: ein Neustart mitten in der Ladung verlor die
# ganze Zeile des Ladeprotokolls. Aufrufe: ladung_mitschrift_holen() beim Dienststart, ladung_buchen() bei Beginn
# und Aenderung, ladung_probe() je Minute, ladung_buchen() beim Ende (Eintrag entnommen). Schreiben und Lesen macht
# der Kern (ladung_mitschrift_speichern/_laden); er prueft "start" und "proben", der Rest gehoert der Linie.
DATEI_MITSCHRIFT = PDATA / "ladung_mitschrift.json"   # offene Ladungen - ueberstehen einen Neustart


def ladung_mitschrift_sichern(jetzt: float) -> None:
    """Die offenen Ladungen in DATEI_MITSCHRIFT (Kern: atomar, 0600)."""
    if not ladung_mitschrift_speichern(DATEI_MITSCHRIFT, _LADEN_OFFEN, jetzt):
        melde_gebremst("mitschrift_schreiben", "Ladekosten: die offene Mitschrift liess sich nicht speichern - "
                       "ein Neustart waehrend der Ladung verliert sie.", 3600)


def ladung_mitschrift_holen(jetzt: float) -> None:
    """Beim Dienststart: offene Ladungen zurueckholen (Kern); beschaedigt oder zu alt -> verworfen, gemeldet."""
    offen, lage = ladung_mitschrift_laden(DATEI_MITSCHRIFT, jetzt)
    _LADEN_OFFEN.clear()
    _LADEN_OFFEN.update(offen)
    if lage == "beschaedigt":
        melde_gebremst("mitschrift_kaputt", "Ladekosten: die gespeicherte Mitschrift ist beschaedigt und wird "
                       "verworfen - eine laufende Ladung bekommt keine Kosten (-1).", 3600)
    elif lage == "teils_verworfen":
        _LOG.info("Ladekosten: eine gespeicherte Mitschrift war aelter als 12 h oder ungueltig und wurde verworfen.")
    elif offen:
        _LOG.info("Ladekosten: %d offene Ladung(en) nach dem Neustart uebernommen.", len(offen))


def ladung_probe(horcher, cfg: dict, jetzt: float) -> None:
    """Je Minute einer Ladung zu Hause eine Probe [t, kW, Preis] in die offene Ladung (und in die Datei)."""
    if not cfg.get("haus_strompreis_ein"):
        return
    h = horcher.haus
    frisch = haus_frisch(h, "strompreis", jetzt)
    neu = False
    for offen in _LADEN_OFFEN.values():
        if offen.get("haus") != 1:
            continue
        l = offen.setdefault("proben", [])
        if l and int(jetzt) - int(l[-1][0]) < LADUNG_TAKT_S - 5:
            continue
        preis = preis_zum_zeitpunkt(haus_wert(h, "strompreis", "haus/strompreis/vorschau"),
                                    haus_wert(h, "strompreis", "haus/strompreis/ab"),
                                    haus_wert(h, "strompreis", "haus/strompreis/raster"),
                                    haus_wert(h, "strompreis", "haus/strompreis/aktuell"), frisch, jetzt)
        l.append([int(jetzt), offen.get("kw_jetzt"), preis])
        del l[:-2000]
        neu = True
    if neu:
        ladung_mitschrift_sichern(jetzt)


def ladung_kosten_abschliessen(nummer: str, offen: dict):
    """Beim Ladeende (ladung_buchen()): (kosten, preis) fuer CSV und Themen; -1 ohne Aussage, nie geschaetzt.
    Skoda meldet keine Akkukapazitaet - die Energie ist die Summe aus gemeldeter Ladeleistung x Zeit."""
    lh = offen.get("haus", -2)
    if lh == 1:
        kwh, kosten, preis, _abd, grund = ladung_kosten(offen.get("proben") or [], None)
    else:
        kwh, kosten, preis = -1, -1, -1
        grund = {0: "unterwegs", -1: "heimzone_fehlt"}.get(lh, "aus")
    _G41["ladung"][str(nummer)] = {"kosten": kosten, "preis": preis}
    json_schreiben(DATEI_LADEKOSTEN, _G41["ladung"], rechte=0o600)
    if lh in (0, 1, -1):
        _LOG.info("Fahrzeug %s: Ladekosten %s EUR, Preis %s ct/kWh, %s kWh (%s).", nummer, kosten, preis, kwh, grund)
    return (kosten, preis)


# ---- G8: Meldungen an SignalBot (E9, wie Renault X4) ----
def signal_nutzlast(text: str, dringend: int = 0) -> str:
    """JSON {"text", "dringend"} fuer signalbot/befehl/plugin/<ordner> (rein), hoechstens 4000 Byte."""
    t = str(text or "").replace("\r", " ")
    while True:
        s = json.dumps({"text": t, "dringend": 1 if dringend else 0}, ensure_ascii=False)
        if len(s.encode("utf-8")) <= 4000 or len(t) <= 1:
            return s
        t = t[:max(1, len(t) - max(1, len(s.encode("utf-8")) - 4000) - 2)] + "…"


def signal_thema(praefix, ordner) -> str:
    """'<praefix>/befehl/plugin/<ordner>' oder '' (ungueltig)."""
    p, o = str(praefix or ""), str(ordner or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", p) or not re.fullmatch(r"[a-z0-9_]{1,40}", o):
        return ""
    return "%s/befehl/plugin/%s" % (p, o)


def broker_senden(thema: str, nutzlast: str) -> bool:
    """Kurze Sitzung direkt am Broker (Regeln/07 Nr. 15 Technik), qos 0, NIE retained."""
    if _BROKER_SENDEN is not None:
        return bool(_BROKER_SENDEN(thema, nutzlast))
    try:
        import paho.mqtt.publish as pub
    except ImportError:
        melde_gebremst("signal_paho", "SignalBot-Meldung nicht gesendet: paho-mqtt fehlt.", 86400)
        return False
    z = mqtt_zustand()
    auth = {"username": z["brokeruser"], "password": z["brokerpass"] or None} if z["brokeruser"] else None
    try:
        pub.single(thema, nutzlast, qos=0, retain=False, hostname=z["broker"] or "127.0.0.1",
                   port=ganz(z["brokerport"], 1883) or 1883, auth=auth,
                   client_id="skodaconnect-signal-%d" % os.getpid())
        return True
    except Exception as err:  # noqa: BLE001
        melde_gebremst("signal_senden", "SignalBot-Meldung nicht gesendet: %s" % type(err).__name__, 3600)
        return False


SIGNAL_TEXTE = {
    "laden_fertig": "%s: Die Ladung ist beendet.",
    "laden_abbruch": "%s: Die Ladung wurde unter der Ladegrenze oder mit einer Stoerung beendet.",
    "offen": "%s steht offen oder unverriegelt.",
    "ausfall": "Skoda Connect: seit drei Abrufen keine Daten mehr.",
}


def signal_senden(cfg: dict, anlass: str, nr, text: str) -> bool:
    """Ein Ereignis an SignalBot (ab Werk aus, je Ereignis abwaehlbar, je Ereignis und Fahrzeug 1x je Stunde)."""
    if not cfg.get("signal_ein") or str(cfg.get("signal_" + anlass)).strip() != "1":
        return False
    if _ansage_sperre("signal:%s:%s" % (anlass, nr), int(time.time())):
        return False
    thema = signal_thema(cfg.get("signal_praefix"), PNAME)
    if not thema:
        melde_gebremst("signal_thema", "SignalBot-Meldung nicht gesendet: Praefix oder Ordnername ungueltig.", 86400)
        return False
    ok = broker_senden(thema, signal_nutzlast(text, 0))
    _LOG.info("SignalBot-Meldung %s (Fahrzeug %s): %s.", anlass, nr, "gesendet" if ok else "NICHT gesendet")
    return ok


# ---- G8-Zusatz (Ruecktragen aus VolkswagenID 0.9.33): Testmeldung an SignalBot (Reiter MQTT unter "Meldungen
# an SignalBot", skoda.py --signal-test). signal_test_thema(), signal_test_auswerten() und signal_test() wie VW;
# brauchen nur config(), broker_anmeldung() bzw. die Nahtstelle _SIGNAL_TEST_SITZUNG.
SIGNAL_TEST_TEXT = "Testmeldung von Skoda Connect (LoxBerry): der Meldeweg an SignalBot funktioniert."
SIGNAL_TEST_WARTEN = 5           # Sekunden, die --signal-test auf die Quittung der SignalBot-Bruecke wartet
_SIGNAL_TEST_SITZUNG = None      # Nahtstelle fuer Proben: Funktion (thema, text, warten) -> Quittungstext oder None


# ---------------------------------------------------------------------------
# Sammelthemen haus/fahrzeug/<name>/... (0.9.36; Regeln/07, Vorbild MGiSmart 1.1.31)
#
# soc, reichweite_km, kabel, laedt, zuhause: retained, ohne Aussage "-" (nie 0, nie leer; Entscheidung Nr. 5).
# zaehler: 0...999 je Minute, NIE retained. Eine kurze Sitzung direkt am Broker mit qos 1, nicht ueber den
# UDP-Eingang (Regeln/07 "Technik"); unabhaengig vom Haken mqtt_ein und vom eigenen Praefix. Zustaende bei einer
# Aenderung und alle 30 Minuten voll, der Zaehler aus dem Wartetakt, also auch zwischen zwei Abrufen.
# Kein Standort, keine VIN. Ein Stand, der aelter als HAUS_FZ_ALT_S ist, ist keine Aussage mehr: "-".
# Abraeumen mit Nachlesen: Haken aus, geaenderter Name, Fahrzeug nicht mehr im Konto, Deinstallation.
# ---------------------------------------------------------------------------
DATEI_HAUS_FZ = PDATA / "haus_fahrzeug.json"
DATEI_KABEL = PDATA / "kabel.json"
HAUS_FZ_FELDER = ("soc", "reichweite_km", "kabel", "laedt", "zuhause")
HAUS_FZ_TAKT_S = 55            # der Wartetakt ruft alle 10 s; so entsteht ein Minutentakt
HAUS_FZ_VOLL_S = 1800
HAUS_FZ_ALT_S = 21600          # 6 h ohne gelungenen Abruf: keine Aussage mehr
KABEL_FRISCH_S = 43200         # die Warnung braucht einen Fahrzeugstand bis 12 h (wie MGiSmart)
DATEI_HAUS_FZ_FREMD = PDATA / "haus_fahrzeug_fremd.json"
HAUS_FZ_LAUSCH_S = 62          # so lange hoert die Pruefung auf fremde Zaehler: jede Linie sendet ihn einmal je Minute
HAUS_FZ_LAUSCH_ABSTAND_S = 3600
_HAUS_FZ_SITZUNG = None        # Nahtstelle fuer Proben: Funktion (nachrichten, lesen, warten, gesehen) -> (ok, behalten)
_HAUS_FZ = {"zaehler": -1, "letzt": 0.0, "lausch": 0.0, "eigene": {}}


def haus_fz_name(name, nr) -> str:
    """<name> nach der Namensregel von Regeln/07; reserviert: zaehler, anbieter. Sonst sk<n>. Rein."""
    s = str(name or "")
    for a, b in (("\u00c4", "ae"), ("\u00d6", "oe"), ("\u00dc", "ue"), ("\u00e4", "ae"), ("\u00f6", "oe"),
                 ("\u00fc", "ue"), ("\u00df", "ss")):
        s = s.replace(a, b)
    s = "".join(c if ("a" <= c <= "z" or "0" <= c <= "9" or c in "_-") else "_" for c in s.lower())[:40]
    if s.strip("_") == "" or s in ("zaehler", "anbieter"):
        return "sk%s" % nr
    return s


def haus_fz_namen(fahrzeuge: dict) -> dict:
    """Nummer -> <name>, je Fahrzeug eindeutig (ein doppelter Name bekommt _<n>). Rein."""
    aus: dict = {}
    for nr in sorted(fahrzeuge, key=lambda n: ganz(n, 0)):
        f = fahrzeuge.get(nr) if isinstance(fahrzeuge.get(nr), dict) else {}
        n = haus_fz_name(f.get("name") or f.get("modell"), nr)
        aus[str(nr)] = "%s_%s" % (n[:36], nr) if n in aus.values() else n
    return aus


def haus_fz_zahl(w) -> str:
    """Zahl >= 0 mit hoechstens einer Nachkommastelle, sonst "-". Rein."""
    if isinstance(w, bool):
        return "-"
    try:
        v = float(w)
    except (TypeError, ValueError):
        return "-"
    if v != v or v < 0 or v == float("inf"):
        return "-"
    return ("%.1f" % v).rstrip("0").rstrip(".")


def haus_fz_ja(w) -> str:
    """Nur 1 oder 0 ist eine Aussage. Rein."""
    return str(int(w)) if isinstance(w, (int, float)) and w in (0, 1) else "-"


def haus_fz_alter(f: dict, stand: dict, jetzt: float):
    """Sekunden seit dem letzten gelungenen Abruf dieses Fahrzeugs, None = unbekannt. Rein."""
    ts = ganz(f.get("ts"), 0) or ganz((stand or {}).get("ts"), 0)
    return None if ts <= 0 else jetzt - ts


def haus_fz_werte(f: dict, stand: dict, jetzt: float) -> dict:
    """Die retained Zustaende eines Fahrzeugs. Ein zu alter oder unbekannter Stand ist ohne Aussage. Rein."""
    alter = haus_fz_alter(f, stand, jetzt)
    if alter is None or alter > HAUS_FZ_ALT_S:
        return {n: "-" for n in HAUS_FZ_FELDER}
    soc = haus_fz_zahl(f.get("soc"))
    if soc != "-" and float(soc) > 100:
        soc = "-"
    return {"soc": soc, "reichweite_km": haus_fz_zahl(f.get("reichweite_km")),
            "kabel": haus_fz_ja(f.get("kabel_verbunden")), "laedt": haus_fz_ja(f.get("laedt")),
            "zuhause": haus_fz_ja(f.get("zuhause"))}


def haus_fz_sitzung(nachrichten: list, lesen=None, warten: float = 0.0, gesehen=None) -> tuple:
    """Eine kurze Sitzung am Broker (Anmeldung aus general.json, nie in einer Befehlszeile).
    nachrichten: [(thema, nutzlast, retain)], qos 1, gewartet wird auf die Bestaetigung (hoechstens 8 s).
    lesen: Themen, deren retained Werte danach gefragt werden. gesehen: Liste, die die fluechtigen Nachrichten dieser
    Themen aufnimmt (thema, wert). Rueckgabe (ok, {thema: wert})."""
    if _HAUS_FZ_SITZUNG is not None:
        return _HAUS_FZ_SITZUNG(nachrichten, lesen, warten, gesehen)
    try:
        import threading  # noqa: PLC0415
        import paho.mqtt.client as mqtt  # noqa: PLC0415
    except ImportError:
        melde_gebremst("haus_fz_paho", "haus/fahrzeug nicht gesendet: paho-mqtt fehlt.", 86400)
        return (False, {})
    b = broker_anmeldung()
    # Jede Sitzung ihre eigene Kennung: die Pruefung auf fremde Zaehler laeuft neben dem Minutentakt, und eine doppelte Kennung wirft der Broker hinaus.
    kennung = "skoda-hausfz-%d-%d" % (os.getpid(), int(time.time() * 1000) % 1000000)
    try:
        k = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=kennung)     # paho 2.x
    except (AttributeError, TypeError):
        k = mqtt.Client(client_id=kennung)                                       # paho 1.x
    if b["auth"]:
        k.username_pw_set(b["auth"]["username"], b["auth"]["password"])
    da, abo = threading.Event(), threading.Event()
    antwort: dict = {"rc": None}
    behalten: dict = {}

    def bei_verbindung(_k, _u, _f, rc, *_r):
        antwort["rc"] = getattr(rc, "value", rc)
        da.set()

    def bei_nachricht(_k, _u, n):
        if getattr(n, "retain", False):
            if n.payload:
                behalten[n.topic] = n.payload.decode("utf-8", "replace")
        elif gesehen is not None:
            gesehen.append((n.topic, n.payload.decode("utf-8", "replace")))

    def bei_abo(*_a):
        abo.set()

    k.on_connect, k.on_message, k.on_subscribe = bei_verbindung, bei_nachricht, bei_abo
    laeuft = False
    try:
        k.connect(b["host"], b["port"], 30)
        k.loop_start()
        laeuft = True
        if not da.wait(5) or antwort["rc"] != 0:
            raise ConnectionError("Broker antwortet nicht oder weist ab")
        marken = [k.publish(t, w if w != "" else None, qos=1, retain=bool(r)) for t, w, r in nachrichten]
        ende = time.time() + 8
        for m in marken:
            while not m.is_published():
                if time.time() > ende:
                    raise TimeoutError("keine Bestaetigung")
                time.sleep(0.02)
        if lesen:
            k.subscribe([(t, 0) for t in lesen])
            abo.wait(3)
            time.sleep(max(0.0, warten))
        return (True, behalten)
    except Exception as err:  # noqa: BLE001
        melde_gebremst("haus_fz_senden", "haus/fahrzeug: Sitzung am Broker gescheitert (%s)." % type(err).__name__, 3600)
        return (False, {})
    finally:
        try:
            k.disconnect()
            if laeuft:
                k.loop_stop()
        except Exception:  # noqa: BLE001
            pass


def haus_fz_staemme(merker: dict) -> list:
    """Die Staemme aus dem Merker, nur unterhalb von haus/fahrzeug/. Rein."""
    aus: list = []
    fz = merker.get("fahrzeuge") if isinstance(merker, dict) else None
    for e in (fz.values() if isinstance(fz, dict) else ()):
        s = e.get("stamm") if isinstance(e, dict) else None
        if isinstance(s, str) and s.startswith("haus/fahrzeug/") and s not in aus:
            aus.append(s)
    return aus


def haus_fz_abraeumen(staemme: list, warten: float = 3.0) -> tuple:
    """Die retained Themen dieser Staemme loeschen und nachlesen. Rueckgabe (rc, Zahl, Rest): 0 bestaetigt, 1 Rest, 2 Broker."""
    themen = [s + "/" + n for s in staemme for n in HAUS_FZ_FELDER]
    if not themen:
        return (0, 0, [])
    ok, _b = haus_fz_sitzung([(t, "", True) for t in themen])
    if not ok:
        return (2, len(themen), themen)
    ok, b = haus_fz_sitzung([], themen, warten)
    if not ok:
        return (2, len(themen), themen)
    rest = sorted(t for t in b if t in themen)
    return (1 if rest else 0, len(themen), rest)


def haus_fz_fremde(staemme: list, warten: float, eigene=None) -> tuple:
    """Hoert warten Sekunden auf <stamm>/zaehler. Ein Wert, den diese Linie nicht gesendet hat, ist ein fremder Zaehler: Unter
    diesem Stamm sendet noch eine andere Linie. Rueckgabe (ok, Liste der Staemme mit fremdem Zaehler)."""
    gesehen: list = []
    ok, _b = haus_fz_sitzung([], [s + "/zaehler" for s in staemme], warten, gesehen)
    if not ok:
        return (False, [])
    eigene = eigene or {}
    aus: list = []
    for t, w in gesehen:
        s = t.rsplit("/", 1)[0]
        if s in staemme and s not in aus and w not in eigene.get(s, ()):
            aus.append(s)
    return (True, aus)


def haus_fz_fremd_lesen() -> dict:
    """Die zuletzt gefundenen Staemme mit fremdem Zaehler: {stamm: Zeit}."""
    d = json_lesen(DATEI_HAUS_FZ_FREMD)
    return {k: v for k, v in d.items() if isinstance(k, str) and k.startswith("haus/fahrzeug/")}


def haus_fz_lausch_lauf(staemme: list) -> None:
    """Einmal je Stunde neben dem Minutentakt. Das Ergebnis liest der Reiter Test; ein sauberer Lauf nimmt den Vermerk zurueck."""
    ok, fremd = haus_fz_fremde(staemme, HAUS_FZ_LAUSCH_S, _HAUS_FZ["eigene"])
    if not ok:
        return
    alt = haus_fz_fremd_lesen()
    neu = {s: int(time.time()) for s in fremd}
    if neu or alt:
        json_schreiben(DATEI_HAUS_FZ_FREMD, neu, 0o600)
    for s in fremd:
        if s not in alt:
            _LOG.warning("%s: hier sendet auch eine andere Linie (fremder Zaehler). Bitte einem Fahrzeug einen anderen Namen geben.", s)


def haus_fz_leeren(warten: float = 3.0, lausch=None) -> int:
    """Deinstallation: die Staemme aus dem Merker und aus dem letzten Stand. Der eigene Dienst ist angehalten: Laeuft unter einem
    Stamm noch ein Zaehler, gehoert er einer anderen Linie, und ihre Themen bleiben stehen. Ausgabe im Format des Installers."""
    staemme = haus_fz_staemme(json_lesen(DATEI_HAUS_FZ))
    fz = json_lesen(DATEI_LOXONE).get("fahrzeuge")
    if isinstance(fz, dict):
        for n in haus_fz_namen(fz).values():
            if "haus/fahrzeug/" + n not in staemme:
                staemme.append("haus/fahrzeug/" + n)
    if not staemme:
        print("<INFO> MQTT: kein Fahrzeug bekannt - unter haus/fahrzeug ist nichts abzuraeumen.")
        return 0
    ok, behalten = haus_fz_sitzung([], [s + "/" + n for s in staemme for n in HAUS_FZ_FELDER], warten)
    if not ok:
        print("<WARNING> MQTT: der Broker war nicht zu erreichen - unter haus/fahrzeug kann noch etwas stehen.")
        return 1
    staemme = [s for s in staemme if any(t.startswith(s + "/") for t in behalten)]
    if not staemme:
        print("<INFO> MQTT: unter haus/fahrzeug steht nichts von diesem Plugin - nachgemessen.")
        return 0
    ok, fremd = haus_fz_fremde(staemme, HAUS_FZ_LAUSCH_S if lausch is None else lausch)
    for s in fremd:
        print("<WARNING> MQTT: unter %s/ sendet noch eine andere Linie (fremder Zaehler) - diese Themen bleiben stehen." % s)
    staemme = [s for s in staemme if s not in fremd]
    if not staemme:
        return 0
    rc, n, rest = haus_fz_abraeumen(staemme, warten)
    if rc == 0:
        print("<OK> MQTT: %d Themen unter haus/fahrzeug geleert (vom Broker bestaetigt)." % n)
        return 0
    if rc == 1:
        print("<WARNING> MQTT: %d Themen unter haus/fahrzeug stehen weiter im Broker." % len(rest))
        return 1
    print("<WARNING> MQTT: der Broker war nicht zu erreichen - unter haus/fahrzeug kann noch etwas stehen.")
    return 1


def haus_fz_takt(cfg: dict, stand: dict, jetzt: float) -> int:
    """Je Minute: Zustaende bei einer Aenderung und alle 30 min voll, der Zaehler immer. Rueckgabe 1 = gesendet."""
    merker = json_lesen(DATEI_HAUS_FZ)
    fremd = haus_fz_fremd_lesen()
    if not cfg.get("haus_fahrzeug_ein"):
        if DATEI_HAUS_FZ.exists():
            # Ein Stamm mit fremdem Zaehler gehoert auch einer anderen Linie: Er bleibt stehen.
            rc, n, _rest = haus_fz_abraeumen([s for s in haus_fz_staemme(merker) if s not in fremd], 1.5)
            if rc == 0:
                _LOG.info("haus/fahrzeug: Haken aus, %d Themen abgeraeumt.", n)
                try:
                    DATEI_HAUS_FZ.unlink()
                except OSError:
                    pass
            else:
                melde_gebremst("haus_fz_aus", "haus/fahrzeug: Haken aus, das Abraeumen gelang noch nicht.", 3600)
        return 0
    fahrzeuge = (stand or {}).get("fahrzeuge") or {}
    if not fahrzeuge:
        return 0                     # kein Fahrzeug: der Zaehler schweigt, das ist die Aussage
    namen = haus_fz_namen(fahrzeuge)
    alt = merker.get("fahrzeuge") if isinstance(merker.get("fahrzeuge"), dict) else {}
    aktuell = ["haus/fahrzeug/" + n for n in namen.values()]
    weg = [s for s in haus_fz_staemme(merker) if s not in aktuell and s not in fremd]
    nachrichten = [(s + "/" + n, "", True) for s in weg for n in HAUS_FZ_FELDER]
    _HAUS_FZ["zaehler"] = (_HAUS_FZ["zaehler"] + 1) % 1000
    neu: dict = {}
    for nr, name in namen.items():
        stamm = "haus/fahrzeug/" + name
        e = alt.get(nr) if isinstance(alt.get(nr), dict) else {}
        werte = haus_fz_werte(fahrzeuge.get(nr) or fahrzeuge.get(int(nr)) or {}, stand, jetzt)
        vorher = e.get("werte") if isinstance(e.get("werte"), dict) else None
        voll = e.get("stamm") != stamm or vorher is None or jetzt - ganz(e.get("zeit"), 0) > HAUS_FZ_VOLL_S
        for n, w in werte.items():
            if voll or str(vorher.get(n)) != w:
                nachrichten.append((stamm + "/" + n, w, True))
        nachrichten.append((stamm + "/zaehler", str(_HAUS_FZ["zaehler"]), False))
        _HAUS_FZ["eigene"][stamm] = (_HAUS_FZ["eigene"].get(stamm, []) + [str(_HAUS_FZ["zaehler"])])[-5:]
        neu[nr] = {"stamm": stamm, "zeit": int(jetzt) if voll else ganz(e.get("zeit"), 0), "werte": werte}
    ok, _b = haus_fz_sitzung(nachrichten)
    if not ok:
        return 0                     # nichts gemerkt: der naechste Lauf sendet es noch einmal
    if neu != alt:
        json_schreiben(DATEI_HAUS_FZ, {"fahrzeuge": neu}, 0o600)
    return 1


def kabel_regeln(cfg: dict) -> tuple:
    """Die Nachtruhe aus den Regeln des Stamms (Block ansage_regeln der Konfiguration): (an, von, bis). Fehlt er oder ist er verbogen: 22 bis 7 Uhr."""
    r = cfg.get("ansage_regeln")
    if isinstance(r, dict):
        v, b = str(r.get("von") or ""), str(r.get("bis") or "")
        if len(v) == 5 and len(b) == 5 and v[2] == ":" and b[2] == ":":
            return (bool(r.get("nachtruhe")), v, b)
    return (True, "22:00", "07:00")


def kabel_nacht(cfg: dict, hm: str) -> bool:
    """Wie ansage_nachtruhe() im Stamm."""
    an, v, b = kabel_regeln(cfg)
    if not an:
        return False
    return (v <= hm < b) if v < b else (hm >= v or hm < b)


def kabel_entscheiden(f: dict, m: dict, cfg: dict, abfahrt_in, jetzt: float, alter) -> tuple:
    """Die Warnung "Kabel vergessen" (Form mg_kabel_entscheiden()): zu Hause, Kabel nicht gesteckt, Akku unter der
    Schwelle, Stand bis 12 h; abends (ab kabel_uhr), am Morgen nach der Nachtruhe oder wenn die Abfahrt naht.
    Unbekannt heisst nie warnen. Hoechstens einmal je Standzeit und Tag. In der Nachtruhe wird nichts verbraucht.
    Rein bis auf die Uhr im Argument. Rueckgabe (faellig, neuer Merker)."""
    m = dict(m or {})
    zu, ka = f.get("zuhause"), f.get("kabel_verbunden")
    if zu == 0 or ka == 1 or _ansage_in_fahrt(f):
        m["seit"], m["gesagt"] = 0, 0
        return (False, m)
    if zu != 1 or ka != 0:
        return (False, m)
    if not m.get("seit"):
        m["seit"] = int(jetzt)
    soc = haus_fz_zahl(f.get("soc"))
    if soc == "-" or float(soc) >= float(ganz(cfg.get("kabel_soc"), 30)) or alter is None or alter > KABEL_FRISCH_S:
        return (False, m)
    z = time.localtime(jetzt)
    hm, tag = time.strftime("%H:%M", z), time.strftime("%Y%m%d", z)
    if m.get("gesagt") or kabel_nacht(cfg, hm) or str(m.get("tag")) == tag:
        return (False, m)
    uhr = str(cfg.get("kabel_uhr") or "")
    if len(uhr) != 5 or uhr[2] != ":":
        uhr = "20:00"
    abends = hm >= uhr
    an, _v, bis = kabel_regeln(cfg)
    morgen = an and hm < "12:00" and int(m["seit"]) < time.mktime(time.strptime(tag + " " + bis, "%Y%m%d %H:%M"))
    grenze = ganz(cfg.get("kabel_abfahrt_min"), 0)
    abfahrt = grenze > 0 and abfahrt_in is not None and 1 <= int(abfahrt_in) <= grenze
    if not abends and not morgen and not abfahrt:
        return (False, m)
    m["gesagt"], m["tag"] = 1, tag
    return (True, m)


def kabel_takt(horcher, cfg: dict, stand: dict, jetzt: float) -> list:
    """Je Minute je Fahrzeug die Warnung pruefen. Ohne Haken geschieht nichts. Rueckgabe: die gewarnten Nummern."""
    if not cfg.get("ansage_kabel_vergessen") and not (cfg.get("signal_ein") and cfg.get("signal_kabel")):
        return []
    fahrzeuge = (stand or {}).get("fahrzeuge") or {}
    alt = json_lesen(DATEI_KABEL)
    neu = dict(alt)
    in_min = None
    if ganz(cfg.get("kabel_abfahrt_min"), 0) > 0 and cfg.get("abfahrt_ein") and horcher is not None:
        in_min, _h = vorklima_minuten(horcher, cfg, jetzt)
    gewarnt = []
    for nr in sorted(fahrzeuge, key=lambda n: ganz(n, 0)):
        f = fahrzeuge[nr]
        if not isinstance(f, dict):
            continue
        faellig, m = kabel_entscheiden(f, alt.get(str(nr)) or {}, cfg, in_min, jetzt, haus_fz_alter(f, stand, jetzt))
        neu[str(nr)] = m
        if faellig:
            gewarnt.append(str(nr))
            name = str(f.get("name") or f.get("modell") or "")[:60]
            soc = int(round(float(f.get("soc"))))
            _LOG.info("Kabel vergessen: Fahrzeug %s steht zu Hause ohne Kabel (Akku %s Prozent).", nr, soc)
            ansage_senden("kabel_vergessen", str(nr), {"name": name, "soc": soc}, cfg)
            text = "%s steht ohne Ladekabel zu Hause, der Akku steht bei %d Prozent." % (name or ("Fahrzeug %s" % nr), soc)
            signal_senden(cfg, "kabel", str(nr), text)
    if neu != alt:
        json_schreiben(DATEI_KABEL, neu, 0o600)
    return gewarnt


def sammel_takt(horcher, cfg: dict, stand: dict) -> None:
    """Aus dem Wartetakt des Dienstes. Eine Stoerung hier haelt nie den Dienst an."""
    jetzt = time.time()
    if jetzt - _HAUS_FZ["letzt"] < HAUS_FZ_TAKT_S:
        return
    _HAUS_FZ["letzt"] = jetzt
    try:
        haus_fz_takt(cfg, stand, jetzt)
    except Exception as err:  # noqa: BLE001
        melde_gebremst("haus_fz", "haus/fahrzeug: %s" % type(err).__name__, 3600)
    try:
        kabel_takt(horcher, cfg, stand, jetzt)
    except Exception as err:  # noqa: BLE001
        melde_gebremst("kabel", "Kabel vergessen: %s" % type(err).__name__, 3600)
    # Einmal je Stunde (und nach dem Start) auf fremde Zaehler hoeren, im eigenen Faden: Der Takt wartet nicht.
    staemme = haus_fz_staemme(json_lesen(DATEI_HAUS_FZ))
    if cfg.get("haus_fahrzeug_ein") and staemme and jetzt - _HAUS_FZ["lausch"] >= HAUS_FZ_LAUSCH_ABSTAND_S:
        import threading  # noqa: PLC0415
        _HAUS_FZ["lausch"] = jetzt
        threading.Thread(target=haus_fz_lausch_lauf, args=(staemme,), daemon=True).start()


def vorklima_sperre(cfg: dict, f: dict) -> str:
    """Warum diese Abfahrt nicht klimatisiert wird: "" (doch), "akku", "kabel". Unbekannt sperrt nie. Rein."""
    grenze = ganz(cfg.get("vorklima_min_soc"), 0)
    soc = haus_fz_zahl(f.get("soc"))
    if grenze > 0 and soc != "-" and float(soc) < grenze:
        return "akku"
    if cfg.get("vorklima_nur_kabel") and f.get("kabel_verbunden") == 0:
        return "kabel"
    return ""


def broker_anmeldung() -> dict:
    """Broker und Anmeldung aus general.json (mqtt_zustand()) - nie in einer Befehlszeile."""
    z = mqtt_zustand()
    return {"host": z.get("broker") or "127.0.0.1", "port": ganz(z.get("brokerport"), 1883) or 1883,
            "auth": ({"username": z["brokeruser"], "password": z.get("brokerpass") or None}
                     if z.get("brokeruser") else None)}


def signal_test_thema(praefix) -> str:
    """'<praefix>/befehl/senden' (Befehl 'senden' der SignalBot-Bruecke, Text als Nutzlast) oder '' (rein)."""
    p = str(praefix or "")
    return "%s/befehl/senden" % p if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", p) else ""


def signal_test_auswerten(quittung) -> str:
    """Quittung der Bruecke -> angenommen | abgelehnt | keine_antwort (rein). Die Bruecke 1.0.2 quittiert
    'angenommen' oder 'abgelehnt: <grund>'; alles andere ist keine verwertbare Antwort."""
    if quittung is None or str(quittung).strip() == "":
        return "keine_antwort"
    q = str(quittung).strip().lower()
    if q.startswith("angenommen"):
        return "angenommen"
    if q.startswith("abgelehnt"):
        return "abgelehnt"
    return "keine_antwort"


def _signal_test_sitzung(thema: str, text: str, warten: float):
    """Eine kurze Sitzung: <thema>/quittung abonnieren, Text senden (retain 0), bis 'warten' s auf die Quittung."""
    import threading
    import paho.mqtt.client as mqtt
    b = broker_anmeldung()
    ergebnis = {"q": None}
    fertig = threading.Event()
    try:
        k = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="skodaconnect-signaltest-%d" % os.getpid())
    except (AttributeError, TypeError):
        k = mqtt.Client(client_id="skodaconnect-signaltest-%d" % os.getpid())
    if b["auth"]:
        k.username_pw_set(b["auth"]["username"], b["auth"]["password"])

    def bei_nachricht(_k, _u, m):
        if not getattr(m, "retain", False):
            ergebnis["q"] = m.payload.decode("utf-8", "replace")
            fertig.set()
    k.on_message = bei_nachricht
    k.connect(b["host"], b["port"], 30)
    k.loop_start()
    try:
        k.subscribe(thema + "/quittung", qos=0)
        time.sleep(0.3)
        k.publish(thema, text, qos=0, retain=False)
        fertig.wait(warten)
    finally:
        k.loop_stop()
        k.disconnect()
    return ergebnis["q"]


def signal_test() -> tuple:
    """(ergebnis, text): aus | nicht_moeglich | angenommen | abgelehnt | keine_antwort. Ab Werk wirkungslos:
    ist 'Meldungen an SignalBot' aus, wird nichts gesendet."""
    cfg = config()
    if not cfg.get("signal_ein"):
        return ("aus", "Meldungen an SignalBot sind aus - es wurde nichts gesendet.")
    thema = signal_test_thema(cfg.get("signal_praefix"))
    if not thema:
        return ("nicht_moeglich", "Das Praefix des SignalBot-Plugins ist ungueltig.")
    try:
        if _SIGNAL_TEST_SITZUNG is not None:
            q = _SIGNAL_TEST_SITZUNG(thema, SIGNAL_TEST_TEXT, SIGNAL_TEST_WARTEN)
        else:
            q = _signal_test_sitzung(thema, SIGNAL_TEST_TEXT, SIGNAL_TEST_WARTEN)
    except ImportError:
        return ("nicht_moeglich", "paho-mqtt fehlt in der virtuellen Umgebung.")
    except Exception as err:  # noqa: BLE001
        return ("nicht_moeglich", "Broker nicht erreichbar (%s)." % type(err).__name__)
    e = signal_test_auswerten(q)
    return (e, mqtt_wert_saeubern(str(q or ""))[:120].replace(";", " "))


# ---- Der Wartetakt (alle 10 s) ----
async def auftrag_ausfuehren(ms, vins: list, cfg: dict, b: dict) -> tuple:
    """Ein Auftrag des Dienstes selbst (Vorklima, Ankunft) - derselbe Weg wie die Warteschlange:
    befehl_ausfuehren() mit Grenze, Neuanmeldung bei 401, Buchung in der Stundenbremse bei Erfolg."""
    try:
        ok, meldung, zusatz = await asyncio.wait_for(befehl_ausfuehren(ms, vins, cfg, b), timeout=GRENZE_BEFEHL)
    except Exception as err:  # noqa: BLE001
        anmeldung_vormerken(err)
        ok, meldung, zusatz = 0, fehlertext(err), {}
    if ok == 1 and zusatz.get("vin"):
        _BREMSE.befehl_buchen(f"{b.get('aktion')}@{zusatz['vin']}", f"{b.get('temp', '')}|{b.get('prozent', '')}")
    return (ok, meldung)


async def g41_takt(ms, vins: list, cfg: dict, merker: dict, stand: dict) -> bool:
    """Vorklimatisierung, Ankunft, Preisprobe, Vorklima-Thema. True = Sofortabruf (Wartetakt verlassen)."""
    jetzt = time.time()
    vorher = json.dumps(merker, sort_keys=True)
    sofort = False
    sammel_takt(_HORCHER, cfg, stand)     # 0.9.36: Sammelthemen und Kabel-Warnung, je Minute
    auftrag = vorklima_takt(_HORCHER, cfg, merker, stand, jetzt)
    if auftrag is not None:
        e_ok, e_meldung = await auftrag_ausfuehren(ms, vins, cfg, auftrag)
        _LOG.info("Vorklimatisierung: ok=%s %s", e_ok, e_meldung)
        vorklima_ergebnis(merker, auftrag, e_ok)
        sofort = auftrag.get("aktion") == "abruf" and e_ok == 1
    if not sofort and ankunft_takt(_HORCHER, cfg, merker, stand, jetzt):
        e_ok, e_meldung = await auftrag_ausfuehren(ms, vins, cfg, {"aktion": "abruf", "anlass": "ankunft"})
        _LOG.info("Ankunft: ok=%s %s", e_ok, e_meldung)
        sofort = e_ok == 1
    ladung_probe(_HORCHER, cfg, jetzt)
    vorklima_melden(cfg, merker, jetzt)
    # Nachtrag 4: Restminuten der Klimatisierung je Minute nachfuehren (nur Geaendertes).
    restminuten_nachfuehren(cfg, jetzt)
    if json.dumps(merker, sort_keys=True) != vorher:
        json_schreiben(DATEI_VORKLIMA, merker, rechte=0o600)
    return sofort


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


def ladung_buchen(nummer: str, f: dict, cfg: dict | None = None) -> None:
    """Bei jedem Durchgang je Fahrzeug aufgerufen."""
    cfg = cfg or {}
    laedt = f.get("laedt")
    soc = f.get("soc")
    offen = _LADEN_OFFEN.get(nummer)

    if laedt == 1:
        # G6-Zusatz: jede Aenderung der offenen Ladung geht sofort in DATEI_MITSCHRIFT (Vergleich vorher/nachher).
        vorher = None if offen is None else json.dumps(offen, sort_keys=True, default=str)
        if offen is None:
            t0 = int(time.time())
            _LADEN_OFFEN[nummer] = {
                "beginn": t0, "start": t0, "soc_von": soc, "kw_max": 0.0,
                "ort": f.get("adresse") or "", "vin": f.get("vin") or "",
                # Gruppe 41 (G6): Ladekosten nur fuer eine Ladung, die ZU HAUSE beginnt, und nur mit
                # "Strompreis vom Spotpreis-Plugin". 1 mitschreiben, 0 unterwegs, -1 ohne Heimzone, -2 aus.
                "haus": ((1 if f.get("zuhause") == 1 else (0 if f.get("zuhause") == 0 else -1))
                         if cfg.get("haus_strompreis_ein") else -2),
                "proben": [],
            }
            offen = _LADEN_OFFEN[nummer]
        kw = f.get("ladeleistung_kw")
        if isinstance(kw, (int, float)) and kw > offen["kw_max"]:
            offen["kw_max"] = float(kw)
        # Gruppe 41 (G6): die zuletzt gemeldete Leistung traegt jede Minutenprobe bis zum naechsten Abruf.
        offen["kw_jetzt"] = float(kw) if isinstance(kw, (int, float)) and not isinstance(kw, bool) else None
        if offen.get("soc_von") is None:
            offen["soc_von"] = soc
        if json.dumps(offen, sort_keys=True, default=str) != vorher:
            ladung_mitschrift_sichern(time.time())
        return

    # laedt ist 0 oder None. None heisst UNBEKANNT - dann wird nichts
    # abgeschlossen: ein ausgefallener Ladeabruf ist kein Ladeende.
    if laedt != 0 or offen is None:
        return
    del _LADEN_OFFEN[nummer]
    ladung_mitschrift_sichern(time.time())      # G6-Zusatz: Eintrag beim Ende aus der Datei
    dauer = int(time.time()) - offen["beginn"]
    if dauer < 120:
        # Zu kurz, um ein Ladevorgang zu sein. Meist ein Flackern im
        # Zustandsfeld zwischen zwei Abrufen.
        return
    # Gruppe 41 (G6): Kosten und Durchschnittspreis aus den Minutenproben (-1 ohne Aussage, nie geschaetzt).
    kosten, preis = ladung_kosten_abschliessen(nummer, offen)
    try:
        DATEI_LADUNGEN.parent.mkdir(parents=True, exist_ok=True)
        neu = not DATEI_LADUNGEN.exists()
        with DATEI_LADUNGEN.open("a", encoding="utf-8") as h:
            if neu:
                h.write("beginn;ende;fahrzeug;vin;soc_von;soc_bis;dauer_min;kw_max;ort;kosten_eur;preis_ct\n")
            # Gruppe 41: kosten_eur;preis_ct hinten angehaengt - alte Zeilen bleiben, leer = unbekannt.
            h.write("%d;%d;%s;%s;%s;%s;%d;%s;%s;%s;%s\n" % (
                offen["beginn"], int(time.time()), nummer, offen["vin"],
                "" if offen["soc_von"] is None else offen["soc_von"],
                "" if soc is None else soc,
                dauer // 60,
                ("%.1f" % offen["kw_max"]) if offen["kw_max"] else "",
                str(offen["ort"]).replace(";", " ").replace("\n", " ")[:120],
                "" if kosten == -1 else kosten, "" if preis == -1 else preis))
    except OSError as err:
        melde_gebremst("ladungen", f"Ladeprotokoll nicht schreibbar: {err}", 3600)


# ---------------------------------------------------------------------------
# Schreibbefehle aus der Warteschlange
#
# Der Loxone-Endpunkt legt hier eine JSON-Datei ab, der Dienst arbeitet sie ab
# und legt die Antwort daneben. Der Endpunkt selbst spricht NIE mit der Cloud.
# ---------------------------------------------------------------------------
def nebendateien_abraeumen(ordner: Path, mindestalter: int = 60) -> int:
    """Nebendateien <ziel>.json.tmp.<pid> eines FREMDEN, TOTEN Schreibers
    abraeumen, die mindestens 'mindestalter' Sekunden alt sind (C7).

    Die Nebendatei eines lebenden Vorgangs gehoert ihm - er benennt sie gleich
    um. Die eigene ebenso. Rueckgabe: Zahl der entfernten Dateien.
    """
    n = 0
    jetzt = time.time()
    for p in ordner.glob("*.json.tmp.*"):
        m = re.match(r"^.+\.json\.tmp\.([0-9]+)$", p.name)
        if not m:
            continue
        pid = int(m.group(1))
        if pid == os.getpid() or Path("/proc", str(pid)).exists():
            continue
        try:
            if jetzt - p.stat().st_mtime < mindestalter:
                continue
            p.unlink()
            n += 1
        except OSError:
            pass
    return n


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
    # UND DIE NEBENDATEIEN HEUTIGER BAUART (C7, Durchgang 01.10.2026).
    # json_schreiben() haengt seit 01.09.2026 die Prozessnummer an
    # (<kennung>.json.tmp.<pid>); die beiden Muster oben fingen sie nie ein -
    # gemessen: c.json.tmp.4711, zwei Stunden alt, blieb liegen
    # (skoda_agenten/code/_agent/m8_nebendatei.py).
    nebendateien_abraeumen(ORDNER_ANTWORTEN)
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


def vin_waehlen(vins: list[str], nummer_oder_vin, karte: dict | None = None) -> str | None:
    """Nimmt entweder die FESTE Fahrzeugnummer oder die VIN selbst.

    DIE NUMMER IST DIE AUS nummern_zuordnen(), NICHT DIE STELLE IN DER LISTE
    (C1, Durchgang 01.10.2026). Bis 0.9.28 stand hier "vins[n - 1]": gelesen
    wurde ueber die feste Nummer aus zustand.json, geschaltet ueber die Stelle
    in der sortierten VIN-Liste. Gemessen (skoda_agenten/code/_agent/
    m1_fahrzeugnummer.py): kam ein zweites Auto mit kleinerer VIN dazu, las
    fahrzeug=1 die Werte des einen und klimatisierte das andere; verliess
    Auto 1 das Konto, schaltete fahrzeug=1 das verbliebene Auto 2 - beides mit
    OK=1. Gilt fuer den Endpunkt, die Knoepfe im Reiter Test und die
    Vorklimatisierung zur Abfahrtszeit gleichermassen.

    Gehoert die Nummer zu einer VIN, die das Konto gerade nicht fuehrt, gibt
    es kein Ziel (None) - geraten wird nicht.
    """
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
    if n < 1:
        return None
    if karte is None:
        karte = nummern_zuordnen(vins)
    for vin, nr in karte.items():
        if nr == n:
            for v in vins:
                if v.upper() == str(vin).upper():
                    return v
            return None
    return None


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
    # Welche Endpunkte haben IN DIESEM ABRUF geantwortet? Nur deren fehlende
    # Felder gelten als "ohne Aussage" (M1/M2) - ein ausgefallener Endpunkt
    # laesst seine Felder wie bisher stehen (Nr. 8).
    geliefert: list[str] = []

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
            geliefert.append("laden")
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
            geliefert.append("klima")
            d.update(abbild_klima(ac))

    if kann(stamm, "PARKING_POSITION"):
        po = await endpunkt(ausfaelle, "position", ms.get_positions(vin))
        if po is not None:
            geliefert.append("position")
            d.update(abbild_position(po))

    if kann(stamm, "VEHICLE_HEALTH_WARNINGS") or kann(stamm, "WARNING_LIGHTS"):
        he = await endpunkt(ausfaelle, "gesundheit", ms.get_health(vin))
        if he is not None:
            geliefert.append("gesundheit")
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
    d["geliefert"] = geliefert
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
    # Gruppe 41 (0.9.34): Vorklimatisierung (0 nichts, 1 gesendet, 2 mild, 3 Wiederholung,
    # 4 wartet auf Anwesenheit, -1 gescheitert) und Kosten/Preis der letzten Ladung zu Hause
    # (-1 ohne Aussage). Sie stehen nicht im Abbild; g41_wert() liefert sie.
    "vorklima", "ladung_kosten", "ladung_preis",
    # Nachtrag 4 (29.10.2026): Restminuten bis die Klimatisierung die Zieltemperatur erreicht
    # (aus ziel_erreicht_um; -1 ohne Aussage, 0 nach dem Ende). Nicht im Abbild.
    "klima_restzeit_min",
)

# Textthemen. Sie stehen getrennt, weil eine LEERE Nutzlast mit 'retain' ein
# behaltenes Thema loescht - ein leerer Text wird deshalb gar nicht gesendet.
MQTT_TEXTFELDER = (
    "modell", "kennzeichen", "ladezustand", "klima_zustand", "adresse",
    "warnleuchten_text",
)


# Die Signalthemen JE FAHRZEUG (M3, Durchgang 01.10.2026; Nr. 26, Nr. 4):
# fahrzeugN/ok (1 = der letzte Abruf dieses Fahrzeugs ist gelungen) und
# fahrzeugN/ts (Zeitstempel seines letzten Erfolgs). Beide fluechtig - "ok" und
# "ts" stehen in MQTT_OHNE_RETAIN - und beide in JEDEM Durchgang. Damit ist der
# MQTT-Weg dem Endpunkt gleichwertig, der OK und ALTER je Fahrzeug fuehrt. Neue
# Namen, keine umgedeutete alte (CLAUDE.md, Abschnitt 4).
MQTT_SIGNALFELDER = (
    "ok", "ts",
)

# Zustaende ohne Aussage (M1/M2, Entscheidung 5 und Nr. 8): liefert ein
# GELUNGENER Abruf des zugehoerigen Endpunkts das Feld nicht, geht einmal "-"
# retained hinaus - nie eine leere Nutzlast und nie der stehenbleibende Altwert.
# Gemessen bis 0.9.28: warnleuchten_text blieb nach dem Erloeschen der Leuchte
# auf "ENGINE", zuhause bei einer Position ohne Fahrzeugeintrag auf 1
# (skoda_agenten/mqtt/_agent/messung_1.txt, W2 und Z2).
OHNE_AUSSAGE = {
    "warnleuchten_text": "gesundheit",
    "ladezustand": "laden",
    "klima_zustand": "klima",
    "adresse": "position",
    "breite": "position",
    "laenge": "position",
    "zuhause": "position",
    "heim_entfernung_m": "position",
}
# Nur Aenderungen, der volle Satz alle 30 Minuten (M7, Nr. 26). Lebenszeichen
# und fahrzeugN/ok, fahrzeugN/ts gehen in jedem Durchgang hinaus.
VOLLSATZ_SEKUNDEN = 1800
_MQTT_GESENDET: dict[str, tuple] = {}
_MQTT_VOLL = {"ts": 0.0}


# ---------------------------------------------------------------------------
# Gruppe 41, Nachtrag 4 (29.10.2026) - Restminuten und die -1-Regel
#
# RESTMINUTEN: Skoda liefert fuer das Laden die Minuten selbst (restzeit_min, seit jeher). Fuer die
# Klimatisierung fuehrt das Abbild eine Endzeit (ziel_erreicht_um, Unix-Zeit); die Minuten bis dahin gehen jetzt
# als klima_restzeit_min hinaus - gleich benannt wie bei Audi und VW. Ganze Minuten (aufgerundet), >= 0; ohne
# Aussage -1; liegt das Ende in der Vergangenheit 0. Beim Abruf gerechnet und je Minute aus g41_takt()
# nachgefuehrt (restminuten_nachfuehren()); bei einer Stoerung nicht.
#
# -1-REGEL (wie BYD 0.9.29; Regeln/07 "MinVal=-1 fuer Felder, die -1 als nicht bekannt senden"): ein MESSWERT
# (fluechtig nach MQTT_OHNE_RETAIN, Zahl), fuer den ein gelieferter Endpunkt keine Aussage hat, geht als -1 hinaus.
# Bis hier ging er gar nicht, und in Loxone stand der letzte Wert und sah gemessen aus. aussentemperatur -999 (-1
# Grad ist eine echte Temperatur). Hat der Endpunkt nicht geliefert, bleibt der Altwert stehen wie bisher.
# Zustaende ohne Aussage bleiben "-" (OHNE_AUSSAGE) bzw. ungesendet, Texte unveraendert. Nur MQTT.
# ---------------------------------------------------------------------------
MQTT_FEHLWERT = {"aussentemperatur": -999}
MQTT_MESSWERT_ENDPUNKT = {
    "ladeleistung_kw": "laden", "ladetempo_kmh": "laden", "restzeit_min": "laden",
    "aussentemperatur": "klima", "klima_restzeit_min": "klima",
}
# Aussagen des Dienstes - die Regel laesst sie in Ruhe. vorklima traegt -1 schon als "gescheitert".
MQTT_OHNE_FEHLWERT = ("ok", "ts", "vorklima")
_RESTMIN = {"quelle": {}, "gesendet": {}}


def restminuten(ende, jetzt: float) -> int:
    """Ganze Minuten bis 'ende' (Unix-Zeit), aufgerundet; 0 nach dem Ende, -1 ohne Aussage (rein)."""
    if isinstance(ende, bool):
        return -1
    try:
        e = int(ende)
    except (TypeError, ValueError, OverflowError):
        return -1
    if e <= 0:
        return -1
    if e <= jetzt:
        return 0
    return int(math.ceil((e - jetzt) / 60.0))


def mqtt_messwert(feld: str, wert, geliefert=None):
    """Der Wert eines Fahrzeugthemas fuer MQTT nach der -1-Regel (rein). None heisst: nicht senden."""
    if wert is not None and not (isinstance(wert, str) and wert.strip() == ""):
        return wert
    if feld not in MQTT_FELDER or not mqtt_ohne_retain(feld) or feld in MQTT_OHNE_FEHLWERT:
        return None
    ep = MQTT_MESSWERT_ENDPUNKT.get(feld, "")
    if ep and ep not in (geliefert or []):
        return None             # Endpunkt hat nicht geliefert: der Altwert bleibt stehen
    return MQTT_FEHLWERT.get(feld, -1)


def restminuten_nachfuehren(cfg: dict, jetzt=None) -> tuple:
    """Je Minute aus g41_takt(): klima_restzeit_min aus der zuletzt gemeldeten Endzeit neu rechnen und nur
    Geaendertes senden; der Aenderungsfilter (_MQTT_GESENDET) erfaehrt es. Bei einer Stoerung leer."""
    if not cfg.get("mqtt_ein") or not _RESTMIN["quelle"]:
        return (0, 0)
    jetzt = time.time() if jetzt is None else jetzt
    p = {}
    for nummer, q in _RESTMIN["quelle"].items():
        for thema, ende in q.items():
            k = "fahrzeug%s/%s" % (nummer, thema)
            w = restminuten(ende, jetzt)
            if _RESTMIN["gesendet"].get(k) != w:
                p[k] = w
    if not p:
        return (0, 0)
    _RESTMIN["gesendet"].update(p)
    praefix = thema_saeubern(cfg.get("mqtt_topic"))
    retain = 1 if cfg.get("mqtt_retain") else 0
    versucht, schlecht = mqtt_senden(p, praefix, retain)
    mqtt_gesendet_merken(p, praefix, retain, False, versucht, schlecht)
    return (versucht, schlecht)


def mqtt_fahrzeugpaare(nummer, f: dict, cfg: dict) -> dict:
    """Die Themen EINES Fahrzeugs (M1-M3).

    Ein Fahrzeug mit ok = 0 bekommt nur sein Signal: die Zustaende bleiben
    retained stehen, Messwerte mit Zeitbezug gehen nicht neu hinaus (bis 0.9.28
    gingen seine Altwerte in jedem Lauf frisch aussehend hinaus - gemessen
    "ladeleistung_kw 11.0" eines seit 24 h ausgefallenen Wagens).
    """
    p = {f"fahrzeug{nummer}/ok": 1 if f.get("ok") else 0,
         f"fahrzeug{nummer}/ts": ganz(f.get("ts"), 0)}
    if not f.get("ok"):
        return p
    geliefert = f.get("geliefert") or []
    heim = cfg.get("heim_breite") not in ("", None) and cfg.get("heim_laenge") not in ("", None)
    for feld in MQTT_FELDER + MQTT_TEXTFELDER:
        if feld == "klima_restzeit_min":
            # Nachtrag 4: aus der Endzeit der Klimatisierung (nicht im Abbild).
            ende = f.get("ziel_erreicht_um")
            w = None if ende is None else restminuten(ende, time.time())
        else:
            w = g41_wert(nummer, feld, f)
        if w is None or str(w).strip() == "":
            m = mqtt_messwert(feld, None, geliefert)
            if m is not None:
                # Nachtrag 4: Messwert ohne Aussage -> -1 (Temperatur -999).
                p[f"fahrzeug{nummer}/{feld}"] = m
                continue
            ep = OHNE_AUSSAGE.get(feld)
            if not ep or ep not in geliefert:
                continue
            if feld in ("zuhause", "heim_entfernung_m") and not heim:
                # Ohne Heimatort gibt es diese beiden Aussagen gar nicht.
                continue
            w = "-"
        p[f"fahrzeug{nummer}/{feld}"] = w
    return p


def mqtt_entfernt_paare(entfernt) -> dict:
    """M4: die retained Themen eines entfernten Fahrzeugs einmal auf "-"."""
    p = {}
    for nr in entfernt or []:
        for feld in MQTT_FELDER + MQTT_TEXTFELDER:
            if not mqtt_ohne_retain(feld):
                p[f"fahrzeug{nr}/{feld}"] = "-"
    return p


def mqtt_aenderungen(immer: dict, fahrzeug: dict, praefix: str, retain: int) -> tuple:
    """Was in diesem Durchgang hinausgeht (M7): 'immer' ganz, aus 'fahrzeug'
    nur, was sich gegenueber dem zuletzt Gesendeten geaendert hat - es sei
    denn, der Vollsatz ist faellig. Rueckgabe (paare, vollsatz)."""
    voll = time.time() - _MQTT_VOLL["ts"] >= VOLLSATZ_SEKUNDEN
    aus = dict(immer)
    for k, v in fahrzeug.items():
        if v is None:
            continue
        signal = k.rsplit("/", 1)[-1] in MQTT_SIGNALFELDER
        stand = (mqtt_wert_saeubern(v), 1 if (retain and not mqtt_ohne_retain(k)) else 0)
        if voll or signal or _MQTT_GESENDET.get(f"{praefix}/{k}") != stand:
            aus[k] = v
    return aus, voll


def mqtt_gesendet_merken(paare: dict, praefix: str, retain: int, voll: bool,
                         versucht: int, schlecht: int) -> None:
    """Erst merken, wenn wirklich etwas hinausging - sonst ginge nach einem
    fehlenden UDP-Port eine Aenderung erst mit dem naechsten Vollsatz hinaus."""
    if versucht <= 0 or schlecht:
        return
    for k, v in paare.items():
        if v is None:
            continue
        _MQTT_GESENDET[f"{praefix}/{k}"] = (mqtt_wert_saeubern(v),
                                            1 if (retain and not mqtt_ohne_retain(k)) else 0)
    if voll:
        _MQTT_VOLL["ts"] = time.time()


def mqtt_praefix_pflegen(cfg: dict, warten: float = 3.0) -> list:
    """Altes Praefix vormerken und am Broker abraeumen (M5, Nr. 26).

    Bis 0.9.28 raeumte der Reiter MQTT beim Praefixwechsel, bei "MQTT aus" und
    bei "Werte behalten aus" nichts ab und merkte sich kein altes Praefix;
    mqtt_leeren() leerte bei der Deinstallation nur das aktuelle (gemessen:
    89 Loeschbefehle unter auto/skoda/, 0 unter skoda/). Jetzt fuehrt
    zustand.json, unter welchem Praefix zuletzt retained gesendet wurde
    ('mqtt_retain_praefix'), und die noch abzuraeumenden ('mqtt_vorgemerkt').
    zustand.json uebersteht jedes Upgrade (preupgrade.sh rettet sie), und die
    Deinstallation leert alle vorgemerkten. Abgeraeumt wird am Broker mit
    Nachlesen (_broker_leeren); ein Fehlschlag bleibt vorgemerkt und wird
    stuendlich erneut versucht. Rueckgabe: die noch vorgemerkten Praefixe.
    """
    z = json_lesen(DATEI_ZUSTAND)
    aktiv = cfg.get("mqtt_ein") and cfg.get("mqtt_retain")
    jetzt_p = thema_saeubern(cfg.get("mqtt_topic")) if aktiv else ""
    vorher = z.get("mqtt_retain_praefix")
    if not isinstance(vorher, str):
        # Erster Lauf nach dem Update: was frueher galt, weiss niemand.
        vorher = jetzt_p
    liste = [p for p in (z.get("mqtt_vorgemerkt") or []) if isinstance(p, str) and p]
    neu_dazu = False
    if vorher and vorher != jetzt_p and vorher not in liste:
        liste.append(vorher)
        neu_dazu = True
        _LOG.info("MQTT: retained Werte unter '%s/' zum Abraeumen vorgemerkt (%s).", vorher,
                  "Praefix gewechselt" if jetzt_p else
                  ("MQTT aus" if not cfg.get("mqtt_ein") else "Werte behalten aus"))
    liste = [p for p in liste if p != jetzt_p]
    versuch = ganz(z.get("mqtt_vormerk_versuch"), 0)
    if liste and (neu_dazu or time.time() - versuch >= 3600):
        rest = []
        for p in liste:
            erg = _broker_leeren(p, lambda t, p=p: bool(mqtt_eigenes_thema(p, t)), warten)
            if erg["rc"] == 0:
                _LOG.info("MQTT: unter '%s/' %d retained Themen am Broker geloescht und "
                          "nachgelesen.", p, len(erg["geleert"]))
            else:
                rest.append(p)
                melde_gebremst("mqtt_vorgemerkt_" + p,
                               f"MQTT: retained Werte unter '{p}/' liessen sich noch nicht "
                               f"abraeumen - {erg['grund'] or 'es blieb etwas stehen'}. Sie "
                               f"bleiben vorgemerkt (auch fuer die Deinstallation).",
                               86400 if erg.get("ohne_paho") else 3600)
        liste = rest
        versuch = int(time.time()) if rest else 0
    if (z.get("mqtt_retain_praefix") != jetzt_p or z.get("mqtt_vorgemerkt") != liste
            or ganz(z.get("mqtt_vormerk_versuch"), 0) != versuch):
        zustand_schreiben(mqtt_retain_praefix=jetzt_p, mqtt_vorgemerkt=liste,
                          mqtt_vormerk_versuch=versuch)
    return liste


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


def lebenszeichen_senden(paare: dict, praefix: str, retain: int) -> tuple[int, int]:
    """mqtt_senden() mit dem einmaligen Abraeumen der Altwerte.

    ERST abraeumen, DANN senden: der Broker reicht die Loeschung an das
    Gateway weiter, das Gateway als leeren Wert an den Miniserver (Regeln/07,
    am Geraet gemessen 06.09.2026) - der gueltige Wert muss unmittelbar
    hinterher. Das leistet der mqtt_senden()-Aufruf im selben Durchgang.

    Abgeraeumt wird AUCH bei "Werte behalten" aus: der Altwert stammt aus der
    Zeit, als der Schalter an war, und ein fluechtiges publish ersetzt ihn
    nicht. Der Merker 'retain_altlast' steht in zustand.json (preupgrade.sh
    rettet die Datei ueber jedes Upgrade) und faellt erst, wenn das Nachlesen
    am Broker nichts mehr findet. Bis 0.9.24 hing der Merker
    'retain_geraeumt' am blossen sendto() eines UDP-Datagramms; verwarf das
    Gateway es, stand der Altwert trotz Merker (in WSL gemessen 24.09.2026,
    Pruefung-Skoda-Connect-NG-0.9.25, Faelle A3 und A4). Jener Merker
    wird nicht gelesen (Fall A8).
    """
    try:
        mqtt_altlast_abraeumen(praefix)
    except Exception as err:  # noqa: BLE001
        melde_gebremst("retain_altlast",
                       f"MQTT: Abraeumen der Altwerte uebersprungen ({fehlertext(err)}).")
    return mqtt_senden(paare, praefix, retain)


def abbild_schreiben(stand: dict, cfg: dict, ok: int, fehler: str = "",
                     fehler_folge: int = 0, zaehler: int = 0, empfehlung=None,
                     entfernt=None) -> dict:
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
    json_schreiben(DATEI_LOXONE, lox, rechte=0o600)

    # Vollstaendiges Abbild fuer die Fehlersuche. Zugangsdaten stehen hier
    # nicht drin - die fuehrt die Bibliothek getrennt.
    # DER ZEITSTEMPEL IST DER DES STANDES, nicht der der Schreibung.
    # Bis 0.9.14 bekam cache.json in JEDEM Lauf ein frisches "ts" - auch bei
    # ok=0 und mit den ALTEN Fahrzeugwerten daneben. Drei Zeilen weiter oben
    # steht die Begruendung, warum genau das nicht sein darf. Wer die Datei
    # zur Fehlersuche aufschlaegt, liest sonst ein Alter, das es nicht gibt.
    # 0600 seit dem Durchgang 01.10.2026 (C4): beide Dateien tragen Standort
    # und Anschrift des Wagens.
    json_schreiben(DATEI_CACHE, {"ts": int(stand.get("ts") or 0), "ok": ok,
                                 "geschrieben": int(time.time()),
                                 "fehler": fehler, "fahrzeuge": fahrzeuge}, rechte=0o600)

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
        _RESTMIN["quelle"] = {}     # Nachtrag 4: bei einer Stoerung nichts nachfuehren
        # Bei einer Stoerung nur das Lebenszeichen senden. Die alten Messwerte
        # erneut zu veroeffentlichen liesse sie frisch aussehen. Dazu das Signal
        # je Fahrzeug (M3) und das "-" fuer ein entferntes Fahrzeug (M4) - die
        # Fahrzeugliste kann in einem sonst gescheiterten Lauf gekommen sein.
        if cfg.get("mqtt_ein"):
            paare = dict(lebenszeichen)
            for nummer, f in fahrzeuge.items():
                paare[f"fahrzeug{nummer}/ok"] = 0
                paare[f"fahrzeug{nummer}/ts"] = ganz(f.get("ts"), 0)
            paare.update(mqtt_entfernt_paare(entfernt))
            versucht, schlecht = lebenszeichen_senden(paare, praefix, retain)
            lox["mqtt_versucht"], lox["mqtt_schlecht"] = versucht, schlecht
            json_schreiben(DATEI_LOXONE, lox, rechte=0o600)
        return lox

    try:
        verlauf_aufraeumen(cfg["verlauf_tage"])
    except (OSError, TypeError, ValueError):
        pass

    for nummer, f in fahrzeuge.items():
        try:
            ladung_buchen(str(nummer), f, cfg)
        except (TypeError, ValueError, KeyError) as err:
            melde_gebremst("ladung_buchen", f"Ladeprotokoll: {err}", 3600)
        try:
            verlauf_anhaengen(int(nummer), f.get("soc"), f.get("reichweite_km"),
                              cfg["verlauf_tage"], f.get("tank_prozent"))
        except (TypeError, ValueError):
            pass

    if cfg.get("mqtt_ein"):
        # M1-M4 und M7 (Durchgang 01.10.2026): je Fahrzeug mqtt_fahrzeugpaare(),
        # gesendet wird nur, was sich geaendert hat, der volle Satz alle 30 min.
        immer = dict(lebenszeichen)
        immer.update(mqtt_entfernt_paare(entfernt))
        fz_paare: dict = {}
        for nummer, f in fahrzeuge.items():
            fz_paare.update(mqtt_fahrzeugpaare(nummer, f, cfg))
        # Nachtrag 4: Endzeiten fuer das Nachfuehren je Minute (nur Fahrzeuge mit ok 1).
        _RESTMIN["quelle"] = {str(nr): {"klima_restzeit_min": f.get("ziel_erreicht_um")}
                              for nr, f in fahrzeuge.items()
                              if f.get("ok") and f.get("ziel_erreicht_um") is not None}
        _RESTMIN["gesendet"] = {k: v for k, v in fz_paare.items() if k.endswith("/klima_restzeit_min")}
        paare, voll = mqtt_aenderungen(immer, fz_paare, praefix, retain)
        versucht, schlecht = lebenszeichen_senden(paare, praefix, retain)
        mqtt_gesendet_merken(paare, praefix, retain, voll, versucht, schlecht)
        lox["mqtt_versucht"], lox["mqtt_schlecht"] = versucht, schlecht
        json_schreiben(DATEI_LOXONE, lox, rechte=0o600)

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


# ---------------------------------------------------------------------------
# Sprachausgabe (Nr. 36 b, Stufe 2, seit 0.9.30)
#
# Der Dienst sagt einzelne Ereignisse an - ueber die gemeinsame Sprachausgabe
# der Plugins dieses Hauses (webfrontend/html/sprachausgabe.php). Die gibt es
# nur in PHP; gesprochen wird deshalb ueber die Bruecke bin/sk_ansage.php. Der
# Auftrag geht ueber die STANDARDEINGABE, nie ueber die Kommandozeile (die
# sieht jeder in der Prozessliste), und er traegt keinen Text: den Satz baut
# die Bruecke aus der Sprachdatei. Ob und wohin gesprochen wird, entscheidet
# die Bruecke aus dem Block tts der Konfiguration (ab Werk aus). Der Dienst
# sieht dort nur nach, ob die Ausgabe aus ist - dann ruft er gar nicht erst.
#
# Angesagt wird nur ein WECHSEL, nie ein Wert im Takt (Bauform wie
# VolkswagenID 0.9.29):
#   laden_fertig   laedt 1 -> 0, Ladestand nicht nachweislich unter der Ladegrenze
#   laden_abbruch  laedt 1 -> 0 und Ladestand mehr als 1 Punkt unter der Ladegrenze,
#                  oder Ladezustand ERROR bzw. CHARGING_INTERRUPTED
#   offen          nicht in Fahrt und unverriegelt, Tuer oder Fenster offen - im
#                  zweiten Abruf in Folge
#   licht          nicht in Fahrt und Licht an - im zweiten Abruf in Folge
#   klima          Klimatisierung 1 -> 0, nicht waehrend der Fahrt
#   ausfall        der dritte gescheiterte Abruf in Folge, erst nachdem seit dem
#                  Start wenigstens einer gelungen ist
# "In Fahrt" heisst: in_bewegung = 1 oder zuendung_an = 1 (abbild_verbindung()).
# Die erste Beobachtung eines Fahrzeugs nach dem Start setzt nur den
# Ausgangsstand: ein Neustart spricht nie. Jeder Anlass hat einen eigenen Haken
# (ansage_<anlass>) und eine Wiederholsperre je Anlass und Fahrzeug
# (ANSAGE_SPERRE_S), die einen Neustart des Dienstes ueberlebt. MQTT, Loxone
# und das Abbild laufen davor und unabhaengig davon.
# ---------------------------------------------------------------------------
SKRIPT_ANSAGE = SELF / "sk_ansage.php"
DATEI_ANSAGE_SPERRE = PDATA / "ansage_sperre.json"
ANSAGE_ANLAESSE = ("laden_fertig", "laden_abbruch", "offen", "licht", "klima", "ausfall", "kabel_vergessen")
ANSAGE_SPERRE_S = 3600     # nur noch SignalBot: je Ereignis und Fahrzeug einmal je Stunde. Die Ansage regelt der Stamm (Welle S4).
ANSAGE_FRIST_S = 25        # Bruecke: PHP-Start plus Sprechfrist 20 s (sk_ansage_k(); Modul 1.2.1: in jedem Weg, B1)
ANSAGE_FOLGE = 2           # offen, licht: so viele Abrufe in Folge
ANSAGE_AUSFALL_FOLGE = 3   # dieselbe Grenze wie die Bremse nach Fehlversuchen
ANSAGE_LADEN_STOERUNG = ("ERROR", "CHARGING_INTERRUPTED")
_ANSAGE_STAND: dict = {}   # je Fahrzeugnummer der zuletzt gesehene Stand - nur im Speicher
_ANSAGE_DIENST = {"ok_gesehen": False, "fehler_folge": 0}


def _ansage_in_fahrt(f: dict) -> bool:
    return f.get("in_bewegung") == 1 or f.get("zuendung_an") == 1


def ansage_ereignisse(nr: str, f: dict) -> list:
    """Die Anlaesse eines Fahrzeugs aus dem Vergleich mit dem zuletzt gesehenen
    Stand. Nur ein frisches Abbild (ok=1) kommt hierher. Rueckgabe: Liste von
    (anlass, daten) - daten ohne Text, nur Name, Ladestand und Ladegrenze."""
    alt = _ANSAGE_STAND.get(nr)
    vorher = alt or {}
    offen_jetzt = (not _ansage_in_fahrt(f)) and (
        f.get("verriegelt") == 0 or f.get("tueren_offen") == 1 or f.get("fenster_offen") == 1)
    licht_jetzt = (not _ansage_in_fahrt(f)) and f.get("licht_an") == 1
    neu = {
        # Ein unbekannter Zustand (None) laesst den bekannten stehen.
        "laedt": f.get("laedt") if f.get("laedt") is not None else vorher.get("laedt"),
        "klima": f.get("klima_an") if f.get("klima_an") is not None else vorher.get("klima"),
        # Die erste Beobachtung zaehlt als schon gemeldet: ein Fahrzeug, das beim Start
        # offen steht, wird nicht angesagt.
        "offen": (vorher.get("offen", 0) + 1 if alt is not None else ANSAGE_FOLGE) if offen_jetzt else 0,
        "licht": (vorher.get("licht", 0) + 1 if alt is not None else ANSAGE_FOLGE) if licht_jetzt else 0,
    }
    _ANSAGE_STAND[nr] = neu
    if alt is None:
        return []
    name = str(f.get("name") or f.get("modell") or "")[:60]
    aus = []
    if vorher.get("laedt") == 1 and neu["laedt"] == 0:
        soc, grenze = f.get("soc"), f.get("ladegrenze")
        try:
            unter = soc is not None and grenze is not None and float(soc) < float(grenze) - 1
        except (TypeError, ValueError):
            unter = False
        stoerung = str(f.get("ladezustand") or "").upper() in ANSAGE_LADEN_STOERUNG
        if unter or stoerung:
            aus.append(("laden_abbruch", {"name": name,
                                          "soc": soc if unter else None,
                                          "grenze": grenze if unter else None}))
        else:
            aus.append(("laden_fertig", {"name": name, "soc": soc}))
    if neu["offen"] == ANSAGE_FOLGE:
        aus.append(("offen", {"name": name}))
    if neu["licht"] == ANSAGE_FOLGE:
        aus.append(("licht", {"name": name}))
    if vorher.get("klima") == 1 and neu["klima"] == 0 and not _ansage_in_fahrt(f):
        aus.append(("klima", {"name": name}))
    return aus


def ansage_ausfall(ok: int, fehler_folge: int) -> bool:
    """Ist das der Abruf, mit dem die Daten als ausgefallen gelten?"""
    d = _ANSAGE_DIENST
    vorher = d["fehler_folge"]
    d["fehler_folge"] = fehler_folge
    if ok:
        d["ok_gesehen"] = True
        return False
    return bool(d["ok_gesehen"]) and vorher < ANSAGE_AUSFALL_FOLGE <= fehler_folge


def _ansage_aus(cfg: dict) -> bool:
    """Ist die Ausgabe aus? Nur der Modus wird angesehen (config() reicht den Block
    tts unveraendert durch); geprueft wird er in der Bruecke. Fehlt er oder ist er
    unlesbar, gilt er als aus (Vorgabe)."""
    t = cfg.get("tts")
    # Stamm 1.3.2: nie gespeichert heisst ab Werk an; ein gespeichertes "aus" bleibt.
    return isinstance(t, dict) and t.get("mode", "aus") == "aus"


def _ansage_sperre(schluessel: str, jetzt: int) -> bool:
    """Gesperrt? Sonst wird die Sperre gesetzt (und abgelaufene Eintraege fallen weg)."""
    s = json_lesen(DATEI_ANSAGE_SPERRE)
    t = s.get(schluessel)
    if isinstance(t, (int, float)) and not isinstance(t, bool) and 0 <= jetzt - t < ANSAGE_SPERRE_S:
        return True
    s = {k: v for k, v in s.items()
         if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= jetzt - v < ANSAGE_SPERRE_S}
    s[schluessel] = jetzt
    json_schreiben(DATEI_ANSAGE_SPERRE, s)
    return False


def ansage_senden(anlass: str, nr: str, daten: dict, cfg: dict) -> None:
    """Einen Anlass ueber die Bruecke ansagen. Ins Protokoll kommen Anlass,
    Fahrzeugnummer und das Ergebnis (Stand, Art, HTTP, Zeichenzahl, Kennung) -
    nie der Text, nie ein Token."""
    if anlass not in ANSAGE_ANLAESSE or not cfg.get("ansage_" + anlass):
        return
    if _ansage_aus(cfg):
        return
    # Stamm 1.3.2: Sperre, Nachtruhe und Schalter stehen im Stamm; die Bruecke legt nur hin.
    auftrag = {"anlass": anlass, "nr": ganz(nr, 0), "name": str(daten.get("name") or "")}
    for k in ("soc", "grenze"):
        v = daten.get(k)
        auftrag[k] = v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    try:
        e = subprocess.run(["php", str(SKRIPT_ANSAGE), PNAME],
                           input=json.dumps(auftrag, ensure_ascii=False).encode("utf-8"),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=ANSAGE_FRIST_S, check=False)
    except (OSError, subprocess.SubprocessError) as err:
        melde_gebremst("ansage_ruf", "Ansage %s (Fahrzeug %s): die Bruecke sk_ansage.php war "
                                     "nicht aufrufbar (%s)." % (anlass, nr, type(err).__name__), 3600)
        return
    zeilen = e.stdout.decode("ascii", "replace").strip().splitlines()
    zeile = zeilen[-1] if zeilen else ""
    f = {}
    if zeile.startswith("ANSAGE;"):
        for teil in zeile.split(";")[1:]:
            if "=" in teil:
                k, v = teil.split("=", 1)
                f[k] = re.sub(r"[^A-Za-z0-9_.:,|/\-]", "?", v)[:120]
    _LOG.log(logging.INFO if e.returncode in (0, 3) else logging.WARNING,
             "Ansage %s (Fahrzeug %s): rc=%d stand=%s art=%s http=%s zeichen=%s kennung=%s",
             anlass, nr, e.returncode, f.get("STAND", "?"), f.get("ART", "?"),
             f.get("HTTP", "?"), f.get("ZEICHEN", "?"), f.get("KENNUNG", "?"))


def ansagen(cfg: dict, fahrzeuge: dict, ok: int, fehler_folge: int) -> None:
    """Nach jedem Abruf: Anlaesse erkennen und ansagen."""
    if ansage_ausfall(ok, fehler_folge):
        ansage_senden("ausfall", "0", {}, cfg)
        signal_senden(cfg, "ausfall", "0", SIGNAL_TEXTE["ausfall"])
    for nr in sorted(fahrzeuge, key=lambda n: ganz(n, 0)):
        f = fahrzeuge[nr]
        # Ein ausgefallenes Fahrzeug liefert keinen frischen Stand - daraus entsteht
        # kein Wechsel.
        if not isinstance(f, dict) or not f.get("ok"):
            continue
        for anlass, daten in ansage_ereignisse(nr, f):
            ansage_senden(anlass, nr, daten, cfg)
            # Gruppe 41 (E9): dieselben Ereignisse an SignalBot - eine Erkennung fuer beide Wege.
            if anlass in SIGNAL_TEXTE:
                wer = str(daten.get("name") or "") or ("Fahrzeug %s" % nr)
                signal_senden(cfg, anlass, nr, SIGNAL_TEXTE[anlass] % wer)


def stand_vorbelegen() -> dict:
    """Den letzten guten Stand aus loxone.json lesen (C4).

    loxone.json ist das Abbild, das der Endpunkt liest; es wird atomar und
    (seit diesem Durchgang) mit 0600 geschrieben, weil es Standort und
    Anschrift traegt. Jedes Fahrzeug kommt mit ok = 0 herein - gemessen ist in
    diesem Prozess noch nichts -, sein Zeitstempel bleibt der des letzten
    Erfolgs, damit ALTER weiterwaechst. Ist die Datei beschaedigt oder fehlt
    sie, beginnt der Stand leer wie bisher.
    """
    lox, lage = json_lage(DATEI_LOXONE)
    if lage != "ok" or not isinstance(lox.get("fahrzeuge"), dict):
        return {"ts": 0, "fahrzeuge": {}}
    aus: dict[str, dict] = {}
    for nr, f in lox["fahrzeuge"].items():
        if not re.match(r"^[0-9]{1,2}$", str(nr)) or not isinstance(f, dict):
            continue
        g = dict(f)
        g["ok"] = 0
        aus[str(nr)] = g
    ts = ganz(lox.get("ts"), 0)
    return {"ts": ts if ts > 0 else 0, "fahrzeuge": aus}


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

    # Kam das Beendigungssignal schon waehrend des Ladens, wird nicht erst
    # "Dienst startet" gemeldet - SEIT 0.9.21. Das Laden dauert auf dem Pi kalt
    # 6 bis 12 Sekunden; ein "Dienst anhalten" in dieser Zeit ergab bis dahin
    # ein Protokoll, in dem "startet" NACH "haelt an" stand.
    if not _LAUF:
        _LOG.info("Beendigungssignal schon beim Laden erhalten - Dienst startet nicht.")
        return 0
    # Fuer bin/dienst.sh: die Bibliotheken sind geladen. Scheitert das
    # Schreiben, meldet dienst.sh "noch beim Laden" - kein Grund zum Abbruch.
    if not einmal:
        try:
            DATEI_BEREIT.write_text(str(os.getpid()), encoding="utf-8")
        except OSError as err:
            _LOG.warning("Startmerker %s liess sich nicht anlegen: %s", DATEI_BEREIT, err)

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
        # SEIT DEM DURCHGANG 01.10.2026 (C4) AUS loxone.json VORBELEGT. Bis
        # 0.9.28 begann jeder Dienststart mit einem leeren Stand: startete der
        # Dienst waehrend einer Cloud-Stoerung neu (Waechter, Upgrade, Neustart
        # des LoxBerry), waren die zuletzt gemessenen Werte fort - gemessen:
        # FAHRZEUG_UNBEKANNT (404) bzw. SOC=-;REICHW=- statt der Altwerte mit
        # OK=0 (skoda_agenten/code/_agent/m4_neustart_stoerung.sh).
        stand: dict = stand_vorbelegen()
        # Gruppe 41 (B2): Merker der Vorklimatisierung und der Ankunft aus der Datei; Ladekosten der
        # letzten Ladung je Fahrzeug (retained Thema, Zustand bis zur naechsten Ladung).
        g41 = vorklima_merker_lesen()
        lk = json_lesen(DATEI_LADEKOSTEN)
        _G41["ladung"] = {str(k): v for k, v in lk.items() if isinstance(v, dict)}
        ladung_mitschrift_holen(time.time())    # G6-Zusatz: offene Ladungen ueber einen Neustart retten
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
            # Hat die Cloud die Fahrzeugliste IN DIESEM LAUF geliefert? Nur dann
            # gilt ein fehlendes Fahrzeug als entfernt (M4) - ein Ausfall des
            # Abrufs ist keine Aussage ueber das Konto.
            vins_frisch = False
            try:
                if not vins or zyklus % cfg["takt_stamm"] == 0:
                    vins = sorted(await asyncio.wait_for(
                        ms.list_vehicle_vins(), timeout=GRENZE_ABRUF))
                    vins_frisch = True
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

            # AUS DEM KONTO ENTFERNTE FAHRZEUGE (M4, Durchgang 01.10.2026;
            # Entscheidungen 8 und 16). Bis 0.9.28 fiel ein Eintrag aus alt_f nie
            # heraus: ein entferntes Fahrzeug ging bis zum naechsten Neustart mit
            # seinen Altwerten weiter hinaus, 'fahrzeuge' zaehlte es mit, und nach
            # dem Neustart standen seine retained Themen fuer immer im Broker.
            # Jetzt: liefert die Cloud die Liste und fehlt die VIN darin, verlaesst
            # das Fahrzeug den Stand, seine retained Themen bekommen EINMAL "-",
            # und seine Nummer bleibt in vin_nummern reserviert.
            entfernt: list[str] = []
            if vins_frisch:
                im_konto = {str(nr) for v, nr in nummern_zuordnen(vins).items() if v in vins}
                entfernt = [nr for nr in sorted(stand.get("fahrzeuge") or {})
                            if nr not in im_konto]
                if entfernt:
                    stand["fahrzeuge"] = {k: v for k, v in stand["fahrzeuge"].items()
                                          if k not in entfernt}
                    _LOG.info("Fahrzeug(e) %s fuehrt das Konto nicht mehr - aus dem Abbild "
                              "genommen, retained Themen einmal auf '-'.", ", ".join(entfernt))

            # Wurde der Durchgang durch ein Beendigungssignal abgebrochen,
            # wird NICHTS geschrieben. Ein halber Zyklus haette sonst ok=0
            # und damit in Loxone eine Stoerung gemeldet, wo nur jemand den
            # Dienst angehalten hat.
            if not _LAUF:
                break
            if ok and fahrzeuge:
                vorklima_nach_abruf(g41, cfg, fahrzeuge)
            vorklima_melden(cfg, g41, time.time())
            _HORCHER.pflegen(cfg)
            empfehlung = _HORCHER.empfehlung(cfg)
            zaehler = zaehler_naechster()
            # Altes Praefix, "MQTT aus", "Werte behalten aus" (M5): vormerken und
            # am Broker abraeumen, bevor unter dem neuen gesendet wird.
            try:
                mqtt_praefix_pflegen(cfg)
            except Exception as err:  # noqa: BLE001
                melde_gebremst("mqtt_vormerken", f"MQTT: Vormerken/Abraeumen alter Praefixe "
                                                 f"uebersprungen ({fehlertext(err)}).")
            abbild_schreiben(stand, cfg, ok, fehler, fehler_folge, zaehler, empfehlung,
                             entfernt=entfernt)
            zustand_schreiben(ok=ok, fehler=fehler, zyklus=zyklus, fehler_folge=fehler_folge,
                              zaehler=zaehler, empfehlung=empfehlung,
                              horcher=_HORCHER.grund if _HORCHER.grund else "",
                              horcher_verbunden=1 if _HORCHER.verbunden else 0,   # Healthcheck (29.10.)
                              pid=os.getpid(), intervall=cfg["intervall"],
                              anzahl_fahrzeuge=len(stand["fahrzeuge"]),
                              haus=haus_zustand(_HORCHER.haus, time.time()))

            # Nr. 36 b: Ansagen - nach Abbild, MQTT und Zustand, in einem Hilfsfaden:
            # die Bruecke ist ein Prozessaufruf (bis ANSAGE_FRIST_S), und die Schleife
            # bleibt fuer Befehle und Abfahrtszeit frei.
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, ansagen, cfg, fahrzeuge, ok, fehler_folge)
            except Exception as err:  # noqa: BLE001
                melde_gebremst("ansage", f"Ansage: {fehlertext(err)}", 3600)

            # Gruppe 41 (G5, B1/B2/B5): die Vorklimatisierung laeuft im Wartetakt (g41_takt()), nach
            # MG-Regeln, mit Merker in vorklima.json und dem eingestellten Fahrzeug - bis 0.9.33 stand hier
            # ein fester Auftrag an Fahrzeug "1", als erledigt gemerkt, bevor das Ergebnis da war.
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
                # Gruppe 41: alle 10 s Vorklimatisierung, Ankunft, Preisprobe; alle 30 s die Frische der
                # Haus-Quellen fuer den Reiter Test.
                if rest % 10 == 0:
                    try:
                        if rest % 30 == 0:
                            zustand_schreiben(haus=haus_zustand(_HORCHER.haus, time.time()))
                        if await g41_takt(ms, vins, cfg, g41, stand):
                            break  # Sofortabruf (Vorklima Versuch 2 oder Ankunft)
                    except Exception as err:  # noqa: BLE001
                        _LOG.error("Gruppe 41: %s", fehlertext(err))
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
    # Drei Bedingungen, nicht eine: argv[1] ist genau unser Skript, argv[0]
    # ist ein Python, und es gibt kein drittes Argument. Sonst gilt auch ein
    # Editor mit geoeffneter skoda.py als laufender Dienst - und, seit 0.9.23
    # ausdruecklich, ein Einmallauf derselben Datei ("--wachzeichen" aus dem
    # Minutentakt, "--selbsttest" aus der Oberflaeche). cmdline endet auf ein
    # Nullbyte; die leere letzte Zeile zaehlt nicht mit.
    echte = [a for a in argv if a != ""]
    return 1 if (len(echte) == 2 and echte[1] == str(SELF / "skoda.py")
                 and re.search(r"(^|/)python[0-9.]*$", echte[0])) else 0


def wachzeichen() -> int:
    cfg = config()
    if not cfg.get("mqtt_ein"):
        return 0
    laeuft = dienst_laeuft()
    # status/dienst ist Lebenszeichen und steht in MQTT_OHNE_RETAIN - der
    # Schalter wird trotzdem durchgereicht, entschieden wird je Thema.
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
                      + (", Zustaende werden behalten (retain), Lebenszeichen und "
                         "Messwerte mit Zeitbezug nicht" if c.get("mqtt_retain")
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
    zeilen.append("  - ob die Vorklimatisierung zur Abfahrtszeit am Fahrzeug wirkt")
    zeilen.append("Am Broker eines LoxBerry gemessen (17.09.2026, paho-mqtt 2.1.0): das Mithoeren")
    zeilen.append("  fremder Themen meldet sich an, abonniert und empfaengt Werte.")
    print("\n".join(zeilen))
    return 1 if fehler else 0


# Die Schalter, die dieses Skript kennt. Alles andere beendet es mit Antwort.
ERLAUBTE_SCHALTER = ("--einmal", "--selbsttest", "--wachzeichen", "--mqtt-leeren", "--signal-test")


def main() -> int:
    # EIN UNBEKANNTER SCHALTER BEENDET DAS WERKZEUG (C6, Durchgang 01.10.2026).
    # Bis 0.9.28 lief "skoda.py --selftest" (Tippfehler) als Dauerlaeufer gegen
    # die Cloud an, legte dienst.bereit mit der fremden PID an und schrieb
    # "Dienst startet" ins Protokoll (gemessen: rc 124 nach timeout 8,
    # skoda_agenten/code/_agent/m7_schalter.sh). Regeln/03: ein unbekannter
    # Schalter wird gemeldet, nicht als Dienst gedeutet. Geschrieben wird
    # nichts - die Pruefung steht vor log_einrichten().
    fremd = [a for a in sys.argv[1:] if a not in ERLAUBTE_SCHALTER]
    if fremd:
        sys.stderr.write("FEHLER: unbekannter Schalter %s. Erlaubt sind: %s. "
                         "Es wurde nichts gestartet.\n"
                         % (", ".join(fremd), ", ".join(ERLAUBTE_SCHALTER)))
        return 2
    # VOR log_einrichten(): --mqtt-leeren laeuft aus der Deinstallation
    # (uninstall/uninstall, Abschnitt 1b), und dort soll kein Protokoll mehr
    # entstehen - LoxBerry raeumt log/plugins/<ordner> vor diesem Skript
    # nicht wieder auf (Fall U1f).
    if "--mqtt-leeren" in sys.argv:
        return mqtt_leeren()
    # Gruppe 41 (Ruecktragen aus VW 0.9.33): Testmeldung an SignalBot (Knopf unter "Meldungen an SignalBot"). Ohne
    # Protokoll, ohne Sperre - er laeuft neben dem Dienst; eine Zeile fuer die Oberflaeche (sk_signal_test_lesen()).
    if "--signal-test" in sys.argv:
        e, text = signal_test()
        print("SIGNAL_TEST;ERGEBNIS=%s;TEXT=%s" % (e, text))
        return 0 if e == "angenommen" else 1
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
