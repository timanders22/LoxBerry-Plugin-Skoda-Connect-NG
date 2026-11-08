<?php
/**
 * Skoda Connect - Ansage auf Zuruf des Abrufdienstes (Nr. 36 b, Stufe 2, seit 0.9.30)
 *
 * Aufruf:  php sk_ansage.php <Pluginordner>      (Auftrag als JSON auf der Standardeingabe)
 *
 * Der Dienst bin/skoda.py ist in Python geschrieben; die gemeinsame Sprachausgabe
 * der Plugins dieses Hauses (sprachausgabe.php neben sk_lib.php) gibt es nur in
 * PHP. Diese Bruecke nimmt einen Anlass entgegen, baut den Satz aus der
 * Sprachdatei (Abschnitt SK_ANSAGE) und spricht ihn mit ansage_cli() ueber die
 * eingestellte Ausgabeart (Block tts der Konfiguration, ab Werk aus).
 *
 * Der Auftrag kommt auf der STANDARDEINGABE, nie auf der Kommandozeile - die
 * sieht jeder in der Prozessliste:
 *   {"anlass": "laden_fertig", "nr": 1, "name": "Enyaq", "soc": 80, "grenze": 80}
 * Angenommen werden nur die Anlaesse aus sk_ansage_anlaesse(); der Satz entsteht
 * hier, der Dienst schickt keinen freien Text.
 *
 * Antwort: EINE Zeile ohne Text und ohne Token, z. B.
 *   ANSAGE;STAND=1;ART=musicserver;KENNUNG=-;HTTP=200;ZEICHEN=39
 * Mit weiteren Ausgabezielen (seit 0.9.34, Stamm 1.2.1, Welle Mehrfach-Ziele) sprechen alle gleichzeitig, jedes
 * hoechstens 'frist' = 20 s (sk_ansage_k()); die Zeile traegt dann zusaetzlich ;ZIELE=x/y - der Dienst liest nur
 * die Felder, die er kennt (B8).
 * Rueckgabewert wie ansage_cli(): 0 gesendet, 1 gescheitert, 3 nichts gesendet
 * ohne Fehler (Ausgabe aus), 2 Aufruf falsch. 1 auch, wenn die Bibliothek fehlt.
 *
 * Der Pluginordner wird mitgegeben wie bei den *_notify.php-Stuecken anderer
 * Linien: dem Dienst koennen die LoxBerry-Umgebungsvariablen fehlen, und bei
 * einer Zweitinstallation heisst der Ordner skodaconnect_01.
 */

error_reporting(E_ALL & ~E_DEPRECATED & ~E_NOTICE);

if (PHP_SAPI !== 'cli') {
    http_response_code(403);
    echo "ANSAGE;OK=0;GRUND=KEIN_ENDPUNKT\n";
    exit;
}

/* Den LoxBerry-Wurzelordner ohne festen Systempfad bestimmen - dieselbe Regel
 * wie sk_lib.php. DIESER BLOCK STEHT VOR SEINEM AUFRUF: PHP zieht Funktionen in
 * einem if-Block nicht vor. */
if (!function_exists('lb_wurzel_ermitteln')) {
    function lb_wurzel_ermitteln()
    {
        $d = __DIR__;
        for ($i = 0; $i < 8; $i++) {
            if (is_dir($d . '/config/plugins') && is_dir($d . '/data/plugins')
                && is_file($d . '/config/system/general.json')) {
                return $d;
            }
            $eltern = dirname($d);
            if ($eltern === $d) { break; }
            $d = $eltern;
        }
        return '';
    }
}

$sk_home = getenv('LBHOMEDIR');
// 0.9.43: auch general.json, wie lb_wurzel_ermitteln() und bb_wurzel_ok() (Regeln/06).
if (!$sk_home || !is_dir($sk_home . '/config/plugins') || !is_dir($sk_home . '/data/plugins')
    || !is_file($sk_home . '/config/system/general.json')) {
    $sk_home = lb_wurzel_ermitteln();
}
$sk_paket = isset($argv[1]) ? preg_replace('/[^A-Za-z0-9_\-]/', '', (string) $argv[1]) : '';
if ($sk_paket === '') {
    $sk_paket = preg_replace('/[^A-Za-z0-9_\-]/', '', basename(rtrim((string) getenv('LBPPLUGINDIR'), '/')));
}
if ($sk_paket === '') {
    $sk_paket = 'skodaconnect';
}

/* Die Bibliothek: installiert unter <home>/webfrontend/html/plugins/<ordner>/,
 * im Archiv unter ../webfrontend/html/. */
$sk_lib = '';
foreach (array(
    $sk_home ? $sk_home . '/webfrontend/html/plugins/' . $sk_paket . '/sk_lib.php' : '',
    dirname(__DIR__) . '/webfrontend/html/sk_lib.php',
) as $sk_kandidat) {
    if ($sk_kandidat !== '' && is_file($sk_kandidat)) {
        $sk_lib = $sk_kandidat;
        break;
    }
}
if ($sk_lib === '') {
    fwrite(STDERR, "sk_lib.php nicht gefunden - es wurde nichts angesagt.\n");
    echo "ANSAGE;STAND=0;KENNUNG=BIBLIOTHEK\n";
    exit(1);
}
/* Die Sprache des LoxBerry (Base.Lang) kennt erst LBSystem. */
if ($sk_home && is_file($sk_home . '/libs/phplib/loxberry_system.php')) {
    require_once $sk_home . '/libs/phplib/loxberry_system.php';
}
require_once $sk_lib;

$sk_roh = stream_get_contents(STDIN);
$sk_d = is_string($sk_roh) && strlen($sk_roh) <= 4096 ? json_decode($sk_roh, true) : null;
$sk_anlaesse = sk_ansage_anlaesse();
$sk_zahl = function ($w) {
    if ($w === null) { return null; }
    if (!is_int($w) && !is_float($w)) { return false; }
    $i = (int) round((float) $w);
    return ($i >= 0 && $i <= 100) ? $i : false;
};
$sk_ok = is_array($sk_d)
    && isset($sk_d['anlass']) && is_string($sk_d['anlass']) && isset($sk_anlaesse[$sk_d['anlass']])
    && isset($sk_d['nr']) && is_int($sk_d['nr']) && $sk_d['nr'] >= 0 && $sk_d['nr'] <= 99
    && (!isset($sk_d['name']) || is_string($sk_d['name']));
$sk_soc = $sk_ok ? $sk_zahl(isset($sk_d['soc']) ? $sk_d['soc'] : null) : false;
$sk_grenze = $sk_ok ? $sk_zahl(isset($sk_d['grenze']) ? $sk_d['grenze'] : null) : false;
if (!$sk_ok || $sk_soc === false || $sk_grenze === false) {
    fwrite(STDERR, "Auftrag fehlt, ist kein JSON oder nennt einen unbekannten Anlass.\n");
    echo "ANSAGE;STAND=0;KENNUNG=AUFRUF\n";
    exit(2);
}
/* Der Fahrzeugname kommt aus dem Konto; nur Steuerzeichen fallen weg, und er
 * wird auf 60 Zeichen begrenzt - er wird gesprochen, nicht gespeichert. */
$sk_name = isset($sk_d['name']) ? trim((string) preg_replace('/[\x00-\x1F\x7F]/u', ' ', $sk_d['name'])) : '';
if (preg_match('//u', $sk_name) !== 1) {
    $sk_name = '';
}
if (function_exists('mb_substr')) {
    $sk_name = mb_substr($sk_name, 0, 60, 'UTF-8');
} elseif (strlen($sk_name) > 60) {
    $sk_name = '';
}

$sk_text = sk_ansage_satz($sk_d['anlass'], $sk_d['nr'], $sk_name, $sk_soc, $sk_grenze);
/* Stamm 1.3.2 (Welle S4): Sperre, Nachtruhe und Schalter "Ansagen aus" stehen im Stamm. Die Bruecke legt nur hin, gesprochen wird in einem eigenen
 * Vorgang: Der Dienst wartet nicht auf Lautsprecher. Die Antwortzeile bleibt in der Form: STAND=1 heisst hier hingelegt. Rueckgabe 0 hingelegt, 3 Ausgabe aus. */
$sk_kf = sk_config();
$sk_ausgabe = sk_tts_von($sk_kf);
if ((string) $sk_ausgabe['mode'] === 'aus') {
    echo "ANSAGE;STAND=-1;ART=aus;KENNUNG=AUS;HTTP=0;ZEICHEN=0\n";
    exit(3);
}
sk_ansage_token_pflegen($sk_kf);
sk_ansage_legen(array(array('schluessel' => $sk_d['anlass'] . '|' . $sk_d['nr'], 'text' => $sk_text)));
// 0.9.43: Zeichen wie das Sprachmodul zaehlt (ansage_zeichen(), UTF-8) - bis 0.9.42 Bytes; ein Umlaut zaehlte doppelt.
echo 'ANSAGE;STAND=1;ART=gelegt;KENNUNG=GELEGT;HTTP=0;ZEICHEN=' . ansage_zeichen((string) $sk_text) . "\n";
exit(0);
