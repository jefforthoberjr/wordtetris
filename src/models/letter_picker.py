import csv
import os
import random
import string


_scrabble_letters = None
_scrabble_weights = None
_english_words = None


def _load_scrabble_distribution():
    global _scrabble_letters, _scrabble_weights
    if _scrabble_letters is not None:
        return
    
    _scrabble_letters = []
    _scrabble_weights = []
    
    csv_path = os.path.join(os.path.dirname(__file__), 'dictionaries', 'scrabble_letters.csv')
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            _scrabble_letters.append(row['letter'])
            _scrabble_weights.append(int(row['count']))


def rule_random_letters(count):
    """
    Pick letters for a tetrimino piece using pure random selection.
    
    Args:
        count: Number of letters needed (typically 4 for standard tetriminos)
    
    Returns:
        List of uppercase letters
    """
    letters = []
    for _ in range(count):
        letters.append(random.choice(string.ascii_uppercase))
    return letters


def rule_scrabble_distribution(count):
    """
    Pick letters using Scrabble tile distribution weights.
    
    Args:
        count: Number of letters needed (typically 4 for standard tetriminos)
    
    Returns:
        List of uppercase letters
    """
    _load_scrabble_distribution()
    return random.choices(_scrabble_letters, weights=_scrabble_weights, k=count)


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
    Pick letters by selecting random single letters from random words.
    
    Args:
        count: Number of letters needed
    
    Returns:
        List of uppercase letters
    """
    _load_english_words()
    letters = []
    for _ in range(count):
        word = random.choice(_english_words)
        idx = random.randint(0, len(word) - 1)
        letters.append(word[idx])
    return letters


def rule_englishcorpus_random_digram(count):
    """
    Pick letters by selecting random 2-letter chunks from random words.
    Words shorter than 2 characters are skipped.
    
    Args:
        count: Number of letters needed (returns count letters, so count/2 digrams rounded up)
    
    Returns:
        List of uppercase letters
    """
    _load_english_words()
    letters = []
    while len(letters) < count:
        word = random.choice(_english_words)
        if len(word) < 2:
            continue
        idx = random.randint(0, len(word) - 2)
        letters.append(word[idx])
        letters.append(word[idx + 1])
    return letters[:count]
