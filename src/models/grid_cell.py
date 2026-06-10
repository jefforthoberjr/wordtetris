class GridCell:
    def __init__(self):
        self.square = None
        self.label = None
        # The Gram the cell holds (its letters, or a wild vowel). Kept so the
        # board can report a cell's letters / wild-ness without inspecting the
        # render objects (the label may be a sprite, not text).
        self.gram = None
        self._hidden_by_hover = False

    def is_occupied(self):
        return self.square is not None

    def set_contents(self, square, label, gram=None):
        self.square = square
        self.label = label
        self.gram = gram
        self._hidden_by_hover = False
        if square:
            square.visible = True
        if label:
            label.visible = True

    def clear(self):
        if self.square:
            self.square.visible = False
        if self.label:
            self.label.visible = False
        self.square = None
        self.label = None
        self.gram = None
        self._hidden_by_hover = False

    def hide_for_hover(self):
        if self.is_occupied() and not self._hidden_by_hover:
            self._hidden_by_hover = True
            self.square.visible = False
            self.label.visible = False

    def restore_from_hover(self):
        if self.is_occupied() and self._hidden_by_hover:
            self._hidden_by_hover = False
            self.square.visible = True
            self.label.visible = True
