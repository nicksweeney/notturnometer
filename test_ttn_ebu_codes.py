from ttn_ebu_codes import decode, EBU_CODES


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
    # Every seeded entry: 3-tuple, 2-letter country_code matching the code prefix.
    for code, (name, cc, cname) in EBU_CODES.items():
        assert len(cc) == 2 and code.startswith(cc), code
        assert name and cname
