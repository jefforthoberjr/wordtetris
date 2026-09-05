"""rule_grams_greater_than_47_lengthcontrolled: the gram_length.* shares are enforced as a quota
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
        grams += gp.pick_grams(gp.rule_grams_greater_than_47_lengthcontrolled, 2)
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
    # Overridden in CONFIG, not on a module constant: the shares are read at draw
    # time (_length_pct_weights), which is what lets a game mode override them.
    rules = CONFIG["rules"]
    saved = {k: rules[k] for k in (
        "gram_length.unigram_percent",
        "gram_length.digram_percent",
        "gram_length.trigramplus_percent")}
    rules["gram_length.unigram_percent"] = 50
    rules["gram_length.digram_percent"] = 50
    rules["gram_length.trigramplus_percent"] = 0
    try:
        counts = Counter(_category(g) for g in _run_formation(40))
        assert counts[3] == 0
        assert counts[1] > 0 and counts[2] > 0
    finally:
        rules.update(saved)


def test_length_shares_track_a_later_config_swap():
    # gram_length.*_percent used to be frozen into a module constant at import,
    # so a game mode's override (applied after import) was silently ignored --
    # hydra mode's all-unigram opening board depends on this not regressing.
    rules = CONFIG["rules"]
    saved = {k: rules[k] for k in (
        "gram_length.unigram_percent",
        "gram_length.digram_percent",
        "gram_length.trigramplus_percent")}
    rules["gram_length.unigram_percent"] = 100
    rules["gram_length.digram_percent"] = 0
    rules["gram_length.trigramplus_percent"] = 0
    try:
        # "QU" is drawn from the unigram bucket but is two characters long, so
        # count by BUCKET (the picker's own convention), not by len() -- otherwise
        # this passes or fails depending on where the shared RNG happens to be.
        grams = _run_formation(40)
        strays = [g.text for g in grams if _category(g) != 1 and g.text != "QU"]
        assert not strays, strays
    finally:
        rules.update(saved)


def test_forced_length_is_cleared_after_formation():
    _run_formation(20)
    assert gp._forced_length is None
    assert gp._forced_unigram_group is None


# --- nested unigram sub-bin quota (common glue vs uncommon flavor) ------

_COMMON = set(gp._COMMON_GLUE_LETTERS)
_FLAVOR = set(gp._UNCOMMON_FLAVOR_LETTERS)


def _unigram_groups(grams):
    # Split the formation's unigram cells into the two configured bins. Every
    # length-1 (or QU) cell belongs to exactly one bin.
    counts = Counter()
    for g in grams:
        if g.text in _COMMON:
            counts["common"] += 1
        elif g.text in _FLAVOR:
            counts["uncommon"] += 1
    return counts


def test_glue_letters_and_flavor_letters_partition_the_alphabet():
    # 25 single letters (every letter but Q) + QU, no overlap.
    assert _COMMON.isdisjoint(_FLAVOR)
    singles = {x for x in _COMMON | _FLAVOR if len(x) == 1}
    assert singles == set("ABCDEFGHIJKLMNOPRSTUVWXYZ")  # no lone Q
    assert "QU" in _FLAVOR


def test_unigram_group_split_enforced_within_one():
    common_w = CONFIG["rules"]["gram_length.unigram_common_percent"]
    uncommon_w = CONFIG["rules"]["gram_length.unigram_uncommon_percent"]
    total = common_w + uncommon_w
    for _ in range(30):
        counts = _unigram_groups(_run_formation(96))
        n = counts["common"] + counts["uncommon"]
        assert abs(counts["common"] - n * common_w / total) <= 1.0
        assert abs(counts["uncommon"] - n * uncommon_w / total) <= 1.0


def test_zero_common_share_yields_only_flavor_unigrams():
    saved = list(gp._UNIGRAM_GROUP_WEIGHTS)
    gp._UNIGRAM_GROUP_WEIGHTS[:] = [0, 100]
    try:
        counts = _unigram_groups(_run_formation(80))
        assert counts["common"] == 0
        assert counts["uncommon"] > 0
    finally:
        gp._UNIGRAM_GROUP_WEIGHTS[:] = saved


def test_qu_is_eligible_as_a_flavor_unigram():
    # All-flavor config; over enough boards QU (the lone Q route) must appear.
    saved = list(gp._UNIGRAM_GROUP_WEIGHTS)
    gp._UNIGRAM_GROUP_WEIGHTS[:] = [0, 100]
    try:
        seen = set()
        for _ in range(60):
            seen.update(g.text for g in _run_formation(60))
        assert "QU" in seen
    finally:
        gp._UNIGRAM_GROUP_WEIGHTS[:] = saved
