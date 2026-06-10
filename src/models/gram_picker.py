import csv
import os
import random
import string

from models.gram import Gram
from models.wild_vowel import is_vowel


_scrabble_letters = None
_scrabble_weights = None
_english_words = None
_corpus_grams = None
_corpus_weights = None
_digrams52 = None
_digrams52_weights = None


def _load_scrabble_distribution():
    global _scrabble_letters, _scrabble_weights
    if _scrabble_letters is not None:
        return

    _scrabble_letters = []
    _scrabble_weights = []

    csv_path = os.path.join(os.path.dirname(__file__), 'gram_corpus', 'scrabble_letters.csv')
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            _scrabble_letters.append(row['letter'])
            _scrabble_weights.append(int(row['count']))


def rule_random_letters(count):
    """
    Pick grams for a piece using pure random single letters.

    Args:
        count: Number of grams needed (one per cell)

    Returns:
        List of unigram Grams
    """
    grams = []
    for _ in range(count):
        grams.append(Gram(random.choice(string.ascii_uppercase)))
    return grams


def rule_scrabble_distribution(count):
    """
    Pick grams using Scrabble tile distribution weights.

    Args:
        count: Number of grams needed (one per cell)

    Returns:
        List of unigram Grams
    """
    _load_scrabble_distribution()
    letters = random.choices(_scrabble_letters, weights=_scrabble_weights, k=count)
    grams = []
    for letter in letters:
        grams.append(Gram(letter))
    return grams


def rule_scrabble_with_allvowelswild(count):
    """
    Like rule_scrabble_distribution -- same Scrabble tile weights -- but every
    time the draw lands on a vowel (A, E, I, O, U, Y) the cell becomes a wild
    vowel instead of that fixed letter. Consonants are unchanged, so the overall
    letter frequencies are preserved; only the identity of the vowels is hidden
    behind a wild cell that can later stand for a 1-3 vowel run.

    Args:
        count: Number of grams needed (one per cell)

    Returns:
        List of Grams, with vowels replaced by wild-vowel Grams
    """
    _load_scrabble_distribution()
    letters = random.choices(_scrabble_letters, weights=_scrabble_weights, k=count)
    grams = []
    for letter in letters:
        if is_vowel(letter):
            grams.append(Gram("", is_wild=True))
        else:
            grams.append(Gram(letter))
    return grams


def _load_english_words():
    global _english_words
    if _english_words is not None:
        return

    _english_words = []
    dict_path = os.path.join(os.path.dirname(__file__), 'dictionaries', 'spellingDictionary20k-nocompound.txt')
    with open(dict_path, 'r') as f:
        for line in f:
            word = line.strip().upper()
            if word:
                _english_words.append(word)


def rule_englishcorpus_random_unigram(count):
    """
    Pick grams by selecting random single letters from random words.

    Args:
        count: Number of grams needed (one per cell)

    Returns:
        List of unigram Grams
    """
    _load_english_words()
    grams = []
    for _ in range(count):
        word = random.choice(_english_words)
        idx = random.randint(0, len(word) - 1)
        grams.append(Gram(word[idx]))
    return grams


def rule_englishcorpus_random_digram(count):
    """
    Pick grams by selecting random 2-letter chunks from random words.
    Words shorter than 2 characters are skipped.

    Args:
        count: Number of grams needed (one per cell)

    Returns:
        List of digram Grams (each Gram holds 2 letters)
    """
    _load_english_words()
    grams = []
    while len(grams) < count:
        word = random.choice(_english_words)
        if len(word) < 2:
            continue
        idx = random.randint(0, len(word) - 2)
        grams.append(Gram(word[idx:idx + 2]))
    return grams

# Raw gram freq count from "v7" of analysis
# 1 letter grams: 26 entries; ~166k total weight
# 2 letter grams: ~300 entries; ~141k total weight
# 3 letter grams: ~700 entries; ~81k total weight
# 4 letter grams: ~150 entries; ~15k total weight
# (tossed out >5 grams; ~65 entries; ~6k total weight)
# known issues: contains weird grams (clipped morphological chunkks)
# known issues: getting a unigram is less likely than a multigram
def _load_gram_corpus():
    global _corpus_grams, _corpus_weights
    if _corpus_grams is not None:
        return

    _corpus_grams = []
    _corpus_weights = []

    csv_path = os.path.join(os.path.dirname(__file__), 'gram_corpus', 'jpo_allGramsGreaterThan47InFreq.csv')
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            _corpus_grams.append(row['gram'])
            _corpus_weights.append(int(row['freq']))


def rule_gramcorpus_distribution(count):
    """
    Pick grams from the JPO gram corpus, weighted by each gram's frequency.

    The corpus mixes 1-4 letter grams, so cells get a frequency-realistic
    blend of unigrams through quadgrams.

    Args:
        count: Number of grams needed (one per cell)

    Returns:
        List of Grams (each 1-4 letters)
    """
    _load_gram_corpus()
    picks = random.choices(_corpus_grams, weights=_corpus_weights, k=count)
    grams = []
    for text in picks:
        grams.append(Gram(text))
    return grams


def _load_digrams52():
    global _digrams52, _digrams52_weights
    if _digrams52 is not None:
        return

    _digrams52 = []
    _digrams52_weights = []

    csv_path = os.path.join(os.path.dirname(__file__), 'gram_corpus', 'jpo_52digrams.csv')
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            _digrams52.append(row['gram'])
            _digrams52_weights.append(int(row['freq']))


# 1-in-3 odds of a digram, 2-in-3 odds of a unigram. Kept as a fraction so the
# split is easy to retune in one spot if we want a different blend later.
_DIGRAM52_CHANCE = 1.0 / 3.0


def rule_mixed_scrabble_digram52(count):
    """
    Pick grams as a blend of Scrabble unigrams and corpus digrams.

    Each cell rolls independently: a 1-in-3 chance to pull a digram from
    jpo_52digrams.csv, otherwise a 2-in-3 chance to pull a unigram from
    scrabble_letters.csv. Within whichever source is chosen, that file's own
    weights are respected.

    Args:
        count: Number of grams needed (one per cell)

    Returns:
        List of Grams (a mix of unigrams and digrams)
    """
    _load_scrabble_distribution()
    _load_digrams52()
    grams = []
    for _ in range(count):
        if random.random() < _DIGRAM52_CHANCE:
            text = random.choices(_digrams52, weights=_digrams52_weights, k=1)[0]
        else:
            text = random.choices(_scrabble_letters, weights=_scrabble_weights, k=1)[0]
        grams.append(Gram(text))
    return grams


def rule_digram52_distribution(count):
    """
    Pick grams as digrams only, drawn from jpo_52digrams.csv weighted by each
    digram's frequency. Like rule_mixed_scrabble_digram52 but with no Scrabble
    unigrams mixed in: every cell gets a 2-letter gram.

    Args:
        count: Number of grams needed (one per cell)

    Returns:
        List of digram Grams (each 2 letters)
    """
    _load_digrams52()
    picks = random.choices(_digrams52, weights=_digrams52_weights, k=count)
    grams = []
    for text in picks:
        grams.append(Gram(text))
    return grams
