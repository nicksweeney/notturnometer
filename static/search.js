/* Notturnometer search: ranking + UI over dist/search-index.json.
 *
 * Replaces Pagefind, whose term-frequency model could not be made to rank a
 * composer page above a page that merely mentions the surname: a composer
 * page's whole indexable body is its name, so "Imagine Chopin" scored 188 and
 * the Frédéric Chopin page 40, un-tunable. Here ranking is ours:
 *
 *   lexical score (MiniSearch)
 *     x field boost      n=3, a=2, s=1.5
 *     x kind prior       KIND -- a bare surname should reach a composer page,
 *                        which no Pagefind knob could express
 *     x airings prior    1 + log10(1 + airings) -- "played 2,266 times"
 *                        should outrank "played once", which Pagefind ignored
 *   then an exact-name pin (widened to match a whole WORD of the name, not
 *   only the full name -- see the pin's own comment below) that fixes the
 *   Chopin case and the low-airing bare-surname cases (Mozart, Sibelius)
 *   alike.
 */
(function (global) {
  "use strict";

  var FIELDS = ["n", "a", "s"];
  var STORE = ["k", "n", "s", "u", "w", "x"];

  var BOOST = { n: 3, a: 2, s: 1.5 };

  /* Per-kind prior. composer/artist lead because a bare name query wants the
   * entity, not a work that cites it.
   *
   * episode is 0.8 DELIBERATELY: single-term "mahler" must not bury the
   * Mahler composer page under 140 nights whose subtitle names him. Multi-term
   * "mahler proms" still surfaces episodes first, because no work or composer
   * matches both terms -- which is why AND-first matching below is load-
   * bearing, not an optimisation. */
  var KIND = {
    composer: 3.0, artist: 2.5,
    country: 2.0, broadcaster: 2.0, form: 2.0, year: 2.0, browse: 2.0,
    work: 1.0, episode: 0.8
  };

  /* Deliberate mirror of ttn_analyze.ascii_fold (ttn_analyze.py, _EXTRA_FOLD
   * + ascii_fold) -- kept in sync by hand, not shared code, because one lives
   * in Python and the other in the browser. Used only by the exact-name pin
   * below: the pin compares `fold(query)` against `fold(doc.n)`, so the two
   * sides must agree on what "folded" means, or a pin match can silently
   * fail (it does NOT feed index.search(), which gets the raw query string
   * and does its own tokenizing/fuzzy matching).
   *
   * _EXTRA_FOLD exists because NFKD does not decompose these characters to
   * ASCII; translate them explicitly before normalizing, exactly as the
   * Python side does. Then NFKD + strip combining marks. */
  var EXTRA_FOLD = {
    "ł": "l", "Ł": "L",
    "ø": "o", "Ø": "O",
    "đ": "d", "Đ": "D",
    "ð": "d", "Ð": "D",
    "þ": "th", "Þ": "Th",
    "ß": "ss",
    "æ": "ae", "Æ": "Ae",
    "œ": "oe", "Œ": "Oe",
    "ı": "i", "İ": "I",
    "‐": "-", "‑": "-"   /* typographic hyphens (segments.json) */
  };
  var EXTRA_FOLD_RE = new RegExp("[" + Object.keys(EXTRA_FOLD).join("") + "]", "g");

  function fold(s) {
    s = (s || "").replace(EXTRA_FOLD_RE, function (c) { return EXTRA_FOLD[c]; });
    return s.normalize("NFKD")
      .replace(/[̀-ͯ]/g, "").toLowerCase().trim();
  }

  /* A folded name's individual words, split on anything that isn't a letter
   * or digit -- so "Jean Sibelius" yields ["jean", "sibelius"]. Used only by
   * the exact-name pin below (never exported): a bare surname query ("mozart")
   * must reach the 7,038-airing Wolfgang Amadeus Mozart, not just a doc whose
   * FULL name happens to be the bare word "Mozart" (9 airings, a real but
   * minor corpus entity -- see CLAUDE.md's Mozart/Bach bare-surname residue).
   * Matching on any single word, not only the whole name, catches both. */
  function nameWords(s) {
    return fold(s).split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  }

  function buildIndex(docs) {
    var ms = new global.MiniSearch({
      fields: FIELDS,
      storeFields: STORE,
      searchOptions: { prefix: true, fuzzy: 0.2, boost: BOOST }
    });
    docs.forEach(function (d, i) { d.id = i; });
    ms.addAll(docs);
    return ms;
  }

  function boostDocument(id, term, doc) {
    var kind = KIND[doc.k] || 1.0;
    return kind * (1 + Math.log10(1 + (doc.w || 0)));
  }

  /* AND-first, OR-fallback. "mahler proms" gives 28 under AND and 557 under
   * OR; a two-word query almost always means both words. But a query with a
   * typo'd or absent second term would return nothing under AND, so fall back
   * once the AND result is too thin to be useful. */
  var AND_FLOOR = 5;

  function runSearch(index, docs, query) {
    var q = (query || "").trim();
    if (!q) return [];

    var opts = { prefix: true, fuzzy: 0.2, boost: BOOST,
                 boostDocument: boostDocument, combineWith: "AND" };
    var hits = index.search(q, opts);
    if (hits.length < AND_FLOOR) {
      opts.combineWith = "OR";
      hits = index.search(q, opts);
    }

    /* Exact-name pin: a document whose folded name IS the query, or whose
     * name contains the query as a whole word, goes first, unconditionally,
     * ahead of scoring. This is what makes "chopin" reach
     * /composer/frederic-chopin/ rather than the work "Imagine Chopin", and
     * it is the one rule no amount of weight tuning could substitute for. */
    var folded = fold(q);
    var exact = [], rest = [];
    hits.forEach(function (h) {
      var isExact = fold(h.n) === folded || nameWords(h.n).indexOf(folded) !== -1;
      (isExact ? exact : rest).push(h);
    });
    /* Among several exact matches (the three Mozarts -- WA, Leopold, Franz
     * Xaver, plus the bare "Mozart" ambiguous-attribution entry) the airings
     * prior decides, so keep MiniSearch's score order within each bucket. */
    return exact.concat(rest);
  }

  global.TTNSearch = {
    buildIndex: buildIndex,
    runSearch: runSearch,
    fold: fold,
    nameWords: nameWords,
    KIND: KIND
  };

  /* ---- UI --------------------------------------------------------------
   * The catalogue is 1.37 MB gzipped, so it is fetched on FIRST FOCUS rather
   * than page load -- a reader who never searches never pays for it. Failure
   * hides the search box: search is an enhancement, never a gate (the same
   * degrade-don't-abort contract as the projection cache). */
  var CATALOGUE_URL = "/search-index.json";
  var MAX_DROPDOWN = 8;

  var state = { docs: null, index: null, loading: false, failed: false };

  function load() {
    if (state.index || state.loading || state.failed) return Promise.resolve();
    state.loading = true;
    return fetch(CATALOGUE_URL)
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (docs) {
        state.docs = docs;
        state.index = buildIndex(docs);
        state.loading = false;
      })
      .catch(function (e) {
        state.failed = true;
        state.loading = false;
        console.warn("Notturnometer search unavailable:", e);
        var box = document.getElementById("search");
        if (box) box.style.display = "none";
      });
  }

  /* A typed date is a JUMP, not an index entry: the 2,085 pre-2014 nights
   * whose subtitle is date junk carry no document, and this is the only way to
   * type your way to them. Accepts 2019-03-14, 14/03/2019, 14 March 2019. */
  var MONTHS = ["january", "february", "march", "april", "may", "june", "july",
                "august", "september", "october", "november", "december"];

  function parseDate(q) {
    var s = fold(q);
    var m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
    if (m) return pad(m[1], m[2], m[3]);
    m = s.match(/^(\d{1,2})[/.](\d{1,2})[/.](\d{4})$/);
    if (m) return pad(m[3], m[2], m[1]);
    m = s.match(/^(\d{1,2})\s+([a-z]+)\s+(\d{4})$/);
    if (m) {
      var mi = MONTHS.indexOf(m[2]);
      if (mi >= 0) return pad(m[3], String(mi + 1), m[1]);
    }
    return null;
  }

  /* A calendar round-trip, not a range check: month 1-12 / day 1-31 alone
   * still lets through impossible dates (2019-02-30, 2019-04-31, and any
   * non-leap-year Feb 29) that would link to an episode URL that can never
   * exist. Date's own month/day rollover means an out-of-range value comes
   * back as a DIFFERENT calendar date -- comparing the round-trip catches
   * every invalid case (including leap years) with no month-length table. */
  function pad(y, mo, d) {
    y = +y; mo = +mo; d = +d;
    var dt = new Date(Date.UTC(y, mo - 1, d));
    if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) {
      return null;
    }
    var moS = String(mo).padStart(2, "0");
    var dS = String(d).padStart(2, "0");
    return { date: y + "-" + moS + "-" + dS, url: "/episode/" + y + "/" + moS + "/" + dS + "/" };
  }

  function resultRow(hit, idx) {
    var li = document.createElement("li");
    li.id = "search-opt-" + idx;
    li.setAttribute("role", "option");
    li.setAttribute("aria-selected", "false");
    var a = document.createElement("a");
    a.href = hit.u;
    var name = document.createElement("span");
    name.className = "sr-name";
    name.textContent = hit.n;
    var kind = document.createElement("span");
    kind.className = "sr-kind";
    kind.textContent = hit.k;
    a.appendChild(name);
    a.appendChild(kind);
    var sub = hit.s || hit.x;
    if (sub) {
      var s = document.createElement("span");
      s.className = "sr-sub";
      s.textContent = sub;
      a.appendChild(s);
    }
    li.appendChild(a);
    return li;
  }

  function dateRow(parsed, idx) {
    var li = document.createElement("li");
    li.id = "search-opt-" + idx;
    li.setAttribute("role", "option");
    li.setAttribute("aria-selected", "false");
    li.className = "sr-date";
    var a = document.createElement("a");
    a.href = parsed.url;
    a.textContent = "Go to " + parsed.date;
    li.appendChild(a);
    return li;
  }

  function initDropdown() {
    var input = document.getElementById("search-input");
    var list = document.getElementById("search-results");
    var form = document.getElementById("search-form");
    if (!input || !list || !form) return;

    /* aria-activedescendant, not real DOM focus: focus stays on the input
     * the whole time, and `cursor` is only a pointer to the "current option"
     * (mirrored onto the input's aria-activedescendant + each row's
     * aria-selected for assistive tech, and .sr-active for sighted users).
     * A result <a> is a SIBLING of the input, not a descendant -- moving
     * real focus onto it means keydown no longer reaches the input's own
     * listener (bubbling stops at the row), which silently breaks a second
     * arrow press, Escape, and the Enter-selects-row branch. Keeping focus
     * on the input keeps every one of those reachable, and the reader can
     * keep typing without losing their place. */
    var cursor = -1;

    function close() {
      list.hidden = true;
      list.textContent = "";
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      cursor = -1;
    }

    function render() {
      var q = input.value.trim();
      if (!q || !state.index) return close();

      list.textContent = "";
      var idx = 0;
      var parsed = parseDate(q);
      if (parsed) list.appendChild(dateRow(parsed, idx++));

      var hits = runSearch(state.index, state.docs, q).slice(0, MAX_DROPDOWN);
      hits.forEach(function (h) { list.appendChild(resultRow(h, idx++)); });

      if (!list.children.length) return close();
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      input.removeAttribute("aria-activedescendant");
      cursor = -1;
    }

    input.addEventListener("focus", function () {
      load().then(function () { if (input.value.trim()) render(); });
    });
    input.addEventListener("input", function () {
      if (state.index) render();
      else load().then(render);
    });
    input.addEventListener("keydown", function (e) {
      var rows = list.querySelectorAll("li");
      if (e.key === "Escape") return close();
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (!rows.length) return;
        e.preventDefault();
        cursor += (e.key === "ArrowDown" ? 1 : -1);
        if (cursor < 0) cursor = rows.length - 1;
        if (cursor >= rows.length) cursor = 0;
        rows.forEach(function (r, i) {
          var active = i === cursor;
          r.classList.toggle("sr-active", active);
          r.setAttribute("aria-selected", active ? "true" : "false");
        });
        input.setAttribute("aria-activedescendant", rows[cursor].id);
        rows[cursor].scrollIntoView({ block: "nearest" });
        return;
      }
      if (e.key === "Enter" && cursor >= 0 && rows.length) {
        e.preventDefault();
        rows[cursor].querySelector("a").click();
      }
      /* Enter with cursor === -1 (nothing highlighted) falls through to the
       * form's native submit -> GET /search/?q=... */
    });
    document.addEventListener("click", function (e) {
      if (!document.getElementById("search").contains(e.target)) close();
    });
  }

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", initDropdown);
    } else {
      initDropdown();
    }
  }

  /* ---- parseDate sanity check --------------------------------------------
   * Small node-runnable assertion block, not a test framework: parseDate has
   * real branching (3 formats, invalid month/day) and no other test covers
   * it. Run with: node static/search.js */
  if (typeof process !== "undefined" && process.argv[1] &&
      process.argv[1].indexOf("search.js") !== -1) {
    (function () {
      function check(input, want) {
        var got = parseDate(input);
        var gotStr = got ? got.date : null;
        var ok = gotStr === want;
        console.log((ok ? "ok  " : "FAIL") + "  parseDate(" + JSON.stringify(input) +
                    ") = " + JSON.stringify(gotStr) + (ok ? "" : "  (wanted " + JSON.stringify(want) + ")"));
        if (!ok) process.exitCode = 1;
      }
      check("2019-03-01", "2019-03-01");
      check("14/03/2019", "2019-03-14");
      check("14 March 2019", "2019-03-14");
      check("2019-13-01", null);   // invalid month
      check("2019-02-40", null);   // invalid day
      check("mahler", null);       // non-date
      check("2019-02-30", null);   // Feb has no 30th
      check("2019-04-31", null);   // April has 30 days
      check("2019-02-29", null);   // 2019 is not a leap year
      check("2020-02-29", "2020-02-29");  // 2020 IS a leap year
    })();
  }
})(typeof window !== "undefined" ? window : globalThis);
