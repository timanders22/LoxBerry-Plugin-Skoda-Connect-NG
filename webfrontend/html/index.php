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
require_once __DIR__ . '/sk_lib.php';
header('Content-Type: text/plain; charset=utf-8');

$sk_cfg = sk_config();
$sk_p = sk_paths();

/* ---------------- Token ---------------- */
$sk_soll = (string) $sk_cfg['aktionstoken'];
$sk_ist = isset($_GET['token']) ? (string) $_GET['token'] : '';
if ($sk_soll === '') {
    http_response_code(403);
    echo "FEHLER;OK=0;GRUND=KEIN_TOKEN_GESETZT\n";
    echo "Die Plugin-Oberflaeche wurde noch nie geoeffnet - es gibt noch kein Token.\n";
    exit;
}
if (!hash_equals($sk_soll, $sk_ist)) {
    http_response_code(403);
    echo "FEHLER;OK=0;GRUND=TOKEN\n";
    exit;
}

/* ---------------- Aktion (Weissliste) ---------------- */
$sk_lesend = array('status', 'laden', 'wartung', 'position', 'fahrzeuge', 'roh');
$sk_schaltend = array('klima_start', 'klima_stop', 'zieltemperatur', 'laden_start',
                      'laden_stop', 'ladegrenze', 'scheibe_ein', 'scheibe_aus',
                      'lueftung_start', 'lueftung_stop', 'wecken', 'abruf');
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
    if ($v === null || $v === '' || !is_numeric($v)) {
        return '-';
    }
    return (string) (0 + $v);
}

$sk_lox = sk_loxone();
$sk_alter = sk_alter();
$sk_ok = (!empty($sk_lox['ok']) && $sk_alter >= 0) ? 1 : 0;
$sk_alle = sk_fahrzeuge();

/** Findet das Fahrzeug zur laufenden Nummer oder zur VIN. */
function sk_waehlen($alle, $schluessel)
{
    if (isset($alle[$schluessel])) {
        return $alle[$schluessel];
    }
    foreach ($alle as $f) {
        if (isset($f['vin']) && strcasecmp((string) $f['vin'], (string) $schluessel) === 0) {
            return $f;
        }
    }
    return null;
}

/* ================= Lesende Aktionen ================= */

if ($sk_aktion === 'roh') {
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($sk_lox, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

if ($sk_aktion === 'fahrzeuge') {
    echo 'FAHRZEUGE;OK=' . $sk_ok . ';N=' . count($sk_alle) . ';ALTER=' . $sk_alter . "\n";
    foreach ($sk_alle as $sk_nr => $sk_f) {
        echo $sk_nr . ';' . (isset($sk_f['modell']) ? $sk_f['modell'] : '') . ';'
           . (isset($sk_f['kennzeichen']) ? $sk_f['kennzeichen'] : '') . ';'
           . (isset($sk_f['vin']) ? $sk_f['vin'] : '') . ';'
           . 'Ausfaelle=' . (isset($sk_f['ausfaelle']) && is_array($sk_f['ausfaelle'])
                             ? count($sk_f['ausfaelle']) : 0) . "\n";
    }
    exit;
}

$sk_f = sk_waehlen($sk_alle, $sk_fahrzeug);

if (in_array($sk_aktion, array('status', 'laden', 'wartung', 'position'), true) && $sk_f === null) {
    printf("%s;OK=0;GRUND=FAHRZEUG_UNBEKANNT;N=%d;ALTER=%d\n",
        strtoupper($sk_aktion), count($sk_alle), $sk_alter);
    exit;
}

/** Ein Wert aus dem Abbild, oder null. */
function sk_v($f, $name)
{
    return isset($f[$name]) ? $f[$name] : null;
}

if ($sk_aktion === 'status') {
    printf("SKODA;OK=%d;SOC=%s;TANK=%s;REICHW=%s;KM=%s;VERR=%s;TUEREN=%s;FENSTER=%s;"
         . "KOFFER=%s;HAUBE=%s;LICHT=%s;KLIMA=%s;ZIELTEMP=%s;AUSSEN=%s;WARN=%s;"
         . "ERREICH=%s;BEWEG=%s;ZUEND=%s;ALTER=%d\n",
        $sk_ok,
        sk_w(sk_v($sk_f, 'soc')), sk_w(sk_v($sk_f, 'tank_prozent')),
        sk_w(sk_v($sk_f, 'reichweite_km')), sk_w(sk_v($sk_f, 'kilometerstand')),
        sk_w(sk_v($sk_f, 'verriegelt')), sk_w(sk_v($sk_f, 'tueren_offen')),
        sk_w(sk_v($sk_f, 'fenster_offen')), sk_w(sk_v($sk_f, 'kofferraum_offen')),
        sk_w(sk_v($sk_f, 'motorhaube_offen')), sk_w(sk_v($sk_f, 'licht_an')),
        sk_w(sk_v($sk_f, 'klima_an')), sk_w(sk_v($sk_f, 'zieltemperatur')),
        sk_w(sk_v($sk_f, 'aussentemperatur')), sk_w(sk_v($sk_f, 'warnleuchten')),
        sk_w(sk_v($sk_f, 'erreichbar')), sk_w(sk_v($sk_f, 'in_bewegung')),
        sk_w(sk_v($sk_f, 'zuendung_an')), $sk_alter);
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
    printf("POSITION;OK=%d;BREITE=%s;LAENGE=%s;ALTER=%d\n",
        $sk_ok, sk_w(sk_v($sk_f, 'breite')), sk_w(sk_v($sk_f, 'laenge')), $sk_alter);
    // Die Anschrift steht in einer zweiten Zeile, damit die erste Zeile fuer
    // Loxone rein aus Zahlen besteht.
    echo 'ADRESSE;' . str_replace(array("\r", "\n", ';'), ' ',
        (string) sk_v($sk_f, 'adresse')) . "\n";
    exit;
}

/* ================= Schaltende Aktionen ================= */

if ($sk_aktion !== 'abruf' && empty($sk_cfg['steuerung_ein'])) {
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
if ($sk_erg === 0) {
    http_response_code(500);
}
printf("SET;OK=%d;AKTION=%s;MELDUNG=%s\n", $sk_erg, $sk_aktion,
    str_replace(array("\r", "\n", ';'), ' ', $sk_meldung));
