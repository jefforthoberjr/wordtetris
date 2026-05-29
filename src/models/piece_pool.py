import random
from models.piece import Piece
from models.tetrimino import TetriminoType


class PiecePool:
    def __init__(self, size, cell_size, batch):
        self._pieces = []
        self._current_index = 0
        self._size = size
        self._cell_size = cell_size
        self._batch = batch
        
        self._rule_fixed_size()
    
    def _rule_fixed_size(self):
        """Populate pool with a fixed number of pieces."""
        #tetrimino_types = self._rule_create_pure_random()
        tetrimino_types = self._rule_create_random_even_distribution()
        
        for t_type in tetrimino_types:
            piece = Piece(t_type, self._cell_size, self._batch, visible=False)
            self._pieces.append(piece)
    
    def _rule_create_pure_random(self):
        """Generate a list of tetrimino types using pure random selection."""
        all_types = list(TetriminoType)
        return [random.choice(all_types) for _ in range(self._size)]
    
    def _rule_create_random_even_distribution(self):
        """Generate a list of tetrimino types with even distribution, shuffled."""
        all_types = list(TetriminoType)
        num_types = len(all_types)
        
        base_count = self._size // num_types
        remainder = self._size % num_types
        
        types_list = []
        for t_type in all_types:
            types_list.extend([t_type] * base_count)
        
        extras = random.sample(all_types, remainder)
        types_list.extend(extras)
        
        random.shuffle(types_list)
        return types_list
    
    @property
    def size(self):
        return self._size
    
    @property
    def current_index(self):
        return self._current_index
    
    def current_piece(self):
        """Returns the current active piece."""
        return self._pieces[self._current_index]
    
    def has_next(self):
        """Returns True if there are more pieces available after the current one."""
        return self._current_index < self._size - 1
    
    def advance(self):
        """Move to the next piece in the pool. Returns the new current piece, or None if exhausted."""
        self._current_index += 1
        if self._current_index < self._size:
            return self._pieces[self._current_index]
        return None
