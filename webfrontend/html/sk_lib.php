<?php
/**
 * Skoda Connect - gemeinsame Bibliothek
 *
 * Liegt bewusst unter webfrontend/html/, weil der Miniserver-Endpunkt sie
 * ebenso braucht wie die Oberflaeche. Nur so gibt es EINE Datei statt zweier
 * Kopien, die auseinanderlaufen. Die Oberflaeche unter htmlauth/ laedt sie von
 * hier (drei Kandidatenpfade: installiert und im Archiv).
 *
 * Die Bibliothek spricht NIE mit der Skoda-Cloud. Sie liest den
 * Zwischenspeicher, den bin/skoda.py schreibt, und legt Schreibbefehle in
 * einer Warteschlange ab. Ein Plugin, das den Datenabruf in der Oberflaeche
 * oder im Endpunkt erledigt, ist falsch gebaut - auch wenn es funktioniert.
 *
 * Praefix 'sk_', weil LBWeb::lbheader() SDK-Globale setzt und gleichnamige
 * Plugin-Variablen ueberschreiben wuerde.
 * Kompatibel mit PHP 7.4 und PHP 8.x (LoxBerry 3.x/4.x).
 */

if (!function_exists('sk_e')) {
    function sk_e($s)
    {
        return htmlspecialchars((string) $s, ENT_QUOTES, 'UTF-8');
    }
}


/* Den LoxBerry-Wurzelordner ohne festen Systempfad bestimmen.
 *
 * Vom eigenen Ablageort aufwaerts, bis ein Verzeichnis gefunden ist, das
 * config/plugins UND webfrontend enthaelt. Das trifft die uebliche
 * Installation genauso wie eine an einem anderen Ort - und es trifft auch
 * den Fall, dass das Plugin noch als entpacktes Archiv daliegt (dann findet
 * es nichts und gibt einen Leerstring zurueck, was der Aufrufer ohnehin
 * abfangen muss).
 *
 * Der Name traegt kein Plugin-Kuerzel und ist deshalb abgesichert: zwei
 * Bibliotheken landen nie im selben Prozess, aber die Pruefung kostet nichts.
 */
if (!function_exists('lb_wurzel_ermitteln')) {
    function lb_wurzel_ermitteln()
    {
        $d = __DIR__;
        for ($i = 0; $i < 8; $i++) {
            if (is_dir($d . '/config/plugins') && is_dir($d . '/webfrontend')) {
                return $d;
            }
            $eltern = dirname($d);
            if ($eltern === $d) { break; }
            $d = $eltern;
        }
        return '';
    }
}

function sk_paths()
{
    static $p = null;
    if ($p !== null) {
        return $p;
    }
    $home = getenv('LBHOMEDIR');
    if (!$home || !is_dir($home)) {
        foreach (array(lb_wurzel_ermitteln(), '/home/loxberry/loxberry') as $k) {
            if (is_dir($k)) {
                $home = $k;
                break;
            }
        }
    }
    // Der Pluginordner ergibt sich aus dem Ablageort dieser Datei. Der
    // MD5-Schluessel aus der plugindatabase.json wird bewusst NICHT benutzt -
    // er wird aus Autorenname, E-Mail und Plugin-Name gebildet und aendert
    // sich bei jedem Fork.
    $dir = basename(dirname(__FILE__));
    /* Frueher stand hier ein Rueckfall auf den festen Namen "skodaconnect",
     * sobald config/plugins/<ordner> noch fehlte - etwa im Augenblick der
     * Installation. Genau diesen Namen traegt aber AUCH das eingestellte
     * Vorgaengerplugin von M. Schlenstedt. Wer es noch installiert hat,
     * bekommt dieses hier von LoxBerry als "skodaconnect_01" - und der
     * Rueckfall haette dann in die Konfiguration des FREMDEN Plugins gezeigt,
     * also dort gelesen und geschrieben.
     *
     * LBPPLUGINDIR ist die Auskunft von LoxBerry selbst und bleibt deshalb.
     * Der feste Name greift nur noch dort, wo der ermittelte nachweislich
     * kein Plugin-Ordner sein kann: aus dem ausgepackten Archiv heraus heisst
     * er "html". */
    $lbp = getenv('LBPPLUGINDIR');
    if ($lbp) {
        $dir = $lbp;
    } elseif ($dir === '' || $dir === '.' || $dir === '/' || $dir === 'html') {
        $dir = 'skodaconnect';
    }
    if ($home) {
        $p = array(
            'home'      => $home,
            'plugin'    => $dir,
            'configdir' => $home . '/config/plugins/' . $dir,
            'config'    => $home . '/config/plugins/' . $dir . '/skoda.json',
            'zugang'    => $home . '/config/plugins/' . $dir . '/zugang.json',
            'sicherung' => $home . '/config/plugins/' . $dir . '.backup.skoda.json',
            'zugang_sicherung' => $home . '/config/plugins/' . $dir . '.backup.zugang.json',
            'datadir'   => $home . '/data/plugins/' . $dir,
            'bindir'    => $home . '/bin/plugins/' . $dir,
            'logdir'    => $home . '/log/plugins/' . $dir,
            'log'       => $home . '/log/plugins/' . $dir . '/skoda.log',
        );
    } else {
        // Nicht installiert (Entwicklung, Attrappe): neben dem Plugin arbeiten.
        $basis = dirname(dirname(__DIR__));
        $p = array(
            'home'      => '',
            'plugin'    => $dir,
            'configdir' => $basis . '/config',
            'config'    => $basis . '/config/skoda.json',
            'zugang'    => $basis . '/config/zugang.json',
            'sicherung' => $basis . '/config/skoda.backup.json',
            'zugang_sicherung' => $basis . '/config/zugang.backup.json',
            'datadir'   => $basis . '/data',
            'bindir'    => $basis . '/bin',
            'logdir'    => $basis . '/log',
            'log'       => $basis . '/log/skoda.log',
        );
    }
    return $p;
}

/** Voreinstellungen. Muessen zu VORGABEN in bin/skoda.py passen. */
function sk_vorgaben()
{
    return array(
        'intervall'      => 300,
        'takt_stamm'     => 12,
        'takt_wartung'   => 24,
        'mqtt_ein'       => 0,
        'mqtt_topic'     => 'skoda',
        'mqtt_retain'    => 0,
        'steuerung_ein'  => 0,
        'temp_min'       => 16,
        'temp_max'       => 29,
        'verlauf_tage'   => 8,
        'sitzung_merken' => 1,
        'abstand_abruf'  => 60,
        'befehle_stunde' => 30,
        'entprellung'    => 20,
        'heim_breite'    => '',
        'heim_laenge'    => '',
        'heim_radius'    => 150,
        'empf_thema'     => '',
        'empf_grenze'    => '',
        'empf_kleiner'   => 1,
        // Hoechstalter des empfangenen Wertes in Sekunden, 0 = ohne Grenze.
        // Muss zu VORGABEN['empf_alter'] in bin/skoda.py passen.
        'empf_alter'     => 10800,
        'abfahrt_ein'    => 0,
        'abfahrt_thema'  => '',
        'abfahrt_vorlauf' => 20,
        'abfahrt_temp'   => 21,
        'aktionstoken'   => '',
        'wartezeit'      => 8,
    );
}

/**
 * Die zulaessigen Werte je Einstellung - an EINER Stelle.
 *
 * Drei Verbraucher lesen daraus: das Formular beim Speichern, die
 * Sicherungsdatei beim Zurueckspielen und die Lesefunktion sk_config_lage().
 * Eine zweite Wahrheit ueber zulaessige Werte gibt es nicht; sonst laesst die
 * eine Stelle durch, was die andere abweist, und niemand merkt es.
 *
 * WARUM ES DIESE FUNKTION SEIT 0.9.13 GIBT. Bis 0.9.12 prueste
 * sk_sicherung_lesen() nur den SCHLUESSEL und uebernahm den Wert unbesehen.
 * Gemessen mit einer von Hand gebauten Datei ging alles davon durch:
 *
 *     intervall      "abc"             (das Formular verlangt 60 bis 3600)
 *     takt_stamm     -99
 *     temp_min 99 / temp_max -5        (das Formular weist die Vertauschung ab)
 *     verlauf_tage   [1,2]             ein Feld
 *     sitzung_merken {"x":1}           ein Objekt
 *     mqtt_topic     "a b;c/../../etc" (Leerzeichen zerlegt die Gateway-Zeile)
 *
 * Form: 'schluessel' => array(art, ...)
 *   ganz:   array('ganz', min, max)
 *   schalt: array('schalt')                 genau 0 oder 1
 *   text:   array('text', muster, maxlaenge)
 *   zahl:   array('zahl', min, max)         Kommazahl, '' erlaubt
 */
function sk_regeln()
{
    return array(
        'intervall'      => array('ganz', 60, 3600),
        'takt_stamm'     => array('ganz', 1, 240),
        'takt_wartung'   => array('ganz', 1, 240),
        'mqtt_ein'       => array('schalt'),
        'mqtt_retain'    => array('schalt'),
        'mqtt_topic'     => array('text', '#^[A-Za-z0-9_\-]+(/[A-Za-z0-9_\-]+)*$#', 64),
        'steuerung_ein'  => array('schalt'),
        'temp_min'       => array('ganz', 10, 30),
        'temp_max'       => array('ganz', 10, 30),
        'verlauf_tage'   => array('ganz', 1, 90),
        'sitzung_merken' => array('schalt'),
        'abstand_abruf'  => array('ganz', 0, 3600),
        'befehle_stunde' => array('ganz', 1, 240),
        'entprellung'    => array('ganz', 0, 600),
        'heim_breite'    => array('zahl', -90, 90),
        'heim_laenge'    => array('zahl', -180, 180),
        'heim_radius'    => array('ganz', 10, 5000),
        /* Themen duerfen + und # tragen - das sind die MQTT-Platzhalter. Was
         * sie NICHT duerfen: Leerzeichen und Steuerzeichen. */
        'empf_thema'     => array('text', '#^[A-Za-z0-9_/+\#-]{0,128}$#', 128),
        'empf_grenze'    => array('zahl', -1000000, 1000000),
        'empf_kleiner'   => array('schalt'),
        'empf_alter'     => array('ganz', 0, 86400),
        'abfahrt_ein'    => array('schalt'),
        'abfahrt_thema'  => array('text', '#^[A-Za-z0-9_/+\#-]{0,128}$#', 128),
        'abfahrt_vorlauf' => array('ganz', 5, 180),
        'abfahrt_temp'   => array('ganz', 10, 30),
        /* Das Aktionstoken: bewusst WEIT gefasst. sk_token_erzeugen() bildet
         * nur Kleinbuchstaben und Ziffern - aber ein Token kann von Hand
         * gesetzt, aus einer aelteren Fassung uebernommen oder von einem
         * Pruefstand vorgegeben sein. Ein zu enges Muster wiese es ab, die
         * Vorgabe (leer) traete an seine Stelle, und sk_token() erzeugte ein
         * neues - womit JEDE im Miniserver eingetragene Adresse ungueltig
         * waere. Stumm, denn ein virtueller Eingang wertet die 403 nicht aus.
         * Zugelassen ist, was ohne Kodierung in eine Adresse passt. */
        'aktionstoken'   => array('text', '#^[A-Za-z0-9_.\-]{0,64}$#', 64),
        'wartezeit'      => array('ganz', 0, 30),
    );
}

/**
 * Taugt der Wert ueberhaupt fuer eine Zeile dieser Konfiguration?
 *
 * Die erste von zwei Wachen. Sie fragt nicht, ob der Wert zur Einstellung
 * passt, sondern ob er ueberhaupt ein Wert ist: kein Feld, kein Objekt, kein
 * Steuerzeichen, nicht endlos lang.
 */
function sk_wert_taugt($v)
{
    if (is_array($v) || is_object($v) || is_null($v) || is_bool($v)) {
        return false;
    }
    $s = (string) $v;
    if (strlen($s) > 4096) {
        return false;
    }
    return preg_match('/[\x00-\x08\x0A-\x1F\x7F]/', $s) !== 1;
}

/**
 * Ist der Wert fuer DIESE Einstellung zulaessig?
 *
 * Rueckgabe: array(ok, bereinigter Wert). Bereinigt heisst ausschliesslich:
 * die Zahl als int oder float statt als Zeichenkette. Es wird nichts gekappt
 * und nichts zurechtgebogen. Beim Speichern ueber das Formular waere Kappen
 * vertretbar, denn der Bediener sieht das Ergebnis sofort - bei einer Datei
 * saehe niemand, dass aus 99999 eine 3600 wurde.
 */
function sk_wert_pruefen($schluessel, $wert)
{
    $regeln = sk_regeln();
    if (!isset($regeln[$schluessel]) || !sk_wert_taugt($wert)) {
        return array(false, null);
    }
    $r = $regeln[$schluessel];
    $s = trim((string) $wert);
    switch ($r[0]) {
        case 'ganz':
            if (!preg_match('/^-?[0-9]+$/', $s)) {
                return array(false, null);
            }
            $n = (int) $s;
            return ($n >= $r[1] && $n <= $r[2]) ? array(true, $n) : array(false, null);
        case 'schalt':
            /* Genau 0 oder 1, und das ist keine Kosmetik. Die Zeichenkette "0"
             * ist in PHP leer und in Python wahr:
             *   PHP    empty("0")         -> true    Oberflaeche: "gesperrt"
             *   Python not cfg.get(...)   -> False   Dienst: fuehrt aus
             * Eine Sicherungsdatei mit "steuerung_ein": "0" - ueber das
             * Formular nicht erzeugbar - liess die Oberflaeche "Schreibende
             * Befehle gesperrt" anzeigen, waehrend ein Knopf im Reiter Test
             * das Auto klimatisierte. Gemessen am 27.08.2026. */
            return ($s === '0' || $s === '1') ? array(true, (int) $s) : array(false, null);
        case 'text':
            if (strlen($s) > $r[2]) {
                return array(false, null);
            }
            return preg_match($r[1], $s) ? array(true, $s) : array(false, null);
        case 'zahl':
            if ($s === '') {
                return array(true, '');
            }
            if (!preg_match('/^-?[0-9]+([.,][0-9]+)?$/', $s)) {
                return array(false, null);
            }
            $f = (float) str_replace(',', '.', $s);
            return ($f >= $r[1] && $f <= $r[2]) ? array(true, $f) : array(false, null);
    }
    return array(false, null);
}

function sk_json_lesen($pfad)
{
    list($d, ) = sk_json_lage($pfad);
    return $d;
}

/**
 * Wie sk_json_lesen(), sagt aber, WARUM nichts herauskam.
 *
 * ANGELEGT 31.08.2026. Bis 0.9.14 gab sk_json_lesen() bei ungueltigem JSON
 * stumm ein leeres Feld zurueck - eine abgeschnittene Datei (Stromausfall
 * mitten im Schreiben) war damit von einer fehlenden nicht zu unterscheiden.
 * Was daraus folgte, ist gemessen: die Werkseinstellung trat ein, das
 * Aktionstoken fehlte also, sk_token() wuerfelte ein neues und schrieb es
 * zurueck - und sk_config_speichern() kopierte die frisch erfundene Datei
 * ueber die INTAKTE Zweitschrift. Einstellungen weg, alle Loxone-Adressen
 * ungueltig, Sicherung vernichtet, kein Wort im Protokoll.
 *
 * Rueckgabe: array(daten, lage) mit lage aus
 *   'fehlt'  - die Datei gibt es nicht (der Normalfall vor der ersten Nutzung)
 *   'leer'   - da, aber leer oder "{}"
 *   'ok'     - gelesen
 *   'kaputt' - da, nicht leer, und kein gueltiges JSON-Objekt
 */
function sk_json_lage($pfad)
{
    clearstatcache(true, $pfad);
    if (!is_file($pfad)) {
        return array(array(), 'fehlt');
    }
    $roh = @file_get_contents($pfad);
    if ($roh === false) {
        // Da, aber nicht lesbar (Rechte). Das ist kein leerer Wert.
        return array(array(), 'kaputt');
    }
    $roh = trim((string) $roh);
    if ($roh === '' || $roh === '{}') {
        return array(array(), 'leer');
    }
    $d = json_decode($roh, true);
    if (!is_array($d)) {
        return array(array(), 'kaputt');
    }
    return array($d, 'ok');
}

function sk_config()
{
    $lage = sk_config_lage();
    return $lage['cfg'];
}

/**
 * Wie sk_config(), gibt aber den ganzen Befund zurueck.
 *
 *   array('cfg' => ..., 'fehlend' => array(schluessel),
 *         'fremd' => array(schluessel), 'abgewiesen' => array(schluessel))
 *
 * 'fehlend'    steht in den Vorgaben, nicht in der Datei  -> kommt aus der Vorgabe
 * 'fremd'      steht in der Datei, nicht in den Vorgaben  -> wirkt NICHT
 * 'abgewiesen' steht in der Datei, ist aber unzulaessig   -> Vorgabe tritt ein
 *
 * Der Reiter Test nennt alle drei. Ein fremder Schluessel wirkt nicht, und
 * genau das ueberrascht: man hat etwas eingestellt, es steht in der Datei, und
 * es tut nichts.
 */
function sk_config_lage()
{
    /* Der Zwischenspeicher liegt in einem Global, nicht in einer statischen
     * Variablen: er muss nach jedem Schreiben im selben Seitenaufbau
     * verworfen werden koennen, und eine Statik laesst sich von aussen nicht
     * zuruecksetzen. Bis 0.9.12 gab es ihn gar nicht - dafuer stand der
     * Handler fuer das Zurueckspielen HINTER dem Laden der Anzeigewerte, was
     * auf dasselbe hinauslief. */
    if (isset($GLOBALS['sk_cfg_speicher']) && is_array($GLOBALS['sk_cfg_speicher'])) {
        return $GLOBALS['sk_cfg_speicher'];
    }
    $p = sk_paths();
    list($datei, $lage) = sk_json_lage($p['config']);
    $vorgaben = sk_vorgaben();
    $cfg = $vorgaben;
    $fremd = array();
    $abgewiesen = array();
    foreach ($datei as $k => $w) {
        if (!array_key_exists($k, $vorgaben)) {
            $fremd[] = (string) $k;
            continue;
        }
        list($ok, $rein) = sk_wert_pruefen($k, $w);
        if ($ok) {
            $cfg[$k] = $rein;
        } else {
            /* Die Vorgabe steht schon drin. Gemeldet wird trotzdem: eine
             * Datei kann von Hand geschrieben, aus einer Sicherung
             * zurueckgespielt oder aus einer aelteren Fassung uebernommen
             * sein - geprueft wird an beiden Enden. */
            $abgewiesen[] = (string) $k;
        }
    }
    $GLOBALS['sk_cfg_speicher'] = array(
        'cfg'        => $cfg,
        'fehlend'    => array_values(array_diff(array_keys($vorgaben), array_keys($datei))),
        'fremd'      => $fremd,
        'abgewiesen' => $abgewiesen,
        /* Der vierte Topf, seit 0.9.15. 'kaputt' heisst: die Datei ist da und
         * unlesbar. Das ist etwas anderes als 'fehlend' - dort steht nichts,
         * hier steht etwas Falsches, und der Unterschied entscheidet, ob man
         * die Werkseinstellung darueberschreiben darf. */
        'lage'       => $lage,
    );
    return $GLOBALS['sk_cfg_speicher'];
}

/**
 * Den Zwischenspeicher von sk_config_lage() verwerfen.
 *
 * Noetig nach JEDEM Schreiben im selben Seitenaufbau. Gemessen am 27.08.2026
 * an 0.9.12: die Konfigurationsdatei trug nach dem Zurueckspielen die neuen
 * Werte, die Seite zeigte aber das alte Aktionstoken und jedes Feld auf altem
 * Stand - und wer daraufhin auf Speichern drueckte, schrieb sieben von zwoelf
 * Werten wieder zurueck.
 */
function sk_config_zwischenspeicher_leeren()
{
    unset($GLOBALS['sk_cfg_speicher']);
}

/**
 * Fehlende Schluessel EINMAL in die Datei schreiben.
 *
 * ANGELEGT 31.08.2026. Der Unterschied zu dem, was bis 0.9.14 geschah, ist
 * klein und der ganze Punkt:
 *
 *   ergaenzen      - beim LESEN tritt fuer einen fehlenden Schluessel seine
 *                    Vorgabe ein. Die Datei bleibt lueckenhaft, und "fehlt"
 *                    ist von "steht auf dem Vorgabewert" nicht zu
 *                    unterscheiden. Das tat sk_config_lage() schon immer.
 *   vervollstaendigen - fehlt ein Schluessel, wird er einmal MIT seiner
 *                    Vorgabe in die Datei geschrieben. Danach steht da, was
 *                    gilt.
 *
 * Gemessen am 31.08.2026: eine Konfiguration aus 0.9.13 mit zehn Schluesseln
 * blieb nach dem Update bei zehn - die sechzehn spaeter dazugekommenen
 * standen dauerhaft nirgends. Das ist der Zustand JEDER bestehenden Anlage
 * nach einem Update.
 *
 * Was ausdruecklich NICHT geschieht: fremde Schluessel werden nicht entfernt.
 * Sie wirken zwar nicht, aber sie sind die Spur einer Umbenennung oder eines
 * Tippfehlers, und der Reiter Test nennt sie. Ein stilles Wegraeumen waere
 * dieselbe Klasse Fehler wie das stille Ueberschreiben, gegen das der ganze
 * Abschnitt hier gebaut ist.
 *
 * Gerufen wird das nur, wo jemand angemeldet ist - aus der Oberflaeche.
 * Der Miniserver-Endpunkt schreibt nichts.
 *
 * Rueckgabe: die Zahl der nachgetragenen Schluessel.
 */
function sk_config_vervollstaendigen()
{
    $p = sk_paths();
    list($datei, $lage) = sk_json_lage($p['config']);
    if ($lage !== 'ok') {
        // 'fehlt', 'leer' und 'kaputt' gehoeren sk_config_heilen(); hier
        // wuerde ein Schreibvorgang die Heilung ueberholen.
        return 0;
    }
    $fehlend = array();
    foreach (sk_vorgaben() as $k => $v) {
        if (!array_key_exists($k, $datei)) {
            $datei[$k] = $v;
            $fehlend[] = $k;
        }
    }
    if (!$fehlend) {
        return 0;
    }
    if (!sk_json_schreiben($p['config'], $datei)) {
        return 0;
    }
    sk_config_zwischenspeicher_leeren();
    // Einmal, nicht bei jedem Lauf: nach dem Schreiben fehlt nichts mehr,
    // und die Bedingung oben trifft nicht wieder zu.
    sk_log_zeile('Konfiguration vervollstaendigt, ' . count($fehlend)
               . ' Schluessel nachgetragen: ' . implode(', ', $fehlend));
    return count($fehlend);
}

/**
 * Fehlende oder leere Konfiguration aus der Zweitschrift zurueckholen.
 *
 * AUSGELAGERT 31.08.2026 aus sk_config_lage(). Der Grund ist die AUFRUFSTELLE,
 * nicht die Sache: webfrontend/html/index.php ruft sk_config() als erstes,
 * noch vor der Tokenpruefung - anders geht es nicht, das Sollzeichen steht ja
 * in der Konfiguration. Damit loeste jeder Aufruf aus dem Netz ein mkdir und
 * ein copy im Konfigordner aus, auch ein abgewiesener.
 *
 * Gemessen: skoda.json auf 0 Byte gekuerzt, Zweitschrift mit altem Inhalt
 * daneben, Aufruf mit FALSCHEM Token -> HTTP 403, und danach stand die alte
 * Datei wieder da, samt dem alten Aktionstoken. Wer sein Token neu wuerfelt
 * und alle Adressen im Miniserver nachtraegt, haette das alte damit ohne sein
 * Zutun wieder gueltig gemacht.
 *
 * Gerufen wird die Heilung jetzt nur noch dort, wo jemand angemeldet ist oder
 * das System selbst arbeitet: aus der Oberflaeche und aus postinstall.sh.
 *
 * Rueckgabe: true, wenn tatsaechlich zurueckgeholt wurde.
 */
function sk_config_heilen()
{
    $p = sk_paths();
    list(, $lage) = sk_json_lage($p['config']);
    if ($lage === 'ok') {
        return false;
    }

    /* EINE BESCHAEDIGTE DATEI WIRD ZUR SEITE GELEGT, NICHT UEBERSCHRIEBEN.
     *
     * Bis 0.9.14 heilte diese Funktion nur bei 'leer'. Eine abgeschnittene
     * Datei ging als Werkseinstellung durch, und der naechste Schreibvorgang
     * loeschte sie samt Zweitschrift. Jetzt bleibt sie als .kaputt liegen -
     * einmal, nicht bei jedem Aufruf: eine zweite kaputte Datei wuerde die
     * erste ueberschreiben, und die erste ist die interessante. */
    if ($lage === 'kaputt') {
        $ziel = $p['config'] . '.kaputt';
        if (!is_file($ziel)) {
            @copy($p['config'], $ziel);
            @chmod($ziel, 0600);
        }
        sk_log_zeile('Die Konfigurationsdatei war beschaedigt (kein gueltiges JSON). '
                   . 'Sie liegt als ' . basename($ziel) . ', '
                   . (is_file($p['sicherung'])
                      ? 'die Zweitschrift wird zurueckgeholt.'
                      : 'eine Zweitschrift gibt es nicht.'));
    }

    if (!is_file($p['sicherung'])) {
        return false;
    }

    /* Die Zweitschrift wird GELESEN, nicht kopiert. Eine kaputte Sicherung
     * ueber eine kaputte Datei zu legen hilft niemandem, und ein 'copy'
     * kann nicht sagen, ob der Inhalt taugt. */
    list($gut, $slage) = sk_json_lage($p['sicherung']);
    if ($slage !== 'ok' || !$gut) {
        sk_log_zeile('Die Zweitschrift ist selbst unbrauchbar (' . $slage . ') - '
                   . 'es wurde nichts zurueckgeholt.');
        return false;
    }
    if (!is_dir($p['configdir'])) {
        @mkdir($p['configdir'], 0775, true);
    }
    if (!sk_json_schreiben($p['config'], $gut)) {
        return false;
    }
    sk_config_zwischenspeicher_leeren();
    return true;
}

/**
 * Eine JSON-Datei schreiben - ueber eine Nebendatei mit rename().
 *
 * ANGELEGT 31.08.2026. Bis 0.9.14 schrieb sk_config_speichern() unmittelbar
 * mit file_put_contents(). Zwei Loecher, beide gemessen an der Vertragslage
 * der Funktion:
 *
 *   1. Ein Abbruch mitten im Schreiben hinterlaesst eine halbe Datei. Genau
 *      die ist der Ausgangspunkt des Vorfalls oben. Mit Nebendatei und
 *      rename() gibt es nur zwei Zustaende: alte Datei oder neue.
 *   2. file_put_contents() liefert die BYTEANZAHL, nicht true. Eine
 *      Kurzschreibung (volle Karte) ist nicht false und lief bis 0.9.14
 *      als Erfolg durch.
 *
 * Die Nebendatei traegt die Prozessnummer, sonst zerlegen zwei gleichzeitige
 * Schreiber einander. Und die Rechte stehen VOR dem Inhalt: in zugang.json
 * steht ein Passwort im Klartext.
 */
function sk_json_schreiben($ziel, $daten, $rechte = 0644)
{
    $json = json_encode($daten, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE
                              | JSON_UNESCAPED_SLASHES);
    // json_encode liefert bei ungueltigem UTF-8 false, und ein blindes
    // Schreiben legte dann eine leere Datei an - und meldete Erfolg.
    if ($json === false) {
        return false;
    }
    $tmp = $ziel . '.tmp.' . getmypid();
    $fh = @fopen($tmp, 'c');
    if ($fh === false) {
        return false;
    }
    @chmod($tmp, $rechte);
    $ok = @ftruncate($fh, 0) && @fwrite($fh, $json) === strlen($json);
    @fflush($fh);
    @fclose($fh);
    if (!$ok || !@rename($tmp, $ziel)) {
        @unlink($tmp);
        return false;
    }
    @chmod($ziel, $rechte);
    return true;
}

function sk_config_speichern($cfg)
{
    $p = sk_paths();
    if (!is_dir($p['configdir'])) {
        @mkdir($p['configdir'], 0775, true);
    }
    if (!sk_json_schreiben($p['config'], $cfg)) {
        return false;
    }
    /* DIE ZWEITSCHRIFT WIRD ERST NACH GELUNGENEM ZURUECKLESEN ERNEUERT.
     *
     * Bis 0.9.14 stand hier ein blindes copy() der eben geschriebenen Datei.
     * War die neue Datei unbrauchbar, war es die Sicherung eine Zeile spaeter
     * auch - beide Staende weg, und das ist der Fall, fuer den es sie gibt. */
    list($zurueck, $lage) = sk_json_lage($p['config']);
    if ($lage === 'ok' && $zurueck) {
        sk_json_schreiben($p['sicherung'], $zurueck);
    }
    sk_config_zwischenspeicher_leeren();
    return true;
}

/** Die Fassung aus der plugin.cfg, oder ''. */
function sk_fassung()
{
    static $f = null;
    if ($f !== null) {
        return $f;
    }
    $f = '';
    $p = sk_paths();
    foreach (array(dirname(dirname(dirname(__FILE__))) . '/plugin.cfg',
                   $p['home'] . '/config/plugins/' . $p['plugin'] . '/plugin.cfg') as $k) {
        if ($k === '' || !is_file($k)) {
            continue;
        }
        /* Zeilenweise, nicht parse_ini_file: die plugin.cfg traegt Kommentare
         * mit Sonderzeichen und unquotierte Werte. */
        foreach (file($k, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) ?: array() as $z) {
            if (preg_match('/^\s*VERSION\s*=\s*([0-9][0-9.]*)/', $z, $m)) {
                $f = $m[1];
                return $f;
            }
        }
    }
    return $f;
}

/**
 * Eine Zeile in die Logdatei des Plugins - fuer Handgriffe der Oberflaeche.
 *
 * WARUM. Bis 0.9.12 schrieb die Oberflaeche NIE ins Protokoll: kein Eintrag,
 * wenn das Aktionstoken neu gewuerfelt, eine Sicherung eingespielt, der Zugang
 * geloescht oder ein Schaltbefehl aus dem Reiter Test abgesetzt wurde. Nach
 * einem fremden Formular (siehe sk_formtoken) oder einem versehentlichen
 * Zurueckspielen gab es damit keine Spur.
 */
function sk_log_zeile($text)
{
    $p = sk_paths();
    if (!is_dir($p['logdir'])) {
        @mkdir($p['logdir'], 0775, true);
    }
    $z = '[' . date('Y-m-d H:i:s') . '] OBERFLAECHE '
       . str_replace(array("\r", "\n"), ' ', (string) $text) . "\n";
    @file_put_contents($p['log'], $z, FILE_APPEND);

    /* KAPPUNG - und sie gehoert HIERHER.
     *
     * Bis 0.9.14 kappte nur der Dienst (bin/skoda.py, RotatingFileHandler,
     * 512000 Byte) - dieselbe Datei. Steht der Dienst, waechst skoda.log
     * durch die Oberflaeche unbegrenzt weiter, und log/plugins liegt auf
     * einer Ramdisk.
     *
     * clearstatcache VOR filesize: PHP merkt sich die Groesse aus dem ersten
     * stat() eines Seitenaufbaus. Ohne das Leeren misst die Kappung die
     * Groesse VOR dem eben angehaengten Text - bei einer Datei, die gerade
     * die Grenze reisst, faellt sie damit still aus. */
    clearstatcache(true, $p['log']);
    if ((int) @filesize($p['log']) <= 512000) {
        return;
    }
    $zeilen = @file($p['log']);
    if (!is_array($zeilen)) {
        return;
    }
    /* GEKAPPT WIRD IN DER DATEI, NICHT UEBER EINE NEBENDATEI.
     *
     * Berichtigt 01.09.2026, noch vor der Auslieferung. Der erste Entwurf
     * schrieb eine Nebendatei und benannte sie um - genau der Handgriff, der
     * den Dauerlaeufer sein Protokoll kostet: er haelt seinen Dateizeiger auf
     * die alte Inode und schreibt dort weiter, wo niemand mehr liest.
     *
     * In der Datei zu kuerzen behaelt die Inode. Der Dauerlaeufer hat sie im
     * Anhaengemodus offen (O_APPEND), setzt also vor jedem Schreiben ans
     * Ende - er haengt danach an den gekuerzten Inhalt an, ohne Luecke.
     *
     * Der Preis: waehrend des Kuerzens ist die Datei kurz halb geschrieben.
     * Das ist die kleinere Muenze - eine Protokollzeile, die einmal
     * verstuemmelt aussieht, gegen ein Protokoll, das ab dem Umlauf leer
     * bleibt. */
    $inhalt = implode('', array_slice($zeilen, -200));
    $fh = @fopen($p['log'], 'r+');
    if ($fh === false) {
        return;
    }
    if (@flock($fh, LOCK_EX)) {
        @ftruncate($fh, 0);
        @rewind($fh);
        @fwrite($fh, $inhalt);
        @fflush($fh);
        @flock($fh, LOCK_UN);
    }
    @fclose($fh);
}

/**
 * Zugangsdaten.
 *
 * Eigene Datei mit Rechten 0600, nicht in der Konfiguration, die die
 * Oberflaeche anzeigt. Passwort und S-PIN werden nie zurueckgegeben - nur
 * ihre Laenge.
 */
function sk_zugang()
{
    $z = sk_json_lesen(sk_paths()['zugang']);
    return array(
        'email'       => isset($z['email']) ? (string) $z['email'] : '',
        'laenge'      => isset($z['passwort']) ? strlen((string) $z['passwort']) : 0,
    );
}

/**
 * Speichert die Zugangsdaten.
 *
 * Ein leer zurueckgegebenes Passwortfeld loescht nichts: sonst stuende
 * irgendwann ein leeres Passwort in der Datei, ohne dass es jemand merkt.
 * Genau dieser Fehler hat im ACTi-Plugin 21 vergebliche Anmeldeversuche
 * verursacht.
 */
/* Ohne S-PIN, und das mit Absicht (0.9.11): das Plugin bietet weder Ver-
 * noch Entriegeln an, und nur dafuer verlangt MySkoda sie. Ein
 * Geheimnis, das nichts bewirkt, ist reines Risiko - es lag dauerhaft
 * auf der Platte und wanderte bei jedem Upgrade in eine Zweitschrift
 * daneben. Ein vorhandener Wert wird beim Speichern MIT ENTFERNT: der
 * neue Inhalt kennt den Schluessel nicht mehr. */
function sk_zugang_speichern($email, $passwort)
{
    $p = sk_paths();
    if (!is_dir($p['configdir'])) {
        @mkdir($p['configdir'], 0775, true);
    }
    $alt = sk_json_lesen($p['zugang']);
    $neu = array(
        'email'    => $email !== null ? $email : (isset($alt['email']) ? $alt['email'] : ''),
        'passwort' => ($passwort !== null && $passwort !== '')
                      ? $passwort
                      : (isset($alt['passwort']) ? $alt['passwort'] : ''),
    );
    // Rechte VOR dem Inhalt, und ueber eine Nebendatei: hier steht ein
    // Passwort im Klartext, und "schreiben, dann chmod" laesst die Datei fuer
    // die Dauer des Schreibens mit den Vorgaben der umask stehen.
    return sk_json_schreiben($p['zugang'], $neu, 0600);
}

/**
 * Loescht Benutzername, Passwort und S-PIN restlos.
 *
 * Warum das eine eigene Funktion und einen eigenen Schalter braucht:
 * sk_zugang_speichern() behaelt ein leeres Passwortfeld absichtlich bei -
 * sonst stuende irgendwann ein leeres Passwort in der Datei, ohne dass es
 * jemand merkt. Genau diese Vorsicht macht aber den umgekehrten Weg
 * unmoeglich: Wer sich vertippt hat oder das Konto aus der Hand gibt, kam
 * bis 0.9.1 ueber die Oberflaeche nicht mehr an die Daten heran. Loeschen
 * muss man ausdruecklich wollen - deshalb das Haekchen, nicht das leere Feld.
 *
 * Die Datei wird ueberschrieben und dann entfernt. Nur unlink() wuerde den
 * Inhalt auf der Karte stehen lassen, bis der Platz neu vergeben wird.
 *
 * MIT WEG MUSS DIE SICHERUNG. preupgrade.sh legt eine Kopie der
 * Zugangsdatei NEBEN dem Plugin-Konfigordner ab, und postinstall.sh spielt
 * sie zurueck, wenn die richtige Datei fehlt oder leer ist - genau dafuer
 * ist sie da. Wuerde hier nur zugang.json geloescht, stuende das Passwort
 * weiterhin auf der Karte und waere bei der naechsten Neuinstallation
 * wieder da. Ein Loeschen, das nicht loescht, ist schlimmer als keines.
 */
function sk_zugang_loeschen()
{
    $p = sk_paths();
    $ok = true;
    foreach (array($p['zugang'], $p['zugang_sicherung']) as $f) {
        if (!is_file($f)) {
            continue;
        }
        // Der Zwischenspeicher von stat() haelt die erste Antwort fest.
        // Wurde die Datei im selben Seitenaufbau geschrieben - Zugangsdaten
        // speichern und im selben Zug loeschen ist ueber das Formular
        // erreichbar -, ueberschriebe die Schleife sonst die ALTE Laenge und
        // liesse den Rest des Klartexts auf der Karte stehen. Der zweite
        // Parameter beschraenkt das Leeren auf diese Datei.
        clearstatcache(true, $f);
        $laenge = (int) @filesize($f);
        if ($laenge > 0) {
            @file_put_contents($f, str_repeat('0', $laenge));
        }
        $ok = @unlink($f) && $ok;
    }
    return $ok;
}

/** Zufallstoken fuer den unangemeldeten Endpunkt. */
function sk_token_erzeugen($laenge = 24)
{
    $zeichen = 'abcdefghijkmnpqrstuvwxyz23456789';
    $t = '';
    for ($i = 0; $i < $laenge; $i++) {
        $t .= $zeichen[random_int(0, strlen($zeichen) - 1)];
    }
    return $t;
}

/** Sorgt dafuer, dass ein Token vorhanden ist, und gibt es zurueck. */
function sk_token()
{
    $cfg = sk_config();
    if (trim((string) $cfg['aktionstoken']) === '') {
        $cfg['aktionstoken'] = sk_token_erzeugen();
        sk_config_speichern($cfg);
    }
    return (string) $cfg['aktionstoken'];
}

/* ==================================================================
 * Der Wachposten gegen fremde Formulare
 *
 * WARUM ES IHN BRAUCHT. htmlauth/ schuetzt gegen den unangemeldeten Aufruf -
 * NICHT dagegen, dass der Browser eines ANGEMELDETEN Bedieners ein Formular
 * abschickt, das auf einer fremden Seite steht. Die HTTP-Basic-Anmeldung
 * schickt er dabei automatisch mit; SameSite greift nicht.
 *
 * Bis 0.9.12 gab es hier nichts, und der Kopfkommentar der index.php
 * behauptete trotzdem einen Wachposten. Gemessen am 27.08.2026 an 0.9.12:
 *
 *   POST {token_neu:1}   -> Aktionstoken neu gewuerfelt
 *   POST {log_leeren:1}  -> Protokoll ueberschrieben
 *
 * Danach bekommen saemtliche virtuellen Eingaenge im Miniserver HTTP 403 -
 * die Ueberwachung ist tot, ohne jede Rueckmeldung -, und die Spur ist gleich
 * mit weg. Der Angreifer sieht die Antwort nicht; er braucht sie auch nicht.
 * Derselbe Befund stand 2026 in Docker NG ueber vier Fassungen.
 *
 * DAS MERKMAL wird ABGELEITET, nicht gespeichert. Es gibt damit keinen
 * zweiten Wert, der verlorengehen oder auseinanderlaufen kann, und es wechselt
 * automatisch mit, wenn das Aktionstoken neu gewuerfelt wird.
 * ================================================================== */

function sk_formtoken()
{
    $cfg = sk_config();
    $t = trim((string) $cfg['aktionstoken']);
    // Fail closed: ohne Aktionstoken gibt es kein Merkmal. Ein aus dem
    // Leerstring abgeleiteter Wert waere fuer jeden ausrechenbar und damit
    // kein Schutz, sondern die Behauptung eines Schutzes.
    if ($t === '') {
        return '';
    }
    return hash_hmac('sha256', 'formular-v1', $t);
}

/** Das versteckte Feld fuer jedes Formular. */
function sk_formfeld()
{
    return '<input data-role="none" type="hidden" name="fmt" value="'
         . sk_e(sk_formtoken()) . '">';
}

/**
 * Traegt dieser POST das richtige Merkmal?
 *
 * Der LEERE Fall wird eigens abgefangen: hash_equals('', '') ergibt in PHP
 * TRUE. Wer das Feld nicht vor dem Vergleich auf leer prueft, hat einen
 * Wachposten gebaut, den jeder passiert, der das Feld einfach leer laesst.
 */
function sk_formtoken_ok()
{
    $soll = sk_formtoken();
    if ($soll === '') {
        return false;
    }
    $ist = isset($_POST['fmt']) && is_string($_POST['fmt']) ? (string) $_POST['fmt'] : '';
    if ($ist === '') {
        return false;
    }
    return hash_equals($soll, $ist);
}

/* ---------------- Zwischenspeicher lesen ---------------- */

function sk_loxone()
{
    return sk_json_lesen(sk_paths()['datadir'] . '/loxone.json');
}

function sk_zustand()
{
    return sk_json_lesen(sk_paths()['datadir'] . '/zustand.json');
}

/** Fahrzeuge aus dem Abbild, 1-basiert. */
function sk_fahrzeuge()
{
    $l = sk_loxone();
    return isset($l['fahrzeuge']) && is_array($l['fahrzeuge']) ? $l['fahrzeuge'] : array();
}

/**
 * Alter des Abbilds in Sekunden. Negativ heisst: es gibt keins Brauchbares.
 *
 *   -1  es hat noch nie einen Abruf gegeben
 *   -2  der Zeitstempel liegt in der ZUKUNFT
 *
 * DER ZWEITE FALL IST SEIT 0.9.14 EIGENS BEHANDELT. Bis dahin stand hier
 * max(0, time() - ts), und ein Zeitstempel aus der Zukunft wurde damit zu
 * ALTER=0 - also zum frischestmoeglichen Wert. Zusammen mit OK=1 sah eine
 * Anlage, an der seit Stunden nichts mehr abgerufen wird, in Loxone aus wie
 * eine, die gerade geantwortet hat. Die Ausfallerkennung, auf die dieses
 * Plugin ausdruecklich baut, greift dann nie.
 *
 * Das ist kein erfundener Fall: bin/skoda.py beschreibt ihn selbst - "ein
 * Raspberry ohne Echtzeituhr springt beim ersten Zeitabgleich". Und
 * webfrontend/html/index.php hatte dieselbe Falle fuer den Wert -1 bereits
 * geschlossen ("minus eins ist kleiner als jede Schwelle, ein nie gelaufener
 * Dienst sah also aus wie ein besonders frischer Wert") - eine Ebene tiefer
 * war sie offen geblieben.
 *
 * Die 60 Sekunden Spielraum sind Absicht: eine Sekunde Unterschied zwischen
 * dem schreibenden und dem lesenden Prozess ist normal und kein Uhrensprung.
 */
function sk_alter()
{
    $l = sk_loxone();
    if (!isset($l['ts'])) {
        return -1;
    }
    $alter = time() - (int) $l['ts'];
    if ($alter < -60) {
        return -2;
    }
    return max(0, $alter);
}

/**
 * Die letzten $anzahl Zeilen einer Datei, neueste zuerst.
 *
 * Bis 0.9.1 las die Oberflaeche das ganze Protokoll mit file() ein und warf
 * 95 Prozent davon wieder weg. Nachgemessen an einem 512 kB grossen Protokoll
 * (7521 Zeilen, 400 gewuenscht), PHP 7.4 und 8.1 gleich:
 *
 *   file() + array_reverse   0,3 ms   Spitze 1503 kB
 *   exec("tail -n 400")      1,9 ms   Spitze   79 kB
 *   rueckwaerts mit fseek    0,1 ms   Spitze  167 kB
 *
 * Der Speicherhinweis war also berechtigt, der vorgeschlagene Weg ueber tail
 * aber der schlechteste von dreien: ein Prozessstart kostet mehr, als das
 * Einlesen je gespart hat. Rueckwaerts lesen ist in beidem besser - und
 * braucht keine Shell, die man wieder absichern muesste.
 */
function sk_log_ende($datei, $anzahl = 400, $block = 8192)
{
    $fp = @fopen($datei, 'rb');
    if ($fp === false) {
        return array();
    }
    fseek($fp, 0, SEEK_END);
    $pos = ftell($fp);
    $puffer = '';
    $zeilen = array();
    // So lange blockweise nach vorn, bis genug Zeilen beisammen sind. Eine
    // Zeile mehr als noetig, damit die oberste nicht halbiert ausgeliefert wird.
    while ($pos > 0 && count($zeilen) <= $anzahl) {
        $lese = (int) min($block, $pos);
        $pos -= $lese;
        fseek($fp, $pos, SEEK_SET);
        $puffer = fread($fp, $lese) . $puffer;
        $zeilen = explode("\n", $puffer);
    }
    fclose($fp);
    $zeilen = array_values(array_filter(array_map('rtrim', $zeilen), 'strlen'));
    return array_slice(array_reverse($zeilen), 0, $anzahl);
}

/* ---------------- Dienst ---------------- */

function sk_dienst_pid()
{
    $f = sk_paths()['datadir'] . '/dienst.pid';
    if (!is_file($f)) {
        return 0;
    }
    $pid = (int) trim((string) @file_get_contents($f));
    if ($pid <= 0 || !is_dir('/proc/' . $pid)) {
        return 0;
    }
    /* Nummernrecycling ausschliessen: der Prozess muss unser Skript sein.
     *
     * Bis 0.9.10 stand hier strpos($cmd, 'skoda.py'). Der Rahmen war schon
     * richtig - geprueft wird nur die Nummer aus der eigenen PID-Datei, es
     * wird nichts gesucht -, aber die Pruefung selbst zu weich:
     * /proc/<pid>/cmdline enthaelt ALLE Argumente, durch Nullbytes getrennt.
     * Hat die wiederverwendete Nummer einen Editor mit geoeffneter skoda.py
     * erwischt, galt der als laufender Dienst. Die Oberflaeche reihte dann
     * Befehle ein, die niemand abarbeitet, und meldete "eingereiht" statt
     * "laeuft nicht".
     *
     * Verglichen wird jetzt argumentweise gegen den vollen Pfad. Das trifft
     * auch den Fall zweier Exemplare des Plugins: LoxBerry haengt bei
     * Namenskonflikt 01, 02 ... an den Ordnernamen an. */
    $cmd = (string) @file_get_contents('/proc/' . $pid . '/cmdline');
    $argv = explode("\0", $cmd);
    $skript = sk_paths()['bindir'] . '/skoda.py';
    /* Zwei Bedingungen, nicht eine:
     *   argv[1] ist genau unser Skript UND
     *   argv[0] ist ein Python.
     * Die zweite braucht es, weil "nano /pfad/skoda.py" ebenfalls den vollen
     * Pfad als zweites Argument fuehrt. Der Dienst wird immer als
     * "<venv>/bin/python3 <pfad>/skoda.py" gestartet. */
    if (isset($argv[0], $argv[1])
        && $argv[1] === $skript
        && preg_match('#(^|/)python[0-9.]*$#', $argv[0])) {
        return $pid;
    }
    return 0;
}

function sk_dienst_soll()
{
    return is_file(sk_paths()['datadir'] . '/soll_laufen') ? 1 : 0;
}

/**
 * $befehl ist 'start', 'stop' oder 'restart'. Rueckgabe: array(ok, Ausgabe)
 *
 * Hier und an den drei anderen exec-Stellen stand bis 0.9.1
 * escapeshellcmd($pfad). Das ist nicht dasselbe wie escapeshellarg(): es
 * entschaerft Sonderzeichen, setzt aber KEINE Anfuehrungszeichen - ein
 * Leerzeichen im Pfad bleibt ein Trennzeichen. Nachgestellt mit
 * /tmp/sk/mit ordner/venv/bin/python3:
 *   escapeshellcmd -> Code 127, "sh: 1: /tmp/sk/mit: not found"
 *   escapeshellarg -> Code 0, das Programm lief
 * Im Regelfall ist der Pfad <LoxBerry-Wurzel>/bin/plugins/<name> und enthaelt
 * kein Leerzeichen, der Fehler war also nicht ausloesbar. Geaendert wurde
 * trotzdem: escapeshellarg ist das richtige Werkzeug und kostet nichts.
 */
function sk_dienst($befehl)
{
    if (!in_array($befehl, array('start', 'stop', 'restart'), true)) {
        return array(0, sk_t('MELD.BEFEHL_UNBEKANNT'));
    }
    $skript = sk_paths()['bindir'] . '/dienst.sh';
    if (!is_file($skript)) {
        return array(0, sprintf(sk_t('MELD.DIENSTSH_FEHLT'), $skript));
    }
    $ausgabe = array();
    $code = 0;
    @exec(escapeshellarg($skript) . ' ' . escapeshellarg($befehl) . ' 2>&1', $ausgabe, $code);
    return array($code === 0 ? 1 : 0, implode("\n", $ausgabe));
}

/** Fassung der Python-Bibliothek in der virtuellen Umgebung, oder ''. */
function sk_bibliothek_fassung()
{
    $py = sk_paths()['bindir'] . '/venv/bin/python3';
    if (!is_file($py)) {
        return '';
    }
    $ausgabe = array();
    @exec(escapeshellarg($py) . ' -c ' . escapeshellarg(
        'import importlib.metadata as m; print(m.version("myskoda"))'
    ) . ' 2>/dev/null', $ausgabe);
    return trim(implode('', $ausgabe));
}

/** Fassung des Python in der virtuellen Umgebung, oder ''. */
function sk_python_fassung()
{
    $py = sk_paths()['bindir'] . '/venv/bin/python3';
    if (!is_file($py)) {
        return '';
    }
    $ausgabe = array();
    @exec(escapeshellarg($py) . ' -c ' . escapeshellarg(
        'import sys; print("%d.%d.%d" % sys.version_info[:3])'
    ) . ' 2>/dev/null', $ausgabe);
    return trim(implode('', $ausgabe));
}

/** Ausgabe von skoda.py --selbsttest. */
function sk_selbsttest()
{
    $p = sk_paths();
    $py = $p['bindir'] . '/venv/bin/python3';
    $skript = $p['bindir'] . '/skoda.py';
    if (!is_file($py) || !is_file($skript)) {
        return sprintf(sk_t('MELD.VENV_FEHLT'), $py, $skript);
    }
    $ausgabe = array();
    @exec(escapeshellarg($py) . ' ' . escapeshellarg($skript) . ' --selbsttest 2>&1', $ausgabe);
    return implode("\n", $ausgabe);
}

/**
 * Die schaltenden Aktionen - an EINER Stelle.
 *
 * Bis 0.9.12 standen sie an dreien, und die drei waren auseinander:
 *
 *   Endpunkt kannte                12
 *   Reiter Loxone nannte als Adresse  7
 *   Reiter Test bot als Knopf         9
 *
 * Undokumentiert waren damit zieltemperatur, scheibe_aus, lueftung_start,
 * lueftung_stop und wecken - fuenf Funktionen, die das Plugin beherrscht und
 * die niemand findet.
 *
 * Je Aktion: Knopfbeschriftung (Reiter Test), Erklaerung (Reiter Loxone und
 * Ausgangsvorlage), der Name des Zusatzwertes ('' = keiner) und ob der Reiter
 * Test einen Knopf dafuer zeigt.
 *
 * Die Knopfbeschriftungen sind die vorhandenen TEST.K_*: sie stehen seit
 * jeher in beiden Sprachdateien und sind dort schon abgestimmt. Eigene
 * Schluessel dafuer zu erfinden haette acht bestehende verwaisen lassen.
 */
function sk_befehle()
{
    return array(
        'klima_start'    => array('TEST.K_KLIMA_EIN',   'SK_BEF.KLIMA_EIN',   'temp',    1),
        'klima_stop'     => array('TEST.K_KLIMA_AUS',   'SK_BEF.KLIMA_AUS',   '',        1),
        'zieltemperatur' => array('TEST.K_ZIELTEMP',    'SK_BEF.ZIELTEMP',    'temp',    1),
        'laden_start'    => array('TEST.K_LADEN_EIN',   'SK_BEF.LADEN_EIN',   '',        1),
        'laden_stop'     => array('TEST.K_LADEN_AUS',   'SK_BEF.LADEN_AUS',   '',        1),
        'ladegrenze'     => array('TEST.K_LADEGRENZE',  'SK_BEF.LADEGRENZE',  'prozent', 1),
        'scheibe_ein'    => array('TEST.K_SCHEIBE_EIN', 'SK_BEF.SCHEIBE_EIN', '',        1),
        'scheibe_aus'    => array('TEST.K_SCHEIBE_AUS', 'SK_BEF.SCHEIBE_AUS', '',        1),
        'lueftung_start' => array('TEST.K_LUEFT_EIN',   'SK_BEF.LUEFT_EIN',   '',        1),
        'lueftung_stop'  => array('TEST.K_LUEFT_AUS',   'SK_BEF.LUEFT_AUS',   '',        1),
        'wecken'         => array('TEST.K_WECKEN',      'SK_BEF.WECKEN',      '',        1),
        'abruf'          => array('TEST.K_ABRUF',       'SK_BEF.ABRUF',       '',        1),
    );
}

/** Die lesenden Aktionen des Endpunkts. */
function sk_lesende()
{
    return array('status', 'laden', 'wartung', 'position', 'fahrzeuge', 'ladungen', 'roh');
}

/* ---------------- Befehlswarteschlange ----------------
 *
 * Sowohl der Miniserver-Endpunkt als auch der Reiter Test setzen Befehle ueber
 * diese eine Funktion ab. Zwei Kopien derselben Logik laufen zwangslaeufig
 * auseinander.
 *
 * Rueckgabe: array(ok, meldung). ok = 1 erledigt, 0 abgelehnt,
 * 2 eingereiht, aber ohne Antwort in der Wartezeit - also Ergebnis unbekannt.
 * Es wird bewusst kein Erfolg gemeldet, den niemand geprueft hat.
 */
function sk_befehl_absetzen($befehl, $wartezeit = null)
{
    $p = sk_paths();
    $cfg = sk_config();
    if ($wartezeit === null) {
        $wartezeit = (int) $cfg['wartezeit'];
    }
    /* Die Grenzen stehen in sk_regeln() - eine zweite Wahrheit ueber einen
     * zulaessigen Wert ist genau das, was diese Funktion dort ausschliesst. */
    $sk_r = sk_regeln();
    $wartezeit = max($sk_r['wartezeit'][1], min($sk_r['wartezeit'][2], (int) $wartezeit));

    /* Die PID-Pruefung steht HIER und nicht beim Aufrufer.
     *
     * Bis 0.9.12 stand sie nur im Miniserver-Endpunkt; sk_test_aktion() im
     * Reiter Test reihte ohne jede Pruefung ein - obwohl die Pruefzeile
     * darueber im selben Bild zeigte, dass der Dienst nicht laeuft. Die
     * Oberflaeche wartete dann acht Sekunden, meldete "Eingereiht, aber der
     * Dienst hat nicht geantwortet", und die Datei blieb bis zum naechsten
     * Start liegen. Ein klima_start vom Vortag heizte das Auto in der Nacht.
     *
     * Der Kommentar ueber dieser Funktion verspricht seit jeher, dass beide
     * Wege dieselbe Logik benutzen, damit sie nicht auseinanderlaufen -
     * eingeloest ist das erst jetzt. */
    if (sk_dienst_pid() === 0) {
        return array(0, sk_t('ALLG.DIENST_LAEUFT_NICHT'));
    }

    /* UND DIE SPERRE STEHT AUCH HIER - seit 0.9.15.
     *
     * Bis 0.9.14 pruefte nur der Miniserver-Endpunkt 'steuerung_ein'. Die
     * Knoepfe des Reiters Test gingen an ihm vorbei: elf davon wies der
     * Dienst ab, der zwoelfte nicht - 'abruf' wird in bin/skoda.py VOR der
     * Sperre abgearbeitet. Wer den Haken ausgeschaltet hatte, loeste mit
     * "Sofortabruf" weiter vollstaendige Cloud-Durchgaenge aus, waehrend im
     * selben Bild stand: "Die Knoepfe geben deshalb eine Ablehnung zurueck."
     *
     * Drei Stellen, zwei Wahrheiten - jetzt eine. Der Endpunkt fuehrt
     * 'abruf' seit 0.9.13 ausdruecklich unter den schaltenden Aktionen; der
     * Dienst zieht mit derselben Fassung nach. */
    if (empty($cfg['steuerung_ein'])) {
        return array(0, sk_t('ALLG.STEUERUNG_AUS'));
    }

    $ordner = $p['datadir'] . '/befehle';
    if (!is_dir($ordner) && !@mkdir($ordner, 0775, true) && !is_dir($ordner)) {
        return array(0, sprintf(sk_t('MELD.WARTESCHLANGE'), $ordner));
    }
    /* Der Kennung geht die ZEIT voran.
     *
     * Der Dienst arbeitet die Warteschlange mit sorted() ueber die Dateinamen
     * ab. Bis 0.9.12 hiess die Datei nur nach bin2hex(random_bytes(8)) -
     * reiner Zufall. Zwei Befehle aus demselben Zyklus liefen mit halber
     * Wahrscheinlichkeit verkehrt herum: Loxone sendet laden_start, zwei
     * Sekunden spaeter laden_stop, ausgefuehrt wurde stop und dann start -
     * das Auto lud. %014.3f haelt die Stellenzahl bis zum Jahr 2286 gleich,
     * damit die Namensfolge die Zeitfolge bleibt. */
    $kennung = sprintf('%014.3f', microtime(true)) . '-' . bin2hex(random_bytes(8));
    /* Ein Befehl verfaellt. Bis 0.9.12 gab es weder Altersgrenze noch
     * Aufraeumen; eine Befehlsdatei konnte Tage liegen und wurde beim
     * naechsten Start des Dienstes ausgefuehrt. Die Frist ist die Wartezeit
     * plus fuenf Minuten - lange genug fuer einen laufenden Abruf, kurz genug,
     * dass niemand ueberrascht wird. */
    $befehl['ts'] = time();
    $befehl['gueltig_bis'] = time() + $wartezeit + 300;
    $datei = $ordner . '/' . $kennung . '.json';
    $tmp = $datei . '.tmp';
    if (@file_put_contents($tmp, json_encode($befehl)) === false || !@rename($tmp, $datei)) {
        @unlink($tmp);
        return array(0, sprintf(sk_t('MELD.BEFEHL_ABLEGEN'), $datei));
    }
    $antwort = $p['datadir'] . '/antworten/' . $kennung . '.json';
    for ($i = 0; $i < $wartezeit * 10; $i++) {
        if (is_file($antwort)) {
            $a = sk_json_lesen($antwort);
            /* Die Antwort ist verbraucht. Sie wegzuraeumen ist Sache dessen,
             * der sie gelesen hat - der Dienst raeumt nur nach Alter auf, und
             * das erst beim naechsten Befehl. */
            @unlink($antwort);
            return array((int) (isset($a['ok']) ? $a['ok'] : 0),
                         (string) (isset($a['meldung']) ? $a['meldung'] : ''));
        }
        usleep(100000);
    }
    return array(2, sprintf(sk_t('MELD.KEINE_ANTWORT'), (int) $wartezeit));
}

/* ---------------- Verlauf ---------------- */

/**
 * Messpunkte eines Tages.
 *
 * Rueckgabe: array(punkte, art). 'punkte' ist ein Array von
 * array(ts, fuellstand, reichweite), 'art' ist 'soc', 'tank' oder ''.
 *
 * WARUM DIE ART DAZUGEHOERT. Bis 0.9.12 schrieb der Dienst den Ladezustand
 * und ERSATZWEISE den Tankfuellstand in dieselbe Spalte. Bei einem Hybrid,
 * dessen Ladeabruf gelegentlich ausfaellt, standen damit zwei verschiedene
 * Groessen in einer Spalte, und das Diagramm zeichnete sie als eine Linie.
 * Seit 0.9.13 hat die Datei vier Spalten (ts;soc;reichweite;tank); hier wird
 * EINE Reihe fuer den ganzen Tag gewaehlt und mitgesagt, welche.
 *
 * Aeltere Dateien mit drei Spalten bleiben lesbar: dort gilt Spalte 2 als
 * Ladezustand, so wie sie bisher gedeutet wurde.
 */
function sk_verlauf_lesen($nummer, $tag = '')
{
    if ($tag === '') {
        $tag = date('Ymd');
    }
    $f = sk_paths()['datadir'] . '/verlauf/fahrzeug' . (int) $nummer . '_' . $tag . '.csv';
    $soc = array();
    $tank = array();
    if (is_file($f)) {
        foreach (file($f, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) ?: array() as $zeile) {
            $c = explode(';', $zeile);
            if (count($c) < 2) {
                continue;
            }
            $ts = (int) $c[0];
            $rw = isset($c[2]) && $c[2] !== '' ? (float) $c[2] : 0;
            if ($c[1] !== '') {
                $soc[] = array($ts, (float) $c[1], $rw);
            }
            if (isset($c[3]) && $c[3] !== '') {
                $tank[] = array($ts, (float) $c[3], $rw);
            }
        }
    }
    if ($soc) {
        return array($soc, 'soc');
    }
    if ($tank) {
        return array($tank, 'tank');
    }
    return array(array(), '');
}

/**
 * Das Ladeprotokoll, neueste Ladung zuerst.
 *
 * $nummer = 0 heisst: alle Fahrzeuge. Geschrieben wird die Datei vom Dienst
 * (ladung_buchen in bin/skoda.py), je abgeschlossenem Ladevorgang eine Zeile.
 */
function sk_ladungen_lesen($nummer = 0, $hoechstens = 200)
{
    $f = sk_paths()['datadir'] . '/ladungen.csv';
    if (!is_file($f)) {
        return array();
    }
    $aus = array();
    $erste = true;
    foreach (file($f, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) ?: array() as $z) {
        if ($erste) {           // Kopfzeile
            $erste = false;
            continue;
        }
        $c = explode(';', $z);
        if (count($c) < 9) {
            continue;
        }
        if ((int) $nummer > 0 && (int) $c[2] !== (int) $nummer) {
            continue;
        }
        $aus[] = array(
            'beginn' => (int) $c[0], 'ende' => (int) $c[1], 'fahrzeug' => (int) $c[2],
            'vin' => $c[3], 'soc_von' => $c[4], 'soc_bis' => $c[5],
            'dauer_min' => (int) $c[6], 'kw_max' => $c[7], 'ort' => $c[8],
        );
    }
    $aus = array_reverse($aus);
    return array_slice($aus, 0, max(1, (int) $hoechstens));
}

/**
 * Welche Tage hat dieses Fahrzeug im Verlauf, neueste zuerst?
 *
 * Bis 0.9.12 las die Oberflaeche ausschliesslich date('Ymd') - die
 * Tagesdateien der Vortage lagen da und wurden nie angesehen. Der Aufraeumlauf
 * im Dienst behaelt sie so lange, wie 'verlauf_tage' sagt.
 */
function sk_verlauf_tage($nummer, $hoechstens = 14)
{
    $ordner = sk_paths()['datadir'] . '/verlauf';
    $tage = array();
    foreach (glob($ordner . '/fahrzeug' . (int) $nummer . '_*.csv') ?: array() as $f) {
        if (preg_match('/_([0-9]{8})\.csv$/', $f, $m)) {
            $tage[] = $m[1];
        }
    }
    rsort($tage);
    return array_slice($tage, 0, max(1, (int) $hoechstens));
}

/* ---------------- MQTT-Gateway ----------------
 *
 * Das MQTT-Gateway ist seit LoxBerry 3 Bestandteil des Systems, kein Plugin.
 * Es wird nicht nachinstalliert, sondern unter System -> MQTT Gateway
 * eingeschaltet.
 *
 * Mqtt.Brokerhost ist ab Werk auf 'localhost' gesetzt. Eine Pruefung darauf
 * beantwortet also NICHT die Frage, ob Nachrichten ankommen koennen.
 * Massgeblich ist Gatewayautostart.
 */
function sk_mqtt_zustand()
{
    $p = sk_paths();
    $leer = array('gefunden' => 0, 'autostart' => 0, 'fassung' => 0, 'udpport' => 0,
                  'broker' => '', 'brokerport' => '', 'websocket' => '');
    if ($p['home'] === '') {
        return $leer;
    }
    $gen = sk_json_lesen($p['home'] . '/config/system/general.json');
    $m = array();
    if (isset($gen['Mqtt']) && is_array($gen['Mqtt'])) {
        $m = $gen['Mqtt'];
    } elseif (isset($gen['mqtt']) && is_array($gen['mqtt'])) {
        $m = $gen['mqtt'];
    }
    if (!$m) {
        return $leer;
    }
    $hol = function ($gross, $klein) use ($m) {
        if (isset($m[$gross])) {
            return $m[$gross];
        }
        return isset($m[$klein]) ? $m[$klein] : '';
    };
    $auto = $hol('Gatewayautostart', 'gatewayautostart');
    return array(
        'gefunden'   => 1,
        'autostart'  => in_array((string) $auto, array('1', 'true'), true) ? 1 : 0,
        /* Die FASSUNG des MQTT-Gateways, ab Werk 1. Sie entscheidet, was der
         * Anwender eintragen muss: unter V1 jedes Thema von Hand, ab V2
         * erscheint die Themengruppe von selbst in den Subscriptions.
         * 0 heisst "nicht feststellbar" - dann wird nichts behauptet,
         * sondern es werden beide Faelle genannt. */
        'fassung'    => (int) $hol('Gatewayversion', 'gatewayversion'),
        'udpport'    => (int) $hol('Udpinport', 'udpinport'),
        'broker'     => (string) $hol('Brokerhost', 'brokerhost'),
        'brokerport' => (string) $hol('Brokerport', 'brokerport'),
        'websocket'  => (string) $hol('Websocketport', 'websocketport'),
    );
}

/**
 * Der Hinweis zum MQTT-Abo - in der Fassung, die zum GATEWAY passt.
 *
 * Bis hierher stand an den Ausgabestellen unbedingt "Ohne diesen Eintrag
 * kommt am Miniserver nichts an". Das gilt fuer Gateway V1, wo jedes Thema
 * von Hand einzutragen ist. Ab V2 erscheint die Themengruppe von selbst in
 * den Subscriptions - der Satz schickte jeden V2-Anwender zu einem
 * Eingabeplatz, den es nicht gibt.
 *
 * Drei Ausgaenge, nicht zwei: ist die Fassung nicht feststellbar, werden
 * BEIDE Faelle genannt statt einer behauptet.
 */
function sk_abo_text()
{
    $m = sk_mqtt_zustand();
    $f = isset($m['fassung']) ? (int) $m['fassung'] : 0;
    if ($f <= 0) {
        return sk_t('MQTT.ABO_UNBEKANNT');
    }
    $gemessen = ' <span class="sm-mono">'
              . sprintf(sk_t('MQTT.ABO_GEMESSEN'), $f) . '</span>';
    return sk_t($f >= 2 ? 'MQTT.ABO_V2' : 'MQTT.ABO_WARNUNG') . $gemessen;
}

/**
 * Der Abo-Hinweis SAMT Kasten - die Farbe gehoert zur Aussage.
 *
 * Bis 0.9.13 stand an beiden Ausgabestellen ein festes
 * <div class="sm-warnung">, auch um den V2-Satz. Eine Warnung, die sagt "hier
 * ist nichts einzutragen", widerspricht sich selbst; die Vorlage
 * (VORLAGE_hausstandard.css.html) sieht dafuer sm-hinweis vor und laesst
 * sm-warnung nur fuer V1 und den unbekannten Fall.
 */
function sk_abo_kasten()
{
    $m = sk_mqtt_zustand();
    $f = isset($m['fassung']) ? (int) $m['fassung'] : 0;
    $klasse = $f >= 2 ? 'sm-hinweis' : 'sm-warnung';
    return '<div class="' . $klasse . '">' . sk_abo_text() . '</div>';
}


/** Alle Themen, die der Dienst veroeffentlicht, mit ihrer Bedeutung. */
function sk_mqtt_themen()
{
    return array(
        /* Das Lebenszeichen. Es geht bei JEDEM Durchgang hinaus, auch bei
         * einer Stoerung - und deshalb steht es oben.
         *
         * Ein virtueller Eingang behaelt seinen letzten Wert, mit Retain sogar
         * ueber jeden Neustart des Miniservers hinweg. Bis 0.9.12 gab es ueber
         * MQTT weder Zeitstempel noch Alter: ein reiner MQTT-Anwender konnte
         * einen Ausfall grundsaetzlich nicht erkennen, waehrend der HTTP-Weg
         * dafuer ALTER fuehrt. Ueber MQTT gibt es kein Alter, nur einen
         * Zeitstempel - der Miniserver rechnet selbst:
         *     Alter = (Loxone-Zeit + 1230768000) - ts
         *
         * status/dienst kommt nicht vom Dienst, sondern vom Minutencron
         * (skoda.py --wachzeichen): ein Dienst, der seinen eigenen Tod melden
         * soll, ist der falsche Zeuge. */
        'status/ok'                   => 'SK_MQTT.S_OK',
        'status/ts'                   => 'SK_MQTT.S_TS',
        'status/zaehler'              => 'SK_MQTT.S_ZAEHLER',
        'status/dienst'               => 'SK_MQTT.S_DIENST',
        'status/fehler_folge'         => 'SK_MQTT.S_FOLGE',
        'status/fehlertext'           => 'SK_MQTT.S_TEXT',
        'empfehlung'                  => 'SK_MQTT.EMPFEHLUNG',
        /* Die beiden alten Themen bleiben: in bestehenden Anlagen liegen
         * virtuelle Eingaenge darauf. Sie wegzunehmen waere eine stille
         * Aenderung an einer fremden Loxone-Konfiguration. */
        'ok'                          => 'SK_MQTT.OK',
        'fahrzeuge'                   => 'SK_MQTT.FAHRZEUGE',
        'fahrzeugN/soc'               => 'SK_MQTT.SOC',
        'fahrzeugN/reichweite_km'     => 'SK_MQTT.REICHWEITE',
        'fahrzeugN/tank_prozent'      => 'SK_MQTT.TANK',
        'fahrzeugN/kilometerstand'    => 'SK_MQTT.KM',
        'fahrzeugN/verriegelt'        => 'SK_MQTT.VERRIEGELT',
        'fahrzeugN/tueren_offen'      => 'SK_MQTT.TUEREN',
        'fahrzeugN/fenster_offen'     => 'SK_MQTT.FENSTER',
        'fahrzeugN/licht_an'          => 'SK_MQTT.LICHT',
        'fahrzeugN/kofferraum_offen'  => 'SK_MQTT.KOFFER',
        'fahrzeugN/motorhaube_offen'  => 'SK_MQTT.HAUBE',
        'fahrzeugN/klima_an'          => 'SK_MQTT.KLIMA',
        'fahrzeugN/zieltemperatur'    => 'SK_MQTT.ZIELTEMP',
        'fahrzeugN/aussentemperatur'  => 'SK_MQTT.AUSSEN',
        'fahrzeugN/scheibe_vorn'      => 'SK_MQTT.SCHEIBE_V',
        'fahrzeugN/scheibe_hinten'    => 'SK_MQTT.SCHEIBE_H',
        'fahrzeugN/laedt'             => 'SK_MQTT.LAEDT',
        'fahrzeugN/ladeleistung_kw'   => 'SK_MQTT.LADEKW',
        'fahrzeugN/restzeit_min'      => 'SK_MQTT.RESTZEIT',
        'fahrzeugN/ladegrenze'        => 'SK_MQTT.LADEGRENZE',
        'fahrzeugN/kabel_verbunden'   => 'SK_MQTT.KABEL',
        'fahrzeugN/breite'            => 'SK_MQTT.BREITE',
        'fahrzeugN/laenge'            => 'SK_MQTT.LAENGE',
        'fahrzeugN/warnleuchten'      => 'SK_MQTT.WARN',
        'fahrzeugN/inspektion_tage'   => 'SK_MQTT.INSP_TAGE',
        'fahrzeugN/inspektion_km'     => 'SK_MQTT.INSP_KM',
        'fahrzeugN/oelservice_tage'   => 'SK_MQTT.OEL_TAGE',
        'fahrzeugN/oelservice_km'     => 'SK_MQTT.OEL_KM',
        'fahrzeugN/erreichbar'        => 'SK_MQTT.ERREICHBAR',
        'fahrzeugN/in_bewegung'       => 'SK_MQTT.BEWEGUNG',
        'fahrzeugN/zuendung_an'       => 'SK_MQTT.ZUENDUNG',
        /* Ergaenzt mit 0.9.13. Die ersten beiden gibt der Lade-Endpunkt als
         * TEMPO und REICHWBAT aus; ueber MQTT waren sie nicht zu bekommen. */
        'fahrzeugN/ladetempo_kmh'     => 'SK_MQTT.LADETEMPO',
        'fahrzeugN/reichweite_batterie_km' => 'SK_MQTT.REICHWBAT',
        'fahrzeugN/zuhause'           => 'SK_MQTT.ZUHAUSE',
        'fahrzeugN/heim_entfernung_m' => 'SK_MQTT.HEIMENTF',
        /* Texte. Sie werden nur gesendet, wenn sie etwas enthalten: eine
         * leere Nutzlast loescht mit Retain ein behaltenes Thema. */
        'fahrzeugN/modell'            => 'SK_MQTT.MODELL',
        'fahrzeugN/kennzeichen'       => 'SK_MQTT.KENNZEICHEN',
        'fahrzeugN/ladezustand'       => 'SK_MQTT.LADEZUSTAND',
        'fahrzeugN/klima_zustand'     => 'SK_MQTT.KLIMAZUSTAND',
        'fahrzeugN/adresse'           => 'SK_MQTT.ADRESSE',
        'fahrzeugN/warnleuchten_text' => 'SK_MQTT.WARNTEXT',
    );
}

/* ==================================================================
 * Loxone-Vorlagen
 *
 * Nachbau der Bausteine aus LoxBerry::LoxoneTemplateBuilder; das Modul gibt es
 * nur in Perl. Attributreihenfolge, CRLF als Zeilenende und der Tabulator vor
 * den Kindelementen entsprechen dem Original.
 *
 * BERICHTIGT 31.08.2026. Hier stand, der Bau sei "wortgleich uebernommen aus
 * LoxBerry-Plugin-APC-UPS-1.0.0 - nicht neu geschrieben, weil die Fassung
 * dort geprueft ist". Das war er nicht mehr: gegenueber APC-UPS 1.2.4 fehlten
 * am Wurzelelement HintText, als erstes Kindelement <Info templateType>, je
 * Befehlserkennung Unit und HintText, und die Grenzen standen pauschal auf
 * +-2147483647. Der Ausgang trug zusaetzlich ein CmdErrorValue, das in
 * KEINER Ausfuhr und in keinem anderen Plugin des Bestands vorkommt, und ihm
 * fehlte das CmdSep, das 35 Linien fuehren.
 *
 * Die beiden Formen sind jetzt gegen ZWEI unabhaengige Quellen geeicht:
 *   Eingang  ap_xml_virtual_in_http() aus LoxBerry-Plugin-APC-UPS-1.2.4
 *            und die Ausfuhr "VI_Rasenmaeher (LoxBerry-Plugin)_Test.xml"
 *   Ausgang  mower_lib.php aus LoxBerry-Plugin-Robonect-1.1.2 und die
 *            Ausfuhr "VO_Rasenmaeher steuern (LoxBerry-Plugin)_Test.xml"
 * Beide Ausfuhren kommen unveraendert aus Loxone Config und liegen im
 * Arbeitsordner. Attribut fuer Attribut verglichen, vier von vier deckungs-
 * gleich. skoda_pruefen.py haelt das seit demselben Tag nach - es trug bis
 * dahin die ALTE Reihenfolge als Sollwert und meldete sie als "wie im
 * Original".
 * ================================================================== */

function sk_x($s)
{
    return htmlspecialchars((string) $s, ENT_QUOTES | ENT_XML1, 'UTF-8');
}

function sk_xml_virtual_in_http($kopf, $cmds)
{
    $crlf = "\r\n";
    $o = '<?xml version="1.0" encoding="utf-8"?>' . $crlf;
    $o .= '<VirtualInHttp ';
    $o .= 'HintText="' . sk_x(isset($kopf['hint']) ? $kopf['hint'] : '') . '" ';
    $o .= 'Title="' . sk_x($kopf['title']) . '" ';
    $o .= 'Comment="' . sk_x(isset($kopf['comment']) ? $kopf['comment'] : '') . '" ';
    $o .= 'Address="' . sk_x(isset($kopf['address']) ? $kopf['address'] : '') . '" ';
    $o .= 'PollingTime="' . sk_x(isset($kopf['polling']) ? $kopf['polling'] : '60') . '"';
    $o .= '>' . $crlf;
    $o .= "\t" . '<Info templateType="2" minVersion="17010727"/>' . $crlf;
    foreach ($cmds as $c) {
        $min = isset($c['min']) && $c['min'] !== null ? (int) $c['min'] : 0;
        $max = isset($c['max']) && $c['max'] !== null ? (int) $c['max'] : 100;
        $einheit = isset($c['einheit']) ? trim((string) $c['einheit']) : '';
        $unit = $einheit === '' ? '<v.1>' : '<v.1> ' . $einheit;
        $o .= "\t" . '<VirtualInHttpCmd ';
        $o .= 'Title="' . sk_x($c['title']) . '" ';
        $o .= 'Comment="' . sk_x(isset($c['comment']) ? $c['comment'] : '') . '" ';
        $o .= 'Check="' . sk_x(isset($c['check']) ? $c['check'] : ' ') . '" ';
        $o .= 'Signed="true" ';
        $o .= 'Analog="true" ';
        $o .= 'SourceValLow="0" ';
        $o .= 'DestValLow="0" ';
        $o .= 'SourceValHigh="100" ';
        $o .= 'DestValHigh="100" ';
        $o .= 'DefVal="0" ';
        $o .= 'MinVal="' . sk_x($min) . '" ';
        $o .= 'MaxVal="' . sk_x($max) . '" ';
        $o .= 'Unit="' . sk_x($unit) . '" ';
        $o .= 'HintText=""';
        $o .= '/>' . $crlf;
    }
    $o .= '</VirtualInHttp>' . $crlf;
    return $o;
}

/**
 * Die Werte des Status-Endpunkts mit Einheit und Bedeutung.
 *
 * Reihenfolge und Namen sind zugleich die Reihenfolge der Befehlserkennungen
 * in der Loxone-Vorlage. Wer hier etwas einfuegt, aendert die Vorlage mit.
 *
 * Je Feld: array(Einheit, Sprachschluessel, Kleinstwert, Groesstwert).
 *
 * DIE BEIDEN GRENZEN SIND SEIT 0.9.14 PFLICHT. Bis dahin schrieb die Vorlage
 * fuer jeden Eingang MinVal="-2147483647" MaxVal="2147483647". Die Hausregel
 * verbietet genau das: "Loxone zieht daraus die Reglergrenzen und die
 * Plausibilitaetspruefung; wer alles offen laesst, verschenkt beides." Ein
 * Ladezustand von 4000 % faellt mit 0..100 auf, mit dem Pauschalwert nicht.
 *
 * Die Zahlen sind physikalisch begruendet, nicht geraten: Prozent 0..100,
 * Schaltwerte 0..1, HEIMENTF bis zum halben Erdumfang, ALTER bis 999999 -
 * das ist der Sentinelwert, den der Endpunkt fuer "noch nie abgerufen"
 * schickt (webfrontend/html/index.php, sk_alter). Eine Grenze, die den
 * eigenen Sentinelwert abschneidet, waere schlimmer als keine.
 */
function sk_status_felder()
{
    return array(
        'SOC'       => array('%',   'SK_FELD.SOC',        0, 100),
        'TANK'      => array('%',   'SK_FELD.TANK',       0, 100),
        'REICHW'    => array('km',  'SK_FELD.REICHW',     0, 2000),
        'KM'        => array('km',  'SK_FELD.KM',         0, 2000000),
        'VERR'      => array('',    'SK_FELD.VERR',       0, 1),
        'TUEREN'    => array('',    'SK_FELD.TUEREN',     0, 10),
        'FENSTER'   => array('',    'SK_FELD.FENSTER',    0, 10),
        'KOFFER'    => array('',    'SK_FELD.KOFFER',     0, 1),
        'HAUBE'     => array('',    'SK_FELD.HAUBE',      0, 1),
        'LICHT'     => array('',    'SK_FELD.LICHT',      0, 1),
        'KLIMA'     => array('',    'SK_FELD.KLIMA',      0, 1),
        'ZIELTEMP'  => array('&deg;C', 'SK_FELD.ZIELTEMP', 10, 30),
        'AUSSEN'    => array('&deg;C', 'SK_FELD.AUSSEN',  -50, 60),
        'WARN'      => array('',    'SK_FELD.WARN',       0, 50),
        'ERREICH'   => array('',    'SK_FELD.ERREICH',    0, 1),
        'BEWEG'     => array('',    'SK_FELD.BEWEG',      0, 1),
        'ZUEND'     => array('',    'SK_FELD.ZUEND',      0, 1),
        /* Angehaengt mit 0.9.13. Neue Felder duerfen ans ENDE: jeder Suchtext
         * traegt seinen eigenen Feldnamen (\i;NAME=\i\v), die Reihenfolge
         * spielt fuer bestehende virtuelle Eingaenge also keine Rolle. Wer
         * mitten in der Liste einfuegt oder umbenennt, zwingt dagegen jeden
         * zum Neuimport - siehe den Kilometerstand in 0.9.11. */
        'ZUHAUSE'   => array('',    'SK_FELD.ZUHAUSE',    0, 1),
        'HEIMENTF'  => array('m',   'SK_FELD.HEIMENTF',   0, 20000000),
        'EMPFEHLUNG'=> array('',    'SK_FELD.EMPFEHLUNG', 0, 1),
        'AUSFAELLE' => array('',    'SK_FELD.AUSFAELLE',  0, 50),
        'ZAEHLER'   => array('',    'SK_FELD.ZAEHLER',    0, 999),
        'ALTER'     => array('s',   'SK_FELD.ALTER',      0, 999999),
        'OK'        => array('',    'SK_FELD.OK',         0, 1),
    );
}

/** Die Werte des Positions-Endpunkts. */
function sk_position_felder()
{
    return array(
        'BREITE'    => array('&deg;', 'SK_PFELD.BREITE',   -90, 90),
        'LAENGE'    => array('&deg;', 'SK_PFELD.LAENGE',   -180, 180),
        'ZUHAUSE'   => array('',      'SK_PFELD.ZUHAUSE',  0, 1),
        'HEIMENTF'  => array('m',     'SK_PFELD.HEIMENTF', 0, 20000000),
        'ALTER'     => array('s',     'SK_PFELD.ALTER',    0, 999999),
        'OK'        => array('',      'SK_PFELD.OK',       0, 1),
    );
}

/** Die Werte des Lade-Endpunkts. */
function sk_laden_felder()
{
    return array(
        'SOC'       => array('%',   'SK_LFELD.SOC',        0, 100),
        'LAEDT'     => array('',    'SK_LFELD.LAEDT',      0, 1),
        'LADEKW'    => array('kW',  'SK_LFELD.LADEKW',     0, 400),
        'TEMPO'     => array('km/h','SK_LFELD.TEMPO',      0, 1000),
        'RESTMIN'   => array('min', 'SK_LFELD.RESTMIN',    0, 10000),
        'LADEGR'    => array('%',   'SK_LFELD.LADEGR',     0, 100),
        'KABEL'     => array('',    'SK_LFELD.KABEL',      0, 1),
        'REICHWBAT' => array('km',  'SK_LFELD.REICHWBAT',  0, 2000),
        'ALTER'     => array('s',   'SK_LFELD.ALTER',      0, 999999),
        'OK'        => array('',    'SK_LFELD.OK',         0, 1),
    );
}

/** Die Werte des Wartungs-Endpunkts. */
function sk_wartung_felder()
{
    /* Vier Werte duerfen NEGATIV sein, und das ist der Sinn der Sache: eine
     * ueberfaellige Inspektion meldet Minustage und Minuskilometer. Eine
     * Untergrenze von 0 haette daraus in Loxone eine 0 gemacht - also
     * ausgerechnet die Meldung verschluckt, wegen der man hinsieht. */
    return array(
        'INSPTAGE'  => array('d',   'SK_WFELD.INSPTAGE', -3650, 3650),
        'INSPKM'    => array('km',  'SK_WFELD.INSPKM',   -100000, 1000000),
        'OELTAGE'   => array('d',   'SK_WFELD.OELTAGE',  -3650, 3650),
        'OELKM'     => array('km',  'SK_WFELD.OELKM',    -100000, 1000000),
        'KM'        => array('km',  'SK_WFELD.KM',        0, 2000000),
        'WARN'      => array('',    'SK_WFELD.WARN',      0, 50),
        'ALTER'     => array('s',   'SK_WFELD.ALTER',     0, 999999),
        'OK'        => array('',    'SK_WFELD.OK',        0, 1),
    );
}

/**
 * Der Suchtext eines Feldes fuer den virtuellen Eingang in Loxone.
 *
 * Das Semikolon gehoert DAZU. Ohne es nimmt Loxone die erste Fundstelle,
 * und die kann zu einem anderen Feld gehoeren, dessen Name auf diesen
 * endet. Gemessen an der Antwort des Wartungs-Endpunkts: das Muster
 * \iKM= trifft dort INSPKM=15000, nicht KM=48210. Beide Zahlen sehen aus
 * wie ein Kilometerstand - der Fehler faellt an keiner Stelle auf.
 *
 * Und es gibt diese Funktion, damit der Suchtext an EINER Stelle
 * entsteht. Vorher stand er fuenfmal woertlich da: einmal in der Vorlage
 * und viermal in der Oberflaeche. Vier Kopien einer Regel sind vier
 * Gelegenheiten, sie an einer Stelle zu vergessen.
 */
function sk_check($feld)
{
    return '\i;' . $feld . '=\i\v';
}

/**
 * Der Rechnername fuer die Adressen - an einer Stelle.
 */
function sk_host()
{
    return isset($_SERVER['HTTP_HOST']) && $_SERVER['HTTP_HOST'] !== ''
        ? preg_replace('/[^A-Za-z0-9\.\-:]/', '', (string) $_SERVER['HTTP_HOST'])
        : (gethostname() ?: 'loxberry');
}

/**
 * Ein Virtueller AUSGANG samt Befehlen.
 *
 * Nachbau aus LoxBerry::LoxoneTemplateBuilder wie sk_xml_virtual_in_http();
 * dasselbe CRLF, derselbe Tabulator, dieselbe Attributreihenfolge.
 *
 * Bis 0.9.12 gab es nur eine Eingangsvorlage. Die zwoelf Befehle musste jeder
 * von Hand abtippen - und fuenf davon nannte die Oberflaeche gar nicht.
 */
function sk_xml_virtual_out($kopf, $cmds)
{
    $crlf = "\r\n";
    $o = '<?xml version="1.0" encoding="utf-8"?>' . $crlf;
    $o .= '<VirtualOut ';
    $o .= 'HintText="" ';
    $o .= 'Title="' . sk_x($kopf['title']) . '" ';
    $o .= 'Comment="' . sk_x(isset($kopf['comment']) ? $kopf['comment'] : '') . '" ';
    $o .= 'Address="' . sk_x(isset($kopf['address']) ? $kopf['address'] : '') . '" ';
    $o .= 'CmdInit="" ';
    $o .= 'CloseAfterSend="true" ';
    $o .= 'CmdSep=""';
    $o .= '>' . $crlf;
    $o .= "\t" . '<Info templateType="3" minVersion="17010727"/>' . $crlf;
    foreach ($cmds as $c) {
        $o .= "\t" . '<VirtualOutCmd ';
        $o .= 'Title="' . sk_x($c['title']) . '" ';
        $o .= 'Comment="' . sk_x(isset($c['comment']) ? $c['comment'] : '') . '" ';
        $o .= 'CmdOnMethod="GET" ';
        $o .= 'CmdOffMethod="GET" ';
        $o .= 'CmdOn="' . sk_x($c['cmd']) . '" ';
        $o .= 'CmdOnHTTP="" ';
        $o .= 'CmdOnPost="" ';
        $o .= 'CmdOff="" ';
        $o .= 'CmdOffHTTP="" ';
        $o .= 'CmdOffPost="" ';
        $o .= 'CmdAnswer="" ';
        $o .= 'Analog="' . (empty($c['analog']) ? 'false' : 'true') . '" ';
        $o .= 'Repeat="0" ';
        $o .= 'RepeatRate="0" ';
        $o .= 'HintText=""';
        $o .= '/>' . $crlf;
    }
    $o .= '</VirtualOut>' . $crlf;
    return $o;
}

/** Welche Feldliste gehoert zu welcher Vorlagenart? */
function sk_felder_zu_art($art)
{
    switch ($art) {
        case 'laden':    return sk_laden_felder();
        case 'wartung':  return sk_wartung_felder();
        case 'position': return sk_position_felder();
        default:         return sk_status_felder();
    }
}

/**
 * Die anbietbaren Vorlagen. Bis 0.9.12 gab es genau eine - fuer 'status' -,
 * obwohl es fuer laden, wartung und position ebenso Felder und Suchtexte
 * gibt. Und der Knopf stand fest auf Fahrzeug 1: wer zwei Autos hat, sah die
 * Adresse fuer das zweite in der Tabelle und bekam die Datei dafuer nicht.
 */
function sk_vorlagenarten()
{
    return array(
        'status'   => 'LOX.ART_STATUS',
        'laden'    => 'LOX.ART_LADEN',
        'wartung'  => 'LOX.ART_WARTUNG',
        'position' => 'LOX.ART_POSITION',
        'aus'      => 'LOX.ART_AUS',
    );
}

/**
 * Der Name eines virtuellen Eingangs - aus DERSELBEN Rechnung wie in
 * sk_vorlage().
 *
 * ANGELEGT 31.08.2026 aus einem Befund: die Baustein-Liste im Reiter
 * "Einbindung in Loxone" fuehrte ihre zwoelf Namen als Sprachschluessel, die
 * Vorlage baut sie aus der Feldliste. Bei elf stimmten beide ueberein, beim
 * zwoelften nicht - INSPTAGE gehoert zur Wartungsvorlage, und die haengt ihre
 * Art in den Namen. Wer die Tabelle nachbaute, legte einen Baustein an, der
 * nie etwas empfaengt.
 *
 * Zwei Stellen, die dieselbe Zeichenkette zusammensetzen, laufen auseinander.
 * Hier ist es eine.
 */
function sk_eingangsname($feld, $art = 'status', $nummer = 1)
{
    $nummer = max(1, min(99, (int) $nummer));
    return 'SKODA_' . $nummer . ($art === 'status' ? '' : '_' . strtoupper($art))
         . '_' . $feld;
}

/** Vorlage fuer den Import in Loxone Config. Rueckgabe: array(name, inhalt) */
function sk_vorlage($nummer = 1, $art = 'status')
{
    $nummer = max(1, min(99, (int) $nummer));
    if (!array_key_exists($art, sk_vorlagenarten())) {
        $art = 'status';
    }
    if ($art === 'aus') {
        return sk_vorlage_vo($nummer);
    }
    $p = sk_paths();
    $host = sk_host();
    $token = sk_token();
    $cmds = array();
    foreach (sk_felder_zu_art($art) as $feld => $info) {
        // Der Text laeuft gleich durch sk_x() und wuerde dort ein zweites Mal
        // maskiert. Deshalb erst Auszeichnung entfernen und Entitaeten
        // aufloesen - sonst stuende in Loxone Config wortwoertlich
        // 'l&auml;dt' statt 'laedt'.
        $bedeutung = trim(strip_tags(html_entity_decode(sk_t($info[1]), ENT_QUOTES, 'UTF-8')));
        $einheit = trim(strip_tags(html_entity_decode($info[0], ENT_QUOTES, 'UTF-8')));
        /* Der Titel ist der NAME des virtuellen Eingangs in Loxone. Fuer die
         * Statusvorlage bleibt er woertlich, wie er seit 0.9.0 lautet -
         * SKODA_1_SOC und nicht SKODA_1_STATUS_SOC. Ihn zu erweitern haette
         * jede bestehende Anlage zum Neuimport und zum Umbenennen in jedem
         * Baustein gezwungen, und zwar fuer nichts.
         *
         * Die drei NEUEN Arten tragen ihn dagegen mit, und sie muessen es:
         * SOC steht sowohl im Status- als auch im Lade-Endpunkt, ALTER und OK
         * in allen vieren. Ohne die Art im Namen kollidierten sie. */
        /* Einheit und Grenzen wandern seit 0.9.14 MIT in die Vorlage. Die
         * Einheit stand bis dahin nur im Kommentar; in Loxone zeigte der
         * virtuelle Eingang deshalb eine nackte Zahl, und die Einheit fand
         * nur, wer den Kommentar aufklappte. Sie kommt aus derselben Zeile
         * der Feldliste wie der Klammerzusatz im Kommentar - zwei
         * Darstellungen, eine Quelle. */
        $cmds[] = array(
            'title'   => sk_eingangsname($feld, $art, $nummer),
            'comment' => $bedeutung . ($einheit !== '' ? ' [' . $einheit . ']' : ''),
            'check'   => sk_check($feld),
            'einheit' => $einheit,
            'min'     => isset($info[2]) ? $info[2] : null,
            'max'     => isset($info[3]) ? $info[3] : null,
        );
    }
    $adresse = 'http://' . $host . '/plugins/' . $p['plugin']
             . '/index.php?token=' . $token . '&aktion=' . $art . '&fahrzeug=' . $nummer;
    return array(
        'skoda_fahrzeug' . $nummer . ($art === 'status' ? '' : '_' . $art) . '.xml',
        sk_xml_virtual_in_http(array(
            'title'   => 'Skoda ' . $nummer . ($art === 'status' ? '' : ' ' . $art),
            'address' => $adresse,
            'polling' => '300',
            'comment' => 'Erzeugt vom LoxBerry-Plugin Skoda Connect (' . date('d.m.Y') . ')',
        ), $cmds),
    );
}

/** Der Virtuelle Ausgang mit allen schaltenden Befehlen. */
function sk_vorlage_vo($nummer = 1)
{
    $nummer = max(1, min(99, (int) $nummer));
    $p = sk_paths();
    $token = sk_token();
    $cmds = array();
    foreach (sk_befehle() as $aktion => $b) {
        $pfad = '/plugins/' . $p['plugin'] . '/index.php?token=' . $token
              . '&aktion=' . $aktion;
        if ($aktion !== 'abruf') {
            $pfad .= '&fahrzeug=' . $nummer;
        }
        /* Der Zusatzwert wird als <v> eingesetzt - so traegt Loxone den Wert
         * des Ausgangs ein. Er steht ZULETZT, damit die Adresse auch dann
         * lesbar bleibt, wenn jemand sie von Hand nacharbeitet. */
        if ($b[2] !== '') {
            $pfad .= '&' . $b[2] . '=<v>';
        }
        $cmds[] = array(
            'title'   => 'SKODA_' . $nummer . '_' . strtoupper($aktion),
            'comment' => trim(strip_tags(html_entity_decode(sk_t($b[1]), ENT_QUOTES, 'UTF-8'))),
            'cmd'     => $pfad,
            'analog'  => $b[2] !== '' ? 1 : 0,
        );
    }
    return array(
        'skoda_fahrzeug' . $nummer . '_befehle.xml',
        sk_xml_virtual_out(array(
            'title'   => 'Skoda ' . $nummer . ' Befehle',
            'address' => 'http://' . sk_host(),
            'comment' => 'Erzeugt vom LoxBerry-Plugin Skoda Connect (' . date('d.m.Y') . ')',
        ), $cmds),
    );
}

/* ==================================================================
 * Sprache (Pflicht: Deutsch und Englisch)
 *
 * Englisch ist die Rueckfallebene, nicht Deutsch: wer eine dritte Sprache
 * eingestellt hat, versteht eher Englisch. Deshalb muss language_en.ini immer
 * vollstaendig sein.
 *
 * Die Funktion setzt kein sk_paths() voraus, damit derselbe Block in jedes
 * Plugin passt. Der Pfad wird zweistufig gesucht:
 *   installiert: <home>/templates/plugins/<ordner>/lang
 *   Archiv:      <pluginwurzel>/templates/lang
 * ================================================================== */

function sk_sprache()
{
    $sprache = 'de';
    if (class_exists('LBSystem', false) && method_exists('LBSystem', 'lblanguage')) {
        $sprache = LBSystem::lblanguage();
    } elseif (getenv('LBLANG')) {
        $sprache = getenv('LBLANG');
    }
    $sprache = strtolower(substr((string) $sprache, 0, 2));
    return in_array($sprache, array('de', 'en'), true) ? $sprache : 'en';
}

/**
 * Text zu einem Schluessel 'ABSCHNITT.SCHLUESSEL'.
 *
 * Ist der Schluessel unbekannt, wird er selbst zurueckgegeben - so faellt beim
 * Durchsehen sofort auf, was fehlt, statt dass die Seite leer bleibt.
 */
function sk_t($schluessel)
{
    static $texte = null;
    if ($texte === null) {
        $home = getenv('LBHOMEDIR');
        if (!$home || !is_dir($home)) {
            foreach (array(lb_wurzel_ermitteln(), '/home/loxberry/loxberry') as $k) {
                if (is_dir($k)) {
                    $home = $k;
                    break;
                }
            }
        }
        $ordner = basename(dirname(__FILE__));
        $pfad = $home . '/templates/plugins/' . $ordner . '/lang';
        if (!is_dir($pfad)) {
            $pfad = dirname(dirname(dirname(__FILE__))) . '/templates/lang';
        }
        $texte = @parse_ini_file($pfad . '/language_' . sk_sprache() . '.ini', true, INI_SCANNER_RAW);
        if (!is_array($texte)) {
            $texte = array();
        }
        $rueck = @parse_ini_file($pfad . '/language_en.ini', true, INI_SCANNER_RAW);
        if (is_array($rueck)) {
            $texte = array_replace_recursive($rueck, $texte);
        }
        // INI_SCANNER_RAW liefert die Werte samt der Anfuehrungszeichen
        // zurueck, in die sie in der Datei stehen muessen. Die gehoeren nicht
        // in die Ausgabe.
        foreach ($texte as $ab => $paare) {
            if (!is_array($paare)) {
                continue;
            }
            foreach ($paare as $s => $w) {
                $texte[$ab][$s] = trim((string) $w, '"');
            }
        }
    }
    $teile = array_pad(explode('.', $schluessel, 2), 2, '');
    $a = $teile[0];
    $s = $teile[1];
    return isset($texte[$a][$s]) ? $texte[$a][$s] : $schluessel;
}


/**
 * Eine Sicherungsdatei einlesen - und dabei NICHTS durchgehen lassen.
 *
 * Die sieben Punkte aus REGELN_2, und der wichtigste ist der dritte: eine
 * halb gueltige Datei ueberschreibt GAR NICHTS. Wer eine Sicherung
 * zurueckspielt, will entweder den ganzen Stand oder gar keinen - eine zur
 * Haelfte uebernommene Konfiguration ist schlimmer als die alte, und man
 * sieht es ihr nicht an.
 *
 * Unbekannte Schluessel sind eine Beanstandung, kein stiller Verlust: sie
 * stammen aus einer anderen Fassung oder einem anderen Plugin.
 *
 * Rueckgabe: array(Konfiguration|null, Beanstandungen[], uebernommene Werte).
 */
function sk_sicherung_lesen($roh)
{
    $mangel = array();
    $daten = json_decode((string) $roh, true);
    if (!is_array($daten)) {
        return array(null, array(sk_t('EINST.SICH_KEIN_JSON')), 0, null);
    }
    $neu = sk_vorgaben();
    $bekannt = array_keys($neu);
    $anzahl = 0;
    $zugang = null;

    foreach ($daten as $k => $w) {
        /* ---- 1. Der eigene Kopf ----
         * Schluessel mit fuehrendem Unterstrich sind Beschriftung, keine
         * Einstellung: _hinweis, _plugin, _fassung, _stand. Sie werden
         * uebersprungen und NICHT als fremd beanstandet - sonst wiese das
         * Plugin seine eigene Sicherungsdatei ab. */
        if ((string) $k !== '' && $k[0] === '_') {
            continue;
        }

        /* ---- 2. Die Zugangsdaten ----
         * Sie stehen nur in der Datei, wenn beim Sichern der Haken gesetzt
         * war. Sie gehoeren NICHT in die Konfiguration, sondern in ihre
         * eigene Datei mit Rechten 0600 - deshalb hier herausgenommen und dem
         * Aufrufer gesondert zurueckgegeben. */
        if ((string) $k === 'zugang' && is_array($w)) {
            $email = isset($w['email']) && !is_array($w['email']) ? trim((string) $w['email']) : '';
            $pw = isset($w['passwort']) && !is_array($w['passwort']) ? (string) $w['passwort'] : '';
            if ($email !== '' && !filter_var($email, FILTER_VALIDATE_EMAIL)) {
                $mangel[] = sprintf(sk_t('EINST.SICH_WERT'), 'zugang.email');
            } elseif (strlen($pw) > 256) {
                $mangel[] = sprintf(sk_t('EINST.SICH_WERT'), 'zugang.passwort');
            } else {
                $zugang = array('email' => $email, 'passwort' => $pw);
                $anzahl++;
            }
            continue;
        }

        /* ---- 3. Unbekannte Schluessel ----
         * Eine Beanstandung, kein stiller Verlust: sie stammen aus einer
         * anderen Fassung oder aus einem anderen Plugin. */
        if (!in_array($k, $bekannt, true)) {
            $mangel[] = sprintf(sk_t('EINST.SICH_FREMD'),
                                 htmlspecialchars((string) $k, ENT_QUOTES, 'UTF-8'));
            continue;
        }

        /* ---- 4. Und jetzt der WERT ----
         *
         * DAS IST DIE HAELFTE, DIE BIS 0.9.12 GEFEHLT HAT. Geprueft wurde nur
         * der Schluessel; der Wert wurde unbesehen uebernommen. Gemessen mit
         * einer von Hand gebauten Datei gingen "abc" als Takt, -99 als
         * Stammdatenzyklus, ein Feld im Verlaufsfeld, ein Objekt im
         * Sitzungsfeld und ein Themenpraefix mit Leerzeichen glatt durch.
         *
         * ABGEWIESEN, NICHT GEKAPPT: beim Speichern ueber das Formular waere
         * Kappen vertretbar, denn der Bediener sieht das Ergebnis sofort. Bei
         * einer Datei saehe niemand, dass aus 99999 eine 3600 wurde. */
        list($ok, $rein) = sk_wert_pruefen($k, $w);
        if (!$ok) {
            $mangel[] = sprintf(sk_t('EINST.SICH_WERT'),
                                 htmlspecialchars((string) $k, ENT_QUOTES, 'UTF-8'));
            continue;
        }
        $neu[$k] = $rein;
        $anzahl++;
    }

    /* Die Grenzen, die kein einzelner Wert kennt. */
    if (!$mangel && $neu['temp_min'] > $neu['temp_max']) {
        $mangel[] = sk_t('EINST.FEHLER_TEMP_TAUSCH');
    }
    if ($anzahl === 0) {
        $mangel[] = sk_t('EINST.SICH_LEER');
    }
    return array($mangel ? null : $neu, $mangel, $anzahl, $mangel ? null : $zugang);
}

/**
 * Die Sicherungsdatei bauen.
 *
 * Drei Dinge, die bis 0.9.12 fehlten:
 *
 * 1. EIN LESBARER KOPF MIT DATUM. Wer die Datei in einem Jahr findet, muss
 *    erkennen koennen, was sie ist.
 * 2. GESIEBT AUS DEN VORGABEN, nicht die gelesene Konfiguration ausgegeben.
 *    Sonst kann ein Schluessel in die Datei geraten, den die Leseseite
 *    danach ablehnt - das Plugin verweigerte seine eigene Sicherung. Heute
 *    gibt es keinen solchen Rest; die Bauart liess ihn nur zu.
 * 3. DIE ZUGANGSDATEN, wenn der Bediener es will. Der Warntext am Knopf sagte
 *    bis 0.9.12 "Die Datei enthaelt Ihre Zugangsdaten" - und das stimmte
 *    nicht: sk_config() kennt weder E-Mail noch Passwort, die wohnen in
 *    zugang.json. Damit war der erklaerte Zweck, der Umzug auf einen zweiten
 *    LoxBerry, nicht erfuellbar: dort stuenden alle Felder richtig, und das
 *    Plugin kaeme trotzdem nicht an die Anlage. Jetzt entscheidet der
 *    Bediener, und der Dateiname sagt es mit.
 */
function sk_sicherung_schreiben($mit_zugang = false)
{
    $cfg = sk_config();
    $aus = array(
        '_hinweis' => 'Einstellungen des LoxBerry-Plugins Skoda Connect. Enthaelt das '
                    . 'Aktionstoken dieser Anlage'
                    . ($mit_zugang ? ' UND die Zugangsdaten des MySkoda-Kontos' : '')
                    . ' - wie ein Passwort behandeln.',
        '_plugin'  => 'skodaconnect',
        '_fassung' => sk_fassung(),
        '_stand'   => date('Y-m-d H:i:s'),
    );
    foreach (array_keys(sk_vorgaben()) as $k) {
        $aus[$k] = isset($cfg[$k]) ? $cfg[$k] : '';
    }
    if ($mit_zugang) {
        $z = sk_json_lesen(sk_paths()['zugang']);
        $aus['zugang'] = array(
            'email'    => isset($z['email']) ? (string) $z['email'] : '',
            'passwort' => isset($z['passwort']) ? (string) $z['passwort'] : '',
        );
    }
    $js = json_encode($aus, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    return $js === false ? '' : $js;
}
