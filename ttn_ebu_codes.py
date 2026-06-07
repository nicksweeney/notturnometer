#!/usr/bin/env python3
"""EBU source-broadcaster codes -> (broadcaster_name, country_code, country_name).

The `record_label` on segment_events is the EBU source-identifier of the
broadcaster that supplied the recording. The first two letters are an ISO-3166
country code; the remainder identifies the broadcaster. This table decodes the
high-volume codes (the seeded set covers the large majority of airings); unknown
codes fall back to the raw code + its 2-letter prefix, so nothing is mis-named.

Values verified against the BBC/EBU source list; extend as new codes surface
(run ttn_broadcasters.py --csv and eyeball the raw-code rows in the tail).
"""

EBU_CODES = {
    "GBBBC": ("BBC", "GB", "United Kingdom"),
    "PLPR":  ("Polish Radio", "PL", "Poland"),
    "CACBC": ("CBC/Radio-Canada", "CA", "Canada"),
    "DEWDR": ("WDR", "DE", "Germany"),
    "NONRK": ("NRK", "NO", "Norway"),
    "SESR":  ("Sveriges Radio", "SE", "Sweden"),
    "DKDR":  ("DR", "DK", "Denmark"),
    "NLNOS": ("NOS", "NL", "Netherlands"),
    "CHSRF": ("SRF", "CH", "Switzerland"),
    "FIYLE": ("Yle", "FI", "Finland"),
    "AUABC": ("ABC", "AU", "Australia"),
    "HUMR":  ("Magyar Radio", "HU", "Hungary"),
    "SIRTVS": ("RTV Slovenija", "SI", "Slovenia"),
    "BGBNR": ("Bulgarian National Radio", "BG", "Bulgaria"),
    "SKSR":  ("Slovak Radio", "SK", "Slovakia"),
    "HRHRT": ("HRT", "HR", "Croatia"),
    "BEVRT": ("VRT", "BE", "Belgium"),
    "ROROR": ("Radio Romania", "RO", "Romania"),
    "ESCAT": ("Catalunya Radio", "ES", "Spain"),
    "CZCR":  ("Czech Radio", "CZ", "Czechia"),
    "KRKBS": ("KBS", "KR", "South Korea"),
    "EEER":  ("Eesti Rahvusringhaaling", "EE", "Estonia"),
    "LVLR":  ("Latvijas Radio", "LV", "Latvia"),
    "BERTBF": ("RTBF", "BE", "Belgium"),
    "LTLR":  ("Lietuvos Radijas", "LT", "Lithuania"),
    "ATORF": ("ORF", "AT", "Austria"),
    "SKRTVS": ("RTVS", "SK", "Slovakia"),
    "CHRSI": ("RSI", "CH", "Switzerland"),
}


def decode(code):
    """(name, country_code, country_name). Unknown non-empty code falls back to
    (code, code[:2], code[:2]); empty/None -> ('', '', '')."""
    if not code:
        return ("", "", "")
    if code in EBU_CODES:
        return EBU_CODES[code]
    return (code, code[:2], code[:2])
