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
        # LoxBerry::System taugt hier nicht - es leitet den Pluginordner aus
        # dem Aufrufort ab und liefert aus einem Installationsskript heraus
        # ueberall Leerstring.
        BASE=$(sk_wurzel_suchen) || BASE=""
    fi
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

# ---------- Die Upgrade-Marke, als ERSTES ----------
#
# Zwischen dem Kopieren der neuen Dateien und postinstall.sh liegt fast eine
# Minute (Regeln/06, am Geraet gemessen: Cron-Datei neu angelegt 03:31:32,
# postinstall erst 03:32:24). In dieser Zeit laeuft der Minutentakt, und die
# Oberflaeche ist erreichbar, obwohl config/plugins/<ordner>/ und
# data/plugins/<ordner>/ gerade geloescht sind.
#
# Fuer DIESE Linie am 18.09.2026 in WSL gemessen
# (Pruefung-Skoda-Connect-NG-0.9.23/messe_luecke.sh):
#   Fall 5  Oberflaeche in der Luecke, Formular unveraendert abgesendet:
#           zugang.json wurde mit {"email":"","passwort":""} neu geschrieben.
#           postinstall.sh haelt eine solche Datei fuer gefuellt und spielt
#           die Zweitschrift NICHT zurueck - das Passwort war nach der
#           Aktualisierung weg, ohne eine Zeile im Protokoll.
#   Fall 3  Der Minutentakt im postinstall-Fenster (Sollmerker und
#           Zugangsdaten sind zurueckgelegt, die Bibliothek wird noch
#           geladen) startete den Dienst mitten in der Installation.
#
# Die Marke liegt NEBEN dem Datenordner - purge_installation loescht
# data/plugins/<ordner>/, den Nachbarn mit dem Punkt trifft es nicht. Sie
# traegt die Unixzeit; bin/dienst.sh und die Oberflaeche achten sie, solange
# sie juenger als 3600 s ist. postupgrade.sh raeumt sie weg (das letzte
# Hakenskript dieser Linie), uninstall ebenfalls.
#
# Als ERSTES in dieser Datei, damit zwischen Marke und Luecke kein Takt liegt.
MARKE="$BASE/data/plugins/$PFOLDER.upgrade_laeuft"
mkdir -p "$BASE/data/plugins" 2>/dev/null
if date +%s > "$MARKE" 2>/dev/null && [ -s "$MARKE" ]; then
    echo "<OK> Aktualisierung angemeldet - Minutentakt und Oberflaeche halten still."
else
    # Die Wirkung pruefen, nicht den Rueckgabewert (Kernschicht 2). Ohne
    # Marke laeuft die Aktualisierung weiter, nur eben mit dem alten Risiko.
    rm -f "$MARKE" 2>/dev/null
    echo "<WARNING> Die Marke $MARKE liess sich nicht anlegen; der Minutentakt"
    echo "<WARNING> koennte den Dienst mitten in der Aktualisierung starten."
fi

# ---------- Eine Rettung aus einem FRUEHEREN Lauf (I1, Durchgang 01.10.2026) ----------
#
# Entscheidung 1: preupgrade.sh raeumt einen alten Bestand weg, bevor es einen
# neuen anlegt - bei einem Upgrade wird nie ein Bestand aus einem frueheren
# Vorgang eingespielt. Bis 0.9.28 blieb eine solche Rettung liegen, wenn im
# Datenordner nichts zu retten war (Installerbericht, Hinweis). Sie wird nicht
# geloescht, sondern nach .alt gelegt (ein vorhandenes .alt vorher abgeraeumt);
# uninstall raeumt die .alt ab. Diese Lage entsteht nur, wenn ein frueheres
# Upgrade nach preupgrade abbrach.
SK_RETTUNG_ALT="$BASE/data/plugins/$PFOLDER.rettung"
if [ -e "$SK_RETTUNG_ALT" ] || [ -L "$SK_RETTUNG_ALT" ]; then
    if [ -L "$SK_RETTUNG_ALT.alt" ]; then
        rm -f "$SK_RETTUNG_ALT.alt"
    elif [ -e "$SK_RETTUNG_ALT.alt" ]; then
        rm -rf "${SK_RETTUNG_ALT:?}.alt"
    fi
    if mv -f "$SK_RETTUNG_ALT" "$SK_RETTUNG_ALT.alt" 2>/dev/null; then
        echo "<WARNING> Eine Rettung aus einem frueheren, abgebrochenen Upgrade wurde nicht wiederverwendet, sondern beiseitegelegt: $SK_RETTUNG_ALT.alt"
    else
        echo "<WARNING> Eine Rettung aus einem frueheren Upgrade liess sich nicht beiseitelegen: $SK_RETTUNG_ALT"
    fi
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
# DRITTE BEDINGUNG SEIT 0.9.23: GENAU ZWEI Argumente. bin/skoda.py laeuft
# auch als Einmallauf ("--wachzeichen" aus dem Minutentakt, "--selbsttest"
# aus der Oberflaeche); beide tragen dasselbe argv[0] und argv[1]. Ein
# Einmallauf ist kein Dienst.
ist_unser_dienst() {
    [ -r "/proc/$1/cmdline" ] || return 1
    ARGS=$( { tr '\0' '\n' < "/proc/$1/cmdline"; } 2>/dev/null )
    [ "$(echo "$ARGS" | sed -n '2p')" = "$PBIN/skoda.py" ] || return 1
    echo "$ARGS" | sed -n '1p' | grep -qE '(^|/)python[0-9.]*$' || return 1
    # cmdline endet auf ein Nullbyte; die leere letzte Zeile zaehlt nicht mit.
    [ "$(echo "$ARGS" | sed '/^$/d' | wc -l)" -eq 2 ] || return 1
    return 0
}

# DER SOLLMERKER WIRD VOR DEM ANHALTEN GELESEN - seit 0.9.21. "dienst.sh stop"
# nimmt ihn weg (so soll es sein: ein angehaltener Dienst soll nicht
# zurueckkommen). Die Rettung weiter unten faende danach nichts mehr, und ein
# Dienst, der nach dem Upgrade von selbst wieder anlaufen sollte, bliebe stehen.
SOLL_VORHER=0
[ -e "$PDATA/soll_laufen" ] && SOLL_VORHER=1

# ANGEHALTEN WIRD UEBER dienst.sh - seit 0.9.21 (Regeln/06, Hausmuster).
#
# Bis 0.9.20 stand hier "kill", zwei Sekunden Pause und "kill -9". Der Dienst
# braucht zum geordneten Ende bis zu 70 Sekunden (bin/dienst.sh, anhalten():
# ein haengender Abruf 30 s, ein Schreibbefehl bis 60 s) - nach zwei Sekunden
# traf ihn also regelmaessig das harte Toeten, mitten in der Warteschlange.
# Und die PID-Datei ist kein Beleg (Regeln/06): gefragt wird "dienst.sh status",
# der den Vorgang argumentweise gegen den vollen Pfad prueft.
#
# Aufgerufen wird das dienst.sh der INSTALLIERTEN, also der alten Fassung - die
# neue ist noch nicht ausgepackt. Fehlt es, bleibt der Weg ueber die Nummer.
DIENSTSH="$PBIN/dienst.sh"
#
# "stop" wird in JEDEM Fall gerufen, auch wenn nichts laeuft: es raeumt den
# Sollmerker und eine verwaiste PID-Datei mit ab. Gesagt wird "angehalten"
# aber nur, wenn vorher etwas lief.
# JEDER EIGENE DIENST, NICHT NUR DER AUS DER PID-DATEI (C3, Durchgang 01.10.2026).
#
# Bis 0.9.28 fragte dieser Block nur das dienst.sh der installierten Fassung,
# und das kennt nur die PID-Datei: eine Waise aus einem Doppelstart lief
# weiter, ueberstand das Upgrade mit dem ALTEN Code, und die Meldung lautete
# trotzdem "angehalten" (gemessen, Installerbericht D2: vorher 2 Dienste,
# nach preupgrade 1). Jetzt: erst geordnet ueber dienst.sh (bis 70 s), dann
# jeder uebrige eigene Vorgang - argumentweise mit ist_unser_dienst() -, und
# "angehalten" steht nur da, wenn danach KEINER mehr laeuft.
eigene_dienste() {
    for sk_f in $(grep -laF -- "$PBIN/skoda.py" /proc/[0-9]*/cmdline 2>/dev/null); do
        sk_n=${sk_f#/proc/}
        sk_n=${sk_n%/cmdline}
        ist_unser_dienst "$sk_n" && echo "$sk_n"
    done
}
VORHER=$(eigene_dienste | tr '\n' ' ')
LIEF=0
[ -n "${VORHER// /}" ] && LIEF=1
AUSGABE=""
if [ -x "$DIENSTSH" ]; then
    "$DIENSTSH" status >/dev/null 2>&1 && LIEF=1
    AUSGABE=$("$DIENSTSH" stop 2>&1)
fi
rm -f "$PID"
REST=$(eigene_dienste | tr '\n' ' ')
if [ -n "${REST// /}" ]; then
    for P in $REST; do kill "$P" 2>/dev/null; done
    i=0
    while [ "$i" -lt 70 ]; do
        NOCH=""
        for P in $REST; do ist_unser_dienst "$P" && NOCH="$NOCH $P"; done
        [ -z "$NOCH" ] && break
        sleep 1
        i=$((i + 1))
    done
    for P in $REST; do ist_unser_dienst "$P" && kill -9 "$P" 2>/dev/null; done
    sleep 1
fi
UEBRIG=$(eigene_dienste | tr '\n' ' ')
[ "$LIEF" = 1 ] && : > "$MERKER"
if [ -n "${UEBRIG// /}" ]; then
    echo "<WARNING> Der Dienst liess sich nicht anhalten (PID ${UEBRIG% }). $AUSGABE"
elif [ "$LIEF" = 1 ]; then
    echo "<INFO> Der Dienst lief - er wird nach dem Upgrade wieder gestartet."
    echo "<INFO> Angehalten: $(echo $VORHER | wc -w) eigene(r) Dienst(e) gezaehlt, danach laeuft keiner mehr."
else
    echo "<INFO> Es lief kein Dienst."
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
    for f in zustand.json ladungen.csv; do
        [ -e "$PDATA/$f" ] && cp -p "$PDATA/$f" "$NEU/$f" 2>/dev/null
    done
    # Der Sollmerker nach dem Stand VOR dem Anhalten (siehe oben).
    [ "$SOLL_VORHER" = 1 ] && : > "$NEU/soll_laufen"
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

# ---------- Zweitschriften: NUR JSON-OBJEKTE (I2, Durchgang 01.10.2026) ----------
#
# Die Zweitschrift ist die laufende Rueckfallkopie: die Oberflaeche erneuert
# sie erst nach gelungenem Zuruecklesen, bin/skoda.py liest sie bei Schaden.
# Bis 0.9.28 kopierte dieses Skript mit cp -p OHNE Pruefung darueber - gerade
# im Fall, fuer den es sie gibt (Datei beschaedigt), zerstoerte das Update sie:
# danach ein neues Aktionstoken bzw. ein verlorenes Passwort, und im Protokoll
# stand <OK> (gemessen, Installerbericht B1/B2). Jetzt: nur eine Datei, die
# sich als JSON-Objekt lesen laesst; gebaut unter .neu, geprueft, dann
# umbenannt. Sonst bleibt die vorhandene Zweitschrift unberuehrt, und es steht
# eine <WARNING> da. 0600 fuer beide (C9).
json_objekt() {
    command -v python3 >/dev/null 2>&1 || return 2
    python3 -c 'import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        d = json.load(f)
except Exception:
    sys.exit(1)
sys.exit(0 if isinstance(d, dict) else 1)' "$1" 2>/dev/null
}
CFGDIR="$BASE/config/plugins/$PFOLDER"
for f in skoda.json zugang.json; do
    QUELLE="$CFGDIR/$f"
    ZIEL="$BASE/config/plugins/$PFOLDER.backup.$f"
    [ -f "$QUELLE" ] || continue
    json_objekt "$QUELLE"
    sk_rc=$?
    if [ "$sk_rc" = 1 ]; then
        echo "<WARNING> $f ist kein gueltiges JSON-Objekt - die vorhandene Zweitschrift bleibt unberuehrt ($ZIEL)."
        continue
    fi
    if [ "$sk_rc" = 2 ] && { [ -e "$ZIEL" ] || [ -L "$ZIEL" ]; }; then
        echo "<WARNING> python3 fehlt - $f liess sich nicht pruefen; die vorhandene Zweitschrift bleibt unberuehrt."
        continue
    fi
    rm -f "$ZIEL.neu"
    if cp -p "$QUELLE" "$ZIEL.neu" 2>/dev/null && chmod 600 "$ZIEL.neu" \
       && { [ "$sk_rc" = 2 ] || json_objekt "$ZIEL.neu"; } && mv -f "$ZIEL.neu" "$ZIEL"; then
        [ "$sk_rc" = 2 ] && echo "<WARNING> python3 fehlt - $f wurde ungeprueft gesichert ($ZIEL)."
    else
        rm -f "$ZIEL.neu"
        echo "<WARNING> $f liess sich nicht sichern - die vorhandene Zweitschrift bleibt unberuehrt ($ZIEL)."
    fi
done
echo "<OK> preupgrade abgeschlossen."
exit 0
