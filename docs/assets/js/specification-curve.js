/* The specification curve, drawn the way Simonsohn, Simmons and Nelson draw one.
 *
 * WHY THIS SHAPE AND NOT A COUNT. 116 of the 120 combinations show a decline,
 * and reporting that number alone would read as a vote among 120 independent
 * analyses. They are not independent: this is a full grid over five choices, so
 * every level appears in exactly the same number of cells, and the four
 * exceptions all sit in one corner of it. The curve plus the choice matrix
 * underneath shows which choice moves the estimate, which a count cannot.
 *
 * The reader's own analysis is marked, not hidden among the rest. */

(function () {
  "use strict";

  const MOUNT = "spec-curve";
  // Group labels sit in a 70 pixel column, so they are the short form. The
  // readout under the figure spells each choice out in full.
  const GROUPS = [
    ["series", "Series"],
    ["window", "Window"],
    ["split", "Split from"],
    ["aggregate", "Aggregate"],
    ["weighting", "Weighting"],
  ];
  const LABELS = {
    frac: "measured days only",
    frac_filled: "gap filled",
    mean: "mean",
    median: "median",
    equal: "equal",
    by_days: "by days",
  };
  const label = (value) => LABELS[value] || String(value);

  function load() {
    const bases = ["../assets/data/", "assets/data/", "/assets/data/"];
    return bases.reduce(
      (chain, base) =>
        chain.catch(() =>
          fetch(base + "specification_curve.json").then((r) => {
            if (!r.ok) throw new Error(String(r.status));
            return r.json();
          })
        ),
      Promise.reject()
    );
  }

  function render(root, data) {
    const points = data.points;
    const n = points.length;

    const rowsFor = [];
    GROUPS.forEach(([key, title]) => {
      data.choices[key].forEach((level, i) =>
        rowsFor.push({ key, level, title: i === 0 ? title : null })
      );
    });

    const PAD = { l: 178, r: 14, t: 26, b: 10 };
    const GROUP_X = 4;
    const ROW_X = 74;
    const W = 760;
    const CURVE_H = 190;
    const ROW_H = 13;
    const GAP = 18;
    const MATRIX_H = rowsFor.length * ROW_H;
    const H = PAD.t + CURVE_H + GAP + MATRIX_H + PAD.b;

    const declines = points.map((p) => p.decline);
    const lo = Math.min(0, Math.min.apply(null, declines));
    const hi = Math.max.apply(null, declines);
    const pad = (hi - lo) * 0.08;
    const yMin = lo - pad;
    const yMax = hi + pad;

    const x = (i) => PAD.l + ((i + 0.5) / n) * (W - PAD.l - PAD.r);
    const y = (v) => PAD.t + CURVE_H - ((v - yMin) / (yMax - yMin)) * CURVE_H;

    const svgns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgns, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("role", "img");
    svg.setAttribute(
      "aria-label",
      `Specification curve: ${n} analysis variants, decline from ${data.summary.min} to ` +
        `${data.summary.max} percent, median ${data.summary.median}. The published variant sits at ` +
        `${data.published ? data.published.decline : "unknown"} percent.`
    );

    const make = (name, attrs, text) => {
      const el = document.createElementNS(svgns, name);
      Object.keys(attrs).forEach((k) => el.setAttribute(k, attrs[k]));
      if (text != null) el.textContent = text;
      return el;
    };

    // y axis, including the line the sign of the result turns on
    [yMin, 0, yMax].concat([10, 20, 30, 40, 50]).forEach((v) => {
      if (v < yMin || v > yMax) return;
      const isZero = v === 0;
      svg.appendChild(
        make("line", {
          x1: PAD.l - 6,
          x2: W - PAD.r,
          y1: y(v),
          y2: y(v),
          class: isZero ? "zero-line" : "axis-line",
        })
      );
      svg.appendChild(
        make(
          "text",
          { x: PAD.l - 10, y: y(v) + 3, "text-anchor": "end", class: "tick-label" },
          (v > 0 ? "+" : "") + Math.round(v) + " %"
        )
      );
    });
    svg.appendChild(
      make(
        "text",
        { x: PAD.l - 10, y: PAD.t - 12, "text-anchor": "end", class: "spec-group-label" },
        "Decline, one point per analysis variant"
      )
    );

    const cursor = make("line", {
      x1: 0, x2: 0, y1: PAD.t, y2: PAD.t + CURVE_H + GAP + MATRIX_H,
      class: "spec-cursor", opacity: 0,
    });
    svg.appendChild(cursor);

    // the estimates
    const dots = points.map((p, i) => {
      const cls =
        "spec-dot" + (p.published ? " published" : p.p < 0.05 ? " significant" : "");
      const dot = make("circle", { cx: x(i), cy: y(p.decline), r: p.published ? 4 : 2.1, class: cls });
      svg.appendChild(dot);
      return dot;
    });

    if (data.published) {
      const i = points.indexOf(data.published);
      svg.appendChild(
        make(
          "text",
          {
            x: x(i) + 8,
            y: y(data.published.decline) - 6,
            class: "spec-row-label",
            "font-weight": "600",
          },
          `published, ${data.published.decline.toFixed(1)} %`
        )
      );
    }

    // the choice matrix
    const top = PAD.t + CURVE_H + GAP;
    const marks = [];
    rowsFor.forEach((row, r) => {
      const cy = top + r * ROW_H + ROW_H / 2;
      if (row.title) {
        svg.appendChild(
          make("text", { x: GROUP_X, y: cy + 3, class: "spec-group-label" }, row.title)
        );
      }
      svg.appendChild(
        make("text", { x: ROW_X, y: cy + 3, class: "spec-row-label" }, label(row.level))
      );
      const rowMarks = points.map((p, i) => {
        const on = String(p[row.key]) === String(row.level);
        const mark = make("rect", {
          x: x(i) - 1.4,
          y: cy - 2.6,
          width: 2.8,
          height: 5.2,
          rx: 1,
          class: "spec-mark" + (on ? " on" : ""),
          opacity: on ? 1 : 0.13,
        });
        svg.appendChild(mark);
        return mark;
      });
      marks.push(rowMarks);
    });

    // one hit target per column, so hovering anywhere in the figure reads out
    // the whole specification rather than only the dot
    const readout = document.createElement("div");
    readout.className = "readout";
    readout.setAttribute("aria-live", "polite");

    const describe = (p) =>
      [
        `${p.decline > 0 ? "+" : ""}${p.decline.toFixed(1)} % decline     p = ${p.p.toFixed(3)}` +
          (p.published ? "     the published choice" : ""),
        `Series       ${label(p.series)}`,
        `Window       day ${p.window}`,
        `Split        from ${p.split}   (${p.early} early against ${p.late} late seasons)`,
        `Aggregate    ${label(p.aggregate)}, weighted ${label(p.weighting)}`,
      ].join("\n");

    const focus = (i) => {
      points.forEach((p, k) => {
        dots[k].setAttribute("r", k === i ? 4 : p.published ? 4 : 2.1);
        dots[k].setAttribute("opacity", i === null || k === i || p.published ? 1 : 0.35);
      });
      marks.forEach((rowMarks, r) => {
        rowMarks.forEach((mark, k) => {
          const on = String(points[k][rowsFor[r].key]) === String(rowsFor[r].level);
          mark.setAttribute("opacity", on ? (i === null || k === i ? 1 : 0.35) : 0.13);
        });
      });
      if (i === null) {
        cursor.setAttribute("opacity", 0);
        readout.textContent = describe(data.published);
      } else {
        cursor.setAttribute("x1", x(i));
        cursor.setAttribute("x2", x(i));
        cursor.setAttribute("opacity", 0.55);
        readout.textContent = describe(points[i]);
      }
    };

    /* Held is a specification the reader chose rather than one they swept over.
       Without it this figure was unreadable on a tablet: the only ways in were
       mouseenter and focus, so a device with no pointer to hover could not read
       a single specification, on a page that promises hovering a column reads
       it out. A tap now holds a column, and a sweep still previews one. */
    let held = null;

    const showing = () => (held === null ? null : held);

    points.forEach((p, i) => {
      const hit = make("rect", {
        x: PAD.l + (i / n) * (W - PAD.l - PAD.r),
        y: PAD.t,
        width: (W - PAD.l - PAD.r) / n,
        height: CURVE_H + GAP + MATRIX_H,
        class: "spec-hit",
      });
      hit.addEventListener("mouseenter", () => {
        if (held === null) focus(i);
      });
      hit.addEventListener("focus", () => focus(i));
      hit.addEventListener("click", () => {
        held = held === i ? null : i;
        focus(showing());
      });
      hit.setAttribute("tabindex", "0");
      svg.appendChild(hit);
    });
    svg.addEventListener("mouseleave", () => {
      if (held === null) focus(null);
    });

    /* One column is six pixels wide in a 736 pixel figure, which no finger can
       aim at and no reader should have to. The arrows walk the grid, so landing
       near the right specification is enough. They also give the figure a
       keyboard route that does not depend on tabbing through 120 rectangles. */
    function stepSpec(direction) {
      const from = held === null ? points.findIndex((q) => q.published) : held;
      const next = Math.min(points.length - 1, Math.max(0, from + direction));
      held = next;
      focus(next);
    }

    const shell = document.createElement("div");
    shell.className = "chart-shell";
    shell.appendChild(svg);
    root.appendChild(shell);

    const legend = document.createElement("ul");
    legend.className = "legend";
    legend.innerHTML =
      '<li><span class="chip" style="background:var(--layer-thermal)"></span>the published choice</li>' +
      '<li><span class="chip" style="background:var(--md-accent-fg-color)"></span>p &lt; 0,05</li>' +
      '<li><span class="chip" style="background:var(--md-default-fg-color--light)"></span>all the rest</li>';
    root.appendChild(legend);
    const specNav = document.createElement("div");
    specNav.className = "spec-nav";
    [
      ["\u2039", "The specification to the left", -1],
      ["\u203a", "The specification to the right", 1],
    ].forEach(([label, name, direction]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "spec-step";
      button.setAttribute("aria-label", name);
      button.textContent = label;
      button.addEventListener("click", () => stepSpec(direction));
      specNav.appendChild(button);
    });
    const release = document.createElement("button");
    release.type = "button";
    release.className = "spec-step spec-release";
    release.textContent = "back to the published choice";
    release.addEventListener("click", () => {
      held = null;
      focus(null);
    });
    specNav.appendChild(release);

    root.appendChild(specNav);
    root.appendChild(readout);

    const s = data.summary;
    const note = document.createElement("p");
    note.className = "figure-note";
    note.textContent =
      `${s.n} combinations of five choices, computed in full. ` +
      `Decline from ${s.min.toFixed(1)} to ${s.max.toFixed(1)} percent, median ${s.median.toFixed(1)}. ` +
      `${s.declining} show a decline, ${s.n - s.declining} do not. ` +
      `The published choice ranks ${s.publishedRank} of ${s.n}.`;
    root.appendChild(note);

    focus(null);
  }

  function boot() {
    const root = document.getElementById(MOUNT);
    if (!root || root.dataset.rendered) return;
    root.dataset.rendered = "1";
    load()
      .then((data) => render(root, data))
      .catch(() => {
        root.innerHTML =
          '<p class="figure-note">The specification curve data could not be loaded. ' +
          "Locally, <code>python3 scripts/build_site_data.py</code> writes what it needs.</p>";
      });
  }

  if (document.readyState !== "loading") boot();
  else document.addEventListener("DOMContentLoaded", boot);
  // Material swaps page content without a reload when instant navigation is on
  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(boot);
  }
})();
