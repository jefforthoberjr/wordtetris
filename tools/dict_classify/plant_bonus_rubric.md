# Plant Bonus Classification Rubric

You classify single English words for a plant-themed word-game bonus.
For each input word, assign exactly one tier:

- **3** — the word IS a plant, or a specific type/kind/name of plant: trees,
  flowers, shrubs, grasses, vines, mosses, ferns, fungi, crops, and species or
  variety names. Examples: OAK, BAMBOO, FERN, ROSE, IVY, MOSS, WHEAT, CACTUS,
  ORCHID, MAPLE.

- **2** — the word is plant-RELATED but is not itself a plant. Keep this tier
  GENEROUS/LOOSE. It includes:
    - plant parts: LEAF, ROOT, STEM, SEED, PETAL, BARK, BUD, THORN, SAP
    - growth / gardening actions & concepts: GROW, BLOOM, SPROUT, PRUNE,
      HARVEST, PLANT, WATER, WILT, PHOTOSYNTHESIS, POLLINATE
    - growing materials & places: SOIL, DIRT, GARDEN, GREENHOUSE, COMPOST,
      MULCH, ORCHARD, MEADOW

- **1** — everything else; no clear plant connection.

Rules:
- One tier per word. When genuinely torn between two tiers, pick the higher
  plant tier only if a normal player would immediately associate the word with
  plants; otherwise default down.
- Do not invent or reorder words. Classify exactly the words given, in order.

Output format: CSV, one row per word, `word,tier` — no header, no extra text.
