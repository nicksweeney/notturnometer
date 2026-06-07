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
    "NCRV":  ("KRO-NCRV (NPO member)", "NC", "Netherlands"),
    "CHSRF": ("SRF (German)", "CH", "Switzerland"),
    "CHRTS": ("RTS (French)", "CH", "Switzerland"),
    "CHRSI": ("RSI (Italian)", "CH", "Switzerland"),
    "CHRSR": ("RSR (French radio, old RTS name)", "CH", "Switzerland"),
    "CHRTSI":("RTSI (Italian, old RSI name)", "CH", "Switzerland"),
    "CHSSR": ("SRG SSR (umbrella)", "CH", "Switzerland"),
    "CHRR":  ("SRG SSR – Suisse Romande", "CH", "Switzerland"),
    "BEVRT": ("VRT (Flemish)", "BE", "Belgium"),
    "BERTBF":("RTBF (French)", "BE", "Belgium"),
    "BRTN":  ("VRT (legacy name 'BRTN', pre-1998)", "BR", "Belgium"),
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
