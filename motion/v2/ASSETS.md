# Asset provenance and generation prompts

The photographic illustrations below were generated with the **built-in ImageGen
tool**. The original outputs were copied into this version's assets directory.
They are illustration plates within a motion composition, not current photos
from a weather provider or Google result captures.

## Mumbai location plate

File: `assets/mumbai.png`.

Exact generation prompt:

> Create a cinematic photographic location plate for the THREAD product film, landscape 16:9. Mumbai Marine Drive at blue hour, looking along the curved seafront with a graceful sweep of warm golden street lights, sea on the left, real dense Mumbai buildings on the right, the Arabian Sea cobalt, deep ink blue sky after monsoon rain. High-end travel editorial photography with physically plausible optics, atmospheric depth, crisp reflections along the waterfront and subdued beautiful city lights. No people in foreground, no text, no logos, no graphics, no interface, no collage. Rich but natural deep blues and tiny warm highlights, never purple neon. Camera at an elevated coastal viewpoint, wide aerial feel without absurd distorted perspective, sophisticated cinematic light. This image will be cropped into animated weather and morning-trip results; strong readable coastline composition with darker negative space in upper sky for type. Generate one detailed photographic illustration, not a UI mockup.

## Cat search illustration

File: `assets/cat.png`.

Exact generation prompt:

> Create one photographic cat image for a premium product film search thumbnail. Landscape 16:9. A charming cream and ginger long-haired cat leaping gracefully across a sunlit pale stone terrace, front paws stretched forward, vividly sharp amber eyes and individual fur detail, beautiful high-end pet editorial photography, captured mid-action with physically believable anatomy. Warm afternoon light, softly blurred sage green garden in the background, tasteful cinematic color. Strong subject separation. No text, no logos, no watermark, no interface or borders. Natural realistic photograph with an engaging sense of motion, not a cartoon.

## Existing identity assets

- THREAD acoustic sphere: `web/images/thread-sphere.png`, retained from the app.
- Manrope variable font: `web/fonts/Manrope.ttf`, licensed under the adjacent OFL.
- Ink, electric blue and pale blue: existing THREAD brand palette.
- All typography, ticket stock, plane paths, checklist controls, graphs, dials,
  home-screen composition and motion are code-native production graphics.

## Public source assets

- IndiGo mark: [Google Flights airline image](https://www.gstatic.com/flights/airline_logos/70px/6E.png).
- Air India mark: [Google Flights airline image](https://www.gstatic.com/flights/airline_logos/70px/AI.png).
- Virat Kohli: [ESPN cricket headshot](https://a.espncdn.com/i/headshots/cricket/players/full/253802.png).
- M87 image: **EHT Collaboration**, via [ESO, First Image of a Black Hole](https://www.eso.org/public/images/eso1907a/).
  [Publication image](https://cdn.eso.org/images/publicationjpg/eso1907a.jpg),
  saved unaltered as `assets/blackhole.jpg`. The film identifies EHT Collaboration.

Airline brands identify demonstration results, with **Sample fares** visible.
No booking, live airline integration or endorsement is claimed.

## Data provenance

- Weather: Open-Meteo, Mumbai, captured **14 September 2026 at 23:45 IST**.
  Exact response and request URL are saved in `assets/weather.json`.
  The film's "Tomorrow" and flight date refer to this capture date.
- Clocks: same 14 September capture moment: Mumbai 23:45 / London 19:15 BST.
- Sports: project captures `reports/profile-virat-kohli.json` and
  `reports/profile-virat-kohli-t20.json`. Cricbuzz source; ODI snapshot 268 runs,
  67.0 average, 111.7 strike rate. T20 snapshot: 296 runs, 98.7 average,
  169.1 strike rate over five returned May 2026 innings. These are neither
  career totals nor a claim of current live form.
- Research paper: [First M87 Event Horizon Telescope Results I](https://doi.org/10.3847/2041-8213/ab0ec7),
  2019, The Astrophysical Journal Letters. Crossref metadata is saved in
  `assets/paper.json`.
- Other research references: [Wikipedia, Black hole](https://en.wikipedia.org/wiki/Black_hole),
  and *A Brief History of Time*, Stephen Hawking, Bantam.
- Flights: clearly labelled sample fares and illustrative carrier combinations.
  Example itinerary and packing list are draft content.

## Audio

Directed synthetic speech: Gemini `gemini-2.5-flash-preview-tts`, Aoede for the
user, Charon for THREAD and the closing signature. The twelve user requests
are cut from a single performance to keep vocal identity consistent. Exact
directions and returned durations are saved beside the takes in `audio/*.json`.
No voice is cloned from a person.

Music and effects: original procedural composition and synthesis in
`soundtrack.py`; 120 BPM, F minor / D-flat / A-flat / E-flat. Separate voice,
music and effects stems are retained. No commercial track was sampled.
