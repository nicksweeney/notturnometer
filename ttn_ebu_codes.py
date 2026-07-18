#!/usr/bin/env python3
"""EBU source-broadcaster codes -> (broadcaster_name, country_code, country_name).

The `record_label` on segment_events is the EBU source-identifier of the
broadcaster that supplied the recording. The first two letters are an ISO-3166
country code; the remainder identifies the broadcaster. This table is the
verified _EBU_SOURCES allowlist (84 broadcasters), covering ~all of the EBU
source segments; unknown non-empty codes fall back to the raw code + its
2-letter prefix, so nothing is mis-named. Variant/typo/legacy codes fold to
their canonical via VARIANTS before lookup.

Values verified against the EBU "List of Members 2021-22"; extend as new codes
surface (run ttn_broadcasters.py --csv and eyeball the raw-code rows in the tail).
"""

# EBU_CODES: code -> (broadcaster_name, country_code, country_name).
# Transcribed from the verified _EBU_SOURCES table (country, name) by reordering
# to (name, code[:2], country). 84 entries.
EBU_CODES = {
    "GBBBC": ("BBC", "GB", "United Kingdom"),
    "IERTE": ("RTÉ – Raidió Teilifís Éireann", "IE", "Ireland"),
    "PLPR":  ("Polskie Radio", "PL", "Poland"),
    "DEWDR": ("WDR – Westdeutscher Rundfunk", "DE", "Germany"),
    "DENDR": ("NDR – Norddeutscher Rundfunk", "DE", "Germany"),
    "DEBR":  ("BR – Bayerischer Rundfunk", "DE", "Germany"),
    "DEMDR": ("MDR – Mitteldeutscher Rundfunk", "DE", "Germany"),
    "DEHR":  ("HR – Hessischer Rundfunk", "DE", "Germany"),
    "DERB":  ("Radio Bremen", "DE", "Germany"),
    "DERBBB":("RBB – Rundfunk Berlin-Brandenburg", "DE", "Germany"),
    "DESWRB":("SWR – Südwestrundfunk", "DE", "Germany"),
    "DESR":  ("SR – Saarländischer Rundfunk", "DE", "Germany"),
    "DEDKU": ("Deutschlandradio (Kultur)", "DE", "Germany"),
    "NONRK": ("NRK", "NO", "Norway"),
    "SESR":  ("SR – Sveriges Radio", "SE", "Sweden"),
    "DKDR":  ("DR", "DK", "Denmark"),
    "FIYLE": ("Yle", "FI", "Finland"),
    "ISRUV": ("RÚV – Ríkisútvarpið", "IS", "Iceland"),
    "NLNOS": ("NOS (NPO)", "NL", "Netherlands"),
    "NLNPO": ("NPO – Nederlandse Publieke Omroep", "NL", "Netherlands"),
    "NLNPB": ("Netherlands public radio (NPO/Radio 4 music ensembles)", "NL", "Netherlands"),
    "NCRV":  ("KRO-NCRV (NPO member)", "NL", "Netherlands"),
    "CHSRF": ("SRF (German)", "CH", "Switzerland"),
    "CHRTS": ("RTS (French)", "CH", "Switzerland"),
    "CHRSI": ("RSI (Italian)", "CH", "Switzerland"),
    "CHRSR": ("RSR (French radio, old RTS name)", "CH", "Switzerland"),
    "CHRTSI":("RTSI (Italian, old RSI name)", "CH", "Switzerland"),
    "CHSSR": ("SRG SSR (umbrella)", "CH", "Switzerland"),
    "CHRR":  ("SRG SSR – Suisse Romande", "CH", "Switzerland"),
    "BEVRT": ("VRT (Flemish)", "BE", "Belgium"),
    "BERTBF":("RTBF (French)", "BE", "Belgium"),
    "BERTEM":("Radio Télé Music (RTEM)", "BE", "Belgium"),
    "ITRAI": ("RAI", "IT", "Italy"),
    "ESRTVE":("RTVE (national)", "ES", "Spain"),
    "ESCAT": ("Catalunya Música (Catalan classical)", "ES", "Spain"),
    "PTRDP": ("RTP – RDP (radio)", "PT", "Portugal"),
    "FRSRF": ("Radio France", "FR", "France"),
    "ATORF": ("ORF", "AT", "Austria"),
    "CZCR":  ("Český rozhlas", "CZ", "Czechia"),
    "SKSR":  ("Slovak Radio (legacy; now RTVS)", "SK", "Slovakia"),
    "SKRTVS":("RTVS", "SK", "Slovakia"),
    "SKSTVR":("STVR (2025 rename of RTVS)", "SK", "Slovakia"),
    "HUMR":  ("Magyar Rádió (legacy)", "HU", "Hungary"),
    "HUMTVA":("MTVA (current)", "HU", "Hungary"),
    "SIRTVS":("RTV Slovenija", "SI", "Slovenia"),
    "HRHRT": ("HRT", "HR", "Croatia"),
    "ROROR": ("Radio România (SRR)", "RO", "Romania"),
    "BGBNR": ("BNR – Bulgarian National Radio", "BG", "Bulgaria"),
    "RSRTS": ("RTS – Radiotelevizija Srbije", "RS", "Serbia"),
    "CSRTS": ("RTS (legacy 'CS' country code)", "CS", "Serbia"),
    "RSRTV": ("RTRS – Radio-televizija Republike Srpske", "RS", "Bosnia (Rep. Srpska)"),
    "MKRTV": ("MKRTV", "MK", "North Macedonia"),
    "MDTRM": ("Teleradio-Moldova", "MD", "Moldova"),
    "GRERT": ("ERT", "GR", "Greece"),
    "LUERSL":("ERSL", "LU", "Luxembourg"),
    "MCMMD": ("Monaco Média Diffusion", "MC", "Monaco"),
    "MCRMC": ("Radio Monte Carlo", "MC", "Monaco"),
    "VARV":  ("Radio Vaticana", "VA", "Vatican"),
    "EEER":  ("ERR – Eesti Rahvusringhääling", "EE", "Estonia"),
    "LVLR":  ("Latvijas Radio", "LV", "Latvia"),
    "LVLPSM":("LSM – Latvijas Sabiedriskais medijs (Latvian Public Media)", "LV", "Latvia"),
    "LTLR":  ("Lietuvos radijas (LRT)", "LT", "Lithuania"),
    "RUOP":  ("Radio Orpheus (Radio Dom Ostankino)", "RU", "Russia"),
    "RURTR": ("RTR – Rossijskoe Teleradio", "RU", "Russia"),
    "UANRCU":("National Radio Company of Ukraine", "UA", "Ukraine"),
    "UAPBC": ("UA:PBC", "UA", "Ukraine"),
    "BYBTRC":("National State Teleradiocompany (suspended)", "BY", "Belarus"),
    "AUABC": ("ABC", "AU", "Australia"),
    "NZRNZ": ("RNZ", "NZ", "New Zealand"),
    "KRKBS": ("KBS", "KR", "South Korea"),
    "JPNHK": ("NHK", "JP", "Japan"),
    "CNSMG": ("Shanghai Media Group", "CN", "China"),
    "BRRC":  ("Rádio Cultura", "BR", "Brazil"),
    "MXUNAM":("Radio UNAM", "MX", "Mexico"),
    "CACBC": ("CBC (English)", "CA", "Canada"),
    "CASRC": ("SRC – Société Radio-Canada (French)", "CA", "Canada"),
    "USAPM": ("American Public Media", "US", "USA"),
    "USWGBH":("WGBH Boston", "US", "USA"),
    "USMPR": ("Minnesota Public Radio", "US", "USA"),
    "USWFMT":("WFMT Chicago", "US", "USA"),
    "USWCLV":("WCLV Cleveland", "US", "USA"),
    "ZZEBU": ("EBU / Euroradio shared relay", "ZZ", "(multilateral)"),
    "CHEUR": ("EBU / Euroradio international relay (guest orchestras)", "CH", "(multilateral)"),
}

# Typo/legacy code folds (bad -> canonical), transcribed from _EBU_VARIANTS.
VARIANTS = {
    # VRT's pre-1998 name: the same Flemish broadcaster before its rename,
    # folded so the institution ranks (and flags) as one -- the old separate
    # entry carried the legacy 'BR' prefix as its country code and wrongly
    # flagged as Brazil (13 corpus airings).
    "BRTN":   "BEVRT",
    "NLNLOS": "NLNOS",
    "HRHRTR": "HRHRT",
    "CHRSRI": "CHRSI",
    "CHSRI":  "CHRSI",
    "EEERR":  "EEER",
    "USWFTM": "USWFMT",
    "BERTF":  "BERTBF",
    "UANRU":  "UANRCU",
    "NLNLPB": "NLNPB",
    "BNBGR":  "BGBNR",
}


def fold(code):
    """Normalize a raw record_label to a canonical EBU code: strip + uppercase,
    then apply known variant/typo folds. Does NOT assert the result is real."""
    if not code:
        return ""
    c = code.strip().upper()
    return VARIANTS.get(c, c)


def is_ebu_code(code):
    """True if `code` (after fold) is a recognized EBU source broadcaster."""
    return fold(code) in EBU_CODES


def decode(code):
    """(broadcaster_name, country_code, country_name). Recognized -> from
    EBU_CODES after fold; empty/None -> ('','',''); unrecognized non-empty ->
    (code, code[:2], code[:2])."""
    if not code:
        return ("", "", "")
    c = fold(code)
    if c in EBU_CODES:
        return EBU_CODES[c]
    return (code, code[:2], code[:2])


# Pseudo/withdrawn country codes that must NOT flag: ZZ is the multilateral
# EBU/Euroradia shared relay, not a country (the EU flag was contemplated and
# rejected -- the EBU is not an EU organisation); CS is the withdrawn
# Serbia-and-Montenegro ISO code, which no platform renders as a flag.
_NO_FLAG_COUNTRIES = {"ZZ", "CS"}

# Country NAMES whose flag is deliberately suppressed even though a code
# exists -- a politically contested attribution where flying EITHER candidate
# flag takes a side. RTRS (Radio-televizija Republike Srpske) is coded RSRTV:
# the RS prefix is Serbia's ISO code, but the broadcaster is in Bosnia (BA);
# Republika Srpska is a contested entity WITHIN Bosnia, so Serbia's flag
# would be factually wrong and read as endorsing the Serb-nationalist framing,
# while asserting Bosnia's flag is itself a stance we decline to take for now.
# Show neither. Keyed on the NAME (not the RS code) so real Serbia keeps its
# flag and a future Bosnian STATE broadcaster (cc BA) would not inherit this.
# See CLAUDE.md / the ebu-bosnia-flag-suppressed memory. Decision 2026-07-17.
_NO_FLAG_COUNTRY_NAMES = {"Bosnia (Rep. Srpska)"}


def flag(country_code):
    """The flag emoji for a 2-letter ISO country code (two Unicode regional
    indicators), or '' for anything that isn't exactly two A-Z letters or is
    a pseudo/withdrawn code (_NO_FLAG_COUNTRIES). Callers must pass a REAL
    country code (e.g. decode()[1] of a recognized EBU code) -- decode()'s
    unrecognized-label fallback returns the label's first two letters as a
    pseudo country, which would flag as garbage, so gate on is_ebu_code()
    first for arbitrary record_label input."""
    cc = (country_code or "").upper()
    if len(cc) != 2 or not cc.isalpha() or not cc.isascii():
        return ""
    if cc in _NO_FLAG_COUNTRIES:
        return ""
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in cc)


# country_name -> ISO country_code, built from EBU_CODES (many codes roll up to
# one name -- the country rollup's grouping key). When a name has codes with
# DIFFERENT ccs, prefer one that actually FLAGS over a legacy/flagless one:
# Serbia carries both RSRTS (cc RS, the live flag) and CSRTS (cc CS, the
# withdrawn Serbia-and-Montenegro code that flag() suppresses), and a plain
# last-wins dict would leave Serbia flagless. Used by the site's country
# flags, which have the NAME, not a code.
_COUNTRY_TO_CC: dict = {}
for _code, (_n, _cc, _country) in EBU_CODES.items():
    _prev = _COUNTRY_TO_CC.get(_country)
    if _prev is None or (not flag(_prev) and flag(_cc)):
        _COUNTRY_TO_CC[_country] = _cc


def country_flag(country_name):
    """The flag emoji for a source-country NAME (via its ISO code), or '' for
    an unknown name, a pseudo/multilateral country (flag() gates ZZ/CS), or a
    name on the deliberate-suppression list (_NO_FLAG_COUNTRY_NAMES)."""
    if country_name in _NO_FLAG_COUNTRY_NAMES:
        return ""
    return flag(_COUNTRY_TO_CC.get(country_name, ""))


def flag_for(code):
    """Flag emoji for an EBU source CODE, the single code-based flag path:
    honours BOTH the cc-based suppression (_NO_FLAG_COUNTRIES via flag()) and
    the country-name-based one (_NO_FLAG_COUNTRY_NAMES) -- so a code whose cc
    would flag the wrong/contested country (RSRTV -> RS) comes out flagless.
    '' for an unrecognized code too (decode's fallback cc is not a real ISO
    code, but callers should still gate on is_ebu_code for arbitrary input)."""
    _name, cc, country = decode(code)
    if country in _NO_FLAG_COUNTRY_NAMES:
        return ""
    return flag(cc)
