#!/bin/bash

# Skoda Connect - preinstall
# command <TEMPFOLDER-KENNUNG> <NAME> <FOLDER> <VERSION> <BASEFOLDER> <WORKDIR>
#
# Neu im Nachzug G1 vom 02.10.2026 (X-1, Entscheidung 1 vom 29.09.2026;
# Muster: Govee 0.9.24, Abfahrts-Assistent 1.6.16). Der Installer ruft dieses
# Skript bei JEDEM Einbau auf, nach dem Aufraeumen der alten Fassung und VOR
# dem Kopieren von Konfiguration, Cron-Datei und Oberflaeche
# (sbin/plugininstall.pl: preupgrade :846, purge :874, preinstall :877,
# Cron :990, HTML :1066 - Geraet/2026-09-05/08_plugininstall.pl).
#
# Eine Aktualisierung erkennt es allein an der Marke
# data/plugins/<ordner>.upgrade_laeuft, die preupgrade.sh anlegt (kein
# Altersvergleich). Dann tut es nichts: die Zweitschriften, die Rettung und
# der Startmerker gehoeren postinstall.sh.
#
# Ohne Marke ist es eine NEUINSTALLATION. Was eine fruehere Installation
# hinterlassen hat - <ordner>.backup.skoda.json (Konfiguration mit
# Aktionstoken), <ordner>.backup.zugang.json (MySkoda-Konto und Passwort),
# data/plugins/<ordner>.rettung und config/plugins/<ordner>.lief_vorher -
# geht nach <name>.alt, gemeldet mit genau einer <WARNING>. Dieselbe Liste
# wie in postinstall.sh (I1); dort bleibt der Zweig als Rueckfall und findet
# danach nichts mehr.
#
# Warum schon hier: zwischen dem Kopieren und postinstall.sh ist die
# Oberflaeche schon da. Wer sie in dieser Luecke oeffnet, ruft
# sk_config_heilen() - bei fehlender skoda.json holt sie die Konfiguration aus
# der Zweitschrift, und die neue Installation traegt das alte Aktionstoken
# (gemessen im Nachzug G1, vb_g1_bau_skripte/sk/proben/x1_*). Die
# Selbstheilung liest .alt nie; die Deinstallation raeumt es ab.

ARGV3=$3
ARGV5=$5
# Rueckfall, falls sudo die Umgebung ausgeraeumt hat (env_reset).
LBHOMEDIR="${LBHOMEDIR:-$5}"
PFOLDER="${ARGV3:-skodaconnect}"
BASE="${ARGV5:-$LBHOMEDIR}"

# Wurzelsuche: ohne config/plugins, data/plugins UND config/system/general.json
# wird nichts angefasst (Regeln/06, Raumklima-Vorfall).
if [ -z "$BASE" ] || [ ! -d "$BASE/config/plugins" ] || [ ! -d "$BASE/data/plugins" ] \
   || [ ! -f "$BASE/config/system/general.json" ]; then
    echo "<WARNING> Kein LoxBerry-Wurzelverzeichnis erkannt ('$BASE') - nichts beiseitegelegt."
    exit 0
fi
# Der Ordnername darf keinen Pfadtrenner tragen, sonst griffe mv/rm daneben.
case "$PFOLDER" in
    ''|*/*|*..*) echo "<WARNING> Unzulaessiger Ordnername '$PFOLDER' - nichts beiseitegelegt."; exit 0 ;;
esac

if [ -f "$BASE/data/plugins/$PFOLDER.upgrade_laeuft" ]; then
    # Aktualisierung: nichts zu tun, postinstall.sh spielt zurueck.
    exit 0
fi

# Wie alt_entfernen() in postinstall.sh: ein Verweis nur als Verweis, eine
# Datei vorher ueberschrieben (sie kann ein Passwort tragen).
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

ALT_LISTE=""
for z in "$BASE/config/plugins/$PFOLDER.backup.skoda.json" \
         "$BASE/config/plugins/$PFOLDER.backup.zugang.json" \
         "$BASE/data/plugins/$PFOLDER.rettung" \
         "$BASE/config/plugins/$PFOLDER.lief_vorher"; do
    [ -e "$z" ] || [ -L "$z" ] || continue
    if [ -e "$z.alt" ] || [ -L "$z.alt" ]; then
        alt_entfernen "$z.alt"
    fi
    if mv -f "$z" "$z.alt" 2>/dev/null; then
        ALT_LISTE="$ALT_LISTE $z.alt"
        [ -f "$z.alt" ] && [ ! -L "$z.alt" ] && chmod 600 "$z.alt" 2>/dev/null
    else
        ALT_LISTE="$ALT_LISTE $z (liess sich NICHT verschieben)"
    fi
done
if [ -n "$ALT_LISTE" ]; then
    echo "<WARNING> Neuinstallation: Zweitschriften und Bestaende einer frueheren Installation wurden nicht eingespielt, sondern beiseitegelegt:$ALT_LISTE - der Dienst wird nicht gestartet; die Deinstallation raeumt sie ab."
fi
exit 0
