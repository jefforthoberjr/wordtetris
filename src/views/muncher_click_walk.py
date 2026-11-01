"""Click-to-walk for the Word Muncher (game_screen.muncher_click), as a mixin on
MuncherMovingMode.

Left-click a cell: he walks there along a shortest route, one cell at a time, and
bites it on arrival. The bite is the same MuncherMovingMode._eat the eat key runs,
so scoring, replenish, the dead-end cap and the belly all behave as they do from
the keyboard.

CLICKS QUEUE. A second click during a walk waits its turn rather than redirecting
him, so clicking C, A, T quickly eats all three, in that order. Three things keep
the queue from fighting the rest of the mode:

  * SUBMIT WAITS for the queue to finish. Otherwise ENTER right after the last
    click would submit half the word and cost a life.
  * THE KEYBOARD TAKES OVER. An arrow or the eat key cancels whatever is left.
  * A FORCED CLEAR cancels it too, since the word those bites were for is gone.

REPLAY. Steps here fire from update(), not from an input event, so a replay could
drift off the recorded frame timing. Each one goes through Source.timing_gate, and
a replay fires it at the recorded time -- see replay.ReplaySource.
"""

from collections import deque

from config import select_rule
from source import rand
import log_codes as L


class MuncherClickWalkMixin:
    # Class-level defaults so a mode built without _init_click_walk (the bare
    # __new__ test instances) reads as "no walk in progress".
    _click_targets = ()
    _click_submit_queued = False

    def _init_click_walk(self):
        self._click_rule = select_rule(
            "game_screen.muncher_click",
            {"rule_muncher_click_off": self._rule_muncher_click_off,
             "rule_muncher_click_walk_and_eat": self._rule_muncher_click_walk_and_eat})
        self._click_walk_reset()

    def on_mouse_press(self, x, y, button):
        gs = self._gs
        if button == gs._buttons["move_primary"] and not self._frozen():
            self._click_rule(gs._board.cell_at(x, y))

    # --- click rules (game_screen.muncher_click) ---------------------------
    def _rule_muncher_click_off(self, cell):
        """Board clicks do nothing: keyboard only. The original behavior."""
        pass

    def _rule_muncher_click_walk_and_eat(self, cell):
        """Queue `cell` to be walked to and bitten. Ignores a miss, a reserved cell,
        and a repeat of the cell already last in the queue -- a double-click must
        not take a second bite out of whatever grows back there. Also ignored once
        a submit is waiting, because that word is already spoken for."""
        board = self._gs._board
        targets = self._click_targets
        repeat = len(targets) > 0 and targets[-1] == cell
        if (cell is not None and board.is_valid(*cell)
                and not repeat and not self._click_submit_queued):
            L.log_20010("click", self._pos, cell)
            self._click_targets = [*targets, cell]

    # --- walking the queue --------------------------------------------------
    def _click_walk_tick(self):
        """One frame's worth of walking, from MuncherMovingMode.update: take the
        next step or bite once the current step has landed, or fire a waiting
        submit once the queue has run dry."""
        if self._click_targets:
            if (not self._frozen()
                    and rand().timing_gate("muncher_click_walk",
                                           not self._sprite.stepping())):
                self._click_walk_advance()
        elif self._click_submit_queued:
            self._click_submit_queued = False
            self.submit()

    def _click_walk_advance(self):
        """Do one action toward the front target. The target leaves the queue BEFORE
        the bite, because the bite can force a clear that cancels the queue."""
        goal = self._click_targets[0]
        if self._pos == goal:
            self._click_targets = self._click_targets[1:]
            L.log_20010("click_bite", self._pos, goal)
            self._eat()
        else:
            hop = self._click_next_hop(self._pos, goal)
            if hop is None:
                self._click_targets = self._click_targets[1:]
                L.log_20010("click_unreachable", self._pos, goal)
            else:
                # Not _walk_to: its step lockout is answered per key press in a
                # replay, and this step's timing was already settled by the gate.
                L.log_20010("click_step", self._pos, hop)
                self._pos = hop
                self._sprite.step_to(*self._center(hop))

    def _click_next_hop(self, start, goal):
        """The neighbor of `start` on a shortest route to `goal`, or None if there
        is no route. Searches outward FROM the goal, so each cell's parent is its
        next step toward it. Empty cells are walkable, as they are from the keys."""
        board = self._gs._board
        parents = {goal: None}
        frontier = deque([goal])
        while frontier and start not in parents:
            cell = frontier.popleft()
            for neighbor in board.neighbors(*cell):
                if neighbor not in parents:
                    parents[neighbor] = cell
                    frontier.append(neighbor)
        return parents.get(start)

    # --- what interrupts the queue ------------------------------------------
    def _click_walk_defer_submit(self):
        """True when a walk is still running, so the submit must wait for it."""
        deferred = len(self._click_targets) > 0
        if deferred:
            self._click_submit_queued = True
            L.log_20010("click_submit_queued", self._pos, self._pos)
        return deferred

    def _click_walk_cancel(self):
        """Drop the queue and any waiting submit. He finishes the step he is on."""
        if self._click_targets or self._click_submit_queued:
            L.log_20010("click_cancel", self._pos, self._pos)
        self._click_walk_reset()

    def _click_walk_reset(self):
        self._click_targets = []
        self._click_submit_queued = False
