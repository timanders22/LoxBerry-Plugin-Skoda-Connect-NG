#!/bin/bash
# Skoda Connect - Start, Stopp und Waechter des Abrufdienstes.
#
# Die Pfade werden aus dem EIGENEN Ablageort abgeleitet, nicht ueber
# LoxBerry::System. Grund: LoxBerry::System leitet den Pluginordner aus dem
# Aufrufort ab; wird dieses Skript aus postinstall.sh oder aus dem Cron
# gestartet, kommt dort ueberall Leerstring zurueck - das Skript werkelt dann
# gegen /-Pfade und meldet trotzdem Erfolg.

# readlink -f loest Symlinks auf, BEVOR das Verzeichnis bestimmt wird.
# LoxBerry legt Daemons als Symlink unter system/daemons/plugins/ ab; von
# dort aufgerufen ergaebe dirname "$0" den Pfad .../system/daemons/plugins,
# der Pluginname waere buchstaeblich "plugins", und PID-Datei, Sollmerker
# und Logdatei landeten neben dem eigenen Ordner statt darin. Die
# Oberflaeche saehe den Dienst dann nie laufen, und der Waechter startete
# ihn im Minutentakt ein zweites Mal.
# Als loxberry laufen, nicht als root.
#
# Der minuetliche Waechter kommt aus dem Cron. Laeuft der als root - und je
# nach Ablage des Cronjobs tut er das -, dann gehoerten PID-Datei, Sollmerker
# und Protokoll danach root. Die Oberflaeche laeuft als loxberry und koennte
# den Dienst anschliessend weder anhalten noch neu starten: sie darf die
# Dateien nicht mehr schreiben. Schlimmer noch, 'dienst.sh stop' meldet dann
# Erfolg - das kill scheitert, aber das rm der PID-Datei gelingt, weil das
# Verzeichnis loxberry gehoert. Der Dienst laeuft weiter und ist nur noch
# ueber die Prozessliste zu finden.
#
# Deshalb setzt sich das Skript selbst herunter, EINMAL und bevor es
# irgendetwas anlegt. exec, damit kein zusaetzlicher Prozess stehen bleibt.
# '-s /bin/bash' ausdruecklich: ohne das nimmt su die Login-Shell aus
# /etc/passwd. Steht dort nologin oder /bin/false, endet dieses Skript hier
# still und ohne Meldung - und weil es 'exec' ist, kaeme nicht einmal ein
# Rueckgabewert zurueck. Auf einem regulaeren LoxBerry ist der Zweig ohnehin
# unerreichbar (der Cron laeuft bereits als loxberry); er greift nur, wenn
# jemand von Hand mit sudo aufruft.
#
# Woertlich uebernommen aus LoxBerry-Plugin-Dashboard-0.9.12, dort seit dem
# 16.08.2026 in Betrieb. Ueber den Bestand gezaehlt am 31.08.2026: 15 von 17
# dienst.sh hatten den Abstieg nicht, obwohl REGELN_2 ihn seit langem
# verlangt.
if [ "$(id -u)" = "0" ] && id loxberry >/dev/null 2>&1; then
    exec su -s /bin/bash loxberry -c "$(printf '%q ' "$0" "$@")"
fi

SELF=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)          # <home>/bin/plugins/<ordner>
PNAME=$(basename "$SELF")
LBHOMEDIR=$(cd "$SELF/../../.." && pwd)
PDATA="$LBHOMEDIR/data/plugins/$PNAME"
PLOG="$LBHOMEDIR/log/plugins/$PNAME"
PCONFIG="$LBHOMEDIR/config/plugins/$PNAME"
PID="$PDATA/dienst.pid"
SOLL="$PDATA/soll_laufen"
# Legt bin/skoda.py an, sobald die Bibliotheken geladen sind - SEIT 0.9.21.
# Siehe starten(): erst dieser Merker beantwortet "ist er wirklich angelaufen".
BEREIT="$PDATA/dienst.bereit"
LOGDATEI="$PLOG/skoda.log"
# Eigene Datei fuer alles, was NEBEN dem Protokoll anfaellt: Meldungen des
# Starts und alles, was das Programm nach stderr schreibt, bevor sein
# Protokoll steht (Syntaxfehler, fehlende Bibliothek, Abbruch im Importpfad).
#
# Bis 0.9.17 ging diese Ausgabe mit ">> $LOGDATEI" in DIESELBE Datei, die
# bin/skoda.py mit einem umlaufenden Handler fuehrt. Das haelt einen zweiten,
# anhaengenden Deskriptor auf diese Datei offen. Beim Ueberlauf benennt der
# Handler um, beim Leeren der Ramdisk verschwindet die Datei ganz - der
# Deskriptor dieser Shell zeigt danach weiter auf die weggeschobene oder
# geloeschte Datei, und was er traegt, sieht niemand mehr. Am Geraet gemessen
# (06.09.2026): sieben Dienste hielten so eine geloeschte Protokolldatei offen.
# Regel: genau einer schreibt in eine Protokolldatei.
STARTLOG="$PLOG/skoda_start.log"
PY="$SELF/venv/bin/python3"
SKRIPT="$SELF/skoda.py"

mkdir -p "$PDATA" "$PLOG" 2>/dev/null

laeuft() {
    [ -f "$PID" ] || return 1
    P=$(cat "$PID" 2>/dev/null)
    [ -n "$P" ] || return 1
    kill -0 "$P" 2>/dev/null || return 1
    # Nummernrecycling ausschliessen: der Prozess muss unser Skript sein.
    #
    # /proc/<pid>/cmdline trennt die Argumente mit Nullbytes. Eine
    # Teilstringsuche ueber die ganze Zeile ("grep -a skoda.py") traefe
    # drei Sorten Unbeteiligter:
    #   - ein zweites Exemplar dieses Plugins (LoxBerry haengt bei
    #     Namenskonflikt 01, 02 ... an den Ordnernamen an),
    #   - jeden Editor oder "tail", der die Datei gerade offen hat,
    #   - bei pgrep -f zusaetzlich die eigene Suche.
    #
    # Geprueft werden deshalb ZWEI Argumente, nicht eines. Bis 0.9.13 stand
    # hier nur das zweite gegen den vollen Pfad - und den traegt auch
    # "nano $SKRIPT" an genau dieser Stelle. Ein offener Editor galt damit
    # als laufender Dienst: "Dienst anhalten" haette auf ihn gezielt, und
    # der Waechter haette den echten Dienst nicht nachgestartet. Das erste
    # Argument muss deshalb ein Python sein - der Dienst wird immer als
    #   "$PY" "$SKRIPT"
    # gestartet. So haelt es bin/skoda.py in dienst_laeuft() bereits.
    #
    # DRITTE BEDINGUNG SEIT 0.9.23: der Dauerlaeufer hat GENAU ZWEI
    # Argumente. Dieselbe Datei wird auch als Einmallauf gestartet -
    # "$PY $SKRIPT --wachzeichen" aus cron/cron.01min jede Minute und
    # "$PY $SKRIPT --selbsttest" aus der Oberflaeche. Beide tragen argv[0]
    # Python und argv[1] genau diesen Pfad und waren damit von einem Dienst
    # nicht zu unterscheiden. Am 18.09.2026 in WSL gemessen
    # (Pruefung-Skoda-Connect-NG-0.9.23/messe_luecke.sh, Fall 8): die
    # Deinstallation beendete einen laufenden "--wachzeichen"-Lauf als
    # waere er der Dienst.
    ARGS=$(tr '\0' '\n' < "/proc/$P/cmdline" 2>/dev/null)
    [ "$(echo "$ARGS" | sed -n '2p')" = "$SKRIPT" ] || return 1
    echo "$ARGS" | sed -n '1p' | grep -qE '(^|/)python[0-9.]*$' || return 1
    # cmdline endet auf ein Nullbyte; die leere letzte Zeile zaehlt nicht mit.
    [ "$(echo "$ARGS" | sed '/^$/d' | wc -l)" -eq 2 ] || return 1
    return 0
}

# ---------- Laeuft gerade eine Aktualisierung dieses Plugins? ----------
#
# preupgrade.sh legt data/plugins/<ordner>.upgrade_laeuft als Erstes an,
# postupgrade.sh raeumt die Marke weg, uninstall ebenfalls. Sie liegt NEBEN
# dem Datenordner, weil purge_installation den Ordner selbst loescht
# (Regeln/06).
#
# Warum ueberhaupt: postinstall.sh legt den Sollmerker und die Zugangsdaten
# zurueck (Z. 105-141) und holt den Dienst erst Minuten spaeter zurueck
# (Z. 363) - dazwischen laedt pip die Bibliothek myskoda. Der Minutentakt
# fand in dieser Zeit einen Sollmerker ohne laufenden Dienst und startete
# ihn gegen die halb eingerichtete Umgebung. Am 18.09.2026 in WSL gemessen
# (Pruefung-Skoda-Connect-NG-0.9.23/messe_luecke.sh, Fall 3: ein Dienst,
# erwartet null).
#
# Aelter als 3600 s, aus der Zukunft oder unlesbar: die Marke gilt NICHT -
# eine abgebrochene Installation darf den Dienst nicht fuer immer
# stilllegen. OHNE LESBARE UHR faellt die Pruefung GESCHLOSSEN aus: wer die
# Zeit nicht messen kann, kann das Alter nicht beurteilen und startet
# deshalb nicht (Fall 7f).
#
# SK_START_TROTZ_MARKE=1 ist die Ausnahme fuer postinstall.sh: dort SOLL der
# Dienst wieder anlaufen, obwohl die Marke noch liegt - postupgrade.sh
# raeumt sie erst danach weg.
MARKE="$LBHOMEDIR/data/plugins/$PNAME.upgrade_laeuft"

upgrade_laeuft() {
    [ -f "$MARKE" ] || return 1
    [ -n "${SK_START_TROTZ_MARKE:-}" ] && return 1
    sk_dann=$(cat "$MARKE" 2>/dev/null)
    case "$sk_dann" in ''|*[!0-9]*) return 1 ;; esac
    # Die Uhr wird gemessen, nicht angenommen: liefert "date" nichts - unter
    # Last kann ein fork scheitern -, rechnete die Schale mit einer leeren
    # Zeichenkette, das Alter fiele negativ aus, und der Dienst liefe mitten
    # in der Aktualisierung an. Ohne lesbare Uhr GILT die Marke.
    # Aufbau wortgleich mit Chromecast4lox 1.3.11 (daemon/daemon:93-100) -
    # dort ist er gemessen, und das Werkzeug der Bestandsaufnahme erkennt
    # genau diese Form wieder.
    sk_jetzt=$(date +%s 2>/dev/null)
    case "$sk_jetzt" in ''|*[!0-9]*) sk_jetzt="" ;; esac
    if [ -z "$sk_jetzt" ]; then
        return 0
    fi
    [ "$sk_dann" -gt "$sk_jetzt" ] && return 1
    [ $((sk_jetzt - sk_dann)) -lt 3600 ]
}

# Stehen Benutzername UND Passwort in der Zugangsdatei? NEU IN 0.9.21.
#
# Bis 0.9.20 fragte starten() nur, ob die Datei EXISTIERT. postinstall.sh
# legt sie bei jeder Neuinstallation als "{}" an - die Pruefung war damit
# immer erfuellt. Am Geraet gemessen (17.09.2026, 0.9.20 frisch installiert,
# zugang.json = "{}"): "dienst.sh start" gab 0 zurueck, setzte den
# Sollmerker, und der Dienst wartete mit "Zugangsdaten fehlen". Regeln/03:
# der Sollmerker wird erst nach erfolgreicher Pruefung gesetzt.
#
# Gelesen wird mit dem Python der eigenen Umgebung, nicht mit grep: eine
# Zeichenkettensuche hielte {"email": "", "passwort": ""} fuer vollstaendig.
# Ist die Datei beschaedigt, gilt die Zweitschrift - so haelt es auch
# bin/skoda.py (_mit_zweitschrift). Ausgegeben wird nichts aus der Datei.
zugang_vollstaendig() {
    "$PY" -c 'import json, sys
def lesen(pfad):
    try:
        with open(pfad, encoding="utf-8") as f:
            z = json.load(f)
    except Exception:
        return None
    return z if isinstance(z, dict) else None
z = lesen(sys.argv[1])
if z is None:
    z = lesen(sys.argv[2]) or {}
ok = str(z.get("email") or "").strip() != "" and str(z.get("passwort") or "") != ""
sys.exit(0 if ok else 1)' "$PCONFIG/zugang.json" "$LBHOMEDIR/config/plugins/$PNAME.backup.zugang.json" 2>/dev/null
}

starten() {
    # Die Marke steht VOR allem anderen: solange sie gilt, wird nichts
    # gestartet und nichts angelegt. Kein Fehler - der Minutentakt soll sich
    # nicht beschweren, und postinstall.sh startet gleich selbst (mit
    # SK_START_TROTZ_MARKE=1). Die Pruefung sitzt hier und nicht im
    # case-Verteiler, damit sie fuer 'start', 'restart' UND den Zweig
    # 'waechter' gilt - alle drei fuehren hierher.
    if upgrade_laeuft; then
        echo "Eine Aktualisierung dieses Plugins laeuft - es wird nichts gestartet."
        return 0
    fi
    if laeuft; then
        echo "laeuft bereits (PID $(cat "$PID"))"
        return 0
    fi
    if [ ! -x "$PY" ]; then
        rm -f "$SOLL"
        echo "FEHLER: virtuelle Python-Umgebung fehlt ($PY). Plugin neu installieren."
        return 1
    fi
    if ! zugang_vollstaendig; then
        rm -f "$SOLL"
        echo "FEHLER: Es sind keine vollstaendigen Zugangsdaten hinterlegt ($PCONFIG/zugang.json)."
        echo "        Erst im Reiter Einstellungen Benutzername und Passwort des MySkoda-Kontos"
        echo "        eintragen und speichern. Der Dienst bleibt angehalten; der Waechter holt ihn nicht zurueck."
        return 1
    fi
    touch "$SOLL"
    rm -f "$BEREIT"
    # Die Ausgabe des Dienstes geht in die Startdatei, NICHT in das Protokoll:
    # dort schreibt allein der Handler des Programms. Beim Start gekappt, damit
    # sie nur die Ausgabe EINES Laufes sammelt und nicht unbegrenzt waechst.
    # Der Waechter kappt selbst, bevor er seine Fehlerausgabe hineinlenkt,
    # und setzt STARTLOG_KAPPEN=0 - sonst ginge hier verloren, was er
    # vorher schon hineingeschrieben hat.
    [ "${STARTLOG_KAPPEN:-1}" = 0 ] || : > "$STARTLOG"
    nohup "$PY" "$SKRIPT" >> "$STARTLOG" 2>&1 &
    echo $! > "$PID"
    # HINSEHEN, BIS ER WIRKLICH ANGELAUFEN IST - BERICHTIGT IN 0.9.21.
    #
    # Bis 0.9.20 stand hier ein einzelnes "sleep 1". Im Sandkasten am Geraet
    # gemessen (17.09.2026, drei Laeufe je Fall): mit einer Bibliothek, die
    # erst nach dem Laden von aiohttp und cryptography abbricht, meldete
    # dienst.sh "gestartet" mit Rueckgabewert 0, und der Prozess war kurz
    # danach tot. Die drei Sekunden aus Regeln/03 reichen hier nicht: ein
    # gesunder Start braucht auf dem Pi kalt 6 bis 12 Sekunden, bis die
    # Bibliotheken geladen sind - ein Abbruch am Ende dieses Weges faellt in
    # die Zeit danach.
    #
    # Deshalb wartet diese Stelle auf den Merker, den bin/skoda.py nach dem
    # Laden anlegt: mindestens drei Sekunden, hoechstens dreissig. Stirbt der
    # Prozess vorher, ist der Start gescheitert. Laeuft er nach dreissig
    # Sekunden noch ohne Merker, wird das gesagt - geraten wird nicht.
    i=0
    while [ "$i" -lt 30 ]; do
        sleep 1
        i=$((i + 1))
        laeuft || break
        [ "$i" -ge 3 ] && [ -f "$BEREIT" ] && break
    done
    if laeuft; then
        if [ -f "$BEREIT" ]; then
            echo "gestartet (PID $(cat "$PID"))"
        else
            echo "gestartet (PID $(cat "$PID")) - nach $i Sekunden noch beim Laden der Bibliotheken."
        fi
        return 0
    fi
    # Stirbt er gleich nach dem Start, hilft ein Neustart je Minute nicht:
    # Sollmerker fort, und die letzten Zeilen gehoeren in die Meldung
    # (Regeln/03), nicht nur ein Verweis auf zwei Dateien. Gemessen am Geraet
    # (17.09.2026): mit liegendem Sollmerker startete der Waechter den toten
    # Dienst bei jedem Lauf neu, jedes Mal mit einer Zeile im Protokoll.
    rm -f "$PID" "$SOLL" "$BEREIT"
    echo "FEHLER: Der Dienst hat sich nach $i Sekunden wieder beendet."
    echo "        Der Waechter holt ihn nicht zurueck, bis er von Hand gestartet wird."
    if [ -s "$LOGDATEI" ]; then
        echo "Letzte Zeilen aus $LOGDATEI:"
        tail -n 3 "$LOGDATEI" | sed 's/^/    /'
    fi
    if [ -s "$STARTLOG" ]; then
        echo "Ausgabe des Starts ($STARTLOG):"
        tail -n 5 "$STARTLOG" | sed 's/^/    /'
    fi
    return 1
}

anhalten() {
    rm -f "$SOLL"
    if ! laeuft; then
        rm -f "$PID"
        echo "laeuft nicht"
        return 0
    fi
    P=$(cat "$PID")
    kill "$P" 2>/dev/null
    # 70 Sekunden, nicht 10.
    #
    # Das Signal setzt nur einen Merker; geprueft wird er im Sekundentakt der
    # Wartezeit und am Kopf der Hauptschleife - NICHT waehrend eines Abrufs.
    # Ein einzelner haengender Endpunkt braucht schon 30 s (GRENZE_ABRUF), ein
    # laufender Schreibbefehl bis zu 60 (GRENZE_BEFEHL). Mit zehn Sekunden war
    # das harte Toeten bei jeder Stoerung der Normalfall statt der Ausnahme -
    # und ein kill -9 mitten in der Warteschlange laesst einen Befehl spurlos
    # verschwinden: die Datei ist schon geloescht, die Antwort noch nicht
    # geschrieben. Der Ausloeser sieht dann OK=2 und wartet auf etwas, das
    # nicht mehr kommt.
    i=0
    while [ "$i" -lt 70 ]; do
        laeuft || break
        sleep 1
        i=$((i + 1))
    done
    if laeuft; then
        kill -9 "$P" 2>/dev/null
        sleep 1
    fi
    # NACHSEHEN, ob er wirklich weg ist - SEIT 0.9.21, uebernommen aus
    # AudiConnect 0.9.12. Bis 0.9.20 folgte hier ohne Pruefung "rm -f $PID"
    # und "angehalten". Gehoert der Vorgang einem anderen Benutzer, scheitert
    # das kill mit EPERM, das rm gelingt aber, weil das Verzeichnis loxberry
    # gehoert. Danach meldet "laeuft" false, und ein anschliessendes "start"
    # legt ein ZWEITES Exemplar an.
    if laeuft; then
        echo "FEHLER: Vorgang $P ist noch da - die PID-Datei bleibt stehen."
        echo "        Gehoert er einem anderen Benutzer? ps -o user= -p $P"
        return 1
    fi
    rm -f "$PID" "$BEREIT"
    echo "angehalten"
    return 0
}

case "$1" in
    start)   starten ;;
    stop)    anhalten ;;
    restart) anhalten; sleep 1; starten ;;
    status)
        if laeuft; then
            echo "laeuft $(cat "$PID")"
            exit 0
        fi
        echo "gestoppt"
        exit 1
        ;;
    wachzeichen)
        # Ein einziges MQTT-Thema: laeuft der Dienst? Ohne virtuelle Umgebung
        # gibt es nichts zu melden - und kein Fehler, denn der Cron laeuft auch
        # in der Minute zwischen Entpacken und Einrichten.
        [ -x "$PY" ] && "$PY" "$SKRIPT" --wachzeichen >/dev/null 2>&1
        exit 0
        ;;
    waechter)
        # Nur neu starten, wenn der Dienst laufen SOLL. Ein bewusst
        # angehaltener Dienst bleibt angehalten.
        #
        # SEIT 0.9.21, uebernommen aus AudiConnect 0.9.15/0.9.16: ohne
        # Zugangsdaten gar nicht erst anlaufen, sondern den Sollmerker
        # zuruecknehmen und es EINMAL sagen. Und scheitert der Neustart, sagt
        # das Protokoll es, statt nur die Startdatei.
        # Die Marke wird HIER schon gefragt und nicht erst in starten():
        # sonst kappte der Waechter die Startdatei und schriebe eine Zeile
        # "Dienst lief nicht, wird neu gestartet" ins Protokoll, obwohl
        # gleich darauf nichts gestartet wird. Eine Meldung, die etwas
        # anderes sagt als der Vorgang tut, ist schlimmer als keine.
        if [ -f "$SOLL" ] && ! laeuft && ! upgrade_laeuft; then
            # Die Fehlerausgabe DIESES Skripts geht, sobald der Waechter etwas
            # tut, in die Startdatei. cron/cron.01min ruft mit
            # ">/dev/null 2>&1" auf, und damit verschwand bis 0.9.20 jede
            # Meldung der Schale (Regeln/03: der Cron verschluckt seine
            # Fehlerausgabe nicht). Die Umlenkung steht HIER und nicht in der
            # Cron-Datei, damit sie auch fuer einen Aufruf von Hand gilt.
            # Erst kappen, dann umlenken; starten() kappt deshalb hier nicht
            # noch einmal.
            : > "$STARTLOG"
            exec 2>>"$STARTLOG"
            jetzt=$(date '+%Y-%m-%d %H:%M:%S')
            if [ -x "$PY" ] && ! zugang_vollstaendig; then
                rm -f "$SOLL"
                echo "[$jetzt] Waechter: keine Zugangsdaten - Dienst bleibt angehalten, Sollmerker entfernt." >> "$LOGDATEI"
                exit 0
            fi
            echo "[$jetzt] Waechter: Dienst lief nicht, wird neu gestartet." >> "$LOGDATEI"
            # Gesammelt und danach angehaengt: starten() zitiert im Fehlerfall
            # aus der Startdatei, eine Umleitung in dieselbe Datei liefe im
            # Kreis.
            if ausgabe=$(STARTLOG_KAPPEN=0 starten 2>&1); then
                printf '%s\n' "$ausgabe" >> "$STARTLOG"
            else
                printf '%s\n' "$ausgabe" >> "$STARTLOG"
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waechter: Neustart gescheitert - Sollmerker entfernt, Einzelheiten in $STARTLOG." >> "$LOGDATEI"
            fi
        fi
        ;;
    *)
        echo "Aufruf: $0 {start|stop|restart|status|waechter|wachzeichen}"
        exit 2
        ;;
esac
