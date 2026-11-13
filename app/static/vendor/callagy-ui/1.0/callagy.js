/*!
 * Callagy UI kit 1.0 — callagy.js
 * Behaviour for the kit's components. Plain JavaScript, no framework, no build step.
 * Needs callagy.css. Charts also need vendor/echarts/echarts.min.js loaded first; the US map also needs maps/us-states.js.
 * Everything is on one global: window.CUI. Nothing here writes page data as HTML: text is set with textContent,
 * and the few HTML strings (chart tooltips) escape every value first.
 */
(function (global) {
  "use strict";

  var CUI = { version: "1.0" };
  var doc = global.document;
  var reducedQuery = global.matchMedia ? global.matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };
  /** Motion is on by default, even with Windows animation effects off. Only a page that sets
   *  <html data-cui-motion="system"> follows the Windows setting. */
  function motionOff() { return doc.documentElement.getAttribute("data-cui-motion") === "system" && !!reducedQuery.matches; }
  CUI.motionOn = function () { return !motionOff(); };

  /* ---------------------------------------------------------------- helpers */

  function el(tag, attrs, kids) {
    var e = doc.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === undefined || v === null || v === false) return;
        if (k === "class") e.className = v;
        else if (k === "text") e.textContent = v;
        else if (k.slice(0, 2) === "on" && typeof v === "function") e.addEventListener(k.slice(2), v);
        else e.setAttribute(k, v === true ? "" : String(v));
      });
    }
    (kids || []).forEach(function (c) { if (c != null) e.appendChild(typeof c === "string" ? doc.createTextNode(c) : c); });
    return e;
  }
  function $(sel, root) { return typeof sel === "string" ? (root || doc).querySelector(sel) : sel; }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function debounce(fn, ms) {
    var t;
    return function () { var a = arguments, self = this; clearTimeout(t); t = setTimeout(function () { fn.apply(self, a); }, ms); };
  }
  var uid = 0;
  function nextId(prefix) { uid += 1; return (prefix || "cui") + "-" + uid; }
  function store(key, value) {
    try {
      if (value === undefined) return global.localStorage.getItem(key);
      global.localStorage.setItem(key, value);
    } catch (e) { return null; }
    return null;
  }
  // Fixed icons (constant markup, never data)
  var ICONS = {
    up: '<svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><path d="M6 2l4.5 6h-9z" fill="currentColor"/></svg>',
    down: '<svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><path d="M6 10L1.5 4h9z" fill="currentColor"/></svg>',
    flat: '<svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><rect x="2" y="5" width="8" height="2" rx="1" fill="currentColor"/></svg>',
    close: '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    caret: '<svg class="cui-select__caret" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    search: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M10.5 10.5L14 14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    sort: '<svg class="cui-table__arrow" viewBox="0 0 12 12" aria-hidden="true"><path d="M6 2.5l3.5 4.5h-7z" fill="currentColor"/></svg>',
    download: '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M8 2v8M4.5 6.5L8 10l3.5-3.5M3 13h10" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    warn: '<svg class="cui-banner__icon" viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2.5l8 14H2z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M10 8v4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="10" cy="14.6" r="1.1" fill="currentColor"/></svg>',
    empty: '<svg class="cui-empty__icon" viewBox="0 0 40 40" aria-hidden="true"><rect x="6" y="9" width="28" height="22" rx="4" fill="none" stroke="currentColor" stroke-width="2"/><path d="M6 17h28M14 9v22" stroke="currentColor" stroke-width="2"/></svg>',
    error: '<svg class="cui-error__icon" viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="20" r="15" fill="none" stroke="currentColor" stroke-width="2.5"/><path d="M20 12v10" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/><circle cx="20" cy="27.5" r="1.8" fill="currentColor"/></svg>'
  };
  function icon(name) { var s = doc.createElement("span"); s.innerHTML = ICONS[name]; return s.firstChild; }

  /* ---------------------------------------------------------------- formats (one of each, used everywhere) */

  var MISSING = "—";      // —
  var MINUS = "−";        // −
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function isNum(v) { return typeof v === "number" && isFinite(v); }
  function trim0(s) { return s.replace(/\.0$/, ""); }

  var fmt = {
    /** 1234.5 -> "1,235" (decimals optional) */
    num: function (v, decimals) {
      if (!isNum(v)) return MISSING;
      var d = decimals || 0;
      var s = Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
      return (v < 0 && s.replace(/[0.,]/g, "") !== "" ? MINUS : "") + s;
    },
    /** 1234567 -> "$1.2M", 45000 -> "$45K", 4500 -> "$4.5K", 950 -> "$950" */
    money: function (v) {
      if (!isNum(v)) return MISSING;
      var a = Math.abs(v), s;
      if (Math.round(a / 1e8) >= 10) s = (a / 1e9).toFixed(1) + "B";
      else if (Math.round(a / 1e5) >= 10) s = (a / 1e6).toFixed(1) + "M";
      else if (a >= 9999.5) s = Math.round(a / 1e3) + "K";
      else if (a >= 999.5) s = trim0((a / 1e3).toFixed(1)) + "K";
      else s = String(Math.round(a));
      if (s === "1000K") s = "1.0M";
      return (v < 0 && s !== "0" ? MINUS : "") + "$" + s;
    },
    /** 0.4532 -> "45.3%" (takes a fraction) */
    pct: function (v) {
      if (!isNum(v)) return MISSING;
      var s = (Math.abs(v) * 100).toFixed(1);
      return (v < 0 && s !== "0.0" ? MINUS : "") + s + "%";
    },
    /** "2026-11-10", "2026-11-10T08:30:00", or a Date -> "10 Nov 2026" */
    date: function (v) {
      var d = toDate(v);
      return d ? d.getDate() + " " + MONTHS[d.getMonth()] + " " + d.getFullYear() : MISSING;
    }
  };
  fmt.missing = MISSING;
  /** A date-only string is read as a local date (never shifted a day by time zones). */
  function toDate(v) {
    if (v instanceof Date) return isNaN(v) ? null : v;
    if (typeof v !== "string" || !v) return null;
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
    if (m) return new Date(+m[1], +m[2] - 1, +m[3]);
    var d = new Date(v);
    return isNaN(d) ? null : d;
  }
  function formatter(f) {
    if (typeof f === "function") return f;
    if (f && fmt[f]) return fmt[f];
    return fmt.num;
  }
  /** Change since last period: money and numbers get a sign; percentages change in points. */
  function formatChange(v, f) {
    if (!isNum(v)) return MISSING;
    var sign = v > 0 ? "+" : v < 0 ? MINUS : "";
    if (f === "pct") return sign + Math.abs(v * 100).toFixed(1) + " pts";
    var s = formatter(f)(Math.abs(v));
    return sign + s;
  }
  CUI.fmt = fmt;

  /** Working days (Mon to Fri) after `from` up to and including `to`. */
  function workingDaysBetween(from, to) {
    var a = toDate(from), b = toDate(to);
    if (!a || !b) return null;
    a = new Date(a.getFullYear(), a.getMonth(), a.getDate());
    b = new Date(b.getFullYear(), b.getMonth(), b.getDate());
    var n = 0, step = a < b ? 1 : -1;
    while (a.getTime() !== b.getTime()) {
      a.setDate(a.getDate() + step);
      var wd = a.getDay();
      if (wd !== 0 && wd !== 6) n += step;
    }
    return n;
  }
  CUI.workingDaysBetween = workingDaysBetween;

  /* ---------------------------------------------------------------- URL hash: "#tab=win&c=123" */

  CUI.hash = {
    get: function () {
      var h = global.location.hash.replace(/^#/, "");
      var out = {};
      if (!h) return out;
      if (h.indexOf("=") < 0) { out.tab = decodeURIComponent(h); return out; }
      h.split("&").forEach(function (p) {
        var i = p.indexOf("=");
        if (i > 0) out[decodeURIComponent(p.slice(0, i))] = decodeURIComponent(p.slice(i + 1));
      });
      return out;
    },
    /** Sets the hash. push=true adds a Back-button step; otherwise the current step is replaced. */
    set: function (obj, push) {
      var s = Object.keys(obj).filter(function (k) { return obj[k] != null && obj[k] !== ""; })
        .map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(obj[k]); }).join("&");
      var url = global.location.pathname + global.location.search + (s ? "#" + s : "");
      try { global.history[push ? "pushState" : "replaceState"](null, "", url); }
      catch (e) { global.location.hash = s; }
    }
  };

  /* ---------------------------------------------------------------- header: "data as of" chip and old-data banner */

  /**
   * CUI.header(headerEl, { asOf: "2026-11-10", expectedEveryDays: 1 })
   * Puts "Data as of 10 Nov 2026" in the header and, when the data is older than expected (in working days),
   * turns the chip amber and adds a banner under the header.
   */
  CUI.header = function (header, opts) {
    header = $(header);
    var meta = header.querySelector(".cui-header__meta") || header.appendChild(el("div", { "class": "cui-header__meta" }));
    var chip = meta.querySelector("[data-cui-asof]") || meta.insertBefore(el("span", { "class": "cui-chip", "data-cui-asof": "" }), meta.firstChild);
    var bannerId = (header.id || "cui-header") + "-stale";
    function update(o) {
      opts = Object.assign({}, opts, o);
      var old = doc.getElementById(bannerId);
      if (old) old.remove();
      if (!opts.asOf) { chip.className = "cui-chip cui-chip--bad"; chip.textContent = "No data date"; return; }
      var age = workingDaysBetween(opts.asOf, opts.today || new Date());
      var every = opts.expectedEveryDays || 1;
      var stale = age !== null && age > every;
      chip.className = "cui-chip" + (stale ? " cui-chip--stale" : "");
      chip.textContent = "Data as of " + fmt.date(opts.asOf);
      if (stale) {
        var text = el("div", { "class": "cui-banner__text" }, [
          el("strong", { text: "This data may be out of date. " }),
          "It is from " + fmt.date(opts.asOf) + ", " + age + " working days ago. It is normally updated " +
            (every === 1 ? "every working day" : "every " + every + " working days") + "." +
            (opts.staleNote ? " " + opts.staleNote : "")
        ]);
        var banner = el("div", { "class": "cui-banner cui-banner--warn cui-banner--page", id: bannerId, role: "status" }, [icon("warn"), text]);
        header.insertAdjacentElement("afterend", banner);
      }
    }
    update();
    return { update: update };
  };

  /* ---------------------------------------------------------------- skeletons */

  function skelBlock(cls) { return el("span", { "class": "cui-skel " + cls }); }
  function skelCard(kids) { return el("div", { "class": "cui-card" }, [el("div", { "class": "cui-card__body" }, kids)]); }
  var SKELETONS = {
    tiles: function (n) {
      var g = el("div", { "class": "cui-skeleton__tiles", style: "--cui-cols:" + (n || 4) });
      for (var i = 0; i < (n || 4); i++) {
        g.appendChild(el("div", { "class": "cui-tile" }, [skelBlock("cui-skel--line cui-skel--short"), skelBlock("cui-skel--value"), skelBlock("cui-skel--line cui-skel--short")]));
      }
      return g;
    },
    chart: function () { return skelCard([skelBlock("cui-skel--title"), skelBlock("cui-skel--chart")]); },
    table: function (n) {
      var kids = [skelBlock("cui-skel--title")];
      for (var i = 0; i < (n || 8); i++) kids.push(skelBlock("cui-skel--row"));
      return skelCard(kids);
    },
    lines: function (n) {
      var kids = [];
      for (var i = 0; i < (n || 3); i++) kids.push(skelBlock("cui-skel--line" + (i === (n || 3) - 1 ? " cui-skel--short" : "")));
      return skelCard(kids);
    },
    card: function () { return skelCard([skelBlock("cui-skel--title"), skelBlock("cui-skel--line"), skelBlock("cui-skel--line"), skelBlock("cui-skel--line cui-skel--short")]); }
  };
  /**
   * CUI.skeleton.show(container, "tiles:4, chart, table:8") hides the container's content and shows grey shapes
   * in the same layout until CUI.skeleton.hide(container). Shapes: tiles:N, chart, table:N (rows), lines:N, card.
   * With no spec, the container's data-skeleton attribute is used.
   */
  CUI.skeleton = {
    show: function (container, spec) {
      container = $(container);
      CUI.skeleton.hide(container);
      spec = spec || container.getAttribute("data-skeleton") || "tiles:4, chart, table:6";
      var box = el("div", { "class": "cui-skeleton", role: "status", "aria-busy": "true" }, [el("span", { "class": "cui-sr-only", text: "Loading…" })]);
      spec.split(",").forEach(function (part) {
        var bits = part.trim().split(":"), make = SKELETONS[bits[0]];
        if (make) box.appendChild(make(bits[1] ? parseInt(bits[1], 10) : undefined));
      });
      container.insertBefore(box, container.firstChild);
      container.classList.add("cui-is-loading");
    },
    hide: function (container) {
      container = $(container);
      container.classList.remove("cui-is-loading");
      Array.prototype.slice.call(container.children).forEach(function (c) { if (c.classList.contains("cui-skeleton")) c.remove(); });
    }
  };

  /* ---------------------------------------------------------------- tabs */

  /**
   * CUI.tabs(tablistEl, { key: "client360", load: function (name, panel) { return promise; }, onChange })
   * Markup: .cui-tabs[role=tablist] > button.cui-tab[role=tab][data-tab=name][aria-controls=panelId]
   * Gives: gliding gold underline, short fade, "#tab=name" deep links, Back button, last tab remembered,
   * arrow keys (Left/Right/Home/End), and loading shapes on the panel for as long as the promise from `load` runs.
   */
  CUI.tabs = function (list, opts) {
    list = $(list);
    opts = opts || {};
    var tabs = Array.prototype.slice.call(list.querySelectorAll('[role="tab"]'));
    var names = tabs.map(function (t) { return t.getAttribute("data-tab"); });
    var storeKey = "cui-tab:" + (opts.key || global.location.pathname);
    var ink = el("span", { "class": "cui-tabs__ink", "aria-hidden": "true" });
    list.appendChild(ink);
    var current = null, firstLoad = true, loadToken = 0;

    function panelOf(t) { return doc.getElementById(t.getAttribute("aria-controls")); }
    function moveInk(t, instant) {
      if (!t) return;
      if (instant) ink.style.transition = "none";
      ink.style.width = t.offsetWidth + "px";
      ink.style.transform = "translateX(" + t.offsetLeft + "px)";
      if (instant) { void ink.offsetWidth; ink.style.transition = ""; }
    }
    function select(name, how) {
      how = how || {};
      var i = names.indexOf(name);
      if (i < 0) i = 0;
      name = names[i];
      var changed = name !== current;
      tabs.forEach(function (t, j) {
        var on = j === i, p = panelOf(t);
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.tabIndex = on ? 0 : -1;
        if (p) p.hidden = !on;
      });
      moveInk(tabs[i], current === null);
      if (how.focus) tabs[i].focus();
      if (!changed) return;
      current = name;
      store(storeKey, name);
      if (how.push) {
        var h = CUI.hash.get(); h.tab = name; CUI.hash.set(h, true);
      }
      var panel = panelOf(tabs[i]);
      if (opts.load) {
        var token = ++loadToken, done = false;
        var res = opts.load(name, panel);
        if (res && typeof res.then === "function" && !done) {
          CUI.skeleton.show(panel);
          var finish = function () { done = true; if (token === loadToken) CUI.skeleton.hide(panel); };
          res.then(finish, finish);
        }
      }
      firstLoad = false;
      if (opts.onChange) opts.onChange(name, panel);
    }
    tabs.forEach(function (t, i) {
      t.addEventListener("click", function () { select(names[i], { push: true }); });
      t.addEventListener("keydown", function (e) {
        var j = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
        if (j === undefined) return;
        e.preventDefault();
        j = (j + tabs.length) % tabs.length;
        select(names[j], { push: true, focus: true });
      });
    });
    function fromUrl() { var h = CUI.hash.get(); if (h.tab && names.indexOf(h.tab) >= 0) select(h.tab); }
    global.addEventListener("popstate", fromUrl);
    global.addEventListener("hashchange", fromUrl);
    global.addEventListener("resize", debounce(function () { moveInk(tabs[names.indexOf(current)], true); }, 100));
    if (doc.fonts && doc.fonts.ready) doc.fonts.ready.then(function () { moveInk(tabs[names.indexOf(current)], true); });

    var start = CUI.hash.get().tab;
    if (names.indexOf(start) < 0) start = store(storeKey);
    if (names.indexOf(start) < 0) start = names[0];
    select(start);
    return { select: function (n) { select(n, { push: true }); }, current: function () { return current; } };
  };

  /* ---------------------------------------------------------------- headline tile */

  var playedCounts = {};
  /**
   * CUI.tile(el, { id, label, value, format: "money"|"pct"|"num"|fn, change, changeLabel: "since last month",
   *                goodWhen: "up"|"down"|"none", trend: [numbers], accent: "gold" })
   * The value counts up the first time a tile with this id is drawn, never again on later tabs or clicks.
   */
  CUI.tile = function (host, o) {
    host = $(host);
    o = o || {};
    var f = formatter(o.format);
    var id = o.id || o.label;
    host.className = "cui-tile" + (o.accent === "gold" ? " cui-tile--gold" : "");
    host.textContent = "";
    var value = el("div", { "class": "cui-tile__value" });
    var row = el("div", { "class": "cui-tile__row" }, [value]);
    host.appendChild(el("div", { "class": "cui-tile__label", text: o.label }));
    host.appendChild(row);
    if (isNum(o.change)) {
      var dir = o.change > 0 ? "up" : o.change < 0 ? "down" : "flat";
      var good = o.goodWhen || "up";
      var tone = dir === "flat" || good === "none" ? "flat" : (dir === good ? "good" : "bad");
      var words = dir === "flat" ? "no change" : (dir === "up" ? "up " : "down ") + formatChange(Math.abs(o.change), o.format).replace(/^\+/, "");
      var delta = el("div", { "class": "cui-tile__delta cui-tile__delta--" + tone }, [
        icon(dir),
        el("span", { "aria-hidden": "true", text: dir === "flat" ? "No change" : formatChange(o.change, o.format) }),
        el("span", { "class": "cui-sr-only", text: words + " " + (o.changeLabel || "since last period") + (tone === "good" ? ", an improvement" : tone === "bad" ? ", a decline" : "") }),
        el("span", { "class": "cui-tile__period", "aria-hidden": "true", text: o.changeLabel || "since last period" })
      ]);
      host.appendChild(delta);
    }
    if (o.trend && o.trend.length > 1 && global.echarts) {
      var sp = el("div", { "class": "cui-tile__spark" });
      row.appendChild(sp);
      CUI.chart.spark(sp, { data: o.trend, format: o.format, color: o.accent === "gold" ? colors().c2 : colors().c1, title: o.label + " trend", id: "tile-" + id });
    }
    var target = o.value;
    var shown = el("span", { "aria-hidden": "true" });
    value.appendChild(shown);
    value.appendChild(el("span", { "class": "cui-sr-only", text: isNum(target) ? f(target) : "No value" }));
    if (!isNum(target) || playedCounts[id] || motionOff()) { shown.textContent = isNum(target) ? f(target) : MISSING; playedCounts[id] = true; return; }
    playedCounts[id] = true;
    var t0 = null, dur = 600;
    function step(ts) {
      if (t0 === null) t0 = ts;
      var k = Math.min(1, (ts - t0) / dur);
      var e = 1 - Math.pow(1 - k, 3);
      shown.textContent = f(target * e);
      if (k < 1) global.requestAnimationFrame(step);
      else shown.textContent = f(target);
    }
    global.requestAnimationFrame(step);
  };

  /* ---------------------------------------------------------------- empty and error states */

  /** CUI.empty(el, { title: "No cases yet", text: "..." }) */
  CUI.empty = function (host, o) {
    host = $(host); o = o || {};
    host.textContent = "";
    host.appendChild(el("div", { "class": "cui-empty" }, [icon("empty"),
      el("p", { "class": "cui-empty__title", text: o.title || "Nothing to show yet" }),
      o.text ? el("p", { "class": "cui-empty__text", text: o.text }) : null]));
  };
  /** CUI.error(el, { title, text, retry: function () {} }) */
  CUI.error = function (host, o) {
    host = $(host); o = o || {};
    host.textContent = "";
    host.appendChild(el("div", { "class": "cui-error", role: "alert" }, [icon("error"),
      el("p", { "class": "cui-error__title", text: o.title || "This part could not load" }),
      o.text ? el("p", { "class": "cui-error__text", text: o.text }) : null,
      o.retry ? el("button", { "class": "cui-btn cui-btn--primary", type: "button", text: o.retryLabel || "Try again", onclick: o.retry }) : null]));
  };

  /* ---------------------------------------------------------------- toast (use instead of alert()) */

  var toastBox = null;
  /** CUI.toast("Saved.", { type: "good"|"bad"|"warn"|"info", timeout: 5000 }) */
  CUI.toast = function (message, o) {
    o = o || {};
    if (!toastBox || !toastBox.isConnected) {
      toastBox = el("div", { "class": "cui-toasts", "aria-live": "polite" });
      doc.body.appendChild(toastBox);
    }
    var type = o.type || "info";
    var close = el("button", { "class": "cui-btn cui-btn--icon cui-btn--ghost", type: "button", "aria-label": "Dismiss" }, [icon("close")]);
    var t = el("div", { "class": "cui-toast cui-toast--" + type, role: type === "bad" ? "alert" : "status" }, [el("div", { "class": "cui-toast__text", text: message }), close]);
    toastBox.appendChild(t);
    var timer;
    function leave() {
      clearTimeout(timer);
      t.classList.add("is-leaving");
      setTimeout(function () { t.remove(); }, motionOff() ? 0 : 220);
    }
    function arm() { timer = setTimeout(leave, o.timeout || (type === "bad" ? 9000 : 5000)); }
    close.addEventListener("click", leave);
    t.addEventListener("mouseenter", function () { clearTimeout(timer); });
    t.addEventListener("mouseleave", arm);
    arm();
    return { close: leave };
  };

  /* ---------------------------------------------------------------- drawer (focus stays inside while open) */

  var FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  var openDrawer = null;
  /**
   * CUI.drawer.open("#my-drawer") / CUI.drawer.close()
   * Markup: .cui-drawer[hidden] > .cui-drawer__backdrop[data-cui-close] + .cui-drawer__panel[role=dialog][aria-modal=true]
   * Esc, the backdrop and any [data-cui-close] close it; focus returns to whatever opened it.
   */
  CUI.drawer = {
    open: function (d, o) {
      d = $(d); o = o || {};
      if (openDrawer) CUI.drawer.close();
      var ret = doc.activeElement;
      var others = Array.prototype.slice.call(doc.body.children).filter(function (c) {
        return c !== d && !c.inert && c.tagName !== "SCRIPT" && !c.classList.contains("cui-toasts");   // toasts stay readable
      });
      others.forEach(function (c) { c.inert = true; });
      d.hidden = false;
      doc.body.classList.add("cui-no-scroll");
      void d.offsetWidth;
      d.classList.add("is-open");
      var panel = d.querySelector(".cui-drawer__panel");
      function keys(e) {
        if (e.key === "Escape") { e.preventDefault(); CUI.drawer.close(); return; }
        if (e.key !== "Tab") return;
        var f = Array.prototype.slice.call(panel.querySelectorAll(FOCUSABLE)).filter(function (x) { return x.offsetParent !== null; });
        if (!f.length) { e.preventDefault(); return; }
        var first = f[0], last = f[f.length - 1];
        if (e.shiftKey && (doc.activeElement === first || doc.activeElement === panel)) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && doc.activeElement === last) { e.preventDefault(); first.focus(); }
      }
      function clicks(e) { if (e.target.closest("[data-cui-close]")) CUI.drawer.close(); }
      d.addEventListener("keydown", keys);
      d.addEventListener("click", clicks);
      openDrawer = { d: d, ret: ret, others: others, keys: keys, clicks: clicks, onClose: o.onClose };
      var first = panel.querySelector("[autofocus]") || panel.querySelector(FOCUSABLE);
      if (!panel.hasAttribute("tabindex")) panel.setAttribute("tabindex", "-1");
      (first || panel).focus();
    },
    close: function () {
      if (!openDrawer) return;
      var s = openDrawer; openDrawer = null;
      s.d.classList.remove("is-open");
      s.d.removeEventListener("keydown", s.keys);
      s.d.removeEventListener("click", s.clicks);
      s.others.forEach(function (c) { c.inert = false; });
      doc.body.classList.remove("cui-no-scroll");
      setTimeout(function () { if (!s.d.classList.contains("is-open")) s.d.hidden = true; }, motionOff() ? 0 : 260);
      if (s.ret && s.ret.focus) s.ret.focus();
      if (s.onClose) s.onClose();
    }
  };

  /* ---------------------------------------------------------------- searchable dropdown */

  /**
   * CUI.select(el, { label, options: ["A", "B"] or [{ value, label }], multiple: true, placeholder: "All",
   *                  value: [...], onChange: function (values) {} })  ->  { get, set, clear }
   * Keyboard: Enter/Space/Down opens; type to search; Up/Down move; Enter picks; Esc closes.
   */
  CUI.select = function (host, o) {
    host = $(host); o = o || {};
    var opts = (o.options || []).map(function (x) { return typeof x === "object" ? x : { value: String(x), label: String(x) }; });
    var chosen = (o.value || []).slice();
    var id = nextId("cui-select");
    host.className = "cui-select";
    host.textContent = "";
    var valueEl = el("span", { "class": "cui-select__value" });
    var btn = el("button", { "class": "cui-select__button", type: "button", id: id + "-btn", "aria-haspopup": "listbox", "aria-expanded": "false" }, [valueEl, icon("caret")]);
    if (o.labelledBy) btn.setAttribute("aria-labelledby", o.labelledBy + " " + id + "-btn");
    else if (o.label) btn.setAttribute("aria-label", o.label);
    var search = el("input", { "class": "cui-input cui-select__search", type: "search", role: "combobox", "aria-expanded": "true",
      "aria-controls": id + "-list", "aria-autocomplete": "list", placeholder: "Search", "aria-label": "Search " + (o.label || "options") });
    var listEl = el("ul", { "class": "cui-select__list", role: "listbox", id: id + "-list", "aria-label": o.label || "Options" });
    if (o.multiple) listEl.setAttribute("aria-multiselectable", "true");
    var popup = el("div", { "class": "cui-select__popup", hidden: true }, [search, listEl]);
    host.appendChild(btn); host.appendChild(popup);
    var shown = [], active = -1;

    function labelOf(v) { for (var i = 0; i < opts.length; i++) if (opts[i].value === v) return opts[i].label; return v; }
    function paintButton() {
      valueEl.className = "cui-select__value" + (chosen.length ? "" : " cui-select__value--placeholder");
      valueEl.textContent = !chosen.length ? (o.placeholder || "All") : chosen.length === 1 ? labelOf(chosen[0]) : chosen.length + " selected";
    }
    function renderList() {
      var q = search.value.trim().toLowerCase();
      shown = opts.filter(function (x) { return !q || x.label.toLowerCase().indexOf(q) >= 0; });
      listEl.textContent = "";
      if (!shown.length) { listEl.appendChild(el("li", { "class": "cui-select__none", text: "No matches" })); search.removeAttribute("aria-activedescendant"); return; }
      shown.forEach(function (x, i) {
        var li = el("li", { "class": "cui-select__option" + (i === active ? " is-active" : ""), role: "option", id: id + "-o" + i,
          "aria-selected": chosen.indexOf(x.value) >= 0 ? "true" : "false" },
          [o.multiple ? el("span", { "class": "cui-select__check", "aria-hidden": "true" }) : null, el("span", { text: x.label })]);
        li.addEventListener("mousedown", function (e) { e.preventDefault(); pick(i); });
        li.addEventListener("mousemove", function () { if (active !== i) { active = i; paintActive(); } });
        listEl.appendChild(li);
      });
      paintActive();
    }
    function paintActive() {
      Array.prototype.forEach.call(listEl.children, function (li, i) { li.classList.toggle("is-active", i === active); });
      if (active >= 0 && listEl.children[active]) {
        search.setAttribute("aria-activedescendant", id + "-o" + active);
        listEl.children[active].scrollIntoView({ block: "nearest" });
      } else search.removeAttribute("aria-activedescendant");
    }
    function pick(i) {
      var x = shown[i]; if (!x) return;
      if (o.multiple) {
        var k = chosen.indexOf(x.value);
        if (k >= 0) chosen.splice(k, 1); else chosen.push(x.value);
        renderList();
      } else { chosen = [x.value]; close(true); }
      paintButton();
      if (o.onChange) o.onChange(chosen.slice());
    }
    function open() {
      if (!popup.hidden) return;
      popup.hidden = false; btn.setAttribute("aria-expanded", "true");
      search.value = ""; active = 0; renderList(); search.focus();
      doc.addEventListener("mousedown", outside, true);
    }
    function close(focusBtn) {
      if (popup.hidden) return;
      popup.hidden = true; btn.setAttribute("aria-expanded", "false");
      doc.removeEventListener("mousedown", outside, true);
      if (focusBtn) btn.focus();
    }
    function outside(e) { if (!host.contains(e.target)) close(false); }
    btn.addEventListener("click", function () { if (popup.hidden) open(); else close(true); });
    btn.addEventListener("keydown", function (e) { if (e.key === "ArrowDown") { e.preventDefault(); open(); } });
    search.addEventListener("input", function () { active = 0; renderList(); });
    search.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(shown.length - 1, active + 1); paintActive(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); paintActive(); }
      else if (e.key === "Enter") { e.preventDefault(); pick(active); }
      else if (e.key === "Escape") { e.preventDefault(); close(true); }
      else if (e.key === "Tab") close(false);
    });
    paintButton();
    return {
      get: function () { return chosen.slice(); },
      set: function (v) { chosen = (v || []).slice(); paintButton(); if (!popup.hidden) renderList(); },
      clear: function () { chosen = []; paintButton(); },
      labelOf: labelOf
    };
  };

  /* ---------------------------------------------------------------- filter bar: dropdowns + removable chips */

  /**
   * CUI.filterBar(el, { filters: [{ key, label, options, multiple }], onChange: function (state) {} })
   * -> { get, set(key, values), clear }. state looks like { insurer: ["Insurer 1"], state: ["NJ"] }.
   */
  CUI.filterBar = function (host, o) {
    host = $(host); o = o || {};
    host.className = "cui-filters";
    host.textContent = "";
    host.setAttribute("role", "group");
    host.setAttribute("aria-label", o.label || "Filters");
    var selects = {};
    var chips = el("div", { "class": "cui-filters__chips", "aria-live": "polite" });
    function state() { var s = {}; Object.keys(selects).forEach(function (k) { s[k] = selects[k].api.get(); }); return s; }
    function changed() { paintChips(); if (o.onChange) o.onChange(state()); }
    (o.filters || []).forEach(function (f) {
      var lid = nextId("cui-flabel");
      var box = el("div");
      var field = el("div", { "class": "cui-field" }, [el("span", { "class": "cui-field__label", id: lid, text: f.label }), box]);
      host.appendChild(field);
      selects[f.key] = { f: f, api: CUI.select(box, { label: f.label, labelledBy: lid, options: f.options, multiple: f.multiple !== false, placeholder: f.placeholder || "All", value: f.value, onChange: changed }) };
    });
    host.appendChild(chips);
    function paintChips() {
      chips.textContent = "";
      var any = false;
      Object.keys(selects).forEach(function (k) {
        var s = selects[k];
        s.api.get().forEach(function (v) {
          any = true;
          var name = s.api.labelOf(v);
          var rm = el("button", { "class": "cui-fchip__remove", type: "button", "aria-label": "Remove " + s.f.label + ": " + name }, [icon("close")]);
          rm.addEventListener("click", function () {
            var next = s.api.get().filter(function (x) { return x !== v; });
            s.api.set(next);
            changed();
            var first = chips.querySelector(".cui-fchip__remove");
            (first || host.querySelector(".cui-select__button")).focus();
          });
          chips.appendChild(el("span", { "class": "cui-fchip" }, [el("span", { "class": "cui-fchip__label" }, [s.f.label + ": ", el("b", { text: name })]), rm]));
        });
      });
      if (any) chips.appendChild(el("button", { "class": "cui-linkbtn", type: "button", text: "Clear all", onclick: function () { api.clear(); } }));
    }
    var api = {
      get: state,
      set: function (k, v) { if (selects[k]) { selects[k].api.set(v); changed(); } },
      clear: function () { Object.keys(selects).forEach(function (k) { selects[k].api.clear(); }); changed(); host.querySelector(".cui-select__button").focus(); }
    };
    paintChips();
    return api;
  };

  /* ---------------------------------------------------------------- CSV */

  /**
   * CUI.csv(rows, columns, "file-name") downloads a CSV that opens cleanly in Excel.
   * Numbers stay numbers; dates stay YYYY-MM-DD; text that starts with = + - @ is prefixed with ' so Excel
   * never runs it as a formula.
   */
  CUI.csv = function (rows, columns, name) {
    function cell(v) {
      if (v == null || (typeof v === "number" && !isFinite(v))) return "";
      if (v instanceof Date) v = v.getFullYear() + "-" + String(v.getMonth() + 1).padStart(2, "0") + "-" + String(v.getDate()).padStart(2, "0");
      if (typeof v === "number") return String(v);
      var s = String(v);
      if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
      return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    }
    var lines = [columns.map(function (c) { return cell(c.label); }).join(",")];
    rows.forEach(function (r) { lines.push(columns.map(function (c) { return cell(valueOf(r, c)); }).join(",")); });
    var blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    var a = el("a", { href: URL.createObjectURL(blob), download: (name || "table") + ".csv" });
    doc.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
  };
  function valueOf(row, col) { return typeof col.value === "function" ? col.value(row) : row[col.key]; }

  /* ---------------------------------------------------------------- table */

  /**
   * CUI.table(el, { title, columns: [{ key, label, format, align: "right", sortable, value: fn }], rows,
   *                 pageSize: 200, search: true, csv: "file-name", onRowClick: fn, sort: { key, dir: "desc" },
   *                 emptyText }) -> { setRows }
   */
  CUI.table = function (host, o) {
    host = $(host); o = o || {};
    var cols = o.columns || [];
    var rows = o.rows || [];
    var pageSize = o.pageSize || 200;
    var sortKey = o.sort ? o.sort.key : null, sortDir = o.sort ? o.sort.dir || "asc" : "asc";
    var query = "", page = 0, view = [];
    var id = nextId("cui-table");
    host.className = "cui-table-wrap";
    host.textContent = "";

    var count = el("span", { "class": "cui-table-count", "aria-live": "polite", id: id + "-count" });
    var left = el("div", { "class": "cui-table-bar__left" });
    var right = el("div", { "class": "cui-table-bar__right" }, [count]);
    if (o.search !== false) {
      var input = el("input", { "class": "cui-input", type: "search", placeholder: o.searchPlaceholder || "Search this table", "aria-label": "Search " + (o.title || "table"), "aria-describedby": id + "-count" });
      left.appendChild(el("div", { "class": "cui-table-search" }, [icon("search"), input]));
      input.addEventListener("input", debounce(function () { query = input.value.trim().toLowerCase(); page = 0; refresh(); }, 250));
    }
    if (o.csv) {
      var dl = el("button", { "class": "cui-btn", type: "button" }, [icon("download"), "Download CSV"]);
      dl.addEventListener("click", function () {
        var d = new Date();
        CUI.csv(view, cols, o.csv + "-" + d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"));
        CUI.toast("Downloaded " + fmt.num(view.length) + " rows as a CSV file.", { type: "good" });
      });
      right.appendChild(dl);
    }
    host.appendChild(el("div", { "class": "cui-table-bar" }, [left, right]));

    var table = el("table", { "class": "cui-table" });
    if (o.title) table.appendChild(el("caption", { "class": "cui-sr-only", text: o.title }));
    var thead = el("thead"), tbody = el("tbody"), hr = el("tr");
    var ths = cols.map(function (c) {
      var num = c.align === "right" || ["money", "pct", "num"].indexOf(c.format) >= 0;
      c._num = num;
      var th = el("th", { scope: "col", "class": num ? "is-num" : null });
      if (c.sortable === false) th.appendChild(el("span", { text: c.label }));
      else {
        var b = el("button", { "class": "cui-table__sort", type: "button" }, [el("span", { text: c.label }), icon("sort")]);
        b.addEventListener("click", function () {
          if (sortKey === c.key) sortDir = sortDir === "asc" ? "desc" : "asc";
          else { sortKey = c.key; sortDir = num ? "desc" : "asc"; }
          page = 0; refresh();
        });
        th.appendChild(b);
      }
      hr.appendChild(th);
      return th;
    });
    thead.appendChild(hr);
    table.appendChild(thead); table.appendChild(tbody);
    var scroll = el("div", { "class": "cui-table-scroll", tabindex: "0", role: "region", "aria-label": (o.title || "Table") + ", scrollable" }, [table]);
    host.appendChild(scroll);
    var pager = el("div", { "class": "cui-pager" });
    host.appendChild(pager);

    function text(r, c) {
      var v = valueOf(r, c);
      if (c.format === "date") return fmt.date(v);
      if (c.format) return formatter(c.format)(v);
      return v == null || v === "" ? MISSING : String(v);
    }
    function compare(a, b) {
      var c = cols.filter(function (x) { return x.key === sortKey; })[0];
      if (!c) return 0;
      var x = valueOf(a, c), y = valueOf(b, c);
      var xm = x == null || x === "" || (typeof x === "number" && !isFinite(x));
      var ym = y == null || y === "" || (typeof y === "number" && !isFinite(y));
      if (xm || ym) return xm && ym ? 0 : xm ? 1 : -1;          // missing values always last
      var r = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "en", { numeric: true, sensitivity: "base" });
      return sortDir === "asc" ? r : -r;
    }
    function refresh() {
      var words = query ? query.split(/\s+/) : [];
      view = rows.filter(function (r) {
        if (!words.length) return true;
        var hay = cols.map(function (c) { return text(r, c); }).join(" ").toLowerCase();
        return words.every(function (w) { return hay.indexOf(w) >= 0; });
      });
      if (sortKey) view = view.slice().sort(compare);
      ths.forEach(function (th, i) {
        if (cols[i].key === sortKey) th.setAttribute("aria-sort", sortDir === "asc" ? "ascending" : "descending");
        else th.removeAttribute("aria-sort");
      });
      var pages = Math.max(1, Math.ceil(view.length / pageSize));
      page = Math.min(page, pages - 1);
      var from = page * pageSize, slice = view.slice(from, from + pageSize);
      tbody.textContent = "";
      if (!slice.length) {
        tbody.appendChild(el("tr", null, [el("td", { "class": "cui-table-empty", colspan: cols.length, text: o.emptyText || (query ? "No rows match your search." : "No rows to show.") })]));
      }
      var frag = doc.createDocumentFragment();
      slice.forEach(function (r) {
        var tr = el("tr");
        cols.forEach(function (c) { tr.appendChild(el("td", { "class": c._num ? "is-num" : null, text: text(r, c) })); });
        if (o.onRowClick) {
          tr.className = "is-clickable"; tr.tabIndex = 0;
          tr.addEventListener("click", function () { o.onRowClick(r); });
          tr.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); o.onRowClick(r); } });
        }
        frag.appendChild(tr);
      });
      tbody.appendChild(frag);
      var shownTxt = slice.length === view.length ? fmt.num(view.length) : (from === 0 ? fmt.num(slice.length) : fmt.num(from + 1) + "–" + fmt.num(from + slice.length));
      count.textContent = "Showing " + shownTxt + " of " + fmt.num(view.length) + (query && view.length !== rows.length ? " matching (" + fmt.num(rows.length) + " in all)" : "");
      pager.textContent = "";
      if (pages > 1) {
        var prev = el("button", { "class": "cui-btn", type: "button", text: "Previous", disabled: page === 0 });
        var next = el("button", { "class": "cui-btn", type: "button", text: "Next", disabled: page >= pages - 1 });
        prev.addEventListener("click", function () { page -= 1; refresh(); scroll.scrollTop = 0; });
        next.addEventListener("click", function () { page += 1; refresh(); scroll.scrollTop = 0; });
        pager.appendChild(prev);
        pager.appendChild(el("span", { text: "Page " + (page + 1) + " of " + pages }));
        pager.appendChild(next);
      }
    }
    refresh();
    return { setRows: function (r) { rows = r || []; page = 0; refresh(); }, rows: function () { return view.slice(); } };
  };

  /* ================================================================ charts (Apache ECharts) */

  var FALLBACK = { c1: "#002D42", c2: "#aa6a00", c3: "#33a376", c4: "#9f5ccc", c5: "#366a78", c6: "#842a2a", c7: "#7f8c96", c8: "#5d24b2" };
  function token(name, fallback) {
    var v = global.getComputedStyle ? global.getComputedStyle(doc.documentElement).getPropertyValue("--cui-" + name).trim() : "";
    return v || fallback;
  }
  var colorCache = null;
  function colors() {
    if (colorCache) return colorCache;
    var c = {};
    Object.keys(FALLBACK).forEach(function (k) { c[k] = token(k, FALLBACK[k]); });
    c.list = ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"].map(function (k) { return c[k]; });
    c.seq = [1, 2, 3, 4, 5, 6, 7].map(function (i) { return token("seq-" + i, ["#eef3f6", "#cfdde6", "#a6c0d0", "#7499b0", "#46738e", "#1f506b", "#002D42"][i - 1]); });
    c.ink = token("ink", "#061d2b"); c.ink2 = token("ink-2", "#3d4b54"); c.muted = token("muted", "#59656e");
    c.line = token("line", "#dfe5e8"); c.lineStrong = token("line-strong", "#c5cfd5"); c.gold = token("gold", "#aa6a00");
    c.goldText = token("gold-text", "#8f5a00"); c.font = token("font", "Manrope, 'Segoe UI', sans-serif");
    colorCache = c;
    return c;
  }
  CUI.colors = function () { return colors(); };

  var themeDone = false;
  function ensureTheme() {
    if (themeDone || !global.echarts) return;
    var c = colors();
    var axis = {
      axisLine: { show: true, lineStyle: { color: c.lineStrong } },
      axisTick: { show: false },
      axisLabel: { color: c.muted, fontSize: 13, fontFamily: c.font, margin: 10 },
      splitLine: { show: true, lineStyle: { color: c.line } },
      nameTextStyle: { color: c.muted, fontSize: 13, fontFamily: c.font }
    };
    global.echarts.registerTheme("callagy", {
      color: c.list,
      backgroundColor: "transparent",
      textStyle: { fontFamily: c.font, color: c.ink2, fontSize: 13 },
      categoryAxis: Object.assign({}, axis, { splitLine: { show: false } }),
      valueAxis: Object.assign({}, axis, { axisLine: { show: false } }),
      line: { symbol: "circle", symbolSize: 7, lineStyle: { width: 2.5 }, smooth: false },
      bar: { itemStyle: { borderRadius: [4, 4, 0, 0] } }
    });
    themeDone = true;
  }

  var playedCharts = {};
  function tooltipBase() {
    var c = colors();
    return {
      backgroundColor: "#ffffff", borderColor: c.line, borderWidth: 1, padding: [10, 12],
      textStyle: { fontFamily: c.font, color: c.ink, fontSize: 13 },
      extraCssText: "border-radius:8px;box-shadow:0 4px 12px rgba(0,45,66,.10),0 16px 40px rgba(0,45,66,.10);",
      confine: true, transitionDuration: motionOff() ? 0 : 0.15
    };
  }
  function tipRow(color, name, val) {
    return '<div class="cui-tip__row"><span class="cui-tip__dot" style="background:' + esc(color) + '"></span>' +
      '<span class="cui-tip__name">' + esc(name) + '</span><span class="cui-tip__val">' + esc(val) + "</span></div>";
  }

  /**
   * The shared frame every chart gets:
   *   figure.cui-chart > legend buttons, the drawing (focusable, with a text summary), notes, a hidden data table.
   */
  function frame(host, o, kind) {
    host = $(host);
    if (!global.echarts) { CUI.error(host, { title: "Charts could not load", text: "The chart file (echarts.min.js) is missing from this dashboard's kit folder." }); return null; }
    ensureTheme();
    if (host._cui && host._cui.chart) { host._cui.chart.dispose(); if (host._cui.ro) host._cui.ro.disconnect(); }
    var id = o.id || host.id || nextId("cui-chart");
    var fig = host.tagName === "FIGURE" ? host : null;
    host.textContent = "";
    if (!fig) { fig = el("figure", { "class": "cui-chart" }); host.appendChild(fig); }
    else fig.className = "cui-chart";
    if (kind === "spark") fig.classList.add("cui-chart--spark");
    var legend = el("div", { "class": "cui-chart__legend", role: "group", "aria-label": "Show or hide series" });
    var canvas = el("div", { "class": "cui-chart__canvas", tabindex: "0", role: "img" });
    if (o.height) canvas.style.setProperty("--cui-chart-height", typeof o.height === "number" ? o.height + "px" : o.height);
    var hint = el("span", { "class": "cui-chart__keyhint", "aria-hidden": "true", text: kind === "map" || kind === "donut" || kind === "heatmap" ? "← → to step through" : "← → to read values" });
    var notes = el("figcaption", { "class": "cui-chart__note" });
    var srTable = el("table");
    if (kind !== "spark") fig.appendChild(legend);
    fig.appendChild(canvas);
    if (kind !== "spark") { fig.appendChild(notes); fig.appendChild(el("div", { "class": "cui-sr-only" }, [srTable])); }
    var noteList = (o.notes || []).slice();
    if (o.asOf) noteList.push("Data as of " + fmt.date(o.asOf));
    noteList.forEach(function (n) { notes.appendChild(el("span", { text: n })); });
    var chart = global.echarts.init(canvas, "callagy", { renderer: "svg" });
    canvas.appendChild(hint);
    var firstDraw = !playedCharts[id] && !motionOff();
    playedCharts[id] = true;
    var ro = global.ResizeObserver ? new global.ResizeObserver(function () { chart.resize(); }) : null;
    if (ro) ro.observe(canvas);
    host._cui = { chart: chart, ro: ro };
    return { host: host, fig: fig, legend: legend, canvas: canvas, chart: chart, srTable: srTable, animate: firstDraw, id: id };
  }
  function anim(F) {
    return { animation: F.animate, animationDuration: 600, animationEasing: "cubicOut", animationDurationUpdate: motionOff() ? 0 : 200 };
  }
  function summary(F, text) { F.canvas.setAttribute("aria-label", text); }
  function fillTable(F, caption, head, body) {
    var t = F.srTable; t.textContent = "";
    t.appendChild(el("caption", { text: caption }));
    var thead = el("thead"), tr = el("tr");
    head.forEach(function (h) { tr.appendChild(el("th", { scope: "col", text: h })); });
    thead.appendChild(tr); t.appendChild(thead);
    var tb = el("tbody");
    body.forEach(function (r) { var row = el("tr"); r.forEach(function (v, i) { row.appendChild(el(i === 0 ? "th" : "td", i === 0 ? { scope: "row", text: v } : { text: v })); }); tb.appendChild(row); });
    t.appendChild(tb);
  }
  /** HTML legend: real buttons, so they work with the keyboard. */
  function makeLegend(F, items) {
    F.legend.textContent = "";
    if (items.length < 2) { F.legend.hidden = true; return; }
    items.forEach(function (it) {
      var sw = el("span", { "class": "cui-legend-item__swatch" + (it.shape === "line" ? " cui-legend-item__swatch--line" : it.shape === "dashed" ? " cui-legend-item__swatch--dashed" : ""), "aria-hidden": "true" });
      sw.style.setProperty("--cui-swatch", it.color);
      var b = el("button", { "class": "cui-legend-item", type: "button", "aria-pressed": "true" }, [sw, el("span", { "class": "cui-legend-item__label", text: it.name })]);
      b.addEventListener("click", function () {
        var on = b.getAttribute("aria-pressed") === "true";
        b.setAttribute("aria-pressed", on ? "false" : "true");
        F.chart.dispatchAction({ type: "legendToggleSelect", name: it.name });
      });
      F.legend.appendChild(b);
    });
  }
  /** Keyboard: focus shows a tooltip; arrow keys step through the points; Esc hides it. */
  function keyboard(F, count, show, startFirst) {
    var i = -1;
    function go(n) {
      if (!count()) return;
      F.chart.dispatchAction({ type: "hideTip" });
      i = (n + count()) % count();
      show(i);
    }
    F.canvas.addEventListener("focus", function () { go(i < 0 ? (startFirst ? 0 : count() - 1) : i); });
    F.canvas.addEventListener("blur", function () { F.chart.dispatchAction({ type: "hideTip" }); F.chart.dispatchAction({ type: "downplay" }); });
    F.canvas.addEventListener("keydown", function (e) {
      var k = e.key;
      if (k === "ArrowRight" || k === "ArrowDown") { e.preventDefault(); go(i + 1); }
      else if (k === "ArrowLeft" || k === "ArrowUp") { e.preventDefault(); go(i - 1); }
      else if (k === "Home") { e.preventDefault(); go(0); }
      else if (k === "End") { e.preventDefault(); go(count() - 1); }
      else if (k === "Escape") { F.chart.dispatchAction({ type: "hideTip" }); }
    });
  }
  function extremes(arr) {
    var hi = -Infinity, lo = Infinity, hiI = -1, loI = -1;
    arr.forEach(function (v, i) { if (isNum(v)) { if (v > hi) { hi = v; hiI = i; } if (v < lo) { lo = v; loI = i; } } });
    return { hi: hi, lo: lo, hiI: hiI, loI: loI };
  }
  function seriesColor(s, i) { return s.color || colors().list[i % 8]; }

  /* ---- line / area, bar, stacked bar (one engine, three looks) */

  function axisChart(host, o, kind) {
    o = o || {};
    var F = frame(host, o, kind);
    if (!F) return null;
    var c = colors(), f = formatter(o.format);
    var cats = o.categories || [];
    var horizontal = !!o.horizontal && kind !== "line";
    var series = (o.series || []).map(function (s, i) {
      var col = seriesColor(s, i);
      var base = { name: s.name, data: s.data, itemStyle: { color: col }, emphasis: { focus: "series" } };
      if (kind === "line") {
        base.type = "line";
        base.lineStyle = { color: col, width: 2.5, type: s.dashed ? "dashed" : "solid" };
        base.showSymbol = cats.length <= 24;
        base.connectNulls = false;
        if (s.area || o.area) {
          base.areaStyle = { color: new global.echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: hexA(col, 0.22) }, { offset: 1, color: hexA(col, 0.02) }]) };
        }
      } else {
        base.type = "bar";
        base.barMaxWidth = 36;
        if (kind === "stacked") { base.stack = "total"; base.itemStyle.borderRadius = 0; base.itemStyle.borderColor = "#fff"; base.itemStyle.borderWidth = 1; }
        else base.itemStyle.borderRadius = horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0];
      }
      return base;
    });
    if (kind === "stacked" && series.length) {          // round only the outer end of each stack
      series[series.length - 1].itemStyle.borderRadius = horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0];
    }
    // Forecast region: shaded from that category to the end, labelled "Forecast"
    if (kind === "line" && o.forecastFrom != null && series.length) {
      var fromCat = typeof o.forecastFrom === "number" ? cats[o.forecastFrom] : o.forecastFrom;
      series[0].markArea = { silent: true, itemStyle: { color: hexA(c.gold, 0.08) },
        label: { show: true, position: "insideTop", color: c.goldText, fontSize: 13, fontWeight: 700, fontFamily: c.font, formatter: o.forecastLabel || "Forecast" },
        data: [[{ xAxis: fromCat }, { xAxis: cats[cats.length - 1] }]] };
    }
    // Target line: a quiet dashed line with its label; a hidden helper series keeps the axis tall enough for it
    if (o.target && isNum(o.target.value)) {
      var tv = o.target.value, tl = (o.target.label || "Target") + " " + f(tv);
      series.push({ name: "__target", type: "line", silent: true, symbol: "none", tooltip: { show: false },
        data: cats.map(function () { return tv; }), lineStyle: { opacity: 0 }, z: 1, animation: false,
        markLine: { silent: true, symbol: "none", animation: false,
          lineStyle: { type: "dashed", color: c.ink2, width: 1.5 },
          label: { formatter: tl, position: horizontal ? "insideEndBottom" : (kind === "line" ? "insideStartTop" : "insideEndTop"), color: c.ink2, fontSize: 13, fontWeight: 700, fontFamily: c.font,
            backgroundColor: "rgba(255,255,255,0.92)", padding: [2, 6], borderRadius: 4 },
          data: [horizontal ? { xAxis: tv } : { yAxis: tv }] } });
    }
    var forecastIndex = o.forecastFrom == null ? Infinity : (typeof o.forecastFrom === "number" ? o.forecastFrom : cats.indexOf(o.forecastFrom));
    var catAxis = { type: "category", data: cats, boundaryGap: kind !== "line",
      axisLabel: { hideOverlap: true } };
    var valAxis = { type: "value", axisLabel: { formatter: function (v) { return f(v); } }, splitNumber: 4, min: o.yMin };
    if (horizontal) catAxis.inverse = true;
    var option = Object.assign(anim(F), {
      grid: { left: kind === "line" && !horizontal ? 24 : 8, right: kind === "line" ? 32 : 16, top: 16, bottom: 8, containLabel: true },
      legend: { show: false },
      xAxis: horizontal ? valAxis : catAxis,
      yAxis: horizontal ? catAxis : valAxis,
      tooltip: Object.assign(tooltipBase(), {
        trigger: "axis",
        axisPointer: kind === "line" ? { type: "line", lineStyle: { color: c.lineStrong } } : { type: "shadow", shadowStyle: { color: "rgba(0,45,66,0.06)" } },
        formatter: function (ps) {
          ps = ps.filter(function (p) { return p.seriesName !== "__target"; });
          if (!ps.length) return "";
          var idx = ps[0].dataIndex;
          var head = esc(ps[0].axisValueLabel) + (idx >= forecastIndex ? " · forecast" : "");
          var html = '<div class="cui-tip"><div class="cui-tip__head">' + head + "</div>";
          var total = 0, any = false;
          ps.forEach(function (p) { if (isNum(p.value)) { total += p.value; any = true; } html += tipRow(p.color, p.seriesName, f(p.value)); });
          var extra = [];
          if (kind === "stacked" && ps.length > 1 && any) extra.push("Total " + f(total));
          if (o.target && isNum(o.target.value) && ps.length === 1 && isNum(ps[0].value)) {
            var gap = ps[0].value - o.target.value;
            extra.push(gap === 0 ? "On target" : (gap > 0 ? "Above" : "Below") + " target by " + f(Math.abs(gap)));
          }
          if (extra.length) html += '<div class="cui-tip__extra">' + esc(extra.join(" · ")) + "</div>";
          return html + "</div>";
        }
      }),
      series: series
    });
    F.chart.setOption(option);
    var real = (o.series || []);
    makeLegend(F, real.map(function (s, i) { return { name: s.name, color: seriesColor(s, i), shape: kind === "line" ? (s.dashed ? "dashed" : "line") : "box" }; }));
    keyboard(F, function () { return cats.length; }, function (i) {
      // anchor the tooltip on a series that has a value at this point (an empty point shows no tooltip)
      var si = 0;
      for (var k = 0; k < series.length; k++) { if (isNum((series[k].data || [])[i])) { si = k; break; } }
      F.chart.dispatchAction({ type: "showTip", seriesIndex: si, dataIndex: i });
    });
    // Text alternative
    var word = { line: o.area ? "Area chart" : "Line chart", bar: "Bar chart", stacked: "Stacked bar chart" }[kind];
    var parts = [(o.title ? o.title + ". " : "") + word + (cats.length ? ", " + cats[0] + " to " + cats[cats.length - 1] + "." : ".")];
    real.forEach(function (s) {
      var x = extremes(s.data || []);
      if (x.hiI < 0) return;
      var last = s.data[s.data.length - 1];
      parts.push(s.name + ": highest " + f(x.hi) + " in " + cats[x.hiI] + ", lowest " + f(x.lo) + " in " + cats[x.loI] + (kind === "line" && isNum(last) ? ", latest " + f(last) : "") + ".");
    });
    if (o.target && isNum(o.target.value)) parts.push((o.target.label || "Target") + " " + f(o.target.value) + ".");
    if (forecastIndex < Infinity && cats[forecastIndex]) parts.push("Figures from " + cats[forecastIndex] + " on are a forecast.");
    if (kind === "stacked") {
      var totals = cats.map(function (_, i) { return real.reduce(function (t, s) { return t + (isNum(s.data[i]) ? s.data[i] : 0); }, 0); });
      var tx = extremes(totals);
      if (tx.hiI >= 0) parts.push("Largest total " + f(tx.hi) + " in " + cats[tx.hiI] + ".");
    }
    summary(F, parts.join(" "));
    fillTable(F, (o.title || word) + " (data)", [o.categoryLabel || ""].concat(real.map(function (s) { return s.name; })),
      cats.map(function (cat, i) { return [String(cat)].concat(real.map(function (s) { return f(s.data[i]); })); }));
    return api(F, function (n) { return axisChart(host, Object.assign({}, o, n, { id: F.id }), kind); });
  }

  function api(F, redraw) {
    return { chart: F.chart, update: function (n) { return redraw(n || {}); }, resize: function () { F.chart.resize(); } };
  }
  function hexA(hex, a) {
    var h = hex.replace("#", "");
    if (h.length === 3) h = h.split("").map(function (x) { return x + x; }).join("");
    var n = parseInt(h, 16);
    return "rgba(" + (n >> 16 & 255) + "," + (n >> 8 & 255) + "," + (n & 255) + "," + a + ")";
  }

  /* ---- donut */

  function donut(host, o) {
    o = o || {};
    var F = frame(host, o, "donut");
    if (!F) return null;
    var c = colors(), f = formatter(o.format);
    var items = (o.items || []).map(function (it, i) { return { name: it.name, value: it.value, itemStyle: { color: it.color || c.list[i % 8] } }; });
    var total = items.reduce(function (t, it) { return t + (isNum(it.value) ? it.value : 0); }, 0);
    F.chart.setOption(Object.assign(anim(F), {
      legend: { show: false },
      tooltip: Object.assign(tooltipBase(), {
        trigger: "item",
        formatter: function (p) {
          return '<div class="cui-tip"><div class="cui-tip__head">' + esc(o.title || "") + "</div>" + tipRow(p.color, p.name, f(p.value)) +
            '<div class="cui-tip__extra">' + esc(fmt.pct(p.percent / 100) + " of " + f(total)) + "</div></div>";
        }
      }),
      graphic: [{ type: "text", left: "center", top: "middle", silent: true,
        style: { text: "{v|" + f(total) + "}\n{l|" + (o.centerLabel || "Total") + "}", align: "center",
          rich: { v: { fontSize: 24, fontWeight: 800, fill: c.ink, fontFamily: c.font, lineHeight: 30 }, l: { fontSize: 13, fill: c.muted, fontFamily: c.font, fontWeight: 600 } } } }],
      series: [{ type: "pie", radius: ["58%", "82%"], center: ["50%", "50%"], padAngle: 1.2, avoidLabelOverlap: true,
        itemStyle: { borderRadius: 4, borderColor: "#fff", borderWidth: 1 },
        label: { show: false }, labelLine: { show: false },
        emphasis: { scale: true, scaleSize: 6, label: { show: false } },
        data: items }]
    }));
    makeLegend(F, items.map(function (it) { return { name: it.name, color: it.itemStyle.color }; }));
    keyboard(F, function () { return items.length; }, function (i) {
      F.chart.dispatchAction({ type: "downplay", seriesIndex: 0 });
      F.chart.dispatchAction({ type: "highlight", seriesIndex: 0, dataIndex: i });
      F.chart.dispatchAction({ type: "showTip", seriesIndex: 0, dataIndex: i });
    }, true);
    var sorted = items.slice().sort(function (a, b) { return (b.value || 0) - (a.value || 0); });
    summary(F, (o.title ? o.title + ". " : "") + "Donut chart of " + items.length + " parts, total " + f(total) + ". " +
      sorted.map(function (it) { return it.name + " " + f(it.value) + " (" + fmt.pct(total ? it.value / total : NaN) + ")"; }).join(", ") + ".");
    fillTable(F, (o.title || "Donut chart") + " (data)", ["", "Value", "Share"], items.map(function (it) { return [it.name, f(it.value), fmt.pct(total ? it.value / total : NaN)]; }));
    return api(F, function (n) { return donut(host, Object.assign({}, o, n, { id: F.id })); });
  }

  /* ---- heat map */

  function heatmap(host, o) {
    o = o || {};
    var F = frame(host, o, "heatmap");
    if (!F) return null;
    var c = colors(), f = formatter(o.format);
    var xs = o.x || [], ys = o.y || [], vals = o.values || [];
    var nums = vals.map(function (v) { return v[2]; }).filter(isNum);
    var min = o.min != null ? o.min : Math.min.apply(null, nums), max = o.max != null ? o.max : Math.max.apply(null, nums);
    // Steps, not a smooth blend: every step keeps its cell label at 4.5:1 or better (dark text on the 3 light
    // steps, white text on the dark ones). A smooth blend passes through mid-tones where neither does.
    var pieces = binPieces(min, max, o.bins || 5, f);
    var data = vals.map(function (v) {
      var p = pieceFor(pieces, v[2]);
      return { value: v, label: { color: p && p.dark ? "#ffffff" : c.ink } };
    });
    F.chart.setOption(Object.assign(anim(F), {
      grid: { left: 8, right: 8, top: 8, bottom: 56, containLabel: true },
      xAxis: { type: "category", data: xs, splitArea: { show: false }, axisLine: { show: false }, axisLabel: { color: c.muted } },
      yAxis: { type: "category", data: ys, inverse: true, axisLine: { show: false }, axisLabel: { color: c.ink2, fontWeight: 600 } },
      visualMap: { type: "piecewise", pieces: pieces, orient: "horizontal", left: "center", bottom: 0, itemWidth: 14, itemHeight: 14, itemGap: 14,
        itemSymbol: "roundRect", textGap: 6, textStyle: { color: c.ink2, fontSize: 13, fontFamily: c.font, fontWeight: 600 } },
      tooltip: Object.assign(tooltipBase(), {
        trigger: "item",
        formatter: function (p) {
          return '<div class="cui-tip"><div class="cui-tip__head">' + esc(ys[p.value[1]]) + "</div>" + tipRow(p.color, xs[p.value[0]], f(p.value[2])) + "</div>";
        }
      }),
      series: [{ type: "heatmap", data: data, label: { show: o.labels !== false, fontSize: 13, fontFamily: c.font, fontWeight: 600, formatter: function (p) { return f(p.value[2]); } },
        itemStyle: { borderColor: "#ffffff", borderWidth: 2, borderRadius: 4 },
        emphasis: { itemStyle: { borderColor: c.gold, borderWidth: 2.5 } } }]
    }));
    F.legend.hidden = true;
    keyboard(F, function () { return data.length; }, function (i) {
      F.chart.dispatchAction({ type: "downplay", seriesIndex: 0 });
      F.chart.dispatchAction({ type: "highlight", seriesIndex: 0, dataIndex: i });
      F.chart.dispatchAction({ type: "showTip", seriesIndex: 0, dataIndex: i });
    }, true);
    var hi = null, lo = null;
    vals.forEach(function (v) { if (isNum(v[2])) { if (!hi || v[2] > hi[2]) hi = v; if (!lo || v[2] < lo[2]) lo = v; } });
    summary(F, (o.title ? o.title + ". " : "") + "Heat map, " + ys.length + " rows by " + xs.length + " columns." +
      (hi ? " Highest: " + ys[hi[1]] + ", " + xs[hi[0]] + ", " + f(hi[2]) + ". Lowest: " + ys[lo[1]] + ", " + xs[lo[0]] + ", " + f(lo[2]) + "." : ""));
    var grid = ys.map(function (y, yi) { return [String(y)].concat(xs.map(function (x, xi) { var v = vals.filter(function (r) { return r[0] === xi && r[1] === yi; })[0]; return v ? f(v[2]) : MISSING; })); });
    fillTable(F, (o.title || "Heat map") + " (data)", [""].concat(xs.map(String)), grid);
    return api(F, function (n) { return heatmap(host, Object.assign({}, o, n, { id: F.id })); });
  }

  /* ---- sparkline */

  function spark(host, o) {
    o = o || {};
    var F = frame(host, o, "spark");
    if (!F) return null;
    var c = colors(), f = formatter(o.format), col = o.color || c.c1;
    var data = o.data || [];
    var cats = o.categories || data.map(function (_, i) { return i + 1; });
    F.chart.setOption(Object.assign(anim(F), {
      grid: { left: 3, right: 5, top: 5, bottom: 3 },
      xAxis: { type: "category", data: cats, show: false, boundaryGap: false },
      yAxis: { type: "value", show: false, scale: true },
      tooltip: Object.assign(tooltipBase(), { trigger: "axis", padding: [6, 10], axisPointer: { type: "line", lineStyle: { color: c.lineStrong } },
        formatter: function (ps) { return '<div class="cui-tip"><div class="cui-tip__row"><span class="cui-tip__name">' + esc(o.categories ? ps[0].axisValueLabel : "") + '</span><span class="cui-tip__val">' + esc(f(ps[0].value)) + "</span></div></div>"; } }),
      series: [{ type: "line", data: data, symbol: "circle", symbolSize: 5, showSymbol: false, lineStyle: { color: col, width: 2 }, itemStyle: { color: col },
        areaStyle: { color: new global.echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: hexA(col, 0.2) }, { offset: 1, color: hexA(col, 0) }]) },
        markPoint: { symbol: "circle", symbolSize: 6, silent: true, itemStyle: { color: col }, label: { show: false }, data: [{ coord: [data.length - 1, data[data.length - 1]] }] } }]
    }));
    keyboard(F, function () { return data.length; }, function (i) { F.chart.dispatchAction({ type: "showTip", seriesIndex: 0, dataIndex: i }); });
    var x = extremes(data);
    summary(F, (o.title || "Trend") + ": " + data.length + " points, from " + f(data[0]) + " to " + f(data[data.length - 1]) +
      (x.hiI >= 0 ? ", highest " + f(x.hi) + ", lowest " + f(x.lo) : "") + ".");
    return api(F, function (n) { return spark(host, Object.assign({}, o, n, { id: F.id })); });
  }

  /* ---- US state map */

  function niceStep(span, n) {
    var raw = span / n, p = Math.pow(10, Math.floor(Math.log10(raw))), m = raw / p;
    return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
  }
  /** Value steps with round edges ("$0 to $1M", ..., "$4M or more"), coloured light to navy on the shade scale. */
  function binPieces(lo, hi, bins, f) {
    var c = colors();
    bins = Math.max(2, Math.min(bins, 6));
    var step = niceStep(Math.max(hi - lo, 1e-9), bins);
    var start = Math.floor(lo / step) * step;
    var pieces = [];
    for (var i = 0; i < bins; i++) {
      var a = start + i * step, b = a + step, last = i === bins - 1 || b > hi;
      pieces.push(last ? { gte: a, label: f(a) + " or more" } : { gte: a, lt: b, label: f(a) + " to " + f(b) });
      if (last) break;
    }
    // Up to 5 steps use shades 3 to 7, so even the lightest step stands clear of the "no data" grey;
    // 6 steps add shade 2. Labels: dark text on #a6c0d0 and lighter, white on #46738e and darker (all 4.5:1+).
    var shades = pieces.length <= 5 ? c.seq.slice(2) : c.seq.slice(1);
    pieces.forEach(function (p, j) {
      var k = Math.round(j * (shades.length - 1) / Math.max(1, pieces.length - 1));
      p.color = shades[k];
      p.dark = c.seq.indexOf(shades[k]) >= 4;
    });
    return pieces;
  }
  function pieceFor(pieces, v) {
    if (!isNum(v)) return null;
    for (var i = pieces.length - 1; i >= 0; i--) if (v >= pieces[i].gte) return pieces[i];
    return pieces[0];
  }

  function usmap(host, o) {
    o = o || {};
    if (!global.CUI_US_STATES) { CUI.error($(host), { title: "Map could not load", text: "The map file (maps/us-states.js) is missing from this dashboard's kit folder." }); return null; }
    var F = frame(host, o, "map");
    if (!F) return null;
    var c = colors(), f = formatter(o.format), names = global.CUI_US_STATES.names;
    if (!global.echarts.getMap("cui-us")) global.echarts.registerMap("cui-us", { svg: global.CUI_US_STATES.svg });
    var values = o.values || {};
    var codes = Object.keys(values).filter(function (k) { return names[k] && isNum(values[k]); });
    var nums = codes.map(function (k) { return values[k]; });
    var lo = o.min != null ? o.min : Math.min.apply(null, nums), hi = o.max != null ? o.max : Math.max.apply(null, nums);
    var pieces = binPieces(lo, hi, o.bins || 5, f);
    var noData = "#eef1f3";
    var data = Object.keys(names).map(function (k) { return { name: k, value: isNum(values[k]) ? values[k] : NaN }; });
    F.chart.setOption(Object.assign(anim(F), {
      tooltip: Object.assign(tooltipBase(), {
        trigger: "item",
        formatter: function (p) {
          var v = values[p.name];
          return '<div class="cui-tip"><div class="cui-tip__head">' + esc(names[p.name] || p.name) + "</div>" +
            (isNum(v) ? tipRow(p.color, o.valueLabel || "Value", f(v)) : '<div class="cui-tip__row"><span class="cui-tip__name">No data</span></div>') + "</div>";
        }
      }),
      visualMap: { type: "piecewise", pieces: pieces, orient: "horizontal", left: "center", bottom: 0, itemWidth: 14, itemHeight: 14, itemGap: 14,
        itemSymbol: "roundRect", text: o.legendTitle ? [null, o.legendTitle + ":  "] : null, showLabel: true, textGap: 6,
        textStyle: { color: c.ink2, fontSize: 13, fontFamily: c.font, fontWeight: 600 }, outOfRange: { color: noData } },
      series: [{ type: "map", map: "cui-us", roam: false, selectedMode: false,
        left: 8, right: 8, top: 8, bottom: 48, preserveAspect: "contain", data: data,
        itemStyle: { areaColor: noData, borderColor: "#ffffff", borderWidth: 1 },
        emphasis: { label: { show: false }, itemStyle: { areaColor: c.gold, borderColor: "#ffffff", borderWidth: 1 } } }]
    }));
    F.legend.hidden = true;
    F.canvas.style.setProperty("--cui-chart-height", o.height ? (typeof o.height === "number" ? o.height + "px" : o.height) : "420px");
    var order = Object.keys(names).sort(function (a, b) { return names[a].localeCompare(names[b]); });
    keyboard(F, function () { return order.length; }, function (i) {
      F.chart.dispatchAction({ type: "downplay", seriesIndex: 0 });
      F.chart.dispatchAction({ type: "highlight", seriesIndex: 0, name: order[i] });
      F.chart.dispatchAction({ type: "showTip", seriesIndex: 0, name: order[i] });
    }, true);
    var ranked = codes.slice().sort(function (a, b) { return values[b] - values[a]; });
    summary(F, (o.title ? o.title + ". " : "") + "US map shaded by value, " + codes.length + " states with data." +
      (ranked.length ? " Highest: " + ranked.slice(0, 3).map(function (k) { return names[k] + " " + f(values[k]); }).join(", ") +
        ". Lowest: " + ranked.slice(-3).reverse().map(function (k) { return names[k] + " " + f(values[k]); }).join(", ") + "." : ""));
    fillTable(F, (o.title || "US map") + " (data)", ["State", o.valueLabel || "Value"], ranked.map(function (k) { return [names[k], f(values[k])]; }));
    return api(F, function (n) { return usmap(host, Object.assign({}, o, n, { id: F.id })); });
  }

  /**
   * Charts. Each takes the element to draw in and an options object, and returns { chart, update(newOpts), resize }.
   * Common options: title (used for the screen-reader summary), format ("money"|"pct"|"num"|fn), notes: [..],
   * asOf: "YYYY-MM-DD", height, id (keeps "draw in once" across redraws).
   */
  CUI.chart = {
    line: function (host, o) { return axisChart(host, o, "line"); },
    area: function (host, o) { return axisChart(host, Object.assign({}, o, { area: true }), "line"); },
    bar: function (host, o) { return axisChart(host, o, "bar"); },
    stacked: function (host, o) { return axisChart(host, o, "stacked"); },
    donut: donut,
    heatmap: heatmap,
    spark: spark,
    usmap: usmap
  };

  CUI._internal = { formatChange: formatChange, toDate: toDate };
  global.CUI = CUI;
})(window);
