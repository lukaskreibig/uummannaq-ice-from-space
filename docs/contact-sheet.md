# Jeder Tag, jede Entscheidung

Zehn Saisons, 1280 Tage, und für jeden Tag das, was die Satelliten an ihm
gesehen haben. Die Farbe der Zelle ist der gemessene Eisanteil aus Sentinel-2.
Die drei Striche darunter sagen, welche weiteren Instrumente an diesem Tag über
dem Fjord standen. Ein Klick öffnet, was jedes von ihnen gemessen hat.

<div id="contact-sheet"></div>

## Vier Ebenen, die nicht dasselbe sind

Der naheliegende Fehler wäre, sie zu einer Reihe zu verrechnen. Sie beantworten
verschiedene Fragen.

**Sentinel-2 ist die Reihe.** Alles, was dieses Projekt veröffentlicht, kommt
von hier: NDSI und NDWI auf einem 40-Meter-Raster, mit einem Helligkeitstor,
ohne das der Index über diesem Fjord nichts trennt.

**Landsat ist eine zweite Meinung, kein zweiter Messwert.** Gleiche Landmaske,
gleiches Koordinatensystem, gleiche Indizes, gleiche Schwellen, gleiches Tor.
Nur das Instrument wechselt, und mit ihm die Optik, die Atmosphärenkorrektur und
die Wolkenmaske. Über 82 Tage, an denen beide den Fjord sahen, korrelieren die
zwei Reihen mit 0,987 bei einem RMSE von 0,078. Das macht Landsat zu einer
Bestätigung. Es macht ihn nicht zu einem Teil der Reihe, und der Bogen zählt ihn
auch nie dazu.

**Der Thermalkanal beantwortet etwas, das keine Optik kann.** Meerwasser dieses
Salzgehalts gefriert bei 271,35 Kelvin. Strahlt der Fjord kälter, kann er nicht
offen sein, gleich was der Index sagt. Über die ganze Reihe wurde das an 226
Tagen nebeneinandergelegt; 181 davon fallen in das Fenster, das dieser Bogen
zeichnet.

**Das Radar entscheidet, wenn die beiden sich widersprechen.** Rückstreuung
unterscheidet eine geschlossene Decke von einem Feld aus Schollen, was ein
Thermometer nicht kann: beide strahlen gleich kalt.

## Was man auf dem Bogen sehen kann

**Wie dünn die Reihe wirklich ist.** 543 der 1280 Tage haben eine eigene
Sentinel-2-Szene, also 42,4 Prozent. Der Rest ist gefüllt, und diese Zellen sind
schraffiert. Sie stehen in der Kurve, aber an ihnen ist kein Satellit
vorbeigekommen.

**Und wie dicht sie zusammen sind.** Landsat trägt 545 Tage bei, viele davon an
Tagen ohne Sentinel-2-Szene. Über alle Instrumente ist der Fjord an deutlich mehr
Tagen beobachtet worden, als die veröffentlichte Reihe allein zeigt.

**Wo es strittig wird.** Die Tage mit einem thermischen Widerspruch tragen alle
vier Striche und liegen auffällig oft in den späteren Saisons. Genau diese Tage
haben das Radar auf den Plan gerufen, und sein Urteil steht in der Tafel.

## Was der Bogen bewusst nicht zeigt

Vor 2017 gibt es keine Zellen, obwohl das Landsat-Archiv über diesem Fjord bis
1973 zurückreicht. Der Grund ist nicht Faulheit, sondern Kalibrierung: MSS trägt
kein kurzwelliges Infrarot, NDSI lässt sich darauf gar nicht bilden, und zwischen
TM und seinen Nachfolgern gibt es in diesem ganzen Archiv **keine einzige
gleichzeitige Aufnahme**, mit der man eine Schwelle über die Sensorgrenze tragen
könnte. Die Grenzen liegen 1999 und 2013, also genau dort, wo die Teilung einer
langen Reihe säße. Ein ungeeichter Übergang wäre von dem Trend, den er messen
soll, nicht zu unterscheiden.

Die Rechnung dazu steht in
[Landsat cross-check](landsat-crosscheck.md#how-far-back-the-archive-reaches-and-why-that-is-not-how-far-the-record-can).

!!! note "Woher die Daten kommen"

    `daily_series.csv`, `summary.csv`, `landsat_season_series.csv`,
    `thermal_audit.csv` und `sar_thermal_verdicts.csv`, alle aus
    `archive/reprocessed_2026`. `scripts/build_site_data.py` fügt sie je Tag
    zusammen, ohne einen Wert zu verändern und ohne Instrumente zu mischen.
