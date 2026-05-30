import csv
import os
import random
import string


_scrabble_letters = None
_scrabble_weights = None


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
