import math
import random
from pathlib import Path
import pyglet
from config import CONFIG, get_color, get_string
from controls import control_keys
from controllers.screen_manager import ScreenType
from models.player_dictionary import PlayerDictionary
from views.gram_preview import GramPreview


# Repo root, for resolving the config-relative mock dictionary path below.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class DictionaryScreen:
    """The "My Dictionary" screen: a read-only, paged view of every word the
    player has collected. Reached from the main menu only; Escape returns there.

    Words are bucketed into 26 A-Z pages (a letter with more words than fit on a
    page splits into numbered sub-pages). A fixed strip of 26 letter tabs at the
    bottom shows the current letter highlighted; Chunk D wires up jumping by
    typing a letter, clicking a tab, or stepping with the arrow keys."""

    LETTERS = "abcdefghijklmnopqrstuvwxyz"

    def __init__(self, window, screen_manager):
        self._window = window
        self._screen_manager = screen_manager
        self._batch = pyglet.graphics.Batch()
        # Tab squares draw in their own batch first, so the letter glyphs (in the
        # main batch) always land on top of them.
        self._tab_batch = pyglet.graphics.Batch()

        # The snapshot of words being viewed. Filled on_enter so it always
        # reflects the latest saved file, then held static while the player pages
        # around (the file won't change while this screen is up).
        self._words = []
        # Page model, (re)built on_enter: a flat list of {"letter", "words"}
        # pages, the page index where each letter starts, and the current page.
        self._pages = []
        self._letter_first_page = {}
        self._page_index = 0

        title_color = get_color("dictionary.title_text")
        # Total-words readout pinned near the top, sized relative to the window
        # so it scales with the (possibly Retina) framebuffer, not raw pixels.
        self._count_label = pyglet.text.Label(
            "",
            font_size=math.floor(window.height / 28),
            x=math.floor(window.width / 2),
            y=window.height - math.floor(window.height / 12),
            anchor_x="center",
            anchor_y="center",
            color=title_color,
            batch=self._batch,
        )

        # --- 3-column word grid -------------------------------------------
        # All geometry is derived from the window size (no raw pixel constants),
        # so it scales with the framebuffer. The grid fills the band between the
        # count readout up top and a strip reserved at the bottom for the A-Z
        # letter tabs that arrive in Chunk C.
        self._cols = 3
        margin_x = math.floor(window.width / 20)
        grid_top = window.height - math.floor(window.height / 6)
        tab_area = math.floor(window.height / 8)        # reserved for Chunk C
        grid_bottom = tab_area + math.floor(window.height / 40)
        usable_height = grid_top - grid_bottom

        font_size = math.floor(window.height / 30)
        self._row_height = math.floor(font_size * 1.5)
        self._rows = max(1, math.floor(usable_height / self._row_height))
        self._capacity = self._rows * self._cols     # words shown per page
        col_width = math.floor((window.width - 2 * margin_x) / self._cols)

        # One pre-allocated Label per cell, kept blank until a page is rendered.
        # Stored in COLUMN-MAJOR order: cell index i lives at column floor(i/rows),
        # row (i - column*rows). That way rendering a slice is a straight
        # cells[i].text = words[i] with no index juggling, and the words read
        # top-to-bottom down each column like a printed dictionary. One Label per
        # word (rather than one multiline block) leaves room for future per-word
        # features (hover, click, recoloring).
        word_color = get_color("dictionary.word_text")
        self._cells = []
        for i in range(self._capacity):
            col = math.floor(i / self._rows)
            row = i - col * self._rows
            cell = pyglet.text.Label(
                "",
                font_size=font_size,
                x=margin_x + col * col_width,
                y=grid_top - row * self._row_height,
                anchor_x="left",
                anchor_y="top",
                color=word_color,
                batch=self._batch,
            )
            self._cells.append(cell)

        self._font_size = font_size

        # Hover preview: a single re-render of the hovered word's gram grouping,
        # drawn over that word's cell (the text Label underneath is untouched).
        # Cells are a touch larger than the word font so the boxes read clearly,
        # but still smaller than the in-game grid. _hover_index tracks which grid
        # cell is previewed so a fresh variation is only picked when the hovered
        # word changes, not on every mouse-motion event.
        preview_cell = math.floor(font_size * 1.1)
        self._preview = GramPreview(preview_cell, self._row_height)
        self._hover_index = None
        # Words currently laid out in the grid, in cell order (set per page).
        self._visible_words = []
        # The PlayerDictionary backing the current view, kept so a hover can look
        # up the word's gram variations (set in on_enter alongside _words).
        self._dict = None

        # --- A-Z tab strip ------------------------------------------------
        # 26 fixed square tabs along the bottom, one per letter. Sizes come from
        # the window width so all 26 always fit. The current letter's tab is
        # recolored to match the page background (so it reads as "open"); the
        # rest stay white. Tab fills are recolored in place on every page change.
        tab_inactive = get_color("dictionary.tab_fill")
        tab_border = get_color("dictionary.tab_border")
        tab_text = get_color("dictionary.tab_text")
        strip_margin = math.floor(window.width / 20)
        strip_width = window.width - 2 * strip_margin
        slot = math.floor(strip_width / len(self.LETTERS))
        tab_size = math.floor(slot * 0.85)
        tab_inset = math.floor((slot - tab_size) / 2)
        tab_y = math.floor(window.height / 30)
        border_thickness = max(1, math.floor(tab_size / 18))

        self._tab_shapes = []
        # Hold the letter glyphs too: a Label only kept in a local would be
        # garbage-collected, taking its vertex list (and the visible glyph)
        # with it -- the squares survive only because they're in _tab_shapes.
        self._tab_labels = []
        for i, letter in enumerate(self.LETTERS):
            tab_x = strip_margin + i * slot + tab_inset
            shape = pyglet.shapes.BorderedRectangle(
                tab_x, tab_y, tab_size, tab_size,
                border=border_thickness,
                color=tab_inactive,
                border_color=tab_border,
                batch=self._tab_batch,
            )
            self._tab_shapes.append(shape)
            letter_label = pyglet.text.Label(
                letter.upper(),
                font_size=math.floor(tab_size * 0.5),
                x=tab_x + math.floor(tab_size / 2),
                y=tab_y + math.floor(tab_size / 2),
                anchor_x="center",
                anchor_y="center",
                color=tab_text,
                batch=self._batch,
            )
            self._tab_labels.append(letter_label)

    # --- paging rules (swap point) ---------------------------------------
    # The page-grouping strategy is the one configurable knob here. Today it is
    # the A-Z letter scheme; a numeric pager (fixed N words per page) could swap
    # in by pointing _build_pages at a different rule, with no other changes.
    def _build_pages(self, words):
        return self._rule_build_pages_by_letter(words)

    def _rule_build_pages_by_letter(self, words):
        """Group alphabetically-sorted `words` into one bucket per A-Z letter,
        then split each bucket into sub-pages of at most `capacity` words. Every
        letter gets at least one page -- an empty letter becomes a single blank
        page -- so the 26 tabs and the arrow keys always have somewhere to land.
        Returns (pages, letter_first_page) where pages is a flat ordered list of
        {"letter", "words"} dicts and letter_first_page maps a letter to the
        index of its first page."""
        buckets = {}
        for letter in self.LETTERS:
            buckets[letter] = []
        for word in words:
            first = word[0:1].lower()
            if first in buckets:
                buckets[first].append(word)

        pages = []
        letter_first_page = {}
        for letter in self.LETTERS:
            bucket = buckets[letter]
            letter_first_page[letter] = len(pages)
            if len(bucket) == 0:
                pages.append({"letter": letter, "words": []})
            else:
                start = 0
                while start < len(bucket):
                    pages.append({
                        "letter": letter,
                        "words": bucket[start:start + self._capacity],
                    })
                    start = start + self._capacity
        return pages, letter_first_page

    def _render_page(self, index):
        """Show the page at `index`: lay out its words and light up its letter
        tab. An empty letter's page renders as a fully blank grid."""
        self._page_index = index
        page = self._pages[index]
        self._render_words(page["words"])
        self._update_tab_highlight(page["letter"])
        # The cells now hold different words, so any active preview is stale.
        self._preview.hide()
        self._hover_index = None

    def _update_tab_highlight(self, current_letter):
        active = get_color("dictionary.tab_active")
        inactive = get_color("dictionary.tab_fill")
        for i, letter in enumerate(self.LETTERS):
            if letter == current_letter:
                self._tab_shapes[i].color = active
            else:
                self._tab_shapes[i].color = inactive

    def _render_words(self, page_words):
        """Fill the cell grid from `page_words` (already sliced to at most
        capacity, in alphabetical order). Cells beyond the supplied words are
        blanked so a short page leaves no stale leftovers. Column-major: because
        cells are stored column-major, the i-th word drops straight into the
        i-th cell."""
        # Held so a hover can map a grid cell index back to its word (and look up
        # that word's gram variations for the preview).
        self._visible_words = page_words
        for i, cell in enumerate(self._cells):
            if i < len(page_words):
                cell.text = page_words[i]
            else:
                cell.text = ""

    def _word_source_path(self):
        # TEMP (playtest): config.yaml dictionary.use_mock_data swaps in the
        # large mock file so paging can be exercised before the player has
        # thousands of words. Returns None to fall back to the real
        # player_dictionary.txt default.
        dict_config = CONFIG.get("dictionary", {})
        source = None
        if dict_config.get("use_mock_data", False):
            source = _REPO_ROOT / dict_config.get("mock_data_path")
        return source

    def on_enter(self):
        # Reload every time so the screen shows words cleared since the last
        # visit; sorted alphabetically by PlayerDictionary.words(). The config
        # toggle can redirect this to the large mock file for paging playtests.
        source = self._word_source_path()
        if source is not None and source.exists():
            self._dict = PlayerDictionary(source)
        else:
            self._dict = PlayerDictionary()
        self._words = self._dict.words()
        # Any preview from a prior visit is stale now the words reloaded.
        self._preview.hide()
        self._hover_index = None
        self._count_label.text = get_string("words_collected", count=len(self._words))
        # Build the A-Z page model and open on the first page (letter "a").
        self._pages, self._letter_first_page = self._build_pages(self._words)
        self._render_page(0)

    def on_exit(self):
        pass

    def draw(self):
        # Same trick game_screen uses: temporarily set the GL clear color to this
        # screen's light-yellow background, clear, then restore the default window
        # background so the menu/title screens still clear to their own color.
        bg = get_color("dictionary.background")
        win_bg = get_color("window.background")
        pyglet.gl.glClearColor(bg[0] / 255, bg[1] / 255, bg[2] / 255, 1)
        self._window.clear()
        pyglet.gl.glClearColor(win_bg[0] / 255, win_bg[1] / 255, win_bg[2] / 255, 1)

        # Tab squares first, then everything else (word grid, count, tab letters).
        self._tab_batch.draw()
        self._batch.draw()
        # The hovered-word preview sits on top of the word grid, occluding the
        # word's text Label with its re-rendered cells.
        self._preview.draw()

    def update(self, dt):
        pass

    def _go_to_page(self, index):
        """Show page `index`, clamped to the valid range. Because pages are a
        flat A-Z list (each letter's sub-pages in order), stepping by +/-1 walks
        sub-pages within a letter and then crosses into the adjacent letter --
        landing on (and stopping at) empty letters' blank pages along the way.
        Clamping means the first/last pages don't wrap around."""
        clamped = index
        if clamped < 0:
            clamped = 0
        last = len(self._pages) - 1
        if clamped > last:
            clamped = last
        self._render_page(clamped)

    def _jump_to_letter(self, letter):
        """Jump straight to a letter's FIRST page (e.g. typing 'S' or clicking
        the S tab lands on S 1-of-N, never a middle sub-page). Non-letters are
        ignored."""
        if letter in self._letter_first_page:
            self._go_to_page(self._letter_first_page[letter])

    def on_key_press(self, symbol, modifiers):
        handled = False
        if symbol in control_keys("dictionary.back"):
            self._screen_manager.switch_to(ScreenType.MAIN_MENU)
            handled = True
        elif symbol in control_keys("dictionary.page_prev"):
            self._go_to_page(self._page_index - 1)
            handled = True
        elif symbol in control_keys("dictionary.page_next"):
            self._go_to_page(self._page_index + 1)
            handled = True
        return handled

    def on_text(self, text):
        # Typing a letter A-Z jumps to that letter's first page; everything else
        # (digits, space, etc.) is ignored by _jump_to_letter.
        self._jump_to_letter(text.lower())

    def on_mouse_press(self, x, y, button, modifiers):
        # Clicking a letter tab jumps to that letter's first page. Tab geometry
        # is read straight off the shapes; mouse coords share the window units
        # the tabs were laid out in (same convention as the menu screens).
        hit = None
        for i, shape in enumerate(self._tab_shapes):
            if (shape.x <= x <= shape.x + shape.width and
                    shape.y <= y <= shape.y + shape.height):
                hit = i
        if hit is not None:
            self._jump_to_letter(self.LETTERS[hit])

    def on_mouse_motion(self, x, y, dx, dy):
        # Which laid-out word, if any, is under the cursor. Each word Label is
        # anchored top-left at (cell.x, cell.y); its glyphs run right by
        # content_width and down from the top, so a row_height-tall box from the
        # top makes the word comfortable to hover.
        hit = None
        for i in range(len(self._visible_words)):
            cell = self._cells[i]
            left = cell.x
            right = cell.x + cell.content_width
            top = cell.y
            bottom = cell.y - self._row_height
            if left <= x <= right and bottom <= y <= top:
                hit = i
        if hit is None:
            self._preview.hide()
            self._hover_index = None
        elif hit != self._hover_index:
            # Only (re)build when the hovered word changes, so the random variation
            # pick stays put while the cursor moves within one word.
            self._show_preview_for(hit)

    def _show_preview_for(self, index):
        """Preview the word in grid cell `index`: pick one of its gram groupings
        at random and render it over the word. A word with no stored grouping
        (e.g. legacy data) just clears any existing preview."""
        self._hover_index = index
        word = self._visible_words[index]
        variations = self._dict.variations(word)
        if not variations:
            self._preview.hide()
        else:
            variation = random.choice(variations)
            cell = self._cells[index]
            center_y = cell.y - math.floor(self._font_size / 2)
            self._preview.show(variation, cell.x, center_y, cell.content_width)
