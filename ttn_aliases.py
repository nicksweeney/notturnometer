"""Hand-curated alias tables for ttn_analyze — composer, ensemble, and work
title rephrasings the canonical_key / work_title_key normalisers can't reach.

Pure data (string-pair tuples), split out of ttn_analyze.py to keep that
module's logic legible. Imported by ttn_analyze._build_*;
ttn_analyze._summary_code_fingerprint hashes this file's bytes, so editing a
table here invalidates the derived caches exactly as an edit to ttn_analyze.py
does.
"""


# Composer aliases — name variants canonical_key alone can't unify. Each pair
# is (alternate_form, preferred_form); matching is on canonical_key(name), so
# capitalisation, diacritics and minor punctuation don't matter. To extend,
# add a tuple. Entries are grouped by category; counts in comments reflect the
# dataset that informed the preferred form (usually the more common BBC form).
_COMPOSER_ALIAS_PAIRS = [
    # --- U+FFFD replacement-char corruptions (2026-07-14) ---
    # é/ó lost to a bad decode (replaced by the Unicode replacement char), so
    # _demojibake can't reverse them -- the original byte is gone. 1 airing each;
    # folding removes the bogus composer pages they minted (surfaced by Pagefind
    # composer-search ranking garbled Chopins above the canonical Fryderyk Chopin).
    ("Fr�d�ric Chopin",   "Fryderyk Chopin"),   # raw U+FFFD
    ("Frï¿½dï¿½ric Chopin",         "Fryderyk Chopin"),   # U+FFFD bytes re-mangled via Latin-1
    ("Henryk Mikolaj Gï¿½recki",    "Henryk Gorecki"),    # Górecki, same corruption

    # --- Named-composer + arranger contamination (2026-07-14) ---
    # An "arr. <arranger>" tail leaked into the composer field. Only NAMED
    # composers fold -- "Traditional/Anonymous arr. X" keep their own identity
    # (the composer really is Traditional, not the arranger). Chopin's Nocturne
    # in C# minor, Milstein's violin arrangement; both spacings, 1 airing each.
    # (Milstein's own Paganiniana stays under "Nathan Milstein".)
    ("Fryderyk Chopin arr. Nathan Milstein", "Fryderyk Chopin"),
    ("Fryderyk Chopin arr.Nathan Milstein",  "Fryderyk Chopin"),

    # --- Older-BBC format variants (pre-~2017 episodes) ---
    # In the 2016 era, BBC included middle names and used German first-name
    # forms that the modern format normalises away. Once the 10-year scrape
    # lands, the analyzer's n_variants column will surface more of these
    # for review.
    ("Edvard Hagerup Grieg",        "Edvard Grieg"),
    # Bare-surname credit: 17 tracks, all identifiable Edvard works
    # (Opp 12/24/36/38/43/45/74 + the unfinished quartet); single in-corpus
    # bearer, the Bellini precedent (audited 2026-07-05).
    ("Grieg",                       "Edvard Grieg"),
    ("Georg Frideric Handel",       "George Frideric Handel"),
    # German form — "Friedrich" + umlauted "Händel"; canonical_key folds the
    # umlaut, so this one pair also covers the de-umlauted "Georg Friedrich
    # Handel". "George Friedrich" (Georg-e) needs its own entry.
    ("Georg Friedrich Händel",      "George Frideric Handel"),
    ("George Friedrich Handel",     "George Frideric Handel"),

    # --- Russian transliteration variants ---
    ("Sergei Prokofiev",            "Sergey Prokofiev"),          # 4 → 236
    ("Dmitri Shostakovich",         "Dmitry Shostakovich"),       # 8 → 228
    ("Pyotr Ilyich Tchaikovsky",    "Peter Ilyich Tchaikovsky"),  # 36 → 449
    ("Anatoly Lyadov",              "Anatol Lyadov"),             # 1 → 20
    # Forward-compat: variants not in the 5-year data but likely in older episodes
    ("Sergei Rachmaninov",          "Sergey Rachmaninov"),
    ("Sergei Rachmaninoff",         "Sergey Rachmaninov"),
    ("Sergey Rachmaninoff",         "Sergey Rachmaninov"),
    ("Modeste Moussorgsky",         "Modest Mussorgsky"),
    ("Modest Moussorgsky",          "Modest Mussorgsky"),
    ("Modest Musorgsky",            "Modest Mussorgsky"),
    ("Modest Petrovich Mussorgsky", "Modest Mussorgsky"),         # 34 → 128
    ("Aleksandr Borodin",           "Alexander Borodin"),
    ("Alexander Porfiryevich Borodin", "Alexander Borodin"),
    ("Mikhail Ivanovich Glinka",    "Mikhail Glinka"),
    ("Aram Khachaturyan",           "Aram Khachaturian"),
    ("Aram Khatchaturian",          "Aram Khachaturian"),

    # --- Polish / French rendering of same composer ---
    # Frédéric Chopin: BBC uses "Fryderyk Chopin" consistently (874 plays); forward-compat:
    ("Frederic Chopin",             "Fryderyk Chopin"),
    ("Frédéric Chopin",             "Fryderyk Chopin"),

    # --- German / Hungarian / Latin renderings ---
    ("Christoph Willibald Gluck",   "Christoph Gluck"),           #  8 → 22
    ("Alexander Zemlinsky",         "Alexander von Zemlinsky"),   # 16 → 18  (with "von" is more formal)
    ("Karoly Goldmark",             "Karl Goldmark"),             # 11 → 31
    ("Josef Rheinberger",           "Joseph Rheinberger"),        #  5 → 14
    ("Sebastian Le Camus",          "Sebastien Le Camus"),        #  6 →  7

    # --- Medieval / preposition variants ---
    ("Hildegard von Bingen",        "Hildegard of Bingen"),       # 38 → 71

    # --- Scandinavian language variants ---
    ("Ludwig Norman",               "Ludvig Norman"),             # 15 → 74

    # --- Honorifics, multi-rendering Latinizations etc. ---
    ("Dame Ethel Mary Smyth",       "Ethel Smyth"),               # 25 → 27
    ("Marianne Martines",                              "Marianne Martinez"),
    ("Marianna Martines",                              "Marianne Martinez"),
    ("Marianne von Martinez",                          "Marianne Martinez"),
    ("Marianne Martines or Marianne von Martinez",     "Marianne Martinez"),  # actual BBC string!
    ("Antoine Forqueray ['le pere']",                  "Antoine Forqueray"),
    ("Antoine Forqueray ['le père']",                  "Antoine Forqueray"),

    # --- High-confidence audit-surfaced splits: typos, mojibake, accents,
    # bare surnames, same-name spelling variants (May 2026 alias sweep) ---
    ("Vicente Adán",                "Vincente Adan"),
    ("Tomasi Albinoni",             "Tomaso Albinoni"),
    ("Ludvig van Beethoven",        "Ludwig van Beethoven"),
    ("George Bizet",                "Georges Bizet"),
    ("Brahms",                      "Johannes Brahms"),
    ("Firminius Caron",             "Firminus Caron"),
    ("Iacobus Gallus Carniolus",    "Jacobus Gallus Carniolus"),
    ("Jacobus Gallus",              "Jacobus Gallus Carniolus"),  # bare form, single bearer (1x, 2009)
    ("Frédéric Chopin",             "Fryderyk Chopin"),
    ("Cornelius Dopper",            "Cornelis Dopper"),
    ("Anton Dvorak",                "Antonin Dvorak"),
    ("Hans Eisler",                 "Hanns Eisler"),
    ("Manuela de Falla",            "Manuel de Falla"),
    ("Niels Wilhelm Gade",          "Niels Gade"),
    ("Johnny Greenwood",            "Jonny Greenwood"),
    ("Sofiya Gubaidulina",          "Sofia Gubaidulina"),
    ("Johann Halvorsen",            "Johan Halvorsen"),
    ("Johann Adolfe Hasse",         "Johann Adolf Hasse"),
    ("Haydn",                       "Joseph Haydn"),
    ("Franz Joseph Haydn",          "Joseph Haydn"),
    ("Josef Haydn",                 "Joseph Haydn"),
    ("Jozef Haydn",                 "Joseph Haydn"),
    ("Johann Michael Haydn",        "Michael Haydn"),  # brother — distinct from Joseph
    ("Nicolo Jommelli",             "Niccolo Jommelli"),
    ("Dimitri Kabalevsky",          "Dmitri Kabalevsky"),
    ("Uno Klami",                   "Uuno Klami"),
    ("Victor Kosenko",              "Viktor Kosenko"),
    ("Frederik Kuhlau",             "Friedrich Kuhlau"),
    ("Johan Kuhnau",                "Johann Kuhnau"),
    ("Krassimir Kyurkchiyski",      "Krasimir Kyurkchiyski"),
    ("Oscar Merikanto",             "Oskar Merikanto"),
    ("Tarquino Merula",             "Tarquinio Merula"),
    ("Goesta Nystroem",             "Gosta Nystroem"),
    ("Jakob Obrecht",               "Jacob Obrecht"),
    ("Frederik Pacius",             "Fredrik Pacius"),
    ("Nicolò Paganini",             "Niccolo Paganini"),
    ("Kryzstof Penderecki",         "Krzysztof Penderecki"),
    ("Lubomir Pipkov",              "Lyubomir Pipkov"),
    ("Puccini",                     "Giacomo Puccini"),
    ("Gioacchino Rossini",          "Gioachino Rossini"),
    ("Dimitri Shostakovich",        "Dmitry Shostakovich"),
    ("Ludwig Spohr",                "Louis Spohr"),
    ("Stanford",                    "Charles Villiers Stanford"),
    ("Bernado Storace",             "Bernardo Storace"),
    ("Johann II Strauss",           "Johann Strauss II"),
    ("Johann Jr Strauss",           "Johann Strauss II"),
    ("Johann Strauss Jr",           "Johann Strauss II"),
    ("Sullivan",                    "Arthur Sullivan"),
    ("Johann Svendsen",             "Johan Svendsen"),
    ("Kjohn Tavener",               "John Tavener"),
    ("Eduardo Toldrá",              "Eduard Toldra"),
    ("Verdi",                       "Giuseppe Verdi"),
    ("Guiseppe Verdi",              "Giuseppe Verdi"),
    ("Mykhalo Verbytsky",           "Mykhailo Verbytsky"),
    ("Charles Marie Widor",         "Charles-Marie Widor"),
    ("Giacches de Wert",            "Giaches de Wert"),

    # --- Audit-surfaced splits, patronymic added/dropped (May 2026 sweep) ---
    ("Anton Stepanovich Arensky",         "Anton Arensky"),
    ("Alexander Konstantinovich Glazunov", "Alexander Glazunov"),
    ("Mily Balakirev",                    "Mily Alexeyevich Balakirev"),
    ("Aram Ilyich Khachaturian",          "Aram Khachaturian"),
    ("Anton Grigoryevich Rubinstein",     "Anton Rubinstein"),
    ("Dmitry Borisovich Kabalevsky",      "Dmitri Kabalevsky"),
    ("Anatoly Konstantinovich Lyadov",    "Anatol Lyadov"),
    ("Maxim Sosontovitch Berezovsky",     "Maxim Berezovsky"),
    ("Maksym Berezovsky",                 "Maxim Berezovsky"),
    ("Dmitri Dmitriyevich Shostakovich",  "Dmitry Shostakovich"),
    ("Dmitry Dmitriyevich Shostakovich",  "Dmitry Shostakovich"),
    ("Alexandr Tikhonovich Grechaninov",  "Alexander Gretchaninov"),
    ("Alexander Grechaninov",             "Alexander Gretchaninov"),
    ("Alexander Raichev",                 "Alexander Raychev"),
    ("Josip Slavenski",                   "Josip Stolcer-Slavenski"),
    ("Ilja Zelenka",                      "Ilja Zeljenka"),
    ("Štefan Németh-Šamorinsky",          "Nemeth-Samorinsky Stefan"),
    ("Ion Dimitrescu",                    "Ion Dumitrescu"),
    ("Maciej Radziwiłll",                 "Maciej Radziwill"),
    ("Gedimas Gelgotas",                  "Gediminas Gelgotas"),
    # --- ttn_composer_duplicates high-confidence batch (same-person splits:
    #     spelling/transliteration/typo/name-order variants) ---
    ("Mario Castelnuovo Tedesco",         "Mario Castelnuovo-Tedesco"),
    ("Florian Leopold Gassman",           "Florian Leopold Gassmann"),
    ("Georg Druschetsky",                 "Georg Druschetzky"),
    ("Jozef Wienawski",                   "Jozef Wieniawski"),
    ("Philip Koutev",                     "Filip Kutev"),
    ("Adolf Fredik Lindblad",             "Adolf Fredrik Lindblad"),
    ("Marcel Samuel-Rosseau",             "Marcel Samuel-Rousseau"),
    ("Ildebrando Pizetti",                "Ildebrando Pizzetti"),
    ("Trond H. F. Kverno",                "Trond H.F.Kverno"),
    ("Trond H.F. Kverno",                 "Trond H.F.Kverno"),
    ("Mykola Leontovitch",                "Mykola Leontovych"),
    ("Clara Schumann-Wieck",              "Clara Schumann"),
    ("Maria Theresia Von Paradies",       "Maria Theresia von Paradis"),
    ("Johann Gottfried Eckhard",          "Johann Gottfried Eckard"),
    ("Georgi Zlatev-Čerkin",              "Georgi Zlatev-Cherkin"),
    ("Sebastian Yradier",                 "Sebastián Iradier"),
    ("Sebastien Yradier",                 "Sebastián Iradier"),
    ("Jan Pieterszoon Sweelink",          "Jan Pieterszoon Sweelinck"),
    ("Théodore Lailliet",                 "Théodore Lalliet"),
    ("Nicholas Gilbert",                  "Nicolas Gilbert"),
    ("Alfreds Kalninš",                   "Alfred Kalnins"),
    ("Ture Rangstöm",                     "Ture Rangstrom"),
    ("Gabriel Mariel",                    "Gabriel Marie"),
    ("Gian Carlo Callo",                  "Gian Carlo Cailo"),
    ("Johannes Schenck",                  "Johann Schenck"),
    ("John Fransden",                     "John Frandsen"),
    ("Antony Holborne",                   "Anthony Holborne"),
    ("Jean de Castro",                    "Jan de Castro"),
    ("François Dufault",                  "Francois Dufaut"),
    ("Gasper Fernandes",                  "Gaspar Fernandes"),
    # --- circa-date cascade: early-music splits surfaced once parse_span
    #     read c./ca. dates correctly (date-corroboration then matched) ---
    ("Josquin Desprez",                   "Josquin des Prez"),
    ("Josquin des Pres",                  "Josquin des Prez"),
    ("Johann Heinrich Schmeltzer",        "Johann Heinrich Schmelzer"),
    ("Johann Christian Schickhard",       "Johann Christian Schickhardt"),
    ("Giovanni Girolamo Kapsperger",      "Giovanni Girolamo Kapsberger"),
    ("Mönch von Salzburg",                "Monk of Salzburg"),
    ("Camille Saint-SaÃ\"ns",             "Camille Saint-Saens"),
    # display-override cases: the corpus-majority spelling is the error, so
    # these fold to the CORRECT spelling and pin it via _COMPOSER_DISPLAY_PREFERENCES
    ("Maurice Green",                     "Maurice Greene"),
    ("Jacques Boufil",                    "Jacques Bouffil"),
    ("Stefan Boleslaw Prodowski",         "Stefan Bolesław Poradowski"),
    ("Samuel de sr Lange",                "Samuel de Lange Sr"),
    # --- ttn_composer_duplicates sub-0.82 judgment calls (same person, large
    #     name variation: forename-language, name-order, nickname, married name) ---
    ("Pau Casals",                        "Pablo Casals"),
    # Pure surname-first / name-order flips the scraper's surname-flip left
    # unflipped (both tokens ambiguous). Found by a same-tokens-reversed scan;
    # the MBID-marked ones are corroborated by segment_events (one spelling
    # carries the MusicBrainz id, the other is its untagged reversal).
    ("Farkas Ferenc",                     "Ferenc Farkas"),    # MBID 12b0b744
    ("Chopin Frédéric",                   "Fryderyk Chopin"),  # MBID 09ff1fe8 (target = final Polish canonical)
    ("Chen Qigang",                       "Qigang Chen"),      # MBID bbb098da (Chinese surname-first)
    ("Romero Aldemaro",                   "Aldemaro Romero"),  # MBID 7d5d850b
    ("Dolf Tumasch",                      "Tumasch Dolf"),     # MBID 2d2cec51 (Romansh)
    ("Kurtág György",                     "Gyorgy Kurtag"),    # György Kurtág, surname-first (no MBID in segments)

    # --- Bare-surname fragments (single token) whose surname has exactly ONE
    #     full-name bearer in the corpus — the safe-fold rule. Multi-bearer
    #     surnames (Mozart, Schubert, Nin, Purcell, Vitali, …) stay split:
    #     genuine ambiguity, not a missing alias. Found by a bare→single-bearer
    #     scan. (Strauss looks multi-bearer by name but is resolved below.)
    ("Chopin",                            "Fryderyk Chopin"),
    ("Moniuszko",                         "Stanislaw Moniuszko"),
    ("Goossens",                          "Eugene Goossens"),
    ("Kaufman",                           "Nikolai Kaufman"),
    ("Kyurkchiyski",                      "Krasimir Kyurkchiyski"),
    ("Vásquez",                           "Juan Vásquez"),
    ("Vivaldi",                           "Antonio Vivaldi"),
    ("Beethoven",                         "Ludwig van Beethoven"),
    ("Castello",                          "Dario Castello"),
    ("Dvorak",                            "Antonin Dvorak"),
    ("Merula",                            "Tarquinio Merula"),
    ("Piccinini",                         "Alessandro Piccinini"),
    ("Storace",                           "Bernardo Storace"),
    # Biber: the two "bearers" are one person (middle name 'Franz' dropped) —
    # fold the variant, then the bare surname folds into the single bearer.
    ("Heinrich Ignaz von Biber",          "Heinrich Ignaz Franz von Biber"),
    ("Biber",                             "Heinrich Ignaz Franz von Biber"),

    # Strauss: name-count says multi-bearer, but bare "Strauss" / "Johann
    # Strauss" are in THIS corpus uniformly Johann Strauss II repertoire (Blue
    # Danube, Wienerblut, Tritsch-Tratsch, Fledermaus, Wein Weib und Gesang …) —
    # never the father or Richard. ttn_mbid_audit resolves bare "Strauss" via
    # MBID 8255db36 (45 air, 0 ambiguity). "Johann Strauss" is folded on
    # REPERTOIRE — every work is the son's; its segment MBID (725fb443) is
    # mis-tagged to a father/ambiguous node, a case where titles beat MBID.
    ("Strauss",                           "Johann Strauss II"),
    ("Johann Strauss",                    "Johann Strauss II"),
    ("Pierre-Alexandre-François Boëly",   "Alexandre Pierre Francois Boely"),
    ("Fredrika Peyron",                   "Ika Peyron"),
    ("Alma Mahler-Werfel",                "Alma Mahler"),
    ("Boris Lyatoshynsky",                "Boris Mykolayovich Lyatoshynsky"),
    ("Borys Mykolayovich Lyatoshynsky",   "Boris Mykolayovich Lyatoshynsky"),
    ("Nicolay Andreyevich Rimsky-Korsakov", "Nikolai Rimsky-Korsakov"),
    ("Nicolai Rimsky-Korsakov",           "Nikolai Rimsky-Korsakov"),
    ("Nikolay Rimsky-Korsakov",           "Nikolai Rimsky-Korsakov"),
    ("Rodion Konstantinovich Shchedrin",  "Rodion Shchedrin"),
    ("Sergei Taneyev",                    "Sergey Ivanovich Taneyev"),
    ("Sergei Ivanovich Taneyev",          "Sergey Ivanovich Taneyev"),
    ("Sergey Sergeyevich Prokofiev",      "Sergey Prokofiev"),
    ("Serge Prokofiev",                   "Sergey Prokofiev"),
    ("Sergei Sergeyevich Prokofiev",      "Sergey Prokofiev"),
    ("Pyotr Il'yich Tchaikovsky",         "Peter Ilyich Tchaikovsky"),
    ("Pyotr Tchaikovsky",                 "Peter Ilyich Tchaikovsky"),
    ("Pitor Illyich Tchaikovsky",         "Peter Ilyich Tchaikovsky"),
    ("Piotr Ilyich Tchaikovsky",          "Peter Ilyich Tchaikovsky"),
    ("Pytor Il'yich Tchaikovsky",         "Peter Ilyich Tchaikovsky"),
    ("Peter Illych Tchaikovsky",          "Peter Ilyich Tchaikovsky"),
    ("Peter Ilych Tchaikovsky",           "Peter Ilyich Tchaikovsky"),
    ("Peter Tchaikovsky",                 "Peter Ilyich Tchaikovsky"),

    # --- Audit-surfaced splits, middle/given name added or dropped ---
    ("Daniel-Francois-Esprit Auber",      "Daniel Auber"),
    ("Adrien Boieldieu",                  "Francois-Adrien Boieldieu"),
    ("Charles Hubert Hastings Parry",     "Hubert Parry"),
    ("Max Christian Friedrich Bruch",     "Max Bruch"),
    ("William Elden Bolcom",              "William Bolcom"),
    ("Henry Charles Litolff",             "Henry Litolff"),
    ("Horatio William Parker",            "Horatio Parker"),
    ("Etienne-Nicolas Méhul",             "Etienne Mehul"),
    ("Johann Peter Emilius Hartmann",     "Johan Peter Emilius Hartmann"),
    ("Jeanne Louise Dumont Farrenc",      "Louise Farrenc"),
    ("Louise Dumont Farrenc",             "Louise Farrenc"),
    ("Johann Franz Xaver Sterkel",        "Franz Xaver Sterkel"),
    ("Friedrich Ludwig Aemilius Kunzen",  "Friedrich Kunzen"),
    ("Erich Korngold",                    "Erich Wolfgang Korngold"),
    ("Count Unico Van Wassenaer",         "Unico Wilhelm Van Wassenaer"),
    ("Grzegorz G Gorczycki",              "Grzegorz Gerwazy Gorczycki"),
    ("Francesco Paolo Tosti",             "Paolo Tosti"),
    ("Bedrich Antonin Wiedermann",        "Bedrich Anton Wiedermann"),
    ("Francesco Veracini",                "Francesco Maria Veracini"),
    ("Daniel Jean Yves Daniel-Lesur",     "Jean-Yves Daniel-Lesur"),
    ("Jean Yves Daniel-Lesur",            "Jean-Yves Daniel-Lesur"),
    ("Antonín Reichenauer",               "Johann Anton Reichenauer"),
    ("Jean-Joseph Cassanéa de Mondonville", "Jean-Joseph de Mondonville"),
    ("Heinrich Ignaz Franz Biber",        "Heinrich Ignaz Franz von Biber"),
    ("Pietro Antonio Cesti",              "Antonio Cesti"),
    ("Pietro Marc'Antonio Cesti",         "Antonio Cesti"),
    ("Fanny Hensel Mendelssohn",          "Fanny Mendelssohn"),
    # Married-name-only credit: 2 tracks ('The Year' = Das Jahr; Overture in
    # C), both hers (2026-07-05).
    ("Fanny Hensel",                      "Fanny Mendelssohn"),
    ("Felix Mendelssohn-Bartholdy",       "Felix Mendelssohn"),
    ("Felix Mendelssohn Bartholdy",       "Felix Mendelssohn"),
    # Bare-surname credit: 22 tracks, every one an identifiable FELIX work
    # (Opp 27/36/78/90/104/107, string symphonies, the 1823 double concerto,
    # Lieder ohne Worte with Felix opus numbers) — audited 2026-07-05. Unlike
    # the Bach/Matteis bare-surname residue there is no mixed attribution in
    # the corpus; if a bare-'Mendelssohn' FANNY credit ever appears, revisit.
    ("Mendelssohn",                       "Felix Mendelssohn"),

    # --- Audit-surfaced splits, name-form / language renderings; merged,
    # display follows the most-aired BBC spelling (May 2026 sweep) ---
    ("Erno Dohnanyi",                     "Ernst von Dohnanyi"),
    ("Dohnányi Ernő",                     "Ernst von Dohnanyi"),
    ("Anton Reicha",                      "Antoine Reicha"),
    ("Carl von Dittersdorf",              "Carl Ditters von Dittersdorf"),
    ("Bernard Henrik Crusell",            "Bernhard Henrik Crusell"),
    ("Józef Antoni Franciszek Elsner",    "Jozef Elsner"),
    ("Imre Kalman",                       "Emmerich Imre Kalman"),
    ("Johann Kaspar Kerll",               "Johann Caspar Kerll"),
    ("Valentin Bakfark",                  "Balint Bakfark"),
    ("Mihail Ivanovic Glinka",            "Mikhail Glinka"),
    ("Christoph Wilibald Gluck",          "Christoph Gluck"),
    ("Komitas",                           "Vardapet Komitas"),
    ("Soghomon Komitas",                  "Vardapet Komitas"),
    ("Orlando Lassus",                    "Orlande de Lassus"),
    ("Orlando di Lasso",                  "Orlande de Lassus"),
    ("Petr Machajdík",                    "Peter Machajdík"),
    ("Pierre van Maldere",                "Pieter van Maldere"),
    ("Henri Du Mont",                     "Henry du Mont"),
    ("Frederic Mompou",                   "Federico Mompou"),
    ("Manuel Ponce",                      "Manuel Maria Ponce"),
    ("Mykola Dmytrovich Leontovych",      "Mykola Leontovych"),
    ("Suor Chiara Margarita Cozzolani",   "Chiara Margarita Cozzolani"),
    ("Anton Kraft",                       "Antonin Kraft"),
    ("Carl Otto Nicolai",                 "Otto Nicolai"),
    ("E.J. Moeran",                       "Ernest John Moeran"),
    ("JA Hasse",                          "Johann Adolf Hasse"),

    # --- Bortniansky: 5 spellings of one composer; display resolves to the
    # most-aired form by play-count (no manual canonical-form pick) ---
    ("Dmitry Bortniansky",                "Dmytro Bortniansky"),
    ("Dmitry Bortnyansky",                "Dmytro Bortniansky"),
    ("Dmitro Bortnyansky",                "Dmytro Bortniansky"),
    ("Dmitri Bortnyansky",                "Dmytro Bortniansky"),

    # --- Surfaced by the --surname aggregation lens (2026-05-30) ---
    # Honorific permutations of Edward Elgar the token sort can't reorder,
    # and a literal '?' mojibake for ł in one Moniuszko row (the proper ł
    # form already folds via _EXTRA_FOLD).
    ("Elgar, Sir Edward",                 "Edward Elgar"),
    ("Sir Edward Elgar",                  "Edward Elgar"),
    ("Edward Sir Elgar",                  "Edward Elgar"),
    ("Stanis?aw Moniuszko",               "Stanislaw Moniuszko"),

    # --- Surfaced by `--mode audit` candidate list (2026-05-31). Same-person
    # forms the token sort can't reach: honorific "Surname, Title Forename"
    # malformed credits, diacritic/transliteration + middle-name expansions,
    # and bare surnames with a single in-corpus bearer. Ambiguous family
    # surnames (Johann Bach → 8 Bachs, Strauss → 7, bare Mozart → 3, Nin → 2)
    # and structurally-subset-but-distinct people (J C Bach vs J C F Bach,
    # the two Fischers, the Chédeville brothers) are deliberately left split.
    ("Bax, Sir Arnold",                     "Arnold Bax"),
    ("Birtwistle, Sir Harrison",            "Harrison Birtwistle"),
    ("Parry, Sir Charles Hubert Hastings",  "Hubert Parry"),
    ("Biber, Heinrich Ignaz Franz von Biber", "Heinrich Ignaz Franz von Biber"),
    ("Ástor Pantaleón Piazzolla",           "Astor Piazzolla"),
    ("Henryk Mikołaj Górecki",              "Henryk Gorecki"),
    ("Mikolaj Gorecki",                     "Henryk Gorecki"),
    ("Juan Crisóstomo de Arriaga",          "Juan Crisostomo Arriaga"),
    ("Kaspar Jr Förster",                   "Kaspar Foerster"),  # retargeted with the Foerster display fix
    ("Grigoraş Ionică Dinicu",              "Grigoras Dinicu"),
    ("Valentin Vasilyovych Silvestrov",     "Valentin Silvestrov"),
    ("Valentin Vasilyevich Silvestrov",     "Valentin Silvestrov"),
    ("Pietro Antonio Locatelli",            "Pietro Locatelli"),
    ("Ivan Mane Jarnovic",                  "Ivan Jarnovic"),
    ("Giya Alexandrovich Kancheli",         "Giya Kancheli"),
    ("Giovanni Gastoldi",                   "Giovanni Giacomo Gastoldi"),
    ("Ferdinand Huber",                     "Ferdinand Furchtegott Huber"),
    ("Pierre Sandrin",                      "Pierre Regnault Sandrin"),
    ("Gordon H. Dyson",                     "Gordon Dyson"),
    ("Clemens non Papa",                    "Jacobus Clemens non Papa"),
    ("Albertus Groneman",                   "Johannes Albertus Groneman"),
    ("Johannes Groneman",                   "Johannes Albertus Groneman"),
    ('Rossi, Camilla de - "La Romana"',     "Camilla de Rossi"),
    ('Camilla de "La Romana" Rossi',        "Camilla de Rossi"),
    ("Bellini",                             "Vincenzo Bellini"),
    ("Contant",                             "Alexis Contant"),
    ("Pettersson",                          "Allan Pettersson"),
    ("Kainz",                               "Joseph Kainz"),
    ("WA Mozart",                           "Wolfgang Amadeus Mozart"),
    # --- Surfaced via the --by composer --once CSV (2026-06-02). Salomone/
    # Salamone is a vowel-transliteration split of one composer; "atrributed"
    # is a single one-off typo (1×) split off the 7-airing "Attributed Mozart"
    # doubtful-attribution group (the Anh.C works) — folded to the correct
    # spelling, not into Mozart proper (the attribution split is left as-is). ---
    ("Salomone Rossi",                      "Salamone Rossi"),
    ("atrributed Mozart, Wolfgang Amadeus", "Attributed Mozart, Wolfgang Amadeus"),
    # --- Surfaced via `--mode audit` surname-span list (2026-06-02). Same-
    # person spelling/transliteration splits hiding among genuinely-distinct
    # same-surname composers. Each composer's spellings merge; the distinct
    # people sharing the surname (Juriaan/Louis Andriessen, Dirk Schafer vs the
    # Canadian R. Murray Schafer, Veselin vs Pencho Stoyanov) stay split. ---
    ("Carl Philipp Emmanuel Bach",          "Carl Philipp Emanuel Bach"),
    ("Carl Philip Emanuel Bach",            "Carl Philipp Emanuel Bach"),
    ("Hendrick Andriessen",                 "Hendrik Andriessen"),
    ("Vesselin Stoyanov",                   "Veselin Stoyanov"),
    ("Pentcho Stoyanov",                    "Pencho Stoyanov"),
    ("R.Murray Schafer",                    "R. Murray Schafer"),
    ("Raymond Murray Schafer",              "R. Murray Schafer"),
    # One "Christmas Medley" recording (Quilico/Quilico, Toronto Children's
    # Chorus) credited 4 ways — Mel Tormé alone vs the full Tormé/Berlin/Martin
    # medley attribution. Fold to the lead-composer form; the full credit is
    # preserved in composer_line. (Work-side title variants folded below.)
    ("Mel Tormé,Irving Berlin",             "Mel Tormé"),
    ("Mel Torme, Irving Berlin",            "Mel Tormé"),
    ("Mel Torme,Irving Berlin,Hugh Martin", "Mel Tormé"),
    # Franz Xaver Richter (1709-1789, Mannheim school) credited under his Czech
    # forename on 2 pre-2012 airings; the BBC source mojibake'd František ->
    # "Franti?ek" (literal '?', 0x3f — survives canonical_key, so the variant
    # MUST carry the '?', not the diacritic). Segment-confirmed canonical name
    # (MBID daef735c-50ba-462e-9b06-7a120f13492f). Distinct from Max Richter.
    ("Franti?ek Richter",                   "Franz Xaver Richter"),
    # Same-person gaps surfaced by the work-alias cross-composer audit (pairs
    # that looked like a shared title were really one composer split by a typo
    # or attribution noise). Typos / forename variants:
    ("Felix Mendelssohn Batholdy",          "Felix Mendelssohn"),   # 'Batholdy' drops the r
    ("Serge Rachmaninov",                   "Sergey Rachmaninov"),
    # Parse artifact on one m0001jzx Vocalise track (a stray 'Unknown' prefix).
    ("Unknown Sergey Rachmaninov",           "Sergey Rachmaninov"),
    # Truncated-mojibake bare surname, 2 tracks (b01rr6rr Pavane Op.50,
    # b01qqs1c Nocturne Op.33/2 — both unambiguously Gabriel's works).
    ("FaurÃ",                               "Gabriel Fauré"),
    # Lyricist noise appended to the composer credit on one 4-song recital
    # recording (b01n11dh/b01pygr3) — the music is all Fauré's.
    ("Gabriel Faure, Paul de Choudens, Paul Verlaine & Charles Leconte de Lisle", "Gabriel Fauré"),
    # Surname-first segment credit (3 airings).
    ("Scriabin, Alexander",                 "Alexander Scriabin"),
    # Liszt sweep (2026-07-06). Bare surname: single in-corpus bearer, all 10
    # tracks audited genuine (b00nyg1q late-piano recital, Mazeppa, Tasso).
    ("Liszt",                               "Franz Liszt"),
    # Parser-mangled dual transcription credits ('Wagner, Richard; Liszt,
    # Franz' etc.) — the works' sibling airings live under the SONG/OPERA
    # composer (Widmung precedent), matching each credit's segment twins.
    ("Richard; Liszt, Franz Wagner",        "Richard Wagner"),
    ("Giuseppe; Liszt, Franz Verdi",        "Giuseppe Verdi"),
    ("Franz Schubert, Franz Liszt",         "Franz Schubert"),
    ("Frans transc. Liszt, Franz Schubert", "Franz Schubert"),
    ("Franz; transcr Liszt, Franz Schubert", "Franz Schubert"),
    ("Bürger, Gottlieb August Schubert/Liszt", "Franz Schubert"),
    ("Schubert / Liszt, Bürger, Gottlieb August", "Franz Schubert"),
    # The POET of Der Geistertanz credited as composer on 3 segment airings
    # of the Schubert partsongs D.494/D.598 — his only corpus credits.
    ("Gottfried August Bürger",             "Franz Schubert"),
    # Löse Himmel S.494 (Liszt's transcription of a Lassen song): the 37
    # sibling airings live under Franz Liszt, so the dual credit follows.
    ("Franz Liszt, Eduard Lassen",          "Franz Liszt"),
    # Segment-era '&' dual credits — same home-composer rule.
    ("Robert Schumann & Franz Liszt",       "Robert Schumann"),
    ("Franz Schubert & Franz Liszt",        "Franz Schubert"),
    ("Franz Liszt & Nicolo Paganini",       "Franz Liszt"),   # La campanella
    ("Johann Sebastian Bach & Franz Liszt", "Johann Sebastian Bach"),
    # Performer-as-composer artifacts: the ORCHESTRA credited on 3 airings of
    # the Mendelssohn string symphony No 12, and the PIANIST on 4 airings of
    # the Liszt concertos (his only corpus credits — revisit if a genuine
    # Neuburger composition ever airs).
    ("Franz Liszt Chamber Orchestra",       "Felix Mendelssohn"),
    ("Jean-Frédéric Neuburger",             "Franz Liszt"),
    ("Juriaan Andriessen",                  "Jurriaan Andriessen"), # 'Juriaan' drops an r (display pref below)
    ("Frenando Lopes-Graça",                "Fernando Lopes-Graça"),# transposed 'Frenando'
    ("Edward R.White",                      "Edward R. White"),     # missing space splits the key
    # Arranger/librettist noise leaking into the composer field (the work is the
    # named composer's; the arranger/poet belongs in performers, not here):
    ("Zoltán arranger unconfirmed Kodály",  "Zoltán Kodály"),
    ("Kodály, Zoltán arr. unknown",         "Zoltán Kodály"),
    ("Lutosławski, Witold arr. Piatagorsky","Witold Lutosławski"),
    ("Johannes Brahms, Goethe, Johann Wolfgang von", "Johannes Brahms"),  # Goethe = librettist
    # "Attributed Mozart" is kept DISTINCT from plain Mozart (the attribution
    # hedge is real — the Matteis Sr/Jr precedent); only its spelling churn folds:
    ("attrib. Mozart, Wolfgang Amadeus",    "Attributed Mozart, Wolfgang Amadeus"),
    ("Attrib. Mozart, Wolfgang Amadeus",    "Attributed Mozart, Wolfgang Amadeus"),
    ("Attrib Mozart, Wolfgang Amadeus",     "Attributed Mozart, Wolfgang Amadeus"),

    # --- Surfaced by `ttn_curate composer-duplicates` (2026-07-02 backlog
    # sweep): 46 date-corroborated/verified same-person splits — typos,
    # transliterations, and BBC '?'-for-diacritic mojibake that defeats the
    # ascii fold. All pre-2017 spellings; the recording-era data is clean.
    # Rejected as DISTINCT the same day (decisions ledger): Gang Chen (b.1935,
    # Butterfly Lovers) vs Qigang Chen (b.1951), plus two parse-artifact
    # non-person strings.
    ("Antonin Reicha",                  "Antoine Reicha"),
    ("Krassimir Kyurkchiiski",          "Krasimir Kyurkchiyski"),
    ("Ferrucio Busoni",                 "Ferruccio Busoni"),
    ("Johanns Brahms",                  "Johannes Brahms"),
    ("Antiochos Evanghelatos",          "Antiochus Evanghelatos"),
    ("Pablo Sarasate",                  "Pablo de Sarasate"),
    ("Girolami Frescobaldi",            "Girolamo Frescobaldi"),
    ("Luka Sorkochevich",               "Luka Sorkocevic"),
    ("Aleksandar Tekeliev",             "Alexander Tekeliev"),
    ("Giaochino Rossini",               "Gioachino Rossini"),
    ("Piotr Il'yich Tchaikovsky",       "Peter Ilyich Tchaikovsky"),
    ("Johann Jacob Froberger",          "Johann Jakob Froberger"),
    ("Johann Jaokob Froberger",         "Johann Jakob Froberger"),
    ("Franti?ek Jiránek",               "Frantisek Jiranek"),
    ("Emīls Dārziņ?",                   "Emils Darzins"),
    ("Johan Nepomuk Hummel",            "Johann Nepomuk Hummel"),
    ("Carl Friederich Abel",            "Carl Friedrich Abel"),
    ("Cornelis de Wolf",                "Cornelius de Wolf"),
    # Forster/Hofmann fold TOWARD the correct spelling (Greene pattern): the
    # majority is the error, pinned via _COMPOSER_DISPLAY_PREFERENCES below.
    ("Kaspar Forster",                  "Kaspar Foerster"),
    ("Josip Stolcer Slavenski",         "Josip Stolcer-Slavenski"),
    ("Nikolaos Mantzaros",              "Nicolaos Mantzaros"),
    ("Sigismondo d' India",             "Sigismondo d'India"),
    ("Janis Mednis",                    "Janis Medins"),
    ("Johann Kasper Kerll",             "Johann Caspar Kerll"),
    ("Johann Pisendel",                 "Johann Georg Pisendel"),
    ("Johann Gottfried Muethel",        "Johann Gottfried Muthel"),
    ("Sergey Rakhmaninov",              "Sergey Rachmaninov"),
    ("Graznya Bacewicz",                "Grazyna Bacewicz"),
    ("Frano Matu?ic",                   "Frano Matusic"),
    ("Frederick Hollander",             "Friedrich Holländer"),
    ("Jules Auguste Demersseman",       "Jules August Demersseman"),
    ("Mikhail Ivanovic Glinka",         "Mikhail Glinka"),
    ("Baldassarre Galuppi",             "Baldassare Galuppi"),
    ("Leopold Hoffmann",                "Leopold Hofmann"),
    ("Daniël Ruynemann",                "Daniël Ruyneman"),
    ("Richard Wager",                   "Richard Wagner"),
    ("Antonín Franti?ek Rosetti",       "Antonin Frantisek Rosetti"),
    ("Igancy Feliks Dobrzynski",        "Ignacy Feliks Dobrzynski"),
    ("Carl Ludvig Lithander",           "Carl Ludwig Lithander"),
    ("Orlando de Lassus",               "Orlande de Lassus"),
    ("Uro? Krek",                       "Uros Krek"),
    ("Uro Krek",                        "Uros Krek"),
    ("Anthoine Busnois",                "Antoine Busnois"),
    ("Carlo Gesualdo di Venosa",        "Carlo Gesualdo da Venosa"),
    ("Dmitri Cantemir",                 "Dimitrie Cantemir"),
    ("Gion-Duno Simeon",                "Gion Duno Simeon"),
    ("Johan Adam Reincken",             "Johan Adamszoon Reincken"),

    # --- The min>=2 tier of the same sweep (2026-07-02, second pass): typos,
    # mojibake ('?'/'�'-for-diacritic, double-encoded UTF-8), particle/
    # hyphen variants, and full-vs-short name forms — all date-corroborated or
    # verified same-person. 'Joseph Attrib. Haydn' was REJECTED to the ledger
    # instead (attribution hedges stay distinct — the Attributed-Mozart rule).
    ("Joseph Hector Fiocco",            "Joseph-Hector Fiocco"),
    ("Jean Baptiste Lully",             "Jean-Baptiste Lully"),
    ("Mily Alekseyevich Balakirev",     "Mily Alexeyevich Balakirev"),
    ("Bohuslav Martin?",                "Bohuslav Martinu"),
    ("Christian G Neefe",               "Christian Neefe"),
    ("Christoff Ernst Friedrich Weyse", "Christoph Ernst Friedrich Weyse"),
    ("Frederyk Chopin",                 "Fryderyk Chopin"),
    ("Igor Stravinksy",                 "Igor Stravinsky"),
    ("Oscar Lindberg",                  "Oskar Lindberg"),
    ("Ionel Perlea",                    "Jonel Perlea"),
    ("Bedrich A. Wiedermann",           "Bedrich Anton Wiedermann"),
    ("Bla? Arnič",                      "Blaz Arnic"),
    ("Dimitri Shostakovitch",           "Dmitry Shostakovich"),
    ("Artur Kaap",                      "Artur Kapp"),
    ("Primo? Ramov?",                   "Primoz Ramovs"),
    ("Johan Adamszoon Reinken",         "Johan Adamszoon Reincken"),
    ("Guillaume de Mauchaut",           "Guillaume de Machaut"),
    ("Nicolas de Grigny",               "Nicholas de Grigny"),
    ("François Poulenc",                "Francis Poulenc"),
    ("Oscar Straus",                    "Oscar Strauss"),  # NB Straus (one s) is his real spelling; display still majority
    ("Ivan Spasov",                     "Ivan Spassov"),
    ("Eustache de Caurroy",             "Eustache du Caurroy"),
    ("Heitor Villa Lobos",              "Heitor Villa-Lobos"),
    ("?tefan Németh-?amorinsky",        "Stefan Németh-Amorinsky"),
    ("Johann Neopumuk Hummel",          "Johann Nepomuk Hummel"),
    ("Alfred Kalniņ?",                  "Alfred Kalnins"),
    ("Gabriel Faur�",                   "Gabriel Fauré"),
    ("Leo? Janáček",                    "Leos Janacek"),
    ("Johann I Strauss",                "Johann Strauss I"),
    ("Xavier Mercadante",               "Saverio Mercadante"),
    ("Giambattista Martini",            "Giovanni Battista Martini"),
    ("Aleksandar Tanev",                "Alexander Tanev"),
    ("FranÃ§ois BoÃ¯eldieu",            "Francois-Adrien Boieldieu"),
    ("César Auguste Franck",            "Cesar Franck"),
    ("Antonio Soler y Ramos",           "Antonio Soler"),
    ("Gustav Adolf Merkel",             "Gustav Merkel"),
    ("Johann August Soderman",          "August Söderman"),
    ("Peter Ilyich Tchaikovsky Tchaikovsky", "Peter Ilyich Tchaikovsky"),
    ("Carlus A Fodor",                  "Carolus Antonius Fodor"),
    ("Alexandr Tikhonovich Gretchaninov", "Alexander Gretchaninov"),
    ("Sulkhan Tsintsadze",              "Sulkhan Fyodorovich Tsintsadze"),
    # the Kunileid cluster: fold all variants to the space-form target so
    # nothing chains (Kunileid = Aleksander Saebelmann's pen name)
    ("Aleksander Kunileid",             "Aleksander Saebelmann Kunileid"),
    ("Aleksander Saebelmann- Kunileid", "Aleksander Saebelmann Kunileid"),
    ("Aleksander Saebelmann-Kunileid",  "Aleksander Saebelmann Kunileid"),
    # Forster family completion (1x mojibake; rides the display-pref reversal)
    ("Kaspar F�rster",                  "Kaspar Foerster"),

    # --- The min=1 singleton tail of the same sweep (2026-07-02, third pass):
    # one-airing typo/mojibake/HTML-entity variants against established
    # identities, each date-corroborated. Verified-with-data traps: the two
    # 'Taneyev' 1x credits carry (1928-1996) = the Bulgarian TANEV misspelled
    # (Sergey Taneyev 1856-1915 is untouched); both corpus Bernhard Schmids
    # are the YOUNGER (1567-1627); every corpus Loeillet is de Gant (no London
    # Loeillet), so the bare form is single-bearer. 'Johannes Cornago/Ockeghem'
    # is a dual-credit string — REJECTED to the ledger, not folded.
    ("Giovanni Domenico de Giovane Da Nola", "Giovanni Domenico del Giovane Da Nola"),
    ("Antoly Konstantinovich Lyadov",   "Anatol Lyadov"),
    ("Ignacy Feliks Dobrznski",         "Ignacy Feliks Dobrzynski"),
    ("Thibault IV de Navarrre",         "Thibault IV de Navarre"),  # fold the triple-r typo, not into it
    ("Johann Joachim Quanz",            "Johann Joachim Quantz"),
    ("Illdebrando Pizzetti",            "Ildebrando Pizzetti"),
    ("Emmerich Imre Klman",             "Emmerich Imre Kalman"),
    ("Guilaume Connesson",              "Guillaume Connesson"),
    ("Witold Lutoslawskii",             "Witold Lutoslawski"),
    ("François Dagincourt",             "Francois Dagincour"),
    ("Jaques Offenbach",                "Jacques Offenbach"),
    ("Johanes Brahms",                  "Johannes Brahms"),
    ("Claude Joseph Rouget de Lisle",   "Claude-Joseph Rouget de Lisle"),
    ("Daniel-Francois Esprit Auber",    "Daniel Auber"),
    ("Claude Dbussy",                   "Claude Debussy"),
    ("Johan Svedsen",                   "Johan Svendsen"),
    ("Johannes Bernard van Bree",       "Johannes Bernardus van Bree"),
    ("Edgar Varèse",                    "Edgard Varese"),
    ("Peter Il'ych Tchaikovsky",        "Peter Ilyich Tchaikovsky"),
    ("Piotr Ilyitch Tchaikovsky",       "Peter Ilyich Tchaikovsky"),
    ("Johann Gottfried M�thel",         "Johann Gottfried Muthel"),
    ("Juan Cristosomo Arriaga",         "Juan Crisostomo Arriaga"),
    ("Ambro Copi",                      "Ambroz Copi"),
    ("Ambro? Copi",                     "Ambroz Copi"),
    ("Vllem Kapp",                      "Villem Kapp"),
    ("Sven-David Landström",            "Sven-David Sandström"),
    ("Karol Jósef Lipinski",            "Karol Józef Lipinski"),
    ("Sigismund Thalberg",              "Sigismond Thalberg"),
    ("Elias Brunnemuller",              "Elias Brönnemüller"),
    ("Elias Bronemuler",                "Elias Brönnemüller"),
    ("John Adolf Hasse",                "Johann Adolf Hasse"),
    ("Johann Adolph Hasse",             "Johann Adolf Hasse"),
    ("Cornelius Doppler",               "Cornelis Dopper"),
    ("Alexander Taneyev",               "Alexander Tanev"),
    ("Aleksandar Taneyev",              "Alexander Tanev"),
    ("J.M.K. Poniatowski",              "J. M. K. Poniatowski"),
    ("JÃ\x83Â³zef Kazimierz Hofmann",   "Józef Kazimierz Hofmann"),
    ("August S�derman",                 "August Söderman"),
    ("Andres Szollosy",                 "Andras Szollosy"),
    ("Antonín Dvo?ák",                  "Antonin Dvorak"),
    ("AntonÃ\x83n DvorÃ\x83Â¡k",        "Antonin Dvorak"),
    ("JoaquÃn Turina",                  "Joaquin Turina"),
    ("Adam Jarz?bski",                  "Adam Jarzebski"),
    ("Leevi Madeloja",                  "Leevi Madetoja"),
    ("Gabriel Piern�",                  "Gabriel Pierne"),
    ("T?ru Takemitsu",                  "Toru Takemitsu"),
    ("Branimir Saka?",                  "Branimir Sakac"),
    ("Johannes Eccard",                 "Johann Eccard"),
    ("Petko Staynov",                   "Petko Stainov"),
    ("Isaac Alb�niz",                   "Isaac Albeniz"),
    ("Leos Jan�cek",                    "Leos Janacek"),
    ("Eugen Sucho?",                    "Eugen Suchon"),
    ("Janis Mendis",                    "Janis Medins"),
    ("Michal Vilek",                    "Michal Vilec"),
    ("Samo Vrem?ak",                    "Samo Vremsak"),
    ("Jaime Ovalle",                    "Jayme Ovalle"),
    ("Tykhon Nikolayevich Khrenykov",   "Tikhon Nikolayevich Khrennikov"),
    ("Bela Bartak",                     "Bela Bartok"),
    ("Alexander Archangelski",          "Alexander Arkhangelsky"),
    ("Bernhard II Schmid",              "Bernhard Schmid"),
    ("Mikolaj Jr Gorecki",              "Mikolaj Junior Górecki"),
    ("Juan Manen",                      "Joan Manen"),
    ("Alfreds Kalnics",                 "Alfred Kalnins"),
    ("Franchinus Gaffurius",            "Franchino Gafurius"),
    ("Jan Antonin Reichenauer",         "Johann Anton Reichenauer"),
    ("Dag Wir�n",                       "Dag Wiren"),
    ("Jan Václav Vorísek",              "Jan Vaclav Hugo Vorisek"),
    ("Stefan Nrmeth-Samorinsky",        "Stefan Németh-Amorinsky"),
    ("Hermann D.Koppel",                "Hermann David Koppel"),  # fold the cramped form, not into it
    ("Uro? Prevor?ek",                  "Uros Prevorsek"),
    # the Grétry split: the 1x 'André-Modeste' bridged the standing 8x
    # 'Andre-Ernest-Modeste' vs 23x-identity 'Andre Gretry' split — one person
    ("André-Modeste Gretry",            "Andre Gretry"),
    ("Andre-Ernest-Modeste Gretry",     "Andre Gretry"),
    # the Loeillet forms, incl. the two quoted variants the finder missed
    ("Jean Baptiste Loeillet de Gant",  "Jean Baptiste Loeillet"),
    ("Loeillet, Jean Baptiste \"Loeillet de Gant\"", "Jean Baptiste Loeillet"),
    ("Loeillet, Jean Baptiste 'Loeillet de Gant'",   "Jean Baptiste Loeillet"),
    ("Unico Van Wassenaer",             "Unico Wilhelm van Wassenaer"),
    ("Carlo Alfredo Piatti",            "Alfredo Piatti"),
    ("William Harris",                  "William Henry Harris"),
    ("Melanie Bonis",                   "Mel Bonis"),
    ("Joseph Gabriel Rheinberger",      "Joseph Rheinberger"),
    ("Francois Boildieu",               "Francois-Adrien Boieldieu"),
    ("Gustaf Lazarus Nordqvist",        "Gustaf Nordqvist"),
    ("Stanis&#322;aw Moniuszko",        "Stanislaw Moniuszko"),
    ("Felix Bartholdy Mendelssohn",     "Felix Mendelssohn"),
    ("Hugo Alfvï¿½n",                   "Hugo Alfvén"),
    ("Em?ls D?rzi?š",                   "Emils Darzins"),
    ("Alexander Arutiunian",            "Aleksandr Grigori Arutiunian"),
    ("Jiri Antonin Benda",              "Georg Anton Benda"),
    # 'Nicola Matteis I' = the Elder unambiguously (a two-credit 'Nicola
    # Matteis I, Lea Sobbe' arrangement credit whose arranger tail is
    # stripped at grouping). Folded to bare 'Nicola Matteis' 2026-07-09: the
    # bare group is MBID-anchored to the Elder under recording projection
    # (the Jr. airings project to 'Nicola Matteis, Jr'), so bare no longer
    # conflates the two men the way it did when the Sr./bare fold was
    # rejected in the dup ledger. Suffixed-ONLY forms fold; bare stays bare.
    ("Nicola Matteis I",                "Nicola Matteis"),
]


# Composer display preferences — the exact spelling to show for a composer
# group, overriding the default "most common original spelling wins" rule.
# For the rare case where the corpus-majority spelling is a known error: the
# BBC's misspelling "Ion Dimitrescu" (19 airings) outnumbers the correct "Ion
# Dumitrescu" (14), so the default would display the wrong name for an
# otherwise-correctly-merged group. Each entry must be a FINAL canonical (a
# right-hand alias target or an un-aliased name), never a left-hand variant,
# so its key matches the resolved group key — enforced by
# test_composer_display_overrides_are_final.
_COMPOSER_DISPLAY_PREFERENCES = [
    "Ion Dumitrescu",        # corpus majority is the misspelling "Ion Dimitrescu"
    "Gediminas Gelgotas",    # corpus majority is the truncation "Gedimas Gelgotas"
    "Maurice Greene",        # majority "Maurice Green" drops the final e
    "Jacques Bouffil",       # majority "Jacques Boufil" drops an f
    "Stefan Bolesław Poradowski",  # majority "Stefan Boleslaw Prodowski" is garbled
    "Samuel de Lange Sr",    # majority "Samuel de sr Lange" mis-places the Sr
    "François Dufaut",       # restore the cedilla over the ASCII majority "Francois"
    "Gaspar Fernandes",      # standard spelling over the majority variant "Gasper"
    "Heinrich Schütz",       # ASCII majority "Heinrich Schutz" (148) outvotes the umlaut (98)
    "Jurriaan Andriessen",   # majority is the typo "Juriaan" (16) over the correct "Jurriaan" (3)
    # (anchor, label): a synthetic display label, not a spelling of the group.
    # Casals went by his Catalan "Pau"; "Pablo" (the Castilian form) still
    # dominates English usage — show both so neither reader is lost.
    ("Pablo Casals", "Pau (Pablo) Casals"),
    # The corpus-dominant spelling is a degraded ASCII rendering; restore the
    # proper hyphenated compound forename and the diacritics (ç, ë).
    ("Alexandre Pierre Francois Boely", "Alexandre-Pierre-François Boëly"),
    # Grove/MGG spell the umlaut; the corpus only has the e-dropping majority
    # "Forster" (217) and the oe transliteration, so the label is synthetic.
    # (Josef Bohuslav Foerster is genuinely 'oe' — leave him alone.)
    ("Kaspar Foerster", "Kaspar Förster"),
    "Leopold Hofmann",       # majority "Leopold Hoffmann" (26); Grove spells Hofmann
]


# Ensemble aliases — same pattern as the composer table, for the bare-vs-city-
# suffixed case the parse_performers city-suffix merger can't fix alone (e.g.
# "WDR Symphony Orchestra" vs "WDR Symphony Orchestra, Cologne"). Direction is
# cosmetic — display picks the most common original spelling regardless.
_ENSEMBLE_ALIAS_PAIRS = [
    # --- Cross-lingual ensemble names (target = the MBID-bearing canonical;
    #     resolve_identity normalizes the variant to it BEFORE the name->MBID
    #     backfill, so both era's spellings land on the one MusicBrainz identity) ---
    ("Ljubljana String Quartet",                     "Ljubljanski godalni kvartet"),  # 81ae03c3; bridges the pre-2012 Wolf Italian Serenade
    ("Ljubljanski String Quartet",                   "Ljubljanski godalni kvartet"),  # mixed-language variant
    ("Yggdrasil String Quartet",                     "Yggdrasil Quartet"),            # f1dccfa3; 'String' dropped, distinctive name (mined)
    ("Consort of Musicke",                           "The Consort of Musicke"),       # b0eb409d; 'The' prefix (mined)
    # --- Bare ↔ city-suffixed forms of the same orchestra/chorus ---
    ("WDR Symphony Orchestra",                       "WDR Symphony Orchestra, Cologne"),          #  32 → 223
    ("WDR Radio Orchestra",                          "WDR Radio Orchestra, Cologne"),             #  84 →  91
    ("WDR Radio Chorus",                             "WDR Radio Chorus, Cologne"),                #   4 →  11
    ("RIAS Chamber Chorus",                          "RIAS Chamber Chorus, Berlin"),              #   4 → 115
    ("Hungarian Radio Symphony Orchestra, Budapest", "Hungarian Radio Symphony Orchestra"),       #  91 ← 208
    ("Hungarian Radio Chorus, Budapest",             "Hungarian Radio Chorus"),                   #  48 ↔  44
    ("Camerata Silesia, Katowice",                   "Camerata Silesia"),                         #   8 ←  83
    ("Polish Radio Orchestra, Warsaw",               "Polish Radio Orchestra"),                   #  35 ↔  35
    # NOSPR (Katowice): canonical is the MBID-bearing bare form (af262d86), so the
    # name normalizes to it BEFORE the MBID backfill and all spellings unify on the
    # MBID. (Was inverted — the city-suffixed canonical carried no MBID, so the bare
    # form went to its MBID and the suffixed form to a name-key, a silent split.)
    ("Polish National Radio Symphony Orchestra, Katowice", "Polish National Radio Symphony Orchestra"),
    ("National Polish Radio Symphony Orchestra",     "Polish National Radio Symphony Orchestra"),

    # --- No-comma city suffix (the merger handles only the comma form) ---
    ("Slovak Radio Symphony Orchestra Bratislava",   "Slovak Radio Symphony Orchestra"),          #  90 → 567

    # --- Website ensembles-table consolidation pass (2026-07-16): the name-keyed
    #     variants >= the browse-table's airings cut, each verified against an
    #     in-corpus sibling (word-order/city/translation variants; the Hungarian
    #     and Cologne folds conductor-overlap-verified: Vásáry/Lehel/Medveczky
    #     shared, and 100% Peter Neumann on both Cologne sides) ---
    ("Bratislava Slovak Radio Symphony Orchestra",   "Slovak Radio Symphony Orchestra"),          # 204 → 567; leading-city variant
    ("Polish Radio National Symphony Orchestra Katowice", "Polish National Radio Symphony Orchestra"),  # 108; NOSPR word-order+city variant
    ("Choir of Latvian Radio",                       "Latvian Radio Choir"),                      # 162 → 119; word order
    ("Hungarian Radio Orchestra",                    "Hungarian Radio Symphony Orchestra"),       # 201 → 557; bare form of the one MR orchestra
    ("Croatian Radio and Television Symphony Orchestra", "Croatian Radio-Television Symphony Orchestra"),  #  72 → 358; 'and'/hyphen
    ("Croatian Radio and Television Chorus",         "Croatian Radio-Television Chorus"),         #  37 ↔  43; 'and'/hyphen
    ("Cologne Chamber Chorus",                       "Kölner Kammerchor"),                        #  72 →  27; English name (Neumann's choir)

    # --- German ↔ English name of one orchestra (SR, Saarbrücken) ---
    ("Rundfunk-Sinfonieorchester Saarbrücken",       "Saarbrücken Radio Symphony Orchestra"),     #  19 →  96

    # --- Deutsche Radio Philharmonie Saarbrücken Kaiserslautern: the post-2007
    #     merger successor, credited under German and English names (and
    #     truncations). Kept DISTINCT from its pre-merger predecessor, the
    #     Saarbrücken Radio Symphony Orchestra above. Canonical is the MBID-bearing
    #     English form (afe4c2d5) so every spelling unifies on the MBID — was
    #     inverted (the German full-name canonical carried no MBID). NB display now
    #     follows the MBID's name (English) rather than the German full name.
    ("German Radio Philharmonic Orchestra, Saarbrücken Kaiserslautern",
     "German Radio Philharmonic Orchestra"),
    ("German Radio Saarbrücken-Kaiserslautern Philharmonic Orchestra",
     "German Radio Philharmonic Orchestra"),
    ("Deutsche Radio Philharmonie Saarbrücken Kaiserslautern",
     "German Radio Philharmonic Orchestra"),
    ("German Radio Philharmonic",
     "German Radio Philharmonic Orchestra"),
    ("Deutsche Radio Philharmonie",
     "German Radio Philharmonic Orchestra"),

    # --- Translation artefact: a stray Swedish genitive -s ---
    # "Erik Westbergs Vokalensemble" anglicised two ways — one rendering
    # keeps the Swedish genitive ("Westbergs"), the other drops it.
    ("Erik Westbergs Vocal Ensemble",                "Erik Westberg Vocal Ensemble"),             #  21 →  28
]


# Each pair is (a real BBC title-variant, the preferred real title). Both
# sides are run through work_title_key, so only the *words* matter here.
_WORK_ALIAS_PAIRS = [
    # --- Beethoven: Op 131 quartet — "Quartet for strings" rephrasing ---
    ("Quartet for strings (Op 131) in C sharp minor",
     "String Quartet No 14 in C sharp minor, Op 131"),  # Ludwig van Beethoven

    # --- Verdi: La Forza del Destino — overture ↔ bare opera name ---
    ("La Forza del Destino",                          "Overture to La Forza del destino"),  # Giuseppe Verdi
    ("La forza del destino (Overture)",               "Overture to La Forza del destino"),  # Giuseppe Verdi
    ("Overture from La Forza del Destino",            "Overture to La Forza del destino"),  # Giuseppe Verdi

    # --- Mussorgsky: Pictures at/from an Exhibition (+ arrangement tags) ---
    ("Pictures from an Exhibition",                   "Pictures at an Exhibition"),  # Modest Mussorgsky
    ("Pictures from an exhibition for piano",         "Pictures at an Exhibition"),  # Modest Mussorgsky

    # --- Mussorgsky: Night on the Bare Mountain (Bald Mountain, ed. R-K) ---
    ("A Night on the bare mountain, ed. Rimsky-Korsakov", "Night on a Bare Mountain"),  # Modest Mussorgsky
    ("A Night on the Bare Mountain",                  "Night on a Bare Mountain"),  # Modest Mussorgsky
    ("A Night on Bare Mountain, symphonic poem",      "Night on a Bare Mountain"),  # Modest Mussorgsky
    ("St John's Night on the Bare Mountain",          "Night on a Bare Mountain"),  # Modest Mussorgsky
    ("Night on Bald Mountain",                        "Night on a Bare Mountain"),  # Modest Mussorgsky

    # --- Glinka: Ruslan and Lyudmila — overture (i ↔ and, to ↔ from) ---
    ("Overture to 'Ruslan and Lyudmila'",             "Ruslan i Lyudmila (overture)"),  # Mikhail Ivanovich Glinka
    ("Overture from Ruslan i Lyudmila",               "Ruslan i Lyudmila (overture)"),  # Mikhail Ivanovich Glinka
    ("Overture - from Ruslan & Lyudmila",             "Ruslan i Lyudmila (overture)"),  # Mikhail Ivanovich Glinka
    ("Ruslan and Lyudmila Overture",                  "Ruslan i Lyudmila (overture)"),  # Mikhail Ivanovich Glinka
    ("Overture to the opera 'Ruslan i Lyudmila'",     "Ruslan i Lyudmila (overture)"),  # Mikhail Ivanovich Glinka

    # --- Mendelssohn: The Hebrides / Fingal's Cave overture, Op 26 ---
    ("The Hebrides (Fingal's Cave) - overture, Op 26", "The Hebrides, Op 26"),  # Felix Mendelssohn
    ("The Hebrides (Fingal's Cave)",                  "The Hebrides, Op 26"),  # Felix Mendelssohn
    ("The Hebrides, Op 26 (Fingal's Cave)",           "The Hebrides, Op 26"),  # Felix Mendelssohn
    ("The Hebrides (Fingal's Cave) overture",         "The Hebrides, Op 26"),  # Felix Mendelssohn
    ("Hebrides overture, Op 26",                      "The Hebrides, Op 26"),  # Felix Mendelssohn
    ("The Hebrides Overture, Op 26",                  "The Hebrides, Op 26"),  # Felix Mendelssohn
    ("Hebrides",                                      "The Hebrides, Op 26"),  # Felix Mendelssohn
    ("The Hebrides",                                  "The Hebrides, Op 26"),  # Felix Mendelssohn

    # --- Nicolai / Schumann: overture word-order the token sort can't reach ---
    ("Overture to \"The Merry Wives of Windsor\"",    "Overture, The Merry Wives of Windsor"),  # Otto Nicolai
    ("Overture Genoveva Op 81",                       "Overture to Genoveva, Op 81"),  # Robert Schumann

    # (Ravel "Daphnis et Chloé, Suite No 2" needs no alias — the et->and
    #  conjunction fold in work_title_key folds it onto "Daphnis & Chloé".)

    # --- Brahms: Hungarian Dances 17-21, Oslo PO / Aadland — one recording
    #     the BBC airs as a filler, titled with the dances spelled out
    #     vs. given as a range, with or without the "orch. Dvorak" tag.
    #     (The range forms — with and without "orch. Dvorak" — already share
    #     a token-sorted key once "Nos" canonicalises cleanly.)
    ("5 Hungarian Dances (originally for piano duet): Nos. 17 in F sharp minor; "
     "18 in D major; 19 in B minor; 20 in E minor; 21 in E minor",
     "5 Hungarian dances (nos.17-21) orch. Dvorak (orig. pf duet)"),  # Johannes Brahms
    ("5 Hungarian Dances: Nos. 17 in F sharp minor; 18 in D major; "
     "19 in B minor; 20 in E minor; 21 in E minor",
     "5 Hungarian dances (nos.17-21) orch. Dvorak (orig. pf duet)"),  # Johannes Brahms
    ("5 Hungarian dances (nos.17-21) (orig. pf duet)",
     "5 Hungarian dances (nos.17-21) orch. Dvorak (orig. pf duet)"),  # Johannes Brahms

    # --- Liszt: Au lac de Wallenstadt — book named as roman "I" vs. spelled
    #     "première année: Suisse" (S.160 is a 9-piece container, so the
    #     catalogue rule rightly leaves this to the alias table) ---
    ("Au lac de Wallenstadt, from 'Années de pèlerinage: première année: "
     "Suisse S.160'",
     "Au Lac de Wallenstadt from Années de pèlerinage I, S.160"),  # Franz Liszt

    # --- Schubert: one-off re-airings surfaced by the --once + exact-
    #     performer audit. Each is a single recording the BBC aired twice
    #     under different titles. The catalogued ones are songs/dances, so
    #     work_title_key's form-word gate (rightly) leaves them to this
    #     table rather than the catalogue rule.
    ("Le Roi des aulnes for violin solo Op 26",
     "Le Roi des aulnes Op 26"),  # Heinrich Wilhelm Ernst
    ("An Mignon from 3 Songs, D.161",
     "An Mignon (D.161), Op.19 No.2 (To Mignon)"),  # Franz Schubert
    ("Sehnsucht (D.636 Op.39)",
     "Sehnsucht, D.636"),  # Franz Schubert
    ("Nine songs with orchestra (Romanze (no. 3b), from Rosamunde, D. 797; "
     "Die Forelle, D. 550 orch. Benjamin Britten; Gretchen am Spinnrade, "
     "D. 118 orch. Max Reger); Du bist die Ruh’, D. 776 orch. Anton Webern; "
     "An Silvia, D. 891 orch. Robert Schollum; Nacht und Träume, D. 827 "
     "orch. Max Reger; Im Abendrot, D. 799 orch. Max Reger; Erlkönig, "
     "D.328 orch. Max Reger; An die Musik, D.547 orch. Max Reger.",
     "Nine songs with orchestra [Romanze from Rosamunde, D. 797; "
     "Die Forelle, D. 550 orch. Benjamin Britten; Gretchen am Spinnrade, "
     "D. 118 orch. Max Reger; Du bist die Ruh’, D. 776 orch. Anton Webern; "
     "An Silvia, D. 891 orch. Robert Schollum; Nacht und Träume, D. 827 "
     "orch. Max Reger; Im Abendrot, D. 799 orch. Max Reger; Erlkönig, "
     "D.328 orch. Max Reger; An die Musik, D.547 orch. Max Reger]"),  # Franz Schubert

    # --- Non-Bach one-off re-airings surfaced by the --once + exact-
    #     performer audit: recordings the BBC aired more than once under
    #     different titles. Phrasing the token sort and catalogue rule
    #     can't reach (separator churn, added/dropped form words, apostrophe-
    #     as-No notation, translations, arrangement tags).

    # --- Beethoven: 14 re-aired works ---
    ('2 Sonatinas WoO 43/1 and WoO 44/1',
     '2 Mandolin Sonatinas: C minor WoO 43/1 and C major WoO 44/1'),  # Ludwig van Beethoven
    ("8 Variations on Mozart's 'La ci darem la mano' (WoO 28) arranged for oboe and piano 0",
     "8 Variations on Mozart's 'La ci darem la mano' (WoO 28) arranged for oboe and piano"),  # Ludwig van Beethoven
    ('Trio in B flat major Op.11 for clarinet (or violin), cello and piano',
     'Clarinet Trio in B flat major, Op 11'),  # Ludwig van Beethoven
    ('Grosse Fuge, Op 133 (version for orchestra)',
     'Grosse Fuge, Op 133'),  # Ludwig van Beethoven
    ('Incidental music to König Stephan (King Stephen) (overture)',
     'Incidental music to "King Stephen"'),  # Ludwig van Beethoven
    ('Overture: The Creatures of Prometheus',
     'Overture to The Creatures of Prometheus'),  # Ludwig van Beethoven
    ("Sonata quasi una fantasia in C sharp minor Op.27'2 (Moonlight)",
     'Piano Sonata quasi una fantasia in C sharp minor, Op 27 No 2, (Moonlight)'),  # Ludwig van Beethoven
    ('Trio for piano and strings in E flat major Op 1 No 1 (4. Finale (Presto))',
     'Trio for piano and strings in E flat major (Op.1 No.1)'),  # Ludwig van Beethoven

    # --- Mozart: 12 re-aired works ---
    ('12 Variations for piano, K.500',
     '12 Variations for piano in B flat (K.500)'),  # Wolfgang Amadeus Mozart
    ('Four Kontra Tänze, KV 267',
     '4 Kontra Tänze, KV 267'),  # Wolfgang Amadeus Mozart
    ('Rivolgete a lui lo sguardo, K.584',
     "Aria 'Rivolgete a lui lo sguardo' (K.584)"),  # Wolfgang Amadeus Mozart
    ("Aria: Un'aura amorosa - from 'Così fan tutte', K588",
     'Aria: "Un\'aura amorosa" from the opera \'Così fan tutte\' (K.588), Act 1'),  # Wolfgang Amadeus Mozart
    ("Un'aura amorosa (Così fan tutte)",
     'Aria: "Un\'aura amorosa" from the opera \'Così fan tutte\' (K.588), Act 1'),  # Wolfgang Amadeus Mozart
    ('Motet: Ave Verum Corpus (K.618)',
     'Ave verum corpus'),  # shared: Wolfgang Amadeus Mozart / Imant Raminsh
    ('Der Schauspieldirektor, K.486',
     'Der Schauspieldirektor - singspiel in 1 act (K.486)'),  # Wolfgang Amadeus Mozart
    ('Eine kleine Nachtmusik, K525',
     'Eine kleine Nachtmusik (Serenade No.13 in G) (K.525)'),  # Wolfgang Amadeus Mozart
    ("Excerpts from 'The Abduction from the Seraglio, K.384, Harmoniemusik'",
     "Excerpts from 'The Abduction from the Seraglio, K. 384, Harmoniemusik'"),  # Wolfgang Amadeus Mozart
    # La Clemenza di Tito — the bare/overture token forms unify with the
    # K.621 catalogue overture group (2026-05-29 audit). The opera never airs
    # whole in the corpus, so the bare title is taken as the overture.
    ('La Clemenza di Tito (overture)',
     'Overture to La Clemenza di Tito (K.621)'),  # Wolfgang Amadeus Mozart
    ('La Clemenza di Tito',
     'Overture to La Clemenza di Tito (K.621)'),  # Wolfgang Amadeus Mozart
    ('Two Flute Quartets: no 3 in C major K.Anh.171 (K.285b) & no 1 in D major (K.285)',
     'Two Flute Quartets: no 3 in C major K.285b & no 1 in D major, K.285'),  # Wolfgang Amadeus Mozart

    # --- Handel: 10 re-aired works ---
    ('"Al lampo Dell\'armi" - Giulio Cesare\'s aria from Act II of the opera \'Giulio Cesare in Egitto\' (Act II Scene 8)',
     '"Al lampo Dell\'armi" - Giulio Cesare\'s aria from Act II of the opera \'Giulio Cesare in Egitto\''),  # George Frideric Handel
    ("Al lampo dell'armi' (from Act II of Giulio Cesare in Egitto)",
     '"Al lampo Dell\'armi" - Giulio Cesare\'s aria from Act II of the opera \'Giulio Cesare in Egitto\''),  # George Frideric Handel
    ('The Arrival of the Queen of Sheba (Solomon, HWV 67)',
     "'The Arrival of the Queen of Sheba' - from 'Solomon', HWV 67"),  # George Frideric Handel
    ("Tu, del ciel ministro eletto (Bellezza's aria) 'Il Trionfo del Tempo e del Disinganno', HWV 46a",
     "'Tu, del ciel ministro eletto' (Bellezza's aria) from 'Il Trionfo del Tempo e del Disinganno', HWV.46a"),  # George Frideric Handel
    ('Die ihr aus dunkeln Grüften den eiteln Mammon grabt (HWV.208) - No.7 from German Arias',
     "Aria: 'Die ihr aus dunkeln Grüften den eiteln Mammon grabt' (HWV.208)"),  # George Frideric Handel
    # Op 6 No 5 in D — HWV 323. Retargeted from "D, HWV 323" to the
    # Op-numbered plurality canonical so the spaceless-typo, the bare
    # HWV-only forms, and the Op-numbered token-sort group all fuse.
    # See the Concerto Grosso audit (2026-05-28) at the file tail for
    # the matching variants.
    ('Concerto Grosso in Dmajor, HWV 323',
     'Concerto Grosso in D major, Op 6 no 5'),  # George Frideric Handel
    # Lascia la spina (Il Trionfo HWV.46a, 1707) — same melody as the
    # earlier Almira Sarabande (HWV 1, 1705, instrumental) and later
    # "Lascia ch'io pianga" in Rinaldo (HWV 7, 1711, retexted). The TTN
    # plurality (26×) uses the short "Lascia la spina, from Il Trionfo"
    # phrasing. These two aliases were originally targeted at the
    # full-text "cogli la rose" canonical; retargeted to the short
    # plurality so the cogli-la-rose form, the long "Aria 'Lascia la
    # spina'" form, and the Lezhneva Almira-attributed vocal all fuse.
    # See Handel audit (2026-05-28) at the file tail.
    ('Lascia la spina cogli la rose, from Il Trionfo del Tempo e del disinganno, HWV.46a',
     "Lascia la spina, from Il Trionfo del tempo e del disinganno"),  # George Frideric Handel
    ("Lascia la spina, cogli la rosa, from 'Il Trionfo del Tempo e del Disinganno'",
     "Lascia la spina, from Il Trionfo del tempo e del disinganno"),  # George Frideric Handel
    # Op 1 no 5 F major — HWV.363a. Retargeted from the no-HWV oboe form
    # to the catalogue-path canonical so the 2× token-sort sibling fuses
    # with the 19× HWV-bearing group. See Handel audit (2026-05-28) at
    # the file tail.
    ('Sonata in F major Op 1 No 5',
     'Sonata in F major, Op 1 no 5 (HWV.363a) vers. oboe & bc'),  # George Frideric Handel

    # --- Brahms: 3 re-aired works ---
    ('Intermezzo in A minor,Op 116, No 2',
     'Intermezzo in A minor, Op 116, No 2'),  # Johannes Brahms
    # (Superseded by the Brahms audit batch below — both this and bare
    # 'Piano Quintet in F minor' fold to 'Piano Quintet in F minor, Op 34'.
    # Note: bare form is shared with Franck; composer-scoped grouping
    # isolates the relabel.)
    ('Piano Quintet in F minor',
     'Piano Quintet in F minor, Op 34'),  # shared: Cesar Franck / Johannes Brahms
    ("Three Songs: 'Meine Liebe ist grun' Op 63 No 5",
     'Three Songs'),  # Johannes Brahms (re-targeted 2026-07-19: old 'etc' target became an LHS)

    # --- Schumann: 2 re-aired works ---
    ('Die Braut von Messina, Op 100 (Overture)',
     'Die Braut von Messina, Op 100'),  # Robert Schumann
    # Retargeted 2026-05-28 (Schumann batch at file tail) — the
    # intermediate "in G major Op 92" was itself folded onward to the
    # short canonical via my new alias. Skip the chain per
    # [[aliases-do-not-chain]].
    ('Introduction and Allegro appassionato in G major Op 92 for piano and orchestra',
     'Introduction and Allegro appassionato (Op.92)'),  # Robert Schumann

    # --- Bach: 12 re-aired works the systematic vocal rule can't reach —
    #     one airing gives "No.N" with no BWV, or an excerpt locator sends
    #     both sides to the token sort.
    ("'Herr! Warum trittest du'(recitative) and 'Die schaumenden Welle' (aria) from Cantata BWV 81, 'Jesus schlaft, was soll ich hoffen'",
     "'Herr! Warum trittest du' (recitative), 'Die schaumenden Welle' (aria) - from Cantata No. 81, 'Jesus schlaft, was soll ich hoffen'"),  # Johann Sebastian Bach
    ("Cantata no. 81 BWV.81 'Jesus schlaft, was soll ich hoffen': 'Herr! Warum trittest du' (recitative), 'Die schaumenden Welle' (aria)",
     "'Herr! Warum trittest du' (recitative), 'Die schaumenden Welle' (aria) - from Cantata No. 81, 'Jesus schlaft, was soll ich hoffen'"),  # Johann Sebastian Bach
    ('Ich traue seiner Gnaden (from Cantata BWV.97)',
     "Aria 'Ich traue seiner Gnaden' from Cantata no. 97 (BWV.97) 'In allen meinen Taten'"),  # Johann Sebastian Bach
    ('Cantata No.11 (Lobet Gott in seinen Reichen) (Ascension Oratorio)',
     'Cantata BWV.11, Lobet Gott in seinen Reichen (Ascension oratorio)'),  # Johann Sebastian Bach
    ("Duet from Cantata BWV 134, 'Wir danken und preisen'",
     "Cantata BWV.134: 'Wir danken und preisen' (duet)"),  # Johann Sebastian Bach
    ('Cantata No.43 (Gott fahret auf mit Jauchzen)',
     'Cantata BWV.43, Gott fahret auf mit Jauchzen'),  # Johann Sebastian Bach
    ('The Well-Tempered Clavier - Book 2, BWV 874-881',
     'Excerpts from The Well-Tempered Clavier, Vol. 2, BWV 874-881'),  # Johann Sebastian Bach
    ("Fuga ricercata No.2 from Bach's 'Musikalischen Opfer' (BWV.1079)",
     "Fuga ricercata No 2 a 6 voci from Bach's 'Musikalischen Opfer' BWV.1079"),  # Johann Sebastian Bach
    ('Gavotte en rondeau, from Partita no 3 in E major',
     'Gavotte en rondeau (Partita No. 3 in E major for solo violin)'),  # Johann Sebastian Bach
    ('Minuet 1 and 2 in F; Fantasia in d',
     'Minuet 1 and 2 in F major; Fantasia in D minor'),  # Carl Philipp Emanuel Bach
    ('Sonata a 5 No.1 in C major & No.2 in F major, for two violins, two violas and continuo',
     'Sonata No 1 in C major & Sonata No 2 in F major for two violins, two violas and continuo'),  # Heinrich Bach
    ('Wer ist so würdig als du, Wq.222',
     'Wer ist so würdig als du (Wq.222) (Hamburg 1774)'),  # Carl Philipp Emanuel Bach

    # --- Source data errors: one airing carries a wrong opus or key. The
    #     performance is the same; fold the mistaken title into the correct
    #     work. (The raw title stays untouched in the DB.)
    ('Passacaglia and Fugue in C, BWV 582',          # mode dropped
     'Passacaglia and Fugue in C minor, BWV 582'),  # Johann Sebastian Bach
    ('Passacaglia and Fugue in D minor, BWV 582',    # BWV 582 is in C minor
     'Passacaglia and Fugue in C minor, BWV 582'),  # Johann Sebastian Bach
    ('Quartet in F major Op.1 No.1 arr. for string orchestra',  # Op.1 are trios
     'Quartet in F major Op.18 No. 1 arr. for string orchestra'),  # Ludwig van Beethoven
    ('Scherzo from Piano Quintet in E minor, Op.44',  # Op.44 is in E flat
     'Scherzo from Piano Quintet in E flat major, Op.44'),  # Robert Schumann

    # --- --once re-airings, audit batch 2 (Vivaldi, Haydn, Dvořák,
    #     Tchaikovsky, Chopin, Mendelssohn, Grieg, Telemann).

    # --- Vivaldi: 2 re-aired works ---
    ('Allegro non molto from Oboe Concerto in A minor, RV.461',
     'Allegro non molto from Oboe Concerto in A minor'),  # Antonio Vivaldi
    # Retargeted 2026-05-28 (Vivaldi batch at file tail) — the
    # intermediate "Op 8 No 12 (RV 178)" canonical was itself folded
    # onward to the no-key-sig form. Skip the chain per
    # [[aliases-do-not-chain]].
    ('Violin Concerto in C major, RV.178',
     'Violin Concerto, Op 8 No 12, RV 178'),  # Antonio Vivaldi

    # --- Haydn: 10 re-aired works ---
    ("String Quartet in G minor, Op 74, No 3 'Rider' - 2nd movt",
     "2nd movement (Largo assai) - from String Quartet in G minor, Op 74 No 3 'Rider'"),  # Joseph Haydn
    ('Ave Regina for double choir, MH 140',
     'Ave Regina for double choir'),  # Michael Haydn
    ('Cantata: Lauft, ihr Hirten allzugleich (Run ye shepherds, to the light) for 4 voices, strings and continuo',
     'Cantata: Lauft, ihr Hirten allzugleich (Run ye shepherds, to the light) for 4 voices, strings and bc'),  # Joseph Haydn
    # London Trio No 1 in C (Hob.IV:1 = Hob.4:1) — retargeted to the larger
    # §hob4 group in the 2026-05-29 Haydn audit so all forms converge.
    ('Divertimento in C major, London Trio no 1, Hob.4:1',
     'Divertimento in C major, aka London Trio No 1 (Hob.4 No 1)'),  # Joseph Haydn
    ('Sonata in B flat major, H.16.41',
     'Keyboard Sonata in B flat major, H.16.41'),  # Joseph Haydn
    ('Overture to Lo Speziale (The Apothecary)',
     'Overture to Lo Speziale, H.28.3'),  # Joseph Haydn
    ('Sonata for piano (H.16.29) in F major',
     'Piano Sonata for piano in F major, Hob 16.29'),  # Joseph Haydn
    ('Symphony No.4 in D major',
     'Symphony No 4 (H.1.4) in D major (Presto'),  # Joseph Haydn
    ('Symphony No.88 in G (H.1.88)',
     'Symphony No.88 (H.1.88)'),  # Joseph Haydn
    ("Variations on the hymn 'Gott erhalte'",
     "Variations about the hymn 'Gott erhalte'"),  # Joseph Haydn

    # --- Dvořák: 4 re-aired works ---
    # Retargeted to align with the Dvořák audit batch — both this and the
    # orig-target now resolve to "Slavonic Dance No. 8 in G minor, op. 46".
    ('Slavonic dance No 8 in G minor Op 46 No 8 orch. composer (orig. for pf duet)',
     'Slavonic Dance No. 8 in G minor, op. 46'),  # Antonin Dvorak
    ('Symphony no 8 in G major, Op 88, B.163',
     'Symphony No.8 in G major (Op.88)'),  # Antonin Dvorak
    ('Three Slavonic Dances: Slavonic Dance No.8 in G minor, Op.46 no.8; Slavonic Dance No.10 in E minor, Op.72 no.2; Slavonic Dance No.15 in C major, Op.72 no.7',
     'Three Slavonic Dances (No 8 in G minor, Op 46 No 8; No 10 in E minor, Op 72 No 2; No 15 in C major, Op 72 No 7)'),  # Antonin Dvorak
    ('Two Waltzes, Op 54 [1.Moderato; 2.Allegro vivace]',
     'Two Waltzes, Op 54'),  # Antonin Dvorak

    # --- Tchaikovsky: 8 re-aired works ---
    ("Cherubim's Song, No. 3 from 'Nine Sacred Pieces' (encore)",
     "1. Cherubim's Song, No. 3 from 'Nine Sacred Pieces'"),  # Peter Ilyich Tchaikovsky
    ('Andante Cantabile from the string quartet (Op.11)',
     'Andante Cantabile (String Quartet, Op11), arranged by the composer'),  # Peter Ilyich Tchaikovsky
    ("Cradle Song (Andantino) from Six Romances, Op.16'1",
     'Cradle Song (Andantino) from Six Romances, Op.16'),  # Peter Ilyich Tchaikovsky
    ("Introduction and Waltz from 'Eugene Onegin'",
     'Introduction and Waltz (Eugene Onegin)'),  # Peter Ilyich Tchaikovsky
    # (Earlier Marche slave alias superseded by the consolidated batch
    # below, which folds all five Marche slave / Slavonic March variants
    # into "Marche Slave, Op 31".)
    ('Souvenir de Florence, Op.70 (Allegro vivace)',
     "Souvenir de Florence (4th mvt, 'Allegro vivace') Op 70"),  # Peter Ilyich Tchaikovsky
    ('Symphony No. 6 in B minor Op.74 (Pathétique) - 3rd mov arr. Carpenter for organ',
     "Symphony No 6 in B minor, Op 74, 'Pathétique' (3rd movt)"),  # Peter Ilyich Tchaikovsky
    ("Symphony No.1 in G minor (Op.13) 'Reves d'hiver'",
     'Symphony No.1 in G minor'),  # shared: Etienne-Nicolas Méhul / Peter Ilyich Tchaikovsky

    # --- Chopin: 12 re-aired works ---
    ('2 Nocturnes for piano (Op.48)no.1 in C minor',
     'Nocturne in C minor, Op 48, No 1'),  # Fryderyk Chopin
    # (The 'Preludes No.11 ... G sharp ...' → '24 Preludes Op.28: No.11 ...'
    # pair that lived here was retargeted 2026-07-03: both spellings now fold
    # to the recording-anchored 'From 24 Preludes, Op 28: nos 11-15' canonical
    # in the Op.28 consolidation block at the end of this table.)
    ('24 Preludes Op.28: No.11 in B major; No.12 in G sharp minor; No.13 in F sharp major; No.14 in E flat minor; No.15 in D flat major',
     'From 24 Preludes, Op 28: nos 11-15'),  # Fryderyk Chopin
    ('Finale. Presto ma non tanto agitato, (Excerpt Sonata No 3 in B flat, Op 58)',  # No 3 is in B minor
     'Finale. Presto ma non tanto agitato, (Excerpt Sonata No 3 in B minor, Op 58)'),  # Fryderyk Chopin
    ('2 Nocturnes for piano, Op 62 [no 1 in B major; no 2 in E major]',
     '2 Nocturnes for piano (Op.62)'),  # Fryderyk Chopin — the segment title of
     # recording p0106kr6 carries a member-LIST bracket (the only such title
     # corpus-wide, either lineage; the year-only [] drop rule rightly leaves
     # it), whose tokens split the set's 24 projected airings from the 5
     # text-only bare-titled ones. Whole-set both times; the Op 62 No 1/No 2
     # single-member airings stay split (set-member excerpt discipline).
    ('From Preludes, Op 28: nos 11-15',
     'From 24 Preludes, Op 28: nos 11-15'),  # Fryderyk Chopin
    ('Impromptu in Ab major, Op 29',
     'Impromptu in A flat major, Op.29'),  # Fryderyk Chopin
    ('Nocturne No 20 in C sharp minor Op posth. B49',
     'Nocturne No 20 C sharp minor Op posth. B49'),  # Fryderyk Chopin
    ('Nocturne in C sharp minor, Op.27 No.1, arr. for violin and piano',
     'Nocturne No 7 in C sharp minor, Op 27 No 1'),  # Fryderyk Chopin (arr. Milstein folds to the nocturne — literal transcription)
    ('Nocturne in D flat major, Op.27',
     'Nocturne in D flat major, Op 27 no 2'),  # Fryderyk Chopin
    ('Three Polonaises: Polonaise in A major, Op.40 No.1, Polonaise in E flat minor, Op.26 No.2; Polonaise in F sharp minor, Op.44',
     'Three Polonaises - Polonaise in A flat (Op.40 No.1), Polonaise in E flat minor (Op.26 No.2) & Polonaise in F sharp minor (Op.44)'),  # Fryderyk Chopin
    ('Waltz No. 42 in A flat, оp. 42',           # leading char is a Cyrillic 'о'
     'Waltz in A flat major, Op 42'),  # Fryderyk Chopin ('No 42' was a BBC mislabel of Op 42)
    ("Waltz No. 7 in C sharp minor, op.64'2",
     'Waltz in C sharp minor, Op 64 no 2'),  # Fryderyk Chopin

    # --- Mendelssohn: 9 re-aired works ---
    ('6 Lieder, Op 59',
     '6 Lieder for mixed voices Op.59'),  # Felix Mendelssohn
    ("Allegro vivace, from 'Symphony No. 4 in A, op. 90 (Italian)'",
     "Allegro vivace, 1st movement from 'Symphony No. 4 in A, op. 90 (Italian)'"),  # Felix Mendelssohn
    ('Elias (Elijah), Op.70 - oratorio: Part I',
     'Elias (Elijah), Op.70 - oratorio (Carus version): Part I'),  # Felix Mendelssohn
    ('Elias (Elijah), Op.70 - oratorio: Part II',
     'Elias (Elijah), Op.70 - oratorio (Carus version): Part II'),  # Felix Mendelssohn
    ('Piano Trio in C minor, MWV Q3',
     'Piano Trio in C minor'),  # Felix Mendelssohn
    ('Piano Trio in C minor, MWV.Q3',
     'Piano Trio in C minor'),  # Felix Mendelssohn
    ('Symphony for String Orchestra No 9 in C minor',
     'String Symphony No 9 in C minor'),  # Felix Mendelssohn
    ("Wedding March & Elfins Dance - from 'A Midsummer Night's Dream', Op.61 - Concert Paraphrase",
     "Wedding March & Elfin Dance - from 'A Midsummer Night's Dream', Op.61 - Concert Paraphrase"),  # Felix Mendelssohn

    # --- Grieg: 9 re-aired works ---
    ("3 Pieces from Slatter (Norwegian Peasant Dances), Op 72: Forspel/Tussebrurefedera pa Vossevangen (The Goblins' Wedding Procession at Vossevangen); Bruremarsj etter Myllarguten (Wedding march after the Miller's boy); Jon Vestafes springar (Jon Vestafe's springar)",
     '3 Pieces from Slatter (Norwegian Peasant Dances), Op 72'),  # Edvard Grieg
    ('3 Pieces from Slåtter (3 Pieces from Norwegian Peasant Dances) (Op.72)',
     '3 Pieces from Slatter (Norwegian Peasant Dances), Op 72'),  # Edvard Grieg
    ("Lyric Pieces (Lyriske stykker): Aften på højfjellet (Evening in the mountains) Op.68 No.4; For dine føtter (At your feet) (Op.68 No.3); Sommeraften (Summer's evening) Op.71 No.2; Forbi (Gone) Op.71 No.6; Etterklang (Remembrances) Op.71 No.7",
     "5 Lyric Pieces: Aften på højfjellet (Evening in the mountains) (Op.68 No.4); For dine føtter (At your feet) (Op.68 No.3); Sommeraften (Summer's evening) (Op.71 No.2); Forbi (Gone) (Op.71 No.6); Etterklang (Remembrances) (Op.71 No.7)"),  # Edvard Grieg
    ("Selected Lyric Pieces: Evening in the mountains (Op.68 No.4); At your feet (Op.68 No.3); Summer's evening (Op.71 No.2); Gone (Op.71 No.6); Remembrances (Op.71 No.7)",
     "5 Lyric Pieces: Aften på højfjellet (Evening in the mountains) (Op.68 No.4); For dine føtter (At your feet) (Op.68 No.3); Sommeraften (Summer's evening) (Op.71 No.2); Forbi (Gone) (Op.71 No.6); Etterklang (Remembrances) (Op.71 No.7)"),  # Edvard Grieg
    ('Fra ungdomsdagene (From early years) from Lyric pieces, book 8 for piano (Op.65 No.1)',
     'Fra ungdomsdagene (From Early Years) from Lyric Pieces, Book 8 for piano, Op.65'),  # Edvard Grieg
    ('Old Norwegian Romance with Variations - orig. for 2 pianos arr. for orchestra (Op.51) (1890)',
     'Gammelnorsk Romance met Variasjoner, Op 51'),  # Edvard Grieg
    ('Hvad est du dog skiøn (How fair thou art), No.1 of Four Pslams, Op 74',
     'How fair thou art from Four Hymns Op. 74'),  # Edvard Grieg
    ('Morning Mood, from Peer Gynt Suite No.1',
     "Morning Mood, from 'Peer Gynt, Suite No.1, Op.46' - arranged for piano four hands"),  # Edvard Grieg

    # --- Telemann: 5 re-aired works ---
    ("Harte Fessel, strenge Ketten, from 'Die syrische Unruh'; Der Himmel will, from 'Mario, TWV 21:6; Ach was für Qual und Schmerz, from 'Der unglückliche Alcmeon'",
     '3 arias: Harte Fessel, strenge Ketten (Die syrische Unruh); Der Himmel will, ich soll ein Ziel (Mario, TWV 21:6); Ach was für Qual und Schmerz (Der unglückliche Alcmeon)'),  # Georg Philipp Telemann
    ('Duet (Affetuoso) TWV 40:107 & Wandelt in der Liebe, gleich wie Christus uns geliebt! (aria)',
     'Affettuoso & Wandelt in der Liebe, gleich wie Christus uns geliebt! (aria)'),  # Georg Philipp Telemann
    ('Concerto in F minor for 3 violins and orchestra from Musique de table, partagée en trois productions',
     'Concerto in F minor for 3 violins (Musique de table)'),  # Georg Philipp Telemann
    ('Concerto in F minor for 3 violins and orchestra, from Musique de table',
     'Concerto in F minor for 3 violins (Musique de table)'),  # Georg Philipp Telemann
    ("Quartet in E minor, TWV.43:e4 'Paris Quartet' for flute, violin, bass viol and continuo",
     "Quartet No 12 in E minor, TWV 43:e4 'Paris Quartet'"),  # Georg Philipp Telemann

    # --- ttn_audit --once finds: re-airings the token sort can't reach ---
    ('Heidenröslein; Heidenröslein; Das Wanderern; Das Wandern',
     'Heidenroslein; Das Wandern'),  # Franz Schubert
    ('Adagio / Allegro in E flat major (K.Anh.C 17.07) for wind octet',
     'Adagio & Allegro in E flat major (K.Anh.C 17.07) for wind octet'),  # shared: Wolfgang Amadeus Mozart / Attributed Mozart, Wolfgang Amadeus

    # --- Sibelius: ttn_audit --once finds ---
    ("4 Songs: Svarta rosor [Black Roses] (Op.36 No.1); 2.Säv, sav, susa [Sigh Sedges sigh] (Op.36 No.4); Flickan kom ifran sin äls klings möte [The Maiden's tryst] (Op.37 No.5); Varen flyktar hastigt [Spring is flying] (Op.13 No.4)",
     "4 Songs: 1.Svarta rosor [Black Roses] (Op.36'1); 2.Säv, sav, susa [Sigh Sedges sigh] (Op.36'4); 3.Flickan kom ifran sin äls klings möte [The Maiden's tryst] (Op.37'5); 4.Varen flyktar hastigt [Spring is flying] (Op.13'4)"),  # Jean Sibelius
    ("4 Songs: Svarta rosor [Black Roses] (Op.36 No.1); Säv, sav, susa [Sigh Sedges sigh] (Op.36 No.4); Flickan kom ifran sin äls klings möte [The Maiden's tryst] (Op.37 No.5); Varen flyktar hastigt [Spring is flying] (Op.13 No.4)",
     "4 Songs: 1.Svarta rosor [Black Roses] (Op.36'1); 2.Säv, sav, susa [Sigh Sedges sigh] (Op.36'4); 3.Flickan kom ifran sin äls klings möte [The Maiden's tryst] (Op.37'5); 4.Varen flyktar hastigt [Spring is flying] (Op.13'4)"),  # Jean Sibelius
    ("Svarta rosor (Black Rose), Op 36 No 1; Säv, sav, susa (Sigh Sedges sigh), Op 36 No 4; Klickan kom ifran sin äls klings möte (The Maiden's Tryst), Op 37 No 5; Varen flyktar hastigt (Spring is Flying), Op 13 No 4",
     "4 Songs: 1.Svarta rosor [Black Roses] (Op.36'1); 2.Säv, sav, susa [Sigh Sedges sigh] (Op.36'4); 3.Flickan kom ifran sin äls klings möte [The Maiden's tryst] (Op.37'5); 4.Varen flyktar hastigt [Spring is flying] (Op.13'4)"),  # Jean Sibelius
    ("Svarta rosor (Black Roses) (Op.36 No.1); Säv, sav, susa (Sigh Sedges sigh) (Op.36 No.4); Klickan kom ifran sin äls klings möte (The Maiden's tryst) (Op.37 No.5); Varen flyktar hastigt (Spring is flying) (Op.13 No.4)",
     "4 Songs: 1.Svarta rosor [Black Roses] (Op.36'1); 2.Säv, sav, susa [Sigh Sedges sigh] (Op.36'4); 3.Flickan kom ifran sin äls klings möte [The Maiden's tryst] (Op.37'5); 4.Varen flyktar hastigt [Spring is flying] (Op.13'4)"),  # Jean Sibelius
    ('Souvenir, Tanz-Idylle and Berceuse from Six Pieces for violin and piano, op. 79',
     "Excerpts from 'Six Pieces for violin and piano, op. 79'"),  # Jean Sibelius
    ('Romance in D flat major Op. 24, No. 9 (encore) (10 Pieces Op.24 for piano, No. 9)',
     'Romance in D flat - from [10] Pieces for piano, Op 24 no 9'),  # Jean Sibelius
    # Retargeted to align with the Sibelius audit batch canonical.
    ('Valso triste op 44, No 1',
     'Valse triste, from Kuolema, incidental music Op 44'),  # Jean Sibelius

    # --- Liszt: ttn_audit --once finds ---
    ('Auf flügeln des Gesanges - from (Mendelssohn) No.1 of Songs (S.547) transc. for piano',
     'Auf Flügeln des Gesanges - from No 1 of 7 Songs by Mendelssohn (S547) transc. for piano'),  # Franz Liszt
    ('Ave Maria, S.20',
     'Ave Maria (1846)'),  # Gustav Holst
    ('Christus - Pastorale and Herald Angels Sing (extract)',
     'Christus - Pastorale and Herald Angels Sing'),  # Franz Liszt
    ('Christus - Pastorale; Herald Angels Sing',
     'Christus - Pastorale and Herald Angels Sing'),  # Franz Liszt
    ('Concert Study no. 2."Gnomenreigen" (S. 145)',
     'Concert Study No. 2, "Gnomenreigen", S. 145'),  # Franz Liszt
    # S.145 "Two Concert Studies" — consolidate each study's framings (bare /
    # "from Two Concert studies [for piano]"); Searle's S.145 spans BOTH
    # studies, so Waldesrauschen and Gnomenreigen stay distinct (no key-on-S).
    ('Gnomenreigen - from Two Concert studies for piano (S.145)',
     'Concert Study No. 2, "Gnomenreigen", S. 145'),  # Franz Liszt
    ('Waldesrauschen - from Two Concert studies, S145',
     'Waldesrauschen (S.145)'),  # Franz Liszt
    ('Waldesrauschen - from Two Concert studies for piano (S.145)',
     'Waldesrauschen (S.145)'),  # Franz Liszt
    ("Funerailles - No.7 from 'Harmonies poétiques et religieuses, S.173'",
     "Funerailles - No.7 from 'Harmonies poétiques et religieuses, S.173 - 10 pieces for piano'"),  # Franz Liszt
    ('Hungarian Coronation Mass, S 11)',
     'Hungarian Coronation Mass for SATB, chorus & orchestra'),  # Franz Liszt
    ('Hungarian Coronation Mass, S.11)',
     'Hungarian Coronation Mass for SATB, chorus & orchestra'),  # Franz Liszt
    ('Préludes - symphonic poem after Lamartine (S.97)',
     'Les Préludes - symphonic poem after Lamartine'),  # Franz Liszt
    ('St François de Paule marchant sur les flots - from 2 Légends (S.175 No.2)',
     'St Francois de Paule marchant sur les flots'),  # Franz Liszt

    # --- Handel: ttn_audit --once finds ---
    ('Dica il falso, dica il vero -- from Alessandro Act 2 Scene 8',
     "'Dica il falso, dica il vero' from Alessandro"),  # George Frideric Handel
    # 'Solitudini amate' (Alessandro) — one Boulin/La Petite Bande recording
    # aired 5 times under 3 work-keys. ttn_audit missed it: the 3-play form
    # is not a one-off, and the two 1-play forms score only 0.4 Jaccard.
    ('"Solitudini amate" (Alessandro)',
     "Alessandro (excerpt 'Solitudini amate')"),  # George Frideric Handel
    ('"Solitudini amate" (Beloved solitude)',
     "Alessandro (excerpt 'Solitudini amate')"),  # George Frideric Handel
    # 'Künft'ger Zeiten eitler Kummer' (HWV 202, Deutsche Arie No 1) — one
    # Plouffe/Pellerin/Laberge recording aired 6 times under 3 work-keys.
    # "HWV 20" in the second title is a typo for HWV 202.
    ('Künft\'ger Zeiten eitler Kummer, HWV 20 - No 1 from Deutsche Arien (originally for soprano, violin & bc, arranged for oboe, violin and organ)',
     "Kunft'ger Zeiten eitler Kummer (HWV.202) - no.1 from Deutsche Arien"),  # George Frideric Handel
    ("Künft'ger Zeiten eitler Kummer (HWV.202) (arr. for oboe, violin and organ)",
     "Kunft'ger Zeiten eitler Kummer (HWV.202) - no.1 from Deutsche Arien"),  # George Frideric Handel

    # --- Prokofiev: ttn_audit --once finds ---
    ('Arrival of the Guests (Romeo and Juliet)',
     'Arrival of the Guests (Minuet) from Romeo and Juliet'),  # Sergey Prokofiev
    ('God of evil and pagan dance (Allegro sostenuto) - no.2 from Scythian suite from "Ala i Lolly", Op.20',
     'God of Evil and Pagan Dance (Allegro sostenuto) - No.2 from Scythian Suite'),  # Sergey Prokofiev
    ('Moderato, from Sonata for Solo Violin in D, op. 115',
     "Moderato, from 'Sonata Solo Violin in D, op. 115'"),  # Sergey Prokofiev
    ('Sonata no.5 in C major, Op 135',
     'Piano Sonata no.5 in C major, Op.135 (version revised)'),  # Sergey Prokofiev
    ('Sonata no.5 in C major, Op.135 (vers. revised)',
     'Piano Sonata no.5 in C major, Op.135 (version revised)'),  # Sergey Prokofiev
    # Retargeted to align with the Prokofiev audit batch canonical.
    ('Prelude - No.7 from Pieces for piano (Op.12)',
     'Prelude - No. 7 from 10 Pieces for piano (Op.12)'),  # Sergey Prokofiev

    # --- Monteverdi: ttn_audit --once finds ---
    ('2 Madrigals by Monteverdi and a Sonate a 3 by Dario Castello',
     '2 Madrigals by Monteverdi and a Sonata a 3 by Dario Castello'),  # Claudio Monteverdi
    ("Lamento d'Arianna, a 5 SV.107",
     "Lamento d'Arianna, a 5 (SV 107)"),  # Claudio Monteverdi

    # --- Verdi: ttn_audit --once finds ---
    ('Caro nome (Rigoletto)',
     '"Caro nome" Gilda\'s aria from Rigoletto'),  # Giuseppe Verdi
    ("Quando le sere al placido (Rodolfo's aria from act 2 of 'Luisa Miller')",
     "'Quando le sere al placido' (Rodolfo's aria) from Luisa Miller"),  # Giuseppe Verdi
    ('Anvil Chorus (Il Troviatore)',
     'Anvil Chorus (Il Trovatore)'),  # Giuseppe Verdi
    ("Danza sacra e duetto finale d'Aida, S436",
     'Danza sacra e Duetto finale - Aida S.436'),  # Giuseppe Verdi
    ('Lina, pensai che un angelo (Stiffelio)',
     'Lina pensai che un angelo (Stiffelio, Act III)'),  # Giuseppe Verdi
    ('Son io mio Carlo (Don Carlos Act III)',
     'Son io mio Carlo (Don Carlo)'),  # Giuseppe Verdi

    # --- Debussy: ttn_audit --once finds ---
    ("Images II (Cloches à travers les feuilles; Et la lune déscend sur la temple qui fut; Poissons d'or)",
     "Cloches à travers les feuilles; Et la lune déscend sur la temple qui fut; Poissons d'or (Images Bk 2)"),  # Claude Debussy
    # (the 'cathÃ©drale' mojibake prelude-list straggler is now repaired by
    # canonical_key's _demojibake, so the former hand-alias is removed)
    ('Des pas sur la neige; No.6 from Preludes Book One',
     'Des pas sur la neige (Preludes Book 1, no 6)'),  # Claude Debussy (re-targeted 2026-07-19: old Book-One target became an LHS)
    ('Des pas sur la neige - from Preludes Book 1',
     'Des pas sur la neige - Preludes Book'),  # Claude Debussy
    ("Preludes (excerpts): Voiles; La Cathedrale engloutie; La Serenade interrompue; Feuilles mortes; La puerta del vino; Les Fees sont d'exquises danseuses",
     "Preludes (excerpts) - [Book 1 no.2: Voiles; Book 1 no.10: La Cathedrale engloutie; Book 1 no.9: La Serenade interrompue; Book 2 no.2: Feuilles mortes; Book 2 no.3 La puerta del vino; Book 2 no.4: Les Fees sont d'exquises danseuses]"),  # Claude Debussy

    # --- Dvořák: ttn_audit --once finds ---
    ('Kdyz men stara matka zpivat , from Ciganske melodie Op 55 No 4',
     'no.4 Als die alte Mutter [songs my mother taught me]'),  # Antonin Dvorak
    # Retargeted to align with the Dvořák audit batch — both forms now
    # fold into "Legend in C major, Op 59 no 4".
    ('Legend in C major (Molto maestoso), Op.59 No.4, orch. by the composer',
     'Legend in C major, Op 59 no 4'),  # Antonin Dvorak
    ('Legend in C major (Molto maestoso) Op 59 No 4 orchestrated by the composer',
     'Legend in C major, Op 59 no 4'),  # Antonin Dvorak
    # the last form's title is truncated mid-string; its ~10m length
    # confirms it carries both dances, like the other four
    ('Two Slavonic Dances (Op.46): No.8 (Presto) in G minor & No.3 (Poco Allegro) in A flat major',
     'Two Slavonic Dances, Op 46 - no 8 in G minor and no 3 in A flat major'),  # Antonin Dvorak
    ('Two Slavonic Dances: Op 46 No 8 in G minor (Presto) & Op 46 No 3 in A flat major (Poco allegro)',
     'Two Slavonic Dances, Op 46 - no 8 in G minor and no 3 in A flat major'),  # Antonin Dvorak
    ('Two Slavonic Dances: Op 46 No 8 in G minor (Presto); Op 46 No 3 in A flat major (Poco Allegro)',
     'Two Slavonic Dances, Op 46 - no 8 in G minor and no 3 in A flat major'),  # Antonin Dvorak
    ('Two Slavonic Dances: Op 46 No 8 in G minor and Op 46 No 3 in A flat major',
     'Two Slavonic Dances, Op 46 - no 8 in G minor and no 3 in A flat major'),  # Antonin Dvorak

    # --- Purcell: ttn_audit --once finds ---
    ("Song 'See, even Night herself is here' (Z.62/11) - from 'The Fairy Queen', Act II Scene 3",
     '"See, even Night herself is here" (Z.62/11) from \'The Fairy Queen\''),  # Henry Purcell
    ("Song 'See, see, even Night herself is here' Z 62/11 - from 'The Fairy Queen', Act II Scene 3",
     '"See, even Night herself is here" (Z.62/11) from \'The Fairy Queen\''),  # Henry Purcell
    ("Ode for the Birthday of Queen Mary 'Come, ye sons of Art, away'",
     'Ode for the birthday of Queen Mary'),  # Henry Purcell
    ('Sonata in B flat major, Z.791, for 2 violins and continuo',
     'Sonata - 1683 no. 2 in B flat major Z.791 for 2 violins and continuo'),  # Henry Purcell

    # --- Franck: ttn_audit --once finds ---
    ('Le Chausseur maudit (The Accursed Huntsman), symphonic poem',
     'Le Chasseur maudit (The Accursed Huntsman), symphonic poem'),  # Cesar Franck
    ('Piece in D flat (1863)',
     'Organ Piece in D flat major'),  # Cesar Franck

    # --- Richard Strauss: ttn_audit --once finds ---
    ('4 Lieder: Ständchen (Serenade) (Op.17 No.2); Morgen (Tomorrow) (Op.27 No.4); Für fünfzehn Pfennige (For 15 Pennies) (Op.36 No.2) (brief appl); Zueignung (Dedication) (Op.10 No.1)',
     '4 Lieder (Ständchen, Op.17 No.2; Morgen, Op.27 No.4; Für fünfzehn Pfennige, Op.36 No.2; Zueignung, Op.10 No.1)'),  # Richard Strauss
    ('4 Lieder: Ständchen (Serenade) (Op.17 No.2); Morgen (Tomorrow) (Op.27 No.4); Für fünfzehn Pfennige (For 15 Pennies) (Op.36 No.2); Zueignung (Dedication) (Op.10 No.1)',
     '4 Lieder (Ständchen, Op.17 No.2; Morgen, Op.27 No.4; Für fünfzehn Pfennige, Op.36 No.2; Zueignung, Op.10 No.1)'),  # Richard Strauss
    ('Ständchen (Op.17 No.2); Morgen (Op.27 No.4); Für fünfzehn Pfennige (Op.36 No.2); Zueignung (Op.10 No.1)',
     '4 Lieder (Ständchen, Op.17 No.2; Morgen, Op.27 No.4; Für fünfzehn Pfennige, Op.36 No.2; Zueignung, Op.10 No.1)'),  # Richard Strauss
    ('Ewig einsam/Wenn du einst die Gauen from "Guntram" Op 25',
     "Ewig einsam ... Wenn du einst die Gauen (from 'Guntram' Op 25)"),  # Richard Strauss
    ('Lieder: Das Rosenband (Op.36 No.1); Glückes genug (Op.37 No.1); Ständchen (Op.17 No.2); Ein Obdach gegen Strum und Regen (Op.46 No.1); Morgen (Op.27 No.4); In goldener Fülle (Op.49 No.2)',
     'Lieder: Das Rosenband (Op.36 No.1); Glückes genug (Op.37 No.1); Standchen (Op.17 No.2); Ein Obdach gegen Sturm und Regen (Op.46 No.1); Morgen (Op.27 No.4); In goldener Fülle (Op.49 No.2)'),  # Richard Strauss
    ('Love Scene from Feuersnot, Op 50',
     "Love Scene - from the opera 'Feuersnot'"),  # Richard Strauss

    # --- Rameau: ttn_audit --once finds ---
    ("3 pieces from 'Les Indes Galantes' (Air pour Zéphire; Musette en Rondeau; Air pour Borée et la Rose); Le Rappel des Oiseaux",
     '3 Pieces from Les Indes galantes; Le Rappel des oiseaux'),  # Jean-Philippe Rameau
    ("Ces oiseaux (à Le Temple de la gloire') (Trajan's aria)",
     "Ces oiseaux ('Le Temple de la gloire')"),  # Jean-Philippe Rameau
    ("Ces oiseaux, from 'Le Temple de la Gloire'",
     "Ces oiseaux ('Le Temple de la gloire')"),  # Jean-Philippe Rameau
    ('Le Rappel des Oiseaux, in E minor, from Pieces de clavecin',
     'Le Rappel des Oiseaux in E minor, from Pieces de clavecin (1724, revised.1731)'),  # Jean-Philippe Rameau

    # --- Pejačević: ttn_audit --once finds ---
    ('Four piano pieces: Barcarole; Song without words, Op.5; Butterfly, Op.6; Impromptu, Op.9',
     'Four piano pieces: Barcarole, Op.4; Song without words, Op.5; Butterfly, Op.6; Impromptu, Op.9'),  # Dora Pejacevic

    # --- Scarlatti: ttn_audit --once finds ---
    ('Sonata in D major Kk.443; Sonata in A major Kk.208; Sonata in D major Kk.29',
     'Keyboard Sonata in D major, Kk.443; Sonata in A major, Kk.208; Sonata in D major, Kk.29)'),  # Domenico Scarlatti
    ('Sonata for keyboard in E major, Kk.46',
     'Sonata for keyboard in E major (K.46/L.25)'),  # Domenico Scarlatti
    ('Sonata in E major, Kk.46',
     'Sonata for keyboard in E major (K.46/L.25)'),  # Domenico Scarlatti
    ('Sonata in G major, K14',
     'Sonata in G major'),  # shared: Jean Baptiste Loeillet / Giovanni Battista Pergolesi

    # --- Rachmaninov: ttn_audit --once finds ---
    # (Both retargeted to the Rachmaninov audit batch canonicals below.)
    ('Six Pieces for four hands, Op 11',
     '6 Duets Op 11 for piano 4 hands'),  # Sergey Rachmaninov
    ('6 Pieces for four hands, Op.11',
     '6 Duets Op 11 for piano 4 hands'),  # Sergey Rachmaninov
    ('Cello Sonata in G minor Op 19 (excerpt Andante)',
     'Cello Sonata in G minor Op 19 (Andante)'),  # Sergey Rachmaninov
    ('Bogoroditse Devo, from Vespers (All-Night Vigil) (Ave Maria)',
     'Bogoróditse Dévo, ráduisya - from All-Night Vigil (Op.37)'),  # Sergey Rachmaninov

    # --- Ravel: ttn_audit --once finds ---
    ('Le Tombeau de Couperin (Forlane & Allegretto)',
     'Le Tombeau de Couperin (Forlane'),  # Maurice Ravel
    ("Soupir, from 'Trois Poèmes de Stéphane Mallarmé'",
     "Soupir, 'Trois Poèmes de Stéphane Mallarmé'"),  # Maurice Ravel

    # --- Schütz: ttn_audit --once finds (incl. a BWV->SWV catalogue typo) ---
    ('3 sacred pieces - Anima mea liquefacta; Adjuro vos, filiae Hierusalem; Siehe, wie fein und lieblich ist',
     '3 sacred pieces - Anima mea liquefacta; Adjuro vos, filiae Hierusalem; Siehe, wi'),  # Heinrich Schütz
    ('Die Himmel erzählen die Ehre Gottes, SWV 76',
     'Die Himmel erzählen die Ehre Gottes, BWV 76'),  # Heinrich Schütz
    ('Saul, Saul, was verfolgst du mich, SWV.415; Nun will sich scheiden Nacht und Tag, after SWV.138; Herr, unser Herrscher (Psalm 8), SWV.27',
     'Saul, Saul, was verfolgst du mich, SWV 415; Nun will sich scheiden Nacht und Tag, after SWV 138; Herr, unser Herrscher (Psalm 8), SWV 27'),  # Heinrich Schütz

    # --- Wagner: ttn_audit --once finds ---
    ('Die Meistersinger von Nürnberg (Prelude)',
     'Die Meistersinger von Nürnberg'),  # Richard Wagner
    # Flying Dutchman overture — retargeted to the larger "(The Flying
    # Dutchman)" group in the 2026-05-29 Wagner audit so all forms converge.
    ("Overture to 'Der fliegende Holländer' - The Flying Dutchman",
     "Overture: Der Fliegende Hollander (The Flying Dutchman)"),  # Richard Wagner
    ("Overture to 'Der fliegende Holländer'",
     "Overture: Der Fliegende Hollander (The Flying Dutchman)"),  # Richard Wagner

    # --- Szymanowski: ttn_audit --once finds ---
    ('Excerpts from 20 Mazurkas for piano (Op.50): no.1, no.2 & no.13',
     '20 Mazurkas for piano, Op 50 nos 1, 2 & 13'),  # Karol Szymanowski
    ('Excerpts from 20 Mazurkas for piano (Op.50): nos.1, 2 & 13',
     '20 Mazurkas for piano, Op 50 nos 1, 2 & 13'),  # Karol Szymanowski
    ('From 20 Mazurkas for piano Op 50: No 1 in E major; No 2; No 13',
     '20 Mazurkas for piano, Op 50 nos 1, 2 & 13'),  # Karol Szymanowski
    ('From 20 Mazurkas for piano, Op.50: No.1; No.2; No.13',
     '20 Mazurkas for piano, Op 50 nos 1, 2 & 13'),  # Karol Szymanowski

    # --- Couperin: ttn_audit --once finds ---
    ('Rondeau: Les Barricades mystérieuses',
     'Les Barricades mystérieuses'),  # François Couperin
    ('Les Fastes de la grande et ancienne Ménestrandise (Mxnxstrxndxsx) (Pièces de clavecin - ordre 11)',
     'Les Fastes de la grande et ancienne Menestrandise from Pieces de clavecin - ordre no.11'),  # François Couperin
    ('Les Fastes de la grande et ancienne Ménestrandise (Mxnxstrxndxsx) (Pièces de clavecin - ordre no.11)',
     'Les Fastes de la grande et ancienne Menestrandise from Pieces de clavecin - ordre no.11'),  # François Couperin
    ('Les Fastes de la grande et ancienne Ménestrandise (Pièces de clavecin - ordre no.11)',
     'Les Fastes de la grande et ancienne Menestrandise from Pieces de clavecin - ordre no.11'),  # François Couperin
    ("Pièces de clavecin - Première ordre (Paris, 1713) (L'Auguste (Allemande); Première Courante; Seconde Courante; La Majestueuse (Sarabande); Gavotte; La Milordine (Gigue); Menuet; Les Sylvains (Rondeau); Les Abeilles (Rondeau); La Nanète; les Sentiments (Sarabande); la Pastorelle; Les Nonètes. Les Blondes. Les Brunes; La Bourbonnoise (Gavotte); La Manon; L'Enchantresse (Rondeau); La Fleurie ou la tendre Nanette; Les plaisirs de Saint-Fermain-en-Laye)",
     "Les Pièces de clavecin - Première ordre (Paris, 1713) (L'Auguste (Allemande); Première Courante; Seconde Courante; La Majestueuse (Sarabande); Gavotte; La Milordine (Gigue); Menuet; Les Sylvains (Rondeau); Les Abeilles (Rondeau); La Nanète; les Sentiments (Sarabande); la Pastorelle; Les Nonètes. Les Blondes. Les Brunes; La Bourbonnoise (Gavotte); La Manon; L'Enchantresse (Rondeau); La Fleurie ou la tendre Nanette; Les plaisirs de Saint-Germain-en-Laye)"),  # François Couperin

    # --- Falla: ttn_audit --once finds ---
    ("Suite from 'El Amor brujo'",
     'El Amor brujo (Suite)'),  # Manuel de Falla
    ('Suite of Spanish Folksongs (nos 2 & 4)',
     'Excerpts from Suite of Spanish Folksongs nos 2 & 4'),  # Manuel de Falla

    # --- Corelli: ttn_audit --once finds ---
    ('Organ Concerto in C major (Op 6 No 10)',
     'Concerto in C major (Op.6 No.10)'),  # Arcangelo Corelli

    # --- Anonymous: ttn_audit --once finds (a Schola Cantorum Riga
    # chant programme aired twice, plus an encore) ---
    ('Calicem salutaris, Psalmus 115 (processional)',
     'Calicem Salutaris, Psalmus 115 Processionale'),  # Anonymous
    ('Quasi stella matutina (antiphon)',
     'Quasi Stella Matutina Antiphona'),  # Anonymous
    ('Simile est regnum (antiphon and Magnificat)',
     'Simile Est Regnum Antiphona and Magnificat'),  # Anonymous
    ('Veni Sancte Spiritus Antiphona',
     'Veni Sancte Spiritus (antiphon)'),  # Anonymous

    # --- Alban Berg: ttn_audit --once finds ---
    ('Drei Bruchstücke aus Wozzeck, (Three fragments frm Wozzeck) Op 7',
     'Drei Bruchstücke aus Wozzeck (Three fragments from Wozzeck) Op 7'),  # Alban Berg
    ('Three Fragments from Wozzeck (Op. 7)',
     'Drei Bruchstücke aus Wozzeck (Three fragments from Wozzeck) Op 7'),  # Alban Berg
    ('Lyric Suite (version for string orchestra)',
     'Lyric Suite (string orchestra version)'),  # Alban Berg
    # --- Alexander Scriabin: ttn_audit --once finds ---
    ('15 Preludes (selection from Opp.11, 16, 17, 22, 27 & 31)',
     '15 Preludes (selection from Opp 11, 16, 17, 22, 27 & 31)'),  # Alexander Scriabin
    ('Study in C sharp minor (3 Pieces for piano Op. 2 No. 1)',
     'From 3 Pieces for piano (Op. 2): No. 1, Study in C sharp minor'),  # Alexander Scriabin
    # --- Anon: ttn_audit --once finds ---
    # --- Bela Bartok: ttn_audit --once finds ---
    ('Volume 4 from 44 Duos for 2 violins, Sz.98/4',
     '44 Duos for 2 violin, Sz 98/4: Vol 4 (excerpts) - No 39 Szerb tanc; No 40 Olah tanc; No 41 Scherzo; No 42 Arab dal; No 43 Pizzicato; No 44 Erdelyi tanc (Ardeleana)'),  # Bela Bartok
    ('Twenty Hungarian Folksongs, BB 98',
     "Excerpts from 'Twenty Hungarian Folksongs, BB 98'"),  # Bela Bartok
    # --- Benjamin Britten: ttn_audit --once finds ---
    ('Canadian Carnival Overture',
     'Canadian Carnival'),  # Benjamin Britten
    ('Les Illuminations for voice and string orchestra',
     'Les Illuminations for organ and string orchestra'),  # Benjamin Britten
    # --- Christoph Willibald Gluck: ttn_audit --once finds ---
    ('Paris e Helena, ballet music',
     "Ballet music (excerpt 'Paris e Helena'"),  # Christoph Willibald Gluck
    # --- Dmitry Shostakovich: ttn_audit --once finds ---
    # --- Eugene Ysaye: ttn_audit --once finds ---
    # --- Fanny Hensel Mendelssohn: ttn_audit --once finds ---
    ('Excerpts from Songs Without Words (Op.6) (1846): Nos.1, 3 & 4',
     'Excerpts from Songs Without Words (Op.6) (1846)'),  # Fanny Mendelssohn
    ('Trio Op.11 in D minor',
     'Piano Trio in D minor, Op.11'),  # Fanny Mendelssohn
    # --- Haydn: ttn_audit --once finds ---
    ("Symphony No. 103 in E flat major 'Drum Roll'",
     "Symphony No. 103 in E flat, Hob. I:103 'Drumroll'"),  # Joseph Haydn
    ('Symphony No.104 in D major "London" (H.1.104)',
     'Symphony No.104 in D major "London"'),  # Joseph Haydn
    # --- Hector Berlioz: ttn_audit --once finds ---
    ('Marche hongroise (Rakoczy march) from La Damnation de Faust - Part 1, scene 3',
     'Marche hongroise (Rakoczy march) from La Damnation de Faust'),  # Hector Berlioz
    # --- Ignacy Jan Paderewski: ttn_audit --once finds ---
    ('Menuet in G (Humoresques de Concert, Op.14 no.1 (1886))',
     'Menuet in G (Humoresques de Concert, Op 14 (1886))'),  # Ignacy Jan Paderewski
    # --- Isaac Albeniz: ttn_audit --once finds ---
    ("El Albaicín, from 'Iberia, Book 3'",
     'El Albaicín (Iberia, Book 3)'),  # Isaac Albeniz
    # --- Jan Pieterszoon Sweelinck: ttn_audit --once finds ---
    ('Fantasia in D minor (3)',
     'Fantasia in D minor'),  # Jan Pieterszoon Sweelinck
    ('Fantasia in G major (2) (10)',
     'Fantasia in G major'),  # Jan Pieterszoon Sweelinck
    # --- Joseph Martin Kraus: ttn_audit --once finds ---
    ('Symphony in E flat',
     'Sinfonie in E flat'),  # Joseph Martin Kraus
    # --- Kaspar Forster: ttn_audit --once finds ---
    ('Dulcis amor Jesu KBPJ 16',
     'Dulcis amor Jesu'),  # Kaspar Förster
    ('Vanitas vanitatum - dialogus de Divite et paupere Lazaro for soprano, tenor, bass and instruments',
     'Vanitas vanitatum - dialogus de Divite et paupere Lazaro'),  # Kaspar Förster
    # --- Max Bruch: ttn_audit --once finds ---
    ('Excerpts from Eight Pieces for clarinet, viola and piano, Op 83 (nos 5-8)',
     'Excerpts from Eight Pieces for clarinet, viola and piano, Op 83'),  # Max Bruch
    ('Scottish Fantasy (Fantasy for Violin and Orchestra with Harp, freely using Scottish Folk Melodies), Op 46',
     'Fantasy for Violin and Orchestra with Harp (Op.46)'),  # Max Bruch
    ('Scottish fantasy for violin and orchestra (Op.46)',
     'Fantasy for Violin and Orchestra with Harp (Op.46)'),  # Max Bruch
    # --- Olivier Messiaen: ttn_audit --once finds ---
    ('Hymne au Saint Sacrament for orchestra',
     'Hymne au Saint Sacrament'),  # Olivier Messiaen
    ("Louange à l'Éternité de Jésus: No 5 from Quatuor pour la fin du temps",
     "Louange à l'Éternité de Jésus (No.5, Quatuor pour la fin du temps for clarinet, piano, violin and cello)"),  # Olivier Messiaen
    # --- Peter Ilyich Tchaikovsky: ttn_audit --once finds ---
    ('Waltz from Sleeping Beauty',
     'Waltz (Sleeping Beauty)'),  # Peter Ilyich Tchaikovsky
    ("Ya vas lyublyu bezmerno (I love you beyond measure) - Prince Yeletsky's aria from The Queen of Spades",
     "Ya vas lyublyu bezmerno (I love you beyond measure) - Prince Yeletsky's aria"),  # Peter Ilyich Tchaikovsky
    # --- Stanislaw Moniuszko: ttn_audit --once finds ---
    ("From 4 Choral Songs: Kozak ('The Cossack'), Wedrowna ptaszyna ('Little Wandering Bird')",
     'Choral Songs (The Cossack; Little Wandering Bird)'),  # Stanislaw Moniuszko
    ('Triolet (Triolet)',
     'Triolet'),  # Stanislaw Moniuszko
    # --- Traditional: ttn_audit --once finds ---
    ('A u sviecie nam navina byla (Belarusian Christmas Song)',
     'A u sviecie nam navina byla'),  # Traditional
    ('Trei cantece de stea din Dobrogea (Steaua sus rasare)',
     'Trei cantece de stea din Dobrogea'),  # Traditional
    # --- ttn_audit --all triage (2026-05): 146 re-airing merge groups ---
    ("Elle ne croyait pas ('Mignon', Act 3)",
     "'Elle ne croyait pas' (aria from Mignon)"),  # Ambroise Thomas
    ('Air à deux parties “Délices des étés” (Le Camus); Pièce pour clavecin (Le Roux); Air de cour “Goûtons un doux repos” (Lambert)',
     '2 French airs and 1 piece for harpsichord [Air à deux parties “Délices des étés”; Pièce pour clavecin; Air de cour “Goûtons un doux repos”]'),  # Sebastian Le Camus
    ('Najpiękniejsze pionski (The most beautiful songs) Op.4 - words by Adam Asnyk; Pod jaworem (Under the sycamore) - folk song from Włoszczowa region',
     '2 Songs: Najpiekniejsze pionski (The most beautiful songs, words by Adam Asnyk) (Op.4); Pod jaworem (Under the sycamore, folk song from Wloszczowa region)'),  # Mieczyslaw Karlowicz
    ('Fairy Tale in A minor, Op.51 No.2; Fairy Tale in E flat major, Op.26 No.2; Fairy Tale in B flat minor Op.20 No.1',
     '3 Fairy Tales (Fairy Tale in A minor, Op 51 No 2; Fairy Tale in E flat major, Op 26 No 2; Fairy Tale in B flat minor Op 20 No 1)'),  # Nikolai Medtner
    ('3 Pieces for Cello and Piano - excerpts',
     '3 Pieces for Cello and Piano - exceprts'),  # Nadia Boulanger
    ('3 Pieces for organ from the film Richard III (March; Elegy; Scherzetto)',
     "3 Pieces for organ from 'Richard III'"),  # William Walton
    ('3 pieces: Josquin: In te Domine speravi; Anon: Zorzi; Giorgio - Saltarello; Anon: Forte cosa e la speranza',
     '3 pieces: Josquin: In te Domine speravi (in 4 parts, with voice); Anon: Zorzi, Giorgio - Salterello (instrumental); Anon: Forte cosa e la speranza (in 5 parts, with voice)'),  # Josquin des Prez
    ('3 pieces: [Josquin: In te Domine speravi (in 4 parts, with voice); Anon: Zorzi; Giorgio - Saltarello (instrumental); Anon: Forte cosa e la speranza (in 5 parts, with voice)]',
     '3 pieces: Josquin: In te Domine speravi (in 4 parts, with voice); Anon: Zorzi, Giorgio - Salterello (instrumental); Anon: Forte cosa e la speranza (in 5 parts, with voice)'),  # Josquin des Prez
    ('4th movement from Viola Sonata, Op 25 No.1',
     '4th movement from Viola Sonata, Op 25 No 1 (Rasendes Zeitmass. Wild. Tonschönheit ist Nebensache)'),  # Paul Hindemith
    ('Rasendes Zeitmaß. Wild. Tonschönheit ist Nebensache, from Viola Sonata op 25',
     '4th movement from Viola Sonata, Op 25 No 1 (Rasendes Zeitmass. Wild. Tonschönheit ist Nebensache)'),  # Paul Hindemith
    ('Adagio patetico, 3rd movement from Piano Quintet, Op 5 (1901)',
     'Adagio patetico (excerpt Piano Quintet, Op 5)'),  # Dirk Schäfer
    ('Alma Redemptoris Mater; Ave Maria, O auctrix vite - Responsorium',
     'Alma Redemptoris Mater & Ave Maria, O auctrix vite'),  # Hildegard of Bingen (re-targeted 2026-07-19: the old ';' target became an alias LHS in the Hildegard batch -- aliases don't chain)
    ('Concert Arabesques on Themes from The Blue Danube Waltz by Johann Strauss',
     'Arabesques on Themes from The Blue Danube Waltz by Johann Strauss, for piano'),  # Adolf Schulz-Evler
    ('Aria "Oh! Ne t\'éveille pas encore" - from \'Jocelyn\', Act 1',
     'Aria "Oh! Ne t\'éveille pas encor" - from \'Jocelyn\', Act 1'),  # Benjamin Godard
    ("Oh! Ne t'eveille pas encore (Jocelyn, Act 1)",
     'Aria "Oh! Ne t\'éveille pas encor" - from \'Jocelyn\', Act 1'),  # Benjamin Godard
    ("Aria 'Voi lo sapete, O Mamma' from 'Cavalleria Rusticana' (from Scene 1, sung by Santuzza)",
     'Aria "Voi lo sapete, O Mamma" from \'Cavalleria Rusticana\''),  # Pietro Mascagni
    ("Santuzza's Aria 'Voi lo sapete, O Mamma' - from 'Cavalleria Rusticana', Scene 1",
     'Aria "Voi lo sapete, O Mamma" from \'Cavalleria Rusticana\''),  # Pietro Mascagni
    ("Santuzza's aria 'Voi lo sapete, O mamma' from 'Cavalleria Rusticana'",
     'Aria "Voi lo sapete, O Mamma" from \'Cavalleria Rusticana\''),  # Pietro Mascagni
    ('Aria No.2 (Vocalise No.2)',
     'Aria No 2 (Vocalise)'),  # Albert Roussel
    ('On the Beautiful Blue Danube (Op.314)',
     'Beautiful Blue Danube (Op.314)'),  # Johann Strauss II
    ("Bride's Waltz - from Et folksagn",
     "Bride's Waltz (from Et folkesagn)"),  # Niels Wilhelm Gade
    ('Canzon II Septimi Toni a 8 from Sacrae Symphoniae 1597',
     'Canzon II Septimi Toni a 8 from Sacrae Symphoniae'),  # Giovanni Gabrieli
    ('Prés des remparts de Séville, from Carmen',
     'Carmen (Prés des remparts de Séville)'),  # Georges Bizet
    ('Cello Concerto (T.120)',
     'Cello Concerto'),  # shared: William Walton / Iris Szeghy / Bliss, Sir Arthur
    ('Sonata in E major arr. for cello and piano',
     'Cello Sonata in E major (orig. for violin and piano)'),  # François Francoeur
    ("Cello Sonata in G, Op 5 No 8 - from 'Eight solos for the violoncello with a thorough bass'",
     "Cello Sonata in G, Op 5 No 8 - from 'Eight solos for the violincello with a thorough bass'"),  # Pieter Hellendaal
    ('Cinques Danses exotiques, for saxophone and piano',
     'Cinq Danses exotiques, for saxophone and piano'),  # Jean Françaix
    ('Trio in E flat major',
     'Clarinet Trio in E flat (1900)'),  # Gustav Uwe Jenner
    ('Yel-yel (Come on, bull)',
     'Come on my bull'),  # Vardapet Komitas
    ('Concerto for flute, (2) oboes, strings & bc in G minor (S.Uu (i hs 58:5))',
     'Concerto for flute, (2) oboes, strings & basso continuo in G minor'),  # Johann Christian Schickhardt
    ('Contre qui Rose - 2nd movement from Les Chansons des Roses',
     'Contre qui Rose (1993) - 2nd movement from Les Chanson des Roses'),  # Morten Lauridsen
    ('Credo From Missa Si Deus pro nobis à16',
     'Credo From Missa Si Deus pro nobis à 16'),  # Orazio Benevoli
    ('De profundis (Psalm 129) in C minor, ZWV 96',
     'De profundis (Psalm 129) in C minor'),  # Jan Dismas Zelenka
    ('Overture from Die Leichte Kavallerie',
     'Die Leichte Kavallerie (Light cavalry)'),  # Franz von Suppe
    ('Overture from Die Leichte Kavallerie (Light cavalry)',
     'Die Leichte Kavallerie (Light cavalry)'),  # Franz von Suppe
    ('Dixit Dominus for 5 voices and continuo',
     'Dixit Dominus - for 5 voices & basso continuo'),  # Giacomo Carissimi
    ('Drommarne - version for orchestra and choir',
     'Drommarne (Dreams) - version for orchestra and choir'),  # Adolf Fredrik Lindblad
    ("Duos from Mozart's Don Giovanni arranged for 2 cellos ('Giovinette che fate all'amore'; 'La ci darem la mano', 'Finch han dal vino')",
     'Duos from "Don Giovanni" arranged for 2 cellos (\'Giovinette che fate all\'amore\'; \'La ci darem la mano\', \'Finch han dal vino\')'),  # Franz Danzi
    ('Overture, Dwie Chatki (Two Huts)',
     'Dwie Chatki (Two Cottages): The Overture'),  # Karol Kurpinski
    ("Ed io che farò, Zefiro's aria for voice, two violins and continuo",
     "Ed io che farò, Zefiro's aria for voice, two violins and basso continuo"),  # Alessandro Stradella
    ('Egyptischer March, Op 335',
     'Egyptian March, Op.335'),  # Johann Strauss II
    ('Elegy in D flat, Op 23 (encore)',
     'Elegy (Op 23) arr. for piano trio'),  # Josef Suk
    ('En ny himmel och en ny jord for a capella chorus',
     'En ny himmel och en ny jord (A New Heaven and a New Earth) for a capella chorus'),  # Sven-David Sandström
    ('En ny himmel och en ny jord for a cappella chorus',
     'En ny himmel och en ny jord (A New Heaven and a New Earth) for a capella chorus'),  # Sven-David Sandström
    ("Excerpts from 'Livre de Guitarre'",
     "Excerpts from 'Livre de Guitare'"),  # Robert de Visée
    ("Excerpts from 'Livre de Guittare'",
     "Excerpts from 'Livre de Guitare'"),  # Robert de Visée
    ('Excerpts from Trios de la chambre du roi simphonie',
     'Excerpts from Trios de la Chambre du Roi'),  # Jean-Baptiste Lully
    ('Trios de la Chambre du Roi Simphonie - Excerpts',
     'Excerpts from Trios de la Chambre du Roi'),  # Jean-Baptiste Lully
    ("Excerpts of Ballet music from 'A Hut out of the Village' - 'Gypsy Dance' & 'Kolomyika' (Ukrainian Dance)",
     'Excerpts of Ballet music from "A Hut out of the Village"'),  # Zygmunt Noskowski
    ('Exulta satis - Offertorium for countertenor, tenor, two violins, viola and basso continuo',
     'Exsulta satis - Offertorium for countertenor, tenor, two violins, viola and basso continuo'),  # Johann Caspar Kerll
    ('Fantaisie et variations brillantes sur 2 airs favoris connus, Op.30',
     'Fantaisie et variations brillantes sur 2 airs favoris connus for guitar (Op.30) in E minor'),  # Fernando Sor
    ('Fantasia sul un linguaggio perduto for string instruments',
     'Fantasia sul linguaggio perduto for string instruments'),  # Marjan Mozetich
    ("First movement from 'Rock Symphony'",
     "First Movement (Allegretto), from 'Rock Symphony'"),  # Imants Kalnins
    ("Five Songs: Auch kleine Dinge, from 'Italienisches Liederbuch'; Gesang Weylas, no. 46 from 'de Mörike Lieder'; Nachtzauber, from 'Eichendorff-Lieder'; Mignon IV: Kennst du das Land, no. 9, from 'Goethe Lieder'; Die Zigeunerin, from 'Eichendorff-Lieder'",
     'Five Songs: Auch kleine Dinge (Italienisches Liederbuch); Gesang Weylas (de Mörike Lieder); Nachtzauber (Eichendorff-Lieder); Mignon IV: Kennst du das Land (Goethe Lieder); Die Zigeunerin (Eichendorff-Lieder)'),  # Hugo Wolf
    ('Galathea; Mahnung (Warning) - from Brettl-Lieder (Cabaret Songs)',
     'Galathea & Mahnung - from Brettl-Lieder (Cabaret Songs) (Galathea & Warning)'),  # Arnold Schoenberg
    ('Grande Sonata in G minor, Op.3',
     'Grande Sonata for piano in G minor, Op 3'),  # Ludwig Schuncke
    ("Improvisation on 'Somewhere over the Rainbow' by Harold Arlen",
     "Improvisation on 'Somewhere over the Rainbow'"),  # Harold Arlen
    ("Improvisations on 'Toccata'; 'La Spagna'; H. Butler's Theme; 'Passamezzo antico'; 'Ciaccona'",
     "Improvisations on 'Toccata'; 'La Spagna'; H. Butler's Theme; 'Passamezzo antico'"),  # Pierre Regnault Sandrin
    ('Mellanspel ur Sången (Interlude from the cantata: The Song)',
     'Interlude from "Sången" (The Song)'),  # Wilhelm Stenhammar
    ('Intraden und Tänze - from Conviviorum Deliciae, Nuremburg 1608',
     'Intraden und Tanze - from Conviviorum Deliciae'),  # Christoph Demantius
    ('It was a lover and his lasse (London, 1600)',
     'It was a lover and his lasse'),  # Thomas Morley
    ('Jolly Soldier: An American Independence Song taken from the Social Harp (1855)',
     'Jolly Soldier (An American Independence song taken from the Social Harp, 1855)'),  # Edward R. White
    ("Rêve angélique, Op.10 No.22 ('Kamennoi Ostrov', 24 Musical Portraits)",
     'Kamennoi Ostrov [Portraits], Op 10 no 22'),  # Anton Rubinstein
    ('Kantate No. 2 Ad genua - Ad ubera prtabimini',
     'Kantate No. 2 Ad genua - Ad ubera portabimini'),  # Dietrich Buxtehude
    ('Kyrie And Gloria From Missa Si Deus pro nobis à16',
     'Kyrie And Gloria From Missa Si Deus pro nobis à 16'),  # Orazio Benevoli
    ('Pantomime-Ballet: La Captive - Suite from Act I (compiled by Frits Celis)',
     'La Captive: Suite from Act I (Ballet-Pantomime compilation by Frits Celis)'),  # Paul Gilson
    ("La Noce Champetre ou l'Himen Pastoral - from Pieces pour la Muzette, Paris",
     "La Noce Champetre ou l'Himen Pastoral - from Pieces pour la Muzette"),  # Jean Hotteterre
    ('La Touriére from Concerto comique No.18',
     'La Tourière from Concerto Comique XVlll'),  # Michael Corette
    ('Laudate pueri - psalm',
     'Laudate pueri'),  # Chiara Margarita Cozzolani
    ('Pièces de luth in F minor',
     'Lute pieces in F minor'),  # Jacques Gallot
    ('Lyrical Poem for small orchestra',
     'Lyric Poem for small orchestra'),  # Lodewijk Mortelmans
    ('Passages in Imitation of the Trumpet (Ayres & Pieces IV (1685)',
     "Passages in Imitation of the Trumpet; 5 Marches from Playford's New Tunes"),  # Nicola Matteis — retargeted 2026-07-09 to the recording-block canonical (was the 'Matteis:'-prefixed intermediate)
    ("Melody, 'Orfeo ed Euridice'",
     'Melody (Orfeo ed Eurydice)'),  # Christoph Willibald Gluck
    ("Missa sancta No.1 in E flat major, J.224, 'Freischutzmesse' for soli, chorus & orchestra",
     "Missa sancta No.1 in E flat major 'Freischützmesse' for soli, chorus & orchestra"),  # Carl Maria von Weber
    ("Missa sancta No.1 in E flat major, J224, 'Freischützmesse', for soloists, chorus & orchestra",
     "Missa sancta No.1 in E flat major 'Freischützmesse' for soli, chorus & orchestra"),  # Carl Maria von Weber
    ("Morning Hymn from Elverskud (The Elf King's Daughter), Op 30",
     "Morning Hymn from Elverskud (The Elf King's Daughter)"),  # Niels Wilhelm Gade
    ("Morning Hymn from The Elf King's Daughter",
     "Morning Hymn from Elverskud (The Elf King's Daughter)"),  # Niels Wilhelm Gade
    # (Re-pointed 2026-07-16: the old target became a variant itself in the
    # Paganini sweep below -- both now go to the final canonical.)
    ('Moses Fantasy for cello and piano (Bravura variations on one chord from a Rossini theme)',
     'Moses fantaisie (after Rossini) for cello and piano'),  # Niccolo Paganini
    ('My River Runs To Thee',
     'My River Runs To'),  # Arturs Maskats
    ('Mzeo tibatvisa (June Sun)',
     'Mzeo Tibatvis (June Sun)'),  # Otar Taktakishvili
    ('O Lord, make thy servant Elizabeth – for 6 voices',
     'O Lord, make thy servant Elizabeth'),  # William Byrd
    ('O quam bonus es - motet for 2 voices (Si Lodano le Piaghe di Christo e le Mammelle Della Madonna)',
     'O quam bonus es - motet for 2 voices (Si Lodano le Piaghe di Christo & le Mamelle Della Madonna)'),  # Chiara Margarita Cozzolani
    ("Oce náš hlapca jerneja [The Bailiff Yerney's Prayer]",
     "Oce náš hlapca jerneja (Bailif Yerney's Prayer)"),  # Karol Pahor
    ('Suite for orchestra (BeRI 6) in D minor',
     'Orchestral Suite in D minor, BeRI 6'),  # Johan Helmich Roman
    ("Overture from the opera 'Taras Bulba'",
     "Ouverture from the opera 'Taras Bulba'"),  # Mykola Lysenko
    ('Overture from The Wasps - Aristophanic suite (from incidental music)',
     'Overture to The Wasps - Aristophanic suite (from incidental music)'),  # Ralph Vaughan Williams
    ("Overture to Elverhøj (Elve's Hill)",
     'Overture to Elverhøj'),  # Friedrich Kuhlau
    ('Overture to Hermina im Venusberg (Hermania in the Cave of Venus)',
     "Overture to Hermina im Venusberg (Hermania in Venus' cave)"),  # Jan Levoslav Bella
    ('Partita for Violins in Sixth-Tone System (1936)',
     'Partita for Violin in a Sixth-tone System (1936)'),  # Július Kowalski
    # Pavane harmonica-arr. variants — target retargeted to the orchestral
    # canonical "Pavane for orchestra Op 50" (the most-aired form). The
    # `_strip_arrangement_tail` machinery already collapses the harmonica
    # scoring into the same work_title_key as the orchestral original.
    ('Pavane in F minor (Op.50) arr. for harmonica and orchestra',
     'Pavane for orchestra Op 50'),  # Gabriel Fauré
    ('Pavane, Op.50, arr. for harmonica and orchestra',
     'Pavane for orchestra Op 50'),  # Gabriel Fauré
    ('Two works: Pavane de Spaigne; La Spagnolletta',
     'Pavane de Spaigne; La Spagnolletta'),  # Michael Praetorius
    ('Piano Concerto in C major, Op 14',
     'Piano Concerto in C'),  # shared: Franciszek Lessel / Leroy Anderson
    ("Sonata for piano (Op.8 No.1) in C major, 'Sonate facile'",
     "Piano Sonata in C major,Op.8 No.1, 'Sonate facile'"),  # Carl Ludwig Lithander
    ('Suite in B flat major, Op 45',
     'Piano Suite in B flat major, Op 45'),  # Willy Hess
    ('Suite in B flat major, Op.45, for piano',
     'Piano Suite in B flat major, Op 45'),  # Willy Hess
    ("Prayer, from 'From Jewish Life'",
     'Prayer (From Jewish Life)'),  # Ernest Bloch
    ('Prima la Musica, Poì le Parole - Divertimento teatrale in one act',
     "Prima la Musica, Poì le Parole ('First the Music and then the Words') - Divertimento teatrale in one act"),  # Antonio Salieri
    ('Quartet in E flat for clarinet, bassoon, horn and piano',
     'Quartet in E flat for clarinet, basson, horn and piano'),  # Franz Berwald
    ("Quartet in F major for horn, oboe d'amore, violin and continuo, FWV N:F3",
     "Quartet in F for horn, oboe d'amore, violin and basso continuo FWV N:F3"),  # Johann Friedrich Fasch
    ('Rodolphe\'s aria ("Your tiny hand is frozen") from La Boheme, Act 1 (sung in Hungarian)',
     'Rodolfo\'s aria ("Your tiny hand is frozen") from \'La bohème\''),  # Giacomo Puccini
    ('Sanctus And Agnus Dei From Missa Si Deus pro nobis à16',
     'Sanctus And Agnus Dei From Missa Si Deus pro nobis à 16'),  # Orazio Benevoli
    ('Seemorgh - The Sunrise for Orchestra',
     'Seemorgh - The Sunrise'),  # Behzad Ranjbaran
    ('Serenata in vano, FS 68',
     'Serenata in vano'),  # Carl Nielsen
    ('Sinfonia no 14 in G',
     'Sinfonia No. 14 in G - excerpt'),  # Alessandro Scarlatti
    ('Sinfonia, Op.1 No.4',
     'Sinfonia in E flat, Op.1 No.4'),  # Johann Gabriel Meder
    ('Sinphonia No.4 (Op.1)',
     'Sinfonia in E flat, Op.1 No.4'),  # Johann Gabriel Meder
    ('You Grey Horse',
     'Siwy koniu (You Grey Horse)'),  # Stanislaw Niewiadomski
    ("Sonata 1.x.1905 for piano in E flat minor, 'Zulice'",
     'Sonata 1.x.1905 for piano in E flat minor'),  # Leos Janacek
    ('Sonata No 11 for cornett, violin and continuo',
     'Sonata No 11 for cornet, violin and continuo'),  # Giovanni Battista Fontana
    ('Sonata for 3 recorders or flutes in C minor, Op 1 no 4',
     'Sonata No 7 for 3 flutes Op 1 No 4'),  # Johann Mattheson
    ('Sonata in C minor, Op 1 no 4',
     'Sonata No 7 for 3 flutes Op 1 No 4'),  # Johann Mattheson
    ('Sonata for oboe, bassoon and basso continuo in C minor, WD.695',
     'Sonata for oboe, bassoon and basso continuo in C minor, WD. 695'),  # Giovanni Benedetto Platti
    ("Violin Sonata in D major, Op 8 No 2, from 'X Sonate' (Amsterdam, 1744)",
     "Sonata for violin and continuo (Op.8 No.2) in D major, from 'X Sonate'"),  # Pietro Antonio Locatelli
    ('Sonatina No.1 in G - from Six Sonatines, Op.8',
     'Sonatina I in G - from Six Sonatines, Op 8'),  # Collizi / Kauchlitz, Johann Andrea
    ('Sonatina in G, Op 8 No 1',
     'Sonatina I in G - from Six Sonatines, Op 8'),  # Collizi / Kauchlitz, Johann Andrea
    ('Violin Sonatina in A flat',
     'Sonatina for Violin and Piano in A flat'),  # Erik Gustaf Geijer
    ('Suite No 1 in G major, Op 15',
     'Suite No 1 in F major for two pianos, Op 15'),  # Anton Stepanovich Arensky
    ("Wind music from 'A Midsummer Night's Dream', Op.61",
     "Suite from 'A Midsummer Night's Dream', Op.61"),  # Felix Mendelssohn
    ('Symphonie à grand orchestre de l\'opéra Cora (Overture to "Cora and Alonzo")',
     "Symphonie à grand orchestre de l'opera Cora"),  # Johann Gottlieb Naumann
    ('Varen kom en valborgsnatt (The spring came on a Walpurgis night)',
     'The Spring Came on a Walpurgis Night'),  # Wilhelm Peterson-Berger
    ('Three pieces for clarinet',
     'Three Pieces for Clarinet and Piano'),  # Clement Calder
    ('Three Songs with texts by JPContamine de La Tour',
     'Three melodies with texts by J.P.Contamine de La Tour'),  # Erik Satie
    ('Three Songs: Die stille Stadt; Licht in der Nacht; Bei dir ist es Traut',
     "Three Songs: Die stille Stadt, from 'Vier Lieder'; Licht in der Nacht, from 'Vier Lieder'; Bei dir ist es Traut, from 'Fünf Lieder'"),  # Alma Mahler
    # (Re-pointed 2026-07-16: the old bare-form target became a variant
    # itself in the Delius pass below -- both now go to the final canonical.)
    ('To be Sung of a Summer Night on the Water (RT.4.5)',
     'To be sung of a summer night on the water for chorus'),  # Frederick Delius
    ("Toccatina from No.1 in D major from 'Fasciculus Musicus'",
     'Toccatina from No 1 in D (Toccatina'),  # Elias Brönnemüller
    ('Traces of Magic (Octet for clarinet, bassoon, horn, string quartet & double bass)',
     'Traces of Magic (Octet for clarinet, bassoon, horn, string qtet & double bass)'),  # David Philip Hefti
    ("Tre madrigali di Torquato Tasso, Op.13: A Virgilio (To Virgil); All' aurora (To the Dawn); Non e questo un morire (This is Not to Die)",
     "Tre madrigal di Torquato Tasso (Op.13): A Virgilio (To Virgil); All' Aurora (To the Dawn); Non e questo un morire (This is not to die)"),  # Bernhard Lewkovitch
    ("Two Love Songs: The Passionate Shepherd to His Love (Text Christopher Marlowe); The Nymph's Reply to the Shepherd (Text Sir Walter Raleigh)",
     "Two Love Songs: 1.The Passionate Shepherd to His Love (Text Christopher Marlowe); 2.The Nymph's Reply to the Shepherd (Text Sir Walter Raleigh)"),  # Ruth Watson Henderson
    ('Two psalm-tunes: Kittery (1786) & Cobham (1794)',
     'Two Psalm-tunes: Kittery (1786); Cobham (1794)'),  # William Billings
    ("Una notte in Ellade (sull'Acropoli), orchestral notturno, Op.31",
     "Una notte in Ellade (sull'Acropoli), orchestral nocturne, Op.31"),  # Blagoje Bersa
    ('Variations on the old Swedish air Och liten Karin tjente, Op 91',
     "Variations on the old Swedish air 'Och liten Karin tjente' in E minor, Op.91"),  # Friedrich Kuhlau
    ('Weihnacht in der uralten Marienkirche zu Krakau. Fantasie Felix Nowowiejski',
     'Weihnacht in der uralten Marienkirche zu Krakau'),  # Felix Nowowiejski
    ("When Mary thro' the garden went, Op 127 No 3",
     "When Mary thro' the garden went (from 8 Partsongs, Op 127 no 3)"),  # Charles Villiers Stanford

    # --- Arvo Pärt — title variants the token sort can't reach ---
    # Cantus: the dedication as the Latin "in memoriam" vs English "in
    # Memory of".
    ("Cantus in Memory of Benjamin Britten",
     "Cantus in memoriam Benjamin Britten"),  # Arvo Pärt
    # A "for chorus" scoring tag dropped.
    ("Magnificat for chorus", "Magnificat"),  # shared: Arvo Pärt / Ruth Watson Henderson
    ("The Woman with the Alabaster box for chorus",
     "The Woman with the Alabaster Box"),  # Arvo Pärt
    # Bogoróditse Djévo — four BBC transliterations of one work
    # (devo/djevo/dyevo, ± "Ráduisya"/"Ave Maria").
    ("Bogoroditse devo",                  'Bogoróditse Dévo, ráduisya - from All-Night Vigil (Op.37)'),  # shared: Sergey Rachmaninov / Arvo Pärt
    ("Bogoróditse Djevo (Ave Maria)",     'Bogoróditse Dévo, ráduisya - from All-Night Vigil (Op.37)'),  # shared: Sergey Rachmaninov / Arvo Pärt
    ("Bogoróditse Dyévo Ráduisya",        'Bogoróditse Dévo, ráduisya - from All-Night Vigil (Op.37)'),  # shared: Sergey Rachmaninov / Arvo Pärt
    # Passio: the short title vs the full Latin.
    ("Passio", "Passio Domini nostri Jesu Christi secundam Joannem"),  # Arvo Pärt
    # Zwei Beter: a parenthetical English gloss dropped.
    ("Zwei Beter (Two Prayers)", "Zwei Beter"),  # Arvo Pärt

    # --- 2026-05-20 multi-play harvest: high-airing spelling-only merges
    # surfaced by ttn_rebroadcast --multiplay, grouped by work. Each maps a
    # work_title_key the token-sort path leaves distinct (a "Strings" vs
    # "string orchestra" wording, a "for piano" suffix, a dropped opus) onto
    # the dominant spelling of the same work. Arrangement variants and
    # excerpt/movement labellings were deliberately excluded. ---

    # Elgar: Serenade for Strings in E minor, Op 20
    ("Serenade for Strings Op 20",                     "Serenade for Strings in E minor, Op 20"),  # Edward Elgar
    ("Serenade for string orchestra in E minor, Op 20", "Serenade for Strings in E minor, Op 20"),  # Edward Elgar
    ("Serenade in E minor for string orchestra",       "Serenade for Strings in E minor, Op 20"),  # Edward Elgar

    # Vaughan Williams: Fantasia on a Theme by Thomas Tallis (by ↔ of,
    # ± "for double string orchestra")
    ("Fantasia on a theme by Thomas Tallis for double string orchestra", "Fantasia on a theme by Thomas Tallis"),  # Ralph Vaughan Williams
    ("Fantasia on a theme of Thomas Tallis for double string orchestra", "Fantasia on a theme by Thomas Tallis"),  # Ralph Vaughan Williams
    ("Fantasia on a theme of Thomas Tallis",           "Fantasia on a theme by Thomas Tallis"),  # Ralph Vaughan Williams

    # Chopin: 24 Preludes, Op 28 (whole set only — the "nos 11-15" excerpt
    # is a different work and is NOT folded here)

    # Chopin: Ballade No 1 in G minor, Op 23
    ("Ballade No.1 (Op.23)",                           "Ballade No 1 in G minor, Op 23"),  # Fryderyk Chopin

    # Weber: Clarinet Quintet in B flat major, Op 34 (J.182) — Quintet ↔
    # Clarinet Quintet, ± J-number/year
    ("Quintet in B flat major Op.34 for clarinet and strings (J.182)", "Clarinet Quintet in B flat major, Op 34"),  # Carl Maria von Weber
    ("Quintet for Clarinet and Strings in B flat J.182 Op 34", "Clarinet Quintet in B flat major, Op 34"),  # Carl Maria von Weber
    ("Clarinet Quintet (Op.34) in B flat major (J.182) (1815)", "Clarinet Quintet in B flat major, Op 34"),  # Carl Maria von Weber

    # Fauré: Nocturne No 1 in E flat minor, Op 33 No 1
    ("Nocturne for piano in E flat minor, Op 33 no 1", "Nocturne No 1 in E flat minor, Op 33 No 1"),  # Gabriel Fauré
    ("Nocturne in E flat minor Op 33 No 1",            "Nocturne No 1 in E flat minor, Op 33 No 1"),  # Gabriel Fauré

    # Debussy: String Quartet in G minor, Op 10 (he wrote only one quartet,
    # so the bare "in G minor" is unambiguous)
    ("String Quartet in G minor",                      "String Quartet in G minor, Op 10"),  # Claude Debussy

    # Sibelius: Finlandia, Op 26 (orchestral original; the "hymn tune arr.
    # for chamber choir" is a separate work_key, not folded)
    ("Finlandia Op.26 for orchestra",                  "Finlandia, Op 26"),  # Jean Sibelius

    # Grieg: Holberg Suite, Op 40 (string-orchestra version)
    ("Holberg suite Op 40 vers. for string orchestra", "Holberg Suite, Op 40"),  # Edvard Grieg
    ("Holberg Suite Op 40 for string orchestra",       "Holberg Suite, Op 40"),  # Edvard Grieg

    # Grieg: Norwegian Dance No 1, Op 35 (Allegro marcato is No 1's marking)
    ("Norwegian Dance No 1 Op 35 for piano duet",      "Norwegian Dance (Allegro marcato) (Op.35 No.1)"),  # Edvard Grieg
    ("Norwegian Dance, Op 35 No 1",                    "Norwegian Dance (Allegro marcato) (Op.35 No.1)"),  # Edvard Grieg
    ("Norwegian Dance No.1 for piano duet",            "Norwegian Dance (Allegro marcato) (Op.35 No.1)"),  # Edvard Grieg

    # Debussy: Cello Sonata in D minor (Cello Sonata ↔ Sonata for cello and piano)

    # Ravel: Piano Trio in A minor (Piano Trio ↔ Trio for piano and strings)

    # --- Spelling/transliteration variants from the 2026-05-25 variant audit ---

    # Rimsky-Korsakov: Scheherazade, Op 35 — consolidate spelling
    # (Scheherazade/Sheherazade/Scheherezade), the "after 1001 Nights"
    # subtitle, and bare-vs-"symphonic suite" phrasings into one work. The
    # excerpt "Arabian Song, from 'Scheherezade'" is deliberately NOT mapped
    # (it carries a 'from' locator — a derived piece, not the suite).
    ("Scheherazade - symphonic suite after 1001 Nights, Op 35", "Scheherazade - symphonic suite, Op.35"),  # Nikolai Rimsky-Korsakov
    ("Sheherazade - symphonic suite Op.35",            "Scheherazade - symphonic suite, Op.35"),  # Nikolai Rimsky-Korsakov
    ("Scheherezade - symphonic suite, Op.35",          "Scheherazade - symphonic suite, Op.35"),  # Nikolai Rimsky-Korsakov
    ("Sheherazade, Op 35",                             "Scheherazade - symphonic suite, Op.35"),  # Nikolai Rimsky-Korsakov
    ("Sheherazade",                                    "Scheherazade - symphonic suite, Op.35"),  # Nikolai Rimsky-Korsakov
    ("Scheherazade, Op 35",                            "Scheherazade - symphonic suite, Op.35"),  # Nikolai Rimsky-Korsakov

    # Schubert: Auf dem Wasser zu singen — D744 is a transposition typo for
    # the correct Deutsch number D.774 (catalogue-path key; the only tracks
    # keyed D744 are this song). Folds the typo'd airings into the original.
    ("Auf dem wasser zu singen, D744",                 "Auf dem Wasser zu singen, D.774"),  # Franz Schubert

    # Doppler: Fantaisie pastorale hongroise, Op 26 — Fantaisie (Fr) vs the
    # Fantasie/pastoral misspellings. (The "version for flute & piano" stays
    # separate, per the bare-scoring policy.)
    ("Fantasie Pastorale Hongroise, Op 26",            "Fantaisie pastorale hongroise, Op 26"),  # Franz Doppler
    ("Fantasie pastoral hongroise (Op.26)",            "Fantaisie pastorale hongroise, Op 26"),  # Franz Doppler

    # Debussy: Prélude à l'après-midi d'un faune — "d'une faune" typo (faune
    # is masculine). The hyphen/apostrophe fold already unifies the rest.
    ("Prélude à l'àpres midi d'une faune",             "Prélude à l'après-midi d'un faune"),  # Claude Debussy
    # ... and the dropped-final-e "faun" spelling (1x, 2012).
    ("Prelude a l'apres-midi d'un faun",               "Prélude à l'après-midi d'un faune"),  # Claude Debussy

    # --- Catalogue-path phantom-ordering splits (2026-05-26 audit) -----------
    # Same catalogue ref, but the BBC inconsistently includes the within-form
    # ordering number ("Cello Suite No 3, BWV 1009" vs "Suite for solo cello
    # in C, BWV 1009"). The catalogue path includes all digits in the key —
    # essential for set-catalogue siblings (D.899 impromptus, K.620 arias) —
    # so these variants split. Each alias merges one variant key into the main
    # work_key. Variant keys checked corpus-wide for exclusivity (no
    # cross-pollution into other works).

    # Bach BWV 1056 — Harpsichord/Keyboard Concerto No 5 in F minor. Both the
    # bare-form keyboard variant AND the G-minor oboe reconstruction (same
    # work in two scorings) fold into the most-aired form.
    ("Keyboard Concerto in F minor, BWV.1056",
     "Harpsichord Concerto no 5 in F minor, BWV.1056"),  # Johann Sebastian Bach
    ("Concerto for oboe and strings in G minor (reconstructed from BWV.1056)",
     "Harpsichord Concerto no 5 in F minor, BWV.1056"),  # Johann Sebastian Bach

    # Bach BWV 1068 — Orchestral Suite No 3 in D. The bare "Air, Overture in
    # D" form (Air on the G String) lacks the suite-ordering "3".
    ("Air, Overture in D major, BWV1068",
     "Orchestral Suite No 3 in D major, BWV 1068"),  # Johann Sebastian Bach

    # Schubert D.940 — Fantasia in F minor for 4 hands. The "(originally for
    # 4 hands)" parenthetical picks up a phantom "4" digit; the more common
    # Mozart K.298 — Flute Quartet No 4 in A. Bare-form lacks the "no 4".
    ("Quartet for flute and strings (K 298) in A major",
     "Flute Quartet no 4 in A major, K 298"),  # Wolfgang Amadeus Mozart

    # --- Mozart quartets & quintets audit (2026-05-28) ----------------------
    # Numbered-vs-unnumbered split: the bare form ("Quartet in G major
    # (K.387)") takes the catalogue path (§k387|387|g), while the numbered
    # form carries the ordinal into the key (§k387|14,387|g), so they don't
    # collapse. The K number pins identity; "no.N" is a redundant ordinal.
    # Each numbered group verified pure whole-work (no excerpts). Bare form
    # is the most-aired in every case here.

    # K.387 — String Quartet No 14 in G ('Spring').
    ("String Quartet no.14 in G major, K.387",
     "Quartet in G major (K.387)"),  # Wolfgang Amadeus Mozart
    # K.465 — String Quartet No 19 in C ('Dissonance'). Two ordinal variants
    # (one keyless) fold in.
    ("String Quartet no 19 in C major, K.465 'Dissonance'",
     'String Quartet in C major (K.465) "Dissonance"'),  # Wolfgang Amadeus Mozart
    ("String Quartet no 19, K.465 \"Dissonance\"",
     'String Quartet in C major (K.465) "Dissonance"'),  # Wolfgang Amadeus Mozart
    # K.458 — String Quartet No 17 in B flat ('Hunt').
    ("String Quartet no 17 in B flat, K. 458 'Hunt'",
     "String Quartet in B flat major, K458, 'Hunt'"),  # Wolfgang Amadeus Mozart
    # K.589 — String Quartet No 22 in B flat ('Prussian').
    ("String Quartet no.22 in B flat major, K. 589 'Prussian'",
     "Quartet for strings (K.589) in B flat major 'Prussian'"),  # Wolfgang Amadeus Mozart
    # K.493 — Piano Quartet No 2 in E flat.
    ("Piano Quartet no 2 in E flat major, K. 493",
     "Piano Quartet in E flat major, K493"),  # Wolfgang Amadeus Mozart
    # K.515 — String Quintet No 3 in C.
    ("String Quintet no.3 in C major, K.515",
     "String Quintet in C major, K515"),  # Wolfgang Amadeus Mozart
    # K.516 — String Quintet No 4 in G minor. Now foldable: the movement-
    # marker gate (2026-05-29) split the "Adagio … from" excerpt off to
    # §k516|adagio, so the no.4 whole-work group is clean.
    ("String Quintet no.4 in G minor, K.516",
     "Quintet for strings in G minor (K.516)"),  # Wolfgang Amadeus Mozart
    # K.576 — Piano Sonata No 18 in D. Now foldable: the "Adagio … from"
    # excerpt split off to §k576|adagio via the movement-marker gate.
    ("Piano Sonata No 18 In D major, K576",
     "Piano Sonata in D major (K.576)"),  # Wolfgang Amadeus Mozart
    # K.331 Rondo alla Turca — the movement-marker gate keys the Rondo
    # excerpt §k331|rondo (its own famous-movement group, distinct from the
    # whole sonata). The "Alla turca, from …" phrasings lead with "Alla"
    # (not a movement name) so they escape the gate — fold them into the
    # §k331|rondo canonical. (The whole sonata and the Fazıl Say fantasy
    # stay separate.)
    ("Alla turca, from 'Piano Sonata No. 11 in A, K. 331'",
     "Rondo alla turca, from Piano Sonata no.11 in A major, K.331"),  # Wolfgang Amadeus Mozart
    ("Alla turca, from Piano Sonata no.11 in A major, K.331",
     "Rondo alla turca, from Piano Sonata no.11 in A major, K.331"),  # Wolfgang Amadeus Mozart

    # --- ttn_duplicates straggler harvest (2026-05-30) ----------------------
    # Genuine same-work folds surfaced by the post-alias duplicate detector
    # (high-Jaccard pairs): redundant scoring annotation, word-order, or an
    # added/dropped catalogue ref. Alt-scorings, excerpts, and whole-vs-
    # subset noise from that run are deliberately excluded.

    # Wolf — Italian Serenade (string quartet IS its scoring; key annotation).
    ("Italian Serenade for string quartet", "Italian Serenade"),  # Hugo Wolf
    ("Italian Serenade in G major", "Italian Serenade"),  # Hugo Wolf
    # Debussy — L'Isle joyeuse (piano work) + Danse sacrée et danse profane
    # (harp+strings is its scoring; L.103 catalogue form).
    ("Danse sacrée et danse profane",
     "Danse sacree et danse profane for harp and strings"),  # Claude Debussy
    # Dvořák — Slavonic Dance Op.72 no.2 (key present/absent); American Quartet.
    ("Slavonic Dance Op.72 No.2", "Slavonic Dance in E minor, Op.72 no.2"),  # Antonin Dvorak
    ("American Quartet no 12 in F major, Op 96",
     "String Quartet No 12 in F Major 'American' Op 96"),  # Antonin Dvorak
    # Brahms — Handel Variations Op 24 (the "by Handel" form, no "G F");
    # Symphony 3 (key); Double Concerto (scoring word-order).
    ("25 Variations and Fugue on a Theme by Handel, Op 24",
     "25 Variations and fugue on a theme by G F Handel, Op 24"),  # Johannes Brahms
    ("Symphony no 3 Op 90", "Symphony no 3 in F major, Op 90"),  # Johannes Brahms
    ("Double Concerto in A minor, Op.102, for violin, cello and orchestra",
     "Double Concerto in A minor for Violin and Cello, Op 102"),  # Johannes Brahms
    # Elgar — Enigma Variations Op 36 ("for orchestra" annotation).
    ("Variations on an original theme (Enigma) Op 36",
     "Variations on an original theme ('Enigma') Op.36 for orchestra"),  # Edward Elgar
    # Chopin — "for piano" annotation / word-order on Op-numbered works.
    ("Sonata No.3 in B minor (Op.58)",
     "Piano Sonata no 3 in B minor, Op 58"),  # Fryderyk Chopin
    # Schumann — Cello Concerto Op 129 (word-order).
    # Clara Schumann — Variations Op 20 (scoring annotation).
    # Berlioz — Le Carnaval romain Op 9 ("overture" added/dropped).
    ("Le Carnaval Romain, Op 9", 'Le Carnaval romain - overture (Op.9)'),  # Hector Berlioz
    # Vaughan Williams — The Wasps overture ("Overture to" added/dropped).
    ("The Wasps - Aristophanic suite (from incidental music) (1909)",
     "Overture to The Wasps - Aristophanic suite (from incidental music)"),  # Ralph Vaughan Williams
    # Korngold — Violin Concerto Op 35 (word-order).
    # Beethoven — Piano Sonata no 18 Op 31/3 (word-order + "for piano").
    # Nielsen — Wind Quintet Op 43 (word-order).
    # Ravel — Alborada del gracioso (the standalone vs 'from Miroirs' framing
    # both name the same piece).
    ("Alborada del gracioso, from 'Miroirs'",
     "Alborada del gracioso  'Miroirs' (1905)"),  # Maurice Ravel
    # Farkas — 5 Ancient Hungarian Dances (wind-quintet scoring annotation).
    ("5 Ancient Hungarian Dances",
     "5 Ancient Hungarian Dances for wind quintet"),  # Ferenc Farkas
    # K.285 — Flute Quartet No 1 in D. (Bare D-major group already carries a
    # couple of "Rondo" movement excerpts — pre-existing, not introduced by
    # this fold; the no-1 whole-work form joins them.)
    ("Flute Quartet No.1 in D major, K.285",
     "Flute Quartet in D major, K.285"),  # Wolfgang Amadeus Mozart
    # K.456 — BBC source typo: the "String Quartet no.19 ... 'Dissonance'"
    # airing is mislabelled K.456 (which is the B-flat Piano Concerto No 18,
    # correctly tagged elsewhere in the same cluster). The title text names
    # the Dissonance Quartet unambiguously, so fold to its real catalogue
    # number K.465 rather than preserve the wrong ref.
    ("String Quartet no.19 in C major K.456, 'Dissonance'",
     'String Quartet in C major (K.465) "Dissonance"'),  # Wolfgang Amadeus Mozart

    # --- ttn_duplicates harvest, 2nd pass (2026-05-30, siblings guard) -------
    # A second post-alias sweep after the precision pass (bare-number boosts
    # dropped, whole-vs-subset and token-sort siblings suppressed). These are
    # genuine same-work folds: an op number / catalogue ref / accent / nick-
    # name added or dropped, a translated or word-order variant, a redundant
    # scoring annotation matching the work's sole scoring, or an obvious typo.
    # Alt-scorings, arrangements to different forces, movement excerpts, and
    # distinct works of one set are deliberately left split.
    # Beethoven
    ("Coriolan Overture", "Coriolan Overture, Op 62"),  # Ludwig van Beethoven
    ("Piano Concerto no 3 in C minor", "Piano Concerto no 3 in C minor, Op 37"),  # Ludwig van Beethoven
    ("Concerto for piano and orchestra no. 3 in C minor",
     "Piano Concerto no 3 in C minor, Op 37"),  # Ludwig van Beethoven
    ("String Quartet in C sharp minor, Op 131",
     "String Quartet no.14 (Op.131) in C sharp minor"),  # Ludwig van Beethoven
    # Debussy
    ("L' Isle joyeuse", "L'Isle joyeuse"),  # Claude Debussy
    # Mendelssohn (Felix)
    ("The Hebrides - overture", "The Hebrides, Op 26"),  # Felix Mendelssohn
    ("Symphony No.3 in A minor (Op.56), 'Scottish' (Andante con moto - "
     "allegro un poco; Vivace non troppo; Adagio; Allegro un poco)",
     "Symphony no 3 in A minor, Op 56 'Scottish'"),  # Felix Mendelssohn
    # Sibelius
    ("Finlandia", "Finlandia, Op 26"),  # Jean Sibelius
    ("Symphony no 5 in E flat major", "Symphony no 5 in E flat major, Op 82"),  # Jean Sibelius
    # Elgar
    ("Enigma Variations, op. 36",
     "Variations on an original theme ('Enigma') Op.36 for orchestra"),  # Edward Elgar
    # Suk
    ("Elegy (Under the impression of Zeyer's Vyšehrad), Op 23, arranged "
     "for piano trio", "Elegy Op 23 arr. for piano trio"),  # Josef Suk
    # Saint-Saëns
    ("Havanaise", "Havanaise, Op 83"),  # Camille Saint-Saëns
    ("Bassoon Sonata in G major", "Bassoon Sonata in G major, Op 168"),  # Camille Saint-Saëns
    ("Bassoon Sonata in G major,Op.168", "Bassoon Sonata in G major, Op 168"),  # Camille Saint-Saëns
    ("Danse Macabre", "Danse macabre, Op 40"),  # Camille Saint-Saëns
    # Berlioz
    ("Le Carnaval Romain - overture", 'Le Carnaval romain - overture (Op.9)'),  # Hector Berlioz
    ("Le Carnaval romain, op. 9, overture after 'Benvenuto Cellini'",
     'Le Carnaval romain - overture (Op.9)'),  # Hector Berlioz
    # Barber — the Adagio music exists in three DISTINCT works (Cerys consult,
    # 2026-06-15; see musicological-notes.txt): the standalone Adagio for Strings,
    # the choral Agnus Dei (re-texted → a new work), and the complete String
    # Quartet Op.11 (the Adagio is its 2nd movement; whole-vs-part stays split).
    # These folds only consolidate rephrasings WITHIN each of the three.
    ("Adagio for Strings", "Adagio for Strings, Op 11"),  # Samuel Barber
    ("Adagio for string orchestra", "Adagio for Strings, Op 11"),  # Samuel Barber
    ("Agnus Dei, Op 11", "Agnus Dei"),  # Samuel Barber
    ("Quartet for strings (Op.11) in B minor",
     "String Quartet no 1, Op 11"),  # Samuel Barber
    # (Tchaikovsky Rococo "original version" deliberately NOT folded: the
    # autograph original is musically distinct from the Fitzenhagen-edited
    # standard version — see test_tchaikovsky_rococo_original_version_stays_split.)
    # Chopin
    ("Ballade in A flat, Op 47", "Ballade no 3 in A flat major, Op 47"),  # Fryderyk Chopin
    ("Scherzo No.2 in B flat, Op.31", "Scherzo No 2 in B flat minor, Op 31"),  # Fryderyk Chopin
    ("Scherzo No 2 B flat minor, Op 31", "Scherzo No 2 in B flat minor, Op 31"),  # Fryderyk Chopin
    ("Sonata in B flat minor (Op.35)",
     "Piano Sonata no 2 in B flat minor, Op 35"),  # Fryderyk Chopin
    ("Piano Sonata No 2, Op 35", "Piano Sonata no 2 in B flat minor, Op 35"),  # Fryderyk Chopin
    ("Piano Sonata no 2 in B flat minor, Op 35 'Funeral March'",
     "Piano Sonata no 2 in B flat minor, Op 35"),  # Fryderyk Chopin
    ("Piano sonata no 2 in B flat minor, Op 35 'Marche funebre'",
     "Piano Sonata no 2 in B flat minor, Op 35"),  # Fryderyk Chopin
    # Smetana — Vltava (accent / parenthetical translation)
    ("Vltava (Moldau), from 'Má vlast' (My Homeland)",
     "Vltava (Moldau) - from 'Ma Vlast'"),  # Bedrich Smetana
    ("Vltava from Má vlast", "Vltava (Moldau) - from 'Ma Vlast'"),  # Bedrich Smetana
    ("Vltava from Má vlast - My Homeland", "Vltava (Moldau) - from 'Ma Vlast'"),  # Bedrich Smetana
    # Grieg
    ("String Quartet No 1 in G minor", "String Quartet no 1 in G minor, Op 27"),  # Edvard Grieg
    # Schubert — Great C major (D.944; trailing semicolon variant)
    ('Symphony No. 9 in C major, "Great";',
     'Symphony no 9 in C major, D.944 "Great"'),  # Franz Schubert
    # Clara Schumann
    ("Variations on a theme by Robert Schumann for piano in F sharp minor, "
     "Op 20",
     "Variations on a theme of Robert Schumann for piano in F sharp minor, "
     "Op 20"),  # Clara Schumann
    ("Variations on a Theme of Robert Schumann, Op 20",
     "Variations on a theme of Robert Schumann for piano in F sharp minor, "
     "Op 20"),  # Clara Schumann
    ("Quatre pièces fugitives, Op 15", "4 Pieces fugitives for piano, Op 15"),  # Clara Schumann
    # Vaughan Williams — The Wasps overture: ALL phrasings fold to one canonical
    # (2026-06-11). The segment/recording data overturned the earlier tracks-only
    # split that held "Overture from The Wasps - An Aristophanic suite" apart:
    # all 5 recordings are the ~9-min Overture (9:03-10:30), there is NO full
    # Aristophanic Suite and no separate movement in 16 years of data, so the
    # from/to/An wording carries no musical distinction. (Retired the protected
    # multiplay split and its test_live_vw_wasps_cross_recording_residual.)
    ("The Wasps - Overture from the Incidental Music",
     "Overture to The Wasps - Aristophanic suite (from incidental music)"),  # Ralph Vaughan Williams
    ("Overture from The Wasps - An Aristophanic suite",
     "Overture to The Wasps - Aristophanic suite (from incidental music)"),  # Ralph Vaughan Williams
    ("Overture from The Wasps",
     "Overture to The Wasps - Aristophanic suite (from incidental music)"),  # Ralph Vaughan Williams
    ("The Wasps - Overture",
     "Overture to The Wasps - Aristophanic suite (from incidental music)"),  # Ralph Vaughan Williams
    ("Overture from The Wasps - Aristophanic suite",
     "Overture to The Wasps - Aristophanic suite (from incidental music)"),  # Ralph Vaughan Williams
    ("Overture to The Wasps - Aristophanic suite",
     "Overture to The Wasps - Aristophanic suite (from incidental music)"),  # Ralph Vaughan Williams
    ("Overture: The Wasps (incidental music 1909)",
     "Overture to The Wasps - Aristophanic suite (from incidental music)"),  # Ralph Vaughan Williams
    # segment-side phrasing (recording p08j59xb projects this title)
    ("The Wasps - Aristophanic suite (Overture)",
     "Overture to The Wasps - Aristophanic suite (from incidental music)"),  # Ralph Vaughan Williams
    # Dvořák
    ("Cello Concerto No.2 in B minor, Op 104",
     "Cello Concerto in B minor, Op 104"),  # Antonin Dvorak
    ("Piano Quintet in A major (B.155) (Op.81)",
     "Piano Quintet in A major, Op 81"),  # Antonin Dvorak
    ("Symphony No.9 in E minor Op 95 'From the New World' (Adagio - allegro "
     "molto; Largo; Molto vivace - poco sostenuto; Allegro con fuoco)",
     "Symphony no 9 in E minor, Op 95 'From the New World'"),  # Antonin Dvorak
    # Holst
    ("St Paul's Suite in C, op. 29/2", "St Paul's Suite, Op 29 no 2"),  # Gustav Holst
    # Prokofiev — Classical Symphony
    ("Symphony No.1 in D major, 'Classical'",
     "Symphony No 1 in D major, Op 25, 'Classical'"),  # Sergey Prokofiev
    # Brahms
    ("Symphony No.3 in F major", "Symphony no 3 in F major, Op 90"),  # Johannes Brahms
    ("Academic Festival Overture", "Academic Festival Overture, Op 80"),  # Johannes Brahms
    ("3 Songs for choru, Op 42", "3 Songs for chorus, Op 42"),  # Johannes Brahms
    # Handel — Water Music suite (HWV 350; the "No. 3" suite number)
    ("Water Music, Suite No. 3 in G, HWV 350",
     "Water Music: Suite in G major for 'flauto piccolo' HWV 350"),  # George Frideric Handel
    # Shostakovich
    # Schütz
    ("Magnificat anima mea Dominum SWV 468",
     "Magnificat anima mea Dominum, SWV468"),  # Heinrich Schütz
    # Fanny Mendelssohn
    ("Allegro moderato for piano, Op 8 no 1",
     "Allegro moderato (Song without words), Op 8 No 1 (1840)"),  # Fanny Mendelssohn
    # Purcell
    ('Rejoice in the Lord alway, Z 49 (Bell Anthem)',
     'Rejoice in the Lord alway (Z.49) "Bell Anthem"'),  # Henry Purcell
    # Pylkkänen
    ("Suite for oboe and strings,Op.32", "Suite for oboe and strings, Op 32"),  # Tauno Pylkkanen
    # Liszt — Hungarian Rhapsody No 2 (S.244/2 catalogue added)
    ("Hungarian Rhapsody No 2, S244/2",
     "Hungarian Rhapsody No 2 in C sharp minor"),  # Franz Liszt
    # Spohr
    ("Fantasie and variations on a theme of Danzi in B flat, Op 81",
     "Fantasia, Theme and Variations on a theme of Danzi in B flat Op.81"),  # Louis Spohr
    # Rimsky-Korsakov
    ("Capriccio espagnol", "Capriccio Espagnol, Op 34"),  # Nikolai Rimsky-Korsakov
    # Mahler — Symphony 4 (soprano finale; scoring annotation)
    ("Symphony No 4 in G major for soprano and orchestra",
     "Symphony No 4 in G major"),  # Gustav Mahler
    # Stenhammar
    ("Spring Night", "Varnatt (Spring Night)"),  # Wilhelm Stenhammar
    # Ibert — Trois Pièces Brèves (wind quintet IS its scoring)
    ("Trois Pieces Breves for wind quintet", "Trois Pieces Breves"),  # Jacques Ibert
    # Palestrina — Stabat Mater (8 voices IS its scoring)
    ("Stabat Mater for 8 voices", "Stabat Mater"),  # shared: Giovanni Pierluigi da Palestrina / Juan Crisostomo Arriaga
    # Wolf — the spurious-"Op 120" string-quartet phrasing (string quartet IS
    # the Italian Serenade's scoring; Wolf has no Op 120). Missed in the first
    # pass of this batch; the bare "...in G major" form was already folded.
    ("Italian Serenade in G major for string quartet, Op 120",
     "Italian Serenade"),  # Hugo Wolf
    # Fanny Mendelssohn — Allegro moderato, Op 8 No 1 (third & fourth phrasings).
    ("Allegro moderato (Op.8 No.1) (1840)",
     "Allegro moderato (Song without words), Op 8 No 1 (1840)"),  # Fanny Mendelssohn
    # Spohr — Danzi Fantasia Op 81: one work the BBC renders ~18 ways
    # (Fantasy/Fantasie/Fantasia, "Theme and"/"and", "Franz Danzi"/"Danzi",
    # "in B flat" present/absent, even a "B minor" typo). Fold the lot.
    ("Fantasy, Theme and Variations on a theme of Danzi in B flat (Op.81)",
     "Fantasia, Theme and Variations on a theme of Danzi in B flat Op.81"),  # Louis Spohr
    ("Fantasia and Variations on a theme by Franz Danzi in B flat Op 81",
     "Fantasia, Theme and Variations on a theme of Danzi in B flat Op.81"),  # Louis Spohr
    ("Fantasia and Variations on a theme of Franz Danzi in B flat major, Op.81",
     "Fantasia, Theme and Variations on a theme of Danzi in B flat Op.81"),  # Louis Spohr
    ("Fantasie and Variations on a Theme of Danzi (Op.81)",
     "Fantasia, Theme and Variations on a theme of Danzi in B flat Op.81"),  # Louis Spohr
    ("Fantasy, Theme and Variations a Theme of Danzi, Op 81",
     "Fantasia, Theme and Variations on a theme of Danzi in B flat Op.81"),  # Louis Spohr
    ("Fantasy, Theme and Variations a theme of Danzi in B minor (Op.81)",
     "Fantasia, Theme and Variations on a theme of Danzi in B flat Op.81"),  # Louis Spohr
    ("Fantasy, Theme and Variations on a Theme of Danzi (Op.81)",
     "Fantasia, Theme and Variations on a theme of Danzi in B flat Op.81"),  # Louis Spohr
    # More Op.81 stragglers surfaced 2026-06-13 by the display fix that stopped
    # collapsing these to a bare "Fantasy" (B-minor typo + "Bb" + on/no-on churn).
    ("Fantasie and variations on a theme of Danzi in B minor (Op.81)",
     "Fantasia, Theme and Variations on a theme of Danzi in B flat Op.81"),  # Louis Spohr
    ("Fantasy, Theme and Variations on a theme of Danzi in B minor (Op.81)",
     "Fantasia, Theme and Variations on a theme of Danzi in B flat Op.81"),  # Louis Spohr
    ("Fantasy, Theme and Variations a theme of Danzi in Bb (Op.81)",
     "Fantasia, Theme and Variations on a theme of Danzi in B flat Op.81"),  # Louis Spohr
    ("Fantasy, Theme and Variations a theme of Danzi in B flat (Op.81)",
     "Fantasia, Theme and Variations on a theme of Danzi in B flat Op.81"),  # Louis Spohr
    # Spohr — Harp Fantasia No 2 in C minor, Op 35: "Fantasia for harp" splits
    # off the dominant "Harp Fantasia" group on the stray "for" token (not in
    # _normalize_scoring's Sonata/Concerto vocab). The (vers. clarinet & string
    # quartet) Danzi arrangements above stay SPLIT — alt-scoring, per policy.
    ("Fantasia for harp no.2 (Op.35) in C minor",
     "Harp Fantasia No 2 in C minor, Op 35"),  # Louis Spohr
    ("Fantasia in C minor, Op 35, for harp",
     "Harp Fantasia No 2 in C minor, Op 35"),  # Louis Spohr

    # --- Catalogue-ref typos / incomplete refs (2026-05-30) -----------------
    # Surfaced auditing the different-ref §-key false-positive class in
    # ttn_duplicates: a handful of pairs there were one work under a mistyped
    # or truncated catalogue number, not two adjacent works. Folding them to
    # the correct ref both fixes the grouping and lets the new "distinct §-ref
    # = distinct work" detector guard stay clean.
    # Schubert — D66 is a typo for D667 (the Trout Quintet; no D66 Trout).
    ('Piano Quintet in A major, D66), (Trout)',
     'Piano Quintet in A major (D.667) "Trout"'),  # Franz Schubert
    # Bach — "BWV 1008o" carries a stray 'o' (Cello Suite No 2 is BWV 1008).
    ("Cello Suite No 2 in D minor, BWV 1008o",
     "Cello Suite no 2 in D minor, BWV 1008"),  # Johann Sebastian Bach
    # Telemann — Sonata Polonaise is TWV 42:a8; bare "TWV 42" / "(TWV.42: A
    # minor 8)" are incomplete renderings of the same work.
    ("Sonata Polonaise in A minor for violin, viola and continuo TWV 42",
     "Sonata Polonaise in A minor for violin, viola and continuo, TWV.42:a8"),  # Georg Philipp Telemann
    ("Sonata Polonaise in A minor for violin, viola and continuo "
     "(TWV.42: A minor 8)",
     "Sonata Polonaise in A minor for violin, viola and continuo, TWV.42:a8"),  # Georg Philipp Telemann
    # Telemann — the D-minor Musique de table quartet is TWV 43:d1; "TWV 42."
    # and "TWV 42:d1" are ref errors for the same (identically-titled) work.
    # Retargeted 2026-07-11 to the segment-canonical 'bc' spelling (the 14x
    # recording-anchored form) after the form-word excerpt guard (5d112ca)
    # moved this citation-titled family to the token-sort path.
    ("Quartet in D Minor for flutes and basso continuo from 'Musique de "
     "Table' TWV 42.",
     "Quartet in D Minor for flutes and bc from 'Musique de Table' "
     "TWV 43:d1"),  # Georg Philipp Telemann
    ("Quartet in D minor for flutes and basso continuo from 'Musique de "
     "Table', TWV 42:d1",
     "Quartet in D Minor for flutes and bc from 'Musique de Table' "
     "TWV 43:d1"),  # Georg Philipp Telemann
    ("Quartet in D minor for flutes and bass continuo from 'Musique de "
     "Table' TWV 43:d1",
     "Quartet in D Minor for flutes and bc from 'Musique de Table' "
     "TWV 43:d1"),  # Georg Philipp Telemann — the pre-retarget hub string
    ("Quartet in D minor for flutes and basso continuo from 'Musique de "
     "Table', TWV.42:d1",
     "Quartet in D Minor for flutes and bc from 'Musique de Table' "
     "TWV 43:d1"),  # Georg Philipp Telemann

    # --- Mozart audit, rest of catalogue (2026-05-29) -----------------------
    # Same numbered-vs-unnumbered / keyless / alt-Köchel / redundant-scoring
    # catalogue-path splits as the quartets batch, across the instrumental
    # and concert-aria repertoire. Each pair verified chain-safe and
    # composer-exclusive (or, for Ave verum, cross-composer-safe via
    # composer-scoped grouping). Excerpt-vs-whole splits, set-catalogue
    # siblings, and multi-work programme items are deliberately left split.

    # Symphonies / concertos / chamber: keyless or phantom-ordinal variants.
    ("Symphony No.35 (K. 385) 'Haffner'",
     "Symphony no 35 in D major, K.385, \"Haffner\""),  # Wolfgang Amadeus Mozart
    ("Piano Concerto in B flat major, K.595",
     "Piano Concerto no 27 in B flat major, K.595"),  # Wolfgang Amadeus Mozart
    ("Sinfonia Concertante (K.364)",
     "Sinfonia Concertante in E flat major, K364"),  # Wolfgang Amadeus Mozart
    ("Sinfonia concertante for oboe, clarinet, horn, bassoon and orchestra (K.297b)",
     "Sinfonia concertante in E flat major, K297b"),  # Wolfgang Amadeus Mozart
    ("Piano Sonata No 13 in B flat major, K333",
     "Sonata in B flat (K.333)"),  # Wolfgang Amadeus Mozart
    ("Piano Trio no 2 in E flat, K.498 'Kegelstatt'",
     "Trio for piano, clarinet and viola in E flat major, K498, 'Kegelstatt'"),  # Wolfgang Amadeus Mozart
    ("Violin Sonata no 18 in G major, K301",
     "Sonata for violin and keyboard (K.301) in G major"),  # Wolfgang Amadeus Mozart
    ("Piano Trio no 3 in B flat major, K. 502",
     "Piano Trio in B flat major, K 502"),  # Wolfgang Amadeus Mozart
    ("Flute Concerto No. 2 in D, K. 314",
     "Flute Concerto in D major, K314"),  # Wolfgang Amadeus Mozart
    # K.525 Eine kleine Nachtmusik — existing canonical is the No.13 form;
    # fold the Serenade-in-G phrasing into it (matching direction, no chain).
    ("Serenade in G major, K525 'Eine kleine Nachtmusik'",
     "Eine kleine Nachtmusik (Serenade No.13 in G) (K.525)"),  # Wolfgang Amadeus Mozart
    # K.388 Serenade No 12 in C minor — alt-Köchel K.384a + "no 12" variants.
    ("Serenade (K.388) in C minor for wind octet (K.384a)",
     "Serenade in C minor for Wind Octet (K.388)"),  # Wolfgang Amadeus Mozart
    ("Serenade No. 12 in C minor, K. 388",
     "Serenade in C minor for Wind Octet (K.388)"),  # Wolfgang Amadeus Mozart
    # K.299 Flute & Harp Concerto — alt-Köchel 297c (one BBC typo "277c").
    ("Concerto for Flute and Harp in C, K.299/277c",
     "Concerto for Flute, Harp and Orchestra in C major, K.299"),  # Wolfgang Amadeus Mozart
    ("Concerto for Flute and Harp in C, K. 299/297c",
     "Concerto for Flute, Harp and Orchestra in C major, K.299"),  # Wolfgang Amadeus Mozart
    # K.365 Concerto for 2 pianos — alt-Köchel 316a + "no 10" variants.
    ("Concerto for 2 pianos in E flat major, K365/316a",
     "Concerto for 2 pianos and orchestra in E flat major (K.365)"),  # Wolfgang Amadeus Mozart
    ("Piano Concerto no 10 in E flat for Two Pianos, K. 365",
     "Concerto for 2 pianos and orchestra in E flat major (K.365)"),  # Wolfgang Amadeus Mozart
    # K.242 Concerto No 7 for 3 pianos — bare form lacks the "no 7".
    ("Concerto in F major K.242 for 3 pianos and orchestra",
     "Concerto no 7 for 3 pianos and orchestra in F major (K.242)"),  # Wolfgang Amadeus Mozart
    # (K.254 "B-flat"/"B flat" pair GC'd 2026-07-10 — subsumed by the
    # hyphen-tolerant _key_signatures gate.) The 'B major' spelling is a BBC
    # KEY ERROR (K.254 is the B-flat Divertimento/piano trio); it merged only
    # accidentally via the old bare-'b' keysig bug, so the gate fix split it
    # out — folded back deliberately here:
    ("Divertimento in B major for violin, cello and piano (K.254)",
     "Divertimento in B-flat major for violin, cello and piano (K.254)"),  # Wolfgang Amadeus Mozart
    # K.32 Gallimathias musicum — key-sig added / spelling variant.
    ("Galimathias musicum in D, K 32",
     "Gallimathias Musicum (K.32)"),  # Wolfgang Amadeus Mozart

    # Variations / church sonatas / cantata: count-prefix or scoring variants.
    ("Variations on 'Ah, vous dirai-je, Maman' in C major, K.265",
     "12 Variations on 'Ah! Vous dirai-je, maman' (K.265)"),  # Wolfgang Amadeus Mozart
    # K.212 / K.328 Kirchen-Sonaten — redundant scoring annotation; K.328
    # also carries alt-Köchel 317c.
    ("Kirchen-Sonate in B flat (K. 212) for 2 violins, double bass and organ",
     "Kirchen-Sonate in B flat, K212"),  # Wolfgang Amadeus Mozart
    ("Church Sonata no 15 in C, K.328 (317c)",
     "Kirchen-Sonate no 15 in C major for 2 violins, bass and solo organ, K.328"),  # Wolfgang Amadeus Mozart
    # K.469 Davidde Penitente — redundant "cantata for …" scoring annotation.
    ("Davidde Penitente (K.469) - cantata for 2 sopranos, tenor, choir and orchestra",
     "Davidde Penitente, K 469"),  # Wolfgang Amadeus Mozart
    # K.549 Notturni — number-word vs digit.
    # K.618 Ave verum corpus — fold the "motet for chorus and strings"
    # scoring form into the bare token canonical (cross-composer-safe).
    ("Ave Verum Corpus (K.618) (motet for chorus and strings)",
     "Ave verum corpus"),  # shared: Wolfgang Amadeus Mozart / Imant Raminsh

    # Standalone concert arias (not opera excerpts) — phrasing variants fold,
    # same precedent as K.418 'Vorrei spiegarvi'.
    ("Ch'io mi scordi di te ...? Non temer, amato bene, K.505",
     "Concert aria: Ch'io mi scordi di te...? Non temer, amato bene (K.505)"),  # Wolfgang Amadeus Mozart
    ("Concert aria: Non piu, tutto ascoltai... Non temer amato bene, K.490",
     "Non piu, tutto ascoltai...Non temer amato bene, K490"),  # Wolfgang Amadeus Mozart
    ("Concert aria \"Bella mia fiamma...Resta, O cara\" (K.528)",
     "Bella mia fiamma - Resta, o cara, K.528"),  # Wolfgang Amadeus Mozart
    ("\"Basta vincesti\" (recit) and \"Ah, non lasciami\" (aria) (K.486a)",
     "Basta vincesti ... Ah, non lasciarmi K.486a"),  # Wolfgang Amadeus Mozart
    # K.584 Rivolgete a lui lo sguardo — the alternate Così aria; fold the
    # "from Così fan tutte" phrasings into the existing K.584 canonical.
    ("Rivolgete a lui lo sguardo, K.584 (from 'Cosi fan tutte')",
     "Aria 'Rivolgete a lui lo sguardo' (K.584)"),  # Wolfgang Amadeus Mozart
    ("Aria: 'Rivolgete a lui lo sguardo' (from \"Cosí fan tutte\", Act 1)",
     "Aria 'Rivolgete a lui lo sguardo' (K.584)"),  # Wolfgang Amadeus Mozart

    # --- Mozart audit, opera overtures & arias (2026-05-29) -----------------
    # Overtures: the BBC phrases each opera overture many ways (English vs
    # Italian/German title, "opera in N acts" tail, with/without K). They all
    # name the same overture, so they fold to one group. None of these operas
    # airs whole in the corpus (verified), so there's no overture/whole-opera
    # collision to worry about here. Arias are folded only with OTHER
    # phrasings of the SAME aria — never into the overture, and never across
    # different arias.

    # K.492 Le Nozze di Figaro — overture (English + Italian phrasings).
    ("Marriage of Figaro - overture",
     "Le Nozze di Figaro, K492, Overture"),  # Wolfgang Amadeus Mozart
    ("The Marriage of Figaro (Overture)",
     "Le Nozze di Figaro, K492, Overture"),  # Wolfgang Amadeus Mozart
    ("Le Nozze di Figaro - overture",
     "Le Nozze di Figaro, K492, Overture"),  # Wolfgang Amadeus Mozart
    ("Overture to Le Nozze di Figaro",
     "Le Nozze di Figaro, K492, Overture"),  # Wolfgang Amadeus Mozart
    ("Overture to Le Nozze di Figaro - opera in 4 acts K.492",
     "Le Nozze di Figaro, K492, Overture"),  # Wolfgang Amadeus Mozart
    # K.527 Don Giovanni — overture ("opera in 2 acts" tail).
    ("Overture from Don Giovanni - opera in 2 acts (K.527)",
     "Overture from 'Don Giovanni' (K.527)"),  # Wolfgang Amadeus Mozart
    # K.620 Die Zauberflöte — overture (English "Magic Flute" → German group).
    ("Overture to the Magic Flute",
     "Overture from Die Zauberflote (K 620)"),  # Wolfgang Amadeus Mozart
    ("The Magic Flute (overture)",
     "Overture from Die Zauberflote (K 620)"),  # Wolfgang Amadeus Mozart
    # K.486 Der Schauspieldirektor — overture into the existing canonical.
    ("Overture - from Der Schauspieldirektor, singspiel in 1 act (K.486)",
     "Der Schauspieldirektor - singspiel in 1 act (K.486)"),  # Wolfgang Amadeus Mozart

    # Arias — same-aria phrasing folds (cross-language opera name + locator
    # rewording). Deliberately NOT folded into the overtures above.
    # K.492 Figaro: 'Dove sono' (Countess) and 'Deh vieni' (Susanna).
    ("'Dove sono i bei momenti' - Countess' aria from The Marriage of Figaro. K.492",
     "Recit and aria 'Dove Sono' - from Act III of Le Nozze di Figaro, K.492"),  # Wolfgang Amadeus Mozart
    ("Aria: Deh vieni, non tardar - from Le Nozze di Figaro",
     "Le Nozze di Figaro, Act 4: Susanna's aria 'Deh vieni, non tardar'"),  # Wolfgang Amadeus Mozart
    # K.620 Zauberflöte: 'Ein Mädchen oder Weibchen' (two phrasings).
    ("Ein Mädchen oder Weibchen - from 'Die Zauberflöte' K 620, Act 2",
     "\"Ein Mädchen oder Weibchen\" - from 'Die Zauberflöte' (K620), Act 2"),  # Wolfgang Amadeus Mozart
    # K.588 Così: 'Un'aura amorosa' phrasing into the existing canonical.
    ("Aria: \"Un'aura amorosa\" from Cosi fan tutte (K.588), Act 1",
     "Aria: \"Un'aura amorosa\" from the opera 'Così fan tutte' (K.588), Act 1"),  # Wolfgang Amadeus Mozart

    # --- Haydn audit (2026-05-29) -------------------------------------------
    # Haydn fragments heavily across Hoboken-format variants: H.1.6 vs
    # Hob.I:6 vs Hob.1.6, roman vs arabic (Hob.VIIb vs Hob.7b), colon vs
    # slash vs period, with/without the Hob ref, backtick ordinals
    # ("Op.76`3" → glued "763"). Each group below is ONE work whose variants
    # the token sort / catalogue path left split; distinct set-catalogue
    # siblings (different Op/Hob numbers) and movement excerpts stay split.

    # Symphonies — nickname works fragmenting across H./Hob. forms.
    ("Symphony no 6 in D major 'Le Matin'",
     'Symphony no 6 in D major (H.1.6) "Le Matin"'),  # Joseph Haydn
    ("Symphony no 6 in D, Hob. I:6 'Le matin'",
     'Symphony no 6 in D major (H.1.6) "Le Matin"'),  # Joseph Haydn
    ("Symphony No 92 in G, Hob I:92 'Oxford'",
     'Symphony No 92 (H.1.92) in G major, "Oxford"'),  # Joseph Haydn
    ("Symphony No 92 'Oxford'",
     'Symphony No 92 (H.1.92) in G major, "Oxford"'),  # Joseph Haydn
    ("Symphony No 73 in D major, Hob.1.73,  'La Chasse'",
     "Symphony no 73 in D major 'La Chasse' (H.1.73)"),  # Joseph Haydn
    ("Symphony no 49 in F minor, Hob.I:49 'La Passione'",
     'Symphony No.49 in F minor (Hob.1.49)  "La Passione"'),  # Joseph Haydn
    ("Symphony No 49 in F minor H.1.49 (La Passione)",
     'Symphony No.49 in F minor (Hob.1.49)  "La Passione"'),  # Joseph Haydn
    ("Symphony no.49 in F minor, H.I:49, 'La Passione'",
     'Symphony No.49 in F minor (Hob.1.49)  "La Passione"'),  # Joseph Haydn
    ("Symphony No. 104 in D, Hob. I:104 'London'",
     "Symphony no 104 in D major, 'London', Hob.1.104"),  # Joseph Haydn
    ("Symphony No 43 in E flat, 'Mercury'",
     "Symphony No 43 in E flat major, Hob.1.43, 'Mercury'"),  # Joseph Haydn
    ("Symphony No. 43 in E flat, Hob. I:43 ('Mercury')",
     "Symphony No 43 in E flat major, Hob.1.43, 'Mercury'"),  # Joseph Haydn
    ('Symphony No.100 in G major, "Military"',
     'Symphony no 100 in G major, Hob.1.100 "Military"'),  # Joseph Haydn

    # String quartets — Op N/M nickname works split by Hob ref, backtick
    # ordinals, "Quartet for strings" wording, redundant Hob.III refs.
    ("String Quartet in D major (Op. 64 No.5) 'The Lark'",
     'String Quartet in D major, Op 64 no 5 (Hob.III.63) "Lark"'),  # Joseph Haydn
    ("String Quartet in D major, Op 64 no 5 'Lark'",
     'String Quartet in D major, Op 64 no 5 (Hob.III.63) "Lark"'),  # Joseph Haydn
    ('Quartet for strings Op 64 No 5 in D major "Lark"',
     'String Quartet in D major, Op 64 no 5 (Hob.III.63) "Lark"'),  # Joseph Haydn
    ("String Quartet in C major Op 76`3 (Emperor)",
     "String Quartet No.62 in C Major, Op.76'3 'Emperor'"),  # Joseph Haydn
    ("Quartet in C major Op 76`3 (Emperor)",
     "String Quartet No.62 in C Major, Op.76'3 'Emperor'"),  # Joseph Haydn
    ('Quartet for strings (Op.77`1) in G major Hob III/81 "Lobkowitz"',
     "String Quartet in G major Op 77 No 1"),  # Joseph Haydn
    ("String Quartet in G major, Op.77'1, Hob.III:81 'Lobkowitz'",
     "String Quartet in G major Op 77 No 1"),  # Joseph Haydn
    ("String Quartet no 30 in E flat, Op 33 no 2 'The Joke'",
     "String Quartet in E flat major, Op.33 No.2, 'Joke'"),  # Joseph Haydn
    ("String Quartet in G minor, Op 20 no 3, Hob.III:33",
     "String Quartet in G minor, Op 20, No 3"),  # Joseph Haydn

    # Chamber / concertos / divertimenti.
    ("Trio for keyboard and strings in G major (H. 15.25) 'Gypsy Rondo'",
     "Trio for keyboard and strings in G major (H.15.25) 'Gypsy Rondo'"),  # Joseph Haydn
    ("Cello Concerto No. 1 in C, Hob. 7b:1",
     "Cello Concerto No. 1 in C, Hob. VIIb:1"),  # Joseph Haydn
    ("Cello Concerto in D major, Hob. 7b:2",
     "Cello Concerto in D major, Hob.VIIb No.2"),  # Joseph Haydn
    ("Sinfonia concertante in B flat major, Hob.1:105",
     "Sinfonia Concertante in B flat, Hob. I:105"),  # Joseph Haydn
    # London Trio No 1 in C (Hob.IV:1) — remaining forms into the §hob4 group.
    ("Divertimento in C, Hob. IV:1 (attacca)",
     "Divertimento in C major, aka London Trio No 1 (Hob.4 No 1)"),  # Joseph Haydn
    ("Divertimento in C major, Hob.IV No.1",
     "Divertimento in C major, aka London Trio No 1 (Hob.4 No 1)"),  # Joseph Haydn
    ("Divertimento in C major (Hob.IV No.1) (London Trio No.1)",
     "Divertimento in C major, aka London Trio No 1 (Hob.4 No 1)"),  # Joseph Haydn
    ("Divertimento in C major, Hob.IV No 1 'London Trio'",
     "Divertimento in C major, aka London Trio No 1 (Hob.4 No 1)"),  # Joseph Haydn
    # London Trio No 1 — "for 2 flutes and cello" scoring forms (Hob.4.1
    # period parses as a separate key) and the bare no-Hob form.
    ("Divertimento for 2 flutes and cello  in C major , Hob.4.1, 'London trio' No 1",
     "Divertimento in C major, aka London Trio No 1 (Hob.4 No 1)"),  # Joseph Haydn
    ('Divertimento for 2 flutes and cello (H.4.1) in C major "London trio" No.1',
     "Divertimento in C major, aka London Trio No 1 (Hob.4 No 1)"),  # Joseph Haydn
    ('Divertimento in C major, "London Trio" No 1',
     "Divertimento in C major, aka London Trio No 1 (Hob.4 No 1)"),  # Joseph Haydn
    # London Trio No 4 in G — "Hob.IV No.4" form into the Hob.IV:4 group.
    ("Divertimento in G major Hob.IV No.4 (London Trio No.4)",
     "Divertimento in G major, Hob.IV:4 (London Trio No.4)"),  # Joseph Haydn

    # Keyboard sonata Hob.XVI:52 — slash vs colon, "No 52" vs catalogue.
    ("Keyboard Sonata No 52 in E Flat,  Hob XVI/52",
     "Keyboard Sonata in B flat, Hob. XVI:52"),  # Joseph Haydn
    ("Keyboard Sonata no 52 in E Flat, Hob.XVI/52",
     "Keyboard Sonata in B flat, Hob. XVI:52"),  # Joseph Haydn

    # Vocal / choral / overtures.
    ("Mass No. 9 in C, Hob. XXII:9 'Missa in tempore belli'",
     "Mass in C major, Missa in tempore belli 'Paukenmesse' H.22.9"),  # Joseph Haydn
    ("Missa in tempore belli (Hob. XXII. 9) 'Paukenmesse'",
     "Mass in C major, Missa in tempore belli 'Paukenmesse' H.22.9"),  # Joseph Haydn
    ("L'Isola disabitata - Overture/Sinfonia",
     "Overture, L'Isola disabitata"),  # Joseph Haydn
    ("Overture to  Speziale (H.28.3)",
     "Overture to Lo Speziale, H.28.3"),  # Joseph Haydn
    ("Overture to Lo Speziale",
     "Overture to Lo Speziale, H.28.3"),  # Joseph Haydn
    ("Der Sturm - chorus for SATB choir and orchestra (H.24a.8)",
     "Der Sturm (The Storm) - madrigal for chorus and orchestra (H.24a.8)"),  # Joseph Haydn
    ("Der Sturm, H.24a.8",
     "Der Sturm (The Storm) - madrigal for chorus and orchestra (H.24a.8)"),  # Joseph Haydn
    ("The Creation, H.21.2",
     "The Creation - oratorio, Hob XXI:2"),  # Joseph Haydn
    ("Variations on the hymn 'Gott erhalte Franz den Kaiser'",
     "Variations about the hymn 'Gott erhalte'"),  # Joseph Haydn
    ("The Mermaid's song (H.26a.25) from 6 Original canzonettas set 1",
     "The Mermaid's song, H.26a.25"),  # Joseph Haydn

    # --- Haydn re-audit (2026-05-29) ----------------------------------------
    # Surfaced after the audit tool learned roman-numeral Hob refs + edge-
    # apostrophe tokenization (commit 6e711aa): one work split across Hob
    # notations that previously scattered into separate clusters. Mostly
    # roman-colon (Hob.I:103) vs arabic-period (Hob.1/103) vs "H." prefix
    # (H.XVI.33) of the same work.

    # Symphonies — second-pass Hob-notation splits.
    ("Symphony No 103 in E flat major, Hob.1/103 ('Drum roll')",
     "Symphony No. 103 in E flat, Hob. I:103 'Drumroll'"),  # Joseph Haydn
    ("Symphony no 100 in G major, Hob. I:100 'Military'",
     "Symphony no 100 in G major, Hob.1.100 \"Military\""),  # Joseph Haydn
    ("Symphony No 95 in C minor, Hob I:95",
     "Symphony No 95 in C minor, Hob.1.95"),  # Joseph Haydn
    ("Symphony No 60 in C major, Hob.1.60, 'Il distratto'",
     "Symphony no 60 in C major 'Il distratto' (Hob.1:60)"),  # Joseph Haydn
    # "H.1.NNN" prefix forms (the audit's Hob bucket can't see "H." prefix);
    # these are the dominant Drum-Roll / 95 spellings, plus bare forms.
    ("Symphony no 103 in E flat major \"Drum Roll\" (H.1.103)",
     "Symphony No. 103 in E flat, Hob. I:103 'Drumroll'"),  # Joseph Haydn
    ("Symphony No 103 in E flat major \"Drumroll\"",
     "Symphony No. 103 in E flat, Hob. I:103 'Drumroll'"),  # Joseph Haydn
    ("Symphony No. 103 in E flat major 'Drum Roll'",
     "Symphony No. 103 in E flat, Hob. I:103 'Drumroll'"),  # Joseph Haydn
    ("Symphony No 95 in C minor H.1.95",
     "Symphony No 95 in C minor, Hob.1.95"),  # Joseph Haydn
    ("Symphony No 95 in C minor",
     "Symphony No 95 in C minor, Hob.1.95"),  # Joseph Haydn

    # String quartets.
    ("Quartet for strings in G major Hob III:81 'Lobkowitz'",
     "String Quartet in G major Op 77 No 1"),  # Joseph Haydn
    # Hob.III:69 — "Op 7 No 1" is a BBC mislabel of Op 71 No 1.
    ("String Quartet in B flat major (Op.7 No.1) (Hob III:69)",
     "String Quartet in B flat major, Op 71 no 1 (Hob III:69)"),  # Joseph Haydn

    # Keyboard sonatas — colon vs slash, and "H." prefix vs "Hob.".
    ("Sonata in D, HobXVI:37",
     "Keyboard Sonata in D major, Hob.XVI/37"),  # Joseph Haydn
    ("Piano Sonata in D major, H.XVI.33",
     "Piano Sonata in D major, Hob.XVI.33"),  # Joseph Haydn
    ("Sonata for piano (H.XVI.33) in D major",
     "Piano Sonata in D major, Hob.XVI.33"),  # Joseph Haydn

    # Piano trios — Hob.15.NN period vs Hob XV:NN colon, H. prefix.
    ("Piano Trio in C major,  Hob.15.27",
     "Piano trio in C major Hob XV:27"),  # Joseph Haydn
    ("Piano Trio in A major, Hob 15.18",
     "Keyboard Trio No.18 in A major (Hob XV:18)"),  # Joseph Haydn
    ("Trio Sonata in E flat major (H.XV.29)",
     "Piano Trio in E flat major, Hob:15.29"),  # Joseph Haydn
    # Gypsy Rondo (Hob.XV:25 = H.15.25 = No 39) — five canonicals unify.
    ("Piano Trio No 39 in G Hob XV:25",
     "Trio for keyboard and strings in G major (H.15.25) 'Gypsy Rondo'"),  # Joseph Haydn
    ("Piano Trio in G major, 'Gypsy rondo' Hob.15.25",
     "Trio for keyboard and strings in G major (H.15.25) 'Gypsy Rondo'"),  # Joseph Haydn
    ("Piano Trio in G major, H15.25 'Gypsy rondo'",
     "Trio for keyboard and strings in G major (H.15.25) 'Gypsy Rondo'"),  # Joseph Haydn
    ("Piano Trio in G major, Hob XV:25",
     "Trio for keyboard and strings in G major (H.15.25) 'Gypsy Rondo'"),  # Joseph Haydn
    ("Trio for keyboard and strings in G major, 'Gypsy rondo'",
     "Trio for keyboard and strings in G major (H.15.25) 'Gypsy Rondo'"),  # Joseph Haydn

    # Divertimenti / Feldpartita (Hob.II:46).
    ("Divertimento in B flat, Hob.II:46",
     "Divertimento 'Feldpartita' in B flat major, Hob.2.46"),  # Joseph Haydn
    ("Divertimento in B flat major H.2.46 arr. for wind quintet",
     "Divertimento 'Feldpartita' in B flat major H.2.46 arr. for wind quintet"),  # Joseph Haydn

    # Cello Concerto No 1 (Hob.7b.1 period form).
    ("Cello Concerto no 1 in C major, Hob.7b.1",
     "Cello Concerto No. 1 in C, Hob. VIIb:1"),  # Joseph Haydn

    # L'Isola disabitata overture — the Hob.Ia:13 form.
    ("Overture to 'L'isola disabitata', Hob.Ia:13",
     "Overture, L'Isola disabitata"),  # Joseph Haydn

    # --- Wagner audit (2026-05-29) ------------------------------------------
    # Mostly opera-excerpt phrasing folds. Same-excerpt phrasings fold;
    # DIFFERENT excerpts stay split — Prelude vs Liebestod vs the combined
    # "Prelude and Liebestod", Act 1 vs Act 3 preludes, Prelude vs Good
    # Friday Music. Piano/organ arrangements kept separate from the original.

    # Siegfried Idyll — "for small orchestra" scoring annotation folds in.
    ("Siegfried Idyll for small orchestra",
     "Siegfried Idyll"),  # Richard Wagner

    # Tristan und Isolde — Prelude (Act 1) alone; phrasing variants.
    ("Prelude to 'Tristan and Isolde'",
     "Tristan and Isolde (Prelude)"),  # Richard Wagner
    ("Tristan und Isolde: Prelude to Act 1",
     "Tristan and Isolde (Prelude)"),  # Richard Wagner
    # Tristan — the combined "Prelude and Liebestod" (distinct from Prelude
    # alone and from Liebestod alone).
    ("Prelude and Liebestod from 'Tristan und Isolde'",
     "Prelude and Liebestod - from the opera 'Tristan and Isolde'"),  # Richard Wagner
    ("Prelude and Isolde's Liebestod - from \"Tristan & Isolde\"",
     "Prelude and Liebestod - from the opera 'Tristan and Isolde'"),  # Richard Wagner
    ("Prelude and Isolde's Liebestod - from 'Tristan und Isolde'",
     "Prelude and Liebestod - from the opera 'Tristan and Isolde'"),  # Richard Wagner
    ("Prelude and Liebestod - from Tristan and Isolde",
     "Prelude and Liebestod - from the opera 'Tristan and Isolde'"),  # Richard Wagner

    # Die Meistersinger — Act 1 Prelude (bare "Prelude" = Act 1 by default);
    # Act 3 prelude and the arias stay separate.
    ("Prelude to Die Meistersinger von Nurnberg",
     "Prelude to Act 1 from 'Die Meistersinger von Nurnberg'"),  # Richard Wagner
    ("Prelude (Act 1 'Die Meistersinger von Nurnberg')",
     "Prelude to Act 1 from 'Die Meistersinger von Nurnberg'"),  # Richard Wagner

    # Der fliegende Holländer — Daland's aria (Die/Der spelling).
    ("Mögst du, mein kind (Daland's aria) - from Der Fliegende Holländer, Act 2",
     "\"Mogst du, mein kind\" (Daland's aria from Act II Die Fliegende Hollander)"),  # Richard Wagner

    # Tannhäuser — Wolfram's aria 'O du mein holder Abendstern' (Act 3).
    ("Recitative and aria \"O du mein holder Abendstern\" from Tannhäuser (Act 3)",
     "O du mein holder Abendstern – from \"Tannhauser\""),  # Richard Wagner
    ("Recitative and aria \"O du mein holder Abendstern\" (Evening Star), from 'Tannhäuser' (Act 3)",
     "O du mein holder Abendstern – from \"Tannhauser\""),  # Richard Wagner
    ("O du mein holder Abendstern - from 'Tannhäuser', Act 3",
     "O du mein holder Abendstern – from \"Tannhauser\""),  # Richard Wagner

    # Parsifal — Prelude (Act 1); Good Friday Music stays a distinct excerpt.
    ("Prelude to Act 1 of 'Parsifal'",
     "Prelude to Parsifal"),  # Richard Wagner

    # Lohengrin — Act 1 Prelude ("Act I" roman = Act 1); Act 3 stays split.
    ("Lohengrin - Prelude to Act 1",
     "Prelude to Act 1 from Lohengrin"),  # Richard Wagner
    ("Prelude to Act I of 'Lohengrin'",
     "Prelude to Act 1 from Lohengrin"),  # Richard Wagner

    # Wesendonck-Lieder cycle — Wesendonk/Wesendonck spelling.
    ("Fünf Lieder von Mathilde von Wesendonk",
     "Funf Lieder von Mathilde von Wesendonck"),  # Richard Wagner

    # Isolde's Liebestod, Liszt piano transcription S.447.

    # Tannhäuser — Overture + Venusberg Music (the concert/Paris version).
    ("Overture and Venusberg Music, from 'Tannhäuser'",
     "Tannhauser: Overture; Venusberg music (concert version)"),  # Richard Wagner

    # Faust Overture, WWV 59.
    ("Overture to 'Faust' WWV 59",
     "Faust Overture, WWV 59"),  # Richard Wagner

    # --- Catalogue-path phantom-ordering: sonatas batch (2026-05-26) ---------
    # Same shape as the earlier batch — BBC inconsistently includes one of
    # several legitimate identifiers per work (sonata index, opus number,
    # movement marker, scoring digit). Each variant key was verified
    # corpus-exclusive before adding.

    # Mozart K.332 — Piano Sonata No 12 in F. Bare form folds into the
    # no-12 form. (The "2nd mvt Adagio" excerpt now keys §k332|adagio via
    # the movement-marker gate, kept distinct from the whole sonata.)
    ("Sonata for piano K.332 in F major",
     "Piano Sonata no 12 in F major, K.332"),  # Wolfgang Amadeus Mozart

    # Schubert D.845 — Piano Sonata No 16 in A minor. Also published as
    # Op. 42, so titles alternate between catalogue + opus references.
    ("Piano Sonata no 16 in A minor, D.845",
     "Piano Sonata in A minor D.845, Op 42"),  # Franz Schubert
    ("Piano Sonata in A minor, D845",
     "Piano Sonata in A minor D.845, Op 42"),  # Franz Schubert

    # Schubert D.960 — Piano Sonata No 21 in B flat. Bare form fold-in.
    ("Piano Sonata in B flat major, D.960",
     "Piano Sonata no 21 in B flat major, D.960"),  # Franz Schubert

    # Schubert D.897 — the Notturno in E flat (single-movement Adagio). Under the
    # recording-anchored default the segment title sometimes drops the D-number
    # ("Piano Trio in E flat, 'Notturno'"), splitting it off the §d897 catalogue
    # group. SAFE per Cerys consult 2026-06-21: scoring + key + the 'Notturno'
    # nickname uniquely pin D.897 (excluding the full E-flat trio D.929) — the
    # nickname is piece-specific, not generic. The key includes 'notturno' but no
    # movement/catalogue token, so it can't catch a D.929-Andante mislabel.
    ("Piano Trio in E flat, 'Notturno'",
     "Piano Trio in E flat major, D.897 'Notturno'"),  # Franz Schubert

    # Scarlatti K.88 — Sonata in G minor. The "arranged for 2 harpsichords"
    # variant is the most-aired form (an arrangement preserved); fold bare
    # into it.
    ("Sonata in G minor, K88",
     "Sonata in G minor (K 88) arranged for 2 harpsichords"),  # Domenico Scarlatti

    # Bach BWV.1001 — Violin Sonata No 1 in G minor. Bare form folds into
    # the no-1 form. (The "Adagio & Fugue - 2 movements from" excerpt now
    # keys §bwv1001|adagio,fugue via the movement-marker gate.)
    ("Sonata for violin solo in G minor, BWV.1001",
     "Sonata for violin solo no 1 in G minor, BWV.1001"),  # Johann Sebastian Bach

    # Schubert D.959 — Piano Sonata No 20 in A. Most-aired form is the
    # Andantino excerpt (movement of the same work).
    ("Piano Sonata no 20 in A, D. 959",
     "Andantino (second movement) from Piano Sonata in A major, D.959"),  # Franz Schubert

    # Schubert D.850 — Piano Sonata No 17 in D. Op.53 variant + bare variant.
    ("Sonata (Op.53) in D major (D.850)",
     "Piano Sonata no 17 in D major, D.850"),  # Franz Schubert
    ("Sonata in D major D.850 for piano",
     "Piano Sonata no 17 in D major, D.850"),  # Franz Schubert

    # Mozart K.330 — Piano Sonata No 10 in C. Bare form fold-in.
    ("Piano Sonata in C K.330",
     "Piano Sonata no 10 in C major, K.330"),  # Wolfgang Amadeus Mozart

    # Handel HWV.363a — Op. 1 No. 5 oboe sonata in F. Bare form (lacks Op
    # numbering) fold-in.
    ("Sonata in F major, HWV.363a vers. oboe & bc",
     "Sonata in F major, Op 1 no 5 (HWV.363a) vers. oboe & bc"),  # George Frideric Handel

    # Handel HWV.362 — Op. 1 No. 4 oboe sonata in A minor; the violin
    # version is a long-standing arrangement of the same work. Same-work,
    # two-scorings (parallel to the BWV.1056 oboe-reconstruction case).
    ("Sonata for oboe and continuo, HWV.362",
     "Violin Sonata in A minor (Op.1 No.4) (HWV.362)"),  # George Frideric Handel

    # Vivaldi RV.63 'La Folia' — Trio Sonata Op. 1 No. 12 in D minor. Four
    # variant title-keys collapse into the most-aired form (with Op + No
    # + scoring digit).
    ("Trio Sonata in D minor, RV 63 (Op 1 No 12), 'La Folia'",
     "Trio sonata for 2 violins & continuo in D minor 'La Folia', RV.63 (Op 1 no 12)"),  # Antonio Vivaldi
    ("Sonata no 12 in D minor, RV.63 ('La Follia')",
     "Trio sonata for 2 violins & continuo in D minor 'La Folia', RV.63 (Op 1 no 12)"),  # Antonio Vivaldi
    ("Trio Sonata in D minor, RV 63 'La Follia'",
     "Trio sonata for 2 violins & continuo in D minor 'La Folia', RV.63 (Op 1 no 12)"),  # Antonio Vivaldi
    # La Folia token-sort tail: titles lacking the RV reference fall to the
    # token-sort path, splitting "Trio Sonata …" (×23) and "Sonata …" (×9)
    # off from the catalogue group. Both token-sort keys are Vivaldi-
    # exclusive.
    ("Trio Sonata in D minor Op 1 No 12 'La Folia' (1705)",
     "Trio sonata for 2 violins & continuo in D minor 'La Folia', RV.63 (Op 1 no 12)"),  # Antonio Vivaldi
    ("Sonata in D minor 'La Folia' Op 1 no 12",
     "Trio sonata for 2 violins & continuo in D minor 'La Folia', RV.63 (Op 1 no 12)"),  # Antonio Vivaldi
    # (2026-05-31 ttn_duplicates straggler — same ref-less token-sort tail.)
    ("Sonata in D minor 'La Folia' (Op.1/12)",
     "Trio sonata for 2 violins & continuo in D minor 'La Folia', RV.63 (Op 1 no 12)"),  # Antonio Vivaldi

    # --- Catalogue-path phantom-ordering: audit batch 3 (2026-05-26) --------
    # Surfaced by the composer/ref split scan: same catalogue ref splits when
    # the BBC inconsistently includes (or omits) a key signature, sonata
    # index, or opus reference alongside the catalogue number. Each variant
    # key verified corpus-exclusive.

    # Schubert D.590 — Overture in the Italian Style in D. Bare-form titles
    # omit the key signature (×17).
    ("Overture in the Italian Style, D.590",
     "Overture in D major 'In the Italian Style', D.590"),  # Franz Schubert

    # Schubert D.667 — Trout Quintet. D.667 IS Op.114; the ×8 group carries
    # both references redundantly.
    ("Piano Quintet in A major 'The Trout', Op 114 (D.667)",
     "Piano Quintet in A major 'The Trout', D.667"),  # Franz Schubert

    # Schubert D.958 — Piano Sonata No 19 in C minor. Same pattern as
    # D.845/D.959/D.960 (already aliased): bare form folds with no-19 form.
    ("Piano sonata no 19 in C minor, D.958",
     "Piano Sonata in C minor, D.958"),  # Franz Schubert

    # Bach BWV.1003 — Violin Sonata No 2 in A minor. Bare form (no key
    # signature) folds in.
    ("Sonata for solo violin no 2, BWV.1003",
     "Violin Sonata no 2 in A minor, BWV.1003"),  # Johann Sebastian Bach

    # Bach BWV.1041 — Violin Concerto No 1 in A minor. Bare form (no "no 1")
    # folds into the indexed form.
    ("Violin Concerto in A minor, BWV.1041",
     "Concerto for violin and string orchestra No.1 in A minor (BWV.1041)"),  # Johann Sebastian Bach

    # Bach BWV.1055 — Harpsichord/oboe d'amore Concerto No 4 in A major.
    # Bare-A-major form (×2) folds into the No 4 form. (The "Allegro from
    # Concerto in C major" movement excerpt now keys §bwv1055|allegro via
    # the movement-marker gate.)
    ("Concerto in A major, BWV.1055",
     "Concerto for oboe d'amore and string orchestra No.4 in A major, BWV.1055"),  # Johann Sebastian Bach

    # Vivaldi RV.428 — 'Il Gardellino' Flute Concerto. RV.428 IS Op.10 No.3;
    # the ×5 group carries both references redundantly.
    ("Flute Concerto in D major, RV.428 (Op.10 No.3) ('Il Gardellino')",
     "Flute Concerto in D major, RV.428 ('Il Gardellino')"),  # Antonio Vivaldi

    # Vivaldi RV.297 — 'L'Inverno' (Winter) Violin Concerto in F minor.
    # RV.297 IS Op.8 No.4. The accordion-arrangement whole-work variant
    # folds in. (The "Largo from L'Inverno" movement excerpt now keys
    # §rv297|largo via the movement-marker gate.)
    ("Violin Concerto in F minor, RV.297 (Op.8 No.4), arr. for accordion",
     "Violin Concerto in F minor, RV.297 'L'Inverno'"),  # Antonio Vivaldi

    # --- Long-tail follow-up to batch 3 (2026-05-26) ------------------------
    # 2-4 airing splits surfaced by the composer/ref scan, kept separate from
    # the main batch because the impact-per-alias is small.

    # Vivaldi RV.269 — 'La Primavera' (Spring) Violin Concerto in E.
    # RV.269 IS Op.8 No.1; ×4 group omits the Op reference.
    ("La Primavera (Spring), Violin Concerto no 1 in E, RV 269",
     "Concerto for violin & orchestra (RV.269) (Op.8 No.1) in E major 'La Primavera'"),  # Antonio Vivaldi

    # Mozart K.421 — String Quartet No 15 in D minor. ×2 group adds "no 15"
    # phantom-ordering digit.
    ("String Quartet no 15 in D minor, K.421",
     "Quartet for Strings in D minor, K.421"),  # Wolfgang Amadeus Mozart

    # Mozart K.418 — 'Vorrei spiegarvi, oh Dio' concert aria. The catalogue
    # path skips because "aria" is an excerpt marker (correctly preventing
    # opera-aria merges); the token-sort variant omits "for orchestra
    # soprano" so it splits. K.418 is a standalone concert aria, not an
    # opera excerpt — alias rather than relax the excerpt-locator gate.
    ("Vorrei spiegarvi, oh Dio - aria K.418",
     "Vorrei spiegarvi, oh Dio - aria for soprano and orchestra, K.418"),  # Wolfgang Amadeus Mozart

    # --- --form audit surfacing (2026-05-26) --------------------------------
    # `--form symphony` and `--form nocturne` revealed splits that `--title`
    # alone (English-only) would have missed.

    # Berlioz Symphonie Fantastique — bare-form variant (×4) lacks the Op 14
    # reference. Token-sort split; composer-exclusive.
    ("Symphonie fantastique",
     "Symphonie Fantastique, Op 14"),  # Hector Berlioz

    # Fauré Nocturne Op 107 — phantom "no 12" ordering digit (×5). Same
    # work, distinguished by opus number.
    ("Nocturne no 12 in E minor, Op 107",
     "Nocturne in E minor, Op 107"),  # Gabriel Fauré

    # Bartók Romanian Folk Dances Sz.56 — phantom "6" (Sz.56 has 6 dances,
    # which the BBC sometimes spells out in the title).
    ("6 Romanian folk dances, Sz.56",
     "Romanian Folk Dances, Sz.56"),  # Bela Bartok

    # Mendelssohn Symphony No 4 'Italian' — bare-form variants lacking Op 90.
    # Token-sort path (no catalogue ref for Mendelssohn's Op-numbered works).
    # "Italian" nickname is the discriminator: bare "Symphony No 4" alone
    # would NOT match — only titles carrying the nickname fold here.
    ("Symphony no.4, 'Italian'",
     "Symphony No 4 in A major, Op 90 'Italian'"),  # Felix Mendelssohn
    ("Symphony No.4 in A major, 'Italian'",
     "Symphony No 4 in A major, Op 90 'Italian'"),  # Felix Mendelssohn

    # Tchaikovsky Marche Slave Op 31 — the BBC oscillates between French
    # ("Marche slave") and English ("Slavonic March") and sometimes both,
    # creating 5 distinct token-sort groups for one work. All fold to the
    # most-aired form. Op 31 + B flat minor pin identity.
    ("Slavonic March in B flat minor 'March Slave'",
     "Marche Slave, Op 31"),  # Peter Ilyich Tchaikovsky
    ("Slavonic March in B flat minor, op. 31",
     "Marche Slave, Op 31"),  # Peter Ilyich Tchaikovsky
    ("Slavonic March in B flat minor (Op.31) 'March Slave'",
     "Marche Slave, Op 31"),  # Peter Ilyich Tchaikovsky
    ("Slavonic March in B flat minor 'Marche slave' (Op.31)",
     "Marche Slave, Op 31"),  # Peter Ilyich Tchaikovsky
    ("March in B flat minor, Op.31, 'Marche slave'",
     "Marche Slave, Op 31"),  # Peter Ilyich Tchaikovsky

    # Chopin 12 Studies — same "for piano" scoring-annotation split on both
    # Op 10 and Op 25. Two aliases.

    # Beethoven WoO.46 'Bei Mannern' Variations — bare form (×12) lacks the
    # "7" ordering digit. WoO.46 is uniquely this work; the "7" describes
    # the variation count, not a sibling index.
    ("Variations on 'Bei Mannern, welche Liebe fuhlen' (WoO.46)",
     "7 Variations on 'Bei Mannern, welche Liebe fuhlen' WoO 46"),  # Ludwig van Beethoven

    # Grieg Holberg Suite, Op 40 — bare form (×7) and "version for string
    # orchestra" scoring annotation (×3) both fold into the main group.
    # Movement excerpts (Praeludium etc.) correctly stay split.
    ("Holberg Suite",
     "Holberg Suite (Op.40)"),  # Edvard Grieg
    ("Holberg suite (Op.40) version for string orchestra",
     "Holberg Suite (Op.40)"),  # Edvard Grieg

    # Weber Clarinet Concertino in E flat, Op 26 — split on word order
    # ("Clarinet Concertino" vs "Concertino for clarinet and orchestra")
    # and on a bare-form variant that drops "clarinet" entirely. Same Op,
    # same scoring; all three keys composer-exclusive.
    ("Concertino for clarinet and orchestra in E flat major, Op 26",
     "Clarinet Concertino in E flat major, Op 26"),  # Carl Maria von Weber
    ("Concertino in E flat, Op 26",
     "Clarinet Concertino in E flat major, Op 26"),  # Carl Maria von Weber

    # Mendelssohn Octet for Strings, Op 20 — same Weber-style word-order
    # split: "String Octet" vs "Octet for strings" (×21) and a bare-form
    # variant lacking the scoring word (×7). Op 20 + E flat pins identity.
    ("Octet in E flat major, Op 20",
     "String Octet in E flat major, Op 20"),  # Felix Mendelssohn

    # Spohr Nonet Op 31 in F — bare form (×8) lacks the detailed scoring.
    # Op 31 + F major + nonet pins identity.
    ("Nonet in F major, Op 31",
     "Nonet for wind quintet, string trio and double bass in F major, Op 31"),  # Louis Spohr

    # Tchaikovsky Violin Concerto in D, Op 35 — bare form (×4) lacks the
    # Op reference. NOTE: this variant key is shared with Stravinsky's
    # own Violin Concerto in D (1931), but composer-scoped grouping in
    # downstream tools (ttn_analyze, ttn_audit both key
    # on (composer, work) tuples) keeps them separate. Stravinsky's
    # tracks pick up the relabeled work_key with no false merge.
    ("Violin Concerto in D major",
     "Violin Concerto in D major (Op.35)"),  # shared: Peter Ilyich Tchaikovsky / Erich Wolfgang Korngold

    # --- Op-bucket scan batch (2026-05-27) ----------------------------------
    # Broad scan grouped tracks by (composer, op_number) to find pairs of
    # high-airing groups for the same opus. ~134 airings across 8 works.

    # Mendelssohn Op 26 'The Hebrides' / 'Fingal's Cave' — ×17 carries the
    # alt-title "Fingal's Cave" and the B-minor key sig that the main form
    # omits. Target string matches the existing Hebrides alias block above.
    ("The Hebrides - Overture in B minor, Op.26, 'Fingal's Cave'",
     "The Hebrides, Op 26"),  # Felix Mendelssohn

    # Beethoven Op 62 Coriolan Overture — ×6 with the key sig "in C minor".
    ("Coriolan - Overture in C minor, Op.62 (1807)",
     "Coriolan Overture Op 62"),  # Ludwig van Beethoven

    # Chopin Op 60 Barcarolle in F sharp major — ×19 lacks the key sig.
    ("Barcarolle, Op 60",
     "Barcarolle in F sharp major, Op 60"),  # Fryderyk Chopin

    # Schumann Op 15 Kinderszenen — bare form (×20) lacks the "for piano"
    # scoring annotation. Movement excerpts (Träumerei, Von fremden
    # Ländern) correctly stay split.

    # Suk Op 23 Elegy — three variant forms: German "Elegie" spelling
    # (×11), key-sig-bearing English variant (×5), and the official
    # Czech subtitle "Pod dojmem Zeyerova Vyšehradu" (×4). All same work.
    ("Elegie, Op 23",
     "Elegy (Op 23) arr. for piano trio"),  # Josef Suk
    ("Elegy in D flat major, Op 23",
     "Elegy (Op 23) arr. for piano trio"),  # Josef Suk
    ("Elegie (Pod dojmem Zeyerova Vysehradu), Op 23, arr. for piano trio",
     "Elegy (Op 23) arr. for piano trio"),  # Josef Suk

    # Chaminade Op 107 Flute Concertino — bare form (×8) drops "flute"
    # entirely. Composer-exclusive.
    ("Concertino, Op 107",
     "Flute Concertino, Op 107"),  # Cecile Chaminade

    # Dvořák Op 96 'American' String Quartet — Weber-pattern word-order
    # split: "Quartet…for strings" vs "String Quartet…" (×6).

    # Schumann Op 73 Phantasiestücke — four variant forms collapse together:
    # bare "Fantasie" spelling (×28), arrangement annotation (×10), English
    # translation "3 Fantasy Pieces" (×11), and a "for clarinet and piano"
    # word-order variant (×7). All Op 73, same work.
    ("Fantasiestucke, Op 73",
     "Phantasiestucke Op 73 for clarinet & piano"),  # Robert Schumann
    ("Phantasiestucke, Op.73",
     "Phantasiestucke Op 73 for clarinet & piano"),  # Robert Schumann
    ("3 Fantasy Pieces, Op 73",
     "Phantasiestucke Op 73 for clarinet & piano"),  # Robert Schumann
    ("Fantasiestucke, Op 73, for clarinet and piano",
     "Phantasiestucke Op 73 for clarinet & piano"),  # Robert Schumann

    # --- Catalogue-ref scan follow-ups (2026-05-27) -------------------------

    # Schubert D.821 Arpeggione Sonata — bare-form variant (×16) lacks the
    # A-minor key sig.
    ("Arpeggione Sonata (D.821)",
     "Arpeggione Sonata in A minor, D.821"),  # Franz Schubert

    # Handel HWV.350 Water Music suite in G — ×5 carries a phantom "2"
    # (from "2 oboes" scoring) in the catalogue path.
    ("Water Music: Suite in G major for 'flauto piccolo', 2 oboes, bassoon and strings, HWV.350",
     "Water Music - suite HWV.350 in G major"),  # George Frideric Handel

    # --- Satie audit (2026-05-27) -------------------------------------------

    # Satie 'Je te veux' (valse-chanson) — three forms collapse: bare title
    # (×6), full Valse-chantée parenthetical (×1), and the most-aired
    # "Je te veux, valse" form (target).
    ("Je te veux",
     "Je te veux, valse"),  # Erik Satie
    ("Je te Veux (Valse chantée pour piano)",
     "Je te veux, valse"),  # Erik Satie

    # Satie Trois mélodies (Contamine de Latour texts, 1916) — four
    # variants across "melodies" / "Songs" English translation and
    # spacing of "J.P. Contamine". All the same set of three songs.
    ("Three melodies with texts by J.P. Contamine de La Tour",
     "Three melodies with texts by J.P.Contamine de La Tour"),  # Erik Satie
    ("Three Songs with texts by JPContamine de La Tour",
     "Three melodies with texts by J.P.Contamine de La Tour"),  # Erik Satie
    ("Three Songs with texts by JP Contamine de La Tour",
     "Three melodies with texts by J.P.Contamine de La Tour"),  # Erik Satie

    # Satie Gnossienne No 1 — split on the "for piano" scoring annotation
    # (the Gnossiennes are written for solo piano; the qualifier is
    # redundant). ×10 + ×10 same piece.

    # Satie '4 Pieces' broadcast program — the BBC airs a 4-piece Satie
    # selection (Gymnopédie No 1; Les anges; Le chapelier; Je te veux)
    # under two title forms: the detailed list and the bare "4 Pieces".
    # ×1 + ×1; Satie-exclusive on the bare title-key.
    ("4 Pieces",
     "4 Pieces: [1.Gymnopedie No.1; 2.Les anges, from 'Trois melodies' (Latour); 3.Le chapelier, from 'Trois melodies'; 4.Je te veux]"),  # Erik Satie

    # --- Liszt audit (2026-05-27) -------------------------------------------
    # Liszt's catalogue has heavy cross-language / spelling churn and
    # frequent optional-S-number variants. Audit findings below; sibling
    # works (different Legendes, Mazeppa etude vs symphonic poem, etc.)
    # correctly stay split.

    # Hungarian Rhapsody No 2 in C sharp minor — three groups merge into
    # the no-S-number form (the most-aired). 'from S.244' and 'for piano
    # (S.244 No.2)' both denote the same piece, the piano original.
    ("Hungarian Rhapsody No 2 in C sharp minor (from S.244)",
     "Hungarian Rhapsody No 2 in C sharp minor"),  # Franz Liszt
    ("Hungarian Rhapsody no 2 for piano in C sharp minor (S.244 No.2)",
     "Hungarian Rhapsody No 2 in C sharp minor"),  # Franz Liszt

    # Hungarian Rhapsody No 6 in D flat major — bare form (×4) drops key sig.
    ("Hungarian Rhapsody No 6",
     "Hungarian Rhapsody No 6 in D flat major"),  # Franz Liszt

    # Piano Concerto No 2 in A major, S.125 — variant with S.125 (×7)
    # folds into bare-form group (×11). Same work; S-number optional.
    ("Piano Concerto No 2 in A major, S125",
     "Piano Concerto no 2 in A major"),  # Franz Liszt

    # Piano Concerto No 1 in E flat, S.124 — tokenization split: "S. 124"
    # (period+space) splits into two tokens "s" "124", while "S124" or
    # "S.124" tokenize as a single "s124" token. Fold the split form.

    # Piano Sonata in B minor, S.178 — three groups: word-order split
    # ("Sonata…for piano" vs "Piano Sonata") and the same tokenization
    # issue as the Op-1 concerto ("S 178" vs "S.178").

    # Rhapsodie espagnole, S.254 — four groups collapse. The 'jota
    # aragone' form is a BBC typo for 'jota aragonesa'. Plus a 'for
    # piano' scoring annotation, a bare form, and a no-parenthetical form.
    ("Rhapsodie espagnole (Folies d'Espagne et jota aragonesa) S.254 for piano",
     "Rhapsodie espagnole (Folies d'Espagne et jota aragone) S.254"),  # Franz Liszt
    ("Rhapsodie espagnole (Folies d'Espagne et jota aragonesa) S.254",
     "Rhapsodie espagnole (Folies d'Espagne et jota aragone) S.254"),  # Franz Liszt
    ("Rhapsodie Espagnole, S 254",
     "Rhapsodie espagnole (Folies d'Espagne et jota aragone) S.254"),  # Franz Liszt

    # Petrarch Sonnet No 104 (S.161 No.5) — five variants across the Italian
    # "Sonetto del Petrarca" form, English "Petrarch Sonnet", and the
    # alternate "Tre Sonetti del Petrarca" parent-set framing. Same piece.
    ("Petrarch Sonnet No 104 (Années de Pelerinage, année 2, S 161)",
     "Sonetto 104 del Petrarca, 'Années de pèlerinage, deuxième année: Italie, S.161'"),  # Franz Liszt
    ("Sonetto 104 from 'Tre Sonetti del Petrarca' (S.161 No.5)",
     "Sonetto 104 del Petrarca, 'Années de pèlerinage, deuxième année: Italie, S.161'"),  # Franz Liszt
    ("Sonetto 104 (Tre Sonetti del Petrarca), S 161 No 5",
     "Sonetto 104 del Petrarca, 'Années de pèlerinage, deuxième année: Italie, S.161'"),  # Franz Liszt
    ("Petrarch Sonnet no 104 S.161",
     "Sonetto 104 del Petrarca, 'Années de pèlerinage, deuxième année: Italie, S.161'"),  # Franz Liszt

    # Transcendental Étude No 11 'Harmonies du soir' (S.139) — full title
    # form (×4) folds into the bare form (×6). Same piece.
    ("Transcendental study No 11 in D flat major 'Harmonies du soir' - from Etudes d'execution transcendante for piano (S.139)",
     "Transcendental study No 11 in D flat major"),  # Franz Liszt

    # Csárdás macabre — Czardas / Csardas spelling split.
    ("Czardas macabre",
     "Csardas macabre"),  # Franz Liszt

    # Petrarch Sonnet 123 (S.158 No.3) — parent-set framing variant (×2)
    # parallel to the Sonnet 104 case. Same piece.
    ("From 'Années de Pèlerinage' (deuxième année - Italie): Sonetto 123 del Petrarca (S.158 No.3): Io vidi in terra angelici costumi",
     "Sonetto 123 di Petrarca (S.158 No.3): Io vidi in terra angelici costumi"),  # Franz Liszt

    # --- Debussy audit (2026-05-27) -----------------------------------------
    # Heavy French/English title oscillation, scoring annotations, and
    # excerpt-from-parent-set framing. Sibling pieces (Images Set 1 vs
    # Set 2; Gigues/Iberia/Rondes as distinct movements of orchestral
    # Images; Première Rhapsodie clarinet vs Rhapsodie saxophone) all
    # correctly stay split.

    # Danses sacrée et profane / "Two Dances for Harp and Strings" —
    # English translation of the canonical title. Same work (1904).
    ("Two Dances for Harp and Strings",
     "Danse sacree et danse profane for harp and strings"),  # Claude Debussy

    # Première Rhapsodie (clarinet, 1909-10) — four groups collapse:
    # rapsodie/rhapsodie spelling × with/without "for clarinet and
    # orchestra" scoring. All the same piece.
    ("Premiere Rhapsodie",
     "Premiere rapsodie"),  # Claude Debussy
    ("Premiere rapsodie for clarinet and orchestra",
     "Premiere rapsodie"),  # Claude Debussy
    ("Premiere rhapsodie for clarinet and orchestra",
     "Premiere rapsodie"),  # Claude Debussy

    # La Mer (1903-05) — variants on the subtitle "3 symphonic sketches"
    # (English numeric, English spelled-out, French "trois esquisses").
    ("La Mer - 3 symphonic sketches for orchestra",
     "La Mer"),  # Claude Debussy
    ("La mer - three symphonic sketches",
     "La Mer"),  # Claude Debussy
    ("La Mer - trois esquisses symphoniques",
     "La Mer"),  # Claude Debussy

    # La cathédrale engloutie (Préludes Book 1 No 10) — bare title (×15)
    # and "from Preludes Book 1" (×3, no No 10) both fold into the most-
    # aired "from Preludes - Book 1 (No 10)" form.
    ("La cathédrale engloutie",
     "La cathedrale engloutie - (No 10 from Preludes - Book 1)"),  # Claude Debussy
    ("La Cathédrale engloutie - from Préludes Book 1",
     "La cathedrale engloutie - (No 10 from Preludes - Book 1)"),  # Claude Debussy

    # Estampes — "for piano" scoring annotation drops (the set is for
    # solo piano; qualifier is redundant). Plus the "puie" typo (×4)
    # for "Jardins sous la pluie" (one of the three Estampes) folds
    # into the correctly-spelled form.

    # Images for orchestra (1905-12) — "3 Images for orchestra" piece-
    # count variant folds into the bare main form. The three constituent
    # pieces (Gigues, Iberia, Rondes de Printemps) correctly stay as
    # separate excerpt entries.
    ("3 Images for orchestra",
     "Images for orchestra"),  # Claude Debussy

    # Rondes de Printemps (No 3 of orchestral Images) — three groups
    # collapse: with/without "for Orchestra", and a no-"from" variant.
    ("Rondes de Printemps, from 'Images' for Orchestra",
     "Rondes de Printemps, from 'Images'"),  # Claude Debussy
    ("Rondes de Printemps, 'Images'",
     "Rondes de Printemps, from 'Images'"),  # Claude Debussy

    # Sonata for Flute, Viola & Harp (L. 137) — three groups across the
    # L-number tokenization issue ("L. 137" vs "L.137") and a bare form.
    # Same as the Liszt S.124 case.

    # Tarantelle styrienne / Danse — Debussy retitled the piece "Danse"
    # later; the BBC sometimes notes both. Same work.
    ("Tarantelle styrienne (Danse)",
     "Tarantelle styrienne"),  # Claude Debussy

    # --- Debussy curation batch (2026-07-19, fragmentation-scan pass):
    # rec-proven + segment-checked folds. Lesure discipline: targets are
    # SYNTHETIC L-LESS strings where the corpus canonical carries an L-ref
    # (the Arabesque pair). KEPT SPLIT: bare 'Chansons de Bilitis' (the 6
    # airings MIX the 1897 songs with the 1901 musique de scene -- narrator+
    # flutes+harp rosters -- an alias cannot split airings); the two-piano
    # Faune transcription (multi-piano guard); Iberia vs the piano Images
    # (different works); Hommage a Rameau (excerpt of set 1). ---
    ('String Quartet, Op 10', 'String Quartet in G minor, Op 10'),  # Claude Debussy
    ('String Quartet (Op.10) in G minor (Op.10)', 'String Quartet in G minor, Op 10'),  # Claude Debussy (doubled-op typo)
    ('Premiere rapsodie for clarinet and piano', 'Première rapsodie'),  # Claude Debussy (own orchestration; same work, flagged)
    ('Tarantelle styrienne (Danse), orch. Ravel', 'Tarantelle styrienne'),  # Claude Debussy (Ravel literal orchestration; rec p00x9jlx)
    ('Tarantelle styrienne (Danse)Winnipeg Symphony Orchestra', 'Tarantelle styrienne'),  # Claude Debussy (performer leak)
    ('La cathedrale engloutie (Preludes Book 1)', 'La cathedrale engloutie - (No 10 from Preludes - Book 1)'),  # Claude Debussy
    ('Images I', 'Images - set 1 for piano'),  # Claude Debussy (all airings Woodward, piano)
    ('Syrinx', 'Syrinx for solo flute'),  # Claude Debussy (bare corpus-exclusive)
    ('Ronde de printemps (from Images)', "Rondes de Printemps, from 'Images'"),  # Claude Debussy (singular typo)
    ('Trois Nocturnes: Nuages, Fetes, Sirenes', 'Trois Nocturnes'),  # Claude Debussy (member-list; rec p015ffv2)
    ("Trois Nocturnes: Nuages, Fetes, Sirenes (with women's chorus)", 'Trois Nocturnes'),  # Claude Debussy
    ('Nocturnes for orchestra', 'Trois Nocturnes'),  # Claude Debussy (corpus-exclusive)
    ('Arabesque No.2 for harp', 'Arabesque No.2 (Allegretto scherzando), no.2'),  # Claude Debussy (harp = literal transcription; SYNTHETIC L-less target)
    ('Mojca Zlobko (harp)', 'Arabesque No.2 (Allegretto scherzando), no.2'),  # Claude Debussy (performer-as-title leak; rec p030v4x9)
    ('Des pas sur la neige (Preludes Book One, No 6)', 'Des pas sur la neige (Preludes Book 1, no 6)'),  # Claude Debussy (Book One word)
    ('Preludes (excepts)', 'Preludes (excerpts)'),  # Claude Debussy (typo)

    # --- Brahms curation batch (2026-07-19, fragmentation-scan pass; most of
    # the scan score was pre-alias inflation -- Brahms is already heavily
    # consolidated). Rec-proven member-list/citation folds + two bare-Op
    # stragglers. The Three/Seven-Songs & 3-Lieder/3-Hungarian-Dances targets
    # are RECITAL-SELECTION groups (mixed-opus programmes; title-honest,
    # recording-proven -- not real works). KEPT SPLIT: Haydn Variations
    # Op.56b (two pianists verified -- the composer's own two-piano version,
    # separate opus letter); bare 'Tragic Overture' (Panufnik shares it,
    # blast-radius); the 7 Fantasies set vs the No.4 Intermezzo excerpt. ---
    ('Rhapsody for piano in B minor, Op 79', 'Rhapsody for piano (Op.79 No.1) in B minor'),  # Johannes Brahms
    ('Symphony No 4 in E minor', 'Symphony no 4 in E minor, Op 98'),  # Johannes Brahms
    ('Fantasien (Op.116): No.1: Capriccio in D minor; No.2: Intermezzo in A minor; No.3: Capriccio in G minor; No.4: Intermezzo in E major; No.5: Intermezzo in E minor; No.6: Intermezzo in E major; No.7: Capriccio in D minor', '7 Fantasies Op.116 for piano'),  # Johannes Brahms
    ('2 Motets (1.Es ist das Heil uns kommen her ; 2.Schaffe in mir, Gott, ein reines Herz)', '2 Motets, Op 29'),  # Johannes Brahms
    ("Three Songs: 'Meine Liebe ist grün' (Op.63 No.5); 'Wie Melodien zieht es mir' (Op.105 No.1); 'Feldeinsamkeit' (Op.86 No.2)", 'Three Songs'),  # Johannes Brahms
    ("Three Songs: 'Meine Liebe ist grun' (Op.63 No.5) etc", 'Three Songs'),  # Johannes Brahms
    ('Seven Songs: Wir wandelten (Op.96 No.2); Alte Liebe (Op.72 No.1); Das Mädchen spricht (Op.107 No.3); Immer leiser wird mein Schlummer (Op.105 No 2); Meine Liebe ist Grün (Op.63 No.5); Von ewiger Liebe (Op.43 No.1); Der Tod, das ist die kühle Nacht (Op.96 No.1)', 'Seven Songs'),  # Johannes Brahms
    ('Seven Songs: Wir wandelten (Op.96 No.2); Alte Liebe - from 5 Gesäng (Op.72); Das Mädchen spricht (Op.107 No.3); Immer leiser wird mein Schlummer - from 5 Lieder für eine tiefere Stimme (Op.105); Meine Liebe ist Grün - from 9 Lieder und Gesange (Op.63); Von ewiger Liebe (Op.43 No.1); Der Tod, das ist die kühle Nacht - from Vier Lieder (Op.96)', 'Seven Songs'),  # Johannes Brahms
    ('3 Hungarian Dances (originally for piano duet) arr. for string orchestra: No.1 in G minor; No.3 in F major; No.5 in F sharp minor', '3 Hungarian Dances'),  # Johannes Brahms
    ('3 Hungarian Dances (originally for piano duet) arr. for string orchestra (No.1 in G minor; No.3 in F major; No.5 in F sharp minor)', '3 Hungarian Dances'),  # Johannes Brahms
    ('3 Lieder, arr. for cello and piano: An ein Veilchen, No.2 from 5 Songs Op.49; Alte Liebe, No.1 from 5 Songs Op.72; Wie Melodien zieht es mir, No.1 from 5 Songs Op.105', '3 Lieder'),  # Johannes Brahms

    # Clair de lune (Suite Bergamasque No 3) — variants: a "bergamesque"
    # spelling typo, an unambiguous "no 3 from Suite bergamasque for
    # piano" form, and an encore tag. All fold into the main "from
    # Suite Bergamasque" group. Bare "Clair de lune" NOW folds too: the
    # recording+performer data settles the old Fêtes-galantes-song ambiguity —
    # there is NO voice "Clair de lune" in 16 years (every recording is
    # ~4:34-5:34 solo-piano/instrumental, 0/20 bare airings carry a singer),
    # so in this corpus bare "Clair de lune" is unambiguously the piano piece
    # (2026-06-11). Composer-scoped, so the Fauré/Vierne/Diepenbrock "Clair de
    # lune" songs stay in their own groups.
    ("Clair de lune", "Clair de Lune - from Suite Bergamasque (1890)"),  # shared: Claude Debussy / Alphons Diepenbrock
    ("Clair de lune (No.3 from Suite bergamesque for piano)",
     "Clair de Lune - from Suite Bergamasque (1890)"),  # shared: Claude Debussy / Alphons Diepenbrock
    ("Clair de lune (no 3 from Suite bergamasque for piano)",
     "Clair de Lune - from Suite Bergamasque (1890)"),  # shared: Claude Debussy / Alphons Diepenbrock
    ("Clair de lune (encore)",
     "Clair de Lune - from Suite Bergamasque (1890)"),  # shared: Claude Debussy / Alphons Diepenbrock

    # --- Mompou audit (2026-05-27) ------------------------------------------
    # Small corpus (~44 tracks). Composer-name alias Frederic↔Federico
    # was already in place. Two work-key folds:

    # 'Damunt de tu només les flors' (No 5 of Combat del somni, the
    # canonical framing). Bare-form variant lacks the parent-set tag.
    ("Damunt de tu, nomes les flors",
     "Damunt de tu només les flors (Combat del somni)"),  # Federico Mompou

    # Música callada — bare "piano cycle" descriptor variant folds into
    # the bare title. The "excerpts" variant left split — could be any
    # subset of the 28-piece cycle.
    ("Musica callada, piano cycle",
     "Música callada"),  # Federico Mompou

    # --- Grieg Lyric Pieces audit (2026-05-27) ------------------------------

    # Notturno / Nocturne in C, Lyric Pieces Book 5 Op 54 No 4 — three
    # variants (Italian Notturno spelling vs English Nocturne, two
    # punctuation forms of the Op number).
    ("Notturno from Lyric Pieces, Op 54 no 4",
     "Nocturne in C from Lyric Suite, Op.54'4"),  # Edvard Grieg

    # Peer Gynt Suite No 1 Op 46 — bare-form group (no Op number, ×10)
    # folds into the main (×31) Op-tagged form.
    ("Peer Gynt, Suite No.1",
     "Peer Gynt - Suite No 1 Op 46"),  # Edvard Grieg

    # Slåtter Op 72 — "for piano" scoring annotation drop (Slåtter is for
    # solo piano; redundant). ×13 + ×9.

    # 5-piece Selected Lyric Pieces program (Aften / At your feet / Summer
    # / Gone / Remembrances) — the BBC frames the same broadcast set as
    # either "5 Lyric Pieces" or "Selected Lyric Pieces (Lyriske stykker)".
    ("Selected Lyric Pieces (Lyriske stykker): Aften på højfjellet (Evening in the mountains), Op.68 No.4; For dine føtter (At your feet), Op.68 No.3; Sommeraften (Summer's evening), Op.71 No.2; Forbi (Gone), Op.71 No.6; Etterklang (Remembrances), Op.71 No.7",
     "5 Lyric Pieces: Aften på højfjellet (Evening in the mountains) (Op.68 No.4); For dine føtter (At your feet) (Op.68 No.3); Sommeraften (Summer's evening) (Op.71 No.2); Forbi (Gone) (Op.71 No.6); Etterklang (Remembrances) (Op.71 No.7)"),  # Edvard Grieg

    # --- Granados audit (2026-05-27) ----------------------------------------

    # Quejas, o La Maja y el Ruiseñor (Goyescas, Op 11 No 4) — four
    # variants of the famous "Maiden and the Nightingale" piano piece.
    # The full title prefixes "Quejas, o" (the genre title); the BBC
    # sometimes drops "Quejas" and sometimes adds "(The Maiden and the
    # Nightingale)" English translation.
    ("Quejas o la maja y el ruisenor (The Maiden and the Nightingale)",
     "La Maja y el Ruisenor - from Goyescas"),  # Enrique Granados
    ("Quejas o la Maja y el Ruiseñor (from Goyescas)",
     "La Maja y el Ruisenor - from Goyescas"),  # Enrique Granados
    ("La maja y el ruiseñor (The Maiden and the Nightingale) - from Goyescas",
     "La Maja y el Ruisenor - from Goyescas"),  # Enrique Granados
    ("Quejas o la maja y el ruisenor (The Maiden and the Nightingale) - from Goyescas: 7 pieces for piano Op 11 No 4",
     "La Maja y el Ruisenor - from Goyescas"),  # Enrique Granados

    # El Pelele (Goyescas Op 11 No 7) — four variant forms collapse:
    # "excerpt" vs "from", bare title, and short-form "Goyescas - El
    # Pelele".
    ("El Pelele (excerpt Goyescas: 7 pieces for piano, Op 11, No 7)",
     "El Pelele - from Goyescas: 7 pieces for piano (Op.11 No.7)"),  # Enrique Granados
    ("Goyescas - El Pelele",
     "El Pelele - from Goyescas: 7 pieces for piano (Op.11 No.7)"),  # Enrique Granados
    ("El Pelele, from 'Goyescas'",
     "El Pelele - from Goyescas: 7 pieces for piano (Op.11 No.7)"),  # Enrique Granados

    # Allegro de concierto, Op 46 — English "Concert Allegro" translation
    # of the canonical Spanish title.
    ("Concert Allegro, Op 46",
     "Allegro de concierto, Op 46"),  # Enrique Granados

    # Spanish Dances Op 37 No 2 'Oriental(e)' — two variant forms across
    # English "Oriental" vs Italian "Orientale" and with/without the
    # "12 Spanish Dances" parent-set framing.
    ("Orientale Op 37 no 2 from '12 Spanish Dances'",
     "No.2 Oriental in C minor – from Danzas espanolas (Set 1) for piano"),  # Enrique Granados

    # --- Albéniz audit (2026-05-27) -----------------------------------------

    # Asturias (Suite española Op 47 No 5) — three variant forms fold:
    # explicit "Op 47 no 5" framing (the "Leyenda" / piano transcription
    # provenance is well-known), "from" word-order, and a Guitar-instrument
    # provenance-tagged form. All same piece.
    ("Asturias Op 47 no 5",
     "Asturias (Suite española, Op 47) (1887)"),  # Isaac Albeniz
    ("Asturias, from Suite española, Op.47 (1887)",
     "Asturias (Suite española, Op 47) (1887)"),  # Isaac Albeniz
    ("Asturias, from 'Suite española, op. 47' (1887) (Guitar by Antonio de Torres Juardo (1817-1892) in Seville, 1859, and owned by Miquel Llobet (1878-1938))",
     "Asturias (Suite española, Op 47) (1887)"),  # Isaac Albeniz

    # Córdoba (Cantos de España, Op 232 No 4 'Nocturne') — two variants:
    # the bare form (no "Nocturne" descriptor) and a "for piano" scoring
    # variant. All same piece.
    ("Cordoba from 'Cantos de Espana' for piano, Op 232 no 4",
     "Cordoba (Nocturne) from Cantos de Espana (Op.232 No.4)"),  # Isaac Albeniz
    ("Cordoba - from Cantos de Espana (Op.232 No.4)",
     "Cordoba (Nocturne) from Cantos de Espana (Op.232 No.4)"),  # Isaac Albeniz

    # Catalunya & Sevilla from Suite Española No 1 — a 2-piece program;
    # with/without "from" preposition.
    ("Catalunya; Sevilla, Suite Espanola No 1",
     "Catalunya; Sevilla - from Suite Espanola No 1"),  # Isaac Albeniz

    # --- Falla audit (2026-05-27) -------------------------------------------

    # Noches en los jardines de España / Nights in the Gardens of Spain —
    # Spanish ↔ English fold, plus a movement-tagged variant.
    ("Nights in the Gardens of Spain",
     "Noches en los jardines de Espana"),  # Manuel de Falla
    ("Noches en los jardines de España (En el Generalife; Danza lejana; En los jardines de la Sierra de Córdoba)",
     "Noches en los jardines de Espana"),  # Manuel de Falla

    # Ritual Fire Dance (from El amor brujo) — three variants fold: with
    # the parent ballet tag, with "El Amor Brujo" prefix, and the Spanish
    # title "Danza Ritual del Fuego".
    ("Ritual Fire Dance, from 'El amor brujo'",
     "Ritual Fire Dance"),  # Manuel de Falla
    ("El Amor Brujo, Ritual Fire Dance",
     "Ritual Fire Dance"),  # Manuel de Falla
    ("Danza Ritual del Fuego",
     "Ritual Fire Dance"),  # Manuel de Falla

    # Siete canciones populares españolas — English translation "Seven
    # Spanish Popular Songs" folds with the full Spanish title. The
    # trumpet+piano arrangement and the Maréchal cello arrangement
    # (Suite populaire espagnole) stay split as distinct scorings.
    ("Seven Spanish Popular Songs",
     "Siete canciones populares espanolas"),  # Manuel de Falla

    # El amor brujo (full ballet) — three variant forms fold (English
    # translation, year/act detail). The Suite arrangement stays split.
    ("El amor brujo (Love, the Magician) - ballet pantomime",
     "El amor brujo - ballet-pantomime"),  # Manuel de Falla
    ("El amor brujo - ballet pantomime in one act (1920 vers)",
     "El amor brujo - ballet-pantomime"),  # Manuel de Falla

    # Spanish Dance No 1 from La Vida breve — "(Molto Ritmico)" tempo
    # annotation variant folds.
    ("Spanish Dance No.1 (Molto Ritmico) from La Vida Breve",
     "Spanish Dance no 1 from 'La Vida breve'"),  # Manuel de Falla

    # Danza del Molinero (Miller's Dance from El Sombrero de tres picos,
    # the Farruca) — Spanish ↔ English title.
    ("Danza del Molinero",
     "Dance of the Miller from 'El Sombrero de tres picos'"),  # Manuel de Falla

    # --- Turina audit (2026-05-27) ------------------------------------------

    # La Oración del Torero, Op 34 — bare form (no Op number) folds.
    ("La Oración del Torero",
     "La Oración del Torero, Op 34"),  # Joaquin Turina

    # --- Ravel audit (2026-05-27) -------------------------------------------

    # Gaspard de la nuit — "for piano" scoring annotation drop (it's for
    # solo piano; redundant). 33+22 = 55× total.

    # Alborada del gracioso (Miroirs No 4) — three variants fold across
    # with/without "from the suite" framing and a bare form.
    ("Alborada del gracioso - from the suite 'Miroirs' (1905)",
     "Alborada del gracioso 'Miroirs' (1905)"),  # Maurice Ravel
    ("Alborada del gracioso",
     "Alborada del gracioso 'Miroirs' (1905)"),  # Maurice Ravel

    # Une Barque sur l'océan (Miroirs No 3) — parent-set framing variant.
    ("Une Barque sur l'ocean (no 3 from Miroirs)",
     "Une Barque sur l'ocean"),  # Maurice Ravel

    # Violin Sonata in G major (1923-27) — word-order split. Note: the
    # variant key is shared with Pergolesi's Sonata for violin and bc
    # in G; composer-scoped grouping keeps them separate.

    # Ma mère l'Oye (ballet, 1911) — two ballet-form variants collapse.
    # Bare "Ma Mère l'Oye" (×9) and "Mother Goose Suite" (×10) left split
    # — could each refer to the piano duet, orchestral Suite, or ballet.
    ("Ma Mere l'Oye (Mother Goose) - ballet",
     "Ma Mere l'Oye - ballet"),  # Maurice Ravel

    # Tzigane (rapsodie de concert) for violin and piano — three variants
    # collapse across bare title, English "for violin and piano", and
    # French "pour violon et piano". The orchestral-arrangement version
    # stays split as a distinct scoring.
    ("Tzigane - rapsodie de concert for violin and piano",
     "Tzigane"),  # Maurice Ravel
    ("Tzigane - rapsodie de concert pour violon et piano",
     "Tzigane"),  # Maurice Ravel

    # String Quartet in F major — BBC's "Op 35" reference is incorrect
    # (Ravel didn't use opus numbers; M.35 is the Marnat number, possibly
    # mistaken for an Op number). Same work.
    ("String Quartet in F major, Op 35",
     "String Quartet in F major"),  # shared: Maurice Ravel / Valborg Aulin

    # La Valse — "choreographic poem for orchestra" subtitle variant.
    ("La Valse - choreographic poem for orchestra",
     "La Valse"),  # Maurice Ravel

    # --- Poulenc audit (2026-05-27) -----------------------------------------

    # Oboe Sonata (FP 185, 1962) — word-order variant. Variant key is
    # shared with Srul Irving Glick's Oboe Sonata; composer-scoped
    # grouping keeps them separate.

    # Concerto in D minor for Two Pianos and Orchestra (FP 61) — three
    # variants: bare, FP 61, and a "for 2 pianos" no-orchestra form.
    ("Concerto for Two Pianos in D minor, FP 61",
     "Concerto in D minor for 2 pianos and orchestra"),  # Francis Poulenc
    ("Concerto in D minor for 2 pianos",
     "Concerto in D minor for 2 pianos and orchestra"),  # Francis Poulenc

    # Sinfonietta (FP 141) — bare and FP-numbered variants fold. The
    # bare "Sinfonietta" key is shared with several other composers but
    # composer-scoped grouping isolates each.
    ("Sinfonietta, FP 141",
     "Sinfonietta for orchestra"),  # Francis Poulenc
    ("Sinfonietta",
     "Sinfonietta for orchestra"),  # Francis Poulenc

    # Concerto for Organ, Timpani and Strings in G minor (FP 93) — three
    # variants: word-order ("organ, strings and timpani") and "FP.93" vs
    # "FP 93" punctuation.
    ("Concerto for organ, strings and timpani",
     "Concerto for Organ, Timpani and Strings in G minor, FP 93"),  # Francis Poulenc
    ("Concerto for Organ, Timpani and Strings in G minor, FP.93",
     "Concerto for Organ, Timpani and Strings in G minor, FP 93"),  # Francis Poulenc

    # Sept chansons (1936) — "7" vs "Sept" + scoring annotation.
    ("7 chansons, for mixed choir a cappella (1936)",
     "Sept chansons"),  # Francis Poulenc

    # Petites voix — bare form folds into the scoring-annotated form.
    ("Petites voix",
     "Petites voix pour voix egales a capella"),  # Francis Poulenc

    # Capriccio (FP 155, 1953) — based on the Finale of 'Le Bal masqué';
    # two variants fold into the main "for Two Pianos" form.
    ("Capriccio (excerpt Finale of 'Bal masque')",
     "Capriccio for Two Pianos"),  # Francis Poulenc
    ("Capriccio - after Finale of cantata 'Le Bal masqué' vers. for 2 pianos",
     "Capriccio for Two Pianos"),  # Francis Poulenc

    # Les Chemins de l'amour (FP 106) — "valse chantée" scoring/genre
    # annotation variant.
    ("Les Chemins de l'amour (valse chantée for voice and piano)",
     "Les Chemins de l'amour"),  # Francis Poulenc

    # Sextet for piano and winds (FP 100) — "Wind Quintet" word-order
    # variant.
    ("Sextet for Piano and Wind Quintet",
     "Sextet for piano and winds"),  # Francis Poulenc

    # --- Saint-Saëns audit (2026-05-27, via ttn_audit_composer) -------------

    # Bassoon Sonata in G major, Op 168 — word-order split. 37× total.

    # Havanaise, Op 83 — two variants fold: with "for violin and orchestra"
    # scoring and with explicit "in F" key signature. 34× total.
    ("Havanaise for violin and orchestra, Op 83",
     "Havanaise, Op 83"),  # Camille Saint-Saëns
    ("Havanaise For Violin and Orchestra in F, op. 83",
     "Havanaise, Op 83"),  # Camille Saint-Saëns

    # Introduction and Rondo Capriccioso, Op 28 — three variants:
    # scoring annotations and an A-minor key sig variant. 28× total.
    ("Introduction and rondo capriccioso for violin and orchestra, Op 28",
     "Introduction and rondo capriccioso (Op.28), arr. for violin & piano"),  # Camille Saint-Saëns
    ("Introduction and Rondo capriccioso in A minor, Op 28",
     "Introduction and rondo capriccioso (Op.28), arr. for violin & piano"),  # Camille Saint-Saëns

    # Cello Concerto No 1 in A minor, Op 33 — word-order split. 25× total.

    # Danse macabre, Op 40 — "symphonic poem" subtitle variant.
    ("Danse macabre - symphonic poem (Op.40)",
     "Danse macabre, Op 40"),  # Camille Saint-Saëns

    # Symphony No 3 in C minor 'Organ', Op 78 — "Organ" vs "Organ Symphony"
    # parenthetical variant.
    ("Symphony no.3 in C minor, Op.78 'Organ'",
     "Symphony No.3 in C minor Op.78 \"Organ Symphony\""),  # Camille Saint-Saëns

    # Étude en forme de valse (Op 52 No 6) — bare form (no "valse"
    # subtitle) folds into main. The Ysaÿe Caprice transcription stays
    # split (cross-composer title-key overlap flagged by ttn_audit_composer).
    ("Etude in D flat (Op.52 No.6)",
     "Etude in D flat, Op 52, No 6 (Etude en forme de valse)"),  # Camille Saint-Saëns

    # Le Cygne / The Swan (from Le Carnaval des Animaux) — four variants
    # fold across French/English title and parent-set framing.
    ("The Swan, from 'The Carnival of the Animals'",
     "Le Cygne (The Swan) from 'Le Carnaval des Animaux'"),  # Camille Saint-Saëns
    ("Le Cygne (The Swan), from 'The Carnival of the Animals'",
     "Le Cygne (The Swan) from 'Le Carnaval des Animaux'"),  # Camille Saint-Saëns
    ("Le Cygne (The Swan) (excerpt The Carnival des Animaux)",
     "Le Cygne (The Swan) from 'Le Carnaval des Animaux'"),  # Camille Saint-Saëns

    # --- Schumann audit (2026-05-27, via ttn_audit_composer) ----------------

    # Abegg Variations, Op 1 — 3 variants (bare, full "Theme and
    # Variations on the Name Abegg" form). 53× total.
    ("Theme and variations on the Name \"Abegg\", Op 1",
     "Abegg variations Op.1 for piano"),  # Robert Schumann

    # Adagio and Allegro, Op 70 — 4 variants (key sig present/absent,
    # "for horn and piano" scoring, "or other" instrumentation note).
    ("Adagio and allegro, Op 70",
     "Adagio and allegro in A flat major, Op 70"),  # Robert Schumann
    ("Adagio and allegro for horn and piano Op 70 in A flat major",
     "Adagio and allegro in A flat major, Op 70"),  # Robert Schumann
    ("Adagio and allegro in A flat (Op.70), for horn or other and piano",
     "Adagio and allegro in A flat major, Op 70"),  # Robert Schumann

    # Arabeske, Op 18 — 3 variants: word-order ("Arabeske for piano in C
    # major" vs "Arabeske in C major"), plus English "Arabesque" spelling.
    ("Arabesque in C major (Op.18)",
     "Arabeske for piano in C major, Op 18"),  # Robert Schumann

    # Dichterliebe, Op 48 — 4 full-cycle variants fold; single-song
    # excerpts ("Hor' ich das Liedchen" etc.) correctly stay split.
    ("Dichterliebe (Op.48) (song cycle)",
     "Dichterliebe for voice and piano, Op 48"),  # Robert Schumann
    ("Dichterliebe, Op 48 - song-cycle for voice and piano",
     "Dichterliebe for voice and piano, Op 48"),  # Robert Schumann
    ("Dichterliebe, Op 48",
     "Dichterliebe for voice and piano, Op 48"),  # Robert Schumann

    # Manfred Overture, Op 115 — 5 variants across word-order and
    # "incidental music" framing. All the same Overture.
    ("Manfred - Overture to the Incidental Music (Op.115)",
     "Overture (Manfred, Op 115)"),  # Robert Schumann
    ("Manfred - incidental music Op 115 (Overture)",
     "Overture (Manfred, Op 115)"),  # Robert Schumann
    ("Overture to Manfred, Op 115",
     "Overture (Manfred, Op 115)"),  # Robert Schumann
    ("Overture to 'Manfred', Op 115, after Byron",
     "Overture (Manfred, Op 115)"),  # Robert Schumann

    # Symphonische Etuden, Op 13 — 4 variants: bare, "for piano" scoring,
    # and the French alternate title "Etudes en formes de variations".
    ("Etudes en formes de variations, Op 13",
     "Symphonische Etuden for piano, Op 13"),  # Robert Schumann
    ("Etudes en formes de variations Op.13 for piano",
     "Symphonische Etuden for piano, Op 13"),  # Robert Schumann

    # String Quartet No 3 in A, Op 41 No 3 — word-order split + no-key-sig
    # variant. (No 1 in A minor has its own fold below.)
    ("String Quartet no 3 in A, op 41 no 3",
     "String Quartet in A major, Op 41 no 3"),  # Robert Schumann
    # String Quartet No 1 in A minor, Op 41 No 1
    ("String Quartet in A minor, Op 41 no 1",
     "String Quartet no 1 in A minor, Op 41 no 1"),  # Robert Schumann

    # Piano Sonata No 1 in F sharp minor, Op 11 — word-order.

    # Fantasy for violin and orchestra, Op 131 — word-order ("Violin
    # Fantasy" vs "Fantasy for violin and orchestra").
    ("Violin Fantasy in C major, Op 131",
     "Fantasy for violin and orchestra in C major, Op 131"),  # Robert Schumann

    # Piano Trio No 1 in D minor, Op 63 — bare-form (no "No 1") variant.
    ("Piano Trio in D minor (Op.63)",
     "Piano Trio No.1 in D minor (Op.63)"),  # Robert Schumann

    # Märchenbilder, Op 113 — "for viola and piano" scoring annotation.
    ("Marchenbilder for viola and piano, Op 113",
     "Marchenbilder, Op 113"),  # Robert Schumann

    # Faschingsschwank aus Wien, Op 26 — "Phantasiebilder" subtitle
    # variant. Both groups at ×8. The single-movement excerpt (Intermezzo
    # in E flat minor) correctly stays split.
    ("Faschingsschwank aus Wien - Phantasiebilder, Op 26",
     "Faschingsschwank aus Wien, Op 26"),  # Robert Schumann

    # Toccata in C major, Op 7 — word-order split.

    # Variations on a Theme by Clara Wieck (slow movement of Piano Sonata
    # No 3 in F minor, Op 14) — parent-context variant folds into bare.
    ("Variations on a Theme by Clara Wieck (from Schumann's Piano Sonata No 3 in F minor, Op 14)",
     "Variations on a Theme by Clara Wieck"),  # Robert Schumann

    # Symphony No 4 in D minor, Op 120 — the 1841 original version splits
    # into two variants that fold together. Note: the 1841 original and
    # the 1851 published version are MUSICALLY DISTINCT (Schumann revised
    # heavily); the published 1851 form and the unspecified-version main
    # group stay separate from the 1841 original group.
    ("Symphony No. 4 in D minor, op. 120 (original version, 1841)",
     "Symphony No.4 in D minor (Op.120), version original (1841)"),  # Robert Schumann

    # Three Romances, Op 94 — word-order variant.
    ("Three Romances for Oboe and Piano, op. 94",
     "Three Romances Op 94"),  # Robert Schumann
    # Romanze for oboe and piano, Op 94 No 1 (single-romance excerpt) —
    # "Op. 94/1" notation variant.

    # Humoreske, Op 20 — bare-form (no "for piano") variant.

    # Kinderszenen, Op 15 — Träumerei single-piece excerpt (No 7) has
    # several variant keys; all fold to the most-aired form.
    ("Traumerei (Kinderszenen, Op 15 no 7)",
     "Träumerei, from Kinderszenen, Op.15"),  # Robert Schumann
    ("Traumerei (Kinderszenen, Op 15)",
     "Träumerei, from Kinderszenen, Op.15"),  # Robert Schumann
    # Von fremden Ländern und Menschen (No 1) — punctuation variant.
    ("Von fremden Ländern und Menschen (Kinderszenen, op 15)",
     "Von fremden Ländern und Menschen, from 'Kinderszenen, Op 15'"),  # Robert Schumann

    # --- Fauré audit (2026-05-27, via ttn_audit_composer) -------------------
    # Op 33 nocturnes (Nos 1, 2, 3) are distinct sibling pieces under one
    # Op — same pattern as Schubert D.899 impromptus — and correctly stay
    # split.

    # Pavane, Op 50 — "Andante molto moderato" tempo marking variant.
    ("Pavane (Andante molto moderato) in F minor Op 50",
     "Pavane for orchestra Op 50"),  # Gabriel Fauré

    # Nocturne No 6 in D flat, Op 63 — "for piano" scoring annotation drop.

    # Élégie, Op 24 — three variants fold: French "Elegie" spelling and
    # "for cello and piano" scoring annotation.
    ("Elegie (Op.24) arr. for cello and orchestra",
     "Elegy, Op 24"),  # Gabriel Fauré
    ("Elegy for cello and piano (Op.24)",
     "Elegy, Op 24"),  # Gabriel Fauré

    # Pelléas et Mélisande Suite, Op 80 — word-order ("Pelleas Suite"
    # vs "Suite from Pelleas").
    ("Suite from 'Pelléas et Mélisande', Op.80",
     "Pelleas et Melisande suite, Op 80"),  # Gabriel Fauré

    # Piano Trio in D minor, Op 120 — bare-form (no "(1923)" date) variant.

    # --- Brahms audit (2026-05-27, via ttn_audit_composer) ------------------
    # Op 56 Haydn Variations (Op 56a 2-pianos vs Op 56b orchestral) left
    # split per scoring policy. Op 120 Clarinet Sonatas (clarinet/viola
    # alt-scorings) left split for the same reason. Op 118 sibling
    # intermezzi and Op 42 song-set excerpts correctly stay split.

    # Op 115 Clarinet Quintet in B minor — word-order variant.

    # Op 24 Variations and Fugue on a Theme by Handel — 3 variants fold:
    # "for piano" scoring, G.F.-with-dot punctuation, and a no-"25"-count
    # bare-form variant.
    ("25 variations and fugue on a theme by G.F. Handel for piano (Op.24)",
     "25 Variations and fugue on a theme by G F Handel, Op 24"),  # Johannes Brahms
    ("Variations and Fugue on a Theme by Handel, Op 24",
     "25 Variations and fugue on a theme by G F Handel, Op 24"),  # Johannes Brahms

    # Op 79 Rhapsody No 1 in B minor — bare-form variant (without "for
    # piano"). Op 79 No 2 in G minor stays split as the sibling piece.

    # Op 91 Gestillte Sehnsucht (No 1) — 2 variants fold. Geistliches
    # Wiegenlied (No 2) stays split as the sibling song.
    ("Gestillte Sehnsucht Op 91 no 1",
     "Gestillte Sehnsucht for alto, viola and piano Op 91 No 1"),  # Johannes Brahms
    ("Gestillte Sehnsucht - song for alto, viola and piano, Op.91 No.1",
     "Gestillte Sehnsucht for alto, viola and piano Op 91 No 1"),  # Johannes Brahms

    # Op 118 No 2 Intermezzo in A major — "118/2" notation variant.
    ("Intermezzo, op. 118/2",
     "Intermezzo in A major, Op 118 no 2"),  # Johannes Brahms

    # Op 102 Double Concerto for Violin and Cello — 3 variants fold.
    ("Concerto for violin, cello and orchestra in A minor, Op.102",
     "Double Concerto in A minor for Violin and Cello, Op 102"),  # Johannes Brahms
    ("Double Concerto in A minor, Op 102",
     "Double Concerto in A minor for Violin and Cello, Op 102"),  # Johannes Brahms
    ("Concerto in A minor for violin and cello, Op 102",
     "Double Concerto in A minor for Violin and Cello, Op 102"),  # Johannes Brahms

    # Op 34 Piano Quintet in F minor — 2 variants fold. Note: the bare
    # title-key is shared with César Franck's Piano Quintet in F minor
    # (also no-Op); composer-scoped grouping isolates them.
    ("Quintet in F minor Op 34",
     "Piano Quintet in F minor, Op 34"),  # shared: Cesar Franck / Johannes Brahms

    # Op 38 Cello Sonata No 1 in E minor — 2 variants fold.
    ("Cello Sonata in E minor, Op 38",
     "Cello Sonata no 1 in E minor, Op 38"),  # Johannes Brahms

    # Op 89 Gesang der Parzen — 3 variants fold across word-order
    # ("for chorus and orchestra") and bare-form.
    ("Gesang der Parzen  Op 89 for chorus and orchestra",
     "Gesang der Parzen (Song of the Fates), Op 89"),  # Johannes Brahms
    ("Gesang der Parzen (Song of the Fates) for chorus and orchestra (Op.89)",
     "Gesang der Parzen (Song of the Fates), Op 89"),  # Johannes Brahms
    ("Gesang der Parzen, Op.89",
     "Gesang der Parzen (Song of the Fates), Op 89"),  # Johannes Brahms

    # Op 17 4 Songs for women's voices, 2 horns and harp — "Four" spelled
    # out variant.
    ("Four Songs, Op 17",
     "4 Songs for women's voices, 2 horns and harp, Op 17"),  # Johannes Brahms

    # Op 77 Violin Concerto in D major — word-order variant.

    # Op 101 Piano Trio No 3 in C minor — word-order + bare-form variants.
    ("Piano Trio in C minor, op. 101",
     "Piano Trio No 3 in C minor, Op 101"),  # Johannes Brahms

    # Op 76 8 Piano Pieces — "Eight" spelled out + word-order variants.
    ("Eight Piano Pieces (Op.76)",
     "8 Pieces for Piano, Op 76"),  # Johannes Brahms
    ("8 Piano Pieces, Op.76",
     "8 Pieces for Piano, Op 76"),  # Johannes Brahms

    # --- Franck audit (2026-05-27, via ttn_audit_composer) ------------------

    # Violin Sonata in A major, M.8 — word-order variant fold. The
    # cello-arrangement variants stay split as distinct scorings.

    # Prélude, fugue et variation, Op 18 (M.30) — four variants fold
    # across French "et" / English "and" connective and bare/scoring/Op
    # tag variants.
    ("Prelude, fugue et variation for organ (M.30) (Op.18)",
     "Prelude, fugue and variation for organ in B minor (M.30)"),  # Cesar Franck
    ("Prelude, Fugue et Variation Op 18",
     "Prelude, fugue and variation for organ in B minor (M.30)"),  # Cesar Franck
    ("Prelude, fugue and variation, Op.18",
     "Prelude, fugue and variation for organ in B minor (M.30)"),  # Cesar Franck
    # The bare/plural/and-form stragglers (the "et"-variants are deferred to a
    # future et→and conjunction fold). The "[transc. for piano]" recording folds
    # in too via _strip_arrangement_tail (organ-vs-piano is not a work boundary).
    ("Prelude, Fugue and Variation",
     "Prelude, fugue and variation for organ in B minor (M.30)"),  # Cesar Franck
    ("Prelude, Fugue and Variations in B minor (Op. 18)",
     "Prelude, fugue and variation for organ in B minor (M.30)"),  # Cesar Franck
    ("Prelude, fugue and variation for organ in B minor (M.30) (Op.18)",
     "Prelude, fugue and variation for organ in B minor (M.30)"),  # Cesar Franck
    ("Prelude, fugue and variation in B minor (M.30)",
     "Prelude, fugue and variation for organ in B minor (M.30)"),  # Cesar Franck

    # Prélude, Choral et Fugue (M.21) — a piano work, so "for piano" is a
    # redundant scoring tag; bare and "for piano" forms fold to the M.21 form.
    # The "Fugue from …" single-movement excerpt is left split.
    ("Prelude, choral et fugue M.21 for piano",
     "Prelude, Chorale and Fugue, M.21"),  # Cesar Franck
    ("Prelude, Chorale and Fugue",
     "Prelude, Chorale and Fugue, M.21"),  # Cesar Franck

    # Trois Chorals pour grand orgue (M.38/39/40) — French "Choral" vs English
    # "Chorale" is a real spelling split canonical_key can't fold (choral≠chorale
    # as tokens, and a global fold would hit English "Choral Symphony" etc.), plus
    # the redundant "from Trois Chorales pour grande orgue" set-citation. Each
    # Choral is a standalone work; fold the variants onto the dominant per-work
    # form. M.39 (No.2 in B minor) never aired. (Aligning M.40 to one key also
    # un-blocks the strict cross-era bridge for the 2010 Pincemaille airings,
    # whose text work_key differed only by choral/chorale — see p021dz4n.)
    ("Choral No.3 in A minor (M.40) from Trois Chorales pour grande orgue",
     "Choral for organ no 3 in A minor, M.40"),  # Cesar Franck
    ("Chorale No.3 in A minor (M.40), from Trois Chorales pour grande orgue",
     "Choral for organ no 3 in A minor, M.40"),  # Cesar Franck
    ("Chorale no 1 in E",
     "Choral for organ no 1 in E major (M.38)"),  # Cesar Franck

    # Cantabile in B major, M.36 (No 2 of 3 Pièces pour grand orgue
    # M.35-37) — bare M.36 form folds into the parent-set framing.
    ("Cantabile in B major, M.36",
     "Cantabile in B major (M.36), no 2 from 3 Pieces pour grand orgue (M.35-37)"),  # Cesar Franck

    # Piano Quintet in F minor (M.7) — adjacent fold not surfaced by
    # the tool's main detection (no Op/standard-catalogue match) but
    # noticed in passing: the bare "Piano Quintet in F minor" form
    # (already aliased via the Brahms-side retarget) and the M.7-tagged
    # form should both reach the same key within Franck. Note: the
    # work_key ends up labeled with Brahms' "Op 34" — composer-scoping
    # keeps Franck/Brahms separate; the label is opaque.
    ("Quintet for piano and strings (M.7) in F minor",
     "Piano Quintet in F minor, Op 34"),  # shared: Cesar Franck / Johannes Brahms

    # --- Sonata in A major, M.8 / FWV.8 (2026-06-15; see musicological-notes.txt)
    # One work: the violin original + Delsart's cello transcription are the SAME
    # work (a literal transcription — same key, same notes), per the transcription-
    # depth policy. Fragmented 11 ways across catalogue (M.8 / FWV.8 / none),
    # spelling, and instrument (violin / cello / "violin or cello"). Fold all onto
    # the dominant violin form; display picks the violin majority. (226 airings.)
    ("Cello Sonata in A major",
     "Violin Sonata in A major, M.8"),  # Cesar Franck
    ("Violin Sonata in A major",
     "Violin Sonata in A major, M.8"),  # Cesar Franck
    ("Sonata in A major (M.8) for either violin or cello",
     "Violin Sonata in A major, M.8"),  # Cesar Franck
    ("Sonata for cello and piano (M.8) in A major",
     "Violin Sonata in A major, M.8"),  # Cesar Franck
    ("Cello Sonata in A, FWV 8",
     "Violin Sonata in A major, M.8"),  # Cesar Franck
    ("Cello Sonata in A major, FWV.8",
     "Violin Sonata in A major, M.8"),  # Cesar Franck
    ("Sonata in A major for violin or cello and piano",
     "Violin Sonata in A major, M.8"),  # Cesar Franck
    ("Sonata in A major for either violin or cello",
     "Violin Sonata in A major, M.8"),  # Cesar Franck
    ("Violihn Sonata (M.8) in A major",
     "Violin Sonata in A major, M.8"),  # Cesar Franck
    ("Violin Sonata in A major, M 8",
     "Violin Sonata in A major, M.8"),  # Cesar Franck

    # --- Keyboard-instrument merge (2026-06-15; see musicological-notes.txt) --
    # Policy: keyboard instruments (organ/piano/harpsichord/fortepiano) are
    # interchangeable for one player on one piece -> NOT a work boundary; merge
    # "keyboard" vs "piano" variants of one work. (Non-keyboard families —
    # violin/cello etc. — stay split.) Catalogued keyboard works already merge
    # via the § path; these 7 are the token-sort-path residue (Haydn trios/
    # sonatas + one Scarlatti). Fold the minority form into the per-work dominant.
    ("3 Sonatas for keyboard",
     "3 Sonatas for piano"),  # Domenico Scarlatti
    ("Sonata for piano (H.16.23) in F major",
     "Sonata in F major H.16.23 for keyboard"),  # Joseph Haydn
    ("Trio for piano and strings (H.15.27) in C major",
     "Trio for keyboard and strings in C major (H.15.27)"),  # Joseph Haydn
    ("Piano Trio in E flat major, H.15.10",
     "Trio in E flat major (H.15.10) for keyboard and strings"),  # Joseph Haydn
    ("Piano Sonata in B flat major, H.16.41",
     "Sonata in B flat major H.16.41 for keyboard"),  # Joseph Haydn
    ("Piano Trio in A major H.15.18",
     "Trio for keyboard and strings (H.15.18) in A major"),  # Joseph Haydn
    ("Piano Trio in E major (H.15.28)",
     "Trio for keyboard and strings H.15.28 in E major"),  # Joseph Haydn

    # --- Bartók audit (2026-05-27, via ttn_audit_composer) ------------------
    # Sz.56 vs Sz.68 (piano original vs orchestral arrangement) stays
    # split per scoring policy. For Children Sz.42 excerpt programs and
    # Mikrokosmos selections stay split as distinct programs.

    # Sz.40 String Quartet No 1 in A minor — key-signature variant.
    ("String Quartet No. 1 in A minor, Sz. 40",
     "Quartet for strings no. 1 (Sz.40)"),  # Bela Bartok

    # Sz.106 Music for Strings, Percussion and Celesta — Sz-tagged variant.
    ("Music for strings, percussion and celesta, Sz.106",
     "Music for Strings, Percussion and Celesta"),  # Bela Bartok

    # Sz.93 4 Hungarian Folk Songs — 3 variants (date variant + alt Magyar
    # title).
    ("4 Hungarian folk songs for chorus, Sz.93",
     "4 Hungarian folk songs for chorus, Sz 93, 1930"),  # Bela Bartok
    ("Hungarian Folksongs (Magyar népdalok), Sz. 93",
     "4 Hungarian folk songs for chorus, Sz 93, 1930"),  # Bela Bartok

    # Sz.95 Piano Concerto No 2 in G — bare-key-sig variant.
    ("Piano Concerto No 2 (Sz.95)",
     "Piano Concerto No. 2 in G, Sz. 95"),  # Bela Bartok

    # --- Tchaikovsky audit (2026-05-27, via ttn_audit_composer) -------------
    # Op 33 Rococo Variations: "original version" (Tchaikovsky's autograph,
    # pre-Fitzenhagen) stays split from the Fitzenhagen-edited standard
    # version per existing version-distinction precedent (Schumann Op 120).
    # Op 71a Nutcracker Suite excerpts and Op 24 Eugene Onegin per-aria
    # excerpts stay split (excerpt-vs-whole boundary).

    # Romeo and Juliet, fantasy overture — 3 variants fold. The 1880
    # version IS the standard published form (Tchaikovsky's final
    # revision).
    ("Romeo and Juliet fantasy overture (1880 version)",
     "Romeo and Juliet - fantasy overture"),  # Peter Ilyich Tchaikovsky
    ("Romeo and Juliet, fantasy overture after Shakespeare",
     "Romeo and Juliet - fantasy overture"),  # Peter Ilyich Tchaikovsky
    ("Romeo and Juliet - fantasy overture vers. standard",
     "Romeo and Juliet - fantasy overture"),  # Peter Ilyich Tchaikovsky

    # Op 33 Variations on a Rococo Theme — standard-version variants
    # fold. The "(original version)" form correctly stays split.
    ("Variations on a Rococo Theme, Op.33",
     "Variations on a rococo theme for cello and String orchestra, Op 33"),  # Peter Ilyich Tchaikovsky
    ("Variations on a rococo theme in A for cello and orchestra, Op 33",
     "Variations on a rococo theme for cello and String orchestra, Op 33"),  # Peter Ilyich Tchaikovsky
    ("Variations on a Roccoco Theme, Op 33, for cello and orchestra",
     "Variations on a rococo theme for cello and String orchestra, Op 33"),  # Peter Ilyich Tchaikovsky
    ("Variations on a Rococo Theme for cello and orchestra, Op.33",
     "Variations on a rococo theme for cello and String orchestra, Op 33"),  # Peter Ilyich Tchaikovsky
    # 'roccoco' typo straggler surfaced by ttn_duplicates (2026-06-02)
    ("Variations on a roccoco theme in A, for cello and orchestra (Op.33)",
     "Variations on a rococo theme for cello and String orchestra, Op 33"),  # Peter Ilyich Tchaikovsky

    # Op 11 String Quartet No 1 in D — word-order. Andante Cantabile
    # excerpt correctly stays split.

    # Op 61 Suite No 4 'Mozartiana' — 2 variants fold.
    ("Suite No.4 in G major for orchestra (Op.61), 'Mozartiana'",
     "Suite No.4 in G major, Op 61, 'Mozartiana'"),  # Peter Ilyich Tchaikovsky
    ("Suite No.4, Op.61, 'Mozartiana'",
     "Suite No.4 in G major, Op 61, 'Mozartiana'"),  # Peter Ilyich Tchaikovsky

    # Op 48 Serenade for Strings — 2 word-order variants fold.
    ("Serenade in C major for strings (Op.48)",
     "Serenade for string orchestra in C major Op.48"),  # Peter Ilyich Tchaikovsky
    ("Serenade in C, op. 48",
     "Serenade for string orchestra in C major Op.48"),  # Peter Ilyich Tchaikovsky

    # Op 18 The Tempest (Burya) — 3 variants fold across Russian/English
    # title and "after Shakespeare" annotation.
    ("Burya  - symphonic fantasia after Shakespeare, Op 18",
     "The Tempest (Burya) - symphonic fantasia Op 18"),  # Peter Ilyich Tchaikovsky
    ("Burya (The Tempest) - symphonic fantasia after Shakespeare (Op.18)",
     "The Tempest (Burya) - symphonic fantasia Op 18"),  # Peter Ilyich Tchaikovsky
    ("The Tempest, op. 18, fantasy after Shakespeare",
     "The Tempest (Burya) - symphonic fantasia Op 18"),  # Peter Ilyich Tchaikovsky

    # Op 59 Dumka 'Russian rustic scene' — "for piano" scoring annotation.

    # Op 78 Voyevoda / Wojewode (Symphonic Ballad) — Russian/German title.
    ("Wojewode, symphonic ballad, Op 78",
     "Voyevoda - Symphonic Ballad Op 78"),  # Peter Ilyich Tchaikovsky
    ("The Voyevoda, symphonic ballad (Op.78)",
     "Voyevoda - Symphonic Ballad Op 78"),  # Peter Ilyich Tchaikovsky

    # Op 13 Symphony No 1 'Winter Daydreams' / Rêves d'hiver French
    # variant skipped: the variant key is shared with Méhul (×10) while
    # Tchaikovsky has only ×2 — below tail threshold and the cross-
    # composer entanglement makes the internal relabel misleading.

    # Waltz of the Flowers (from The Nutcracker) — word-order variant.
    ("The Nutcracker: Waltz of the Flowers",
     "Waltz of the Flowers (from The Nutcracker)"),  # Peter Ilyich Tchaikovsky

    # Op 24 Eugene Onegin — Introduction & waltz program (the most-aired
    # excerpt combination); two variant forms fold. Other excerpts
    # (Polonaise, Lensky's aria, Waltz Scene alone) correctly stay split.
    ("Eugene Onegin, Op 24 (Introduction & waltz)",
     "Eugene Onegin, Op 24 (Act 2: Introduction & waltz)"),  # Peter Ilyich Tchaikovsky
    ("Introduction and waltz from 'Eugene Onegin' - lyric scenes in 3 acts (Op.24)",
     "Eugene Onegin, Op 24 (Act 2: Introduction & waltz)"),  # Peter Ilyich Tchaikovsky

    # Op 70 Souvenir de Florence — "Allegro vivace" 4th-movement excerpt;
    # mvt/mvmt typo fold within the excerpt group.
    ("Souvenir de Florence (4th mvmt, 'Allegro vivace') Op 70",
     "Souvenir de Florence (4th mvt, 'Allegro vivace') Op 70"),  # Peter Ilyich Tchaikovsky

    # --- Dvořák audit (2026-05-27, via ttn_audit_composer) ------------------

    # Slavonic Dance Op 72 No 2 in E minor (= No 10 of the complete set
    # of 16) — multiple variants fold across full-set vs Op-only
    # numbering and the "Starodávny" nickname.
    ("Slavonic Dance no 10 in E minor Op 72 no 2",
     "Slavonic Dance in E minor, Op.72 no.2"),  # Antonin Dvorak
    ("Slavonic Dance No 10 in E minor, Op 72 no 2, 'Starodavny'",
     "Slavonic Dance in E minor, Op.72 no.2"),  # Antonin Dvorak
    ("Slavonic dance no 10 in E minor for piano duet, Op 72 no 2",
     "Slavonic Dance in E minor, Op.72 no.2"),  # Antonin Dvorak
    ("Slavonic Dance No.9 in B minor, Op.72 No.1",
     'Slavonic Dance No.9 in B major (Op.72 No.1) orch. composer [orig. pf duet]'),  # Antonin Dvorak

    # Slavonic Dance Op 72 No 4 in D flat major (= No 12 of 16) —
    # Slavonic Dance Op 46 No 2 in E minor — bare-form (no key sig).
    ("Slavonic Dance (Op.46 No.2)",
     "Slavonic Dance in E minor, Op 46 no 2"),  # Antonin Dvorak

    # Slavonic Dance Op 46 No 8 in G minor — orchestrated variant fold.
    ("Slavonic Dance in G minor, Op 46 No 8, orch composer (orig for pf duet)",
     "Slavonic Dance No. 8 in G minor, op. 46"),  # Antonin Dvorak

    # Op 96 American Quartet — only ×2 excerpt currently splits; movement
    # excerpts correctly stay split.

    # Op 81 Piano Quintet in A major — bare-form (no "no 2"). Same work
    # as the indexed form. The Scherzo movement excerpt correctly stays
    # split.
    ("Piano Quintet no 2 in A major, Op 81",
     "Piano Quintet in A major, Op 81"),  # Antonin Dvorak
    ("Quintet no. 2 in A major Op.81 for piano and strings",
     "Piano Quintet in A major, Op 81"),  # Antonin Dvorak

    # Op 104 Cello Concerto in B minor — 2 word-order variants fold.
    ("Concerto for cello and orchestra no.2 (Op.104) in B minor",
     "Cello Concerto in B minor, Op 104"),  # Antonin Dvorak

    # Op 44 Wind Serenade in D minor — 3 variant forms fold.
    ("Serenade for wind instruments in D minor Op 44",
     "Wind Serenade in D minor, Op 44"),  # Antonin Dvorak
    ("Serenade for winds in D minor, Op.44",
     "Wind Serenade in D minor, Op 44"),  # Antonin Dvorak
    ("Serenade in D minor, op. 44",
     "Wind Serenade in D minor, Op 44"),  # Antonin Dvorak

    # Op 90 'Dumky' Piano Trio No 4 — 3 variants fold (with/without "no 4"
    # and word-order).
    ("Trio in E minor, \"Dumky\" Op 90",
     "Piano Trio no 4 in E minor, Op 90 'Dumky'"),  # Antonin Dvorak
    ("Trio for piano and strings no 4, Op 90 \"Dumky\"",
     "Piano Trio no 4 in E minor, Op 90 'Dumky'"),  # Antonin Dvorak
    ("Piano Trio in E minor 'Dumky', Op 90",
     "Piano Trio no 4 in E minor, Op 90 'Dumky'"),  # Antonin Dvorak

    # 'Song to the Moon' from Rusalka, Op 114 — bare-form (no Op) folds.
    ("Song to the Moon from Rusalka",
     "Song to the Moon from Rusalka, Op 114"),  # Antonin Dvorak

    # Op 11 Romance in F minor — 2 variants fold (word-order and bare).
    ("Romance for violin and orchestra in F minor, Op 11",
     "Romance Op 11 in F minor vers. for violin and piano"),  # Antonin Dvorak
    ("Romance in F minor, Op 11",
     "Romance Op 11 in F minor vers. for violin and piano"),  # Antonin Dvorak

    # Op 59 No 4 Legend in C major — 2 variants fold (with "Molto
    # maestoso" tempo marking and "From Legends" parent-set framing).
    ("From \"Legends\" Op 59 No 4 (Molto maestoso) in C major",
     "Legend in C major, Op 59 no 4"),  # Antonin Dvorak
    ("Legend in C major (Molto maestoso) (Op.59 No.4)",
     "Legend in C major, Op 59 no 4"),  # Antonin Dvorak

    # Op 22 Serenade for Strings in E major — 2 variants fold. Larghetto
    # movement excerpt correctly stays split.
    ("String Serenade in E, op. 22",
     "Serenade for strings in E major, Op.22"),  # Antonin Dvorak
    ("Serenade for String Orchestra in E major, Op.22, B.52",
     "Serenade for strings in E major, Op.22"),  # Antonin Dvorak

    # Op 65 Piano Trio No 3 in F minor — word-order variant.

    # Op 21 Piano Trio No 1 in B flat major — word-order variant.

    # Op 75 4 Romantic Pieces — "Four" spelled out variant. Single-piece
    # excerpt (Allegro appassionato) correctly stays split.

    # Op 91 In Nature's Realm Overture — "concert overture" subtitle variant.
    ("In Nature's Realm, op. 91, concert overture",
     "In Nature's Realm (Overture), Op 91"),  # Antonin Dvorak

    # --- Rachmaninov audit (2026-05-27, via ttn_audit_composer) -------------

    # Op 34 No 14 Vocalise — "for orchestra" scoring annotation + apostrophe
    # notation. Main group already merges multiple arrangement scorings
    # via _strip_arrangement_tail; "for orchestra" doesn't trigger the
    # strip (no "arr." marker) so needs explicit alias.
    ("Vocalise, Op 34 No 14 for orchestra",
     "Vocalise (Op.34 No.14)"),  # Sergey Rachmaninov

    # Op 35 The Bells (Kolokola) — 2 variant forms fold (poem subtitle +
    # "choral symphony" alt-subtitle).
    ("The Bells - poem for soloists, mixed choir and symphony orchestra (Op.35)",
     "The Bells (Kolokola) for soloists, chorus and orchestra, Op 35"),  # Sergey Rachmaninov
    ("The Bells, op. 35, choral symphony",
     "The Bells (Kolokola) for soloists, chorus and orchestra, Op 35"),  # Sergey Rachmaninov

    # Op 42 Variations on a Theme of Corelli — "for piano" scoring fold.

    # Op 43 Rhapsody on a Theme of Paganini — "for piano and orchestra"
    # scoring fold.
    ("Rhapsody on a theme of Paganini Op.43 for piano and orchestra",
     "Rhapsody on a Theme of Paganini, Op 43"),  # Sergey Rachmaninov

    # Op 17 Suite No 2 for 2 pianos — bare-form (no scoring) variant.
    ("Suite No 2 Op 17",
     "Suite no 2 for 2 pianos, Op 17"),  # Sergey Rachmaninov

    # Op 19 Cello Sonata in G minor — bare-form word-order + Andante
    # movement excerpt variants. The Andante excerpt stays split from
    # the whole sonata; "(Andante)" and "from ... (Andante)" excerpt
    # forms fold together.
    ("Andante from Cello Sonata in G minor, Op 19",
     "Cello Sonata in G minor Op 19 (Andante)"),  # Sergey Rachmaninov

    # Op 11 6 Duets for piano 4 hands — "Pieces" vs "Duets" + "Six"
    # spelled out variants.
    ("Pieces for four hands (Op.11)",
     "6 Duets Op 11 for piano 4 hands"),  # Sergey Rachmaninov
    ("Six Pieces for four hands, Op 11",
     "6 Duets Op 11 for piano 4 hands"),  # Sergey Rachmaninov

    # Op 37 Vespers (All-Night Vigil) — bare-form variant. Excerpt
    # programs correctly stay split.
    ("Vespers (All-Night Vigil), Op 37",
     "Vespers (All-night vigil) for chorus (Op.37)"),  # Sergey Rachmaninov

    # Op 40 Piano Concerto No 4 in G minor — word-order variant.

    # Op 22 Variations on a Theme of Chopin — "for piano" scoring fold.

    # Op 36 Piano Sonata No 2 in B flat minor — word-order variant.
    ("Sonata No.2 in B flat Minor (Op.36)",
     "Piano Sonata No. 2 in B flat minor, op. 36"),  # Sergey Rachmaninov

    # Op 12 Caprice bohémien — "Capriccio on Gypsy Themes" alt-subtitle.
    ("Caprice bohémien, Op 12 (Capriccio on Gypsy Themes)",
     "Caprice Bohemien, Op 12"),  # Sergey Rachmaninov

    # 2 Songs (When Night Descends / Oh stop thy singing maiden fair)
    # — "Two" spelled out variant.

    # Op 39 Etudes-Tableaux — excerpts I-VI program with 2 variant
    # framings. Single-excerpt entries (No 3, No 8 etc.) stay split.
    ("Etudes-Tableaux (Op.39) (I to VI only)",
     "Etudes-Tableaux, Op 39 (excerpts - I to VI)"),  # Sergey Rachmaninov

    # --- Prokofiev audit (2026-05-27, via ttn_audit_composer) ---------------
    # Op 64 Romeo and Juliet — many generic "(excerpts)" forms whose
    # contents aren't specified left split as distinct broadcast units.
    # Op 115 Solo Violin Sonata movement excerpts (single movements
    # split across multiple notation variants) too risky to bulk-fold.
    # Op 33 Love for Three Oranges Suite vs Scherzo&March stay split.

    # Op 63 Violin Concerto No 2 — bare-key-sig variant.
    ("Violin Concerto No 2, Op 63",
     "Violin Concerto No 2 in G minor, Op 63"),  # Sergey Prokofiev

    # Op 60 Lieutenant Kijé Suite — word-order. Troika excerpt stays
    # split.
    ("Lieutenant Kije Suite, Op.60",
     "Lieutenant Kije - suite for orchestra, Op 60"),  # Sergey Prokofiev

    # Op 83 Piano Sonata No 7 — word-order. Precipitato 3rd-mvt excerpt
    # stays split.

    # Op 94/94a/94bis Violin Sonata No 2 in D — Prokofiev's own violin
    # arrangement of his Op 94 flute sonata is catalogued as both 94a
    # and 94bis. Same work, two valid catalogue notations.
    ("Violin Sonata No. 2 in D, op. 94a",
     "Sonata for violin and piano no. 2 (Op.94bis) in D major"),  # Sergey Prokofiev

    # Op 100 Symphony No 5 — bare-key-sig variant.
    ("Symphony No.5 (Op.100)",
     "Symphony No. 5 in B flat, op. 100"),  # Sergey Prokofiev

    # Op 80 Violin Sonata No 1 in F minor — word-order.

    # Op 12 No 7 Prelude (from 10 Pieces for Piano) — bare-form variant.
    ("Prelude Op.12 No.7",
     "Prelude - No. 7 from 10 Pieces for piano (Op.12)"),  # Sergey Prokofiev

    # --- Janáček audit (2026-05-27, via ttn_audit_composer) -----------------
    # Kreutzer Sonata string-orchestra arrangement stays split per scoring
    # policy.

    # Taras Bulba (rhapsody for orchestra) — bare-form variant.
    ("Taras Bulba - Rhapsody",
     "Taras Bulba - rhapsody for orchestra"),  # Leos Janacek

    # Pohádka (Fairy Tale) for cello and piano — 4 variants fold across
    # Czech-only "Pohadka", with/without English "(Fairy Tale)" subtitle,
    # and with/without "for cello and piano" scoring. All the same work.
    ("Pohadka",
     "Pohádka (Fairy Tale)"),  # Leos Janacek
    ("Pohadka for cello and piano",
     "Pohádka (Fairy Tale)"),  # Leos Janacek
    ("Pohadka (Fairy tale) for cello and piano",
     "Pohádka (Fairy Tale)"),  # Leos Janacek

    # Šumařovo dítě (The Fiddler's Child) — "ballad for orchestra"
    # scoring annotation variant.
    ("The fiddler's child (Sumarovo dite) - ballad for orchestra",
     "Sumarovo dite (The Fiddler's Child)"),  # Leos Janacek

    # --- Sibelius audit (2026-05-27, via ttn_audit_composer) ----------------
    # Op 14 Rakastava arrangements (chorus vs string orchestra) stay split
    # per scoring policy. Op 22 sibling pieces (Lemminkäinen's Return vs
    # The Swan of Tuonela) correctly stay split.

    # Op 49 Pohjola's daughter — bare-form (no subtitle).
    ("Pohjola's Daughter, Op 49",
     "Pohjola's daughter - symphonic fantasia, Op 49"),  # Jean Sibelius

    # Op 11 Ballad from Karelia Suite — "Ballad (Karelia suite)" vs
    # "Ballad from Karelia suite".
    ("Ballad from Karelia suite, Op 11",
     "Ballad (Karelia suite, Op 11)"),  # Jean Sibelius

    # Op 112 Tapiola — "symphonic poem" / "tone poem" subtitle variants.
    ("Tapiola - symphonic poem, Op. 112 (1926)",
     "Tapiola, Op 112"),  # Jean Sibelius
    ("Tapiola - tone poem Op.112",
     "Tapiola, Op 112"),  # Jean Sibelius

    # Op 22 Lemminkäinen's Return (No 4 of the Suite) — "from Lemminkainen
    # Suite" parent-set framing variant.
    ("Lemminkainen's Return - No.4 from Lemminkainen Suite, Op.22",
     "Lemminkainen's Return (Lemminkainen Suite) Op 22"),  # Jean Sibelius

    # Op 22 Lemminkäinen Suite (full set) — bare-form variant.
    ("Lemminkainen Suite, op 22",
     "Lemminkainen Suite: 4 Legends from the Kalevala for orchestra (Op 22)"),  # Jean Sibelius

    # Op 93 Jordens sang (Song of the Earth) — "cantata for chorus and
    # orchestra" scoring annotation.
    ("Jordens sang (Song of the Earth) - cantata for chorus and orchestra (Op.93)",
     "Jordens sang (Song of the Earth), Op 93"),  # Jean Sibelius

    # Op 114 5 Esquisses for piano — bare-form variant.
    ("Esquisses, Op 114",
     "5 Esquisses for piano, Op 114"),  # Jean Sibelius

    # Op 44 Valse triste (from Kuolema) — 4 variant forms collapse.
    ("Valse Triste - from Kuolemo (Op.44 No.1)",
     "Valse triste, from Kuolema, incidental music Op 44"),  # Jean Sibelius
    ("Valse Triste, from 'Kuolema, Op 44'",
     "Valse triste, from Kuolema, incidental music Op 44"),  # Jean Sibelius
    ("Valse triste (Kuolema - incidental music, Op 44)",
     "Valse triste, from Kuolema, incidental music Op 44"),  # Jean Sibelius
    ("Valse triste Op 44 no 1",
     "Valse triste, from Kuolema, incidental music Op 44"),  # Jean Sibelius

    # Op 42 Romance for strings in C major — word-order variant.
    ("Romance for string orchestra in C major (Op.42)",
     "Romance for strings in C major, Op 42"),  # Jean Sibelius

    # Op 51 Belshazzar's Feast Suite — "incidental music" framing variant.
    ("Belshazzar's Feast - suite from the incidental music, Op 51",
     "Belshazzar's feast suite, Op 51"),  # Jean Sibelius

    # Op 40 10 Pensées lyriques for piano — bare-form variant (no "10").
    ("Pensees Lyriques, Op.40",
     "10 Pensees lyriques for piano, Op 40"),  # Jean Sibelius

    # Op 70 Luonnotar — "symphonic poem" / "tone poem" subtitle variants.
    ("Luonnotar, Op 70, symphonic poem",
     "Luonnotar, Op 70"),  # Jean Sibelius
    ("Luonnotar, tone poem, Op 70",
     "Luonnotar, Op 70"),  # Jean Sibelius

    # Andante Festivo — bare-form (no scoring) variant. Caught by the
    # tool's new subset-detection pass.
    ("Andante Festivo",
     "Andante Festivo for strings and timpani"),  # Jean Sibelius

    # Op 105 Symphony No 7 in C — "(in one continuous movement)"
    # parenthetical variant.
    ("Symphony No 7 in C major Op 105 (in one continuous movement)",
     "Symphony no 7 in C major, Op 105"),  # Jean Sibelius

    # --- Handel audit (2026-05-28, via ttn_audit_composer) ------------------
    # 46 candidate clusters from the tool. This batch handles the high-
    # confidence merges: catalogue↔token bridges, catalogue-path quirks
    # (key-sig appendage, phantom numbers), HWV-bearing/no-HWV splits,
    # and multi-phrasing aria folds. Skipped: HWV.362 violin/oboe alt
    # scoring (precedent exists but warrants a separate explicit pass),
    # Lascia la spina (existing aliases need retarget decision), Aure deh
    # per pieta scena vs aria-only boundary, set-catalogue siblings.

    # HWV.363a / Op 1 no 5 F major — the existing line ~1092 alias was
    # retargeted. The "Oboe Sonata" variant needs its own bridge since it
    # tokenises with "oboe" and skips that alias's source key.
    ("Oboe Sonata in F major Op 1 No 5",
     "Sonata in F major, Op 1 no 5 (HWV.363a) vers. oboe & bc"),  # George Frideric Handel

    # HWV.362 / Op 1 no 4 A minor — Pellerin's no-HWV oboe variants fold
    # into the HWV-bearing canonical (which already merges Lorenz violin
    # forms + the HWV-coded oboe form via line ~2286). Extends the
    # documented scoring-policy precedent (BWV.1056 / HWV.362 composer-
    # authored alt-scoring fold). Roed's recorder forms in
    # §hwv362|362|aminor stay separate for now — the broader "should all
    # three scorings collapse?" question is parked. See [[hwv362-alt-
    # scoring-deferred]] memory note for the open question.
    ("Oboe Sonata Op 1 No 4",
     "Violin Sonata in A minor (Op.1 No.4) (HWV.362)"),  # George Frideric Handel
    ("Oboe Sonata in A minor Op.1 No.4",
     "Violin Sonata in A minor (Op.1 No.4) (HWV.362)"),  # George Frideric Handel

    # HWV.365 / Op 1 no 7 C major. 2× no-HWV token-sort → 14× catalogue.
    ("Sonata in C major, Op 1 No 7",
     "Sonata for recorder and continuo (HWV.365) (Op.1`7) in C major"),  # George Frideric Handel

    # HWV.399 / Op 5 no 4 G major. 4× no-HWV token-sort → 8× catalogue.
    ("Trio Sonata in G major, Op 5 No 4",
     "Trio Sonata in G major (HWV 399) for 2 violins, viola and continuo Op 5 No 4"),  # George Frideric Handel

    # HWV.430 — Aria with Variations 'Harmonious Blacksmith'. The 4×
    # variant titled with "Piano Suite No.5" pushes a phantom "5" into
    # the catalogue path (§hwv430|430,5|e). Fold into the bare canonical.
    ("Aria with variations from Piano Suite No.5 in E major (HWV.430) \"The harmonious blacksmith\"",
     "Aria with Variations, HWV 430 'Harmonious Blacksmith'"),  # George Frideric Handel
    ("Aria with Variations from Piano Suite No.5 in E major, HWV.430, \"The harmonious blacksmith\"",
     "Aria with Variations, HWV 430 'Harmonious Blacksmith'"),  # George Frideric Handel
    ("Aria with Variations from Piano Suite No.5 in E major (HWV.430) \"The harmonious blacksmith\"",
     "Aria with Variations, HWV 430 'Harmonious Blacksmith'"),  # George Frideric Handel

    # HWV.237 — Laudate pueri Dominum. Key-signature appendage "in D"
    # on a multi-movement work that has no canonical home key. Same
    # case as Dixit Dominus in G minor (yesterday's batch).
    ("Laudate pueri Dominum in D, HWV 237",
     "Laudate pueri Dominum, HWV 237"),  # George Frideric Handel

    # HWV.45 — Gentle Morpheus from Alceste. 3× HWV-bearing form folds
    # into the 27× no-HWV plurality.
    ("Gentle Morpheus, son of night (Calliope's song) from 'Alceste' (HWV.45)",
     "Gentle Morpheus, son of night (Calliope's song) from Alceste"),  # George Frideric Handel
    ("Gentle Morpheus, Son of Night (Calliope's song) from 'Alceste' (HWV.45)",
     "Gentle Morpheus, son of night (Calliope's song) from Alceste"),  # George Frideric Handel

    # --- Handel arias from Giulio Cesare (2026-05-28) -----------------------

    # Va tacito e nascosto — Caesar's aria, Act 1 Sc 9. Three phrasings.
    ("'Va tacito e nascosto' (Giulio Cesare)",
     "Caesar's aria: 'Va tacito e nascosto' (from 'Giulio Cesare in Egitto', Act 1 Sc.9)"),  # George Frideric Handel
    ("'Va tacito e nascosto' (from Giulio Cesare in Egitto)",
     "Caesar's aria: 'Va tacito e nascosto' (from 'Giulio Cesare in Egitto', Act 1 Sc.9)"),  # George Frideric Handel
    ("'Va tacito e nascosto' from 'Giulio Cesare in Egitto'",
     "Caesar's aria: 'Va tacito e nascosto' (from 'Giulio Cesare in Egitto', Act 1 Sc.9)"),  # George Frideric Handel

    # Piangerò la sorte mia — Cleopatra's aria, Act 3 Sc 3. All five
    # phrasings now fold to the plurality canonical. The "Giulio Cesare,
    # HWV 17" parenthetical form (4×) was previously a catalogue-path FP
    # grouped with the §hwv17|17| suite; the _has_parent_work_reference
    # gate routes it to the token-sort path now, so this alias is safe.
    ("Piangerò la sorte mia (Giulio Cesare, HWV 17)",
     "Cleopatra's aria: 'Piangero la sorte mia' - from \"Giulio Cesare\" (Act 3 Sc.3)"),  # George Frideric Handel
    ("Piangerò la sorte mia, from 'Giulio Cesare, HWV.17'",
     "Cleopatra's aria: 'Piangero la sorte mia' - from \"Giulio Cesare\" (Act 3 Sc.3)"),  # George Frideric Handel
    ("Piangerò la sorte mia (excerpt 'Giulio Cesare', HWV 17)",
     "Cleopatra's aria: 'Piangero la sorte mia' - from \"Giulio Cesare\" (Act 3 Sc.3)"),  # George Frideric Handel
    ("Cleopatra's aria: 'Piangerò la sorte mia' - from 'Giulio Cesare', Act 3 Scene 3",
     "Cleopatra's aria: 'Piangero la sorte mia' - from \"Giulio Cesare\" (Act 3 Sc.3)"),  # George Frideric Handel

    # --- Handel arias from other operas (2026-05-28) ------------------------

    # Cara sposa — Rinaldo, Act 1 Sc 7. Five phrasings fold into the
    # plurality (12×) full-title form.
    ("Cara sposa, aria from Rinaldo",
     "Aria: Cara sposa, amante cara from Rinaldo (Act 1 Scene 7)"),  # George Frideric Handel
    ("Cara sposa - aria from Rinaldo",
     "Aria: Cara sposa, amante cara from Rinaldo (Act 1 Scene 7)"),  # George Frideric Handel
    ("Cara sposa - aria from 'Rinaldo'",
     "Aria: Cara sposa, amante cara from Rinaldo (Act 1 Scene 7)"),  # George Frideric Handel
    ("Cara sposa, (Rinaldo)",
     "Aria: Cara sposa, amante cara from Rinaldo (Act 1 Scene 7)"),  # George Frideric Handel
    ("Cara sposa (Rinaldo)",
     "Aria: Cara sposa, amante cara from Rinaldo (Act 1 Scene 7)"),  # George Frideric Handel

    # Lascia ch'io pianga — Almirena's aria, Rinaldo Act 2 Sc 2.
    ("Lascia ch'io pianga (from Act 2 Sc 2 of 'Rinaldo' HWV.7)",
     "Lascia ch'io pianga from Act 2 Sc.2 of Rinaldo (HWV.7)"),  # George Frideric Handel
    ("Almirena's aria 'Lascia ch'io pianga' from Act 2 Sc.2 of 'Rinaldo' (HWV.7)",
     "Lascia ch'io pianga from Act 2 Sc.2 of Rinaldo (HWV.7)"),  # George Frideric Handel

    # Già che morir non posso — Radamisto aria. Existing 1084-1085 alias
    # already targets "Già che morir non posso - from 'Radamisto'"; add
    # the remaining phrasings to the same target.
    ("Radamisto (excerpt 'Già che morir non posso')",
     "Già che morir non posso - from 'Radamisto'"),  # George Frideric Handel
    ("'Già che morir non posso' – aria from Radamisto",
     "Già che morir non posso - from 'Radamisto'"),  # George Frideric Handel
    ("Aria \"Già che morir non posso\" - from 'Radamisto'",
     "Già che morir non posso - from 'Radamisto'"),  # George Frideric Handel

    # Ombra mai fu — Serse/Xerxes, Act 1. The piano-arr. plurality (4×)
    # absorbs Serse-named and HWV-coded variants. Same aria across all
    # five phrasings.
    ("Aria \"Ombra mai fu\" from Act 1 of the opera 'Serse'",
     "\"Ombra mai fu\" - from the opera 'Xerxes' arr. for piano"),  # George Frideric Handel
    ("Serse (Ombra mai fu, Act 1) HWV 40",
     "\"Ombra mai fu\" - from the opera 'Xerxes' arr. for piano"),  # George Frideric Handel
    ("Ombra mai fu (Serse, HWV 40 Act 1)",
     "\"Ombra mai fu\" - from the opera 'Xerxes' arr. for piano"),  # George Frideric Handel

    # Rejoice greatly, O daughter of Zion — Messiah aria.
    ("Rejoice Greatly, O Daughter of Sion (Messiah)",
     "Rejoice greatly, O daughter of Zion' (aria from \"The Messiah\")"),  # George Frideric Handel

    # Lascia la spina — same melody appears across Almira (1705,
    # instrumental Sarabande), Il Trionfo (1707, "Lascia la spina"
    # vocal), and Rinaldo (1711, "Lascia ch'io pianga", different text).
    # The Lezhneva/Petrou Almira-attributed VOCAL airing (m001dxyp) is
    # the Il Trionfo aria with the Almira ancestry credited; folds with
    # the other Il Trionfo airings. Instrumental Almira HWV 1 (Steger /
    # La Cetra) and the Rinaldo Lascia ch'io pianga group stay separate.
    ("Lascia la spina, from 'Almira', HWV 1",
     "Lascia la spina, from Il Trionfo del tempo e del disinganno"),  # George Frideric Handel
    # Long-form 9× group: "Aria 'Lascia la spina' - from the oratorio
    # \"Il Trionfo...\"" — all 4 sub-variants share the same work_key, so
    # one alias source covers them.
    ('Aria "Lascia la spina" - from the oratorio Il Trionfo del Tempo e del Disinganno',
     "Lascia la spina, from Il Trionfo del tempo e del disinganno"),  # George Frideric Handel
    # The bare cogli-la-rose form (no HWV.46a tag) that the existing
    # 1088-1091 aliases targeted; now itself aliased to the short
    # canonical so the cogli-la-rose group fuses with the plurality.
    ("Lascia la spina cogli la rose, from 'Il Trionfo del tempo e del disinganno'",
     "Lascia la spina, from Il Trionfo del tempo e del disinganno"),  # George Frideric Handel

    # Tu del Ciel ministro eletto — Bellezza's aria from Il Trionfo.
    # Five no-HWV phrasings collapse to the plurality (6×). The HWV.46a-
    # coded variant (at lines ~1073-1074) keeps its own target.
    ("\"Tu del Ciel ministro eletto\" - aria from the oratorio 'Il Trionfo del tempo e del disinganno'",
     "Tu del Ciel ministro eletto (excerpt 'Il Trionfo del tempo e del disinganno')"),  # George Frideric Handel
    ("Tu del ciel ministro eletto - aria from the oratorio 'Il Trionfo del tempo e del disinganno'",
     "Tu del Ciel ministro eletto (excerpt 'Il Trionfo del tempo e del disinganno')"),  # George Frideric Handel
    ("Tu del Ciel ministro eletto - aria from the oratorio 'Il Trionfo del tempo e del disinganno'",
     "Tu del Ciel ministro eletto (excerpt 'Il Trionfo del tempo e del disinganno')"),  # George Frideric Handel
    ("Tu, del ciel ministro eletto from 'Il Trionfo del Tempo e del Disinganno'",
     "Tu del Ciel ministro eletto (excerpt 'Il Trionfo del tempo e del disinganno')"),  # George Frideric Handel
    ("Tu, del ciel ministro eletto",
     "Tu del Ciel ministro eletto (excerpt 'Il Trionfo del tempo e del disinganno')"),  # George Frideric Handel

    # --- Bruckner audit (2026-05-28, via ttn_audit_composer) ---------------
    # Small catalogue (4 candidate clusters surfaced + a few symphony
    # WAB-annotation folds). Bruckner's symphonies have multiple known
    # versions (1873/1877/1889 for Sym 3, 1877/etc for Sym 2, Nowak/Schalk
    # editorial revisions) which the BBC sometimes flags explicitly —
    # those variants STAY SPLIT as a deliberate decision (parked per
    # [[composer-audit-campaign]] note on version-distinguishing splits).

    # Symphonies — WAB-catalogue annotation forms fold to the canonical
    # short forms (these are just catalogue annotations, not version tags).
    ("Symphony No 4 in E flat major, WAB 104, 'Romantic'",
     "Symphony No.4 in E flat major, 'Romantic'"),  # Anton Bruckner
    ("Symphony No 4 in E flat major, WAB.104, 'Romantic'",
     "Symphony No.4 in E flat major, 'Romantic'"),  # Anton Bruckner
    ("Symphony no 5 in B flat major, WAB 105",
     "Symphony No. 5 in B flat"),  # shared: Andreas Schencker / Anton Bruckner / Alexander Konstantinovich Glazunov
    ("Symphony no 6 in A major, WAB 106",
     "Symphony No 6 in A major"),  # Anton Bruckner

    # Te Deum in C — extended-scoring form, "(1870)" date-annotated form,
    # and the bare "Te Deum" all fold (Bruckner has only one Te Deum).
    # The bare key is cross-composer (shared with Lassus, Sandström) —
    # composer-scoping keeps each composer's group correct.
    ("Te Deum in C (1870)",
     "Te Deum for soloists, chorus and orchestra in C major"),  # Anton Bruckner
    ("Te Deum",
     "Te Deum for soloists, chorus and orchestra in C major"),  # Anton Bruckner

    # Motets — 17×/5× "Locus iste & Christus Factus est" punctuation pair
    # folds; 15×/3× "3 Motets" / "(motets)" parenthesis pair folds.
    ("2 graduals for chorus: Locus iste; Christus Factus est",
     "2 graduals for chorus: Locus iste & Christus Factus est"),  # Anton Bruckner
    ("Ave Maria; Christus factus est; Locus iste (motets)",
     "3 Motets: Ave Maria; Christus factus est; Locus iste"),  # Anton Bruckner

    # Psalm 150 WAB 38 — dot/space catalogue variants fold.
    ("Psalm 150, WAB.38",
     "Psalm 150, WAB 38"),  # Anton Bruckner

    # Mass no 3 in F minor WAB.28 — dot/space catalogue variants fold.
    ("Mass no 3 in F minor, WAB.28",
     "Mass no 3 in F minor, WAB 28"),  # Anton Bruckner

    # --- Schumann audit (2026-05-28, via ttn_audit_composer) ----------------
    # 36 candidate clusters. Cycle/collection flag correctly fired on Op 48
    # Dichterliebe + Op 39 Liederkreis + Op 25 Myrthen (after extending the
    # token list with 'liederkreis' / 'myrten'). Skipped: Op 7 / Op 10 /
    # Op 13 / Op 15 / Op 16 / Op 17 / Op 20 (Clara Schumann's DIFFERENT
    # Op N works — cross-composer not same-work), Op 41 String Quartets
    # (3 distinct works, set-catalogue siblings), Op 44 / Op 47 / Op 12
    # / Op 23 / Op 6 / Op 82 individual movement excerpts (stay split),
    # Op 35 / Op 21 individual songs/novelettes (distinct works), Op 120
    # Symphony 4 1841 vs 1851 versions (parked like the Bruckner-versions
    # question — stay split for now), Op 46 alt-scoring (parked).

    # Op 73 Phantasiestücke for clarinet — extended-scoring "violin or
    # cello" variant folds (composer-authored alternative instrument
    # specifications, but the same work).
    ("Fantasiestücke for clarinet (violin or cello) and piano, Op 73",
     "Phantasiestucke Op 73 for clarinet & piano"),  # Robert Schumann

    # Op 18 Arabeske in C — "Arabesque" English spelling folds.
    ("Arabesque, Op 18",
     "Arabeske for piano in C major, Op 18"),  # Robert Schumann

    # S.566 Widmung (Liszt transcription of Schumann) — retargeted 2026-07-05:
    # the whole S.566 family now folds into the SONG (Cerys: arrangement-grade,
    # not a distinct work), so this pair targets the song's final canonical.
    ("Widmung from Liederkreise, S.566",
     "Widmung (Op.25 No.1)"),  # Robert Schumann

    # Op 133 Gesänge der Frühe — extended-subtitle form folds.
    ("Gesänge der Frühe (Chants de l'Aube) (Op.133) - 5 pieces for piano dedicated to the poet Bettina Brentano",
     "Gesange der Fruhe - Songs of Dawn, Op 133"),  # Robert Schumann

    # Op 135 Mary Stuart Gedichte — "Konigen" BBC misspelling and short-form
    # variants fold to the corrected "Konigin" spelling.
    ("5 Gedichte der Konigen Maria Stuart (5 Poems of Queen Mary Stuart), Op 135",
     "5 Gedichte der Konigin Maria Stuart (5 Poems of Queen Mary Stuart), Op 135"),  # Robert Schumann
    ("Gedichte der Königin Maria Stuart, Op 135",
     "5 Gedichte der Konigin Maria Stuart (5 Poems of Queen Mary Stuart), Op 135"),  # Robert Schumann

    # Violin Concerto in D minor (Op.posthumous) — word-order variant.

    # Op 86 Konzertstück for 4 Horns in F — typo + word-order variants.
    ("Koncertstuck in F major for 4 Horns and Orchestra, Op 86",
     "Konzertstück in F major for 4 Horns and Orchestra, Op 86"),  # Robert Schumann
    ("Konzertstück for four horns and Orchestra, Op.86",
     "Konzertstück in F major for 4 Horns and Orchestra, Op 86"),  # Robert Schumann

    # Op 85 Abendlied no 12 — slash-format Op number folds.

    # Op 92 Introduction and Allegro appassionato — "in G major" key-sig
    # annotation folds.
    ("Introduction and Allegro appassionato in G major Op 92",
     "Introduction and Allegro appassionato (Op.92)"),  # Robert Schumann

    # Op 126 7 Klavierstücke in Fughettenform — "(excerpts)" generic form
    # folds with the specific "(nos.5-7)" canonical. The two refer to
    # the same airing selection in practice.
    ("7 Klavierstucke in Fughettenform Op.126 for piano (excerpts)",
     "7 Klavierstucke in Fughettenform Op.126 for piano (nos.5-7)"),  # Robert Schumann

    # --- Mendelssohn audit (2026-05-28, via ttn_audit_composer) ------------
    # 35 candidate clusters. Skipped: Op 6 / Op 8 / Op 11 (Fanny Mendelssohn's
    # different Op N works — cross-composer not same-work; composer-scoping
    # handles those naturally). Other set-catalogue ops (Op 30 / Op 67 /
    # Op 65 organ sonatas) contain distinct Songs Without Words / sonatas.

    # Hebrides Op 26 — bare "Hebrides - overture" short form. Existing
    # alias chain (line ~977) targets "The Hebrides, Op 26"; reuse that.
    ("Hebrides - overture",
     "The Hebrides, Op 26"),  # Felix Mendelssohn

    # Op 13 String Quartet No 2 in A minor — word-order variant + "A major"
    # BBC typo (the work IS in A minor).
    ("String Quartet No 2 in A major, Op 13",
     "String Quartet no 2 in A minor, Op 13"),  # Felix Mendelssohn

    # Op 14 Rondo capriccioso — word-order variant ("for piano").

    # Op 15 Fantasia / "Fantasy" on an Irish Song — spelling variant.
    ("Fantasy on an Irish Song 'The Last Rose of Summer', Op.15",
     "Fantasia on an Irish song \"The last rose of summer\" for piano Op 15"),  # Felix Mendelssohn

    # Op 27 Meeresstille und glückliche Fahrt — English subtitle + bare
    # English-title forms fold to German canonical.
    ("Meeresstille und gluckliche Fahrt (Calm sea and a prosperous voyage) - overture (Op.27)",
     "Meeresstille und gluckliche Fahrt - Overture, Op 27"),  # Felix Mendelssohn
    ("Calm Sea and a Prosperous Voyage - overture, Op.27",
     "Meeresstille und gluckliche Fahrt - Overture, Op 27"),  # Felix Mendelssohn

    # Op 32 Die schöne Melusine — English title folds to German canonical.
    ("The Fair Melusina, op. 32, overture",
     "Die schöne Melusine  - overture Op 32"),  # Felix Mendelssohn

    # Op 36 St Paul Overture — "Overture to" word-order variant.
    ("Overture to 'St Paul', Op 36",
     "St.Paul, Op 36, Overture"),  # Felix Mendelssohn

    # Op 39 Laudate Pueri — backtick form + English subtitle fold to canonical.
    ("Motet: Laudate Pueri (O praise the Lord), Op 39 No 2",
     "Laudate Pueri - motet, Op 39 no 2"),  # Felix Mendelssohn

    # Op 44 String Quartet in D major No 1 — backtick form folds.

    # Op 54 Variations sérieuses — the "(1841)" annotated form folds with
    # the short canonical. Plurality tied; pick the (1841) form arbitrarily.
    ("Variations Serieuses, Op54",
     "Variations serieuses in D minor (Op.54) (1841)"),  # Felix Mendelssohn

    # Op 56 Symphony No 3 'Scottish' — short form (no Op number) folds.
    ("Symphony No.3 in A minor, 'Scottish'",
     "Symphony no 3 in A minor, Op 56 'Scottish'"),  # Felix Mendelssohn

    # Op 61 A Midsummer Night's Dream — "Excerpts from" form folds with
    # the incidental music canonical; the two "Suite from" forms fold
    # with each other.
    ("Excerpts from 'A Midsummer Night's Dream, op. 61' (incidental music)",
     "A Midsummer Night's Dream - incidental music (Op.61)"),  # Felix Mendelssohn
    ("A Midsummer Night's Dream, suite, op. 61",
     "Suite from 'A Midsummer Night's Dream', Op.61"),  # Felix Mendelssohn

    # Op 64 Violin Concerto in E minor — word-order variant ("Concerto
    # for violin and orchestra in E minor (Op.64)").

    # Op 66 Piano Trio No 2 — word-order variant ("Trio for piano and
    # strings No.2 (Op.66) in C minor").

    # Op 81 Capriccio in E minor No 3 — "Op 81 no 3" folds with the
    # plurality "Op.81`3" backtick form.

    # Op 87 String Quintet No 2 in B flat — short form (no "No 2") folds.
    ("String Quintet in B flat, op. 87",
     "String Quintet No 2 in B flat major, Op 87"),  # Felix Mendelssohn

    # Op 107 Symphony No 5 'Reformation' — the "D minor" BBC typo (the
    # work IS in D major). Same edge case as Mahler Symphony 1 'Titan'
    # implicit-major handling.
    ("Symphony no 5 in D minor, op 107 'Reformation'",
     'Symphony No.5 in D major "Reformation" (Op.107)'),  # Felix Mendelssohn

    # Op 109 Song Without Words in D — English title folds to the German
    # canonical (Lied ohne Worte). Plurality tied 3/3; original language wins.
    ("Song Without Words, Op 109",
     "Lied ohne Worte in D major, Op 109"),  # Felix Mendelssohn

    # Hora est — "(antiphon and responsorium)" form folds to bare.
    ("Hora est (antiphon and responsorium)",
     "Hora est"),  # Felix Mendelssohn

    # Op 78 Richte mich, Gott (Psalm 43) — the long-form English "(Psalm
    # 43), from 3 Psalmen" variant folds with the short canonical.
    ("Richte mich, Gott (Psalm 43), from 3 Psalmen, Op 78",
     "Richte mich, Gott, Op 78 no 2"),  # Felix Mendelssohn

    # Op 42 Psalm 42 'Wie der Hirsch schreit' — long "nach frischem
    # Wasser" subtitle folds with the short canonical.
    ("Psalm 42 'Wie der Hirsch schreit nach frischem Wasser, op. 42'",
     "Psalm 42 'Wie der Hirsch schreit', Op 42, cantata"),  # Felix Mendelssohn

    # 'Denn er hat seinen Engeln befohlen' (from Elias) — the "from 'Elias'"
    # annotation folds with the bare aria title (same Elias aria either way).
    ("Denn er hat seinen Engeln befohlen, from 'Elias'",
     "Denn er hat seinen Engeln befohlen"),  # Felix Mendelssohn

    # --- Vivaldi audit (2026-05-28, via ttn_audit_composer) -----------------
    # 23 candidate clusters surfaced. The new set-catalogue flag fired
    # correctly on 4 collections (Op 3 / Op 4 / Op 8 / multi-RV 'cellos'
    # cluster) — those are SKIPPED. Pass 1b cross-path bridges: 0 new
    # candidates (RV.565 was the only one, already aliased above). This
    # batch handles the multi-phrasing folds within distinct RV works.

    # RV.595 Dixit Dominus — no-RV scoring form folds to canonical.
    ("Dixit Dominus for SSATB soloists and double choir and orchestra in D major",
     "Dixit Dominus in D major, RV.595"),  # Antonio Vivaldi

    # RV.610 Magnificat — "RV 610/611" (lists both versions) and the
    # extended-scoring form fold to the bare canonical.
    ("Magnificat RV 610/RV 611",
     "Magnificat in G minor, RV 610"),  # Antonio Vivaldi
    ("Magnificat in G minor, RV.610, for SSAT soloists, choir, 2 oboes, strings and continuo",
     "Magnificat in G minor, RV 610"),  # Antonio Vivaldi

    # RV.93 Lute Concerto in D — short title folds to scored canonical.
    ("Lute Concerto in D major, RV 93",
     "Concerto for lute, 2 violins & continuo in D major, RV.93"),  # Antonio Vivaldi

    # RV.178 Violin Concerto Op 8 No 12 — the "in C major" key-sig
    # annotation folds (the work IS in C; the annotation is descriptive).
    ("Violin Concerto in C major, Op 8 No 12 (RV 178)",
     "Violin Concerto, Op 8 No 12, RV 178"),  # Antonio Vivaldi

    # RV.567 Concerto for 4 violins, cello in F — Op 3 No 7. The no-Op
    # variant and the alt-ordering "Op.3 No.7, RV.567" variant fold.
    ("Concerto for 4 violins, cello and orchestra in F major, RV.567",
     "Concerto for 4 violins, cello and orchestra (RV.567) Op 3 No 7 in F major"),  # Antonio Vivaldi
    ("Concerto for four violins & basso continuo in F, Op.3 No.7, RV.567",
     "Concerto for 4 violins, cello and orchestra (RV.567) Op 3 No 7 in F major"),  # Antonio Vivaldi

    # RV.315 L'Estate (Summer) — the bare form (no Op 8 No 2) folds.
    # Movement excerpts ("Presto from...", "(excerpt)") stay split.
    ("Concerto for violin & orchestra in G minor 'L'Estate', RV.315",
     "Concerto for violin & orchestra (RV.315) (Op.8 No.2) in G minor 'L'Estate'"),  # Antonio Vivaldi

    # RV.608 Nisi Dominus — "Psalm:" prefix form and key-sig form fold
    # to the "(Psalm 127)" canonical.
    ("Psalm: Nisi Dominus, RV.608",
     "Nisi Dominus (Psalm 127) for voice and orchestra (RV.608)"),  # Antonio Vivaldi
    ("Nisi Dominus in G minor, RV 608",
     "Nisi Dominus (Psalm 127) for voice and orchestra (RV.608)"),  # Antonio Vivaldi

    # RV.108 Concerto for recorder in A minor — the "sopranino recorder"
    # scoring variant folds to canonical.
    ("Concerto for sopranino recorder, two violins and continuo, RV 108",
     "Concerto in A minor for recorder, two violins and basso continuo, RV 108"),  # Antonio Vivaldi

    # RV.522 Op 3 No 8 — the "from L'estro Armonico" form folds to bare.
    ("Concerto VIII in A minor for 2 violins, strings and continuo, RV 522, from 'L'estro Armonico', Op 3",
     "Concerto VIII in A minor for 2 violins, strings and continuo, RV 522"),  # Antonio Vivaldi

    # RV.104 La Notte (flute concerto in G minor) — extended-scoring
    # form folds to the canonical.
    ("Concerto in G minor, RV 104, (La notte) for flute, 2 violins, bassoon and continuo",
     "Flute Concerto in G minor, RV104 (La Notte)"),  # Antonio Vivaldi

    # RV.293 L'Autunno (Autumn from Four Seasons) — the "Autumn" bare
    # English title folds to the canonical Italian Op 8 No 3 form.
    ("Violin Concerto in F major, RV 293, 'Autumn'",
     "Concerto for violin & orchestra RV.293 Op 8 No 3 in F major 'L'Autunno'"),  # Antonio Vivaldi

    # RV.230 Op 3 No 9 — "Concerto IX" Roman-numeral form folds to the
    # canonical. The 2× Larghetto excerpt stays its own group.
    ("Concerto IX in D major (RV.230), from 'L'Estro Armonico', Op 3",
     "Violin Concerto in D (Op.3 No.9) (RV.230)"),  # Antonio Vivaldi

    # Sonata a quattro in C — the extended-scoring form folds.
    ("Sonata a quattro in C major for 2 oboes, bassoon & continuo",
     "Sonata a quattro in C major"),  # shared: Antonio Vivaldi / Arcangelo Califano

    # --- Vivaldi RV.565 audit (2026-05-28, ttn_audit_composer Pass 1b) ----
    # First catch by the new Op↔catalogue-ref cross-path bridge. The
    # 10× catalogue-bearing form ("RV.565 Op 3 No 11") bridged the 23×
    # token-sort canonical ("Op.3 No.11 from L'Estro Armonico") and a
    # 4× truncated variant ("from 'L'Estro" without "Armonico"). All
    # three groups are the same L'Estro Armonico concerto for 2 violins,
    # cello and continuo in D minor.
    ("Concerto in D minor for 2 violins, cello and orchestra RV.565 Op 3 No 11",
     "Concerto in D minor (Op.3 No.11) from 'L'Estro Armonico'"),  # Antonio Vivaldi
    ("Concerto in D minor (Op.3 No.11) from 'L'Estro",
     "Concerto in D minor (Op.3 No.11) from 'L'Estro Armonico'"),  # Antonio Vivaldi
    # Stragglers found while applying the Pass 1b candidate: bare RV.565
    # forms and a minimal Op-bearing form, each below the 4-airing tool
    # threshold.
    ("Concerto in D minor, RV.565",
     "Concerto in D minor (Op.3 No.11) from 'L'Estro Armonico'"),  # Antonio Vivaldi
    ("Concerto in D minor for 2 violins, cello and orchestra RV.565",
     "Concerto in D minor (Op.3 No.11) from 'L'Estro Armonico'"),  # Antonio Vivaldi
    ("Concerto in D minor, RV.565 Op 3 no 11",
     "Concerto in D minor (Op.3 No.11) from 'L'Estro Armonico'"),  # Antonio Vivaldi

    # --- Mahler audit (2026-05-28, via ttn_audit_composer) -----------------
    # 8 candidate clusters surfaced. Mahler's catalogue is uniformly
    # attributed by the BBC; lower yield than Schubert/Handel. Skipped:
    # Kindertotenlieder individual songs ("Nun seh' ich…", "Oft denk'
    # ich…"), individual Wunderhorn songs, Alma Mahler cross-composer
    # cluster, "Excerpts from Des Knaben Wunderhorn" multi-song program.

    # Rückert-Lieder whole-collection — bare and "5 Rückert-Lieder"
    # (phantom "5" prefix counting the 5 songs in the set) fold. The
    # individual songs (Ich bin der Welt, Ich atmet, Liebst du um
    # Schönheit) stay split — each is its own group.
    ("Rückert-Lieder",
     "5 Ruckert-Lieder"),  # Gustav Mahler

    # Ich bin der Welt abhanden gekommen — the most-aired Rückert song.
    # The "from 'Rückert-Lieder'" phrasing folds with the parenthetical
    # canonical (both refer to the same song, in the same collection).
    ("Ich bin der Welt abhanden gekommen, from 'Rückert-Lieder",
     "Ich bin der Welt abhanden gekommen (Rückert Lieder)"),  # Gustav Mahler
    ("Ich bin der Welt abhanden gekommen, from 'Rückert-Lieder'",
     "Ich bin der Welt abhanden gekommen (Rückert Lieder)"),  # Gustav Mahler

    # Ich ging mit Lust durch einen grünen Wald — same song, the
    # parenthetical "(no.7 from Lieder und Gesänge aus der Jugendzeit)"
    # variant identifies the source collection. Same melody also forms
    # the 1st-movement opening theme of Symphony No 1, but the song
    # and the symphonic appearance stay as their own works.
    ("Ich ging mit Lust durch einen grünen Wald (I walked with joy through a green forest) (no.7 from Lieder und Gesänge aus der Jugendzeit)",
     "Ich ging mit lust durch einen grunen Wald"),  # Gustav Mahler

    # Symphony No 1 'Titan' — edge case: `_drop_implicit_major` strips
    # the trailing "major" only after the "in <note>" pattern, so
    # "in D major" → "in D" but bare "D major" stays. The 2× "Symphony
    # No.1 D major, 'Titan'" form lacks "in" and so doesn't fold with
    # the 24× canonical. One alias bridges the gap.
    ("Symphony No.1 D major, 'Titan'",
     "Symphony no 1 in D major, 'Titan'"),  # Gustav Mahler

    # Symphony No 2 'Resurrection' — the verbose-scoring form (with
    # "for soprano, alto, chorus and orchestra") folds with the short
    # canonical. Same work, scoring annotation is redundant.
    ("Symphony No.2 in C minor for soprano, alto, chorus and orchestra \"Resurrection\"",
     "Symphony No. 2 in C minor ('Resurrection')"),  # Gustav Mahler

    # Adagietto from Symphony No 5 — the short form (no key signature)
    # folds with the canonical. The Adagietto is the famous 4th-movement
    # excerpt; both forms are the same excerpt.
    ("Adagietto, from Symphony No. 5",
     "Adagietto, from Symphony no 5 in C sharp minor"),  # Gustav Mahler

    # Symphony No 10 — Adagio is the only completed movement. The two
    # variants (parenthetical "(Adagio)" vs "Adagio, from ... (unfinished)")
    # fold. The 4 airings are split 2/2 between the forms.
    ("Symphony No 10 (Adagio)",
     "Adagio, from 'Symphony No. 10 in F sharp' (unfinished)"),  # Gustav Mahler

    # Des Knaben Wunderhorn whole-collection — the "Songs from" prefix
    # folds with the bare canonical. Individual songs (Rheinlegendchen,
    # Verlorne Müh, etc.) stay split.
    ("Songs from 'Des Knaben Wunderhorn'",
     "Des Knaben Wunderhorn"),  # Gustav Mahler
    ("Songs from Des Knaben Wunderhorn",
     "Des Knaben Wunderhorn"),  # Gustav Mahler

    # --- Schubert audit (2026-05-28, via ttn_audit_composer) ---------------
    # 54 candidate clusters surfaced. This batch handles the high-confidence
    # high-yield merges. Skipped: D.899 / D.935 Impromptus (set-catalogue
    # siblings, distinguished by key — DO NOT touch), D.780 individual
    # movements, individual Winterreise songs (cycle denylist), Sehnsucht
    # as distinct settings (D.123, D.636, D.658, D.879 are different works),
    # Mahler arrangement of D.810 (alt scoring, stays split), Liszt's
    # transcription of D.760 Wandererfantasie (different work from the
    # original).

    # D.821 Arpeggione Sonata — bare-form / token-sort siblings of the 60×
    # catalogue canonical.
    ("Arpeggione Sonata in A minor",
     "Sonata in A minor D.821 for arpeggione (or viola or cello) and piano"),  # Franz Schubert
    ("Arpeggione Sonata",
     "Sonata in A minor D.821 for arpeggione (or viola or cello) and piano"),  # Franz Schubert

    # D.780 Six Moments musicaux — phantom "6" from "6 Moments Musicaux"
    # vs "Six Moments musicaux" splits two whole-collection groups. The
    # individual movement (": no 3 in F minor") stays split via its own
    # number/key.
    ("6 Moments Musicaux (D.780)",
     "Six Moments musicaux, D. 780"),  # Franz Schubert

    # D.703 Quartettsatz — D.703 IS the only completed movement; the
    # "(movement) for strings" parenthetical triggers the existing
    # 'movement' locator and routes to token-sort.
    ("Quartettsatz (movement) for strings in C minor (D.703)",
     "Quartettsatz in C minor, D.703"),  # Franz Schubert

    # D.774 Auf dem Wasser zu singen — "Barcarolle" alt-title.
    ("Barcarolle (Auf dem Wasser zu singen)",
     "Auf dem Wasser zu singen, D.774"),  # Franz Schubert

    # D.957 Ständchen from Schwanengesang. The 10× canonical "Standchen,
    # D957" is the plurality. Four other phrasings (arr.-for-piano, "from
    # Schwanengesang", D.957'4 backtick, D.957/4 slash) fold to it. Note:
    # the bare "Ständchen" key is shared with Strauss — the alias relabels
    # the key but composer-scoping keeps Schubert and Strauss in separate
    # groups (display follows airing count within each).
    ("Ständchen arr. for piano - from Schwanengesang (D. 957)",
     "Standchen, D957"),  # Franz Schubert
    ("Standchen from Schwanengesang (D.957)",
     "Standchen, D957"),  # Franz Schubert
    ("Ständchen, D.957'4",
     "Standchen, D957"),  # Franz Schubert
    ("Ständchen, D. 957/4",
     "Standchen, D957"),  # Franz Schubert

    # D.810 String Quartet No 14 "Death and the Maiden". 3× bare form
    # folds into 27× canonical. Mahler's string-orchestra arrangement
    # stays split as composer-non-authored alt-scoring.
    ("String Quartet in D minor, D810 'Death and the Maiden'",
     "String Quartet No 14 in D minor, D 810 'Death and the Maiden'"),  # Franz Schubert

    # D.312b Hektors Abschied — Op.58 No.1 annotation form folds to bare.
    ("Hektors Abschied (D.312b, Op.58 No.1)",
     "Hektors Abschied D.312b"),  # Franz Schubert

    # D.544 Ganymed — Op.19 No.3 + "from 3 Songs" annotation folds to bare.
    ("Ganymed (D.544) - from 3 Songs (Op.19 No.3)",
     "Ganymed, D.544"),  # Franz Schubert

    # D.161 An Mignon — Op.19 No.2 + "from 3 Songs" annotation. The
    # token-sort 5× form folds into the catalogue-path 2× canonical.
    # Target chosen to bypass the existing line ~1017 alias chain (which
    # itself folds "An Mignon from 3 Songs, D.161" → this string).
    ("An Mignon (D.161) from 3 Songs, Op 19 no 2 (To Mignon)",
     "An Mignon (D.161), Op.19 No.2 (To Mignon)"),  # Franz Schubert

    # S.366 Wandererfantasie (Liszt's transcription of D.760) — the two
    # phrasings "arranged by Liszt" and "transcribed for piano and
    # orchestra" fold; Schubert's original D.760 stays split.
    ("Wandererfantasie, transcribed for piano and orchestra (S.366)",
     "Wandererfantasie, D760 arranged by Liszt (S.366)"),  # Franz Schubert

    # D.965 Der Hirt auf dem Felsen — Op.129 annotation forms fold to
    # the bare D.965 canonical.
    ("Der Hirt auf dem Felsen, Op.129 (D965)",
     "Der Hirt auf dem Felsen, D965"),  # Franz Schubert
    ("Der Hirt auf dem Felsen, Op.129",
     "Der Hirt auf dem Felsen, D965"),  # Franz Schubert

    # D.478 Wer sich der Einsamkeit — "ergibit" typo folds with the
    # correct "ergibt".
    ("Wer sich der Einsamkeit ergibit (D.478) from Three Songs of the Harpist Op 12",
     "Wer sich der Einsamkeit ergibt (D.478) from Three Songs of the Harpist"),  # Franz Schubert

    # D.911 Winterreise whole-cycle forms (NOT the individual songs,
    # which the cycle denylist correctly keeps split).
    ("Winterreise, D.911 (arr. for voice & piano trio)",
     "Winterreise, D.911"),  # Franz Schubert
    ("Winterreise - song-cycle, D.911",
     "Winterreise, D.911"),  # Franz Schubert

    # 3 Songs - Liebesbotschaft, Heidenroslein & Litanei auf das Fest —
    # the "(including between songs)" annotation form folds.
    ("3 Songs - Liebesbotschaft, Heidenroslein & Litanei auf das Fest (including between songs)",
     "3 Songs - Liebesbotschaft, Heidenroslein & Litanei auf das Fest"),  # Franz Schubert

    # --- Handel audit follow-up (2026-05-28): gate-fix mop-up ---------------

    # Bach BWV 4 — Christ lag in Todesbanden. The
    # `_has_parent_work_reference` gate fires on "(Cantata BWV 4)"
    # because "Cantata" reads as a name-like word in the parenthetical's
    # residue. Semantically this is annotation, not a parent reference
    # — Christ lag IS BWV 4 (the whole cantata). The 1× variant goes
    # to token-sort via the gate; this alias folds it back into the
    # 11× §bwv4|4| canonical group. See [[catalogue-path-phantom-
    # ordering]] for the gate's known FP shape.
    ("Christ lag in Todesbanden (Cantata BWV 4)",
     "Cantata 'Christ lag in Todesbanden', BWV 4"),  # Johann Sebastian Bach

    # --- Handel Concerto Grosso Op 6 audit (2026-05-28) ---------------------
    # 85 airings across 17 groups. The main split mechanism is HWV-bearing
    # title (catalogue path, key includes HWV###) vs no-HWV (token-sort
    # path, key is sorted tokens). Backtick "Op.6`N" forms tokenize as
    # glued digits ("65" = "Op.6`5") and split too.
    #
    # Op 6 No 4 in A minor — HWV 322. Plurality (5×) lacks HWV; fold the
    # 5× HWV-bearing variants into it (10× total → 15× consolidated).
    ("Concerto grosso in A minor, HWV 322, Op 6 no 4",
     "Concerto Grosso in A minor, Op 6 no 4"),  # George Frideric Handel
    ("Concerto grosso in A minor, Op 6 no 4 (HWV 322)",
     "Concerto Grosso in A minor, Op 6 no 4"),  # George Frideric Handel
    ("Concerto grosso in A minor, Op 6 No 4 (HWV 322)",
     "Concerto Grosso in A minor, Op 6 no 4"),  # George Frideric Handel

    # Op 6 No 5 in D — HWV 323. Plurality (15×) is no-HWV "Op 6 no 5";
    # fold the 2× HWV-only forms and the 1× backtick. The existing
    # Dmajor-typo alias was retargeted earlier in the table.
    ("Concerto Grosso in D, HWV 323",
     "Concerto Grosso in D major, Op 6 no 5"),  # George Frideric Handel

    # Op 6 No 7 in B flat — HWV 325. Plurality (9×) is HWV-bearing;
    # fold the 2× no-HWV variants into it (→ 11× consolidated).
    ("Concerto Grosso in B flat Op.6 No.7",
     "Concerto grosso in B flat major Op.6 No.7 HWV.325"),  # George Frideric Handel
    ("Concerto Grosso in B flat, Op 6 No 7",
     "Concerto grosso in B flat major Op.6 No.7 HWV.325"),  # George Frideric Handel

    # Op 6 No 11 in A — HWV 329. Plurality (3×) is no-HWV "Op 6 no 11";
    # fold the 1× backtick form (→ 4× consolidated).

    # --- Handel Dixit Dominus (2026-05-28) ----------------------------------
    # HWV.232 is Handel's 1707 setting of Psalm 110. Bare-form (×15) is the
    # plurality. Three variants split on the catalogue path:
    #   - "Psalm 110" descriptive suffix pushes a phantom "110" into the key
    #     (×13 across three spacings)
    #   - "in G minor" key-signature appendage (×2) on a multi-movement work
    #     that has no canonical home key
    # The ×3 "no.7; De torrente in via bibet" group is the 7th-movement aria
    # — genuine excerpt, stays split.
    ("Dixit Dominus - Psalm 110, HWV.232",
     "Dixit Dominus, HWV 232"),  # George Frideric Handel
    ("Dixit Dominus - Psalm 110 HWV.232",
     "Dixit Dominus, HWV 232"),  # George Frideric Handel
    ("Dixit Dominus - Psalm 110 HWV 232",
     "Dixit Dominus, HWV 232"),  # George Frideric Handel
    ("Dixit Dominus in G minor, HWV.232",
     "Dixit Dominus, HWV 232"),  # George Frideric Handel

    # --- 2026-05-31 ttn_duplicates straggler folds: redundant genre/phrasing
    # annotations on an otherwise-identical title. Composer-scoped grouping
    # keeps these safe across the many composers who share these titles. ---
    # Palestrina Stabat Mater — "motet"/"a cappella" descriptors.
    # (The Vaughan Williams "The Wasps" straggler this scan surfaced is now
    # folded with every other Wasps-overture phrasing — the recording data
    # showed all 5 recordings are the one ~9-min Overture; see the Wasps block
    # near "Overture from the Incidental Music" above.)
    ("Stabat mater, motet a cappella",                "Stabat Mater"),  # shared: Giovanni Pierluigi da Palestrina / Juan Crisostomo Arriaga
    ("Stabat mater - motet",                          "Stabat Mater"),  # shared: Giovanni Pierluigi da Palestrina / Juan Crisostomo Arriaga
    # More Palestrina — descriptive-tail / scoring churn the token sort can't
    # reach (no thematic catalogue, so the descriptive title is load-bearing).
    # The "[1581]"/"[1563]" publication-year splits in this catalogue (Fundamenta
    # ejus, Ad te levavi, Sicut cervus, Nos autem) are NOT here — they fold
    # systemically via canonical_key's square-bracket-year strip. These are the
    # rest, several recording-proven (one recording_pid titled two ways, via the
    # work-alias-candidates oracle):
    ("Tu es Petrus",                                  "Tu es Petrus - motet for 6 voices"),  # Giovanni Pierluigi da Palestrina
    ("Tu es Petrus - motet",                          "Tu es Petrus - motet for 6 voices"),  # Giovanni Pierluigi da Palestrina
    ("Agnus Dei - super ut-re-mi-fa-sol-la",
     "Agnus Dei - super ut-re-mi-fa-sol-la (for 6 and 7 voices)"),               # oracle p011mrk7
    ("Agnus Dei - Missa super ut-re-mi-fa-sol-la (for 6 and 7 voices)",
     "Agnus Dei - super ut-re-mi-fa-sol-la (for 6 and 7 voices)"),  # Giovanni Pierluigi da Palestrina
    ("Agnus Dei - Missa super ut-re-mi-fa-sol-la",
     "Agnus Dei - super ut-re-mi-fa-sol-la (for 6 and 7 voices)"),  # Giovanni Pierluigi da Palestrina
    ("Missa in duplicibus minoribus II for 5 voices",
     "Missa in duplicibus minoribus II"),                                        # oracle p0101d71
    ("Missa in duplicibus minoribus II (Kyrie, Gloria, Credo, Sanctus, Agnus Dei) for 5 voices",
     "Missa in duplicibus minoribus II"),  # Giovanni Pierluigi da Palestrina
    ("Motet Salve Regina",                            "Motet Salve Regina (4 high parts)"),  # oracle p0259zht
    ("Sicut cervus - motet for 4 voices",             "Sicut cervus - Like as the hart"),    # oracle p00tc429
    # Monteverdi Vespro della Beata Vergine (1610). The WHOLE work fragments by a
    # ('Vespers') gloss and a 'Virgine' typo (the (1610)/[1610] year already folds
    # via the year-strip). Movements (Magnificat II, Dixit Dominus, Audi coelum,
    # Sonata sopra…) air standalone and stay split; "(excerpts)"/"Part 1/2" are
    # partial airings, also left split.
    ("Vespro della Beata Vergine ('Vespers') (1610)", "Vespro della Beata Vergine"),  # Claudio Monteverdi
    ("Vespro della Beata Virgine",                    "Vespro della Beata Vergine"),  # 'Virgine' typo
    # The 6-voice Magnificat FROM the Vespers splits on a bare 'Venice 1610'
    # place+year (not paren/bracketed, so the year-strip doesn't reach it):
    ("Magnificat for 6 voices from Vespro della Beata Vergine",
     "Magnificat for 6 voices from Vespro della Beata Vergine (Venice, 1610)"),  # Claudio Monteverdi
    ("Magnificat (for 6 voices) - from Vespro della Beata Vergine",
     "Magnificat for 6 voices from Vespro della Beata Vergine (Venice, 1610)"),  # Claudio Monteverdi
    # Schubert "Des Teufels Lustschloss" (D.84) overture — one recording
    # (Blaszczyk / Polish RSO), 18 airings, split 4 ways by the "Overture to"
    # phrasing and an added English-translation gloss. Surfaced by the
    # ttn_rebroadcast multiplay scan (2026-06-02). The "Overture to '...'"
    # quoted form shares a key with the unquoted one, so one alias covers both.
    ("Overture to Des Teufels Lustschloss",
     "'Des Teufels Lustschloss' (Overture)"),  # Franz Schubert
    ("Overture to the opera \"Des Teufels Lustschloss\" (The Devil's Castle)",
     "'Des Teufels Lustschloss' (Overture)"),  # Franz Schubert
    ("Overture to the opera \"Des Teufels Lustschloss\" (The Devil's Pleasure Palace)",
     "'Des Teufels Lustschloss' (Overture)"),  # Franz Schubert
    # "Christmas Medley" (Tormé/Berlin/Martin, Quilico recording) — long
    # song-listing title forms fold to the bare title. Composer-side credit
    # variants folded above; together these collapse the 5 airings to one work.
    ("Christmas Medley: The Christmas Song / White Christmas / Have Yourself a Merry Little Christmas",
     "Christmas Medley"),  # Mel Tormé
    ("Christmas Medley - The Christmas Song (Mel Tormé & Robert Wells) / White Christmas (Irving Berlin) / Have Yourself a Merry Little Christmas (Hugh Martin & Ralph Blaine)",
     "Christmas Medley"),  # Mel Tormé

    # Cross-era (2010-2012) title variants ratified via the bridge relaxed matcher
    # (`ttn_curate bridge --relaxed`): each pre-2012 text title folds to its
    # post-2012 recording's clean segment title, the fold justified by recording
    # identity (same composer + performer + duration). Top-20 worklist, 2026-06-10.
    ("Laudate Pueri (O praise the Lord)", "Laudate Pueri - motet, Op 39 no 2"),  # Felix Mendelssohn
    ("Concerto in the Italian style for keyboard (BWV.971) in F major", "Concerto in the Italian style (BWV.971)"),  # Johann Sebastian Bach
    ("Two Lyric Pieces: Evening in the Mountains (Op.68 No.4); At the cradle (Op.68 No.5)", "Evening in the Mountains, Op 68 no 4; At the cradle, Op 68 no 5 [Lyric Pieces]"),  # Edvard Grieg
    ("Overture (Sinfonia) from L' Isola disabitata - azione teatrale in 2 acts (H.28.9)", "Overture, L'Isola disabitata"),  # Joseph Haydn
    ("Triumphal March from 'Sigurd Jorsalfar'", "Triumphal March (Sigurd Jorsalfar)"),  # Edvard Grieg
    ("Hymne de l'enfant à son reveil - for female chorus, harmonium and harp (S.19)", "Hymne de l'enfant à son reveil, S19"),  # Franz Liszt
    ("Overture - Candide", "Overture - from Candide"),  # Leonard Bernstein
    ("Theme and Variations", "Theme and Variations for violin and piano"),  # shared: Olivier Messiaen / George Frideric Handel
    ("Romance for violin and orchestra in G major (Op.26)", "Violin Romance in G major, Op 26"),  # Johan Svendsen

    # Cross-era (2010-2012) bridge relaxed-matcher folds, batches 2-3 (#21-60),
    # ratified 2026-06-10. Same justification as the batch-1 block above; rejects
    # (same-performer different-works false positives + VW Wasps test-protected
    # split) parked in ttn_bridge_decisions.json.
    ("Eight Ländler (from D.790)", "Eight Landler (German dances) (from D.790)"),  # Franz Schubert
    ("Prelude and Allegro (1943)", "Prelude and Allegro (for organ and orchestra) (1943)"),  # Walter Piston
    ("Adagio and rondo for glass harmonica, flute, oboe, vla & vcl (K.617) in C minor", "Adagio and rondo for glass harmonica/accordion, flute, oboe, vla & vcl, K617"),  # Wolfgang Amadeus Mozart
    ("To a Nordic Princess", "To a Nordic Princess (bridal song) vers. piano"),  # Percy Grainger
    ("Spanish Suite", "Suite española for guitar"),  # Gaspar Sanz
    ("Meine Freundin, du bist schön", "Meine Freundin, du bist schon - wedding piece"),  # Johann Christoph Bach
    ("Concerto for 3 oboes and orchestra in B flat major", "Concerto for 3 oboes in B flat major"),  # Georg Philipp Telemann
    ("Serenade for Strings (1921-22)", "Serenade (to Frederick Delius on his 60th birthday)"),  # Peter Warlock
    ("Pieces from Les Indes Galantes", "Les Indes Galantes (excerpts)"),  # Jean-Philippe Rameau
    ("The Walk to the Paradise Garden (from 'A Village Romeo and Juliet')", "The Walk to the Paradise Garden"),  # Frederick Delius
    ("6 Quartets for chorus and piano (Op.112)", "6 Quartets for soprano, alto, tenor, bass and piano, Op 112"),  # Johannes Brahms
    ("Lute Concerto in D minor", "Concerto for lute, strings and basso continuo in D minor"),  # Johann Friedrich Fasch
    ("Le Festin d'Esope (Op.39 no.12 in E minor, from '12 studies' Op.39) (1857)", "Le Festin d'Esope in E minor, from '12 studies', Op 39 no 12"),  # Charles-Valentin Alkan
    ("Concerto for trumpet and orchestra in E flat major", "Trumpet Concerto in E flat major, H.7e.1"),  # shared: Joseph Haydn / Johann Nepomuk Hummel
    ("Suite for accordion and piano - 4 pieces based on East Canadian folksongs", "Canadian folk-song suite for accordion and piano"),  # Andrew Huggett
    ("Habanera (L'amour est un oiseau rebelle) - from Carmen", "Carmen (Habanera)"),  # Georges Bizet
    ("Festive Overture (Op.96)", "Festive Overture"),  # shared: Dmitry Shostakovich / Eduard Tubin
    ("Suscipe, quaeso Domine for 7 voices", "Suscipe, quaeso Domine à 7"),  # Thomas Tallis
    ("España - rhapsody for orchestra", "Espana"),  # Emmanuel Chabrier
    ("Variations Brillantes in B flat major, on a theme from Hérold's 'Ludovic'", "Introduction & variations on a theme from Herold's Ludovic (Op.12) in B flat major ('Varations brillantes')"),  # Fryderyk Chopin
    ("Overture to Flis 'The Raftsman' (1858)", "Flis (Overture)"),  # Stanislaw Moniuszko
    ("Serenade for String Orchestra in E flat (Op.6)", "Serenade for strings in E flat major Op 6"),  # Josef Suk

    # Cross-era (2010-2012) bridge relaxed-matcher folds, batch 4 (#61-80),
    # ratified 2026-06-11. Rejects parked in ttn_bridge_decisions.json; 5 accepted
    # links were NOT aliased (already-grouped: Falla/Bach/Vivaldi/Weber; chained:
    # Albeniz 'Spanish Suite' -> Sanz's alias source) — flipped to reject w/ notes.
    ("Missa sancta No.2 in G major (Op.76) 'Jubelmesse'", "Missa Sancta no 2 in G major J.251, Op 76 'Jubelmesse'"),  # Carl Maria von Weber
    ("Trio in A minor (Op.114)", "Trio for clarinet or viola, cello and piano in A minor, Op 114"),  # Johannes Brahms
    ("Overture to Charlotte Corday (1876)", "Overture (Charlotte Corday (1876))"),  # Peter Benoit
    ("Golliwog's Cake-walk from Children's Corner Suite (1906-8)", "Children's Corner Suite, 6: Cakewalk"),  # Claude Debussy
    ("Hungarian Fantasy (Op.68)", "Hungarian rhapsody, Op 68"),  # David Popper
    ("Choral Prelude (1988)", "Chorale Prelude"),  # Wojciech Kilar
    ("4 Madrigals, (1959)", "Part-song book - 4 madrigals for mixed chorus"),  # Bohuslav Martinu
    ("Trio for horn, violin and piano in E flat major (Op.40)", "Trio for violin, French horn and piano in E flat major, Op 40"),  # Johannes Brahms
    ("Rossiniana", "Rossiniana - suite from Rossini's 'Les riens'"),  # Ottorino Respighi
    ("Rhapsodie pour la harpe (Op.10)", "Rhapsodie pour la harpe (1921)"),  # Marcel Grandjany
    ("Rapsodia española", "Rapsodia española, Op 70"),  # Isaac Albeniz
    ("Lyric suite - arr for orchestra from Lyric Pieces (Book 5) for piano (Op.54)", "Lyric suite for orchestra from Lyric Pieces (Book 5)"),  # Edvard Grieg

    # Cross-era (2010-2012) bridge relaxed-matcher folds, batch 5 (#81-100),
    # ratified 2026-06-11.
    ("Pavan and Fantasie", "Pavan and Fantasie for lute"),  # Alfonso Ferrabosco
    ("Overture - from The Light Cavalry", "The Light Cavalry - overture"),  # Franz von Suppe
    ("Cantus Arcticus - 'a concerto for birds and orchestra' (Op.61) (1972)", "Cantus Arcticus, Concerto for Birds and Orchestra, Op 61"),  # Einojuhani Rautavaara
    ("Concerto for Violin and Orchestra", "Violin Concerto in B minor"),  # shared: William Walton / Frederick Delius
    ("White-flowering days for chorus (Op.37)", "White-flowering days (A Garland for the Queen), Op 37 no 8"),  # Gerald Finzi
    ("Serenade to music for 16 soloists (or 4 soloists & chorus) & orchestra", "Serenade to music"),  # Ralph Vaughan Williams
    ("Fest- und Gedenksprüche for 8 voices (2 choirs) (Op.109)", "Fest- und Gedenkspruche for 8 voices, Op 109"),  # Johannes Brahms
    # Retargeted 2026-07-05: the A-minor key now folds into the Mendelssohn
    # Scottish final (composer-scoped grouping keeps the sharers separate).
    ("Symphony No.3",
     "Symphony no 3 in A minor, Op 56 'Scottish'"),  # shared: Luka Sorkocevic / Alexander Borodin / Grazyna Bacewicz / Felix Mendelssohn
    ("Symphonic sketch 'Autumn Dawn'", "Symphonic sketch \"Autumn Twilight\""),  # Alfred Alessandrescu
    ("Fantasy for Violin and Orchestra with Harp, freely using Scottish Folk Melodies (Op.46)", "Scottish fantasy, Op 46"),  # Max Bruch
    ("Symphony No. 1 in C Major (Op. 21)", "Symphony No. 1 in C Major"),  # Ludwig van Beethoven
    ("Songs of farewell for mixed voices: no.6; Lord, let me know mine end", "Songs of farewell for mixed voices: no.6 Lord, let me know mine end [chorus a 8]"),  # Hubert Parry
    ("Symphony No.1 in D major (Op.25)", "Symphony no 1 in D major, Op 25, 'Classical'"),  # Sergey Prokofiev
    ("Trumpet Concerto in E flat major (Hob.VIIe:1)", "Concerto for Trumpet & Orchestra in E flat major, H.7e.1"),  # shared: Joseph Haydn / Johann Nepomuk Hummel

    # Cross-era (2010-2012) bridge relaxed-matcher folds, batch 6 (#101-120),
    # ratified 2026-06-11.
    ("Piano Quartet No.1 (Op.1)", "Piano Quartet no 1 in C minor, Op 1"),  # Felix Mendelssohn
    ("Overture - The Barber of Seville", "Overture from Il Barbiere di Siviglia (The Barber of Seville)"),  # Gioachino Rossini
    ("Trio pathetique for clarinet, bassoon and piano in D minor", "Trio Pathétique in D minor"),  # Mikhail Ivanovich Glinka
    ("Tableaux de Provence (1954)", "Tableaux de Provence - 5 pieces for saxophone and orchestra"),  # Paule Maurice
    ("From 'Morceaux de Salon' (Op.10)", "3 Pieces from Morceaux de salon for piano, Op 10"),  # Sergey Rachmaninov
    ("Symphony in D major (Op.5 No.3) 'Pastorella'", "Symphony in D major 'Pastorella'"),  # François-Joseph Gossec
    ("Preludes No.16 in Bb minor; No.17 in Ab major; No.18 in F minor; No.19 in Eb major; No.20 in C minor - from Preludes (Op.28)", "Preludes, Op 28 Nos 16-20"),  # Fryderyk Chopin
    ("Divertimento for chamber orchestra", "Divertimento"),  # shared: Igor Stravinsky / Pancho Vladigerov
    ("Ballet music from 'Anakreon'", "Ballet music from Anacreon"),  # Luigi Cherubini
    ("Mass in B flat major, 'Krecovicka'", "Křečovice Mass for chorus, strings and organ in B flat major"),  # Josef Suk
    ("Mountain Dances - from the opera 'Halka' (1846-1857)", "Mountain Dance (from the opera 'Halka')"),  # Stanislaw Moniuszko

    # Cross-era (2010-2012) bridge relaxed-matcher folds, batch 7 (#121-150),
    # ratified 2026-06-11 (first batch of 30).
    ("Suite for Orchestra from 'King Gustav II Adolf' (Op.49)", "King Gustav II Adolf (Suite)"),  # Hugo Alfvén
    ("Norwegian Rhapsody No 1", "Norwegian Rhapsody no 1 in A minor"),  # Johan Halvorsen
    ("Metamorphosen for 23 solo strings (AV.142)", "Metamorphosen for 23 solo strings"),  # Richard Strauss
    ("Danish Folk-Music Suite", "Suite on Danish folk songs vers. orchestral"),  # Percy Grainger
    ("Quartet for flute, clarinet, horn and bassoon no.6 in F major 'Andante et tema con variazioni'", "Quartet for flute, clarinet, horn and bassoon no 6 in F major"),  # Gioachino Rossini
    ("Concerto for piano and orchestra No.3 in D minor (Op.30)", "Piano Concerto no 3 in D minor"),  # Sergey Rachmaninov
    ("Symphonic Dance No.1 (Op.45)", "Symphonic Dance no 1 [Non allegro], Op 45"),  # Sergey Rachmaninov
    ("Exaudi me, for 12 part triple chorus, continuo and 4 trombones", "Exaudi me"),  # Giovanni Gabrieli
    ("Summer evening", "Summer evening (Nyari este)"),  # Zoltan Kodaly
    ("Concerto for Violoncello and Orchestra (HV VIIb:2) in D major", "Cello Concerto in D major"),  # Joseph Haydn
    ("The Secret of the Struma River", "The Secret of the Struma River - ballad for men's choir (1931)"),  # Petko Stainov
    ("Overture to Maskarade - opera in 3 acts (FS.39)", 'Overture to Maskarade'),  # Carl Nielsen
    ("Deux Pièces caracteristiques, Op.25", "2 pieces caracteristiques, Op 25"),  # Johan Peter Emilius Hartmann
    ("Allegro vivace ma non troppo in C major - No.7 from Pieces for clarinet, viola/cello & piano (harp) (Op.83) arr. for violin, cello & piano", "Allegro vivace ma non troppo in C major, Op 83 no 7"),  # Max Bruch
    ("(Eduard Lassen) Löse Himmel, meine seele (S.494) transc. for piano", "Löse Himmel, meine seele, S.494"),  # Franz Liszt
    ("3 Psaumes de David (Op.339)", "3 Psaumes de David for chorus, Op 339"),  # Darius Milhaud
    ("Scherzo - from the Concerto Symphonique No.4 (Op.102)", "Scherzo - Concerto Symphonique no 4, Op 102"),  # Henry Litolff
    ("Johannesberg Festival Overture", "Johannesburg Festival Overture"),  # William Walton
    ("The Italian Girl in Algiers - overture", "Overture to L' Italiana in Algeri"),  # Gioachino Rossini
    ("Taras Bulba", "Taras Bulba - rhapsody for orchestra"),  # Leos Janacek
    ("To be sung of a summer night on the water for chorus (RT.4.5)", "To be sung of a summer night on the water for chorus"),  # Frederick Delius
    ("Violin Sonatina (1939)", "Violin Sonatina, Op 15"),  # shared: Dag Wirén / Lars-Erik Larsson
    ("Four Irish Songs orch. Michael Conway Baker", "Four Irish Songs"),  # Jean Coulthard
    ("Orchestral Suite from Dardanus", "Dardanus (orchestral suites)"),  # Jean-Philippe Rameau

    # Cross-era (2010-2012) bridge relaxed-matcher folds, batch 8 (#151-180),
    # ratified 2026-06-11. (3 accepts auto-dropped as already-grouped; Spohr Danzi
    # straggler re-rejected — chained; Gombert/Sor dups collapsed to one each.)
    ("Ghanaia for solo percussion", "Ghanaia"),  # Matthias Schmitt
    ("Sonata No.3 in F minor (Op.14)", "Sonata for piano no.3 (Op.14) in F minor, 'Concert sans orchestre'"),  # Robert Schumann
    ("Polonaise for orchestra in E flat major", "Polonaise in E flat major"),  # shared: Antonin Dvorak / Stanislaw Moniuszko
    ("Romance", "Romance for violin and piano"),  # shared: Jazeps Vitols / Johan Svendsen
    ("Rakastava (Op.14) arranged for string orchestra and percussion", "Rakastava (The lover), Op.14 arr. for string orchestra, triangle & timpani"),  # Jean Sibelius
    ("Overture - from 'Der Freischütz'", "Der Freischutz (Overture)"),  # Carl Maria von Weber
    ("Musae Jovis a6", "Musae Jovis a 6"),  # Nicolas Gombert
    ("Overture from Béatrice et Bénédict - opera in 2 acts (Op.27)", "Beatrice et Benedict (Overture)"),  # Hector Berlioz
    ("Iberia - suite", "Iberia"),  # Isaac Albeniz
    ("Sonata in A major (M.8)", "Violin Sonata in A major (M.8)"),  # Cesar Franck
    ("Sonata for piano no. 30 (Op. 109) in E major", "Piano Sonata No 30 in E"),  # Ludwig van Beethoven
    ("With joy we go dancing", "Och gladjen den dansar [With joy we go dancing]"),  # Einojuhani Rautavaara
    ("Brezairola", "Brezairola - from Songs of the Auvergne"),  # Joseph Canteloube
    ("Carnival in Paris - Overture/Episode for orchestra (Op.9)", "Carnival in Paris, Op 9"),  # Johan Svendsen
    ("Introduction and variations on Mozart's 'O cara armonia' for guitar (Op.9)", "Introduction and variations on a theme from Mozart's Magic Flute, Op 9"),  # Fernando Sor
    ("Rondo quasi Fantasia for Piano & Orchestra (1872)", "Rondo quasi Fantasia"),  # Martin Wegelius
    ("Dances of Galánta", "Dances of Galánta, (Galántai táncok)"),  # Zoltan Kodaly

    # Cross-era (2010-2012) bridge relaxed-matcher folds, batch 9 (#181-210),
    # ratified 2026-06-11. (3 auto-dropped as already-grouped: Haydn 73, Moonlight,
    # Funérailles; Bach Air re-rejected — excerpt vs whole-suite; Nielsen retargeted
    # to the batch-7 FS.39 canonical to consolidate.)
    ("Egmont, incidental music: Overture (Op.84)", "Egmont Overture, Op 84"),  # Ludwig van Beethoven
    ("Variations on a theme by Haydn (Op.56a) vers. for orchestra \"St Antoni Chorale\"", "Variations on a theme by Haydn, Op 56a"),  # Johannes Brahms
    ("Sonata 1.x.1905 for piano in E flat minor, 'Z ulice'", "Sonata 1.x.1905 for piano in E flat minor"),  # Leos Janacek
    ("Variations on a Slovak Theme", "Variations on a Slovak theme for cello and piano"),  # Bohuslav Martinu
    ("Till Eulenspiegel (Op.28)", "Till Eulenspiegels lustige streiche, Op 28"),  # Richard Strauss
    ("5 movements from the ballet music \"les Petits riens\" (K.299b)", "5 movements from \"Les petits riens\" ballet music, K.299b"),  # Wolfgang Amadeus Mozart
    ("March of the Toys (from the operetta 'Babes in Toyland', 1903)", "March of the Toys from the operetta \"Babes in Toyland\""),  # Victor Herbert
    ("Fantasy and fugue for piano in C major, (K.394) (Vienna 1782)", "Fantasy and fugue for piano K.394 in C major"),  # Wolfgang Amadeus Mozart
    ("Sonata for Piano and Violin in F major (Op.24) 'Spring'", "Violin sonata in F, Op 24 \"Spring\""),  # Ludwig van Beethoven
    ("Capriccio", "Capriccio-Scherzo, Op 25c"),  # Blagoje Bersa
    ("Prague Waltzes (Prazske valciky) (B.99)", "Prague Waltzes"),  # Antonin Dvorak
    ("Träumerei am Kamin - from the opera 'Intermezzo'", "Traumerei am Kamin: Symphonic interlude no.2 from Intermezzo, Op 72"),  # Richard Strauss
    ("Aftonen (evening)", "Aftonen"),  # Hugo Alfvén
    ("Concerto for violin, strings and continuo in B flat", "Violin Concerto in B flat major"),  # Giovanni Battista Pergolesi
    ("Sorcerer's apprentice - symphonic scherzo for orchestra", "The Sorcerer's apprentice - symphonic scherzo for orchestra"),  # Paul Dukas
    ("Overture to Masquerade", 'Overture to Maskarade'),  # Carl Nielsen
    ("Sonata No.6 in G major for transverse flute and harpsichord (Op.6 No.6)", "Sonata in G major for transverse flute and harpsichord, Op 6 no 6"),  # Carl Friedrich Abel

    # Cross-era (2010-2012) bridge relaxed-matcher folds, batch 10 (#211-240),
    # ratified 2026-06-11. Heavy reject batch (Wassenaer/Abel 5-way clusters); 15/15.
    ("When Mary thro' the garden went, No.3 of 8 Partsongs (Op.127. No.3)", "When Mary thro' the garden went (from 8 Partsongs, Op 127 no 3)"),  # Charles Villiers Stanford
    ("Fantasie in F minor for piano four hands (Op. 226)", "Fantasie for piano duet in F minor"),  # Carl Czerny
    ("Concerto for oboe and strings, arranged for trumpet", "Trumpet Concerto in C minor"),  # Domenico Cimarosa
    ("Sonata movement in E minor (B.70) - for 2 pianos", "Sonata movement in E minor for 2 pianos, 8 hands"),  # Bedrich Smetana
    ("Overture to Les Franc-juges (Op.3)", "Les Franc-juges Op 3 (Overture)"),  # Hector Berlioz
    ("Polkas and Études for Piano, Book III", "Etudes and polkas (book 3)"),  # Bohuslav Martinu
    ("Concerto for cello and orchestra No.1 in A minor (Op.33)", "Cello concerto No 1 in A minor"),  # Camille Saint-Saëns
    ("Overture to the 'King and the Charcoal Burner' (1874)", "Overture to the \"King and the Charcoal Burner\" [Kral a Uhlir] (1874)"),  # Antonin Dvorak
    ("Concerto No.6 in E flat major (from Sei Concerti Armonici 1740)", "Concerto armonico no 6 in E flat major (from Sei Concerti Armonici, 1740)"),  # Unico Wilhelm van Wassenaer
    ("Symphony (Op.10 No.2)", "Symphony in B flat major, Op 10 no 2"),  # Carl Friedrich Abel
    ("Ma Vlast No 2 - Vltava", "Vltava (Moldau) - from 'Ma Vlast'"),  # Bedrich Smetana
    ("Sonata for oboe and keyboard (BWV.1030) in B minor", "Sonata for oboe and keyboard, BWV.1030"),  # Johann Sebastian Bach
    ("Sonata for violin and piano (JW 7/7)", "Violin Sonata"),  # shared: Leos Janacek / Francis Poulenc

    # Cross-era (2010-2012) bridge relaxed-matcher folds, batch 11 (#241-270),
    # ratified 2026-06-11. (Tombeau dup collapsed; Liszt PC2 re-rejected — chains
    # via the parked Searle-S split. Many opera-aria/song-set cross-match rejects +
    # the Scarlatti Kk.96 5-way cluster.)
    ("Ecco ridente in cielo - from 'Il Barbiere di Siviglia' Act 1 Sc 1", "Ecco ridente in cielo ('Il barbiere di Siviglia')"),  # Gioachino Rossini
    ("Ma Mère l'Oye ('Mother Goose Suite')", "Ma mere L'Oye (Mother Goose)"),  # Maurice Ravel
    ("Cinq mélodies populaires grecques", "Cinq melodies populaires grecques [5 popular Greek Songs]"),  # Maurice Ravel
    ("Suite No.4 in D minor (Op.1 No.4)", "Suite No 4 in D minor Op 1 no 4 from 'Le Journal du printemps'"),  # Johann Caspar Ferdinand Fischer
    ("Song 'See, see, even Night herself is here' (Z.62/11) - from The Fairy Queen, Act II Scene 3", "See, see, even Night herself is here (Z.62/11) from 'The Fairy Queen'"),  # Henry Purcell
    ("Pamina's aria: Ach, ich fühl's, es ist verschwunden - from 'The Magic Flute', Act 2, Scene 6 no.17", "Pamina's aria: \"Ach, ich fuhl's, es ist verschwunden\" - from 'The Magic Flute'"),  # Wolfgang Amadeus Mozart
    ("Psalm 23 from 5 Psalms of David (1604)", "Psalm 23 [5 Psalms of David (1604)]: 'The Lord is my Shepherd'"),  # Jan Pieterszoon Sweelinck
    ("Newe ausserlesne Paduanen und Galliarden auff allen musicalischen Instrumenten und insonderheit auff Fiolen lieblich zu gebrauchen (mit 6 Stimmen) (Hamburg 1614)", "Newe ausserlesne Paduanen und Galliarden"),  # William Brade
    ("Sonata for piano and violin (Op.34) (1910)", "Violin Sonata, Op 34 (1910)"),  # Leander Schlegel
    ("La Charmeuse", "La Charmeuse for violin, cello and piano"),  # Alexis Contant
    ("Scherzo from A Midsummer Night's Dream", "A Midsummer Night's Dream (Scherzo)"),  # Felix Mendelssohn
    ("Overture 'Othello' (Op.93) (1891-2)", 'Othello - concert overture (Op.93)'),  # Antonin Dvorak
    ("Le Tombeau de Couperin - suite for orchestra", "Le Tombeau de Couperin"),  # Maurice Ravel
    ("Pygmalion, cantata for bass and orchestra", "Pygmalion, cantata for bass and orchestra W 18/5, B 50"),  # Johann Christoph Friedrich Bach
    ("Repleta est malis (KBPJ.35)", "Repleta est malis (KBPJ.35) - sacred concerto"),  # Kaspar Förster
    ("Sonetto 123 di Petrarca (S.158 No.3)", "Sonetto 123 di Petrarca (S.158 No.3): Io vidi in terra angelici costumi"),  # Franz Liszt

    # Cross-era (2010-2012) bridge relaxed-matcher folds, batch 12 (#271-300),
    # ratified 2026-06-11. (Brahms Haydn-Variations auto-dropped: already grouped
    # with batch-9 canonical. R.Strauss Fünf Klavierstücke 6-way cluster + Martinů
    # symphony cluster + Schumann DO-NOT-USE seg + Ives whole-vs-movement rejected.)
    ("Tarantella for guitar", "Tarantella, Op 87b"),  # Mario Castelnuovo-Tedesco
    ("Overture to Prince Igor", "Prince Igor (Overture)"),  # Alexander Borodin
    ("Jauchzet dem Herren alle Welt", "Jauchzet dem Herren alle Welt - cantata for voice, 2 violins, [bassoon] and continuo"),  # Nicolaus Bruhns
    ("Duet 'Wie eine Rosenknospe' and 'Romanze' - from 'The Merry Widow' Act II", "Duet \"Wie eine Rosenknospe\" and \"Romanze\" - from \"The Merry Widow\""),  # Franz Lehár
    ("Music from 'Le Bourgeois Gentilhomme'", "Le Bourgeois Gentilhomme suite, Op 60"),  # Richard Strauss
    ("Concerto grosso (Op.6 No.8) in G minor 'per la notte di Natale' ('Christmas night')", "Concerto grosso in G minor, Op 6 No 8, 'per la notte di Natale'"),  # Arcangelo Corelli
    ("Guitarre", "Guitarre for cello and piano"),  # Moritz Moszkowski
    ("Frithjof's Meerfahrt' - Concert piece for orchestra (Op.5)", "Frithjof's Meerfahrt"),  # Johan Wagenaar
    ("The Graces' Dance; Gavott; Sarabande for the Graces - from Venus and Adonis", "Venus and Adonis (dance extracts)"),  # John Blow
    ("Motet: 'Ach Herr, strafe mich nicht' (Op.110 No.2)", "Ach Herr, strafe mich nicht, Op.110, No.2"),  # Max Reger
    ("Sextet for piano, 2 violins, viola, violincello and double bass in A minor (Op.29) (1869/1873)", "Piano Sextet in A minor"),  # Ludvig Norman
    ("Guitar Prelude No.3 in A minor", "Prelude for guitar no 3 in A minor"),  # Heitor Villa-Lobos
    ("Andante - from Fünf Klavierstücke (Op.3 No.1)", "Andante, Op 3 no 1"),  # Richard Strauss
    ("Introduction and allegro for harp, flute, clarinet and string quartet", "Introduction and allegro"),  # Maurice Ravel
    ("Symphony no.1", "Symphony no 1, H.289"),  # Bohuslav Martinu
    ("Symphony No.4", "Symphony no 4, H.305"),  # Bohuslav Martinu (H-number presence)
    ("Cello Concerto no.1 in D major, H.196", "Cello Concerto No 1 in D, H 196"),  # Bohuslav Martinu (H.196 vs H 196 spacing)
    ("Three Madrigals for violin and viola, H.313", "3 Madrigals for violin and viola"),  # Bohuslav Martinu (Three/3 + H-number)
    ("Trois Fresques de Piero della Francesca (1955)", "The Frescoes of Piero della Francesca"),  # Bohuslav Martinu (cross-language, H.352)
    ("The Kitchen Revue (La revue de cuisine) - suite from the ballet for 6 instruments", "La revue de cuisine - suite from the ballet"),  # Bohuslav Martinu (English gloss + scoring tail; tracks-title form)
    ("The Kitchen Revue (La revue de cuisine) - suite from the ballet", "La revue de cuisine - suite from the ballet"),  # Bohuslav Martinu (segment-title form, no scoring tail — projection lineage)
    ('Symphony No.6 (H.343) [1953] "Fantasies symphoniques" EXPIRED', 'Symphony No.6 (H.343) "Fantasies symphoniques"'),  # Bohuslav Martinu (EXPIRED internal annotation)
    ('Symphony No.6 (H.343) "Fantaisies symphoniques"', 'Symphony No.6 (H.343) "Fantasies symphoniques"'),  # Bohuslav Martinu (Fantaisies/Fantasies FR/EN)
    ('Symphony No.6, "Fantaisies symphoniques"', 'Symphony No.6 (H.343) "Fantasies symphoniques"'),  # Bohuslav Martinu (Fantaisies, no H.343)
    ("Sonnet No.43", "Sonnet No.43 [When most I wink]"),  # Jurriaan Andriessen
    ("3 Pieces (from 'Five Pieces for Strings')", "Romance, Dance and A Homeland Tune (from Five Pieces for Strings)"),  # Heino Eller
    ("String Quintet no.2 in Bb major (Op.87)", "String Quintet No 2 in B flat major, Op 87"),  # Felix Mendelssohn

    # Cross-era (2010-2012) bridge relaxed-matcher AUTO-FOLD tier, ratified
    # 2026-06-11. One deterministic pass over the undecided single-candidate
    # strong folds (ttn_curate bridge --relaxed --auto): 491 folds after
    # dropping 11 chained-target NB lines + 7 dups + 6 cross-chains the
    # per-line NB check couldn't see (sibling folds in the same block became
    # alias sources). Two gate-flagged false
    # positives rejected in the ledger (Earl of Salisbury gaillard≠pavan;
    # '4 Lieder' single-member-vs-set). Clusters + weak + trap-marked deferred
    # to the human flow (2159 deferred).
    ('Meine seel erhebet den Herren (Deutsches Magnificat) - from Puericinium. Teutsche Kirchenlieder und andere geistliche Concert-Gesang', 'Meine seel erhebet den Herren (Deutsches Magnificat)'),  # Michael Praetorius
    ('Prelude no.13 in D flat major', 'Prelude no 13 in D flat major [from 13 Preludes Op 32 for piano]'),  # Sergey Rachmaninov
    ('Silence and music - madrigal for chorus', 'Silence and music'),  # Ralph Vaughan Williams
    ('Leonora Overture No.3 (Op.72b)', 'Leonora Overture No 3'),  # Ludwig van Beethoven
    ('Serenata in vano for clarinet, horn, bassoon, cello and double bass', 'Serenata in vano'),  # Carl Nielsen
    ('La bella Erminia (from Madrigali concertati a 2.3.4 & uno a sei voci)', 'La bella Erminia'),  # Giovanni Rovetta
    ('La chapelle de Guillaume Tell', 'La chapelle de Guillaume Tell, S.160'),  # Franz Liszt
    ('Mátrai Kepek (Mátra Pictures) for choir', 'Mátrai Kepek (Mátra Pictures)'),  # Zoltan Kodaly
    ('Romance in D flat - from Pieces for piano (Op.24 No.9)', 'Romance in D flat - from [10] Pieces for piano, Op 24 no 9'),  # Jean Sibelius
    ('Auf laßt uns den Herren loben (Come let us praise the Lord)', 'Auf lasst uns den Herren loben'),  # Johann Michael Bach
    ('Concerto in D major for violin, piano and string quartet (Op.21) (1891)', 'Concert in D major for violin, piano and string quartet (Op.21) (1891)'),  # Ernest Chausson
    ('Wenn der Herr die Gefangenen zu Zion erlosen wird - Concert for 4 voices, strings & continuo', 'Wenn der Herr die Gefangenen zu Zion erlosen wird'),  # Matthias Weckmann
    ("Sagt dir eine schöne Frau, 'Vielleicht' (If a beautiful woman says to you 'perhaps') - from the film 'Das Lied der Wüste'", "Sagt dir eine schone Frau, 'Vielleicht' - from the film 'Das Lied der Wüste'"),  # Nico Dostal
    ('Tsar Saltan - suite (Op.57)', 'The tale of Tsar Saltan - suite Op 57'),  # Nikolai Rimsky-Korsakov
    ('Tragic overture (Op.81)', 'Tragic Overture in D minor (Op.81) (1881)'),  # Johannes Brahms
    ('The Maidens on the Headlands - symphonic poem', 'Maidens on the Headlands - symphonic poem'),  # Vaino Raitio
    ("From 'Macbeth', Act IV: 'Patria oppressa...'", 'From "Macbeth", Act IV: \'Patria oppressa\' (sung in Hungarian)'),  # Giuseppe Verdi
    ('Kujawiak in A minor for violin and piano (1853)', 'Kujawiak in A minor (1853)'),  # Henryk Wieniawski
    ("Cuba' from Suite espanola No.1 (Op.47 No.8)", 'Cuba (Suite espanola no 1, Op 47 no 8)'),  # Isaac Albeniz
    ("Waltz from 'Faust'", 'Waltz (Faust)'),  # Charles Gounod
    ('Capriccio - Luim (1953)', 'Capriccio - Luim (Merriment)'),  # Flor Alpaerts
    ('Habanera - from Carmen', 'Carmen (Habanera)'),  # Georges Bizet
    ('Four squared for a cappella choir', 'Four squared for a capella choir'),  # John Cage
    ('"Un bel dì" (One Fine Day) - from \'Madame Butterfly\'', 'One Fine Day (Madame Butterfly)'),  # Giacomo Puccini
    ('In a Spring Mood', 'Wiosenno [In a Spring Mood]'),  # Piotr Moss
    ('Sinfonia amore, pace e providenza', 'Sinfonia (Amore, Pace e Providenza (Al fragor di lieta tromba))'),  # Alessandro Scarlatti
    ('Ved solnedgang (Op.46) - for choir and orchestra', 'Ved solnedgang (At sunset) for choir and orchestra, Op.46'),  # Niels Wilhelm Gade
    ('Toccata/Chiaccona', 'Toccata/Chiaccona from Intavolatura di liuto, et di chitarrone, libro primo'),  # Alessandro Piccinini
    ('Après un rêve', 'Après un rêve, Op 7 no 1'),  # shared: Percy Grainger / Gabriel Fauré (retargeted to the op-bearing final, Fauré sweep)
    ('Concerto Grosso for Three Cellos and Orchestra', 'Concerto Grosso for Three Cellos'),  # Krzysztof Penderecki
    ('Rosenkavalier -- Grand Suite', 'Der Rosenkavalier - Grand Suite'),  # Richard Strauss
    ('Quintet for piano, flute, oboe, clarinet and bassoon (Op.6) (1913)', 'Quintet for piano, flute, oboe, clarinet and bassoon'),  # Alexander Albrecht
    ('Lullaby (Berceuse) on the name of Fauré, orch. for violin and orchestra', 'Lullaby (Berceuse) on the name of Faure'),  # Maurice Ravel
    ('Siehe, wie fein und lieblich ist es', 'Siehe, wie fein und lieblich ist es - vocal concerto'),  # Georg Christoph Bach
    ("3 Rose Gardens Songs (1919) : 'Surely I may kiss you'; 'Behind the wall'; 'Tired'", '3 Rose Gardens Songs (1919)'),  # Rued Langgaard
    ('Dance of the Blessed Spirits from Orfeo ed Euridice', 'Dance of the Blessed Spirits (Orfeo ed Euridice)'),  # Christoph Willibald Gluck
    ("L'Apothéose de la Danse", "L'Apotheose de la Danse - orchestral suite of dance music by Rameau"),  # Jean-Philippe Rameau
    ('Sonata for violin and continuo (Brainard F5) (Op.2 No.5) in F major', 'Violin Sonata in F major, Op 2 no 5'),  # Giuseppe Tartini
    ("4 Folk Songs: Mo Nighean Dhu (My dark-haired maiden); O Mistress Mine ; Six Dukes went afishin' ; Mary Thomson", '4 Folk Songs'),  # Percy Grainger
    ('Elegy and Toccata for piano, strings and percussion', 'Elegy and Toccata'),  # Eugen Suchon
    ('Concerto for flute, bassoon, cello, double bass and harpsichord', 'Concerto in G major for flute, bassoon, cello, double bass and harpsichord'),  # Johann David Heinichen
    ('Tarantella for guitar Op. 87b', 'Tarantella, Op 87b'),  # Mario Castelnuovo-Tedesco
    ('Rondo brillante in E flat (Op.62)', 'Rondo brillante in E flat "La gaiete for piano" (J.252) (Op.62)'),  # Carl Maria von Weber
    ('Jezus es a kufarok', 'Jezus es a kufarok [Jesus and the Traders]'),  # Zoltan Kodaly
    ('Die Geschopfe des Prometheus (Op. 43)', 'Die Geschopfe des Prometheus, Op 43 (Overture)'),  # Ludwig van Beethoven
    ("Agnus Dei - 'Baises moy'", "Agnus Dei (Missa 'Baises moy')"),  # Mathurin Forestier
    ("Salome's Dans van de zeven sluiers", "Salome's Dans van de zeven sluiers [Salome's Dance of the Seven Veils]"),  # Flor Alpaerts
    ('Nani mi nani, Damiancho', 'Nani mi nani, Damiancho [Sleep, my Damiancho, sleep]'),  # Lyubomir Pipkov
    ('Bacchanalia, No.10 from Poetické nálady (Poetic tone pictures) (Op.85)', 'Bacchanalia (no 10 from Poeticke nalady)'),  # Antonin Dvorak
    ('La Scala di seta - overture', 'La Scala di seta (The silken ladder) Overture'),  # Gioachino Rossini
    ('In Autumn, Overture (Op.11)', 'In Autumn - concert overture, Op 11'),  # Edvard Grieg
    ("Concerto a quattro in forma Pastorale per il Santo Natale (Op.8 No.6), 'Christmas Concerto'", 'Concerto a quattro in forma Pastorale per il Santo Natale, Op 8, no 6'),  # Giuseppe Torelli
    ('El cant del ocells', 'El cant dels ocells'),  # shared: Bernat Vivancos / Traditional Catalan, arr. Montsalvatge, Xavier / Pau (Pablo) Casals
    ("Five Spirituals from 'A Child of our Time'", "Five Spirituals from 'A Child of our Time' for chorus"),  # Michael Tippett
    ('Symphony no. 10 Compl. Cooke', 'Symphony no 10 (compl. Deryck Cooke)'),  # Gustav Mahler
    ('Norsk kunstnerkarneval (Op.14)', "Norsk kunstnerkarneval (Norwegian artists' carnival), Op 14"),  # Johan Svendsen
    ("Surely this is my mother's room - from Jenufa Act II", "To je mamincina jizba (Surely this is my mother's room) - from Jenufa, Act II"),  # Leos Janacek
    ('Les Biches - suite', 'Les Biches, suite from the ballet (1939-1940)'),  # Francis Poulenc
    ('Concerto for violin, cello, piano and orchestra (Op.56) in C major', 'Triple Concerto for violin, piano and orchestra in C major (Op. 56)'),  # Ludwig van Beethoven
    ('Hulde aan Paul (Op.79)', 'Hulde aan Paul [Homage to Paul], Op 79'),  # Willem Kersters
    ('Meeresstille und gluckliche Fahrt', 'Meeresstille und gluckliche Fahrt - Overture, Op 27'),  # Felix Mendelssohn
    ('Prélude à la Damoiselle élue', 'Prelude à la Damoiselle elue [The Blessed Damsel]'),  # Claude Debussy
    ('Piano Preludes (1926)', '3 Preludes for piano'),  # George Gershwin
    ('2 pieces for cello & piano, Op.2 (Prélude; Danse Orientale)', '2 pieces for cello & piano, Op 2'),  # Sergey Rachmaninov
    ('Mentre ti lascio, o figlia', 'Mentre ti lascio, o figlia - aria for bass and orchestra, K.513'),  # Wolfgang Amadeus Mozart
    ("L'entretien des Muses (from Pieces de clavessin, Paris 1724)", "L'entretien des Muses (from Pieces de clavecin, Paris 1724)"),  # Jean-Philippe Rameau
    ("Sonata No.6, 'Senti lo Mare'", "Sonata no 6, 'Senti lo Mare' (Listen to the Sea)"),  # Giuseppe Tartini
    ('Symphonic Dance No.4 (Andante) - from Symphonic dances (Op.64)', 'Symphonic Dance No 4, Op 64'),  # Edvard Grieg
    ('Erminia, scÃ¨ne lyrique-dramatique', 'Erminia, scene lyrique-dramatique for soprano and orchestra'),  # Juan Crisostomo Arriaga
    ('On Hearing the First Cuckoo in Spring', 'On hearing the first cuckoo in spring for orchestra (RT.6.19) (1911/12)'),  # Frederick Delius
    ("Sonata No.9 'Black Mass' (Op.68)", 'Sonata no 9 in F major "Black Mass", Op 68'),  # Alexander Scriabin
    ('Towards a Higher Light', 'Naar Hoger Licht (Towards a Higher Light), symphonic poem with cello solo (1933)'),  # Lodewijk De Vocht
    ('Overture from the Incidental music to König Stephan (Op.117)', 'Overture from the Incidental music to König Stephan'),  # Ludwig van Beethoven
    ('Litaniae de providential divina (c.1726)', 'Litaniae de providential divina'),  # Grzegorz Gerwazy Gorczycki
    ('Cello Concerto in A minor (Op.129)', 'Cello Concerto in A minor'),  # Robert Schumann
    ('Requiem Mass for chorus and orchestra no. 1 in C minor; (à la mémoire deLouis XVI)', 'Requiem Mass for chorus and orchestra no 1 in C minor'),  # Luigi Cherubini
    ('Messe Basse - for solo soprano, choir and orchestra', 'Messe Basse'),  # Gabriel Fauré
    ('Etude no.4 in G major (Un Peu Modéré) - from 12 Estúdios for guitar (A.235)', 'Etude no 4 in G major - from 12 Studies for guitar, A.235'),  # Heitor Villa-Lobos
    ('Divertimento for Strings', 'Divertimento for Strings (1948, rev. 1954)'),  # shared: Oskar Morawetz / Gareth Walters
    ("Potpourri Caracteristique 'Den Brug over den Oceaan' (1873", "Potpourri Caracteristique 'Den Brug over den Oceaan' [The Bridge over the Ocean]"),  # Albert Grundt
    ('Cello Concerto in E flat major (G.474)', 'Cello Concerto no 1 in E flat major'),  # Luigi Boccherini
    ('Candombe: Llamada de tambores (Ritmos y sonidos de Uruguay y Argentina)', 'Candombe: Llamada de tambores (Ritmos y sonidos de Huruguay y Argentina)'),  # Daniel Binelli
    ('Légende, for violin & piano (Op.17) (published 1860)', 'Legende for violin and piano, Op 17'),  # Henryk Wieniawski
    ('Scale, tear!', 'Scale, tear! (Halog, hasadj meg!) - folk prayers'),  # Miklos Kocsar
    ('Hungarian Dance No. 1 in G minor', 'Hungarian dance no. 1 in G minor, orch. composer'),  # Johannes Brahms
    ("Cinderella's waltz from Zolushka - suite no.1 (Op.107)", "Cinderella's waltz from Zolushka [Cinderella] suite no 1, Op 107"),  # Sergey Prokofiev
    ('Illuxit sol (c.1700)', 'Illuxit sol'),  # Grzegorz Gerwazy Gorczycki
    ('The Water Goblin (Op.107)', 'Vodnik - The Water Goblin, Op 107'),  # Antonin Dvorak
    ('Serenata in vano for clarinet, horn, bassoon, cello and double bass (FS.68)', 'Serenata in vano'),  # Carl Nielsen
    ('Der Bürger als Edelmann (Le Bourgeois gentilhomme) - suite (Op.60)', 'Der Burger als Edelmann - suite'),  # Richard Strauss
    ('Erwartung - No.1 from 4 lieder (Op.2)', 'Erwartung, Op 2 no 1'),  # Arnold Schoenberg
    ('Bajka - concert overture', 'Bajka [The fairy tale] - concert overture'),  # Stanislaw Moniuszko
    ('La Création du monde - ballet (Op.81a)', 'La Creation du monde, ballet (Op.81a) (overture & 5 scenes)'),  # Darius Milhaud
    # --- Darius Milhaud curation batch (2026-07-18): recording-anchored +
    # catalogue-verified folds. Op.81/81a and Le Globe-trotter verdicts in
    # musicological-notes.txt; the orchestral Globe-trotter version and the
    # whole-suite Scaramouche spellings are deliberately left split. ---
    ('La creation du monde, Op 81a', 'La Creation du monde, ballet (Op.81a) (overture & 5 scenes)'),  # Darius Milhaud (81a spelling; rec p010brcj)
    ('La création du monde (Op.81)', 'La Creation du monde, ballet (Op.81a) (overture & 5 scenes)'),  # Darius Milhaud (Op.81 == 81a ballet; 81b chamber ver. absent)
    ('La crÃ(c)ation du monde (Op.81)', 'La Creation du monde, ballet (Op.81a) (overture & 5 scenes)'),  # Darius Milhaud (mojibake straggler → final canonical)
    ('Le Globe-trotter, Op.358', 'The Globetrotter suite, Op.358 (orig. for solo piano)'),  # Darius Milhaud (rec p00t31xp spans both spellings)
    ('Trois Psaumes de David, Op. 339', '3 Psaumes de David for chorus, Op 339'),  # Darius Milhaud (trois/for-chorus)
    ('Suite for clarinet, violin and piano (Op.157b)', 'Suite for clarinet, violin and piano, Op 157b (Le voyageur sans bagages)'),  # Darius Milhaud (subtitle only)
    ('Segoviana, Op.366', 'Segoviana'),  # Darius Milhaud (-> bare segment title; whole-suite follow-up)
    ('Three Rag caprices arr. for small orchestra, Op 78', 'Three Rag caprices, Op 78 (1922)'),  # Darius Milhaud (arr-tail ate the Op no.)
    ('Brazileira from Scaramouche suite op.165b', 'Brazileira from Scaramouche, Op.165b'),  # Darius Milhaud (excerpt; suite-word)
    # --- Milhaud whole-suite consolidation (2026-07-18 follow-up): the 2-piano
    # Scaramouche suite + Segoviana fragment to the BARE segment title the
    # recording carries (bare title as TARGET is composer-scoped, so Sibelius's
    # Scaramouche is untouched); the Brazileira-from-Scaramouche EXCERPT stays split. ---
    ('Scaramouche: Suite for 2 Pianos (Op.165b)', 'Scaramouche'),  # Darius Milhaud
    ("Scaramouche [Suite for 2 pianos after incidental music for 'Le medecin Volant']", 'Scaramouche'),  # Darius Milhaud
    ('Scaramouche (after incidental music for Le medecin volant)', 'Scaramouche'),  # Darius Milhaud
    ('Scaramouche (Vif; Modéré, Brasileira)', 'Scaramouche'),  # Darius Milhaud (movements-listed = whole suite)
    ('Scaramouche (Vif; Modéré, Braziliera )', 'Scaramouche'),  # Darius Milhaud (Braziliera misspelling)
    ('Segoviana for guitar (Op.366)', 'Segoviana'),  # Darius Milhaud (-> bare segment title)
    ('The American Girl', 'Die Amerikanerin (The American Girl) - lyric painting for soprano and ensemble'),  # Johann Christoph Friedrich Bach
    ('Maskerade (FS.39) - overture', 'Maskerade (overture)'),  # Carl Nielsen
    ("Symphony no.22 (H.1.22) in E flat major 'The Philosopher'", 'Symphony No 22 in E flat, "The Philosopher"'),  # Joseph Haydn
    ('Miserere Mei Deus', 'Miserere Mei Deus - concertato a due chori'),  # shared: Leonardo Leo / Gregorio Allegri
    ('Concerto festivo for orchestra', 'Concerto festivo for orchestra (Pomposo; Lirico; Giocoso)'),  # Andrzej Panufnik
    ('Der Zephir â\x80\x93 from 6 Blumenleben (Op.30 No.5)', 'Der Zephir - from 6 Blumenleben'),  # Jenö Hubay
    ('A Charm of lullabies for mezzo-soprano and piano (Op.41)', 'A Charm of lullabies, Op 41'),  # Benjamin Britten
    ('20 Mazurkas for piano (Op. 50); no. 1 in E major; no 2; no. 13', '20 Mazurkas for piano, Op 50 nos 1, 2 & 13'),  # Karol Szymanowski
    ('32 Piano Variations in C minor (Wo0.80)', '32 Variations for Piano in C minor, Wo0.80'),  # Ludwig van Beethoven
    ('3 Shakespeare Songs for Chorus', '3 Shakespeare songs'),  # Ralph Vaughan Williams
    ('Meine seel erhebet den Herren', 'Meine seel erhebet den Herren (Deutsches Magnificat)'),  # Michael Praetorius
    ('Suite No.1 from "Carmen"', 'Carmen Suite no 1'),  # Georges Bizet
    ('Concerto for flute and strings in D minor', 'Concerto for flute and strings in D minor (H.426) (1747?)'),  # Carl Philipp Emanuel Bach
    ('Liebster Jesu, hor mein Flehen - dialogue for 5 voices, 2vn, 2va & bc', 'Liebster Jesu, hor mein Flehen'),  # Johann Michael Bach
    ('The Night of the Witches, symphonic poem', 'The Night of the Witches'),  # Eugen Suchon
    ("Raduz and Mahulena (Op.16), 'A fairy tale suite' ; Mourning Music , Runa's curse and how love triumphed over it]", "Raduz and Mahulena, Op 16 'A fairy tale suite'"),  # Josef Suk
    ('Troldtog (March of the Dwarfs) - from Lyric Pieces Book 5 (Op.54 No.3)', 'Troldtog (March of the Dwarfs) - from Lyric Pieces Book'),  # Edvard Grieg
    ('Drei Bruchstücke aus Wozzeck (Op. 7)', '3 Bruchstücke aus Wozzeck'),  # Alban Berg
    ('2 Marches in E flat major for wind', '2 Marches for wind band'),  # Joseph Haydn
    ("Giovanna D'Arco", "Giovanna d'Arco - Sinfonia"),  # Giuseppe Verdi
    ('3 songs for American schools (words: Fiona Macleod]', '3 Songs for American Schools'),  # Jean Sibelius
    ('2 Motets: 1.Es ist das Heil uns kommen her ; 2.Schaffe in mir, Gott, ein reines Herz (Op.29)', '2 Motets, Op 29'),  # Johannes Brahms
    ('Symphony of Psalms (1930 revised 1948) (Exaudi orationem mean (Ps 38, 13-14); Expectans expectavi (Ps.39, 1-4); Alleliua. Laudate Dominum (Ps.150))', 'Symphony of Psalms'),  # Igor Stravinsky
    ('Cancoes regionais portuguesas (Op.39) (1943-88)', 'Cancoes regionais portuguesas [Portuguese Regional Songs], Op 39 (1943-88)'),  # Fernando Lopes-Graca
    ('Le voile du bonheur (1971)', 'Le voile du bonheur [The Veil of Happiness]'),  # Louis Andriessen
    ('Die schweigsame Frau - potpourri', 'Potpourri from the opera Die schweigsame Frau'),  # Richard Strauss
    ('Sonata for violin or cello and piano (M.8) in A major', 'Violin Sonata in A major (M.8)'),  # Cesar Franck
    ("V prirode (In Nature's Realm) (Op.91)", "In Nature's Realm (Overture), Op 91"),  # Antonin Dvorak
    ('Mazurka in G major, for violin and piano (Op.26)', 'Mazurka in G major, Op 26'),  # Aleksander Zarzycki
    ('Marcia - from Serenade for Strings (Op.11)', 'Marcia [March] from Serenade for Strings, Op 11 (1937)'),  # Dag Wirén
    ('Trio No.1 for piano, violin and cello in F (Op.18)', 'Piano Trio No 1 in F major, Op 18'),  # Camille Saint-Saëns
    ('The Music Makers for contralto, choir and orchestra (Op.69)', 'The Music Makers, Op 69'),  # Edward Elgar
    ('Variations on "Casta diva... Ah! Bello a me ritorna" from Bellini\'s \'Norma\' for cornet and piano', 'Variations on "Casta diva - Ah! Bello" from Bellini\'s \'Norma\''),  # Jean-Baptiste Arban
    ("Agnus Dei - 'Et ecce terrae motus'", 'Agnus Dei - Et ecce terrae motus (for 12 voices)'),  # Antoine Brumel
    ('25 Variations and Fugue on a Theme by G.F.Handel (Op.24)', '25 Variations and fugue on a theme by G F Handel, Op 24'),  # Johannes Brahms
    ('Prelude and Fugue (Op. 37) in G', 'Prelude and fugue in G major for organ, Op 37 no 2'),  # Felix Mendelssohn
    ('Wie bist du, meine Königin (Op.32 No.9)', 'Wie bist du, meine Konigin (Op.32 No.9) (song)'),  # Johannes Brahms
    ('Blow wind gently (Op.23 No.6b)', 'Tuule, tuuli leppeammin (Blow wind gently) (Op.23 No.6b)'),  # Jean Sibelius
    ('The Maidens on the Headlands', 'Maidens on the Headlands - symphonic poem'),  # Vaino Raitio
    ('Och glädjen den dansar', 'Och gladjen den dansar [With joy we go dancing]'),  # Einojuhani Rautavaara
    ('Benedic Domino, anima mea - from Liber Canticorum II (1952-53)(Op.59a)', 'Benedic Domino, anima mea, Op 59a'),  # Vagn Holmboe
    ('Ballade for flute', 'Ballade for Flute and Piano (arr for flute and orchestra)'),  # Frank Martin
    ('Introduction e staccato etude', 'Introduction e staccato etude for trumpet and orchestra'),  # Uuno Klami
    ('Symphony No. 43 in E flat major "Mercury" (H. 1/43)', 'Symphony No.43 in E flat major "Mercury" (H.1/43)'),  # Joseph Haydn
    ('Toccata/Chiaccona - from Intavolatura di liuto, et di chitarrone, libro primo (Bologna 1623)', 'Toccata/Chiaccona from Intavolatura di liuto, et di chitarrone, libro primo'),  # Alessandro Piccinini
    ('Azulão [Blue Bird]', 'Blue Bird'),  # Jayme Ovalle
    ('2 Elegiac melodies for string orchestra (Op.34) No.2 - Varen (Spring)', '2 Elegiac melodies for string orchestra, Op 34'),  # Edvard Grieg
    ('Schönster Tulipan - Suite of Variations on a Swiss Folk Song for 2 violins (Op.294)', 'Schonster Tulipan - Suite of Variations on a Swiss Folksong Op 294'),  # Caspar Diethelm
    ('Le Chasseur Maudit, symphonic poem (M.44)', 'Le Chasseur Maudit'),  # Cesar Franck
    ("Viennese Clock and Entrance of the Emperor and His Courtiers (from 'Hary János')", 'Viennese Clock and Entrance of the Emperor and His Courtiers (Hary Janos)'),  # Zoltan Kodaly
    ("Cinderella's waltz from (Cinderella) - suite no.1 (Op.107)", "Cinderella's waltz from Zolushka [Cinderella] suite no 1, Op 107"),  # Sergey Prokofiev
    ('Solemn Procession to Gethsemani', 'Solemn Procession to Gethsemani (Part II of Evangelical Diptych)'),  # Lodewijk Mortelmans
    ('Bacchus et Arianne - Suite No.2 (Op.43)', 'Bacchus et Ariane - Suite No 2, Op 43'),  # Albert Roussel
    ('Suite for accordion and piano', 'Canadian folk-song suite for accordion and piano'),  # Andrew Huggett
    ('St. Matthew Passion - Opening Chorus (BWV.244:1)', 'St. Matthew Passion (Opening Chorus)'),  # Johann Sebastian Bach
    ('Overture to La Fille du régiment', 'Overture (La Fille du regiment)'),  # Gaetano Donizetti
    ('King Lily of the Valley', 'Kung Liljekonvalje (King Lily of the Valley)'),  # David Wikander
    ('Roméo et Juliette - symphonie dramatique (Op.17) [orchestral movements only]', 'Romeo et Juliette - symphonie dramatique, Op 17 [1839]'),  # Hector Berlioz
    ('Dahomeyan Rhapsody (1893)', 'Dahomeyse Rapsodie [Dahomeyan Rhapsody] (1893)'),  # August de Boeck
    ("A Tale of a Winter's evening (Op.9)", "A Winter's tale, Op 9"),  # Josef Suk
    ('Zlaty kolovrat - symphonic poem (Op.109)', 'The Golden spinning-wheel (Zlaty kolovrat) - symphonic poem, Op 109'),  # Antonin Dvorak
    ('Venetian Boat Song (Op.30 No.6)', "Venetian Boat Song from 'Songs Without Words', book II, Op 30 no 6"),  # Felix Mendelssohn
    ('In Natures Realm (Op.63)', "V prirode (In Nature's Realm), Op 63"),  # Antonin Dvorak
    ('Dance, clarion air', 'Dance, clarion air - madrigal for 5-part chorus'),  # Michael Tippett
    ('Mu Isamaa On Minu Arm', 'Mu Isamaa On Minu Arm [My Fatherland you are my love]'),  # Gustav Ernesaks
    ('Allegro con fuoco from the Sonata for violin and piano', 'Sonata for violin and piano'),  # shared: Leos Janacek / Francis Poulenc
    ('Les Élémens: simphonie nouvelle', 'Les Elemens: simphonie nouvelle for 2 violins, 2 flutes & b.c.'),  # Jean-Fery Rebel
    ('Es ist ein großer Gewinn', 'Es ist ein grosser Gewinn - sacred concerto for soprano, 4 violins and continuo'),  # Johann Michael Bach
    ('Free Variations on Byzantium theme for cello and orchestra', 'Free Variations on Byzantine theme for cello and orchestra'),  # Paul Constantinescu
    ('Aufforderung zum Tanz', 'Aufforderung zum Tanz [Invitation to the Dance]'),  # Carl Maria von Weber
    ('Musica della commedia di Franc. Corteccia recitata al secondo convito', 'Musica della commedia di Francesco Corteccia recitata al secondo convito'),  # Francesco Corteccia
    ('Leonora No.3 - overture (Op.72b)', 'Leonora Overture No 3'),  # Ludwig van Beethoven
    ('Excerpts from Tassilone', 'Tassilone - excerpts'),  # Agostino Steffani
    ('Avondmuziek for wind octet (1915)', 'Avondmuziek'),  # Flor Alpaerts
    ("Martha (aka 'Der Markt zu Richmond') - overture", "Martha ('Der Markt zu Richmond') -  overture"),  # Friedrich von Flotow
    ('Satie Gnossienne no. 1 for piano', 'Gnossienne no 1 for piano'),  # Erik Satie
    ("Trio des Jeunes Ismaelites - from L'enfance du Christ", 'Trio des Ismaelites from "L\'enfance du Christ"'),  # Hector Berlioz
    ("One Fine Day - from 'Madame Butterfly'", 'One Fine Day (Madame Butterfly)'),  # Giacomo Puccini
    ('My foolish heart (improvisation)', 'My foolish heart'),  # Victor Young
    ("4 Folk Songs: My dark-haired maiden; O Mistress Mine ; Six Dukes went afishin' ; Mary Thomson", '4 Folk Songs'),  # Percy Grainger
    ("Sorcerer's apprentice", "The Sorcerer's apprentice - symphonic scherzo for orchestra"),  # Paul Dukas
    ('2 Dances from the Lőcse Virginal Book', '2 Dances from Locse Virginal Book'),  # Trad. Hungarian
    ("The Gum-Suckers' March", "The Gum-Suckers' March, No.4 from In a Nutshell suite for orchestra"),  # Percy Grainger
    ('Overture - Peter Schmoll und sein Nachbarn (J.8)', 'Peter Schmoll und sein Nachbarn (Overture)'),  # Carl Maria von Weber
    ('La bella Erminia - from Madrigali concertati a 2.3.4 & uno a sei voci (Venice 1629)', 'La bella Erminia'),  # Giovanni Rovetta
    ('Agnus Dei for chorus', 'Agnus Dei'),  # Samuel Barber
    ("Symphony, Duet and Chorus 'Let all mankind the pleasure share And bless this happy day', from 'Dioclesian', Z.627", "Symphony, Duet and Chorus 'Let all mankind the pleasure share"),  # Henry Purcell
    ('O Maria salvatoris mater (a 8)', 'O Maria salvatoris mater'),  # John Browne
    ('Pierrette fatyla, Keringo (The Wedding Waltz) from the incidental music to Pierrette fatyla by Arthur Schnitzler', 'Pierrette fatyla - keringo'),  # Ernõ Dohnányi
    ('Marcia (March) from Serenade for string orchestra (Op.11) in C major (1937)', 'Marcia [March] from Serenade for Strings, Op 11 (1937)'),  # Dag Wirén
    ('Siehe, wie fein und lieblich ist es - vocal concerto for 2 tenors, bass and instruments', 'Siehe, wie fein und lieblich ist es - vocal concerto'),  # Georg Christoph Bach
    ("A Midsummer Night's Dream (Op.61)", "A Midsummer Night's Dream - incidental music, Op 61"),  # Felix Mendelssohn
    ('Bacchanalia, No.10 from Poetické nálady (Op.85)', 'Bacchanalia (no 10 from Poeticke nalady)'),  # Antonin Dvorak
    ('The Lark Ascending for violin & orchestra', 'The Lark Ascending'),  # Ralph Vaughan Williams
    ('Rom�o et Juliette - symphonie dramatique (Op.17)', 'Romeo et Juliette - symphonie dramatique, Op 17 [1839]'),  # Hector Berlioz
    ("Two orchestral intermezzi from 'Il Gioielli della Madonna' (Op.4)", "Two orchestral intermezzi from 'I Gioielli della Madonna', Op 4"),  # Ermanno Wolf-Ferrari
    ('Der Pfeil und das Lied; Marien Lied; Ich komme Heim aus dem Sonnenland - from 6 Lieder (Op.17 Nos 1, 2 & 3)', '6 Lieder (Op 17 nos 1, 2 & 3)'),  # Elisabeth Kuyper
    ('African Suite (1944) for Strings', 'African suite for harp and strings'),  # Fela Sowande
    ('Ick voer al over Rijn (47)', 'Ick voer al over Rijn'),  # Jan Pieterszoon Sweelinck
    ('Overture to Norma', 'Norma Overture'),  # Vincenzo Bellini
    ('Draw on, sweet night', 'Draw on, sweet night for violin & viols'),  # John Wilbye
    ('Vorrei spiegarvi, oh Dio', 'Vorrei spiegarvi, oh Dio - aria for soprano and orchestra, K.418'),  # Wolfgang Amadeus Mozart
    ("Les roses d'Ispahan (Op.39 No.4) (1884)", "Les roses d'Ispahan"),  # Gabriel Fauré
    ('Suite in E minor', 'Overture (Suite) in E minor (Tafelmusik, 1ère production)'),  # Georg Philipp Telemann
    ('La Fanfare du Printemps (Spring Fanfare)', 'Spring fanfare'),  # Abbé Joseph Bovet
    ('Sonata torso for violin and piano, from incomplete Sonata of 1911', 'Violin Sonata torso, from incomplete Sonata'),  # George Enescu
    ('In the mists - 4 pieces for piano', 'In the mists [V mihach] - 4 pieces for piano'),  # Leos Janacek
    ('2 graduals for chorus', '2 graduals for chorus: Locus iste & Christus Factus est'),  # Anton Bruckner
    ('Doucéte, sucrine, toute de miél', 'Doucete, sucrine, toute de miel [Paris, 1603]'),  # Claude le Jeune
    ("A sa chut' il se va dejetér", "A sa chut' il se va dejeter [Paris, 1603]"),  # Claude le Jeune
    ('Zomer-idylle (1928)', 'Zomer-idylle [Summer Idyll]'),  # Flor Alpaerts
    ("Impressions d'enfance (Op.28)", "Impressions d'enfance for violin and piano, Op 28"),  # George Enescu
    ('Fantaisie et variations brillantes sur 2 airs favoris connus for guitar (Op.30) in E minor (Fantasia no.7)', 'Fantaisie et variations brillantes sur 2 airs favoris connus'),  # Fernando Sor
    ('11 Variations on a Theme by Haydn, for 9 wind instruments and double bass', '11 Variations on a theme by Haydn'),  # Jean Françaix
    ('Gloria - from Mass Puer natus est nobis', 'Gloria from Mass Puer natus est nobis for 7 voices'),  # Thomas Tallis
    ('No.8 La fille aux cheveux de lin', 'La fille au cheveux de lin'),  # Claude Debussy
    ("White-flowering days for chorus (Op.37); [no.8 in 'A Garland for the Queen']", 'White-flowering days (A Garland for the Queen), Op 37 no 8'),  # Gerald Finzi
    ('Frescoes of Piero della Francesca', 'The Frescoes of Piero della Francesca'),  # Bohuslav Martinu
    ('Harold en Italie (Op.16)', 'Harold en Italie - symphony for viola and orchestra, Op 16'),  # Hector Berlioz
    ('Fantasia in G minor (g1)', 'Fantasia in G minor (g1) - fuga contraria, from Fitzwilliam Virginal Book'),  # Jan Pieterszoon Sweelinck
    ("Se mai, Tirsi, mio bene - from the cantata 'Clori e Tirsi'", 'Clori e Tirsi: cantata ("Se mai, Tirsi, mio bene")'),  # Johann David Heinichen
    ('Walsingham (Have with you to Walsingham)', 'Walsingham (Have with you to Walsingham) - variations for keyboard (MB.7.8)'),  # William Byrd
    ('De kleine Rijnkoning [The Little King of the Rhine] (1906) - suite for symphonic orchestra after the opera De Rijndwegern', 'The Little King of the Rhine'),  # August de Boeck
    ('F�rv�rskv�ll (An evening early in spring)', 'Forvarskvall (An evening early in spring)'),  # David Wikander
    ('Scènes Breugheliennes', 'Scenes Breugheliennes (Scenes after Breughel)'),  # Michel Brusselmans
    ('Canamus, amici, canamus & Finnegans wake', "Canamus, amici, canamus; Finnigan's wake"),  # Henk Badings
    ('Le Temple de la Gloire', 'Le Temple de la Gloire (orchestral suites)'),  # Jean-Philippe Rameau
    ('Symphonic dance no.2 (Op.64 No.2)', 'Symphonic dance no 2 (Allegro grazioso) Op 64 no 2'),  # Edvard Grieg
    ('Kõver Kuuseke', 'Kover Kuuseke [A little crooked fir-tree] (1931)'),  # Mart Saar
    ('Ricordati (op.26/1) (c.1856)', 'Ricordati (Op 26 no 1)'),  # Louis Moreau Gottschalk
    ("David's Lamentation", "David's Lamentation [from Samuel 18:33]"),  # William Billings
    ('Late Summer Nights (1914)', 'Sensommarnätter (Late Summer Nights) Op 33 (1914)'),  # Wilhelm Stenhammar
    ('(2) Finnlandische Volksweisen (Finnish Folksong arrangements) for piano duet (Op.27)', '2 Finnlandische Volksweisen (Finnish folksong arrangements) for 2 pianos, Op 27'),  # Ferruccio Busoni
    ('Sonata movement in E minor (B.70)', 'Sonata movement in E minor for 2 pianos, 8 hands'),  # Bedrich Smetana
    ('Improvisation for violin, cello & piano', 'Improvisation for violin, cello & piano (dedicated to Miron Soarec)'),  # Dinu Lipatti
    ('Concertino for harp and orchestra', 'Harp Concertino'),  # Zvonimir Ciglic
    ("Le poème de l'extase [Symphony no.4] (1905-08)", "Le Poeme de l'extase for orchestra, Op 54"),  # Alexander Scriabin
    ('V Tatrach [In the Tatra mountains] - symphonic poem (Op.26)', 'In the Tatra mountains, op 26'),  # Vitezslav Novak
    ('Invitation to the Dance', 'Aufforderung zum Tanz [Invitation to the Dance]'),  # Carl Maria von Weber
    ('3 Chansons for unaccompanied chorus', '3 Chansons'),  # Maurice Ravel
    ('Der Tod, das ist die kühle Nacht', 'Der Tod, das ist die kühle Nacht, Op 96 no 1'),  # Johannes Brahms
    ('5 Bukoliki [Bucolics]', '5 Bukoliki [Bucolics] for viola and cello'),  # Witold Lutoslawski
    ('Tempo di Waltz', "Tempo di Waltz for children's chorus and piano"),  # Alexander Tekeliev
    ('The Warriors (music to an imaginary ballet) for orchestra and 3 pianos', 'The Warriors (music to an imaginary ballet)'),  # Percy Grainger
    ("Son qual misera Colomba (from 'Cleofide')", 'Aria: Son qual misera Colomba from "Cleofide"'),  # Johann Adolf Hasse
    ('Galathea & Mahnung', 'Galathea & Mahnung [Galathea & Warning] from Brettl-Lieder (Cabaret Songs)'),  # Arnold Schoenberg
    ('I Love Thee (Op.5 No.3)', "I Love Thee - no.3 from Hjertets melodier (The heart's melodies) (Op.5)"),  # Edvard Grieg
    ("Kochanka hetmanska [The Commander-in-Chief's Lover] -- overture", "The Commander-in-Chief's Lover (overture)"),  # Stanislaw Moniuszko
    ('Schönster Tulipan (Op.294)', 'Schonster Tulipan - Suite of Variations on a Swiss Folksong Op 294'),  # Caspar Diethelm
    ('El Corpus en Sevilla from Iberia', "El Corpus en Sevilla from 'Iberia' (Book 1)"),  # Isaac Albeniz
    ('Recitativo and scherzo-caprice for violin solo, (Op.6)', 'Recitativo and scherzo-caprice'),  # Fritz Kreisler
    ('Song of the Earth (Op.93) (1919)', 'Jordens sang (Song of the Earth), Op 93'),  # Jean Sibelius
    ("Les nuits d'été (Op.7) (Six songs on poems by Théophile Gautier)", "Les nuits d'ete, Op 7"),  # Hector Berlioz
    ("Sonata à 8 - from 'Musiche sacre concernenti messa, e salmi concertati con istromenti, imni, antifone et sonate' (Venice 1656)", 'Sonata à 8 - from "Musiche sacre concernenti messa\' (Venice 1656)'),  # Francesco Cavalli
    ('Cinderella - suite no.1 (Op.107)', 'Cinderella [Zolushka] - Suite no 1, Op 107'),  # Sergey Prokofiev
    ('Impressioni brasiliane for orchestra (1928)', 'Impressioni Brasiliane'),  # Ottorino Respighi
    ('Ardo, sospiro e piango - duet for soprano, baritone and continuo', 'Ardo, sospiro e piango'),  # Alessandro Stradella
    ('János Vitéz (The Hero John) - excerpts', 'Janos Vitez [The Hero (Sir) John] - excerpts'),  # Pongrac Kacsoh
    ('Ballo alla polacha for harpsichord', 'Ballo alla polacha for harpsichord ["Intavolatura di balli d\'arpicordo", 1621]'),  # Giovanni Picchi
    ('Ruralia Hungarica for orchestra (Op.32b)', 'Ruralia Hungarica, Op 32b'),  # Ernõ Dohnányi
    ("Méditation - from the opera 'Thaïs'", "Meditation from 'Thais'"),  # Jules Massenet
    ('Häämarssi (Wedding March)', 'Haamarssi (Wedding March) (Op.3b No.2)'),  # Toivo Kuula
    ('Organ Sonata finale', 'Organ Sonata per flauto'),  # Vincenzo Petrali
    ('4 Letzte Lieder (AV.150)', '4 Letzte Lieder for voice and orchestra (AV.150)'),  # Richard Strauss
    ('Concert Fantasia on two Russian themes (Op.33)', 'Concert Fantasia on two Russian themes for violin and orchestra, Op 33'),  # Nikolai Rimsky-Korsakov
    ("Concerto Grosso No.12 in D minor, 'Folia'", 'Concerto Grosso no 12 in D minor, "Folia" (after Corelli\'s Sonata Op 5 no 12)'),  # Francesco Geminiani
    ('Saltarelle (Op.74) (Emile Deschamps)', 'Saltarelle, Op 74'),  # Camille Saint-Saëns
    ('Golden Wedding', 'La Cinquantaine (Golden Wedding)'),  # Gabriel Marie
    ("Divisions on 'John Come Kiss Me Now'", "Prelude and divisions on 'John come kiss me now'"),  # Thomas Baltzar
    ('Vardar - Rhapsodie bulgare (Op.16)', 'Vardar - Rhapsodie bulgare'),  # Pancho Vladigerov
    ('Thalia-ouverture for wind orchestra', 'Thalia - overture for wind orchestra'),  # Nicolaas Arie Bouwman
    ("Christmas Cantata': Oh di Betlemme altera poverta for soprano and orchestra", 'Oh di Betlemme altera poverta for soprano and orchestra'),  # Alessandro Scarlatti
    ('Erminia, scène lyrique-dramatique', 'Erminia, scene lyrique-dramatique for soprano and orchestra'),  # Juan Crisostomo Arriaga
    ("Das war sehr gut./Dann aber, wie ich Sie gespürt hab' hier im Finstern steh'n - from the opera 'Arabella', Act 3 final scene", "Das war sehr gut .../Dann aber, wie ich Sie gespurt hab' (from Arabella)"),  # Richard Strauss
    ('Introduction and variations on a Polish Noël', 'Introduction and variations on a Polish Noel [aka Infant holy infant lowly]'),  # Alexandre Guilmant
    ('Come Holy Spirit', 'Come Holy Spirit for SATB with organ accompaniment'),  # Ruth Watson Henderson
    ('Valse-fantasie in B minor for orchestra', 'Valse-fantasie in B minor'),  # Mikhail Ivanovich Glinka
    ('Missa Tempore paschali: Agnus Dei', 'Agnus Dei from Missa tempore paschali for 6 voices (1564)'),  # Nicolas Gombert
    ('Variations for violin and piano in E minor (D.802) [Op.posth.160]', 'Variations for violin and piano in E minor (D.802)'),  # Franz Schubert
    ('Silent woods (B.182)', 'Klid (Silent woods), B182'),  # Antonin Dvorak
    ('The Veil of Happiness', 'Le voile du bonheur [The Veil of Happiness]'),  # Louis Andriessen
    ('Maria the Gypsy Girl', 'Ciganka Marija [Maria the Gypsy Girl] (1905)'),  # Benjamin Ipavec
    ('The Ostrobothnians, Suite for Orchestra (Op.52) (1923)', 'The Ostrobothnians'),  # Leevi Madetoja
    ('No.3 La Puerta del Vino', 'No.3 La Puerta del Vino - from Preludes Book II'),  # Claude Debussy
    ('Candombe: Llamada de tambores', 'Candombe: Llamada de tambores (Ritmos y sonidos de Huruguay y Argentina)'),  # Daniel Binelli
    ('Three melodies with texts by J.P. Contamine de La Tour (Les Anges ; Elegie²; Sylvie³)', 'Three melodies with texts by J.P.Contamine de La Tour'),  # Erik Satie
    ('La Mort de Cléopâtre [The Death of Cleopatra] - lyric scene for soprano and orchestra', 'La Mort de Cleopatre'),  # Hector Berlioz
    ('Raduz and Mahulena (Op.16)', "Raduz and Mahulena, Op 16 'A fairy tale suite'"),  # Josef Suk
    ('(S)irato for Orchestra (UK Premiere)', '(S)irató for Orchestra'),  # Heinz Holliger
    ('Arrival of the Guests (Minuet)', 'Arrival of the Guests (Minuet) from Romeo and Juliet ballet suite'),  # Sergey Prokofiev
    ('Here is the Little Door', 'Here is the Little Door - from Three Carol-Anthems'),  # Herbert Howells
    ('Polymnia - Suite No.8 in D major', 'Polymnia - Suite No.8 in D major (from Musicalischer Parnassus, Augsburg [1738])'),  # Johann Caspar Ferdinand Fischer
    ('Quintet in B flat major (Op.32)', 'Clarinet Quintet (Introduction, theme and variations) in B flat major, Op 32'),  # Joseph Kuffner
    ("Sonata quarta à 3 - from 'Sonate' (Nuremburg 1682)", 'Sonata no.4 à 3 in C major - from "Sonate" (Nuremberg 1682)'),  # Johann Rosenmuller
    ('Der Sturm orchestra (H.24a.8)', 'Der Sturm (The Storm) - madrigal for chorus and orchestra (H.24a.8)'),  # Joseph Haydn
    ('Oboe Concerto in D major (1945, rev. 1948)', 'Oboe Concerto in D major'),  # Richard Strauss
    ('Tombeau pour Monsr. de Lully (from Suite - Book 2/5 in B minor for bass viol and continuo)', 'Tombeau pour Monsr. de Lully'),  # Marin Marais
    ('Returning Waves', 'Returning waves [Powracajace fale] - symphonic poem'),  # Mieczyslaw Karlowicz
    ('Hymn to St Cecilia for chorus (Op.27)', 'Hymn to St Cecilia'),  # Benjamin Britten
    ('O Rose von Stambul - from Die Rose von Stambul Act 1', 'O Rose von Stambul (Die Rose von Stambul, Act 1)'),  # Leo Fall
    ('Nun komm, der Heiden Heiland', 'Nun komm, der Heiden Heiland - Mass for 4 voices & basso continuo'),  # Johann Caspar Ferdinand Fischer
    ('Toccata and Fugue in D minor (BWV.565)', 'Toccata and Fugue in D minor (BWV.565) reconstsr. Manze for violin in A minor'),  # Johann Sebastian Bach
    ('Smutna jest dusza moja (Op.1 No.6)', 'Smutna jest dusza moja (My soul is sad) (Op.1 No.6)'),  # Mieczyslaw Karlowicz
    ("L'anime del Purgatorio (1680)", "L'anime del Purgatorio - cantata for 2 voices, chorus & ensemble"),  # Alessandro Stradella
    ('Prelude and Act III Liebestod - from the opera Tristan and Isolde', "Prelude and Liebestod - from the opera 'Tristan and Isolde'"),  # Richard Wagner
    ('3 Pieces from Slåtter (Op.72)', '3 Pieces from Slatter (Norwegian Peasant Dances), Op 72'),  # Edvard Grieg
    ('no.4 Als die alte Mutter [songs my mother taught me] (Op.55)', 'no.4 Als die alte Mutter [songs my mother taught me]'),  # Antonin Dvorak
    ('Sonata in F minor (Op.120 No.1) for clarinet or viola and piano', 'Sonata in F minor, Op 120 No 1'),  # Johannes Brahms
    ('Murder on the Orient Express', 'Murder on the Orient Express - music from the film'),  # Richard Rodney Bennett
    ('Concerto in A minor for two oboes & violin', 'Concerto in A minor for two oboes, solo violin, strings & basso continuo'),  # Conrad Friedrich Hurlebusch
    ('The Bells of Kallio Church (Op.56b)', 'Kallion kirkon kellosavelma (The Bells of Kallio Church) (Op.56b)'),  # Jean Sibelius
    ('Slavonic Dances (Op.46) - No. 8 In G Minor & No.3 In A flat Major', 'Two Slavonic Dances, Op 46 - no 8 in G minor and no 3 in A flat major'),  # Antonin Dvorak
    ('Lay a garland on her hearse', 'Lay a garland on her hearse - for 8 voices'),  # Robert Lucas Pearsall
    ('Tre madrigal di Torquato Tasso (Op.13)', 'Tre madrigal di Torquato Tasso'),  # Bernhard Lewkovitch
    ('The Golden Spinning Wheel - symphonic poem (Op.109)', 'The Golden spinning-wheel (Zlaty kolovrat) - symphonic poem, Op 109'),  # Antonin Dvorak
    ('Dahomeyse Rapsodie', 'Dahomeyse Rapsodie [Dahomeyan Rhapsody] (1893)'),  # August de Boeck
    ('In de Schuur (op. posth.)', 'In de Schuur [In the Barn] (op. posth.)'),  # August de Boeck
    ('Symphony in F minor, Op 4', 'Symphony in F minor, "Fairytale" Op 4 (1897)'),  # Ernst Mielck
    ("Songs (Vikingen (The Viking) ; Den lilla kolargossen (The Little Charcoal-burner); Reseda (Mignonette) ; Min politik (My Politics) ; På Nyå (On New Year's Day) ; Tal och tystnad (Speech and Silence) ; Natthimlen (The Night Sky) ; Skärslipargossen (The Little Knifegrinder) )", '7 Songs Vikingen (The Viking) [1811]; Den lilla kolargossen'),  # Erik Gustaf Geijer
    ('The Magic Harp (Op.27)', 'Trylleharpen (The Magic Harp), Op 27'),  # Friedrich Kuhlau
    ('Ich danke dir, Gott', 'Ich danke dir, Gott - cantata for 5 voices, strings and continuo'),  # Heinrich Bach
    ('Finale from the ballet music to "Prometheus"', 'Prometheus (Finale from the ballet music)'),  # Ludwig van Beethoven
    ('Polovtsian dances', "Polovtsian dances from 'Prince Igor'"),  # Alexander Borodin
    ('Gavotte Louis XIII', 'Gavotte Louis XIII (Amaryllis)'),  # Joseph Ghys
    ('Serenata in vano bass (FS.68)', 'Serenata in vano (FS.68)'),  # Carl Nielsen
    ('Pavane in D minor', "Pavane in D minor, 'Entretien des Dieux', from Bk.1 of 'Pieces de Clavecin'"),  # Jacques Champion de Chambonnieres
    ('Overture to William Tell', 'Overture (William Tell)'),  # Gioachino Rossini
    ('Pochod modracku (March of the Blue Boys)', 'Pochod modracku (March of the Blue Boys) for piccolo & piano'),  # Leos Janacek
    ('Ad te levavi oculos meos', 'Ad te levavi oculos meos - motet for 4 voices [1581]'),  # shared: Giovanni Pierluigi da Palestrina / Orlande de Lassus
    ('Fundamenta ejus', 'Fundamenta ejus - motet for 4 voices [1581]'),  # Giovanni Pierluigi da Palestrina
    ('Tragic Overture (Op.81)', 'Tragic Overture in D minor (Op.81) (1881)'),  # Johannes Brahms
    ('keringo from the incidental music to Pierrette fatyla by Arthur Schnitzler', 'Pierrette fatyla - keringo'),  # Ernõ Dohnányi
    ('La Sonnerie de Sainte-Genevieve du Mont de Paris for violin, bass viol and continuo', 'La Sonnerie de Sainte-Genevieve du Mont de Paris'),  # Marin Marais
    ("4 songs: [A Dream; Eight O'clock; Down by the Salley Gardens; Greeting]", '4 Songs'),  # shared: Rebecca Clarke / Mieczyslaw Karlowicz / Richard Strauss
    ("Ballade 32, 'Ploures, dames, ploures vostre servant' - from Le Veoir Dit", "Ballade 32, 'Ploures, dames'"),  # Guillaume de Machaut
    ("Sonata 1.x.1905 for piano in E flat minor, 'Z ulice' [From the street]", 'Sonata 1.x.1905 for piano in E flat minor'),  # Leos Janacek
    ('Meine Seele erhebt den Herrn', 'Meine Seele erhebt den Herrn (motet)'),  # Johann Ernst Bach
    ('Suncana Polja [Sunny Fields]', 'Sunny Fields'),  # Blagoje Bersa
    ('Hommage Ã Rameau', 'Hommage à Rameau - no 2 from Images (Set 1)'),  # Claude Debussy
    ('Le CimitiÃ¨re Marin for piano', 'Le Cimetière Marin for piano'),  # Gordon H. Dyson
    ('No.4 Als die alte Mutter (Op.55)', 'no.4 Als die alte Mutter [songs my mother taught me]'),  # Antonin Dvorak
    ('Tragic Overture, Op.81', 'Tragic Overture in D minor. Op 81'),  # Johannes Brahms
    ('Pohodka [Fairy tale] for cello and piano [1910]', 'Pohádka (Fairy Tale)'),  # Leos Janacek
    ('Musikalische Kurbishutte', 'Musikalische Kurbishutte - songcycle for 3 voices and continuo'),  # Heinrich Albert
    ('La Françoise (La pucelle) - sonata', 'La Françoise (La pucelle) sonata (from Les Nations ordre no 1 in E minor)'),  # François Couperin
    ('Midsummer night', 'Midsommarnatt [Midsummer night]'),  # Oskar Lindberg
    ("Symfonietta Rustica (1954-55) - from 'Pictures from Slovakia'", 'Symfonietta Rustica (Pictures from Slovakia)'),  # Eugen Suchon
    ('The Music Makers for contralto, choir and orchestra (Op.69) [1912]', 'The Music Makers, Op 69'),  # Edward Elgar
    ('Ludicrous Dance', "Ludicrous Dance for children's chorus"),  # Georgi Kostov
    ('Fantasia No.8 in E minor', 'Fantasia No 8 in E minor from 12 Fantasies for flute'),  # Georg Philipp Telemann
    ('Venite Exsultemus', 'Venite Exsultemus - concerto a 2'),  # Adam Jarzebski
    ('Aria Quarta in G', 'Aria Quarta in g [Aria; Variations 1 to 6; Aria da Capo]'),  # Johann Pachelbel
    ('Nos autem gloriari oportet', 'Nos autem gloriari oportet - motet for 4 voices [1563]'),  # Giovanni Pierluigi da Palestrina
    ('KÃµver Kuuseke', 'Kover Kuuseke [A little crooked fir-tree] (1931)'),  # Mart Saar
    ('Symphony of Psalms (1930 revised 1948)', 'Symphony of Psalms'),  # Igor Stravinsky
    ('Gratia sola Dei', 'Gratia sola Dei (motet)'),  # Orlande de Lassus
    ('Beati pauperes spiritu (motet)', 'Beati pauperes spiritu'),  # Jan Pieterszoon Sweelinck
    ('Licitarsko srce (Gingerbread Heart)', 'Licitarsko srce (Gingerbread Heart) - Suite from the Ballet'),  # Kresimir Baranovic
    ('5 Gedichte der Koenigen Maria Stuart [5 Poems of Queen Mary Stuart] (Op 135)', '5 Gedichte der Konigin Maria Stuart (5 Poems of Queen Mary Stuart), Op 135'),  # Robert Schumann
    ('Excerpts from Tassilone (comp. Dusseldorf 1709)', 'Tassilone - excerpts'),  # Agostino Steffani
    ("Prelude and divisions on 'John come kiss me now' (from The division viol, 1685)", "Prelude and divisions on 'John come kiss me now'"),  # Thomas Baltzar
    ('11 Variations on a theme by Haydn for 9 wind instruments and double bass (1982)', '11 Variations on a theme by Haydn'),  # Jean Françaix
    ('Meine seel erhebet den Herren (Deutsches Magnificat) - from Puericinium. Teutsche Kirchenlieder und andere geistliche Concert-Gesang (Frankfurt 1621)', 'Meine seel erhebet den Herren (Deutsches Magnificat)'),  # Michael Praetorius
    ('V Tatrach [In the Tatra mountains] (Op.26)', 'In the Tatra mountains, op 26'),  # Vitezslav Novak
    ('Rondeaux - Les Enchaînement harmonieux', 'Rondeaux - Les Enchainements harmonieux'),  # Louis-Claude Daquin
    ('The Bride Arrives', 'The Bride Arrives from South Ostrobothnian Suite no.2'),  # Toivo Kuula
    ('6 Metamorphoses after Ovid for oboe solo (Op.49)', '6 Metamorphoses after Ovid'),  # Benjamin Britten
    ('Variations in B flat minor (Op.3)', 'Variations in B flat minor'),  # Karol Szymanowski
    ('Variations for flute and piano in E minor (D.802) [Op.posth.160]', 'Variations for flute and piano in E minor, D.802'),  # Franz Schubert
    ('Serenade (To Frederick Delius on his 60th birthday) for string orchestra (1921-22)', 'Serenade (to Frederick Delius on his 60th birthday)'),  # Peter Warlock
    ("Concert fantasy on 'Carmen' for violin and orchestra (Op.25)", 'Concert fantasy on Carmen'),  # Pablo de Sarasate
    ('Scale, tear! (Halog, hasadj meg!) (nÃ©pi imÃ¡dsÃ¡gok) folk prayers collected by Zsuzsanna Erdelyi', 'Scale, tear! (Halog, hasadj meg!) - folk prayers'),  # Miklos Kocsar
    ('3 Rose Gardens Songs (1919) [3 Rosengaardsviser]', '3 Rose Gardens Songs (1919)'),  # Rued Langgaard
    ("Symphony in D major (Op.5 No.5) 'Pastorella'", "Symphony in D major 'Pastorella'"),  # François-Joseph Gossec
    ('Helsinki March (1930)', 'Helsinki March for orchestra'),  # Uuno Klami
    ('Quatre motets sur des thÃ¨mes GrÃ©goriens for a capella choir (Op.10)', 'Quatre motets sur des themes Gregoriens, Op 10'),  # Maurice Duruflé
    # --- Maurice Duruflé curation batch (2026-07-19): small, clean catalogue.
    # 'version originale' is the French label for the same '[original version]'
    # the bare-Requiem alias already targets (NOT a Fassung split). The bare
    # 'Notre Père' LHS is corpus-exclusive to Duruflé (tracks + segments
    # checked) and covers the segment-titled recording. Ubi caritas stays
    # split from the Quatre Motets set (excerpt policy; Gjeilo's setting is
    # composer-scoped anyway). ---
    ('Requiem, Op 9 - version originale', 'Requiem, Op 9 [original version]'),  # Maurice Duruflé
    ('Quatre motets sur des themes Gregoriens for a cappella choir (Op.10)', 'Quatre motets sur des themes Gregoriens, Op 10'),  # Maurice Duruflé (rec p00ty11q spans both; covers the accented spelling too)
    ('Notre Père Op.14 for chorus', 'Notre Père, Op 14'),  # Maurice Duruflé
    ('Notre Père', 'Notre Père, Op 14'),  # Maurice Duruflé (bare segment title; corpus-exclusive)
    # --- Handel curation batch (2026-07-19): top of the fragmentation-scan
    # worklist (117 rec-proven foldable airings). Mostly the catalogue-vs-
    # token-sort split class (an HWV-annotated spelling takes the §-key, its
    # bare/annotated twin doesn't) plus number-leak §-variants folded BY TITLE
    # STRING -- the systemic fix (exclude scoring/act/psalm numbers from the
    # §-number list) is a PARKED gate-design item, measure-first. Kept split:
    # the Quartet-billed Op.5/4 (no recording evidence), the lone Terpsichore
    # Prelude (excerpt), bare 'Sonata in A' (generic, blast-radius),
    # HWV 367a vs 367b (different versions). Va-tacito/Lascia oracle rows were
    # ALREADY consolidated (the oracle counts pre-alias keys). ---
    ("Suite in G for 'flauto piccolo' (Water Music)", "Water Music: Suite in G major for 'flauto piccolo' HWV 350"),  # George Frideric Handel
    ('Suite in G (Water Music, HWV 350)', "Water Music: Suite in G major for 'flauto piccolo' HWV 350"),  # George Frideric Handel (parent-ref parens demoted it)
    ('Violin Sonata in A minor (Op.1 No.4)', 'Violin Sonata in A minor (Op.1 No.4) (HWV.362)'),  # George Frideric Handel
    ('Music for the Royal Fireworks (HWV 351)', 'Music for the Royal Fireworks'),  # George Frideric Handel (bare dominates tracks+segments)
    ('Dixit Dominus - Psalm 109 HWV.232', 'Dixit Dominus, HWV 232'),  # George Frideric Handel (psalm-number leak)
    ('Trio Sonata in G, Op 5 No 4, with viola ad lib', 'Trio Sonata in G major, Op 5 no 4 (HWV 399) for 2 violins, violone and organ'),  # George Frideric Handel (synthetic final-key target)
    ('Gentle Morpheus, son of night - from Alceste', "Gentle Morpheus, son of night (Calliope's song) from Alceste"),  # George Frideric Handel (rec p00qs7py)
    ('Alceste - Gentle Morpheus, son of night', "Gentle Morpheus, son of night (Calliope's song) from Alceste"),  # George Frideric Handel (rec p00qs7py)
    ("'Cara sposa, amante cara' from Rinaldo (Act 1 Scene 7)", 'Aria: Cara sposa, amante cara from Rinaldo (Act 1 Scene 7)'),  # George Frideric Handel
    ("Cara sposa, amante cara, from 'Rinaldo, HWV 7'", 'Aria: Cara sposa, amante cara from Rinaldo (Act 1 Scene 7)'),  # George Frideric Handel
    ("Cantata Delirio amoroso ('Da quel giorno fatale', HWV.99)", 'Cantata Delirio amoroso: "Da quel giorno fatale" (HWV.99)'),  # George Frideric Handel
    ('Delirio amoroso - Italian cantata no.12 for soprano and ensemble (HWV.99)', 'Cantata Delirio amoroso: "Da quel giorno fatale" (HWV.99)'),  # George Frideric Handel (cantata-number leak)
    ("Cleopatra's aria: 'Piangerò la sorte mia' - from 'Giulio Cesare', Act 3 Sc 3", 'Cleopatra\'s aria: \'Piangero la sorte mia\' - from "Giulio Cesare" (Act 3 Sc.3)'),  # George Frideric Handel
    ('Terpsichore ballet music', "Ballet music from 'Terpsichore'"),  # George Frideric Handel (rec p00q35q4)
    ("Prelude-Chaconne; Sarabande; Gigue; Air; Ballo - from 'Terpsichore', ballet music", "Ballet music from 'Terpsichore'"),  # George Frideric Handel (member-list spelling)
    ("Prelude-Chaconne; Sarabande; Gigue; Air; Ballo - from 'Terpsichore'", "Ballet music from 'Terpsichore'"),  # George Frideric Handel (member-list spelling)
    ('Aure, deh, per pieta (excerpt Giulio Cesare)', 'Aure, deh, per pieta (Giulio Cesare)'),  # George Frideric Handel (rec p022q0zk)
    ("Dall' ondoso periglio (recit); Aure, deh, per pieta (aria) - scena from 'Giulio Cesare'", 'Aure, deh, per pieta (Giulio Cesare)'),  # George Frideric Handel (recit+aria scena, same recording)
    ('Ah! che troppo inequali, Italian cantata no.26 for soprano, 2 violins, viola and continuo HWV 230', 'Ah! che troppo ineguali, HWV 230'),  # George Frideric Handel (scoring+cantata-number leak)
    ('Overture and Prelude to Act 2 - from Acis and Galatea, K566', 'Acis and Galatea, K 566 (Overture and prelude to act II)'),  # George Frideric Handel (act-number leak)
    ("Pensieri notturni di Filli:Nel dolce del' oblio' Cantata for soprano, recorder and continuo (HWV.134)", 'Pensieri notturni di Filli: Italian cantata No 17, HWV 134'),  # George Frideric Handel (one spelling carries leaked performer credits)
    ('Overture to Die Fischerin - a singspiel to a text by Goethe', 'Overture to Die Fischerin'),  # Corona Schroter
    ('[3] Folksongs for chorus (Op.49)', 'Folksongs for chorus, Op 49'),  # Arnold Schoenberg
    ('Fantasia in G minor', 'Fantasia in G minor (g1) - fuga contraria, from Fitzwilliam Virginal Book'),  # Jan Pieterszoon Sweelinck
    ('Spem in Alium', 'Spem in Alium, for 40 voices'),  # Thomas Tallis
    ('Der Sturm [The Storm] - chorus for SATB choir and orchestra (H.24a.8)', 'Der Sturm (The Storm) - madrigal for chorus and orchestra (H.24a.8)'),  # Joseph Haydn
    ('Les Illuminations for voice and string orchestra (Op.18)', 'Les Illuminations, Op 18'),  # Benjamin Britten
    ('Kullervo - symphonic poem (Op.15) (1913)', 'Kullervo, Op 15 (1913)'),  # Leevi Madetoja
    ('Suite Concertino in F major for bassoon, string orchestra and two horns (Op.16)', 'Suite Concertino in F major for bassoon and small orchestra, Op 16'),  # Ermanno Wolf-Ferrari
    ('Concerto for trumpet and piano no. 1 in C minor', 'Trumpet Concerto no 1 in C minor'),  # Vladimir Peskin
    ('Mambo (West Side Story)', "Mambo from Symphonic dances from 'West Side story'"),  # Leonard Bernstein
    # Two more spellings of the same single Mambo number that escaped the alias
    # above (WSS-specific keys, cross-composer-safe). Completes the established
    # merge of the standalone Mambo with the Symphonic Dances Mambo movement.
    ("Mambo (excerpt West Side Story)", "Mambo from Symphonic dances from 'West Side story'"),  # Leonard Bernstein
    ("Mambo, from 'West Side Story'", "Mambo from Symphonic dances from 'West Side story'"),  # Leonard Bernstein

    # Ballet mop-up (2026-06-17, duration-verified per the Cerys ballet consult).
    # Ravel Daphnis et Chloe COMPLETE BALLET: the '[with chorus]' and unqualified
    # '- ballet' phrasings are the same ~52-62 min full work (segment-verified) as
    # '(complete ballet)'. Folded to that canonical. Distinct from Suite No.2
    # (~17 min, kept) and from 'ballet, Part I' (a portion, kept); bare 'Daphnis
    # et Chloe' left alone (ambiguous, unverifiable).
    ("Daphnis et Chloe - ballet [with chorus]", "Daphnis et Chloé (complete ballet)"),  # Maurice Ravel
    ("Daphnis et Chloé - ballet",               "Daphnis et Chloé (complete ballet)"),  # Maurice Ravel
    # Falla Three-Cornered Hat: 'Suite no 2' and 'Ballet Suite no 2' are the same
    # ~12.7 min Suite No.2 (segment-verified).
    ("The Three-Cornered Hat, Suite no 2", "The Three-Cornered Hat - Ballet Suite no 2"),  # Manuel de Falla
    # Bernstein: the orchestral Symphonic Dances from West Side Story (Bernstein's
    # ~23-min suite, orchestrated by Ramin & Kostal) is the only orchestral suite
    # from the show. "Symphonic Suite from West Side Story" (p01251d2, ~24.7 min)
    # is the same work under an alt name; the "orch. Ramin & Kostal" annotation is
    # redundant (those are the Symphonic Dances orchestrators). Both fold to the
    # dominant Symphonic Dances group. The two-piano Symphonic Dances (Bizjak) is
    # an alt-scoring but carries no distinguishing token, so it cannot be split
    # here. Individual numbers (Mambo, I Feel Pretty, One Hand One Heart, Jet
    # Song) and other arrangements (Brass Quintet suite, Highlights) stay split.
    ("Symphonic Suite from West Side Story",          "Symphonic Dances from West Side Story"),  # Leonard Bernstein
    ("Symphonic dances from 'West Side story' orch. Ramin & Kostal",
     "Symphonic Dances from West Side Story"),  # Leonard Bernstein
    ('Elegy for cello and piano (Op.24) [1883]', 'Elegy, Op 24 [1883]'),  # Gabriel Fauré
    ('Overture - from Il Barbiere di Siviglia', 'Overture from Il Barbiere di Siviglia (The Barber of Seville)'),  # Gioachino Rossini
    ('Overture Domov muj [My Home Land] (Op.62)', 'My Home Land, Overture Op 62'),  # Antonin Dvorak
    # Verdi's one Requiem, the Messa da Requiem, fragments 4 ways: Messa /
    # Missa (Latinism) / a "for soloists, chorus and orchestra" scoring tail /
    # bare "Requiem". Fold all onto the generic "Requiem" key (the only key the
    # bare airings can reach); display resolves to the majority "Messa da
    # Requiem". The key is composer-scoped, so other composers' requiems are
    # untouched. (The de->da spelling pair is retargeted here to stay chain-free.)
    ('Messa de Requiem', 'Requiem'),  # Giuseppe Verdi
    ('Messa da Requiem', 'Requiem'),  # Giuseppe Verdi
    ('Missa da Requiem', 'Requiem'),  # Giuseppe Verdi
    ('Messa da Requiem for soloists, chorus and orchestra', 'Requiem'),  # Giuseppe Verdi
    ('Overture from Mireille', 'Overture to Mireille'),  # Charles Gounod
    ('Adagio for viola and piano', 'Adagio for viola and piano in C'),  # Zoltan Kodaly
    ("Carolan's draught", "Carolan's draught for two harps"),  # Turlough O'Carolan
    ('Tardo per gli anni, e tremulo (Attila and Ezio) from the Prologue to Attila', 'Duet: Tardo per gli anni, e tremulo (Attila & Ezio) from the prologue to Attila'),  # Giuseppe Verdi
    ('Overture to Polyeucte', 'Overture (Polyeucte)'),  # Edgar Tinel
    ('Recitativo and scherzo-caprice for violin solo, (Op.6)b', 'Recitativo and scherzo-caprice'),  # Fritz Kreisler
    ('Printemps [symphonic suite]', 'Printemps (symphonic suite) [Tres modere; Modere]'),  # Claude Debussy
    ('Two Pieces for Strings (written for the film Henry V in 1944)', 'Two Pieces for Strings (from Henry V)'),  # William Walton
    ('Orjan poika [The Son of the Slave] - symphonic legend for soprano, baritone, mixed choir and orchestra (Op.14) (1910)', 'Orjan poika [The Son of the Slave] Op.14 (1910)'),  # Toivo Kuula
    ('O Living Will - motet for unaccompanied chorus', 'O living will'),  # Charles Villiers Stanford
    ('Pohadka Zimniho Vecera [A Tale of a Winters evening] (Op.9)', "A Winter's tale, Op 9"),  # Josef Suk
    ('Concerto for flute and strings in D minor (H.426)', 'Concerto for flute and strings in D minor (H.426) (1747?)'),  # Carl Philipp Emanuel Bach
    ('Ballo alla Polacca; Ballo Ongaro; Ballo ditto il Pichi', '3 Ballos - Ballo alla Polacca; Ballo Ongaro; Ballo ditto il Pichi'),  # Giovanni Picchi
    ("Selection from L'Arlésienne Suites Nos.1 & 2", "L'Arlesienne Suites Nos 1 & 2"),  # Georges Bizet
    ('Höstkväll [Autumn Evening] (Op.38 No.1)', 'Hostkvall [Autumn Evening] (Op.38 No.1) for voice and orchestra'),  # Jean Sibelius
    ('Variations on a theme of Niccolo Paganini (Op.26)', 'Variations on a theme of Nicolo Paganini, Op 26'),  # Boris Blacher
    ('5 Songs from 6 Original canzonettas - set 2 for voice & keyboard', '5 Songs from 6 Original canzonettas - set 2 for voice & keyboard (H.26a)'),  # Joseph Haydn
    ('Concerto for oboe & orchestra in C minor', 'Trumpet Concerto in C minor'),  # Domenico Cimarosa
    ('6 Orchestral songs (nos. 1-5 only) (EG.177) from Peer Gynt (Op.23)', '6 Orchestral songs (nos 1-5 only) (EG.177)'),  # Edvard Grieg
    ("Sonata Pian'e forte alla quarta bassa a 8 (B.2.64) [1597 No.6]", "Sonata Pian'e forte alla quarta bassa a 8 (B.2.64) [1597 no.6] for wind"),  # Giovanni Gabrieli
    ('Concertstucke for viola and piano (1906)', 'Concertstuck for viola and piano (1906)'),  # George Enescu
    ('Laetatus sum for 4 voices, 2 violins, 2 trumpets & organ', 'Laetatus Sum'),  # Grzegorz Gerwazy Gorczycki
    ('Pastoral Suite for flute, harp and strings (Op.13b)', 'Pastoral Suite, Op 13b'),  # Gunnar de Frumerie
    ('KlagosÃ¥ngen (The Lament)', 'The Lament'),  # Gunnar de Frumerie
    ('My Fatherland you are my love', 'Mu Isamaa On Minu Arm [My Fatherland you are my love]'),  # Gustav Ernesaks
    ('Christus am Olberge (The Mount of Olives) (Op.85)', 'Christus am Olberge (The Mount of Olives)'),  # Ludwig van Beethoven
    ('Solemn Procession to Gethsemani (Part II of Evangelical Diptych (1893-97 orchestrated in 1933)', 'Solemn Procession to Gethsemani (Part II of Evangelical Diptych)'),  # Lodewijk Mortelmans
    ('Overture from Iphigénie en Aulide', 'Iphigenie en Aulide, Overture'),  # Christoph Willibald Gluck
    ("Madrigal: 'Altri canti d'Amor' Ã 6 - from 'Madrigali guerrieri et amorosi con alcuni opuscoli in genere rappresentativo, che saranno per brevi episodi frÃ i canti senza gesto: libro ottavo' (Venice 1638)", 'Madrigal: "Altri canti d\'Amor" à 6'),  # Claudio Monteverdi
    ("Canamus, amici, canamus & Finnigan's wake", "Canamus, amici, canamus; Finnigan's wake"),  # Henk Badings
    ('Romanian Rhapsody No.1 in A major (Op.11)', 'Romanian Rhapsody No.1 in A major (Op.11 No.1)'),  # George Enescu
    ('Les Baricades misterieuses', 'Les Baricades misterieuses [from Pieces de clavecin –ordre no.6]'),  # François Couperin
    ('Romance in D flat (Op.24 No.9)', 'Romance in D flat - from [10] Pieces for piano, Op 24 no 9'),  # Jean Sibelius
    ('St Francois de Paule marchant sur les flots (S.175 No.2)', 'St Francois de Paule marchant sur les flots'),  # Franz Liszt
    ("Aino's Aria 'Tuli kevät, tuli toivo'- from the opera 'Aino', Op.50 (1909)", 'Aino\'s aria "Tuli kevat, tuli toivo" [Spring came with hope] - from Aino, Op 50'),  # Erkki Melartin
    ("Ode for the birthday of Queen Mary (1694) 'Come, ye sons of Art, away' (Z.323)", 'Ode for the birthday of Queen Mary'),  # Henry Purcell
    ('Tombeau pour Monsr. de Lully from Suite - Book 2 No.5 in B minor', 'Tombeau pour Monsr. de Lully'),  # Marin Marais
    ('O salutaris hostia - motet', 'O salutaris hostia'),  # shared: Henry du Mont / Pierre de la Rue
    ('Polish Rhapsody (Op.25)', 'Rapsodja polska (Polish Rhapsody), Op 25'),  # Grzegorz Fitelberg
    ("Diminution on Orlando Lassus's 'Susanne un jour'", "Diminution on Orlando Lassus's 'Susanne un jour' for organ"),  # Andrea Gabrieli
    ('Notturno No.3 in A flat major (S.541)', 'Liebestraume no 3 in A flat major (S.541)'),  # Franz Liszt
    ('Piao Sextet in A minor (Op.29)', 'Piano Sextet in A minor'),  # Ludvig Norman
    ('Symphony No.2 (dedicated to Peeter Liljele)', 'Symphony no 2 (dedicated to Peeter Lilje) (1984)'),  # Lepo Sumera
    ('Tardo per gli anni, e tremulo from the Prologue to Attila', 'Duet: Tardo per gli anni, e tremulo (Attila & Ezio) from the prologue to Attila'),  # Giuseppe Verdi
    ('Ay, amor, quÃ© dulce tirano', 'Ay amor que dulce tirano [Love, the sweet tyrant]'),  # Matias Juan de Veana
    ('Romantic Concerto for piano and orchestra', 'Koncert romantyczny [Romantic Concerto] for piano and orchestra (1950)'),  # Kazimierz Serocki
    ('Concerto for horn and orchestra in D minor', 'Horn Concerto in D minor, C 38'),  # Antonio Rosetti
    ('Grand Duo Concertant for clarinet & piano (Op.48) (in three movements)', 'Grand Duo Concertant for clarinet & piano, Op 48'),  # Carl Maria von Weber
    ('Concerto for horn in D major', 'Concerto for Horn, Timpani and Strings in D major'),  # Frantisek Xaver Pokorný
    ('Norwegian Rhapsody No 1 (appl)', 'Norwegian Rhapsody no 1 in A minor'),  # Johan Halvorsen
    ("Overture to Hermina im Venusberg (Hermania in Venus' cave) (Operetta of 1886)", 'Hermina im Venusberg (Overture)'),  # Jan Levoslav Bella
    ("4 Folk Songs: Come thee unto the hills; O Mistress Mine [words. Shakespeare]; Six Dukes went afishin' [BFMS.11]; Mary Thomson [c.1913]", '4 Folk Songs'),  # Percy Grainger
    ("Ich ging mit lust durch einen grünen Wald ('I walked with joy through a green forest')", 'Ich ging mit lust durch einen grunen Wald'),  # Gustav Mahler
    ('Aria variata alla maniera italiana for keyboard (BWV.989) in A minor', 'Aria variata alla maniera italiana in A minor, BWV 989'),  # Johann Sebastian Bach
    ('Trylleharpen (The Magic Harp) for orchestra (Op.27)', 'Trylleharpen (The Magic Harp), Op 27'),  # Friedrich Kuhlau
    ('Pirâme et Tisbé - cantata for voice and simphonie (1710)', 'Pirame et Tisbe (1710)'),  # Louis-Nicolas Clerambault
    ('Overture to Maskarade (FS.39) (appl)', 'Overture to Maskarade'),  # Carl Nielsen
    ('Spring Sketches', 'Kevadkillud (Spring sketches)'),  # Veljo Tormis
    ('Duo rahvatoonis for flute and violin', 'Duo rahvatoonis'),  # Ester Magi
    ('The White reindeer (Valkoinen puura) - suite for orchestra (1952)', 'The White Reindeer - suite'),  # Einar Englund
    ('Avondmuziek [1915] [Serenade No.1 in A; Serenade No.2 in E]', 'Avondmuziek'),  # Flor Alpaerts
    ("Golden Oriole (No.2 of Catalogue d'Oiseaux)", "Le Loriot [Golden Oriole] (No.2 of Catalogue d'Oiseaux)"),  # Olivier Messiaen
    ('Fantasia No.8 in E minor from [12] Fantasies for flute [or oboe] solo [Hamburg, 1732-3]', 'Fantasia No 8 in E minor from 12 Fantasies for flute'),  # Georg Philipp Telemann
    ('Wie murren denn die Leut (Dialogo a doi voci)', 'Wie murren denn die Leut (Dialogo a due voci)'),  # Johann Valentin Meder
    ("Sonatina super Carmen 'Kammerfantasie'", "Sonatina super Carmen (Sonatina no.6) for piano 'Kammerfantasie'"),  # Ferruccio Busoni
    ('1st movement (Allegro) from Trumpet Concerto (H.7e.1) in E flat major', "Trumpet concerto in E flat (1st mvt 'Allegro')"),  # Joseph Haydn
    ('O Living Will - motet', 'O living will'),  # Charles Villiers Stanford

    # Berlioz overtures — heavy fragmentation cleanup (2026-06-11). Folds the
    # cross-language wholes (King Lear/Le Roi Lear, Le Carnaval romain/Roman
    # Carnival), the et/and + Op-present/absent + from/to churn, and the
    # Franc-/Francs-juges and 'Learm' typos to one canonical per work.
    ("Overture - Beatrice and Benedict (Op.27)", "Béatrice et Bénédict (Overture)"),  # Hector Berlioz
    ("Overture from Beatrice et Benedict", "Béatrice et Bénédict (Overture)"),  # Hector Berlioz
    ("Beatrice et Benedict - opera in 2 acts Op 27 (Overture)", "Béatrice et Bénédict (Overture)"),  # Hector Berlioz
    ("Overture to Béatrice et Bénédict - opera in 2 acts Op 27", "Béatrice et Bénédict (Overture)"),  # Hector Berlioz
    ("Overture to Beatrice and Benedict, Op 27", "Béatrice et Bénédict (Overture)"),  # Hector Berlioz
    ("Overture to 'Béatrice et Bénedict', Op.27", "Béatrice et Bénédict (Overture)"),  # Hector Berlioz
    ("Overture from Béatrice et Bénédict (Op.27)", "Béatrice et Bénédict (Overture)"),  # Hector Berlioz
    ("Le Carnival Romain, op 9", "Le Carnaval romain - overture (Op.9)"),  # Hector Berlioz
    ("Roman Carnival Overture op 9", "Le Carnaval romain - overture (Op.9)"),  # Hector Berlioz
    ("Overture to Les francs-juges (Op. 3)", "Les Franc-juges Op 3 (Overture)"),  # Hector Berlioz
    ("Les Francs-juges, op.3, overture", "Les Franc-juges Op 3 (Overture)"),  # Hector Berlioz
    ("Le Roi Lear - overture (Op.4)", "King Lear Overture (Op.4)"),  # Hector Berlioz
    ("Le Roi Learm Op 4 (Overture)", "King Lear Overture (Op.4)"),  # Hector Berlioz
    ("Overture: Les Troyens a Carthage", "Overture to Les Troyens a Carthage"),  # Hector Berlioz
    ("Le Corsaire (overture)", "Overture, Le Corsaire, Op 21"),  # Hector Berlioz

    # Schubert 'Des Teufels Lustschloss' overture — bilingual 'German (English
    # translation)' title churns a new token-key per BBC phrasing (opera/to/the
    # placement + Castle vs Pleasure Palace gloss + a pure-English variant).
    # Folds the 3 current fragments to the German canonical; reaches the 4
    # pre-2012 text-only airings + the count-mismatch un-projected 2012+ ones.
    ('Overture to "Des Teufels Lustschloss" (The Devil\'s Castle) opera', "Des Teufels Lustschloss - Overture"),  # Franz Schubert
    ('Overture to "Des Teufels Lustschloss" (The Devil\'s Castle)', "Des Teufels Lustschloss - Overture"),  # Franz Schubert
    ("Overture to The Devil's Castle", "Des Teufels Lustschloss - Overture"),  # Franz Schubert

    # Gershwin: Catfish Row label-variant of the dominant suite. The 20x
    # "Symphonic Suite from Porgy and Bess" and this "Catfish Row -" prefixed
    # airing are the SAME recording (p06dffmz, Hamilton PO / Brott / Tritt) =
    # Gershwin's own Catfish Row suite; only the prefix tokens split them. NB
    # the other Porgy suites/selections (Bullock+WDR vocal, Signum sax-quartet,
    # Barcelona band arr. Barnes, Bennett's Symphonic Picture, the Alexander Qt
    # excerpt) are GENUINELY distinct arrangements/forces (durations 3-35 min,
    # different recordings) and are deliberately left split.
    ("Catfish Row - Symphonic Suite from Porgy and Bess",
     "Symphonic Suite from Porgy and Bess"),  # George Gershwin

    # Gershwin: Three Preludes (1926, solo piano) — the COMPLETE set fragments
    # across three keys: the bare "3 Preludes for piano" (Coleman, Evrov), the
    # Lundin recording's verbose movement-enumerating title, and bare "3
    # Preludes" (Ekberg). All solo piano, ~6-7 min complete sets = one work.
    # Folded to the dominant "3 Preludes for piano". NB deliberately NOT folding
    # the "Three" word-form key ('preludes three') — _strip_arrangement_tail
    # collapses solo "Three Preludes" and "...arr. for two pianos" onto it, so
    # aliasing it would drag the two-piano alt-scoring into the solo set. The
    # two-piano (15x) and trumpet+piano (2x) arrangements, and the single-
    # prelude excerpts (No 1/2/3), stay split (scoring / whole-vs-part).
    ("3 Preludes (1926): No 1 in B flat; No 2 in C sharp minor; No 3 in E flat",
     "3 Preludes for piano"),  # George Gershwin
    # Single Prelude No 1: "Allegro ben ritmato e deciso" is the tempo marking
    # of Prelude No 1 in B flat (No 3 is "Allegro ben ritmato" WITHOUT "e
    # deciso"), so this excerpt = the "Prelude No. 1" group. Stays split from
    # the whole set (whole-vs-part).
    ("Allegro ben ritmato e deciso, from 'Three Preludes'",
     "Prelude No. 1 from 3 Preludes for piano"),  # George Gershwin
    # ------------------------------------------------------------------
    # Chopin 24 Preludes Op.28 consolidation (2026-07-03). The set is TTN's
    # standard space-filler, aired whole, as numbered runs, and as single
    # preludes — each a distinct group per the whole-vs-excerpt policy. What
    # folds here is SAME-CONTENT variants keyed apart: pre-2012 verbose
    # key-signature enumerations ('Preludes No.16 in Bb minor; ...') the bridge
    # can't reach, and the same single/run split across different recordings'
    # segment titles. Targets are the dominant (recording-anchored) group's
    # key. recording_pid+duration oracle checked: all no.15 satellites are
    # 301-326s single-prelude recordings. Deliberately NOT folded: 'selected
    # Preludes from the Op.28 set' (content unenumerated on both lineages),
    # 'Ten Preludes' (927s, own selection), the 4-11+19+17 run, the 16-24
    # nine-prelude enumeration, the 6&11 / 7&8 / 4&8 pairs, and the
    # 'Funeral March; Fantasia K.475; Ballade' multi-work medley line.
    # -- single Prelude no.15 'Raindrop'
    ("No.15 in D flat 'Raindrop' - from 24 Preludes Op.28 for piano",
     "Prelude in D flat major, Op 28 no 15, 'Raindrop'"),  # Fryderyk Chopin
    ("24 Preludes Op.28 for piano - no 15 in D flat 'Raindrop'",
     "Prelude in D flat major, Op 28 no 15, 'Raindrop'"),  # Fryderyk Chopin
    ("24 Preludes for piano (Op.28) no.15",
     "Prelude in D flat major, Op 28 no 15, 'Raindrop'"),  # Fryderyk Chopin
    # -- Nos 16-20 run
    ("Preludes No.16 in Bb minor; No.17 in Ab major; No.18 in F minor; "
     "No.19 in Eb major; No.20 in C minor - from [24] Preludes (Op.28)",
     "Preludes, Op 28 Nos 16-20"),  # Fryderyk Chopin
    ("Preludes: No 16 in B flat minor; No 17 in A flat; No 18 in F minor; "
     "No 19 in E flat; No 20 in C minor (24 Preludes, Op 28)",
     "Preludes, Op 28 Nos 16-20"),  # Fryderyk Chopin
    ("Preludes Op 28: No 16 in B flat minor; No 17 in A flat major; "
     "No 18 in F minor; No 19 in E flat major; No 20 in C minor",
     "Preludes, Op 28 Nos 16-20"),  # Fryderyk Chopin
    ("A selection of Preludes, Op.28 (No.16 in Bb minor; No.17 in Ab major; "
     "No.18 in F minor; No.19 in Eb major; No.20 in C minor)",
     "Preludes, Op 28 Nos 16-20"),  # Fryderyk Chopin
    # -- Nos 11-15 run
    ("Preludes No.11 in B major; No.12 in G# minor; No.13 in F# major; "
     "No.14 in Eb minor; No.15 in Db major - from 24 Preludes (Op.28)",
     "From 24 Preludes, Op 28: nos 11-15"),  # Fryderyk Chopin
    ("Preludes No.11 in B major; No.12 in G sharp minor; No.13 in F sharp "
     "major; No.14 in E flat minor; No.15 in D flat major - from 24 Preludes "
     "(Op.28)",
     "From 24 Preludes, Op 28: nos 11-15"),  # Fryderyk Chopin
    ("Preludes (Op.28 Nos. 11-15)",
     "From 24 Preludes, Op 28: nos 11-15"),  # Fryderyk Chopin
    ("Five Preludes for piano, Op 28, Nos 11-15",
     "From 24 Preludes, Op 28: nos 11-15"),  # Fryderyk Chopin
    ("Preludes Nos. 11 - 15 from 24 Preludes (Op.28)",
     "From 24 Preludes, Op 28: nos 11-15"),  # Fryderyk Chopin
    # -- Nos 21-24 run
    ("Preludes No.21 in B flat major; No.22 in G minor; No.23 in F major; "
     "No.24 in D minor - from Preludes (Op.28)",
     "Preludes - Op 28 Nos 21-24"),  # Fryderyk Chopin
    ("Preludes No.21 in Bb major; No.22 in G minor; No.23 in F major; "
     "No.24 in D minor - from Preludes (Op.28)",
     "Preludes - Op 28 Nos 21-24"),  # Fryderyk Chopin
    # -- Nos 6-10 run
    ("Preludes No.6 in B minor; No.7 in A major; No.8 in F sharp minor; "
     "No.9 in E major; No.10 in C sharp minor - from Preludes (Op.28)",
     "[24] Preludes (Op.28 Nos. 6-10)"),  # Fryderyk Chopin
    ("Preludes No.6 in B minor; No.7 in A major; No.8 in F# minor; "
     "No.9 in E major; No.10 in C# minor (from Preludes, Op.28)",
     "[24] Preludes (Op.28 Nos. 6-10)"),  # Fryderyk Chopin
    ("Preludes (Op.28 Nos. 6-10)",
     "[24] Preludes (Op.28 Nos. 6-10)"),  # Fryderyk Chopin
    # -- Nos 1-5 run
    ("Preludes No.1 in C major; No.2 in A minor; No.3 in G major; "
     "No.4 in E minor; No.5 in D major - from Preludes (Op.28)",
     "[24] Preludes (Op.28 Nos. 1-5)"),  # Fryderyk Chopin
    ("Preludes (Op.28 Nos. 1-5)",
     "[24] Preludes (Op.28 Nos. 1-5)"),  # Fryderyk Chopin
    # -- single preludes 1 / 3 / 4 / 17 / 20
    ("Prelude for piano (Op. 28 no. 1) in C major",
     "Prelude No 1 in C, Op 28 No 1"),  # Fryderyk Chopin
    ("Prelude, Op 28 No 4",
     "Prelude No. 4 in E minor, Op 28/4"),  # Fryderyk Chopin
    ("Prelude No.17 in A flat - from 24 Preludes Op.28 for piano",
     "No.17 in A flat - from 24 Preludes Op.28 for piano"),  # Fryderyk Chopin
    ("Prelude no.17 in A flat major (24 Preludes for piano (Op.28)",
     "No.17 in A flat - from 24 Preludes Op.28 for piano"),  # Fryderyk Chopin
    # no.20 is Op 28's only C-minor prelude, so the bare C-minor key is
    # unambiguous within Chopin; the vaguer spelling is the dominant one.
    ("Prelude in C minor, Op. 28 No 20",
     "Prelude in C minor, Op 28"),  # Fryderyk Chopin
    ("24 Preludes Op.28 for piano; no.20 in C minor",
     "Prelude in C minor, Op 28"),  # Fryderyk Chopin
    # ------------------------------------------------------------------
    # Chopin opus-set sweep (2026-07-03) — the Op.28 method over the whole
    # Chopin catalogue: cluster every title by effective key, flag opus/number
    # signatures split across keys, fold SAME-CONTENT variants to the dominant
    # (usually recording-anchored) canonical. 193 pairs. Recurring shapes:
    # redundant 'for piano' scoring tails, 'Op N/M' slash + "Op N'M" apostrophe
    # opus forms (the separator-squash corrupts the latter to a bogus opus,
    # e.g. Op.10'3 -> 'op103'), word-vs-digit set counts (Four/4), Study=Etude
    # / Valse=Waltz / Fantasy=Fantaisie vocabulary, pre-2012 verbose
    # key-signature enumerations, junk tails (**EXPIRED**, a concatenated
    # performer credit, a '(1810-1849):' date prefix). Policy calls: Op 73
    # Rondo folds ALL versions incl. the composer's own 2-piano re-scoring
    # (own re-scoring = same work, flagged); Op 9/2 the D-major 'original in
    # E flat' transposed arrangement folds to the E-flat original (literal
    # transcription = same work); Op 54 Scherzo No 4 folds the pervasive
    # 'E minor' mislabel INTO the correct E major (display majority will still
    # show the mislabel - known wart); the Hamelin 'Minute' re-tooling stays
    # its own work (paraphrase) - only its Op.42 mislabel folds into it.
    # Deliberately left split: Op 68/4 Ekier vs Fontana editions (edition
    # question, unresolved); 'Rondo in C, Op 7' (suspect opus - Op 7 is
    # mazurkas - but no recording evidence to reassign); the two 'Study in
    # F minor Op.10 No.8' strays (number says 8=F major, key says 9 - conflict
    # unresolved); distinct numbered selections and multi-work medley lines.
    ("Study Op.10'3 in E major", 'Etude in E major, Op 10 no 3'),  # Fryderyk Chopin
    ('Study Op.10 No.3 in E major', 'Etude in E major, Op 10 no 3'),  # Fryderyk Chopin
    ("Study Op.10'1 in C major", 'Etude in C (Op.10 No. 1)'),  # Fryderyk Chopin
    ('Study in C major, Op.10 No.1', 'Etude in C (Op.10 No. 1)'),  # Fryderyk Chopin
    ('12 Studies Op.10 for piano; no.1 in C major', 'Etude in C (Op.10 No. 1)'),  # Fryderyk Chopin
    ("Study Op.10'2 in A minor", 'Etude in A minor, Op 10 No 2'),  # Fryderyk Chopin
    ('Etude C sharp minor (Op.10, No.4)', 'Etude in C sharp minor, Op 10 no 4'),  # Fryderyk Chopin
    ('Study in C sharp minor, Op.10 No.4', 'Etude in C sharp minor, Op 10 no 4'),  # Fryderyk Chopin
    ('Study in G flat major, Op.10 No.5', 'Etude in G flat (Op. 10 no. 5)'),  # Fryderyk Chopin
    ('12 Studies Op.10 for piano; no.5 in G flat major', 'Etude in G flat (Op. 10 no. 5)'),  # Fryderyk Chopin
    ('Etude in C minor, Op.10 no.12 (from 12 Etudes Op.10) for piano',
     'Étude Op.10 no.12 in C minor (Revolutionary)'),  # Fryderyk Chopin
    ('Etude in C minor, Op.10 no.12 (from 12 Etudes Op.10)', 'Étude Op.10 no.12 in C minor (Revolutionary)'),  # Fryderyk Chopin
    ('12 Etudes (Op. 25)', '12 Studies Op 25 for piano'),  # Fryderyk Chopin
    ('Study in A flat major, Op 25 No 1', "Etude in A flat major (Op.25 No.1) 'Aeolian Harp'"),  # Fryderyk Chopin
    ('Berceuse (Op.57)', 'Berceuse in D flat major, Op 57'),  # Fryderyk Chopin
    ('3 Nocturnes for piano, Op.9: No.1 in B flat minor; No.2 in E flat major; No.3 in B major',
     '3 Nocturnes for piano, Op.9'),  # Fryderyk Chopin
    ('3 Nocturnes, Op.9: No.1 in B flat minor; No.2 in E flat major; No.3 in B major',
     '3 Nocturnes for piano, Op.9'),  # Fryderyk Chopin
    ('Nocturne in D major (original in E flat), Op 9 no 2', 'Nocturne in E flat major, Op 9 no 2'),  # Fryderyk Chopin
    ('Nocturne in D, Op 9 No 2', 'Nocturne in E flat major, Op 9 no 2'),  # Fryderyk Chopin
    ('3 Nocturnes for piano, Op.15: No.1 in F major; No.2 in F sharp major; No.3 in G minor',
     '3 Nocturnes for piano, Op.15'),  # Fryderyk Chopin
    ('3 Nocturnes (Op.15): No.1 in F major; No.2 in F sharp minor; No.3 in G minor',
     '3 Nocturnes for piano, Op.15'),  # Fryderyk Chopin
    ('3 Nocturnes, Op.15: No.1 in F major; No.2 in F sharp major; No.3 in G minor',
     '3 Nocturnes for piano, Op.15'),  # Fryderyk Chopin
    ('Nocturrnes in F sharp major and G minor, Op.15 Nos 5 and 6',
     'Nocturnes in F sharp major and G minor, Op 15 Nos 5 and 6.'),  # Fryderyk Chopin
    ('2 Nocturnes for piano, Op.27: No.1 in C sharp minor; No.2 in D flat major',
     '2 Nocturnes for piano, Op.27'),  # Fryderyk Chopin
    ('2 Nocturnes, Op.27: No.1 in C sharp minor; No.2 in D flat major', '2 Nocturnes for piano, Op.27'),  # Fryderyk Chopin
    ('2 Nocturnes Op.27 for piano - no 2', 'Nocturne in D flat major, Op 27 no 2'),  # Fryderyk Chopin
    ('Nocturne No 2, Op 27', 'Nocturne in D flat major, Op 27 no 2'),  # Fryderyk Chopin
    ('Nocturne in D Flat major, from 2 Nocturnes Op 27', 'Nocturne in D flat major, Op 27 no 2'),  # Fryderyk Chopin
    ('Nocturne in D flat major, from 2 Nocturnes Op 27 for piano', 'Nocturne in D flat major, Op 27 no 2'),  # Fryderyk Chopin
    ('Nocturne in C sharp minor Op.27`1, arr. Milstein for violin and piano',
     'Nocturne No 7 in C sharp minor, Op 27 No 1'),  # Fryderyk Chopin
    ('2 Nocturnes Op.37 for piano - no 1 in G minor', 'Nocturne in G minor, Op.37 No.1'),  # Fryderyk Chopin
    ('From 2 Nocturnes Op.37 for piano - No 1 in G minor', 'Nocturne in G minor, Op.37 No.1'),  # Fryderyk Chopin
    ('Nocturnes Op 48 in C minor and F sharp major', 'Nocturnes in C minor and F sharp minor, Op 48'),  # Fryderyk Chopin
    ('2 Nocturnes for piano (Op.48) no.1 in C minor', 'Nocturne in C minor, Op 48, No 1'),  # Fryderyk Chopin
    ('2 Nocturnes Op.48; no. 1 in C minor', 'Nocturne in C minor, Op 48, No 1'),  # Fryderyk Chopin
    ('Nocture Op.48, No.1 in C minor', 'Nocturne in C minor, Op 48, No 1'),  # Fryderyk Chopin
    ('Nocturne in F sharp, Op 48 no 2', 'Nocturne in F sharp minor for piano (Op 48 no 2)'),  # Fryderyk Chopin
    ('2 Nocturnes for piano (Op.48)no.2 in F sharp minor', 'Nocturne in F sharp minor for piano (Op 48 no 2)'),  # Fryderyk Chopin
    ('2 Nocturnes for piano (Op.48) no.2 in F sharp minor', 'Nocturne in F sharp minor for piano (Op 48 no 2)'),  # Fryderyk Chopin
    ('From 2 Nocturnes for piano (Op.48): no.2 in F sharp minor',
     'Nocturne in F sharp minor for piano (Op 48 no 2)'),  # Fryderyk Chopin
    ('Nocturne in Eb (Op.55, No.2) arr. Kocsis for flute, cor anglais and harp',
     'Nocturne in E flat, Op 55 no 2'),  # Fryderyk Chopin
    ('From 2 Nocturnes for piano Op 62: No 2 in E major', 'Nocturne for piano in E major, Op 62 no 2'),  # Fryderyk Chopin
    ('2 Nocturnes for piano (Op.62) - no.2 in E major', 'Nocturne for piano in E major, Op 62 no 2'),  # Fryderyk Chopin
    ('Nocturne for piano in E major, Op.62 No.2 **EXPIRED**', 'Nocturne for piano in E major, Op 62 no 2'),  # Fryderyk Chopin
    ('Grande Valse brillante in E flat, op. 18',
     'Waltz for piano (Op.18) in E flat major "Grande valse brillante"'),  # Fryderyk Chopin
    ('Waltz for piano (Op.18) in E flat major',
     'Waltz for piano (Op.18) in E flat major "Grande valse brillante"'),  # Fryderyk Chopin
    ('Three Waltzes for piano, Op 34', 'Waltzes, Op 34'),  # Fryderyk Chopin
    ('Waltzes Op.34 for piano - No.1 in A flat major', 'Waltz in A flat major Op 34 no 1'),  # Fryderyk Chopin
    ('Waltz for piano, Op.34 No.1', 'Waltz in A flat major Op 34 no 1'),  # Fryderyk Chopin
    ('Waltz in A, Op 34 No 1', 'Waltz in A flat major Op 34 no 1'),  # Fryderyk Chopin
    ('Waltz fin A flat major, Op 42', 'Waltz in A flat major, Op 42'),  # Fryderyk Chopin
    ('Waltz No 42 in A flat, Op 42', 'Waltz in A flat major, Op 42'),  # Fryderyk Chopin
    ('Valse in D flat, Op 64 No 1 (Minute Waltz)', "Waltz for piano (Op.64 No.1) in D flat major 'Minute'"),  # Fryderyk Chopin
    ("Waltzes Op.64 for piano - No.1 in D flat major 'Minute'",
     "Waltz for piano (Op.64 No.1) in D flat major 'Minute'"),  # Fryderyk Chopin
    ('(1810-1849): Waltz, Op 64 No 1 (Minute Waltz)', "Waltz for piano (Op.64 No.1) in D flat major 'Minute'"),  # Fryderyk Chopin
    ("Waltz (Op.64 No.1) 'Minute'", "Waltz for piano (Op.64 No.1) in D flat major 'Minute'"),  # Fryderyk Chopin
    ('Waltz in D flat major Op.42 no.1 for piano (Minute) re-tooled by Marc-André Hamelin',
     'Waltz in D flat major Op.64 no.1 for piano (Minute) re-tooled Marc-André Hamelin'),  # Fryderyk Chopin
    ('Waltz in D flat major Op.42 no.1 for piano (Minute) re-tooled Marc-André Hamelin',
     'Waltz in D flat major Op.64 no.1 for piano (Minute) re-tooled Marc-André Hamelin'),  # Fryderyk Chopin
    ('Valse in C sharp minor (Op.64 No.2)', 'Waltz in C sharp minor, Op 64 no 2'),  # Fryderyk Chopin
    ('Waltz no.2 in C sharp minor from 3 Waltzes for piano (Op.64)', 'Waltz in C sharp minor, Op 64 no 2'),  # Fryderyk Chopin
    ('Waltz No 7 in C sharp minor, Op 64 No 2', 'Waltz in C sharp minor, Op 64 no 2'),  # Fryderyk Chopin
    ('Waltz no 7 C sharp minor Op 64 no 2', 'Waltz in C sharp minor, Op 64 no 2'),  # Fryderyk Chopin
    ('Waltz No. 7 in C sharp minor, op. 64/2', 'Waltz in C sharp minor, Op 64 no 2'),  # Fryderyk Chopin
    ('Mazurkas, Op 67', '4 Mazurkas for piano (Op.67)'),  # Fryderyk Chopin
    ('4 Mazurkas Op.67 for piano - no. 4 in A minor', 'Mazurka in A minor, Op.67 No.4'),  # Fryderyk Chopin
    ('From 4 Mazurkas Op.67 for piano - No.4 in A minor', 'Mazurka in A minor, Op.67 No.4'),  # Fryderyk Chopin
    ('4 Mazurkas for piano (Op.24) - no.2 in C major', 'Mazurka op. 24 no.2 in C major for piano'),  # Fryderyk Chopin
    ('Mazurka in in B flat, op. 17/1', 'Mazurka in B flat, Op 17 No 1'),  # Fryderyk Chopin
    ('3 Mazurkas Op.59 for piano - no. 1 in A minor', 'Mazurka in A minor (Op.59 No.1)'),  # Fryderyk Chopin
    ('Mazurka No 31 in A, Op 50', 'Mazurka No 31 in A flat, Op 50'),  # Fryderyk Chopin
    ('Four Mazurkas [1. Op.17 No.4 in A minor; 2. Op.33 No.1 in G sharp minor; 3. Op.67 No.3 in C major; 4. Op.59 No.2 in A flat major]',
     'Four Mazurkas - Op.17 No.4 in A minor; Op.33 No.1 in G sharp minor; Op.67 No.3 in C major; Op.59 No.2 in A flat major'),  # Fryderyk Chopin
    ('Mazurkas: Op 17 No 4 in A minor; Op 33 No 1 in G sharp minor; Op 67 No 3 in C; Op 59 No 2 in A flat',
     'Four Mazurkas - Op.17 No.4 in A minor; Op.33 No.1 in G sharp minor; Op.67 No.3 in C major; Op.59 No.2 in A flat major'),  # Fryderyk Chopin
    ('6 Mazurkas: in G major, Op.50 No.1; in C minor, Op.56 No.3; in A flat major, Op.17 No.3; in A minor, Op.17 No.4; in C Major, Op.67 No.3; in C major, Op.56 No.2',
     '6 Mazurkas (1. G major, Op.50/1; 2. C minor, Op.56/3; 3. A flat major, Op.17/3; 4. A minor, Op.17/4; 5. C Major, Op.67/3; 6. C major, Op.56/2)'),  # Fryderyk Chopin
    ('Polonaise No.2 in C minor (Op.40 No.2)', 'Polonaise in C minor, Op 40 no 2'),  # Fryderyk Chopin
    ('Polonaise No 2 in E flat minor, Op 26 No 2', 'Polonaise No 2 in E flat minor, Op 26'),  # Fryderyk Chopin
    ('Three Polonaises: Polonaise in A major (Op.40 No.1), Polonaise in E flat minor (Op.26 No.2) & Polonaise in F sharp minor (Op.44)',
     'Three Polonaises - Polonaise in A flat (Op.40 No.1), Polonaise in E flat minor (Op.26 No.2) & Polonaise in F sharp minor (Op.44)'),  # Fryderyk Chopin
    ("Three Polonaises: Polonaise in A major, Op 40'1; Polonaise in E flat minor, Op 26'2; Polonaise in F sharp minor, Op 44",
     'Three Polonaises - Polonaise in A flat (Op.40 No.1), Polonaise in E flat minor (Op.26 No.2) & Polonaise in F sharp minor (Op.44)'),  # Fryderyk Chopin
    ("Polonaise for piano in A flat major, Op 53 'Polonaise heroique'", 'Polonaise in A flat major, Op 53'),  # Fryderyk Chopin
    ('Polonaise in A flat major (Op. 53) "Polonaise héroïque"', 'Polonaise in A flat major, Op 53'),  # Fryderyk Chopin
    ('Polonaise in A flat major Op.53 (Eroica) for piano', 'Polonaise in A flat major, Op 53'),  # Fryderyk Chopin
    ('Polonaise in A flat Op.53 (Eroica)', 'Polonaise in A flat major, Op 53'),  # Fryderyk Chopin
    ('Polonaise in A flat, Op 53 (Heroique)', 'Polonaise in A flat major, Op 53'),  # Fryderyk Chopin
    ('Polonaise-Fantaisie in A flat, Op 61', 'Polonaise-fantasy in A flat major, Op 61'),  # Fryderyk Chopin
    ('Andante spianato and grande polonaise brillante in E flat major, Op 22',
     'Andante Spianato and Grande Polonaise brillante, Op 22'),  # Fryderyk Chopin
    ("Grande Polonaise Brillanté precedee d'un Andante Spianato (Op.22)",
     'Andante Spianato and Grande Polonaise brillante, Op 22'),  # Fryderyk Chopin
    ('Andante spianato and grande polonaise brillante (Op.22) for piano & orchestra',
     'Andante Spianato and Grande Polonaise brillante, Op 22'),  # Fryderyk Chopin
    ('Andante spianato and grande polonaise brillante (Op.22) for piano &amp;amp;amp;amp; orchestra',
     'Andante Spianato and Grande Polonaise brillante, Op 22'),  # Fryderyk Chopin
    ('Andante spianato and grande polonaise brillante (Op.22) in E flat major version for piano solo',
     'Andante Spianato and Grande Polonaise brillante, Op 22'),  # Fryderyk Chopin
    ('Andante spianato and grande polonaise brillante (Op.22) version for piano & orchestra',
     'Andante Spianato and Grande Polonaise brillante, Op 22'),  # Fryderyk Chopin
    ('Andante spianato; Grande polonaise brillante, Op 22',
     'Andante Spianato and Grande Polonaise brillante, Op 22'),  # Fryderyk Chopin
    ('Andante spianato and grande polonaise brillante in E flat major Op.22 vers. for piano',
     'Andante Spianato and Grande Polonaise brillante, Op 22'),  # Fryderyk Chopin
    ('Introduction and polonaise brillante (Op.3) arr.for piano trio',
     'Introduction and polonaise for cello and piano (Op.3) in C major'),  # Fryderyk Chopin
    ('Introduction et Polonaise brilliante in C, op. 3',
     'Introduction and polonaise for cello and piano (Op.3) in C major'),  # Fryderyk Chopin
    ('Introductio et Polonaise brilliante in C, op. 3',
     'Introduction and polonaise for cello and piano (Op.3) in C major'),  # Fryderyk Chopin
    ('Scherzo No 1 in B, Op 20', 'Scherzo no 1 in B minor, Op 20'),  # Fryderyk Chopin
    ('Scherzo No.2 in Bb minor (Op.31)', 'Scherzo no 2 in B flat minor, Op 31'),  # Fryderyk Chopin
    ('Scherzo No.3 in C sharp (Op.39)', 'Scherzo no 3 in C sharp minor, Op 39'),  # Fryderyk Chopin
    ('Scherzo no 4 in E minor, Op 54', 'Scherzo no 4 in E major, Op 54'),  # Fryderyk Chopin
    ("Sonata No. 2 (Op. 35) in B flat minor 'Marche funebre'", 'Piano Sonata no 2 in B flat minor, Op 35'),  # Fryderyk Chopin
    ('Sonata in G minor Op.65', 'Cello Sonata in G minor, Op 65'),  # Fryderyk Chopin
    ('Sonata in G minor Op.65 for cello and piano - Largo', "Largo (from 'Cello Sonata in G minor, Op 65')"),  # Fryderyk Chopin
    ('Cello Sonata in G minor, Op 65 (3rd mvt, Largo)', "Largo (from 'Cello Sonata in G minor, Op 65')"),  # Fryderyk Chopin
    ('Impromptu in F# major (Op.36)', 'Impromptu in F sharp major, Op 36'),  # Fryderyk Chopin
    ('Fantasie Impromptu in C sharp minor (Op.66)', 'Fantaisie-impromptu for piano in C sharp minor, Op 66'),  # Fryderyk Chopin
    ('Fantasie in F minor (Op.49)', 'Fantasy for piano (Op.49) in F minor'),  # Fryderyk Chopin
    ('Rondo in C minor, Op.1 (Allegro)', 'Rondo for piano in C minor, Op 1'),  # Fryderyk Chopin
    ('Rondo à la Mazur for piano in F major (Op.5) [Vivace]', 'Rondo à la Mazur in F major, Op 5'),  # Fryderyk Chopin
    ('Rondo à la Mazur, Op 5', 'Rondo à la Mazur in F major, Op 5'),  # Fryderyk Chopin
    ('Introduction in C minor and Rondo in E flat major, (Op.16)', 'Rondo in E flat major, Op.16'),  # Fryderyk Chopin
    ('Introduction and rondo in E flat major Op.16 for piano', 'Rondo in E flat major, Op.16'),  # Fryderyk Chopin
    ('Rondo in C major, Op 73', 'Rondo in C for Two Pianos, Op 73'),  # Fryderyk Chopin
    ('Rondo in C major B.27 (Op 73) arr. for 2 pianos', 'Rondo in C for Two Pianos, Op 73'),  # Fryderyk Chopin
    # The multi-piano arr-tail guard (Cerys 2026-07-03) keys arr-marked
    # spellings separately by default; Op 73 is the ratified exception (the
    # 2-piano version is Chopin's own re-scoring, all versions one group),
    # so pin the arr-marked key back into the union.
    ('Rondo in C major, Op.73, arr for 2 pianos',
     'Rondo in C for Two Pianos, Op 73'),  # Fryderyk Chopin
    ('Rondo in C major, Op.73 (Allegro maestoso)', 'Rondo in C for Two Pianos, Op 73'),  # Fryderyk Chopin
    ("Variations on 'Là ci darem la mano', Op 2", "Variations on 'La ci darem la mano' (Op.2) in B flat major"),  # Fryderyk Chopin
    ("Variations on 'La ci darem la mano' (Op.2) in B flatNelson Goerner (piano) Orchestra of the Eighteenth Century, Frans Brüggen (conductor)",
     "Variations on 'La ci darem la mano' (Op.2) in B flat major"),  # Fryderyk Chopin
    ("Introduction & variations on a theme from 'Herold's Ludovic' in B flat, Op 12",
     "Introduction & variations on a theme from Herold's Ludovic (Op.12) in B flat major ('Varations brillantes')"),  # Fryderyk Chopin
    ("Introduction & variations on a theme from Herold's Ludovic (Op.12) in B flat maj",
     "Introduction & variations on a theme from Herold's Ludovic (Op.12) in B flat major ('Varations brillantes')"),  # Fryderyk Chopin
    ("Introduction and variations on a theme from Herold's Ludovic for piano (Op.12)",
     "Introduction & variations on a theme from Herold's Ludovic (Op.12) in B flat major ('Varations brillantes')"),  # Fryderyk Chopin
    ("Introduction and variations in B flat on a theme from Herold's Ludovic, Op 12 (aka Variations brillantes)",
     "Introduction & variations on a theme from Herold's Ludovic (Op.12) in B flat major ('Varations brillantes')"),  # Fryderyk Chopin
    ("Introduction and variations on a theme from Herold's Ludovic in B flat for piano, Op 12",
     "Introduction & variations on a theme from Herold's Ludovic (Op.12) in B flat major ('Varations brillantes')"),  # Fryderyk Chopin
    ('Six Songs (Polish Songs, Op 74)', 'Six Songs from Polish Songs, Op 74'),  # Fryderyk Chopin
    ("Zyczenie (A Young Gir's Wish) op. 74/1", 'Zyczenie (The wish), Op.74 No.1'),  # Fryderyk Chopin
    ('The wish, Op.74 No.1 (Chopin)', 'Zyczenie (The wish), Op.74 No.1'),  # Fryderyk Chopin
    ("A Young Gir's Wish op. 74/1", 'Zyczenie (The wish), Op.74 No.1'),  # Fryderyk Chopin
    ('Wiosna (Spring) (Op.74, No.2) [aka Andantino in G minor]', 'Wiosna (Spring) (Op.74, No.2)'),  # Fryderyk Chopin
    ('Spring op. 74/2', 'Wiosna (Spring) (Op.74, No.2)'),  # Fryderyk Chopin
    ('Sad River op. 74/3', 'Smutna rzeka (Sad River) op. 74/3'),  # Fryderyk Chopin
    ("A Girl's Desire Op. 74/5", "Gdzie lubi (A Girl's Desire) Op. 74/5"),  # Fryderyk Chopin
    ('Out of my Sight op. 74/6', 'Precz z moich oczu (Out of my Sight) op. 74/6'),  # Fryderyk Chopin
    ('Posel [The envoy], Op.74 No.7', 'Posel (The Messenger) op. 74/7'),  # Fryderyk Chopin
    ('Posel, Op.74 No.7', 'Posel (The Messenger) op. 74/7'),  # Fryderyk Chopin
    ('The Messenger op. 74/7', 'Posel (The Messenger) op. 74/7'),  # Fryderyk Chopin
    ('Sliczny chlopiec (Handsome Lad), (Op. 74/8)', 'Śliczny chłopiec (The Handsome Lad) op. 74/8'),  # Fryderyk Chopin
    ('Sliczny chlopiec Op.74 No.8', 'Śliczny chłopiec (The Handsome Lad) op. 74/8'),  # Fryderyk Chopin
    ('Sliczny chlopiec Op.74 No.8 (Chopin)', 'Śliczny chłopiec (The Handsome Lad) op. 74/8'),  # Fryderyk Chopin
    ('Sliczny chlopiec (Handsome Lad), (Op 74 no.8)', 'Śliczny chłopiec (The Handsome Lad) op. 74/8'),  # Fryderyk Chopin
    ('The Handsome Lad op. 74/8', 'Śliczny chłopiec (The Handsome Lad) op. 74/8'),  # Fryderyk Chopin
    ('The Double End op. 74/11', 'Dwojaki koniec (The Double End) op. 74/11'),  # Fryderyk Chopin
    ('My Sweetheart op. 74/12', 'Moja pieszczotka (My Sweetheart) op. 74/12'),  # Fryderyk Chopin
    ('Nie ma czego trzeba (Faded and Vanished)op.74/13',
     'Nie ma czego trzeba [I want what I have not], Op.74 No.13'),  # Fryderyk Chopin
    ('Nie ma czego trzeba (Faded and Vanished) op.74/13',
     'Nie ma czego trzeba [I want what I have not], Op.74 No.13'),  # Fryderyk Chopin
    ('Nie ma czego trzeba , Op.74 No.13', 'Nie ma czego trzeba [I want what I have not], Op.74 No.13'),  # Fryderyk Chopin
    ('Faded and Vanished op.74/13', 'Nie ma czego trzeba [I want what I have not], Op.74 No.13'),  # Fryderyk Chopin
    ('The Ring op. 74/14', 'Pierscien (The Ring)op. 74/14'),  # Fryderyk Chopin
    # ------------------------------------------------------------------
    # Brahms opus-set sweep (2026-07-04) — first of the post-gate backlog
    # composers (60 fragmented signatures / 194 keys measured after the three
    # canonicalization gates). 119 pairs. Residue character: German/English
    # vocabulary twins (Fünf Gesänge = 5 Songs for chorus; Vier Klavierstücke
    # = 4 Klavierstücke; Ein Deutsches Requiem = A German Requiem;
    # Schicksalslied's five phrasings), enumerated set listings, junk tails
    # (MONO - 1964, 'Schiller, Friedrich:' prefix, 'orchestar'/'Conceto'/
    # 'Muhseligenm'/'Klvierstucke' typos), and the CLARINET-OR-VIOLA family:
    # Opp. 114/115/120 (and Op 40's horn/viola) are composer-published
    # alternative scorings of one work — own re-scoring = same, flagged —
    # so the instrument-named spellings fold to one group per opus number.
    # Op 25's Schoenberg orchestration folds per the standing arr-strip
    # transcription behavior. Op 8: the 1854 first version is a genuinely
    # different text — its spellings unify but it stays SPLIT from the
    # standard (1889) text; 'revised 1889' folds INTO the standard since
    # that IS the standard. Op 18b (Brahms's own piano setting of the
    # sextet variations) folds into the variations-movement group. Left
    # split: Op 56b (the composer's two-piano Haydn Variations — multi-piano
    # genre presumption), Book 1 of the Paganini Variations (a distinct
    # half-set, its own spellings unified), 'From Fantasien:' and
    # 'Excerpts from Six Pieces' (unspecified excerpts), '4 songs from
    # 6 Quartets Op.112' (a selection), movement excerpts (the Op 102
    # Vivace, Op 108 Allegro, Op 67/3 Andante pairs unified within
    # themselves).
    ("4 Ballades for piano (Op.10) (1. D minor 'Edward'; 2. D major; 3. B minor; 4. B major)",
     '4 Ballades for piano, Op 10'),  # Johannes Brahms
    ('Fantasien (Op.116)', '7 Fantasies Op.116 for piano'),  # Johannes Brahms
    ('Fantasies, Op 116', '7 Fantasies Op.116 for piano'),  # Johannes Brahms
    ('Intermezzo in E major (No.4 from 7 Fantasies Op.116 for piano)', 'Intermezzo in E major, Op.116 no.4'),  # Johannes Brahms
    ('Intermezzo in E flat, op. 117/1', 'Intermezzo in E flat major, Op 117 no 1 "Schlummerlied"'),  # Johannes Brahms
    ("Intermezzo E flat major (op. 117 no. 1) 'Schlummerlied'",
     'Intermezzo in E flat major, Op 117 no 1 "Schlummerlied"'),  # Johannes Brahms
    ("3 Intermezzi for piano (Op. 117) no. 1 in E flat major 'Schlummerlied'",
     'Intermezzo in E flat major, Op 117 no 1 "Schlummerlied"'),  # Johannes Brahms
    ('Intermezzi No. 1 in E flat, op. 117', 'Intermezzo in E flat major, Op 117 no 1 "Schlummerlied"'),  # Johannes Brahms
    ('Intermezzo in A minor, No.1 from 6 Pieces for piano (Op.118)', 'Intermezzo in A minor, Op 118 No 1'),  # Johannes Brahms
    ('Intermezzo No. 2 in A major, op. 118 no. 2', 'Intermezzo in A major, Op 118 no 2'),  # Johannes Brahms
    ('6 Pieces for piano - Intermezzo (Op.118 no.2)', 'Intermezzo in A major, Op 118 no 2'),  # Johannes Brahms
    ('Intermezzo in A - No.2 from 6 Pieces for piano (Op.118)(encore)', 'Intermezzo in A major, Op 118 no 2'),  # Johannes Brahms
    ('Four Piano Pieces, Op 119', '4 Klavierstücke, Op 119'),  # Johannes Brahms
    ('Vier Klavierstucke, Op 119', '4 Klavierstücke, Op 119'),  # Johannes Brahms
    ('Vier Klvierstucke, Op 119', '4 Klavierstücke, Op 119'),  # Johannes Brahms
    ('Intermezzo in B minor from 4 Pieces for piano (Op.119), no.1', 'Intermezzo in B minor, Op 119 No 1'),  # Johannes Brahms
    ('Trio for viola, cello and piano (Op.114) in A minor',
     'Trio for clarinet or viola, cello and piano in A minor, Op 114'),  # Johannes Brahms
    ('Trio for Clarinet, Cello and Piano in A minor, op. 114',
     'Trio for clarinet or viola, cello and piano in A minor, Op 114'),  # Johannes Brahms
    ('Trio for clarinet or viola, cello and piano in A minor(Op.114)',
     'Trio for clarinet or viola, cello and piano in A minor, Op 114'),  # Johannes Brahms
    ('Clarinet Quintet in B minor, Op 115 for viola and string quartet', 'Clarinet Quintet in B minor, Op 115'),  # Johannes Brahms
    ('Viola Sonata in F minor, Op 120 no 1', 'Sonata in F minor, Op 120 No 1'),  # Johannes Brahms
    ('Clarinet Sonata in F minor, Op 120 no 1', 'Sonata in F minor, Op 120 No 1'),  # Johannes Brahms
    ('Sonata in F minor (Op.120 No.1) for clarinet or viola and', 'Sonata in F minor, Op 120 No 1'),  # Johannes Brahms
    ('Sonata in F minor (Op.120 No.1) for clarinet or viola and piano (Allegro appassionato; Andante un poco adagio; Allegretto grazioso; Vivace)',
     'Sonata in F minor, Op 120 No 1'),  # Johannes Brahms
    ('Clarinet Sonata (Op.120 No 2)', 'Sonata for clarinet and piano (Op.120 No.2) in E flat major'),  # Johannes Brahms
    ('Sonata for clarinet or viola and piano (Op.120 No.2) in E flat major',
     'Sonata for clarinet and piano (Op.120 No.2) in E flat major'),  # Johannes Brahms
    ('Viola Sonata in E flat major, Op 120 no 2',
     'Sonata for clarinet and piano (Op.120 No.2) in E flat major'),  # Johannes Brahms
    ('Trio for violin, viola and piano in E flat major, Op 40',
     'Trio for violin, French horn and piano in E flat major, Op 40'),  # Johannes Brahms
    ('Horn Trio in E flat major, Op 40', 'Trio for violin, French horn and piano in E flat major, Op 40'),  # Johannes Brahms
    ('Trio in E flat (Op. 40)', 'Trio for violin, French horn and piano in E flat major, Op 40'),  # Johannes Brahms
    ('Piano Trio in E flat major (Op.40)', 'Trio for violin, French horn and piano in E flat major, Op 40'),  # Johannes Brahms
    ('Violin Sonata No.2 in A major, Op.100 (Thunder)', 'Violin Sonata no 2 in A major, Op 100'),  # Johannes Brahms
    ('Sonata no 2 in A op 100', 'Violin Sonata no 2 in A major, Op 100'),  # Johannes Brahms
    ('Sonata No.3 in D minor for violin and piano (Op.108) MONO - 1964',
     'Violin Sonata No 3 in D minor, Op 108'),  # Johannes Brahms
    ('Violn Sonata No.3 , Op.108 - 1st Movement Only (Allegro)', 'Allegro from Violin Sonata No.3, Op.108'),  # Johannes Brahms
    ('Sonata No.1 (Op.78) in G major', 'Violin Sonata no 1 in G major, Op 78'),  # Johannes Brahms
    ('Violin Sonata No.1 in G major, Op.78 (Rain)', 'Violin Sonata no 1 in G major, Op 78'),  # Johannes Brahms
    ('Concerto in D for violin and orchestra in, Op 77', 'Violin Concerto in D major, Op 77'),  # Johannes Brahms
    ('Violin Conceto in D major (Op.77)', 'Violin Concerto in D major, Op 77'),  # Johannes Brahms
    ('Vivace non troppo (part of 3rd movement) from Double Concerto in A minor, Op.102',
     'Vivace non troppo (3rd mvt) from Double Concerto in A minor, Op.102'),  # Johannes Brahms
    ('Piano Quartet in G minor, Op 25', 'Quartet for piano and strings No.1 (Op.25) in G minor'),  # Johannes Brahms
    ('Piano Quartet in G minor Op 25 orch. Schoenberg',
     'Quartet for piano and strings No.1 (Op.25) in G minor'),  # Johannes Brahms
    ('Quartet (Op.25) in G minor orchestrated by Schoenberg',
     'Quartet for piano and strings No.1 (Op.25) in G minor'),  # Johannes Brahms
    ('Piano Quartet no 1 in G minor, Op 25 (orchestral version)',
     'Quartet for piano and strings No.1 (Op.25) in G minor'),  # Johannes Brahms
    ('Piano Quartet No.2 A major (Op.26)', 'Piano Quartet No 2 in A major, Op 26'),  # Johannes Brahms
    ('Piano Quartet No.3 in C minor (Op.60)', "Piano Quartet no 3 in C minor, Op 60, 'Werther'"),  # Johannes Brahms
    ('Piano Quartet No.3 in C minor (Op.60) (Allegro non troppo; Scherzo; Andante; Finale )',
     "Piano Quartet no 3 in C minor, Op 60, 'Werther'"),  # Johannes Brahms
    ('Piano Trio in B major (Op.8)', 'Piano Trio no 1 in B major, Op 8'),  # Johannes Brahms
    ('Trio in B major (Op.8 )', 'Piano Trio no 1 in B major, Op 8'),  # Johannes Brahms
    ('Trio in B major (Op.8 ) [revised 1889]', 'Piano Trio no 1 in B major, Op 8'),  # Johannes Brahms
    ('Piano Trio no 1 in B flat, Op 8 (first version) (1854)',
     'Piano Trio no 1 in B major, Op 8 (first version, 1854)'),  # Johannes Brahms
    ('String Quartet No 1 in C minor, Op 51', 'String Quartet no 1 in C minor, Op 51 No 1'),  # Johannes Brahms
    ('String Quartet (Op. 51 No.1) in C minor (Op. 51 No.1)', 'String Quartet no 1 in C minor, Op 51 No 1'),  # Johannes Brahms
    ('String Quartet in A minor, op. 51/2', 'String Quartet no 2 in A minor, Op 51 no 2'),  # Johannes Brahms
    ('Theme with Variations (Sextet in B flat, Op 18)',
     'Theme with variations from Sextet in B flat major, Op 18'),  # Johannes Brahms
    ('Theme and Variations in D minor, Op 18b', 'Theme with variations from Sextet in B flat major, Op 18'),  # Johannes Brahms
    ('Five Choral Songs (Op.104)', '5 Songs for chorus, Op 104'),  # Johannes Brahms
    ('Five Songs, op. 104', '5 Songs for chorus, Op 104'),  # Johannes Brahms
    ('Fünf Gesänge, Op 104', '5 Songs for chorus, Op 104'),  # Johannes Brahms
    ('Five Choral Songs, Op.104 (Nachtwache 1; Nachtwache 2; Letztes Glück; Verlorene Jugend; Im Herbst)',
     '5 Songs for chorus, Op 104'),  # Johannes Brahms
    ('5 Songs for chorus (Op.104) [Nachtwache 1', '5 Songs for chorus, Op 104'),  # Johannes Brahms
    ("Letztes Glück, from 'Fünf Gesänge, op. 104/3'", 'Letztes Glück (5 Gesänge, Op.104 no.3)'),  # Johannes Brahms
    ('11 Zigeunerlieder, Op 103', '11 Zigeunerlieder for 4 voices and piano (Op.103)'),  # Johannes Brahms
    ('Fest- und Gedenksprüche, Op.109', 'Fest- und Gedenkspruche for 8 voices, Op 109'),  # Johannes Brahms
    ('6 Quartets for chorus and piano (Op.112) (Ziguenerlieder)',
     '6 Quartets for soprano, alto, tenor, bass and piano, Op 112'),  # Johannes Brahms
    ('6 Quartets for chorus and piano (Op.112) Zigeunerlieder',
     '6 Quartets for soprano, alto, tenor, bass and piano, Op 112'),  # Johannes Brahms
    ('6 Quartets for chorus and piano (Op.112) Ziguenerlieder for SATB/piano]',
     '6 Quartets for soprano, alto, tenor, bass and piano, Op 112'),  # Johannes Brahms
    ('4 Ernste Gesange, Op 121', 'Vier ernste Gesänge, Op 121'),  # Johannes Brahms
    ('Vier Gesänge, op. 17', "4 Songs for women's voices, 2 horns and harp, Op 17"),  # Johannes Brahms
    ('Four Songs, Op 17: Es tönt ein voller Harfenklang; Lied von Shakespeare; Der Gärtner; Gesang aus Fingal',
     "4 Songs for women's voices, 2 horns and harp, Op 17"),  # Johannes Brahms
    ('2 Motets: 1. Es ist das Heil uns kommen her; 2. Schaffe in mir, Gott, ein reines Herz (Op.29)',
     '2 Motets, Op 29'),  # Johannes Brahms
    ('Es ist das Heil uns kommen her; Schaffe in mir, Gott, ein rein Herz, Op 29', '2 Motets, Op 29'),  # Johannes Brahms
    ('Two Motets: Es ist das Heil uns kommen her; Schaffe in mir, Gott, ein reines Herz, Op 29',
     '2 Motets, Op 29'),  # Johannes Brahms
    ('Schaffe in mir, Gott, ein rein Herz, from 2 Motets (Op.29 No.2)',
     'Schaffe in mir, Gott, ein rein Herz, Op 29 no 2'),  # Johannes Brahms
    ('4 Gesänge,Op.32', '4 Gesange, Op 32'),  # Johannes Brahms
    ('4 Songs, Op.32', '4 Gesange, Op 32'),  # Johannes Brahms
    ('3 Songs for chorus (Op.42) (Abendständchen; Vineta; Darthulas Grabesgesang)',
     '3 Songs for chorus, Op 42'),  # Johannes Brahms
    ('Von ewiger Liebe (Op.43 No.1) (song)', 'Von ewiger Liebe, Op 43 no 1'),  # Johannes Brahms
    ("No.1 'Minnelied' & No.10 'Und gehst du über den Kirchhof' - from Songs and romances for female chorus (Op.44)",
     "No.1 'Minnelied' & No.10 'Und gehst du uber den Kirchhof' (Op.44)"),  # Johannes Brahms
    ('A German Requiem, Op 45', 'Ein Deutsches Requiem, Op 45'),  # Johannes Brahms
    ("Ein deutsches Requiem, Op.45 ('German Requiem')", 'Ein Deutsches Requiem, Op 45'),  # Johannes Brahms
    ("Guten Abend, gut' Nacht, op. 49/4", 'Wiegenlied, Op 49 no 4'),  # Johannes Brahms
    ('Wiegenlied - Lullaby, Op 49 no 4', 'Wiegenlied, Op 49 no 4'),  # Johannes Brahms
    ('Wiegenlied (Funf Lieder, Op 49, No 4) - arr Lee', 'Wiegenlied, Op 49 no 4'),  # Johannes Brahms
    ('Wiegenlied – from Funf Lieder (Op.49 No.4)', 'Wiegenlied, Op 49 no 4'),  # Johannes Brahms
    ("Wiegenlied. Zar bewegt, from '5 Lieder, Op 49'", 'Wiegenlied, Op 49 no 4'),  # Johannes Brahms
    ("Wiegenlied. Zart bewegt, from '5 Lieder, Op 49'", 'Wiegenlied, Op 49 no 4'),  # Johannes Brahms
    ('Rhapsody for contralto, male chorus & orchestra (Op.53)',
     'Rhapsody for alto, male chorus and orchestra, Op 53'),  # Johannes Brahms
    ('Alto Rhapsody, Op 53', 'Rhapsody for alto, male chorus and orchestra, Op 53'),  # Johannes Brahms
    ('Schicksalslied [Song of Destiny] for chorus and orchestra, Op 54',
     'Schicksalslied (Song of destiny), Op 54'),  # Johannes Brahms
    ('Schicksalslied for chorus and orchestra (Op.54)', 'Schicksalslied (Song of destiny), Op 54'),  # Johannes Brahms
    ('Schicksalslied, Op 54', 'Schicksalslied (Song of destiny), Op 54'),  # Johannes Brahms
    ('Schicksalslied', 'Schicksalslied (Song of destiny), Op 54'),  # Johannes Brahms — bare title, unique in his catalogue
    ('Schicksalslied (Song of destiny) for chorus and orchestar (Op.54)',
     'Schicksalslied (Song of destiny), Op 54'),  # Johannes Brahms
    ('Song of destiny (Op.54)', 'Schicksalslied (Song of destiny), Op 54'),  # Johannes Brahms
    ('Warum ist das Licht gegeben dem Mühseligen, Op 74 no 1 (motet)',
     'Warum ist das Licht gegeben dem Muhseligen, Op 74 no 1'),  # Johannes Brahms
    ('Warum ist das Licht gegeben dem Muhseligen (Op.74) (part 1)',
     'Warum ist das Licht gegeben dem Muhseligen, Op 74 no 1'),  # Johannes Brahms
    ('Warum ist das Licht gegeben dem Muhseligen (Op.74)',
     'Warum ist das Licht gegeben dem Muhseligen, Op 74 no 1'),  # Johannes Brahms
    ('Warum ist das Licht gegeben dem Muhseligenm Op 74, part 1',
     'Warum ist das Licht gegeben dem Muhseligen, Op 74 no 1'),  # Johannes Brahms
    ('O Heiland, reiss die Himmel auf (Motet, Op. 74/2)',
     'O Heiland, reiss die Himmel auf from Op. 74/2 from 2 Motets'),  # Johannes Brahms
    ('Nanie Op.82 for chorus and orchestra', 'Nanie Op 82'),  # Johannes Brahms
    ('Schiller, Friedrich: Nanie, Op 82', 'Nanie Op 82'),  # Johannes Brahms
    ('Gesang des Parzen (song of the fates) for chorus and orchestra, Op 89',
     'Gesang der Parzen (Song of the Fates), Op 89'),  # Johannes Brahms
    ('Song of the Fates (Op.89)', 'Gesang der Parzen (Song of the Fates), Op 89'),  # Johannes Brahms
    ('Song of the Fates for chorus and orchestra (Op.89)', 'Gesang der Parzen (Song of the Fates), Op 89'),  # Johannes Brahms
    ('Six Songs: Wir wandelten (Op.96 No.2); Alte Liebe (Op.72); Das MÃ¤dchen spricht (Op.107 No.3); Immer leiser wird mein Schlummer (Op.105); Meine Liebe ist GrÃ¼n (Op.63); Von ewiger Liebe (Op.43 No.1); Der Tod, das ist die kÃ¼hle Nacht (Op.96)',
     'Six Songs: Wir wandelten (Op.96 No.2); Alte Liebe - from 5 Gesäng (Op.72); Das Mädchen spricht (Op.107 No.3); Immer leiser wird mein Schlummer - from 5 Lieder für eine tiefere Stimme (Op.105); Meine Liebe ist Grün - from 9 Lieder und Gesange (Op.63); Von ewiger Liebe (Op.43 No.1); Der Tod, das ist die kühle Nacht - from Vier Lieder (Op.96)'),  # Johannes Brahms
    ('Seven Songs: Wir wandelten (Op.96 No.2); Alte Liebe - from 5 Songs (Op.72); Das Mädchen spricht (Op.107 No.3); Immer leiser wird mein Schlummer - from 5 Songs (Op.105); Meine Liebe ist Grün - from 9 Lieder und Gesange (Op.63); Von ewiger Liebe (Op.43 No.1); Der Tod, das ist die kühle Nacht - from 4 Songs (Op.96)',
     'Seven Songs'),  # Johannes Brahms (re-targeted 2026-07-19: mega target became an LHS)
    ('Seven Songs: Wir wandelten (Op.96 No.2); Alte Liebe - from Fünf Gesäng (Op.72); Das Mädchen spricht (Op.107 No.3); Immer leiser wird mein Schlummer - from 5 Lieder fur eine tiefere Stimme (Op.105); Meine Liebe ist Grün - from Neun Lieder und Gesange (Op.63); Von ewiger liebe (Op.43 No.1); Der Tod, das ist die kühler Nacht - from Vier Lieder (Op.96)',
     'Seven Songs'),  # Johannes Brahms (re-targeted 2026-07-19: mega target became an LHS)
    ('Neue Liebeslieder, Op.65', 'Neue Liebeslieder - [15] waltzes for voices & piano duet (Op.65)'),  # Johannes Brahms
    ('Neue Liebeslieder - waltzes for voices & piano duet (Op.65)',
     'Neue Liebeslieder - [15] waltzes for voices & piano duet (Op.65)'),  # Johannes Brahms
    ('Variations on a Theme of Paganini Op. 35', '28 Variations on a theme by Paganini for piano (Op.35)'),  # Johannes Brahms
    ('Variations on a theme by Paganini, Op 35 (excerpts Book 1, Nos 1-14)',
     'Variations on a theme by Paganini, Op 35 (excerpts from Book 1, Nos 1-14)'),  # Johannes Brahms
    ('28 Variations on a theme by Paganini Op.35 for piano - Book 1',
     'Variations on a theme by Paganini, Op 35 (excerpts from Book 1, Nos 1-14)'),  # Johannes Brahms
    ('Variations on a theme of Haydn (Op.56a) "St Antoni Chorale"', 'Variations on a theme by Haydn (Op.56a)'),  # Johannes Brahms
    ('Variations on a theme by Haydn vers. for orchestra, Op 56a', 'Variations on a theme by Haydn (Op.56a)'),  # Johannes Brahms
    ("Variations on a theme of Haydn, Op 56a 'St Antoni Chorale' (vers. for orchestra)",
     'Variations on a theme by Haydn (Op.56a)'),  # Johannes Brahms
    ('Variations on a Theme by Haydn (Op.56a) vers. for orchestra "St Anthony Chorale"',
     'Variations on a theme by Haydn (Op.56a)'),  # Johannes Brahms
    ('Variations on a Theme by Haydn, Op 56a - version for orchestra',
     'Variations on a theme by Haydn (Op.56a)'),  # Johannes Brahms
    ('Variations on a Theme by Haydn, Op 56a - version for orchestra (St Antoni Chorale)',
     'Variations on a theme by Haydn (Op.56a)'),  # Johannes Brahms
    ('Waltz in B minor, Op 39, No 11; Waltz in E arranged for chamber orchestra, Op 39, No 12',
     'Waltz No.11 in B minor & Waltz No.12 in E major (arranged for chamber orchestra) - from the Waltzes for two pianos (Op.39)'),  # Johannes Brahms
    # --- Schumann opus-set sweep (2026-07-05): 80 folds over the 49 Robert +
    # 3 Clara post-gate fragmented signatures (scratch/schumann_post.txt /
    # clara_post.txt). Notable calls: ALL Manfred Op 115 phrasings = the
    # overture (recording-duration oracle: the 'incidental music' recording is
    # 760s, in the 713-805s overture band); Opp 70/73/94 alt-scorings merged
    # (composer-designated alternatives, the Brahms Op 114 class); Liszt's
    # Widmung transcription S.566 folded (Cerys: arrangement-grade, no new
    # thematic invention); Op 44 'E minor' and Op 61 'C minor' mislabels
    # folded; DO-NOT-USE/KILL internal-annotation strays folded (Opp 129/132).
    # Left split: Sym 4 original-1841 and Andante & Variations Op 46 1843
    # quintet version (authorial revision/Fassung — Cerys 2026-07-05);
    # '4 Fugues Op 72 (excerpts)' (unspecified); movement excerpts vs wholes;
    # Paradise & the Peri Acts 1/2 vs the Parts-1&2 pairing; Clara's Op 13
    # excerpts and Op 7 1st movement. 'Ihr Bildnis' = alternate title of
    # Clara's 'Ich stand in dunklen Träumen' (one Heine setting, Op 13 no 1).
    ('5 Stucke im Volkston for cello (or violin) and piano (Op.102)', 'Fünf Stücke im Volkston, Op.102'),  # Robert Schumann
    ('Sonata no. 1 in F sharp minor Op.11', 'Piano Sonata no 1 in F sharp minor, Op 11'),  # Robert Schumann
    ('Fantasiestücke, Op 111 no 2', 'Fantasiestück in A flat, Op 111 no 2'),  # Robert Schumann
    ('Fairy Tale Pictures op.113', 'Marchenbilder, Op 113'),  # Robert Schumann
    ('Manfred - incidental music (Op.115)', 'Overture (Manfred, Op 115)'),  # Robert Schumann
    ('Overture - from the incidental music to Manfred (Op.115)', 'Overture (Manfred, Op 115)'),  # Robert Schumann
    ('Overture (incidental music to Manfred, Op 115)', 'Overture (Manfred, Op 115)'),  # Robert Schumann
    ('Symphony No 4 Op 120 in D minor, vers. standard (1851)', 'Symphony No 4 in D minor, Op 120'),  # Robert Schumann
    ('Symphony No. 4 in D minor, op. 120 (published version 1851)', 'Symphony No 4 in D minor, Op 120'),  # Robert Schumann
    ('Cello Concerto in A minor (Op.129) DO NOT USE - AMADEUS ORCHESTRA', 'Cello Concerto in A minor'),  # Robert Schumann
    ('Symphonic Etudes (Op.13)', 'Symphonische Etuden for piano, Op 13'),  # Robert Schumann
    ('Etudes en formes de variations Op.13 for piano (vers.rev.1852 w/out Variations Op.posth.)',
     'Symphonische Etuden for piano, Op 13'),  # Robert Schumann
    ('Märchenerzählungen (Fairy tales) for clarinet, viola and piano (Op.132)', 'Fairy Tales, Op 132'),  # Robert Schumann
    ('Märchenerzählungen for clarinet, viola and piano (Op.132)', 'Fairy Tales, Op 132'),  # Robert Schumann
    ('Fairy Tales for clarinet, viola and piano, Op 132', 'Fairy Tales, Op 132'),  # Robert Schumann
    ('Marchenerzahlungen, Op 132', 'Fairy Tales, Op 132'),  # Robert Schumann
    ('KILL   Marchenerzahlungen [Fairy Tales] for clarinet, viola and piano (Op.132)', 'Fairy Tales, Op 132'),  # Robert Schumann
    ('Gesänge der Frühe (Op.133)', 'Gesänge Der Frühe - Songs of Dawn, Op 133'),  # Robert Schumann
    ('5 Gesange der Fruhe Op 133 for piano', 'Gesänge Der Frühe - Songs of Dawn, Op 133'),  # Robert Schumann
    ("Gesänge der Frühe (Chants de l'Aube) (Op.133)", 'Gesänge Der Frühe - Songs of Dawn, Op 133'),  # Robert Schumann
    ("Gesänge der Frühe (Chants de l'Aube) (Op.133) Brentano", 'Gesänge Der Frühe - Songs of Dawn, Op 133'),  # Robert Schumann
    ("GesÃ¤nge der FrÃ¼he (Chants de l'Aube) [Songs of Dawn] (Op.133)",
     'Gesänge Der Frühe - Songs of Dawn, Op 133'),  # Robert Schumann
    ('Songs of Dawn, Op 133', 'Gesänge Der Frühe - Songs of Dawn, Op 133'),  # Robert Schumann
    ('5 Gedichte der Königen Maria Stuart (Op.135)',
     '5 Gedichte der Konigin Maria Stuart (5 Poems of Queen Mary Stuart), Op 135'),  # Robert Schumann
    ('5 Gedichte der Königin Maria Stuart (Op.135)',
     '5 Gedichte der Konigin Maria Stuart (5 Poems of Queen Mary Stuart), Op 135'),  # Robert Schumann
    ('Five Poems of Queen Mary Stuart, Op 135',
     '5 Gedichte der Konigin Maria Stuart (5 Poems of Queen Mary Stuart), Op 135'),  # Robert Schumann
    ('Piano Sonata No.3 in F minor (Op.14)', 'Piano Sonata No 3 in F minor, Op 14 (Concert sans orchestre)'),  # Robert Schumann
    ('Four Songs for Double Chorus, op. 141; An die Sterne (Friedrich Rückert); Ungewisses Licht (Joseph Christian von Zedlitz); Zuversicht (Joseph Christian von Zedlitz); Talismane (Johann Wolfgang von Goethe)',
     'Four Songs for Double Chorus, op. 141'),  # Robert Schumann
    ("Träumerei (excerpt 'Kinderszenen', Op 15", 'Träumerei, from Kinderszenen, Op.15'),  # Robert Schumann
    ('Träumerei (No.7) - from Kinderszenen for piano (Op.15)', 'Träumerei, from Kinderszenen, Op.15'),  # Robert Schumann
    ('Der Dichter Spricht (Kinderszenen, Op.15) (encore)', 'Der Dichter spricht, from Kinderszenen (Op.15)'),  # Robert Schumann
    ('Kreisleriana - 8 fantasies Op.16 for piano', 'Kreisleriana Op 16'),  # Robert Schumann
    ('Songs (Myrten, Op 25)', 'Songs from Myrten (Op.25)'),  # Robert Schumann
    ('Songs from Myrthen (Op.25)', 'Songs from Myrten (Op.25)'),  # Robert Schumann
    ('Widmung, Op 25 no 1 from Myrthen', 'Widmung (Op.25 No.1)'),  # Robert Schumann
    ("Widmung (Dedication), from 'Myrten, op. 25/1, (S. 566)", 'Widmung (Op.25 No.1)'),  # Robert Schumann
    ("Du bist wie eine Blume, Op 25/24, from 'Myrthen'",
     'Du bist wie eine Blume, Op.25 No.24 (from Myrthen) (You are so like a flower)'),  # Robert Schumann
    ('Faschingsschwank aus Wien - Phantasiebilder Op.26 (4. Intermezzo in Eb minor)',
     'Intermezzo in E flat minor (Faschingsschwank aus Wien - Phantasiebilder, Op 26)'),  # Robert Schumann
    ('Symphony No 1 in B flat, Op 38', "Symphony No.1 in B flat major (Op.38) 'Spring'"),  # Robert Schumann
    ("Symphony No.1 in B flat major,Op.38, 'Spring'", "Symphony No.1 in B flat major (Op.38) 'Spring'"),  # Robert Schumann
    ("String Quartet A major, Op.41'3", "String Quartet in A major, Op. 41'3"),  # Robert Schumann
    ('Quintet in E minor for piano and strings, Op 44', 'Piano Quintet in E flat major, Op 44'),  # Robert Schumann
    ('Quintet for piano and strings (Op.44) in E flat major [scherzo]',
     'Scherzo from Piano Quintet in E flat, Op 44'),  # Robert Schumann
    ('Piano Quartet in E flat, Op 47 (Sostenuto assai - Allegro Ma Non Troppo)',
     'Piano Quartet in E flat, Op 47 - 1st movt'),  # Robert Schumann
    ('Heine, Heinrich (1797-1856): Dichterliebe for voice and piano, Op 48',
     'Dichterliebe for voice and piano, Op 48'),  # Robert Schumann
    ('Heinrich Heine: Dichterliebe, Op 48', 'Dichterliebe for voice and piano, Op 48'),  # Robert Schumann
    ("Hor' ich das Liedchen klingen (Dichterliebe, Op 48 No 10)",
     "Hor' ich das Liedchen klingen - from Dichterliebe, Op 48 no 10"),  # Robert Schumann
    ('"Hör\' ich das Liedchen klingen" - from Dichterliebe (Op 48) arranged for baritone, piano, violin & cello',
     "Hor' ich das Liedchen klingen - from Dichterliebe, Op 48 no 10"),  # Robert Schumann
    ('Das Paradies und die Peri, Op.50 - Act 3', 'Paradise and the Peri, op. 50 Part 3'),  # Robert Schumann
    ('Andantino from Six studies in canonic form (Six studies for pedal piano) arr. piano trio (Op.56, No.3)',
     'Andantino from Six studies in canonic form (Op.56, no.3)'),  # Robert Schumann
    ('Andantino from Six studies in canonic form for pedal piano, arr. piano trio (Op.56 no.3)',
     'Andantino from Six studies in canonic form (Op.56, no.3)'),  # Robert Schumann
    ('6 Studies Op.56 (no.4)', "Etude no 4, 'Innig' - from Six Canonic Etudes, Op 56"),  # Robert Schumann
    ('Innig (No. 4), from Studies for Pedal Piano: Six Pieces in Canonic Form (Op. 56)',
     "Etude no 4, 'Innig' - from Six Canonic Etudes, Op 56"),  # Robert Schumann
    ('Adagio (Op.56 no.6) from Six studies for pedal piano, arr. piano trio',
     'Adagio (from Six studies for pedal piano, arr. piano trio, Op 56 no 6)'),  # Robert Schumann
    ('Adagio (Six studies for pedal piano, arr. piano trio (Op.56 no.6))',
     'Adagio (from Six studies for pedal piano, arr. piano trio, Op 56 no 6)'),  # Robert Schumann
    ('Adagio from Six studies in canonic form (Six studies for pedal piano) arr. piano trio (Op.56 No.6)',
     'Adagio (from Six studies for pedal piano, arr. piano trio, Op 56 no 6)'),  # Robert Schumann
    ('Adagio from Six studies in canonic form for pedal piano, arr. piano trio (Op.56 no.6)',
     'Adagio (from Six studies for pedal piano, arr. piano trio, Op 56 no 6)'),  # Robert Schumann
    ('Davidsbündlertänze, Op 6', 'Davidsbündlertänze - 18 character-pieces for piano, Op 6'),  # Robert Schumann
    ('Fugue No 3 in G minor (Sechs Fugen uber BACH, Op 60)',
     'Fugue No.3 in G minor - from Sechs Fügen über B.A.C.H. (Op.60)'),  # Robert Schumann
    ('Symphony No 2 in C minor, Op 61', 'Symphony No.2 in C major (Op.61)'),  # Robert Schumann
    ('Bilder aus Osten - 6 impromptus Op.66 for piano duet', 'Bilder aus Osten, Op 66'),  # Robert Schumann
    ('Toccata (Op.7)', 'Toccata in C major, Op.7'),  # Robert Schumann
    ('Adagio and allegro for cello and piano (Op.70) in A flat major',
     'Adagio and allegro in A flat major, Op 70'),  # Robert Schumann
    ('Adagio and allegro in A flat major Op.70 for horn & piano, version with oboe',
     'Adagio and allegro in A flat major, Op 70'),  # Robert Schumann
    ('Drei Fantaisiestucke (Op.73)', 'Phantasiestucke Op 73 for clarinet & piano'),  # Robert Schumann
    ('Drei Fantasiestucke (Op.73)', 'Phantasiestucke Op 73 for clarinet & piano'),  # Robert Schumann
    ('Phantasiestucke for cello and piano (Op.73)', 'Phantasiestucke Op 73 for clarinet & piano'),  # Robert Schumann
    ('Fantasiestucke for cello and piano, Op 73', 'Phantasiestucke Op 73 for clarinet & piano'),  # Robert Schumann
    ('Fantasiestücke (Op.73) for clarinet (or violin or cello) & piano',
     'Phantasiestucke Op 73 for clarinet & piano'),  # Robert Schumann
    ('Fantasiestücke (Op.73) vers. for cello and piano', 'Phantasiestucke Op 73 for clarinet & piano'),  # Robert Schumann
    ('Der Vogel als Prophet, op. 82', "Vogel als Prophet, from 'Waldszenen, Op.82'"),  # Robert Schumann
    ('Vogel als Prophet (Waldszenen Op.82)', "Vogel als Prophet, from 'Waldszenen, Op.82'"),  # Robert Schumann
    ('Concertstuck in F major Op.86 for 4 horns and orchestra',
     'Konzertstück in F major for 4 Horns and Orchestra, Op 86'),  # Robert Schumann
    ('Carnaval (Op.9)', 'Carnaval, scenes mignonnes sur quatre notes for piano, Op 9'),  # Robert Schumann
    ('Six Songs and Requiem, Op 90', 'Six Poems by Lenau and Requiem, Op 90'),  # Robert Schumann
    ('3 Romances Op.94 for oboe & piano, version with horn', 'Three Romances Op 94'),  # Robert Schumann
    ('3 Romances Op.94 for violin and piano', 'Three Romances Op 94'),  # Robert Schumann
    ('Symphony No 3 in E flat, Op 97', 'Symphony no 3 in E flat major, Op 97 "Rhenish"'),  # Robert Schumann
    ("Symphony No.3 in E flat major (Op.97) 'Rhenish', (Lebhaft; Scherzo; Unbeshaftigt; Feierlich; Lebhaft)",
     'Symphony no 3 in E flat major, Op 97 "Rhenish"'),  # Robert Schumann
    ('Ihr Bildnis, Op 13 no 1', 'Ich stand in dunklen Träumen, Op 13 no 1'),  # Clara Schumann
    # --- Schumann sweep batch 2 (2026-07-05): bare-title / S-number stragglers
    # invisible to the Op-anchored probe (ranking tail-check). The Widmung
    # S.566 Liszt-transcription family (~36 airings) folds into the SONG per
    # the Cerys arrangement-grade verdict (the pre-existing Liederkreise pair
    # above was retargeted to match); the posthumous Violin Concerto's three
    # Op-spelling keys unify; the rest are opus-less twins of consolidated
    # groups (bare 'in A' quartet = A major, corpus-confirmed usage).
    ('Widmung, S.566', 'Widmung (Op.25 No.1)'),  # Robert Schumann
    ('Widmung (Dedication), from Myrthen, S.566', 'Widmung (Op.25 No.1)'),  # Robert Schumann
    ('Widmung (from Liebeslied)', 'Widmung (Op.25 No.1)'),  # Robert Schumann
    ('Widmung from Liederkreis, S.566', 'Widmung (Op.25 No.1)'),  # Robert Schumann
    ('Concerto for Violin and Orchestra in D minor (Op.posthumous)',
     'Concerto for violin and orchestra in D minor'),  # Robert Schumann
    ('Concerto for Violin and Orchestra in D minor (Op.post.)', 'Concerto for violin and orchestra in D minor'),  # Robert Schumann
    ('Concerto in D minor for violin and orchestra, Op posth', 'Concerto for violin and orchestra in D minor'),  # Robert Schumann
    ('Overture (Genoveva)', 'Overture to Genoveva, Op 81'),  # Robert Schumann
    ('Overture to Manfred, after Byron', 'Overture (Manfred, Op 115)'),  # Robert Schumann
    ('Symphony No 4 D minor (standard version, 1851)', 'Symphony No 4 in D minor, Op 120'),  # Robert Schumann
    ('Violin Sonata No 1 in A minor', 'Violin Sonata no 1 in A minor, Op 105'),  # Robert Schumann
    ('Piano Concerto in A minor', 'Piano Concerto in A minor, Op 54'),  # Robert Schumann
    ('String Quartet in A', 'String Quartet in A major, Op 41 no 3'),  # Robert Schumann
    ('Kinderszenen - no.13; Der Dichter spricht', 'Der Dichter spricht, from Kinderszenen (Op.15)'),  # Robert Schumann
    ("Traumerei from 'Kinderszenen'", 'Träumerei, from Kinderszenen, Op.15'),  # Robert Schumann
    ('Symphonische Etuden', 'Symphonische Etuden for piano, Op 13'),  # Robert Schumann
    ('Gesange der Fruhe (Songs of Dawn)', 'Gesänge Der Frühe - Songs of Dawn, Op 133'),  # Robert Schumann
    ('5 Gedichte der Konigen Maria Stuart',
     '5 Gedichte der Konigin Maria Stuart (5 Poems of Queen Mary Stuart), Op 135'),  # Robert Schumann
    ("Hor' ich das Liedchen klingen (Dichterliebe)",
     "Hor' ich das Liedchen klingen - from Dichterliebe, Op 48 no 10"),  # Robert Schumann
    ('Symphony No 2 in C minor', 'Symphony No.2 in C major (Op.61)'),  # Robert Schumann
    ('Symphony No.2 in C major', 'Symphony No.2 in C major (Op.61)'),  # Robert Schumann
    # --- Mendelssohn opus-set sweep (2026-07-05): 65 folds over the 34 Felix
    # + 3 Fanny post-gate fragmented signatures (scratch/felix_post.txt /
    # fanny_post.txt). Notable calls: the Op 61 'Concert Paraphrase (excerpts)'
    # recording (459s) = the Liszt Wedding March & Elfin Dance paraphrase, so
    # all WM&ED keys unify there (paraphrase group stays SPLIT from the
    # incidental music); Elijah Part keys fold per-Part into the Elias/Carus
    # finals (Carus is an edition, not a version), and 'For He shall give his
    # angels' folds cross-language into 'Denn er hat seinen Engeln befohlen';
    # Op 110 'd minor' mislabel folded; Op 81 'Spring Quartet' typo folded;
    # Fanny Op 6: the 598s excerpts recording = nos 1,3,4, so the enumerated/
    # selection phrasings fold to the excerpts group (whole-set-titled key
    # stays split). Left split: Op 61 incidental music vs paraphrase vs suite
    # vs enumerated 3-movement selection; Op 21-mislabelled MSND Scherzo
    # excerpt group; oratorio wholes vs Parts; single psalms vs the Op 78 set;
    # Op 20 Scherzo orch.; movement excerpts vs wholes throughout.
    ('Three Etudes (Op.104)', '3 Studies for piano, Op 104b'),  # Felix Mendelssohn
    ("Symphony No.5 in D major 'Reformation' (Op.107) (Andante - allegro con fuoco; Allegro vivace; Andante; Andante con moto - allegro vivace)",
     'Symphony No.5 in D major Op.107 "Reformation"'),  # Felix Mendelssohn
    ('Lied ohne Worte in D major Op.109 for cello and piano', 'Lied ohne Worte in D major, Op 109'),  # Felix Mendelssohn
    ('Sextet in d minor for piano and strings, Op 110', 'Sextet for piano and strings in D major, Op 110'),  # Felix Mendelssohn
    ('Quartet no. 2 in A minor, Op 13', 'String Quartet no 2 in A minor, Op 13'),  # Felix Mendelssohn
    ('String Quartet No 2, Op 13', 'String Quartet no 2 in A minor, Op 13'),  # Felix Mendelssohn
    ('Rondo capriccioso, Op 14', 'Rondo capriccioso in E major/minor, Op 14'),  # Felix Mendelssohn
    ('Fantasy on The Last Rose of Summer, Op 15',
     "Fantasia on an Irish song 'The last rose of summer' for piano, Op 15"),  # Felix Mendelssohn
    ("Fantasy on the Irish song 'The Last Rose of Summer' (Op.15)",
     "Fantasia on an Irish song 'The last rose of summer' for piano, Op 15"),  # Felix Mendelssohn
    ('Fantasia No 2 in E minor (The Little Trumpeter) - Three Fantasias (Caprices) for piano, Op 16',
     "Fantasia No.2 in E minor (Presto) 'The little trumpeter' - from 3 Fantasias (Caprices) for piano (Op.16)"),  # Felix Mendelssohn
    ('Fantasia No.2 in E minor (Presto) (Op.16)  "The little trumpeter"',
     "Fantasia No.2 in E minor (Presto) 'The little trumpeter' - from 3 Fantasias (Caprices) for piano (Op.16)"),  # Felix Mendelssohn
    ('String Octet (Op.20) in E flat major Yoshiko Arai and Ik-Hwan Bae (male) (violins), Yuko Inoue (viola), Christoph Richter (cello), Vogler Quartet',
     'String Octet in E flat major, Op 20'),  # Felix Mendelssohn
    ("A Midsummer Night's Dream, Op 21 (Overture)", "Overture to 'A Midsummer Night's Dream', Op. 21"),  # Felix Mendelssohn
    ('Overture in C major Op.24', 'Overture for wind instruments (Op.24) in C major'),  # Felix Mendelssohn
    ('Hebrides Overture, Op 26 (1830 rev 1832)', 'The Hebrides, Op 26'),  # Felix Mendelssohn
    ('Meeresstille und gluckliche Fahrt, Op 27', 'Meeresstille und gluckliche Fahrt - Overture, Op 27'),  # Felix Mendelssohn
    ('Lieder ohne Worte - book 2 (Op.30), no.6; Venetianisches Gondellied in F# minor',
     "Venetian Boat Song from 'Songs Without Words', book II, Op 30 no 6"),  # Felix Mendelssohn
    ('Venetian Boat Song, Op 30, No 6 (Songs Without Words, Book 2)',
     "Venetian Boat Song from 'Songs Without Words', book II, Op 30 no 6"),  # Felix Mendelssohn
    ('Venetianisches Gondellied in F# minor, No.6 from Lieder ohne Worte - book 2 (Op.30)',
     "Venetian Boat Song from 'Songs Without Words', book II, Op 30 no 6"),  # Felix Mendelssohn
    ('Die schone Melusine [The Fair Melusine] - overture Op 32', 'Die schöne Melusine - overture (Op.32)'),  # Felix Mendelssohn
    ('Die schÃ\x83ne Melusine - overture (Op.32)', 'Die schöne Melusine - overture (Op.32)'),  # Felix Mendelssohn
    ('Auf Flugen des Gesanges [On Wings of Song] (Op.34 no.2)',
     'On wings of song (Op 34 no 2) arr. anon for clarinet & piano'),  # Felix Mendelssohn
    ('Overture (St Paul, Op 36)', 'St.Paul, Op 36, Overture'),  # Felix Mendelssohn
    ('Sonata for cello and piano No.1 in B flat major (Op.45) (Allegro vivace; Andante; Allegro assai)',
     'Cello Sonata No 1 in B flat major, Op 45'),  # Felix Mendelssohn
    ('Lobgesang (Symphony no.2) for soloists, chorus and orchestra (Op.52)',
     "Symphony no 2 in B flat, Op 52 ('Lobgesang')"),  # Felix Mendelssohn
    ('4 songs from Im Grünen, Op 59 - Nos 1, 4, 5 & 6', '4 songs from Op 59 - Nos 1, 4, 5 & 6'),  # Felix Mendelssohn
    ('4 songs from Im Grünen (Op.59)', '4 songs from Op 59 - Nos 1, 4, 5 & 6'),  # Felix Mendelssohn
    ('Four songs (Im Grunen, Op 59)', '4 songs from Op 59 - Nos 1, 4, 5 & 6'),  # Felix Mendelssohn
    ('4 songs from Im Grünen, Op.59 (Im Grünen; Die Nachtigall; Ruhetal; Jagdlied)',
     '4 songs from Op 59 - Nos 1, 4, 5 & 6'),  # Felix Mendelssohn
    ('Im Grunen - 6 songs for chorus (Op.59)', '6 Lieder for mixed voices Op.59'),  # Felix Mendelssohn
    ("A Midsummer Night's Dream - Concert Paraphrase, Op.61 (excerpts)",
     "Wedding March & Elfin Dance - from 'A Midsummer Night's Dream', Op.61 - Concert Paraphrase"),  # Felix Mendelssohn
    ("Wedding March & Elfins Dance - from 'A Midsummer Night's Dream', Op.61",
     "Wedding March & Elfin Dance - from 'A Midsummer Night's Dream', Op.61 - Concert Paraphrase"),  # Felix Mendelssohn
    ("Wedding March and Elfins Dance (A Midsummer Night's Dream, Op 61)",
     "Wedding March & Elfin Dance - from 'A Midsummer Night's Dream', Op.61 - Concert Paraphrase"),  # Felix Mendelssohn
    ("A Midsummer Night's Dream (Op.61) - incidental music (excerpts)",
     "Excerpts from 'A Midsummer Night's Dream, Op 61'"),  # Felix Mendelssohn
    ('Spring Song (Frühlingslied) Op.62 No.6', 'Spring Song (Fruhlingslied) in A major (Op.62 No.6)'),  # Felix Mendelssohn
    ('Violin Concerto in E minor, Op 64 (Proms 2015)', 'Violin Concerto in E minor, Op 64'),  # Felix Mendelssohn
    ('Violin Concerto (Op.64) in E minor, Op.64', 'Violin Concerto in E minor, Op 64'),  # Felix Mendelssohn
    ('Sonata in A, Op 65 No 3', 'Sonata for organ in A major, Op 65 no 3'),  # Felix Mendelssohn
    ('Organ Sonata in D major, Op 65 No 5', 'Sonata in D major (1844) (Op.65 No.5)'),  # Felix Mendelssohn
    ('Elijah, Op.70 - oratorio (Carus version): Part I',
     'Elias (Elijah), Op.70 - oratorio (Carus version): Part I'),  # Felix Mendelssohn
    ('Elijah Op.70 - Part 1', 'Elias (Elijah), Op.70 - oratorio (Carus version): Part I'),  # Felix Mendelssohn
    ('Elijah, Op.70 - oratorio (Carus version): Part II',
     'Elias (Elijah), Op.70 - oratorio (Carus version): Part II'),  # Felix Mendelssohn
    ('Elijah Op.70 - Part 2', 'Elias (Elijah), Op.70 - oratorio (Carus version): Part II'),  # Felix Mendelssohn
    ('For He shall give his angels (Elijah, Op 70)', 'Denn er hat seinen Engeln befohlen'),  # Felix Mendelssohn
    ('For He shall give his angels - from Elijah (Op.70)', 'Denn er hat seinen Engeln befohlen'),  # Felix Mendelssohn
    ('3 Psalms for soloists and double chorus (Op.78)', 'Three Psalms, Op 78'),  # Felix Mendelssohn
    ('Three Psalms (Op.78): Warum toben die Heiden [Why do the nations conspire] [Ps.2]; Richte mich, Gott [Grant me justice, God] [Ps.43]; Mein Gott, warum hast du mich verlassen [My God, my God, why have you abandoned me?] [Ps.22]',
     'Three Psalms, Op 78'),  # Felix Mendelssohn
    ('Richte mich Gott (Psalm 43) from 3 Psalms (Op 78)', 'Richte mich, Gott, Op 78 no 2'),  # Felix Mendelssohn
    ('Psalm 22: My God, my God, why hast thou forsaken me? (3 Psalms for soloists and double chorus, Op 78 No 3)',
     'Psalm 22, Op 78 No 3'),  # Felix Mendelssohn
    ('Excerpts from Four Pieces for Spring Quartet, Op 81',
     "Excerpts from 'Four Pieces for String Quartet, Op 81'"),  # Felix Mendelssohn
    ('Symphony No 4 in A, Op 90', "Symphony no 4 in A major, Op 90 'Italian'"),  # Felix Mendelssohn
    ('Infelice - concert aria, Op. 94', 'Infelice - concert aria Op. 94 for soprano and orchestra'),  # Felix Mendelssohn
    ('Ruy Blas, Op 95', 'Ruy Blas (overture), Op 95'),  # Felix Mendelssohn
    ('Songs Without Words (Op.6) (1846) - selection', 'Excerpts from Songs Without Words, Op 6 (1846)'),  # Fanny Mendelssohn
    ('Songs Without Words (Op.6) (1846) - selections', 'Excerpts from Songs Without Words, Op 6 (1846)'),  # Fanny Mendelssohn
    ('Excerpts from Songs Without Words, Op 6 (1846): 1. Andante espressivo; 3. Andante cantabile; 4. Il saltarello Romano: Allegro molto',
     'Excerpts from Songs Without Words, Op 6 (1846)'),  # Fanny Mendelssohn
    ('Excerpts from Songs Without Words, Op 6 (1846): No 1 (Andante espressivo); No 3 Andante cantabile; No 4 Il saltarello Romano: Allegro molto',
     'Excerpts from Songs Without Words, Op 6 (1846)'),  # Fanny Mendelssohn
    ('Songs Without Words Op.6 (1846): No.1 (Andante espressivo); No.3 (Andante cantabile); No.4 (Il saltarello Romano: Allegro molto)',
     'Excerpts from Songs Without Words, Op 6 (1846)'),  # Fanny Mendelssohn
    ('Songs Without Words (Op.6) - selection (1846) (Andante espressivo; Andante cantabile; Il saltarello Romano: Allegro molto)',
     'Excerpts from Songs Without Words, Op 6 (1846)'),  # Fanny Mendelssohn
    ('Songs Without Words (Op.6) (1846) Sylviane Deferne (piano)', 'Songs Without Words (Op.6) (1846)'),  # Fanny Mendelssohn
    ('Songs Without Words (Op.6) (1846) - Il saltarello Romano', 'Il salterello romano, Op 6 No 4'),  # Fanny Mendelssohn
    ('Lied (Lenau), Wanderlied (Op.8 Nos.3 & 4)', 'Lied (Lenau): Larghetto; Wanderlied: Presto Op 8 Nos 3 & 4'),  # Fanny Mendelssohn
    ('Larghetto; Presto (Lieder ohne Worte, Op 8 Nos 3, 4)',
     'Lied (Lenau): Larghetto; Wanderlied: Presto Op 8 Nos 3 & 4'),  # Fanny Mendelssohn
    ('Lied & Wanderlied (Op.8 Nos.3 & 4)', 'Lied (Lenau): Larghetto; Wanderlied: Presto Op 8 Nos 3 & 4'),  # Fanny Mendelssohn
    ('Lied (Lenau) and Wanderlied, Op 8 Nos 3 & 4',
     'Lied (Lenau): Larghetto; Wanderlied: Presto Op 8 Nos 3 & 4'),  # Fanny Mendelssohn
    # The Op 8 pairing + Songs Without Words Op 6 COMBO listing (one longer
    # programme segment, two phrasings keyed apart by Lenau/'and' tokens);
    # unified with itself, deliberately split from the plain Op 8 pairing.
    ('Lied: Larghetto; Wanderlied: Presto, Op 8 Nos 3 and 4; Songs Without Words, Op 6',
     'Lied (Lenau): Larghetto; Wanderlied: Presto, Op 8 Nos 3, 4 (1840); Songs Without Words, Op 6 (1846)'),  # Fanny Mendelssohn
    # --- Mendelssohn sweep batch 2 (2026-07-05): bare-title / no-opus
    # stragglers from the ranking tail-check. The string symphonies (MWV
    # juvenilia, opus-less so probe-blind) consolidate per number — incl. the
    # 'No 1 in B minor' mislabel (B minor is unique among them; No 1 is C) and
    # the No 9 C-minor/C-major key squabble (folded on the number); Hora est
    # folds to its existing bare final; Hear My Prayer/Hör mein Bitten unify
    # (composer's own orchestration); the Wedding March MOVEMENT group (plain
    # excerpt + literal piano arr) stays split from the Liszt WM&ED paraphrase;
    # 'Spinning Song, Op 64 No 4' = the Op 67/4 Spinnerlied (Op 64 is the
    # Violin Concerto). NOT folded: the 1822 violin-only D-minor concerto vs
    # the 1823 violin+piano double (distinct works); 'Venetian Gondola Song'
    # (ambiguous among the three); bare 'Lieder ohne Worte' (ambiguous book).
    ('String Symphony No 10 in B minor', 'Symphony for string orchestra in B minor, No.10'),  # Felix Mendelssohn
    ('Symphony for Strings No. 10 in B minor', 'Symphony for string orchestra in B minor, No.10'),  # Felix Mendelssohn
    ('Symphony for strings No 10 in B minor, MWV10', 'Symphony for string orchestra in B minor, No.10'),  # Felix Mendelssohn
    ('Symphony for string orchestra in B minor', 'Symphony for string orchestra in B minor, No.10'),  # Felix Mendelssohn
    ('Symphony No 1 in B minor for string orchestra', 'Symphony for string orchestra in B minor, No.10'),  # Felix Mendelssohn
    ('Symphony for Strings no 9 in C minor', 'String Symphony No 9 in C minor'),  # Felix Mendelssohn
    ('Symphony for string orchestra no. 9 in C', 'String Symphony No 9 in C minor'),  # Felix Mendelssohn
    ('Symphony for string orchestra no.8 in D major', 'String Symphony No 8 in D'),  # Felix Mendelssohn
    ('Symphony for strings No.8 in D', 'String Symphony No 8 in D'),  # Felix Mendelssohn
    ('Hora est for chorus and organ', 'Hora est'),  # Felix Mendelssohn
    ('Hora est for chorus and organ (antiphon and responsorium)', 'Hora est'),  # Felix Mendelssohn
    ('Hear my prayer', 'Hear my prayer - hymn, arr. for soprano, chorus & orchestra'),  # Felix Mendelssohn
    ('Hor mein Bitten (Hear My Prayer), Op posth',
     'Hear my prayer - hymn, arr. for soprano, chorus & orchestra'),  # Felix Mendelssohn
    ('Hör mein Bitten (Hear my Prayer)', 'Hear my prayer - hymn, arr. for soprano, chorus & orchestra'),  # Felix Mendelssohn
    ("Wedding March, from 'A Midsummer Night's Dream'",
     "Wedding March (A Midsummer Night's Dream - Incidental Music)"),  # Felix Mendelssohn
    ("Wedding March (A Midsummer Night's Dream) arr for piano",
     "Wedding March (A Midsummer Night's Dream - Incidental Music)"),  # Felix Mendelssohn
    ('Hark the Herald Angels Sing', 'Hark! the Herald Angels Sing'),  # Felix Mendelssohn
    ('Denn er hat seinen Engeln befohlen (from Elijah)', 'Denn er hat seinen Engeln befohlen'),  # Felix Mendelssohn
    ("Denn er hat seinen Engeln befohlen, from 'Elias' (Elijah)", 'Denn er hat seinen Engeln befohlen'),  # Felix Mendelssohn
    ('Spinning Song, Op 64 No 4', "Spinning Song, op. 67/4, from 'Songs without Words'"),  # Felix Mendelssohn
    ('Concerto for violin, piano and orchestra in D minor',
     'Concerto for violin, piano and string orchestra in D minor'),  # Felix Mendelssohn
    ('Symphony No 3 in A minor', "Symphony no 3 in A minor, Op 56 'Scottish'"),  # Felix Mendelssohn
    ("Symphony No.5 in D major, 'Reformation'", 'Symphony No.5 in D major Op.107 "Reformation"'),  # Felix Mendelssohn
    ('3 Psalms', 'Three Psalms, Op 78'),  # Felix Mendelssohn
    ('Trio for piano and strings no. 1', 'Piano Trio No 1 in D minor, Op 49'),  # Felix Mendelssohn
    ('Three Etudes', '3 Studies for piano, Op 104b'),  # Felix Mendelssohn
    ('Rondo capriccioso in E major/minor', 'Rondo capriccioso in E major/minor, Op 14'),  # Felix Mendelssohn
    ('Die schöne Melusine - overture', 'Die schöne Melusine - overture (Op.32)'),  # Felix Mendelssohn
    ('Spring Song (Fruhlingslied)', 'Spring Song (Fruhlingslied) in A major (Op.62 No.6)'),  # Felix Mendelssohn
    # --- Dvořák opus-set sweep (2026-07-05): 91 folds over the 38 post-gate
    # fragmented signatures (scratch/dvorak_post.txt) + the tail-check
    # stragglers — B-numbers (Burghauser) are not in _CATALOGUE_RE, so the
    # Klid B.182 family (one work, 9 keys, ~86 airings) and the Prague
    # Waltzes B.99 family were probe-blind. Notable calls: Songs My Mother
    # Taught Me (Op 55/4) unified across German/Czech/English phrasings (7
    # keys); the Op 72 no 1 dance unified across its dual numbering (No 9)
    # AND the pervasive 'B minor' mislabel (the dance is B major); Notturno/
    # Nocturne Op 40 translation twin folded (the project's namesake);
    # own-orchestration ('orch. composer') spellings fold throughout per the
    # transcription-depth policy; six pre-existing pairs were retargeted to
    # the new mains (46 3&8 pair, Kdyz→Als die alte Mutter, No.9-B-minor,
    # Sym 8 B.163, In Nature's Realm Op 91, Othello). Left split: Czech
    # Suite movements vs whole; the Op 72 2&7 pair vs the 9-12 four vs the
    # series-2 whole; movement excerpts vs wholes throughout; Cavatina
    # (Miniatures Op 75a = a different work); 'Slavonic Dance No. 15'
    # (internally consistent); ambiguous 1x 'Furiant (No.7)' / 'Allegro
    # moderato' / 'Fuga in G flat major'.
    ('Quartet No 13 in G major Op 106', 'String Quartet No 13 in G, op 106'),  # Antonin Dvorak
    ('Quartet no 11 in C major, Op 61', 'String Quartet no.11 in C major, Op.61'),  # Antonin Dvorak
    ('The Golden Spinning Wheel, Op 109',
     'The Golden spinning-wheel (Zlaty kolovrat) - symphonic poem, Op 109'),  # Antonin Dvorak
    ('Zlaty kolovrat, Op 109', 'The Golden spinning-wheel (Zlaty kolovrat) - symphonic poem, Op 109'),  # Antonin Dvorak
    ('The Golden Spinning Wheel', 'The Golden spinning-wheel (Zlaty kolovrat) - symphonic poem, Op 109'),  # Antonin Dvorak
    ('Romance in F minor Op.11 vers. for violin and orch.',
     'Romance Op 11 in F minor vers. for violin and piano'),  # Antonin Dvorak
    ('Romance in F, Op 11 - vers. for violin and piano', 'Romance Op 11 in F minor vers. for violin and piano'),  # Antonin Dvorak
    ('A Hero’s Song, Op. 111 symphonic poem', 'Heroic Song - symphonic poem, Op.111'),  # Antonin Dvorak
    ('Song to the Moon (Rusalka, Op 114)', 'Song to the Moon from Rusalka, Op 114'),  # Antonin Dvorak
    ('Serenade for string orchestra (Op.22) in E major', 'Serenade for strings in E major, Op.22'),  # Antonin Dvorak
    ('Nocturne in B major (Op.40)', 'Notturno in B major, Op 40'),  # Antonin Dvorak
    ('Slavonic Dance in E minor,Op 46 No 2', 'Slavonic Dance in E minor (Op.46 No.2)'),  # Antonin Dvorak
    ('Slavonic dance (Op.46 No.2) (B.171) in E minor', 'Slavonic Dance in E minor (Op.46 No.2)'),  # Antonin Dvorak
    ('Slavonic Dance in A flat major, Op.46 No. 3',
     'Slavonic dance Op.46 No. 3 in A flat major, orch. composer'),  # Antonin Dvorak
    ('Slavonic Dances, Op.46 (No. 8 In G minor: Presto; No.3 In A flat major: Poco Allegro)',
     'Two Slavonic Dances, Op 46 - no 8 in G minor and no 3 in A flat major'),  # Antonin Dvorak
    ('Two Slavonic Dances (Op.46) - No. 8 In G Minor: Presto & No.3 In A flat Major',
     'Two Slavonic Dances, Op 46 - no 8 in G minor and no 3 in A flat major'),  # Antonin Dvorak
    ('Two Slavonic Dances (Op.46) - No. 8 and No.3',
     'Two Slavonic Dances, Op 46 - no 8 in G minor and no 3 in A flat major'),  # Antonin Dvorak
    ('Two Slavonic Dances, Op 46: No 8 in G minor; No 3 in A flat',
     'Two Slavonic Dances, Op 46 - no 8 in G minor and no 3 in A flat major'),  # Antonin Dvorak
    # The truncated corpus title that was the OLD final for this pair group
    # (retargeted 2026-07-05); its own key needs the fold too.
    ('Slavonic Dance G minor, Op.46 No.8', 'Slavonic Dance No. 8 in G minor, op. 46'),  # Antonin Dvorak
    ('Violin Concerto in A minor, Op 53', 'Violin Concerto in A minor, B108, Op 53'),  # Antonin Dvorak
    ('Violin Concerto in A minor', 'Violin Concerto in A minor, B108, Op 53'),  # Antonin Dvorak
    ('Als die alte Mutter - No.4 from Ciganske melodie (Op.55)',
     'no.4 Als die alte Mutter [songs my mother taught me]'),  # Antonin Dvorak
    ('Kdyz men stara matka zpivat [songs my mother taught], from Ciganske melodie [Gypsy melodies] Op.55 No.4',
     'no.4 Als die alte Mutter [songs my mother taught me]'),  # Antonin Dvorak
    ('Kdyz men stara matka zpivat , from Ciganske melodie',
     'no.4 Als die alte Mutter [songs my mother taught me]'),  # Antonin Dvorak
    ('No.4 Als die alte Mutter from Ciganske melodie [Gypsy melodies] (Op.55)',
     'no.4 Als die alte Mutter [songs my mother taught me]'),  # Antonin Dvorak
    ('Songs my mother taught me; no.4 Als die alte Mutter from Ciganske melodie (Op.55)',
     'no.4 Als die alte Mutter [songs my mother taught me]'),  # Antonin Dvorak
    ('Legend No.1 in D minor (Op.59) (Allegretto)', 'Legend No.1 in D minor (Op.59)'),  # Antonin Dvorak
    ('Legend No.4 in C major (Molto maestoso) - from Legends (Op.59) orch. composer',
     'Legend in C major, Op 59 no 4'),  # Antonin Dvorak
    ('Legends, Op 59 (No 4 in C)', 'Legend in C major, Op 59 no 4'),  # Antonin Dvorak
    ('Legend No 4 in C (Legends, Op 59)', 'Legend in C major, Op 59 no 4'),  # Antonin Dvorak
    ('Legend No.4 in C major (Molto maestoso) - from Legends (Op.59)', 'Legend in C major, Op 59 no 4'),  # Antonin Dvorak
    ('Legend No.4 in C major (from Legends (Op.59), orch. composer)', 'Legend in C major, Op 59 no 4'),  # Antonin Dvorak
    ('Legends, Op 59 (No 4)', 'Legend in C major, Op 59 no 4'),  # Antonin Dvorak
    ('Legend No.4 in C major', 'Legend in C major, Op 59 no 4'),  # Antonin Dvorak
    ('Overture Domov muj  Op 62', 'My Home Land, Overture Op 62'),  # Antonin Dvorak
    ('Overture Domov muj (My Homeland), Op 62', 'My Home Land, Overture Op 62'),  # Antonin Dvorak
    ('My Home Land, Op 62', 'My Home Land, Overture Op 62'),  # Antonin Dvorak
    ('Overture Domov muj (My Homeland)(Op.62)', 'My Home Land, Overture Op 62'),  # Antonin Dvorak
    ('V Pirorode (Op.63)', "V prirode (In Nature's Realm), Op 63"),  # Antonin Dvorak
    ('V Pirorode (Songs of Nature), Op.63', "V prirode (In Nature's Realm), Op 63"),  # Antonin Dvorak
    ("V Pirorode (In Nature's Realm) (Op.63)", "V prirode (In Nature's Realm), Op 63"),  # Antonin Dvorak
    ('Slavonic Dances Nos 9-12, Op 72, Nos 1-4', 'Slavonic Dances Nos 9 -12, Op 72'),  # Antonin Dvorak
    ('Slavonic Dances (Op.72 No.1-4)', 'Slavonic Dances Nos 9 -12, Op 72'),  # Antonin Dvorak
    ('Slavonic dances - series 2 Op.72, orch. composer [orig. pf duet]', 'Slavonic dances - series 2 Op.72'),  # Antonin Dvorak
    ('Slavonic Dance No.9 in B minor (Op.72 No.1) orch. composer',
     'Slavonic Dance No.9 in B major (Op.72 No.1) orch. composer [orig. pf duet]'),  # Antonin Dvorak
    ('Slavonic Dance No.9 in B major (Op.72 No.1)',
     'Slavonic Dance No.9 in B major (Op.72 No.1) orch. composer [orig. pf duet]'),  # Antonin Dvorak
    ('Slavonic Dance no 1 in B major, Op 72',
     'Slavonic Dance No.9 in B major (Op.72 No.1) orch. composer [orig. pf duet]'),  # Antonin Dvorak
    ('Slavonic dances (Op.72, No.2) in E minor', 'Slavonic Dance in E minor, Op 72 no 2'),  # Antonin Dvorak
    ('In Folk Tone op. 73', 'V národnim tónu op. 73 (In Folk Tone)'),  # Antonin Dvorak
    ('V národnim tónu (In Folk Tone), Four Songs Op. 73', 'V národnim tónu op. 73 (In Folk Tone)'),  # Antonin Dvorak
    ('4 Romantic Pieces Op.75 for violin and piano', '4 Romantic pieces Op.75'),  # Antonin Dvorak
    ('Allegro appassionato (4 Romantic Pieces for violin and piano, Op 75)',
     'Allegro appassionato (4 Romantic pieces, Op 75)'),  # Antonin Dvorak
    ('Allegro moderato; Allegro appassionato (Four Romantic pieces for violin and piano, Op 75, Nos 1 and 3)',
     'Allegro moderato & Allegro appassionato from 4 Romantic pieces for violin & piano (Op.75 Nos.1 & 3)'),  # Antonin Dvorak
    ('Piano Quintet in A major (B.155) (Op.81) (Allegro ma non tanto; Dumka ; Scherzo ; Allegro)',
     'Piano Quintet in A major, Op 81'),  # Antonin Dvorak
    ('Scherzo furiant (molto vivace) from Piano Quintet no.2 Op.81',
     'Scherzo furiant (molto vivace) from Piano Quintet no.2 in A major Op.81'),  # Antonin Dvorak
    ('Piano Quintet No 2 in A major, Op 81 (Scherzo furiant)',
     'Scherzo furiant (molto vivace) from Piano Quintet no.2 in A major Op.81'),  # Antonin Dvorak
    ('Bacchanalia (Poeticke nalady - No 10, Op 85)', 'Bacchanalia (no 10 from Poeticke nalady)'),  # Antonin Dvorak
    ('Bacchanalia, Op 85 No 10', 'Bacchanalia (no 10 from Poeticke nalady)'),  # Antonin Dvorak
    ('Symphony No. 8 in G major, Op. 88, B. 163', 'Symphony No.8 in G major (Op.88)'),  # Antonin Dvorak
    ('Lento maestoso in C minor (Trio No 4 for piano and strings, Op 90 - Dumky)',
     "Lento maestoso, from 'Piano Trio no 4 in E minor, Op 90 'Dumky'"),  # Antonin Dvorak
    ('Lento maestoso in C minor from Trio for piano and strings no. 4 (Op.90)',
     "Lento maestoso, from 'Piano Trio no 4 in E minor, Op 90 'Dumky'"),  # Antonin Dvorak
    ('V prirode (Op.91)', "In Nature's Realm (Overture), Op 91"),  # Antonin Dvorak
    ("In Nature's Realm (Overture)", "In Nature's Realm (Overture), Op 91"),  # Antonin Dvorak
    ("In Nature's Realm (V prirode) - overture (Op.91)", "In Nature's Realm (Overture), Op 91"),  # Antonin Dvorak
    ('Othello (Overture)', 'Othello - concert overture (Op.93)'),  # Antonin Dvorak
    ('Othello, Op.93', 'Othello - concert overture (Op.93)'),  # Antonin Dvorak
    ("Overture to 'Othello', Op. 93", 'Othello - concert overture (Op.93)'),  # Antonin Dvorak
    ('Rondo for cello and orchestra (Op.94)', 'Rondo in G minor Op 94'),  # Antonin Dvorak
    ('Symphony no. 9 (Op. 95) ‘From the New World’', "Symphony no 9 in E minor, Op 95 'From the New World'"),  # Antonin Dvorak
    ('Symphony no. 9 in E minor Op.95', "Symphony no 9 in E minor, Op 95 'From the New World'"),  # Antonin Dvorak
    ('String Quartet No 12 in F, Op 96', "String Quartet no 12 in F major, Op 96, 'American'"),  # Antonin Dvorak
    ('String Quartet No 12 in F (American)', "String Quartet no 12 in F major, Op 96, 'American'"),  # Antonin Dvorak
    ('Quintet in E flat major Op.97 for strings', "String Quintet in E flat major, Op 97 'American'"),  # Antonin Dvorak
    ('Suite for orchestra in A major (Op.98b)', 'Suite in A major, Op 98b'),  # Antonin Dvorak
    ("Klid for cello and orchestra (B.182) arr. from no.5 of 'From the Bohemian forest'",
     'Klid (Silent woods), B182'),  # Antonin Dvorak
    ('Klid , B182', 'Klid (Silent woods), B182'),  # Antonin Dvorak
    ('Klid (Silent Woods) for cello and orchestra (B.182)', 'Klid (Silent woods), B182'),  # Antonin Dvorak
    ('Silent Woods/Klid (Lento e molto cantabile)', 'Klid (Silent woods), B182'),  # Antonin Dvorak
    ('Klid (Slent Woods), B182', 'Klid (Silent woods), B182'),  # Antonin Dvorak
    ("Klid (Silent Woods), arr for cello and orchestra (B.182) from no.5 of 'From the Bohemian Forest'",
     'Klid (Silent woods), B182'),  # Antonin Dvorak
    ('Silent Woods', 'Klid (Silent woods), B182'),  # Antonin Dvorak
    ('Silent woods for cello and orchestra, B182 (arr from No 5 of From the Bohemian Forest)',
     'Klid (Silent woods), B182'),  # Antonin Dvorak
    ('Prague Waltzes B.99', 'Prague Waltzes'),  # Antonin Dvorak
    ('Prague Waltzes (Prazske valciky)', 'Prague Waltzes'),  # Antonin Dvorak
    ('Scherzo Capriccioso', 'Scherzo capriccioso (Op.66)'),  # Antonin Dvorak
    ('Carnival Overture', 'Carnival overture (Op.92)'),  # Antonin Dvorak
    ('Serenade in D minor', 'Wind Serenade in D minor, Op 44'),  # Antonin Dvorak
    ('Overture (The King and the Charcoal Burner)',
     'Overture: The King and the Charcoal Burner (Kral a Uhlir) - 1874'),  # Antonin Dvorak
    ('Overture - King and the Charcoal Burner',
     'Overture: The King and the Charcoal Burner (Kral a Uhlir) - 1874'),  # Antonin Dvorak
    ('Slavonic Dances: No 2 in E minor (Dumka) and No 8 in G minor (Furiant)',
     "Excerpts from 'Slavonic Dances' - No. 2 in E minor ('Dumka') & No. 8 in G minor ('Furiant')"),  # Antonin Dvorak
    # --- Grieg opus-set sweep (2026-07-05): 59 folds over the 29 post-gate
    # fragmented signatures (scratch/grieg_post.txt). Notable calls: the
    # Op 74 choral fragmentation (13 keys — psalm titles in Norwegian and
    # English, Salmer/Psalms/Hymns garnish) consolidated per psalm/pairing;
    # the Op 35/1 Norwegian Dance under 8 duet/four-hands/from-set keys;
    # Gammelnorsk Op 51 (own orchestration of the 2-piano original, 5 keys);
    # 'Walz' typo twin of the Op 12/38 recital selection; five pre-existing
    # pairs retargeted (Symphonic Dance 4, Slåtter 3-pieces x2, Hvad est du
    # dog skiøn, Gammelnorsk). Kept split: Peer Gynt Op 23 excerpts vs the
    # Op 46/55 suite-cited excerpts and the Op 33/2 song vs the Op 34
    # Elegiac-cited Last Spring (citation convention: excerpts key by their
    # cited source); the Karr/Horovitz double-bass CONCERTO vs the Op 36
    # cello sonata (re-genred arrangement by other hands; its 2 keys unify);
    # whole sets vs selections (Op 35, Op 54 Lyric Suite, Op 72, Op 74).
    ('In Autumn, Op 11', 'In Autumn - concert overture, Op 11'),  # Edvard Grieg
    ('Selected Lyric Pieces - Walz (Op.12 No.2); Norwegian Melody (Op.12 No.6); Folk song (Op.12 No.5); Canon (Op.38 No.8); Elegy (Op.38 No.6); Waltz (Op.38 No.7); Melody (Op.38 No.3)',
     'Selected Lyric Pieces - Waltz (Op.12 No.2); Norwegian Melody (Op.12 No.6); Folk song (Op.12 No.5); Canon (Op.38 No.8); Elegy (Op.38 No.6); Waltz (Op.38 No.7); Melody (Op.38 No.3)'),  # Edvard Grieg
    ('Concerto In A Minor Op.16', 'Piano Concerto in A minor, Op 16'),  # Edvard Grieg
    ('Piano Concerto, Op.16', 'Piano Concerto in A minor, Op 16'),  # Edvard Grieg
    ('Norwegian Bridal march - from Pictures from country life for piano (Op.19 No.2)',
     'Norwegian Bridal march from Pictures from country Life(Op.19 No.2)'),  # Edvard Grieg
    ('Norwegian Bridal march (Pictures from Country Life, Op 19, No 2)',
     'Norwegian Bridal march from Pictures from country Life(Op.19 No.2)'),  # Edvard Grieg
    ('Norwegian Bridal march - from Pictures from country life (Folkelivsbilleder) for piano (Op.19 No.2)',
     'Norwegian Bridal march from Pictures from country Life(Op.19 No.2)'),  # Edvard Grieg
    ("Solveig's Song (Peer Gynt, Op 23)", "Solveig's Song from 'Peer Gynt', Op 23 arr. for oboe and piano"),  # Edvard Grieg
    ("Prelude to Act 1 of 'Peer Gynt, Op 23'", "Prelude, 'At the Wedding', from Act I of 'Peer Gynt, Op 23'"),  # Edvard Grieg
    ('Six Orchestral songs (Nos 1-5)', '6 Orchestral songs (nos 1-5 only) (EG.177)'),  # Edvard Grieg
    ('Letzter Frühling (Last Spring, orig. song Op.33/2)', 'Last Spring, Op 33 no 2'),  # Edvard Grieg
    ('Last Spring (Letzter Fruhling),  Op 33, No 2', 'Last Spring, Op 33 no 2'),  # Edvard Grieg
    ('Last Spring, orig song, Op 33, No 2', 'Last Spring, Op 33 no 2'),  # Edvard Grieg
    ('Two Elegiac melodies, Op 34', '2 Elegiac melodies for string orchestra, Op 34'),  # Edvard Grieg
    ('Last Spring (from 2 Elegiac Melodies, Op.34)', "The Last Spring, from 'Two Elegiac Melodies, Op 34'"),  # Edvard Grieg
    ('2 Norwegian Dances, Op 35 nos 1 & 2 [orchestral version]', '2 Norwegian Dances (Op.35, nos. 1 & 2)'),  # Edvard Grieg
    ('4 Norwegian dances (Op.35) orch. Hans Sitt', '4 Norwegian dances, Op 35 [orig. for piano duet]'),  # Edvard Grieg
    ('Norwegian Dance No.1 (Allegro marcato) from 4 Norwegian Dances for Piano Duet (Op.35)',
     'Norwegian Dance (Allegro marcato) (Op.35 No.1)'),  # Edvard Grieg
    ('Norwegian Dance No.1 from 4 Norwegian Dances for Piano Duet (Op.35)',
     'Norwegian Dance (Allegro marcato) (Op.35 No.1)'),  # Edvard Grieg
    ('Four Norwegian Dances for piano duet, Op 35 (No 1) (arr. for orchestra)',
     'Norwegian Dance (Allegro marcato) (Op.35 No.1)'),  # Edvard Grieg
    ('Norwegian Dance No 1 (4 Norwegian Dances for Piano Duet, Op 35)',
     'Norwegian Dance (Allegro marcato) (Op.35 No.1)'),  # Edvard Grieg
    ('Norwegian Dance No 1, Op 35 (for four hands)', 'Norwegian Dance (Allegro marcato) (Op.35 No.1)'),  # Edvard Grieg
    ('Norwegian Dance No 1, Op 35 for four-handed piano', 'Norwegian Dance (Allegro marcato) (Op.35 No.1)'),  # Edvard Grieg
    ('Norwegian Dance No.1 (Op.35) for piano four hands', 'Norwegian Dance (Allegro marcato) (Op.35 No.1)'),  # Edvard Grieg
    ('Sonata in A minor Op.36', 'Cello Sonata in A minor, Op 36'),  # Edvard Grieg
    ("Concerto for double bass and orchestra [transcribed by Gary Karr, orchestrated by Joseph Horovitz after Grieg's cello sonata] (Op.36)",
     'Concerto for double bass and orchestra (Op.36)'),  # Edvard Grieg
    ('Sommerfugl - from Lyric pieces, book 3 for piano (Op.43 No.1)',
     'Sommerfugl [Butterfly] from Lyric pieces, book 3 for piano (Op.43 No.1)'),  # Edvard Grieg
    ('3 Lyric Pieces: Erotik (Love Poem), Op.43/5; Troldtog (March of the Trolls), Op.54/3; Nocturne (Notturno), Op.54/4',
     '3 Lyric Pieces (Op 43 no 5, Op 54 no 3, Op 54 no 4)'),  # Edvard Grieg
    ('Violin Sonata No.3 in C minor (Op.45), version for viola', 'Violin Sonata no 3 in C minor, Op 45'),  # Edvard Grieg
    ("Aase's Death - from Peer Gynt Suite No.1, Op.46 (arr. for harps)",
     "Aase's Death (excerpt Peer Gynt suite No 1, Op 46)"),  # Edvard Grieg
    ('I Love Thee, No 3 from Hjertets melodier, Op 5',
     "I Love Thee - no.3 from Hjertets melodier (The heart's melodies) (Op.5)"),  # Edvard Grieg
    ('Gammelnorsk Romance met Variasjoner (Old Norwegian Romance with Variations) - orig. for 2 pianos arr for orchestra (Op.51) (1890)',
     'Gammelnorsk Romance met Variasjoner, Op 51'),  # Edvard Grieg
    ('Gammelnorsk Romance met Variasjoner (Op.51) (1890, orch 1900)',
     'Gammelnorsk Romance met Variasjoner, Op 51'),  # Edvard Grieg
    ('Gammelnorsk Romance met Variasjoner - orig for 2 pianos arr for orchestra (Op.51)',
     'Gammelnorsk Romance met Variasjoner, Op 51'),  # Edvard Grieg
    ('Old Norwegian Romance with Variations, Op 51', 'Gammelnorsk Romance met Variasjoner, Op 51'),  # Edvard Grieg
    ('Lyric pieces (Op.54): Nos. 2, 4, 3', 'Lyric pieces - book 5 for piano, Op 54: Nos 2, 3. 4'),  # Edvard Grieg
    ('Lyric pieces - book 5 for piano (Op.54): Nos 2, 4, 3 ?',
     'Lyric pieces - book 5 for piano, Op 54: Nos 2, 3. 4'),  # Edvard Grieg
    ('Lyric suite \x96 arr. for orchestra from Lyric Pieces (Book 5) for piano, Op.54',
     'Lyric suite for orchestra from Lyric Pieces (Book 5)'),  # Edvard Grieg
    ('Selected Lyric Pieces – March of the Trolls (Op.54 No.3)',
     'Troldtog (March of the Dwarfs) - from Lyric Pieces Book'),  # Edvard Grieg
    ('Notturno, Op 54 no 4', 'Nocturne in C from Lyric Suite, Op.54 No. 4'),  # Edvard Grieg
    ('Symphonic Dance No 2, Op 64', 'Symphonic dance no 2 (Allegro grazioso) Op 64 no 2'),  # Edvard Grieg
    ('Symphonic Dance No 2, Op 64 (Allegro grazioso)', 'Symphonic dance no 2 (Allegro grazioso) Op 64 no 2'),  # Edvard Grieg
    ('Evening in the Mountains, Op 68 No 4; At the cradle, Op 68 No 5',
     'Evening in the Mountains, Op 68 no 4; At the cradle, Op 68 no 5 [Lyric Pieces]'),  # Edvard Grieg
    ('Sonata (Op.7) in E minor', 'Piano Sonata in E minor, Op 7'),  # Edvard Grieg
    ('Slatter Op.72 for piano', 'Slatter, Op 72 (Norwegian peasant dances)'),  # Edvard Grieg
    ('3 Pieces from Norwegian Peasant Dances, Op.72',
     '3 Pieces from Slatter (Norwegian Peasant Dances), Op 72'),  # Edvard Grieg
    ("3 Pieces from Norwegian Peasant Dances, Op 72: The Goblins' Wedding Procession at Vossevangen; Wedding march after the Miller's boy; Jon Vestafe's springar",
     '3 Pieces from Slatter (Norwegian Peasant Dances), Op 72'),  # Edvard Grieg
    ('Three Pieces (Slatter - Norwegian Peasant Dances), Op 72',
     '3 Pieces from Slatter (Norwegian Peasant Dances), Op 72'),  # Edvard Grieg
    ('From 4 Psalms for baritone and mixed voices (Op.74)',
     '4 Psalms for baritone and mixed voices, Op 74 (excerpts)'),  # Edvard Grieg
    ("Excerpts from 'Fire Salmer, Op. 74'", '4 Psalms for baritone and mixed voices, Op 74 (excerpts)'),  # Edvard Grieg
    ('Jesus Kristus er opfaren & I himmelen, i himmelen from 4 Psalms for baritone and mixed voices (Op.74)',
     "Jesus Kristus er opfaren' & 'I himmelen, i himmelen' - from 4 Psalms for baritone and mixed voices (Op.74 Nos.3&4)"),  # Edvard Grieg
    ('Jesus Kristus er opfaren (Jesus Christ is risen); I himmelen, i himmelen (In heaven) (Four Psalms for baritone and mixed voices, Op 74 Nos 3 and 4)',
     "Jesus Kristus er opfaren' & 'I himmelen, i himmelen' - from 4 Psalms for baritone and mixed voices (Op.74 Nos.3&4)"),  # Edvard Grieg
    ("Jesus Kristus er opfaren' (Jesus Christ is risen); I himmelen, i himmelen (In heaven) (Four Psalms for baritone and mixed voices, Op 74 Nos 3, 4)",
     "Jesus Kristus er opfaren' & 'I himmelen, i himmelen' - from 4 Psalms for baritone and mixed voices (Op.74 Nos.3&4)"),  # Edvard Grieg
    ("Jesus Kristus er opfaren, from 'Four Psalms (Hymns), (Op. 74)",
     "Jesus Kristus er opfaren, from 'Four Salmer (Hymns), Op 74"),  # Edvard Grieg
    ('Hvad est du dog skiøn , No.1 from Four Salmer Op.74', 'How fair thou art from Four Hymns Op. 74'),  # Edvard Grieg
    ('How fair thou art (Four Hymns), Op 74 No 1', 'How fair thou art from Four Hymns Op. 74'),  # Edvard Grieg
    ("Hvad est du dog skiøn (How fair thou art) , from 'Four Salmer (Hymns), Op 74/1",
     'How fair thou art from Four Hymns Op. 74'),  # Edvard Grieg
    ('How Fair is Thy Face (Four Psalms, Op 74 No 1)', 'How fair thou art from Four Hymns Op. 74'),  # Edvard Grieg
    ('Hvad est du dog skiøn [How fair thou art], No.1  from 4 Salmer Op.74',
     'How fair thou art from Four Hymns Op. 74'),  # Edvard Grieg
    # --- Grieg sweep batch 2 (2026-07-05): tail-check stragglers. The EG.177
    # orchestral-songs set consolidates (EG numbers are probe-blind); the
    # 30-airing bare segment key of the Op 35/1 dance folds; Peer Gynt
    # excerpt strays join their only existing groups; Våren = the Norwegian
    # title of Last Spring Op 33/2; unspecified Lyric-Pieces selections
    # unify as one content class. Left split: bare '3 Pieces' (its 414s
    # recording differs from the 504s Slåtter one — unknown content);
    # single-key songs; specific Lyric-Pieces selections.
    ('6 Orchestral songs - nos 1-5, EG.177', '6 Orchestral songs (nos 1-5 only) (EG.177)'),  # Edvard Grieg
    ('From 6 Orchestral songs: Nos 1-5 (EG.177)', '6 Orchestral songs (nos 1-5 only) (EG.177)'),  # Edvard Grieg
    ('Six Orchestral songs (Nos 1-5), EG 177', '6 Orchestral songs (nos 1-5 only) (EG.177)'),  # Edvard Grieg
    ("6 Orchestral songs (Nos 1-5 only) (EG.177): Solveigs sang (Solveig's Song) from Peer Gynt (Op.23); Solveigs vuggevise (Solveig's Cradle Song) from Peer Gynt (Op.23); Fra Monte Pincio (From Monte Pincio) from Romancer (Op.39 No.1); En Svane (A Swan) from 6 songs (Op.25 No.2); Våren (Last Spring) from 12 songs (Op.33 No.2)",
     '6 Orchestral songs (nos 1-5 only) (EG.177)'),  # Edvard Grieg
    ('Norwegian Dance No 1', 'Norwegian Dance (Allegro marcato) (Op.35 No.1)'),  # Edvard Grieg
    ("Morning Mood, from 'Peer Gynt'", "Morning Mood, from 'Peer Gynt, Suite No.1, Op.46'"),  # Edvard Grieg
    ("Aase's Death - from Peer Gynt", "Aase's Death (excerpt Peer Gynt suite No 1, Op 46)"),  # Edvard Grieg
    ("Anitra's dance (from Peer Gynt)", "Anitra's Dance (Peer Gynt Suite no.1, Op.46)"),  # Edvard Grieg
    ("Anitra's Dance from Peer Gynt - suite no. 1 arr. for piano 4 hands",
     "Anitra's Dance (Peer Gynt Suite no.1, Op.46)"),  # Edvard Grieg
    ("Solveig's song (from Peer Gynt)", "Solveig's Song from 'Peer Gynt', Op 23 arr. for oboe and piano"),  # Edvard Grieg
    ("Solveig's Song from 'Peer Gynt Suite'", "Solveig's Song, from 'Peer Gynt, Suite No.2', Op.55"),  # Edvard Grieg
    ('Våren (Last Spring)', 'Last Spring, Op 33 no 2'),  # Edvard Grieg
    ('2 Elegiac melodies for string orchestra (Op.34) (arrangement of Songs Op.33 Nos.2 and 3: No.1 - Den Saerde (The wounded heart) ; No.2 - Varen (Spring) )',
     '2 Elegiac melodies for string orchestra, Op 34'),  # Edvard Grieg
    ('2 Elegiac melodies for string orchestra (Op.34) (arrangement of Songs Op.33 Nos.2 and 3: Den Saerde (The wounded heart); Varen (Spring) )',
     '2 Elegiac melodies for string orchestra, Op 34'),  # Edvard Grieg
    ('String Quartet No 2 in F', 'String Quartet no 2 in F major (unfinished)'),  # Edvard Grieg
    ('Andante con moto in C minor', 'Andante con moto for piano trio in C minor'),  # Edvard Grieg
    ('Two Lyric Pieces: Evening in the Mountains; At the cradle',
     'Evening in the Mountains, Op 68 no 4; At the cradle, Op 68 no 5 [Lyric Pieces]'),  # Edvard Grieg
    ('Symphonic Dance No.2', 'Symphonic dance no 2 (Allegro grazioso) Op 64 no 2'),  # Edvard Grieg
    ('Lyric Pieces (excerpts)', 'Lyric Pieces (selection)'),  # Edvard Grieg
    ('Excerpts from Lyric Pieces', 'Lyric Pieces (selection)'),  # Edvard Grieg
    ("Excerpts from 'Luriske Stykker' ('Lyric Pieces')", 'Lyric Pieces (selection)'),  # Edvard Grieg
    # --- Rachmaninov opus-set sweep (2026-07-05): 44 folds over the 25
    # post-gate fragmented signatures (scratch/rach_post.txt) + the famous
    # opus-less strays: bare 'Vocalise' (28 airings) and the C-sharp-minor
    # Prelude's opus-less keys incl. the segment '[Bells]' nickname gloss
    # (19 airings). Notable calls: the Op 10 '3 Pieces from Morceaux de
    # salon' recording (737s) = Barcarolle/Romance/Humoresque, so the
    # enumerated and (excerpts) phrasings fold there; 'Suite No 1 Op 5' =
    # the Fantaisie-tableaux 2-piano suite; Op 39/9 'D minor' mislabel
    # folded (the étude is D major); Op 40's '[1941-42 version]' = the
    # standard text; Vespers single numbers unify per number (Bogoróditse
    # Dévo = 'Rejoice, O Virgin'). Left split: bare 'Preludes, op 32' vs
    # '(excerpts)' vs the Nos-4&6 pair; Op 37/39 wholes vs selections vs
    # single numbers; movement excerpts vs wholes.
    ('Piano Concerto no.1 in F sharp minor (Op.1) (Vivace - moderato; Andante; Allegro vivace)',
     'Piano Concerto no 1 in F sharp minor, Op 1'),  # Sergey Rachmaninov
    ('Piano Concerto No. 1 in F sharp minor', 'Piano Concerto no 1 in F sharp minor, Op 1'),  # Sergey Rachmaninov
    ("3 pieces from 'Morceaux de Salon', Op.10: Barcarolle; Romance; Humoresque",
     '3 Pieces from Morceaux de salon for piano, Op 10'),  # Sergey Rachmaninov
    ('Barcarolle; Romance; Humoresque (Morceaux de Salon, Op 10)',
     '3 Pieces from Morceaux de salon for piano, Op 10'),  # Sergey Rachmaninov
    ('Morceaux de Salon, Op 10 (excerpts)', '3 Pieces from Morceaux de salon for piano, Op 10'),  # Sergey Rachmaninov
    ('Morceaux de salon for piano, Op 10 (three excerpts)', '3 Pieces from Morceaux de salon for piano, Op 10'),  # Sergey Rachmaninov
    ('Moments musicaux for piano (Op.16)', '6 Moments musicaux, Op 16'),  # Sergey Rachmaninov
    ('Andante from Sonata in G minor Op.19', 'Cello Sonata in G minor Op 19 (Andante)'),  # Sergey Rachmaninov
    ('Prelude No.5 in G minor - from [10] Preludes for piano (Op.23)', 'Prelude in G minor (Op.23 No.5)'),  # Sergey Rachmaninov
    ('Prelude No.5 in G minor - from Preludes for piano (Op.23)', 'Prelude in G minor (Op.23 No.5)'),  # Sergey Rachmaninov
    ('10 Preludes Op.23 for piano - no 5 in G minor', 'Prelude in G minor (Op.23 No.5)'),  # Sergey Rachmaninov
    ('Prelude No.5 in G minor (Op.23/5)', 'Prelude in G minor (Op.23 No.5)'),  # Sergey Rachmaninov
    ('10 Preludes Op.23 for piano; no.6 in E flat major', 'Prelude in E flat, op. 23/6'),  # Sergey Rachmaninov
    ('Symphony No.2 (Op.27) in E', 'Symphony no 2 in E minor, Op 27'),  # Sergey Rachmaninov
    ('Symphony no. 2 in E minor Op.27 (Proms 2015)', 'Symphony no 2 in E minor, Op 27'),  # Sergey Rachmaninov
    ('Liturgy of St John Chrysostom, Op 31', 'The Liturgy of St John Chrysostom Op.31 for chorus'),  # Sergey Rachmaninov
    ('Litugy of St John Chrysostom, op 31', 'The Liturgy of St John Chrysostom Op.31 for chorus'),  # Sergey Rachmaninov
    ("Prelude No. 5 in G, from '13 Preludes, op. 32'", 'Prelude in G major, Op 32 no 5'),  # Sergey Rachmaninov
    ('Prelude in G major (Op.32 no.5) -  encore', 'Prelude in G major, Op 32 no 5'),  # Sergey Rachmaninov
    ('13 Preludes for piano (Op.32) no. 6', 'Prelude in F minor, op. 32/6'),  # Sergey Rachmaninov
    ('Vocalise (Op.34 No.14) for viola and piano', 'Vocalise (Op.34 No.14)'),  # Sergey Rachmaninov
    ('Vocalise', 'Vocalise (Op.34 No.14)'),  # Sergey Rachmaninov
    ('The Bells (Op.35)', 'The Bells (Kolokola) for soloists, chorus and orchestra, Op 35'),  # Sergey Rachmaninov
    ('The Bells Op.35 for soloists, chorus and orchestra',
     'The Bells (Kolokola) for soloists, chorus and orchestra, Op 35'),  # Sergey Rachmaninov
    ('Vespers Op.37 (excerpts)', 'Vespers (All-Night Vigil), Op 37 (excerpts)'),  # Sergey Rachmaninov
    ('Bogoróditse Dévo, ráduisya (Op.37)', 'Bogoróditse Dévo, ráduisya - from All-Night Vigil (Op.37)'),  # Sergey Rachmaninov
    ('Rejoice, O Virgin (All-Night Vigil, Op 37)', 'Bogoróditse Dévo, ráduisya - from All-Night Vigil (Op.37)'),  # Sergey Rachmaninov
    ('Blessed is the Man from Vespers [All night Vigil] (Op.37)', 'Blessed is the Man from Vespers (Op.37)'),  # Sergey Rachmaninov
    ('Etudes-Tableaux (Op.39) (I - VI only)', 'Etudes-Tableaux, Op 39 (excerpts - I to VI)'),  # Sergey Rachmaninov
    ('Etudes-Tableaux (Op.39) (Nos 1 to 6)', 'Etudes-Tableaux, Op 39 (excerpts - I to VI)'),  # Sergey Rachmaninov
    ('Etude-tableau in D major for piano (Op.39 No.9)',
     'No.9 in D major from Etudes-tableaux for piano (Op.39)'),  # Sergey Rachmaninov
    ('Étude-Tableau in D minor, op. 39/9', 'No.9 in D major from Etudes-tableaux for piano (Op.39)'),  # Sergey Rachmaninov
    ('No 9 in D (Etudes-tableaux for piano, Op 39)', 'No.9 in D major from Etudes-tableaux for piano (Op.39)'),  # Sergey Rachmaninov
    ('6 Romances op 4 - Sing not to me beautiful maiden',
     'Sing not to me beautiful maiden (from 6 Romances, Op 4)'),  # Sergey Rachmaninov
    ('Piano Concerto No.4 in G minor, Op.40 [1941-42 version]', 'Piano Concerto No 4 in G minor, Op 40'),  # Sergey Rachmaninov
    ('Corelli Variations, Op 42', 'Variations on a Theme of Corelli, Op 42'),  # Sergey Rachmaninov
    ('Rhapsody on a theme of Paganini for piano and orchestra (Op.43); Rachmaninov Rhapsody on a theme of Paganini;',
     'Rhapsody on a theme of Paganini, Op 43'),  # Sergey Rachmaninov
    ('3 Symphonic dances Op.45 for orchestra', 'Symphonic Dances, Op 45'),  # Sergey Rachmaninov
    ('Suite for 2 pianos in G minor (Op.5)', 'Suite for 2 pianos in G minor (Op.5) (Fantasie-Tableaux)'),  # Sergey Rachmaninov
    ('Suite No 1 Op 5', 'Suite for 2 pianos in G minor (Op.5) (Fantasie-Tableaux)'),  # Sergey Rachmaninov
    ('Elegiac trio for piano and strings no. 2 (Op.9) in D minor', 'Trio élégiaque No. 2 in D minor, op. 9'),  # Sergey Rachmaninov
    ('Prelude in C sharp minor', 'Prelude in C sharp minor (Op.3, No.2)'),  # Sergey Rachmaninov
    ('Prelude in C sharp minor [Bells]', 'Prelude in C sharp minor (Op.3, No.2)'),  # Sergey Rachmaninov
    # --- Rachmaninov sweep batch 2 (2026-07-05): tail-check stragglers.
    # Bare 'The Bells' (41 segment airings) folds to Op 35; the Bogoroditse
    # Devo strays consolidate into the Op-37-cited group (the pre-existing
    # Devo/Djevo pairs were retargeted there). NOT folded: 'O mother of
    # God, ever-vigilant in prayer' — the [1893] early sacred concerto, a
    # DIFFERENT work from the Vespers number; 'Polishynel' (sole spelling,
    # no twin); Etude-Tableau 39/5 (single key).
    ('The Bells', 'The Bells (Kolokola) for soloists, chorus and orchestra, Op 35'),  # Sergey Rachmaninov
    ('Bogoroditse Devo, from Vespers (All-Night Vigil)',
     'Bogoróditse Dévo, ráduisya - from All-Night Vigil (Op.37)'),  # Sergey Rachmaninov
    ('Bogoroditse Djevo', 'Bogoróditse Dévo, ráduisya - from All-Night Vigil (Op.37)'),  # Sergey Rachmaninov
    ('Bogoroditse djevo (from Vespers)', 'Bogoróditse Dévo, ráduisya - from All-Night Vigil (Op.37)'),  # Sergey Rachmaninov
    ('Bogoroditse Djevo, (extract Vespers)', 'Bogoróditse Dévo, ráduisya - from All-Night Vigil (Op.37)'),  # Sergey Rachmaninov
    ('Symphony No 2 in E', 'Symphony no 2 in E minor, Op 27'),  # Sergey Rachmaninov
    ('The Isle of the dead', 'The Isle of the Dead, Op 29'),  # Sergey Rachmaninov
    ("Andante from 'Cello Sonata in G minor'", 'Cello Sonata in G minor Op 19 (Andante)'),  # Sergey Rachmaninov
    ('Excerpts from Vespers, All Night Vigil', 'Vespers (All-Night Vigil), Op 37 (excerpts)'),  # Sergey Rachmaninov
    # Fauré opus-set sweep (2026-07-06): 28 folds + the shared Grainger
    # 'Après un rêve' family (2 pairs) after retargeting the old final.
    ('Nocturne (Op.107) in E minor (Op.107)', 'Nocturne in E minor, Op 107'),  # Gabriel Fauré
    ('Sonata no. 2 in G minor Op.117', 'Cello Sonata no 2 in G minor, Op 117'),  # Gabriel Fauré
    ('3 Songs op.18 no.1: Nell', 'Nell (Op.18 No.1)'),  # Gabriel Fauré
    ('Après un Rêve (op 7/1); Sylvie (op 6/3);Clair de lune (op 46/2);  Nell (op 18/1)',
     'Après un Rêve (op 7/1); Sylvie (op 6/3); Clair de lune (op 46/2); Nell (op 18/1)'),  # Gabriel Fauré
    ('Elegie for cello and orchestra (Op.24)', 'Elegy, Op 24'),  # Gabriel Fauré
    ('Elegy for cello and orchestra (Op.24)', 'Elegy, Op 24'),  # Gabriel Fauré
    ('Romance in B flat major, Op.28', 'Romance in B flat major for violin and piano, Op 28'),  # Gabriel Fauré
    ('Impromptu No.2 (Op.31) in F minor (Op.31)', 'Impromptu No.2 in F minor (Op.31)'),  # Gabriel Fauré
    ('Nocturne No. 2 in B major (Op. 33, no. 2)', 'Nocturne in B major, Op 33 no 2'),  # Gabriel Fauré
    ('4 Songs Op.39: no.2 Fleur jetee', 'Fleur jetée, Op.39 No.2'),  # Gabriel Fauré
    ("Les roses d'Ispahan (4 Songs Op.39)", "Les roses d'Ispahan"),  # Gabriel Fauré
    ('Requiem (Op.48) [standard version]', 'Requiem, Op 48'),  # Gabriel Fauré
    ('Requiem Op.48 for soprano, baritone, chorus and orchestra', 'Requiem, Op 48'),  # Gabriel Fauré
    ('In paradisum (from Requiem)', 'In paradisum (excerpt Requiem Op 48)'),  # Gabriel Fauré
    ("La Bonne chanson Op.61 for voice and piano (1. Une sainte en son auréole; 2. Puisque l'aube grandit; 3. La lune blanche luit dans les bois; 4. J'allais dans des chemins perfides; 5. J'ai presque peur, en verité; 6. Avant que tu ne t'en ailles; 7. Donc, ce sera par un clair jour d'été; 8. N'est-ce pas?; 9. L'hiver a cessé)",
     'La Bonne Chanson, Op 61'),  # Gabriel Fauré
    ('La Bonne chanson Op.61 for voice and piano', 'La Bonne Chanson, Op 61'),  # Gabriel Fauré
    ('Nocturne No 6 in D for piano, Op 63', 'Nocturne for piano no 6 in D flat major, Op 63'),  # Gabriel Fauré
    ('Nocturne for piano no.7 (Op.74) in C sharp minor', 'Nocturne in C sharp minor, Op 74'),  # Gabriel Fauré
    ('3 Songs Op.7: no.1 Apres un reve', 'Après un rêve, Op 7 no 1'),  # Gabriel Fauré
    ('Pelléas et Mélisande, Op 80', 'Pelleas et Melisande suite, Op 80'),  # Gabriel Fauré
    ('En sourdine', 'En Sourdine, Op 58 no 2'),  # Gabriel Fauré
    ('Fantasy', 'Fantasy for flute and piano'),  # Gabriel Fauré
    ('Messe Basse (orch. Jon Washburn)', 'Messe Basse'),  # Gabriel Fauré
    ('Messe Basse - for solo soprano, choir and orchestra (orch. Jon Washburn)', 'Messe Basse'),  # Gabriel Fauré
    ('4 Songs [1. Prison, Op.83 no.1; 2. Spleen, Op.51 no.3; 3. Clair de lune, Op.46 no.2; 4. Mandoline, Op.58 no.1]',
     '4 Songs for voice and piano (1. Prison, Op.83 no.1; 2. Spleen, Op.51 no.3; 3. Clair de lune, Op.46 no.2; 4. Mandoline, Op.58 no.1)'),  # Gabriel Fauré
    ('4 Songs for voice and piano (1. Prison, Op.83 no.1; 2. Spleen, Op.51 no.3;',
     '4 Songs for voice and piano (1. Prison, Op.83 no.1; 2. Spleen, Op.51 no.3; 3. Clair de lune, Op.46 no.2; 4. Mandoline, Op.58 no.1)'),  # Gabriel Fauré
    ('4 Songs for voice and piano',
     '4 Songs for voice and piano (1. Prison, Op.83 no.1; 2. Spleen, Op.51 no.3; 3. Clair de lune, Op.46 no.2; 4. Mandoline, Op.58 no.1)'),  # Gabriel Fauré
    ('Clair de lune; En sourdine (texts by Verlaine)', 'Clair de lune; En sourdine'),  # Gabriel Fauré
    ('Après un rêve (after Fauré)', 'Après un rêve, Op 7 no 1'),  # Percy Grainger / Gabriel Fauré
    ('Après un rêve (Fauré)', 'Après un rêve, Op 7 no 1'),  # Percy Grainger / Gabriel Fauré
    # Scriabin opus-set sweep (2026-07-06): 29 folds.
    ('Sonata no. 2 in G sharp minor Op.19 (Sonata-fantasia) for piano',
     'Piano Sonata No 2 in G sharp minor, Op 19'),  # Alexander Scriabin
    ('Study in C sharp minor, Op.2 No.1', 'From 3 Pieces for piano (Op. 2): No. 1, Study in C sharp minor'),  # Alexander Scriabin
    ('Piano Concerto, Op 20, in F sharp minor, Op 20', 'Piano Concerto in F sharp minor, Op 20'),  # Alexander Scriabin
    ('Piano Concerto in F sharp minor', 'Piano Concerto in F sharp minor, Op 20'),  # Alexander Scriabin
    ('Piano Concerto No.1 in F sharp minor, Op.20', 'Piano Concerto in F sharp minor, Op 20'),  # Alexander Scriabin
    ('Sonata no. 3 (Op.23) in F sharp minor', 'Piano Sonata no 3 in F sharp minor, Op 23'),  # Alexander Scriabin
    ('Piano Sonata no 4 in F sharp minor, Op 30', 'Piano Sonata no 4 in F sharp major, Op 30'),  # Alexander Scriabin
    ('Sonata No.4 in F sharp minor (Op.30)', 'Piano Sonata no 4 in F sharp major, Op 30'),  # Alexander Scriabin
    ('Andante cantabile, from Two Poems, Op 32 No 1', 'Poème in F sharp (Op.32 No.1)'),  # Alexander Scriabin
    ('Two Poems, Op 32 No 1 (Andante cantabile)', 'Poème in F sharp (Op.32 No.1)'),  # Alexander Scriabin
    ('Andante cantabile (Op. 32/1)from 2 Poems for piano', 'Poème in F sharp (Op.32 No.1)'),  # Alexander Scriabin
    ("Symphony No. 3 in C minor, op. 43 ('The Divine Poem')", 'Symphony No. 3 Op. 43 (The Divine Poem)'),  # Alexander Scriabin
    ('Symphony no. 3 (Op.43) in C major "The Divine poem"', 'Symphony No. 3 Op. 43 (The Divine Poem)'),  # Alexander Scriabin
    ("Poeme de l'extase for orchestra, Op 54 (1908)", "Le Poeme de l'extase for orchestra, Op 54"),  # Alexander Scriabin
    ("Le poeme de l'extase, Op 54", "Le Poeme de l'extase for orchestra, Op 54"),  # Alexander Scriabin
    ("Le Poème de l'extase", "Le Poeme de l'extase for orchestra, Op 54"),  # Alexander Scriabin
    ('The Poem of Ecstasy', "Le Poeme de l'extase for orchestra, Op 54"),  # Alexander Scriabin
    ("Poema ekstaza/Le poeme de l'extase (Symphony No 4) - 1905-08",
     "Le Poeme de l'extase for orchestra, Op 54"),  # Alexander Scriabin
    ("Poema ekstaza/Le poÃ¨me de l'extase [Symphony no.4] (1905-08)",
     "Le Poeme de l'extase for orchestra, Op 54"),  # Alexander Scriabin
    ("Poema ekstaza/Le poème de l'extase (1905-08)", "Le Poeme de l'extase for orchestra, Op 54"),  # Alexander Scriabin
    ('Prometheus (The poem of fire) Op.60',
     'Prometheus (The poem of fire) Op.60 for piano, chorus, organ and orchestra'),  # Alexander Scriabin
    ('Three Studies, Op 65', '3 Etudes, Op 65'),  # Alexander Scriabin
    ('Sonata no. 10 in C major Op.70 for piano', 'Piano Sonata no 10, Op 70'),  # Alexander Scriabin
    ('2 Pieces Op.9 for piano [left hand]', 'Prelude and Nocturne for the Left Hand, Op 9'),  # Alexander Scriabin
    ('From 2 Pieces Op.9 for piano (left hand): No.1 Prelude in C sharp minor',
     'Prelude for the Left Hand, Op 9/1'),  # Alexander Scriabin
    ('2 Pieces Op.9 for piano (left hand) - no. 1 Prelude in C sharp minor',
     'Prelude for the Left Hand, Op 9/1'),  # Alexander Scriabin
    ('Sonata No.9 "Black Mass"', 'Sonata no 9 in F major "Black Mass", Op 68'),  # Alexander Scriabin
    ('Five Preludes: Op 16, No 4 in E flat minor; Op 17, No 4 in B flat minor; Op 27, Nos 1 in G minor and 2 in B; Op 31, No 3 in E flat',
     '5 Preludes: in E flat minor, Op 16 No 4; in B flat minor, Op 17 No 4; in G minor, Op 27 No 1; in B, Op 27 No 2; in E flat, Op 31 No 3'),  # Alexander Scriabin
    ('5 works for piano: 1. Desire (Op.57 no.1); 2. Nuances (Op.56 no.3); 3. Danced caress (Op.57 no.2); 4. Album Leaf (Op.58); 5. Enigma (Op.52 no.2)',
     '5 works for piano; 5 works for piano orch. Oliver Knussen'),  # Alexander Scriabin
    # Liszt opus-set sweep (2026-07-06), post Searle-ref gate: 120 folds.
    ('A Faust symphony (S.108) [with optional male chorus]', 'A Faust Symphony, S.108'),  # Franz Liszt
    ('Eine Faust-Sinfonie (in drei Charakterbildern) (S.108)', 'A Faust Symphony, S.108'),  # Franz Liszt
    ('Eine Faust-Sinfonie, S108', 'A Faust Symphony, S.108'),  # Franz Liszt
    ('A Symphony to Dante\'s "Divine comedy" for female voices and orchestra (S.109)', 'Dante Symphony, S.109'),  # Franz Liszt
    ('12 Transcendental Études, S139', "Etudes d'execution transcendante for piano (S.139)"),  # Franz Liszt
    ("Harmonies du Soir in D flat major: No.11 from Etudes d'execution transcendante S.139",
     'Transcendental study No 11 in D flat major'),  # Franz Liszt
    ("Harmonies du Soir: No.11 from Etudes d'execution transcendante S.139",
     'Transcendental study No 11 in D flat major'),  # Franz Liszt
    ("Etudes d'execution transcendante S.139 for piano - No 11. Harmonies du soir",
     'Transcendental study No 11 in D flat major'),  # Franz Liszt
    ('Harmonies du soir S.139 no.11', 'Transcendental study No 11 in D flat major'),  # Franz Liszt
    ('Transendental Study S.139 no. 12 - Chasse-neige in B flat major',
     'Transcendental Study S. 139 no. 12 Chasse-neige in B flat major'),  # Franz Liszt
    ("Mazeppa, No. 4 of '12 Études d'exécution transcendante, S. 139'", "Etude no 4 in D minor 'Mazeppa'"),  # Franz Liszt
    ("Etude No.4 in D minor 'Mazeppa' - from 12 Études d'exécution transcendante for piano (S.139)",
     "Etude no 4 in D minor 'Mazeppa'"),  # Franz Liszt
    ("Etude No 4 in D minor (Mazeppa) - 12 Etudes d'execution transcendante for piano, S139",
     "Etude no 4 in D minor 'Mazeppa'"),  # Franz Liszt
    ("Etude No 4 in D minor (Mazeppa) (12 Etudes d'execution transcendante)",
     "Etude no 4 in D minor 'Mazeppa'"),  # Franz Liszt
    ("Etude No.5 in B flat major; Feux-follets - from 12 Études d'exécution transcendante for piano (S.139)",
     "Transcendental Study in B flat major 'Feux follets' (S.139 No.5)"),  # Franz Liszt
    ("Transcendental study no.5 in B flat major 'Feux follets' (S.139 No.5)",
     "Transcendental Study in B flat major 'Feux follets' (S.139 No.5)"),  # Franz Liszt
    ("Etude No 5 in B flat (Feux-follets, 12 Etudes d'execution transcendante for piano, S139)",
     "Transcendental Study in B flat major 'Feux follets' (S.139 No.5)"),  # Franz Liszt
    ('Grandes Etudes de Paganini No 2 in E flat, S141 (Andantino capriccioso)',
     'Grandes Etudes de Paganini no.2 (S.141) in E flat major'),  # Franz Liszt
    ('Grande Etude de Paganini No 2 in E flat, S141',
     'Grandes Etudes de Paganini no.2 (S.141) in E flat major'),  # Franz Liszt
    ('Waldesrauschen', 'Waldesrauschen (S.145)'),  # Franz Liszt
    ('Sonetto 123 di Petrarca (S.158 No.3): I vidi in terra angelici costumi',
     'Sonetto 123 di Petrarca (S.158 No.3): Io vidi in terra angelici costumi'),  # Franz Liszt
    ('Sonetto 123 di Petrarca: Io vidi in terra angelici costumi',
     'Sonetto 123 di Petrarca (S.158 No.3): Io vidi in terra angelici costumi'),  # Franz Liszt
    ('Sonetto 123 del Petrarca (Annees de pelerinage - Deuxieme annee, Italie)',
     'Sonetto 123 di Petrarca (S.158 No.3): Io vidi in terra angelici costumi'),  # Franz Liszt
    ("From 'Années de Pèlerinage' (deuxième année - Italie): Sonetto 123 del Petrarca",
     'Sonetto 123 di Petrarca (S.158 No.3): Io vidi in terra angelici costumi'),  # Franz Liszt
    ("Vallée d'Obermann, from Années de pèlerinage - 1er année, Suisse S.160",
     "Vallée d'Obermann, from 'Années de pèlerinage, première année: Suisse, S. 160'"),  # Franz Liszt
    ('Années de pèlerinage - 1er année, Suisse S.160', 'Annees de pelerinage - 1ere annee, Suisse S.160'),  # Franz Liszt
    ('Années de Pèlerinage, Première année: Suisse', 'Annees de pelerinage - 1ere annee, Suisse S.160'),  # Franz Liszt
    ('Après une Lecture de Dante: Fantasia quasi Sonata - from Années de Pèlerinage: Deuxième Année (S.160 No.7)',
     'Apres une Lecture de Dante: Fantasia quasi Sonata'),  # Franz Liszt
    ('Apres une Lecture de Dante (Fantasia quasi Sonata, S160, No 7)',
     'Apres une Lecture de Dante: Fantasia quasi Sonata'),  # Franz Liszt
    ('Après une lecture de Dante - Fantasia quasi sonata - from Années de Pèlerinage, deuxième année, Italie, S161',
     'Apres une Lecture de Dante: Fantasia quasi Sonata'),  # Franz Liszt
    ('Après une lecture de Dante - Fantasia quasi sonata, from Années de Pèlerinage, duexième année, Italie, S.161',
     'Apres une Lecture de Dante: Fantasia quasi Sonata'),  # Franz Liszt
    ('Apres une lecture du Dante from Annees de pelerinage - 2me annee, Italie (S.161)',
     'Apres une Lecture de Dante: Fantasia quasi Sonata'),  # Franz Liszt
    ('Après une lecture de Dante **EXPIRED**', 'Apres une Lecture de Dante: Fantasia quasi Sonata'),  # Franz Liszt
    ('Apres une Lecture de Dante', 'Apres une Lecture de Dante: Fantasia quasi Sonata'),  # Franz Liszt
    ("Sonetto 104 del Petrarca (Petrarch's Sonnet 104) (S.161 No.5)",
     "Sonetto 104 del Petrarca, 'Années de pèlerinage, deuxième année: Italie, S.161'"),  # Franz Liszt
    ('Sonetto 104 del Petrarca',
     "Sonetto 104 del Petrarca, 'Années de pèlerinage, deuxième année: Italie, S.161'"),  # Franz Liszt
    ('Tarantella (Venezia e Napoli, S162)', 'Tarantella from Venezia e Napoli (S.162)'),  # Franz Liszt
    ('Venezia e Napoli (S.162)', 'Venezia e Napoli S.162, rev. 1859'),  # Franz Liszt
    ("Venezia e Napoli (S.162) rev. 1859 [supp.to 'Annees de pelerinage' 2me annee]",
     'Venezia e Napoli S.162, rev. 1859'),  # Franz Liszt
    ('Ballade no.2 in B flat, S.171', 'Ballade no.2 in B minor, S.171'),  # Franz Liszt
    ('Consolation No 3 in D flat major S172 No 3', 'Consolation in D flat, S. 172/3'),  # Franz Liszt
    ('Consolation No.3 in D flat major (Lento placido) for piano (S.172)', 'Consolation in D flat, S. 172/3'),  # Franz Liszt
    ('Consolations, S. 172: No. 3 in D-Flat Major iii) Lento placido', 'Consolation in D flat, S. 172/3'),  # Franz Liszt
    ('Harmonies poetiques et religieuses - 10 pieces for piano (excerpts)',
     'Excerpts from Harmonies Poetiques et Religieuses: 10 pieces for piano S.173'),  # Franz Liszt
    ('Harmonies poétiques et religieuses (excerpts);',
     'Excerpts from Harmonies Poetiques et Religieuses: 10 pieces for piano S.173'),  # Franz Liszt
    ("Harmonies poétiques et religieuses - 10 pieces for piano (excerpts): Invocation; Pater Noster; Hymne de l'enfant à son réveil; Funérailles",
     "Harmonies poetiques et religieuses - 10 pieces for piano (excerpts); 1. Invocation; 2. Pater Noster; 3. Hymne de l'enfant à son réveil; 4. Funérailles"),  # Franz Liszt
    ("Harmonies poetiques et religieuses (excerpts): 1. Invocation; 2. Pater Noster; 3. Hymne de l'enfant à son réveil; 4. Funérailles",
     "Harmonies poetiques et religieuses - 10 pieces for piano (excerpts); 1. Invocation; 2. Pater Noster; 3. Hymne de l'enfant à son réveil; 4. Funérailles"),  # Franz Liszt
    ('No.2 Ave Maria, No.3 Bénédiction de Dieu dans la solitude, No.7 Funérailles, No.5 Pater Noster - from Harmonies Poétiques et Religieuses: 10 pieces for piano (S.173)',
     'Excerpts from Harmonies Poétiques et Religieuses: 10 pieces for piano (S.173): No.2 Ave Maria, No.3 Bénédiction de Dieu dans la solitude, No.7 Funérailles, No.5 Pater Noster'),  # Franz Liszt
    ('Funerailles (Harmonies Poetiques et Religieuses: Ten pieces for piano, S173 No 7)',
     'Funérailles - from Harmonies Poétiques et Religieuses: 10 pieces for piano (S.173 No.7)'),  # Franz Liszt
    ('Funerailles - from Harmonies poetiques et religieuses: 10 pieces for piano',
     'Funérailles - from Harmonies Poétiques et Religieuses: 10 pieces for piano (S.173 No.7)'),  # Franz Liszt
    ("LÃ©gende No.1: St FranÃ§ois d'Assise prÃªchant aux oiseaux (S.175 No.1)",
     "Legende no 1: St Francois d'Assise prechant aux oiseaux, S.175"),  # Franz Liszt
    ("St Francis' Sermon to the Birds (1st of 2 Legends, S.175 No.1)",
     "Legende no 1: St Francois d'Assise prechant aux oiseaux, S.175"),  # Franz Liszt
    ("Legende No 1 (St Francois d'Assise prechant aux oiseaux)",
     "Legende no 1: St Francois d'Assise prechant aux oiseaux, S.175"),  # Franz Liszt
    ('St François de Paule marchant sur les flots - from 2 Légendes (S.175 No.2)',
     'St Francois de Paule marchant sur les flots'),  # Franz Liszt
    ('2 Legendes S.175 for piano - no 2', 'St Francois de Paule marchant sur les flots'),  # Franz Liszt
    ('Polonaise No.2 in E major from (S.223)', 'Polonaise No. 2 in E, S. 223'),  # Franz Liszt
    ('Concert Paraphrase on God Save the Queen, S235 (composed 1841)',
     "Concert Paraphrase on 'God Save the Queen' (S.235) [1841]"),  # Franz Liszt
    ('Hungarian Rhapsody No.1 (S.244 No.1) in E major', 'Hungarian Rhapsody No.1 in E major, S.244'),  # Franz Liszt
    ('Hungarian Rhapsody No.1 (S.244 No.1) in E major (à son ami E. Zerdahely)',
     'Hungarian Rhapsody No.1 in E major, S.244'),  # Franz Liszt
    ('Hungarian Rhapsody No 1 in F minor', 'Hungarian Rhapsody no 1 for orchestra in F minor'),  # Franz Liszt
    ('Hungarian Rhapsody No.2 (S.244 No.2) in C-sharp minor (au Comte Ladislas Teleky)',
     'Hungarian Rhapsody No 2 in C sharp minor'),  # Franz Liszt
    ('Hungarian Rhapsody No 2 in C sharp minor, S244 (au Comte Ladislas Teleky)',
     'Hungarian Rhapsody No 2 in C sharp minor'),  # Franz Liszt
    ('Hungarian Rhapsody No 2 in C sharp minor, S244', 'Hungarian Rhapsody No 2 in C sharp minor'),  # Franz Liszt
    ('Hungarian Rhapsody No.2, S.244', 'Hungarian Rhapsody No 2 in C sharp minor'),  # Franz Liszt
    ('Hungarian Rhapsody No.3 (S.244 No.3) in B flat minor', 'Hungarian Rhapsody no 3 in B flat minor, S244'),  # Franz Liszt
    ('Hungarian Rhapsody No.3 (S.244 No.3) in B-flat minor (au Comte Leo Festetics)',
     'Hungarian Rhapsody no 3 in B flat minor, S244'),  # Franz Liszt
    ('Hungarian Rhapsody No.8 in F# minor (S.244)', 'Hungarian Rhapsody No.8 in F sharp minor (S.244)'),  # Franz Liszt
    ('Hungarian Rhapsody No 10 in E, transcr Paderewski', 'Hungarian Rhapsody No.10 in E major (Preludio)'),  # Franz Liszt
    ('Hungarian Rhapsody no 12 in C Sharp Minor, S.244', 'Hungarian Rhapsody No.12 in C sharp minor'),  # Franz Liszt
    ('Hungarian rhapsody (S.244) no. 12 in C sharp minor; Mesto', 'Hungarian Rhapsody No.12 in C sharp minor'),  # Franz Liszt
    ('Hungarian Rhapsody No.13 in A minor', 'Hungarian Rhapsody no 13 in A minor (Andante sostenuto)'),  # Franz Liszt
    ("Rhapsodie Espagnole (S.254) (Folies d'Espagne - Jota Aragonaise)",
     "Rhapsodie espagnole (Folies d'Espagne et jota aragone) S.254"),  # Franz Liszt
    ('Prelude and Fugue on the Name BACH, S.260', 'Prelude and Fugue on B-A-C-H, S260'),  # Franz Liszt
    ('Präludium und Fuge über den Namen B.A.C.H.', 'Prelude and Fugue on B-A-C-H, S260'),  # Franz Liszt
    ('Liebestraum (S.541) no.3 in A flat major', 'Liebestraume no 3 in A flat major (S.541)'),  # Franz Liszt
    ("Liebesträume (Rêve d'amour ): Notturno III: 'O Lieb' in A flat major (S.541)",
     'Liebestraume no 3 in A flat major (S.541)'),  # Franz Liszt
    ('Notturno No 3 in A flat (Liebestraume, S541), arr from O lieb, S298',
     'Liebestraume no 3 in A flat major (S.541)'),  # Franz Liszt
    ('Liebesträume No.3', 'Liebestraume no 3 in A flat major (S.541)'),  # Franz Liszt
    ('Liebestraum No.3', 'Liebestraume no 3 in A flat major (S.541)'),  # Franz Liszt
    ('Liebestraume (orig. for piano solo)', 'Liebestraume no 3 in A flat major (S.541)'),  # Franz Liszt
    ('Liebestraume in A flat major - from 3 notturnos for piano (S.541)',
     'Liebestraume no 3 in A flat major (S.541)'),  # Franz Liszt
    ('Liebestraum in A flat major - from 3 notturnos for piano (S.541)',
     'Liebestraume no 3 in A flat major (S.541)'),  # Franz Liszt
    ('(Schumann) Widmung (S.566) transcribed for piano', 'Widmung (Op.25 No.1)'),  # Franz Liszt
    ('Liebeslied (Widmung by Schumann), S.566', 'Widmung (Op.25 No.1)'),  # Franz Liszt
    ("Liebeslied, S566, (Schumann's 'Widmung' transcribed for piano)", 'Widmung (Op.25 No.1)'),  # Franz Liszt
    ("Transcription from Mozart's 'Magic Flute' (presumably unpubl. transcription of Mozart: Adagio 'Der welcher wandelt diese strasse', S.634a)",
     "Transcription from Mozart's Magic Flute (S.634a)"),  # Franz Liszt
    ('Tasso, S.96 (symphonic poem)', 'Tasso: lamento e trionfo - symphonic poem after Byron (S.96)'),  # Franz Liszt
    ('Tasso: lamento e trionfo, symphonic poem S.96',
     'Tasso: lamento e trionfo - symphonic poem after Byron (S.96)'),  # Franz Liszt
    ('Tasso - symphonic poem after Byron (S.96)',
     'Tasso: lamento e trionfo - symphonic poem after Byron (S.96)'),  # Franz Liszt
    ('Tasso: lamento e trionfo', 'Tasso: lamento e trionfo - symphonic poem after Byron (S.96)'),  # Franz Liszt
    ('Tasso: lamento e trionfo - symphonic poem after Byron',
     'Tasso: lamento e trionfo - symphonic poem after Byron (S.96)'),  # Franz Liszt
    ('Les Preludes - symphonic poem after Lamartine (S.97)', 'Les Préludes - symphonic poem after Lamartine'),  # Franz Liszt
    ('Les Les Préludes - symphonic poem after Lamartine (S.97)',
     'Les Préludes - symphonic poem after Lamartine'),  # Franz Liszt
    ('Les Préludes (S.97)', 'Les Préludes - symphonic poem after Lamartine'),  # Franz Liszt
    ('Orpheus - symphonic poem, S.98', 'Orpheus - symphonic poem S.98 for orchestra'),  # Franz Liszt
    ('Orpheus - Symphonic poem (1853-4)', 'Orpheus - symphonic poem S.98 for orchestra'),  # Franz Liszt
    ('Orpheus', 'Orpheus - symphonic poem S.98 for orchestra'),  # Franz Liszt
    ('(Lassen) Löse Himmel, meine seele (S.494)', 'Löse Himmel, meine seele, S.494'),  # Franz Liszt
    ('Mephisto Waltz No.1 (S. 514) (Der Tanz in der Dorfschenke)', 'Mephisto Waltz No.1 (S.514)'),  # Franz Liszt
    ('Der Tanz in der Dorfschenke (Mephisto waltz no.1)', 'Mephisto Waltz No.1 (S.514)'),  # Franz Liszt
    ('Mephisto waltz no 1', 'Mephisto Waltz No.1 (S.514)'),  # Franz Liszt
    ('Ungarischer Marsch zur Krönungsfeier in Ofen-Pest (Hungarian March for the Coronation Celebrations in Buda and Pest 8th June 1867) S 523',
     'Ungarischer Marsch zur Kronungsfeier in Ofen-Pest (S.523) (1870)'),  # Franz Liszt
    ("Reminiscences on Bellini's 'Norma'", 'Reminiscences de Norma S.394 for piano'),  # Franz Liszt
    ("Reminiscences de Norma S.394 for piano [on themes from Bellini's opera]",
     'Reminiscences de Norma S.394 for piano'),  # Franz Liszt
    # Campaign re-survey straggler (2026-07-06): the one true find across all
    # 10 swept composers — a 'from'-presence split on the Chopin-credited
    # Liszt transcription.
    ("The Maiden's Wish (Six Polish songs, S480)",
     "The Maiden's Wish (from 'Six Polish songs', S.480)"),  # Fryderyk Chopin / Liszt S.480
    # Goldberg pair (2026-07-06, the long-open campaign leftovers): the Aria
    # is BWV 988's — 'BWV 1087' (the 14 Canons) is a catalogue mislabel on
    # one recording's titles; the genuine 14-Canons excerpts stay separate.
    ("Aria, from 'Goldberg Variations, BWV 1087'",
     'Aria, from Goldberg variations BWV.988'),  # Johann Sebastian Bach
    # Sitkovetsky's string-trio arrangement is a literal transcription of the
    # whole (the arr-tail strip leaves a bare catalogue-less key); the
    # 'Improvisation on Goldberg Variations' stays split (paraphrase-grade).
    ('Goldberg Variations, arr. Sitkovetsky for string trio',
     'Goldberg Variations, BWV 988'),  # Johann Sebastian Bach
    # Épigraphes re-examination (2026-07-06, Cerys + web verification — see
    # musicological-notes): the 'vers. for piano duet' titles are the PRIMARY
    # 1914 scoring, stranded by the deliberate non-arr 'vers.' marker; one
    # work with the bare group (which already carries the verified-literal
    # Ansermet orchestration via the arr-tail strip).
    ('6 Epigraphes antiques vers. for piano duet',
     'Six Epigraphes Antiques'),  # Claude Debussy
    # Chansons de Bilitis SONG CYCLE (1897) asserted strays — both
    # performer-verified mezzo+piano. NB bare 'Chansons de Bilitis' stays
    # SPLIT: the oracle shows it mixing the song cycle with airings of the
    # 1901 incidental music (narrator/2fl/harp/celesta, 1208s) — per-airing
    # attribution the whole-title alias layer can't express (Matteis class).
    ('3 Chansons de Bilitis',
     'Chansons de Bilitis - 3 melodies for voice & piano'),  # Claude Debussy
    ('Chansons de Bilitis - 3 songs for voice and piano',
     'Chansons de Bilitis - 3 melodies for voice & piano'),  # Claude Debussy
    ('Reminiscences de Don Juan for piano (S.418)', "Reminiscences on Mozart's 'Don Giovanni'"),  # Franz Liszt
    ("Reminiscences de Don Juan for piano on Themes from Mozart's Don Giovanni, S418",
     "Reminiscences on Mozart's 'Don Giovanni'"),  # Franz Liszt
    ('Czardas obstine (1884)', 'Csardas obstine'),  # Franz Liszt
    ('Czardas obstinee', 'Csardas obstine'),  # Franz Liszt
    ('Concerto Pathetique in E minor for Two Piano', 'Concerto Pathétique in E minor for Two Pianos'),  # Franz Liszt
    ('Piano Concerto no.1 in E flat major', 'Piano Concerto no.1 in E flat major, S.124'),  # Franz Liszt
    ("Fantasies on 'Szozdat' (Second Hungarian National Anthem)",
     "Fantasy on 'Szozat' (2nd Hungarian National Anthem)"),  # Franz Liszt
    ("Fantasies on 'Szozdat' (Second Hungarian National Anthem) and Hungarian National Anthem",
     "Fantasy on 'Szozat' (2nd Hungarian National Anthem)"),  # Franz Liszt
    ('Hungarian Coronation Mass', 'Hungarian Coronation Mass for SATB, chorus & orchestra'),  # Franz Liszt
    ('Christus - Pastorale and Herald Angels Sing (excerpt)', 'Christus - Pastorale and Herald Angels Sing'),  # Franz Liszt
    ('La Notte (3 odes funebres - No 2)', 'La Notte (no 2 from 3 Odes funèbres)'),  # Franz Liszt
    ('Transcendental Etudes Nos. 9, 5. 6',
     "Transcendental Studies Nos 9 in A flat 'Ricordanza', 6 in G minor 'Vision', 5 in B flat 'Feux follets'"),  # Franz Liszt
    ('A la Chapelle Sixtine', 'A la Chapelle Sixtine (Miserere de Allegri et Ave verum corpus de Mozart)'),  # Franz Liszt
    ('La Campanella', "Etude in G sharp minor, S141/3, 'La campanella'"),  # Franz Liszt
    ('Grande etude de Paganini no.3 in G sharp minor: La Campanella',
     "Etude in G sharp minor, S141/3, 'La campanella'"),  # Franz Liszt
    ('La campanella, S. 140 No. 3 in A flat minor',
     "La campanella, No. 3 in A flat minor, from 'Etudes d'exécution transcendante d'après Paganini, S. 140'"),  # Franz Liszt
    ('La campanella, No. 3 in A flat minor',
     "La campanella, No. 3 in A flat minor, from 'Etudes d'exécution transcendante d'après Paganini, S. 140'"),  # Franz Liszt
    # Cross-era relaxed-bridge ratification batch (2026-07-06): 601 folds
    # from the full deferred-backlog triage (every deferred link triaged;
    # ledger-anchored - see ttn_bridge_decisions.json).
    ('Liebesbotschaft (Schwanengesang, D.957 No.1); Heidenröslein (D.257 No.3); Litanei auf das Fest Aller Seelen (D.343)', "3 Songs: 'Liebesbotschaft', 'Heidenroslein' and 'Litanei auf das Fest'"),   # [strong] p00wnc79 1x
    ("No.2 in G minor, 'Hornpipe' (from 'Miniatures', set 3 for violin, cello and piano)", 'Hornpipe (Miniatures, Set 3, no 2)'),   # [strong] p00x0tvt 1x
    ("13 pieces from 'Drottningholmsmusiquen' (1744)", "13 pieces from 'Drottningholmsmusiquen' (for the Swedish Royal Wedding of 1744)"),   # [weak] p00w6nk0 6x
    ('4 works for Viola da gamba & bass continuo. from Pièces de Viole', '4 works for Viola da gamba & b.c. from Pieces de Viole, 5me livre, Paris 1725 EX'),   # [weak] p00z64l0 1x
    ('Barcarola', 'Barcarola for orchestra'),   # [strong] p0135jy8 1x
    ("Primo Ballo della notte d'amore & Sinfonica (Spirito del ciel) - from Il primo libro delle musiche", "Primo Ballo della notte d'amore & Sinfonia (Spirito del ciel)"),   # [weak] p00x815s 1x
    ('Sinfonia for orchestra (Op.36) "Jupiter" (fragment)', 'Sinfonia for orchestra, Op 36 "Jupiter"'),   # [strong] p012jv5q 1x
    ("Piano Sonata no.14 (Op.27 No.2) in C sharp minor, 'Moonlight'", "Sonata quasi una fantasia for piano (Op.27 No.2) in C sharp minor, 'Moonlight'"),   # [strong] p014kyzn 1x
    ('String Quartet', 'String Quartet (Unfinished, 1922)'),   # [weak] p00w58hl 5x
    ("Symphony No.64 in A major, 'Tempora mutantur'", "Symphony no 64 in A major, Hob: I/64, 'Tempora mutantur'"),   # [strong] p00s5398 1x
    ('Ma vlast - cycle of symphonic poems', 'Ma vlast [My country] - cycle of symphonic poems'),   # [weak] p012jq3z 1x
    ('Vetrate di Chiesa - 4 Symphonic impressions', 'Vetrate di Chiesa (Church Windows)'),   # [strong] p0157bbp 2x
    ('Fantaisie pastorale hongroise (Op.26) (vers. for flute and piano)', 'Fantaisie pastorale hongroise, Op 26'),   # [strong] p00txgs4 1x
    ("Un'aura amorosa (from Così fan tutte, Act I)", 'Aria: "Un\'aura amorosa" from the opera \'Così fan tutte\' (K.588), Act 1'),   # [strong] p00vlxvw 1x
    ('Concerto for 2 chalumeaux and strings in D minor', 'Concerto for 2 chalumeaux and strings in D minor (c.1728)'),   # [weak] p00vlxx9 1x
    ('Sextet for piano, 2 violins, viola, violoncello and double bass in A minor (Op.29) (1869/1873)', 'Piano Sextet in A minor'),   # [strong] p0702mnm 2x
    ('Alma susanna', 'Madrigal - Alma susanna (1568)'),   # [strong] p024jyxn 3x
    ('Auf stillem Waldespfad - from Stimmungsbilder (Op.9 No.1)', 'Auf stillem Waldespfad (Stimmungsbilder, Op 9 No 1)'),   # [strong] p027rdxt 1x
    ('Stanczyk - Symphoni Scherzo (Op.1) (1904)', 'Stanczyk - Symphonic Scherzo Op 1'),   # [weak] p00zgxpr 2x
    ('Sonate da Chiesa in C major (Op.1 No.7)', 'Sonata da chiesa in C major (Op.1 No.7)'),   # [weak] p018xs8s 6x
    ('Slow Drags No.4', 'Pastime Rags (1913-20): Slow Drags No.4'),   # [strong] p00xw9zr 1x
    ("Overture: L'Italiana in Algeri (Italian Girl in Algiers)", "L'Italiana in Algeri (Overture)"),   # [strong] p00wnc09 1x
    ('Der Herr ist König (und herrlich geschmückt)', 'Der Herr ist Konig (und herrlich geschmuckt) – motet for double chorus & bc'),   # [weak] p03nr5ll 1x
    ('Phantasy in C major (D.934)', 'Phantasy in C major, D.934 (Op.Posth.159)'),   # [strong] p00ybr2q 1x
    ('Overture from Die Geschopfe des Prometheus (Op.43)', 'Creatures of Prometheus (Die Geschopfe des Prometheus), Overture, Op 43'),   # [strong] p00yr4b1 2x
    ('Sonata for Piano Trio in E major (H.XV:28)', 'Trio for keyboard and strings H.15.28 in E major'),   # [weak] p00xx6dy 4x
    ('Four Old Hungarian Folksongs', 'Four Old Hungarian Folk Songs'),   # [weak] p00ty03v 3x
    ('Pavane in G minor (Z.752) and Chaconne (Chacony) in G minor (Z.730)', 'Pavan (Z.752) and Chacony (Z.730) for 4 instruments in G minor'),   # [weak] p00y3431 6x
    ('In Autumn', 'In Autumn - concert overture, Op 11'),   # [weak] p00w3ycr 3x
    ("Vaghi pensieri'", 'Madrigal "Vaghi pensieri"'),   # [strong] p00rgcy9 3x
    ("L'Autunno (Autumn), RV 293", "Concerto for violin & orchestra RV.293 Op 8 No 3 in F major 'L'Autunno'"),   # [strong] p00wgz3x 3x
    ('Concert Piece for viola and piano', 'Concertstuck for viola and piano (1906)'),   # [strong] p00yj161 7x
    ('5 Bukoliki', '5 Bukoliki [Bucolics] for viola and cello'),   # [strong] p0182598 1x
    ('Fantasia su un linguaggio perduto for string instruments', 'Fantasia sul linguaggio perduto'),   # [weak] p01gzy04 2x
    ('Le Temple de la Gloire - orchestral suites from the opera-ballet (1745)', 'Le Temple de la Gloire (orchestral suites)'),   # [strong] p01dpbtm 2x
    ('Madrigal: Draw on sweet night - for 6 voices', 'Draw on sweet night for 6 voices (1609)'),   # [weak] p00q8qgl 3x
    ('S.U.su.P.E.R.per - motet for 4 voices', 'S.U.su.P.E.R.per - motet for 4 voices [Super flumina Babylonis]'),   # [strong] p00sry42 3x
    ('Bulgarian Madonna from 2 works after paintings of Vladimir Dimitrov - the Master', "Bulgarian Madonna (excerpts 'paintings of Vladimir Dimitrov - the Master')"),   # [strong] p00sryn5 2x
    ("Cantata 'Es wird ein unbarmherzig Gericht' for 4 voices, 2 oboes, strings and continuo", 'Cantata "Es wird ein unbarmherzig Gericht" for 4 voices'),   # [strong] p0mdb2xm 1x
    ('Intermezzo from Manon Lescaut', "Intermezzo (excerpt from 'Manon Lescaut' between Acts 2 and 3)"),   # [strong] p00w0x5v 2x
    ('"Basta vincesti" (recit) and "Ah, non lasciarmi" (aria) (K.486a)', 'Basta vincesti ... Ah, non lasciarmi K.486a'),   # [strong] p00vjcp3 1x
    ('Der Pilgrim (D.794 Op.37 No.1)', 'Der Pilgrim D.794'),   # [strong] p00w10n7 1x
    ("Concerto for 4 keyboards in A minor (BWV.1065) - from Vivaldi's Concerto for 4 violins (Op.3 No.10, RV.580)", 'Concerto for 4 keyboards in A minor (BWV.1065)'),   # [strong] p00vppfk 3x
    ("Five Spirituals - from the oratorio 'A Child of our Time'", "Five Spirituals from 'A Child of our Time' for chorus"),   # [strong] p010b11r 3x
    ('Printemps - suite symphonique', 'Printemps (symphonic suite) [Tres modere; Modere]'),   # [strong] p013qh0b 2x
    ("Quartet for strings in C minor (D.103) 'Satz'", "String Quartet in C minor, D.703 'Quartettsatz'"),   # [weak] p00qc6q2 13x
    ('Trio in B flat major Op.11 for clarinet, cello and piano', 'Trio in B flat major, Op 11'),   # [strong] p00zb6hn 1x
    ('Symphony No.2 in B flat major (Op.15)', 'Symphony No 2 in B flat major'),   # [strong] p028k3hd 1x
    ('Salve Regina', 'Salve Regina (Hail, Holy Queen)'),   # [weak] p00sdzqr 9x
    ('Sorrow for cello and orchestra (Op.2 No.2)', 'Sorrow for cello and orchestra'),   # [strong] p00vkpxz 2x
    ('Second Waltz from the Second Jazz suite', 'Waltz no.2 from Suite for jazz band no. 2 (1938)'),   # [weak] p0145jrl 8x
    ("Sonata from Concerto No.XI in E minor 'Delirium amoris'", 'Sonata from Concerto no XI in E minor'),   # [weak] p00vjc2l 2x
    ('Córdoba (Nocturne) from Cantos de Espana, arr. unknown for guitar and cello', 'Cordoba (Nocturne) from Cantos de Espana, Op 232 no 4'),   # [strong] p00r68s5 1x
    ("Overture to the singspiel 'Vinhoesten'", 'Vinhoesten (Der Fest der Winzer) (Overture)'),   # [strong] p025qcr5 1x
    ("Cantata: 'Paratum cor meum'", 'Alleluja. Paratum cor meum'),   # [strong] p00rw2nr 3x
    ('Music to a Scene (1904)', 'Music to a Scene [original version of Dance Intermezzo]'),   # [strong] p00x2kp5 3x
    ('Häämarssi (Wedding March) - from Pieces vers. for piano (Op.3b No.2)', 'Haamarssi (Wedding March) (Op.3b No.2)'),   # [strong] p02r8qj1 3x
    ('Passacaglia & Aria - from Concerto Pastorella in F major for 2 recorders, strings & continuo', 'Passacaglia & Aria (presto)'),   # [weak] p01h00yy 1x
    ('Oboe Concerto in C Major (Hob.VIIg:C1)', 'Oboe Concerto in C Major (Hob.VIIg:C1) [doubtful]'),   # [strong] p00tf6p0 2x
    ("10 Variations in G on the aria 'Unser dummer Pöbel meint' from the opera 'La rencontre imprévue' by Christoph Willibald Gluck (K. 455)", "10 Variations on 'Unser dummer Pobel meint', K455"),   # [strong] p00tndn6 2x
    ('Litanies à la Vierge Noire', "Litanies à la Vierge Noire version for women's voices and organ"),   # [weak] p00t8fnf 4x
    ('Lotus Land (Op.47 No.1)', 'Lotus Land (Op.47 No.1) [version for piano]'),   # [strong] p00q6cks 2x
    ('Dances Concertantes for chamber orchestra', 'Danses Concertantes for chamber orchestra'),   # [weak] p016ffzf 7x
    ('Pantomime for wind and percussion', 'Pantomime'),   # [weak] p00vgtff 4x
    ('Trio (QV 218) in E flat major', 'Clarinet Trio in E flat (1900)'),   # [weak] p010w9mw 3x
    ('Concerto for cello and orchestra no. 1 (H.7b.1) in C major', 'Cello Concerto No. 1 in C, Hob. VIIb:1'),   # [strong] p00s8b3g 2x
    ("Mazurka - from the idyll 'Jawnuta' (1850)", "Mazurka from the idyll 'Jawnuta' (The Gypsies)"),   # [strong] p00s0wn6 3x
    ('Sinfonia (Op.3 No.4) in A major for strings and continuo', 'Sinfonia in A major, Op 3 no 4'),   # [weak] p00s8j6p 6x
    ('Nocturne for Cello and Orchestra', 'Nocturne'),   # [strong] p00r54vs 3x
    ("Quatre Intermèdes et Divertissements for Molière's comedy 'Amphitryon' (VB.27)", "7 Divertissements for Moliere's comedy 'Amphitryon' (VB.27)"),   # [strong] p00zt6tk 1x
    ('Overture to the play The Hussites', "Overture to the play 'Husitterne' (The Hussites)"),   # [strong] p00t9zp0 1x
    ('Symphony No.4 in C minor (Op.19)', 'Symphony No.4 in C minor (Op.19) [in four movements]'),   # [weak] p00wjqgt 8x
    ('Trio No.4 from Essercizii Musici', 'Trio No 4 (Essercizii Musici)'),   # [weak] p00q8rgw 3x
    ('Motet: Caligaverunt', 'Caligaverunt oculi mei (My eyes are blinded by tears), motet'),   # [strong] p00wjscz 2x
    ("Grand Motet 'Deus judicium tuum regi da' (Psalm 71) for 5 voices, 2 oboes, bassoon, strings and continuo", 'Grand Motet "Deus judicium tuum regi da" (Psalm 71)'),   # [strong] p00wjtck 3x
    ('Blow Ye Wind!', 'Put vejini [Blow Ye Wind!] for mixed chorus'),   # [weak] p00tpn40 2x
    ("Sonata in F major 'Echo-Sonate' for 2 oboes, bassoon and continuo", "Sonata for 2 oboes, bassoon and continuo in F major, 'Echo sonata'"),   # [weak] p00rxjn2 5x
    ('Allegro appassionato (Op.95, No.2) from 2 pieces for Piano Trio', 'Allegro appassionato, Op 95 no 2'),   # [weak] p00wd9dm 2x
    ('Sextet for piano, 2 violins, viola, cello and double bass in A minor (Op.29) (1869/1873)', 'Piano Sextet in A minor'),   # [strong] p0702mnm 2x
    ("Quartet for strings (Op.18'1) in F major", 'Quartet in F major, Op 18 no 1'),   # [weak] p00vgm5z 3x
    ("Capriccio Brillante for symphony orchestra on the theme of 'Jota Aragonese'", "Capriccio brillante on the theme 'Jota Aragonesa'"),   # [strong] p00s4fnr 1x
    ('Lauda Jerusalem (Psalm 147) - for 2 choirs (concert & ripieno) & instruments', "Lauda Jerusalem (Psalm 147, 'How good it is to sing praises to our God')"),   # [weak] p00s561k 2x
    ('Suru (Op.22 No.2)', 'Suru (Sorrow), Op 22 no 2 for cello and piano (orig. cello and orchestra)'),   # [strong] p00t4jz7 1x
    ('Sonata for viola da gamba & basso continuo in A minor - from Essercizii Musici', 'Sonata for viola da gamba & basso continuo in A minor'),   # [weak] p00z8x4j 3x
    ('Trio for clarinet, cello and piano (Op.40)', 'Trio for clarinet, cello and piano,Op 40'),   # [weak] p00x4cks 3x
    ("Overture from 'Der Schauspieldirektor'", 'Der Schauspieldirektor - singspiel in 1 act (K.486)'),   # [strong] p00vtzc7 3x
    ("Fugue in G minor (BWV.542) 'Great'", "Fugue BWV.542 'Great' (orig. for organ)"),   # [weak] p00t4lny 3x
    ('Four piano pieces: Barkarola; Song without words (Op.5); Butterfly (Op.6); Impromptu (Op.9)', 'Four piano pieces'),   # [strong] p00y7rs7 1x
    ('Agnus Dei - super ut-re-mi-fa-so-la', 'Agnus Dei from Missa ut-re-me-fa-sol-la for 7 voices'),   # [weak] p00y7s3b 2x
    ('Pièce en forme de Habanera', "Piece en forme d'habanera arr. Gillet for oboe and piano"),   # [strong] p036hv07 1x
    ('Keltic Suite (Op.29)', 'Keltic Suite'),   # [strong] p00v00hm 1x
    ('Fantasia in C minor (Op.53)', 'Harp Fantasia no 2 in C minor, Op 35'),   # [strong] p00sx16f 8x
    ('8 Danses exotiques version for 2 pianos', '8 Danses exotiques vers. for 2 pianos'),   # [strong] p0108lkh 3x
    ('Canzon II Septimi Toni a 8', 'Canzon II Septimi Toni a 8 from Sacrae Symphoniae'),   # [weak] p04rhpv5 4x
    ('Trio No.2 from Essercizii Musici, for Viola da gamba, Harpsichord obligato and continuo', 'Essercizii Musici (Trio No 2)'),   # [weak] p00rd4tf 3x
    ('Surte e la Notte - from Ernani MONO', 'Surta è la Notte (Recitative and aria: Surta è la Notte .... Ernani, Ernani)'),   # [strong] p04ry1z7 1x
    ('Orchestral excerpts from the Married Beau', 'The Married Beau, or The Curious Impertinent (incidental music), Z.603'),   # [strong] p06zchyd 3x
    ('Overture to The Bartered Bride (1870)', 'The Bartered Bride (Overture)'),   # [strong] p00r2zqq 3x
    ('Sonata in D major (Op.31 No.2)', 'Piano Sonata in D major, Op 31 no 2'),   # [strong] p00rj3s9 1x
    ('Vecer (Evening) - Symphonic Idyll', 'Vecer (Evening)'),   # [weak] p00rj45m 2x
    ('Sinfonia from Christmas Oratorio (BWV.248)', 'Sinfonia from Christmas Oratorio (BWV.248 Part 2)'),   # [weak] p0131p8q 2x
    ('Piano Trio in B flat (Op.97) "Archduke"', "Piano Trio No 9, 'Archduke'"),   # [weak] p00yzb5c 3x
    ('Verklärte Nacht (Op.4)', 'Verklarte Nacht for string sextet (Op.4)'),   # [weak] p011kb58 3x
    ('Tango', 'Tango (Lento) from "La revue de Cuisine" (1930)'),   # [strong] p00tdkmd 3x
    ('Concerto No.2 in G minor', 'Concerto per quartetto No 2 in G minor'),   # [weak] p00xx3jf 5x
    ('Csárdás from the comic opera Duch wójewody (The Ghost of Voyvode) (1875)', 'Csardas (The Ghost of Voyvode)'),   # [weak] p00tlxl8 4x
    ('Adagietto from Symphony No.5 in C sharp minor MONO', 'Symphony No 5 in C sharp minor (4th mvt, Adagietto)'),   # [strong] p067lxpw 1x
    ('From 6 Lieder (Op.18) arranged for choir', '6 Lieder, Op 18 (arranged for choir)'),   # [strong] p00vppv9 2x
    ('Concerto No.5 in A major', 'Concerto per quartetto for strings no 5 in A major'),   # [weak] p00v67lx 3x
    ('Trio No.6 from Essercizii Musici, for Transverse Flute, Viola da Gamba, and continuo', 'Trio no 6 from Essercizii Musici'),   # [weak] p00s0wgj 2x
    ('Nacht en Morgendontwaken aan de Nete', 'Night and Dawn at the Nete'),   # [strong] p0164yxp 1x
    ('Trio in E flat major (Op.12)', 'Trio for piano and strings (Op.12) in E flat major'),   # [weak] p011rv54 4x
    ('Phantasy', 'Phantasy vers. flute and piano'),   # [weak] p00sw8yj 3x
    ('Trio for violin, cello and piano (Op.11) in B flat major', 'Piano Trio in B flat major, Op 11'),   # [weak] p00qbz20 9x
    ('Orawa for string orchestra (1988) (Vivo)', 'Orawa for string orchestra'),   # [strong] p00wchmt 3x
    ('Quintet for flute, oboe, clarinet, horn & bassoon (Op.43)', 'Quintet for wind, Op 43'),   # [weak] p00ts1c2 5x
    ('Divertimento assai facile for guitar and fortepiano (J.207) (Op.38)', 'Divertimento assai facile for guitar and fortepiano (J.207)'),   # [strong] p00qydkg 3x
    ('La Vague et la cloche - for voice and piano (1871)', 'La Vague et la cloche'),   # [strong] p00vb52n 2x
    ('Pagodes orchestrated by Grainger', 'Pagodes [no.1 of Estampes] orch. Grainger [orig. for piano]'),   # [strong] p04zlchh 2x
    ('Scènes Breugheliennes - symphonic sketches', 'Scenes Breugheliennes (Scenes after Breughel)'),   # [strong] p00r79w2 1x
    ("13 Variationen über 'Es war einmal ein' (WoO 66)", "13 Variations on 'Es war einmal ein alter Mann' for piano (WoO.66) in A major"),   # [strong] p011mz73 1x
    ('Memories of a Summer Night in Madrid (Spanish Overture No.2)', "Souvenir d'une nuit d'ete a Madrid, 'Spanish overture no 2'"),   # [weak] p00qc500 9x
    ('Introduction and Variations on a theme from Rossini\'s "Mosè in Egitto" (Moses-Fantasie) (MS.23)', 'Moses Fantaisie (after Rossini) for cello and piano'),   # [strong] p012cpp4 2x
    ('Concerto for harpsichord (fortepiano) and orchestra in E flat major (G.487)', 'Concerto for harpsichord and orchestra (G.487) in E flat major'),   # [weak] p00qs6t5 2x
    ("No.2 in G minor, 'Hornpipe'", 'Hornpipe (Miniatures, Set 3, no 2)'),   # [strong] p00x0tvt 3x
    ('Totus tuus Totus tuus (Op.60)', 'Totus tuus, Op 60'),   # [weak] p00x8rd0 1x
    ('Overture in Bb major (D.470)', 'Overture in B flat major, D470'),   # [strong] p00shxj0 2x
    ('Idila (Op.25b) (1902)', 'Idila [Idyll], Op 25b'),   # [strong] p00wbwfp 1x
    ('Soirees de Vienne for piano, Op.56 - concert paraphrase on themes of Johann Strauss (Son)', 'Soiree de Vienne for piano, Op 56'),   # [strong] p00q9y9t 2x
    ("Quatre Intermèdes et Divertissements for Molière's comedy 'Amphitryon'", "Quatre Intermedes for Moliere's comedy 'Amphitryon' - Intermede IV, VB.27"),   # [strong] p00ty1fc 1x
    ("Gypsy Dance - from the idyll 'Jawnuta' (1850)", "Gypsy Dance from the idyll 'Jawnuta' (The Gypsies) [1850]"),   # [strong] p018008w 3x
    ('Fantasy on Two Ukrainian Themes', 'Fantasy on Two Ukrainian Themes for flute and orchestra'),   # [weak] p014c7l3 4x
    ("4 Madrigals for women's chorus", '4 Italian madrigals for female chorus'),   # [weak] p011kdsr 3x
    ('Il Tramonto', 'Il Tramonto - poemetto lirico'),   # [strong] p00qyzt2 1x
    ("Suite from 'Le Festin de l'Araignée (Op.17)", "Le Festin de l'araignee - symphonic fragments, Op 17"),   # [strong] p00qq180 3x
    ("Sonata Pian'e forte, for brass", "Sonata Pian'e forte alla quarta bassa a 8 (B.2.64) [1597 no.6] for wind"),   # [strong] p00yff3t 2x
    ('Overture - from Sicilian Vespers', 'Overture (Sicilian Vespers)'),   # [strong] p00yff7g 2x
    ('Sonata for transverse flute & basso continuo in D major - from Essercizii Musici', 'Sonata for transverse flute & basso continuo in D major'),   # [weak] p00sbbj9 4x
    ('Violin Concerto in E major (BWV.1042)', 'Concerto for violin and string orchestra no 2 in E major, BWV.1042'),   # [weak] p00x8rr2 3x
    ('Sonata for recorder & basso continuo in D minor - from Essercizii Musici', 'Recorder Sonata in D minor'),   # [weak] p010m86p 3x
    ('Rondo in A flat for piano and strings', 'Rondo for piano and strings in A flat major, H.18A'),   # [weak] p00t9v6j 7x
    ('Dances polonaises', 'Danses polonaises [orig for piano]'),   # [weak] p02v91bc 4x
    ('Suite from Platée (Junon jalouse)', 'Suite from Platee (Junon jalouse) - comedie-lyrique in three acts'),   # [weak] p00vty8s 3x
    ('The Four Seasons, Concertos Op.8 Nos.1-4', 'The Four Seasons'),   # [strong] p01ljns5 2x
    ("Quel guardo il cavaliere, Norina's Cavatina from Act 1, scene 2 of Don Pasquale", '"Quel guardo il cavaliere" (Norina\'s Cavatina from \'Don Pasquale\', Act 1 sc 2)'),   # [strong] p00y5221 3x
    ("Brünnhilde's Immolation Scene (Act III) - from Götterdämmerung (1876)", "Brunnhilde's Immolation -- from Gotterdammerung (1876)"),   # [strong] p06vqqnl 2x
    ('Le Bachelier de Salamanque (Op.20 No.2)', 'Le Bachelier de Salamanque, Op.20 no.1'),   # [strong] p0gmp6dn 2x
    ('Aria No.2 (Vocalise No.2), version for clarinet and piano', 'Aria, version for clarinet and piano'),   # [weak] p019sjk6 2x
    ('Images II', 'Images - set 2 for piano'),   # [strong] p00spbln 3x
    ('Concerto fragments for horn and orchestra in E flat (K.370b)', 'Concerto fragment for horn and orchestra in E flat (K.370b and K.371)'),   # [strong] p00s4fz0 1x
    ('Prelude No. 7 "Ce qu\'a vu le vent d\'ouest" from Preludes - book 1', "No 7 Ce qu'a vu le vent d'ouest (Preludes - book 1)"),   # [strong] p07x89f8 3x
    ('Sextet for piano and wind quintet in B flat major (Op.6) (in four movements)', 'Sextet for piano and wind quintet in B flat major, Op 6'),   # [weak] p00qc40j 2x
    ('Sonata in F major "Echo sonata"', "Sonata for 2 oboes, bassoon and continuo in F major, 'Echo sonata'"),   # [weak] p00rxjn2 2x
    ('Morpheus (1779); Broad Cove (1794); 2 Psalm-tunes: Kittery (1786) & Cobham (1794)', 'Two Psalm-tunes: Kittery (1786); Cobham (1794)'),   # [strong] p03fqf9z 1x
    ('Sola perduta abbandonata - from Act IV of Manon Lescaut', 'Aria: Sola, perduta, abbandonata - from Act IV of Manon Lescaut'),   # [strong] p037j84w 3x
    ("Overture (Suite) (TWV.55:G10) in G major 'Burlesque de Quixotte'", "'Burlesque de Quixotte' Suite in G minor, TWV.55:G10"),   # [strong] p0134nyt 3x
    ("L'Italiana in Algeri (Italian Girl in Algiers) - Opera in 2 Acts: Overture", "L'Italiana in Algeri (Overture)"),   # [strong] p00wnc09 1x
    ("Cantata 'Unschuld und ein gut Gewissen' for 4 voices, 2 oboes, strings and continuo - from the 'Französischen Jahrgang zum Sonntag Oculi 1715' (TWV.1:1440)", 'Cantata "Unschuld und ein gut Gewissen" for 4 voices'),   # [strong] p013qfhz 1x
    ('Zuola roda, zuola', 'Zuola roda, zuola [Turn spinning wheel, turn]'),   # [weak] p0mqh1qp 2x
    ("5 Chansons: 'Au joly boys'", '5 Chansons'),   # [weak] p014ml9b 2x
    ('Fantasie and variations on a theme of Danzi in B minor (Op.81) (vers. clarinet & string quartet)', 'Fantasia, Theme and Variations on a theme of Danzi in B flat Op.81'),   # [strong] p00y2h05 1x
    ('Symphony No. 8 in G major', 'Symphony No 8 in G major, Op 88'),   # [strong] p00ttkgh 1x
    ("Piano Trio in G major 'Premier Trio' (c.1879)", "Piano Trio in G major 'Premier Trio'"),   # [weak] p00r2qxk 7x
    ('Overture to Paria - an opera in 3 Acts (1859-69)', 'Overture (Paria)'),   # [strong] p00r304j 2x
    ("Feu d'artifice (Op. 4)", "Feux d'artifice [Fireworks]"),   # [strong] p00r30p3 2x
    ('Miniatures - No.8 Valse Russe for violin, cello and piano', 'Valse Russe (Miniatures set 3, no 1)'),   # [weak] p00x9j3b 1x
    ('Sonata in C major (Cantabile) (Kk.132)', 'Sonata in C major, Kk.132'),   # [strong] p00r0mqm 3x
    ("Lachrymae (Reflections on 'If my complaints could passions move' by Dowland) for viola and piano (Op.48)", 'Lachrymae (Reflections on a song of Dowland) for viola and piano, Op 48'),   # [strong] p030cyvw 2x
    ('Minuet for Strings', 'Minuet (from String Quintet G.275)'),   # [strong] p00tfxkm 1x
    ('Friede auf Erden for chorus (Op.13)', 'Friede auf Erden, Op.13'),   # [weak] p00w3y92 2x
    ('La Gazza Ladra - Overture', 'The Thieving Magpie (Overture)'),   # [strong] p00s0xrw 3x
    ('Krakowiak for orchestra [1949]', 'Krakowiak'),   # [strong] p010226c 2x
    ('Ave Regina Caelorum', 'Ave, regina coelorum for 5 voices'),   # [weak] p015fhz8 2x
    ('Irmelin prelude (RT.6.27) arr. from Preludes to Acts 1 & 3 of the opera', 'Irmelin (prelude)'),   # [strong] p00wms19 2x
    ('Ancient Airs and Dances - Suite no.3', 'Antiche Arie e Danze - Suite no 3 (1932)'),   # [strong] p00tpllb 1x
    ('Night covers up the rigid land for voice and piano', 'Night covers up the rigid land'),   # [strong] p00tpm96 2x
    ("Ballet music: 'Dance of the Blessed Spirits' - from 'Orphée et Euridice'", "Dance of the Blessed Spirits - dance music from 'Orphée et Euridice'"),   # [strong] p00th5n6 3x
    ('Eternal Father - from 3 Motets (Op.135 No.2)', 'Eternal Father - 3 Motets, Op 135 no 2'),   # [strong] p00typn2 3x
    ("Ballet music: 'Dances of the Blessed Spirits' - from 'Orphée et Euridice'", "Dance of the Blessed Spirits - dance music from 'Orphée et Euridice'"),   # [strong] p00th5n6 2x
    ('Mazurkas (No.1 in G major, Op.50/1; No.2 in C minor, Op.56/3; No.5 in A flat major, Op.17/3; No.4 in A minor, Op.17/4; No.5 in C Major, Op.67/3; No.6 in C major, Op.56/2)', 'Mazurkas (selection)'),   # [weak] p00th658 3x
    ('Piano Trio in C minor (Op.50 No.4) (1904) for violin, cello and piano', 'Piano Trio in C minor, Op 50 no 4'),   # [strong] p00th6b6 2x
    ('Four Intradas', 'Four Intradas for brass'),   # [weak] p00qtrdk 3x
    ('Morgonen', 'Morgonen (Morning)'),   # [strong] p025jdkr 3x
    ("Oce ná? hlapca Jerneja (The Bailiff Yerney's Prayer)", "Oce náš hlapca jerneja (Bailif Yerney's Prayer)"),   # [weak] p00xl264 2x
    ("J'ai pris amours a ma devise", "J'ay pris amours for ensemble"),   # [weak] p00q8rfr 4x
    ('German Dance Suite', 'Suite of German dances'),   # [weak] p00xtw8b 2x
    ('Sonata undecima for cornet, violin and bass continuo', 'Sonata undecima for cornett, violin and bass continuo'),   # [weak] p00z7k9r 2x
    ("Liebesträume (Rêve d'amour )", 'Liebestraume no 3 in A flat major (S.541)'),   # [strong] p00w2c64 2x
    ("String Quintet No.60 (G.324) (Op.30 No.6) in C major 'La Musica notturna delle strade di Madrid'", 'String Quintet No. 60 (G.324) (Op.30 No.6) in C major'),   # [weak] p0475hbw 3x
    ('Mercé, grido piangendo', 'Merce, grido piangendo - from Madrigali a cinque'),   # [weak] p00wmrxf 3x
    ('Trio No.8 from Essercizii Musici, for Recorder, Harpsichord obligato, and continuo', 'Trio no 8 from Essercizii Musici'),   # [weak] p00rbxrv 5x
    ('Overture - from Iphigenia in Aulide', 'Overture from Iphigenia en Aulide'),   # [strong] p035lkp4 3x
    ('Quintet in D major (Op.11 No.6) for flute, 2 violins, cello and harpsichord', 'Quintet in D major, Op.11, No.6 for flute, 2 violins, cello'),   # [weak] p00tcc8p 3x
    ('Fancies, toyes and dreames - A Giles Farnaby suite arr. Howarth for brass ensemble', 'Fancies, toyes and dreames'),   # [weak] p00zrpzf 2x
    ('Symphony No. 26 in D minor', 'Symphony no. 26 (H.1.26) in D minor "Lamentatione"'),   # [weak] p00z64c0 3x
    ('Sonata IV (Op.7)', 'Sonata IV for harp Op.7 No.4'),   # [strong] p00ym89w 2x
    ('Hexentanz (Witches Dance) (Op.17 No.2)', 'Hexentanz (Witches Dance) from 2 Fantasiestucke for piano (Op.17 No.2)'),   # [weak] p00ws5yz 3x
    ('Danza rituale del fuoco (Ritual Fire Dance) - from El Amor brujo', 'Ritual Fire Dance'),   # [strong] p00rbxms 3x
    ('Dixit Dominus - Psalmkonzert for 5 voices & basso continuo', 'Dixit Dominus'),   # [weak] p0133jjw 2x
    ("Sonata I, Op.5 (from '6 solos for the violoncello with a thorough bass' 1780)", 'Sonata Prima in G major (Op.5)'),   # [strong] p01fcz7x 3x
    ("Poudre d'or", "Poudre d'or, waltz for piano"),   # [strong] p00q8r8x 3x
    ('Le Tombeau de Couperin for orchestra [after nos. 1, 3, 5 & 4 of piano work]', 'Le Tombeau de Couperin'),   # [weak] p00vvz7f 3x
    ('Turcaria', 'Turcaria - Eine musikalische Beschreibung'),   # [weak] p010hzn9 4x
    ('Benedicto mensae', 'Benedictio mensae'),   # [strong] p010chw3 2x
    ("Ya pomnyu chudnoye mgnoven'ye (I recall a wondrous moment) (song)", "Ya pomnyu chudnoye mgnoven'ye (song)"),   # [strong] p00yr3pf 2x
    ('Overture from Die Leichte Kavallerie (Light cavalry) - operetta', 'The Light Cavalry - overture'),   # [strong] p00r4hrf 2x
    ("The Earle of Oxford's March (MB.28 No.93)", "The Earle of Oxford's March"),   # [strong] p012bylc 3x
    ('Requiem (Op.9)', 'Requiem, Op 9 [original version]'),   # [strong] p02c09v3 2x
    ('Sonate da Chiesa in D major (Op.1 No.12)', 'Sonata da chiesa in D, Op 1 No 12'),   # [weak] p00y52wd 2x
    ("Dixit Dominus à 8 - from 'Musiche sacre concernenti messa, e salmi concertati con istromenti, imni, antifone et sonate' (Venice 1656)", 'Dixit Dominus a 8'),   # [strong] p00sfrpx 1x
    ('Höstkväll (Op.38 No.1) for voice and orchestra', 'Hostkvall [Autumn Evening] (Op.38 No.1) for voice and orchestra'),   # [strong] p00z4sj1 2x
    ('William Lawes: Why so pale?', "Why so pale?; Bid me to live; 2 tunes new to Playford's Dancing Master"),   # [strong] p03f440n 3x
    ('Våren är ung och mild', 'Varen ar ung och mild (Spring is young and mild)'),   # [weak] p02sf0zl 2x
    ("Mentre, lumi maggior'", "'Mentre, lumi maggior' [from Il quinto libro di madrigali, 1568]"),   # [strong] p02rsrhk 2x
    ('Lza (song)', 'Lza [Tear] (song)'),   # [strong] p02kxjsw 2x
    ('Quartet for piano and strings (K.478) in G major', 'Piano Quartet in G minor, K478'),   # [strong] p00slnh9 2x
    ('7 Schubert Song transcriptions', '7 Schubert Song transcriptions from S.560, S.561 & S.565'),   # [strong] p00q45rq 1x
    ('Humoresque for Orchestra (second version 1928)', 'Humoresque for Orchestra (2nd version 1928)'),   # [strong] p00vjdrk 3x
    ('Cello Concerto in D major, Hob VIIb No.4', 'Concerto in D major H.7b.4 for cello, attrib. Costanzi'),   # [strong] p00rz78v 3x
    ("The Melancolic valse, from 'Marvel pieces for violin and piano'", "Melancolic valse (No.3 from 'Marvel Pieces')"),   # [weak] p00rz7yy 2x
    ('Passacaglia & Aria (presto) - from Concerto Pastorella in F major for 2 recorders, strings & continuo', 'Passacaglia & Aria (presto)'),   # [weak] p01h00yy 2x
    ('Soirée dans Grenade (No.2 from Estampes)', 'La Soiree dans Grenade, (No.2 from Estampes)'),   # [strong] p018sh2g 1x
    ('Quejas o la Maja y el Ruiseñor', 'La Maja y el Ruisenor - from Goyescas'),   # [strong] p00zrl20 1x
    ('Third Song-Wreath', 'Third Song-Wreath (From my homeland)'),   # [weak] p00r9n4g 2x
    ('Concerto No.5 in F minor', 'Concerto no 5 in F minor (from Sei Concerti Armonici 1740)'),   # [strong] p00r8cnx 1x
    ('Serenade No.1 in D major for violin & orchestra (Op.69a)', 'Serenade no 1 in D major, Op 69a'),   # [strong] p00q5tlf 2x
    ('5 Chansons: (Paris 1528-1538)', '5 Chansons'),   # [weak] p014ml9b 2x
    ("The Mermaid's song (H.26a.25) from 6 Original canzonettas", "The Mermaid's song, H.26a.25"),   # [strong] p00vjyxz 2x
    ("No.2 in G minor, 'Hornpipe' - from 'Miniatures'", 'Hornpipe (Miniatures, Set 3, no 2)'),   # [strong] p00x0tvt 1x
    ('O vos omnes for 5 voices (W.8.40)', 'O vos omnes for 5 voices (W.8.40) [1603a]'),   # [strong] p05dhktj 2x
    ('Wedding March - from Pieces vers. for piano (Op.3b No.2)', 'Haamarssi (Wedding March) (Op.3b No.2)'),   # [strong] p02r8qj1 1x
    ('Sonetto 292', 'Sonetto 292 (Sonnet 292 - Petrarch)'),   # [weak] p03p37gd 3x
    ('Sonata for strings No.5 in E flat major', 'String Sonata no 5 in E flat major'),   # [weak] p00tkb8x 7x
    ('Pohjarannik', 'Pohjarannik (The North Coast) - poem for bass soloist, male choir and organ'),   # [strong] p02xgnvh 1x
    ('Elegy for violin and piano', 'Elegy from Five Pieces for two violins and piano, arr. for solo violin and piano'),   # [weak] p01rzbjb 6x
    ('Meditation', 'Meditation for violin, cello and piano'),   # [strong] p0mq1yyq 3x
    ("Kyrie and Gloria from 'Missa São Sebastião'", "Kyrie and Gloria from 'Missa Sao Sebastiao' **DO NOT USE**"),   # [strong] p00v1k4d 2x
    ("'O let me weep'", "Aria 'O let me weep' from the Fairy Queen"),   # [strong] p00tndxr 1x
    ('Der Sturm', 'Der Sturm (The Storm) - madrigal for chorus and orchestra (H.24a.8)'),   # [strong] p00zns2w 1x
    ('Adèle', 'Adele (song)'),   # [strong] p00yr3ny 1x
    ('Exsurgat Deus', 'Exsurgat Deus - motet for double chorus'),   # [weak] p0299ddw 1x
    ("Kochanka hetmanska -- overture to Lucjan Siemienski's stage play (1854)", "The Commander-in-Chief's Lover (overture)"),   # [strong] p00x2kx7 1x
    ("No.12 Feux d'artifice (Fireworks): Modérément animé - from Preludes Book II", "No.12 Feux d'artifices - from Preludes Book II"),   # [strong] p00wgycj 1x
    ('Zigeunerweisen (Op.20)', 'Zigeunerweisen, Op 20 vers. for violin and orchestra'),   # [weak] p0163bkn 2x
    ('La Vie antérieure - for voice and piano (1884)', 'La Vie anterieure [The Former Life] for voice and piano [1884]'),   # [strong] p00ws4gw 1x
    ('Concerto in B flat major (Op.10 No.2)', 'Concerto grosso for 2 violins, strings and continuo in B flat major, Op 10 no 2'),   # [strong] p00v00z3 3x
    ('Arabesque No 2', 'Arabesque No.2 (Allegretto scherzando) (no.2)'),   # [strong] p02k359k 2x (synthetic L-less pair: Lesure scoping)
    ("The Doll's Song (from 'The Tales of Hoffmann')", "Les Oiseaux dans la charmille - The Doll's Song"),   # [strong] p00wp69x 2x
    ('Marionettes Suite (Op.1)', 'Marionetteja [Marionettes] Suite (Op.1) [orig. for piano duet]'),   # [strong] p0983knb 3x
    ('Öregek', 'Oregek (The Aged)'),   # [strong] p01fgjwc 2x
    ('Stimmungsbilder (Op.9) - No.2 An einsamer Quelle', 'An einsamer Quelle - from Stimmungsbilder, Op 9 no 2'),   # [strong] p03w31bg 1x
    ('Lamento della ninfa (from libro VIII de madrigali - Venice 1638)', 'Lamento della ninfa'),   # [weak] p00qyzjq 1x
    ("Hor che Apollo è a Theti in seno'", 'Hor che Apollo - Serenade for soprano, 2 violins & continuo'),   # [weak] p00qyznw 1x
    ('Finnlandische Volksweisen for piano duet (Op.27)', '2 Finnlandische Volksweisen (Finnish folksong arrangements) for 2 pianos, Op 27'),   # [strong] p00t30xf 1x
    ('Sonate da Chiesa in F major (Op.1 No.1)', 'Sonata da chiesa in F major, Op 1 no 1'),   # [weak] p00w58kf 3x
    ('Des pas sur la neige', 'Des pas sur la neige (Preludes Book 1, no 6)'),   # [strong] p02zt6yx 1x
    ('Phantasiestucke for piano (Op.12) - no.7; Traumes Wirren', "Traumes Wirren, from 'Fantasiestücke, Op 12'"),   # [strong] p0m166vb 1x
    ('Jauchzet dem Herren alle Welt - cantata for voice, 2 violins, and continuo', 'Jauchzet dem Herren alle Welt - cantata for voice, 2 violins, [bassoon] and continuo'),   # [strong] p01cpb5v 1x
    ("Nachtstück from 'Der ferne Klang'", 'Nachtstuck (orchestral interlude) from "Der ferne Klang" (Opera in 3 acts)'),   # [strong] p02nxn1s 1x
    ("L'invitation au voyage - for voice and piano (1870)", "L'invitation au voyage [Invitation to a Journey]"),   # [strong] p00s61c5 1x
    ('Forelle (S.564) transcribed for piano 2nd version', 'Die Forelle (S.564)'),   # [strong] p00rm05n 2x
    ('Sonatine for Harp (1965)', 'Sonatina for Harp (1965)'),   # [strong] p03ry12l 3x
    ("Three motets from 'Sacrae Cantiones' - Quam pulchra es; Quemadmodum desiderat; Panis angelicus", "Three motets ('Sacrae Cantiones')"),   # [weak] p01c4nf7 2x
    ('Sonata VI (BWV.530) in G (BB A-5, c.1929)', 'Sonata no. 6 in G major BWV.530 for organ (trans. for piano)'),   # [strong] p00rpfz7 1x
    ("The Sorcerer's apprentice", "The Sorcerer's apprentice - symphonic scherzo for orchestra"),   # [weak] p00ws5lz 2x
    ('The Melancolic valse', "Melancolic valse (No.3 from 'Marvel Pieces')"),   # [weak] p00rz7yy 3x
    ('Korsholma', 'Korsholma - Symphonic Poem'),   # [strong] p02n6sz8 3x
    ('Four Minuets for orchestra (K.601) - No.1 in A major; No.2 in C major; No.3 in G major; No.4 in D major', 'Four Minuets for orchestra, K601'),   # [strong] p00v8g5b 2x
    ('Symphony No 3 in B flat Major (Op.18) for small orchestra', 'Symphony no 3 in B flat major, Op 18'),   # [strong] p01fzkdw 1x
    ('Toccata', 'Toccata for harpsichord'),   # [strong] p053qfpp 2x
    ('2 Songs: Själens frid (Peace of mind) (Op.37 No.2) ; Kärlek (Love) (Op.37, No.5)', '2 Songs: Sjalens frid & Karlek (Op.37 Nos. 2 & 5)'),   # [strong] p02t1xwh 1x
    ('It was a lover and his lass', 'It was a lover and his lasse'),   # [strong] p017hkqw 2x
    # (Re-pointed 2026-07-16: the bare-English target became a variant itself
    # in the Sibelius pass -- both now go to the Swedish-titled canonical.)
    ('On a balcony by the sea (Op.38 No.2) arr. for voice & orchestra',
     'Pa verandan vid havet (On a balcony by the sea) (Op.38 No.2)'),   # [strong] p01brpv9 2x
    ('Lauda Jerusalem (Psalm 147)', "Lauda Jerusalem (Psalm 147, 'How good it is to sing praises to our God')"),   # [weak] p00s561k 2x
    ('Vattene pur, crudel - from Il terzo libro de madrigali a cinque voci (Venice 1592)', 'Vattene pur, crudel'),   # [strong] p01jcgps 1x
    ('Toccata in G (BB.A-4i, 1927)', 'Toccata in G'),   # [strong] p04p9zyh 1x
    ('Sonata da chiesa in E minor (Op.3 No.5)', 'Sonata da chiesa in D minor, Op 3 no 5'),   # [weak] p00w2bvs 2x
    ("Three motets from 'Sacrae Cantiones'", "Three motets ('Sacrae Cantiones')"),   # [strong] p01c4nf7 3x
    ('Ave, dulcissima Maria for 5 voices', 'Ave dulcissima Maria'),   # [strong] p03czl37 1x (retargeted to final past the [1603a] intermediate)
    ('A Song at Sunset (Walt Whitman)', "**DON'T USE** A Song at Sunset, Op 138b"),   # [strong] p00y34y2 1x
    ('Berceuse romantique (Op.9) - for violin and piano', 'Berceuse romantique, Op 9'),   # [strong] p00vtz8h 1x
    ('Méndez Csárdás', 'Csárdás for trumpet and piano'),   # [strong] p0108kst 1x
    ("Sonata quasi una fantasia for piano (Op.27 No.2) in C sharp minor, 'Moonlight' (Piano sonata no.14)", "Sonata quasi una fantasia for piano (Op.27 No.2) in C sharp minor, 'Moonlight'"),   # [strong] p014kyzn 1x
    ('Dances of Galanta vers. for piano', 'Dances of Galanta (Galantai tancok) arr. for piano'),   # [strong] p00rf41y 1x
    ('Concertino for piano and chamber orchestra (Op.3)', "Concertino for piano and chamber orchestra, Op 3 'en style ancien'"),   # [strong] p00zrqfb 2x
    ('2 Finnish folksong arrangements for piano duet (Op.27)', '2 Finnlandische Volksweisen (Finnish folksong arrangements) for 2 pianos, Op 27'),   # [strong] p00t30xf 2x
    ('Ballet music from Otello, Act III (written for Paris production of 1894)', 'Ballet music from Otello, Act III'),   # [strong] p00qq1rk 1x
    ("Pastorale for string trio (from the film 'Babette's Feast')", 'Pastorale for String Trio'),   # [weak] p00xl129 3x
    ('Overture from Aladdin', 'Aladdin (Overture)'),   # [strong] p018fpqh 3x
    ('Nocturne for harp', 'Nocturno for harp'),   # [strong] p00rlxds 3x
    ('Concerto for oboe and strings in F major reconstr. From BWV.1053 (originally keyboard & strings, after BWV.49 & BWV.169)', 'Oboe Concerto in F major reconstructed from BWV.1053'),   # [strong] p014xv8m 2x
    ("O primavera & O dolcezze amarissime d'Amore", "O primavera for solo soprano and bc & O dolcezze d'Amore"),   # [weak] p00rz597 3x
    ("Chant de l'éternelle aspiration, première partie du tryptique symphonique 'Chants éternels' (Op.10) (1904-1906)", "Chant de l'eternelle aspiration"),   # [weak] p013qgg9 3x
    ('The Swans (Op.15)', 'The Swans'),   # [strong] p00zt782 2x
    ("Valse Boston: 'Wer hat die Liebe uns ins Herz gesenkt?' - from the operetta Das Land des Lächelns (Land of Smiles)", "Valse Boston: 'Wer hat die Liebe uns ins Herz gesenkt?'"),   # [strong] p01y0lnh 2x
    ('Overture to Pskovitjanka', 'Overture to The Maid of Pskov'),   # [strong] p00vjypr 1x
    ('Secondo Trietto', 'Secondo Trietto [Vivace - Andante - Vivace]'),   # [weak] p02jdd8h 2x
    ('Trio (Op.3)', 'Trio for clarinet, cello and piano Op 3'),   # [weak] p00qxwpf 2x
    ("Sonata XII from 'Sacroprofanus concentus musicus'", "Sonata No 12, 'Sacroprofanus concentus musicus'"),   # [weak] p017z88b 3x
    ("Mass in B flat major, 'Krecovicka' (Kyrie; Gloria; Credo; Sanctus; Benedictus; Agnus Dei)", 'Křečovice Mass for chorus, strings and organ in B flat major'),   # [strong] p00t4jx3 1x
    ('Sonata for Piano and Violin No.6 in A major (Op.30 No.1)', 'Violin Sonata no 6 in A major, Op 30 no 1'),   # [strong] p00rszwm 1x
    ("Capriccio Brillante for symphony orchestra on the theme of 'Jota Aragonesa'", "Capriccio brillante on the theme 'Jota Aragonesa'"),   # [strong] p00s4fnr 1x
    ('5 Hungarian Dances - Nos. 17 in F# minor; 18 in D major; 19 in B minor; 20 in E minor; 21 in E minor', '5 Hungarian dances (nos 17-21) orch. Dvorak (orig. pf duet)'),   # [strong] p00xk62g 2x
    ('La Paraza', 'La Paraza [from Pieces de viole (5e livre) (Paris - 1725)]'),   # [strong] p02sjj67 2x
    ('Dixit Dominus (RV.595)', 'Dixit Dominus in D major, RV.595'),   # [strong] p00q59t8 1x
    ("Une Barque sur l'océan orch. from no.3 of 'Miroirs'", "Une Barque sur l'ocean"),   # [strong] p00v1jpz 1x
    ('Psalm 99', "Or est maintenant, l'eternel regnant (Psalm 99)"),   # [strong] p011myld 1x
    ('Meditation (dedicated by composer to his son Edgar)', 'Meditation for violin, cello and piano'),   # [strong] p0mq1yyq 1x
    ("Prelude and Fugue in Eb Major 'St. Anne' (BWV.552) from the Clavierübung, Volume III (1739)", "Prelude and fugue in E flat major BWV.552, 'St Anne'"),   # [strong] p00s50y9 1x
    ('2 Songs -The most beautiful songs (Op.4); Under the sycamore', '2 Songs: Najpiekniejsze pionski (Op.4) & Pod jaworem'),   # [strong] p00s5554 2x
    ('Maske (MB.24.31) & Fantasia (MB.24.12)', 'Maske & Fantasia from the Fitzwilliam Virginal Book'),   # [strong] p00s565x 1x
    ('Slavonic Dance in D flat major (Op.72 No.4)', 'Slavonic Dance No 12 in D flat major Op 72 No 4'),   # [strong] p00s56p2 1x
    ('Beatus vir (KBPJ.3) for soprano, alto, bass, 2 violins & basso continuo', 'Beatus vir , KBPJ 3'),   # [strong] p017zzxt 1x
    ("Complaint 'Fortune my foe'", 'Fortune my foe'),   # [weak] p07z1vqc 2x
    ('Leivo (Op.138 No.2)', 'Leivo [Skylark], Op 138 no 2'),   # [strong] p07fdhy4 1x
    ('Symphony in D major', "Symphony in D major 'Pastorella'"),   # [strong] p00vjywk 1x
    ('Suite from Platée', 'Suite from Platee (Junon jalouse) - comedie-lyrique in three acts'),   # [weak] p00vty8s 2x
    ('Variations on "Deandl is arb auf mi\'" for string trio', 'Variations on "Deandl is arb auf mi\'"'),   # [weak] p0135jds 3x
    ("Wellingtons Sieg (Op.91) 'Battle Symphony'", 'Battle symphony'),   # [strong] p017svsv 2x
    ('Córdoba (Op.232 No.4)', 'Cordoba (Nocturne) from Cantos de Espana, Op 232 no 4'),   # [strong] p00r68s5 2x
    ('The bells of Berhall church (Op.65b)', 'Kallion kirkon kellosavelma (The Bells of Kallio Church) (Op.56b)'),   # [strong] p00ts61b 2x
    ('Extase', 'Extase - for voice and piano'),   # [strong] p01nlt3l 2x
    ('Psalm 114 (from the Genevan Psalter)', 'When Israel came out of Egypt, (Psalm 114, Genevan Psaltar)'),   # [weak] p0540r9m 2x
    ('Quintet for clarinet and strings in B flat major (Op.32)', 'Clarinet Quintet (Introduction, theme and variations) in B flat major, Op 32'),   # [strong] p00rbyf2 1x
    ('Viri sancti gloriosum sanguinem', 'Motet: Viri sancti gloriosum sanguinem'),   # [strong] p0fhpglf 1x
    ('Pavan for 4 instruments in G minor (Z.752)', 'Pavan for 4 instruments in G minor'),   # [strong] p058wfbm 2x
    ('5 popular Greek Songs', 'Cinq melodies populaires grecques [5 popular Greek Songs]'),   # [strong] p00v2v14 2x
    ('Fairytale, Fantastic Overture (1848)', 'Bajka (The fairy tale) - concert overture'),   # [strong] p016n4ng 2x
    ('The Son of the Slave (Op.14) (1910)', 'Orjan poika [The Son of the Slave] Op.14 (1910)'),   # [strong] p01bdm6s 1x
    ('Wiosenno', 'Wiosenno [In a Spring Mood]'),   # [strong] p00s2k1h 1x
    ('A sequence from the Tenebrae responsaries', "Excerpts from 'Tenebrae Responses and Lamentations'"),   # [weak] p0dx1298 1x
    ('Les titans (Op.71 No.2) (T.Saint-Félix)', 'Les titans, Op 71 no 2'),   # [weak] p01g0mps 2x
    ('7 Schubert Song transcriptions -- Am Meer; Die Stadt; Erstarrung; Frühlingslaube; Der Müller und der Bach; Aufenthalt; Der Doppelgänger', '7 Schubert Song transcriptions from S.560, S.561 & S.565'),   # [strong] p00q45rq 2x
    ('H��marssi (Wedding March) - from Pieces vers. for piano (Op.3b No.2)', 'Haamarssi (Wedding March) (Op.3b No.2)'),   # [strong] p02r8qj1 1x
    ('Passacaglia & Aria (presto) - from Concerto Pastorella in F major', 'Passacaglia & Aria (presto)'),   # [weak] p01h00yy 1x
    ('Waltzes - Suite (1920) vers. for 2 pianos', 'Waltzes - Suite arr. Prokofiev'),   # [strong] p0913ctm 2x
    ('An Mignon (D.161)', 'An Mignon (D.161), Op.19 No.2 (To Mignon)'),   # [strong] p039k4sb 1x
    ('Rondeau - Soeur Monique', 'Rondeau: Soeur Monique from Pieces de Clavecin (1722)'),   # [strong] p013s1hw 2x
    ('1st movement from Sinfonia a 8 Concertanti in A minor (ZWV.189)', '1st movement (Allegro) from Sinfonia a 8 Concertanti in A minor, ZWV.189'),   # [weak] p00xkp4m 2x
    ('Chants populaires', 'Chants populaires (Popular Songs)'),   # [strong] p00sdzv8 3x
    ('Jägers Abendlied (D.368) (Op.3 No.4)', "Jagers Abendlied (D.368) (The huntsman's evening song)"),   # [strong] p00rlh1k 1x
    ('Sola, perduta, abbandonata', 'Aria "Sola perduta abbandonata" - from Act IV of \'Manon Lescaut\''),   # [strong] p068z21b 2x
    ('O vis aeternitatis (Responsorium) - for voice, female chorus, 2 fiddles, organistrum', 'O vis aeternitatis (Responsorium) for female voice'),   # [weak] p02g1rb7 2x
    # --- Hildegard von Bingen curation batch (2026-07-19): recording-anchored
    # + segment-dominant folds. The standalone "Alma Redemptoris Mater" trio is
    # the ANONYMOUS Marian antiphon appearing on Hildegard discs (attribution
    # preserved as-written); its bare key is shared by Ockeghem/Palestrina so it
    # is target-only, NEVER an LHS (blast-radius rule). Keep-splits: the
    # Spiritus Sanctus 3-work medley, the St Ursula excerpts pair, and
    # standalone-Alma vs the combined '& Ave Maria' track. ---
    ('O vis aeternitatis (Responsorium)', 'O vis aeternitatis (Responsorium) for female voice'),  # Hildegard (rec p02g1rb7 spans both; segment title is the female-voice form)
    ('Alma Redemptoris Mater; Ave Maria, O auctrix vite', 'Alma Redemptoris Mater & Ave Maria, O auctrix vite'),  # Hildegard (rec p019my77; ';' vs '&' separator)
    ('Alma Redemptoris Mater; Ave Maria, O auctrix vite - Responsorium for voice, chorus, 2 fiddles', 'Alma Redemptoris Mater & Ave Maria, O auctrix vite'),  # Hildegard (rec p019my77; scoring tail)
    ('O clarissima Mater', 'O clarissima Mater (respond)'),  # Hildegard (bare 1x -> dominant/segment spelling)
    ('1. Alma Redemptoris Mater', 'Alma Redemptoris Mater'),  # Hildegard discs (movement-number prefix; anon antiphon)
    ('1. Alma Redemptoris Mater (Marian Antiphon for chorus, 10.jh./cent.Anon)', 'Alma Redemptoris Mater'),  # Hildegard discs (annotation junk)
    ('Suite Champêtre (Op.98b) (Pièce charactéristique ; Mélodie élégiaque ; Danse )', 'Suite Champetre, Op 98b'),   # [strong] p00r9qwh 1x
    ('When David heard (O my son Absalom) - for 6 voices', 'When David heard (O my son Absalom)'),   # [weak] p02fd6k1 2x
    ('Trio No.4 from Essercizii Musici, for Transverse Flute, Harpsichord obligato and continuo', 'Trio No 4 (Essercizii Musici)'),   # [weak] p00q8rgw 4x
    ('Capriccio Espagnole', 'Capriccio espagnol Op.34'),   # [strong] p00sj5kd 2x
    ('Harmonia Caelestis', 'Harmonia Caelestis (excerpts)'),   # [strong] p01xf4j8 3x
    ("No.12 Feux d'artifice (Fireworks) from Preludes Book II", "No.12 Feux d'artifices - from Preludes Book II"),   # [strong] p00wgycj 1x
    ("La Calinda - concert version for orchestra from 'Koanga'", 'La Calinda'),   # [strong] p00sdcnb 3x
    ('El Dorado', 'El Dorado for harp and strings'),   # [strong] p00txgn7 1x
    ('Sonatina No.2 in C minor', 'Sonatina no 2 in C major'),   # [strong] p07pkskt 2x
    ('Sinfonia in D major (Op.5 No.1)', 'Sinfonia a piu strumenti (Favourite overture) (Op.5 No.1) in D major'),   # [strong] p02c0ll2 3x
    ("Sinfonischer Prolog zu Heinrich Heine's Tragödie 'William Ratcliff' [Symphonic prologue to Heinrich Heine's tragedy 'William Ratcliffe']", "Symphonic prologue to Heinrich Heine's tragedy 'William Ratcliffe'"),   # [strong] p00tvwlt 2x
    ('Surte e la Notte - from Ernani', 'Surta è la Notte (Recitative and aria: Surta è la Notte .... Ernani, Ernani)'),   # [strong] p04ry1z7 2x
    ("Un bel dÃ¬ (One Fine Day) (arranged for orchestra) - from 'Madame Butterfly'", 'One Fine Day (Madame Butterfly)'),   # [strong] p06vx43n 2x
    ('Lahko Noc', 'Lahko Noc (Goodnight)'),   # [strong] p0423fzp 2x
    ("Rondo brillante in E flat 'La gaité for piano' (J.252) (Op.62)", "Rondo brillante in E flat 'La gaieté', Op 62, J252 [1819]"),   # [strong] p00t562g 1x
    ('A song about King Stephen', 'Hymn to King Stephen'),   # [strong] p00xkzq1 1x
    ('Miroir de Peine - song-cycle for voice and orchestra', 'Miroir de Peine - song-cycle (1933) vers. voice and orchestra'),   # [strong] p00t6t62 2x
    ('Singet dem Herrn', 'Singet dem Herrn - motet for double chorus & bc'),   # [weak] p019k32s 2x
    ('Hungarian Rhapsody No.1 for Orchestra in F minor (also known as No.14 in F minor for piano, S.244)', 'Hungarian Rhapsody no 1 for orchestra in F minor'),   # [strong] p00szqwp 1x
    ('Sonata for violin & basso continuo in F major - from Essercizii Musici', 'Violin Sonata in F major'),   # [strong] p00xr1ls 1x
    ("Elegie d'automne - from 3 pieces pour piano (Op.15)", "Elegie d'automne, Op 15"),   # [strong] p027kg9x 3x
    ('Pan and Syrinx (Op.49) (symphonic poem)', 'Pan og Syrinx (Pan and Syrinx), Op 49 [FS.87]'),   # [strong] p00t5trp 1x
    ('Dance of the Persian Slaves - from the Opera Khovanshchina (Act IV, Scene 1)', 'Dance of the Persian Slaves (Khovanshchina)'),   # [strong] p00z3fxd 1x
    ("Symphony No.44 in E minor, 'Trauer' and trio", "Symphony no 44 in E minor, 'Trauer'"),   # [strong] p00sy465 1x
    ('Nocturne (Andante) - 3rd movement from Quartet for strings no.2 in D major arr. Sargent for orchestra', 'Notturno (Andante) - 3rd mvt from String Quartet no 2 in D major'),   # [strong] p021hphx 2x
    ("Valse de l'Opera Faust", 'Waltz (Faust)'),   # [strong] p011qr5z 1x
    ('Selection from Vespro della Beata Vergine', 'Vespro della Beata Vergine (excerpts)'),   # [strong] p0mrv2fr 1x
    ("Le Coq d'Or (concert suite)", 'The Golden cockerel - suite'),   # [strong] p03qcydc 1x
    ('Vesipatsas (Waterspout) - ballet music (Scene 1 & 2)', 'Vesipatsas (Waterspout) - ballet music'),   # [strong] p04qf5l1 2x
    ('Quartet No.1 in A minor (Wq.93/H.537)', 'Quartet for flute, viola and continuo in A minor, Wq 93, H537'),   # [weak] p00ybr0s 3x
    ('Arrival of the Guests (Minuet) from the ballet suite Romeo and Juliet', 'Arrival of the Guests (Minuet) from Romeo and Juliet ballet suite'),   # [strong] p059hv7m 1x
    ('No.10 La Cathédrale engloutie - from Preludes Book One.', 'La cathédrale engloutie (No 10 from Preludes - Book 1)'),   # [strong] p00xr1l8 3x
    ('La Peri', 'La Peri - poeme danse'),   # [strong] p01fd0kq 2x
    ('Noveletta (Op.82 No.2)', 'Noveletta for orchestra, Op 82 no 2'),   # [strong] p00rcgwl 2x
    ("Gott, wie gross ist deine Güte (BWV.462); Dich bet' ich an, mein höchster Gott (BWV.449); Dir, dir, Jehova, will ich singen (BWV.452); O liebe Seele, zieh' die Sinnen (BWV.494); Vergiss mein nicht, mein allerliester Gott (BWV.505); Ich halte treulich still und liebe meinen Gott (BWV.466)- 6 Chorales from the Schemelli Collection", 'Six Chorales from the Schemelli Collection'),   # [strong] p00s0x73 2x
    ('The Maiden and the Nightingale - from Goyescas: 7 pieces for piano (Op.11 No.4)', 'La Maja y el Ruisenor - from Goyescas'),   # [strong] p00tdhnx 1x
    ("Suite from 'The Lavender Hill Mob'", 'The Lavender Hill Mob (Suite)'),   # [strong] p00tdjx2 3x
    ('Concerto per quartetto for strings No.3 in E flat major', 'Concerto per quartetto no 3 in E flat major'),   # [weak] p00tdkjr 5x
    ('3 Psaumes de David (Op.339) - No.2 Psalm 50 - No.3 Psalms 114 and 115', '3 Psaumes de David for chorus, Op 339'),   # [strong] p00wqlwr 1x
    ('Scherzo', 'Scherzo for double bass and piano'),   # [strong] p02pyq4n 2x
    ('Sonata à 8', 'Sonata à 8 - from "Musiche sacre concernenti messa\' (Venice 1656)'),   # [strong] p02tf0k4 1x
    ('Sonata No.7 for 2 violins and continuo in E minor (Z.796) (1683)', 'Sonata No 7 for 2 violins in E minor, Z796'),   # [strong] p011rvd3 1x
    ('Offertur ad duos choros (Ms. Kremsier)', 'Offertur ad duos choros in A major(Ms. Kremsier)'),   # [weak] p00svfqc 1x
    ('Vorrei spiegarvi, oh Dio (K.418)', 'Vorrei spiegarvi, oh Dio - aria for soprano and orchestra, K.418'),   # [strong] p02mgd7f 2x
    ('Der Vogelfänger bin ich ja - from Die Zauberflöte Act 1 (K.620)', 'Aria: Der Vogelfanger bin ich ja - from Die Zauberflote'),   # [strong] p07vvf28 1x
    ('Duet: Bei Männern welche Liebe fühlen, from Die Zauberflöte Act 1 (K.620)', 'Duet: Bei Mannern, from Die Zauberflote'),   # [strong] p02ggw9r 1x
    ('Der Hölle Rache kocht in meinem Herzen - from Die Zauberflöte Act 2 (K.620)', 'Queen of the Night: Die holle Rache'),   # [strong] p040p6rc 1x
    ('Recitative & Aria: Giunse alfin il momento & Deh vieni, non tardar - from Le Nozze di Figaro (K.492)', "Le Nozze di Figaro, Act 4: Susanna's aria 'Deh vieni, non tardar'"),   # [strong] p00t560t 1x
    ('Horn Concerto in E flat (K.495)', 'CHECK BEFORE USING Horn Concerto No 4 in E flat major, K 495'),   # [strong] p00sbq2s 2x
    ("Un'aura amorosa - Ferrando's aria from Così fan tutte (K.588) Act 1", 'Aria: "Un\'aura amorosa" from the opera \'Così fan tutte\' (K.588), Act 1'),   # [strong] p00vlxvw 1x
    ("Donne mie, la fate a tanti - Guglielmo's aria from Act II of Così Fan tutte (K.588)", '"Donne mie la fate a tanti" (aria from "Cosi fan tutte")'),   # [strong] p0mnc358 1x
    ('Porgi amor qualche ristoro - from Le Nozze di Figaro (K.492)', 'Porgi amor qual que ristoro from Le Nozze di Figaro (K.492)'),   # [strong] p03mzx9x 1x
    ('Sinfonia concertante for oboe, clarinet, horn, bassoon and orchestra (K.297b) in E flat major attrib. unknown hand [from lost Mozart original K.Anh.C 14.01] (K.297b)', 'Sinfonia concertante in E flat major, K297b'),   # [strong] p00z390l 1x
    ("12 Variations in C for piano on 'Ah, vous dirai-je, Maman' (K.265)", "12 Variations on 'Ah, vous dirai-je, Maman', K265"),   # [strong] p01rqflf 1x
    ('On Hearing the First Cuckoo in Spring - from Two Pieces for Small Orchestra (1911/12)', 'On hearing the first cuckoo in spring for orchestra (RT.6.19) (1911/12)'),   # [strong] p00q4bm7 1x
    ('Omnia tempus habent - motet for 8 voices', 'Omnia tempus habent'),   # [strong] p00xx66w 2x
    ('Invitation to the Dance Piano (Op.65)', 'Aufforderung zum Tanz [Invitation to the Dance]'),   # [strong] p00sj1nq 1x
    ('Regina coeli (K.276) in C major', 'Regina coeli for soloists SATB, chorus, orchestra & organ (K.276) in C major'),   # [strong] p02kdx7n 1x
    ('Elö-Játékok (Pre-Games)', 'Elö-Játékok (Pre-Games) (extracts)'),   # [strong] p07z1pvs 1x
    ('Overture in the Italian Style (D.590) [ie NOT 591]', "Overture in D major 'In the Italian Style', D.590"),   # [strong] p00qxy2m 2x
    ('From 44 Duos for 2 violins, Sz.98/4: Vol.4', '44 Duos for 2 violins, Vol 4 (excerpts)'),   # [strong] p01302pc 1x
    ('6 Deutsche 9German dances) for piano (D.820)', '6 Deutsche Tänze, D.820'),   # [strong] p00sfrfh 1x
    ('Kung Liljekongvalje', 'Kung Liljekonvalje [King Lily of the Valley]'),   # [strong] p00tw39y 1x
    ("If a beautiful woman says to you 'perhaps'- from the film 'Das Lied der Wüste' (1939)", "Sagt dir eine schone Frau, 'Vielleicht' - from the film 'Das Lied der Wüste'"),   # [strong] p0hlkj68 1x
    ('Duet: Fra gli amplessi - from Così fan tutte', 'Duet: Fra gli amplessi (Cosi fan tutte)'),   # [strong] p00wchvn 1x
    # Zemlinsky, Die Seejungfrau (The Little Mermaid) -- ONE symphonic fantasy
    # aired under ~12 German/English title variants; token-sort can't bridge the
    # cross-language token sets, so fold all to the fullest bilingual form.
    # The old target ("The Little mermaid - Fantasy for orchestra after Andersen")
    # was a PHANTOM key -- no current title produces that English-only form -- so
    # the "Fantasie" airings sat split from the "Seejungfrau ... after Andersen"
    # ones; retargeted here to a live key. (2026-07-15)
    ('Die Seejungfrau - Fantasie for Orchestra (1902/3)', 'Die Seejungfrau (The Little mermaid) - Fantasy for orchestra after Andersen'),   # was -> phantom English-only key
    ('Die Seejungfrau',                                              'Die Seejungfrau (The Little mermaid) - Fantasy for orchestra after Andersen'),
    ('Die Seejungfrau (The Little mermaid) - Fantasy for orchestra', 'Die Seejungfrau (The Little mermaid) - Fantasy for orchestra after Andersen'),
    ('The Little mermaid',                                           'Die Seejungfrau (The Little mermaid) - Fantasy for orchestra after Andersen'),
    ('Die Seejungfrau (The Little Mermaid) – fantasy after Andersen','Die Seejungfrau (The Little mermaid) - Fantasy for orchestra after Andersen'),
    ('Die Seejungfrau (The Little mermaid)',                         'Die Seejungfrau (The Little mermaid) - Fantasy for orchestra after Andersen'),
    ('Die Seejungfrau (The Mermaid)',                                'Die Seejungfrau (The Little mermaid) - Fantasy for orchestra after Andersen'),
    # SEGMENT-title spelling (the recording-anchored site keys on segment titles,
    # not tracks titles): the DOMINANT recording p00rlj9s (19 airings) is billed
    # English-only "The Little mermaid - Fantasy for orchestra after Andersen" --
    # the old dead alias's phantom TARGET, now needed as a live SOURCE. Missed in
    # the first pass (tracks-only verification); caught by a post-build registry
    # mint. Always re-check folds against segment_events titles too.
    ('The Little mermaid - Fantasy for orchestra after Andersen',    'Die Seejungfrau (The Little mermaid) - Fantasy for orchestra after Andersen'),
    # Zemlinsky, Trio in D minor, Op. 3 -- ONE work (Cerys verdict 2026-07-15):
    # standard literature carries it as one opus with a parenthetical
    # instrumentation footnote, and the composer's violin-for-clarinet version is
    # a straight port (no recomposition) -- the cleanest same-work alt-scoring
    # case. Fold the clarinet / piano-trio / movements / typo billings; the
    # clarinet-vs-violin distinction survives at the RECORDING level (distinct
    # recording_pids keep their own titles under the one work).
    ('Piano Trio in D minor, op. 3',                          'Trio for clarinet, cello and piano Op 3'),   # composer's own violin version
    ('Clarinet Trio in D minor, Op 3',                        'Trio for clarinet, cello and piano Op 3'),
    ('Trio (Op.3) (Allegro ma non troppo; Andante; Allegro)', 'Trio for clarinet, cello and piano Op 3'),
    ('Trio in D minor for clairinet, cello and piano (Op.3)', 'Trio for clarinet, cello and piano Op 3'),   # 'clairinet' typo
    ('Quintet in D major (Op.11 No.6)', 'Quintet in D major, Op.11, No.6 for flute, 2 violins, cello'),   # [weak] p00tcc8p 3x
    ('Amor che deggio far? (from libro VII de madrigali - Venice 1619)', 'Amor che deggio far'),   # [weak] p05zyzh8 2x
    ('Beatus vir (KBPJ.3)', 'Beatus vir , KBPJ 3'),   # [strong] p017zzxt 1x
    ('Tzigane - concert rhapsody for violin and orchestra', 'Tzigane - rapsodie de concert arr. for violin & orchestra'),   # [strong] p00qxyh4 1x (orchestral arr, stays split from bare per Tzigane scoring policy)
    ('The Song about a Falcon', 'The Song about a Falcon - symphonic Poem, Op 18'),   # [weak] p01bz2mf 2x
    ('La Gitana', 'La Gitana (after an 18th century Arabo-Spanish Gypsy song) for violin and piano'),   # [strong] p00s0wnb 3x
    ('Tunis-Nefta - No.2 from Escales', 'Tunis-Nefra - from Escales (orig. for orchestra)'),   # [strong] p02wmgs2 2x
    ("'See, see, even Night herself is here' (Z.62/11) - from The Fairy Queen, Act II Scene 3", "See, see, even Night herself is here (Z.62/11) from 'The Fairy Queen'"),   # [strong] p00tlyc3 1x
    ('Drei Bruchstücke aus Wozzeck (Op. 7) 1. Act 1 scenes 2 & 3, Act 3, Scene 1, Act 3, scenes 4 & 5 (instrumental)', '3 Bruchstücke aus Wozzeck'),   # [strong] p05qkj0h 1x
    ('Die Amerikanerin', 'Die Amerikanerin (The American Girl) - lyric painting for soprano and ensemble'),   # [strong] p010bt5f 1x
    ('Canções heróicas (Heroic Songs) from Books 1 and 2 (Op.44) (1946-85)', 'Heroic Songs Op 44'),   # [strong] p089f8qh 2x
    ("Plainte d'Armide for voice & basso continuo", "Plainte d'Armide (from Les Amours deguises)"),   # [strong] p00ws5sj 2x
    ('Sügismaastikud', 'Sugismaastikud (Autumn landscapes)'),   # [weak] p00r9rmk 2x
    ('Fulmini quanto sà - duet for soprano, bass and continuo', 'Fulmini quanto sa for voice and accompaniment'),   # [strong] p00qyd1g 2x
    ('Deus in nomine tuo', 'Deus in nomine tuo - Psalmkonzert for bass, 2 violins, cello and continuo'),   # [weak] p028twnt 1x
    ('Piesn ; Moja piosnka', 'Czego chcesz od nas Panie & Moja piosnka from 10 Songs to Lyrics by Polish Poets'),   # [weak] p00vjd5x 1x
    ('Scherzo (Op.102)', 'Scherzo - Concerto Symphonique no 4, Op 102'),   # [strong] p00yj10n 1x
    ('Zasmuconej (Op.1 No.1)', 'Zasmuconej [To a sorrowful girl] (Op 1 no 1) (1895)'),   # [strong] p02m7k1j 1x
    ('Na sniegu (Op.1 No.3)', 'Na sniegu [In the snow] (Op.1 No.3) (Tempo mazurka)'),   # [strong] p01n37cp 1x
    ('Two Love Songs for chorus and piano', 'Two Love Songs'),   # [weak] p026lhld 1x
    ('Adagio from Trio for clarinet (or violin), cello and piano in B flat major (Op.11)', 'Adagio from Trio for violin, cello & piano in B flat major, Op 11'),   # [weak] p07sg6v4 2x
    ("Beschränkt, ihr Weisen dieser Welt (BWV.443); Ich liebe Jesum alle Stund' (BWV.468); Jesu, Jesu, du bist mein (BWV.470); Ach daß nicht die letzte Stunde meines Lebens (BWV.439) - 4 Chorales from the Schemelli collection", '4 Lieder from the Schemelli songbook (BWV.443, 468, 470 & 439)'),   # [strong] p00rchnj 2x
    ('Finnish Folksong arrangements for piano duet (Op.27)', '2 Finnlandische Volksweisen (Finnish folksong arrangements) for 2 pianos, Op 27'),   # [strong] p00t30xf 1x
    ('String Quartet No.10 in Eb major "Harp" (Op.74) (1809)', 'String Quartet no 10 in E flat major, Op 74 "Harp" (1809)'),   # [strong] p04lb73v 2x
    ('Dodolice (Op. 27)', "Dodolice: traditional folk ceremony for soprano, piano and girls' choir"),   # [strong] p011vx5d 2x
    ('Madrigale', 'Madrigale for trumpet, trombone and accordion'),   # [strong] p015yjpg 1x
    ('Mátra Pictures for choir', 'Mátrai Kepek (Mátra Pictures)'),   # [strong] p01cf5ww 1x
    ('Preludium and Allegro', 'Praeludium and allegro in the style of Gaetano Pugnani for violin and piano'),   # [strong] p00vjf27 1x
    ("Cantata No.170 'Vergnügte Ruh', beliebte Seelenlust' (BWV.170) (Leipzig, 1726)", "Cantata no 170 'Vergnugte Ruh', beliebte Seelenlust', BWV.170"),   # [strong] p014w1jb 1x
    ("Maria Theres... Hab' mir's gelobt, ihn lieb zu haben -Der Rosenkavalier (Op.59)", 'Trio (Der Rosenkavalier Act II)'),   # [strong] p00v66yd 1x
    ('Dances of Galanta (Galántai táncok) vers. for piano', 'Dances of Galanta (Galantai tancok) arr. for piano'),   # [strong] p00rf41y 1x
    ('La Captive : Suite', 'La Captive [1900]: Suite from Act 1. Ballet-Pantomime'),   # [strong] p0158n9x 1x
    ('Nigun', 'Nigun (Baal-shem - 3 pictures from Chassidic life, No 2)'),   # [strong] p06l9pb9 1x
    ('Intermezzo', 'Intermezzo for cor anglais and orchestra'),   # [strong] p00wbwzk 1x
    ('Concerto Grosso No.4 in A minor', 'Concerto Grosso no 4 in A minor (after Domenico Scarlatti)'),   # [weak] p00zt8bs 1x
    ('Sumarovo dite', "Sumarovo dite (The Fiddler's Child)"),   # [strong] p00xp8s2 1x
    ('Violin Concerto No.4 in A major (Op.32)', 'Violin Concerto no 4 in A major, Op 32 [Allegro] (1844)'),   # [strong] p00wxsnr 1x
    ('Concerto primo à 2, Concerto secondo à 2, Concerto terza à 2, Concerto quarto à 2 (1627)', 'Concerto primo, Concerto secondo, Concerto terza & Concerto quarto à 2 (1627)'),   # [strong] p02rsj51 2x
    ('Selig sind, die Verfolgung leiden - from Der Evangelimann Act 2', "Selig sind, die Verfolgung leiden (from Act 2 of 'Der Evangelimann')"),   # [strong] p03z37yc 1x
    ('Trio des Jeunes Ismaelites', 'Trio des Ismaelites from "L\'enfance du Christ"'),   # [strong] p029k8gj 1x
    ("Overture to the opera 'Erik Ejegod'", "Overture ('Erik Ejegod')"),   # [strong] p00ttmd4 1x
    ('Der Vogelfänger bin ich ja - from Die Zauberflöte', 'Aria: Der Vogelfanger bin ich ja - from Die Zauberflote'),   # [strong] p07vvf28 1x
    ('South Ostrobothnian Dances 1-5 (Op.17) (1909)', 'South Ostrobothnian Dances, Op 17 (excerpts)'),   # [strong] p00wyfqx 1x
    ('Der Abend (Op.34 No.1)', "Der Abend for 16 part choir, Op.34'1"),   # [strong] p00sp8fq 1x
    ('Suite from', 'Suite from Platee (Junon jalouse) - comedie-lyrique in three acts'),   # [weak] p00vty8s 1x
    ('Loquebantur variis linguis', 'Loquebantur variis linguis for 7 voices'),   # [weak] p00r68nm 1x
    ('Nad grobom ljepote djevojke (Op.39)', 'Nad grobom ljepote djevojke, Op 39 (By the grave of the Beauty)'),   # [weak] p025ckp3 1x
    ("Poeme de l'amour et de la mer (Op.19)", "Poeme de l'amour et de la mer, Op 19 (vers. for voice)"),   # [strong] p00tb05n 1x
    ('Anbetung dem Erbarmer Wq. 243', 'Anbetung dem Erbarmer - Easter Cantata Wq. 243 (before 1784)'),   # [strong] p062nyvb 1x
    ("La Vida breve 'Danse espagnole no.1'", "Spanish Dance no 1, from 'La Vida breve'"),   # [strong] p0c6knbv 1x
    ('Rondo in C major, Op.7', 'Rondo in C for Two Pianos, Op 73'),   # [strong] p00vtz81 2x
    ('Sonata da Chiesa in C minor (Op.1 No.8)', 'Trio sonata in C minor, Op 1 no 8'),   # [weak] p00tc59z 2x
    ('StÃ¤ndchen [(Serenade) arranged for piano from Schwanengesang (D. 957)]', 'Standchen, D.957'),   # [strong] p00t56bp 1x
    ('4 Caprices (Op.18:1) (1835)', '4 Caprices, Op 18:I'),   # [strong] p014p4c7 2x
    ('Timon of Athens [Overture; The Masque (eleven numbers)]', 'Timon of Athens, the man-hater - incidental music (Z.632)'),   # [strong] p010y30r 2x
    ('Symphony in D major/minor (sic)', 'Symphony in D major/minor ok'),   # [strong] p06q2pgv 1x
    ('Overture to Pskovitjanka [The Maid of Pskov] (1873)', 'Overture to The Maid of Pskov'),   # [strong] p00vjypr 1x
    ("Images I (Reflets dans l'eau; Hommage a Rameau; Mouvement)", 'Images - set 1 for piano'),   # [strong] p00wd9h0 1x (re-targeted 2026-07-19: 'Images I' became an LHS)
    ("The Carman's Whistle", "The Carman's Whistle (Air and Variations)"),   # [weak] p0kkmwcm 2x
    ('Concerto No.4 in G major (from Sei Concerti Armonici (1740)', 'Concerto no 4 in G major (from Sei Concerti Armonici 1740)'),   # [strong] p00wqm2f 1x
    ('Klaverstykker (piano pieces): No.2 Waltz, No.3 Intermezzo', '2 Klaverstykker (2 piano pieces)'),   # [strong] p02p841j 2x
    ('Draw on, sweet night (the second set of madrigals . apt both for voyals and voices ..; London, Browne, 1609)', 'Draw on, sweet night for violin & viols'),   # [strong] p02r8r1g 1x
    ('Don Juan (Op.20)', 'Don Juan (Op.20) (symphonic poem)'),   # [strong] p00rj2g9 1x
    ('Piano Concerto in C major (K. 467)', "Piano Concerto No.21 in C major,K467, 'Elvira Madigan'"),   # [strong] p039rxkj 3x
    ('Suru (Sorrow) (Op.22 No.2)', 'Suru (Sorrow), Op 22 no 2 for cello and piano (orig. cello and orchestra)'),   # [strong] p00t4jz7 2x
    ('Overture from Tannhäuser', 'Tannhauser (Overture)'),   # [strong] p04v24pl 2x
    ('Bacchus et Arianne (Op.43 no.2)', 'Bacchus et Ariane - Suite No 2, Op 43'),   # [strong] p00z3k6r 1x
    ('12 Variations on a Theme of The Magic Flute by Mozart', "12 Variations on 'Ein Madchen oder Weibchen' for cello and piano, Op 66"),   # [strong] p00xdqh0 2x
    ('Ave dulcissima Maria for 5 voices [1603a]', 'Ave dulcissima Maria'),   # [weak] p00v66tz 2x
    ('Intermezzo from Manon Lescaut (between Acts 2 and 3)', "Intermezzo (excerpt from 'Manon Lescaut' between Acts 2 and 3)"),   # [strong] p00w0x5v 2x
    ('Flute Concerto in D minor (Op.283)', 'Flute Concerto in D major, Op 283'),   # [strong] p0189l15 2x
    ('3 Psaumes de David (Op.339) (No.1 Psalm 51 [Vulgate no.50] - No.2 Psalm 50 - No.3 Psalms 114 and 115', '3 Psaumes de David for chorus, Op 339'),   # [strong] p00wqlwr 1x
    ('Overture - from [The] Sicilian Vespers', 'Overture (Sicilian Vespers)'),   # [strong] p00yff7g 2x
    ('Sonata No. 9 in B minor (Op. 145)', "Piano Sonata No 9 in B minor, Op 145, 'Grande fantaisie en forme de Sonate'"),   # [strong] p01jvy08 1x
    ('Veni Domine', 'Veni Domine - Geistliches Konzert for 2 sopranos, bass, and continuo'),   # [weak] p00xknwt 1x
    ('When David Heard', 'When David heard (O my son Absalom)'),   # [weak] p02fd6k1 1x
    ('De Profundis', 'De Profundis (cantata)'),   # [strong] p00vtz9x 1x
    ('Così nel mio cantar', 'Cosi nel mio cantar (Della pratica del moderno contrappunto)'),   # [weak] p02mczfb 2x
    ('La Maja y el Ruiseñor [The Maiden and the Nightingale]', 'La Maja y el Ruisenor - from Goyescas'),   # [strong] p00z645f 1x
    ('Pavan', 'Pavan for lute'),   # [strong] p02s2v4h 2x
    ('Nights in the Gardens of Spain for piano and orchestra', 'Noches en los jardines de Espana [Nights in the Gardens of Spain]'),   # [strong] p00t5sb9 1x
    ('Siegfrieds Rheinfahrt- from GÃ¶tterdÃ¤mmerung', "Siegfrieds Rheinfahrt [Siegfried's Rhine Journey] - from 'Götterdämmerung'"),   # [strong] p08fm1sb 1x
    ('An die Musik (Op.88 No.4)', 'An die Musik (Op.88 No.4) (song)'),   # [strong] p02nxl5x 2x
    ('Divertimento for Strings (1960 - BBC Commision)', 'Divertimento for Strings (1948, rev. 1954)'),   # [strong] p02phb0b 1x
    ("Close your Eyes and Smile, excerpt from 'Emils Darzins. The Valse Mélancolique'", 'Close your Eyes and Smile'),   # [strong] p0270ck9 2x
    ('Sonata for oboe & basso continuo in B flat major - from Essercizii Musici', 'Sonata for oboe and continuo in B flat major (Essercizii Musici, 1739-40)'),   # [weak] p0122d5h 2x
    ('Jauchzet dem Herrn - motet for double chorus & bc', 'Jauchzet dem Herrn'),   # [weak] p00tpn1x 1x
    ('Extase - for voice and piano (?1874)', 'Extase - for voice and piano'),   # [strong] p01nlt3l 1x
    ('Don Quixote, Op, 35 (1897)', 'Don Quixote'),   # [strong] p00tll6d 1x
    ('Vardar - Bulgarian rhapsody (Op.16) (appl)', 'Vardar - Rhapsodie bulgare'),   # [strong] p00tqmvt 2x
    ('Danzon Cubano vers. for 2 pianos', 'Danzon Cubano'),   # [strong] p00xydgd 2x
    ('Cuba (Capricho) from Suite española for piano no.1 (Op.47 No.8) arr. unknown for guitar', 'Cuba (Suite espanola no 1, Op 47 no 8)'),   # [strong] p00w10d3 2x
    ('5 Flower Songs for chorus (Op.47)', "5 Flower Songs for chorus (Op.47) DON'T USE!"),   # [strong] p00wxsjk 1x
    ('Sonata no.6 (BWV.530) in G major transcr. BartÃ³k for piano (BB A-5, c.1929)', 'Sonata no. 6 in G major BWV.530 for organ (trans. for piano)'),   # [strong] p00rpfz7 1x
    ('Suite Hï¿½braï¿½que No.5 for flute, clarinet, violin and cello', 'Suite Hebraique No.5 for flute, clarinet, violin and cello'),   # [strong] p02f4vxy 1x
    ('Jauchzet Gott, alle Lande - motet for double chorus & bc [text: Psalm 66/1-5, 7, 16, 19-20]', 'Jauchzet Gott, alle Lande - motet for double chorus & bc'),   # [weak] p00z3g7v 1x
    ('Sonata No.6 in G major (Op.6 No.6)', 'Sonata in G major for transverse flute and harpsichord, Op 6 no 6'),   # [strong] p00wnc8w 1x
    ("Introduction and variations on Mozart's 'O cara armonia' (Op.9)", "Introduction and variations on a theme from Mozart's Magic Flute, Op 9"),   # [strong] p011mk3x 1x
    ('Der AlpenjÃ¤ger (D.588b Op.37 No.2)', 'Der Alpenjager - The Alpine hunter, D.588b'),   # [strong] p00wby6k 2x
    ("Due Cori di Mchaelangelo Buonarroto il Giovane'", '2 Cori di Michelangelo Buonarroti il Giovane - set 1 for unaccompanied chorus'),   # [strong] p00s3ty5 1x
    ('Overture from La Gazza Ladra', 'Overture to La Gazza Ladra [The Thieving Magpie]'),   # [strong] p00sddh1 1x
    ('Three melodies with texts by J.P. Contamine de La Tour (Les Anges [The Angels1]; Elegie²; Sylvie³)', 'Three melodies with texts by J.P.Contamine de La Tour'),   # [strong] p025rv1w 2x
    ('Deux mÃ©lodies hÃ©braÃ¯ques', "2 Hebrew melodies (Kaddisch; L'Enigme eternelle)"),   # [strong] p060pqq2 1x
    ('Sonata in F minor', 'Sonata in F minor, from \'\'Der Getreue Music-Meister"'),   # [strong] p00slkrm 1x
    ("Manon Act 1: Manon and Des Grieux recit and duet 'Et je sais votre nom'; 'Nous vivrons Ã Paris....Tous les deux'", 'Manon, Act 1: Manon and Des Grieux recit and duet'),   # [strong] p06f1dv9 2x
    ('FÃ¼rchte dich nicht - motet for 5 voices', 'Furchte dich nicht'),   # [weak] p00sw95w 1x
    ('Svetliy prazdnik [Russian Easter festival] - overture (Op.36)', 'Russian Easter Festival Overture, Op 36'),   # [strong] p014w1gw 1x
    ('Tes beaux yeux', 'Tes beaux yeux causent mon amour - chanson for 4 voices'),   # [weak] p00q6bww 2x
    ('Ouverture voor Groot Orkest [1831, arranged 1841]', 'Ouverture voor Groot Orkest'),   # [strong] p00v64xj 1x
    ("Alborada del gracioso [The Jester's Aubade] - from the suite 'Miroirs' (1905)", "Alborada del gracioso  'Miroirs' (1905)"),   # [strong] p00x0vqr 1x
    ('Concerto Grosso in G minor [after Corelli Op.5 No.5]', 'Concerto Grosso in G minor'),   # [weak] p00qv2kt 2x
    ('The Globe-trotter suite (Op.358)', 'The Globetrotter suite, Op.358 (orig. for solo piano)'),   # [strong] p00t31xp 2x
    ('In ballingschap (In Exile)', "In ballingschap (In Exile) - Symphonic Poem (1914) DON'T USE!"),   # [strong] p02b205f 1x
    ('Symphony No 3 in B Major (Op.18) for small orchestra', 'Symphony no 3 in B flat major, Op 18'),   # [strong] p01fzkdw 1x
    ('Flute Sonata [an arrangement of the Violin Sonata]', 'Sonata for flute and piano (orig. violin and piano)'),   # [strong] p00vn5tj 1x
    ("Due Cori di Michaelangelo Buonarroto il Giovane'", '2 Cori di Michelangelo Buonarroti il Giovane - set 1 for unaccompanied chorus'),   # [strong] p00s3ty5 1x
    ('Dwie Chatki (Two Huts)', 'Dwie Chatki (Two Cottages): The Overture'),   # [strong] p05f2917 1x
    ('Fantaisie sur Rigoletto (Op.19)', 'Fantasie sur Rigoletto (Op.19)'),   # [weak] p00x2lqz 2x
    ('LÃ©gende', 'Legende - symphonic poem'),   # [strong] p0329v99 1x
    ('Concerto No.6 in E flat major', 'Concerto armonico no 6 in E flat major (from Sei Concerti Armonici, 1740)'),   # [strong] p020d273 1x
    ('Tribulationem et dolorem inveni for 5 voices', 'Tribulationem et dolorem inveni for 5 voices [1603a]'),   # [strong] p0826zph 1x
    ('Flora gave mee fairest flowers for 5 voices', 'Flora gave mee fairest flowers'),   # [strong] p0301134 1x
    ('What is our life?', 'What is our life? - for 5 voices'),   # [weak] p02djvnf 1x
    ("Cantata 'Unschuld und ein gut Gewissen'- from the 'FranzÃ¶sischen Jahrgang zum Sonntag Oculi 1715' (TWV.1:1440)", 'Cantata "Unschuld und ein gut Gewissen" for 4 voices'),   # [strong] p013qfhz 1x
    ('Selection from 44 Duos for 2 violins, Sz.98/4: Vol.4', '44 Duos for 2 violins, Vol 4 (excerpts)'),   # [strong] p01302pc 1x
    ('Sarabande from Suite for solo cello no.6 (BWV.1012) in D major arr. for 4 cellos', 'Sarabande from cello suite No 6 arr. for 4 cellos'),   # [strong] p015vbmz 1x
    ("The Fiddler's child", "Sumarovo dite (The Fiddler's Child)"),   # [weak] p00xp8s2 1x
    ('Iberia No 2', 'Iberia: Images for Orchestra, no 2'),   # [strong] p01kg1km 1x (synthetic L-less variant: Lesure scoping)
    ('Prelude and fugue in F major - from Das Wohltemperierte Klavier, Book.2 No.11 (BWV.880)', 'Prelude and fugue in F major, BWV 880'),   # [strong] p00xkp45 1x
    ("The Jester's Aubade - from the suite 'Miroirs'", "Alborada del gracioso  'Miroirs' (1905)"),   # [strong] p00x0vqr 1x
    ('Lachrymae (Op.48)', 'Lachrymae (Reflections on a song of Dowland) for viola and piano, Op 48'),   # [strong] p030cyvw 1x
    ('Fairy tale for cello and piano', 'Pohadka (Fairy tale)'),   # [strong] p01ndwrq 1x
    ('Duet: Fra gli amplessi - from Così fan tutti', 'Duet: Fra gli amplessi (Cosi fan tutte)'),   # [strong] p00wchvn 1x
    ("Siegfried's Rhine Journey - from Götterdämmerung (1876)", "Siegfrieds Rheinfahrt [Siegfried's Rhine Journey] - from 'Götterdämmerung'"),   # [strong] p08fm1sb 1x
    ('Sonata in B minor (L.263) (Kk.377)', 'Sonata in B minor, Kk.377'),   # [strong] p0ggvrh2 1x
    ("Pavane in D minor - 'L'Entretien des Dieux', from 'Les PiÃ¨ces de Clavessin', book 1, Paris 1670", "Pavane in D minor, 'Entretien des Dieux', from Bk.1 of 'Pieces de Clavecin'"),   # [strong] p02mqjsn 1x
    ('Italian Polka - for two pianos', 'Italian Polka for piano duet'),   # [strong] p01056q2 1x
    ('Preludium and Allegro (à la Pugnani) for violin and piano', 'Praeludium and allegro in the style of Gaetano Pugnani for violin and piano'),   # [strong] p00vjf27 1x
    ('Confitebor - Psalm 110 (111)', 'Confitebor tibi - Psalm 110/111'),   # [strong] p040srtv 1x
    ('Suite about the well (Op.56)', 'Suita O Vodnjaku (Suite about the well), Op 5'),   # [strong] p00qzgzf 1x
    ('Preludes for piano, Op.1 (No.1 in B minor; No.2 in D minor; No.3 in D flat major; No.4 in B flat minor; No.5 in D minor; No.6 in A minor; No.7 in C minor; No.8 in E flat minor; No.9 in B flat minor)', 'Preludes for piano, Op 1'),   # [strong] p01q57rm 1x
    ('Skylark (Op.138 No.2)', 'Leivo [Skylark], Op 138 no 2'),   # [strong] p07fdhy4 1x
    ('Morning', 'Morgonen (Morning)'),   # [strong] p025jdkr 1x
    ('Symphony in D major (Op.5 No.3)', "Symphony in D major 'Pastorella'"),   # [strong] p00vjywk 1x
    ('Italian Girl in Algiers - overture', "L'Italiana in Algeri (Overture)"),   # [strong] p00wnc09 1x
    ('Suite on Danish folk songs', 'Suite on Danish folk songs vers. orchestral'),   # [strong] p00xwbqn 1x
    ('Dance preludes', 'Dance preludes (Preludia taneczne) vers. for clarinet and piano'),   # [strong] p02k37t8 1x
    ('Un soir de neige', 'Un Soir de neige - cantata for 6 voices'),   # [weak] p01g1sqb 1x
    ('keringo from the incidental music to The Veil of Pierrette by Arthur Schnitzler', 'Pierrette fatyla - keringo'),   # [strong] p00qq19d 1x
    ('The Maiden and the Nightingale - from Goyescas', 'La Maja y el Ruisenor - from Goyescas'),   # [strong] p00q787m 1x
    ('Solo for cello and continuo (Op.5 No.1) in G major (1780)', 'Solo (sonata) for cello and continuo in G major, Op 5 no 1'),   # [strong] p01498g6 1x
    ('In ballingschap', "In ballingschap (In Exile) - Symphonic Poem (1914) DON'T USE!"),   # [strong] p02b205f 1x
    ('Bei MÃ¤nnern, from Die ZauberflÃ¶te', 'Duet: Bei Mannern, from Die Zauberflote'),   # [strong] p02ggw9r 1x
    ("Mercordi' (TWV42:G5) - from 'Pyrmonter Kurwoche'", '"Mercordi" (TWV42:G5)'),   # [strong] p02jp5pc 1x
    ('Dreams', 'Drommarne [Dreams]'),   # [strong] p0300xgj 1x
    ('Passacaglia & Aria', 'Passacaglia & Aria (presto)'),   # [weak] p01h00yy 1x
    ("'Salut, demeure chaste et pure' from 'Faust'", 'Faust\'s Aria "Salut, demeure chaste et pure" -- from Act III of \'Faust\''),   # [strong] p01c3jvm 1x
    ("'Dances of the Blessed Spirits'", "Dance of the Blessed Spirits - dance music from 'Orphée et Euridice'"),   # [strong] p00th5n6 1x
    ('Et cum ingressus esset Jesu (KBPJ 16)', 'Et cum ingressus esset Jesu, KBPJ.16'),   # [strong] p031bqhh 1x
    ('Kamarinskaya', 'Kamarinskaya (fantasy for orchestra)'),   # [strong] p0126t50 1x
    ('Koncert za violino in orkester [Violin Concerto]', 'Violin Concerto in B minor'),   # [strong] p060knv3 1x
    ("Variations on a theme from Bellini's 'Norma' for cornet and piano", 'Variations on "Casta diva - Ah! Bello" from Bellini\'s \'Norma\''),   # [strong] p00vn7vz 1x
    ("Alma real, se come fida stella' (Royal lady, like the faithful star that now leads three kings to the greatest king, you summoned me.)", '"Alma real, se come fida stella" (Royal lady, like the faithful star ...'),   # [strong] p02fzgkv 1x
    ('Sonata IV, for 2 violins and continuo (from Sonate concertarte in stil moderno, per sonare nel organo, overo spineta con diversi instrumenti, a 2 & 3 voci. Libro primo. Venice 1629)', 'Sonata IV, for 2 violins and continuo'),   # [weak] p010mwxg 1x
    ('Prelude for guitar no.1 in E minor (from 5 preludes for guitar)', 'Prelude for guitar no 1 in E minor'),   # [strong] p00r1slb 1x
    ('Rivolgete a lui lo sguardo', "Aria 'Rivolgete a lui lo sguardo' (K.584)"),   # [strong] p044y5k7 1x
    ('Missa Sancti Henrici, for 5 soloists, 5-part chorus, 5 trumpets, timpani, 2 violins, 3 violas, violone, and organ (1701)', 'Missa Sancti Henrici'),   # [strong] p00xl0gj 1x
    ('Suite española [Spanish Suite] (Op.47)', 'Suite española for guitar'),   # [strong] p015h89f 1x
    ('Piano Concerto in A major (K.488)', 'Piano Concerto No.23 in A major (K.488)'),   # [strong] p00qs5g5 1x
    ('Sonata No. 9 in B minor (Op. 145) "Grande fantaisie en forme de Sonate"', "Piano Sonata No 9 in B minor, Op 145, 'Grande fantaisie en forme de Sonate'"),   # [strong] p01jvy08 1x
    ('Toccata in D minor ([senza indicazione] Fuga)', 'Toccata in D minor (Fuga)'),   # [strong] p07pnymp 1x
    ('Salve Regina in F minor [vers. of C minor setting for soprano]', 'Salve Regina in F minor'),   # [strong] p00r0mnj 1x
    ("Suite No.2 from the ballet 'Papessa Joanna'", 'Pope Joan, Suite No.2'),   # [strong] p02ry32m 1x
    ('Laetatus su', 'Laetatus Sum'),   # [strong] p00vjyqq 1x
    ('[A] Maske (MB.24.31) & Fantasia (MB.24.12) for keyboard - from the Fitzwilliam Virginal Book Nos.198 & 237', 'Maske & Fantasia from the Fitzwilliam Virginal Book'),   # [strong] p00s565x 1x
    ('Suite for violin and piano No.2', 'Suite for violin and piano no 2 (in Modo barocco)'),   # [strong] p00v012r 1x
    ('Printemps', 'Printemps (symphonic suite) [Tres modere; Modere]'),   # [strong] p044qnph 2x (converges with the existing Printemps alias)
    # 2010-floored orphan easy-win pass (2026-07-06): 42 single-work
    # cosmetic folds (case/typo/translation-gloss/scoring-annotation/
    # truncation) from the tail; recital-blocks + different-work +
    # whole-vs-part rejected by hand. Alias-only (no bridge link).
    ('Etude en forme de valse - from [6] Studies for piano (Op.52 No.6)', 'Etude en forme de valse - from Studies for piano (Op.52 No.6)'),
    ("Clarinet Trio (Op.11) in B flat major, 'Gassenhauer-Trio'", "Trio for clarinet (or violin), cello and piano (Op.11) in B flat major , 'Gassenhauer-Trio'"),
    ("Les Nuits d'ete for voice orchestra (Op.7)", "Les Nuits d'ete for voice and orchestra (Op.7)"),
    ('Canto di lanzi venturieri', '? Canto di lanzi venturieri'),
    ('Amis, quelx est li mieuz vaillanz (jeu parti) and estampie on Chascuns dit que je foloi by Tobie Miller', 'Amis, quelx est li mieuz vaillanz (jeu parti) and estampie on Chascuns dit que je foloi by Tobie Miller (group instrumental)'),
    ('Eine Frau wird erst schön durch die', 'Eine Frau wird erst schön durch die Liebe'),
    ('Sometimes when long I dream half asleep', 'Sometimes when long I dream half asleep - song for voice and piano (1895)'),
    ('Aman novi/Heu, Fortuna Subdola & retrove', 'Aman novi/Heu, Fortuna Subdola & retrove (estampie)'),
    ("Rimanti in pace for 5 voices [from 'Il primo libro de madrigali', 1600], prima parte", "Rimanti in pace for 5 voices [from 'Il primo libro della madrigali', 1600], prima parte"),
    ('Sakura (Cherry Blossoms) from Uta', 'Sakura (Cherry Blossoms) from Uta - songs for chorus'),
    ('Rondeau 4: Sans cuer dolens - from Le Voir Dit', 'Rondeau 4: Sans cuer dolens - from Le Veoir Dit'),
    ('Aufforderung zum Tanz - Rondo brillante in D flat (J.260) for Piano (Op.65)', 'Aufforderung zum Tanz (Invitation to the Dance) - Rondo brillante in D flat (J.260) for Piano (Op.65)'),
    ("If Love's a sweet passion from the Fairy Queen (Z.629)", "If love's a sweet passion from The Fairy Queen (Z. 629)"),
    ('Missa Gabriel Archangelus', 'Missa Gabriel Archangelus, a 4'),
    ('Chanterai por mon coriage and estampie on the same piece', 'Chanterai por mon coriage & Estampie'),
    ('Rapsodie espagnole, version for orchestra', 'Rapsodie espagnole vers. for orchestra'),
    ('Tanto tempore', 'Tanto tempore - motet'),
    ('Full Throttle', 'Full Throttle for Saxophone Quartet'),
    ('Chime, you bells', 'Kimer, I klokker (Chime, you bells)'),
    ('Piano Sonata No 1 - IV b Allegro', 'Piano Sonata No 1 - IV b Allegro (third verse, chorus)'),
    ('Brigg Fair (An English rhapsody) for orchestra (RT.6.16)', 'Brigg Fair for orchestra (RT.6.16)'),
    ('Prelude to Act 3 of Lohengrin - opera in 3 acts', 'Prelude to Act 3 Lohengrin'),
    ('Suita w dawnym stylu (Suite in the Old Style)', 'Suita w dawnym stylu'),
    ('O mio core from Giasone', 'Duet: O mio core (Medea and Giasone) from Giasone'),
    ('Tombeau de Monsieur de Lully', 'Le Tombeau de Monsieur Lully (for 2 violins and continuo)'),
    ('Wein, Weib und Gesang', 'Wein, Weib und Gesang (Wine, Woman and Song)'),
    ("Dessus le marché d'Arras", "Dessus le marché d'Arras ('In the market at Arras')"),
    ('Quartet in G major for 2 violins, viola and continuo (Op.5 No.4)', 'Quartet in G major (Op.5 No.4)'),
    ('The Spanish Hour', "L'Heure espagnole (The Spanish Hour)"),
    ('Sai Ma for erhu and piano', 'Sai Ma [2 Horses Racing] for erhu and piano'),
    ("Birds' Song", "Lindude Laul (Birds' Song) (1927)"),
    ('Open for us, Lord', 'Pats Mez Der (Open for us, Lord)'),
    ('Symphony in D major from the opera "Pasterz nad Wisla"', 'Symphony in D major on themes from the opera "Pasterz nad Wisla" (The Shepherd on the Vistula) (c.1786)'),
    ("An der schÃ¶nen, blauen Donau (Op.314) 'The Blue Danube'", 'An der sch�nen Blauen Donau - waltz for orchestra (Op.314)'),
    ('Cor mio, deh non languire [Dear heart, I prithee do not waste away]', 'Cor mio, deh non languire'),
    ('Canon of Repentance  - Part 1 (1997)', 'Canon of Repentance to Our Lord Jesus Christ - Part 1 (1997) [I- VII]'),
    ('Wine, Woman and Song - waltz', 'Wein, Weib und Gesang (Wine, Woman and Song)'),
    ("Rondeau - L'Ã\x89tourdie, from Suite for harpsichord no.4", "Rondeau - L'Étourdie, from Suite for harpsichord no.4 [Deuxième livre de pièces de clavecin]"),
    ('Die Schlacht von Waterloo', 'Die Schlacht von Waterloo (1815) [Ein historisches Tongemälde für das Piano Forte (Op.43)]'),
    ('Sonata Violino Solo Representativa', 'Sonata Violino Solo Representiva'),
    ("Madrigal: Pace non trov' (I have no peace)", 'I have no peace'),
    ('Les Eolides', 'Les Eolides - symphonic poem after Leconte de Lisle'),
    # --- Matteis pre-2012 stragglers (2026-07-09, Part B of the per-work
    # attribution close-out): fold the text-era variants of the two Matteis
    # recording blocks onto their segment-title canonicals so the cross-era
    # bridge picks the airings up. Recording-fingerprint verified: every
    # pre-2012 'Passages' airing carries the Playford 5-Marches coupling in
    # its performers field (Memelsdorff/Staier, recording p00wgymn — the only
    # Passages recording corpus-wide), so the bare title UNDER-describes the
    # same block (not a whole-vs-part fold); 'L'amore' is the Wallfisch/Kent
    # recording. The triple-block '...After Nicola Matteis: Chaconne, Plaint,
    # Ecchi' title stays split (extended recital block, standing policy). The
    # old 'Matteis:'-prefixed intermediate target was retargeted above.
    ('Matteis: Passages in Imitation of the Trumpet (Ayres & Pieces IV (1685))',
     "Passages in Imitation of the Trumpet; 5 Marches from Playford's New Tunes"),
    ('Matteis: Passages in Imitation of the Trumpet (Ayres & Pieces IV, 1685)',
     "Passages in Imitation of the Trumpet; 5 Marches from Playford's New Tunes"),
    ('Matteis: Passages in Imitation of the Trumpet',
     "Passages in Imitation of the Trumpet; 5 Marches from Playford's New Tunes"),
    ('Passages in Imitation of the Trumpet (Ayres and Pieces IV - 1685)',
     "Passages in Imitation of the Trumpet; 5 Marches from Playford's New Tunes"),
    ('Passages in Imitation of the Trumpet',
     "Passages in Imitation of the Trumpet; 5 Marches from Playford's New Tunes"),
    ("L'amore", "L'Amore (Love)"),
    # --- orphan-alias fix batch (2026-07-10): repair truncated-paste
    # misfires found by the transcription-depth sweep's orphan audit —
    # variants were pasted from TRUNCATED display output in past batches,
    # so their keys matched nothing and the intended folds never fired.
    # Wrong/hazardous folds retired instead (Visions ranges, 44-Duos
    # selections, bare Irmelin/Damnation/O-Mistress ambiguity, inert
    # impossible-truncation strings). Validate variants against the
    # corpus before pasting — see scratch/transcription_depth_probe.py.
    ("Già che morir non posso' ? aria from Rinaldo HWV 7",
     "Già che morir non posso - from 'Radamisto'"),
    ('Piano Quintet in F minor, Op.34 (Molto moderato quasi lento - allegro; Lento con molto sentimento; Allegro non troppo, ma con fuoco)',
     'Piano Quintet in F minor, Op 34'),
    ("Various Works [1. See, Even Night Herself Is Here from 'The Fairy Queen'; 2. Curtain Tune on a Ground from 'Timon of Athens'; 3. Hornpipe d-Moll from 'The Fairy Queen'; 4. Hornpipe g-Moll from 'The Fairy Queen'; 5. Dance of the Bacchanals from 'Dioclesian'; 6. The Old Bachelor Hornpipe; 7. Ouverture, Minuet und Rondeau from 'Abdelazer Suite']",
     "1. See, Even Night Herself Is Here from 'The Fairy Queen'; 2. Curtain Tune on a Ground from 'Timon of Athens'; 3. Hornpipe d-Moll from 'The Fairy Queen'; 4. Hornpipe g-Moll from 'The Fairy Queen'; 5. Dance of the Bacchanals from 'Dioclesian'; 6. The Old Bachelor Hornpipe; 7. Ouverture, Minuet und Rondeau from 'Abdelazer Suite'"),
    ("Four Works: [1. Sing, ye Druids all from Bonduca, or The British heroine - incidental music Z.574; 2. Divine Andate from Bonduca, or The British heroine - incidental music Z.574; 3. Sing, ye Druids all (reprise) Bonduca, or The British heroine - incidental music Z.574; 4. I look'd, and saw within the book of Fate from The Indian emperor, or The conquest of Mexico Z.598 - incidental music] (followed by Four Works by John Playford [1. The King of Poland; 2. Pye Corner; 3. The Old Bachelor; 4. Lili Burlero]",
     "Four works: Sing, ye Druids all; Divine Andate; Sing, ye Druids all (reprise) - from Bonduca, or The British heroine - incidental music Z.574; I look'd, and saw within the book of Fate from The Indian emperor, or The conquest of Mexico Z.598 - incidental music; followed by Four Works by John Playford [1. The King of Poland; 2. Pye Corner; 3. The Old Bachelor; 4. Lili Burlero]"),
    ("Various Works [1. Prélude – Air accompagné Tristes apprêts from 'Castor et Pollux'; 2. Musette et Tambourin en Rondeau from 'Les Fêtes d'Hébé'; 3. Vaste Empire des Mers from 'Les Indes galantes'; 4. Dieux vengeurs from 'Hippolyte et Aricie'; 5. Sommeil from 'Dardanus'; 6. Les Vents from 'Les Boréades'; 7.Contredanse en Rondeau from 'Les Boréades'; 8. Bruit de guerre, pour entr’acte 'Dardanus'; 9. Aux langueurs d’Apollon from 'Platée'; 10. Tambourin I und Tambourin II from 'Dardanus'; 11. Entrée de Polymnie from 'Les Boréades'; 12. Forêts paisibles (Danse des Sauvages) from 'Les Indes galantes']",
     "1. Prélude – Air accompagné Tristes apprêts from 'Castor et Pollux'; 2. Musette et Tambourin en Rondeau from 'Les Fêtes d'Hébé'; 3. Vaste Empire des Mers from 'Les Indes galantes'; 4. Dieux vengeurs from 'Hippolyte et Aricie'; 5. Sommeil from 'Dardanus'; 6. Les Vents from 'Les Boréades'; 7. Contredanse en Rondeau from 'Les Boréades'; 8. Bruit de guerre, pour entr’acte 'Dardanus'; 9. Aux langueurs d’Apollon from 'Platée'; 10. Tambourin I und Tambourin II from 'Dardanus'; 11. Entrée de Polymnie from 'Les Boréades'; 12. Forêts paisibles (Danse des Sauvages) from 'Les Indes galantes'"),
    ('1. Agnus Dei. Gloriosa spes reorum - or; 2. Beata Viscera - Graduale Romanum ad Communionem; 3. Haec est mater; 3. Benedicamus Domino; 5. Benedicamus Domino',
     '1. Agnus Dei. Gloriosa spes reorum; 2. Beata Viscera; 3. Haec est mater; 4. Benedicamus Domino; 5. Benedicamus Domino'),
    ('1. O monialis concio burgensis - planctus; 2. Rorate caeli - Graduale Romanum ad Introitum; 3. Cum iubilo Romanum Kyrie lX; Kyrie, Rex virginum; 5. Gloria in excelsis',
     '1. O monialis concio burgensis; 2. Rorate caeli; 3. Cum iubilo; 4. Kyrie, Rex virginum; 5. Gloria in excelsis'),
    ('3 pieces from "Les Indes Galantes" & Le Rappel des Oiseaux',
     '3 Pieces from Les Indes galantes; Le Rappel des oiseaux'),
    ('3 pieces from "Les Indes Galantes" & Le Rappel des Oiseaux [1. Air pour Zéphire; 2. Musette en Rondeau; 3. Air pour Borée et la Rose]',
     '3 Pieces from Les Indes galantes; Le Rappel des oiseaux'),
    ('Suite for Orchestra (Op.3) (Con moto; Adagio; Allegro ; Con moto)',
     'Suite for Orchestra (Op.3)'),
    ('3 Danish Romances for Choir (1. Den Kedsom vinter gik sin gang ; 2. Min yndlingsdal ; 3. Natteregn )',
     '3 Danish Romances for Choir'),
    ('Walsingham (Have with you to Walsingham) - variations for keyboard, MB 7 8',
     'Walsingham (Have with you to Walsingham) - variations for keyboard (MB.7.8)'),
    ('Three choral songs: September; I Seraillets Have (In the seraglio garden); Havde jeg en datterson (If I had a grandson)',
     'Three choral songs'),
    ('Three choral songs: September; I Seraillets have (The Garden of Seraglio); Hayde jeg en datterson (If I had)',
     'Three choral songs'),
    ('Three choral songs: September; In the seraglio garden; If I had a grandson.',
     'Three choral songs'),
    ('Three choral songs: September; The Garden of Seraglio; If I had',
     'Three choral songs'),
    ('Three choral songs: September; The Seraglio Garden; If I Had',
     'Three choral songs'),
    ("Piano medley - Swanee; I'll Build A Stairway To Paradise etc..",
     'Piano Medley'),
    ("Piano medley - Swanee; I'll Build A Stairway To Paradise; Oh Lady Be Good; Do It Again; Nobody But You; Somebody Loves Me; Fascinating Rhythm",
     'Piano Medley'),
    ("Cor mio, deh non languire [Dear heart, I prithee do not waste away] - from Il primo libro de madrigali a cinque voci di Michelangelo Nantermi [Venice 1609] (Filiberto Nantermi's only extant work)",
     'Cor mio, deh non languire'),
    ('5 Lieder (Op. 38) [1947] 1. Gluckwunsch; 2. Der Kranke; 3. Alt-Spanisch; 4. Old English Song; 5. My mistress eyes',
     '5 Lieder (Op.38) [1947]'),
    ('Sonata for piano (H.16.34) in E minor (Presto; Adagio; Final: Molto vivace)',
     'Piano Sonata in E minor, H.16.34'),
    ('Musica della commedia di Franc. Corteccia recitata al secondo convito (Aurora; Pastori; Sirene; Sileno; Ninfe cacciatrici; La Notte; Finale)',
     'Musica della commedia di Francesco Corteccia recitata al secondo convito'),
    ('Kimer, I klokke',
     'Kimer, I klokker (Chime, you bells)'),
    ('Excerpts from Eight Pieces for clarinet, viola and piano (Op.83) ; No.7 - Allegro Vivace ma non troppo in B major; No.8 - Moderato in E flat minor]',
     'Excerpts from Eight Pieces for clarinet, viola and piano, Op 83'),
    ('Sola, perduta, abbandonata - aria from Act 4 of Manon Lescaut',
     'Aria "Sola perduta abbandonata" - from Act IV of \'Manon Lescaut\''),
    ('2 Marches in E flat major for wind (Hungarian National March (Hob:VIII:4) (1802); Prince of Wales March (Hob:VIII:3))',
     '2 Marches for wind band'),
    ('Sonata for flute and piano (Op.167) in E minor "Undine" Allegro; Intermezzo',
     'Flute Sonata in E minor, Op 167 "Undine"'),
    ('Rivolgete a lui lo sguardo (Cosi fan tutte)',
     "Aria 'Rivolgete a lui lo sguardo' (K.584)"),
    ('Rivolgete a lui lo sguardo - aria for bass and orchestra',
     "Aria 'Rivolgete a lui lo sguardo' (K.584)"),
    ('Rivolgete a lui lo sguardo - aria for bass and orchestra (K.584)',
     "Aria 'Rivolgete a lui lo sguardo' (K.584)"),
    ('Quintet (Introduction, theme and variations) for clarinet and strings in B flat major (Op.32) previously attrib. Weber',
     'Clarinet Quintet (Introduction, theme and variations) in B flat major, Op 32'),
    ('Quintet (Introduction, theme and variations) in B flat for clarinet and strings major (Op.32)',
     'Clarinet Quintet (Introduction, theme and variations) in B flat major, Op 32'),
    ('Quintet (Introduction, theme and variations) in B flat for clarinet and strings, Op 32 (sometimes attrib Weber)',
     'Clarinet Quintet (Introduction, theme and variations) in B flat major, Op 32'),
    ('Prelude to Act 3; The Apprentices dance; Prelude to Act 1 of Die Meistersinger',
     "Prelude to Act 3; The Apprentices dance; Prelude to Act 1 of 'Die Meistersinger von Nürnberg'"),
    ('La Damnation de Faust, Op 24 (excerpts)',
     'Excerpts from La Damnation de Faust (Op.24)'),
    # Debussy Jardins sous la pluie: SYNTHETIC L-LESS variant strings (the
    # Lesure trap — for Debussy, alias keys must match the L-STRIPPED
    # composer-threaded grouping keys, so L-bearing pair strings never fire).
    # The retired L-bearing 'puie' alias had silently never fixed this typo.
    ('Jardins sous la puie (Estampes)', 'Jardins sous la pluie (Estampes)'),
    ('Jardins sous la pluie (No.3 from Estampes)', 'Jardins sous la pluie (Estampes)'),
    # WTC BWV.870 Prelude & Fugue — the leading-'From <collection>:' spellings
    # demote to token-sort under the form-word excerpt guard (5d112ca) while
    # the ref-before-'from' spellings stay §-keyed; fold everything onto the
    # segment-canonical string (2026-07-11 residue pass).
    ("From 'Das Wohltemperierte Klavier': Prelude and Fuga in C major, BWV.870",
     "Prelude and Fuga in C major, BWV.870 from 'Das Wohltemperierte Klavier Book 2'"),
    ('From Das Wohltemperierte Klavier Book 2: Prelude and Fuga in C major, BWV.870',
     "Prelude and Fuga in C major, BWV.870 from 'Das Wohltemperierte Klavier Book 2'"),
    ('Prelude and Fuga in C, BWV 870 (Das Wohltemperierte Klavier)',
     "Prelude and Fuga in C major, BWV.870 from 'Das Wohltemperierte Klavier Book 2'"),

    # --- Website-surfaced curation batch (2026-07-16, curation.txt): splits
    #     Nick spotted browsing the live site. All corpus-verified spellings;
    #     blast radius checked (only the named composers carry each variant
    #     key, bar one 1-row performer-as-composer junk credit).
    # Ligeti Lux Aeterna: scoring annotation + ae/e spelling split it 3 ways.
    ('Lux aeterna for chorus',                        'Lux Aeterna'),
    ('Lux Eterna for Chorus',                         'Lux Aeterna'),
    # Holst The Planets: suite-annotation / bare / op-less / [Holst]-suffixed
    # whole-work spellings (movement excerpts key separately and STAY split).
    ('The Planets - suite Op 32',                     'The Planets, Op 32'),
    ('The Planets - suite',                           'The Planets, Op 32'),
    ('The Planets',                                   'The Planets, Op 32'),
    ('The Planets - suite Op.32 [Holst]',             'The Planets, Op 32'),
    # Holst Beni Mora: the bare form is the SEGMENT-side dominant spelling
    # (the site keys on it), the annotated forms are tracks-side.
    ('Beni Mora',                                     'Beni Mora - Oriental suite, Op 29 no 1'),
    ('Beni Mora - oriental suite',                    'Beni Mora - Oriental suite, Op 29 no 1'),
    # Holst Ave Maria: "(Hail Mary)" is a translation gloss, not an identity.
    ('Ave Maria (Hail Mary)',                         'Ave Maria'),
    # Holst St Paul's Suite: the op-less residue (mostly the stripped
    # arr-for-guitar-quartet forms -- literal transcription, same work).
    ("St Paul's Suite",                               "St Paul's Suite, Op 29 no 2"),
    # Imogen Holst Leiston Suite: bare form.
    ('Leiston Suite',                                 'Leiston Suite for brass quartet'),
    # Holst The Evening-Watch: bare vs op-numbered.
    ('The Evening-Watch',                             'The Evening-watch, Op 43, No 1'),
    # Holst Betelgeuse: 'Humber' typo.
    ('Betelgeuse, from 12 Humber Wolfe Songs, Op 48',
     'Betelgeuse, from 12 Humbert Wolfe Songs, Op 48'),
    # Holst Indra: segment-side 'Op,13' comma typo glues to 'op13'.
    ('Indra, Symphonic Poem (Op,13)',                 'Indra, Symphonic Poem (Op.13)'),

    # --- Paganini sweep (2026-07-16, curation.txt round 2): Nick spotted the
    #     Moto perpetuo / Perpetuum Mobile split on the live composer page;
    #     `ttn_curate audit-composer --composer Paganini` surfaced the rest.
    #     All corpus-verified spellings, all composer-exclusive keys.
    # Moto perpetuo, Op 11 (MS 66): Latin/Italian title twins; the spurious
    # 'No.2' is a BBC label, not a real opus subdivision; the unison-violins
    # orchestral version is a literal re-scoring (transcription-depth: folds).
    ('Perpetuum Mobile (Op.11 No.2)',                 'Moto perpetuo, Op 11'),
    # NB the BARE 'Perpetuum mobile' is deliberately NOT aliased here: Jeffes
    # and Novacek carry the same bare title, and a global bare->op-specific
    # alias would stamp Paganini's Op 11 into their keys (caught by the
    # registry-orphan probe). Rule: never alias a generic bare title to a
    # composer-specific target unless the bare key is corpus-exclusive.
    ('Moto perpetuo (Op.11) in C major vers. for orchestra', 'Moto perpetuo, Op 11'),
    # Duetto Amoroso: bare form.
    ('Duetto Amoroso',                                'Duetto Amoroso for violin and guitar'),
    # Moses fantaisie (MS 23): one work, five keys -- descriptive Bravura
    # annotations, the double-bass literal transcription (arr-stripped bare
    # form), the formal MS.23 title, and a Fantasy/fantaisie spelling. The
    # pre-existing pair above was re-pointed to this same final canonical.
    ('Moses fantaisie (after Rossini)',               'Moses fantaisie (after Rossini) for cello and piano'),
    ('Moses fantaisie (after Rossini) for cello and piano (Bravura Variations on one chord from a Rossini theme)',
     'Moses fantaisie (after Rossini) for cello and piano'),
    ('Moses Fantasy (after Rossini) for cello and piano (Bravura Variations on one chord from a Rossini theme)',
     'Moses fantaisie (after Rossini) for cello and piano'),
    ('Introduction and Variations on a theme from Rossini\'s "Mosè in Egitto" (MS.23)',
     'Moses fantaisie (after Rossini) for cello and piano'),
    # Centone di sonate, Op 64 No 3: collection-citation phrasings.
    ('Sonata for violin and guitar in C major, Op 64 No 3',
     'Sonata for violin and guitar No.3 in C major from Centone di sonate (Op.64)'),
    ('Sonata No 3 in C for violin and guitar, Op 64 (Centone di sonate)',
     'Sonata for violin and guitar No.3 in C major from Centone di sonate (Op.64)'),
    # Cantabile (MS 109, sometimes labelled Op 17).
    ('Cantabile, Op.17',                              'Cantabile'),
    # La Campanella: two phrasings of the SAME 3rd-movement excerpt (the
    # whole concerto keys separately and stays split).
    ("La Campanella, from 'Violin Concerto No. 2 in B minor, Op.7'",
     "Violin Concerto No 2 in B minor, Op 7 - 3rd movement 'La Campanella'"),
    # 24 Caprices, Op 1: the leading-'From' phrasing of No 11 (Nos 17/24 are
    # different caprices and stay split).
    ('From 24 Caprices for violin solo, Op 1: no 11 in C major',
     '24 Caprices Op 1 for violin solo No 11 in C major'),
    # I Palpiti, Op 13: short-form title.
    ("Variations on 'I Palpiti', Op 13",
     "I Palpiti - introduction and variations on Rossini's 'Di tanti palpiti', Op 13"),
    # 24 Caprices, round 2 (Nick, 2026-07-16): each caprice is one work but
    # the spellings vary along op-present / 'for solo violin' / collection-
    # citation / annotation axes, so single caprices key apart. Fold to the
    # dominant per-number spelling (blast-checked: every variant key is
    # Paganini-exclusive bar one performer-as-composer junk credit).
    # No 24 in A minor -- the famous one, was split 4 ways:
    ('Caprice in A minor, Op 1 no 24',                'Caprice no 24 in A minor'),
    ('Caprice no.24',                                 'Caprice no 24 in A minor'),
    ('Caprice no.24 in A minor (Theme and Variations) for solo violin (Op.1 No.24)',
     'Caprice no 24 in A minor'),
    ('24 Caprices for violin solo, Op 1 (No 24 in A minor: Theme and variations)',
     'Caprice no 24 in A minor'),
    # No 17 in E flat:
    ('Caprice for solo violin in E flat major, Op.1 no.17', 'Caprice No. 17 in E flat'),
    ('From 24 Caprices for violin solo (Op.1): no.17 in E flat major',
     'Caprice No. 17 in E flat'),
    # No 5 in A minor:
    ('Caprice No.5',                                  'Caprice No. 5 in A minor'),

    # --- Delius pass (2026-07-16, curation loop): the catalogue is largely
    #     consolidated (Walk to the Paradise Garden = one 109-row key); these
    #     are the stragglers. All Delius-exclusive keys (blast-checked).
    #     The "; On Craig Dhu" composite two-work credit is deliberately NOT
    #     folded (it would hide On Craig Dhu); "A song of summer, RT VI 25"
    #     has no sibling group to fold to. Spaced-Roman RT refs ("RT IV 5")
    #     = 3 rows corpus-wide, hand-aliased here, no gate.
    ('In a Summer Garden for orchestra',              'In a Summer Garden'),
    ('To be Sung of a Summer Night on the Water',
     'To be sung of a summer night on the water for chorus'),
    ('To be sung of a summer night on the water for chorus, RT IV 5',
     'To be sung of a summer night on the water for chorus'),
    ('On hearing the first cuckoo in spring for orchestra, RT VI 19 (Two Pieces for small orchestra, 1911/12)',
     'On hearing the first cuckoo in spring for orchestra (RT.6.19) (1911/12)'),
    ("Intermezzo (Fennimore and Gerda) - arr. Fenby from two of the opera's interludes",
     "Intermezzo [from 'Fennimore and Gerda']"),
    ('Cynara',                                        'Cynara for baritone and orchestra'),
    ('The Walk to the Paradise Garden (A Village Romeo and Juliet)',
     'The Walk to the Paradise Garden'),

    # --- Sibelius pass (2026-07-16, curation loop): 13 folds from the
    #     audit-composer clusters. DELIBERATE LEAVES: bare 'Valse Triste'
    #     (shared with Mignone) and bare 'Petite Suite' (Bartok + Debussy)
    #     are blast-radius-blocked ([[work-alias-blast-radius-rule]] class
    #     -- 25 + 35 airings of honest residue pending composer-scoped alias
    #     machinery); En Saga '1st version of 1892' stays split (authorial
    #     Fassung); Danses champetres 'nos 1 & 2' stays split from the 5-set
    #     (excerpt); Pelleas '(excerpts)' stays split (whole-vs-part); the
    #     4-song recital composites left for recording-fingerprint methods.
    ("Lemminkäinen's Return from Lemminkäinen Suite Op. 22",
     "Lemminkainen's Return (Lemminkainen Suite, Op 22)"),
    ("Lemminkainen suite (Op.22), no.4; Lemminkainen's return",
     "Lemminkainen's Return (Lemminkainen Suite, Op 22)"),
    # Rakastava: the dominant key already mixes the composer's own chorus and
    # string-orchestra scorings (arr-tails strip), so the suite-phrased
    # spelling joins it -- composer-authored re-scorings of one work.
    ('Rakastava - suite for string orchestra (Op.14)', 'Rakastava (The Lover), Op 14'),
    ('Suite Champêtre (Op.98b) (1. Pièce characteristique; 2. Mélodie élégiaque; 3. Danse)',
     'Suite Champêtre (Op.98b)'),
    ('Jordens sang, Op 93',                           'Jordens sang (Song of the Earth), Op 93'),
    ('Pensees Lyriques (Op.40) - No.1: Valsette; no.2: Chanson sans paroles; no.3: Humoresque; no.4: Minuetto; no.5: Berçeuse; no.6: Pensee melodique; no.7: Rondoletto; no.8: Scherzando; no.9: Petite serenade; no.10: Polonaise',
     '10 Pensees lyriques for piano, Op 40'),
    ('Valsette in E minor (Ten Pensees lyriques for piano, Op 40, No 1)',
     'Valsette in E minor - from 10 Pensées lyriques for piano (Op.40 No.1)'),
    ('Luonnotar, tone poem (Op.70) for soprano and orchestra', 'Luonnotar, Op 70'),
    ('Pelléas et Mélisande - incidental music Op.46', 'Pelléas et Mélisande, op. 46'),
    # En Saga: the bare form is Sibelius-exclusive across BOTH lineages
    # (32 rows), so the bare->op-anchored fold clears the blast-radius rule.
    ('En Saga',                                       'En Saga Op 9'),
    ('En Saga, Op.9 for orchestra',                   'En Saga Op 9'),
    ('Rondine (Op.81 No.2)',                          'Rondine for violin and piano, Op 81, No 2'),
    # Pa verandan vid havet: the bare-English spelling joins the Swedish
    # canonical (the old op-bearing-English pair above was re-pointed too).
    ('On a balcony by the sea',
     'Pa verandan vid havet (On a balcony by the sea) (Op.38 No.2)'),
]
