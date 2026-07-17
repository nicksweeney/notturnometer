from ttn_ebu_codes import decode, EBU_CODES, flag, fold, is_ebu_code


def test_decode_known_code():
    assert decode("GBBBC") == ("BBC", "GB", "United Kingdom")
    assert decode("PLPR")[2] == "Poland"


def test_decode_unknown_falls_back_to_raw_code_and_prefix():
    # Unknown: name = the raw code, country_code/name = first two chars.
    assert decode("ZZXYZ") == ("ZZXYZ", "ZZ", "ZZ")


def test_decode_handles_empty_and_none():
    assert decode("") == ("", "", "")
    assert decode(None) == ("", "", "")


def test_table_values_are_well_formed():
    # Every entry: 3-tuple, 2-letter country_code. cc is code[:2] by
    # transcription for the standard 2+3 EBU codes, so the prefix match
    # normally holds -- but a few labels the BBC actually emits are IRREGULAR
    # (not country-prefixed), and their cc is the real ISO country, not
    # code[:2]. NCRV (KRO-NCRV, a Dutch broadcaster labelled 'NCRV' not
    # 'NL...') is the case that exposed a mis-transcription: cc had been "NC"
    # (New Caledonia's flag!) instead of "NL". Such codes are allowlisted.
    _IRREGULAR = {"NCRV"}
    for code, (name, cc, cname) in EBU_CODES.items():
        assert len(cc) == 2 and cc.isalpha(), code
        if code not in _IRREGULAR:
            assert code.startswith(cc), code
        assert name and cname


def test_ncrv_is_dutch_not_new_caledonian():
    # Regression: the code is the irregular 'NCRV' label but the broadcaster
    # is Dutch -- cc must flag the Netherlands, never New Caledonia ("NC").
    name, cc, country = decode("NCRV")
    assert country == "Netherlands"
    assert flag(cc) == "\U0001F1F3\U0001F1F1"      # NL, not NC


def test_fold_collapses_variant_and_case():
    assert fold("NLNLOS") == "NLNOS"
    assert fold("chsrf") == "CHSRF"
    assert is_ebu_code("NLNLOS")
    assert is_ebu_code("nlnos")


def test_non_ebu_label_not_recognized():
    assert not is_ebu_code("Decca")
    assert not is_ebu_code("BBC recording")


def test_flag_regional_indicators_for_iso_codes():
    assert flag("GB") == "\U0001F1EC\U0001F1E7"
    assert flag("hu") == "\U0001F1ED\U0001F1FA"   # case-folded
    assert flag("") == "" and flag(None) == ""
    assert flag("GBR") == "" and flag("G1") == ""  # not exactly two A-Z letters


def test_flag_pseudo_and_withdrawn_codes_go_flagless():
    assert flag("ZZ") == ""    # multilateral EBU relay, not a country
    assert flag("CS") == ""    # withdrawn Serbia-and-Montenegro ISO code


def test_country_flag_by_name():
    from ttn_ebu_codes import country_flag
    assert country_flag("Germany") == "\U0001F1E9\U0001F1EA"      # DE
    assert country_flag("Netherlands") == "\U0001F1F3\U0001F1F1"  # NL, not NC
    assert country_flag("Unknownland") == ""                     # unknown name
    assert country_flag("") == ""


def test_every_real_ebu_country_code_flags():
    for _name, cc, _country in EBU_CODES.values():
        if cc in ("ZZ", "CS"):   # pseudo/withdrawn codes stay flagless
            continue
        assert flag(cc) != "", cc
