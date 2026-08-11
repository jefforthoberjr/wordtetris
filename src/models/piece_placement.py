"""Settling a piece onto a board -- the one place that knows a piece may be ONE
oversized (JUMBO) cell rather than one cell per coordinate.

Ordinary pieces place a cell per coordinate, as they always have. A jumbo-cell
piece (`piece.jumbo_cell` -- currently the triangle grid's JUMBO_HEX cell) places a
single cell that OWNS its whole footprint, via the board's place_jumbo. Keeping
the branch here means the callers that settle pieces -- a jigsaw drop, the
starting formation -- stay one line each and never grow a second code path.
"""


def place_piece_cells(board, piece):
    """Place every cell of `piece` onto `board`. Returns the list of
    (grid_x, grid_y, gram) actually recorded -- one entry per CELL, so a jumbo
    cell yields a single entry at its primary coordinate even though it covers
    several. Callers that need the covered area (occupancy bookkeeping) should ask
    piece.get_cell_positions() instead.

    Returns an EMPTY list when the board REFUSES the placement, which only a jumbo
    can do: place_jumbo is all-or-nothing (every coordinate must be on-board and
    free, since half a jumbo means nothing), while an ordinary cell places
    per-coordinate and simply skips any that is off-board.

    Callers must treat [] as "this piece did not land" and undo whatever they were
    about to record for it. Discarding the refusal instead is what produced the
    jumbo overlap bug: the piece kept its SHAPES, which were already positioned and
    about to be made visible, so a refused jumbo hexagon drew itself on top of the
    neighbor that beat it to the coordinates -- a cell the board had no record of.
    """
    placed = []
    if getattr(piece, "jumbo_cell", False):
        gx, gy, cell, label, gram, overlay = piece.get_cell_data()[0]
        if board.place_jumbo(piece.get_cell_positions(), cell, label, gram, overlay):
            placed.append((gx, gy, gram))
    else:
        for gx, gy, cell, label, gram, overlay in piece.get_cell_data():
            board.place(gx, gy, cell, label, gram, overlay)
            placed.append((gx, gy, gram))
    return placed
