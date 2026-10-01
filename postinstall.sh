#!/bin/bash
# Skoda Connect - postinstall
# command <TEMPFOLDER-KENNUNG> <NAME> <FOLDER> <VERSION> <BASEFOLDER> <WORKDIR>
#
# Zu den Argumenten, gemessen an sbin/plugininstall.pl:
#   $1  PTEMPDIR   eine zehnstellige Zufallskennung aus generate(10) -
#                  KEIN Pfad. Wer "$1/config" schreibt, baut ein
#                  Verzeichnis, das es nicht gibt.
#   $2  PSHNAME    Name des Plugins fuer Skripte
#   $3  PDIR       Installationsordner des Plugins
#   $4  PVERSION   Fassung
#   $5  LBHOMEDIR  Wurzelverzeichnis des LoxBerry
#   $6  PWORKDIR   Arbeitsordner des Installers, absolut - das ist der
#                  Pfad, der in $1 faelschlich vermutet wird.
#
# Legt an: Konfigurations-, Daten- und Logordner, die Zugangsdatei mit Rechten
# 0600 und die virtuelle Python-Umgebung samt der Bibliothek myskoda.
#
# WICHTIG (PEP 668): Debian 12/13 kennzeichnen die System-Python-Umgebung als
# extern verwaltet. Ein systemweites "pip3 install" wird mit
# "error: externally-managed-environment" abgewiesen - auch mit --user, auch
# als root. Deshalb eine eigene venv, und der Shebang der Skripte zeigt direkt
# darauf. JEDER Rueckgabewert wird geprueft: eine Installation, die "ALLES
# ERLEDIGT" meldet, obwohl die venv fehlschlug, ist schlimmer als ein Abbruch.
#
# ZWEITE WICHTIGE VORAUSSETZUNG: myskoda verlangt ab Fassung 2.0.0
# Python 3.13 (pyproject: requires-python >= 3.13.0). Debian 12 (Bookworm)
# liefert 3.11, Debian 13 (Trixie) liefert 3.13. Auf einem zu alten System
# bricht dieses Skript mit einer benannten Meldung ab, statt stillschweigend
# ein totes Plugin zu hinterlassen.

ARGV3=$3
ARGV5=$5
PFOLDER="${ARGV3:-skodaconnect}"
# ---------- Die Wurzel: GELESEN, nicht geraten ----------
#
# Bis 0.9.23 stand hier ein Rueckfall auf feste Ebenen ueber dem eigenen
# Ablageort, und geprueft wurde danach nur auf config/plugins UND
# data/plugins. Ein Baum, der wie eine Wurzel aussieht, es aber nicht ist,
# wurde damit zur Wurzel - in WSL gemessen (24.09.2026,
# Pruefung-Skoda-Connect-NG-0.9.24, messe_haken.sh, Faelle Ha1 bis Ha4).
# Eine LoxBerry-Wurzel traegt immer config/system/general.json (Regeln/06,
# der Raumklima-Vorfall). Ohne Wurzel: <WARNING>, nichts anlegen, nichts
# entfernen, Rueckgabe != 0.
sk_wurzel_suchen() {
    sk_v=$(cd "$(dirname "$(readlink -f "$0")")" 2>/dev/null && pwd -P)
    sk_i=0
    while [ -n "$sk_v" ] && [ "$sk_v" != "/" ] && [ "$sk_i" -lt 8 ]; do
        if [ -d "$sk_v/config/plugins" ] && [ -d "$sk_v/data/plugins" ] \
           && [ -f "$sk_v/config/system/general.json" ]; then
            echo "$sk_v"
            return 0
        fi
        sk_v=$(dirname "$sk_v")
        sk_i=$((sk_i + 1))
    done
    return 1
}
BASE="${ARGV5:-}"
if [ -z "$BASE" ] || [ ! -d "$BASE" ]; then
    if [ -n "${LBHOMEDIR:-}" ] && [ -d "$LBHOMEDIR/config/plugins" ] \
       && [ -d "$LBHOMEDIR/data/plugins" ]; then
        BASE="$LBHOMEDIR"
    else
        # LoxBerry::System taugt hier nicht, weil es den Pluginordner aus dem
        # Aufrufort ableitet und aus postinstall.sh heraus ueberall
        # Leerstring liefert.
        BASE=$(sk_wurzel_suchen) || BASE=""
    fi
fi

# Und danach wird nachgesehen, ob dabei wirklich ein LoxBerry herausgekommen
# ist - wortgleich mit preupgrade.sh, das die Pruefung seit 0.9.14 hat.
# Ohne sie arbeitet dieses Skript gegen "/config/plugins/..." und "/data/...",
# legt dort Ordner an und meldet am Ende trotzdem Erfolg.
if [ -z "$BASE" ] || [ ! -d "$BASE/config/plugins" ] || [ ! -d "$BASE/data/plugins" ]; then
    echo "<FAIL> Das Wurzelverzeichnis des LoxBerry liess sich nicht bestimmen:"
    echo "<FAIL> weder das fuenfte Argument noch \$LBHOMEDIR noch der eigene"
    echo "<FAIL> Ablageort fuehrten auf einen Ordner mit config/plugins und"
    echo "<FAIL> data/plugins. Es wurde nichts eingerichtet."
    exit 1
fi

PBIN="$BASE/bin/plugins/$PFOLDER"
PDATA="$BASE/data/plugins/$PFOLDER"
PLOG="$BASE/log/plugins/$PFOLDER"
PCONFIG="$BASE/config/plugins/$PFOLDER"
VENV="$PBIN/venv"

# Der Merker aus preupgrade.sh - und die Zusage, ihn IN JEDEM FALL zu
# entfernen.
#
# Bis 0.9.13 stand das "rm -f" ganz unten, hinter sechs "exit 1". Der
# Kommentar behauptete "IN JEDEM FALL", das Skript hielt es nicht: brach
# die Installation vorher ab (kein Netz beim pip, zu altes Python), blieb
# der Merker liegen und startete den Dienst bei der naechsten Installation
# ungefragt - auch dann, wenn er absichtlich abgeschaltet worden war.
#
# Deshalb ein trap auf EXIT: er raeumt den Merker weg, gleich an welcher
# Stelle und mit welchem Rueckgabewert dieses Skript endet. Ob der Dienst
# gestartet werden soll, steht danach in LIEF_VORHER - einer Variablen,
# die kein Abbruch liegen lassen kann.
# ---------- Upgrade oder Neuinstallation? (I1, Durchgang 01.10.2026) ----------
#
# Entscheidung 1 (29.09.2026): zurueckgespielt wird NUR bei einer
# Aktualisierung, und eine Aktualisierung erkennt dieses Skript an der Marke,
# die preupgrade.sh als Erstes anlegt - ohne Altersvergleich (Entscheidung 8:
# auch eine vergessene Marke gilt; wer frisch anfangen will, deinstalliert
# vorher). Bis 0.9.28 spielte eine Neuinstallation liegengebliebene
# Zweitschriften, Bestaende und den Startmerker einer FRUEHEREN Installation
# ein - altes Konto, altes Passwort, altes Aktionstoken - und startete den
# Dienst ungefragt (gemessen, Installerbericht F1/F1b).
MARKE="$BASE/data/plugins/$PFOLDER.upgrade_laeuft"
UPG_MARKE=0
[ -f "$MARKE" ] && UPG_MARKE=1

MERKER="$BASE/config/plugins/$PFOLDER.lief_vorher"
LIEF_VORHER=0
[ "$UPG_MARKE" = 1 ] && [ -f "$MERKER" ] && LIEF_VORHER=1
trap 'rm -f "$MERKER"' EXIT

# Ist die Datei ein JSON-Objekt mit mindestens einem nicht leeren Textwert?
# (I2, Durchgang 01.10.2026: statt grep; bis 0.9.28 nahm die Zeichenkettensuche
# eine abgeschnittene Datei an und meldete "<OK> wiederhergestellt", gemessen
# B1/B2.) Gelesen mit dem System-Python - die venv entsteht erst weiter unten.
# Rueckgabe 0 ja, 1 nein, 2 nicht pruefbar (kein python3).
json_mit_inhalt() {
    command -v python3 >/dev/null 2>&1 || return 2
    python3 -c 'import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        d = json.load(f)
except Exception:
    sys.exit(1)
sys.exit(0 if isinstance(d, dict) and any(isinstance(v, str) and v.strip() for v in d.values()) else 1)' "$1" 2>/dev/null
}

# Eine Datei oder einen Ordner der .alt-Ablage entfernen. Ein Verweis wird nur
# als Verweis entfernt (I6), eine Datei vorher ueberschrieben (sie kann ein
# Passwort tragen).
alt_entfernen() {
    if [ -L "$1" ]; then
        rm -f "$1"
    elif [ -d "$1" ]; then
        rm -rf "${1:?}"
    elif [ -f "$1" ]; then
        sk_l=$(stat -c %s "$1" 2>/dev/null || echo 0)
        [ "$sk_l" -gt 0 ] && dd if=/dev/zero of="$1" bs=1 count="$sk_l" conv=notrunc >/dev/null 2>&1
        rm -f "$1"
    fi
}

# Fassung der Bibliothek. Auf eine Fassung festgenagelt, damit eine
# Installation von heute morgen und eine von heute abend dasselbe ergeben.
# 2.16.1 ist die Fassung, gegen die dieses Plugin gebaut wurde; die
# Feldnamen im Dienst stammen aus ihren Datenklassen.
LIBVERSION="2.16.1"

mkdir -p "$PDATA" "$PLOG" "$PCONFIG" "$PDATA/befehle" "$PDATA/antworten" || {
    echo "<FAIL> Ordner konnten nicht angelegt werden."
    exit 1
}
chmod 755 "$PDATA" "$PLOG" "$PCONFIG" 2>/dev/null

# ---------- Was preupgrade.sh vor dem Upgrade gerettet hat ----------
#
# Der Installateur raeumt data/plugins/<ordner>/ beim Upgrade vollstaendig ab
# (sbin/plugininstall.pl: &purge_installation im Upgrade-Zweig, :886, Rumpf
# ab :1626 mit "rm -rfv .../data/plugins/$pfolder/"; Stand mit 2054 Zeilen).
# preupgrade.sh legt
# deshalb Sollmerker, Verlauf und Ladeprotokoll NEBEN den Ordner; hier kommen
# sie zurueck.
#
# Nichts wird ueberschrieben: was der Archivinhalt schon mitgebracht hat,
# bleibt stehen. Und die Rettung wird IN JEDEM FALL abgeraeumt - eine
# liegengebliebene Rettung wuerde beim naechsten Upgrade einen alten Stand
# ueber einen neuen legen.
RETTUNG="$BASE/data/plugins/$PFOLDER.rettung"

# NEUINSTALLATION: alles aus einer frueheren Installation nach .alt (I1).
# Einmal <WARNING> mit den Pfaden; ein vorhandenes .alt wird vorher
# abgeraeumt; uninstall raeumt die .alt mit ab. Die Selbstheilung der
# Bibliothek liest .alt nie.
if [ "$UPG_MARKE" = 0 ]; then
    ALT_LISTE=""
    for z in "$BASE/config/plugins/$PFOLDER.backup.skoda.json" \
             "$BASE/config/plugins/$PFOLDER.backup.zugang.json" \
             "$RETTUNG" "$MERKER"; do
        [ -e "$z" ] || [ -L "$z" ] || continue
        if [ -e "$z.alt" ] || [ -L "$z.alt" ]; then
            alt_entfernen "$z.alt"
        fi
        if mv -f "$z" "$z.alt" 2>/dev/null; then
            ALT_LISTE="$ALT_LISTE $z.alt"
        else
            ALT_LISTE="$ALT_LISTE $z (liess sich NICHT verschieben)"
        fi
    done
    if [ -n "$ALT_LISTE" ]; then
        echo "<WARNING> Neuinstallation: Zweitschriften und Bestaende einer frueheren Installation wurden nicht eingespielt, sondern beiseitegelegt:$ALT_LISTE - der Dienst wird nicht gestartet; die Deinstallation raeumt sie ab."
    fi
fi

if [ "$UPG_MARKE" = 1 ] && [ -d "$RETTUNG" ]; then
    ZURUECK=0
    for f in soll_laufen zustand.json ladungen.csv; do
        if [ -e "$RETTUNG/$f" ] && [ ! -e "$PDATA/$f" ]; then
            cp -p "$RETTUNG/$f" "$PDATA/$f" 2>/dev/null && ZURUECK=$((ZURUECK+1))
        fi
    done
    if [ -d "$RETTUNG/verlauf" ] && [ ! -d "$PDATA/verlauf" ]; then
        cp -a "$RETTUNG/verlauf" "$PDATA/verlauf" 2>/dev/null && ZURUECK=$((ZURUECK+1))
    fi
    rm -rf "$RETTUNG"
    if [ "$ZURUECK" -gt 0 ]; then
        echo "<OK> $ZURUECK Eintrag/Eintraege aus dem Datenordner zurueckgelegt."
    else
        echo "<INFO> Es war nichts zurueckzulegen."
    fi
fi

# ---------- Konfiguration ----------
[ -f "$PCONFIG/skoda.json" ] || echo '{}' > "$PCONFIG/skoda.json"
if [ ! -f "$PCONFIG/zugang.json" ]; then
    echo '{}' > "$PCONFIG/zugang.json"
fi
chmod 600 "$PCONFIG/zugang.json"

# Sicherung zurueckspielen - NUR BEI EINER AKTUALISIERUNG (I1). Bei einer
# Neuinstallation liegen die Zweitschriften schon unter .alt (oben). Bis 0.9.28
# stand hier "uebersteht Update UND Neuinstallation" - genau das war der
# Befund.
if [ "$UPG_MARKE" = 1 ]; then   # Upgrade-Marke (upgrade_laeuft) lag beim Start
    for f in skoda.json zugang.json; do
        BK="$BASE/config/plugins/$PFOLDER.backup.$f"
        CF="$PCONFIG/$f"
        if [ -L "$BK" ]; then
            echo "<WARNING> $BK ist ein Verweis, keine Datei - nichts zurueckgespielt."
        elif [ -f "$BK" ]; then
            INHALT=$(cat "$CF" 2>/dev/null)
            if [ ! -s "$CF" ] || [ "$INHALT" = "{}" ]; then
                # Nur eine Zweitschrift, die ein JSON-Objekt MIT Inhalt ist
                # (mindestens ein nicht leerer Textwert; bis 0.9.25 wurde auch
                # "{}" kopiert, bis 0.9.28 auch eine abgeschnittene Datei).
                # <OK> erst, wenn die zurueckgespielte Datei selbst die Pruefung
                # besteht - die Wirkung, nicht der Rueckgabewert von cp.
                json_mit_inhalt "$BK"
                sk_rc=$?
                if [ "$sk_rc" = 2 ]; then
                    echo "<WARNING> $f: python3 fehlt - die Sicherung liess sich nicht pruefen und wurde nicht zurueckgespielt ($BK)."
                elif [ "$sk_rc" != 0 ]; then
                    echo "<INFO> $f: Sicherung ohne Einstellungen oder kein gueltiges JSON-Objekt - nichts zurueckgespielt."
                elif cp -p "$BK" "$CF" && chmod 600 "$CF" && json_mit_inhalt "$CF"; then
                    echo "<OK> $f aus Sicherung wiederhergestellt."
                else
                    echo "<WARNING> $f liess sich aus der Sicherung nicht zurueckspielen ($BK)."
                fi
            fi
        fi
    done
fi
# 0600 auch fuer skoda.json (C9): sie traegt das Aktionstoken.
chmod 600 "$PCONFIG/zugang.json" "$PCONFIG/skoda.json"

# ---------- Die S-PIN abraeumen, die es nicht mehr gibt (0.9.11) ----------
#
# WARUM DIESER BLOCK HIER OBEN STEHT UND NICHT MEHR UNTEN
#
# Bis 0.9.13 stand er hinter dem Python-, venv- und pip-Abschnitt, also
# hinter sechs "exit 1". Scheiterte "pip install myskoda" - und dafuer
# genuegt eine fehlende Internetverbindung -, wurde er nie erreicht: die
# S-PIN blieb in zugang.json UND in der Zweitschrift stehen, waehrend
# README und Hilfe zusagen, sie werde entfernt. Ein Geheimnis, das laut
# Beschreibung fort ist und tatsaechlich noch dasteht, ist schlimmer als
# eines, von dem man weiss.
#
# Der Block braucht die venv nicht: er faellt weiter unten auf das
# System-python3 zurueck und benutzt nur die Standardbibliothek. Es gibt
# also keinen Grund, ihn hinter der Netzarbeit zu fuehren.
#
# Bis 0.9.10 nahm das Formular eine S-PIN an und legte sie in zugang.json ab.
# Benutzt wurde sie NIE: das Plugin bietet weder Ver- noch Entriegeln an, und
# nur dafuer verlangt MySkoda sie. Mit 0.9.11 ist das Feld fort - und damit
# muss auch der gespeicherte Wert fort. Ein Feld zu entfernen und den Wert
# liegen zu lassen waere die schlechteste der drei Moeglichkeiten: ein
# Geheimnis, das niemand mehr sieht und niemand mehr verwaltet.
#
# Ueberschrieben wird vor dem Neuschreiben. Auf einem Journaling-Dateisystem
# und auf Flash-Speicher ist das kein sicheres Loeschen - es ist der
# Unterschied zwischen "steht noch da" und "muss man suchen".
SPIN_WEG=0
for Z in "$PCONFIG/zugang.json" "$BASE/config/plugins/$PFOLDER.backup.zugang.json"; do
    [ -f "$Z" ] || continue
    if ! grep -q '"spin"' "$Z" 2>/dev/null; then
        continue
    fi
    PYBIN="python3"
    [ -x "$PBIN/venv/bin/python3" ] && PYBIN="$PBIN/venv/bin/python3"
    if "$PYBIN" - "$Z" <<'PYENDE'
import json, os, sys
p = sys.argv[1]
with open(p, 'r', encoding='utf-8') as f:
    d = json.load(f)
if not isinstance(d, dict) or 'spin' not in d:
    sys.exit(2)
d.pop('spin', None)
neu = json.dumps(d, ensure_ascii=False, indent=1)
# Erst den alten Platz ueberschreiben, dann den neuen Inhalt schreiben.
groesse = os.path.getsize(p)
with open(p, 'r+b') as f:
    f.write(b'0' * groesse)
    f.flush()
    os.fsync(f.fileno())
    f.seek(0)
    f.truncate(0)
    f.write(neu.encode('utf-8'))
    f.flush()
    os.fsync(f.fileno())
os.chmod(p, 0o600)
PYENDE
    then
        SPIN_WEG=$((SPIN_WEG + 1))
        echo "<OK> Die nicht mehr benutzte S-PIN wurde aus $(basename "$Z") entfernt."
    else
        echo "<FAIL> Die S-PIN liess sich aus $Z NICHT entfernen."
        echo "<FAIL> Bitte die Datei von Hand pruefen - sie enthaelt noch ein Geheimnis,"
        echo "<FAIL> das dieses Plugin nicht mehr benutzt."
    fi
done
if [ "$SPIN_WEG" -gt 0 ]; then
    echo "<INFO> Das Feld S-PIN gibt es in der Oberflaeche nicht mehr. Es kehrt zurueck,"
    echo "<INFO> wenn das Plugin Ver- und Entriegeln anbietet - dann wird es gebraucht."
fi

# ---------- Python suchen ----------
PY=""
for k in python3.15 python3.14 python3.13; do
    if command -v "$k" >/dev/null 2>&1; then PY="$k"; break; fi
done
if [ -z "$PY" ] && command -v python3 >/dev/null 2>&1; then
    if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,13) else 1)'; then
        PY="python3"
    fi
fi
if [ -z "$PY" ]; then
    HAVE=$(python3 -V 2>&1 || echo "kein python3")
    echo "<FAIL> Es wurde kein Python 3.13 oder neuer gefunden (gefunden: $HAVE)."
    echo "<FAIL> Die Bibliothek myskoda setzt ab Fassung 2.0.0 Python >= 3.13 voraus."
    echo "<FAIL> Debian 12 (Bookworm) liefert nur 3.11 - dort laeuft auch die letzte"
    echo "<FAIL> aeltere myskoda-Fassung (1.2.3, verlangt 3.12) nicht."
    echo "<FAIL> Abhilfe: LoxBerry auf Debian 13 (Trixie, Python 3.13) heben oder"
    echo "<FAIL> Python 3.13 zusaetzlich installieren."
    echo "<FAIL> Das Plugin bleibt installiert, der Dienst kann aber nicht starten."
    exit 1
fi
echo "<INFO> Verwendetes Python: $PY ($($PY -V 2>&1))"

# ---------- virtuelle Umgebung ----------
BRAUCHBAR=0
if [ -x "$VENV/bin/python3" ]; then
    if "$VENV/bin/python3" -c 'import sys; sys.exit(0 if sys.version_info >= (3,13) else 1)' 2>/dev/null; then
        BRAUCHBAR=1
    fi
fi
if [ "$BRAUCHBAR" -eq 0 ]; then
    rm -rf "$VENV"
    if ! "$PY" -m venv "$VENV"; then
        echo "<FAIL> Virtuelle Umgebung konnte nicht angelegt werden ($VENV)."
        echo "<FAIL> Haeufigste Ursache: das Paket python3-venv fehlt. Es steht"
        echo "<FAIL> seit 0.9.14 in dpkg/apt und wird vom LoxBerry-Installer"
        echo "<FAIL> selbst nachgezogen; kam es dort nicht an, von Hand:"
        echo "<FAIL>   sudo apt-get update && sudo apt-get install -y python3-venv"
        exit 1
    fi
    echo "<OK> Virtuelle Umgebung angelegt: $VENV"
fi
if [ ! -x "$VENV/bin/python3" ]; then
    echo "<FAIL> $VENV/bin/python3 fehlt - Abbruch."
    exit 1
fi

"$VENV/bin/python3" -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1 || \
    echo "<INFO> pip liess sich nicht aktualisieren - wird mit der vorhandenen Fassung versucht."

echo "<INFO> Installiere myskoda $LIBVERSION (benoetigt eine Internetverbindung) ..."
if ! "$VENV/bin/python3" -m pip install --no-cache-dir "myskoda==$LIBVERSION"; then
    echo "<INFO> Feste Fassung $LIBVERSION nicht installierbar - versuche die neueste."
    if ! "$VENV/bin/python3" -m pip install --no-cache-dir "myskoda"; then
        echo "<FAIL> myskoda konnte nicht installiert werden."
        echo "<FAIL> Haeufigste Ursachen: keine Internetverbindung, oder PyPI war"
        echo "<FAIL> nicht erreichbar."
        exit 1
    fi
    # Ersatzweg gegangen - und angezeigt, sonst wird aus dem Ersatz unbemerkt
    # der Normalfall. Bei einer anderen Fassung koennen sich Feldnamen
    # geaendert haben.
    echo "<INFO> ERSATZWEG: Es wurde die neueste Fassung statt $LIBVERSION installiert."
    echo "<INFO> Falls Werte leer bleiben, im Reiter Test 'Rohdaten als JSON ansehen'"
    echo "<INFO> aufrufen und die Feldnamen vergleichen."
fi

# Rueckgabewert allein genuegt nicht - es wird nachgesehen, ob sich die
# Bibliothek auch laden laesst.
#
# Der GRUND wird zitiert - seit 0.9.21. Bis 0.9.20 ging die Fehlerausgabe
# nach /dev/null, und im Installationsprotokoll stand nur "laesst sich nicht
# laden". Welche Abhaengigkeit fehlt, stand nirgends.
if ! LADEFEHLER=$("$VENV/bin/python3" -c 'from myskoda import MySkoda' 2>&1); then
    echo "<FAIL> myskoda ist installiert, laesst sich aber nicht laden. Letzte Zeilen:"
    printf '%s\n' "$LADEFEHLER" | tail -n 5 | sed 's/^/<FAIL>     /'
    exit 1
fi
IST=$("$VENV/bin/python3" -c 'import importlib.metadata as m; print(m.version("myskoda"))' 2>/dev/null || echo "unbekannt")
echo "<OK> myskoda geladen, Fassung $IST"

# ---------------------------------------------------------------------------
# paho-mqtt - FREIWILLIG, und ein Fehlschlag ist KEIN Fehlschlag
#
# Gebraucht nur fuer das Mithoeren fremder MQTT-Themen (Ladeempfehlung,
# Abfahrtszeit), beides ab Werk aus. Alles uebrige - Abruf, Endpunkt,
# Veroeffentlichen ueber das Gateway - arbeitet ohne die Bibliothek
# unveraendert.
#
# Deshalb bricht ein Fehlschlag die Installation NICHT ab. Er wird gesagt,
# und der Selbsttest im Reiter Test sagt es spaeter noch einmal. Ein
# Bedienelement, dessen Wert nirgends ankommt, ist schlimmer als ein
# fehlendes - aber ein Plugin, das wegen eines freiwilligen Zusatzes gar
# nicht erst installiert wird, ist am schlimmsten.
# ---------------------------------------------------------------------------
echo "<INFO> Installiere paho-mqtt (freiwillig, nur fuer das Mithoeren fremder Themen) ..."
if "$VENV/bin/python3" -m pip install --no-cache-dir "paho-mqtt" >/dev/null 2>&1; then
    echo "<OK> paho-mqtt installiert - Ladeempfehlung und Abfahrtszeit sind verfuegbar."
else
    echo "<INFO> paho-mqtt liess sich nicht installieren. Das ist kein Fehler:"
    echo "<INFO> Ladeempfehlung und Abfahrtszeit stehen dann nicht zur Verfuegung,"
    echo "<INFO> alles uebrige arbeitet unveraendert."
fi

# ---------- Rechte ----------
chmod 755 "$PBIN/skoda.py" 2>/dev/null
chmod 755 "$PBIN/dienst.sh" 2>/dev/null

# Der Eigentuemerwechsel geht NUR als root - und genau deshalb stand hier bis
# 0.9.14 ein Befehl, der nichts tat, wenn er gebraucht wurde: als loxberry
# aufgerufen scheitert chown, und "2>/dev/null" verschluckte es. Wo die
# Dateien ohnehin loxberry gehoeren, war er wirkungslos; wo sie root gehoeren
# - der einzige Fall, fuer den er da ist -, blieb es dabei und niemand sah es.
#
# Jetzt wird gefragt, ob er ueberhaupt greifen kann, und ein Fehlschlag wird
# gesagt statt weggeworfen.
if [ "$(id -u)" = "0" ]; then
    if ! chown -R loxberry:loxberry "$PBIN" "$PDATA" "$PLOG" "$PCONFIG"; then
        echo "<WARNING> Der Eigentuemer liess sich nicht auf loxberry setzen."
        echo "<WARNING> Der Dienst schreibt nach data/ und log/ - Dateien mit"
        echo "<WARNING> fremdem Eigentuemer bitte von Hand pruefen."
    fi
fi
chmod 600 "$PCONFIG/zugang.json" "$PCONFIG/skoda.json"
for f in skoda.json zugang.json; do
    [ -f "$BASE/config/plugins/$PFOLDER.backup.$f" ] && [ ! -L "$BASE/config/plugins/$PFOLDER.backup.$f" ] \
        && chmod 600 "$BASE/config/plugins/$PFOLDER.backup.$f"
done

# ---------- Jeder eigene Dienst, bevor gestartet wird (C3, Durchgang 01.10.2026) ----------
#
# Regeln/06: bei liegender Marke haelt postinstall JEDEN eigenen Dienst an,
# auch einen ohne PID-Datei. Bis 0.9.28 ueberstand eine Waise aus einem
# Doppelstart jedes Upgrade und lief mit dem ALTEN Code weiter, und nach dem
# Start hier liefen zwei (gemessen, Installerbericht D2). Argumentweise wie in
# preupgrade.sh, bin/dienst.sh und uninstall.
ist_unser_dienst() {
    [ -r "/proc/$1/cmdline" ] || return 1
    ARGS=$( { tr '\0' '\n' < "/proc/$1/cmdline"; } 2>/dev/null )
    [ "$(echo "$ARGS" | sed -n '2p')" = "$PBIN/skoda.py" ] || return 1
    echo "$ARGS" | sed -n '1p' | grep -qE '(^|/)python[0-9.]*$' || return 1
    [ "$(echo "$ARGS" | sed '/^$/d' | wc -l)" -eq 2 ] || return 1
    return 0
}
if [ "$UPG_MARKE" = 1 ]; then
    WAISEN=""
    for sk_f in $(grep -laF -- "$PBIN/skoda.py" /proc/[0-9]*/cmdline 2>/dev/null); do
        sk_n=${sk_f#/proc/}
        sk_n=${sk_n%/cmdline}
        ist_unser_dienst "$sk_n" && WAISEN="$WAISEN $sk_n"
    done
    if [ -n "$WAISEN" ]; then
        for P in $WAISEN; do kill "$P" 2>/dev/null; done
        i=0
        REST="$WAISEN"
        while [ "$i" -lt 70 ]; do
            REST=""
            for P in $WAISEN; do ist_unser_dienst "$P" && REST="$REST $P"; done
            [ -z "$REST" ] && break
            sleep 1
            i=$((i + 1))
        done
        for P in $REST; do ist_unser_dienst "$P" && kill -9 "$P" 2>/dev/null; done
        [ -n "$REST" ] && sleep 1
        UEBRIG=""
        for P in $WAISEN; do ist_unser_dienst "$P" && UEBRIG="$UEBRIG $P"; done
        if [ -n "$UEBRIG" ]; then
            echo "<WARNING> Ein Dienst aus der Zeit vor der Aktualisierung laeuft noch (PID$UEBRIG)."
            echo "<WARNING> Nach der Aktualisierung im Reiter Einstellungen 'Dienst anhalten' und neu starten."
        else
            echo "<INFO> $(echo $WAISEN | wc -w) Dienst(e) aus der Zeit vor der Aktualisierung angehalten (PID$WAISEN); es laeuft keiner mehr."
        fi
    fi
fi

# ---------- Dienst wieder starten, wenn er vor dem Upgrade lief ----------
#
# Der Merker entsteht nur in preupgrade.sh und nur dann, wenn dort ein
# laufender Vorgang angehalten wurde. Bei einer Erstinstallation gibt es
# ihn nicht, und dann passiert hier nichts.
#
# ZURUECKGENOMMEN am 31.08.2026. Hier stand, der Sollmerker unter data/
# ueberlebe das Upgrade "(gemessen an sbin/plugininstall.pl)" und der
# Cron-Waechter hole den Dienst ohnehin binnen einer Minute zurueck. Beides
# war falsch, und das Wort "gemessen" war das Schlimmste daran: die Funktion
# purge_installation hat ZWEI Aufrufstellen, und die zweite (:886, Stand mit
# 2054 Zeilen) steht im
# Upgrade-Zweig. data/plugins/<ordner>/ ist zwischen preupgrade.sh und dieser
# Zeile vollstaendig abgeraeumt, der Sollmerker mit ihm.
#
# Dieser Start ist damit NICHT nur eine Abkuerzung, sondern das Einzige, was
# einen laufenden Dienst nach einem Upgrade zurueckholt - der Waechter
# (bin/dienst.sh, "waechter") startet nur, wenn soll_laufen dasteht, und
# preupgrade.sh rettet ihn deshalb seit 0.9.15 neben den Ordner.
#
# Er wird IN JEDEM FALL entfernt - das erledigt der trap ganz oben, auch
# bei einem Abbruch weiter oben. Hier wird nur noch gefragt, ob er beim
# Start dieses Skriptes dalag.
if [ "$LIEF_VORHER" -eq 1 ]; then
    if [ ! -x "$PBIN/dienst.sh" ]; then
        echo "<INFO> $PBIN/dienst.sh fehlt - der Dienst wurde nicht gestartet."
    else
        # Als loxberry und nicht als root: der Dienst schreibt in data/
        # und log/. Was root dort anlegt, kann die Oberflaeche danach
        # nicht mehr ueberschreiben.
        # SK_START_TROTZ_MARKE=1: HIER soll der Dienst anlaufen, auch wenn
        # die Upgrade-Marke aus preupgrade.sh noch liegt. Sie faellt erst in
        # postupgrade.sh, dem letzten Hakenskript dieser Linie - faellt sie
        # vorher, kann der Minutentakt genau zwischen ihrem Wegfall und
        # diesem Start einen ZWEITEN Dienst anlegen.
        if [ "$(id -u)" = "0" ]; then
            AUSGABE=$(su -s /bin/bash -c "SK_START_TROTZ_MARKE=1 $PBIN/dienst.sh start" loxberry 2>&1)
        else
            AUSGABE=$(SK_START_TROTZ_MARKE=1 "$PBIN/dienst.sh" start 2>&1)
        fi
        case "$AUSGABE" in
            *gestartet*|*laeuft*)
                echo "<OK> Dienst wieder gestartet: $AUSGABE" ;;
            *)
                echo "<INFO> Der Dienst liess sich nicht wieder starten: $AUSGABE"
                echo "<INFO> Reiter Einstellungen, Knopf 'Dienst starten'." ;;
        esac
    fi
fi

# ---------- Abschluss: Erstanleitung nur ohne Zugangsdaten ----------
# Dieses Skript laeuft bei der Erstinstallation UND bei jedem Upgrade. Bis
# 0.9.25 stand die Aufforderung, die Zugangsdaten einzutragen, deshalb auch
# nach jedem gelungenen Upgrade da, obwohl sie eben zurueckgespielt waren
# (gemessen 24.09.2026 in WSL, Pruefung-Skoda-Connect-NG-0.9.26, Fall b).
#
# Entschieden wird nach dem INHALT, nicht nach der Upgrade-Marke. Eine
# Inhaltspruefung fuer zugang.json hat diese Linie sonst nicht (das
# Zurueckspielen oben fragt nur "leer oder {}"); genommen wird deshalb das
# einfachste belastbare Merkmal: E-Mail UND Passwort als nicht leerer Text -
# genau die beiden Felder, die sk_zugang_speichern() in
# webfrontend/html/sk_lib.php schreibt und ohne die der Dienst sich nicht
# anmelden kann. Ein leeres Konto ({"email":"","passwort":""}, siehe
# preupgrade.sh) zaehlt als nicht eingerichtet. "$PY" ist hier sicher
# bestimmt (Abbruch weiter oben, wenn nicht).
if "$PY" -c 'import json,sys
d=json.load(open(sys.argv[1],encoding="utf-8"))
ok=lambda k: isinstance(d.get(k),str) and d.get(k).strip()!=""
sys.exit(0 if isinstance(d,dict) and ok("email") and ok("passwort") else 1)' \
        "$PCONFIG/zugang.json" >/dev/null 2>&1; then
    # Die Schlusszeile richtet sich nach der Marke (I1): eine Neuinstallation
    # heisst nicht "Aktualisierung abgeschlossen".
    if [ "$UPG_MARKE" = 1 ]; then
        if [ "$LIEF_VORHER" -eq 0 ]; then
            echo "<INFO> Der Dienst lief vor dem Update nicht und bleibt angehalten;"
            echo "<INFO> gestartet wird er im Reiter Einstellungen."
        fi
        echo "<OK> Aktualisierung abgeschlossen, Einstellungen uebernommen."
    else
        echo "<OK> Installation abgeschlossen."
        echo "<INFO> Der Dienst ist angehalten; gestartet wird er im Reiter Einstellungen."
    fi
else
    if [ "$UPG_MARKE" = 1 ]; then
        echo "<OK> Aktualisierung abgeschlossen."
    else
        echo "<OK> Installation abgeschlossen."
    fi
    echo "<INFO> Bitte die Plugin-Oberflaeche oeffnen, die Zugangsdaten des MySkoda-Kontos"
    echo "<INFO> eintragen und den Dienst im Reiter Einstellungen starten."
fi
exit 0
