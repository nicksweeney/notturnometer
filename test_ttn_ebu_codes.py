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
    # Every entry: 3-tuple, 2-letter country_code matching the code prefix.
    # (cc is code[:2] by transcription, so the prefix match is always satisfied;
    # no code needed the prefix assertion relaxed.)
    for code, (name, cc, cname) in EBU_CODES.items():
        assert len(cc) == 2 and code.startswith(cc), code
        assert name and cname


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


def test_every_ebu_country_code_flags():
    for _name, cc, _country in EBU_CODES.values():
        assert flag(cc) != "", cc
