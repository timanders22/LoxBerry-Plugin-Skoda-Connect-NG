#!/bin/bash
# Skoda Connect - postinstall
# command <TEMPFOLDER> <NAME> <FOLDER> <VERSION> <BASEFOLDER>
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
BASE="${ARGV5:-$LBHOMEDIR}"
if [ -z "$BASE" ] || [ ! -d "$BASE" ]; then
    # Ableitung aus dem eigenen Ablageort - LoxBerry::System taugt hier nicht,
    # weil es den Pluginordner aus dem Aufrufort ableitet und aus
    # postinstall.sh heraus ueberall Leerstring liefert.
    SELF=$(cd "$(dirname "$0")" && pwd)
    BASE=$(cd "$SELF/../.." 2>/dev/null && pwd)
fi

PBIN="$BASE/bin/plugins/$PFOLDER"
PDATA="$BASE/data/plugins/$PFOLDER"
PLOG="$BASE/log/plugins/$PFOLDER"
PCONFIG="$BASE/config/plugins/$PFOLDER"
VENV="$PBIN/venv"

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

# ---------- Konfiguration ----------
[ -f "$PCONFIG/skoda.json" ] || echo '{}' > "$PCONFIG/skoda.json"
if [ ! -f "$PCONFIG/zugang.json" ]; then
    echo '{}' > "$PCONFIG/zugang.json"
fi
chmod 600 "$PCONFIG/zugang.json"

# Sicherung zurueckspielen (uebersteht Update UND Neuinstallation)
for f in skoda.json zugang.json; do
    BK="$BASE/config/plugins/$PFOLDER.backup.$f"
    CF="$PCONFIG/$f"
    if [ -f "$BK" ]; then
        INHALT=$(cat "$CF" 2>/dev/null)
        if [ ! -s "$CF" ] || [ "$INHALT" = "{}" ]; then
            cp -p "$BK" "$CF" && echo "<OK> $f aus Sicherung wiederhergestellt."
        fi
    fi
done
chmod 600 "$PCONFIG/zugang.json"

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
        echo "<FAIL> Fehlt das Paket python3-venv? (apt install python3-venv)"
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
if ! "$VENV/bin/python3" -c 'from myskoda import MySkoda' 2>/dev/null; then
    echo "<FAIL> myskoda ist installiert, laesst sich aber nicht laden."
    exit 1
fi
IST=$("$VENV/bin/python3" -c 'import importlib.metadata as m; print(m.version("myskoda"))' 2>/dev/null || echo "unbekannt")
echo "<OK> myskoda geladen, Fassung $IST"

# ---------- Rechte ----------
chmod 755 "$PBIN/skoda.py" 2>/dev/null
chmod 755 "$PBIN/dienst.sh" 2>/dev/null
chown -R loxberry:loxberry "$PBIN" "$PDATA" "$PLOG" "$PCONFIG" 2>/dev/null
chmod 600 "$PCONFIG/zugang.json"

echo "<OK> Installation abgeschlossen."
echo "<INFO> Bitte die Plugin-Oberflaeche oeffnen, die Zugangsdaten des MySkoda-Kontos"
echo "<INFO> eintragen und den Dienst im Reiter Einstellungen starten."
exit 0
