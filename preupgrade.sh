#!/bin/bash
# Skoda Connect - preupgrade
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
# Vor dem Upgrade: laufenden Dienst anhalten und die Konfiguration ausserhalb
# des Plugin-Ordners sichern. Die Zugangsdaten liegen in einer eigenen Datei
# und werden getrennt gesichert (Rechte 0600 bleiben erhalten).
ARGV3=$3
ARGV5=$5
PFOLDER="${ARGV3:-skodaconnect}"
BASE="${ARGV5:-$LBHOMEDIR}"
if [ -z "$BASE" ] || [ ! -d "$BASE" ]; then
    # Dritter Rueckfall wie in postinstall.sh: Ableitung aus dem eigenen
    # Ablageort. LoxBerry::System taugt hier nicht - es leitet den
    # Pluginordner aus dem Aufrufort ab und liefert aus einem
    # Installationsskript heraus ueberall Leerstring.
    SELF=$(cd "$(dirname "$0")" && pwd)
    BASE=$(cd "$SELF/../.." 2>/dev/null && pwd)
fi
# Und danach wird nachgesehen, ob dabei wirklich ein LoxBerry heraus-
# gekommen ist. Bis 0.9.13 gab es diesen Rueckfall gar nicht, und geprueft
# wurde nichts: standen weder das fuenfte Argument noch $LBHOMEDIR, so
# arbeitete dieses Skript gegen "/config/plugins/..." und "/data/..." -
# es hielt keinen Dienst an, sicherte nichts, und meldete am Ende
# trotzdem "<OK> preupgrade abgeschlossen". Das Upgrade lief dann ohne
# Sicherung, und niemand sah es. Ein Rueckgabewert ungleich 0 und eine
# <WARNING>-Zeile sind hier das Mindeste.
if [ -z "$BASE" ] || [ ! -d "$BASE/config/plugins" ] || [ ! -d "$BASE/data/plugins" ]; then
    echo "<WARNING> Das Wurzelverzeichnis des LoxBerry liess sich nicht"
    echo "<WARNING> bestimmen: weder das fuenfte Argument noch \$LBHOMEDIR noch"
    echo "<WARNING> der eigene Ablageort fuehrten auf einen Ordner mit"
    echo "<WARNING> config/plugins und data/plugins."
    echo "<WARNING> Es wurde NICHTS gesichert und kein Dienst angehalten."
    exit 1
fi

# Der Merker sagt dem postinstall, dass der Dienst LIEF.
#
# BERICHTIGT am 20.08.2026. Hier stand, der Installateur raeume beim
# Upgrade data/ und config/ des Plugins aus. Das ist FALSCH und war nie
# gemessen. Nachgelesen in sbin/plugininstall.pl: beide Ordner werden
# angelegt, falls sie fehlen, und der Archivinhalt wird darueber kopiert
# (:891, :895, :996, :1000). Geloescht werden sie nur in
# purge_installation (:1604, :1606), und die laeuft ausschliesslich im
# Deinstallations-Zweig (:233).
#
# Was daraus folgt, und es ist wichtiger als der Merker: der Sollmerker
# data/plugins/<ordner>/soll_laufen UEBERLEBT das Upgrade, und dieses
# preupgrade loescht ihn nicht. Der Cron-Waechter holt den Dienst also von
# selbst zurueck - binnen einer Minute. Der Merker hier macht daraus einen
# SOFORTIGEN Start und macht ihn unabhaengig vom Waechter; er behebt keinen
# Stillstand, er verkuerzt ein Fenster von bis zu 60 Sekunden, in dem
# Loxone auf alten Werten sitzt.
MERKER="$BASE/config/plugins/$PFOLDER.lief_vorher"
rm -f "$MERKER"

PID="$BASE/data/plugins/$PFOLDER/dienst.pid"
if [ -f "$PID" ]; then
    # Gefragt wird, ob der Vorgang WIRKLICH laeuft. Eine liegengebliebene
    # PID-Datei ist kein laufender Dienst - und sie darf nach dem Upgrade
    # keinen Start ausloesen, den niemand gewollt hat.
    if kill -0 "$(cat "$PID")" 2>/dev/null; then
        : > "$MERKER"
        echo "<INFO> Der Dienst lief - er wird nach dem Upgrade wieder gestartet."
    fi
    kill "$(cat "$PID")" 2>/dev/null || true
    sleep 2
    kill -9 "$(cat "$PID")" 2>/dev/null || true
    rm -f "$PID"
    echo "<INFO> Laufender Dienst angehalten."
fi

CFGDIR="$BASE/config/plugins/$PFOLDER"
for f in skoda.json zugang.json; do
    if [ -f "$CFGDIR/$f" ]; then
        cp -p "$CFGDIR/$f" "$BASE/config/plugins/$PFOLDER.backup.$f" || true
    fi
done
chmod 600 "$BASE/config/plugins/$PFOLDER.backup.zugang.json" 2>/dev/null || true
echo "<OK> preupgrade abgeschlossen."
exit 0
