"""Right-click gram manipulation (game_screen.rightclick_*): the pure text
transforms and the vowel/consonant shape classifier that routes a gram to its
config slot.

These had no coverage before being extracted from game_screen.py into
views/game_screen_grammanip.py, so this pins the behavior the extraction had to
preserve. The dispatcher itself (_handle_gram_manipulate) needs a live board and
is exercised by playtest.
"""
from views import game_screen_grammanip as gm


def test_unigram_doubles():
    assert gm.rule_unigram_double("O") == "OO"
    assert gm.rule_unigram_double("B") == "BB"


def test_doubled_pairs_collapse():
    assert gm.rule_cc_collapse("LL") == "L"
    assert gm.rule_vv_collapse("EE") == "E"


def test_cvk_doubling_alternates_by_side():
    # MER doubles its consonant on the requested side; the dispatcher alternates
    # the side per cell so a round trip reads MER -> MMER -> MER -> MERR.
    assert gm.rule_cvk_double("MER", "front") == "MMER"
    assert gm.rule_cvk_double("MER", "back") == "MERR"


def test_none_rule_leaves_the_gram_untouched():
    # The pre-feature behavior: returning None tells the dispatcher to relabel
    # nothing.
    assert gm.rule_rightclick_none("ANY") is None


def test_shape_classifier_routes_by_vowel_consonant_shape():
    assert gm._gram_manip_family("LL") == "cc"
    assert gm._gram_manip_family("BA") == "cv"
    assert gm._gram_manip_family("AN") == "vc"
    assert gm._gram_manip_family("EA") == "vv"
    assert gm._gram_manip_family("ARE") == "vcv"
    assert gm._gram_manip_family("MER") == "cvk"


def test_y_counts_as_a_consonant():
    # Deliberate: with Y as a vowel, ARY/ITY would read as VCV/CVK and doubling
    # them never lands in real words.
    assert gm._gram_manip_family("ARY") != "vcv"


def test_unmatched_shapes_are_a_no_op():
    # CKV / VCK / CKS were analyzed and given no doubling rule.
    assert gm._gram_manip_family("STA") is None


def test_every_rule_name_resolves_in_the_registry():
    # The registry is what GameScreen.__init__ hands select_rule for the nine
    # rightclick_* config slots, so a name missing here is a startup crash.
    for name, fn in gm._GRAM_MANIP_RULES.items():
        assert callable(fn), name
        assert fn.__name__ == name
