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
})(typeof window !== "undefined" ? window : globalThis);
