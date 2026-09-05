from models.spell_check import (
    evaluate, distance_cap, count_vowel_runs,
    vowel_run_cost, consonant_run_cost,
    DEFAULT_COSTS, DEFAULT_SUFFIX_TAILS,
)


def _ok(typed, candidate):
    return evaluate(typed, candidate) is not None


# --- the design's accept cases (close, forgivable misspellings) ---

def test_accepts_diphthong_and_doubling():
    assert _ok("appauled", "appalled")     # AU->A drop + L->LL double


def test_accepts_consonant_dedup():
    assert _ok("appartment", "apartment")  # PP->P


def test_accepts_end_transposition():
    assert _ok("bottel", "bottle")         # ...EL <-> ...LE at the end
    assert _ok("centre", "center")         # ...RE <-> ...ER at the end


def test_accepts_sc_cluster_and_c_s_swap():
    assert _ok("sience", "science")        # S <-> SC cluster
    assert _ok("induse", "induce")         # S <-> C


def test_accepts_tch_class():
    assert _ok("wach", "watch")            # CH  -> TCH (dropped T)
    assert _ok("kichen", "kitchen")        # CH  -> TCH mid-word
    assert _ok("mutch", "much")            # TCH -> CH  (added T)


def test_accepts_single_vowel_swap():
    assert _ok("buttin", "button")         # I -> O


def test_accepts_midword_transposition_plus_suffix():
    # PER<->PRE transposition AND SION<->TION suffix swap together.
    assert _ok("perscripsion", "prescription")


# --- the design's reject cases (too far / changes the C/V layout) ---

def test_rejects_inserted_vowel_changes_skeleton():
    assert not _ok("diagnol", "diagonal")  # extra vowel = new V segment


def test_rejects_dropped_consonant():
    assert not _ok("aparment", "apartment")  # missing T is unforgivable


def test_rejects_two_transpositions():
    # One C/V swap is allowed; a second is not (contrived per the spec).
    assert not _ok("nday", "andy")


def test_rejects_short_words():
    # Under min_word_length (4): no suggestions even for a 1-letter swap.
    assert evaluate("cet", "cat") is None


def test_rejects_arbitrary_consonant_swap():
    assert not _ok("buppy", "bunny")       # P/N is not an allowed class


# --- unit-level checks on the pieces ---

def test_count_vowel_runs():
    assert count_vowel_runs("CART") == 1
    assert count_vowel_runs("CARTOON") == 2
    assert count_vowel_runs("CARTOONING") == 3


def test_distance_cap_scales_with_vowel_runs():
    assert distance_cap("CART") == 2          # floor
    assert distance_cap("CARTOON") == 2       # 2 runs, still floored
    assert distance_cap("CARTOONING") == 3    # 3 runs lifts the cap


def test_vowel_run_cost_classes():
    assert vowel_run_cost("A", "E", DEFAULT_COSTS)[0] == 2   # lone swap
    assert vowel_run_cost("AU", "A", DEFAULT_COSTS)[0] == 1  # drop
    assert vowel_run_cost("IE", "EI", DEFAULT_COSTS)[0] == 1  # reverse
    assert vowel_run_cost("A", "A", DEFAULT_COSTS) == (0, 0)


def test_consonant_run_cost_classes():
    cands = ("X", 0, DEFAULT_SUFFIX_TAILS)
    assert consonant_run_cost("S", "C", DEFAULT_COSTS, *cands)[0] == 2  # csk
    assert consonant_run_cost("G", "J", DEFAULT_COSTS, *cands)[0] == 3  # gj
    assert consonant_run_cost("L", "LL", DEFAULT_COSTS, *cands)[0] == 1  # dup
    assert consonant_run_cost("CH", "TCH", DEFAULT_COSTS, *cands)[0] == 2  # tch
    # T is in both td_class (3) and tch_class (2); the cheaper class wins.
    assert consonant_run_cost("T", "CH", DEFAULT_COSTS, *cands)[0] == 2
    assert consonant_run_cost("P", "N", DEFAULT_COSTS, *cands) is None   # bad


def test_consonant_suffix_swap_is_cheap_and_contextual():
    # T<->S is only allowed inside a recognized morpheme ending.
    assert consonant_run_cost(
        "S", "T", DEFAULT_COSTS, "PRESCRIPTION", 8, DEFAULT_SUFFIX_TAILS)[0] == 1
    assert consonant_run_cost(
        "S", "T", DEFAULT_COSTS, "STOP", 0, DEFAULT_SUFFIX_TAILS) is None


def test_exoticness_ranks_closer_spelling_lower():
    # A pure doubling (exoticness 1) should score below a lone vowel swap (2).
    near = evaluate("appartment", "apartment")
    far = evaluate("buttin", "button")
    assert near["exoticness"] < far["exoticness"]
