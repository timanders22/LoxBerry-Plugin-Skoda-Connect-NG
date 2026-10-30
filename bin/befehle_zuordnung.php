<?php
/**
 * bin/befehle_zuordnung.php - Zuordnungstabelle der Befehlsbruecke, Linie Skoda Connect (Gruppe 41, 0.9.34).
 *
 * Die Befehlsbruecke (bin/befehlsbruecke.php und .sh, byte-gleich aus der Stammfassung Werkzeuge/gemeinsam/, 1.0.2)
 * abonniert <mqtt_topic>/befehl/# und gibt jeden gueltigen Befehl an tun() dieser Tabelle. tun() ruft DIESELBE
 * Funktion wie der HTTP-Endpunkt webfrontend/html/index.php - sk_befehl_annehmen() in sk_lib.php, Quelle 'mqtt'
 * (Pruefreihenfolge wie dort: Fahrzeug, Zusatzwert, Steuerung, Dienst) - und gibt array(ok, grund) fuer die
 * Quittung zurueck (sk_befehl_quittung()). Ein Token gibt es auf diesem Weg nicht; an seiner Stelle steht der
 * Haken "Befehle ueber MQTT annehmen" (befehle_mqtt_ein, ab Werk und beim Update aus; Entscheidung E4 Gruppe 41;
 * UDP 11884 ist im Heimnetz ohne Anmeldung erreichbar), und schaltende Befehle wirken nur zusammen mit
 * "Schreibende Befehle zulassen" (steuerung_ein).
 *
 * Einen zweiten Haken gibt es nicht: Skoda Connect kennt keine eingreifenden Befehle (weder Ver- noch
 * Entriegeln, weder Hupe noch Licht - MySkoda verlangt dafuer die S-PIN, die das Plugin seit 0.9.11 nicht mehr
 * fuehrt). Regeln/07 :307 "eingreifend ... nur hinter eigenem Haken" trifft nicht zu (wie Renault NG 2.1.20).
 *
 * Quittungsart "uebergeben" (E3): die Bruecke wartet nie - angenommen heisst, der Befehl liegt in der
 * Warteschlange des Dienstes. Der Dienst prueft danach ein zweites Mal (Steuerung, Entprellung gleicher Werte,
 * Stundenbremse 30/h fuer alle Wege gemeinsam, Wertgrenzen) und schreibt das Ergebnis ins Protokoll.
 *
 * Sperrzeiten (Bauvorschrift G41 G2): Sollwerte und Zustaende 0 s - die Entprellung des Dienstes (gleicher Befehl
 * mit gleichem Wert binnen 'entprellung' s, ab Werk 20) bleibt die eine Pruefung; Ereignisse (auffrischen, wecken)
 * 60 s (Vorgabe der Bruecke). Fahrzeug 1 unter <p>/befehl/<name>, Fahrzeug 2-9 unter <p>/befehl/<n>/<name>.
 * Ladegrenze 50 bis 100 % - der Bereich, den die MySkoda-App anbietet und den der Dienst prueft.
 * Die Datei setzt keine Konfiguration und schreibt nichts; wie der unangemeldete Endpunkt heilt die Bruecke
 * nichts (sk_config() liest nur).
 */
if (!function_exists('sk_befehl_annehmen')) {
    $sk_kand = array();
    $sk_kand[] = 'REPLACELBPHTMLDIR/sk_lib.php';
    $sk_kand[] = dirname(__DIR__) . '/webfrontend/html/sk_lib.php';
    if (basename(dirname(__DIR__)) === 'plugins') {
        $sk_kand[] = dirname(dirname(dirname(__DIR__))) . '/webfrontend/html/plugins/' . basename(__DIR__) . '/sk_lib.php';
    }
    foreach ($sk_kand as $sk_k) {
        if (strpos($sk_k, 'REPLACE') !== 0 && is_file($sk_k)) {
            require_once $sk_k;
            break;
        }
    }
}
$sk_grund_soll = 'Die Entprellung des Dienstes (gleicher Befehl mit gleichem Wert, ab Werk 20 s) bleibt die eine '
    . 'Pruefung; ein Sollwert darf jederzeit neu gesetzt werden (Bauvorschrift Gruppe 41, G2).';
/* Ein Befehl der Bruecke -> (Aktion des Endpunkts, Zusatzwerte) fuer sk_befehl_annehmen(). */
$sk_tun = function ($wie) {
    return function ($w, $t) use ($wie) {
        $nr = isset($t['nr']) ? (string) (int) $t['nr'] : '1';
        list($aktion, $param) = $wie((string) $w);
        if ($aktion === 'aussentemp') {
            return sk_befehl_quittung(sk_aussentemp_merken($param['wert']));
        }
        return sk_befehl_quittung(sk_befehl_annehmen($aktion, $param, $nr, 'mqtt'));
    };
};
$sk_fest = function ($a) { return function ($w) use ($a) { return array($a, array()); }; };
$sk_mit = function ($a, $feld) { return function ($w) use ($a, $feld) { return array($a, array($feld => $w)); }; };
$sk_schalter = function ($an, $aus) { return function ($w) use ($an, $aus) { return array($w === '1' ? $an : $aus, array()); }; };
/* Name => array(Art, sperre_s|null fuer die Vorgabe 60, Titel in Loxone, Kachel, Zusatz, Aufruf) */
$sk_def = array(
    'auffrischen'    => array('puls', null, 'Skoda Werte abfragen (MQTT)', 'BEFEHL.K_AUFFRISCHEN', array(), $sk_fest('abruf')),
    'laden'          => array('schalter', 0, 'Skoda Laden (MQTT)', 'BEFEHL.K_LADEN', array(), $sk_schalter('laden_start', 'laden_stop')),
    'klima_an'       => array('zahl', 0, 'Skoda Klimatisierung ein (MQTT)', 'BEFEHL.K_KLIMA_AN', array('min' => 10, 'max' => 30), $sk_mit('klima_start', 'temp')),
    'klima_aus'      => array('puls', 0, 'Skoda Klimatisierung aus (MQTT)', 'BEFEHL.K_KLIMA_AUS', array(), $sk_fest('klima_stop')),
    'zieltemperatur' => array('zahl', 0, 'Skoda Zieltemperatur (MQTT)', 'BEFEHL.K_ZIELTEMP', array('min' => 10, 'max' => 30), $sk_mit('zieltemperatur', 'temp')),
    'ladegrenze'     => array('ganz', 0, 'Skoda Ladegrenze (MQTT)', 'BEFEHL.K_LADEGRENZE', array('min' => 50, 'max' => 100), $sk_mit('ladegrenze', 'prozent')),
    'scheibe'        => array('schalter', 0, 'Skoda Scheibenheizung (MQTT)', 'BEFEHL.K_SCHEIBE', array(), $sk_schalter('scheibe_ein', 'scheibe_aus')),
    'lueftung'       => array('schalter', 0, 'Skoda Standlüftung (MQTT)', 'BEFEHL.K_LUEFTUNG', array(), $sk_schalter('lueftung_start', 'lueftung_stop')),
    'wecken'         => array('puls', null, 'Skoda Fahrzeug wecken (MQTT)', 'BEFEHL.K_WECKEN', array(), $sk_fest('wecken')),
);
$sk_befehle_mqtt = array();
foreach (array('' => '', '{nr}/' => ' Fahrzeug N') as $sk_vor => $sk_zus) {
    foreach ($sk_def as $sk_name => $sk_d) {
        $sk_e = array('art' => $sk_d[0], 'eingreifend' => false,
                      'titel' => $sk_zus === '' ? $sk_d[2] : preg_replace('/^Skoda /', 'Skoda Fahrzeug N ', $sk_d[2]),
                      'kachel' => $sk_d[3], 'quittung' => 'uebergeben', 'tun' => $sk_tun($sk_d[5]));
        if ($sk_d[1] !== null) {
            $sk_e['sperre_s'] = $sk_d[1];
            $sk_e['begruendung'] = $sk_grund_soll;
        }
        $sk_befehle_mqtt[$sk_vor . $sk_name] = $sk_e + $sk_d[4];
    }
}
/* G39 E-E4 / G41 G5: die Aussentemperatur der Hauswetterstation aus Loxone - nur einmal, gilt fuer alle
 * Fahrzeuge (Wettergrenze der Vorklimatisierung, 30 min gueltig). */
$sk_befehle_mqtt['aussentemp'] = array('art' => 'zahl', 'eingreifend' => false, 'min' => -40, 'max' => 60,
    'sperre_s' => 0, 'begruendung' => 'Ein Messwert: jeder neue Wert zaehlt, auch ein gleicher (frischt das Alter auf).',
    'titel' => 'Skoda Außentemperatur aus Loxone (MQTT)', 'kachel' => 'BEFEHL.K_AUSSENTEMP', 'quittung' => 'uebergeben',
    'tun' => $sk_tun(function ($w) { return array('aussentemp', array('wert' => $w)); }));
return array(
    'fassung' => 1,
    'linie'   => 'skodaconnect',
    'plugin'  => 'Skoda',
    'geladen' => function_exists('sk_befehl_annehmen') && function_exists('sk_befehl_quittung')
                 && function_exists('sk_config') && function_exists('sk_aussentemp_merken'),
    'einstellungen' => function () {
        $c = sk_config();   // liest nur - wie der unangemeldete Endpunkt: nichts heilen, nichts anlegen
        $p = trim((string) $c['mqtt_topic'], '/ ');
        return array('praefix'     => $p === '' ? 'skoda' : $p,
                     'annehmen'    => !empty($c['befehle_mqtt_ein']),
                     'eingreifend' => false,
                     'mqtt_ein'    => !empty($c['mqtt_ein']));
    },
    'protokoll' => function ($stufe, $text) {
        sk_log_zeile('Befehlsbruecke: ' . ($stufe === 'INFO' ? '' : $stufe . ' ') . $text);
    },
    'teile' => array('nr' => '[2-9]'),
    'befehle' => $sk_befehle_mqtt,
);
