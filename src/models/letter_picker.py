import random
import string


def pick_letters(count):
    """
    Pick letters for a tetrimino block.
    
    Args:
        count: Number of letters needed (typically 4 for standard tetriminos)
    
    Returns:
        List of uppercase letters
    """
    letters = []
    for _ in range(count):
        letters.append(random.choice(string.ascii_uppercase))
    return letters
