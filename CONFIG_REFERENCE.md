# CONFIG REFERENCE

Detailed explanations for every knob in `src/assets/config.yaml`. The config file
itself is kept scannable (flat keys + the commented-out toggle alternatives, with
only a terse one-line label each); the full prose lives here.

**Headings match the config keys verbatim**, so to look up a knob just search this
file for its dotted name (e.g. `game_screen.mode`). When you add or change a rule,
put the short label in `config.yaml` and the explanation here under a matching
heading — do NOT grow multi-paragraph comments back into the config file.

Sibling reference files: `colors.yaml` (styling), `strings.yaml` (UI text),
`loading_animation.yaml` (the LOADING fade timeline), `controls.yaml` (input
bindings).

---

## Game modes (`assets/game_modes/`)

Instead of hand-editing `config.yaml` between plays, each playable configuration
lives in its own file under `src/assets/game_modes/*.yaml`, surfaced in-game by the
**Start Game → Select Mode** submenu. `config.yaml` remains the **shared base**; a
mode file is a *partial* config that is deep-merged on top of a freshly-loaded base
when the mode is picked (`config.apply_game_mode`), replacing the live `CONFIG`
dict's contents in place so every module sees the swap without a restart.

A mode file:
- Starts with `mode_label: "..."` — the menu display name (stripped before merge;
  not a game knob). Modes are listed sorted by label.
- Lists **only the keys that define the mode** (typically the `rules:` block: the
  MOVING-phase `game_screen.mode` and its preset flips). Everything it omits —
  window size, scoring, dictionary, gram picks, `spell_check`, the affix lists —
  comes from the base file, so those are tuned once. The seeded starters list the
  full mode-signature key set so each stays self-contained even if base is retuned.

Deep-merge rule: nested dicts merge key-by-key; scalars and **lists replace
wholesale** (a mode's `suffix_tails:` overrides the base list entirely, not appends).

Switching modes rebuilds the game screen from scratch (GameScreen snapshots most
rule-derived state at construction) and always starts a fresh game. Window-level
settings (`window.*`, `game.ups`) are locked in at process start and are **not**
re-applied per mode — keep those in the base file only.

Each session records its mode: `sessions/<id>.meta` carries a `# game_mode :` header
and embeds the **effective merged** config (so `replay.py` reloads the exact rule
set), and the mode slug is folded into the session filename
(`<timestamp>_<slug>_<seed>`) so a mode's sessions group together. Seeded starters:
`constellation.yaml`, `typewriter.yaml`, `omniswap.yaml` (see the *PRESET* sections
below for what each flips).

---

## Top-level blocks

### assets.colors / assets.loading_animation
Which styling / animation file to load, named by bare filename under its assets/
subdir (`assets/colors/`, `assets/loading_animation/`). Both live in the `rules:`
block so a game mode can swap the whole file through the same deep-merged override
that carries every other knob — the base `config.yaml` names the default, a mode
override names its own.
- `assets.colors` — the colors table `get_color` resolves against (channels 0–255).
  Default `default_colors.yaml`. NOTE: many color constants are resolved at import
  time (class-level), before any mode is applied, so a mode that overrides
  `assets.colors` only affects colors resolved after the swap — the split is wired,
  but a fully per-mode palette needs those constants made instance-resolved.
- `assets.loading_animation` — the opening-reveal fade timeline `get_loading_anim`
  resolves against. Default `default_loading_animation.yaml`. Read per game at
  construction (after the mode is applied), so it fully tracks the selected file —
  e.g. `constellation_emptyit.yaml` selects a copy with every delay + duration
  halved, so its reveal plays 2× as fast.

Both globals reload when a game mode is applied (`config.apply_game_mode`), and the
session log embeds the mode-selected file so replays stay faithful. `controls.yaml`
is deliberately NOT split — still one file.

### window / game / audio
- `window.width` / `window.height` — logical window size. On a Retina display
  `window.width` reports the physical framebuffer size (see TECH.md → PYGLET STYLE).
- `game.ups` — updates per second.
- `game.language` — UI language: a top-level key in `assets/strings.yaml` (e.g.
  `en`, `es`). Missing keys fall back to English.
- `audio.master_volume` — 0.0–1.0.

### logging.enabled
Session logging: capture a full play session to `sessions/<id>.log` for later
analysis and replay (see `src/session_log.py`, `src/log_codes.py`). Toggle off for
quick playtests where you don't want a file written.

### window.vsync
Vertical sync. `true` (pyglet's default) locks the buffer-swap to the monitor
refresh to avoid screen tearing — but on macOS that swap (`context.flip()`) BLOCKS
the main thread until the next refresh (~16 ms/frame), and pyglet only pumps the
Cocoa event queue between frames, so input goes unserviced during the block. That
is the prime suspect for the "click twice" drops (see `ONGOING_BUGS.md`): a fast
trackpad tap landing in the flip-block blind spot is missed, and the same gap makes
the red-X close button laggy. `false` makes `flip()` return immediately; pyglet's
default event loop still paces redraws off the clock at `game.ups` (no busy-spin)
and spends the inter-frame wait in an OS event-wait that wakes on input — so clicks
are serviced promptly. Trade-off: possible screen tearing (unlikely to matter for a
mostly-static word board). Applied in `main.py` via `window.set_vsync(...)`; the
value is captured in each session's `.meta` snapshot, so you can A/B it and see
which setting a given log ran under.

### window.osx_alt_loop
Forces pyglet to use its `CocoaAlternateEventLoop` on macOS. This is the actual fix
for the "click twice" / dropped-click / laggy red-X bug on Apple Silicon (see
`ONGOING_BUGS.md`, round 6). pyglet ships two macOS event loops: the standard
`EventLoop`, which pumps input with `nextEventMatchingMask_untilDate_inMode_dequeue_`
(one event per `step()`), and `CocoaAlternateEventLoop`, which drives pyglet off the
built-in `NSApp.run()` loop via a timer. pyglet's OWN source comment on the standard
pump reads: *"very broken with ctypes calls. Events eventually stop working properly
after X returns"* — i.e. after a while it silently stops delivering clicks, exactly
our symptom. pyglet auto-selects the good loop only when
`platform.machine() == 'arm64' and "M1" in get_chip_model()` (`pyglet/app/__init__.py`),
so an M2/M3/M4 chip (whose string lacks "M1") falls through to the broken loop. This
machine reports `Apple M3`, so it was silently getting the broken loop. `true`
(default) sets `pyglet.options.osx_alt_loop = True` in `main.py` BEFORE `pyglet.app`
is imported (the loop class is locked in at that import), sidestepping the buggy pump
on every Apple chip; `false` restores pyglet's stock per-chip auto-selection. Harmless
off macOS (the option is only read in pyglet's darwin branch). Captured in each
session's `.meta` snapshot for A/B.

### logging.perf_metrics
Writes a performance snapshot (`log_00015`) into the session log on every ~2s
heartbeat while a session is open: update and draw time (min/avg/max ms), fps, ups,
idle %, process RAM, and VRAM (n/a on integrated GPUs). Sourced from
`src/debug_panel.py`'s timing taps via `perf_snapshot()`, so it records whether or
not the debug panel is toggled visible. Purpose (see `ONGOING_BUGS.md`): the "click
twice" drops are the OS discarding mouse-downs when the app services its Cocoa
event port too slowly — if `update_max`/`draw_max` climb over a long session, that
is the smoking gun, and a spike should line up with a gap in the `[00014]` window
mouse-downs. Same cadence as the heartbeat so volume is trivial (~180 lines / 6-min
game). Turn off to keep the log lean once the perf question is settled.

### logging.first_mouse_probe
macOS-only diagnostic for the "have to click twice" bug (see `ONGOING_BUGS.md`).
Cocoa asks a view `acceptsFirstMouse:` ONLY when a mouseDown lands on a window
that isn't the active window; the default answer (NO) makes that first click get
swallowed to activate the window, so it never reaches the app as a click and is
invisible in the log. When on, `src/macos_first_mouse_probe.py` adds that selector
to pyglet's Cocoa view, still answering NO (**behavior-preserving** — identical to
the current default, changes nothing), and logs each call as a `log_00013`
first-mouse probe. Each line is one otherwise-invisible swallowed click; correlate
its timestamps with the player's "click twice" moments and the `log_00010` focus
timeline. No-op off macOS. Flipping the probe's answer to YES would be the actual
fix, held back until the logs confirm the swallow.

### scoring
Points the player earns for each cleared word, summed into a running total shown
near the timer in the right pane (see `models/scoring.py`). Every weight is an
INDEPENDENT tunable — this is a playtest surface, so tune freely; set
`enabled: false` to switch scoring off entirely. A typical word should land
~10–100 points with the defaults (a 3-letter unigram word ~20, a 5-letter
digram+trigram word ~33, an 8-letter new word over an obstacle ~75).

| key | meaning |
| --- | --- |
| `word_base` | flat points for completing any word |
| `per_cell` | points per board cell the word used |
| `per_letter` | points per letter in the word (rewards LONGER words) |
| `per_extra_gram_letter` | points per letter beyond the first in a cell (rewards using LONGER grams) |
| `obstacle_cell_bonus` | per starting-OBSTACLE cell the word cleared |
| `mission_cell_bonus` | per starting-MISSION cell the word cleared |
| `sand_timer_cell_bonus` | per SAND-TIMER cell the word used (the double-points cells) |
| `fossil_reuse_bonus` | per already-FOSSILIZED cell the word reused (only the fossilize modes have these; requires `fossil_word_use` allow) |
| `new_word_bonus` | word is NEW to the player's lifetime dictionary |
| `fill_board_bonus` | whole board filled ONCE (what "filled" means is mode-dependent; see `game_screen.fill_board`) |
| `time_remaining_per_second` | per whole second left on the clock at game end |

#### scoring.word_score_display
How each cleared word's points read in the word list (right of the word) — the
running total at the top is unaffected either way, and the number(s) are always
the same points, just formatted differently:
- `sum` — one figure, the word's whole score (`+33`). The original behavior.
- `breakdown` — the score split into its three DISPLAY groups, listed
  `+A +B +C`: **(1)** the basic cell sum (`word_base` + `per_cell` +
  `per_letter` + `per_extra_gram_letter`), **(2)** the cell-type bonuses
  (`obstacle` + `mission` + `sand_timer` + `fossil_reuse`), **(3)**
  `new_word_bonus`. Groups worth 0 are DROPPED, so an ordinary word shows just
  its base (`+13`) and the extra values appear only on words that earned them
  (`+13 +15 +10`). The three groups always sum to the `sum`-mode figure.
  The score column is widened to fit the list, so on bonus-heavy rows it can
  crowd the word text — a playtest trade-off.

### dictionary.word_source
Validation word list — the "is this a valid word?" corpus the word-clearing rule
checks against (`models/word_dictionary.py`). Swap between the curated headword
list and the inflection-expanded list:
- `headwords_20k` — the 21.9k curated headwords, no inflections or compounds
  (`spellingDictionary20k-nocompound.txt`). READ is valid, READING is not.
- `expanded` — headwords + every inflected & British form + re-admitted closed
  compounds (~60k; `expandedAllowedWords.txt`). READ and READING both valid.
  Regenerate with `dictionaries/build_expanded_dictionary.py` (see TECH.md).

### dictionary.include_obscure
Obscure tier: also accept the ~16k exclusively-rare 2of12-sourced words
(`expandedAllowedWords_obscure.txt`, built disjoint from `word_source` by
`dictionaries/build_obscure_dictionary.py`). When on, `is_word` accepts both
tiers; a word matched ONLY via this tier is "obscure" — it earns the +2 hint
surcharge (`spell_check.obscurity_extra_score`) and shows orange in the
collected-words pane the first time the player clears it.

### dictionary.use_mock_data / mock_data_path
TEMP (playtest): page the large mock word list so the A–Z tabs and sub-pages can be
exercised before the player has collected thousands of words. Set `use_mock_data`
to false to read the player's real `player_dictionary.txt`.

### dictionary.show_word_scores
My Dictionary screen: when true, each word shows its score (`+N`) beside it. The
score is COMPOSITION-only — the "basic cell sum" (`word_base` + `per_cell` +
`per_letter` + `per_extra_gram_letter`); the board bonuses (obstacle / mission /
sand / fossil) and the new-word bonus are ignored, since a collected word carries
no board context. A word cleared several ways keeps its BEST-scoring grouping.
The same per-word scores are summed into the "Total Score" readout at the top of
the screen — that total is always shown; this toggle only controls the per-word
figures. Off hides the per-word scores (the total stays). Uses
`Scorer.composition_points_rule`; a word stored without any gram grouping (legacy
data) scores 0.

### dictionary.show_word_scores_on_hover
Same per-word composition score as `dictionary.show_word_scores`, but shown ONLY
while a word is hovered — the same moment its cell render (gram grouping) pops up
over the word. Independent of `show_word_scores`: either or both may be on (with
both on, the always-listed score simply stays put through the hover). The score
sits in its own right-justified Label clear of the hover preview, so it reads
alongside the revealed cells. The "Total Score" readout at the top is unaffected
(always shown).

---

## rules

`game_screen.grid` is a bundle: the chosen grid builder wires up its own movement +
clear rules.

### gram.font_size
How gram text is auto-sized. All length grams are beholden to auto-sizing.
- `rule_gram_font_scale_by_length` — scale by gram length.
- `rule_gram_font_fixed` — fixed size.
- `rule_gram_font_scale_single_as_double` — single letters take the 2-letter size;
  longer grams still autosize.

### board.cell_text_color
Recolors each cell's gram GLYPHS to hint its potential point value. The per-gram
value reuses the `scoring:` weights (`per_letter` + `per_extra_gram_letter`), so
the hint tracks the knobs that actually award points; the constant `per_cell` /
`word_base` terms are excluded (they'd shift every cell equally). Colors come from
`board.cell_text_low_value` (low) and `board.cell_text_high_value` (high) in
colors.yaml. Applies to every gram label (settled cells and the live piece).
Cell-KIND bonuses
(obstacle / mission / sand / fossil) aren't reflected — this first idea grades by
the gram alone. See `models/gram_text_color.py`.
- `rule_cell_text_plain` — no hint: every gram uses the flat `board.cell_text`
  color (the original behavior).
- `rule_cell_text_score_gradient` — grade the glyph color from
  `board.cell_text_low_value` (a unigram) toward `board.cell_text_high_value`
  (a full quadgram) by potential points
  — black → dark gold by default, so longer / higher-scoring grams read richer.
  Collapses to the plain color when scoring is off or the weights make length
  irrelevant.

### gram.dedup
Duplicate grams: one toggle for EVERY gram picker (player / obstacle / mission,
square + hex; the initial formation and the piece queue).
- `rule_no_duplicate_multigrams` — avoid repeating any 2+-letter gram across a game
  (single letters and wild vowels are never deduped); falls back to allowing
  repeats if the picker's corpus runs out of fresh multigrams.
- `rule_allow_duplicate_grams` — no dedup.

### gram.unigram_dedup
Duplicate single letters: a SEPARATE toggle from `gram.dedup` (which governs
multi-letter grams). Applies to the OPENING FORMATION only — the piece pool is
exempt, since 100+ pieces can't fit under a 3-each cap of 26 letters. Both run on
top of the `gram.dedup` multigram rule.
- `rule_max_3_duplicate_unigrams` — caps any one letter at 3 copies across the
  opening formation.
- `rule_nolimit_duplicate_unigrams` — single letters repeat freely (original).

### gram.double_consonant_digram / gram.only_vowel_digram
Skippable digrams: two MORE toggles for EVERY gram picker, alongside the dedup
rules. The skip rules re-roll digrams the player likely can't spell with. Unigrams,
trigram+, and wild vowels always pass. Best-effort: falls back to allowing a skipped
digram if the picker can't produce a fresh one in budget.
- `rule_skip_double_consonant_digrams` — skip a DOUBLED consonant (GG, MM, LL, SS);
  an unequal pair (RN, CK) and a doubled vowel (EE — that's the next rule) still
  pass. (`rule_allow_double_consonant_digrams` to disable.)
- `rule_skip_only_vowel_digrams` — skip an ALL-VOWEL digram (EE, EA, IO …), Y
  counted as a vowel (AY, YY also skipped).
- `rule_skip_only_vowel_digrams_no_y` — same, but Y is NOT a vowel (AY, YE, YY pass).
- `rule_allow_only_vowel_digrams` — disable.

### game_screen.grid
`rule_use_hex_grid`, `rule_use_square_grid`, or `rule_use_triangle_grid`.

The triangle board tiles equilateral triangles, rows alternating point-up and
point-down (the orientation of a cell is the parity of `col + row`, so it is one
checkerboard across the whole board; cell (0,0) points up). Its side length is the
square grid's cell size, so it fits about twice the columns and 1.15x the rows in
the same area — cells are smaller, which is why triangle modes default to unigrams.
A triangle has only three edges, so a cell has only three neighbors: left, right,
and the one across its horizontal edge (below it when it points up, above when it
points down). That third step is the movement "flip" (see the movement rules in
`game_screen.py`) and the reason a piece walks up the board by alternating a flip
with a sideways step. Cleared words are recorded in the player dictionary with `^`
as the gram separator (`|` square, `/` hex).

### game_screen.grid_width / game_screen.piece_pool_size
`grid_width` is the number of columns (the grid area is a square, so cell size
derives from it). `piece_pool_size` is how many player pieces the pool pre-builds
for a game.

### game_screen.mode
MOVING-phase mode bundle: which moving-phase strategy runs. The mode owns how the
moving phase presents its active element and turns one input into one committed
action; the shared SELECT pipeline, word-finding, board and dictionary are
mode-agnostic.
- `rule_mode_jigsaw` — MOVING_JIGSAWPUZZLE: one live piece at a time, free movement,
  place anywhere (the original mode).
- `rule_mode_typewriter` — MOVING_TYPEWRITER: a single-cell cursor sweeps the
  pre-filled board; each turn swaps/replaces/passes the cursor cell (WIP).
- `rule_mode_omniswap_vs_timer` — MOVING_OMNISWAP: a pre-filled board, no cursor
  sweep or piece queue; the player freely swaps any two cells against a countdown,
  then SELECT (timer-zero or spacebar). See the OMNISWAP PRESET.
- `rule_mode_constellation` — MOVING_CONSTELLATION: a pre-filled board the player
  never rearranges (no piece/cursor/timer/swap). The trivial MOVING phase is just
  the doorway into SELECT (ENTER); there the player types word after word. A word
  is accepted when its letters can be assembled from grams sitting ANYWHERE on the
  board — each cell used once, whole grams only, no adjacency, no nucleation. The
  used cells clear or fossilize and a word_trail "constellation" is drawn through
  them. See the CONSTELLATION PRESET.
- `rule_mode_shooting_gallery` — MOVING_SHOOTING_GALLERY: a fairground shooter over
  an otherwise-empty board. Grams appear in fading batches (`shooting_batch_*`); the
  player aims a crosshair and left-clicks ("shoots") a cell to append its gram to a
  running buffer and blow that cell away (a fast `shooting_shot_fade_seconds` fade).
  Detection is greedy — the instant the buffer spells a dictionary word it auto-
  submits for points and clears; a non-word buffer left idle for
  `shooting_word_timeout_seconds` errors and clears. No typing, no board
  rearrangement, one continuous real-time phase against `game_screen.game_timer`.
  See the SHOOTING GALLERY PRESET.
- `rule_mode_line_blast` — MOVING_LINE_BLAST: pieces are preselected into a finite
  pool and offered a few at a time as half-size previews in the right pane. The
  player clicks a preview to take it in hand; a copy then FLOATS on the empty board
  following the mouse (snapped to the grid, half alpha, tinted green where a drop is
  legal and red where it would overlap or hang off), and left/right arrows rotate it.
  A board click drops it only on a fully-on-board, ZERO-OVERLAP spot; placing
  repopulates that pane slot from the pool. The instant a placement fills a whole row
  or column, those cells highlight and SELECT opens over exactly them: the player
  types as many words as the highlighted cells can spell (adjacency-pathable per
  `square_grid.word_pathfinding`, cells reusable across words), scoring each. On Next
  piece the ENTIRE highlighted set clears (tetris line-clear, used in a word or not)
  and play returns to MOVING. No victory rule — the moving pane's End-game button is
  the only end (auto-detecting an unplaceable hand is deferred). See the LINE BLAST
  PRESET.

### game_screen.line_blast_pool_size / line_blast_slots / line_blast_preview_scale
Line blast only (ignored by every other mode). `line_blast_pool_size` is how many
pieces the finite preselected pool holds (each a random player piece type with its
cells' unigrams drawn through `square_player.gram_pick`); when it drains, fewer than
`line_blast_slots` previews are offered and no more appear (no auto-end for now).
`line_blast_slots` is how many piece previews sit in the right pane at once (a placed
slot repopulates from the pool). `line_blast_preview_scale` is the preview cell size
as a fraction of a board cell (0.5 = half size). The floating piece is drawn at full
board-cell size; only the pane previews are shrunk. Paired colors live in the colors
file: `board.line_blast_highlight` (the completed row/column), and
`board.line_blast_floating_valid` / `board.line_blast_floating_invalid` (the
green/red floating-piece tint).

### game_screen.shooting_batch_size
Shooting gallery only: how many cells make up one fade batch. The `ShootingField`
picks this many empty board cells at random, gives each a fresh gram from the player
picker, and fades them all in together over `shooting_fade_in_seconds`; each then
fades out over `shooting_fade_out_seconds` (or `shooting_shot_fade_seconds` if shot).
Once the whole batch has cleared, that batch waits `shooting_batch_delay_seconds`
before spawning again. Ignored by every other mode.

### game_screen.shooting_batch_count
Shooting gallery only: how many batches run at the same time, each on its own clock.
`1` is the original single-batch churn (spawn → clear → delay → respawn). With more,
each batch cycles independently, and their first spawns are staggered evenly across
one full cycle (fade-in + hold + fade-out + delay) so they fade on alternating
schedules — e.g. `batch_count: 5` with `batch_size: 10` ripples five waves of ten
cells across the board rather than flashing all fifty at once. Batches never collide:
each only ever draws from currently-empty board cells, so the live total is capped by
the board size (extra demand simply spawns fewer cells).

### game_screen.shooting_batch_delay_seconds
Shooting gallery only: the pause, in seconds, between one batch fully clearing (every
cell faded away) and that same batch spawning again. `0` respawns immediately. With
several batches this is per-batch, so the board never goes fully empty between waves.

### game_screen.shooting_fade_in_seconds
Shooting gallery only: seconds a fresh batch cell takes to bloom from transparent to
its resting color when it spawns. A cell is shootable throughout its whole life,
including mid fade-in. `0` pops it in instantly.

### game_screen.shooting_hold_seconds
Shooting gallery only: seconds a cell stays pinned fully shown (opaque) after it
finishes fading in, before the fade-out begins — the steady window that's easiest to
aim at. `0` starts the fade-out the instant the bloom completes (the original
in→out behavior). The cell is shootable during the hold like any other phase.

### game_screen.shooting_fade_out_seconds
Shooting gallery only: seconds an un-shot cell takes to fade away once its visible
hold ends. This is the slow, ambient churn; a cell that fades fully away without
being shot contributes nothing to the buffer.

### game_screen.shooting_shot_fade_seconds
Shooting gallery only: seconds a SHOT cell takes to fade away — the quick "hit"
reaction, much faster than the ambient `shooting_fade_out_seconds`. The gram is
appended to the buffer at the moment of the shot, so the cell's fast fade is purely
visual (a shot gram still counts even after it has vanished).

### game_screen.shooting_word_timeout_seconds
Shooting gallery only: seconds of no shot after which a buffer that is NOT yet a
dictionary word is declared a miss — an error blip shows and the buffer clears, so a
dead-end run of letters doesn't linger. Reset by every shot. Because detection is
greedy (a valid word auto-submits the instant it forms), the timeout only ever fires
on a genuine non-word prefix.

### game_screen.shooting_crosshair_scale
Shooting gallery only: the crosshair's half-size as a fraction of one cell radius, so
`1.0` makes a crosshair about a cell wide. Purely cosmetic.

### game_screen.shooting_crosshair_gap
Shooting gallery only: the blank gap at the crosshair's center as a fraction of its
half-size (`0` = solid cross through the middle, `1` = the arms vanish). Purely
cosmetic.

### game_screen.misspell_instadeath
Shooting gallery only: a sudden-death spelling rule. After each shot the running
buffer is checked against the dictionary's prefix set; if it has become an *impossible
word* — no active dictionary word begins with it, so no further shot could ever
complete a word — the game ends immediately (the FINISHED end panel, plus any
`end_video`), a spelling forfeit. Because the complete-word test runs first, a buffer
that IS a word auto-submits and never triggers this; and because a short-but-valid
prefix (e.g. `AT` on the way to `ATE`) is still a prefix, only genuine dead ends fire
it. This overrides any other end mechanic: if `game_timer` is running, the instadeath
still ends the game now (entering VICTORY stops the clock rather than waiting it out).
- `rule_misspell_instadeath_off` — a dead-end buffer instead lingers until
  `shooting_word_timeout_seconds` clears it as an ordinary miss (the default).
- `rule_misspell_instadeath_on` — a dead-end buffer ends the game at once.
Ignored by every other mode (only the shooting buffer produces impossible-word runs).

### game_screen.constellation_max_paths
Constellation only: the maximum number of distinct cell-assemblies the on-submit
matcher returns for one typed word. A scattered board can spell a word many ways;
this caps how many the disambiguation chooser cycles (the auto-pick rule still keeps
the fewest-cell one, which the longest-gram-first search surfaces early, so a low
cap is safe). Ignored by every other mode.

### game_screen.constellation_turnover
Constellation only: after a submitted word clears, what happens to the cells it
vacated.
- `rule_constellation_no_replenish` — vacated cells stay empty, so the board shrinks
  toward the whole-board-cleared endgame (pair with `rule_remove_cells` +
  `rule_victory_grid_empty`). With `rule_fossilize_cells` the cells aren't empty
  anyway, so this is the natural choice there too (board freezes toward
  `rule_victory_grid_fossilized`).
- `rule_constellation_replenish` — each now-empty vacated cell refills with a fresh
  gram from the configured player picker, so the board never empties (an endless
  constellation; no grid-empty win). Only refills cells the clear-action actually
  emptied, so it's a no-op under `rule_fossilize_cells`.

### game_screen.replenish_fade_seconds
Any mode that replenishes vacated cells (constellation's
`rule_constellation_replenish` turnover, plant's `rule_clear_plant` refresh): how
many seconds a just-replenished cell takes to fade in from transparent to its
resting color, instead of popping in at full opacity the instant the vacated cell
refills. The fade reuses the opening reveal's handles (glyph alpha-ramp; hex inner
white-fade / square alpha-fade) and easing (`loading_animation.yaml` `easing`), but
on its own lightweight one-shot timeline per cell (see `TimedFade`), independent of
the LOADING reveal. `0` restores the instant pop. Paused while the in-game menu is
open, like the mode timer. A purely visual knob — the refill itself (the placed
gram, logging, scoring) is unchanged, so replay reproduces the same board.
(Formerly `game_screen.constellation_replenish_fade_seconds`, renamed once plant
mode began sharing the same replenish machinery.)

### game_screen.replenish_delay_seconds
Any mode that replenishes vacated cells (see `replenish_fade_seconds`): how many
seconds a vacated cell stays visibly empty before its fresh gram is picked and
placed on the board. Unlike `replenish_fade_seconds` (which controls the fade-in
*after* the gram exists), this delays the placement itself — the cell holds no
gram, and none can be typed from it, until the wait elapses. Pending waits are
counted down each play tick in `_update_pending_replenishes` and paused while the
in-game menu is open, like the mode timer; once a wait fires the gram is placed and
then fades in per `replenish_fade_seconds`. `0` fills instantly (the original
behavior). Note this defers when the new gram becomes usable, so under constellation
it slightly lengthens the window in which `constellation_auto_end` sees a smaller
board. (Formerly `game_screen.constellation_replenish_delay_seconds`.)

### game_screen.constellation_auto_end
Constellation only: after each word clears, whether the game finishes on its own
once the remaining grams can no longer spell ANY dictionary word (the existence
check reuses `starting_coverage.any_word_formable`, honoring the active
`game_screen.word_length` rule; each occupied, non-wild, non-fossil-wall cell is
one usable gram). Ends as FINISHED, the same end-state as the manual End game
button, running the final score tally. Pairs naturally with
`rule_constellation_no_replenish` (a shrinking board eventually runs dry); under
`rule_constellation_replenish` fresh grams keep arriving so it rarely, if ever,
fires.
- `rule_constellation_auto_end_off` — never auto-end (the default); the player
  finishes by hand (the End game button) or a configured victory rule fires.
- `rule_constellation_auto_end_on` — auto-finish the moment no word is formable.
  Note this cuts against the no-word-availability-hints principle: an auto-finish
  tells the player the board is exhausted. Opt in deliberately.

### game_screen.omniswap_auto_end
Omniswap only: after each word fossilizes, whether the game finishes on its own
once the remaining **swappable** grams can no longer spell ANY submittable
dictionary word (the existence check reuses `starting_coverage.any_word_formable`,
honoring the active `game_screen.word_length` rule). The omniswap twin of
`game_screen.constellation_auto_end`, with one deliberate difference: the usable
pool is the freely-swappable, non-wild, **non-fossil** cells only. Under
`rule_fossil_allow` a fossilized cell is walkable, but it is frozen in place and a
new word must still include at least one fresh cell
(`_rule_fossil_allow_word_ok`), so fossil grams are not material the player can
rearrange into a submittable word and are excluded from the check. Because
omniswap lets the player rearrange any non-fossil cell freely, this
arrangement-independent multiset check is exact for words built from the swappable
pool. Ends as FINISHED, the same end-state as the End game button / the race
clock hitting zero, running the final score tally. The point is to not waste the
player's time hunting (and running the clock down) for a word that cannot exist —
e.g. once the board is all but fully fossilized.
- `rule_omniswap_auto_end_off` — never auto-end (the default); the player finishes
  by hand (the End game button) or the timer runs out.
- `rule_omniswap_auto_end_on` — auto-finish the moment no word is submittable.
  Note this cuts against the no-word-availability-hints principle: an auto-finish
  tells the player the board is exhausted. Opt in deliberately.

### game_screen.omniswap_timer_seconds
Seconds the MOVING_OMNISWAP countdown starts at (only used by
`rule_mode_omniswap_vs_timer`). Under `rule_omniswap_timer_per_phase` this is the
per-phase budget, reset to full each time play returns to MOVING; under
`rule_omniswap_timer_race` it is the single whole-game clock (try ~360).

### game_screen.game_timer
A whole-game countdown that works in ANY mode. `rule_game_timer_off` (the default)
disables it; `rule_game_timer_on` arms it for `game_timer_seconds`. When on,
GameScreen — not the moving mode — runs one wall clock that starts as play begins
(when the opening reveal ends) and counts down continuously across both MOVING and
SELECTING (paused only by the menu, like every other clock). The instant it reaches
zero the game ends as FINISHED (no win check), exactly like the omniswap race clock.
The seconds-left are painted on whichever side pane is showing (top-edge label, in
place of the pieces-until-select count). This is the mode-agnostic sibling of the
omniswap timer: that clock lives inside `OmniswapVsTimerMode` and only exists in the
omniswap modes, whereas this one is owned by GameScreen so a constellation speed-type
(or any mode) can be time-boxed. Do NOT combine it with an omniswap timer variant in
the same mode — pick one clock, since both paint the same label and both end the game
at zero. Any victory rule still wins the game before the clock runs out (the time-left
score bonus reads this clock when it is the active one).

### game_screen.game_timer_seconds
Length of the `game_screen.game_timer` countdown, in seconds. Only read when the
timer is `rule_game_timer_on`. Try ~120 for a fast speed-type.

### game_screen.end_video
Filename of a video clip (under `assets/video/`) played once, fullscreen with sound,
the moment the game freezes into the end state — over the VICTORY/FINISHED panel.
Blank (the base default) turns the feature off; any mode can name a clip. The clip
plays through once and removes itself when it finishes; there is no user dismiss.
Decoded via pyglet's FFmpeg backend, so the host needs the FFmpeg shared libraries
installed. Currently used only by the shooting gallery (`goldeneye.mp4`).

### game_screen.sand_timer_delay_seconds / sand_timer_seconds / sand_timer_count
SAND-TIMER settings (only used by `rule_omniswap_timer_sand`). Instead of one global
countdown, up to `sand_timer_count` board cells are "sand timers" at a time; a sand
timer follows its gram when swapped. A cell's full life is a SILENT delay
(`sand_timer_delay_seconds` — no visible fill, but already the active/swappable sand
cell) followed by the FILLING animation (`sand_timer_seconds`); it fossilizes when
the fill completes, i.e. after delay + fill seconds total.

### game_screen.omniswap_timer
MOVING_OMNISWAP timer + endgame variant. All share the OMNISWAP PRESET; they differ
only in WHEN the clock runs and HOW the game ends:
- `rule_omniswap_timer_per_phase` — the countdown runs only while MOVING and resets
  to full each time a submitted word returns play to MOVING. Timer-zero forces a
  last-chance SELECT; leaving SELECT without submitting a word ends the game (a
  "surrender", FINISHED). The original omniswap behavior.
- `rule_omniswap_timer_race` — one continuous clock counts down across BOTH phases
  (visible in MOVING and SELECTING). The player toggles MOVING/SELECT freely — ENTER
  opens SELECT, Next piece returns to MOVING, neither ends the game — racing to form
  as many words as possible. The instant the clock hits zero the game ends
  (FINISHED, no win check). Pair with a shorter `omniswap_timer_seconds` (~360).
- `rule_omniswap_timer_sand` — no global clock. Up to `sand_timer_count` cells fill
  over `sand_timer_seconds` each (see above). A sand cell that fills before its gram
  is used in a word FOSSILIZES and a fresh non-fossilized cell takes its place; using
  a sand cell's gram in a word fossilizes it at once and frees the slot. The timer
  follows its gram on a swap. MOVING/SELECT toggle freely (like race); the game ends
  when the WHOLE board is fossilized (no cell left to time).

### game_screen.cursor_path
Order the MOVING_TYPEWRITER cursor visits cells.
- `rule_cursor_typewriter` — top-left, left→right per line, carriage-return down,
  ending bottom-right (jittery on the offset hex rows; fine for now).

### game_screen.typewriter_swap
On a MOVING_TYPEWRITER swap (cursor cell ↔ another board cell), which cells count as
"placed" this turn — i.e. nucleation sites for word-finding. The other (non-placed)
cell is treated as a settled board cell.
- `rule_swap_places_cursor_only` — only the cursor cell is placed; the swapped-in
  cell settles (a word must nucleate around the cursor).
- `rule_swap_places_both` — both swapped cells are placed (original behavior).

### TYPEWRITER PRESET
To play MOVING_TYPEWRITER, set `game_screen.mode` to `rule_mode_typewriter` and also
flip these (so the board starts full, formed words freeze instead of clearing,
there's no instant win, a pass always opens word entry, and every action is a select
turn):
- `game_screen.setup_formation` → `rule_formation_fill_player_diagonal`
- `game_screen.clear_action` → `rule_fossilize_cells`
- `game_screen.victory` → `rule_victory_none`
- `game_screen.skip_select_isolated` → `rule_never_skip_select`
- `game_screen.select_trigger` → `rule_select_every_placement`
- `game_screen.word_nucleation` → `rule_nucleate_anywhere` (so words can form anywhere)

(`game_screen.word_select` stays `rule_select_by_text_input`.)

### OMNISWAP PRESET
To play MOVING_OMNISWAP, set `game_screen.mode` to `rule_mode_omniswap_vs_timer` and
flip these (board starts full and swappable, formed words freeze, no instant win,
words can form anywhere with no placed piece, every commit is a select turn). Tune
`omniswap_timer_seconds` for length and `omniswap_timer` for the per-phase vs race
variant; `select_word_limit` picks one-word-then-MOVING vs many-words-per-SELECT:
- `game_screen.setup_formation` → `rule_formation_fill_player_diagonal`
- `game_screen.clear_action` → `rule_fossilize_cells`
- `game_screen.victory` → `rule_victory_none`
- `game_screen.skip_select_isolated` → `rule_never_skip_select`
- `game_screen.select_trigger` → `rule_select_every_placement`
- `game_screen.word_nucleation` → `rule_nucleate_anywhere`
- `game_screen.select_word_limit` → `rule_one_word_per_select` (or `rule_unlimited_words`)

(`game_screen.word_select` stays `rule_select_by_text_input`.)

### CONSTELLATION PRESET
To play MOVING_CONSTELLATION, set `game_screen.mode` to `rule_mode_constellation` and
flip these (board starts full, no placed piece so words form anywhere, every action
opens word entry, and SELECT stays open so many words clear per visit):
- `game_screen.setup_formation` → a fill formation (e.g. `rule_formation_fill_player_diagonal`
  or one of the ideation fills — every cell must carry a gram)
- `game_screen.word_nucleation` → `rule_nucleate_anywhere`
- `game_screen.skip_select_isolated` → `rule_never_skip_select`
- `game_screen.select_trigger` → `rule_select_every_placement`
- `game_screen.clear_timing` → `rule_clear_on_submit`
- `game_screen.select_word_limit` → `rule_unlimited_words` (keep typing without leaving SELECT)
- `game_screen.word_trail` → `rule_word_trail_on` (draw the constellation line)
- `game_screen.clear_action` + `game_screen.victory` — pick a matching pair:
  - `rule_fossilize_cells` + `rule_victory_grid_fossilized` (freeze cells; win when all frozen), or
  - `rule_remove_cells` + `rule_victory_grid_empty` (remove cells; win when board empty),
  - or `rule_victory_none` for an endless board.
- `game_screen.constellation_turnover` → `rule_constellation_no_replenish` (board shrinks
  toward the win) or `rule_constellation_replenish` (vacated cells refill; endless board —
  use with `rule_victory_none`).

The auto-pick vs blue-line chooser for which constellation clears is the existing
`game_screen.clear_disambiguation` (`rule_disambig_auto_pick` = fewest-cell, no
choice; `rule_disambig_cycle_*` = cycle the star patterns with the blue lines).
(`game_screen.word_select` stays `rule_select_by_text_input`.)

### SHOOTING GALLERY PRESET
To play MOVING_SHOOTING_GALLERY, set `game_screen.mode` to `rule_mode_shooting_gallery`.
The word is built by shooting cells, not typing, and validated as a plain dictionary
lookup on the shot-gram buffer (no board assembly / adjacency / nucleation), so the
constellation and pathfinder word-finding both sit idle. Flip:
- `game_screen.setup_formation` → `rule_formation_empty` (the `ShootingField` owns the
  grams, spawning them in fading batches into the empty grid)
- `game_screen.phase_model` → `rule_single_phase` (one continuous real-time phase; the
  player never leaves MOVING, the buffer + Clear-word button ride the merged pane)
- `game_screen.game_timer` → `rule_game_timer_on` with `game_screen.game_timer_seconds`
  → `300` (the 5-minute gallery clock)
- `game_screen.victory` → `rule_victory_none` (the timer is the only end)
- `game_screen.show_clear_button` → `rule_show_clear_button`; hide Submit / Next / End
  (there is nothing to submit or advance by hand — detection is automatic)
- tune the churn with `game_screen.shooting_batch_size` / `_batch_count` (concurrent
  staggered batches) / `_batch_delay_seconds` / `_fade_in_seconds` / `_hold_seconds`
  (linger fully shown) / `_fade_out_seconds` / `_shot_fade_seconds`, the miss timeout
  with `_word_timeout_seconds`, and the reticle with `_crosshair_scale` / `_gap` and
  the `board.crosshair` color.

### LINE BLAST PRESET
To play MOVING_LINE_BLAST, set `game_screen.mode` to `rule_mode_line_blast` and pair:
- `game_screen.grid` → `rule_use_square_grid` (line blast focuses on the square grid;
  full-row/column detection assumes it)
- `game_screen.setup_formation` → `rule_formation_empty` (the pool fills the board;
  nothing is pre-placed)
- `game_screen.phase_model` → `rule_two_phase` (drop pieces in MOVING, type words in
  SELECTING)
- `square_player.piece_set` → `rule_use_tetriminos` and `square_player.gram_pick` →
  a unigram picker (e.g. `rule_scrabble_distribution`) so each piece cell is one letter
- `game_screen.word_nucleation` → `rule_nucleate_within_highlight` (words must lie
  inside the completed line)
- `game_screen.word_select` → `rule_select_by_text_input`,
  `game_screen.clear_timing` → `rule_clear_at_phase_end` and
  `game_screen.select_word_limit` → `rule_unlimited_words` (batch several words, cells
  reusable across them, all cleared together on Next piece)
- `game_screen.clear_action` → `rule_remove_cells`, `game_screen.select_click` →
  `rule_select_click_none`, `game_screen.player_word_piece` → `..._disabled`
- `game_screen.moving_hunt_field` → `rule_hunt_field_off` and
  `game_screen.hunt_highlight` → `rule_hunt_none` (the moving pane shows piece
  previews, not a hunt field)
- `game_screen.victory` → `rule_victory_none` (no win condition; the moving pane's
  End-game button ends the game — so `game_screen.show_end_button` →
  `rule_hide_end_button` keeps the SELECTING pane's own End button off)
- `game_screen.word_length` → `rule_word_min3letters_min2cells` (unigram cells, so ≥3
  letters means ≥3 cells)
- tune the pool + previews with `game_screen.line_blast_pool_size` / `_slots` /
  `_preview_scale`, and the tints with `board.line_blast_highlight` /
  `_floating_valid` / `_floating_invalid`.

### game_screen.word_length
- `rule_word_min3letters_min2cells` — words need ≥3 letters and ≥2 cells.
- `rule_word_min2letters_min2cells` — words need ≥2 letters and ≥2 cells.
- `rule_word_min3letters_min1cell` — words need ≥3 letters, any cell count (so a
  single multi-letter gram can be a whole word). The shooting-gallery choice: one
  shot is one cell, so this cuts single-letter shots (S / O / T — which the
  dictionary's obscure tier accepts as words) while still allowing a 3-letter word
  shot from one trigram cell, which the min2cells rules would wrongly reject.

### game_screen.starting_coverage_dictionary
Starting-coverage dictionary (debug/analysis): once at game start, before the
opening reveal, enumerate EVERY dictionary word the initial board could spell (any
arrangement — ignores adjacency/nucleation/fit; respects `word_length` and
no-cell-reuse; pools player+obstacle+mission grams; ignores wild vowels, the jigsaw
pool, and gram-manipulation). Writes `sessions/<id>.coverage.csv` and logs how long
it took. BLOCKING — the player can't act until it finishes. Requires
`logging.enabled` (the file lives beside the log). Off by default; `on` slows the
opening of every game.
- `rule_starting_coverage_off` / `rule_starting_coverage_on`.

### game_screen.word_repeat
`rule_repeat_block` or `rule_repeat_allow` — whether a word already cleared this game
can be cleared again.

### game_screen.mode_title
Show the current game mode's human-readable name (`mode_label` from the active
`game_modes/*.yaml`, via `active_mode()`) as a single small line along the top of
the board. Blank when the game is on the bare base `config.yaml` (no mode applied).
Toggle with `rule_mode_title_on` / `rule_mode_title_off`. Text color is
`board.mode_title` in the colors file.

### game_screen.word_trail (+ word_trail_thickness / word_trail_opacity)
Word trail: overlay a polyline along each cleared word's cell path (center to
center) on top of the board. Trails accumulate for the whole game (cleared on a new
game). `word_trail_thickness` is in pixels; `word_trail_opacity` is a 0–1 fraction
(0.5 = 50%). Toggle with `rule_word_trail_on` / `rule_word_trail_off`.

A trail IS dropped early when the cells it runs through leave the board together — which
happens under `game_screen.cell_health`, where an attacking word's line would otherwise
outlive the obstacle it was drawn against (see `game_screen.attacker_release`).

The polyline meets each cell at its VISUAL center, which differs from the cell
coordinate's centroid only for the triangle board's jumbo hexagons (one cell spanning
six triangles) — so a line into a big hexagon lands in the hexagon's middle rather than
on the anchor triangle holding its gram.

### game_screen.clear_disambiguation (+ disambig_line_* )
When a submitted word can clear several ways on the board (multiple paths, or
wild-vowel expansions), how the one to clear is chosen — and whether a lone path
still asks to confirm.
- `rule_disambig_auto_pick` — silently keep the fewest-cell spelling, ties broken at
  random (original; fastest, good for timer-pressured modes); no confirm step ever.
- `rule_disambig_cycle_two_or_more_choices` — draw every candidate as a polyline on
  the board (light blue, the highlighted one dark blue), let the player cycle with
  `word_cycle_prev` / `word_cycle_next`, then confirm with `word_submit`. Only opens
  when 2+ ways exist; a lone path clears instantly.
- `rule_disambig_cycle_one_or_more_choices` — the same chooser, but it opens for
  EVERY clearable word, a lone path included, so every valid submit gets the
  blue-path preview + an explicit confirm (a second `word_submit`). Back out (per
  `disambig_cancel`) with Backspace / Escape / any letter to hunt a different word.

Line styling (only under `disambig_display: rule_disambig_display_lines`):
- `disambig_line_thickness` / `disambig_line_thickness_selected` (pixels) — the
  highlighted candidate can read thicker so it stands out alongside its darker color.
- `disambig_line_opacity` — 0–1.

### game_screen.disambig_display
HOW an open chooser is drawn — orthogonal to the `clear_disambiguation` cycle rules
above, which only decide WHEN it opens. Both modes cycle with `word_cycle_prev` /
`word_cycle_next` and confirm with `word_submit` identically.
- `rule_disambig_display_lines` — the original blue polylines (see the line-styling
  keys above and the `board.disambig_line[_selected]` colors).
- `rule_disambig_display_highlight` — no lines. Every cell that ANY candidate would
  clear has its whole gram lit in the hunt-highlight color (the `board.hunt_highlight`
  green, reusing the word-hunt overlays), and the CURRENTLY-selected candidate's cells
  get a pale-lime background fill (`board.disambig_highlight_fill`); cycling moves the
  fill from one spelling to the next. Each tinted cell's prior color is restored on
  confirm / cancel, so the fill layers cleanly over settled / obstacle / mission /
  fossil / pending cells.

### game_screen.disambig_cancel
Whether a back-out gesture (`word_clear` / Backspace / Escape / any letter) exits the
chooser — returning to the typed word — or the player must commit to one candidate
once a valid word is submitted. `rule_disambig_cancel_on` / `_off`.

### game_screen.botanical_disambiguation
Botanical only. A typed word can often grow off the stem several ways — a different
stem cell whose gram it contains, or the same gram at a different position in the word
— each laying the leaves in a different spot. This chooses WHICH grow-site is used.
Botanical places cells rather than clearing them, so it bypasses the SELECT
`clear_disambiguation` pipeline and consults this seam instead; the cycle rules reuse
the same shared chooser (cycle with `word_cycle_prev` / `word_cycle_next`, confirm with
`word_submit`), so pair them with `disambig_display: rule_disambig_display_lines` — the
leaf targets are still-empty cells, so only the blue polylines (drawn through cell
centers) visualize each candidate; the highlight display would show nothing there.
- `rule_botanical_disambig_auto_pick` — silently grow the most compact layout (fewest
  new leaves, then the earliest crossing), no confirm step (original).
- `rule_botanical_disambig_cycle_two_or_more_choices` — open the chooser only when 2+
  grow-sites fit; a lone layout grows instantly.
- `rule_botanical_disambig_cycle_one_or_more_choices` — open the chooser for every
  accepted word, a lone layout included, so every grow previews its span + confirms.

### moving_side_pane.wordlist_rows
How many word rows the right pane's scrolling cleared-word list shows. Fewer rows
than the pane fits pack from the top (blank space below); more rows than fit shrink
the font so they all stay inside the pane.

### game_screen.spawn
Player-piece spawn: where each single live piece appears, one at a time.
`rule_spawn_random_spot` or `rule_spawn_center`.

### game_screen.spawn_orientation
`rule_orient_random` or `rule_orient_default`.

### game_screen.setup_formation
How the whole opening set of obstacle + mission pieces is laid out (built and placed
before play). Separate from the per-piece player spawn above; the formation owns how
many pieces of each it lays down.
- `rule_formation_empty` — leave the board completely empty: no obstacle, mission, or
  player fill. For modes whose own field populates cells at runtime (the shooting
  gallery's `ShootingField` spawns fade-in batches into the empty grid). Pair with
  `game_screen.victory: rule_victory_none` (an empty board is not a win here).
- `rule_formation_scattered` — `obstacle_count` obstacles + `mission_count` missions,
  each at a random non-overlapping spot (the original opening).
- `rule_formation_mission_center_obstacle_ring` — 1 mission on the center cell,
  ringed by one obstacle per neighbor (6 on a hex grid). Single-cell pieces:
  the ring sits one CELL away, so a multi-cell piece would overlap it. Use the
  jumbo rule below for jumbo cells.
- `rule_formation_jumbo_mission_center_obstacle_ring` — the JUMBO twin of the
  above: one jumbo mission cell at the center, ringed by up to six jumbo obstacles
  touching it edge-to-edge (a flower of seven big cells). Jumbos tile on the
  HEXAGON lattice, not the triangle one, so the ring anchors are the center's six
  jumbo-neighbors rather than its triangle-neighbors — placing a jumbo on a
  triangle-neighbor overlaps four of the center's six coordinates. Triangle grid
  only. Pair with `rule_use_triangle_jumbos` on BOTH `triangle_mission.piece_set`
  and `triangle_obstacle.piece_set`. Like the ring rule above it derives its own
  counts, so `game_screen.obstacle_count` / `mission_count` are ignored; ring
  anchors whose footprint runs off the board are dropped, so a small board opens
  with a partial ring rather than a crowded one.
- `rule_formation_fill_player_diagonal` — fill every board cell with a single-cell
  player piece (no obstacles/missions). Board opens fully packed; pair with
  `game_screen.victory: rule_victory_none` so it isn't an instant/blocked win. The
  gram lengths form DIAGONAL LINES (the round-robin length cadence aliases into
  diagonals), unless the length-controlled picker is inactive — then row-major.
  NOTE: the diagonal here is an aliasing artifact — it only holds at certain
  digram/trigram+ percentages; use `rule_formation_fill_player_wood_grain` for a
  formalized diagonal that survives any percentages.
- `rule_formation_fill_player_wood_grain` — the legacy diagonal grain, but PINNED to
  a fixed length mix so it no longer breaks when you tune the percentages. It runs
  the round-robin 1/2/3+ cadence (the same thing that made the original grain)
  mapped row-major, using a hard-coded uni/digram/trigram weighting baked into the
  code (`WOOD_GRAIN_LENGTH_WEIGHTS` in `game_screen`, currently 50/30/20 — recovered
  from the session that produced the desired grain). So the GRAIN SHAPE is fixed for
  a given board size regardless of `gram_length.*_percent`; those percentages still
  drive every other draw (piece pool, other formations). Needs the length-controlled
  picker (same as the diagonal fill).
- `rule_formation_fill_player_random` — same uniform fill, but the gram lengths are
  SCATTERED to random cells (same uni/digram/3+ counts, no diagonal), unless the
  length-controlled picker is inactive — then row-major.
- `rule_formation_fill_ideation_trigram_sidepanes_digram_centercircle` — like the
  uniform fill, but laid out by gram TYPE: trigram+ PREFIX grams packed into the
  far-LEFT edge, trigram+ MIDFIX/SUFFIX into the far-RIGHT edge, all DIGRAMS in a
  rough CENTER circle (random *fix mix), and UNIGRAMS filling the gaps.
- `rule_formation_fill_ideation_trigram_sidepanes_digram_bottompyramid` — same
  trigram+ side panes, but the DIGRAMS form a TRIANGLE at the screen bottom pointing
  up (widest along the bottom, narrowing upward); UNIGRAMS fill in.
- `rule_formation_fill_ideation_trigram_sidepanes` — same trigram+ side panes, but
  with NO dedicated digram region: DIGRAMS and UNIGRAMS are mixed RANDOMLY together
  across every non-pane cell.
- `rule_formation_fill_ideation_trigram_sidepanes_zigzag` — same as
  `rule_formation_fill_ideation_trigram_sidepanes` (no digram region, random
  digram/unigram mix), but each trigram+ pane ZIGZAGS down its two outermost columns
  — outer column on even rows, inner column on odd rows, one cell per row — so the
  multigrams alternate left/right as they descend instead of packing one straight
  edge column. Same counts and left/right split.

The ideation layouts: how many of each length comes from `gram_length.*`; the
left/right trigram split from `gram_ideation.trigramplus.*` (prefix : midfix+suffix).
Force the length-controlled picker regardless of `*_player.gram_pick`; pair with
`game_screen.victory: rule_victory_none`.

### game_screen.obstacle_count / mission_count
How many obstacle / mission pieces `rule_formation_scattered` lays down. The ring
formation derives its own counts from board geometry and ignores these. Also gate the
obstacle/mission victory rules: a count of 0 means "the board never started with this
kind", so that victory rule can't be satisfied.

### hex_grid.word_pathfinding
Stage 1 (pathfind): how the search walks the board to find words. Grid-level because
geometry differs — the hex board's snake directions are configured here, the square
board's under `square_grid.word_pathfinding`.
- `rule_snake_rightanddown_nosharptwist`, `rule_snake_rightanddown`,
  `rule_snake_straightline` — TODO: retest after refactor.
- `rule_snake_anydirection` — current.

### triangle_grid.word_pathfinding
Stage 1 (pathfind) for the triangle board — the counterpart to
`hex_grid.word_pathfinding`.
- `rule_snake_edges_anydirection` — the three edge-neighbors, any turn. This is the
  full physical-adjacency set for a triangle. Vertex-adjacency (the twelve cells
  that merely touch a corner) is deliberately not offered: word paths stay
  edge-connected. Register a second rule here if that is ever worth trying.

### square_grid.word_pathfinding
Stage 1 (pathfind) for the square board — the counterpart to
`hex_grid.word_pathfinding`. Chooses which step directions the word-walk may take.
Neither rule restricts turns; the walk's path-visited guard is what stops a word
doubling back onto its own cells. (Physical adjacency for the SELECT phase stays
cardinal-only regardless — this knob only affects the word-finding walk.)
- `rule_snake_anydirection` — the four cardinals, any turn (the board's original
  hardcoded behavior).
- `rule_snake_anydirection_diagonal` — the eight king-move directions (cardinals +
  diagonals), any turn; lets words run diagonally across the grid.

### game_screen.word_nucleation
Stage 2a (nucleate): of every word found, which count for the moving phase just
ended.
- `rule_adjacent_to_placed_pieces` — keep words bridging any piece placed this phase
  (all of them are nucleation sites, not just the last) AND an existing cell.
- `rule_nucleate_anywhere` — every board word counts, wherever it sits (no tie to a
  placed piece, so words can be built anywhere).
- `rule_nucleate_none` — nothing qualifies (clearing off).
- `rule_nucleate_within_highlight` — line blast: keep only words whose path lies
  WHOLLY inside the currently highlighted line(s) (`_line_blast_highlight`, the cells
  of a just-completed row/column). Placement plays no part; the highlighted set is
  the entire SELECT domain, so a word stepping to any cell outside it is dropped.
  Empty highlight ⇒ nothing qualifies. See MOVING_LINE_BLAST / the LINE BLAST PRESET.

### game_screen.placed_cell_requirement
Stage 2b (placed-cell requirement): an independent filter on the nucleated words —
whether a word must include a cell from a piece placed this phase. Orthogonal to
`word_nucleation`, so it composes: e.g. `rule_nucleate_anywhere` +
`rule_require_placed_cell` keeps any board word that also touches a placed cell.
- `rule_require_placed_cell` — word must cover ≥1 placed cell.
- `rule_placed_cell_optional` — no such requirement.

(Optional by default; `rule_adjacent_to_placed_pieces` already needs a placed cell,
so the current behavior is unchanged.)

### game_screen.fossil_requirement
Stage 2c (fossil requirement): a third independent filter on the words that pass the
placed-cell stage — whether a word must cover at least one fossilized cell. Composes
with `word_nucleation` and `placed_cell_requirement`. Fossils only exist once a word
has cleared under a fossilize clear-action (see `game_screen.clear_action` /
`fossil_word_use`), so on its own `rule_require_fossil_cell` makes the opening word of
a game unclearable — pair it with `fossil_requirement_first_word` below to bootstrap.
A word rejected solely for missing a fossil cell reports `err_not_fossil` (log reason
`not_fossil`).
- `rule_require_fossil_cell` — word must cover ≥1 fossilized cell (subject to the
  first-word skip below).
- `rule_fossil_cell_optional` — no such requirement (default; existing configs
  unchanged).

Depends on `game_screen.fossil_word_use: rule_fossil_allow` to be meaningful: under
`rule_fossil_block` fossilized cells are walls the word-finder never walks, so no word
can contain one and `rule_require_fossil_cell` would reject everything.

### game_screen.fossil_requirement_first_word
Enable/disable knob read by `rule_require_fossil_cell`: whether to waive the fossil
requirement while no word has cleared this game yet. Lets the opening word (which can
never touch a fossil, since none exist yet) land and create the first fossils. Inert
when `fossil_requirement` is `rule_fossil_cell_optional`.
- `rule_fossil_skip_first_word` — waive the requirement until the first word clears
  (default).
- `rule_fossil_no_skip` — enforce it from the very first word (unplayable unless
  fossils already exist by some other means).
- `rule_fossil_seed_center` — instead of waiving, fossilize one random occupied cell
  at game start drawn from the board center cell plus its immediate neighbours (four
  on square, six on hex — physical adjacency; empty candidates skipped). The
  requirement then holds from word one without a skip, since a fossil already exists
  to build the first word around. The draw uses the session RNG, so a replay
  reproduces the same seeded cell (logged as `06005`). No-op if no cell near the
  centre carries a gram (e.g. an empty opening board), which leaves the requirement
  unsatisfiable until a fossil appears.

### game_screen.gram_usage
Whether a word must use all of a cell's gram, or may take part.
- `rule_gram_use_whole` — a word always consumes a cell's entire gram (original).
- `rule_gram_use_partial` — a word may start inside a gram (a suffix of its first
  cell) and end inside one (a prefix of its last cell); middle cells stay whole. The
  unused letters stay on the board, re-rendered in place (e.g. W + ING → WIN leaves
  G; ING + OO + D → GOOD leaves IN). In batch mode (`clear_at_phase_end`) several
  words may take different bites of one gram (H ING O → HI + GO leaves N; W ING O →
  WIN + GO clears it).

### game_screen.fossil_word_use
May a NEW word use fossilized cells (frozen formed words; only present under
`clear_action: rule_fossilize_cells`).
- `rule_fossil_block` — fossils are walls: a word can't start on, pass through, or end
  on one (original behavior).
- `rule_fossil_allow` — a word may use fossilized cells, but must include at least one
  non-fossilized cell (never built purely from frozen ones).

### game_screen.phase_model
Whether the game runs two distinct phases or one merged phase. The two-phase machine
(MOVING to place/rearrange, then a separate SELECTING phase to type/submit words) is the
original; single-phase collapses both into one MOVING_AND_SELECTING pane where the player
rearranges the board and submits words at the same time, with no modal transition.
- `rule_two_phase` — MOVING then SELECTING, each with its own right pane (original).
- `rule_single_phase` — one merged right pane; the game never leaves MOVING and words are
  submitted inline. Intended for the pre-filled-board modes only (constellation, omniswap,
  typewriter), which have no piece-spawn cycle that needs a SELECT gate. Pairs with an
  interactive `word_select` (`rule_select_by_text_input`); ignored by the auto selector.
  With no phase boundary, single-phase FORCES `clear_timing` to clear-on-submit regardless
  of the configured value (a phase-end batch would never flush -- its cells would tint green
  forever and never clear or list), and `select_word_limit` is inert (nothing ends the
  never-ending phase). So set `clear_timing: rule_clear_on_submit` + `select_word_limit:
  rule_unlimited_words` to match what actually runs. The disambiguation cycle chooser works
  here too (routed in MOVING).

### game_screen.word_select
Stage 3 (select): of the nucleated candidates, which to actually clear.
- `rule_select_mostwords_withoverlaps_withrepeats` — automatic, instant (keep maximal
  paths: overlaps + repeats included, strict sub-words dropped).
- `rule_select_by_text_input` — interactive: player types the words to clear in the
  right pane, then hits Next piece (the SELECTING phase).

### game_screen.clear_timing
When typed words clear during the interactive SELECT phase.
- `rule_clear_on_submit` — each submitted word clears from the board the moment it is
  submitted (original behavior).
- `rule_clear_at_phase_end` — submitted words are held and their cells tinted light
  green; the whole batch clears together when the phase ends, so cells can be reused
  across words (overlaps + repeats — a word may be entered once per distinct path).
  The interactive twin of `rule_select_mostwords_withoverlaps_withrepeats`.

### game_screen.select_word_limit
How many words the player may clear in one interactive SELECT phase before it ends and
play returns to MOVING. Composes with `clear_timing`.
- `rule_unlimited_words` — the phase stays open until the player hits Next piece (or,
  in clear-on-submit mode, the placed piece is stranded). Original.
- `rule_one_word_per_select` — the first accepted word ends the phase at once (in
  batch mode that one held word clears on the way out).

### game_screen.select_autosubmit_hunt
Auto-submit the carried word when ENTER opens the interactive SELECT phase with a word
still sitting in the MOVING word-hunt field. On, opening SELECT goes straight to the
blue-path confirm — one ENTER to open, one to confirm — instead of a dead middle ENTER
to submit the word already in the field. A junk / too-short hunt just rejects (ghost +
reason) and the field clears for a fresh type. Off keeps the word pre-loaded but
unsubmitted, so the player confirms or edits it first (the original anti-fat-finger
behavior). Only bites under `word_select: rule_select_by_text_input`.
- `rule_select_autosubmit_on` / `rule_select_autosubmit_off`.

### game_screen.select_trigger (+ select_trigger_count)
- `rule_select_every_placement` — run selection after every placement.
- `rule_select_after_n_placements` — run selection every `select_trigger_count`
  placements.

### game_screen.skip_select_isolated
Whether a placed piece touching nothing on the board skips the selection (if an
isolated piece can't bridge into any word, auto-skip for UX flow).
- `rule_skip_select_if_isolated` — skip when the placed piece is isolated (original).
- `rule_never_skip_select` — always run selection, isolated or not.

### game_screen.select_click
What a left-click on a board cell does during the SELECTING phase.
- `rule_select_click_move_piece` — route the click to the active MOVING mode's board
  handler, so the player can rearrange cells (omniswap swap, etc.) without leaving
  word entry; the clearable words re-find after the edit. Blurs the SELECTING/MOVING
  line for the free-choice modes.
- `rule_select_click_none` — board clicks do nothing while selecting (keep the hard
  phase separation, e.g. for the timed transition modes).

(The "Clear word" control is always shown, independent of this rule.)

### game_screen.reject_ghost
After a REJECTED word submission during SELECTING (misspelled / not on the board),
whether to echo the rejected word as a dim "You typed: …" line above a CLEARED entry
field — so the player compares it to the spelling suggestion and retypes fresh,
instead of unknowingly appending to the failed attempt. The echo persists while
retyping and clears on the next accept / Clear word.
- `rule_reject_ghost_on` — clear the field, show the ghost echo.
- `rule_reject_ghost_off` — leave the failed word in the field (original).

### game_screen.error_display
How a rejected submission surfaces its reason in the right pane's error slot. The
stable reason key that the submission-error logic already logs (`not_in_dictionary`,
`not_on_board`, `already_cleared`, …) is passed to the SELECT / merged pane, which
maps it to an icon under icon mode.
- `rule_error_text` — show the worded reason message (original), plus the
  "Did you mean: …?" spelling suggestion under a not-a-word rejection.
- `rule_error_icon` — show a reason icon in place of the text, scaled to fit the
  same slot. Icons exist for: `not_in_dictionary`; `too_short`; the duplicate family
  (`already_cleared` / `already_selected_one_way` / `every_way_selected`); and the
  two not-on-board sub-classes split by `game_screen._not_on_board_reason` —
  `not_on_board_missing_letter` (the word needs more of some letter than the board
  has, including letters it has none of → the absentletter art) and
  `not_on_board_gram_mismatch` (every letter is available in enough supply, but the
  grams don't divide to spell it → the tiling art). Reasons with no icon
  (`not_involved`, `not_fossil`) fall back to the text message. Whether the
  "Did you mean: …?" spelling suggestion survives the icon is a separate knob,
  `game_screen.error_icon_keeps_suggestion` (below). Reason→icon wiring lives in
  `_REASON_TO_ICON` in `views/textures.py`.

### game_screen.error_icon_keeps_suggestion
Only meaningful under `game_screen.error_display = rule_error_icon` (inert in text
mode, which always shows the suggestion). Controls what happens to the
"Did you mean: …?" spelling hint (`game_screen.spell_suggest`) when a not-a-word
rejection is shown as an icon: the icon replaces the reason *sentence*, but the
suggestion is a separate line.
- `rule_error_icon_keeps_suggestion_on` — keep the hint. The reason icon shrinks to
  the top ~60% of the error box (`SUGGESTION_ICON_FRACTION` in the panes) and the
  suggestion text sits underneath it, so the player sees both the icon and
  "Did you mean: BARNACLE?".
- `rule_error_icon_keeps_suggestion_off` — drop the hint (original icon behavior):
  the icon fills the whole error box and the suggestion line is discarded, so only
  the icon shows.

Either way the computed hint (and whether it was shown) is recorded in the session
log via `log_30005`, so a replay can tell a hint the engine never produced from one
this knob suppressed.

### game_screen.missing_letter_highlight
On a NOT-ON-BOARD rejection, redden the letters of the "You typed: WORD" ghost the
board can't supply — a quick "you haven't got that letter" cue. A supply-COUNT check
(not mere existence): the board's occupied grams are pooled into a multiset of letters
(a wild cell counts as one of every vowel), and each occurrence of a letter in the word
past the board's available count is reddened. So a word needing two S when the board has
one S reddens the *second* S; a letter the board has none of reddens every copy. NO
tiling / arrangement awareness — but the letter count is a hard upper bound on any
tiling, so a reddened letter is provably unspellable. This is the same computation that
splits the rejection into `not_on_board_missing_letter` (some letter over-demanded) vs
`not_on_board_gram_mismatch` (supply sufficient, arrangement fails), so the highlight
and the message/icon always agree. Rides on the ghost, so it needs
`game_screen.reject_ghost = rule_reject_ghost_on`; the color is
`selecting_side_pane.missing_letter`.
- `rule_missing_letter_highlight_off` — draw the ghost in one dim color (original).
- `rule_missing_letter_highlight_on` — redden the over-demanded letters.

### game_screen.show_clear_button / show_submit_button / show_next_button / show_end_button
Whether each control label in the right pane is drawn. The pane stacks its controls
top-to-bottom in the fixed order Clear word / Submit word / Next piece / End game;
a hidden button takes **no vertical slot** (the buttons below it close the gap) and
is skipped in click hit-testing. Hiding a button removes only the mouse affordance —
the keyboard route is untouched: ENTER still submits, the `selection_end` key still
ends the SELECT phase, and the `word_clear` key still empties the field. These apply
to both the two-phase SELECT pane (`SelectingSidePane`, all four buttons) and the
single-phase merged pane (`MovingSelectingSidePane`, which has no Next piece button
regardless — there is no phase to leave, so `show_next_button` is ignored there).
- `game_screen.show_clear_button`: `rule_show_clear_button` / `rule_hide_clear_button`.
- `game_screen.show_submit_button`: `rule_show_submit_button` / `rule_hide_submit_button`.
- `game_screen.show_next_button`: `rule_show_next_button` / `rule_hide_next_button`.
- `game_screen.show_end_button`:
  - `rule_end_button_auto` — historical behavior: shown only for constellation, which
    has no piece to shrink the board and (endless preset) no victory rule to close on;
    hidden in every mode that ends on its own.
  - `rule_show_end_button` — always shown.
  - `rule_hide_end_button` — never shown.

### game_screen.player_word_piece
Player word-piece: clicking a cleared word in the right pane during the MOVING phase
swaps the live piece for a single-cell piece carrying that whole word as a multigram
(usable to complete words like any other player piece). The displaced piece is set
aside and returns as the next piece once the word-piece is placed. Only one swap per
piece — you can't click another word until the word-piece is placed and a fresh
pre-selected piece appears.
- `rule_player_word_piece_enabled` — allow the swap (clicks consume the word).
- `rule_player_word_piece_disabled` — right-pane clicks do nothing.

### game_screen.rightclick_* (cell gram-manipulation)
A RIGHT-click on a board cell during the MOVING phase transforms the letters in that
one cell (the `controls.yaml` `mouse.gram_manipulate` button; mode-agnostic, so it
works in jigsaw / typewriter / omniswap). The rule is chosen by the gram's
vowel/consonant SHAPE (unigram + five digram shapes + two trigram shapes + a
catch-all), plus a slot for wild-vowel cells. Empty and fossilized cells are never
affected. Every rule is the doubling primitive C → CC (double a consonant) with its
reverse CC → C (a doubled consonant collapses on the next right-click); **Y counts as
a CONSONANT throughout** (so ITY / ARY / PHY are NOT treated as VCV/CVK). Each slot's
`rule_rightclick_none` option restores "right-click does nothing". (NOTE: by default
`controls.yaml` leaves `mouse.place_piece` UNASSIGNED so RIGHT is free for this.)

- `rightclick_unigram` (1-letter cell) — `rule_unigram_double`: double the letter
  (O → OO, B → BB). Pairs with the CC slot for the L ↔ LL toggle.
- `rightclick_cc` (a doubled consonant, e.g. LL) — `rule_cc_collapse`: collapse to the
  single letter (LL → L). The forward L → LL is the unigram slot, so the two make an
  L ↔ LL toggle.
- `rightclick_cv` (consonant+vowel, e.g. BA) — `rule_cv_double`: double the consonant
  (BA → BBA), collapse back on the next click (BBA → BA).
- `rightclick_vc` (vowel+consonant, e.g. AN) — `rule_vc_double`: double the consonant
  (AN → ANN), collapse back (ANN → AN).
- `rightclick_vv` (two vowels, e.g. EE / EA) — `rule_vv_collapse`: collapse a doubled
  vowel to the single letter (EE → E), the vowel mirror of `rule_cc_collapse`. Pairs with
  `rightclick_unigram`'s `rule_unigram_double` (E → EE) to make the E ↔ EE toggle. Distinct
  vowels (EA) have nothing to dedup, so it's a no-op there. The `rule_rightclick_none`
  option restores the old "no consonant to double, right-click does nothing" behavior.
- `rightclick_ck` (two DISTINCT consonants, e.g. ST) — `rule_ck_double`: double the
  FRONT consonant (ST → SST), collapse back (SST → ST). Front-ONLY by design: the
  corpus says the front double lands in real words for 32% of CK digrams (ly→lly,
  pr→ppr, pl→ppl, bl→bbl, tr→ttr) but the back double (STT) for 0/59 — so the back
  double is dropped, and no alternation state is needed.
- `rightclick_vcv` (vowel-consonant-vowel, e.g. ARE) — `rule_vcv_double`: double the
  single middle consonant (ARE → ARRE), collapse back (ARRE → ARE). Corpus-backed:
  the middle-consonant double lands in real words for ~73% of VCV trigrams (ate→atte,
  ile→ille, ome→omme) — the strongest of all the shapes, so it's on by default.
- `rightclick_cvk` (consonant-vowel-consonant, e.g. MER) — `rule_cvk_double`: double a
  consonant, ALTERNATING which one across successive clicks so both forms are
  reachable — MER → MMER → MER → MERR → MER. Each doubled form collapses back on the
  next click. The alternation is tracked per board cell (starts on the 'back'
  consonant, MER → MERR, the corpus-favored double). Corpus-backed: ~46% of CVK
  trigrams hit real words on the back double (cal→call, les→less), ~39% on the front
  (com→comm, per→pper).
- `rightclick_vowelwild` (wild-vowel emblem cells, `rule_scrabble_with_allvowelswild`)
  — `rule_rightclick_none`: no transform yet. A wild cell holds no fixed letters, so a
  manipulation rule for it is still TBD.

Every OTHER 3+ shape (CKV like "tra", VCK like "ant", CKS like "str") is an
unconfigured no-op — the corpus showed doubling a consonant inside a real cluster
almost never yields a spellable chunk (CKV useful ~16% and front-only; VCK ~0%; CKS
exactly 0%), so there's no catch-all rule for them.

### game_screen.gram_manip_in_selecting
Whether the gram-manipulate button (right-click) also works during the SELECTING
phase, not just MOVING. The omniswap modes spend most of their play in SELECT, so
MOVING-only leaves right-click feeling dead there.
- `rule_gram_manip_in_selecting_enabled` — right-click doubles/collapses grams in
  SELECTING too (the board cell is relabeled; the typed word field is independent, so
  nothing desyncs).
- `rule_gram_manip_in_selecting_disabled` — right-click is inert in SELECTING
  (MOVING-only; original behavior).

### game_screen.moving_hunt_field
Whether the MOVING side pane shows its word-hunt field at all — the "Hunt a word"
prompt and the live-typed input at the top of the pane (`views/moving_side_pane.py`).
- `rule_hunt_field_on` — normal: the field is drawn and typed letters feed it (which
  in turn drives `hunt_highlight`).
- `rule_hunt_field_off` — no field is built and typed letters are swallowed, giving a
  bare MOVING board with no text surface. The layout below (Pieces / score / Select)
  reflows up to reclaim the two lines. SELECTING is still reachable via ENTER or the
  "Select words" button. Because nothing is ever typed, `hunt_text()` stays empty, so
  `hunt_highlight` never lights and `select_autosubmit_hunt` no-ops on the carry-in.

This is meaningful only under `phase_model: rule_two_phase`. In `rule_single_phase`
the merged MOVING_AND_SELECTING pane owns its own text entry (that IS how words are
submitted), so this rule does not touch it — leave the field on there.

### game_screen.hunt_highlight (+ hunt_highlight_style)
Word hunt (MOVING phase): the player types a word in the moving side pane and the
grams on the board involved in it light up (see `views/hunt_highlight.py`). Two
independent toggles.

`hunt_highlight` — WHICH grams/letters match the typed word:
- `rule_hunt_none` — off: nothing lights. The typed field and submit still work; only
  the on-board green paint is suppressed, for a bare typing surface (constellation
  speed type).
- `rule_hunt_full_gram` — only a cell whose whole gram is a contiguous chunk of the
  word (INDICATIVE lights "IVE", not "CU"/"EN"/"ING"); all its letters color.
- `rule_hunt_full_gram_or_dedup` — like full_gram, but ALSO lights a gram that is one
  right-click (a doubling/dedup collapse) from fitting: search "LAMP", gram "MMP"
  lights its "MP" (collapse MMP → MP), the redundant doubled copy left dark. Accounts
  for the `game_screen.rightclick_*` doubling rules. Doubling never adds a NEW match (a
  word with "BBA" already has "BA"), so only the collapse direction is considered.
- `rule_hunt_single_letters` — every single letter that appears anywhere in the word
  colors, even a partial / out-of-order cell (INDICATIVE lights C of "CU", both of
  "EN", I+N of "ING").

`hunt_highlight_style` — HOW a matched gram looks (the visual). Only the text-recolor
style exists today (`rule_hunt_style_text_recolor`); rect-tint / outline would be
siblings.

### game_screen.dictionary_count
Whether the right pane shows the player's lifetime dictionary-size readout.
`rule_show_dictionary_count` / `rule_hide_dictionary_count`.

### game_screen.victory
Victory condition (only one active at a time):
- `rule_victory_missions_cleared`
- `rule_victory_missions_and_obstacles_cleared`
- `rule_victory_obstacles_cleared`
- `rule_victory_grid_empty` — win when the board holds no cells (the whole-board-
  cleared endgame; pair with `rule_remove_cells`, e.g. constellation without replenish).
- `rule_victory_grid_fossilized` — win when every board cell is fossilized (the whole-
  board-frozen endgame; pair with `rule_fossilize_cells`, e.g. constellation/omniswap).
- `rule_victory_none` — no win condition at all; the game runs until the player quits
  (use with `rule_formation_fill_player_diagonal`, which has no missions/obstacles).

### game_screen.fill_board
Whole-board fill bonus: awards `scoring.fill_board_bonus` ONCE per game the first time
the board is entirely filled. What "filled" means is MODE-DEPENDENT, so pick the
variant matching `game_screen.mode` / `clear_action`:
- `rule_fill_board_all_fossilized` — every board cell is FOSSILIZED (the fossilize
  modes: omniswap / typewriter, `clear_action: rule_fossilize_cells`, where a
  completed-word cell freezes in place until the whole board is frozen).
- `rule_fill_board_all_occupied` — every board cell is OCCUPIED by a settled piece
  (the place/remove modes: jigsaw fills empty cells until none remain).
- `rule_fill_board_off` — no whole-board fill bonus.

### game_screen.cell_overlap_* 
Whether a piece may be moved onto / placed over a type of occupied cell.
- `cell_overlap_player` — `rule_moveandplace_over_player_cell` /
  `rule_block_moveandplace_over_player_cell`.
- `cell_overlap_obstacle` — `rule_moveandplace_over_obstacle_cell` /
  `rule_block_moveandplace_over_obstacle_cell`.
- `cell_overlap_mission` — `rule_moveandplace_over_mission_cell` /
  `rule_block_moveandplace_over_mission_cell`.
- `cell_overlap_fossilized` — `rule_moveandplace_over_fossilized_cell` /
  `rule_block_moveandplace_over_fossilized_cell`.

### game_screen.clear_action
The fate of the cells a formed word covers when it is applied (clear-on-submit or the
phase-end batch).
- `rule_remove_cells` — the consumed cells leave the board, partial-gram aware (a word
  ending mid-gram leaves the leftover letters) — the original.
- `rule_fossilize_cells` — every cell on the word's path freezes in place: the whole
  cell stays (letters intact) but goes dead — un-swappable, skipped by word-finding
  and the typewriter cursor, tinted stone grey.

### game_screen.cell_overlap_action
What happens to the "old" cells a placement covers. `rule_old_cells_get_delete` treats
them as gone, so a covered starting obstacle (or mission) counts as cleared for the
mission/obstacle victory rules (otherwise covering one strands that victory
condition).

### game_screen.cell_health
Whether starting obstacle / mission cells carry HEALTH: the number of words that must
be spelled through a cell before it clears. `rule_cell_health_off` is the original game
(the first word through a cell clears it) and keeps the whole feature dormant —
`_clear_paths` runs its pre-health path untouched. `rule_cell_health_on` gives each
starting cell the health its per-track rule asks for (`game_screen.obstacle_health` /
`game_screen.mission_health`) and damages it by one per word spelled through it.

A damaged-but-alive cell keeps its gram and its obstacle/mission tint, so it can be
spelled through again — that is how it is chipped down. It only leaves the board (and
only then stops counting toward `rule_victory_obstacles_cleared` /
`rule_victory_missions_cleared`) when its health reaches 0.

Note that one word damages EVERY health-carrying cell on its path, so a word threaded
through two obstacles hits both.

### game_screen.obstacle_health / game_screen.mission_health
How much health each starting cell of that track gets when `cell_health` is on. The two
tracks are configured independently.
- `rule_obstacle_health_one` / `rule_mission_health_one` — 1 health: the first word
  through the cell clears it, exactly as before the feature. The default.
- `rule_obstacle_health_fixed` / `rule_mission_health_fixed` — every cell of that track
  gets the same health, `game_screen.obstacle_health_amount` /
  `game_screen.mission_health_amount` words.

### game_screen.health_word_action
The fate of a word spelled through a target that SURVIVED the hit (a word that destroys
all of its targets always clears normally, through `game_screen.clear_action`).
- `rule_health_word_fossilize` — the word ATTACKS: its player cells fossilize in place
  as that target's ATTACKERS and stay on the board until it falls. The attacker trail is
  a running visible record of how many words the obstacle has absorbed, and — under
  `game_screen.fossil_word_use: rule_fossil_allow` — material the next word can chain
  onto (spell `P`+`INE`, then chain `S`+`P`+`INE`). The target cell itself is never
  fossilized while it lives. The default.
- `rule_health_word_clear` — no attacker trail: the word clears through the normal
  clear-action and the target simply loses a point of health.

### game_screen.obstacle_damage_display (+ damage_fill_opacity)
How a damaged-but-alive obstacle / mission cell shows the hits it has taken. Only ever
shows PARTIAL damage: at full health nothing is drawn, and a cell at zero health has
already left the board. Applies to both tracks despite the name.
- `rule_damage_fill_rising` — the cell fills from the floor up as it is damaged (1 of 3
  hits fills a third, 2 fills two thirds), in `board.damage_fill` (light red) at
  `game_screen.damage_fill_opacity` — a 0–1 fraction, kept translucent so the cell's
  gram still reads through the fill. Shares its machinery with the omniswap sand timers
  (`views/rising_fill.py`), and clips to each cell's own outline, so it works on the
  square, hex and triangle boards — and rises through a jumbo hexagon as one shape
  rather than filling the anchor triangle.
- `rule_damage_border_dashed` — the cell's outline is divided into max-health slots by
  arc length, and one slot is painted per hit in `board.damage_dash`, at
  `game_screen.damage_border_thickness` pixels. The dash COLOR decides how it reads: set
  it to the board background (the default white) and the painted stretches are GAPS, so
  the solid outline visibly breaks apart; set it to red (or any other color) and they are
  colored dashes painted ON the outline instead. Either way the cell's FILL is untouched,
  so the obstacle/mission tint still reads cleanly (unlike the rising fill, which sits on
  top of it). Caveat on the square grid, where neighboring cells share an edge: a slot
  painted over a shared edge marks the neighbor's outline too — harmless on the hex and
  triangle boards, whose cells own their outlines.
- `rule_damage_border_fill` — the same slot scheme, but painting `board.damage_fill` over
  the WHOLE slot instead of part of it, so the outline reddens a slot at a time and stays
  continuous. Reads as a cell heating up rather than cracking apart.
- `rule_damage_display_none` — no indicator; the attacker trail beside the cell is the
  only cue. The pre-feature look.

All of them derive from the cell's own outline (the grid's `cell_vertices`), so they
work on the square, hex and triangle boards, and treat a jumbo hexagon as the one big
shape it is. Only PARTIAL damage ever shows, so a 1-health cell (the default) displays
nothing at all — it goes from untouched to gone in one word.

### game_screen.attacker_release
When an attacking cell WITHDRAWS, for a word whose path crossed SEVERAL damaged targets
(it is committed to all of them). An attacker committed to exactly one target always
leaves when that target falls.
- `rule_attacker_release_when_all_dead` — withdraws only once every target it attacks
  has fallen. The trail stays while any of its obstacles is still being chipped at, so
  the player can keep chaining onto it and never has to think about which obstacle to
  kill first. The default.
- `rule_attacker_release_when_any_dead` — withdraws as soon as any one of its targets
  falls. Opens board space sooner, at the cost of making clear ORDER a strategic
  concern.

Whichever rule applies, the withdrawing cells take their WORD LINES with them when
`game_screen.word_trail` is on — an attacking word's line is drawn against the target it
attacks, so it is dropped rather than left behind on an empty board.

### gram_length.*_percent (length mix)
Length mix for `rule_grams_greater_than_47_lengthcontrolled`: how often that picker
yields a unigram vs digram vs 3+-letter gram. Used ONLY when a `*.gram_pick` slot is
set to `rule_grams_greater_than_47_lengthcontrolled` (it draws from the same JPO
corpus as `rule_grams_greater_than_47`, but these percentages override the corpus's
own length skew). Treated as relative shares, so they need not sum to 100; setting one
to 0 drops that length entirely. Within each length the corpus's frequency weights
still apply.

For the OPENING BOARD these shares are enforced as a quota — the actual
unigram/digram/3+ counts land within ~1 of the configured split, so a board can't come
out trigram-heavy by luck. (The player piece pool just rolls them per piece; it
self-averages over 100+ pieces.)

Keys: `gram_length.unigram_percent`, `gram_length.digram_percent`,
`gram_length.trigramplus_percent`.

### gram_length.unigram_common_percent / unigram_uncommon_percent
Within the OPENING BOARD's unigrams, a second quota splits single letters into two
bins (relative shares, same largest-remainder enforcement as above):
- common glue — E I A T R N O S L C U
- uncommon flavor — P M D G H Y B F V K W Z X J QU

("QU" is the one digram counted as a unigram here, and the only way Q reaches the
board.) Within a bin the corpus's own letter frequencies still apply, so glue draws
lean E/I/A and flavor draws lean P/M/D over Z/X/J. Applies to the opening formation
only; the piece pool rolls unigrams from the whole letter set.

### game_screen.formation_vowel_coverage
Guarantee coverage of certain letters among the opening formation's UNIGRAM cells. The
picker draws unigrams normally (weighted, under the common/uncommon quota) and only
FORCES a still-missing required letter into the final unigram slots — so a forced
letter perturbs the distribution by at most the missing count (often zero, as A/E/I/O/U
are common glue and usually appear on their own; Y is the typical force). A forced
letter is tallied into its own common/uncommon bin so that quota stays honest. Needs
the length-controlled picker + a fill formation (the same dependency as the length
arrangements); a no-op otherwise.
- `rule_vowel_coverage_off` — no guarantee (the picker decides everything).
- `rule_vowel_coverage_each_unigram` — at least one of each vowel A E I O U Y.

NOTE: the diagonal-vs-random length arrangement of the uniform fill is no longer a
separate key — it is picked via `game_screen.setup_formation`
(`rule_formation_fill_player_diagonal` = diagonal,
`rule_formation_fill_player_random` = scattered). Both place the SAME
unigram/digram/3+ counts (the `gram_length.*` quota) and only differ in WHERE each
length lands; both require the length-controlled picker to have lengths to arrange.

### game_screen.loading_fade_glyphs_category
How the opening reveal (LOADING fade-in) groups each cell's GLYPH (letter) into fade
categories. This is the **glyph axis** — it governs EVERY cell's letter, ordinary or
special. It is independent of the **background axis**: a cell's kind (mission /
obstacle / fossilized) drives its FILL fade on a `<kind>_background` dial, not its
letter. So a fossilized single letter fades on this scheme's `uni_glyph` bucket while
its gray fill reveals separately (and can land last) on `fossilized_background`. This
is where the fossilized-vs-unigram precedence is resolved: the glyph always follows
the active glyph scheme; only `rule_loading_fade_by_category_glyph` makes the letter
follow the cell's kind. Category names carry a `_glyph` suffix (the fill dials carry
`_background`) so each dial states which part of the cell it fades. Each scheme's
category names have their own delay/duration slots in `assets/loading_animation.yaml`
(tune timing there).
- `rule_loading_fade_by_length_glyph` — by gram length: settled_3plus_glyph /
  settled_2_glyph / settled_1_glyph (the original reveal; pairs with the diagonal
  length arrangement).
- `rule_loading_fade_by_ideation_strength_glyph` — by cleaned3 strength: strong_glyph
  vs not_strong_glyph (m/n/ungraded). Reveals the strong-ideation grams first/separately.
- `rule_loading_fade_by_ideation_fix_glyph` — by cleaned3 *fix: prefix_glyph /
  suffix_glyph / midfix_glyph / no_fix_glyph (priority prefix > suffix > midfix). Pairs
  with the side-pane formations.
- `rule_loading_fade_by_ideation_length_strength_fix_glyph` — COMPOSITE: all three axes
  nested, e.g. tri_strong_pre_glyph, tri_strong_mid_glyph, … di_weak_suf_glyph, then
  uni_glyph. 16 multigram buckets ({tri|di}_{strong|weak}_{pre|mid|suf|nofix}) + uni;
  order them via their delay slots in `loading_animation.yaml`.
- `rule_loading_fade_by_category_glyph` — by cell KIND: mission_glyph / obstacle_glyph
  / fossilized_glyph for special cells, else a single settled_glyph for every plain
  letter. The one scheme where a cell's kind times its letter.

Note: only the special cells' BACKGROUND fills have their own dials today
(`mission_background` / `obstacle_background` / `fossilized_background`); a plain cell's
(white) fill just rides with its glyph. A full parallel `loading_fade_backgrounds_category`
for every cell is deferred until it's needed.

### game_screen.ideation_formation (+ gram_ideation.*)
Ideation-strength formation steering. When ON, the opening board's DIGRAM and TRIGRAM+
cells (the lengths the arrangement already placed) are steered toward the gram ideation
profile graded in `jpo_allGramsGreaterThan47InFreq_cleaned3.csv` (the
strong/prefix/midfix/suffix columns). Each percentage is an INDEPENDENT target: the
share of that length's cells whose gram is graded 'y' for that attribute.

Only 'y' counts toward a percentage — 'm' and 'n' are both treated as NOT having the
attribute (so `strong_percent: 50` means ~50% graded y-strong, and the other ~50% are
the m's and n's lumped together, not just the n's). Targets OVERLAP and need not sum to
100 — one gram can be strong AND prefix AND suffix. Steering is greedy
(largest-remainder toward the most under-filled attribute each draw), so it approaches
the targets but may overshoot an attribute that's naturally common in the corpus.
Within a steered draw the corpus frequency weights still apply. Two separate rule sets,
digram and trigram+; UNIGRAM cells are never steered. OFF = draw each length's gram by
plain corpus frequency (the pre-ideation behavior).

Requires the length-controlled picker (`rule_grams_greater_than_47_lengthcontrolled`)
+ `rule_formation_fill_player_diagonal` / `_random`; otherwise it has no effect.

Keys: `game_screen.ideation_formation` (`rule_ideation_formation_on` / `_off`);
`gram_ideation.digram.{strong,prefix,midfix,suffix}_percent`;
`gram_ideation.trigramplus.{strong,prefix,midfix,suffix}_percent`.

### *_player / *_obstacle / *_mission .gram_pick
Which gram-picking rule each cell class uses. `square_*` and `hex_*` are separate;
obstacles and missions have their own picks so they can differ from the playable
pieces (e.g. unigram dominos as obstacles). The hex player pick also governs the
initial board formation cells. Options:
- `rule_scrabble_distribution` — Scrabble letter weights.
- `rule_scrabble_with_allvowelswild` — Scrabble weights, but vowels become wild cells.
- `rule_random_letters`
- `rule_englishcorpus_random_unigram` / `rule_englishcorpus_random_digram`
- `rule_grams_greater_than_47` — draw from the JPO corpus (grams appearing >47× in
  frequency).
- `rule_grams_greater_than_47_lengthcontrolled` — same corpus, but length mix driven by
  `gram_length.*_percent` (see above).
- `rule_mixed_scrabble_digram52` / `rule_digram52_distribution`
- `rule_trigram_equalweight` — every trigram in `jpo_5.2.2_trigrams.csv`, equal odds.

### *_player / *_obstacle / *_mission .piece_set
Which piece shapes a cell class draws.
- Square: `rule_use_tetriminos`, `rule_use_dominos`, `rule_use_unimos`.
- Hex: `rule_use_hex_dominos`, `rule_use_hex_unimos`.
- Triangle: `rule_use_triangle_dominos`, `rule_use_triangle_unimos`,
  `rule_use_triangle_hexagons`, `rule_use_triangle_unimos_and_dominos`,
  `rule_use_triangle_unimos_dominos_hexagons`. A triangle domino is two triangles
  sharing an edge (a rhombus); it has three rotation states, not four or six. A
  triangle hexagon is the six triangles meeting at one vertex — a regular hexagon
  six cells (so six letters) in size, and rotation-symmetric, so turning it is a
  visual no-op. The two combined rules deal several shapes from one pool, mixed by
  `piece_pool.order`; the single-shape rules ignore that knob.
- Triangle JUMBO CELLS: `rule_use_triangle_jumbos`,
  `rule_use_triangle_unimos_dominos_jumbos`. A *jumbo* is one cell whose shape
  spans several grid coordinates — the board's first cell bigger than a grid
  coordinate. The only jumbo so far is `JUMBO_HEX`, which covers the same six
  triangles as the hexagon piece but is ONE cell holding ONE gram. It deliberately
  spends six coordinates on a single gram and gets six edge-neighbors for it
  (twice a triangle's three), so it plays as a hub words route through. It counts
  as one cell everywhere — one node in a word path, one for the min-cell rules,
  one for scoring — and clears whole, freeing all six coordinates. Its gram may be
  any length; the cell has room for a multigram. See `models/triangle_jumbo.py`,
  the footprint layer in `TriangleGrid` (`place_jumbo` / `resolve` / `footprint`),
  and `_rule_triangle_movement_jumbo` for why it moves on the hex lattice.
  (Named "hexcell" / "large cell" before 2026-08-11; renamed throughout so a
  future non-hexagonal big cell fits the same vocabulary.)

### piece_pool.order
For piece sets that have multiple shapes, how to manage the distribution of shapes.
- `rule_create_shuffled_roundrobin`, `rule_create_pure_random`,
  `rule_create_fixed_roundrobin`, `rule_create_random_even_distribution`.

### game_screen.spell_suggest
Which "did you mean?" engine runs when a submitted word is not in the dictionary. The
constrained matcher (`models/spell_check.py`) only offers close, same-C/V-shape
misspellings so the player can't farm it for unknown words; `_constrained_morpheme`
ALSO offers wrong-affix words (`models/morpheme_check.py`, e.g. ABSOLUTIONIST →
ABSOLUTION), merged under the same `max_suggestions` cap; `_off` disables suggestions
entirely. Tunables live in the top-level `spell_check:` and `morpheme_check:` blocks.
- `rule_spell_suggest_constrained_morpheme`, `rule_spell_suggest_constrained`,
  `rule_spell_suggest_off`.

---

## spell_check (tunables)

Live in `assets/spell_check.yaml` (folded into CONFIG by `config.py`), not
`config.yaml`; only the `game_screen.spell_suggest` enable/disable knob stays there.

Spelling-suggestion weights for `rule_spell_suggest_constrained` — the restricted
edit-distance matcher (`models/spell_check.py`).
- `exoticness` = sum of the per-change weights below; used only to RANK results.
- `edits` = the Damerau edit count; the only hard GATE, capped per word at
  `max(base_distance, vowel_runs * distance_per_vowel_run)`.

| key | meaning |
| --- | --- |
| `min_word_length` | only suggest for typed words this long or longer |
| `max_suggestions` | most "did you mean?" words to show |
| `base_distance` | edit-distance floor of the per-word cap |
| `distance_per_vowel_run` | +this to the cap for each vowel run in the word |
| `max_transpositions` | consonant+vowel letter swaps allowed (e.g. RE↔ER) |
| `max_length_delta` | scan pre-filter: skip dict words this much longer/shorter |
| `obscurity_extra_score` | exoticness added to a suggestion valid ONLY via the obscure tier (`dictionary.include_obscure`), so a rare "did you mean?" ranks below an equally-close common word. Applied to both the letter- and morpheme-level scans; 0 (or obscure tier off) means no surcharge. See `obscurity_surcharge()`. |

**Vowel-run change weights** (`vowel:`) — a wrong vowel / diphthong:
`single_to_diphthong` (A→AU), `diphthong_to_single` (AU→A), `diphthong_swap_one`
(EA→EE), `diphthong_reverse` (IE→EI), `single_swap` (A→E), `silent_e` (WORD→WORDE, add
a silent E at the end).

**Consonant-run change weights** (`consonant:`): `csk_class` (C/S/K/CK/SC), `gj_class`
(G/J), `td_class` (T/D), `zs_class` (Z/S), `dup` (D→DD), `dedup` (DD→D), `suffix_swap`
(T/S/C/SH confusion in a -TION/-SION/-OUS ending).

**Adjacent consonant+vowel transposition weights** (`transposition:`): `end` — the
final two letters (CENTRE→CENTER); `elsewhere` — anywhere else (PERscripsion→
PREscription).

`suffix_tails` — morpheme tails (the part AFTER the confusable lead consonant) that
license a cheap T/S/C/SH swap. Mined from the 20k dictionary; all end in the N or S
families per the cV+n / cV+s design. Same tail covers TION/SION/CION etc. Current:
`[ION, IOUS, IONAL, IAN, OUS, IENT, IONARY, IONIST, EOUS, IENCY, UOUS]`.

---

## morpheme_check (tunables)

Morpheme-distance suggestions (`models/morpheme_check.py`). Catches MORPHEME-level
slips rather than letter slips: a real stem with the wrong / one-too-many affix
(ABSOLUTIONIST → ABSOLUTION, ABSOLUTIST → ABSOLUTISM, REVISIONIST → REVISION). A word
is PREFIX\* + stem + SUFFIX\*; a correction takes at most ONE action per SLOT (the
prefix end and the suffix end): remove / add / swap an affix.
- `morpheme_distance` = how many slots acted (1 or 2); the hard GATE.
- `exoticness` = summed action cost; RANKING only. Each action has a base score below,
  plus a CLASS surcharge per special morpheme it touches.

So UN-x → DE-x is one prefix_swap (4); UN-x → x-ENCE is a fix_remove (2) + suffix_add
(4) = 6, distance 2. Inventory mined from an old stemming pass.

| key | meaning |
| --- | --- |
| `max_morpheme_distance` | most slots an action may touch (1 = one end only) |
| `fix_remove_score` | remove any affix, either end (UN-x → x) |
| `prefix_add_score` | add a prefix (x → UN-x) |
| `prefix_swap_score` | swap prefix→prefix (UN-x → DE-x) |
| `suffix_add_score` | add a suffix (x → x-MENT) |
| `suffix_swap_score` | swap suffix→suffix (x-ENCE → x-MENT) |

**Class surcharges**, ADDED to the action cost for every special morpheme the action
touches (a swap touches two). Heaviest class wins per morpheme:
`common_inflection_comparative` (7) > `neoclassical` (5) > `compounding` (3).
- `common_inflection_comparative_extra_score` — -s/-ed/-ing/-er "did you mean a
  plural?"
- `compounding_class_extra_score` — free-word affixes (super-, -woman).
- `neoclassical_class_extra_score` — Greek/Latin combining forms (-graphy).

**Inventories.** `prefixes:` / `suffixes:` are the affix inventory. The three surcharge
bins (`common_inflection_comparative`, `compounding`, `neoclassical`) only ADD a
surcharge — a binned affix must ALSO stay in `prefixes:`/`suffixes:` (the bins are not
separate inventories). Hand-tune a bin by moving items in/out of it — membership is all
that matters.
- `common_inflection_comparative` — super-common inflections/comparatives; the
  surcharge sinks "did you mean a plural?" swaps (ABSOLUTIST → ABSOLUTES) to the
  bottom. NOTE: -er/-ers are dual-use (comparative BIGGER vs agent-noun BAKER); drop
  them from this bin if you want agent nouns to rank normally.
- `compounding` — free-word affixes / near-compounds.
- `neoclassical` — Greek/Latin combining forms (heaviest surcharge).
