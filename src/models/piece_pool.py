from models.square_piece import SquarePiece, PLAYER_PIECE_TYPES
from config import select_rule
# Pool ordering draws route through the swappable Source seam (see source.py) so
# a replay reproduces the same piece queue.
from source import rand
import log_codes as L


class PiecePool:
    def __init__(self, size, cell_size, batch, piece_class=SquarePiece, piece_types=None, gram_pick_rule=None, cell_color=None, kind="player"):
        self._pieces = []
        self._current_index = 0
        self._size = size
        self._cell_size = cell_size
        self._batch = batch
        # Injected so the same pool serves square or hex pieces (set by the
        # geometry rule in GameScreen). Defaults keep the square behavior.
        self._piece_class = piece_class
        if piece_types is None:
            piece_types = PLAYER_PIECE_TYPES
        self._piece_types = piece_types
        # Injected so an obstacle pool can pick grams by a different rule than
        # the main pool. None lets each piece fall back to its configured default.
        self._gram_pick_rule = gram_pick_rule
        # Injected so an obstacle pool can tint its cells differently from the
        # main pool. None lets each piece fall back to its default (white).
        self._cell_color = cell_color
        # Which pool this is (player / obstacle / mission), for the session log.
        self._kind = kind

        self._rule_fixed_size()

    def _rule_fixed_size(self):
        """Populate pool with a fixed number of pieces. The ordering rule is
        chosen by the YAML key piece_pool.order."""
        order_rules = {
            "rule_create_pure_random": self._rule_create_pure_random,
            "rule_create_fixed_roundrobin": self._rule_create_fixed_roundrobin,
            "rule_create_shuffled_roundrobin": self._rule_create_shuffled_roundrobin,
            "rule_create_random_even_distribution": self._rule_create_random_even_distribution,
        }
        piece_types = select_rule("piece_pool.order", order_rules)()
        # Record the resolved deal order so a replay/analysis sees the queue.
        L.log_06001(self._kind, piece_types)

        for p_type in piece_types:
            piece = self._piece_class(
                p_type, self._cell_size, self._batch, visible=False,
                gram_pick_rule=self._gram_pick_rule, cell_color=self._cell_color
            )
            self._pieces.append(piece)
    
    def _rule_create_pure_random(self):
        """Generate a list of piece types using pure random selection."""
        all_types = list(self._piece_types)
        return [rand().choice(all_types) for _ in range(self._size)]
    
    def _rule_create_random_even_distribution(self):
        """Generate a list of piece types with even distribution, shuffled."""
        all_types = list(self._piece_types)
        num_types = len(all_types)
        
        base_count = self._size // num_types
        remainder = self._size % num_types
        
        types_list = []
        for p_type in all_types:
            types_list.extend([p_type] * base_count)
        
        extras = rand().sample(all_types, remainder)
        types_list.extend(extras)

        rand().shuffle(types_list)
        return types_list
    
    def _rule_create_fixed_roundrobin(self):
        """Generate a list of piece types by cycling through enum order."""
        all_types = list(self._piece_types)
        types_list = []
        for i in range(self._size):
            types_list.append(all_types[i % len(all_types)])
        return types_list
    
    def _rule_create_shuffled_roundrobin(self):
        """Generate batches of all piece types, each batch shuffled."""
        all_types = list(self._piece_types)
        types_list = []
        
        while len(types_list) < self._size:
            batch = all_types.copy()
            rand().shuffle(batch)
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
