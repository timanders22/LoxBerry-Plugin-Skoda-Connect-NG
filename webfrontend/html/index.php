<?php
/**
 * Skoda Connect - Endpunkt fuer den Miniserver
 *
 * Liegt im unangemeldeten Bereich, damit Loxone ihn ohne Zugangsdaten
 * erreicht, und ist deshalb durch ein Token geschuetzt. Verglichen wird mit
 * hash_equals, also in gleichbleibender Zeit - ein einfaches == liesse sich
 * ueber die Antwortzeit Zeichen fuer Zeichen erraten.
 *
 *   /plugins/<ordner>/index.php?token=<TOKEN>&aktion=<Befehl>
 *
 * Lesende Aktionen:
 *   status   [&fahrzeug=N]   Hauptwerte des Fahrzeugs
 *   laden    [&fahrzeug=N]   Ladewerte (nur bei Elektro und Hybrid belegt)
 *   wartung  [&fahrzeug=N]   Inspektion, Oelservice, Warnleuchten
 *   position [&fahrzeug=N]   Standort
 *   fahrzeuge                Liste der erkannten Fahrzeuge
 *   ladungen [&fahrzeug=N]   abgeschlossene Ladevorgaenge, neueste zuerst
 *   roh                      vollstaendiges Abbild als JSON (Fehlersuche)
 *
 * Schaltende Aktionen (nur wenn im Reiter Einstellungen zugelassen):
 *   klima_start &temp=<Grad>    klima_stop
 *   zieltemperatur &temp=<Grad>
 *   laden_start                 laden_stop
 *   ladegrenze &prozent=<%>
 *   scheibe_ein                 scheibe_aus
 *   lueftung_start              lueftung_stop
 *   wecken
 *   abruf                       sofortiger Abruf statt Warten auf den Takt
 *
 * Die Liste steht nicht mehr hier drin, sondern in sk_befehle() - dieser
 * Kommentar beschreibt sie nur. Wer eine Aktion ergaenzt, aendert dort.
 *
 * Der Endpunkt spricht NIE selbst mit der Skoda-Cloud. Lesende Aktionen
 * beantwortet er aus dem Zwischenspeicher, schaltende legt er in einer
 * Warteschlange ab, die der Dienst abarbeitet.
 *
 * Ein Strich als Wert bedeutet: dieser Wert liegt nicht vor. Es wird bewusst
 * keine 0 gesendet - eine 0 waere eine stille Falschaussage. Loxone behaelt
 * dann den letzten gueltigen Wert; genau das ist bei einem fehlenden Messwert
 * richtig.
 */

error_reporting(E_ALL & ~E_DEPRECATED & ~E_NOTICE);
/* Dieser Endpunkt antwortet einer MASCHINE. Eine PHP-Meldung im Rumpf ist
 * fuer Loxone Muell, und sie traegt den vollen Dateisystempfad - in einem
 * Bereich, den jeder ohne Anmeldung erreicht. Gemessen am 31.08.2026 unter
 * PHP 8.4: eine 'Array to string conversion' stand mitten in der
 * POSITION-Zeile, samt Pfad. Unter 7.4 ist dieselbe Sache ein E_NOTICE und
 * wird oben weggefiltert - der Unterschied haengt an der PHP-Fassung, die
 * Abhilfe darf nicht daran haengen.
 *
 * Protokolliert wird weiterhin: log_errors bleibt unberuehrt. */
ini_set('display_errors', '0');
require_once __DIR__ . '/sk_lib.php';
header('Content-Type: text/plain; charset=utf-8');

$sk_cfg = sk_config();
$sk_p = sk_paths();

/* ---------------- Token ---------------- */
$sk_soll = (string) $sk_cfg['aktionstoken'];
$sk_ist = isset($_GET['token']) && is_string($_GET['token']) ? (string) $_GET['token'] : '';
if ($sk_soll === '') {
    /* ZWEI GRUENDE, NICHT EINER. Bis 0.9.13 meldeten beide Faelle
     * KEIN_TOKEN_GESETZT: "die Oberflaeche wurde noch nie geoeffnet".
     *
     * Der zweite Fall ist aber ein anderer - in der Datei STEHT ein Token, es
     * passt nur nicht ins Muster von sk_regeln() (ein '+', ein '@', mehr als
     * 64 Zeichen; erreichbar ueber eine von Hand gesetzte Datei, eine
     * zurueckgespielte Sicherung oder eine aeltere Fassung). sk_wert_pruefen()
     * weist es ab, die leere Vorgabe tritt ein, und der Bediener las
     * "noch nie geoeffnet". Er oeffnet daraufhin die Oberflaeche - und die
     * wuerfelt ueber sk_token() ein NEUES Token, womit jede im Miniserver
     * eingetragene Adresse endgueltig ungueltig ist.
     *
     * sk_config_lage() weiss den Unterschied; sie fuehrt den Schluessel unter
     * 'abgewiesen'. Gefragt hat ihn bis 0.9.13 niemand. */
    $sk_lage = sk_config_lage();
    if (in_array('aktionstoken', $sk_lage['abgewiesen'], true)) {
        http_response_code(403);
        echo "FEHLER;OK=0;GRUND=TOKEN_UNZULAESSIG\n";
        echo "In skoda.json steht ein Aktionstoken, das nicht ins erlaubte Muster passt.\n";
        echo "Zugelassen sind Buchstaben, Ziffern, Punkt, Strich und Unterstrich, hoechstens 64 Zeichen.\n";
        echo "ACHTUNG: Die Oberflaeche wuerfelt beim naechsten Oeffnen ein NEUES Token.\n";
        exit;
    }
    http_response_code(403);
    if (isset($_GET['selftest'])) {
        echo "SELFTEST;OK=0;ERR=KEIN_TOKEN_EINGERICHTET\n";
        exit;
    }
    echo "FEHLER;OK=0;GRUND=KEIN_TOKEN_GESETZT\n";
    echo "Die Plugin-Oberflaeche wurde noch nie geoeffnet - es gibt noch kein Token.\n";
    exit;
}
if (!hash_equals($sk_soll, $sk_ist)) {
    http_response_code(403);
    if (isset($_GET['selftest'])) {
        echo "SELFTEST;OK=0;ERR=TOKEN\n";
        exit;
    }
    echo "FEHLER;OK=0;GRUND=TOKEN\n";
    exit;
}

/* ---------------- ?selftest=1 ----------------
 *
 * ERGAENZT 31.08.2026. Ein Token muss sich pruefen lassen, ohne dass etwas
 * passiert. Ohne diesen Zweig gab es nur zwei schlechte Wege: entweder man
 * setzt einen der zwoelf schaltenden Befehle ab - dann klimatisiert das Auto
 * oder der Ladevorgang haelt an -, oder man erfaehrt nie, ob die Adresse im
 * Miniserver noch stimmt. Ein Lesebefehl beantwortet die Frage auch nicht
 * sauber: er ruehrt das Abbild an und liefert eine Antwort, deren OK von der
 * Cloud abhaengt, nicht vom Token.
 *
 * Drei Festlegungen, alle eingehalten:
 *   - Der Zweig steht HINTER der Tokenpruefung: ein falsches Token bekommt
 *     dieselbe Abweisung wie sonst auch (403), nur mit dem SELFTEST-Kopf.
 *     Ein Selbsttest darf keine Abkuerzung an der Sicherheit vorbei sein.
 *   - Er steht VOR der Aktionsweissliste, damit ?selftest=1 ohne aktion
 *     genuegt und keine Wirkung ausloest.
 *   - Kein Geraetekontakt, kein Schreibzugriff, kein Protokolleintrag. Er
 *     beantwortet genau eine Frage: stimmt das Token.
 */
if (isset($_GET['selftest'])) {
    echo "SELFTEST;OK=1;TOKEN=OK\n";
    exit;
}

/* ---------------- Aktion (Weissliste) ----------------
 * Beide Listen stammen aus sk_lib.php - derselben Quelle, aus der die Tabelle
 * im Reiter Loxone, die Knoepfe im Reiter Test und die Ausgangsvorlage
 * entstehen. Bis 0.9.12 standen sie hier woertlich, und die Oberflaeche nannte
 * fuenf der zwoelf schaltenden Aktionen nicht. */
$sk_lesend = sk_lesende();
$sk_alle_befehle = sk_befehle();
$sk_schaltend = array_keys($sk_alle_befehle);
/* is_string davor: ?aktion[]=x macht aus $_GET['aktion'] ein Feld, und
 * (string) darauf erzeugt eine Warnung, die VOR http_response_code()
 * hinausgeht - der Statuscode fehlt dann, und die Abweisung kaeme als HTTP 200
 * beim Aufrufer an.
 *
 * ABGEWIESEN, NICHT ZURECHTGEBOGEN (seit 0.9.14). Bis dahin fiel ein Feld
 * still auf 'status' zurueck, waehrend ?fahrzeug[]=1 drei Zeilen weiter unten
 * mit 400 abgewiesen wurde - zwei Wahrheiten in derselben Datei, und die
 * stillere widersprach dem Satz, der direkt darunter steht: "Was nicht ins
 * Muster passt, wird abgewiesen und gemeldet. Nie Zeichen entfernen, nie
 * zurechtbiegen." */
if (isset($_GET['aktion']) && !is_string($_GET['aktion'])) {
    http_response_code(400);
    echo "FEHLER;OK=0;GRUND=PARAMETER\n";
    echo "Der Wert von aktion ist kein einfacher Wert.\n";
    exit;
}
$sk_aktion = isset($_GET['aktion']) ? (string) $_GET['aktion'] : 'status';
if (!in_array($sk_aktion, array_merge($sk_lesend, $sk_schaltend), true)) {
    http_response_code(400);
    echo "FEHLER;OK=0;GRUND=UNBEKANNTE_AKTION\n";
    echo 'Erlaubt sind: ' . implode(', ', array_merge($sk_lesend, $sk_schaltend)) . "\n";
    exit;
}

/* ---------------- Parameter pruefen ----------------
 * Was nicht ins Muster passt, wird abgewiesen und gemeldet. Nie Zeichen
 * entfernen, nie zurechtbiegen - ein still veraenderter Wert fuehrt zu einem
 * Fahrzeug, das etwas anderes tut, als die Adresse sagt.
 */
function sk_param($name, $muster, $vorgabe = '')
{
    if (!isset($_GET[$name]) || $_GET[$name] === '') {
        return $vorgabe;
    }
    if (!is_string($_GET[$name])) {
        http_response_code(400);
        echo "FEHLER;OK=0;GRUND=PARAMETER\n";
        echo 'Der Wert von ' . $name . " ist kein einfacher Wert.\n";
        exit;
    }
    $w = (string) $_GET[$name];
    if (!preg_match($muster, $w)) {
        http_response_code(400);
        echo "FEHLER;OK=0;GRUND=PARAMETER\n";
        echo 'Der Wert von ' . $name . " passt nicht ins erlaubte Muster.\n";
        exit;
    }
    return $w;
}

// Die laufende Nummer oder eine VIN (17 Zeichen, Buchstaben und Ziffern).
$sk_fahrzeug = sk_param('fahrzeug', '/^([0-9]{1,2}|[A-Za-z0-9]{17})$/', '1');
$sk_temp     = sk_param('temp', '/^[0-9]{1,2}([.,][05])?$/', '');
$sk_prozent  = sk_param('prozent', '/^[0-9]{1,3}$/', '');

/* ---------------- Hilfsausgabe ---------------- */
function sk_w($v)
{
    /* NICHT is_numeric() allein. Gemessen am 31.08.2026 mit dem Wert "55 "
     * (Ziffern mit angehaengtem Leerzeichen) im Abbild:
     *
     *     PHP 7.4.33  ->  SOC=-      (is_numeric nimmt Leerraum HINTEN nicht)
     *     PHP 8.4.24  ->  SOC=55     (seit 8.0 nimmt es ihn)
     *
     * Dieselbe Datei ergaebe damit auf LoxBerry 3 und LoxBerry 4
     * verschiedene Aussagen - und der Strich bedeutet hier "dieser Wert liegt
     * nicht vor", Loxone behaelt also den letzten Wert. Ein eigenes Muster
     * haengt an keiner PHP-Fassung.
     *
     * Felder und Objekte fallen ueber is_scalar heraus, bevor eine
     * Umwandlung sie zu "Array" macht. */
    if ($v === null || is_bool($v) || !is_scalar($v)) {
        return '-';
    }
    $s = trim((string) $v);
    if (!preg_match('/^-?[0-9]+([.][0-9]+)?$/', $s)) {
        return '-';
    }
    return (string) (0 + $s);
}

$sk_lox = sk_loxone();
$sk_alter = sk_alter();
/* -1 bedeutet "noch nie abgerufen". Bis 0.9.12 ging genau diese -1 hinaus -
 * und eine Loxone-Regel nach dem naheliegenden Muster "ALTER > 900 heisst
 * Stoerung" schlug dabei NICHT an: minus eins ist kleiner als jede Schwelle,
 * ein nie gelaufener Dienst sah also aus wie ein besonders frischer Wert.
 * Jetzt geht eine Zahl hinaus, die jede Schwelle reisst. */
if ($sk_alter < 0) {
    $sk_alter = 999999;
}
/* UND NACH OBEN GEDECKELT. Ergaenzt 31.08.2026.
 *
 * Die erzeugte Loxone-Vorlage traegt fuer ALTER MaxVal="999999" - dieselbe
 * Zahl, die "noch nie abgerufen" bedeutet. Nach 11,6 Tagen ohne Abruf ginge
 * ein groesserer Wert hinaus, den Loxone an seiner eigenen
 * Plausibilitaetsgrenze abschneidet: die Zahl in der Antwort und die Zahl im
 * Miniserver waeren dann verschieden. Fuer jede Ausfallerkennung ist
 * "999999" so gut wie jede groessere Zahl. */
$sk_alter = min(999999, $sk_alter);
$sk_zaehler = (isset($sk_lox['zaehler']) && is_numeric($sk_lox['zaehler']))
            ? (int) $sk_lox['zaehler'] : 0;
$sk_alle = sk_fahrzeuge();

/**
 * Der Marker, mit dem die erste Zeile einer Antwort beginnt.
 *
 * ANGELEGT 31.08.2026, weil es dafuer bis dahin zwei Wahrheiten gab. Die
 * gelungene Statusantwort beginnt seit 0.9.0 mit "SKODA;" - die Abweisung
 * derselben Aktion begann mit strtoupper('status'), also "STATUS;". Eine
 * Ueberwachung in Loxone, die auf den Marker hoert, sah die Abweisung
 * deshalb nie. Und jede schaltende Aktion wies mit ihrem eigenen Namen ab
 * ("KLIMA_START;"), obwohl ihre Erfolgsmeldung "SET;" lautet.
 *
 * Zwoelf mal derselbe Marker fuer die schaltenden Aktionen ist Absicht: die
 * Antwort auf einen Befehl hat immer dieselbe Gestalt, und wer sie auswertet,
 * soll nicht zwoelf Befehlserkennungen anlegen muessen.
 */
function sk_marke($aktion)
{
    if (array_key_exists($aktion, sk_befehle())) {
        return 'SET';
    }
    return $aktion === 'status' ? 'SKODA' : strtoupper($aktion);
}

/**
 * Ein Textfeld des Abbilds, so dass es die Zeilenform nicht zerlegen kann.
 *
 * Semikolon, Wagenruecklauf und Zeilenvorschub sind die drei Zeichen, die die
 * Antwort gliedern. Sie standen bis 0.9.13 an drei Stellen woertlich in
 * str_replace-Aufrufen und an einer vierten gar nicht - deshalb jetzt an
 * EINER Stelle. Ein Feld, das kein Text ist, wird zu einer leeren Zeichenkette
 * statt zu "Array".
 */
function sk_feld($f, $name)
{
    if (!isset($f[$name]) || !is_scalar($f[$name])) {
        return '';
    }
    return str_replace(array("\r", "\n", ';'), ' ', (string) $f[$name]);
}

/** Findet das Fahrzeug zur laufenden Nummer oder zur VIN. */
function sk_waehlen($alle, $schluessel)
{
    if (isset($alle[$schluessel])) {
        return $alle[$schluessel];
    }
    /* Fuehrende Nullen. Bis 0.9.12 bedeutete dieselbe Adresse fuer lesende und
     * schreibende Aktionen etwas Verschiedenes: ?fahrzeug=01 wies der
     * Endpunkt beim Lesen als unbekannt ab - die Schluessel des Abbilds
     * heissen "1", "2" und werden woertlich verglichen -, waehrend der Dienst
     * beim Schreiben ueber int("01") auf Fahrzeug 1 kam. Eine Adresse, die
     * lesend nichts findet und schreibend etwas tut, ist eine Falle. */
    if (preg_match('/^0[0-9]{1,2}$/', (string) $schluessel)) {
        $n = (string) (int) $schluessel;
        if (isset($alle[$n])) {
            return $alle[$n];
        }
    }
    foreach ($alle as $f) {
        if (isset($f['vin']) && strcasecmp((string) $f['vin'], (string) $schluessel) === 0) {
            return $f;
        }
    }
    return null;
}

/* ================= Das Fahrzeug - EINMAL, fuer ALLE Aktionen =============
 *
 * Bis 0.9.13 stand diese Pruefung erst nach den drei Listenaktionen und galt
 * nur fuer status/laden/wartung/position. Gemessen am 31.08.2026:
 *
 *   ?aktion=status&fahrzeug=99       -> 404 FAHRZEUG_UNBEKANNT   richtig
 *   ?aktion=klima_start&fahrzeug=99  -> 200 SET;OK=2             eingereiht!
 *   ?aktion=ladungen&fahrzeug=99     -> 200 LADUNGEN;OK=1;N=0    gar kein Grund
 *
 * Der Endpunkt WUSSTE also, dass es das Fahrzeug nicht gibt, und reihte den
 * Schaltbefehl trotzdem ein. OK=2 heisst "eingereiht, Ergebnis unbekannt" und
 * ist von einem echten Befehl nicht zu unterscheiden; der Dienst weist ihn
 * spaeter zu Recht ab, aber in eine Antwortdatei, die nach der Wartezeit
 * niemand mehr abholt. Ein Tippfehler im virtuellen Ausgang - fahrzeug=3 bei
 * zwei Wagen - sah damit dauerhaft nach Erfolg aus.
 *
 * Drei Aktionen tragen KEIN Fahrzeug, und nur diese drei:
 *   roh        das ganze Abbild
 *   fahrzeuge  die Liste selbst
 *   abruf      gilt fuer das Konto, nicht fuer ein Auto
 */
$SK_OHNE_FAHRZEUG = array('roh', 'fahrzeuge', 'abruf');

$sk_f = sk_waehlen($sk_alle, $sk_fahrzeug);
if (!in_array($sk_aktion, $SK_OHNE_FAHRZEUG, true) && $sk_f === null) {
    // 404, nicht 200. Bis 0.9.12 kam diese Abweisung ohne Statuscode heraus,
    // waehrend UNBEKANNTE_AKTION eine 400 bekam - zwei gleichartige Faelle mit
    // verschiedener Auskunft an jedes Ueberwachungswerkzeug.
    http_response_code(404);
    printf("%s;OK=0;GRUND=FAHRZEUG_UNBEKANNT;N=%d;ALTER=%d\n",
        sk_marke($sk_aktion), count($sk_alle), $sk_alter);
    exit;
}

/* ================= Lesende Aktionen ================= */

if ($sk_aktion === 'roh') {
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($sk_lox, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

if ($sk_aktion === 'ladungen') {
    /* Das Ladeprotokoll als Klartext, neueste zuerst. Eine Kopfzeile, dann je
     * Ladung eine Zeile - fuer den Blick von aussen und fuer eine Tabelle in
     * der Visualisierung. */
    /* Die Nummer kommt aus dem GEFUNDENEN Fahrzeug, nicht aus (int) auf der
     * Adresse. Gemessen am 31.08.2026: (int) "TMBJJ7NE0K0000002" ist 0, und 0
     * heisst in sk_ladungen_lesen() ausdruecklich "alle Fahrzeuge". Eine
     * gueltige VIN lieferte deshalb die Ladungen BEIDER Wagen - samt Ort, also
     * die Standorthistorie des anderen. Dieselbe Adressform bedeutete damit
     * bei 'ladungen' etwas anderes als bei den vier uebrigen Aktionen; genau
     * diese Falle hatte 0.9.13 fuer die fuehrende Null geschlossen. */
    $sk_nr_lad = array_search($sk_f, $sk_alle, true);
    $sk_l = sk_ladungen_lesen((int) $sk_nr_lad, 200);
    echo 'LADUNGEN;OK=' . ((!empty($sk_lox['ok']) && $sk_alter < 999999) ? 1 : 0)
       . ';N=' . count($sk_l) . ';ALTER=' . $sk_alter . "\n";
    foreach ($sk_l as $sk_z) {
        printf("%s;%d;%d;%s;%s;%s;%s\n",
            date('Y-m-d H:i', $sk_z['beginn']), $sk_z['fahrzeug'], $sk_z['dauer_min'],
            $sk_z['soc_von'] === '' ? '-' : $sk_z['soc_von'],
            $sk_z['soc_bis'] === '' ? '-' : $sk_z['soc_bis'],
            $sk_z['kw_max'] === '' ? '-' : $sk_z['kw_max'],
            sk_feld($sk_z, 'ort'));
    }
    exit;
}

if ($sk_aktion === 'fahrzeuge') {
    $sk_gesamt = (!empty($sk_lox['ok']) && $sk_alter < 999999) ? 1 : 0;
    echo 'FAHRZEUGE;OK=' . $sk_gesamt . ';N=' . count($sk_alle)
       . ';ALTER=' . $sk_alter . ';ZAEHLER=' . $sk_zaehler . "\n";
    foreach ($sk_alle as $sk_nr => $sk_eintrag) {
        /* BEREINIGT wie 'position' und 'ladungen' es laengst tun. Bis 0.9.13
         * gingen modell, kennzeichen und vin ROH hinaus - Werte, die aus der
         * Skoda-Cloud kommen. Gemessen: ein Semikolon im Modellnamen machte
         * aus fuenf Feldern sechs, ein Zeilenumbruch aus "N=1" zwei Zeilen.
         * Ein Werkzeug, das die Kopfzahl gegen die Zeilenzahl haelt, sieht
         * dann einen Fehler, wo keiner ist - oder uebersieht einen. */
        echo $sk_nr . ';' . sk_feld($sk_eintrag, 'modell') . ';'
           . sk_feld($sk_eintrag, 'kennzeichen') . ';'
           . sk_feld($sk_eintrag, 'vin') . ';'
           /* ausfaelle_n zuerst: der Dienst schreibt seit 0.9.13 die ZAHL
            * mit. Die Statuszeile rechnet genauso - zwei Zaehlweisen fuer
            * dieselbe Zahl waeren eine Gelegenheit, sie auseinanderlaufen zu
            * lassen. */
           . 'Ausfaelle=' . (isset($sk_eintrag['ausfaelle_n'])
                             ? (int) $sk_eintrag['ausfaelle_n']
                             : (isset($sk_eintrag['ausfaelle'])
                                && is_array($sk_eintrag['ausfaelle'])
                                ? count($sk_eintrag['ausfaelle']) : 0)) . "\n";
    }
    exit;
}


/* OK gilt JE FAHRZEUG, nicht global.
 *
 * Bis 0.9.12 stand hier ein einziges $sk_ok aus loxone.json, und der Dienst
 * setzte das mit any() ueber alle Fahrzeuge. Bei zwei Autos genuegte damit
 * eines, das antwortet: fiel das zweite vollstaendig aus, meldete
 * ?aktion=status&fahrzeug=2 weiterhin OK=1 mit kleinem ALTER und lauter
 * Strichen. Die Ausfallerkennung, die dieses Plugin ausdruecklich auf ALTER
 * und OK aufbaut, griff fuer dieses Fahrzeug nicht.
 */
$sk_ok = (!empty($sk_lox['ok']) && $sk_alter < 999999) ? 1 : 0;
$sk_ausfaelle = 0;
if ($sk_f !== null) {
    $sk_ok = ($sk_ok && !empty($sk_f['ok'])) ? 1 : 0;
    /* UND DAS ALTER GILT AUCH JE FAHRZEUG. Ergaenzt 31.08.2026.
     *
     * Das OK war seit 0.9.12 je Fahrzeug, das Alter nicht: bei zwei Autos
     * frischte ein erfolgreicher Abruf des einen den gemeinsamen Zeitstempel
     * auf, und das ausgefallene zweite meldete OK=0 mit einem ALTER von
     * wenigen Sekunden. Eine Loxone-Regel, die auf ALTER schaut - und dazu
     * raet dieses Plugin ausdruecklich -, sah dort einen frischen Wert.
     *
     * Der Dienst schreibt den Zeitstempel seit 0.9.15 je Fahrzeug mit. Fehlt
     * er (Abbild einer aelteren Fassung), gilt der gemeinsame - dann ist die
     * Lage wie bisher und nicht schlechter. */
    if (isset($sk_f['ts']) && is_numeric($sk_f['ts']) && (int) $sk_f['ts'] > 0) {
        $sk_falter = time() - (int) $sk_f['ts'];
        $sk_alter = min(999999, max(0, $sk_falter));
    }
    $sk_ausfaelle = isset($sk_f['ausfaelle_n']) ? (int) $sk_f['ausfaelle_n']
                  : (isset($sk_f['ausfaelle']) && is_array($sk_f['ausfaelle'])
                     ? count($sk_f['ausfaelle']) : 0);
}

/** Ein Wert aus dem Abbild, oder null. */
function sk_v($f, $name)
{
    return isset($f[$name]) ? $f[$name] : null;
}

if ($sk_aktion === 'status') {
    printf("SKODA;OK=%d;SOC=%s;TANK=%s;REICHW=%s;KM=%s;VERR=%s;TUEREN=%s;FENSTER=%s;"
         . "KOFFER=%s;HAUBE=%s;LICHT=%s;KLIMA=%s;ZIELTEMP=%s;AUSSEN=%s;WARN=%s;"
         . "ERREICH=%s;BEWEG=%s;ZUEND=%s;ZUHAUSE=%s;HEIMENTF=%s;EMPFEHLUNG=%s;"
         . "AUSFAELLE=%d;ZAEHLER=%d;ALTER=%d\n",
        $sk_ok,
        sk_w(sk_v($sk_f, 'soc')), sk_w(sk_v($sk_f, 'tank_prozent')),
        sk_w(sk_v($sk_f, 'reichweite_km')), sk_w(sk_v($sk_f, 'kilometerstand')),
        sk_w(sk_v($sk_f, 'verriegelt')), sk_w(sk_v($sk_f, 'tueren_offen')),
        sk_w(sk_v($sk_f, 'fenster_offen')), sk_w(sk_v($sk_f, 'kofferraum_offen')),
        sk_w(sk_v($sk_f, 'motorhaube_offen')), sk_w(sk_v($sk_f, 'licht_an')),
        sk_w(sk_v($sk_f, 'klima_an')), sk_w(sk_v($sk_f, 'zieltemperatur')),
        sk_w(sk_v($sk_f, 'aussentemperatur')), sk_w(sk_v($sk_f, 'warnleuchten')),
        sk_w(sk_v($sk_f, 'erreichbar')), sk_w(sk_v($sk_f, 'in_bewegung')),
        sk_w(sk_v($sk_f, 'zuendung_an')),
        sk_w(sk_v($sk_f, 'zuhause')), sk_w(sk_v($sk_f, 'heim_entfernung_m')),
        /* Die Ladeempfehlung gilt fuer das KONTO, nicht je Fahrzeug: sie
         * entsteht aus einem einzigen fremden Thema. Sie steht trotzdem in
         * der Fahrzeugzeile, damit ein Loxone-Baustein alles aus einer
         * Antwort bekommt. */
        sk_w(isset($sk_lox['empfehlung']) ? $sk_lox['empfehlung'] : null),
        $sk_ausfaelle, $sk_zaehler, $sk_alter);
    exit;
}

if ($sk_aktion === 'laden') {
    printf("LADEN;OK=%d;SOC=%s;LAEDT=%s;LADEKW=%s;TEMPO=%s;RESTMIN=%s;LADEGR=%s;"
         . "KABEL=%s;REICHWBAT=%s;ALTER=%d\n",
        $sk_ok,
        sk_w(sk_v($sk_f, 'soc')), sk_w(sk_v($sk_f, 'laedt')),
        sk_w(sk_v($sk_f, 'ladeleistung_kw')), sk_w(sk_v($sk_f, 'ladetempo_kmh')),
        sk_w(sk_v($sk_f, 'restzeit_min')), sk_w(sk_v($sk_f, 'ladegrenze')),
        sk_w(sk_v($sk_f, 'kabel_verbunden')), sk_w(sk_v($sk_f, 'reichweite_batterie_km')),
        $sk_alter);
    exit;
}

if ($sk_aktion === 'wartung') {
    printf("WARTUNG;OK=%d;INSPTAGE=%s;INSPKM=%s;OELTAGE=%s;OELKM=%s;KM=%s;WARN=%s;ALTER=%d\n",
        $sk_ok,
        sk_w(sk_v($sk_f, 'inspektion_tage')), sk_w(sk_v($sk_f, 'inspektion_km')),
        sk_w(sk_v($sk_f, 'oelservice_tage')), sk_w(sk_v($sk_f, 'oelservice_km')),
        sk_w(sk_v($sk_f, 'kilometerstand')), sk_w(sk_v($sk_f, 'warnleuchten')),
        $sk_alter);
    exit;
}

if ($sk_aktion === 'position') {
    printf("POSITION;OK=%d;BREITE=%s;LAENGE=%s;ZUHAUSE=%s;HEIMENTF=%s;ALTER=%d\n",
        $sk_ok, sk_w(sk_v($sk_f, 'breite')), sk_w(sk_v($sk_f, 'laenge')),
        sk_w(sk_v($sk_f, 'zuhause')), sk_w(sk_v($sk_f, 'heim_entfernung_m')), $sk_alter);
    // Die Anschrift steht in einer zweiten Zeile, damit die erste Zeile fuer
    // Loxone rein aus Zahlen besteht.
    /* (string) auf ein Feld erzeugte hier eine Warnung
     * "Array to string conversion" - unter PHP 7.4 ein E_NOTICE und damit
     * weggefiltert, unter 8.4 eine WARNUNG, die samt vollem Dateipfad
     * mitten in der Klartextantwort stand. sk_feld() faengt alles ab, was
     * kein Text ist, und bereinigt in einem Zug die Gliederungszeichen. */
    echo 'ADRESSE;' . sk_feld($sk_f, 'adresse') . "\n";
    exit;
}

/* ================= Schaltende Aktionen ================= */

/* AUCH 'abruf'. Bis 0.9.13 stand hier "$sk_aktion !== 'abruf' &&", der
 * sofortige Abruf war also von der Sperre ausgenommen - waehrend der
 * Kopfkommentar dieser Datei ihn ausdruecklich unter "Schaltende Aktionen
 * (nur wenn im Reiter Einstellungen zugelassen)" fuehrte. Wer den Haken
 * ausschaltete, konnte weiterhin vollstaendige Cloud-Durchgaenge ausloesen -
 * genau der Weg, ueber den laut bin/skoda.py in 0.9.12 3600 Durchgaenge je
 * Stunde entstanden sind. */
if (empty($sk_cfg['steuerung_ein'])) {
    http_response_code(403);
    echo "SET;OK=0;GRUND=STEUERUNG_AUS\n";
    echo "Schreibende Befehle sind gesperrt. Reiter Einstellungen, Haken 'Schreibende Befehle zulassen'.\n";
    exit;
}
if (sk_dienst_pid() === 0) {
    // Nicht stillschweigend einreihen: ohne laufenden Dienst passiert nichts,
    // und der Befehl laege bis zum naechsten Start in der Warteschlange.
    http_response_code(503);
    echo "SET;OK=0;GRUND=DIENST_LAEUFT_NICHT\n";
    echo "Der Abrufdienst laeuft nicht. Reiter Einstellungen, Knopf 'Dienst starten'.\n";
    exit;
}

$sk_befehl = array('aktion' => $sk_aktion, 'fahrzeug' => $sk_fahrzeug);

$sk_zusatz = isset($sk_alle_befehle[$sk_aktion][2]) ? $sk_alle_befehle[$sk_aktion][2] : '';

if ($sk_aktion === 'klima_start' || $sk_aktion === 'zieltemperatur') {
    if ($sk_temp === '') {
        http_response_code(400);
        echo "SET;OK=0;GRUND=TEMP_FEHLT\n";
        echo "Der Parameter temp fehlt (Zieltemperatur in Grad Celsius).\n";
        exit;
    }
    $sk_befehl['temp'] = str_replace(',', '.', $sk_temp);
} elseif ($sk_aktion === 'ladegrenze') {
    if ($sk_prozent === '') {
        http_response_code(400);
        echo "SET;OK=0;GRUND=PROZENT_FEHLT\n";
        exit;
    }
    $sk_befehl['prozent'] = (int) $sk_prozent;
}

list($sk_erg, $sk_meldung) = sk_befehl_absetzen($sk_befehl);
/* 409, nicht 500.
 *
 * Bis 0.9.12 stand hier http_response_code(500) fuer JEDES ok = 0 - also auch
 * fuer "Zieltemperatur 35 Grad liegt ausserhalb der eingestellten Grenzen",
 * "Fahrzeug 5 gibt es nicht", "50 bis 100 Prozent zulaessig" und
 * "die Steuerung ist ausgeschaltet". Das sind fachliche Ablehnungen, keine
 * Serverfehler; wer den Endpunkt hinter einem Ueberwachungswerkzeug betreibt,
 * bekam fuer Bedienfehler Serveralarm. 409 Conflict sagt: die Anfrage war
 * verstanden, der Zustand laesst sie nicht zu.
 *
 * ok = 2 heisst "eingereiht, Ergebnis unbekannt" und bleibt bei 200 - der
 * Befehl ist ja angenommen. Die Zeile sagt es im Klartext mit. */
if ($sk_erg === 0) {
    http_response_code(409);
}
printf("SET;OK=%d;AKTION=%s;ZAEHLER=%d;MELDUNG=%s\n", $sk_erg, $sk_aktion, $sk_zaehler,
    str_replace(array("\r", "\n", ';'), ' ', $sk_meldung));
