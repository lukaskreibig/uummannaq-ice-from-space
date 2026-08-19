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
    [53, "22 Feb"], [60, "1 Mar"], [91, "1 Apr"], [121, "1 May"], [152, "1 Jun"],
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

    let pinned = null;      // the day a click fixed in place, if any
    let hovered = null;     // the cell the pointer is over
    let hoverTimer = null;
    let frame = null;       // the pending reposition
    let cursor = { x: 0, y: 0 };

    /* A hover is only worth a repaint once the pointer has settled. Without
       this, dragging across one season repaints 128 times and every one of them
       asks the browser for a different image. */
    const HOVER_SETTLE = 45;

    /* How far the panel sits from the pointer. Enough that it never lands under
       the cursor, which would put it between the pointer and the cell it is
       describing and start a flicker the reader cannot escape. */
    const CURSOR_GAP = 18;
    const EDGE = 12;

    /* Below this the panel stays docked under the sheet. A 340 pixel card
       floating over a 600 pixel window is not a panel, it is a takeover, and a
       touch screen has no hover to open it with anyway. */
    const FLOAT_FROM = 1100;

    const floats = () =>
      window.matchMedia(`(min-width: ${FLOAT_FROM}px)`).matches &&
      window.matchMedia("(hover: hover)").matches;

    /* Every instrument's picture sits in that instrument's own row, under that
       instrument's own number. Nothing stands in for anything else: on the 304
       days that Landsat saw and Sentinel-2 did not, the Sentinel-2 row still
       says it has no scene, and the Landsat picture appears beside the Landsat
       reading rather than in the gap above. build_site_data.py refuses to merge
       the numbers and tests assert that it cannot; a picture doing it visually
       would be the same claim by another route. */
    const figureFor = (pictures) => {
      const wrap = document.createElement("div");
      wrap.className = "layer-figures";
      let alive = 0;
      pictures.forEach((pic) => {
        const figure = document.createElement("figure");
        figure.className = "layer-figure" + (pic.pixelated ? " pixelated" : "");
        const img = document.createElement("img");
        img.src = pic.src;
        img.alt = pic.alt;
        // NOT lazy, and that is a correction rather than an oversight. The panel
        // holds one day at a time, so at most five pictures of a few kilobytes
        // each are ever in the document, and there is nothing to defer. Worse,
        // the pinned card is `position: fixed` with its own scrollbar, and
        // inside that combination the browser never decided the lower pictures
        // had come near the viewport: they answered 200 to a fetch and stayed
        // at 0 by 0 pixels forever. Four of the five rows were blank.
        img.decoding = "async";
        img.width = pic.width || 320;
        img.height = pic.height || 393;
        alive += 1;
        // A picture the renderer never reached leaves no gap and no broken
        // icon, and the last one to go takes the empty row with it.
        img.addEventListener("error", () => {
          figure.remove();
          alive -= 1;
          if (alive <= 0) wrap.remove();
        });
        figure.appendChild(img);
        if (pic.caption) {
          const cap = document.createElement("figcaption");
          cap.textContent = pic.caption;
          figure.appendChild(cap);
        }
        wrap.appendChild(figure);
      });
      return wrap;
    };

    const layerRow = (colour, role, value, detail, absent, pictures) => {
      const row = document.createElement("div");
      row.className = "day-layer" + (absent ? " absent" : "");
      row.innerHTML =
        `<div class="bar" style="background:${absent ? "var(--md-default-fg-color--lightest)" : colour}"></div>` +
        `<div><div class="role">${role}</div>` +
        `<div class="value">${value}</div>` +
        (detail ? `<div class="detail">${detail}</div>` : "") +
        "</div>";
      if (pictures && pictures.length) row.lastChild.appendChild(figureFor(pictures));
      return row;
    };

    /* `compact` is the hovered popup, which is a glance; the full form is the
       pinned panel and the docked one, which are a read. This is done in the
       rendering rather than with a CSS line clamp, because the clamp needs
       `display: -webkit-box` and Material forces `display: flow-root` on
       content elements, so the clamp applied and did nothing. Choosing what to
       draw is also testable, which a truncation is not. */
    function show(day, compact) {
      panel.innerHTML = "";
      /* The pictures turned upright when the thumbnails were corrected to the
         AOI's real 0.814 aspect, and three upright pictures stacked in a 340 px
         card come to over 900 pixels, which is the whole window. So the hovered
         card carries ONE picture, belonging to the first layer that has one,
         and it stays inside that layer's row where its label is. The pinned
         card carries all of them. That is the same bargain the text already
         makes: a glance shows less, and clicking shows everything. */
      let picturesSpent = false;
      const budget = (list) => {
        if (!list || !list.length) return null;
        if (!compact) return list;
        if (picturesSpent) return null;
        picturesSpent = true;
        return list.slice(0, 1);
      };
      if (!day) {
        panel.innerHTML =
          '<p class="figure-note">Hover a day. Every cell is one day of the analysed ' +
          "window, day 53 to 180, which is 22 February to 29 June.</p>";
        return;
      }

      // The picture first, then what each instrument made of it. Only days with
      // a Sentinel-2 scene have one; the file is named after the scene id so a
      // reader can trace it back to the row in summary.csv.
      const heading = document.createElement("h4");
      const when = new Date(Date.UTC(day.season, 0, day.doy));
      heading.textContent =
        when.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }) +
        `  ·  day ${day.doy}`;
      panel.appendChild(heading);

      // layer one, the record
      const s2 = day.s2 || {};
      if (s2.measured != null) {
        const scene = day.scene;
        /* The photograph and the decision, side by side in the pinned form.
           The class raster is the classifier's own output on the 40 m grid the
           decision was made on, 368 by 453 cells under a 1302 by 1600 image,
           and it is drawn without smoothing so that coarseness stays visible.
           That difference IS the honest picture of this method: a sharp
           photograph with a coarse grid of judgements over it. The hovered card
           shows the photograph alone, because two pictures in a glance is one
           too many. */
        const pictures = scene
          ? [
              {
                src: `../assets/thumbs/${scene.id}.webp`,
                alt:
                  `Sentinel-2 true colour quicklook of the Uummannaq fjord on ${day.date}, ` +
                  `scene ${scene.id}`,
                caption: compact ? null : "true colour, B04 B03 B02",
              },
            ]
          : [];
        if (scene && !compact) {
          pictures.push({
            src: `../assets/classes/${scene.id}.png`,
            alt:
              `The classifier's own output for ${day.date}: solid ice, light ice, open water, ` +
              "land and cloud, on the 40 m analysis grid",
            caption: "classified, 40 m grid",
            pixelated: true,
            width: 368,
            height: 453,
          });
        }
        panel.appendChild(
          layerRow(
            "var(--layer-s2)",
            "Sentinel-2 · the series",
            `ice fraction ${fmt(s2.measured)}, measured`,
            scene && compact
              ? `${(scene.solid * 100).toFixed(0)} % solid · ${(scene.light * 100).toFixed(0)} % light · ` +
                `${(scene.water * 100).toFixed(0)} % water`
              : scene
              ? `${(scene.solid * 100).toFixed(0)} percent solid ice, ${(scene.light * 100).toFixed(0)} ` +
                `percent light ice, ${(scene.water * 100).toFixed(0)} percent open water, each of the ` +
                `classified cells. The fraction above is solid and light together.<br>` +
                `${scene.id} · the scene could see ${(scene.clearPct * 100).toFixed(1)} percent of the ` +
                `fjord, ${(scene.cloudPct * 100).toFixed(1)} percent was cloud · sun ${scene.sunElev}° · ` +
                `${scene.usable ? "kept" : "dropped by the visibility gate"}`
              : null,
            false,
            budget(pictures)
          )
        );
      } else {
        panel.appendChild(
          layerRow(
            "var(--layer-s2)",
            "Sentinel-2 · the series",
            s2.curve != null ? `${fmt(s2.curve)} in the series, not measured` : "no scene",
            s2.curve != null
              ? "Gap filled from neighbouring days and smoothed. No satellite passed on this day."
              : null,
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
              "Landsat · a second opinion",
              `ice fraction ${fmt(ls.ice)}`,
              compact
                ? `classified share ${(ls.share * 100).toFixed(1)} %`
                : `${ls.scene} · classified share ${(ls.share * 100).toFixed(1)} percent · ` +
                  `sun ${ls.sunElev}° · same mask, same indices, same thresholds. Never part of the series.`,
              false,
              budget([
                {
                  src: `../assets/thumbs-landsat/${ls.scene}.webp`,
                  alt:
                    `Landsat true colour quicklook of the Uummannaq fjord on ${day.date}, ` +
                    `scene ${ls.scene}`,
                  // Its own fixed stretch and its own white balance, measured on
                  // Landsat. Sharing Sentinel-2's would invite a brightness
                  // comparison between two instruments that does not hold.
                  caption: compact ? null : "Landsat true colour, its own fixed stretch",
                },
              ])
            )
          : layerRow("var(--layer-landsat)", "Landsat · a second opinion", "no acquisition", null, true)
      );

      // layer three, the physics
      const th = day.thermal;
      panel.appendChild(
        th
          ? layerRow(
              "var(--layer-thermal)",
              "Landsat thermal · the physics",
              `${(th.frozenShare * 100).toFixed(0)} percent of the fjord below freezing` +
                (th.celsius != null ? `, ${fmt(th.celsius, 1)} °C on average` : ""),
              compact
                ? (th.contradicted ? "<strong>Contradicted.</strong>" : "")
                : th.contradicted
                ? "<strong>Contradicted.</strong> The optical chain calls the fjord mostly open while more " +
                  "than half of it radiates below 271.35 K. Open water cannot be colder than that."
                : th.chainSaysOpen
                ? "The chain calls the fjord open and the thermal band does not contradict it."
                : "The chain does not call the fjord open, so no contradiction is possible here.",
              false,
              th.scene
                ? budget([
                    {
                      src: `../assets/thumbs-thermal/${th.scene}.webp`,
                      alt:
                        `Brightness temperature of the Uummannaq fjord on ${day.date}, blue below ` +
                        "the freezing point of seawater and amber above it",
                      // The ramp is centred on 271.35 K rather than spread over
                      // the record's range, because within one scene the fjord
                      // varies by about nine kelvin while the seasons vary by
                      // forty. Spread over forty, every picture was one colour.
                      caption: compact ? null : "brightness temperature, blue is below 271.35 K",
                    },
                  ])
                : null
            )
          : layerRow("var(--layer-thermal)", "Landsat thermal · the physics", "no acquisition", null, true)
      );

      // layer four, the adjudicator
      const sar = day.sar;
      panel.appendChild(
        sar
          ? layerRow(
              "var(--layer-sar)",
              "Sentinel-1 · the verdict",
              `<span class="verdict">${
                sar.verdict
              }</span>`,
              // `position` is normalised against this season's own references:
              // 0 is its open water, 1 is its fast ice. It runs past both ends,
              // and often does, so the text must not claim the day sits between
              // them when it does not.
              compact
                ? `${fmt(sar.valueDb, 1)} dB, at ${fmt(sar.position, 2)} on this season's own scale`
                : `${fmt(sar.valueDb, 1)} dB. On a scale where 0 is this season's own open water ` +
                `(${fmt(sar.waterRefDb, 1)} dB) and 1 its own fast ice (${fmt(sar.iceRefDb, 1)} dB), ` +
                `the day sits at ${fmt(sar.position, 2)}` +
                (sar.position != null && (sar.position < 0 || sar.position > 1)
                  ? ", outside both references. "
                  : ". ") +
                (sar.verdict === "between"
                  ? "Neither one nor the other, which is 13 of the 27 days that could be placed."
                  : ""),
              false,
              // Only where one acquisition IS the verdict. On the days whose
              // value came from more than one pass, `scene` is null and the row
              // carries its numbers without a picture, rather than showing one
              // overpass as though it were the measurement.
              sar.scene
                ? budget([
                    {
                      src: `../assets/thumbs-sar/${day.date}.webp`,
                      alt:
                        `Sentinel-1 terrain corrected backscatter over the Uummannaq fjord on ` +
                        `${day.date}, scene ${sar.scene}`,
                      caption: compact ? null : "gamma0 HH in dB, fixed scale. Roughness, not brightness",
                    },
                  ])
                : null
            )
          : layerRow("var(--layer-sar)", "Sentinel-1 · the verdict", "no acquisition", null, true)
      );

      const hint = document.createElement("p");
      hint.className = "pin-hint";
      hint.textContent =
        panel.dataset.pinned === "true"
          ? "Pinned. Click again or press Escape to release."
          : "Click to pin this day and read every line.";
      panel.appendChild(hint);
    }

    function mark(cell) {
      if (hovered && hovered !== pinned) hovered.dataset.selected = "false";
      hovered = cell;
      if (cell) cell.dataset.selected = "true";
    }

    /* Place the panel beside the pointer: right of it when there is room, left
       of it when there is not, and never off the top or bottom of the window.
       Measured against the panel's real box rather than a guessed size, because
       a day with four instruments is a good deal taller than a day with one and
       a guess would clip the tall ones. */
    function place(anchor) {
      if (!panel.classList.contains("floating")) return;
      const box = panel.getBoundingClientRect();
      const room = { w: document.documentElement.clientWidth, h: window.innerHeight };

      let left = anchor.x + CURSOR_GAP;
      if (left + box.width > room.w - EDGE) {
        const flipped = anchor.x - CURSOR_GAP - box.width;
        // Only flip if the other side is genuinely roomier; on a narrow window
        // both sides overflow and shifting beats flipping into a worse corner.
        left = flipped >= EDGE ? flipped : Math.max(EDGE, room.w - EDGE - box.width);
      }

      let top = anchor.y - box.height / 2;
      top = Math.min(Math.max(EDGE, top), room.h - EDGE - box.height);

      panel.style.left = `${Math.round(left)}px`;
      panel.style.top = `${Math.round(top)}px`;
    }

    function reposition(anchor) {
      cursor = anchor;
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = null;
        place(cursor);
      });
    }

    function setFloating(on) {
      panel.classList.toggle("floating", on);
      if (!on) {
        panel.style.left = "";
        panel.style.top = "";
      }
    }

    function preview(day, cell, anchor) {
      if (pinned) return; // a pinned day owns the panel until it is unpinned
      window.clearTimeout(hoverTimer);
      if (!day) return;
      hoverTimer = window.setTimeout(() => {
        mark(cell);
        const floating = floats();
        setFloating(floating);
        show(day, floating);
        // After show(), because the panel has only just gained its content and
        // therefore its height, and the placement depends on it.
        place(anchor || cursor);
      }, HOVER_SETTLE);
    }

    function pin(day, cell, anchor) {
      window.clearTimeout(hoverTimer);
      if (pinned === cell) {
        pinned.dataset.pinned = "false";
        pinned = null;
        panel.dataset.pinned = "false";
        mark(cell);
        show(day, panel.classList.contains("floating"));
        place(anchor || cursor);
        return;
      }
      if (pinned) pinned.dataset.pinned = "false";
      if (hovered && hovered !== cell) hovered.dataset.selected = "false";
      pinned = cell;
      hovered = cell;
      cell.dataset.pinned = "true";
      cell.dataset.selected = "true";
      panel.dataset.pinned = "true";
      setFloating(floats());
      show(day, false);   // pinned is the reading form, never compact
      place(anchor || cursor);
    }

    /* Keyboard reaches the sheet through the cells themselves, and a focused
       cell has a box rather than a pointer. Anchoring to its right edge puts
       the panel where a mouse user would have found it. */
    function anchorOf(cell) {
      const r = cell.getBoundingClientRect();
      return { x: r.right, y: r.top + r.height / 2 };
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

        const dateLabel = new Date(Date.UTC(season, 0, doy)).toLocaleDateString("en-GB", {
          day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
        });
        const layers = day
          ? [day.s2 && day.s2.measured != null && "Sentinel-2", day.landsat && "Landsat",
             day.thermal && "thermal", day.sar && "radar"].filter(Boolean)
          : [];
        cell.title = `${dateLabel}: ${layers.length ? layers.join(", ") : "no measurement"}`;
        cell.setAttribute("aria-label", cell.title);

        if (day) {
          // Hovering shows, clicking pins. Sweeping across a season should read
          // like scrubbing a timeline, and the click is there for anyone who
          // wants a day to stay put while they read it.
          cell.addEventListener("pointerenter", (event) =>
            preview(day, cell, { x: event.clientX, y: event.clientY })
          );
          cell.addEventListener("pointermove", (event) => {
            if (pinned || hovered !== cell) return;
            reposition({ x: event.clientX, y: event.clientY });
          });
          cell.addEventListener("focus", () => preview(day, cell, anchorOf(cell)));
          cell.addEventListener("click", (event) =>
            pin(day, cell, { x: event.clientX, y: event.clientY })
          );
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
    // Two groups on one line, split by a rule rather than by two words: the
    // cell's fill on the left, the instruments that measured on the right. The
    // words cost 110 pixels of a 688 pixel column and the prose above already
    // says which half is which.
    legend.innerHTML =

      '<li><span class="chip" style="background:' + iceFill(0.95) + ';border:1px solid var(--md-default-fg-color--lighter)"></span>ice</li>' +
      '<li><span class="chip" style="background:' + iceFill(0.05) + '"></span>water</li>' +
      '<li><span class="chip" style="background:' + iceFill(0.6) + ';opacity:0.38"></span>gap filled</li>' +
      '<li class="divider" aria-hidden="true"></li>' +
      '<li><span class="chip" style="background:var(--layer-s2)"></span>Sentinel-2</li>' +
      '<li><span class="chip" style="background:var(--layer-landsat)"></span>Landsat</li>' +
      '<li><span class="chip" style="background:var(--layer-thermal)"></span>thermal</li>' +
      '<li><span class="chip" style="background:var(--layer-sar)"></span>radar</li>';
    root.appendChild(legend);
    root.appendChild(panel);

    // Leaving the sheet puts the floating panel away and hands the space back.
    // A pinned day survives, since pinning is the way to keep one.
    root.addEventListener("pointerleave", () => {
      window.clearTimeout(hoverTimer);
      if (pinned) return;
      if (hovered) hovered.dataset.selected = "false";
      hovered = null;
      setFloating(false);
      show(null);
    });

    // Escape releases a pin, which is the one thing a reader cannot discover by
    // pointing at something.
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || !pinned) return;
      pinned.dataset.pinned = "false";
      pinned.dataset.selected = "false";
      pinned = null;
      hovered = null;
      panel.dataset.pinned = "false";
      setFloating(false);
      show(null);
    });

    // The window can change under a pinned panel. Re-placing costs nothing and
    // stops it hanging off an edge after a resize or a scroll.
    ["resize", "scroll"].forEach((name) =>
      window.addEventListener(name, () => place(cursor), { passive: true })
    );

    const c = data.counts;
    const note = document.createElement("p");
    note.className = "figure-note";
    note.textContent =
      `${c.days} days in the analysed window across ten seasons. ` +
      `${c.s2} carry a Sentinel-2 scene of their own, ${c.landsat} a Landsat one, ${c.sar} radar. ` +
      `The thermal band sits beside ${c.thermal} of these days; on ${c.chainSaysOpen} of them the chain ` +
      `calls the fjord open, and on ${c.contradicted} the thermal band contradicts it. ` +
      `These counts are for the window. Over the whole record the comparison covers 226 days, ` +
      `84 of them called open, with 36 contradicted.`;
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
          '<p class="figure-note">The contact sheet could not be loaded. ' +
          "Locally, <code>python3 scripts/build_site_data.py</code> writes what it needs.</p>";
      });
  }

  if (document.readyState !== "loading") boot();
  else document.addEventListener("DOMContentLoaded", boot);
  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(boot);
  }
})();
