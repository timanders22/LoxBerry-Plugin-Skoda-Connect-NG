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
        'steuerung_ein'  => 0,
        'temp_min'       => 16,
        'temp_max'       => 29,
        'verlauf_tage'   => 8,
        'sitzung_merken' => 1,
        'aktionstoken'   => '',
        'wartezeit'      => 8,
    );
}

function sk_json_lesen($pfad)
{
    if (!is_file($pfad)) {
        return array();
    }
    $d = json_decode((string) @file_get_contents($pfad), true);
    return is_array($d) ? $d : array();
}

function sk_config()
{
    $p = sk_paths();
    // Selbstheilung: fehlende oder leere Konfiguration aus der Sicherung holen.
    $roh = is_file($p['config']) ? trim((string) @file_get_contents($p['config'])) : '';
    if (($roh === '' || $roh === '{}') && is_file($p['sicherung'])) {
        @mkdir($p['configdir'], 0775, true);
        @copy($p['sicherung'], $p['config']);
    }
    $cfg = sk_json_lesen($p['config']);
    return array_merge(sk_vorgaben(), $cfg);
}

function sk_config_speichern($cfg)
{
    $p = sk_paths();
    if (!is_dir($p['configdir'])) {
        @mkdir($p['configdir'], 0775, true);
    }
    $json = json_encode($cfg, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    // json_encode liefert bei ungueltigem UTF-8 false, und file_put_contents
    // schriebe dann eine Datei mit NULL Bytes - und meldete das als Erfolg.
    if ($json === false || @file_put_contents($p['config'], $json) === false) {
        return false;
    }
    @copy($p['config'], $p['sicherung']);
    return true;
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
        'spin_laenge' => isset($z['spin']) ? strlen((string) $z['spin']) : 0,
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
function sk_zugang_speichern($email, $passwort, $spin)
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
        'spin'     => ($spin !== null && $spin !== '')
                      ? $spin
                      : (isset($alt['spin']) ? $alt['spin'] : ''),
    );
    $json = json_encode($neu, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    // json_encode liefert bei ungueltigem UTF-8 false, und file_put_contents
    // schriebe dann eine LEERE Datei - hier waeren das die Zugangsdaten.
    $ok = $json !== false && @file_put_contents($p['zugang'], $json) !== false;
    @chmod($p['zugang'], 0600);
    return $ok;
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

/** Alter des Abbilds in Sekunden, oder -1 wenn es keines gibt. */
function sk_alter()
{
    $l = sk_loxone();
    return isset($l['ts']) ? max(0, time() - (int) $l['ts']) : -1;
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
    // Nummernrecycling ausschliessen: der Prozess muss unser Skript sein.
    $cmd = (string) @file_get_contents('/proc/' . $pid . '/cmdline');
    return strpos($cmd, 'skoda.py') !== false ? $pid : 0;
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
        return array(0, 'Unbekannter Befehl.');
    }
    $skript = sk_paths()['bindir'] . '/dienst.sh';
    if (!is_file($skript)) {
        return array(0, 'dienst.sh nicht gefunden: ' . $skript);
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
        return "[FEHL] Die virtuelle Python-Umgebung oder skoda.py fehlt.\n"
             . "       Erwartet: " . $py . "\n"
             . "                 " . $skript . "\n"
             . "       Abhilfe: Plugin neu installieren; die Installation legt beides an.";
    }
    $ausgabe = array();
    @exec(escapeshellarg($py) . ' ' . escapeshellarg($skript) . ' --selbsttest 2>&1', $ausgabe);
    return implode("\n", $ausgabe);
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
    $wartezeit = max(0, min(30, (int) $wartezeit));

    $ordner = $p['datadir'] . '/befehle';
    if (!is_dir($ordner) && !@mkdir($ordner, 0775, true) && !is_dir($ordner)) {
        return array(0, 'Der Ordner fuer die Warteschlange liess sich nicht anlegen: ' . $ordner);
    }
    $kennung = bin2hex(random_bytes(8));
    $datei = $ordner . '/' . $kennung . '.json';
    $tmp = $datei . '.tmp';
    if (@file_put_contents($tmp, json_encode($befehl)) === false || !@rename($tmp, $datei)) {
        @unlink($tmp);
        return array(0, 'Der Befehl liess sich nicht ablegen: ' . $datei);
    }
    $antwort = $p['datadir'] . '/antworten/' . $kennung . '.json';
    for ($i = 0; $i < $wartezeit * 10; $i++) {
        if (is_file($antwort)) {
            $a = sk_json_lesen($antwort);
            return array((int) (isset($a['ok']) ? $a['ok'] : 0),
                         (string) (isset($a['meldung']) ? $a['meldung'] : ''));
        }
        usleep(100000);
    }
    return array(2, 'Eingereiht, aber der Dienst hat innerhalb von ' . $wartezeit . ' s nicht geantwortet.');
}

/* ---------------- Verlauf ---------------- */

/** Messpunkte eines Tages: Array von array(ts, fuellstand, reichweite). */
function sk_verlauf_lesen($nummer, $tag = '')
{
    if ($tag === '') {
        $tag = date('Ymd');
    }
    $f = sk_paths()['datadir'] . '/verlauf/fahrzeug' . (int) $nummer . '_' . $tag . '.csv';
    $out = array();
    if (is_file($f)) {
        foreach (file($f, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) ?: array() as $zeile) {
            $c = explode(';', $zeile);
            if (count($c) >= 2) {
                $out[] = array((int) $c[0], (float) $c[1], isset($c[2]) && $c[2] !== '' ? (float) $c[2] : 0);
            }
        }
    }
    return $out;
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
    $leer = array('gefunden' => 0, 'autostart' => 0, 'udpport' => 0,
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
        'udpport'    => (int) $hol('Udpinport', 'udpinport'),
        'broker'     => (string) $hol('Brokerhost', 'brokerhost'),
        'brokerport' => (string) $hol('Brokerport', 'brokerport'),
        'websocket'  => (string) $hol('Websocketport', 'websocketport'),
    );
}

/** Alle Themen, die der Dienst veroeffentlicht, mit ihrer Bedeutung. */
function sk_mqtt_themen()
{
    return array(
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
    );
}

/* ==================================================================
 * Loxone-Vorlagen
 *
 * Nachbau der Bausteine aus LoxBerry::LoxoneTemplateBuilder; das Modul gibt es
 * nur in Perl. Attributreihenfolge, CRLF als Zeilenende und der Tabulator vor
 * den Kindelementen entsprechen dem Original. Wortgleich uebernommen aus
 * LoxBerry-Plugin-APC-UPS-1.0.0 (ap_xml_virtual_in_http) - nicht neu
 * geschrieben, weil die Fassung dort geprueft ist.
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
    $o .= 'Title="' . sk_x($kopf['title']) . '" ';
    $o .= 'Comment="' . sk_x(isset($kopf['comment']) ? $kopf['comment'] : '') . '" ';
    $o .= 'Address="' . sk_x(isset($kopf['address']) ? $kopf['address'] : '') . '" ';
    $o .= 'PollingTime="' . sk_x(isset($kopf['polling']) ? $kopf['polling'] : '60') . '"';
    $o .= '>' . $crlf;
    foreach ($cmds as $c) {
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
        $o .= 'MinVal="-2147483647" ';
        $o .= 'MaxVal="2147483647"';
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
 */
function sk_status_felder()
{
    return array(
        'SOC'       => array('%',   'SK_FELD.SOC'),
        'TANK'      => array('%',   'SK_FELD.TANK'),
        'REICHW'    => array('km',  'SK_FELD.REICHW'),
        'KM'        => array('km',  'SK_FELD.KM'),
        'VERR'      => array('',    'SK_FELD.VERR'),
        'TUEREN'    => array('',    'SK_FELD.TUEREN'),
        'FENSTER'   => array('',    'SK_FELD.FENSTER'),
        'KOFFER'    => array('',    'SK_FELD.KOFFER'),
        'HAUBE'     => array('',    'SK_FELD.HAUBE'),
        'LICHT'     => array('',    'SK_FELD.LICHT'),
        'KLIMA'     => array('',    'SK_FELD.KLIMA'),
        'ZIELTEMP'  => array('&deg;C', 'SK_FELD.ZIELTEMP'),
        'AUSSEN'    => array('&deg;C', 'SK_FELD.AUSSEN'),
        'WARN'      => array('',    'SK_FELD.WARN'),
        'ERREICH'   => array('',    'SK_FELD.ERREICH'),
        'BEWEG'     => array('',    'SK_FELD.BEWEG'),
        'ZUEND'     => array('',    'SK_FELD.ZUEND'),
        'ALTER'     => array('s',   'SK_FELD.ALTER'),
        'OK'        => array('',    'SK_FELD.OK'),
    );
}

/** Die Werte des Lade-Endpunkts. */
function sk_laden_felder()
{
    return array(
        'SOC'       => array('%',   'SK_LFELD.SOC'),
        'LAEDT'     => array('',    'SK_LFELD.LAEDT'),
        'LADEKW'    => array('kW',  'SK_LFELD.LADEKW'),
        'TEMPO'     => array('km/h','SK_LFELD.TEMPO'),
        'RESTMIN'   => array('min', 'SK_LFELD.RESTMIN'),
        'LADEGR'    => array('%',   'SK_LFELD.LADEGR'),
        'KABEL'     => array('',    'SK_LFELD.KABEL'),
        'REICHWBAT' => array('km',  'SK_LFELD.REICHWBAT'),
        'OK'        => array('',    'SK_LFELD.OK'),
    );
}

/** Die Werte des Wartungs-Endpunkts. */
function sk_wartung_felder()
{
    return array(
        'INSPTAGE'  => array('d',   'SK_WFELD.INSPTAGE'),
        'INSPKM'    => array('km',  'SK_WFELD.INSPKM'),
        'OELTAGE'   => array('d',   'SK_WFELD.OELTAGE'),
        'OELKM'     => array('km',  'SK_WFELD.OELKM'),
        'KM'        => array('km',  'SK_WFELD.KM'),
        'WARN'      => array('',    'SK_WFELD.WARN'),
        'OK'        => array('',    'SK_WFELD.OK'),
    );
}

/** Vorlage fuer den Import in Loxone Config. Rueckgabe: array(name, inhalt) */
function sk_vorlage($nummer = 1)
{
    $p = sk_paths();
    $host = isset($_SERVER['HTTP_HOST']) && $_SERVER['HTTP_HOST'] !== ''
        ? preg_replace('/[^A-Za-z0-9\.\-:]/', '', (string) $_SERVER['HTTP_HOST'])
        : (gethostname() ?: 'loxberry');
    $token = sk_token();
    $cmds = array();
    foreach (sk_status_felder() as $feld => $info) {
        // Der Text laeuft gleich durch sk_x() und wuerde dort ein zweites Mal
        // maskiert. Deshalb erst Auszeichnung entfernen und Entitaeten
        // aufloesen - sonst stuende in Loxone Config wortwoertlich
        // 'l&auml;dt' statt 'laedt'.
        $bedeutung = trim(strip_tags(html_entity_decode(sk_t($info[1]), ENT_QUOTES, 'UTF-8')));
        $einheit = trim(strip_tags(html_entity_decode($info[0], ENT_QUOTES, 'UTF-8')));
        $cmds[] = array(
            'title'   => 'SKODA_' . $nummer . '_' . $feld,
            'comment' => $bedeutung . ($einheit !== '' ? ' [' . $einheit . ']' : ''),
            'check'   => '\i' . $feld . '=\i\v',
        );
    }
    $adresse = 'http://' . $host . '/plugins/' . $p['plugin']
             . '/index.php?token=' . $token . '&aktion=status&fahrzeug=' . (int) $nummer;
    return array(
        'skoda_fahrzeug' . (int) $nummer . '.xml',
        sk_xml_virtual_in_http(array(
            'title'   => 'Skoda ' . (int) $nummer,
            'address' => $adresse,
            'polling' => '300',
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
