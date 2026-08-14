"""Cell health: obstacle / mission cells that survive more than one word.

CellHealthMixin is mixed into GameScreen, so every method here runs with
GameScreen's `self` and reaches the board, the cell-kind sets and the fossil
helpers directly.

THE MODEL. Each starting obstacle / mission cell may carry HEALTH -- the number
of words that must be spelled through it before it clears. Health lives in
_cell_health (cell -> remaining); a cell absent from that map has no health
tracking at all, which is exactly the pre-health behavior. A cell that reaches 0
is DESTROYED: it leaves the board and stops counting toward the victory rules.

THE ATTACKER TRAIL. A word spelled through a still-alive target is an ATTACKING
WORD, and it does NOT clear in the usual way -- its player cells FOSSILIZE in
place as the target's ATTACKERS (_cell_attackers: target -> the cells attacking
it; _attacker_targets: the reverse). They stay on the board as a visible record
of how many words the target has already absorbed, and -- since a fossil stays
walkable under game_screen.fossil_word_use: rule_fossil_allow -- as material the
next word can chain onto: P+INE fossilizes the P, then S+P+INE can reuse it. Only
when the target falls do its attackers withdraw and leave the board together.

Note the TARGET cell itself never fossilizes while it lives: it keeps its gram
and its obstacle/mission tint, so it can be spelled through again.

The whole feature sits behind game_screen.cell_health; under rule_cell_health_off
_clear_paths runs the original path untouched.
"""

from config import CONFIG, select_rule
import log_codes as L


class CellHealthMixin:
    """Health + attacker bookkeeping for GameScreen (see module docstring)."""

    # --- health-amount rules (game_screen.obstacle_health / .mission_health) ---
    # How much health each starting cell of that track gets. "one" reproduces the
    # original game exactly (the first word through the cell clears it).

    def _rule_obstacle_health_one(self):
        """Every obstacle cell has 1 health: the first word through it clears it,
        as it did before the health feature."""
        return 1

    def _rule_obstacle_health_fixed(self):
        """Every obstacle cell gets the same health, game_screen.obstacle_health_
        amount words."""
        return self._obstacle_health_amount

    def _rule_mission_health_one(self):
        """The mission twin of _rule_obstacle_health_one."""
        return 1

    def _rule_mission_health_fixed(self):
        """The mission twin of _rule_obstacle_health_fixed
        (game_screen.mission_health_amount)."""
        return self._mission_health_amount

    # --- attacker-release rules (game_screen.attacker_release) -----------------
    # An attacking cell can be committed to several targets at once (its word's
    # path crossed two damaged obstacles). These decide when it withdraws.

    def _rule_attacker_release_when_all_dead(self, targets):
        """Withdraw the attacker only once EVERY target it attacks has fallen.
        Keeps the trail on the board as long as any of its obstacles is still
        being chipped at, so the player can keep chaining onto it -- and never has
        to think about which obstacle to kill first."""
        return all(t not in self._cell_health for t in targets)

    def _rule_attacker_release_when_any_dead(self, targets):
        """Withdraw the attacker as soon as ANY of its targets falls. Opens board
        space sooner, at the cost of making clear ORDER a strategic concern."""
        return any(t not in self._cell_health for t in targets)

    # --- attacker-hold rules (game_screen.attacker_cell_clear) ---------------
    # A committed attacker cell stays walkable (game_screen.fossil_word_use:
    # rule_fossil_allow), so a LATER word can be spelled through it. If that later
    # word misses every target it is not an attacking word, so it goes to the
    # normal clear-action -- which, before this rule existed, removed the attacker
    # cells along with its own, silently withdrawing an attack the player had
    # already paid a word for. These decide, per cell, whether the clear-action may
    # take it. Called with a single cell; True means HOLD it back.

    def _rule_attacker_cells_consumable(self, cell):
        """Attacker cells are ordinary cells to a later word: whatever the clear-
        action does to the rest of that word's path, it does to them too (the
        original behavior, kept for restore)."""
        return False

    def _rule_attacker_cells_held(self, cell):
        """A cell committed to a live target is HELD: the clear-action skips it, so
        it stays on the board with its gram and its commitment intact. The rest of
        the word clears normally, and the held cell leaves the usual way -- with the
        target it is attacking, per game_screen.attacker_release. This keeps the
        attacker trail an honest record of the words a target has absorbed."""
        return cell in self._attacker_targets

    # --- word-action rules (game_screen.health_word_action) ------------------
    # What becomes of a word spelled through a target that SURVIVES the hit.

    def _rule_health_word_fossilize(self, fw, alive_targets, targets):
        """The word ATTACKS: its player cells fossilize in place, committed to
        EVERY target the word hit -- including any that fell on this very word, so
        rule_attacker_release_when_any_dead can free the trail at once (under the
        all-dead default a dead link is simply already satisfied). No target cell
        of the word is fossilized itself: a survivor keeps its gram and tint so it
        can be spelled through again, and a dead one is about to leave. Returns
        False -- the word does NOT go on to the normal clear-action."""
        for cell in fw.path:
            if cell in targets:
                continue
            if self._board.gram_at(*cell) is None:
                continue
            self._fossilize_cell(cell)
            self._link_attacker(cell, targets)
        return False

    def _rule_health_word_clear(self, fw, alive_targets, targets):
        """No attacker trail: the word clears normally (the target simply loses a
        point of health and stays). Returns True -- the word goes on to the normal
        clear-action. The alternative to _rule_health_word_fossilize; nothing
        fossilizes, so nothing is held or released."""
        return True

    # --- damage-display rules (game_screen.obstacle_damage_display) ----------
    # How a damaged-but-alive target SHOWS the hits it has taken. Each is called
    # with the cell after every change to its health, and again when it leaves.
    # A target only ever displays partial damage: at full health nothing shows,
    # and at zero it has already left the board.

    def _rule_damage_display_none(self, cell):
        """No damage indicator -- a chipped obstacle looks exactly like a fresh
        one, and the attacker trail beside it is the only cue. The original look;
        also the fallback for a board with no rising-fill overlay."""
        return

    def _rule_damage_border_dashed(self, cell):
        """Break the cell's solid outline into dashes as it takes damage: the
        border is divided into max-health slots and one is painted per hit, in
        board.damage_dash -- set that to the board background and the painted
        stretches read as GAPS breaking the solid outline apart; set it to any
        other color (red, say) and they read as colored dashes painted ON it.
        Either way the cell's FILL is untouched, so the obstacle tint still reads
        cleanly, unlike the rising fill which sits on top of it.

        Caveat on a board where cells share an edge (the square grid): a slot
        painted over a shared edge marks the neighbor's outline too."""
        self._damage_border_gap.set_marked(
            cell, self._cell_damage_taken(cell), self._cell_health_max.get(cell))

    def _rule_damage_border_fill(self, cell):
        """FILL the cell's outline with the damage color a slot at a time: the same
        slot scheme as rule_damage_border_dashed, but painting board.damage_fill
        over the WHOLE slot instead of part of it. The outline stays continuous and
        reddens as it goes, so it reads as a cell heating up rather than cracking
        apart."""
        self._damage_border_mark.set_marked(
            cell, self._cell_damage_taken(cell), self._cell_health_max.get(cell))

    def _rule_damage_fill_rising(self, cell):
        """Fill the cell from the floor up as it takes damage: 1 of 3 hits fills a
        third, 2 fills two thirds. Reads as a progress bar toward the cell's
        destruction with no legend to learn, and stays legible across a boardful of
        targets at a glance. Shares the machinery with the omniswap sand timers
        (views/rising_fill.py), tinted by board.damage_fill instead."""
        self._damage_fill.set_fraction(cell, self._cell_damage_fraction(cell))

    # --- trail cleanup rule (game_screen.word_trail) -------------------------
    # Whether a cleared cell also drops the word line drawn through it. Paired
    # with the trail rule that RECORDS the lines, so both sides move together.

    def _rule_drop_trails_on_release(self, cells):
        """Remove every trail running through `cells` as they leave the board."""
        self._word_trail.remove_paths_touching(cells)

    def _rule_drop_trails_never(self, cells):
        """Trails are off (or accumulate for the whole game): nothing to drop."""
        return

    # --- the health seam (game_screen.cell_health) ---------------------------
    # Interposed by _clear_paths between the accepted words and the clear-action.
    # Each returns (words_for_the_clear_action, cells_that_left_the_board).

    def _rule_cell_health_off(self, accepted):
        """No health tracking: every accepted word goes straight to the clear-
        action, exactly as before the feature. The original path."""
        return accepted, set()

    def _rule_cell_health_on(self, accepted):
        """Damage every target on each accepted word's path, then decide that
        word's fate. Runs in two passes on purpose: ALL damage lands first, so a
        word that kills its only target never ends up attacking a corpse.

        Pass 1 damages each target once per word that used it. Pass 2 gives each
        word to the health-word-action rule if any of its targets SURVIVED,
        otherwise passes it through to the normal clear-action. Finally the fallen
        targets leave the board, withdrawing the attackers committed to them."""
        damaged = []                      # (word, targets it hit) in accept order
        for fw in accepted:
            targets = [c for c in fw.path if c in self._cell_health]
            for cell in targets:
                self._damage_cell(cell, fw.word)
            damaged.append((fw, targets))

        normal = []
        for fw, targets in damaged:
            alive = {c for c in targets if c in self._cell_health}
            if not alive or self._health_word_action_rule(fw, alive, set(targets)):
                normal.append(fw)
        # Every target killed above (by any of these words) now leaves, taking its
        # released attackers with it.
        released = self._release_dead_cells()
        return normal, released

    # --- bare-instance defaults ----------------------------------------------
    # GameScreen.__init__ overwrites all of these (the maps per game, the rules
    # from config). They exist so a bare __new__ instance -- what the tests build
    # -- reads the feature as OFF instead of raising, matching the error-display
    # defaults at the top of GameScreen. Naming a rule method here rather than a
    # lambda keeps it a plain function, so instance access still binds self.
    _cell_health = {}
    _cell_health_max = {}
    _cell_attackers = {}
    _attacker_targets = {}
    _cell_health_tracking = False
    _obstacle_health_amount = 1
    _mission_health_amount = 1
    _cell_health_rule = _rule_cell_health_off
    _health_word_action_rule = _rule_health_word_fossilize
    _attacker_release_rule = _rule_attacker_release_when_all_dead
    _attacker_hold_rule = _rule_attacker_cells_consumable
    _drop_trails_rule = _rule_drop_trails_never
    _damage_display_rule = _rule_damage_display_none
    _damage_fill = None
    _damage_border_gap = None
    _damage_border_mark = None
    _obstacle_health_rule = _rule_obstacle_health_one
    _mission_health_rule = _rule_mission_health_one

    # --- construction ---------------------------------------------------

    def _init_cell_health(self):
        """Wire up the whole cell-health feature: the per-game maps, every rule
        selection, and the damage-display knobs. Called from GameScreen.__init__;
        lives here so the feature's config surface sits with the code that reads
        it (and so __init__ does not grow another 50 lines per feature). The
        per-game overlays it leaves as None are built in _start_new_game, once a
        board exists to take their geometry from."""
        # Obstacle / mission cells that take several words to clear, and the
        # fossilized player cells attacking them meanwhile. All four maps stay
        # empty under rule_cell_health_off; they are (re)built per game by
        # _assign_cell_health.
        self._cell_health = {}          # cell -> health remaining
        self._cell_health_max = {}      # cell -> health it started with
        self._cell_attackers = {}       # target cell -> the cells attacking it
        self._attacker_targets = {}     # attacking cell -> targets it attacks
        # Whether health is tracked at all -- read by _assign_cell_health, which
        # runs per game, so the flag is resolved once here.
        self._cell_health_tracking = (
            CONFIG["rules"]["game_screen.cell_health"] == "rule_cell_health_on")
        self._obstacle_health_amount = CONFIG["rules"]["game_screen.obstacle_health_amount"]
        self._mission_health_amount = CONFIG["rules"]["game_screen.mission_health_amount"]
        self._obstacle_health_rule = select_rule("game_screen.obstacle_health", {
            "rule_obstacle_health_one": self._rule_obstacle_health_one,
            "rule_obstacle_health_fixed": self._rule_obstacle_health_fixed,
        })
        self._mission_health_rule = select_rule("game_screen.mission_health", {
            "rule_mission_health_one": self._rule_mission_health_one,
            "rule_mission_health_fixed": self._rule_mission_health_fixed,
        })
        # The seam _clear_paths runs between the accepted words and the clear-
        # action; the 'off' rule hands the words straight through unchanged.
        self._cell_health_rule = select_rule("game_screen.cell_health", {
            "rule_cell_health_off": self._rule_cell_health_off,
            "rule_cell_health_on": self._rule_cell_health_on,
        })
        self._health_word_action_rule = select_rule("game_screen.health_word_action", {
            "rule_health_word_fossilize": self._rule_health_word_fossilize,
            "rule_health_word_clear": self._rule_health_word_clear,
        })
        # How a damaged-but-alive target shows the hits it has taken. The rising
        # fill needs the per-game RisingFill overlay, built in _start_new_game
        # once the board exists.
        self._damage_display_rule = select_rule("game_screen.obstacle_damage_display", {
            "rule_damage_display_none": self._rule_damage_display_none,
            "rule_damage_fill_rising": self._rule_damage_fill_rising,
            "rule_damage_border_dashed": self._rule_damage_border_dashed,
            "rule_damage_border_fill": self._rule_damage_border_fill,
        })
        self._damage_fill_opacity = round(
            255 * CONFIG["rules"]["game_screen.damage_fill_opacity"])
        self._damage_border_thickness = CONFIG["rules"]["game_screen.damage_border_thickness"]
        # All three overlays are built per game in _start_new_game (they need the
        # board's outlines and the per-game batch); only the active rule's is ever
        # drawn into, so the other two cost nothing but an empty dict.
        self._damage_fill = None
        self._damage_border_gap = None
        self._damage_border_mark = None
        self._attacker_release_rule = select_rule("game_screen.attacker_release", {
            "rule_attacker_release_when_all_dead": self._rule_attacker_release_when_all_dead,
            "rule_attacker_release_when_any_dead": self._rule_attacker_release_when_any_dead,
        })
        # Whether a later, non-attacking word may clear away cells already
        # committed to a live target (the companion to the release rule above: that
        # one says when a held cell LEAVES, this one says who else may take it).
        self._attacker_hold_rule = select_rule("game_screen.attacker_cell_clear", {
            "rule_attacker_cells_consumable": self._rule_attacker_cells_consumable,
            "rule_attacker_cells_held": self._rule_attacker_cells_held,
        })

    # --- health bookkeeping --------------------------------------------------

    def _assign_cell_health(self):
        """Give every starting obstacle / mission cell its health, per the active
        per-track rule. Called once per game, right after the setup formation has
        placed them. Under rule_cell_health_off the map stays empty, so nothing
        downstream tracks health at all."""
        self._cell_health = {}
        self._cell_health_max = {}
        self._cell_attackers = {}
        self._attacker_targets = {}
        if not self._cell_health_tracking:
            return
        for cell in self._obstacle_cells:
            self._cell_health[cell] = self._obstacle_health_rule()
        for cell in self._mission_cells:
            self._cell_health[cell] = self._mission_health_rule()
        # Starting health kept alongside the remaining health, so the damage
        # display can read a 0-1 fraction (see _cell_damage_fraction).
        self._cell_health_max = dict(self._cell_health)
        L.log_06008("obstacle", len(self._obstacle_cells), self._obstacle_health_rule())
        L.log_06008("mission", len(self._mission_cells), self._mission_health_rule())

    def _damage_cell(self, cell, word):
        """Take one point of health off `cell`. At 0 the cell is DESTROYED: it
        drops out of _cell_health (which is what 'dead' means everywhere else
        here) and _release_dead_cells clears it from the board."""
        remaining = self._cell_health[cell] - 1
        if remaining > 0:
            self._cell_health[cell] = remaining
        else:
            del self._cell_health[cell]
        # Repaint the damage indicator for its new health. At 0 the cell is gone
        # from _cell_health, so the display reads "untracked" and clears itself --
        # the cell is about to leave the board anyway.
        self._damage_display_rule(cell)
        L.log_30009(cell, self._cell_kind(cell), remaining, word)

    def _link_attacker(self, fossil, targets):
        """Commit the attacking cell `fossil` to each cell in `targets` -- recorded
        both ways, so a falling target can find its attackers and an attacker can
        ask whether every target it attacks is gone."""
        held = self._attacker_targets.setdefault(fossil, set())
        for target in targets:
            held.add(target)
            self._cell_attackers.setdefault(target, set()).add(fossil)

    def _release_dead_cells(self):
        """Clear every destroyed target from the board, then withdraw the attackers
        whose targets satisfy the release rule. Returns the cells that left the
        board, for the obstacle / mission victory tracking in _clear_paths."""
        dead = [c for c in self._cell_attackers if c not in self._cell_health]
        # A target with no attackers (killed by the very first word through it, or
        # under rule_health_word_clear) never entered _cell_attackers, so collect
        # those from the kind sets too.
        for cell in self._obstacle_cells | self._mission_cells:
            if cell not in self._cell_health and cell not in self._cell_attackers:
                if self._cell_had_health(cell):
                    dead.append(cell)
        left = set()
        for target in dead:
            if self._board.gram_at(*target) is not None:
                self._board.clear_cell(*target)
                left.add(target)
            attackers = self._cell_attackers.pop(target, set())
            freed = self._release_attackers(attackers)
            left |= freed
            L.log_30010(target, self._cell_kind(target), freed)
        # Drop the word lines of everything that just left (gated by
        # game_screen.word_trail; a trail-off game recorded none). An attacking
        # word's line is drawn to its target, so it must not outlive it.
        self._drop_trails_rule(left)
        return left

    def _release_attackers(self, attackers):
        """Withdraw those `attackers` the release rule says are done -- clear the
        cell, un-fossilize it and drop its links. An attacker still committed to a
        live target (rule_attacker_release_when_all_dead) stays where it is."""
        freed = set()
        for fossil in attackers:
            targets = self._attacker_targets.get(fossil, set())
            if not self._attacker_release_rule(targets):
                continue
            self._attacker_targets.pop(fossil, None)
            self._fossilized_cells.discard(fossil)
            if self._board.gram_at(*fossil) is not None:
                self._board.clear_cell(*fossil)
                freed.add(fossil)
        return freed

    def _forget_cell_health(self, cells):
        """Drop `cells` from every health structure -- they left the board by some
        route other than damage (covered by a placement; see
        _rule_old_cells_get_delete). Any attackers committed to them withdraw by
        the normal release rule, since a forgotten cell reads as fallen."""
        for cell in cells:
            self._cell_health.pop(cell, None)
            self._cell_health_max.pop(cell, None)
            self._damage_display_rule(cell)   # untracked now -> drops its indicator
        for cell in cells:
            attackers = self._cell_attackers.pop(cell, set())
            self._release_attackers(attackers)

    # --- accessors -----------------------------------------------------------

    def _cell_kind(self, cell):
        """Which track `cell` started on -- 'obstacle' / 'mission' / 'cell' -- for
        the session log."""
        if cell in self._obstacle_cells:
            return "obstacle"
        if cell in self._mission_cells:
            return "mission"
        return "cell"

    def _cell_had_health(self, cell):
        """True if `cell` was ever given health this game -- i.e. it is a starting
        obstacle / mission cell and tracking is on. Distinguishes 'died just now'
        from 'never tracked' when scanning the kind sets."""
        return self._cell_health_tracking and (
            cell in self._obstacle_cells or cell in self._mission_cells)

    def _cell_health_remaining(self, cell):
        """Remaining health of `cell`, or None if it isn't a tracked cell. The
        damage DISPLAY reads this (see the rising-fill rule)."""
        return self._cell_health.get(cell)

    def _cell_damage_taken(self, cell):
        """How many hits `cell` has absorbed, or 0 if it isn't tracked (or has
        already left). The border displays count in whole hits rather than the
        0-1 fraction the rising fill uses."""
        remaining = self._cell_health.get(cell)
        if remaining is None:
            return 0
        return self._cell_health_max.get(cell, remaining) - remaining

    def _cell_damage_fraction(self, cell):
        """0.0-1.0 share of `cell`'s health already taken, or None if it isn't
        tracked. 1.0 never shows -- a fully damaged cell has already left."""
        remaining = self._cell_health.get(cell)
        if remaining is None:
            return None
        full = self._cell_health_max.get(cell, remaining)
        if full <= 0:
            return None
        return (full - remaining) / full
