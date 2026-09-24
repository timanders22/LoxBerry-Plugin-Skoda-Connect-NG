#!/bin/bash
# Skoda Connect - postupgrade
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
# ---------------------------------------------------------------------------
# WARUM HIER FAST NICHTS MEHR STEHT
#
# Bis 0.9.13 rief diese Datei postinstall.sh auf. Das sah nach Sorgfalt aus,
# war aber eine Verdopplung: der LoxBerry-Installer fuehrt postinstall OHNE
# Bedingung aus (sbin/plugininstall.pl, Abschnitt "Executing postinstall
# script" - kein if ($isupgrade) davor) und postupgrade danach ZUSAETZLICH
# beim Upgrade. postinstall lief also zweimal.
#
# Das ist nicht bloss unschoen: postinstall.sh legt die virtuelle Umgebung an
# und holt myskoda samt Abhaengigkeiten mit "pip install --no-cache-dir" aus
# dem Netz. Auf einem Raspberry Pi dauert das Minuten - und es geschah bei
# jedem Upgrade doppelt.
#
# Was ein Upgrade zusaetzlich braucht, steht hier. Alles andere hat
# postinstall.sh zu diesem Zeitpunkt bereits erledigt, einschliesslich des
# Zurueckspielens der gesicherten Konfiguration und des Abraeumens der S-PIN.
# ---------------------------------------------------------------------------

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
        BASE=$(sk_wurzel_suchen) || BASE=""
    fi
fi

# NACHGESEHEN WIRD SEIT 0.9.24. Bis 0.9.23 pruefte dieses Skript als einziges
# der vier ueberhaupt nicht nach: mit leerem BASE raeumte es gegen
# "/data/plugins/<ordner>.upgrade_laeuft" ab und loeschte
# "/bin/plugins/<ordner>/__pycache__" - und meldete danach "<OK> postupgrade
# abgeschlossen". In WSL gemessen (24.09.2026,
# Pruefung-Skoda-Connect-NG-0.9.24, messe_haken.sh, Fall Ha3: im fremden Baum
# war die Marke weg, der Rueckgabewert 0).
if [ -z "$BASE" ] || [ ! -d "$BASE/config/plugins" ] || [ ! -d "$BASE/data/plugins" ]; then
    echo "<WARNING> Das Wurzelverzeichnis des LoxBerry liess sich nicht"
    echo "<WARNING> bestimmen: weder das fuenfte Argument noch \$LBHOMEDIR noch"
    echo "<WARNING> die Suche oberhalb des eigenen Ablageorts fuehrten auf einen"
    echo "<WARNING> Ordner mit config/plugins, data/plugins und"
    echo "<WARNING> config/system/general.json."
    echo "<WARNING> Es wurde nichts entfernt und keine Upgrade-Marke abgeraeumt."
    exit 1
fi

PBIN="$BASE/bin/plugins/$PFOLDER"

# Alte Python-Zwischendateien wegraeumen. Eine .pyc, die aelter ist als der
# Quelltext daneben, kann im ungluecklichen Fall statt des neuen Codes
# geladen werden. Der Ordner wird bei Bedarf neu und passend zur laufenden
# Python-Fassung angelegt.
if [ -d "$PBIN/__pycache__" ]; then
    rm -rf "$PBIN/__pycache__"
    echo "<OK> Alte Python-Zwischendateien entfernt."
fi

# ---------- Die Upgrade-Marke aus preupgrade.sh wegraeumen ----------
#
# Dies ist das LETZTE Hakenskript dieser Linie - ein postroot.sh gibt es
# nicht (Reihenfolge nach Regeln/06: preroot, preinstall, preupgrade,
# postinstall, postupgrade, postroot).
#
# Die Marke faellt HIER und nicht frueher: postinstall.sh hat den Dienst
# oben mit SK_START_TROTZ_MARKE=1 bereits gestartet, und faellt die Marke
# vor diesem Start, kann der Minutentakt genau dazwischen einen ZWEITEN
# Dienst anlegen.
#
# Bleibt sie liegen - abgebrochene Installation -, gilt sie nach 3600 s
# ohnehin nicht mehr; bin/dienst.sh und die Oberflaeche rechnen das nach.
MARKE="$BASE/data/plugins/$PFOLDER.upgrade_laeuft"
if [ -f "$MARKE" ]; then
    rm -f "$MARKE"
    # Die Wirkung pruefen, nicht den Rueckgabewert (Kernschicht 2).
    if [ -f "$MARKE" ]; then
        echo "<WARNING> Die Marke $MARKE liess sich nicht entfernen; der Dienst"
        echo "<WARNING> startet erst wieder, wenn sie aelter als eine Stunde ist."
    else
        echo "<OK> Aktualisierung abgemeldet."
    fi
fi

echo "<OK> postupgrade abgeschlossen."
exit 0
