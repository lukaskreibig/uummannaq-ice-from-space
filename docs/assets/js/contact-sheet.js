/* The contact sheet: one cell per day of the analysed window, ten seasons deep.
 *
 * FOUR LAYERS, NEVER MERGED. The cell's fill is the value the published curve
 * carries; the four lanes beneath it are who actually looked that day, one lane
 * per instrument. So a day three instruments saw reads as three marks rather
 * than as a darker cell, and nothing here averages across them, because nothing
 * in the project does: Landsat corroborates the record, it is not part of it.
 *
 * MEASURED AND FILLED ARE DRAWN APART. The curve is gap filled and smoothed, so
 * a cell can carry a value no satellite produced. Those are held apart twice
 * over: the fill drops to 38 percent, and the Sentinel-2 lane beneath it stays
 * empty. The first draft hatched them instead, which at three pixels a column
 * was static rather than a pattern. */

(function () {
  "use strict";

  const MOUNT = "contact-sheet";

  const MONTHS = [
    [53, "22. Feb"], [60, "1. Mär"], [91, "1. Apr"], [121, "1. Mai"], [152, "1. Jun"],
  ];

  const load = () =>
    ["../assets/data/", "assets/data/", "/assets/data/"].reduce(
      (chain, base) =>
        chain.catch(() =>
          fetch(base + "contact_sheet.json").then((r) => {
            if (!r.ok) throw new Error(String(r.status));
            return r.json();
          })
        ),
      Promise.reject()
    );

  const fmt = (v, digits) => (v == null ? "—" : v.toFixed(digits == null ? 2 : digits));

  /* Ice fraction to a fill. Deliberately not a rainbow: one hue, dark water to
     pale ice, so the eye reads quantity rather than category. */
  function iceFill(frac) {
    const t = Math.max(0, Math.min(1, frac));
    const water = [21, 52, 74];
    const ice = [226, 240, 246];
    const mix = water.map((c, i) => Math.round(c + (ice[i] - c) * t));
    return `rgb(${mix[0]},${mix[1]},${mix[2]})`;
  }

  function render(root, data) {
    const { start, end } = data.window;
    const span = end - start + 1;

    const bySeason = new Map();
    data.seasons.forEach((s) => bySeason.set(s, new Map()));
    data.days.forEach((d) => {
      const season = bySeason.get(d.season);
      if (season) season.set(d.doy, d);
    });

    const head = document.createElement("div");
    head.className = "sheet-months";
    head.style.gridTemplateColumns = `repeat(${span}, 1fr)`;
    MONTHS.forEach(([doy, text], i) => {
      const cell = document.createElement("span");
      const next = MONTHS[i + 1] ? MONTHS[i + 1][0] : end + 1;
      cell.style.gridColumn = `${doy - start + 1} / span ${next - doy}`;
      cell.textContent = text;
      head.appendChild(cell);
    });
    root.appendChild(head);

    const panel = document.createElement("div");
    panel.className = "day-panel";
    panel.setAttribute("aria-live", "polite");

    let selected = null;

    const layerRow = (colour, role, value, detail, absent) => {
      const row = document.createElement("div");
      row.className = "day-layer" + (absent ? " absent" : "");
      row.innerHTML =
        `<div class="bar" style="background:${absent ? "var(--md-default-fg-color--lightest)" : colour}"></div>` +
        `<div><div class="role">${role}</div>` +
        `<div class="value">${value}</div>` +
        (detail ? `<div class="detail">${detail}</div>` : "") +
        "</div>";
      return row;
    };

    function show(day) {
      panel.innerHTML = "";
      if (!day) {
        panel.innerHTML =
          '<p class="figure-note">Einen Tag anklicken. Jede Zelle ist ein Tag im ausgewerteten ' +
          "Fenster, Tag 53 bis 180, also 22. Februar bis 29. Juni.</p>";
        return;
      }

      // The picture first, then what each instrument made of it. Only days with
      // a Sentinel-2 scene have one; the file is named after the scene id so a
      // reader can trace it back to the row in summary.csv.
      const heading = document.createElement("h4");
      const when = new Date(Date.UTC(day.season, 0, day.doy));
      heading.textContent =
        when.toLocaleDateString("de-DE", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }) +
        `  ·  Tag ${day.doy}`;
      panel.appendChild(heading);

      if (day.scene) {
        const figure = document.createElement("figure");
        figure.className = "day-figure";
        const img = document.createElement("img");
        img.src = `../assets/thumbs/${day.scene.id}.webp`;
        img.alt =
          `Sentinel-2 Echtfarbaufnahme des Uummannaq-Fjords vom ${day.date}, ` +
          `Szene ${day.scene.id}`;
        img.loading = "lazy";
        img.decoding = "async";
        img.width = 320;
        img.height = 256;
        // A scene the renderer could not reach leaves no gap and no broken icon.
        img.addEventListener("error", () => figure.remove());
        const caption = document.createElement("figcaption");
        caption.textContent =
          "Sentinel-2 L1C, Echtfarbe aus B04, B03 und B02. Fester Kontrast und fester " +
          "Weißabgleich über die ganze Reihe, damit eine dunkle Saison dunkel aussieht.";
        figure.appendChild(img);
        figure.appendChild(caption);
        panel.appendChild(figure);
      }

      // layer one, the record
      const s2 = day.s2 || {};
      if (s2.measured != null) {
        const scene = day.scene;
        panel.appendChild(
          layerRow(
            "var(--layer-s2)",
            "Sentinel-2 · die Reihe",
            `${fmt(s2.measured)} Eisanteil, gemessen`,
            scene
              ? `${(scene.solid * 100).toFixed(0)} % festes Eis, ${(scene.light * 100).toFixed(0)} % ` +
                `leichtes Eis, ${(scene.water * 100).toFixed(0)} % offenes Wasser, jeweils von der ` +
                `lesbaren Fläche. Der Eisanteil oben zählt festes und leichtes Eis zusammen.<br>` +
                `${scene.id} · ${(scene.clearPct * 100).toFixed(1)} % der Fläche lesbar, ` +
                `${(scene.cloudPct * 100).toFixed(1)} % Wolke · Sonne ${scene.sunElev}° · ` +
                `${scene.usable ? "verwendet" : "vom Abdeckungstor verworfen"}`
              : null
          )
        );
      } else {
        panel.appendChild(
          layerRow(
            "var(--layer-s2)",
            "Sentinel-2 · die Reihe",
            s2.curve != null ? `${fmt(s2.curve)} in der Kurve, aber nicht gemessen` : "keine Szene",
            s2.curve != null ? "Wert aus Nachbartagen gefüllt und geglättet, keine Aufnahme an diesem Tag" : null,
            true
          )
        );
      }

      // layer two, a second optical instrument
      const ls = day.landsat;
      panel.appendChild(
        ls
          ? layerRow(
              "var(--layer-landsat)",
              "Landsat · Bestätigung",
              `${fmt(ls.ice)} Eisanteil`,
              `${ls.scene} · ${(ls.share * 100).toFixed(1)} % lesbar · Sonne ${ls.sunElev}° · ` +
                "gleiche Maske, gleiche Indizes, gleiche Schwellen. Zählt nie in die Reihe."
            )
          : layerRow("var(--layer-landsat)", "Landsat · Bestätigung", "keine Aufnahme", null, true)
      );

      // layer three, the physics
      const th = day.thermal;
      panel.appendChild(
        th
          ? layerRow(
              "var(--layer-thermal)",
              "Landsat Thermal · Physik",
              `${(th.frozenShare * 100).toFixed(0)} % der Fläche unter dem Gefrierpunkt` +
                (th.celsius != null ? `, im Mittel ${fmt(th.celsius, 1)} °C` : ""),
              th.contradicted
                ? "<strong>Widerspruch:</strong> die optische Kette nennt den Fjord überwiegend offen, " +
                  "während mehr als die Hälfte unter 271,35 K strahlt. Offenes Wasser kann nicht kälter sein."
                : th.chainSaysOpen
                ? "Die Kette nennt den Fjord offen, und das Thermometer widerspricht nicht."
                : "Die Kette nennt den Fjord nicht offen, ein Widerspruch ist hier gar nicht möglich."
            )
          : layerRow("var(--layer-thermal)", "Landsat Thermal · Physik", "keine Aufnahme", null, true)
      );

      // layer four, the adjudicator
      const sar = day.sar;
      panel.appendChild(
        sar
          ? layerRow(
              "var(--layer-sar)",
              "Sentinel-1 · Schiedsspruch",
              `<span class="verdict">${
                { "like fast ice": "wie Festeis", "like open water": "wie offenes Wasser", between: "dazwischen" }[
                  sar.verdict
                ] || sar.verdict
              }</span>`,
              // `position` is normalised against this season's own references:
              // 0 is its open water, 1 is its fast ice. It runs past both ends,
              // and often does, so the text must not claim the day sits between
              // them when it does not.
              `${fmt(sar.valueDb, 1)} dB. Auf einer Skala, auf der 0 das offene Wasser dieser Saison ` +
                `ist (${fmt(sar.waterRefDb, 1)} dB) und 1 ihr Festeis (${fmt(sar.iceRefDb, 1)} dB), ` +
                `liegt der Tag bei ${fmt(sar.position, 2)}` +
                (sar.position != null && (sar.position < 0 || sar.position > 1)
                  ? ", also jenseits der beiden Bezugswerte. "
                  : ". ") +
                (sar.verdict === "between"
                  ? "Weder das eine noch das andere, und das ist bei 13 von 27 eingeordneten Tagen die Mehrheit."
                  : "")
            )
          : layerRow("var(--layer-sar)", "Sentinel-1 · Schiedsspruch", "keine Aufnahme", null, true)
      );
    }

    data.seasons.forEach((season) => {
      const row = document.createElement("div");
      row.className = "sheet-row";

      const year = document.createElement("div");
      year.className = "sheet-year";
      year.textContent = season;
      row.appendChild(year);

      const strip = document.createElement("div");
      strip.className = "sheet-strip";
      strip.style.gridTemplateColumns = `repeat(${span}, 1fr)`;

      for (let doy = start; doy <= end; doy++) {
        const day = bySeason.get(season).get(doy);
        const cell = document.createElement("button");
        cell.type = "button";
        cell.className = "sheet-cell";

        const measured = day && day.s2 ? day.s2.measured : null;
        const curve = day && day.s2 ? day.s2.curve : null;
        const shown = measured != null ? measured : curve;

        const fill = document.createElement("div");
        fill.className = "fill";
        fill.style.background =
          shown != null ? iceFill(shown) : "var(--md-default-fg-color--lightest)";
        cell.appendChild(fill);
        cell.dataset.measured = measured != null ? "true" : "false";

        const marks = document.createElement("div");
        marks.className = "sheet-marks";
        [
          [measured != null, "var(--layer-s2)"],
          [day && day.landsat, "var(--layer-landsat)"],
          [day && day.thermal, "var(--layer-thermal)"],
          [day && day.sar, "var(--layer-sar)"],
        ].forEach(([present, colour]) => {
          const mark = document.createElement("div");
          mark.className = "sheet-mark";
          if (present) mark.style.background = colour;
          marks.appendChild(mark);
        });
        cell.appendChild(marks);

        const dateLabel = new Date(Date.UTC(season, 0, doy)).toLocaleDateString("de-DE", {
          day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
        });
        const layers = day
          ? [day.s2 && day.s2.measured != null && "Sentinel-2", day.landsat && "Landsat",
             day.thermal && "Thermal", day.sar && "Radar"].filter(Boolean)
          : [];
        cell.title = `${dateLabel}: ${layers.length ? layers.join(", ") : "keine Messung"}`;
        cell.setAttribute("aria-label", cell.title);

        if (day) {
          cell.addEventListener("click", () => {
            if (selected) selected.dataset.selected = "false";
            selected = cell;
            cell.dataset.selected = "true";
            show(day);
          });
        } else {
          cell.disabled = true;
        }
        strip.appendChild(cell);
      }

      row.appendChild(strip);
      root.appendChild(row);
    });

    const legend = document.createElement("ul");
    legend.className = "legend";
    legend.innerHTML =
      '<li><span class="chip" style="background:' + iceFill(0.95) + ';border:1px solid var(--md-default-fg-color--lighter)"></span>viel Eis</li>' +
      '<li><span class="chip" style="background:' + iceFill(0.05) + '"></span>offenes Wasser</li>' +
      '<li><span class="chip" style="background:' + iceFill(0.6) + ';opacity:0.38"></span>blass: gefüllt, nicht gemessen</li>' +
      '<li><span class="chip" style="background:var(--layer-s2)"></span>Sentinel-2 hat gemessen</li>' +
      '<li><span class="chip" style="background:var(--layer-landsat)"></span>Landsat optisch</li>' +
      '<li><span class="chip" style="background:var(--layer-thermal)"></span>Landsat thermal</li>' +
      '<li><span class="chip" style="background:var(--layer-sar)"></span>Sentinel-1 Radar</li>';
    root.appendChild(legend);
    root.appendChild(panel);

    const c = data.counts;
    const note = document.createElement("p");
    note.className = "figure-note";
    note.textContent =
      `${c.days} Tage im ausgewerteten Fenster über zehn Saisons. ` +
      `${c.s2} mit eigener Sentinel-2-Szene, ${c.landsat} mit Landsat, ${c.sar} mit Radar. ` +
      `Der Thermalkanal liegt an ${c.thermal} dieser Tage daneben; an ${c.chainSaysOpen} davon nennt die ` +
      `Kette den Fjord offen, und an ${c.contradicted} widerspricht ihm das Thermometer. ` +
      `Alle Zahlen hier gelten für das Fenster; über die ganze Reihe, auch außerhalb, sind es 226 ` +
      `verglichene Tage, 84 mit Aussage „offen" und 36 Widersprüche.`;
    root.appendChild(note);

    show(null);
  }

  function boot() {
    const root = document.getElementById(MOUNT);
    if (!root || root.dataset.rendered) return;
    root.dataset.rendered = "1";
    load()
      .then((data) => render(root, data))
      .catch(() => {
        root.innerHTML =
          '<p class="figure-note">Der Kontaktbogen konnte nicht geladen werden. ' +
          "Lokal hilft <code>python3 scripts/build_site_data.py</code>.</p>";
      });
  }

  if (document.readyState !== "loading") boot();
  else document.addEventListener("DOMContentLoaded", boot);
  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(boot);
  }
})();
