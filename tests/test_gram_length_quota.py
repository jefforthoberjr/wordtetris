"""rule_grams_lengthcontrolled: the gram_length.* shares are enforced as a quota
across the opening formation (counts land within ~1 of the configured split),
while outside the formation each cell just rolls them."""
from collections import Counter

import models.gram_picker as gp
from config import CONFIG


def _category(gram):
    # Length bucket the way the picker partitions the corpus: 1, 2, or 3+ -> 3.
    return min(len(gram.text), 3)


def _shares():
    rules = CONFIG["rules"]
    return {
        1: rules["gram_length.unigram_percent"],
        2: rules["gram_length.digram_percent"],
        3: rules["gram_length.trigramplus_percent"],
    }


def _run_formation(cells):
    """Draw `cells` formation grams two-at-a-time (as dominos do), through the
    real pick_grams choke point with the formation bracket active."""
    gp.reset_gram_dedup()
    gp.begin_formation_gram_run()
    grams = []
    while len(grams) < cells:
        grams += gp.pick_grams(gp.rule_grams_lengthcontrolled, 2)
    gp.end_formation_gram_run()
    return grams[:cells]


def test_formation_quota_within_one_of_ideal():
    shares = _shares()
    total = sum(shares.values())
    cells = 64
    counts = Counter(_category(g) for g in _run_formation(cells))
    for category, share in shares.items():
        ideal = cells * share / total
        assert abs(counts[category] - ideal) <= 1.0, (
            f"len{category}: got {counts[category]}, ideal {ideal:.1f}"
        )


def test_formation_quota_is_stable_across_boards():
    # The quota must hold every game, not just on average -- the whole point is
    # that a board can't come out trigram-heavy by luck.
    shares = _shares()
    total = sum(shares.values())
    cells = 64
    for _ in range(50):
        counts = Counter(_category(g) for g in _run_formation(cells))
        for category, share in shares.items():
            ideal = cells * share / total
            assert abs(counts[category] - ideal) <= 1.0


def test_zero_share_category_never_drawn_in_formation():
    # Pin the trigram share to 0 and confirm the formation has no 3+ grams.
    saved = list(gp._LENGTH_PCT_WEIGHTS)
    gp._LENGTH_PCT_WEIGHTS[:] = [50, 50, 0]
    try:
        counts = Counter(_category(g) for g in _run_formation(40))
        assert counts[3] == 0
        assert counts[1] > 0 and counts[2] > 0
    finally:
        gp._LENGTH_PCT_WEIGHTS[:] = saved


def test_forced_length_is_cleared_after_formation():
    _run_formation(20)
    assert gp._forced_length is None
