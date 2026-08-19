# The number under every assumption that could have been made

The published decline of 22.6 percent is one of 120 answers the same data
supports. Five analysis choices had to be made, none of them wrong, and each one
moves the number. All 120 are here at once.

The points come from `archive/reprocessed_2026/specification_curve.csv`, written
by `scripts/robustness.py`. `scripts/build_site_data.py` reshapes it for the
figure and changes no value.

<div id="spec-curve"></div>

## How to read it

Each combination is a point, sorted by the size of the decline. The matrix
underneath marks which choice was active at that position. Hovering a column
reads the whole specification out under the figure.

**The shape is deliberate.** It would also be possible to say that 116 of 120
show a decline, and that sentence reads as a vote among 120 independent
analyses. They are not independent. This is a full grid, every level appears in
the same number of cells, and the four exceptions all sit in one corner of it.
The curve with its choice matrix shows WHICH choice moves the number. A count
cannot.

## What the curve shows

**The season aggregate carries both extremes.** The lowest value, a decline of
-8.9 percent, and the highest, 51.9 percent, both come from summarising a season
by its median rather than its mean. The published analysis uses the mean and sits
in the quiet middle of the grid.

**The four negative values share one corner.** All four combine the measured-days
series with the split at 2022 and the median. That is a particular combination of
choices rather than scatter, and the matrix shows it.

**Significance does not follow the size of the decline.** The eight combinations
with p below 0.05 sit at the upper end, and they are not significant because the
decline is large. They are significant because the median removes the
between-season spread. With ten winters the test has so little power that the
distribution of p across this grid says more about the choice of estimator than
about the ice.

## Why the published choice looks the way it does

It was fixed before the 2026 season existed, and it has not moved. The period
boundary at 2021 was the split closest to an even cut on a nine-season record. On
ten seasons the even cut would be 2022, which gives roughly half as much decline.
Moving a boundary after seeing the new season is the thing that could not be
defended.

The reasoning behind each individual choice is in
[Limitations](limitations.md#the-result-depends-on-three-analysis-choices).
