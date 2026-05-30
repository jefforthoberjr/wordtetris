import random
from models.piece import Piece
from models.tetrimino import TetriminoType
from models.domino import DominoType

# Configuration: which piece types to use
PIECE_TYPES = TetriminoType
# PIECE_TYPES = DominoType


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
        # tetrimino_types = self._rule_create_pure_random()
        # tetrimino_types = self._rule_create_fixed_roundrobin()
        tetrimino_types = self._rule_create_shuffled_roundrobin()
        # tetrimino_types = self._rule_create_random_even_distribution()
        
        for t_type in tetrimino_types:
            piece = Piece(t_type, self._cell_size, self._batch, visible=False)
            self._pieces.append(piece)
    
    def _rule_create_pure_random(self):
        """Generate a list of piece types using pure random selection."""
        all_types = list(PIECE_TYPES)
        return [random.choice(all_types) for _ in range(self._size)]
    
    def _rule_create_random_even_distribution(self):
        """Generate a list of piece types with even distribution, shuffled."""
        all_types = list(PIECE_TYPES)
        num_types = len(all_types)
        
        base_count = self._size // num_types
        remainder = self._size % num_types
        
        types_list = []
        for p_type in all_types:
            types_list.extend([p_type] * base_count)
        
        extras = random.sample(all_types, remainder)
        types_list.extend(extras)
        
        random.shuffle(types_list)
        return types_list
    
    def _rule_create_fixed_roundrobin(self):
        """Generate a list of piece types by cycling through enum order."""
        all_types = list(PIECE_TYPES)
        types_list = []
        for i in range(self._size):
            types_list.append(all_types[i % len(all_types)])
        return types_list
    
    def _rule_create_shuffled_roundrobin(self):
        """Generate batches of all piece types, each batch shuffled."""
        all_types = list(PIECE_TYPES)
        types_list = []
        
        while len(types_list) < self._size:
            batch = all_types.copy()
            random.shuffle(batch)
            types_list.extend(batch)
        
        return types_list[:self._size]
    
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
