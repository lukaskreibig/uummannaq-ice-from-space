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

  /* Month names alone. The first slot is seven columns wide, 36 px at 736, and
     "22 Feb" needs about 40, so with wrapping it doubled the whole header band
     and with `nowrap` it ran over "1 Mar" instead. Neither is a label. This
     header orients; the window's exact ends, day 53 to 180, are in the prose
     and in the panel's own dates. */
  const MONTHS = [
    [53, "Feb"], [60, "Mar"], [91, "Apr"], [121, "May"], [152, "Jun"],
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
    /* Everything that IS the sheet in one box, so it can be lifted into the
       viewer and put back. The viewer's job is to show a day large, and a day
       is chosen on the sheet, so the sheet goes with it: moving the real one
       rather than drawing a second keeps 1280 cells, their handlers and their
       marked state as one thing that cannot drift out of step. */
    const sheetBox = document.createElement("div");
    sheetBox.className = "sheet-box";
    root.appendChild(sheetBox);
    sheetBox.appendChild(head);

    /* THE PANEL IS THE PAGE'S ANSWER TO ITS OWN TITLE, and it used to be empty.
       A contact sheet is a sheet of pictures. This one showed a heat map, a
       legend and paragraphs, and kept 1364 satellite images behind a click on a
       cell four pixels wide that nothing invited anyone to click. On a touch
       screen there was not even a hover to stumble into it with.

       So a day is on screen from the moment the page loads, with its pictures,
       and the sheet becomes what it looks like: the index into 1280 more. The
       panel never empties, never moves, and never waits to be discovered. */
    /* A div rather than a figure, and that is a layout decision, not a semantic
       one: Material sizes `figure` to its content, so the panel came out 487 px
       wide inside a 938 px column and every picture shrank to fit. It is a
       labelled region instead, which is what it actually is: something that
       changes as the reader moves, not a static illustration. */
    const panel = document.createElement("div");
    panel.className = "day-panel";
    panel.setAttribute("role", "region");
    panel.setAttribute("aria-label", "The selected day, through each instrument");
    panel.setAttribute("aria-live", "polite");

    const panelHead = document.createElement("div");
    panelHead.className = "panel-head";
    const panelTitle = document.createElement("div");
    panelTitle.className = "panel-title";
    const panelNav = document.createElement("div");
    panelNav.className = "panel-nav";

    const arrow = (label, name) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "panel-step";
      button.setAttribute("aria-label", name);
      button.textContent = label;
      panelNav.appendChild(button);
      return button;
    };
    const panelPrev = arrow("\u2039", "The day before");
    const panelNext = arrow("\u203a", "The day after");

    const panelOpen = document.createElement("button");
    panelOpen.type = "button";
    panelOpen.className = "panel-open";
    panelOpen.textContent = "open full size";
    panelNav.appendChild(panelOpen);

    panelHead.appendChild(panelTitle);
    panelHead.appendChild(panelNav);

    const panelBody = document.createElement("div");
    panelBody.className = "panel-body";
    panel.appendChild(panelHead);
    panel.appendChild(panelBody);

    /* A native dialog rather than a div, and the reasons are all things that
       would otherwise have to be written by hand and got wrong: Escape closes
       it, the page behind it goes inert so Tab cannot wander out of it, focus
       is trapped and returned to the cell that opened it, and ::backdrop is a
       real backdrop instead of a fixed overlay guessing at a z-index. */
    const viewer = document.createElement("dialog");
    viewer.className = "day-viewer";
    // Named by its own title, so the name changes with the day. A constant
    // string meant a screen reader heard "One day, and what each instrument
    // made of it" whichever day was open, and heard nothing at all when the
    // arrows moved to another one.
    viewer.setAttribute("aria-labelledby", "day-viewer-title");
    viewer.setAttribute("aria-modal", "true");

    const viewerHead = document.createElement("div");
    viewerHead.className = "viewer-head";
    const viewerTitle = document.createElement("h3");
    viewerTitle.id = "day-viewer-title";

    const viewerNav = document.createElement("div");
    viewerNav.className = "viewer-nav";
    const step = (label, name) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "viewer-step";
      button.setAttribute("aria-label", name);
      button.textContent = label;
      viewerNav.appendChild(button);
      return button;
    };
    const viewerPrev = step("\u2039", "The day before");
    const viewerNext = step("\u203a", "The day after");

    const viewerClose = document.createElement("button");
    viewerClose.type = "button";
    viewerClose.className = "viewer-close";
    viewerClose.setAttribute("aria-label", "Close");
    viewerClose.textContent = "\u00d7";
    viewerNav.appendChild(viewerClose);

    viewerHead.appendChild(viewerTitle);
    viewerHead.appendChild(viewerNav);

    /* The sheet on top, the pictures underneath, which is the page's own shape
       and the reason this is worth opening at all: the arrows walk day by day,
       but ten seasons are a place you point at. */
    const viewerSheet = document.createElement("div");
    viewerSheet.className = "viewer-sheet";

    const viewerBody = document.createElement("div");
    viewerBody.className = "viewer-body";
    viewer.appendChild(viewerHead);
    viewer.appendChild(viewerSheet);
    viewer.appendChild(viewerBody);
    root.appendChild(viewer);

    /* One function, called by every way out, rather than cleanup hung on the
       `close` event. Measured here: `viewer.close()` runs, `viewer.open` goes
       false, and no `close` event is raised, so a listener on it left the cell
       still marked as open with the dialog already gone. Whether that is a
       browser quirk or something on the page swallowing it does not matter.
       Three exits and one place that tidies up beats three exits and a promise
       that the browser will tell us. Idempotent, so the belt-and-braces
       listener below cannot undo anything twice. */
    function closeViewer() {
      const cell = opened;
      opened = null;
      if (cell) cell.dataset.opened = "false";
      // The sheet goes back where it came from, above the panel it feeds.
      if (sheetBox.parentElement === viewerSheet) root.insertBefore(sheetBox, panel);
      if (viewer.open) viewer.close();
      // The panel keeps whatever day the viewer was left on, so closing it
      // lands the reader where they were rather than where they started.
      const entry = ordered.find((e) => e.cell === cell);
      if (entry) select(entry);
      // The focus call comes AFTER the close, and the order is the whole point.
      // A modal dialog traps focus, so focusing a cell behind it while it is
      // still open silently does nothing and the reader is left at the top of
      // the document. Closing first releases the trap.
      if (cell) cell.focus();
    }

    viewerClose.addEventListener("click", closeViewer);
    // Clicking the backdrop closes it. The dialog's own box is the only child
    // that receives the click, so anything landing on the dialog element itself
    // came from outside that box.
    viewer.addEventListener("click", (event) => {
      if (event.target === viewer) closeViewer();
    });
    /* Escape, handled rather than inherited. A modal dialog is supposed to close
       itself on Escape and this one did not: the keydown reached window and
       document with defaultPrevented false, and no `cancel` event was raised at
       all. Whatever swallows it, the reader should not have to care, and one
       listener costs less than finding out. `keydown` on the dialog, so it only
       ever fires while the dialog has focus. */
    /* Escape, on the document and in the capture phase, rather than on the
       dialog. Two things forced that. A modal dialog is supposed to close
       itself on Escape and this one does not: the keydown arrives at window and
       at document with defaultPrevented false, and no `cancel` is ever raised.
       And a listener on the dialog only fires while focus is inside it, which
       is true right after opening and stops being true as soon as the reader
       clicks a picture. Capture on the document catches it wherever focus sits,
       and only while the viewer is actually open, so Material keeps Escape for
       its own search box the rest of the time. */
    document.addEventListener(
      "keydown",
      (event) => {
        if (!viewer.open) return;
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
          event.preventDefault();
          event.stopPropagation();
          stepTo(event.key === "ArrowLeft" ? -1 : 1);
          return;
        }
        if (event.key !== "Escape") return;
        event.preventDefault();
        event.stopPropagation();
        closeViewer();
      },
      true
    );

    // For any close the browser starts by itself, where one is raised.
    viewer.addEventListener("close", closeViewer);

    let opened = null;      // the cell whose day the viewer is showing

    /* Every cell in the order the sheet draws them, so the viewer can step from
       one day to the next. This is what makes the sheet usable by finger at all:
       a cell is four pixels wide in a 736 pixel column, which no thumb can aim
       at, and widening it would mean either scrolling sideways through ten
       seasons or giving up the overview that is the whole point of a contact
       sheet. So aim is not required. A tap lands within a few days, and the
       arrows walk to the exact one. */
    const ordered = [];

    let hovered = null;     // the cell the pointer is over
    let current = null;     // the entry the panel is showing
    let settleTimer = null;

    /* A hover is only worth a repaint once the pointer has settled. Without
       this, dragging across one season repaints 128 times and every one of them
       asks the browser for a different set of images. */
    const HOVER_SETTLE = 45;

    /* There is no floating card any more. It existed to spare the reader a look
       away at a panel that was empty until they hovered, which is a problem
       that stops existing once the panel is never empty. Two things showing the
       same day, one of them moving, was noise; one thing that is always in the
       same place is learnable. Everything it needed, place, reposition, flip,
       clamp, pointer-events and a settle timer, went with it.

       What remains is the one question the interaction still turns on: can this
       pointer hover at all. With hover, moving across the sheet fills the panel
       and a click means "bigger". Without it, a tap fills the panel and the
       button beside the date means "bigger", because a tap that took over the
       whole screen would make a mis-aimed finger expensive. */
    const canHover = () => window.matchMedia("(hover: hover)").matches;

    /* The long wording needs width AND height, and asking only about width got
       that wrong: at 1024 by 768, a tablet in landscape, four columns of full
       sentences came to 653 px in a 444 px strip, because the sheet above it
       had taken 207. Height is the scarce dimension once the sheet is in the
       dialog too. */
    const wideViewer = () =>
      window.matchMedia("(min-width: 1200px) and (min-height: 820px)").matches;

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
        // the old pinned card was `position: fixed` with its own scrollbar, and
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

    /* Name, picture, number, explanation, in that order, and the order is what
       makes the columns comparable. With the picture last, four instruments
       whose sentences differ in length put their quicklooks at four different
       heights, and pictures that do not line up cannot be read against each
       other, which is the only reason they are side by side. A role is always
       exactly one line, so putting the figure straight after it lands every
       picture on the same baseline without measuring anything. */
    const layerRow = (colour, role, value, detail, absent, pictures) => {
      const row = document.createElement("div");
      row.className = "day-layer" + (absent ? " absent" : "");
      const bar = document.createElement("div");
      bar.className = "bar";
      bar.style.background = absent ? "var(--md-default-fg-color--lightest)" : colour;

      const body = document.createElement("div");
      body.innerHTML = `<div class="role">${role}</div>`;
      if (pictures && pictures.length) body.appendChild(figureFor(pictures));
      const rest = document.createElement("div");
      rest.className = "layer-text";
      rest.innerHTML =
        `<div class="value">${value}</div>` +
        (detail ? `<div class="detail">${detail}</div>` : "");
      body.appendChild(rest);

      row.appendChild(bar);
      row.appendChild(body);
      return row;
    };

    /* `compact` is the hovered popup, which is a glance; the full form is the
       viewer, which is a read. This is done in the
       rendering rather than with a CSS line clamp, because the clamp needs
       `display: -webkit-box` and Material forces `display: flow-root` on
       content elements, so the clamp applied and did nothing. Choosing what to
       draw is also testable, which a truncation is not. */
    /* TWO CONTAINERS, BECAUSE THERE ARE TWO TASKS, and conflating them was the
       mistake this replaced. Hovering a cell is a GLANCE: the reader is moving
       across a season and wants to know roughly what a day was. A narrow card
       that follows the cursor is exactly right for that. Opening a day is a
       STUDY: comparing a photograph with the classifier's decision on the same
       scene, or one instrument against another. That needs width and stillness,
       and a 340 px card that moves with the pointer can give neither.
       Five upright quicklooks in it came to 1917 px of scrolling inside a 340 px
       column, each picture 134 px wide, and "pin it first" was a workaround for
       having chosen the wrong container rather than a feature. */
    /* `compact` is the panel, which is a look; the full form is the viewer,
       which is a read. Both now carry every picture the day has: the panel was
       the only reason a picture was ever withheld, and it withheld them because
       it used to be a 340 pixel card. What still differs is the words. */
    function show(day, compact, into) {
      const target = into || panelBody;
      target.innerHTML = "";
      const budget = (list) => (list && list.length ? list : null);
      if (!day) return;

      // The picture first, then what each instrument made of it. Only days with
      // a Sentinel-2 scene have one; the file is named after the scene id so a
      // reader can trace it back to the row in summary.csv.
      // The viewer states the date in its own title bar, so repeating it here
      // would spend a whole grid column on saying it twice.
      if (target === panel) {
        const heading = document.createElement("h4");
        const when = new Date(Date.UTC(day.season, 0, day.doy));
        heading.textContent =
          when.toLocaleDateString("en-GB", {
            day: "numeric",
            month: "long",
            year: "numeric",
            timeZone: "UTC",
          }) + `  ·  day ${day.doy}`;
        target.appendChild(heading);
      }

      // layer one, the record
      const s2 = day.s2 || {};
      if (s2.measured != null) {
        const scene = day.scene;
        /* The photograph and the decision, side by side in the viewer.
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
                caption: "true colour",
              },
            ]
          : [];
        // In the panel as well as the viewer. The photograph beside the decision
        // taken on it is the comparison this page exists to make, and keeping it
        // for the viewer was keeping it for the readers who found the viewer.
        if (scene) {
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
        target.appendChild(
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
        target.appendChild(
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
      target.appendChild(
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
                  caption: compact ? "Landsat true colour" : "Landsat true colour, its own fixed stretch",
                },
              ])
            )
          : layerRow("var(--layer-landsat)", "Landsat · a second opinion", "no acquisition", null, true)
      );

      // layer three, the physics
      const th = day.thermal;
      target.appendChild(
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
                      caption: compact ? "blue is below 271.35 K" : "brightness temperature, blue is below 271.35 K",
                    },
                  ])
                : null
            )
          : layerRow("var(--layer-thermal)", "Landsat thermal · the physics", "no acquisition", null, true)
      );

      // layer four, the adjudicator
      const sar = day.sar;
      target.appendChild(
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
                      caption: compact ? "gamma0 HH in dB" : "gamma0 HH in dB, fixed scale. Roughness, not brightness",
                    },
                  ])
                : null
            )
          : layerRow("var(--layer-sar)", "Sentinel-1 · the verdict", "no acquisition", null, true)
      );

    }

    /* One entry point for "this is the day now". Everything that changes the
       day goes through it: hovering, tapping, the arrows, and closing the
       viewer. */
    /* One place that answers "the day is now this", whichever surface is on
       screen. The sheet lives in the page or inside the dialog depending on
       what is open, and it fires the same events either way, so the handler
       must not care which. */
    function choose(entry) {
      if (!entry || !entry.day) return;
      select(entry);
      if (viewer.open) fillViewer(entry.day, entry.cell);
    }

    function select(entry) {
      if (!entry || !entry.day) return;
      mark(entry.cell);
      current = entry;
      const when = new Date(Date.UTC(entry.day.season, 0, entry.day.doy));
      panelTitle.textContent =
        when.toLocaleDateString("en-GB", {
          day: "numeric",
          month: "long",
          year: "numeric",
          timeZone: "UTC",
        }) + `  \u00b7  day ${entry.day.doy}`;
      show(entry.day, true);
      panelPrev.disabled = !neighbour(-1);
      panelNext.disabled = !neighbour(1);
    }

    function mark(cell) {
      if (hovered) hovered.dataset.selected = "false";
      hovered = cell;
      if (cell) cell.dataset.selected = "true";
    }

    /* Walk to the neighbouring day within the same season.
    
       `ordered` is built season by season, so a flat walk off the end of one row
       lands on the start of the next: a button labelled "the day after", pressed
       on 29 June 2017, opened 22 February 2018. Ten months away, with only the
       title bar to say so. The arrows exist to correct a tap that landed a few
       days off, and jumping a winter is not that. At the ends of a row the
       button says so by being disabled.

       The `.day` check below never fires today, because every one of the 1280
       cells in this window carries a day. It is here so that narrowing the
       window later cannot produce a viewer of four empty rows. */
    function neighbour(direction, from) {
      const anchor = from || (viewer.open ? opened : current && current.cell);
      const here = ordered.findIndex((entry) => entry.cell === anchor);
      if (here < 0) return null;
      const season = ordered[here].season;
      for (let i = here + direction; i >= 0 && i < ordered.length; i += direction) {
        if (ordered[i].season !== season) return null;
        if (ordered[i].day) return ordered[i];
      }
      return null;
    }

    function stepTo(direction) {
      choose(neighbour(direction, opened));
    }

    viewerPrev.addEventListener("click", () => stepTo(-1));
    viewerNext.addEventListener("click", () => stepTo(1));

    /* Fills the viewer with a day. Separate from opening it, because once the
       sheet is inside the dialog the reader chooses days without ever closing
       it, and calling showModal on an open dialog throws. */
    function fillViewer(day, cell) {
      if (opened && opened !== cell) opened.dataset.opened = "false";
      opened = cell;
      cell.dataset.opened = "true";
      cell.scrollIntoView({ block: "nearest", inline: "nearest" });

      const when = new Date(Date.UTC(day.season, 0, day.doy));
      viewerTitle.textContent =
        when.toLocaleDateString("en-GB", {
          day: "numeric",
          month: "long",
          year: "numeric",
          timeZone: "UTC",
        }) + `  \u00b7  day ${day.doy}`;
      /* The long wording only where four columns fit it. Below 1000 px the
         viewer falls to two columns and two rows, and the full sentences put
         195 pixels past the bottom of a 768 by 1024 tablet held upright. The
         short form is the panel's own, so what the reader gets there is
         literally the view they came from, larger, on one screen. */
      show(day, !wideViewer(), viewerBody);
      viewerBody.scrollTop = 0;
      viewerPrev.disabled = !neighbour(-1, cell);
      viewerNext.disabled = !neighbour(1, cell);
    }

    function open(day, cell) {
      if (!day) return;
      window.clearTimeout(settleTimer);
      fillViewer(day, cell);
      if (viewer.open) return;
      // The sheet moves in rather than being copied. See sheetBox.
      viewerSheet.appendChild(sheetBox);
      // No fallback branch. `<dialog>` without showModal does not exist in any
      // browser that reaches this page, and the branch that was here set the
      // `open` attribute instead, which renders the viewer as a permanently
      // visible block in the page flow: worse than not opening at all, and
      // impossible to notice because it can never run.
      viewer.showModal();
      cell.scrollIntoView({ block: "nearest", inline: "nearest" });
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

        ordered.push({ cell, day, season });

        const entry = ordered[ordered.length - 1];

        if (day) {
          /* Sweeping the sheet scrubs the panel, the way a timeline scrubs a
             video. A click means "bigger", but only where there is a hover to
             have already filled the panel: on a touch screen the tap IS the
             selection, and making every tap take over the whole screen would
             make a finger aimed at a cell five pixels wide expensive to
             mis-aim. There the button beside the date opens the viewer. */
          cell.addEventListener("pointerenter", () => {
            window.clearTimeout(settleTimer);
            settleTimer = window.setTimeout(() => choose(entry), HOVER_SETTLE);
          });
          cell.addEventListener("focus", () => choose(entry));
          cell.addEventListener("click", () => {
            window.clearTimeout(settleTimer);
            choose(entry);
            // Inside the viewer a click has already done its work: choose()
            // filled it. Outside, a click means "bigger", but only with a
            // pointer that hovered first; on touch the tap IS the selection.
            if (!viewer.open && canHover()) open(day, cell);
          });
        } else {
          cell.disabled = true;
        }
        strip.appendChild(cell);
      }

      row.appendChild(strip);
      sheetBox.appendChild(row);
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
    sheetBox.appendChild(legend);
    root.appendChild(panel);

    /* Leaving the sheet stops the sweep but does NOT empty the panel. Emptying
       it was what made this page look like it had nothing in it: the reader
       moved the mouse away and every picture went with it. The last day stays,
       only its cell stops being marked. */
    root.addEventListener("pointerleave", () => {
      window.clearTimeout(settleTimer);
      if (viewer.open) return;
      if (hovered) hovered.dataset.selected = "false";
      hovered = null;
    });

    panelPrev.addEventListener("click", () => choose(neighbour(-1)));
    panelNext.addEventListener("click", () => choose(neighbour(1)));
    panelOpen.addEventListener("click", () => {
      if (current) open(current.day, current.cell);
    });

    /* THE DAY THE PAGE OPENS ON, chosen rather than hardcoded. The richest day
       in the record is the one all four instruments saw AND disagreed about:
       the optical chain calls the fjord mostly open, the thermal band says more
       than half of it radiates below the freezing point of seawater, and the
       radar was asked to settle it. That day shows five pictures, four
       populated rows and the reason this page has four layers, which is more
       than any sentence above it manages.

       If the archive ever loses that combination the fallbacks step down in
       order rather than leaving the panel empty, because an empty panel is the
       exact failure this whole thing was rebuilt to remove. */
    const withPictures = ordered.filter((e) => e.day);
    const opening =
      withPictures.find(
        (e) =>
          e.day.scene &&
          e.day.landsat &&
          e.day.thermal &&
          e.day.thermal.contradicted &&
          (e.day.sar || {}).scene
      ) ||
      withPictures.find((e) => e.day.scene && e.day.landsat && e.day.thermal) ||
      withPictures.find((e) => e.day.scene) ||
      withPictures[0];
    if (opening) {
      select(opening);
      // Selected, not marked: nothing is under the pointer yet, and a marked
      // cell on load reads as a place the reader has already been.
      if (hovered) hovered.dataset.selected = "false";
      hovered = null;
    }

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
