import random
import string


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
