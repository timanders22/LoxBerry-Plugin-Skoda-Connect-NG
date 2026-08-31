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
BASE="${ARGV5:-$LBHOMEDIR}"
if [ -z "$BASE" ] || [ ! -d "$BASE" ]; then
    SELF=$(cd "$(dirname "$0")" && pwd)
    BASE=$(cd "$SELF/../.." 2>/dev/null && pwd)
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

echo "<OK> postupgrade abgeschlossen."
exit 0
