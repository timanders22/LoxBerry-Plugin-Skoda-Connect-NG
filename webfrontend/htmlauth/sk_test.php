<?php
/**
 * Skoda Connect - die Aktionen des Reiters Test
 *
 * Die Selbstpruefung beantwortet OHNE Loxone und ohne Skoda-Konto, ob die
 * Einrichtung traegt. Was sich nur mit Fahrzeug pruefen liesse, wird als
 * solches benannt statt geraten.
 */

/** Eine Zeile der Selbstpruefung. $stand: 1 = ja, 0 = nein, -1 = Hinweis. */
function sk_pruefzeile($stand, $frage, $antwort)
{
    return array('stand' => $stand, 'frage' => $frage, 'antwort' => $antwort);
}

function sk_pruefungen()
{
    $p = sk_paths();
    $cfg = sk_config();
    $z = sk_zugang();
    $zeilen = array();

    $venv = $p['bindir'] . '/venv/bin/python3';
    $zeilen[] = sk_pruefzeile(is_file($venv) ? 1 : 0, sk_t('TEST.F_VENV'),
        is_file($venv) ? $venv : sk_t('TEST.A_VENV_FEHLT'));

    // Die Fassung des Python in der venv ist die entscheidende Huerde: myskoda
    // verlangt ab 2.0.0 Python 3.13. Debian 12 liefert 3.11.
    $pyv = sk_python_fassung();
    $pyok = 0;
    if ($pyv !== '') {
        $teile = explode('.', $pyv);
        $pyok = ((int) $teile[0] > 3 || ((int) $teile[0] === 3 && (int) $teile[1] >= 13)) ? 1 : 0;
    }
    $zeilen[] = sk_pruefzeile($pyv === '' ? 0 : $pyok, sk_t('TEST.F_PYTHON'),
        $pyv !== '' ? sk_e($pyv) . ($pyok ? '' : ' &mdash; ' . sk_t('TEST.A_PYTHON_ZU_ALT'))
                    : sk_t('TEST.A_PYTHON_UNBEKANNT'));

    $fassung = sk_bibliothek_fassung();
    $zeilen[] = sk_pruefzeile($fassung !== '' ? 1 : 0, sk_t('TEST.F_LIB'),
        $fassung !== '' ? 'myskoda ' . sk_e($fassung) : sk_t('TEST.A_LIB_FEHLT'));

    $pid = sk_dienst_pid();
    $zeilen[] = sk_pruefzeile($pid > 0 ? 1 : 0, sk_t('TEST.F_DIENST'),
        $pid > 0 ? sk_t('TEST.A_DIENST_LAEUFT') . ' ' . $pid
                 : (sk_dienst_soll() ? sk_t('TEST.A_DIENST_SOLL_TOT') : sk_t('TEST.A_DIENST_GESTOPPT')));

    $zeilen[] = sk_pruefzeile($z['email'] !== '' && strpos($z['email'], '@') !== false ? 1 : 0,
        sk_t('TEST.F_KONTO'),
        $z['email'] !== '' ? sk_e($z['email']) : sk_t('TEST.A_KONTO_FEHLT'));

    // Ein Pruefknopf darf die FORM eines Geheimnisses beurteilen, nie seinen
    // Wert anzeigen.
    $zeilen[] = sk_pruefzeile($z['laenge'] > 0 ? 1 : 0, sk_t('TEST.F_PASSWORT'),
        $z['laenge'] > 0 ? sprintf(sk_t('TEST.A_PASSWORT_DA'), $z['laenge']) : sk_t('TEST.A_PASSWORT_FEHLT'));

    $rechte = is_file($p['zugang']) ? (fileperms($p['zugang']) & 0777) : -1;
    $zeilen[] = sk_pruefzeile(($rechte >= 0 && ($rechte & 0077) === 0) ? 1 : 0,
        sk_t('TEST.F_RECHTE'),
        $rechte >= 0 ? '0' . decoct($rechte) : sk_t('TEST.A_ZUGANGSDATEI_FEHLT'));

    $fahrzeuge = sk_fahrzeuge();
    $zeilen[] = sk_pruefzeile(count($fahrzeuge) > 0 ? 1 : 0, sk_t('TEST.F_FAHRZEUGE'),
        count($fahrzeuge) > 0 ? sprintf(sk_t('TEST.A_FAHRZEUGE'), count($fahrzeuge))
                              : sk_t('TEST.A_KEINE_FAHRZEUGE'));

    // Ausgefallene Einzelabrufe benennen, statt sie zu verschweigen. Ein
    // Fahrzeug, das die Klimasteuerung nicht kennt, ist kein Fehler - ein
    // stillschweigend leeres Feld dagegen schon.
    $aus = array();
    foreach ($fahrzeuge as $nr => $f) {
        if (!empty($f['ausfaelle']) && is_array($f['ausfaelle'])) {
            foreach (array_keys($f['ausfaelle']) as $name) {
                $aus[] = $nr . ':' . $name;
            }
        }
    }
    if ($aus) {
        $zeilen[] = sk_pruefzeile(0, sk_t('TEST.F_AUSFAELLE'), sk_e(implode(', ', $aus)));
    } elseif ($fahrzeuge) {
        $zeilen[] = sk_pruefzeile(1, sk_t('TEST.F_AUSFAELLE'), sk_t('TEST.A_KEINE_AUSFAELLE'));
    }

    $alter = sk_alter();
    if ($alter < 0) {
        $zeilen[] = sk_pruefzeile(0, sk_t('TEST.F_ABRUF'), sk_t('TEST.A_NIE_ABGERUFEN'));
    } else {
        $frisch = $alter <= max(600, 3 * (int) $cfg['intervall']);
        $zeilen[] = sk_pruefzeile($frisch ? 1 : 0, sk_t('TEST.F_ABRUF'),
            sprintf(sk_t('TEST.A_ABRUF_ALTER'), $alter));
    }

    $zu = sk_zustand();
    if (!empty($zu['fehler'])) {
        $zeilen[] = sk_pruefzeile(0, sk_t('TEST.F_LETZTER_FEHLER'), sk_e($zu['fehler']));
    }

    /* ZUERST der eigene Haken. Bis 0.9.12 prueste diese Stelle ausschliesslich
     * das LoxBerry-Gateway; $cfg['mqtt_ein'] - der Schalter, der bestimmt, ob
     * DIESES Plugin ueberhaupt sendet - wurde nirgends abgefragt. Bei
     * ausgeschaltetem Haken stand hier eine gruene MQTT-Zeile mit Broker und
     * UDP-Port, obwohl kein einziges Thema veroeffentlicht wurde. */
    $zeilen[] = sk_pruefzeile(!empty($cfg['mqtt_ein']) ? 1 : -1, sk_t('TEST.F_MQTT_EIN'),
        !empty($cfg['mqtt_ein'])
            ? sprintf(sk_t('TEST.A_MQTT_EIN'), sk_e($cfg['mqtt_topic']),
                      sk_t(!empty($cfg['mqtt_retain']) ? 'TEST.A_RETAIN_EIN' : 'TEST.A_RETAIN_AUS'))
            : sk_t('TEST.A_MQTT_PLUGIN_AUS'));

    /* EIN KREUZ NUR, WENN ES EINEN BETRIFFT. Berichtigt 31.08.2026.
     *
     * Bis 0.9.14 urteilte diese Zeile hart mit 0, sobald das Gateway fehlte
     * oder nicht auf Autostart stand - unabhaengig davon, ob dieses Plugin
     * ueberhaupt ueber MQTT sendet. Eine Anlage, die es bewusst nur ueber
     * HTTP anbindet, hatte damit ein dauerhaftes rotes Kreuz im Reiter Test.
     * Wer sich daran gewoehnt, uebersieht das naechste. Die Zeile darueber
     * macht es fuer denselben Sachverhalt seit 0.9.13 richtig und nimmt -1. */
    $m = sk_mqtt_zustand();
    $mqtt_noetig = !empty($cfg['mqtt_ein']);
    if (!$m['gefunden']) {
        $zeilen[] = sk_pruefzeile($mqtt_noetig ? 0 : -1, sk_t('TEST.F_MQTT'),
            sk_t('TEST.A_MQTT_NICHT_GEFUNDEN'));
    } elseif ($m['autostart']) {
        $zeilen[] = sk_pruefzeile(1, sk_t('TEST.F_MQTT'),
            sk_e($m['broker']) . ':' . sk_e($m['brokerport']) . ' (UDP ' . (int) $m['udpport'] . ')');
    } else {
        $zeilen[] = sk_pruefzeile($mqtt_noetig ? 0 : -1, sk_t('TEST.F_MQTT'),
            sk_t('TEST.A_MQTT_AUS'));
    }

    /* ---- Der eigene Cron-Eintrag ----
     *
     * ERGAENZT 31.08.2026. Das Plugin sah bis dahin nie nach, ob sein
     * Cron-Eintrag ueberhaupt da ist - und an ihm haengt alles: der Waechter,
     * der den Dienst zurueckholt, und das vierte Lebenszeichen. Ein Plugin
     * kann vollstaendig installiert dastehen, alle Pruefungen gruen, und tut
     * nichts, weil sein Eintrag an der falschen Stelle liegt.
     *
     * is_dir() ist der Befund, nicht der Erfolg: LoxBerry fuehrt in diesen
     * Ordnern nur DATEIEN aus. Und die anderen Takte werden mitgesucht, weil
     * eine frueherer Fassung ihren Rest dort gelassen haben kann. */
    $cron_takt = 'cron.01min';
    $cron_datei = $p['home'] . '/system/cron/' . $cron_takt . '/' . $p['plugin'];
    $cron_reste = array();
    foreach (array('cron.reboot', 'cron.03min', 'cron.05min', 'cron.10min',
                   'cron.15min', 'cron.30min', 'cron.hourly', 'cron.daily') as $takt) {
        if (file_exists($p['home'] . '/system/cron/' . $takt . '/' . $p['plugin'])) {
            $cron_reste[] = $takt;
        }
    }
    if (is_file($cron_datei)) {
        $zeilen[] = sk_pruefzeile(1, sk_t('TEST.F_CRON'),
            sk_e($cron_takt . '/' . $p['plugin'])
            . ($cron_reste ? ' &mdash; ' . sprintf(sk_t('TEST.A_CRON_RESTE'),
                                                   sk_e(implode(', ', $cron_reste))) : ''));
    } elseif (is_dir($cron_datei)) {
        $zeilen[] = sk_pruefzeile(0, sk_t('TEST.F_CRON'), sk_t('TEST.A_CRON_VERZEICHNIS'));
    } elseif (!is_dir($p['home'] . '/system/cron')) {
        // Kein Cron-Baum: hier ist nichts zu messen, und das ist kein Haken.
        $zeilen[] = sk_pruefzeile(-1, sk_t('TEST.F_CRON'), sk_t('TEST.A_CRON_UNKLAR'));
    } else {
        $zeilen[] = sk_pruefzeile(0, sk_t('TEST.F_CRON'),
            sprintf(sk_t('TEST.A_CRON_FEHLT'), sk_e($cron_takt))
            . ($cron_reste ? ' ' . sprintf(sk_t('TEST.A_CRON_RESTE'),
                                           sk_e(implode(', ', $cron_reste))) : ''));
    }

    /* ---- Reiter: Liste, Beschriftungen und Bereiche ----
     * Der Fall, den kein Werkzeug dieses Hauses hier gesehen hat: die Leiste
     * entsteht in einer Schleife, und hausstandard_pruefen.py sucht
     * woertliche Namen im Quelltext - es meldete einen Strich, also "nichts
     * gemessen", was sich wie "nichts zu beanstanden" liest. */
    $r = sk_reiter_lesen();
    if ($r === null || !$r['liste'] || !$r['bereiche']) {
        $zeilen[] = sk_pruefzeile(-1, sk_t('TEST.F_REITER'),
            sk_t('TEST.A_REITER_UNKLAR'));
    } else {
        $abw = array();
        $ohne_bereich = array_values(array_diff($r['liste'], $r['bereiche']));
        if ($ohne_bereich) {
            $abw[] = sprintf(sk_t('TEST.A_REITER_OHNE_BEREICH'),
                sk_e(implode(', ', $ohne_bereich)));
        }
        $ohne_liste = array_values(array_diff($r['bereiche'], $r['liste']));
        if ($ohne_liste) {
            $abw[] = sprintf(sk_t('TEST.A_REITER_OHNE_LISTE'),
                sk_e(implode(', ', $ohne_liste)));
        }
        $ohne_text = array_values(array_diff($r['liste'], $r['text']));
        if ($ohne_text) {
            $abw[] = sprintf(sk_t('TEST.A_REITER_OHNE_TEXT'),
                sk_e(implode(', ', $ohne_text)));
        }
        // Ein woertlicher Eintrag in der Leiste, den die Liste nicht kennt.
        // Heute gibt es keinen - aber wer die Schleife spaeter aufloest,
        // soll es hier erfahren und nicht am Bildschirm.
        $leiste_fremd = array_values(array_diff($r['leiste_fest'], $r['liste']));
        if ($leiste_fremd) {
            $abw[] = sprintf(sk_t('TEST.A_REITER_LEISTE_FEST'),
                sk_e(implode(', ', $leiste_fremd)));
        }
        $zeilen[] = sk_pruefzeile($abw ? 0 : 1, sk_t('TEST.F_REITER'),
            $abw ? sprintf(sk_t('TEST.A_REITER_FEHL'), implode(' ', $abw))
                 : sprintf(sk_t('TEST.A_REITER_OK'), count($r['liste'])));
    }

    $zeilen[] = sk_pruefzeile(!empty($cfg['steuerung_ein']) ? 1 : -1, sk_t('TEST.F_STEUERUNG'),
        !empty($cfg['steuerung_ein']) ? sk_t('TEST.A_STEUERUNG_EIN') : sk_t('TEST.A_STEUERUNG_AUS'));

    /* Die Konfigurationslage.
     *
     * Ein fremder Schluessel WIRKT NICHT, und genau das ueberrascht: man hat
     * etwas eingestellt, es steht in der Datei, und es tut nichts. Reste einer
     * aelteren Fassung, ein Tippfehler von Hand, oder - der teuerste Fall -
     * ein umbenannter Schluessel, dessen Uebernahme vergessen wurde. Ein
     * ABGEWIESENER Wert ist dasselbe eine Stufe weiter: der Schluessel ist
     * richtig, der Wert unbrauchbar, und es gilt die Vorgabe.
     *
     * Bis 0.9.12 nannte der Reiter Test nichts davon. */
    $lage = sk_config_lage();
    if (!$lage['fremd'] && !$lage['abgewiesen'] && !$lage['fehlend']) {
        $zeilen[] = sk_pruefzeile(1, sk_t('TEST.F_CFG_LAGE'), sk_t('TEST.A_CFG_SAUBER'));
    } else {
        $teile = array();
        if ($lage['fremd']) {
            $teile[] = sprintf(sk_t('TEST.A_CFG_FREMD'), sk_e(implode(', ', $lage['fremd'])));
        }
        if ($lage['abgewiesen']) {
            $teile[] = sprintf(sk_t('TEST.A_CFG_ABGEWIESEN'),
                               sk_e(implode(', ', $lage['abgewiesen'])));
        }
        if ($lage['fehlend']) {
            $teile[] = sprintf(sk_t('TEST.A_CFG_FEHLEND'), count($lage['fehlend']));
        }
        $zeilen[] = sk_pruefzeile($lage['fremd'] || $lage['abgewiesen'] ? 0 : -1,
                                  sk_t('TEST.F_CFG_LAGE'), implode(' ', $teile));
    }

    /* Der Wachposten. Er ist ohne Aktionstoken wirkungslos - fail closed -,
     * und dann laesst sich in dieser Oberflaeche gar nichts mehr absenden.
     * Das ist ein Zustand, den man sehen muss, nicht einen, den man erraet. */
    /* ---- Antwortet der eigene Endpunkt? ---- */
    $ep = sk_endpunkt_probe();
    if ($ep['stand'] === 1) {
        $zeilen[] = sk_pruefzeile(1, sk_t('TEST.F_ENDPUNKT'), sk_t('TEST.A_ENDPUNKT_OK'));
    } elseif ($ep['stand'] === 0) {
        $zeilen[] = sk_pruefzeile(0, sk_t('TEST.F_ENDPUNKT'),
            sprintf(sk_t('TEST.A_ENDPUNKT_FALSCH'), sk_e($ep['text'])));
    } else {
        $zeilen[] = sk_pruefzeile(-1, sk_t('TEST.F_ENDPUNKT'),
            sprintf(sk_t('TEST.A_ENDPUNKT_UNKLAR'), sk_e($ep['text'])));
    }

    /* GEZAEHLT, NICHT BEHAUPTET. Berichtigt 31.08.2026.
     *
     * Diese Zeile setzte den Haken allein daran, dass ein Merkmal gebildet
     * werden KANN - und ihr Antworttext lautet "jedes Formular dieser Seite
     * fuehrt ein Merkmal". Ueber die Formulare wurde nichts gezaehlt. Sie
     * stuende also auch dann gruen da, wenn morgen ein Formular ohne Merkmal
     * dazukaeme. Ein Formular vergisst man; das ist der ganze Grund, warum
     * der Hausstandard hier eine ZAEHLUNG verlangt.
     *
     * Gelesen wird der Quelltext der Oberflaeche, wie in sk_reiter_lesen().
     * Und die Zahl der angesehenen Stellen steht in der Antwort: eine Null
     * ist dann kein "in Ordnung", sondern der Hinweis, dass nichts gemessen
     * wurde. */
    $f = sk_formulare_lesen();
    if ($f === null || $f['formulare'] === 0) {
        $zeilen[] = sk_pruefzeile(-1, sk_t('TEST.F_WACHPOSTEN'),
            sk_t('TEST.A_WACHPOSTEN_UNKLAR'));
    } elseif (sk_formtoken() === '') {
        $zeilen[] = sk_pruefzeile(0, sk_t('TEST.F_WACHPOSTEN'), sk_t('TEST.A_WACHPOSTEN_LEER'));
    } elseif ($f['merkmal'] === $f['formulare'] && $f['activetab'] >= $f['formulare']) {
        $zeilen[] = sk_pruefzeile(1, sk_t('TEST.F_WACHPOSTEN'),
            sprintf(sk_t('TEST.A_WACHPOSTEN_OK'), $f['formulare']));
    } else {
        $zeilen[] = sk_pruefzeile(0, sk_t('TEST.F_WACHPOSTEN'),
            sprintf(sk_t('TEST.A_WACHPOSTEN_LUECKE'),
                    $f['merkmal'], $f['formulare'], $f['activetab']));
    }

    /* ---- Die Themenliste gegen den Sendecode ----
     *
     * ERGAENZT 31.08.2026. Die Tabelle im Reiter MQTT ist die ANLEITUNG: wer
     * einen virtuellen Eingang anlegt, benennt ihn danach. Laeuft sie gegen
     * den Sendecode aus, legt der Anwender Eingaenge an, die dauerhaft auf 0
     * stehen - ohne Fehlermeldung. Gelesen wird der Quelltext des Dienstes
     * statisch, und verglichen wird deshalb auch statisch: gegen die
     * VEREINIGUNG aller Zweige, nicht gegen den, der gerade laeuft. */
    $t = sk_themen_vergleich();
    if ($t === null) {
        $zeilen[] = sk_pruefzeile(-1, sk_t('TEST.F_THEMEN'), sk_t('TEST.A_THEMEN_UNKLAR'));
    } elseif (!$t['fehlend'] && !$t['ueberzaehlig']) {
        $zeilen[] = sk_pruefzeile(1, sk_t('TEST.F_THEMEN'),
            sprintf(sk_t('TEST.A_THEMEN_OK'), $t['gezaehlt']));
    } else {
        $teile = array();
        if ($t['fehlend']) {
            $teile[] = sprintf(sk_t('TEST.A_THEMEN_FEHLEND'),
                               sk_e(implode(', ', $t['fehlend'])));
        }
        if ($t['ueberzaehlig']) {
            $teile[] = sprintf(sk_t('TEST.A_THEMEN_UEBERZAEHLIG'),
                               sk_e(implode(', ', $t['ueberzaehlig'])));
        }
        $zeilen[] = sk_pruefzeile(0, sk_t('TEST.F_THEMEN'), implode(' ', $teile));
    }

    /* ---- Sind die Vorlagen wohlgeformt? ----
     *
     * ERGAENZT 31.08.2026. Eine kaputte Importdatei merkt der Anwender sonst
     * erst in Loxone Config - und dort sucht er den Fehler bei sich. Geprueft
     * wird JEDE der fuenf erzeugbaren Arten, mit dem Parser, nicht mit einem
     * Suchmuster. */
    $arten = array_keys(sk_vorlagenarten());
    $kaputt = array();
    $libxml_vorher = libxml_use_internal_errors(true);
    foreach ($arten as $art) {
        $v = sk_vorlage(1, $art);
        if (!is_array($v) || count($v) < 2 || simplexml_load_string($v[1]) === false) {
            $kaputt[] = $art;
        }
    }
    libxml_clear_errors();
    libxml_use_internal_errors($libxml_vorher);
    $zeilen[] = sk_pruefzeile($kaputt ? 0 : 1, sk_t('TEST.F_VORLAGEN'),
        $kaputt ? sprintf(sk_t('TEST.A_VORLAGEN_KAPUTT'), sk_e(implode(', ', $kaputt)))
                : sprintf(sk_t('TEST.A_VORLAGEN_OK'), count($arten)));

    return $zeilen;
}

/**
 * Welche Reiternamen kennen die Liste und die Bereiche?
 *
 * Gelesen wird der QUELLTEXT der Oberflaeche, nicht der Zustand zur Laufzeit.
 * Nur so faellt ein Bereich auf, den es in der Datei gibt und den zur Laufzeit
 * niemand oeffnet.
 *
 * Die Reiterleiste wird NICHT verglichen, und das ist keine Luecke: sie
 * entsteht in einer Schleife ueber dieselbe Liste und kann deshalb nicht
 * abweichen. Woertliche Eintraege in der Leiste - die es hier nicht gibt -
 * wuerden trotzdem auffallen; sie werden mitgelesen.
 */
function sk_reiter_lesen()
{
    $f = __DIR__ . '/index.php';
    if (!is_file($f)) {
        return null;
    }
    $t = (string) @file_get_contents($f);
    $aus = array('liste' => array(), 'text' => array(),
                 'bereiche' => array(), 'leiste_fest' => array());
    if (preg_match('/\$sk_reiter\s*=\s*array\((.*?)\);/s', $t, $m)) {
        preg_match_all("/'([a-z0-9]+)'\s*=>/", $m[1], $x);
        $aus['liste'] = $x[1];
        // Liste und Beschriftung stehen hier in EINER Tabelle - es gibt
        // nichts, was auseinanderlaufen koennte.
        $aus['text'] = $x[1];
    }
    preg_match_all('/id="tab-([a-z0-9]+)"/', $t, $z);
    $aus['bereiche'] = $z[1];
    preg_match_all('/data-ziel="tab-([a-z0-9]+)"/', $t, $y);
    $aus['leiste_fest'] = $y[1];
    return $aus;
}

/**
 * Ruft den EIGENEN Endpunkt wirklich auf - ueber 127.0.0.1, als HTTP.
 *
 * ERGAENZT 31.08.2026. Das ist die Fehlerklasse, die keine Leseprüfung sieht:
 * auf dem installierten LoxBerry liegen webfrontend/html und
 * webfrontend/htmlauth in GETRENNTEN Baeumen. Ein 'require' oder ein Pfad,
 * der im ausgepackten Archiv aufgeht, geht dort nicht auf - und der Endpunkt
 * antwortet mit HTTP 500 und leerem Rumpf. Gemerkt hat das in anderen Linien
 * niemand, weil ihn nur der Miniserver aufruft und der kein Protokoll liest.
 *
 * Gefragt wird mit ?selftest=1: das beantwortet genau die Frage, ob der
 * Endpunkt erreichbar ist und das Token stimmt, und loest keine Wirkung aus.
 *
 * DREI AUSGAENGE, nicht zwei. "Ich kann es nicht messen" darf nicht wie "in
 * Ordnung" aussehen: fehlt allow_url_fopen oder antwortet niemand auf 127.0.0.1
 * (eigener Port, Reverse Proxy), ist das ein Strich und kein Haken.
 *
 * ZWISCHENGESPEICHERT, 300 s. Ohne das ruft sich der Webserver bei jedem
 * Klick selbst auf - und weil die Oberflaeche alle Reiter mitrendert, waere
 * das JEDER Seitenaufbau.
 */
function sk_endpunkt_probe()
{
    $p = sk_paths();
    $marke = $p['datadir'] . '/endpunktprobe.json';
    $alt = sk_json_lesen($marke);
    if (isset($alt['ts']) && (time() - (int) $alt['ts']) < 300 && isset($alt['stand'])) {
        return $alt;
    }
    $token = sk_token();
    $erg = array('ts' => time(), 'stand' => -1, 'text' => '');
    if ($token === '') {
        $erg['text'] = 'kein Token';
        return $erg;
    }
    if (!function_exists('curl_init')
            && (!function_exists('file_get_contents') || !ini_get('allow_url_fopen'))) {
        $erg['text'] = 'weder curl noch allow_url_fopen';
        return $erg;
    }
    /* Der Port ist der, unter dem diese Seite gerade ausgeliefert wird -
     * geraten wird er nicht. Auf 127.0.0.1, nicht auf HTTP_HOST: die Adresse,
     * die ein Programm benutzt, und die, die ein Mensch anklickt, sind zwei
     * verschiedene Dinge. */
    $port = isset($_SERVER['SERVER_PORT']) ? (int) $_SERVER['SERVER_PORT'] : 80;
    $schema = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') ? 'https' : 'http';
    $url = $schema . '://127.0.0.1' . ($port && $port !== 80 && $port !== 443 ? ':' . $port : '')
         . '/plugins/' . $p['plugin'] . '/index.php?selftest=1&token=' . rawurlencode($token);
    if (function_exists('curl_init')) {
        /* curl meldet ueber seinen Rueckgabewert und schreibt nichts in den
         * Fehlerkanal - deshalb steht es vorn. */
        $ch = curl_init($url);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, 5);
        curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 3);
        curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
        curl_setopt($ch, CURLOPT_SSL_VERIFYHOST, 0);
        $antwort = curl_exec($ch);
        $curlfehler = curl_error($ch);
        curl_close($ch);
        if ($antwort === false) {
            $erg['text'] = $curlfehler !== '' ? $curlfehler : 'keine Antwort';
            sk_json_schreiben($marke, $erg);
            return $erg;
        }
    } else {
        $ctx = stream_context_create(array(
            'http' => array('timeout' => 5, 'ignore_errors' => true,
                            'header' => "Connection: close\r\n"),
            'ssl'  => array('verify_peer' => false, 'verify_peer_name' => false),
        ));
        /* Ein eigener Aufnehmer um genau diesen Aufruf. Das '@' allein
         * genuegt nicht: es unterdrueckt die Anzeige, ruft aber weiterhin
         * einen mit set_error_handler() eingehaengten Aufnehmer - und dann
         * steht eine WARNUNG im Protokoll, wo in Wahrheit nur die erwartete
         * Antwort ausblieb. */
        set_error_handler(function () { return true; });
        $antwort = file_get_contents($url, false, $ctx);
        restore_error_handler();
        if ($antwort === false) {
            $erg['text'] = 'keine Antwort';
            sk_json_schreiben($marke, $erg);
            return $erg;
        }
    }
    $erste = trim(strtok((string) $antwort, "\n"));
    if (strpos($erste, 'SELFTEST;OK=1') === 0) {
        $erg['stand'] = 1;
    } else {
        $erg['stand'] = 0;
    }
    $erg['text'] = substr($erste, 0, 120);
    sk_json_schreiben($marke, $erg);
    return $erg;
}

/**
 * Zaehlt die Formulare der Oberflaeche und ihre Merkmale.
 *
 * Gelesen wird der QUELLTEXT, nicht der Zustand zur Laufzeit - wie in
 * sk_reiter_lesen() und aus demselben Grund: ein Formular, das nur unter
 * einer Bedingung gerendert wird, faellt sonst durch.
 *
 * Gezaehlt werden drei Dinge, und alle drei stehen in der Antwort: die
 * oeffnenden Formularmarken mit POST-Methode, die Aufrufe des
 * Merkmalbausteins und die versteckten Reiterfelder. Die Suchmuster
 * stehen unten im Code und ABSICHTLICH nicht hier im Wortlaut: ein
 * Kommentar, der die gesuchte Form selbst traegt, wird vom Pruefwerkzeug
 * mitgezaehlt - das ist in diesem Haus schon dreimal passiert, und beim
 * Einbau dieser Funktion zum vierten Mal.
 *
 * activetab wird mit >= verglichen: der Reiterwaehler im JavaScript traegt
 * denselben Namen und zaehlt mit, ohne ein Formular zu sein.
 *
 * Rueckgabe: array oder null, wenn die Datei nicht lesbar ist.
 */
function sk_formulare_lesen()
{
    $f = __DIR__ . '/index.php';
    if (!is_file($f)) {
        return null;
    }
    $q = @file_get_contents($f);
    if ($q === false) {
        return null;
    }
    return array(
        'formulare' => preg_match_all('/<' . 'form\b[^>]*method\s*=\s*"post"/i', $q),
        'merkmal'   => preg_match_all('/sk_formfeld\s*\(/', $q),
        'activetab' => preg_match_all('/name\s*=\s*"activetab"/', $q),
    );
}

/**
 * Deckt sich die Themenliste des Reiters MQTT mit dem Sendecode?
 *
 * Die Liste ist die Anleitung. Laeuft sie gegen den Dienst aus, legt der
 * Anwender virtuelle Eingaenge an, die nie etwas empfangen - und niemand
 * bekommt eine Meldung.
 *
 * Gelesen wird bin/skoda.py statisch. Deshalb wird auch statisch verglichen:
 * gegen die VEREINIGUNG dessen, was der Code veroeffentlichen kann, nicht
 * gegen den Zweig, der bei dieser Konfiguration gerade laeuft. Eine Pruefung,
 * die statisch liest und dynamisch vergleicht, steht auf jeder normalen
 * Anlage rot.
 *
 * Rueckgabe: array('gezaehlt','fehlend','ueberzaehlig') oder null, wenn der
 * Dienst nicht lesbar ist - "nicht messbar" ist kein Haken.
 */
function sk_themen_vergleich()
{
    $p = sk_paths();
    $quelle = $p['bindir'] . '/skoda.py';
    if (!is_file($quelle)) {
        return null;
    }
    $q = @file_get_contents($quelle);
    if ($q === false || strpos($q, 'MQTT_FELDER') === false) {
        return null;
    }
    /* Die beiden Listen des Dienstes: MQTT_FELDER traegt Zahlen- und
     * Schaltwerte, MQTT_TEXTFELDER die Texte. Beide werden als Tupel von
     * Zeichenketten geschrieben. */
    $dienst = array();
    foreach (array('MQTT_FELDER', 'MQTT_TEXTFELDER') as $name) {
        if (!preg_match('/' . $name . '\s*=\s*\((.*?)\)/s', $q, $m)) {
            return null;
        }
        if (preg_match_all('/"([a-z0-9_]+)"/', $m[1], $t)) {
            $dienst = array_merge($dienst, $t[1]);
        }
    }
    if (!$dienst) {
        return null;
    }
    /* Und die Anleitung: aus sk_mqtt_themen() die Themen unterhalb von
     * fahrzeugN/ - nur die stammen aus den beiden Listen oben. Die
     * Zustandsthemen (status/...) entstehen an anderer Stelle im Dienst und
     * werden hier nicht verglichen; das steht auch in der Antwort. */
    $liste = array();
    foreach (sk_mqtt_themen() as $thema => $bedeutung) {
        if (preg_match('#^fahrzeug\{?N?\}?[0-9]*/(.+)$#', $thema, $m)) {
            $liste[] = $m[1];
        }
    }
    $liste = array_values(array_unique($liste));
    $dienst = array_values(array_unique($dienst));
    sort($liste);
    sort($dienst);
    return array(
        'gezaehlt'     => count($liste),
        'fehlend'      => array_values(array_diff($dienst, $liste)),
        'ueberzaehlig' => array_values(array_diff($liste, $dienst)),
    );
}

/**
 * Fuehrt eine Aktion des Reiters Test aus.
 * Rueckgabe: array(stand, Meldung) - stand wie bei sk_befehl_absetzen.
 */
function sk_test_aktion($aktion)
{
    $nr = isset($_POST['test_fahrzeug']) && is_string($_POST['test_fahrzeug'])
        ? (string) $_POST['test_fahrzeug'] : '1';
    if (!preg_match('/^[0-9]{1,2}$/', $nr)) {
        return array(0, sk_t('TEST.M_FAHRZEUG_UNGUELTIG'));
    }

    switch ($aktion) {
        case 'abruf':
            return sk_befehl_absetzen(array('aktion' => 'abruf'), 10);

        case 'klima_start':
            $temp = isset($_POST['test_temp']) && is_string($_POST['test_temp'])
                ? str_replace(',', '.', (string) $_POST['test_temp']) : '';
            if (!preg_match('/^[0-9]{1,2}(\.[05])?$/', $temp)) {
                return array(0, sk_t('TEST.M_TEMP_UNGUELTIG'));
            }
            return sk_befehl_absetzen(array('aktion' => 'klima_start', 'fahrzeug' => $nr, 'temp' => $temp));

        case 'klima_stop':
            return sk_befehl_absetzen(array('aktion' => 'klima_stop', 'fahrzeug' => $nr));

        /* Bis 0.9.12 fehlten diese drei. Der Endpunkt nahm sie an, der Dienst
         * fuehrte sie aus, und der Reiter Test bot sie nicht an - die
         * Standlueftung liess sich damit ueberhaupt nicht erproben, ohne
         * vorher die ganze Loxone-Anbindung zu bauen. */
        case 'zieltemperatur':
            $temp = isset($_POST['test_temp']) && is_string($_POST['test_temp'])
                ? str_replace(',', '.', (string) $_POST['test_temp']) : '';
            if (!preg_match('/^[0-9]{1,2}(\.[05])?$/', $temp)) {
                return array(0, sk_t('TEST.M_TEMP_UNGUELTIG'));
            }
            return sk_befehl_absetzen(array('aktion' => 'zieltemperatur',
                                            'fahrzeug' => $nr, 'temp' => $temp));

        case 'lueftung_start':
            return sk_befehl_absetzen(array('aktion' => 'lueftung_start', 'fahrzeug' => $nr));

        case 'lueftung_stop':
            return sk_befehl_absetzen(array('aktion' => 'lueftung_stop', 'fahrzeug' => $nr));

        case 'laden_start':
            return sk_befehl_absetzen(array('aktion' => 'laden_start', 'fahrzeug' => $nr));

        case 'laden_stop':
            return sk_befehl_absetzen(array('aktion' => 'laden_stop', 'fahrzeug' => $nr));

        case 'ladegrenze':
            $p = isset($_POST['test_prozent']) && is_string($_POST['test_prozent'])
                ? (string) $_POST['test_prozent'] : '';
            if (!preg_match('/^[0-9]{1,3}$/', $p)) {
                return array(0, sk_t('TEST.M_PROZENT_UNGUELTIG'));
            }
            return sk_befehl_absetzen(array('aktion' => 'ladegrenze', 'fahrzeug' => $nr, 'prozent' => (int) $p));

        case 'scheibe_ein':
            return sk_befehl_absetzen(array('aktion' => 'scheibe_ein', 'fahrzeug' => $nr));

        case 'scheibe_aus':
            return sk_befehl_absetzen(array('aktion' => 'scheibe_aus', 'fahrzeug' => $nr));

        case 'wecken':
            return sk_befehl_absetzen(array('aktion' => 'wecken', 'fahrzeug' => $nr));

        default:
            return array(0, sk_t('TEST.M_UNBEKANNT'));
    }
}

/**
 * Mini-SVG: Fuellstand ueber EINEN Tag (0 bis 24 h, 0 bis 100 %).
 *
 * $tag ist 'YYYYMMDD'; leer heisst heute. Bis 0.9.12 war der Tag fest auf
 * heute verdrahtet - die Tagesdateien der Vortage lagen da und wurden nie
 * angesehen, obwohl der Dienst sie so lange behaelt, wie 'verlauf_tage' sagt.
 */
function sk_soc_svg($punkte, $tag = '')
{
    $w = 720; $h = 120; $x0 = 34; $y0 = 8; $pw = $w - $x0 - 8; $ph = $h - $y0 - 20;
    $tag0 = ($tag !== '' && preg_match('/^[0-9]{8}$/', $tag))
        ? (int) strtotime(substr($tag, 0, 4) . '-' . substr($tag, 4, 2) . '-'
                          . substr($tag, 6, 2) . ' 00:00')
        : (int) strtotime('today 00:00');
    $svg = '<svg viewBox="0 0 ' . $w . ' ' . $h . '" style="width:100%;max-width:' . $w
         . 'px;height:auto;background:#fafafa;border:1px solid #e0e0e0;border-radius:8px;"'
         . ' xmlns="http://www.w3.org/2000/svg">';
    foreach (array(0, 25, 50, 75, 100) as $pct) {
        $y = $y0 + $ph - $ph * $pct / 100;
        $svg .= '<line x1="' . $x0 . '" y1="' . $y . '" x2="' . ($x0 + $pw) . '" y2="' . $y
              . '" stroke="#e5e5e5" stroke-width="1"/>';
        $svg .= '<text x="' . ($x0 - 5) . '" y="' . ($y + 3)
              . '" font-size="9" fill="#999" text-anchor="end">' . $pct . '</text>';
    }
    foreach (array(0, 6, 12, 18, 24) as $hh) {
        $x = $x0 + $pw * $hh / 24;
        $svg .= '<line x1="' . $x . '" y1="' . $y0 . '" x2="' . $x . '" y2="' . ($y0 + $ph)
              . '" stroke="#eeeeee" stroke-width="1"/>';
        $svg .= '<text x="' . $x . '" y="' . ($h - 6)
              . '" font-size="9" fill="#999" text-anchor="middle">' . $hh . ':00</text>';
    }
    $poly = array();
    foreach ($punkte as $pt) {
        $anteil = ($pt[0] - $tag0) / 86400;
        if ($anteil < 0 || $anteil > 1) {
            continue;
        }
        $poly[] = round($x0 + $pw * $anteil, 1) . ','
                . round($y0 + $ph - $ph * max(0, min(100, $pt[1])) / 100, 1);
    }
    if (count($poly) >= 2) {
        $erst = explode(',', $poly[0]);
        $letzt = explode(',', $poly[count($poly) - 1]);
        $svg .= '<polygon points="' . $erst[0] . ',' . ($y0 + $ph) . ' ' . implode(' ', $poly) . ' '
              . $letzt[0] . ',' . ($y0 + $ph) . '" fill="#6dac20" opacity="0.15"/>';
        $svg .= '<polyline points="' . implode(' ', $poly) . '" fill="none" stroke="#6dac20" stroke-width="2"/>';
        $svg .= '<circle cx="' . $letzt[0] . '" cy="' . $letzt[1] . '" r="3" fill="#6dac20"/>';
    } else {
        $svg .= '<text x="' . ($x0 + $pw / 2) . '" y="' . ($y0 + $ph / 2)
              . '" font-size="11" fill="#aaa" text-anchor="middle">'
              . sk_e(sk_t('TEST.KEINE_MESSPUNKTE')) . '</text>';
    }
    return $svg . '</svg>';
}
