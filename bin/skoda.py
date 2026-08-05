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
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

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
if len(SELF.parents) >= 3:
    LBHOME = SELF.parents[2]
else:
    LBHOME = Path(os.environ.get("LBHOMEDIR") or "/opt/loxberry")
PDATA = LBHOME / "data" / "plugins" / PNAME
PLOG = LBHOME / "log" / "plugins" / PNAME
PCONFIG = LBHOME / "config" / "plugins" / PNAME

DATEI_CONFIG = PCONFIG / "skoda.json"
DATEI_ZUGANG = PCONFIG / "zugang.json"
DATEI_CACHE = PDATA / "cache.json"
DATEI_LOXONE = PDATA / "loxone.json"
DATEI_ZUSTAND = PDATA / "zustand.json"
DATEI_MARKE = PDATA / "sitzung.json"          # zwischengespeicherter Refresh-Token
ORDNER_BEFEHLE = PDATA / "befehle"
ORDNER_ANTWORTEN = PDATA / "antworten"
DATEI_LOG = PLOG / "skoda.log"

# Muessen zu sk_vorgaben() in webfrontend/html/sk_lib.php passen.
VORGABEN = {
    "intervall": 300,
    "takt_stamm": 12,
    "takt_wartung": 24,
    "mqtt_ein": 0,
    "mqtt_topic": "skoda",
    "steuerung_ein": 0,
    "temp_min": 16,
    "temp_max": 29,
    "verlauf_tage": 8,
    "sitzung_merken": 1,
}

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


# ---------------------------------------------------------------------------
# Protokollierung
#
# Ausschliesslich in die Datei. Das Startskript leitet die Ausgabe des Dienstes
# ohnehin in dieselbe Datei um - ein zweiter Kanal nach stdout schriebe jede
# Zeile doppelt hinein.
# ---------------------------------------------------------------------------
def log_einrichten() -> None:
    PLOG.mkdir(parents=True, exist_ok=True)
    _LOG.setLevel(logging.INFO)
    try:
        h = RotatingFileHandler(DATEI_LOG, maxBytes=512000, backupCount=1, encoding="utf-8")
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


def melde_gebremst(schluessel: str, text: str, sekunden: int = 3600) -> None:
    """Dieselbe Meldung hoechstens einmal je Zeitfenster - sonst wird die
    Logdatei durch eine Dauerstoerung unlesbar."""
    jetzt = time.time()
    if jetzt - _LETZTE_MELDUNG.get(schluessel, 0) >= sekunden:
        _LETZTE_MELDUNG[schluessel] = jetzt
        _LOG.warning(text)


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
def json_lesen(pfad: Path) -> dict:
    try:
        with pfad.open("r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def json_schreiben(pfad: Path, daten, rechte: int | None = None) -> bool:
    """Erst in eine Nebendatei, dann umbenennen. So liest die Oberflaeche nie
    eine halb geschriebene Datei."""
    try:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        tmp = pfad.with_suffix(pfad.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(daten, f, ensure_ascii=False, indent=1, default=str)
        if rechte is not None:
            os.chmod(tmp, rechte)
        os.replace(tmp, pfad)
        return True
    except (OSError, TypeError, ValueError) as err:
        _LOG.error("Datei %s konnte nicht geschrieben werden: %s", pfad, err)
        return False


def config() -> dict:
    c = dict(VORGABEN)
    c.update(json_lesen(DATEI_CONFIG))
    c["intervall"] = max(60, min(3600, ganz(c.get("intervall"), 300)))
    c["takt_stamm"] = max(1, min(240, ganz(c.get("takt_stamm"), 12)))
    c["takt_wartung"] = max(1, min(240, ganz(c.get("takt_wartung"), 24)))
    c["temp_min"] = max(10, min(30, ganz(c.get("temp_min"), 16)))
    c["temp_max"] = max(10, min(30, ganz(c.get("temp_max"), 29)))
    if c["temp_min"] > c["temp_max"]:
        c["temp_min"], c["temp_max"] = c["temp_max"], c["temp_min"]
    c["verlauf_tage"] = max(1, min(90, ganz(c.get("verlauf_tage"), 8)))
    return c


def ganz(wert, ersatz: int) -> int:
    try:
        return int(wert)
    except (TypeError, ValueError):
        return ersatz


def zugang() -> dict:
    z = json_lesen(DATEI_ZUGANG)
    return {
        "email": str(z.get("email") or "").strip(),
        "passwort": str(z.get("passwort") or ""),
        "spin": str(z.get("spin") or ""),
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


def mqtt_senden(paare: dict, praefix: str) -> None:
    z = mqtt_zustand()
    if not z["udpport"]:
        melde_gebremst("mqtt_kein_port",
                       "MQTT: kein UDP-Eingangsport in general.json gefunden - nichts gesendet.")
        return
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
        return
    try:
        for k, v in paare.items():
            if v is None:
                continue
            s.sendto(f"publish {praefix}/{k} {v}".encode("utf-8"), ("127.0.0.1", z["udpport"]))
    except OSError as err:
        melde_gebremst("mqtt_senden", f"MQTT: Senden fehlgeschlagen ({err}).")
    finally:
        s.close()


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
        "am_gespeicherten_ort": 1 if hole(ch, "is_vehicle_in_saved_location") else 0,
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
            d[feld] = int(getattr(wert, "value", wert)) or None
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
        "sitzheizung_vorn_links": 1 if hole(ac, "seat_heating_activated", "front_left") else 0,
        "sitzheizung_vorn_rechts": 1 if hole(ac, "seat_heating_activated", "front_right") else 0,
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


def abbild_verbindung(vs) -> dict:
    return {
        "erreichbar": 0 if hole(vs, "unreachable") else 1,
        "in_bewegung": 1 if hole(vs, "in_motion") else 0,
        "zuendung_an": (None if hole(vs, "ignition_on") is None
                        else (1 if hole(vs, "ignition_on") else 0)),
    }


# ---------------------------------------------------------------------------
# Verlauf (Ladezustand beziehungsweise Tankfuellstand ueber den Tag)
# ---------------------------------------------------------------------------
def verlauf_anhaengen(nummer: int, soc, reichweite, tage: int) -> None:
    if soc is None:
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
            f.write(f"{int(time.time())};{soc};{reichweite if reichweite is not None else ''}\n")
        marke.write_text(str(int(time.time())))
    except OSError:
        return
    grenze = time.time() - tage * 86400
    for alt in ordner.glob("fahrzeug*_*.csv"):
        try:
            if alt.stat().st_mtime < grenze:
                alt.unlink()
        except OSError:
            pass


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
    for alt in ORDNER_ANTWORTEN.glob("*.json"):
        try:
            if alt.stat().st_mtime < grenze:
                alt.unlink()
        except OSError:
            pass


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
        n = 1
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

    if aktion == "abruf":
        return (1, "Sofortabruf eingeplant.", {})

    if not cfg.get("steuerung_ein"):
        return (0, "Die Steuerung ist ausgeschaltet. Reiter Einstellungen, "
                   "Haken 'Schreibende Befehle zulassen'.", {})

    if not vins:
        return (0, "Es ist noch kein Fahrzeug bekannt. Erst einen Abruf abwarten.", {})

    vin = vin_waehlen(vins, b.get("fahrzeug"))
    if vin is None:
        return (0, f"Fahrzeug '{b.get('fahrzeug')}' gibt es nicht. Bekannt sind {len(vins)} Fahrzeuge.", {})

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
    for datei in sorted(ORDNER_BEFEHLE.glob("*.json")):
        b = json_lesen(datei)
        kennung = datei.stem
        try:
            datei.unlink()
        except OSError:
            pass
        if not b:
            antwort_schreiben(kennung, 0, "Befehlsdatei war leer oder unlesbar.")
            continue
        try:
            ok, meldung, zusatz = await befehl_ausfuehren(ms, vins, cfg, b)
        except Exception as err:  # noqa: BLE001 - jeder Fehler gehoert gemeldet, nicht verschluckt
            ok, meldung, zusatz = 0, fehlertext(err), {}
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
async def endpunkt(ausfaelle: dict, name: str, koro):
    try:
        return await koro
    except Exception as err:  # noqa: BLE001
        ausfaelle[name] = fehlertext(err)
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
            d.update(laden)

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

    d["ausfaelle"] = ausfaelle
    d["ok"] = 0 if len(ausfaelle) >= 3 else 1
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
)


def abbild_schreiben(stand: dict, cfg: dict, ok: int, fehler: str = "") -> dict:
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
        "letzter_versuch": int(time.time()),
        "anzahl_fahrzeuge": len(fahrzeuge),
        "fahrzeuge": fahrzeuge,
    }
    if stand.get("ts"):
        lox["ts"] = int(stand["ts"])
    json_schreiben(DATEI_LOXONE, lox)

    # Vollstaendiges Abbild fuer die Fehlersuche. Zugangsdaten stehen hier
    # nicht drin - die fuehrt die Bibliothek getrennt.
    json_schreiben(DATEI_CACHE, {"ts": int(time.time()), "ok": ok,
                                 "fehler": fehler, "fahrzeuge": fahrzeuge})

    praefix = str(cfg.get("mqtt_topic") or "skoda").strip("/") or "skoda"
    if not ok:
        # Bei einer Stoerung nur das ok-Thema senden. Die alten Messwerte
        # erneut zu veroeffentlichen liesse sie frisch aussehen.
        if cfg.get("mqtt_ein"):
            mqtt_senden({"ok": 0}, praefix)
        return lox

    for nummer, f in fahrzeuge.items():
        try:
            verlauf_anhaengen(int(nummer),
                              f.get("soc") if f.get("soc") is not None else f.get("tank_prozent"),
                              f.get("reichweite_km"), cfg["verlauf_tage"])
        except (TypeError, ValueError):
            pass

    if cfg.get("mqtt_ein"):
        paare = {"ok": ok, "fahrzeuge": len(fahrzeuge)}
        for nummer, f in fahrzeuge.items():
            for feld in MQTT_FELDER:
                paare[f"fahrzeug{nummer}/{feld}"] = f.get(feld)
        mqtt_senden(paare, praefix)

    return lox


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
                await ms.connect(refresh_token=token)
            except Exception as err:  # noqa: BLE001
                _LOG.info("Gemerkte Sitzung nicht mehr gueltig (%s) - Anmeldung mit "
                          "Benutzername und Passwort.", fehlertext(err))
                sitzung_loeschen()
            else:
                return "gemerkte Sitzung"
    await ms.connect(email=z["email"], password=z["passwort"])
    if cfg.get("sitzung_merken"):
        try:
            sitzung_schreiben(await ms.get_refresh_token())
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
    from aiohttp import ClientSession
    from myskoda import MySkoda

    cfg = config()
    z = zugang()
    if not z["email"] or not z["passwort"]:
        _LOG.error("Zugangsdaten fehlen. Reiter Einstellungen der Plugin-Oberflaeche oeffnen.")
        zustand_schreiben(ok=0, fehler="Zugangsdaten fehlen.")
        return 1

    _LOG.info("Dienst startet (Takt %s s, Steuerung %s).",
              cfg["intervall"], "ein" if cfg.get("steuerung_ein") else "aus")

    async with ClientSession() as sitzung:
        # mqtt_enabled=False mit Absicht: die Ereignisleitung der Bibliothek
        # laeuft ueber Firebase Cloud Messaging und meldet dazu ein Geraet beim
        # Anbieter an. Fuer einen Dienst, der ohnehin im Takt abruft, ist das
        # unnoetig. Folge: Schreibbefehle warten nicht auf die Bestaetigung des
        # Fahrzeugs - das steht so in jeder Antwort.
        ms = MySkoda(sitzung, mqtt_enabled=False)
        try:
            weg = await anmelden(ms, z, cfg)
        except Exception as err:  # noqa: BLE001
            meldung = fehlertext(err)
            _LOG.error("Anmeldung fehlgeschlagen: %s", meldung)
            zustand_schreiben(ok=0, fehler=meldung)
            return 1
        _LOG.info("Angemeldet ueber %s.", weg)

        stammdaten: dict[str, dict] = {}
        vins: list[str] = []
        # Letzter gueltiger Stand. Bleibt bei einer Stoerung stehen, damit der
        # Endpunkt nicht ploetzlich "Fahrzeug unbekannt" meldet und damit ALTER
        # weiterwaechst - daran haengt die Ausfallerkennung in Loxone.
        stand: dict = {"ts": 0, "fahrzeuge": {}}
        zyklus = 0
        fehler_folge = 0

        while _LAUF:
            cfg = config()  # Aenderungen aus der Oberflaeche ohne Neustart uebernehmen
            ok = 0
            fehler = ""
            fahrzeuge: dict[str, dict] = {}
            try:
                if not vins or zyklus % cfg["takt_stamm"] == 0:
                    vins = sorted(await ms.list_vehicle_vins())
                for i, vin in enumerate(vins, start=1):
                    stammdaten.setdefault(vin, {})
                    fahrzeuge[str(i)] = await fahrzeug_abrufen(
                        ms, vin, stammdaten[vin], cfg, zyklus)
                ok = 1 if fahrzeuge and any(f.get("ok") for f in fahrzeuge.values()) else 0
                if not vins:
                    fehler = "Das Konto fuehrt kein Fahrzeug."
                fehler_folge = 0 if ok else fehler_folge + 1
            except Exception as err:  # noqa: BLE001
                fehler = fehlertext(err)
                fehler_folge += 1
                melde_gebremst("abruf", f"Abruf fehlgeschlagen: {fehler}", 900)
                if type(err).__name__ in ("TokenExpiredError", "NotAuthorizedError"):
                    # Sitzung neu aufbauen, statt bis zum Neustart zu scheitern.
                    sitzung_loeschen()
                    try:
                        weg = await anmelden(ms, z, cfg)
                        _LOG.info("Neu angemeldet ueber %s.", weg)
                    except Exception as err2:  # noqa: BLE001
                        _LOG.error("Neuanmeldung fehlgeschlagen: %s", fehlertext(err2))

            if ok and fahrzeuge:
                stand = {"ts": int(time.time()), "fahrzeuge": fahrzeuge}
            abbild_schreiben(stand, cfg, ok, fehler)
            zustand_schreiben(ok=ok, fehler=fehler, zyklus=zyklus, fehler_folge=fehler_folge,
                              pid=os.getpid(), intervall=cfg["intervall"],
                              anzahl_fahrzeuge=len(stand["fahrzeuge"]))
            zyklus += 1
            if einmal:
                return 0 if ok else 1

            rest = cfg["intervall"]
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

        try:
            await ms.disconnect()
        except Exception:  # noqa: BLE001
            pass
    _LOG.info("Dienst beendet.")
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
    if z["spin"]:
        if z["spin"].isdigit() and len(z["spin"]) == 4:
            zeilen.append("[OK]   S-PIN hinterlegt (vier Ziffern)")
        else:
            fehler += 1
            zeilen.append(f"[FEHL] Die S-PIN hat {len(z['spin'])} Zeichen - erwartet werden "
                          f"genau vier Ziffern")
    else:
        zeilen.append("[INFO] Keine S-PIN hinterlegt (nur fuer Ver- und Entriegeln noetig, "
                      "das dieses Plugin nicht anbietet)")
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
    print("\n".join(zeilen))
    return 1 if fehler else 0


def main() -> int:
    log_einrichten()
    if "--selbsttest" in sys.argv:
        return selbsttest()
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
