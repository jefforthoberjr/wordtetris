"""Right pane shown during the MOVING phase of MOVING_LINE_BLAST
(game_screen.mode = rule_mode_line_blast).

Unlike the plain MovingSidePane (a word-hunt field + cleared-word list), this pane
shows the player's PIECE OPTIONS: up to `slots` half-size previews of the pieces
that can be placed next, drawn straight from the mode's piece pool. Clicking a
preview selects it (the mode then floats a full-size copy on the board); the
selected preview dims to half alpha to show which one is in hand. The running
score sits below the previews and a manual "End game" button at the very bottom
(MOVING_LINE_BLAST has no victory rule, so the player ends the game by hand).

It implements the same call surface GameScreen uses on the moving pane (reset,
set_score_label, hunt_text, ...) so the engine talks to it exactly as it does the
other moving panes; the word-hunt / cleared-word methods are inert no-ops here
(this pane shows neither). The SELECTING phase still uses the normal
SelectingSidePane, built by the engine as for any two-phase mode."""

import math
import pyglet
from views.shaders import get_shape_shader
from models.square_piece import ALL_PIECE_ROTATIONS
from config import get_color, get_string


class LineBlastMovingPane:
    DIVIDER_COLOR = get_color("moving_side_pane.divider")
    SCORE_LABEL_COLOR = get_color("moving_side_pane.score_label")
    BUTTON_COLOR = get_color("moving_side_pane.button_text")
    PHASE_LABEL_COLOR = get_color("moving_side_pane.phase_label")
    CELL_FILL_COLOR = get_color("board.settled_cell_fill")
    CELL_BORDER_COLOR = get_color("board.cell_border")
    CELL_TEXT_COLOR = get_color("board.cell_text")
    # Alpha a selected slot's preview dims to (the "in hand" cue) -- half, matching
    # the floating piece's own half alpha on the board.
    SELECTED_OPACITY = 128

    def __init__(self, x, y, width, height, on_end, preview_cell, slots):
        # on_end(): the manual End-game control (MOVING_LINE_BLAST has no victory
        # rule, so the player ends the game by hand). preview_cell: pixel size of one
        # cell in a half-size preview. slots: how many preview boxes to lay out.
        self._x = x
        self._y = y
        self._width = width
        self._height = height
        self._on_end = on_end
        self._preview_cell = preview_cell
        self._slot_count = max(1, int(slots))
        self._batch = pyglet.graphics.Batch()
        # Per-slot preview render objects, rebuilt on each set_slots; parallel to the
        # slot boxes below (a slot with no piece keeps an empty list).
        self._slot_shapes = [[] for _ in range(self._slot_count)]

        margin = max(6, width // 12)
        base = max(12, int(width * 0.09))
        line_h = base * 1.6

        self._divider = pyglet.shapes.Line(
            x, y, x, y + height, thickness=1, color=self.DIVIDER_COLOR,
            batch=self._batch, program=get_shape_shader())

        top = y + height - margin
        self._title = pyglet.text.Label(
            get_string("line_blast_pieces"), font_size=base * 0.7,
            x=x + margin, y=top, anchor_x="left", anchor_y="top",
            color=self.PHASE_LABEL_COLOR, batch=self._batch)

        # Slot boxes stack down the pane between the title and the score/End controls
        # pinned to the bottom. Each box is a fixed-height band; its preview is
        # centered inside it (see _render_slots).
        end_y = y + margin
        self._end_btn = pyglet.text.Label(
            get_string("end_game"), font_size=base, x=x + margin, y=end_y,
            anchor_x="left", anchor_y="bottom",
            color=self.BUTTON_COLOR, batch=self._batch)
        score_y = end_y + line_h
        self._score = pyglet.text.Label(
            "", font_size=base * 0.7, x=x + margin, y=score_y,
            anchor_x="left", anchor_y="bottom",
            color=self.SCORE_LABEL_COLOR, batch=self._batch)

        slots_top = top - line_h
        slots_bottom = score_y + line_h
        band = max(self._preview_cell, (slots_top - slots_bottom) / self._slot_count)
        # (left, bottom, right, top) of each slot band, top slot first.
        self._slot_boxes = []
        for i in range(self._slot_count):
            box_top = slots_top - i * band
            self._slot_boxes.append((x, box_top - band, x + width, box_top))

    @property
    def x(self):
        return self._x

    @property
    def width(self):
        return self._width

    # --- piece-option previews --------------------------------------------
    def set_slots(self, specs, selected):
        """Rebuild the piece previews from `specs` (a list of (piece_type, letters)
        or None per slot; None = empty slot, e.g. a drained pool). `selected` is the
        index of the in-hand slot (dimmed) or None."""
        for shapes in self._slot_shapes:
            for obj in shapes:
                obj.delete()
        self._slot_shapes = [[] for _ in range(self._slot_count)]
        for i in range(self._slot_count):
            spec = specs[i] if i < len(specs) else None
            if spec is None:
                continue
            self._slot_shapes[i] = self._render_slot(
                self._slot_boxes[i], spec, dim=(i == selected))

    def _render_slot(self, box, spec, dim):
        """Draw one piece preview centered in its slot box, at half cell size.
        Returns the render objects (so set_slots can delete them next time)."""
        piece_type, letters = spec
        offsets = ALL_PIECE_ROTATIONS[piece_type][0]
        min_dx = min(dx for dx, _ in offsets)
        min_dy = min(dy for _, dy in offsets)
        span_x = max(dx for dx, _ in offsets) - min_dx + 1
        span_y = max(dy for _, dy in offsets) - min_dy + 1
        left, bottom, right, top = box
        cx = (left + right) / 2
        cy = (bottom + top) / 2
        cell = self._preview_cell
        origin_x = cx - span_x * cell / 2
        origin_y = cy - span_y * cell / 2
        opacity = self.SELECTED_OPACITY if dim else 255
        shapes = []
        for (dx, dy), letter in zip(offsets, letters):
            px = origin_x + (dx - min_dx) * cell
            py = origin_y + (dy - min_dy) * cell
            rect = pyglet.shapes.BorderedRectangle(
                px, py, cell, cell, border=2, color=self.CELL_FILL_COLOR,
                border_color=self.CELL_BORDER_COLOR, batch=self._batch,
                program=get_shape_shader())
            rect.opacity = opacity
            shapes.append(rect)
            label = pyglet.text.Label(
                letter, font_size=int(cell * 0.55), weight="bold",
                x=px + cell / 2, y=py + cell / 2, anchor_x="center",
                anchor_y="center", color=self.CELL_TEXT_COLOR, batch=self._batch)
            label.opacity = opacity
            shapes.append(label)
        return shapes

    def slot_at(self, x, y):
        """The slot index whose box contains pixel (x, y) AND holds a piece, or
        None. The mode maps a click here to selecting that piece."""
        for i, (left, bottom, right, top) in enumerate(self._slot_boxes):
            if left <= x <= right and bottom <= y <= top and self._slot_shapes[i]:
                return i
        return None

    def hit_end(self, x, y):
        """Whether (x, y) is on the End-game button."""
        return self._hit(self._end_btn, x, y)

    def _hit(self, label, x, y):
        left = label.x
        right = label.x + label.content_width
        # End/score labels are bottom-anchored; box runs UP from (x, y).
        bottom = label.y
        top = label.y + label.content_height
        return left <= x <= right and bottom <= y <= top

    # --- score -------------------------------------------------------------
    def set_score_label(self, points):
        self._score.text = get_string("score_count", count=points)

    def reset(self):
        """New game: drop every preview (the mode repopulates on start)."""
        self.set_slots([], None)

    def draw(self):
        self._batch.draw()

    # --- inert MovingSidePane surface --------------------------------------
    # This pane shows neither a word-hunt field nor a cleared-word list, so the
    # methods the engine calls for those on the moving pane are no-ops here. Kept so
    # GameScreen can treat every moving pane uniformly (see the call sites in
    # game_screen / the selection + boardrules mixins).
    def set_phase_label(self, count):
        pass

    def set_time_label(self, seconds):
        pass

    def set_finished_label(self):
        pass

    def set_word_count(self, count):
        pass

    def add_cleared_words(self, words, new_flags=None, obscure_flags=None, scores=None):
        pass

    def word_at(self, x, y):
        return None

    def hit_select(self, x, y):
        return False

    def hunt_text(self):
        return ""

    def clear_hunt(self):
        pass

    def clear_word(self):
        pass

    def is_empty(self):
        return True

    def on_text(self, text):
        pass

    def on_key_press(self, symbol, modifiers):
        return False
