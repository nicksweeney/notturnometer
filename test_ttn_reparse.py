from ttn_reparse import diff_tracks


def test_diff_identical():
    a = [("t", "c", "cl", "[]", "ti", "p")]
    assert diff_tracks(a, a) == (0, 0)


def test_diff_count_gain():
    old = [("t", "c", "cl", "[]", "ti", "p")]
    new = old + [("t2", "c2", "cl2", "[]", "ti2", "p2")]
    assert diff_tracks(old, new) == (1, 0)


def test_diff_count_loss():
    old = [("a",), ("b",)]
    new = [("a",)]
    assert diff_tracks(old, new) == (-1, 0)


def test_diff_content_change_same_count():
    old = [("t", "OldComposer", "cl", "[]", "ti", "p")]
    new = [("t", "NewComposer", "cl", "[]", "ti", "p")]
    assert diff_tracks(old, new) == (0, 1)


def test_diff_empty_old():
    new = [("t", "c", "cl", "[]", "ti", "p")]
    assert diff_tracks([], new) == (1, 0)


def test_diff_empty_new():
    old = [("t", "c", "cl", "[]", "ti", "p")]
    assert diff_tracks(old, []) == (-1, 0)


def test_diff_count_and_content_together():
    # position 0 content-changed, position 1 added
    old = [("t", "Old", "cl", "[]", "ti", "p")]
    new = [("t", "New", "cl", "[]", "ti", "p"),
           ("t2", "c2", "cl2", "[]", "ti2", "p2")]
    assert diff_tracks(old, new) == (1, 1)
