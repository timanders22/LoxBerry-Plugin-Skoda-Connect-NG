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
# ZURUECKGENOMMEN am 31.08.2026, und das ist die zweite Berichtigung an
# dieser Stelle. Hier stand seit 0.9.6, purge_installation laufe
# "ausschliesslich im Deinstallations-Zweig (:233)", der Sollmerker
# ueberlebe das Upgrade und der Cron-Waechter hole den Dienst binnen einer
# Minute von selbst zurueck. Das war falsch: die Funktion hat ZWEI
# Aufrufstellen, und die zweite steht im Upgrade-Zweig.
#
# Nachgemessen an der Primaerquelle, nicht aus zweiter Hand -
# sbin/plugininstall.pl, Zweig master. Die Zeilennummern gelten fuer den
# Stand mit 2054 Zeilen / 65120 Byte (geholt 31.08.2026, am 01.09.2026
# byte-gleich nachgeprueft). Eine Zahl aus einer FREMDEN Datei ist nur mit
# ihrem Bezug ueberpruefbar; deshalb steht die suchbare Zeile daneben.
#
#   :858   if ($isupgrade) {
#   :859ff   darin zuerst die preupgrade*-Skripte
#   :886     &purge_installation;                  <- hier
#   :1626    if ($pfolder) {   - OHNE Pruefung auf $option eq "all"
#   :1629ff  rm -rfv config/plugins/$pfolder/ bin/ data/ templates/
#            und beide webfrontend/
#   :233   &purge_installation("all") im Deinstallations-Zweig; das "all"
#          schaltet nur ZUSAETZLICH Crontab und uninstall frei
#
# BERICHTIGT am 01.09.2026: hier stand :885. Um eins daneben - und das in
# dem Absatz, der einen Satz zuruecknimmt, WEIL er eine Zahl nannte, die
# nicht hielt. Aufgefallen erst nach dem Veroeffentlichen von 0.9.15.
#
# Was daraus folgt: zwischen diesem Skript und postinstall.sh wird
# data/plugins/<ordner>/ VOLLSTAENDIG abgeraeumt. Es ueberlebt nichts -
# weder der Sollmerker noch der Verlauf noch das Ladeprotokoll. Und der
# Waechter (bin/dienst.sh, "waechter") startet nur, wenn soll_laufen da
# ist; ohne ihn steht der Dienst still, waehrend die Installation Erfolg
# meldet.
#
# Deshalb wird hier NEBEN den Ordner gerettet, was ein Upgrade ueberstehen
# muss - ein "rm -rf <ordner>/" trifft den Nachbarn mit dem Punkt nicht -,
# und postinstall.sh legt es zurueck. Bewusst NICHT gerettet wird
# sitzung.json: darin steht der zwischengespeicherte Refresh-Token, und
# ein Geheimnis mehr ausserhalb des Konfigordners waere teurer als die
# eine zusaetzliche Anmeldung nach einem Update.
MERKER="$BASE/config/plugins/$PFOLDER.lief_vorher"
rm -f "$MERKER"

PDATA="$BASE/data/plugins/$PFOLDER"
PBIN="$BASE/bin/plugins/$PFOLDER"
PID="$PDATA/dienst.pid"

# Gehoert die Nummer wirklich unserem Dienst?
#
# "kill -0" beantwortet nur, DASS es die Nummer gibt, nicht WESSEN sie ist.
# Nach einem Neustart mit liegengebliebener PID-Datei und wiederverwendeter
# Nummer traf SIGTERM und zwei Sekunden spaeter SIGKILL einen unbeteiligten
# Vorgang - und der Startmerker wurde gesetzt, weil der Fremdvorgang als
# "unser Dienst lief" galt.
#
# Geprueft wird argumentweise gegen den VOLLEN Pfad: /proc/<pid>/cmdline
# trennt mit Nullbytes, das zweite Argument ist das Skript, das erste muss
# ein Python sein. Der volle Pfad, damit das Upgrade des einen Exemplars
# nicht den Dienst eines zweiten abschiesst (LoxBerry haengt bei
# Namenskonflikt 01, 02 ... an den Ordnernamen an). Wortgleich mit
# uninstall/uninstall und bin/dienst.sh.
ist_unser_dienst() {
    [ -r "/proc/$1/cmdline" ] || return 1
    ARGS=$(tr '\0' '\n' < "/proc/$1/cmdline" 2>/dev/null)
    [ "$(echo "$ARGS" | sed -n '2p')" = "$PBIN/skoda.py" ] || return 1
    echo "$ARGS" | sed -n '1p' | grep -qE '(^|/)python[0-9.]*$' || return 1
    return 0
}

if [ -f "$PID" ]; then
    PNUM=$(cat "$PID" 2>/dev/null)
    if [ -n "$PNUM" ] && ist_unser_dienst "$PNUM"; then
        : > "$MERKER"
        echo "<INFO> Der Dienst lief - er wird nach dem Upgrade wieder gestartet."
        kill "$PNUM" 2>/dev/null || true
        sleep 2
        kill -9 "$PNUM" 2>/dev/null || true
        echo "<INFO> Laufender Dienst angehalten."
    else
        # Kein Wort von "angehalten": es lief nichts. Bis 0.9.14 stand die
        # Zeile ausserhalb der Bedingung und behauptete das Gegenteil.
        echo "<INFO> Die PID-Datei war verwaist - es lief kein Dienst."
    fi
    rm -f "$PID"
fi

# Was ein Upgrade ueberstehen muss, wandert NEBEN den Ordner (siehe oben).
#
# DIE VORHANDENE RETTUNG WIRD ERST GELOESCHT, WENN EINE NEUE STEHT.
#
# Dieses Skript laeuft bei JEDEM Upgrade, und der Installateur raeumt
# data/plugins/<ordner>/ dazwischen ab. Bricht ein Upgrade nach preupgrade ab
# - kein Netz, Paketfehler, Neustart -, und der Anwender spielt erneut ein,
# dann ist der Datenordner bereits leer. Ein "rm -rf" gleich zu Beginn haette
# in diesem Lauf die Rettung des ersten geloescht und nichts Neues gefunden:
# Sollmerker, Mehrtagesverlauf und Ladeprotokoll waeren endgueltig weg. Genau
# der Verlust, den diese Stelle verhindern soll, nur einen Lauf spaeter.
#
# Nachgestellt: erster Lauf rettet 4 Eintraege, Installateur raeumt ab,
# Abbruch, zweiter Lauf - mit der alten Reihenfolge blieben 0 Eintraege.
RETTUNG="$BASE/data/plugins/$PFOLDER.rettung"
NEU="$BASE/data/plugins/$PFOLDER.rettung.neu"
rm -rf "$NEU"
if [ -d "$PDATA" ]; then
    mkdir -p "$NEU" 2>/dev/null
    for f in soll_laufen zustand.json ladungen.csv; do
        [ -e "$PDATA/$f" ] && cp -p "$PDATA/$f" "$NEU/$f" 2>/dev/null
    done
    [ -d "$PDATA/verlauf" ] && cp -a "$PDATA/verlauf" "$NEU/verlauf" 2>/dev/null
    # Gezaehlt, nicht behauptet: eine Rettung, die nichts gerettet hat,
    # sagt das - sonst steht in der Installationsmeldung eine Zusage, die
    # niemand geprueft hat.
    ANZ=$(find "$NEU" -mindepth 1 2>/dev/null | wc -l)
    if [ "$ANZ" -gt 0 ]; then
        rm -rf "$RETTUNG"
        mv "$NEU" "$RETTUNG" 2>/dev/null
        echo "<INFO> $ANZ Eintrag/Eintraege aus dem Datenordner gerettet"
        echo "<INFO> (Sollmerker, Verlauf, Ladeprotokoll) - der Installateur"
        echo "<INFO> raeumt data/plugins/$PFOLDER/ beim Upgrade vollstaendig ab."
    else
        rm -rf "$NEU"
        if [ -d "$RETTUNG" ]; then
            echo "<INFO> Im Datenordner lag nichts - die Rettung eines"
            echo "<INFO> frueheren, abgebrochenen Laufs bleibt unberuehrt."
        else
            echo "<INFO> Im Datenordner lag nichts, was zu retten waere."
        fi
    fi
elif [ -d "$RETTUNG" ]; then
    echo "<INFO> Kein Datenordner - die Rettung eines frueheren,"
    echo "<INFO> abgebrochenen Laufs bleibt unberuehrt."
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
