# Die Zahl unter allen Annahmen

Der veröffentlichte Rückgang von 22,6 Prozent ist eine von 120 Antworten, die
sich aus derselben Datengrundlage gewinnen lassen. Fünf Auswertungsentscheidungen
mussten getroffen werden, keine davon ist falsch, und jede verschiebt die Zahl.
Hier sind alle 120 auf einmal.

<div id="spec-curve"></div>

## Wie man das liest

Oben steht jede Kombination als ein Punkt, nach Größe des Rückgangs sortiert.
Darunter zeigt die Matrix, welche Wahl an dieser Stelle aktiv war. Fährt man über
eine Spalte, liest sich die ganze Spezifikation unter der Grafik ab.

Das ist die Darstellung nach Simonsohn, Simmons und Nelson, und die Form ist
Absicht. Man könnte auch sagen „116 von 120 zeigen einen Rückgang", aber das
klingt nach einer Abstimmung unter 120 unabhängigen Auswertungen. Sie sind nicht
unabhängig: dies ist ein vollständiges Raster, jede Wahlmöglichkeit kommt in
gleich vielen Zellen vor, und die vier Ausnahmen liegen alle in derselben Ecke.
Die Kurve zeigt, **welche Wahl die Zahl bewegt**. Eine Zählung kann das nicht.

## Was die Kurve zeigt

**Das Mittelungsverfahren trägt beide Extreme.** Der niedrigste Wert, −8,9
Prozent, und der höchste, +51,9 Prozent, kommen beide aus dem Median statt dem
Mittelwert. Die veröffentlichte Auswertung nutzt den Mittelwert und liegt damit
in der ruhigen Mitte des Rasters.

**Die vier negativen Werte teilen sich eine Ecke.** Alle vier verbinden die
Reihe aus nur gemessenen Tagen mit der Teilung ab 2022 und dem Median. Das ist
keine willkürliche Streuung, sondern eine bestimmte Kombination von
Entscheidungen, und man kann sie in der Matrix ablesen.

**Signifikanz hängt nicht am Rückgang.** Die acht Kombinationen mit p unter 0,05
liegen am oberen Ende, aber sie sind nicht deshalb signifikant, weil der
Rückgang groß ist, sondern weil der Median die Streuung zwischen den Saisons
wegnimmt. Bei zehn Wintern hat der Test so wenig Trennschärfe, dass die
Verteilung der p-Werte mehr über die Wahl des Schätzers sagt als über das Eis.

## Warum die veröffentlichte Wahl so aussieht, wie sie aussieht

Sie stand fest, bevor die Saison 2026 existierte, und sie wurde nicht bewegt.
Die Periodengrenze 2021 war die Teilung, die bei neun Saisons einer geraden
Aufteilung am nächsten kam. Bei zehn Saisons wäre die gerade Teilung 2022, die
etwa halb so viel Rückgang ergibt. Eine Grenze zu verschieben, nachdem man die
neue Saison gesehen hat, wäre das, was sich nicht verteidigen ließe.

Die vollständige Begründung jeder einzelnen Wahl steht in
[Limitations](limitations.md#the-result-depends-on-three-analysis-choices).

!!! note "Woher die Daten kommen"

    `archive/reprocessed_2026/specification_curve.csv`, erzeugt von
    `scripts/robustness.py`. Die Seite liest sie über
    `scripts/build_site_data.py`, das keine Zahl verändert, sondern nur umformt.
