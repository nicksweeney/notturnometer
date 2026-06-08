from ttn_segment_meta import INTERSTITIAL_RECORDING_PIDS, is_interstitial


def test_known_interstitials_flagged():
    assert is_interstitial("p03hd05x")      # Milhaud Cheminée (827x, 32s)
    assert is_interstitial("p02ggvkg")      # Milhaud Madrigal-Nocturne (381x)
    assert {"p03hd05x", "p02ggvkg"} <= INTERSTITIAL_RECORDING_PIDS


def test_normal_recording_and_none_not_interstitial():
    assert not is_interstitial("p00swz7q")  # a real Milhaud Scaramouche recording
    assert not is_interstitial(None)
    assert not is_interstitial("")
