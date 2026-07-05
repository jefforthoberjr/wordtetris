"""Morpheme-distance suggestion matcher (a sibling of models/spell_check.py).

Where spell_check catches LETTER-level slips (a wrong vowel, a transposition),
this catches MORPHEME-level slips: the player built a real stem but hung the
wrong affix on it, or one affix too many. Examples the letter matcher can't:

    ABSOLUTIONIST -> ABSOLUTION   (drop a suffix: -IST too many)
    ABSOLUTIST    -> ABSOLUTISM   (swap a suffix: -IST for -ISM)
    REVISIONIST   -> REVISION     (drop a suffix)

MODEL: a word is PREFIX* + stem + SUFFIX*. A correction touches at most ONE
action on each SLOT -- the prefix end and the suffix end, independently:

    action    prefix          suffix
    remove    UN-x   -> x      x-NESS -> x
    add       x      -> UN-x   x      -> x-NESS
    swap      UN-x   -> DE-x   x-ENCE -> x-MENT

The morpheme DISTANCE is how many slots acted (1 or 2); it is the hard gate
(max_morpheme_distance). EXOTICNESS (ranking only) is the summed action cost:
each action has a base score (fix_remove / prefix_add / prefix_swap / suffix_add
/ suffix_swap), plus a CLASS surcharge for every special morpheme it touches:

  * common_inflection_comparative -- super-common plural/tense/comparative
    endings (-s, -ed, -er): heaviest surcharge, since "a plural" is rarely a
    useful "did you mean".
  * compounding  -- free words used as affixes (super-, -woman): near-compounds.
  * neoclassical -- Greek/Latin combining forms (anthro-, -graphy, kilo-).

The inventory and every score are passed in as a `model` dict (build_model), so
this module stays PURE -- no game, no config, no dictionary I/O. The one outside
fact it needs, "is this string a real word?", arrives as the `is_word` callable.
"""

# Standalone defaults (small sane subsets). The live game / CLI overrides ALL of
# these from config.yaml's morpheme_check block -- see build_model().
DEFAULT_PREFIXES = set(["re", "un", "dis", "pre", "over", "anti", "non", "mis"])
DEFAULT_SUFFIXES = set(["ist", "ism", "ion", "tion", "er", "ing", "ed", "ly",
                        "ness", "ment", "able", "ity", "ence", "ary"])
DEFAULT_COMMON_INFLECTION_COMPARATIVE = set(["es", "ies", "ed", "ied", "ing",
                                             "er", "ers", "est", "ier", "iest"])
DEFAULT_COMPOUNDING = set(["over", "under", "out", "super", "counter", "man",
                           "woman", "like", "proof"])
DEFAULT_NEOCLASSICAL = set(["ology", "graphy", "phobia", "anthro", "kilo"])
DEFAULT_SCORES = {
    "fix_remove_score": 2,                # remove any affix (prefix or suffix)
    "prefix_add_score": 5,                # add a prefix
    "prefix_swap_score": 4,               # swap one prefix for another
    "suffix_add_score": 4,                # add a suffix
    "suffix_swap_score": 3,               # swap one suffix for another
    "common_inflection_comparative_extra_score": 7,  # + per such morpheme touched
    "compounding_class_extra_score": 3,   # + per compounding morpheme touched
    "neoclassical_class_extra_score": 5,  # + per neoclassical morpheme touched
    "max_morpheme_distance": 2,           # most slots (sides) an action may touch
}


def build_model(block):
    """Assemble a morpheme `model` dict from a config `morpheme_check` block
    (falling back to the module defaults for any missing key). Pure: takes a
    plain dict, returns a plain dict; no I/O."""
    def _lower_set(key, default):
        vals = block.get(key)
        return set(v.lower() for v in vals) if vals else set(default)

    scores = dict(DEFAULT_SCORES)
    for key in DEFAULT_SCORES:
        if key in block:
            scores[key] = block[key]
    return {
        "prefixes": _lower_set("prefixes", DEFAULT_PREFIXES),
        "suffixes": _lower_set("suffixes", DEFAULT_SUFFIXES),
        "common_inflection_comparative": _lower_set(
            "common_inflection_comparative", DEFAULT_COMMON_INFLECTION_COMPARATIVE),
        "compounding": _lower_set("compounding", DEFAULT_COMPOUNDING),
        "neoclassical": _lower_set("neoclassical", DEFAULT_NEOCLASSICAL),
        "fix_remove_score": scores["fix_remove_score"],
        "prefix_add_score": scores["prefix_add_score"],
        "prefix_swap_score": scores["prefix_swap_score"],
        "suffix_add_score": scores["suffix_add_score"],
        "suffix_swap_score": scores["suffix_swap_score"],
        "common_inflection_comparative_extra":
            scores["common_inflection_comparative_extra_score"],
        "compounding_extra": scores["compounding_class_extra_score"],
        "neoclassical_extra": scores["neoclassical_class_extra_score"],
        "max_distance": scores["max_morpheme_distance"],
    }


# --- per-action cost ---------------------------------------------------------

def _class_extra(model, morpheme):
    """Surcharge for a special-class morpheme (heaviest class wins):
    common_inflection_comparative (7) > neoclassical (5) > compounding (3) >
    plain affix (0)."""
    if morpheme in model["common_inflection_comparative"]:
        return model["common_inflection_comparative_extra"]
    if morpheme in model["neoclassical"]:
        return model["neoclassical_extra"]
    if morpheme in model["compounding"]:
        return model["compounding_extra"]
    return 0


def _op(kind, action, morphemes, score):
    """A single morpheme-action record (carries a human label + its cost)."""
    if action == "swap":
        arrow = "-%s→-%s" if kind == "suffix" else "%s-→%s-"
        desc = "swap %s %s" % (kind, arrow % (morphemes[0].upper(),
                                              morphemes[1].upper()))
    else:
        fmt = "-%s" if kind == "suffix" else "%s-"
        verb = "drop" if action == "remove" else "add"
        desc = "%s %s %s" % (verb, kind, fmt % morphemes[0].upper())
    return {"kind": kind, "action": action, "morphemes": list(morphemes),
            "score": score, "desc": desc}


def _action_cost(model, kind, action, from_m, to_m):
    """(cost, op) for one slot action. `from_m` is the removed/swapped-out affix,
    `to_m` the added/swapped-in affix (either may be None)."""
    if action == "remove":
        base = model["fix_remove_score"]
        score = base + _class_extra(model, from_m)
        return score, _op(kind, "remove", [from_m], score)
    if action == "add":
        base = model[kind + "_add_score"]
        score = base + _class_extra(model, to_m)
        return score, _op(kind, "add", [to_m], score)
    base = model[kind + "_swap_score"]                       # swap
    score = base + _class_extra(model, from_m) + _class_extra(model, to_m)
    return score, _op(kind, "swap", [from_m, to_m], score)


# --- per-slot options --------------------------------------------------------

def _prefix_ops(word, model):
    """Every (word_after, cost, op, n_actions) for the PREFIX slot of `word`,
    including the identity (word, 0, None, 0). Applied to the front, so results
    are concrete words the suffix recipes then transform on the back."""
    ops = [(word, 0, None, 0)]
    pres = model["prefixes"]
    for p in pres:                                           # add
        cost, op = _action_cost(model, "prefix", "add", None, p)
        ops.append((p + word, cost, op, 1))
    for p in pres:
        if word.startswith(p) and len(word) > len(p):
            stem = word[len(p):]
            cost, op = _action_cost(model, "prefix", "remove", p, None)
            ops.append((stem, cost, op, 1))                  # remove
            for q in pres:                                   # swap
                if q != p:
                    cost, op = _action_cost(model, "prefix", "swap", p, q)
                    ops.append((q + stem, cost, op, 1))
    return ops


def _suffix_recipes(word, model):
    """SUFFIX-slot options as recipes to apply to any prefix-transformed `wp`
    (the back is untouched by a prefix action, so the matching set is fixed).
    Each is (action, from_affix, to_affix, cost, op, n_actions)."""
    recipes = [("keep", None, None, 0, None, 0)]
    sufs = model["suffixes"]
    for s in sufs:                                           # add
        cost, op = _action_cost(model, "suffix", "add", None, s)
        recipes.append(("add", None, s, cost, op, 1))
    for s in sufs:
        if word.endswith(s) and len(word) > len(s):
            cost, op = _action_cost(model, "suffix", "remove", s, None)
            recipes.append(("remove", s, None, cost, op, 1))  # remove
            for t in sufs:                                    # swap
                if t != s:
                    cost, op = _action_cost(model, "suffix", "swap", s, t)
                    recipes.append(("swap", s, t, cost, op, 1))
    return recipes


def _apply_suffix(wp, recipe):
    """Apply a suffix recipe to prefix-result `wp`, or None if it no longer fits
    (wp got too short after a prefix removal)."""
    action, s, t = recipe[0], recipe[1], recipe[2]
    if action == "keep":
        return wp
    if action == "add":
        return wp + t
    if not wp.endswith(s) or len(wp) <= len(s):
        return None
    base = wp[:-len(s)]
    return base if action == "remove" else base + t          # remove / swap


def suggest(typed, is_word, model, max_actions=None):
    """Real dictionary words within the morpheme model of `typed`: at most one
    action per slot, out to `max_actions` slots (default model max, capped at 2).

    Returns {word: {"distance", "exoticness", "ops"}}, keeping the best (fewest
    actions, then lowest exoticness) route to each. `typed` is never a hit.
    """
    if max_actions is None:
        max_actions = model["max_distance"]
    max_actions = min(max_actions, 2)
    w = typed.lower()
    prefix_ops = _prefix_ops(w, model)
    suffix_recipes = _suffix_recipes(w, model)
    best = {}
    for wp, cost_p, op_p, acts_p in prefix_ops:
        for recipe in suffix_recipes:
            acts = acts_p + recipe[5]
            if acts == 0 or acts > max_actions:
                continue
            cand = _apply_suffix(wp, recipe)
            if not cand or cand == w or not is_word(cand):
                continue
            exo = cost_p + recipe[3]
            prev = best.get(cand)
            if prev is None or (acts, exo) < (prev["distance"], prev["exoticness"]):
                ops = [op for op in (op_p, recipe[4]) if op]
                best[cand] = {"distance": acts, "exoticness": exo, "ops": ops}
    return best
