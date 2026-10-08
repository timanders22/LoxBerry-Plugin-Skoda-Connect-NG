<?php
/**
 * Skoda Connect - Bedienoberflaeche
 *
 * Reiter: Einstellungen | MQTT | Einbindung in Loxone | Test | Logdateien
 *
 * Diese Datei ist NUR Oberflaeche. Der Datenabruf laeuft im Dienst
 * (bin/skoda.py), der Miniserver spricht mit webfrontend/html/index.php.
 * Ein Plugin, das den Abruf hier erledigt, ist falsch gebaut - auch wenn es
 * funktioniert.
 *
 * Praefix 'sk_', weil LBWeb::lbheader() SDK-Globale setzt (unter anderem $cfg
 * aus der general.json als stdClass) und gleichnamige Plugin-Variablen
 * ueberschreiben wuerde.
 * Kompatibel mit PHP 7.4 und PHP 8.x (LoxBerry 3.x/4.x).
 */

error_reporting(E_ALL & ~E_DEPRECATED & ~E_NOTICE);

/* Bibliothek einbinden. Sie liegt unter webfrontend/html/, weil der
 * Miniserver-Endpunkt sie ebenfalls braucht - installiert unter
 * .../html/plugins/<ordner>/, im Archiv unter ../html/. */
$sk_gefunden = false;
foreach (array(
    // installiert: <home>/webfrontend/htmlauth/plugins/<ordner>  ->
    //              <home>/webfrontend/html/plugins/<ordner>
    dirname(dirname(__DIR__)) . '/html/plugins/' . basename(__DIR__) . '/sk_lib.php',
    dirname(dirname(dirname(__DIR__))) . '/html/plugins/' . basename(__DIR__) . '/sk_lib.php',
    // im Archiv: <plugin>/webfrontend/htmlauth -> <plugin>/webfrontend/html
    dirname(__DIR__) . '/html/sk_lib.php',
) as $sk_kandidat) {
    if (is_file($sk_kandidat)) {
        require_once $sk_kandidat;
        $sk_gefunden = true;
        break;
    }
}
if (!$sk_gefunden) {
    echo '<p><b>Fehler:</b> sk_lib.php wurde nicht gefunden. Bitte das Plugin neu installieren.</p>';
    exit;
}
require_once __DIR__ . '/sk_test.php';

$sk_p = sk_paths();
if ($sk_p['home'] !== '' && is_file($sk_p['home'] . '/libs/phplib/loxberry_system.php')) {
    require_once $sk_p['home'] . '/libs/phplib/loxberry_system.php';
    require_once $sk_p['home'] . '/libs/phplib/loxberry_web.php';
}

/* EINE Quelle fuer Reihenfolge, Beschriftung und Positivliste. Bis 0.9.1
 * standen die Reiternamen an drei Stellen: in diesem Muster, in der
 * Reiterleiste und in den fuenf Flaechen-ids. Wer einen Reiter ergaenzt und
 * eine davon vergisst, bekommt keinen Fehler, sondern eine Seite, die nach
 * dem Absenden auf Einstellungen zurueckspringt. */
$sk_reiter = array(
    'settings' => sk_t('REITER.EINSTELLUNGEN'),
    'mqtt'     => 'MQTT',
    'loxone'   => sk_t('REITER.LOXONE'),
    'test'     => sk_t('REITER.TEST'),
    'log'      => sk_t('REITER.LOG'),
);
$sk_muster = '/^tab-(' . implode('|', array_keys($sk_reiter)) . ')$/';
$sk_tab = 'tab-settings';
if (preg_match($sk_muster, sk_post('activetab'))) {
    $sk_tab = sk_post('activetab');
} elseif (isset($_GET['form']) && preg_match($sk_muster, 'tab-' . (string) $_GET['form'])) {
    $sk_tab = 'tab-' . (string) $_GET['form'];
}

/* Die Selbstheilung der Konfiguration - HIER, nicht in der Lesefunktion.
 *
 * Sie stand bis 0.9.13 in sk_config_lage() und lief damit auch fuer den
 * unangemeldeten Endpunkt: ein Aufruf mit falschem Token legte den
 * Konfigordner an und spielte die Zweitschrift samt altem Aktionstoken
 * zurueck. Der Bediener ist hier angemeldet, und er sieht das Ergebnis
 * sofort auf der Seite - das ist der richtige Ort dafuer. */
/* ZUERST ABER: laeuft gerade eine Aktualisierung dieses Plugins?
 *
 * Zwischen dem Kopieren der neuen Dateien und postinstall.sh liegt fast eine
 * Minute (Regeln/06). In dieser Zeit ist config/plugins/<ordner>/ geloescht,
 * die Seite aber erreichbar. Am 18.09.2026 in WSL gemessen
 * (Pruefung-Skoda-Connect-NG-0.9.23/messe_luecke.sh, Fall 5): das Formular
 * des Reiters Einstellungen, in der Luecke unveraendert abgesendet, schrieb
 * zugang.json mit leerem Benutzernamen und leerem Passwort neu.
 * postinstall.sh haelt eine gefuellte Datei fuer gewollt und spielt die
 * Zweitschrift nicht zurueck - das Passwort war danach weg.
 *
 * Solange die Marke aus preupgrade.sh gilt, zeigt die Seite deshalb nur
 * einen Hinweis: sie heilt nichts, sie erzeugt kein Aktionstoken, und sie
 * nimmt kein Formular an - auch keines, das vor der Aktualisierung
 * ausgeliefert wurde. Die Entscheidung zu sperren ist eine Messung, keine
 * Regel (Regeln/06; Sprachsteuerung 0.11.7 sperrt aus demselben Grund
 * NICHT: dort ging in der Luecke nichts verloren). */
$sk_upgrade = sk_upgrade_laeuft();
if ($sk_upgrade) {
    if (class_exists('LBWeb', false)) {
        LBWeb::lbheader('Skoda Connect', 'https://wiki.loxberry.de/', 'help.html');
    }
    echo '<div class="sm-wrap" style="max-width:980px;margin:0 auto;'
       . 'font-family:-apple-system,\'Segoe UI\',Roboto,sans-serif;color:#333;">' . "\n"
       . '<h1>Skoda Connect</h1>' . "\n"
       . '<div style="border:1px solid #e0c060;border-left:4px solid #e0a020;'
       . 'background:#fdf8e8;border-radius:6px;padding:12px 14px;margin:12px 0;">'
       . '<b>' . sk_e(sk_t('HINWEIS.UPGRADE_LAEUFT')) . '</b> '
       . sk_e(sk_t('HINWEIS.UPGRADE_LAEUFT_TEXT')) . '</div>' . "\n"
       . '</div>' . "\n";
    if (class_exists('LBWeb', false)) {
        LBWeb::lbfooter();
    }
    exit;
}

/* SEIT DEM DURCHGANG 01.10.2026 MIT MELDUNG (C8). Bis 0.9.28 wurde der
 * Rueckgabewert verworfen: eine beschaedigte skoda.json wurde still durch die
 * Zweitschrift ersetzt oder - ohne Zweitschrift - still auf Werkseinstellung
 * mit neuem Token gesetzt (gemessen, Oberflaechenbericht K1/K2). Jetzt steht
 * auf der Seite, was geschah; reist ueber die Einmalmeldung, wenn es bei einem
 * POST geschieht. */
$sk_heil = sk_config_heilen();
$sk_heilkasten = array();
if ($sk_heil['aktion'] === 'zweitschrift') {
    $sk_heilkasten[] = array('sm-warnung', sprintf(sk_t('ALLG.KONFIG_AUS_ZWEITSCHRIFT'),
        sk_e(sk_t('ALLG.LAGE_' . strtoupper($sk_heil['lage'])))));
} elseif ($sk_heil['aktion'] === 'werk') {
    $sk_heilkasten[] = array('sm-fehler', sk_t('ALLG.KONFIG_WERK'));
} elseif ($sk_heil['aktion'] === 'fehlgeschlagen') {
    $sk_heilkasten[] = array('sm-fehler', sk_t('ALLG.KONFIG_HEIL_FEHL'));
}

/* Und danach die Vervollstaendigung: fehlende Schluessel werden EINMAL in die
 * Datei geschrieben.
 *
 * Die Reihenfolge ist nicht beliebig. Erst heilen (Datei fehlt, ist leer oder
 * beschaedigt), dann vervollstaendigen - andersherum schriebe die
 * Vervollstaendigung eine Werkseinstellung fest, bevor die Zweitschrift
 * zurueckgeholt ist.
 *
 * Auch das steht HIER und nicht in der Lesefunktion: der unangemeldete
 * Endpunkt ruft sk_config() als erstes, noch vor der Tokenpruefung, und darf
 * nichts schreiben. */
sk_config_vervollstaendigen();

/**
 * Ein Feld eines Fahrzeugs, maskiert - und ohne Warnung, wenn es fehlt.
 *
 * ANGELEGT 31.08.2026. Sechs Stellen dieser Datei griffen ohne isset auf
 * modell, kennzeichen, motorart und software zu. Der Dienst fuellt diese vier
 * aber nur, wenn der Endpunkt 'info' geantwortet hat (bin/skoda.py: "if info
 * is not None: stamm.update(...)"). Genau dieser Endpunkt ist der, gegen den
 * das Plugin drei eigene Bremsen gegen HTTP 429 fuehrt - ein Fahrzeugeintrag
 * mit vin und soc, aber ohne Stammdaten, ist also der Regelfall nach einer
 * Abweisung, nicht ein Randfall.
 *
 * Gemessen mit einem solchen Teilabbild: sechs "Undefined array key" je
 * Seitenaufbau, in jedem der fuenf Reiter. Unter PHP 7.4 sind das E_NOTICE
 * und damit vom error_reporting dieser Datei stillgelegt, unter PHP 8.4
 * E_WARNING - der Warntext stand dort mitten in einer Tabellenzelle, samt
 * vollem Serverpfad. LoxBerry 4 faehrt PHP 8.
 *
 * Die Nachbarzeilen machten es mit !empty() und !isset() laengst richtig;
 * jetzt tun es alle, und an einer Stelle.
 */
function sk_fz($fz, $name, $ersatz = '')
{
    if (!isset($fz[$name]) || !is_scalar($fz[$name]) || $fz[$name] === '') {
        return $ersatz;
    }
    return sk_e((string) $fz[$name]);
}

/**
 * Ein POST-Wert als Zeichenkette - oder die Vorgabe.
 *
 * ANGELEGT 31.08.2026. Sieben Stellen dieser Datei riefen (string) auf einen
 * Wert, der auch ein Feld sein kann. Unter PHP 8 ist das eine WARNUNG
 * ("Array to string conversion"), und der Wert wird zur Zeichenkette "Array" -
 * gemessen mit passwort[]=x, das genau so in zugang.json landete.
 *
 * Der Endpunkt in webfrontend/html/index.php macht es seit 0.9.13 richtig und
 * begruendet es dort ausfuehrlich; hier fehlte es. Ein Feld ist keine Eingabe,
 * die man zurechtbiegt - es gibt die Vorgabe zurueck.
 */
function sk_post($name, $vorgabe = '')
{
    if (!isset($_POST[$name]) || !is_scalar($_POST[$name])) {
        return $vorgabe;
    }
    return (string) $_POST[$name];
}

/** Ein POST-Feld als Text fuer ein beanstandetes Formular (X-2): nur gueltiges
 *  UTF-8, hoechstens 2100 Byte - eine Liste reist nicht mit. */
function sk_eingaben_sammeln($formular, $felder, $falsch)
{
    $werte = array();
    foreach ($felder as $f) {
        if (!isset($_POST[$f]) || !is_string($_POST[$f])) {
            continue;
        }
        if (strlen($_POST[$f]) <= 2100 && preg_match('//u', $_POST[$f])) {
            $werte[$f] = $_POST[$f];
        }
    }
    return array('formular' => $formular, 'werte' => $werte,
                 'falsch' => array_values(array_unique($falsch)));
}

/* ---- X-2: Werte und Markierung nach einer Beanstandung (Regeln/04) ---- */
/** Ist dieses Formular das beanstandete? */
function sk_fa($formular)
{
    global $sk_eingaben;
    return is_array($sk_eingaben) && isset($sk_eingaben['formular'])
        && $sk_eingaben['formular'] === $formular;
}
/** Wert eines Feldes: nach einer Beanstandung die Eingabe, sonst der gespeicherte. */
function sk_fw($formular, $feld, $gespeichert)
{
    global $sk_eingaben;
    if (sk_fa($formular) && isset($sk_eingaben['werte'][$feld])
        && is_string($sk_eingaben['werte'][$feld])) {
        return $sk_eingaben['werte'][$feld];
    }
    return (string) $gespeichert;
}
/** Haken: nach einer Beanstandung so, wie er abgeschickt wurde. */
function sk_fh($formular, $feld, $gespeichert)
{
    global $sk_eingaben;
    if (!sk_fa($formular)) {
        return (bool) $gespeichert;
    }
    return isset($sk_eingaben['werte'][$feld]);
}
/** Markierung eines beanstandeten Feldes (Attribute, schon maskiert). */
function sk_fm($feld)
{
    global $sk_eingaben;
    return (is_array($sk_eingaben) && isset($sk_eingaben['falsch'])
            && in_array($feld, $sk_eingaben['falsch'], true))
        ? ' class="sm-beanstandet" aria-invalid="true"' : '';
}
/** Ein beanstandetes Zahlenfeld wird als Textfeld gezeigt - sonst verwirft der
 *  Browser die Eingabe "abc", und X-2 zeigte ein leeres Feld. */
function sk_ftyp($feld)
{
    return sk_fm($feld) !== '' ? 'text' : 'number';
}

$sk_meldungen = array();   // Erfolgsmeldungen
$sk_fehler = array();      // Beanstandungen - gesammelt, nicht ueberschrieben
/* DIE DRITTE ART, seit 0.9.15. Zwei Toepfe waren zu wenig, und beide Faelle
 * haben es gezeigt: eine Lage, die der Bediener ansehen soll, die aber weder
 * ein Erfolg noch ein Grund ist, das Speichern zu beanstanden.
 *
 *   - "Es ist ein Passwort gespeichert, aber kein Benutzername" hing in
 *     $sk_fehler und unterdrueckte damit die Erfolgsmeldung bei JEDEM
 *     Speichern.
 *   - "Eingereiht, aber der Dienst hat nicht geantwortet" (Stand 2 von
 *     sk_befehl_absetzen) stand unter der roten Ueberschrift "Es wurde nichts
 *     gespeichert" - "ich weiss es nicht" sah aus wie "es ist
 *     schiefgegangen". */
$sk_warnungen = array();   // weder Erfolg noch Beanstandung
/* DIE VIERTE ART, seit 0.9.21 (Regeln/04). Ein Knopf, dessen Vorgang
 * scheitert - Dienst starten, eine Aktion im Reiter Test, der Selbsttest,
 * die Sicherung -, hat nichts zu speichern versucht. Bis 0.9.20 stand sein
 * Fehler unter "Es wurde nichts gespeichert. Bitte diese Punkte
 * berichtigen" - am Geraet etwa "Zugangsdaten fehlen" nach "Dienst starten".
 * Die Ueberschrift beschrieb einen anderen Vorgang als den, der misslang. */
$sk_stoerungen = array();
/* DIE FUENFTE ART, seit dem Durchgang 01.10.2026 (O10): "Eingereiht, aber der
 * Dienst hat nicht geantwortet" stand bis 0.9.28 unter "Zur Kenntnis -
 * gespeichert wurde trotzdem:", obwohl nichts gespeichert wurde. */
$sk_unklar = array();
$sk_testausgabe = '';
$sk_eingaben = null;       // X-2: das beanstandete Formular samt Eingaben
$sk_teil = false;          // es wurde etwas gespeichert, aber nicht alles
$sk_post = (isset($_SERVER['REQUEST_METHOD']) ? $_SERVER['REQUEST_METHOD'] : '') === 'POST';
/* Ob die Anfrage ein POST WAR - auch dann, wenn der Wachposten sie abweist.
 * Jeder POST endet mit einer Umleitung (O1). */
$sk_ist_post = $sk_post;

/* ==================================================================
 * DER WACHPOSTEN - EINE PRUEFUNG, VOR ALLEN HANDLERN
 * ==================================================================
 *
 * Bis 0.9.12 gab es ihn nicht, und der Kommentar zwanzig Zeilen weiter unten
 * behauptete ihn trotzdem. Gemessen am 27.08.2026 an 0.9.12: ein POST von
 * einer beliebigen fremden Seite mit
 *
 *     token_neu=1     -> das Aktionstoken wurde neu gewuerfelt
 *     log_leeren=1    -> das Protokoll wurde ueberschrieben
 *
 * Danach bekommen saemtliche virtuellen Eingaenge im Miniserver HTTP 403 -
 * die Ueberwachung ist tot, ohne jede Rueckmeldung -, und die Spur ist
 * gleich mit weg. htmlauth/ schuetzt gegen den unangemeldeten Aufruf, nicht
 * gegen das Formular auf einer fremden Seite: die Basic-Anmeldung schickt
 * der Browser automatisch mit, SameSite greift nicht.
 *
 * EINE Pruefung am Eingang, nicht eine je Handler: einen einzelnen Handler
 * kann man beim Erweitern vergessen, den Eingang nicht. Geleert wird $_POST
 * selbst - danach laeuft KEIN Zweig mehr an, ohne dass einer davon wissen
 * muesste. Der aktive Reiter wird behalten, damit der Bediener nach der
 * Abweisung dort steht, wo er war.
 * ================================================================== */
if ($sk_post && !sk_formtoken_ok()) {
    $sk_behalten = isset($_POST['activetab']) && is_string($_POST['activetab'])
        ? sk_post('activetab') : null;
    $_POST = array();
    if ($sk_behalten !== null) {
        $_POST['activetab'] = $sk_behalten;
    }
    $sk_post = false;
    $sk_fehler[] = sk_t('ALLG.FREMDES_FORMULAR');
    sk_log_zeile('Formular ohne gueltiges Merkmal abgewiesen.');
}

/* ==================================================================
 * DIE HANDLER STEHEN VOR lbheader() - DAS IST BAUVORSCHRIFT
 * ==================================================================
 *
 * Stand der Kopf davor, war er beim Aufruf von header() schon
 * geschrieben - "Cannot modify header information", und der Knopf
 * "Einstellungen sichern" lieferte eine Seite mit angehaengtem JSON
 * statt einer Datei.
 *
 * Am PHP-CLI ist das unsichtbar: header() ist dort wirkungslos und
 * headers_sent() immer falsch. Und wer OHNE gueltiges Formularmerkmal
 * misst, wird vom Wachposten abgewiesen, bevor der Handler anlaeuft.
 * Beides hat den Fehler lange verdeckt.
 *
 * Reihenfolge: Bibliothek, Konfiguration, Wachposten, Reiterwahl,
 * ALLE Handler samt Downloads, dann erst lbheader(), dann HTML.
 * ================================================================== */
/* ---------------- Vorlage herunterladen ---------------- */
if ($sk_post && isset($_POST['vorlage'])) {
    $sk_nr = (isset($_POST['vorlage']) && is_string($_POST['vorlage'])
              && preg_match('/^[0-9]{1,2}$/', sk_post('vorlage')))
        ? (int) $_POST['vorlage'] : 1;
    /* Die ART kommt seit 0.9.13 dazu. Bis dahin gab es genau eine Vorlage -
     * fuer 'status', fest auf Fahrzeug 1 -, obwohl es fuer laden, wartung und
     * position ebenso Felder und Suchtexte gibt und die Tabelle darueber die
     * Adressen aller erkannten Fahrzeuge zeigt. Wer zwei Autos hatte, musste
     * das XML von Hand nacharbeiten. */
    $sk_art = (isset($_POST['vorlage_art']) && is_string($_POST['vorlage_art'])
               && array_key_exists(sk_post('vorlage_art'), sk_vorlagenarten()))
        ? sk_post('vorlage_art') : 'status';
    list($sk_name, $sk_inhalt) = sk_vorlage($sk_nr, $sk_art);
    header('Content-Type: application/xml; charset=utf-8');
    header('Content-Disposition: attachment; filename="' . $sk_name . '"');
    header('Content-Length: ' . strlen($sk_inhalt));
    echo $sk_inhalt;
    exit;
}

/* ---------------- Einstellungen speichern ----------------
 *
 * BEI EINER BEANSTANDUNG WIRD NICHTS GESPEICHERT (O2, Durchgang 01.10.2026;
 * Entscheidungen 16 und 19) - auch nicht die uebrigen, richtigen Felder und
 * nicht die Zugangsdaten im selben Zug. Bis 0.9.28 stand hier "GESPEICHERT
 * WIRD IMMER": intervall=abc zusammen mit takt_stamm=13 speicherte die 13, und
 * die Kopfzeile behauptete "Es wurde nichts gespeichert" (gemessen F2). Die
 * Eingaben kommen markiert zurueck ins Formular (X-2, O3), die Seite selbst
 * kommt per Umleitung (O1). Still bleibt nur Leerraum am Rand (Nr. 19); ein
 * leeres Zahlenfeld behaelt seinen Wert und sagt es - aber nur, wenn
 * gespeichert wird. */
if ($sk_post && isset($_POST['speichern'])) {
    $sk_cfg = sk_config();
    $sk_falsch = array();
    $sk_leer = array();
    $sk_regeln = sk_regeln();
    $sk_zahlfelder = array('intervall', 'takt_stamm', 'takt_wartung', 'temp_min', 'temp_max',
                           'verlauf_tage', 'wartezeit', 'abstand_abruf', 'befehle_stunde',
                           'entprellung', 'heim_radius');
    foreach ($sk_zahlfelder as $sk_feld) {
        $sk_name = sk_t('EINST.L_' . strtoupper($sk_feld));
        $sk_roh = isset($_POST[$sk_feld]) ? $_POST[$sk_feld] : '';
        if (!is_string($sk_roh)) {
            $sk_fehler[] = sprintf(sk_t('EINST.FEHLER_LISTE'), $sk_name);
            $sk_falsch[] = $sk_feld;
            continue;
        }
        $sk_wert = trim($sk_roh);
        if ($sk_wert === '') {
            $sk_leer[] = sprintf(sk_t('EINST.LEER_UEBERNOMMEN'), $sk_name, (int) $sk_cfg[$sk_feld]);
            continue;
        }
        if (!preg_match('/^[0-9]+$/', $sk_wert)) {
            $sk_fehler[] = sprintf(sk_t('EINST.FEHLER_ZAHL'), $sk_name);
            $sk_falsch[] = $sk_feld;
            continue;
        }
        $sk_zahl = (int) $sk_wert;
        if ($sk_zahl < $sk_regeln[$sk_feld][1] || $sk_zahl > $sk_regeln[$sk_feld][2]) {
            $sk_fehler[] = sprintf(sk_t('EINST.FEHLER_BEREICH'), $sk_name,
                                   $sk_regeln[$sk_feld][1], $sk_regeln[$sk_feld][2]);
            $sk_falsch[] = $sk_feld;
            continue;
        }
        $sk_cfg[$sk_feld] = $sk_zahl;
    }
    if (!in_array('temp_min', $sk_falsch, true) && !in_array('temp_max', $sk_falsch, true)
        && (int) $sk_cfg['temp_min'] > (int) $sk_cfg['temp_max']) {
        $sk_fehler[] = sk_t('EINST.FEHLER_TEMP_TAUSCH');
        $sk_falsch[] = 'temp_min';
        $sk_falsch[] = 'temp_max';
    }

    $sk_cfg['steuerung_ein'] = isset($_POST['steuerung_ein']) ? 1 : 0;
    $sk_cfg['sitzung_merken'] = isset($_POST['sitzung_merken']) ? 1 : 0;

    /* Die Heimatkoordinaten duerfen LEER bleiben (kein Geofence). Ein
     * unbrauchbarer Wert wird abgewiesen, nicht gekappt. */
    foreach (array('heim_breite', 'heim_laenge') as $sk_feld) {
        $sk_roh = isset($_POST[$sk_feld]) ? $_POST[$sk_feld] : '';
        if (!is_string($sk_roh)) {
            $sk_fehler[] = sprintf(sk_t('EINST.FEHLER_LISTE'), sk_t('EINST.L_' . strtoupper($sk_feld)));
            $sk_falsch[] = $sk_feld;
            continue;
        }
        $sk_wert = trim($sk_roh);
        if ($sk_wert === '') {
            $sk_cfg[$sk_feld] = '';
            continue;
        }
        list($sk_ok2, $sk_rein) = sk_wert_pruefen($sk_feld, $sk_wert);
        if ($sk_ok2) {
            $sk_cfg[$sk_feld] = $sk_rein;
        } else {
            $sk_fehler[] = sprintf(sk_t('EINST.FEHLER_KOORD'),
                                   sk_t('EINST.L_' . strtoupper($sk_feld)));
            $sk_falsch[] = $sk_feld;
        }
    }

    /* Zugangsdaten: dieselbe Regel wie beim Zurueckspielen (sk_email_pruefen,
     * sk_passwort_max). Bis 0.9.28 wurden Anfuehrungszeichen und Steuerzeichen
     * STILL entfernt - o'brien@example.com wurde als obrien@example.com
     * gespeichert (gemessen F3) -, und ein Passwort mit 300 Zeichen wurde
     * angenommen, das die eigene Sicherung danach abwies (F8). */
    $sk_email_roh = isset($_POST['email']) ? $_POST['email'] : '';
    list($sk_ok_email, $sk_email) = sk_email_pruefen($sk_email_roh);
    if (!$sk_ok_email) {
        $sk_fehler[] = is_string($sk_email_roh) ? sk_t('EINST.FEHLER_EMAIL')
                                               : sprintf(sk_t('EINST.FEHLER_LISTE'), sk_t('EINST.L_EMAIL'));
        $sk_falsch[] = 'email';
    }
    $sk_pw = isset($_POST['passwort']) ? $_POST['passwort'] : '';
    if (!is_string($sk_pw)) {
        $sk_fehler[] = sprintf(sk_t('EINST.FEHLER_LISTE'), sk_t('EINST.L_PASSWORT'));
        $sk_falsch[] = 'passwort';
        $sk_pw = '';
    } elseif (strlen($sk_pw) > sk_passwort_max()) {
        $sk_fehler[] = sprintf(sk_t('EINST.FEHLER_PW_LANG'), sk_passwort_max());
        $sk_falsch[] = 'passwort';
    }

    /* Nr. 36 b (Stufe 2, seit 0.9.30): Sprachausgabe und Anlaesse. Jede Beanstandung verhindert
     * das Speichern (Nr. 16); kein Sprechtoken steht in einer Meldung, ein leeres Tokenfeld heisst
     * "behalten", der Haken loescht, beides zugleich ist ein Widerspruch. */
    $sk_anlass_felder = array();
    foreach (sk_ansage_anlaesse() as $sk_a) {
        $sk_cfg[$sk_a[0]] = isset($_POST[$sk_a[0]]) ? 1 : 0;
        $sk_anlass_felder[] = $sk_a[0];
    }
    $sk_tmangel = array();
    $sk_tbean = array();
    $sk_cfg['tts'] = ansage_formular_lesen($_POST, sk_tts(), $sk_tmangel, $sk_tbean, sk_ansage_opt(),
                                           sk_ansage_k());
    foreach ($sk_tmangel as $sk_tm) {
        $sk_fehler[] = sk_e($sk_tm['text']);
    }
    foreach ($sk_tbean as $sk_tb) {
        $sk_falsch[] = $sk_tb;
    }

    if ($sk_fehler) {
        /* NICHTS gespeichert. Das Passwort und die Sprechtoken reisen nie mit
         * (ansage_x2_felder() nennt die Token nicht). */
        $sk_eingaben = sk_eingaben_sammeln('einst', array_merge($sk_zahlfelder,
            array('heim_breite', 'heim_laenge', 'email', 'steuerung_ein', 'sitzung_merken'),
            $sk_anlass_felder, ansage_x2_felder(sk_ansage_opt())), $sk_falsch);
    } elseif (sk_config_speichern($sk_cfg)) {
        $sk_meldungen[] = sk_t('EINST.GESPEICHERT');
        foreach ($sk_leer as $sk_l) {
            $sk_meldungen[] = $sk_l;
        }
        sk_log_zeile('Einstellungen gespeichert.');
        if (isset($_POST['zugang_loeschen'])) {
            // Ausdruecklich gewollt: alles weg. Was im selben Absenden im
            // Formular stand, wird bewusst verworfen.
            if (sk_zugang_loeschen()) {
                $sk_meldungen[] = sk_t('EINST.ZUGANG_GELOESCHT');
                sk_log_zeile('Zugangsdaten geloescht.');
            } else {
                $sk_fehler[] = sk_t('EINST.FEHLER_ZUGANG_LOESCHEN');
                $sk_teil = true;
            }
        } elseif (!sk_zugang_speichern($sk_email, $sk_pw)) {
            $sk_fehler[] = sk_t('EINST.FEHLER_ZUGANG_SPEICHERN');
            $sk_teil = true;
        }
        $sk_zg = sk_zugang();
        if ($sk_zg['laenge'] > 0 && $sk_zg['email'] === '') {
            $sk_warnungen[] = sk_t('EINST.WARN_PW_OHNE_KONTO');
        }
    } else {
        $sk_fehler[] = sprintf(sk_t('EINST.FEHLER_SPEICHERN'), $sk_p['config']);
    }
    $sk_tab = 'tab-settings';

    /* mqtt_ein und mqtt_topic werden hier bewusst NICHT angefasst: sie wohnen im
     * Reiter MQTT und haben dort ein eigenes Formular. */
}

/* ---------------- MQTT (eigener Reiter, eigenes Formular) ----------------
 *
 * Eigenes Formular UND eigener Handler gehoeren zusammen; der Handler laedt
 * den Bestand und ruehrt ausschliesslich die MQTT-Werte an. Seit dem
 * Durchgang 01.10.2026 wie das Einstellungsformular: bei einer Beanstandung
 * nichts speichern (bis 0.9.28 wurden die uebrigen Haken trotzdem
 * gespeichert, MQTT-Bericht, Randbefund), nichts still entfernen (bis 0.9.28
 * wurde aus sk"oda still skoda, F4), und eine Liste ist eine Beanstandung (bis
 * 0.9.28 stand danach mqtt_topic="Array" in der Datei, F5). */
if ($sk_post && isset($_POST['save_mqtt'])) {
    $sk_mcfg = sk_config();
    $sk_falsch = array();
    $sk_leer = array();
    $sk_vorher = array((int) $sk_mcfg['mqtt_ein'], (int) $sk_mcfg['mqtt_retain'], (string) $sk_mcfg['mqtt_topic']);
    $sk_mcfg['mqtt_ein'] = isset($_POST['mqtt_ein']) ? 1 : 0;
    $sk_mcfg['mqtt_retain'] = isset($_POST['mqtt_retain']) ? 1 : 0;
    $sk_roh = isset($_POST['mqtt_topic']) ? $_POST['mqtt_topic'] : '';
    if (!is_string($sk_roh)) {
        $sk_fehler[] = sprintf(sk_t('EINST.FEHLER_LISTE'), sk_t('EINST.L_MQTT_TOPIC'));
        $sk_falsch[] = 'mqtt_topic';
    } else {
        list($sk_ok_topic, $sk_rein_topic) = sk_wert_pruefen('mqtt_topic', $sk_roh);
        if (!$sk_ok_topic) {
            $sk_fehler[] = sk_t('EINST.FEHLER_TOPIC');
            $sk_falsch[] = 'mqtt_topic';
        } else {
            $sk_mcfg['mqtt_topic'] = $sk_rein_topic;
        }
    }
    $sk_mcfg['empf_kleiner'] = isset($_POST['empf_kleiner']) ? 1 : 0;
    $sk_mcfg['abfahrt_ein'] = isset($_POST['abfahrt_ein']) ? 1 : 0;
    foreach (array('empf_thema', 'empf_grenze', 'abfahrt_thema',
                   'abfahrt_vorlauf', 'abfahrt_temp', 'empf_alter') as $sk_feld) {
        $sk_name = sk_t('EINST.L_' . strtoupper($sk_feld));
        $sk_roh = isset($_POST[$sk_feld]) ? $_POST[$sk_feld] : '';
        if (!is_string($sk_roh)) {
            $sk_fehler[] = sprintf(sk_t('EINST.FEHLER_LISTE'), $sk_name);
            $sk_falsch[] = $sk_feld;
            continue;
        }
        $sk_wert = trim($sk_roh);
        if ($sk_wert === '' && in_array($sk_feld, array('empf_thema', 'empf_grenze',
                                                        'abfahrt_thema'), true)) {
            $sk_mcfg[$sk_feld] = '';
            continue;
        }
        if ($sk_wert === '') {
            $sk_leer[] = sprintf(sk_t('EINST.LEER_UEBERNOMMEN'), $sk_name, (int) $sk_mcfg[$sk_feld]);
            continue;
        }
        list($sk_ok3, $sk_rein3) = sk_wert_pruefen($sk_feld, $sk_wert);
        if ($sk_ok3) {
            $sk_mcfg[$sk_feld] = $sk_rein3;
        } else {
            $sk_fehler[] = sprintf(sk_t('EINST.FEHLER_WERT'), $sk_name);
            $sk_falsch[] = $sk_feld;
        }
    }
    if ($sk_mcfg['abfahrt_ein'] && $sk_mcfg['abfahrt_thema'] === '' && !in_array('abfahrt_thema', $sk_falsch, true)) {
        $sk_fehler[] = sk_t('EINST.FEHLER_ABFAHRT_OHNE_THEMA');
        $sk_falsch[] = 'abfahrt_thema';
    }
    if ($sk_mcfg['empf_thema'] !== '' && $sk_mcfg['empf_grenze'] === '' && !in_array('empf_grenze', $sk_falsch, true)) {
        $sk_fehler[] = sk_t('EINST.FEHLER_EMPF_OHNE_GRENZE');
        $sk_falsch[] = 'empf_grenze';
    }

    if ($sk_fehler) {
        $sk_eingaben = sk_eingaben_sammeln('mqtt', array('mqtt_ein', 'mqtt_topic', 'mqtt_retain',
            'empf_thema', 'empf_grenze', 'empf_kleiner', 'empf_alter', 'abfahrt_ein',
            'abfahrt_thema', 'abfahrt_vorlauf', 'abfahrt_temp'), $sk_falsch);
    } elseif (sk_config_speichern($sk_mcfg)) {
        $sk_meldungen[] = sk_t('EINST.GESPEICHERT');
        foreach ($sk_leer as $sk_l) {
            $sk_meldungen[] = $sk_l;
        }
        sk_log_zeile('MQTT-Einstellungen gespeichert.');
        /* M5 (Durchgang 01.10.2026): Lagen bisher retained Werte unter einem
         * Praefix, das jetzt nicht mehr retained beschickt wird, raeumt der
         * Dienst sie am Broker ab (mit Nachlesen) und merkt sie bis dahin vor -
         * auch fuer die Deinstallation. Die Seite sagt es. */
        if ($sk_vorher[0] && $sk_vorher[1]
            && (!$sk_mcfg['mqtt_ein'] || !$sk_mcfg['mqtt_retain'] || $sk_mcfg['mqtt_topic'] !== $sk_vorher[2])) {
            $sk_meldungen[] = sprintf(sk_t('MQTT.ABRAEUMEN_VORGEMERKT'), sk_e($sk_vorher[2]));
        }
    } else {
        $sk_fehler[] = sprintf(sk_t('EINST.FEHLER_SPEICHERN'), $sk_p['config']);
    }
    $sk_tab = 'tab-mqtt';
}

/* ---------------- Dienst starten, anhalten, neu starten ---------------- */
if ($sk_post && isset($_POST['dienst'])) {
    $sk_befehl = sk_post('dienst');
    sk_log_zeile('Dienst: ' . preg_replace('/[^a-z]/', '', $sk_befehl) . '.');
    list($sk_ok, $sk_ausgabe) = sk_dienst($sk_befehl);
    if ($sk_ok) {
        $sk_meldungen[] = sk_t('EINST.DIENST_' . strtoupper($sk_befehl)) . ' ' . sk_e($sk_ausgabe);
    } else {
        /* Mehrzeilig seit 0.9.21: dienst.sh zitiert im Fehlerfall die letzten
         * Protokollzeilen, und die sollen als Zeilen lesbar bleiben. */
        $sk_stoerungen[] = nl2br(sk_e($sk_ausgabe));
    }
    $sk_tab = 'tab-settings';
}

/* ---------------- Gemerkte Sitzung verwerfen ---------------- */
if ($sk_post && isset($_POST['sitzung_verwerfen'])) {
    $sk_datei = $sk_p['datadir'] . '/sitzung.json';
    if (is_file($sk_datei) && @unlink($sk_datei)) {
        $sk_meldungen[] = sk_t('EINST.SITZUNG_VERWORFEN');
    } else {
        $sk_meldungen[] = sk_t('EINST.SITZUNG_KEINE');
    }
    $sk_tab = 'tab-settings';
}

/* ---------------- Neues Token ---------------- */
if ($sk_post && isset($_POST['token_neu'])) {
    $sk_cfg = sk_config();
    $sk_cfg['aktionstoken'] = sk_token_erzeugen();
    if (sk_config_speichern($sk_cfg)) {
        $sk_meldungen[] = sk_t('LOX.TOKEN_NEU');
        /* Der Handgriff mit der groessten Wirkung: danach sind ALLE Adressen
         * im Miniserver ungueltig. Er gehoert ins Protokoll. */
        sk_log_zeile('Aktionstoken neu erzeugt - alle Adressen im Miniserver '
                     . 'muessen nachgezogen werden.');
    } else {
        $sk_fehler[] = sprintf(sk_t('EINST.FEHLER_SPEICHERN'), $sk_p['config']);
    }
    $sk_tab = 'tab-loxone';
}

/* ---------------- Log leeren ---------------- */
if ($sk_post && isset($_POST['log_leeren'])) {
    /* Ohne is_dir davor meldet PHP bei jedem Handgriff
     * "mkdir(): File exists" ins Fehlerprotokoll - unterdrueckt
     * durch das @, aber bei log_errors=On steht es trotzdem dort. */
    if (!is_dir(dirname($sk_p['log']))) {
        @mkdir(dirname($sk_p['log']), 0775, true);
    }
    @file_put_contents($sk_p['log'], '[' . date('Y-m-d H:i:s') . '] ' . sk_t('LOG.GELEERT') . "\n");
    $sk_meldungen[] = sk_t('LOG.GELEERT');
    $sk_tab = 'tab-log';
}

/* ---------------- Aktionen des Reiters Test ---------------- */
if ($sk_post && isset($_POST['test'])) {
    sk_log_zeile('Reiter Test: Befehl "'
                 . preg_replace('/[^a-z_]/', '', sk_post('test')) . '" abgesetzt.');
    list($sk_stand, $sk_text) = sk_test_aktion(sk_post('test'));
    /* DREI STAENDE, DREI AUSGAENGE. Berichtigt 31.08.2026.
     *
     * sk_befehl_absetzen() liefert ausdruecklich drei: 1 erledigt,
     * 0 abgelehnt, 2 eingereiht ohne Antwort in der Wartezeit - also
     * Ergebnis unbekannt. Bis 0.9.14 kannte diese Stelle nur zwei, und
     * Stand 2 landete unter der roten Ueberschrift "Es wurde nichts
     * gespeichert. Bitte diese Punkte berichtigen". "Ich weiss es nicht"
     * sah damit aus wie "es ist schiefgegangen" - bei einer Wartezeit von
     * acht Sekunden der Regelfall. Der eigene Endpunkt trennt die drei
     * Faelle laengst (HTTP 409 nur bei ok=0). */
    if ($sk_stand === 1) {
        $sk_meldungen[] = sk_e($sk_text);
    } elseif ($sk_stand === 2) {
        // O10 (Durchgang 01.10.2026): eigene Ueberschrift "Ergebnis unbekannt".
        $sk_unklar[] = sk_e($sk_text);
    } else {
        $sk_stoerungen[] = sk_e($sk_text);
    }
    $sk_tab = 'tab-test';
}
/* ---------------- Testansage (Nr. 36 b, seit 0.9.30) ----------------
 * Spricht den Pruefsatz des Moduls ueber die eingestellte Ausgabeart - unabhaengig
 * von den Anlaessen. Ins Protokoll nur die Kurzform ohne Text und Token. F5 nach dem
 * Knopf spricht nicht erneut: der PRG-Block unten leitet um. */
if ($sk_post && isset($_POST['ansage_test'])) {
    $sk_ak = sk_ansage_k();
    $sk_ar = ansage_testansage(sk_tts(), $sk_ak);
    sk_log_zeile('Testansage: ' . ansage_kurz($sk_ar));
    if ($sk_ar['stand'] === 1) {
        $sk_meldungen[] = sk_e(sk_t('TEST.M_ANSAGE_TEST_OK'));
    } elseif ($sk_ar['stand'] === -1) {
        /* Nichts gesendet ohne Fehler (Ausgabe aus): eine Auskunft, kein Speicherhinweis. */
        $sk_meldungen[] = sk_e(sprintf(sk_t('TEST.M_ANSAGE_TEST_NICHTS'),
                                       ansage_kennung_text($sk_ar['kennung'], $sk_ak)));
    } else {
        $sk_stoerungen[] = sk_e(sprintf(sk_t('TEST.M_ANSAGE_TEST_FEHL'),
                                        ansage_kennung_text($sk_ar['kennung'], $sk_ak)));
    }
    $sk_tab = 'tab-test';
}
if ($sk_post && isset($_POST['selbsttest'])) {
    $sk_testausgabe = sk_selbsttest();
    /* EINE LEERE AUSGABE IST KEIN ERGEBNIS. Ergaenzt 31.08.2026.
     *
     * sk_selbsttest() gibt zusammengefuegte Zeilen aus @exec() zurueck. Ist
     * exec() gesperrt oder liefert das Skript nichts, ist das der Leerstring
     * - und der Kasten weiter unten wurde dann gar nicht erst gezeigt. Die
     * Seite lud neu und sah unveraendert aus: kein Text, keine Meldung, kein
     * Fehler. Der Bediener drueckt dann noch einmal. */
    if (trim($sk_testausgabe) === '') {
        $sk_stoerungen[] = sk_t('TEST.SELBSTTEST_LEER');
    }
    $sk_tab = 'tab-test';
}

/* ---------------- Einstellungen sichern ----------------
 *
 * DIESER BLOCK STAND BIS 0.9.12 HINTER DEM LADEN DER ANZEIGEWERTE - UND DAS
 * WAR EIN FEHLER, DEN DIE DATEI IM EIGENEN KOPFKOMMENTAR VERBIETET.
 *
 * Gemessen am 27.08.2026 unter PHP 8.4: das Zurueckspielen schrieb die Datei
 * richtig, die Seite zeigte danach aber durchweg den alten Stand -
 *
 *     Meldung       "Einstellungen zurueckgespielt: 12 Werte uebernommen."
 *     Feld Takt     300   (in der Datei stand 600)
 *     Aktionstoken  altes (in der Datei stand das neue)
 *     Kasten        "Schreibende Befehle gesperrt", obwohl freigegeben
 *
 * Zwei Folgen. Erstens schrieb ein anschliessender Druck auf Speichern die
 * angezeigten alten Werte zurueck: sieben von zwoelf Werten waren wieder auf
 * dem Stand vor dem Zurueckspielen. Zweitens zeigte die Seite das alte Token,
 * waehrend die im selben Zug heruntergeladene Loxone-Vorlage das neue trug -
 * wer eine Adresse von der Seite abschrieb, bekam dauerhaft HTTP 403, und ein
 * virtueller Eingang wertet den nicht aus.
 *
 * Ausgegeben wird die volle Konfiguration samt Aktionstoken. Ohne ihn stuenden
 * nach dem Zurueckspielen alle Felder richtig, und das Plugin kaeme trotzdem
 * nicht an die Anlage. Die Zugangsdaten gehen nur mit, wenn der Haken gesetzt
 * ist - und der Dateiname sagt es dann mit.
 */
if ($sk_post && isset($_POST['sk_sichern'])) {
    $sk_mit_zugang = isset($_POST['mit_zugang']);
    $sk_js = sk_sicherung_schreiben($sk_mit_zugang);
    if ($sk_js !== '') {
        header('Content-Type: application/json; charset=utf-8');
        header('Content-Disposition: attachment; filename="skoda_einstellungen'
               . ($sk_mit_zugang ? '_mit_zugang' : '') . '_'
               . date('Ymd_His') . '.json"');
        header('Content-Length: ' . strlen($sk_js));
        sk_log_zeile('Einstellungen gesichert'
                     . ($sk_mit_zugang ? ' - MIT Zugangsdaten.' : ' - ohne Zugangsdaten.'));
        echo $sk_js;
        exit;
    }
    $sk_stoerungen[] = sk_t('EINST.SICH_SCHREIBFEHLER');
}

/* ---------------- Einstellungen zurueckspielen ----------------
 *
 * is_uploaded_file() ZUERST: ohne diese Pruefung liesse sich jede Datei des
 * Servers unterschieben. Dann die Groessengrenze - eine Sicherung dieses
 * Plugins ist wenige Kilobyte gross; alles darueber wird gar nicht gelesen. */
if ($sk_post && isset($_POST['sk_zurueck'])) {
    if (!isset($_FILES['sk_sicherung']) || !is_array($_FILES['sk_sicherung'])
        || !isset($_FILES['sk_sicherung']['tmp_name'])
        || !@is_uploaded_file($_FILES['sk_sicherung']['tmp_name'])) {
        $sk_fehler[] = sk_t('EINST.SICH_KEINE_DATEI');
    } elseif ((int) $_FILES['sk_sicherung']['size'] > 65536) {
        // 64 kB. Eine Sicherung dieses Plugins ist wenige Kilobyte gross.
        $sk_fehler[] = sk_t('EINST.SICH_ZU_GROSS');
    } else {
        list($sk_neu, $sk_mangel, $sk_n, $sk_neuzugang, $sk_hinw) = sk_sicherung_lesen(
            (string) @file_get_contents($_FILES['sk_sicherung']['tmp_name']));
        if ($sk_neu === null) {
            /* ALLE Beanstandungen, nicht nur die erste - und geaendert wird
             * nichts. Eine zur Haelfte uebernommene Konfiguration ist
             * schlimmer als die alte, und man sieht es ihr nicht an. */
            $sk_fehler[] = sk_t('EINST.SICH_ABGELEHNT') . ' '
                            . implode(' ', $sk_mangel);
            sk_log_zeile('Sicherung abgelehnt: ' . implode(' ', $sk_mangel));
        } elseif (sk_config_speichern($sk_neu)) {
            $sk_meldungen[] = sprintf(sk_t('EINST.SICH_UEBERNOMMEN'), $sk_n);
            sk_log_zeile('Einstellungen zurueckgespielt (' . $sk_n . ' Werte).');
            // O7: ein leeres Token in der Datei - das geltende bleibt, gesagt wird es.
            foreach ((array) $sk_hinw as $sk_h) {
                $sk_warnungen[] = $sk_h;
            }
            if ($sk_neuzugang !== null) {
                if (sk_zugang_speichern($sk_neuzugang['email'], $sk_neuzugang['passwort'])) {
                    $sk_meldungen[] = sk_t('EINST.SICH_ZUGANG_UEBERNOMMEN');
                    sk_log_zeile('Zugangsdaten aus der Sicherung uebernommen.');
                } else {
                    $sk_fehler[] = sk_t('EINST.FEHLER_ZUGANG_SPEICHERN');
                    $sk_teil = true;
                }
            }
            /* Punkt 7 der Hausregel: den Dienst nachziehen UND sagen, was mit
             * ihm geschehen ist. Der Dienst liest seine Konfiguration in jedem
             * Takt neu, ein Neustart ist also nicht noetig - aber das weiss
             * niemand, dem es keiner sagt. Laeuft er nicht, wird auch das
             * gesagt statt stillschweigend nichts zu tun. */
            $sk_meldungen[] = sk_dienst_pid()
                ? sk_t('EINST.SICH_DIENST_LAEUFT')
                : sk_t('EINST.SICH_DIENST_STEHT');
        } else {
            $sk_fehler[] = sk_t('EINST.SICH_SCHREIBFEHLER');
        }
    }
}

/* ==================================================================
 * PRG: JEDER POST ENDET MIT EINER UMLEITUNG (O1, Durchgang 01.10.2026)
 * ==================================================================
 *
 * Regeln/04, Entscheidung 19. Bis 0.9.28 wurde nach jedem POST unmittelbar
 * gerendert: F5 nach "Laden starten" im Reiter Test legte eine zweite
 * Befehlsdatei an, F5 nach "Token neu" zeigte die Angriffswarnung des
 * Wachpostens (gemessen F1, F6, F7). Was der Handler zu sagen hat, reist in
 * der Einmalmeldung (sk_flash_*: 0600, 120 s, nur beim GET gelesen). Die
 * Downloads (Vorlage, Sicherung) haben ihre Datei oben schon geliefert. Laesst
 * sich die Einmalmeldung nicht schreiben, wird wie bisher direkt gezeigt -
 * eine verlorene Meldung waere schlimmer als ein F5-Risiko. */
if ($sk_ist_post) {
    $sk_inhalt = array('tab' => $sk_tab, 'meldungen' => $sk_meldungen,
                       'warnungen' => $sk_warnungen, 'unklar' => $sk_unklar,
                       'fehler' => $sk_fehler, 'stoerungen' => $sk_stoerungen,
                       'heil' => $sk_heilkasten, 'teil' => $sk_teil,
                       'testausgabe' => $sk_testausgabe, 'eingaben' => $sk_eingaben);
    if (sk_flash_schreiben($sk_inhalt)) {
        header('Location: index.php?form=' . rawurlencode(preg_replace('/^tab-/', '', $sk_tab)), true, 303);
        exit;
    }
} else {
    $sk_flash = sk_flash_lesen();
    if ($sk_flash) {
        if (isset($sk_flash['tab']) && is_string($sk_flash['tab']) && preg_match($sk_muster, $sk_flash['tab'])) {
            $sk_tab = $sk_flash['tab'];
        }
        foreach (array('meldungen', 'warnungen', 'unklar', 'fehler', 'stoerungen') as $sk_fk) {
            if (isset($sk_flash[$sk_fk]) && is_array($sk_flash[$sk_fk])) {
                foreach ($sk_flash[$sk_fk] as $sk_ft) {
                    if (is_string($sk_ft)) {
                        ${'sk_' . $sk_fk}[] = $sk_ft;
                    }
                }
            }
        }
        if (isset($sk_flash['heil']) && is_array($sk_flash['heil'])) {
            foreach ($sk_flash['heil'] as $sk_hk) {
                if (is_array($sk_hk) && count($sk_hk) === 2 && is_string($sk_hk[0]) && is_string($sk_hk[1])) {
                    $sk_heilkasten[] = $sk_hk;
                }
            }
        }
        $sk_teil = !empty($sk_flash['teil']);
        if (isset($sk_flash['testausgabe']) && is_string($sk_flash['testausgabe'])) {
            $sk_testausgabe = $sk_flash['testausgabe'];
        }
        if (isset($sk_flash['eingaben']['formular'], $sk_flash['eingaben']['werte'], $sk_flash['eingaben']['falsch'])
            && is_array($sk_flash['eingaben']['werte']) && is_array($sk_flash['eingaben']['falsch'])) {
            $sk_eingaben = $sk_flash['eingaben'];
        }
    }
}

/* ---------------- Laden ---------------- */
$sk_cfg = sk_config();
$sk_token = sk_token();
$sk_zg = sk_zugang();
$sk_fahrzeuge = sk_fahrzeuge();
$sk_zustand = sk_zustand();
$sk_alter = sk_alter();
$sk_pid = sk_dienst_pid();
$sk_mqtt = sk_mqtt_zustand();
$sk_pyv = sk_python_fassung();
$sk_libv = sk_bibliothek_fassung();
/* AUS EINEM BAUTEIL. Berichtigt 31.08.2026: hier stand der Rumpf von
 * sk_host() woertlich noch einmal, waehrend der Kommentar ueber jener
 * Funktion "an einer Stelle" verspricht. Die erzeugte Loxone-Vorlage benutzt
 * sk_host(); zwei Stellen, die dieselbe Adresse zusammensetzen, laufen
 * auseinander - und dann steht in der Vorlage eine andere Adresse als auf
 * dem Bildschirm daneben. */
$sk_host = sk_host();
/* Die Grenzen der Eingabefelder kommen aus derselben Quelle wie die Pruefung
 * beim Speichern. Bis 0.9.14 standen sie ein drittes Mal woertlich in den
 * min/max-Attributen - drei Stellen fuer dieselbe Zahl. */
$sk_regeln_anz = sk_regeln();
/* Fuer welches Fahrzeug zeigt die Baustein-Liste ihre Namen?
 *
 * Das NIEDRIGSTE erkannte, sonst die 1. Bis 0.9.14 stand die 1 fest in zwoelf
 * Sprachschluesseln - bei zwei Wagen war die halbe Bauanleitung damit fuer
 * das falsche Auto. Die Adresstabelle in Schritt 3 zeigt laengst jede Nummer;
 * nur die Namensspalte tat es nicht. */
$sk_bnr = $sk_fahrzeuge ? (int) min(array_map('intval', array_keys($sk_fahrzeuge))) : 1;
if ($sk_bnr < 1) {
    $sk_bnr = 1;
}
$sk_basis = 'http://' . $sk_host . '/plugins/' . $sk_p['plugin'] . '/index.php';
$sk_logzeilen = is_file($sk_p['log']) ? sk_log_ende($sk_p['log'], 400) : array();
/* Welcher Tag im Verlauf? Rein lesend ueber GET - deshalb ohne Formular und
   ohne Merkmal; der Wachposten deckt nur schreibende Zweige ab. */
$sk_verlauftag = (isset($_GET['tag']) && is_string($_GET['tag'])
                  && preg_match('/^[0-9]{8}$/', (string) $_GET['tag']))
    ? (string) $_GET['tag'] : date('Ymd');

$sk_rahmen = class_exists('LBWeb', false);

if ($sk_rahmen) {
    LBWeb::lbheader('Skoda Connect', 'https://wiki.loxberry.de/', 'help.html');
}

?>
<style>
/* Hausstandard, wortgetreu aus VORLAGE_hausstandard.css.html uebernommen.
   Nicht neu erfinden: der Knopf-Fehler vom 30.07.2026 steckte in sieben
   Plugins gleichzeitig, weil jedes seine eigene Kopie hatte. */
.sm-wrap { max-width: 980px; margin: 0 auto; font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; color: #333; }
.sm-wrap, .sm-wrap *, .sm-tabs, .sm-tabs * { text-shadow: none !important; }
.sm-wrap h2 { color: #6dac20; margin: 24px 0 10px; font-size: 1.15em; border-bottom: 2px solid #e0e0e0; padding-bottom: 6px; }
.sm-wrap h3 { color: #4f7d17; font-size: 1.0em; font-weight: 700; margin: 16px 0 2px; }
.sm-tabs { display: flex; gap: 4px; margin: 14px 0 0; border-bottom: 2px solid #6dac20; flex-wrap: wrap; }
.sm-tab { background: #eee; border: 1px solid #ccc; border-bottom: 0; border-radius: 8px 8px 0 0;
          padding: 9px 18px; font-size: 0.95em; color: #444 !important; text-decoration: none; display: inline-block; }
.sm-tab.sm-active { background: #6dac20; color: #fff !important; border-color: #6dac20; font-weight: 600; }
.sm-feld { margin: 14px 0; }
.sm-feld > label { display: block; font-weight: 600; font-size: 0.9em; color: #555; margin: 0 0 4px; }
.sm-feld .ui-input-text, .sm-feld .ui-select, .sm-feld .ui-textinput { max-width: 520px; }
.sm-feld .ui-input-text input, .sm-feld .ui-input-text textarea { font-size: 0.95em; }
.sm-hilfe { font-size: 0.85em; color: #555; margin: 4px 0 0; max-width: 640px; }
.sm-step { border: 1px solid #ddd; border-left: 4px solid #6dac20; background: #fafafa;
    border-radius: 6px; padding: 12px 14px; margin: 12px 0; font-size: 0.92em; line-height: 1.5; }
.sm-tbl { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 0.9em; }
.sm-tbl th, .sm-tbl td { border: 1px solid #ccc; padding: 5px 7px; text-align: left; vertical-align: top; }
.sm-tbl th { background: #eef3e6; font-weight: 600; }
.sm-mono { font-family: Consolas, "Courier New", monospace; background: #f0f0f0;
    padding: 1px 4px; border-radius: 3px; font-size: 0.94em; word-break: break-all; }
.sm-pre { background: #f4f4f4; border: 1px solid #ccc; padding: 10px; font-size: 0.85em;
    overflow: auto; margin: 8px 0; white-space: pre-wrap; }
.sm-knopfreihe { display: flex; flex-wrap: wrap; gap: 10px; margin: 10px 0 4px; align-items: stretch; }
.sm-knopfreihe form { margin: 0; display: flex; }
.sm-wrap .sm-knopfreihe .sm-btn, .sm-wrap a.sm-btn, .sm-wrap button.sm-btn {
    flex: 0 0 auto; min-width: 250px; text-align: center; display: inline-flex;
    align-items: center; justify-content: center; line-height: 1.25;
    padding: 10px 14px !important; border-radius: 6px !important;
    color: #fff !important; text-decoration: none !important; font-size: 0.92em;
    border: 0 !important; cursor: pointer; font-weight: 600 !important;
    text-shadow: none !important; box-shadow: none !important;
    opacity: 1 !important; margin: 0 !important; width: auto !important; }
.sm-kacheln { display: flex; flex-wrap: wrap; gap: 10px; margin: 10px 0; }
.sm-kachel { border: 1px solid #ddd; border-radius: 10px; padding: 10px 14px; min-width: 130px; }
.sm-kachel b { display: block; font-size: 1.35em; color: #33691e; }
.sm-legende { display: flex; flex-wrap: wrap; gap: 14px; margin: 10px 0 2px; font-size: 0.86em; color: #555; }
.sm-legende span { display: inline-flex; align-items: center; gap: 6px; }
.sm-punkt { width: 13px; height: 13px; border-radius: 3px; display: inline-block; }
.sm-wrap .sm-btn.sm-b-lesen   { background: #6dac20 !important; }
.sm-wrap .sm-btn.sm-b-technik { background: #546e7a !important; }
.sm-wrap .sm-btn.sm-b-aktion  { background: #e0620d !important; }
.sm-wrap .sm-btn.sm-b-lesen:hover,   .sm-wrap .sm-btn.sm-b-lesen:focus   { background: #5c9219 !important; color: #fff !important; }
.sm-wrap .sm-btn.sm-b-technik:hover, .sm-wrap .sm-btn.sm-b-technik:focus { background: #435962 !important; color: #fff !important; }
.sm-wrap .sm-btn.sm-b-aktion:hover,  .sm-wrap .sm-btn.sm-b-aktion:focus  { background: #b84f0a !important; color: #fff !important; }
.sm-punkt.sm-b-lesen   { background: #6dac20; }
.sm-punkt.sm-b-technik { background: #546e7a; }
.sm-punkt.sm-b-aktion  { background: #e0620d; }
.sm-seite { display: none; padding-top: 4px; }
.sm-seite.sm-active { display: block; }
.sm-hinweis { border: 1px solid #cfe3b0; background: #f2f8ea; border-radius: 6px;
    padding: 10px 12px; margin: 12px 0; font-size: 0.9em; }
.sm-warnung { border: 1px solid #f0c9a0; background: #fdf4ec; border-radius: 6px;
    padding: 10px 12px; margin: 12px 0; font-size: 0.9em; }
.sm-fehler { border: 1px solid #ef9a9a; background: #ffebee; border-radius: 6px;
    padding: 10px 12px; margin: 12px 0; font-size: 0.9em; }
.sm-an  { color: #1a7f1a; font-weight: 700; }
.sm-aus { color: #b00000; font-weight: 700; }
.sm-log { background: #1e1e1e; color: #d4d4d4; font-family: Consolas, "Courier New", monospace;
    font-size: 0.82em; padding: 12px; border-radius: 8px; max-height: 480px; overflow: auto;
    white-space: pre-wrap; }
/* Ein Auswahlfeld muss man als Auswahlfeld erkennen. Nachgezogen am
   05.09.2026 nach Regeln/04; Wortlaut aus VORLAGE_hausstandard.css.html.

   Am Geraet gemessen (LoxBerry 4.0.0.15, components.css): die Rahmen-CSS
   zeichnet seit der neuen Oberflaeche selbst einen Pfeil - Regel
   ".lb-content select". Darauf kann sich eine Plugin-Oberflaeche nicht
   verlassen: die Regel gibt es erst seit dieser Fassung, und die eigene
   Feldregel loescht sie, sobald sie die Kurzform "background:" benutzt.
   Dann steht ein Auswahlfeld da, das aussieht wie ein Textfeld.

   Die Raute im SVG wird als %23 geschrieben: eine rohe Raute beendet in
   einer CSS-Adresse den Wert. */
.sm-wrap select {
    appearance: none; -webkit-appearance: none; -moz-appearance: none;
    background-image: url("data:image/svg+xml;charset=UTF-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='9' viewBox='0 0 14 9'%3E%3Cpath d='M1 1l6 6 6-6' fill='none' stroke='%234f7d17' stroke-width='2'/%3E%3C/svg%3E");
    background-repeat: no-repeat; background-position: right 10px center;
    padding-right: 32px; cursor: pointer; }
.sm-tbl select { padding-right: 28px; background-position: right 7px center; }
/* X-2 (Regeln/04, Durchgang 01.10.2026): ein beanstandetes Feld ist rot
   gerahmt und traegt aria-invalid. */
.sm-wrap .sm-beanstandet { border: 2px solid #c62828 !important; background: #fff5f5 !important; }
.sm-wrap input[type=checkbox].sm-beanstandet { outline: 2px solid #c62828; outline-offset: 2px; }

</style>
<div class="sm-wrap">

<?php foreach ($sk_heilkasten as $sk_hk) { ?>
<div class="<?= sk_e($sk_hk[0]) ?>"><?= $sk_hk[1] ?></div>
<?php } ?>
<?php foreach ($sk_meldungen as $sk_m) { ?>
<div class="sm-hinweis"><?= $sk_m ?></div>
<?php } ?>
<?php if ($sk_unklar) { ?>
<div class="sm-warnung"><b><?= sk_e(sk_t('ALLG.ERGEBNIS_UNBEKANNT')) ?></b>
<ul style="margin:6px 0 0 18px;padding:0;">
<?php foreach ($sk_unklar as $sk_u) { ?><li><?= $sk_u ?></li><?php } ?>
</ul></div>
<?php } ?>
<?php if ($sk_warnungen) { ?>
<div class="sm-warnung"><b><?= sk_e(sk_t('ALLG.HINWEIS')) ?></b>
<ul style="margin:6px 0 0 18px;padding:0;">
<?php foreach ($sk_warnungen as $sk_w) { ?><li><?= $sk_w ?></li><?php } ?>
</ul></div>
<?php } ?>
<?php if ($sk_fehler) { ?>
<!-- Zwei Kopftexte, nicht einer (O2/O10, Durchgang 01.10.2026). Seit Nr. 16
     wird bei einer Beanstandung nichts gespeichert; "nicht alles" gilt nur
     noch, wenn die Konfiguration geschrieben wurde und danach die
     Zugangsdaten scheiterten ($sk_teil). Bis 0.9.28 hing der Kopf an der
     blossen Existenz einer Meldung. -->
<div class="sm-fehler"><b><?= sk_e(sk_t($sk_teil ? 'ALLG.BEANSTANDUNG_TEIL'
                                                 : 'ALLG.BEANSTANDUNG')) ?></b>
<ul style="margin:6px 0 0 18px;padding:0;">
<?php foreach ($sk_fehler as $sk_f) { ?><li><?= $sk_f ?></li><?php } ?>
</ul></div>
<?php } ?>
<?php if ($sk_stoerungen) { ?>
<div class="sm-fehler"><b><?= sk_e(sk_t('ALLG.VORGANG_FEHLER')) ?></b>
<ul style="margin:6px 0 0 18px;padding:0;">
<?php foreach ($sk_stoerungen as $sk_stoer) { ?><li><?= $sk_stoer ?></li><?php } ?>
</ul></div>
<?php } ?>

<!-- ================= Statuskacheln ================= -->
<div class="sm-kacheln">
  <div class="sm-kachel"><?= sk_e(sk_t('ALLG.DIENST')) ?>
    <b class="<?= $sk_pid ? 'sm-an' : 'sm-aus' ?>"><?= $sk_pid ? sk_e(sk_t('ALLG.LAEUFT')) : sk_e(sk_t('ALLG.GESTOPPT')) ?></b>
    <span class="sm-hilfe"><?= $sk_pid ? 'PID ' . (int) $sk_pid : sk_e(sk_t('ALLG.KEINE_PID')) ?></span>
  </div>
  <div class="sm-kachel"><?= sk_e(sk_t('ALLG.LETZTER_ABRUF')) ?>
    <b><?= $sk_alter < 0 ? '&ndash;' : (int) $sk_alter . ' s' ?></b>
    <!-- Drei Faelle, nicht zwei: -1 heisst "noch nie abgerufen", -2 heisst
         "der Zeitstempel liegt in der Zukunft". Beide zeigen einen Strich,
         aber sie bedeuten Verschiedenes, und der zweite ist der, bei dem man
         die Uhr des LoxBerry nachsieht. -->
    <span class="sm-hilfe"><?= $sk_alter === -2 ? sk_e(sk_t('ALLG.UHR_VOR'))
        : ($sk_alter < 0 ? sk_e(sk_t('ALLG.NIE'))
                         : sk_e(date('d.m.Y H:i:s', time() - $sk_alter))) ?></span>
  </div>
  <div class="sm-kachel"><?= sk_e(sk_t('ALLG.FAHRZEUGE')) ?>
    <b><?= count($sk_fahrzeuge) ?></b>
    <span class="sm-hilfe"><?= $sk_libv !== '' ? 'myskoda ' . sk_e($sk_libv) : sk_e(sk_t('ALLG.LIB_FEHLT')) ?></span>
  </div>
  <!-- DIE KACHEL FRAGT BEIDES. Berichtigt 31.08.2026: sie haengte allein am
       Autostart des LoxBerry-Gateways. Bei ausgeschaltetem Haken des Plugins
       stand dort gruen "MQTT - ein", waehrend dieses Plugin nichts
       veroeffentlicht. Eine Statuskachel ganz oben ist die Zusammenfassung,
       und die darf nicht besser aussehen als ihr schlechtester Punkt. -->
  <div class="sm-kachel">MQTT
    <b class="<?= ($sk_mqtt['autostart'] && !empty($sk_cfg['mqtt_ein'])) ? 'sm-an' : 'sm-aus' ?>"><?= ($sk_mqtt['autostart'] && !empty($sk_cfg['mqtt_ein'])) ? sk_e(sk_t('ALLG.EIN')) : sk_e(sk_t('ALLG.AUS')) ?></b>
    <span class="sm-hilfe"><?= empty($sk_cfg['mqtt_ein']) ? sk_e(sk_t('ALLG.MQTT_PLUGIN_AUS')) : sk_e(sk_t('ALLG.GATEWAY')) ?></span>
  </div>
</div>

<?php if (!empty($sk_zustand['fehler'])) { ?>
<div class="sm-warnung"><b><?= sk_e(sk_t('ALLG.LETZTE_STOERUNG')) ?></b> <?= sk_e($sk_zustand['fehler']) ?></div>
<?php } ?>

<?php foreach ($sk_fahrzeuge as $sk_nr => $sk_fz) { ?>
<div class="sm-hinweis">
<b><?= sk_fz($sk_fz, 'modell', sk_e(sk_t('ALLG.OHNE_NAMEN'))) ?></b>
(<?= sk_e(sk_t('ALLG.FAHRZEUG')) ?> <?= sk_e($sk_nr) ?><?= sk_fz($sk_fz, 'kennzeichen') !== '' ? ', ' . sk_fz($sk_fz, 'kennzeichen') : '' ?>)
&middot; <?= sk_e(sk_t('ALLG.SOC')) ?> <b><?= !isset($sk_fz['soc']) || $sk_fz['soc'] === null ? '&ndash;' : sk_e($sk_fz['soc']) . ' %' ?></b>
&middot; <?= sk_e(sk_t('ALLG.REICHWEITE')) ?> <?= !isset($sk_fz['reichweite_km']) || $sk_fz['reichweite_km'] === null ? '&ndash;' : sk_e($sk_fz['reichweite_km']) . ' km' ?>
&middot; <?= sk_e(sk_t('ALLG.KM')) ?> <?= !isset($sk_fz['kilometerstand']) || $sk_fz['kilometerstand'] === null ? '&ndash;' : sk_e($sk_fz['kilometerstand']) . ' km' ?>
&middot; <?= sk_e(sk_t('ALLG.VERRIEGELT')) ?>
<?php if (!isset($sk_fz['verriegelt']) || $sk_fz['verriegelt'] === null) { ?>&ndash;<?php
      } elseif ($sk_fz['verriegelt']) { ?><span class="sm-an"><?= sk_e(sk_t('ALLG.JA')) ?></span><?php
      } else { ?><span class="sm-aus"><?= sk_e(sk_t('ALLG.NEIN')) ?></span><?php } ?>
<?php list($sk_punkte, $sk_art) = sk_verlauf_lesen((int) $sk_nr, $sk_verlauftag); ?>
<div style="margin-top:8px;"><?= sk_soc_svg($sk_punkte, $sk_verlauftag) ?></div>
<div class="sm-hilfe"><?php if ($sk_art !== '') { ?><b><?= sk_e(sk_t($sk_art === 'tank' ? 'ALLG.VERLAUF_TANK' : 'ALLG.VERLAUF_SOC')) ?></b> <?php } ?><?= sk_e(sk_t('ALLG.VERLAUF_HINWEIS')) ?>
<?php $sk_tage = sk_verlauf_tage((int) $sk_nr, 14); if (count($sk_tage) > 1) { ?>
<br><?= sk_e(sk_t('ALLG.VERLAUF_TAGE')) ?>
<?php foreach ($sk_tage as $sk_t1) { ?>
<a href="index.php?form=settings&amp;tag=<?= sk_e($sk_t1) ?>"<?= $sk_t1 === $sk_verlauftag ? ' style="font-weight:700;"' : '' ?>><?=
    sk_e(substr($sk_t1, 6, 2) . '.' . substr($sk_t1, 4, 2) . '.') ?></a>
<?php } ?>
<?php } ?>
</div>
<?php if (!empty($sk_fz['ausfaelle']) && is_array($sk_fz['ausfaelle'])) { ?>
<div class="sm-hilfe"><b><?= sk_e(sk_t('ALLG.AUSFAELLE')) ?></b>
<?php foreach ($sk_fz['ausfaelle'] as $sk_ep => $sk_gr) { ?>
<br><span class="sm-mono"><?= sk_e($sk_ep) ?></span>: <?= sk_e($sk_gr) ?>
<?php } ?>
</div>
<?php } ?>
</div>
<?php } ?>

<!-- Reiterleiste: echte Links, JavaScript faengt den Klick ab. So bleibt jeder
     Reiter verlinkbar, Eingaben in anderen Reitern gehen nicht verloren, und
     faellt das Skript aus, ist die Seite weiterhin bedienbar. -->
<div class="sm-tabs">
<?php foreach ($sk_reiter as $sk_r => $sk_beschriftung) { ?>
	<a class="sm-tab<?= $sk_tab === 'tab-' . $sk_r ? ' sm-active' : '' ?>" data-ziel="tab-<?= $sk_r ?>" href="index.php?form=<?= $sk_r ?>"><?= sk_e($sk_beschriftung) ?></a>
<?php } ?>
</div>

<!-- ================= Reiter: Einstellungen ================= -->
<div class="sm-seite<?= $sk_tab === 'tab-settings' ? ' sm-active' : '' ?>" id="tab-settings">

<?php if ($sk_pyv !== '' && version_compare($sk_pyv, '3.13.0', '<')) { ?>
<div class="sm-fehler"><?= sk_t('EINST.PYTHON_ZU_ALT') ?></div>
<?php } ?>

<h2><?= sk_e(sk_t('EINST.H_DIENST')) ?></h2>
<p class="sm-hilfe"><?= sk_t('EINST.DIENST_ERKLAERUNG') ?></p>
<div class="sm-legende">
<span><i class="sm-punkt sm-b-lesen"></i> <?= sk_t('LEGENDE.LESEN') ?></span>
<span><i class="sm-punkt sm-b-aktion"></i> <?= sk_t('LEGENDE.AKTION') ?></span>
</div>
<div class="sm-knopfreihe">
  <form action="index.php" method="post">
    <?= sk_formfeld() ?>
    <input data-role="none" type="hidden" name="activetab" value="tab-settings">
    <button data-role="none" class="sm-btn sm-b-lesen" type="submit" name="dienst" value="start"><?= sk_e(sk_t('EINST.K_START')) ?></button>
  </form>
  <form action="index.php" method="post">
    <?= sk_formfeld() ?>
    <input data-role="none" type="hidden" name="activetab" value="tab-settings">
    <button data-role="none" class="sm-btn sm-b-aktion" type="submit" name="dienst" value="restart"><?= sk_e(sk_t('EINST.K_NEUSTART')) ?></button>
  </form>
  <form action="index.php" method="post">
    <?= sk_formfeld() ?>
    <input data-role="none" type="hidden" name="activetab" value="tab-settings">
    <button data-role="none" class="sm-btn sm-b-aktion" type="submit" name="dienst" value="stop"><?= sk_e(sk_t('EINST.K_STOPP')) ?></button>
  </form>
  <form action="index.php" method="post">
    <?= sk_formfeld() ?>
    <input data-role="none" type="hidden" name="activetab" value="tab-settings">
    <button data-role="none" class="sm-btn sm-b-aktion" type="submit" name="sitzung_verwerfen" value="1"><?= sk_e(sk_t('EINST.K_SITZUNG')) ?></button>
  </form>
</div>

<form action="index.php" method="post" autocomplete="off">
<input data-role="none" type="hidden" name="speichern" value="1">
<?= sk_formfeld() ?>
<input data-role="none" type="hidden" name="activetab" value="tab-settings">

<h2><?= sk_e(sk_t('EINST.H_KONTO')) ?></h2>
<div class="sm-warnung"><?= sk_t('EINST.KONTO_ERKLAERUNG') ?></div>
<div class="sm-feld">
  <label for="email"><?= sk_e(sk_t('EINST.L_EMAIL')) ?></label>
  <input data-role="none" type="text" id="email" name="email" value="<?= sk_e(sk_fw('einst', 'email', $sk_zg['email'])) ?>"<?= sk_fm('email') ?> placeholder="name@example.com">
  <div class="sm-hilfe"><?= sk_t('EINST.H_EMAIL') ?></div>
</div>
<div class="sm-feld">
  <label for="passwort"><?= sk_e(sk_t('EINST.L_PASSWORT')) ?></label>
  <input data-role="none" type="password" id="passwort" name="passwort" value=""<?= sk_fm('passwort') ?> placeholder="<?= $sk_zg['laenge'] > 0 ? sk_e(sprintf(sk_t('EINST.PW_GESETZT'), $sk_zg['laenge'])) : sk_e(sk_t('EINST.PW_LEER')) ?>">
  <div class="sm-hilfe"><?= sk_t('EINST.H_PASSWORT') ?></div>
</div>
<div class="sm-feld">
  <label style="display:inline-flex;align-items:center;gap:8px;">
    <input data-role="none" type="checkbox" name="sitzung_merken" value="1" <?= sk_fh('einst', 'sitzung_merken', !empty($sk_cfg['sitzung_merken'])) ? 'checked' : '' ?>>
    <?= sk_e(sk_t('EINST.L_SITZUNG_MERKEN')) ?>
  </label>
  <div class="sm-hilfe"><?= sk_t('EINST.H_SITZUNG_MERKEN') ?></div>
</div>
<?php if ($sk_zg['email'] !== '' || $sk_zg['laenge'] > 0) { ?>
<div class="sm-feld">
  <label style="display:inline-flex;align-items:center;gap:8px;">
    <input data-role="none" type="checkbox" name="zugang_loeschen" value="1">
    <?= sk_e(sk_t('EINST.L_ZUGANG_LOESCHEN')) ?>
  </label>
  <div class="sm-hilfe"><?= sk_t('EINST.H_ZUGANG_LOESCHEN') ?></div>
</div>
<?php } ?>

<h2><?= sk_e(sk_t('EINST.H_TAKT')) ?></h2>
<div class="sm-warnung"><?= sk_t('EINST.TAKT_WARNUNG') ?></div>
<div class="sm-feld">
  <label for="intervall"><?= sk_e(sk_t('EINST.L_INTERVALL')) ?></label>
  <input data-role="none" type="<?= sk_ftyp('intervall') ?>" id="intervall" name="intervall" value="<?= sk_e(sk_fw('einst', 'intervall', (int) $sk_cfg['intervall'])) ?>"<?= sk_fm('intervall') ?> min="<?= (int) $sk_regeln_anz['intervall'][1] ?>" max="<?= (int) $sk_regeln_anz['intervall'][2] ?>">
  <div class="sm-hilfe"><?= sk_t('EINST.H_INTERVALL') ?></div>
</div>
<div class="sm-feld">
  <label for="takt_stamm"><?= sk_e(sk_t('EINST.L_TAKT_STAMM')) ?></label>
  <input data-role="none" type="<?= sk_ftyp('takt_stamm') ?>" id="takt_stamm" name="takt_stamm" value="<?= sk_e(sk_fw('einst', 'takt_stamm', (int) $sk_cfg['takt_stamm'])) ?>"<?= sk_fm('takt_stamm') ?> min="<?= (int) $sk_regeln_anz['takt_stamm'][1] ?>" max="<?= (int) $sk_regeln_anz['takt_stamm'][2] ?>">
  <div class="sm-hilfe"><?= sk_t('EINST.H_TAKT_STAMM') ?></div>
</div>
<div class="sm-feld">
  <label for="takt_wartung"><?= sk_e(sk_t('EINST.L_TAKT_WARTUNG')) ?></label>
  <input data-role="none" type="<?= sk_ftyp('takt_wartung') ?>" id="takt_wartung" name="takt_wartung" value="<?= sk_e(sk_fw('einst', 'takt_wartung', (int) $sk_cfg['takt_wartung'])) ?>"<?= sk_fm('takt_wartung') ?> min="<?= (int) $sk_regeln_anz['takt_wartung'][1] ?>" max="<?= (int) $sk_regeln_anz['takt_wartung'][2] ?>">
  <div class="sm-hilfe"><?= sk_t('EINST.H_TAKT_WARTUNG') ?></div>
</div>
<div class="sm-feld">
  <label for="verlauf_tage"><?= sk_e(sk_t('EINST.L_VERLAUF_TAGE')) ?></label>
  <input data-role="none" type="<?= sk_ftyp('verlauf_tage') ?>" id="verlauf_tage" name="verlauf_tage" value="<?= sk_e(sk_fw('einst', 'verlauf_tage', (int) $sk_cfg['verlauf_tage'])) ?>"<?= sk_fm('verlauf_tage') ?> min="<?= (int) $sk_regeln_anz['verlauf_tage'][1] ?>" max="<?= (int) $sk_regeln_anz['verlauf_tage'][2] ?>">
  <div class="sm-hilfe"><?= sk_t('EINST.H_VERLAUF_TAGE') ?></div>
</div>

<h2><?= sk_e(sk_t('EINST.H_STEUERUNG')) ?></h2>
<div class="sm-warnung"><?= sk_t('EINST.STEUERUNG_ERKLAERUNG') ?></div>
<div class="sm-feld">
  <label style="display:inline-flex;align-items:center;gap:8px;">
    <input data-role="none" type="checkbox" name="steuerung_ein" value="1" <?= sk_fh('einst', 'steuerung_ein', !empty($sk_cfg['steuerung_ein'])) ? 'checked' : '' ?>>
    <?= sk_e(sk_t('EINST.L_STEUERUNG_EIN')) ?>
  </label>
</div>
<div class="sm-feld">
  <label for="temp_min"><?= sk_e(sk_t('EINST.L_TEMP_MIN')) ?></label>
  <input data-role="none" type="<?= sk_ftyp('temp_min') ?>" id="temp_min" name="temp_min" value="<?= sk_e(sk_fw('einst', 'temp_min', (int) $sk_cfg['temp_min'])) ?>"<?= sk_fm('temp_min') ?> min="<?= (int) $sk_regeln_anz['temp_min'][1] ?>" max="<?= (int) $sk_regeln_anz['temp_min'][2] ?>">
</div>
<div class="sm-feld">
  <label for="temp_max"><?= sk_e(sk_t('EINST.L_TEMP_MAX')) ?></label>
  <input data-role="none" type="<?= sk_ftyp('temp_max') ?>" id="temp_max" name="temp_max" value="<?= sk_e(sk_fw('einst', 'temp_max', (int) $sk_cfg['temp_max'])) ?>"<?= sk_fm('temp_max') ?> min="<?= (int) $sk_regeln_anz['temp_max'][1] ?>" max="<?= (int) $sk_regeln_anz['temp_max'][2] ?>">
  <div class="sm-hilfe"><?= sk_t('EINST.H_TEMP') ?></div>
</div>
<div class="sm-feld">
  <label for="wartezeit"><?= sk_e(sk_t('EINST.L_WARTEZEIT')) ?></label>
  <input data-role="none" type="<?= sk_ftyp('wartezeit') ?>" id="wartezeit" name="wartezeit" value="<?= sk_e(sk_fw('einst', 'wartezeit', (int) $sk_cfg['wartezeit'])) ?>"<?= sk_fm('wartezeit') ?> min="<?= (int) $sk_regeln_anz['wartezeit'][1] ?>" max="<?= (int) $sk_regeln_anz['wartezeit'][2] ?>">
  <div class="sm-hilfe"><?= sk_t('EINST.H_WARTEZEIT') ?></div>
</div>

<h2><?= sk_e(sk_t('EINST.H_BREMSEN')) ?></h2>
<div class="sm-warnung"><?= sk_t('EINST.BREMSEN_ERKLAERUNG') ?></div>
<div class="sm-feld">
  <label for="abstand_abruf"><?= sk_e(sk_t('EINST.L_ABSTAND_ABRUF')) ?></label>
  <input data-role="none" type="<?= sk_ftyp('abstand_abruf') ?>" id="abstand_abruf" name="abstand_abruf" value="<?= sk_e(sk_fw('einst', 'abstand_abruf', (int) $sk_cfg['abstand_abruf'])) ?>"<?= sk_fm('abstand_abruf') ?> min="<?= (int) $sk_regeln_anz['abstand_abruf'][1] ?>" max="<?= (int) $sk_regeln_anz['abstand_abruf'][2] ?>">
  <div class="sm-hilfe"><?= sk_t('EINST.H_ABSTAND_ABRUF') ?></div>
</div>
<div class="sm-feld">
  <label for="befehle_stunde"><?= sk_e(sk_t('EINST.L_BEFEHLE_STUNDE')) ?></label>
  <input data-role="none" type="<?= sk_ftyp('befehle_stunde') ?>" id="befehle_stunde" name="befehle_stunde" value="<?= sk_e(sk_fw('einst', 'befehle_stunde', (int) $sk_cfg['befehle_stunde'])) ?>"<?= sk_fm('befehle_stunde') ?> min="<?= (int) $sk_regeln_anz['befehle_stunde'][1] ?>" max="<?= (int) $sk_regeln_anz['befehle_stunde'][2] ?>">
  <div class="sm-hilfe"><?= sk_t('EINST.H_BEFEHLE_STUNDE') ?></div>
</div>
<div class="sm-feld">
  <label for="entprellung"><?= sk_e(sk_t('EINST.L_ENTPRELLUNG')) ?></label>
  <input data-role="none" type="<?= sk_ftyp('entprellung') ?>" id="entprellung" name="entprellung" value="<?= sk_e(sk_fw('einst', 'entprellung', (int) $sk_cfg['entprellung'])) ?>"<?= sk_fm('entprellung') ?> min="<?= (int) $sk_regeln_anz['entprellung'][1] ?>" max="<?= (int) $sk_regeln_anz['entprellung'][2] ?>">
  <div class="sm-hilfe"><?= sk_t('EINST.H_ENTPRELLUNG') ?></div>
</div>

<h2><?= sk_e(sk_t('EINST.H_HEIM')) ?></h2>
<div class="sm-hinweis"><?= sk_t('EINST.HEIM_ERKLAERUNG') ?></div>
<div class="sm-feld">
  <label for="heim_breite"><?= sk_e(sk_t('EINST.L_HEIM_BREITE')) ?></label>
  <input data-role="none" type="text" id="heim_breite" name="heim_breite" value="<?= sk_e(sk_fw('einst', 'heim_breite', $sk_cfg['heim_breite'])) ?>"<?= sk_fm('heim_breite') ?> placeholder="51.318339">
</div>
<div class="sm-feld">
  <label for="heim_laenge"><?= sk_e(sk_t('EINST.L_HEIM_LAENGE')) ?></label>
  <input data-role="none" type="text" id="heim_laenge" name="heim_laenge" value="<?= sk_e(sk_fw('einst', 'heim_laenge', $sk_cfg['heim_laenge'])) ?>"<?= sk_fm('heim_laenge') ?> placeholder="9.489601">
  <div class="sm-hilfe"><?= sk_t('EINST.H_HEIM_KOORD') ?></div>
</div>
<div class="sm-feld">
  <label for="heim_radius"><?= sk_e(sk_t('EINST.L_HEIM_RADIUS')) ?></label>
  <input data-role="none" type="<?= sk_ftyp('heim_radius') ?>" id="heim_radius" name="heim_radius" value="<?= sk_e(sk_fw('einst', 'heim_radius', (int) $sk_cfg['heim_radius'])) ?>"<?= sk_fm('heim_radius') ?> min="<?= (int) $sk_regeln_anz['heim_radius'][1] ?>" max="<?= (int) $sk_regeln_anz['heim_radius'][2] ?>">
  <div class="sm-hilfe"><?= sk_t('EINST.H_HEIM_RADIUS') ?></div>
</div>

<h2><?= sk_e(sk_t('EINST.H_ANSAGE')) ?></h2>
<div class="sm-hinweis"><?= sk_t('EINST.ANSAGE_ERKLAERUNG') ?></div>
<?= ansage_formular_html(sk_tts(), array(
    'w' => function ($n, $g) { return sk_fw('einst', $n, $g); },
    'm' => function ($n) { return sk_fm($n); },
    'c' => function ($n, $g) { return sk_fh('einst', $n, $g); },
    'modi' => sk_ansage_modi()), sk_ansage_k()) ?>
<h3><?= sk_e(sk_t('EINST.H_ANSAGE_ANLAESSE')) ?></h3>
<?php foreach (sk_ansage_anlaesse() as $sk_a) { ?>
<div class="sm-feld">
  <label style="display:inline-flex;align-items:center;gap:8px;">
    <input data-role="none" type="checkbox" name="<?= sk_e($sk_a[0]) ?>" value="1" <?= sk_fh('einst', $sk_a[0], !empty($sk_cfg[$sk_a[0]])) ? 'checked' : '' ?><?= sk_fm($sk_a[0]) ?>>
    <?= sk_e(sk_t($sk_a[1])) ?>
  </label>
</div>
<?php } ?>
<div class="sm-hilfe"><?= sk_t('EINST.H_ANSAGE_ANLAESSE_HILFE') ?></div>

<?php /* MQTT stand hier bis zu dieser Fassung. Es wohnt jetzt
         vollstaendig im Reiter MQTT - eine Sache, eine Stelle. */ ?>

<div class="sm-knopfreihe">
  <button data-role="none" class="sm-btn sm-b-aktion" type="submit"><?= sk_e(sk_t('ALLG.SPEICHERN')) ?></button>
</div>
</form>

<h2><?= sk_e(sk_t('EINST.H_ERKANNT')) ?></h2>
<?php if (!$sk_fahrzeuge) { ?>
<div class="sm-warnung"><?= sk_t('EINST.KEINE_FAHRZEUGE') ?></div>
<?php } else { ?>
<table class="sm-tbl">
<tr><th><?= sk_e(sk_t('EINST.T_NR')) ?></th><th><?= sk_e(sk_t('EINST.T_MODELL')) ?></th>
    <th><?= sk_e(sk_t('EINST.T_KENNZEICHEN')) ?></th><th><?= sk_e(sk_t('EINST.T_VIN')) ?></th>
    <th><?= sk_e(sk_t('EINST.T_ANTRIEB')) ?></th><th><?= sk_e(sk_t('EINST.T_BATTERIE')) ?></th>
    <th><?= sk_e(sk_t('EINST.T_SOFTWARE')) ?></th></tr>
<?php foreach ($sk_fahrzeuge as $sk_nr => $sk_fz) { ?>
<tr><td><?= sk_e($sk_nr) ?></td><td><?= sk_fz($sk_fz, 'modell', '&mdash;') ?></td>
    <td><?= sk_fz($sk_fz, 'kennzeichen', '&mdash;') ?></td>
    <td><span class="sm-mono"><?= sk_fz($sk_fz, 'vin', '&mdash;') ?></span></td>
    <td><?= sk_fz($sk_fz, 'motorart', '&mdash;') ?></td>
    <td><?= empty($sk_fz['batterie_kwh']) ? '&mdash;' : sk_e($sk_fz['batterie_kwh']) . ' kWh' ?></td>
    <td><?= sk_fz($sk_fz, 'software', '&mdash;') ?></td></tr>
<?php } ?>
</table>
<p class="sm-hilfe"><?= sk_t('EINST.VIN_HINWEIS') ?></p>
<?php } ?>

<h2><?= sk_e(sk_t('EINST.H_LADUNGEN')) ?></h2>
<?php
/* Das Ladeprotokoll. Der Dienst sieht 'laedt' ohnehin in jedem Takt; bis
   0.9.12 fuehrte niemand Buch darueber, und damit war die einfachste Frage
   ueberhaupt unbeantwortbar: wann und wie lange hat das Auto zuletzt geladen. */
$sk_ladungen = sk_ladungen_lesen(0, 15);
if (!$sk_ladungen) { ?>
<div class="sm-hinweis"><?= sk_t('EINST.LADUNGEN_LEER') ?></div>
<?php } else { ?>
<table class="sm-tbl">
<tr><th><?= sk_e(sk_t('EINST.T_LAD_BEGINN')) ?></th><th><?= sk_e(sk_t('ALLG.FAHRZEUG')) ?></th>
    <th><?= sk_e(sk_t('EINST.T_LAD_DAUER')) ?></th><th><?= sk_e(sk_t('EINST.T_LAD_SOC')) ?></th>
    <th><?= sk_e(sk_t('EINST.T_LAD_KW')) ?></th><th><?= sk_e(sk_t('EINST.T_LAD_ORT')) ?></th></tr>
<?php foreach ($sk_ladungen as $sk_l) { ?>
<tr><td><?= sk_e(date('d.m.Y H:i', $sk_l['beginn'])) ?></td>
    <td><?= (int) $sk_l['fahrzeug'] ?></td>
    <td><?= (int) $sk_l['dauer_min'] ?> min</td>
    <td><?= $sk_l['soc_von'] === '' ? '&mdash;' : sk_e($sk_l['soc_von']) ?> &rarr; <?= $sk_l['soc_bis'] === '' ? '&mdash;' : sk_e($sk_l['soc_bis']) ?> %</td>
    <td><?= $sk_l['kw_max'] === '' ? '&mdash;' : sk_e($sk_l['kw_max']) . ' kW' ?></td>
    <td><?= sk_e($sk_l['ort']) ?></td></tr>
<?php } ?>
</table>
<p class="sm-hilfe"><?= sk_t('EINST.LADUNGEN_HINWEIS') ?></p>
<?php } ?>

<h2><?= sk_e(sk_t('EINST.H_SICHERUNG')) ?></h2>
<div class="sm-hinweis"><?= sk_t('EINST.SICH_ERKLAERUNG') ?></div>
<div class="sm-warnung"><?= sk_t('EINST.SICH_WARNUNG') ?></div>
<div class="sm-hinweis"><?= sk_t('EINST.SICH_OHNE_SPRECHTOKEN') ?></div>
<div class="sm-hilfe"><?= sk_t('EINST.SICH_MIT_ZUGANG_HILFE') ?></div>
<?php
/* X-3 (O6, Durchgang 01.10.2026): wuerde die eigene Sicherung beim
   Zurueckspielen abgewiesen, sagt es die Seite VOR dem Sichern - mit
   denselben Pruefungen wie das Zurueckspielen. Nur Namen, nie Werte. */
$sk_x3 = sk_sicherung_maengel(false);
$sk_x3z = $sk_x3 ? array() : sk_sicherung_maengel(true);
if ($sk_x3) { ?>
<div class="sm-warnung"><?= sprintf(sk_t('EINST.SICH_X3'), sk_e(implode(', ', $sk_x3))) ?></div>
<?php } elseif ($sk_x3z) { ?>
<div class="sm-warnung"><?= sprintf(sk_t('EINST.SICH_X3_ZUGANG'), sk_e(implode(', ', $sk_x3z))) ?></div>
<?php } ?>
<div class="sm-knopfreihe">
  <!-- ZWEI GETRENNTE Formulare. Das Sichern schickt einen Download und ruft
       exit auf; das Zurueckspielen braucht enctype="multipart/form-data".
       Wer beides in ein Formular legt, bekommt entweder keinen Upload oder
       einen Download, der das Speichern verschluckt. -->
  <form action="index.php" method="post">
    <?= sk_formfeld() ?>
    <input data-role="none" type="hidden" name="activetab" value="tab-settings">
    <label style="display:inline-flex;align-items:center;gap:8px;margin-right:10px;">
      <input data-role="none" type="checkbox" name="mit_zugang" value="1">
      <?= sk_e(sk_t('EINST.L_MIT_ZUGANG')) ?>
    </label>
    <button data-role="none" class="sm-btn sm-b-lesen" type="submit" name="sk_sichern" value="1"><?= sk_e(sk_t('EINST.K_SICHERN')) ?></button>
  </form>
  <form action="index.php" method="post" enctype="multipart/form-data">
    <?= sk_formfeld() ?>
    <input data-role="none" type="hidden" name="activetab" value="tab-settings">
    <input data-role="none" type="file" name="sk_sicherung" accept=".json">
    <button data-role="none" class="sm-btn sm-b-aktion" type="submit" name="sk_zurueck" value="1"><?= sk_e(sk_t('EINST.K_ZURUECK')) ?></button>
  </form>
</div>
</div>

<!-- ================= Reiter: MQTT ================= -->
<div class="sm-seite<?= $sk_tab === 'tab-mqtt' ? ' sm-active' : '' ?>" id="tab-mqtt">

<h2>MQTT</h2>
<form action="index.php" method="post">
<input data-role="none" type="hidden" name="save_mqtt" value="1">
<?= sk_formfeld() ?>
<input data-role="none" type="hidden" name="activetab" value="tab-mqtt">
<div class="sm-feld">
  <label style="display:inline-flex;align-items:center;gap:8px;">
    <input data-role="none" type="checkbox" name="mqtt_ein" value="1" <?= sk_fh('mqtt', 'mqtt_ein', !empty($sk_cfg['mqtt_ein'])) ? 'checked' : '' ?>>
    <?= sk_e(sk_t('EINST.L_MQTT_EIN')) ?>
  </label>
</div>
<div class="sm-feld">
  <label for="mqtt_topic"><?= sk_e(sk_t('EINST.L_MQTT_TOPIC')) ?></label>
  <input data-role="none" type="text" id="mqtt_topic" name="mqtt_topic" value="<?= sk_e(sk_fw('mqtt', 'mqtt_topic', $sk_cfg['mqtt_topic'])) ?>"<?= sk_fm('mqtt_topic') ?> placeholder="skoda">
  <div class="sm-hilfe"><?= sk_t('EINST.H_MQTT_TOPIC') ?></div>
</div>
<div class="sm-warnung"><?= sk_t('EINST.RETAIN_WARNUNG') ?></div>
<div class="sm-feld">
  <label style="display:inline-flex;align-items:center;gap:8px;">
    <input data-role="none" type="checkbox" name="mqtt_retain" value="1" <?= sk_fh('mqtt', 'mqtt_retain', !empty($sk_cfg['mqtt_retain'])) ? 'checked' : '' ?>>
    <?= sk_e(sk_t('EINST.L_MQTT_RETAIN')) ?>
  </label>
  <div class="sm-hilfe"><?= sk_t('EINST.H_MQTT_RETAIN') ?></div>
</div>
<h2><?= sk_e(sk_t('MQTT.H_HORCHER')) ?></h2>
<div class="sm-warnung"><?= sk_t('MQTT.HORCHER_WARNUNG') ?></div>
<h3><?= sk_e(sk_t('MQTT.H_EMPFEHLUNG')) ?></h3>
<p class="sm-hilfe"><?= sk_t('MQTT.EMPFEHLUNG_ERKLAERUNG') ?></p>
<div class="sm-feld">
  <label for="empf_thema"><?= sk_e(sk_t('EINST.L_EMPF_THEMA')) ?></label>
  <input data-role="none" type="text" id="empf_thema" name="empf_thema" value="<?= sk_e(sk_fw('mqtt', 'empf_thema', $sk_cfg['empf_thema'])) ?>"<?= sk_fm('empf_thema') ?> placeholder="pv/ueberschuss_w">
</div>
<div class="sm-feld">
  <label for="empf_grenze"><?= sk_e(sk_t('EINST.L_EMPF_GRENZE')) ?></label>
  <input data-role="none" type="text" id="empf_grenze" name="empf_grenze" value="<?= sk_e(sk_fw('mqtt', 'empf_grenze', $sk_cfg['empf_grenze'])) ?>"<?= sk_fm('empf_grenze') ?> placeholder="3000">
</div>
<div class="sm-feld">
  <label style="display:inline-flex;align-items:center;gap:8px;">
    <input data-role="none" type="checkbox" name="empf_kleiner" value="1" <?= sk_fh('mqtt', 'empf_kleiner', !empty($sk_cfg['empf_kleiner'])) ? 'checked' : '' ?>>
    <?= sk_e(sk_t('EINST.L_EMPF_KLEINER')) ?>
  </label>
  <div class="sm-hilfe"><?= sk_t('EINST.H_EMPF_KLEINER') ?></div>
</div>
<div class="sm-feld">
  <label for="empf_alter"><?= sk_e(sk_t('EINST.L_EMPF_ALTER')) ?></label>
  <input data-role="none" type="<?= sk_ftyp('empf_alter') ?>" id="empf_alter" name="empf_alter" min="<?= (int) $sk_regeln_anz['empf_alter'][1] ?>" max="<?= (int) $sk_regeln_anz['empf_alter'][2] ?>" value="<?= sk_e(sk_fw('mqtt', 'empf_alter', (int) $sk_cfg['empf_alter'])) ?>"<?= sk_fm('empf_alter') ?>>
  <div class="sm-hilfe"><?= sk_t('EINST.H_EMPF_ALTER') ?></div>
</div>

<h3><?= sk_e(sk_t('MQTT.H_ABFAHRT')) ?></h3>
<div class="sm-warnung"><?= sk_t('MQTT.ABFAHRT_WARNUNG') ?></div>
<div class="sm-feld">
  <label style="display:inline-flex;align-items:center;gap:8px;">
    <input data-role="none" type="checkbox" name="abfahrt_ein" value="1" <?= sk_fh('mqtt', 'abfahrt_ein', !empty($sk_cfg['abfahrt_ein'])) ? 'checked' : '' ?>>
    <?= sk_e(sk_t('EINST.L_ABFAHRT_EIN')) ?>
  </label>
</div>
<div class="sm-feld">
  <label for="abfahrt_thema"><?= sk_e(sk_t('EINST.L_ABFAHRT_THEMA')) ?></label>
  <input data-role="none" type="text" id="abfahrt_thema" name="abfahrt_thema" value="<?= sk_e(sk_fw('mqtt', 'abfahrt_thema', $sk_cfg['abfahrt_thema'])) ?>"<?= sk_fm('abfahrt_thema') ?> placeholder="abfahrt/restminuten">
  <div class="sm-hilfe"><?= sk_t('EINST.H_ABFAHRT_THEMA') ?></div>
</div>
<div class="sm-feld">
  <label for="abfahrt_vorlauf"><?= sk_e(sk_t('EINST.L_ABFAHRT_VORLAUF')) ?></label>
  <input data-role="none" type="<?= sk_ftyp('abfahrt_vorlauf') ?>" id="abfahrt_vorlauf" name="abfahrt_vorlauf" value="<?= sk_e(sk_fw('mqtt', 'abfahrt_vorlauf', (int) $sk_cfg['abfahrt_vorlauf'])) ?>"<?= sk_fm('abfahrt_vorlauf') ?> min="<?= (int) $sk_regeln_anz['abfahrt_vorlauf'][1] ?>" max="<?= (int) $sk_regeln_anz['abfahrt_vorlauf'][2] ?>">
</div>
<div class="sm-feld">
  <label for="abfahrt_temp"><?= sk_e(sk_t('EINST.L_ABFAHRT_TEMP')) ?></label>
  <input data-role="none" type="<?= sk_ftyp('abfahrt_temp') ?>" id="abfahrt_temp" name="abfahrt_temp" value="<?= sk_e(sk_fw('mqtt', 'abfahrt_temp', (int) $sk_cfg['abfahrt_temp'])) ?>"<?= sk_fm('abfahrt_temp') ?> min="<?= (int) $sk_regeln_anz['abfahrt_temp'][1] ?>" max="<?= (int) $sk_regeln_anz['abfahrt_temp'][2] ?>">
</div>

<div class="sm-legende"><span><i class="sm-punkt sm-b-aktion"></i> <?= sk_t('LEGENDE.AKTION') ?></span></div>
<div class="sm-knopfreihe">
  <button data-role="none" class="sm-btn sm-b-aktion" type="submit"><?= sk_e(sk_t('ALLG.SPEICHERN')) ?></button>
</div>
</form>
<h2><?= sk_e(sk_t('MQTT.H_ZUSTAND')) ?></h2>
<p class="sm-hilfe"><?= sk_t('MQTT.GATEWAY_ERKLAERUNG') ?></p>

<?php if (!$sk_mqtt['gefunden']) { ?>
<div class="sm-fehler"><?= sk_t('MQTT.NICHT_GEFUNDEN') ?></div>
<?php } elseif (!$sk_mqtt['autostart']) { ?>
<div class="sm-fehler"><?= sk_t('MQTT.AUTOSTART_AUS') ?></div>
<?php } elseif (empty($sk_cfg['mqtt_ein'])) { ?>
<!-- DER GRUENE KASTEN SAGT "Nachrichten dieses Plugins koennen also
     ankommen". Das stimmt nur, wenn der Haken oben gesetzt ist - und die
     Zeile T_PLUGIN drei Zeilen weiter unten zeigt bei ausgeschaltetem Haken
     ein rotes AUS. Zwei Aussagen in derselben Tabelle, eine davon falsch.
     Der Reiter Test hat denselben Fall seit 0.9.13 richtig; hier ist es
     am 31.08.2026 nachgezogen worden. -->
<div class="sm-hinweis"><?= sk_t('MQTT.AUTOSTART_EIN_PLUGIN_AUS') ?></div>
<?php } else { ?>
<div class="sm-hinweis"><?= sk_t('MQTT.AUTOSTART_EIN') ?></div>
<?php } ?>

<table class="sm-tbl">
<tr><th><?= sk_e(sk_t('ALLG.EIGENSCHAFT')) ?></th><th><?= sk_e(sk_t('ALLG.WERT')) ?></th></tr>
<tr><td><?= sk_e(sk_t('MQTT.T_AUTOSTART')) ?></td><td class="<?= $sk_mqtt['autostart'] ? 'sm-an' : 'sm-aus' ?>"><?= $sk_mqtt['autostart'] ? sk_e(sk_t('ALLG.EIN')) : sk_e(sk_t('ALLG.AUS')) ?></td></tr>
<tr><td><?= sk_e(sk_t('MQTT.T_BROKER')) ?></td><td><span class="sm-mono"><?= sk_e($sk_mqtt['broker']) ?>:<?= sk_e($sk_mqtt['brokerport']) ?></span></td></tr>
<tr><td><?= sk_e(sk_t('MQTT.T_UDP')) ?></td><td><span class="sm-mono"><?= (int) $sk_mqtt['udpport'] ?></span></td></tr>
<tr><td><?= sk_e(sk_t('MQTT.T_PLUGIN')) ?></td><td class="<?= !empty($sk_cfg['mqtt_ein']) ? 'sm-an' : 'sm-aus' ?>"><?= !empty($sk_cfg['mqtt_ein']) ? sk_e(sk_t('ALLG.EIN')) : sk_e(sk_t('ALLG.AUS')) ?></td></tr>
<tr><td><?= sk_e(sk_t('MQTT.T_RETAIN')) ?></td><td><?= sk_e(sk_t(!empty($sk_cfg['mqtt_retain']) ? 'TEST.A_RETAIN_EIN' : 'TEST.A_RETAIN_AUS')) ?></td></tr>
<?php
/* M5 (Durchgang 01.10.2026): Praefixe, unter denen noch retained Werte dieses
   Plugins liegen koennen und die der Dienst am Broker abraeumt. */
$sk_zv = sk_zustand();
$sk_vm = (isset($sk_zv['mqtt_vorgemerkt']) && is_array($sk_zv['mqtt_vorgemerkt']))
    ? array_values(array_filter($sk_zv['mqtt_vorgemerkt'], 'is_string')) : array(); ?>
<tr><td><?= sk_e(sk_t('MQTT.T_VORGEMERKT')) ?></td>
    <td class="<?= $sk_vm ? 'sm-aus' : '' ?>"><?= $sk_vm ? sk_e(implode(', ', $sk_vm)) . ' &mdash; ' . sk_t('MQTT.A_VORGEMERKT') : sk_e(sk_t('MQTT.A_VORGEMERKT_KEINE')) ?></td></tr>
<?php
/* WIE VIELE MELDUNGEN SIND BEIM LETZTEN DURCHGANG WIRKLICH HINAUSGEGANGEN?
 *
 * Bis 0.9.12 gab mqtt_senden() nichts zurueck und meldete nur gebremst ins
 * Protokoll. Eine Zahl an dieser Stelle beantwortet die Frage, ob ueberhaupt
 * etwas hinausgeht - auch dann, wenn das Gateway gar nicht eingerichtet ist.
 * Der Dienst schreibt sie in loxone.json. */
$sk_lox = sk_loxone();
if (isset($sk_lox['mqtt_versucht'])) { ?>
<tr><td><?= sk_e(sk_t('MQTT.T_HINAUS')) ?></td>
    <td class="<?= (int) $sk_lox['mqtt_versucht'] > 0 && empty($sk_lox['mqtt_schlecht']) ? 'sm-an' : 'sm-aus' ?>">
    <?= sprintf(sk_t('MQTT.A_HINAUS'), (int) $sk_lox['mqtt_versucht'],
                (int) (isset($sk_lox['mqtt_schlecht']) ? $sk_lox['mqtt_schlecht'] : 0)) ?></td></tr>
<?php } else { ?>
<tr><td><?= sk_e(sk_t('MQTT.T_HINAUS')) ?></td><td><?= sk_e(sk_t('MQTT.A_HINAUS_NIE')) ?></td></tr>
<?php } ?>
</table>

<?php
/* Was der Horcher meldet - vor allem, WENN er nichts kann. Ein
   Bedienelement, dessen Wert nirgends ankommt, ist schlimmer als ein
   fehlendes; das gilt auch fuer zwei Textfelder, die niemand abhoert. */
$sk_zu = sk_zustand();
if (($sk_cfg['empf_thema'] !== '' || !empty($sk_cfg['abfahrt_ein']))
    && !empty($sk_zu['horcher'])) { ?>
<div class="sm-fehler"><b><?= sk_e(sk_t('MQTT.T_HORCHER')) ?></b> <?= sk_e($sk_zu['horcher']) ?></div>
<?php } elseif ($sk_cfg['empf_thema'] !== '' && isset($sk_zu['empfehlung'])) { ?>
<div class="sm-hinweis"><?= sprintf(sk_t('MQTT.A_EMPFEHLUNG'),
    $sk_zu['empfehlung'] === null ? sk_t('ALLG.KEIN_WERT') : (int) $sk_zu['empfehlung']) ?></div>
<?php } ?>

<h2><?= sk_e(sk_t('MQTT.H_ABO')) ?></h2>
<?= sk_abo_kasten() ?>
<div class="sm-step">
<?= sk_t('MQTT.ABO_SCHRITTE') ?>
<p><span class="sm-mono"><?= sk_e($sk_cfg['mqtt_topic']) ?>/#</span></p>
</div>

<h2><?= sk_e(sk_t('MQTT.H_THEMEN')) ?></h2>
<p class="sm-hilfe"><?= sk_t('MQTT.THEMEN_ERKLAERUNG') ?></p>
<table class="sm-tbl">
<tr><th><?= sk_e(sk_t('MQTT.T_THEMA')) ?></th><th><?= sk_e(sk_t('MQTT.T_BEDEUTUNG')) ?></th><th><?= sk_e(sk_t('MQTT.T_RETAIN_SPALTE')) ?></th></tr>
<?php foreach (sk_mqtt_themen() as $sk_thema => $sk_schluessel) { ?>
<tr><td><span class="sm-mono"><?= sk_e($sk_cfg['mqtt_topic'] . '/' . $sk_thema) ?></span></td>
    <td><?= sk_t($sk_schluessel) ?></td>
    <td><?= sk_e(sk_t(!sk_mqtt_behalten($sk_thema) ? 'MQTT.RETAIN_NEIN'
        : (!empty($sk_cfg['mqtt_retain']) ? 'MQTT.RETAIN_JA' : 'MQTT.RETAIN_NEIN_HAKEN'))) ?></td></tr>
<?php } ?>
</table>
<p class="sm-hilfe"><?= sk_t('MQTT.PLATZHALTER') ?></p>
</div>

<!-- ================= Reiter: Einbindung in Loxone ================= -->
<div class="sm-seite<?= $sk_tab === 'tab-loxone' ? ' sm-active' : '' ?>" id="tab-loxone">
<h2><?= sk_e(sk_t('LOX.H_TITEL')) ?></h2>
<p><?= sk_t('LOX.EINLEITUNG') ?></p>

<!-- EINE gesammelte Legende fuer den ganzen Reiter, oben. Bis 0.9.13 standen
     hier zwei Einzellegenden, und beide UNTER ihrer Knopfreihe. -->
<div class="sm-legende">
<span><i class="sm-punkt sm-b-technik"></i> <?= sk_t('LEGENDE.TECHNIK') ?></span>
<span><i class="sm-punkt sm-b-aktion"></i> <?= sk_t('LEGENDE.AKTION_TOKEN') ?></span>
</div>

<!-- Der Pflichtsatz zum Import. Er fehlte bis 0.9.13 vollstaendig - im Reiter
     und in der Hilfe. Das Plugin bietet FUENF Vorlagen an; wer nach einem
     Fehlversuch ein zweites Mal importiert, hat danach SKODA_1_SOC doppelt im
     Projekt und sucht den Fehler bei sich. -->
<div class="sm-hinweis"><?= sk_t('LOX.H_IMPORT') ?></div>

<div class="sm-step"><b><?= sk_e(sk_t('LOX.S1_TITEL')) ?></b><br>
<?= sk_t('LOX.S1_TEXT') ?>
</div>

<div class="sm-step"><b><?= sk_e(sk_t('LOX.S2_TITEL')) ?></b><br>
<?= sk_t('LOX.S2_TEXT') ?>
<p><span class="sm-mono"><?= sk_e($sk_cfg['mqtt_topic']) ?>/#</span></p>
<?= sk_abo_kasten() ?>
</div>

<div class="sm-step"><b><?= sk_e(sk_t('LOX.S3_TITEL')) ?></b><br>
<?= sk_t('LOX.S3_TEXT') ?>
<table class="sm-tbl">
<tr><th><?= sk_e(sk_t('ALLG.EIGENSCHAFT')) ?></th><th><?= sk_e(sk_t('ALLG.WERT')) ?></th></tr>
<tr><td><?= sk_e(sk_t('LOX.T_ADRESSE')) ?></td>
    <td><span class="sm-mono"><?= sk_e($sk_basis) ?>?token=<?= sk_e($sk_token) ?>&amp;aktion=status&amp;fahrzeug=1</span></td></tr>
<tr><td><?= sk_e(sk_t('LOX.T_ZYKLUS')) ?></td><td>300 <?= sk_e(sk_t('ALLG.SEKUNDEN')) ?></td></tr>
</table>
<?= sk_t('LOX.S3_BEFEHLE') ?>
<table class="sm-tbl">
<tr><th><?= sk_e(sk_t('LOX.T_TITEL')) ?></th><th><?= sk_e(sk_t('LOX.T_BEFEHL')) ?></th>
    <th><?= sk_e(sk_t('LOX.T_EINHEIT')) ?></th><th><?= sk_e(sk_t('LOX.T_BEDEUTUNG')) ?></th></tr>
<?php foreach (sk_status_felder() as $sk_feld => $sk_info) { ?>
<tr><td><span class="sm-mono">SKODA_1_<?= sk_e($sk_feld) ?></span></td>
    <td><span class="sm-mono"><?= sk_e(sk_check($sk_feld)) ?></span></td>
    <td><?= $sk_info[0] ?></td><td><?= sk_t($sk_info[1]) ?></td></tr>
<?php } ?>
</table>
<div class="sm-warnung"><?= sk_t('LOX.S3_STRICH') ?></div>
<?php if (count($sk_fahrzeuge) > 1) { ?>
<p><b><?= sk_e(sk_t('LOX.MEHRERE_FAHRZEUGE')) ?></b></p>
<table class="sm-tbl">
<tr><th><?= sk_e(sk_t('ALLG.FAHRZEUG')) ?></th><th><?= sk_e(sk_t('EINST.T_MODELL')) ?></th><th><?= sk_e(sk_t('LOX.T_ADRESSE')) ?></th></tr>
<?php foreach ($sk_fahrzeuge as $sk_nr => $sk_fz) { ?>
<tr><td><?= sk_e($sk_nr) ?></td><td><?= sk_fz($sk_fz, 'modell', '&mdash;') ?></td>
    <td><span class="sm-mono"><?= sk_e($sk_basis) ?>?token=<?= sk_e($sk_token) ?>&amp;aktion=status&amp;fahrzeug=<?= sk_e($sk_nr) ?></span></td></tr>
<?php } ?>
</table>
<?php } ?>
<form action="index.php" method="post">
    <?= sk_formfeld() ?>
    <input data-role="none" type="hidden" name="activetab" value="tab-loxone">
<div class="sm-feld">
  <label for="vorlage"><?= sk_e(sk_t('LOX.L_VORLAGE_FZ')) ?></label>
  <select data-role="none" id="vorlage" name="vorlage">
<?php
/* Die erkannten Fahrzeuge, nicht eine feste 1. Bis 0.9.12 stand hier
   value="1" fest verdrahtet - wer zwei Autos hatte, sah die Adresse fuer das
   zweite in der Tabelle darueber und bekam die Importdatei dafuer nicht. */
$sk_liste = $sk_fahrzeuge ? array_keys($sk_fahrzeuge) : array(1);
foreach ($sk_liste as $sk_n) { ?>
    <option value="<?= (int) $sk_n ?>"><?= sk_e(sk_t('ALLG.FAHRZEUG')) ?> <?= (int) $sk_n ?><?=
        isset($sk_fahrzeuge[$sk_n]['modell']) && $sk_fahrzeuge[$sk_n]['modell'] !== ''
            ? ' - ' . sk_e($sk_fahrzeuge[$sk_n]['modell']) : '' ?></option>
<?php } ?>
  </select>
</div>
<div class="sm-feld">
  <label for="vorlage_art"><?= sk_e(sk_t('LOX.L_VORLAGE_ART')) ?></label>
  <select data-role="none" id="vorlage_art" name="vorlage_art">
<?php foreach (sk_vorlagenarten() as $sk_a => $sk_ak) { ?>
    <option value="<?= sk_e($sk_a) ?>"><?= sk_e(sk_t($sk_ak)) ?></option>
<?php } ?>
  </select>
  <div class="sm-hilfe"><?= sk_t('LOX.H_VORLAGE_ART') ?></div>
</div>
<div class="sm-knopfreihe">
    <button data-role="none" class="sm-btn sm-b-technik" type="submit"><?= sk_e(sk_t('LOX.K_VORLAGE')) ?></button>
</div>
</form>
</div>

<div class="sm-step"><b><?= sk_e(sk_t('LOX.S4_TITEL')) ?></b><br>
<?= sk_t('LOX.S4_TEXT') ?>
<table class="sm-tbl">
<tr><th><?= sk_e(sk_t('ALLG.EIGENSCHAFT')) ?></th><th><?= sk_e(sk_t('ALLG.WERT')) ?></th></tr>
<tr><td><?= sk_e(sk_t('LOX.T_ADRESSE')) ?></td><td><span class="sm-mono"><?= sk_e($sk_basis) ?>?token=<?= sk_e($sk_token) ?>&amp;aktion=laden&amp;fahrzeug=1</span></td></tr>
<tr><td><?= sk_e(sk_t('LOX.T_ZYKLUS')) ?></td><td>300 <?= sk_e(sk_t('ALLG.SEKUNDEN')) ?></td></tr>
</table>
<table class="sm-tbl">
<tr><th><?= sk_e(sk_t('LOX.T_BEFEHL')) ?></th><th><?= sk_e(sk_t('LOX.T_EINHEIT')) ?></th><th><?= sk_e(sk_t('LOX.T_BEDEUTUNG')) ?></th></tr>
<?php foreach (sk_laden_felder() as $sk_feld => $sk_info) { ?>
<tr><td><span class="sm-mono"><?= sk_e(sk_check($sk_feld)) ?></span></td>
    <td><?= $sk_info[0] ?></td><td><?= sk_t($sk_info[1]) ?></td></tr>
<?php } ?>
</table>
<?= sk_t('LOX.S4_WARTUNG') ?>
<table class="sm-tbl">
<tr><th><?= sk_e(sk_t('LOX.T_BEFEHL')) ?></th><th><?= sk_e(sk_t('LOX.T_EINHEIT')) ?></th><th><?= sk_e(sk_t('LOX.T_BEDEUTUNG')) ?></th></tr>
<?php foreach (sk_wartung_felder() as $sk_feld => $sk_info) { ?>
<tr><td><span class="sm-mono"><?= sk_e(sk_check($sk_feld)) ?></span></td>
    <td><?= $sk_info[0] ?></td><td><?= sk_t($sk_info[1]) ?></td></tr>
<?php } ?>
</table>
<?= sk_t('LOX.S4_POSITION') ?>
<!-- AUS DER FELDLISTE, wie die drei Tabellen darueber. Bis 0.9.14 standen
     hier zwei der sechs Befehlserkennungen fest im Quelltext - ausgerechnet
     ALTER fehlte, und auf ALTER baut Schritt 7 die Ausfallerkennung auf. -->
<table class="sm-tbl">
<tr><td colspan="3"><span class="sm-mono"><?= sk_e($sk_basis) ?>?token=<?= sk_e($sk_token) ?>&amp;aktion=position&amp;fahrzeug=1</span></td></tr>
<tr><th><?= sk_e(sk_t('LOX.T_BEFEHL')) ?></th><th><?= sk_e(sk_t('LOX.T_EINHEIT')) ?></th><th><?= sk_e(sk_t('LOX.T_BEDEUTUNG')) ?></th></tr>
<?php foreach (sk_position_felder() as $sk_feld => $sk_info) { ?>
<tr><td><span class="sm-mono"><?= sk_e(sk_check($sk_feld)) ?></span></td>
    <td><?= $sk_info[0] ?></td><td><?= sk_t($sk_info[1]) ?></td></tr>
<?php } ?>
</table>
</div>

<div class="sm-step"><b><?= sk_e(sk_t('LOX.S5_TITEL')) ?></b><br>
<?= sk_t('LOX.S5_TEXT') ?>
<table class="sm-tbl">
<tr><th><?= sk_e(sk_t('ALLG.EIGENSCHAFT')) ?></th><th><?= sk_e(sk_t('ALLG.WERT')) ?></th></tr>
<tr><td><?= sk_e(sk_t('LOX.T_VA_ADRESSE')) ?></td><td><span class="sm-mono">http://<?= sk_e($sk_host) ?></span></td></tr>
</table>
<?php
/* ALLE Befehle, aus sk_befehle().
 *
 * Bis 0.9.12 standen hier sieben von zwoelf, von Hand abgetippt. Nicht
 * genannt waren zieltemperatur, scheibe_aus, lueftung_start, lueftung_stop
 * und wecken - fuenf Funktionen, die das Plugin beherrscht, die der Endpunkt
 * annimmt und die niemand finden konnte. */
?>
<table class="sm-tbl">
<tr><th><?= sk_e(sk_t('LOX.T_BEFEHL')) ?></th><th><?= sk_e(sk_t('LOX.T_BEDEUTUNG')) ?></th></tr>
<?php foreach (sk_befehle() as $sk_aktion => $sk_b) { ?>
<tr><td><span class="sm-mono">/plugins/<?= sk_e($sk_p['plugin']) ?>/index.php?token=<?= sk_e($sk_token) ?>&amp;aktion=<?= sk_e($sk_aktion) ?><?=
    $sk_aktion === 'abruf' ? '' : '&amp;fahrzeug=1' ?><?=
    $sk_b[2] !== '' ? '&amp;' . sk_e($sk_b[2]) . '=&lt;v&gt;' : '' ?></span></td>
    <td><?= sk_t($sk_b[1]) ?></td></tr>
<?php } ?>
</table>
<p class="sm-hilfe"><?= sk_t('LOX.VA_HINWEIS') ?></p>
<div class="sm-warnung"><?= sk_t('LOX.S5_WARNUNG') ?></div>
</div>

<div class="sm-step"><b><?= sk_e(sk_t('LOX.S6_TITEL')) ?></b><br>
<table class="sm-tbl">
<tr><th><?= sk_e(sk_t('ALLG.EIGENSCHAFT')) ?></th><th><?= sk_e(sk_t('ALLG.WERT')) ?></th></tr>
<tr><td><?= sk_e(sk_t('LOX.T_TOKEN')) ?></td><td><span class="sm-mono"><?= sk_e($sk_token) ?></span></td></tr>
</table>
<?= sk_t('LOX.S6_TEXT') ?>
<div class="sm-knopfreihe">
  <form action="index.php" method="post">
    <?= sk_formfeld() ?>
    <input data-role="none" type="hidden" name="activetab" value="tab-loxone">
    <button data-role="none" class="sm-btn sm-b-aktion" type="submit" name="token_neu" value="1"><?= sk_e(sk_t('LOX.K_TOKEN_NEU')) ?></button>
  </form>
</div>
</div>

<div class="sm-step"><b><?= sk_e(sk_t('LOX.S7_TITEL')) ?></b><br>
<?= sk_t('LOX.S7_TEXT') ?>
</div>

<?php
/**
 * Die komplette Baustein-Liste. Pflicht im Hausstandard.
 *
 * Anspruch: Wer die Tabelle von oben nach unten abarbeitet, hat die Funktion
 * nachgebaut, ohne nachzudenken. Loxone Config fuehrt alle Bausteine in der
 * Baustein-Suche (F5).
 *
 * Je Zeile: Nummer, Typ, Name, Parameter, woran die Eingaenge kommen.
 * Typ, Name und Parameter stehen als Sprachschluessel drin, die Eingangsspalte
 * ist symbolisch und damit sprachfrei.
 */
function sk_bausteine($nr = 1)
{
    return array(
        /* DIE NAMEN WERDEN GEBAUT, NICHT ABGESCHRIEBEN - seit 0.9.15.
         *
         * Sie standen als Sprachschluessel N01..N12 in beiden .ini-Dateien
         * und mussten bei jeder Aenderung an der Feldliste von Hand
         * nachgezogen werden. Genau das ist einmal unterblieben: #12 nannte
         * SKODA_1_INSPTAGE, erzeugt wird SKODA_1_WARTUNG_INSPTAGE.
         *
         * Ein Feld ist ein PHP-Feld statt eines Schluessels - der Renderer
         * unten unterscheidet daran, ob er uebersetzen muss. Und die Nummer
         * ist die des angezeigten Fahrzeugs, nicht mehr fest die 1. */
        array(1,  'BAUSTEIN.T_VE', array(sk_eingangsname('SOC', 'status', $nr)),      'BAUSTEIN.P01', '&mdash;'),
        array(2,  'BAUSTEIN.T_VE', array(sk_eingangsname('TANK', 'status', $nr)),     'BAUSTEIN.P02', '&mdash;'),
        array(3,  'BAUSTEIN.T_VE', array(sk_eingangsname('REICHW', 'status', $nr)),   'BAUSTEIN.P03', '&mdash;'),
        array(4,  'BAUSTEIN.T_VE', array(sk_eingangsname('KM', 'status', $nr)),       'BAUSTEIN.P04', '&mdash;'),
        array(5,  'BAUSTEIN.T_VE', array(sk_eingangsname('VERR', 'status', $nr)),     'BAUSTEIN.P05', '&mdash;'),
        array(6,  'BAUSTEIN.T_VE', array(sk_eingangsname('TUEREN', 'status', $nr)),   'BAUSTEIN.P06', '&mdash;'),
        array(7,  'BAUSTEIN.T_VE', array(sk_eingangsname('FENSTER', 'status', $nr)),  'BAUSTEIN.P07', '&mdash;'),
        array(8,  'BAUSTEIN.T_VE', array(sk_eingangsname('KOFFER', 'status', $nr)),   'BAUSTEIN.P08', '&mdash;'),
        array(9,  'BAUSTEIN.T_VE', array(sk_eingangsname('KLIMA', 'status', $nr)),    'BAUSTEIN.P09', '&mdash;'),
        array(10, 'BAUSTEIN.T_VE', array(sk_eingangsname('WARN', 'status', $nr)),     'BAUSTEIN.P10', '&mdash;'),
        array(11, 'BAUSTEIN.T_VE', array(sk_eingangsname('ALTER', 'status', $nr)),    'BAUSTEIN.P11', '&mdash;'),
        array(12, 'BAUSTEIN.T_VE', array(sk_eingangsname('INSPTAGE', 'wartung', $nr)), 'BAUSTEIN.P12', '&mdash;'),
        array(13, 'BAUSTEIN.T_NICHT',   'BAUSTEIN.N13', '',             'I &larr; #5'),
        /* Regel A4 (Regeln/04; Nachzug 02.10.2026): ein UND/ODER hat zwei Eingaenge, an jedem
         * genau eine Quelle. Bisher hingen an #14 vier Quellen an zwei Eingaengen; jetzt drei
         * ODER, und jede spaetere Zeile rueckt um zwei. Die Sprachschluessel N15 ff. behalten
         * ihre Namen - die angezeigte Nummer ist die erste Spalte. */
        array(14, 'BAUSTEIN.T_ODER',    'BAUSTEIN.N14A', '',            'I1 &larr; #13, I2 &larr; #6'),
        array(15, 'BAUSTEIN.T_ODER',    'BAUSTEIN.N14B', '',            'I1 &larr; #7, I2 &larr; #8'),
        array(16, 'BAUSTEIN.T_ODER',    'BAUSTEIN.N14', '',             'I1 &larr; #14, I2 &larr; #15'),
        array(17, 'BAUSTEIN.T_EVZ',     'BAUSTEIN.N15', 'BAUSTEIN.P15', 'I &larr; #16'),
        array(18, 'BAUSTEIN.T_BENACHR', 'BAUSTEIN.N16', 'BAUSTEIN.P16', 'I &larr; #17'),
        array(19, 'BAUSTEIN.T_SWS',     'BAUSTEIN.N17', 'BAUSTEIN.P17', 'I &larr; #1'),
        array(20, 'BAUSTEIN.T_SWS',     'BAUSTEIN.N18', 'BAUSTEIN.P18', 'I &larr; #2'),
        array(21, 'BAUSTEIN.T_ODER',    'BAUSTEIN.N19', '',             'I1 &larr; #19, I2 &larr; #20'),
        array(22, 'BAUSTEIN.T_BENACHR', 'BAUSTEIN.N20', 'BAUSTEIN.P20', 'I &larr; #21'),
        array(23, 'BAUSTEIN.T_SWS',     'BAUSTEIN.N21', 'BAUSTEIN.P21', 'I &larr; #10'),
        array(24, 'BAUSTEIN.T_BENACHR', 'BAUSTEIN.N22', 'BAUSTEIN.P22', 'I &larr; #23'),
        array(25, 'BAUSTEIN.T_SWS',     'BAUSTEIN.N23', 'BAUSTEIN.P23', 'I &larr; #12'),
        array(26, 'BAUSTEIN.T_BENACHR', 'BAUSTEIN.N24', 'BAUSTEIN.P24', 'I &larr; #25'),
        array(27, 'BAUSTEIN.T_SWS',     'BAUSTEIN.N25', 'BAUSTEIN.P25', 'I &larr; #11'),
        array(28, 'BAUSTEIN.T_BENACHR', 'BAUSTEIN.N26', 'BAUSTEIN.P26', 'I &larr; #27'),
        array(29, 'BAUSTEIN.T_STATUS',  'BAUSTEIN.N27', 'BAUSTEIN.P27', 'I1 &larr; #1, I2 &larr; #3, I3 &larr; #5'),
        array(30, 'BAUSTEIN.T_WOCHE',   'BAUSTEIN.N28', 'BAUSTEIN.P28', '&mdash;'),
        array(31, 'BAUSTEIN.T_TASTER',  'BAUSTEIN.N29', 'BAUSTEIN.P29', '&mdash;'),
        array(32, 'BAUSTEIN.T_UND',     'BAUSTEIN.N30', 'BAUSTEIN.P30', 'I1 &larr; #30, I2 &larr; ' . sk_t('BAUSTEIN.ANWESEND')),
        array(33, 'BAUSTEIN.T_ODER',    'BAUSTEIN.N31', '',             'I1 &larr; #31, I2 &larr; #32'),
        array(34, 'BAUSTEIN.T_IMPULS',  'BAUSTEIN.N32', 'BAUSTEIN.P32', 'I &larr; #33'),
        array(35, 'BAUSTEIN.T_VA',      'BAUSTEIN.N33', 'BAUSTEIN.P33', 'I &larr; #34'),
        array(36, 'BAUSTEIN.T_VA',      'BAUSTEIN.N34', 'BAUSTEIN.P34', sk_t('BAUSTEIN.MANUELL')),
    );
}
?>

<div class="sm-step"><b><?= sk_e(sk_t('LOX.S8_TITEL')) ?></b><br>
<?= sk_t('LOX.S8_TEXT') ?>
<table class="sm-tbl">
<tr><th>#</th><th><?= sk_e(sk_t('LOX.T_BAUSTEIN')) ?></th><th><?= sk_e(sk_t('LOX.T_NAMENSVORSCHLAG')) ?></th>
    <th><?= sk_e(sk_t('LOX.T_PARAMETER')) ?></th><th><?= sk_e(sk_t('LOX.T_EINGAENGE')) ?></th></tr>
<?php foreach (sk_bausteine($sk_bnr) as $sk_b) { ?>
<!-- Ein Feld in der Namensspalte ist ein fertiger Name, ein String ein
     Sprachschluessel. Ohne die Unterscheidung liefe ein Name durch sk_t()
     und saehe bei einem Tippfehler wie ein fehlender Schluessel aus. -->
<tr><td><?= (int) $sk_b[0] ?></td><td><?= sk_t($sk_b[1]) ?></td><td><?= is_array($sk_b[2]) ? sk_e($sk_b[2][0]) : sk_t($sk_b[2]) ?></td>
    <td><?= $sk_b[3] !== '' ? sk_t($sk_b[3]) : '&mdash;' ?></td><td><?= $sk_b[4] ?></td></tr>
<?php } ?>
</table>
<?php if (count($sk_fahrzeuge) > 1) { ?>
<!-- Die Namen in der Spalte "Name (Vorschlag)" tragen fest die 1. Bei
     mehreren Fahrzeugen erzeugt sk_vorlage() SKODA_2_..., SKODA_3_... - die
     Adresstabelle in Schritt 3 zeigt das laengst je Fahrzeug, die
     Baustein-Liste nicht. Statt eine Anleitung fuer EIN Fahrzeug als die
     fuer alle auszugeben, sagt sie es seit 0.9.15. -->
<div class="sm-hinweis"><?= sprintf(sk_t('LOX.S8_MEHRERE'), count($sk_fahrzeuge)) ?></div>
<?php } ?>
<?= sk_t('LOX.S8_ERLAEUTERUNG') ?>
</div>

<div class="sm-step"><b><?= sk_e(sk_t('LOX.S9_TITEL')) ?></b><br>
<?= sk_t('LOX.S9_TEXT') ?>
<table class="sm-tbl">
<tr><th><?= sk_e(sk_t('LOX.T_PRUEFUNG')) ?></th><th><?= sk_e(sk_t('LOX.T_ERWARTUNG')) ?></th></tr>
<tr><td><span class="sm-mono"><?= sk_e($sk_basis) ?>?token=<?= sk_e($sk_token) ?>&amp;aktion=status</span></td>
    <td><span class="sm-mono">SKODA;OK=1;SOC=...</span></td></tr>
<tr><td><span class="sm-mono"><?= sk_e($sk_basis) ?>?aktion=status</span></td>
    <td><span class="sm-mono">FEHLER;OK=0;GRUND=TOKEN</span> (HTTP 403)</td></tr>
<tr><td><span class="sm-mono"><?= sk_e($sk_basis) ?>?token=<?= sk_e($sk_token) ?>&amp;aktion=quatsch</span></td>
    <td><span class="sm-mono">FEHLER;OK=0;GRUND=UNBEKANNTE_AKTION</span> (HTTP 400)</td></tr>
</table>
</div>
</div>

<!-- ================= Reiter: Test ================= -->
<div class="sm-seite<?= $sk_tab === 'tab-test' ? ' sm-active' : '' ?>" id="tab-test">
<h2><?= sk_e(sk_t('TEST.H_SELBSTPRUEFUNG')) ?></h2>
<p class="sm-hilfe"><?= sk_t('TEST.EINLEITUNG') ?></p>
<table class="sm-tbl">
<tr><th style="width:36px;">&nbsp;</th><th><?= sk_e(sk_t('TEST.T_FRAGE')) ?></th><th><?= sk_e(sk_t('TEST.T_BEFUND')) ?></th></tr>
<?php foreach (sk_pruefungen($sk_tab === 'tab-test') as $sk_z) { ?>
<tr><td style="text-align:center;"><?php
    if ($sk_z['stand'] === 1) { echo '<span class="sm-an">&#10004;</span>'; }
    elseif ($sk_z['stand'] === 0) { echo '<span class="sm-aus">&#10008;</span>'; }
    else { echo '<span style="color:#888;">&#9679;</span>'; }
?></td><td><?= $sk_z['frage'] ?></td><td><?= $sk_z['antwort'] ?></td></tr>
<?php } ?>
</table>

<div class="sm-legende">
<span><i class="sm-punkt sm-b-lesen"></i> <?= sk_t('LEGENDE.LESEN') ?></span>
<span><i class="sm-punkt sm-b-technik"></i> <?= sk_t('LEGENDE.TECHNIK') ?></span>
<span><i class="sm-punkt sm-b-aktion"></i> <?= sk_t('LEGENDE.AKTION') ?></span>
</div>

<h3><?= sk_e(sk_t('TEST.H_LESEN')) ?></h3>
<div class="sm-knopfreihe">
  <a class="sm-btn sm-b-lesen" href="<?= sk_e($sk_basis) ?>?token=<?= sk_e($sk_token) ?>&amp;aktion=status&amp;fahrzeug=1" target="_blank"><?= sk_e(sk_t('TEST.K_STATUS')) ?></a>
  <a class="sm-btn sm-b-lesen" href="<?= sk_e($sk_basis) ?>?token=<?= sk_e($sk_token) ?>&amp;aktion=laden&amp;fahrzeug=1" target="_blank"><?= sk_e(sk_t('TEST.K_LADEN')) ?></a>
  <a class="sm-btn sm-b-lesen" href="<?= sk_e($sk_basis) ?>?token=<?= sk_e($sk_token) ?>&amp;aktion=wartung&amp;fahrzeug=1" target="_blank"><?= sk_e(sk_t('TEST.K_WARTUNG')) ?></a>
  <a class="sm-btn sm-b-lesen" href="<?= sk_e($sk_basis) ?>?token=<?= sk_e($sk_token) ?>&amp;aktion=fahrzeuge" target="_blank"><?= sk_e(sk_t('TEST.K_FAHRZEUGE')) ?></a>
</div>

<h3><?= sk_e(sk_t('TEST.H_TECHNIK')) ?></h3>
<div class="sm-knopfreihe">
  <form action="index.php" method="post">
    <?= sk_formfeld() ?>
    <input data-role="none" type="hidden" name="activetab" value="tab-test">
    <button data-role="none" class="sm-btn sm-b-technik" type="submit" name="selbsttest" value="1"><?= sk_e(sk_t('TEST.K_SELBSTTEST')) ?></button>
  </form>
  <a class="sm-btn sm-b-technik" href="<?= sk_e($sk_basis) ?>?token=<?= sk_e($sk_token) ?>&amp;aktion=roh" target="_blank"><?= sk_e(sk_t('TEST.K_ROH')) ?></a>
</div>
<?php if ($sk_testausgabe !== '') { ?>
<div class="sm-pre"><?= sk_e($sk_testausgabe) ?></div>
<?php } ?>

<h3><?= sk_e(sk_t('TEST.H_ANSAGE')) ?></h3>
<p class="sm-hilfe"><?= sk_e(sk_t('TEST.ANSAGE_TEST_TEXT')) ?></p>
<div class="sm-knopfreihe">
  <form action="index.php" method="post">
    <?= sk_formfeld() ?>
    <input data-role="none" type="hidden" name="activetab" value="tab-test">
    <button data-role="none" class="sm-btn sm-b-aktion" type="submit" name="ansage_test" value="1"><?= sk_e(sk_t('TEST.K_ANSAGE_TEST')) ?></button>
  </form>
</div>

<h3><?= sk_e(sk_t('TEST.H_SCHALTEN')) ?></h3>
<div class="sm-warnung"><?= sk_t('TEST.SCHALTEN_WARNUNG') ?></div>
<?php if (empty($sk_cfg['steuerung_ein'])) { ?>
<div class="sm-hinweis"><?= sk_t('TEST.SCHALTEN_GESPERRT') ?></div>
<?php } ?>
<?php if (!$sk_pid) { ?>
<div class="sm-fehler"><?= sk_t('TEST.SCHALTEN_OHNE_DIENST') ?></div>
<?php } ?>
<form action="index.php" method="post">
<?= sk_formfeld() ?>
<input data-role="none" type="hidden" name="activetab" value="tab-test">
<div class="sm-feld">
  <label for="test_fahrzeug"><?= sk_e(sk_t('TEST.L_FAHRZEUG')) ?></label>
  <input data-role="none" type="number" id="test_fahrzeug" name="test_fahrzeug" value="1" min="1" max="99">
</div>
<div class="sm-feld">
  <label for="test_temp"><?= sk_e(sk_t('TEST.L_TEMP')) ?></label>
  <input data-role="none" type="text" id="test_temp" name="test_temp" value="<?= (int) $sk_cfg['temp_min'] ?>">
  <div class="sm-hilfe"><?= sk_t('TEST.H_TEMP') ?></div>
</div>
<div class="sm-feld">
  <label for="test_prozent"><?= sk_e(sk_t('TEST.L_PROZENT')) ?></label>
  <input data-role="none" type="number" id="test_prozent" name="test_prozent" value="80" min="50" max="100">
  <div class="sm-hilfe"><?= sk_t('TEST.H_PROZENT') ?></div>
</div>
<?php
/* Die Knopfreihe entsteht aus sk_befehle() - derselben Quelle wie die
 * Weissliste des Endpunkts, die Befehlstabelle im Reiter Loxone und die
 * Ausgangsvorlage.
 *
 * Bis 0.9.12 standen hier neun Knoepfe von Hand, waehrend der Endpunkt zwoelf
 * Aktionen kannte: zieltemperatur, lueftung_start und lueftung_stop liessen
 * sich nirgends ausprobieren. Die Standlueftung war damit die einzige
 * Funktion, die man vor dem Bau der Loxone-Anbindung ueberhaupt nicht
 * erproben konnte. */
?>
<div class="sm-knopfreihe">
<?php foreach (sk_befehle() as $sk_aktion => $sk_b) {
    if (empty($sk_b[3])) { continue; } ?>
  <button data-role="none" class="sm-btn sm-b-aktion" type="submit" name="test" value="<?= sk_e($sk_aktion) ?>"><?= sk_e(sk_t($sk_b[0])) ?></button>
<?php } ?>
</div>
</form>

<div class="sm-warnung"><b><?= sk_e(sk_t('TEST.H_UNGEPRUEFT')) ?></b><br><?= sk_t('TEST.UNGEPRUEFT') ?></div>
</div>

<!-- ================= Reiter: Logdateien ================= -->
<div class="sm-seite<?= $sk_tab === 'tab-log' ? ' sm-active' : '' ?>" id="tab-log">
<h2><?= sk_e(sk_t('LOG.H_TITEL')) ?></h2>
<?php
if (class_exists('LBWeb', false) && method_exists('LBWeb', 'loglist_html')) {
    echo LBWeb::loglist_html();
}
?>
<p class="sm-hilfe"><?= sk_t('LOG.ERKLAERUNG') ?><br>
<span class="sm-mono"><?= sk_e($sk_p['log']) ?></span></p>
<?php if ($sk_logzeilen) { ?>
<div class="sm-log"><?= sk_e(implode("\n", $sk_logzeilen)) ?></div>
<?php } else { ?>
<div class="sm-hinweis"><?= sk_t('LOG.LEER') ?></div>
<?php } ?>
<div class="sm-legende">
<span><i class="sm-punkt sm-b-aktion"></i> <?= sk_t('LEGENDE.AKTION_LOG') ?></span>
</div>
<div class="sm-knopfreihe">
  <form action="index.php" method="post">
    <?= sk_formfeld() ?>
    <input data-role="none" type="hidden" name="activetab" value="tab-log">
    <button data-role="none" class="sm-btn sm-b-aktion" type="submit" name="log_leeren" value="1"><?= sk_e(sk_t('LOG.K_LEEREN')) ?></button>
  </form>
</div>
</div>

</div><!-- /sm-wrap -->

<script>
(function () {
	var reiter = document.querySelectorAll('.sm-tab');
	function zeige(id) {
		reiter.forEach(function (r) { r.classList.toggle('sm-active', r.dataset.ziel === id); });
		document.querySelectorAll('.sm-seite').forEach(function (s) { s.classList.toggle('sm-active', s.id === id); });
		document.querySelectorAll('input[name="activetab"]').forEach(function (f) { f.value = id; });
		if (history.replaceState) { history.replaceState(null, '', 'index.php?form=' + id.replace('tab-', '')); }
	}
	reiter.forEach(function (r) {
		r.addEventListener('click', function (e) { e.preventDefault(); zeige(r.dataset.ziel); });
	});
	zeige(<?= json_encode($sk_tab) ?>);
})();
</script>
<?php
if ($sk_rahmen) {
    LBWeb::lbfooter();
}
