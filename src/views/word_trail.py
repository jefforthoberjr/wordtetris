import pyglet
from views.shaders import get_shape_shader
from config import CONFIG, get_color


class WordTrail:
    """Overlay of polylines -- one per cleared word -- each connecting the pixel
    centers of the cells the word used, center to center, in word order.

    Trails accumulate for the whole game (game_screen.word_trail = option C) and
    are dropped only on a new game via clear(). Drawn after the board batches so
    they sit on top of the cells and glyphs. Toggle + style come from config:
    game_screen.word_trail (on/off), word_trail_thickness, word_trail_opacity,
    and the colors.yaml board.word_trail color."""

    # Defaults, read at IMPORT -- so these hold the BASE config.yaml values and a
    # game mode's overrides never reach them. __init__ re-reads both knobs from
    # the live CONFIG (a WordTrail is built per game, after apply_game_mode), so
    # the instance values are the ones actually drawn with. See the same pattern
    # in GameScreen._read_config_knobs.
    COLOR = get_color("board.word_trail")
    THICKNESS = CONFIG["rules"]["game_screen.word_trail_thickness"]
    # Config stores opacity as a 0-1 fraction (0.5 = 50%); pyglet wants 0-255.
    OPACITY = round(255 * CONFIG["rules"]["game_screen.word_trail_opacity"])

    def __init__(self):
        self.THICKNESS = CONFIG["rules"]["game_screen.word_trail_thickness"]
        self.OPACITY = round(255 * CONFIG["rules"]["game_screen.word_trail_opacity"])
        self._batch = pyglet.graphics.Batch()
        # Kept so the Line objects aren't garbage-collected while batched.
        self._segments = []
        # One entry per recorded trail: [the board cells it runs through, its Line
        # segments, seconds of fade left (or None for no fade), the fade time it
        # started with]. A trail added without cells gets
        # an empty set, so it is listed but never matches remove_paths_touching --
        # the pre-fade behavior for untagged trails. See update().
        self._paths = []

    def add_path(self, points, cells=None, fade_seconds=None):
        """Add a trail along `points` (a list of (px, py) cell centers in word
        order): one Line segment between each consecutive pair. A 0/1-point path
        adds nothing.

        `cells` is the board cells the word ran through. Passing them makes the
        trail REMOVABLE by cell (remove_paths_touching) -- which is how a cell-
        health attacker trail disappears when its target falls. Omitting them
        keeps the original behavior: the trail stays for the whole game.

        `fade_seconds` (when set) makes the trail self-expire: update() fades its
        opacity to zero over that many seconds and then deletes it. None keeps the
        trail up until the game ends or its cells leave."""
        shader = get_shape_shader()
        segments = []
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            line = pyglet.shapes.Line(
                x1, y1, x2, y2,
                thickness=self.THICKNESS, color=self.COLOR,
                batch=self._batch, program=shader,
            )
            line.opacity = self.OPACITY
            self._segments.append(line)
            segments.append(line)
        if segments:
            self._paths.append([set(cells) if cells else set(), segments,
                                fade_seconds, fade_seconds])

    def update(self, dt):
        """Advance every fading trail by `dt`: dim its lines in proportion to the
        fade time left, and delete the trail once it reaches zero. Trails with no
        fade time (fade_seconds None) are skipped, so a game with the fade rule off
        pays only this walk of the list."""
        kept = []
        for entry in self._paths:
            segments, remaining, total = entry[1], entry[2], entry[3]
            if remaining is None:
                kept.append(entry)
                continue
            remaining = remaining - dt
            if remaining <= 0:
                self._delete_segments(segments)
            else:
                # Opacity tracks the fraction of the fade still to run, so the line
                # leaves at a steady rate from its configured opacity down to zero.
                fraction = remaining / total
                for line in segments:
                    line.opacity = round(self.OPACITY * fraction)
                entry[2] = remaining
                kept.append(entry)
        self._paths = kept

    def _delete_segments(self, segments):
        """Drop these Line objects from the batch and the keep-alive list."""
        for line in segments:
            line.delete()
            self._segments.remove(line)

    def remove_paths_touching(self, cells):
        """Delete every tagged trail running through any cell in `cells`. Called
        when those cells leave the board, so a word's line goes with the word
        rather than outliving it. Untagged trails are never touched."""
        gone = set(cells)
        kept = []
        for entry in self._paths:
            path_cells, segments = entry[0], entry[1]
            if path_cells & gone:
                self._delete_segments(segments)
            else:
                kept.append(entry)
        self._paths = kept

    def clear(self):
        """Drop every trail (a new game). A fresh batch releases the old segments
        for GC, matching the per-game batch idiom used for the board."""
        self._segments = []
        self._paths = []
        self._batch = pyglet.graphics.Batch()

    def draw(self):
        self._batch.draw()
