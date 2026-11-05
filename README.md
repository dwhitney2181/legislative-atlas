# U.S. State and Territory Legislature Atlas — 2026 (v1.4.0)

An interactive map and seat list of the 2026 state legislative elections in all 50 states, D.C. and the five inhabited territories (56 jurisdictions, 7,575 seats; 6,223 seats regularly on the 2026 ballot, per NCSL's June 25, 2026 chamber schedules). Results are **unofficial** and partial until canvassed.

## What's new in v1.4.0: runs on its own

- **No server needed.** The atlas is now a plain website: put the files on GitHub Pages (or any static host) and it works. The Python server is optional.
- **Instant clicks.** Every result loads once when the page opens, and every state's district map ships with the site (`geo/`), so choosing a state draws it right away instead of waiting on a server.
- **Results stay current by themselves.** The page reads the published results feed (`atlas-feed.json` in the election-2026 repository) straight from GitHub, so updating that file updates the site. If GitHub can't be reached, it uses the bundled copy, `results_feed.json`. **Update selected** re-reads the feed; auto-refresh re-reads it every 15 minutes.
- **Bundled district maps.** 2022 Census boundaries for all 50 states and Puerto Rico, labeled to match the results feed. Michigan, Wisconsin, Ohio, Georgia, North Carolina, Washington, Montana, North Dakota and New York redrew some districts after 2022: for those, the page first tries Election Wrld's current maps and, if it can't reach them, shows the 2022 lines with a note saying so. New Hampshire's floterial (overlay) districts have no separate shape; their results appear in the seat list.
- Multi-seat districts are colored once every seat in them is reported, even without a member roster.
- **Governors, U.S. Senate and U.S. House.** Switches above the national map show each office (state legislatures, U.S. House, U.S. Senate, governors), each state's view has **Governor**, **U.S. Senate** and **U.S. House** tabs next to its legislative chambers (states without a 2026 legislative election, like Virginia, open on these), and a side panel lists a state's governor, Senate and House races with vote shares, calls and party changes; with no state selected it lists every seat changing party. The data is `atlas-federal.json` from the election-2026 repository (bundled copy: `federal_results.json`), refreshed by the same daily update.
- **Congressional district maps.** The U.S. House tab draws each state's districts, colored by who is ahead, for the 38 states whose 2026 congressional lines are the same as in 2022 (2022 Census boundaries, `geo/cd/`, built by `tools/build_cd.py`). Alabama, California, Florida, Georgia, Louisiana, Missouri, North Carolina, New York, Ohio, Tennessee, Texas and Utah use newer lines in 2026; until their official boundary files are added they show district tiles. Senate and governor tabs show the state outline in the winner's color.
- **The national map is colored.** A switch picks between *Reported winners* (which party won more of the 2026 races reported so far; deeper color = more lopsided and more races in) and *Seats that changed party* (net gains). Neither is chamber control: seats not on the ballot and uncalled races aren't counted. Hover or tap a state for its numbers.

## v1.3.0

- **Every state loads on open.** The page now pulls one nationwide results feed when it starts (`GET /api/results-all`), so a first-time visitor sees reported winners and flips for every state that has them, not only Utah.
- **Nationwide results feed.** The server reads `atlas-feed.json` from the [election-2026](https://github.com/dwhitney2181/election-2026) repository (MultiState reported winners for 45 states, plus Utah vote counts). A dated copy, `results_feed.json`, ships with the app and is used automatically if GitHub can't be reached.
- **The feed no longer replaces the other sources.** Previously, setting `ATLAS_RESULTS_FEED_URL` switched off MultiState, civicAPI, the curated rows and the territory seeds, and any state missing from the feed returned an error. Now the feed is merged with them.
- **Utah always has data.** If every source fails, Utah falls back to its bundled November 4 snapshot, the same way Guam and the Virgin Islands already did.
- States with no regular legislative election in 2026 (Louisiana, Mississippi, New Jersey, Virginia, Puerto Rico and others) now return an empty result with a notice instead of an error.
- South Dakota's two-member House districts are no longer read as single-seat races from MultiState.

Earlier fixes still apply: the Utah House 41 correction (John Arthur, D), restored terminal logging (v1.2.3), the flip-counter repair (v1.2.2) and the bundled territory outlines with the Guam and Virgin Islands slates (v1.2.5).

## Run it

**As a website (recommended):** turn on GitHub Pages for this repository (Settings → Pages → Deploy from a branch → `main`, `/ (root)`). The site appears at `https://<username>.github.io/legislative-atlas/`. Nothing else is needed.

**On your computer:** open a terminal in this folder and run `python3 -m http.server 8000`, then browse to http://localhost:8000. (Opening `index.html` by double-clicking won't load the maps, because browsers block local file reads.)

**With the optional server:** `python3 -u live_server.py`, then http://127.0.0.1:8766. The server adds live MultiState and civicAPI checks for the selected state every 3 minutes, and a member-roster cache. `render.yaml` and the `Dockerfile` deploy it to Render's free plan (see `START_HERE.md`).

### Server settings (environment variables; only used by `live_server.py`)

| Variable | Default | Purpose |
|---|---|---|
| `ATLAS_RESULTS_FEED_URL` | the election-2026 `atlas-feed.json` raw URL | Nationwide results feed. Set to another JSON/CSV URL to override, or `off` to disable. |
| `ATLAS_MULTISTATE_ENABLE` | `1` | Check MultiState's results page for the selected state. |
| `ATLAS_CIVIC_ENABLE` | `1` | Check civicAPI vote counts for the selected state. |
| `ATLAS_DATA_DIR` | `./runtime` | Where observed snapshots are saved. Optional; on Render Free this storage is wiped on restart. |
| `HOST`, `PORT` | `127.0.0.1`, `8766` | Where the server listens. |

### API

- `/api/results-all`: every known result, all jurisdictions (used for the first page load).
- `/api/results?state=WI`: one jurisdiction, merging the feed, MultiState, civicAPI, curated rows and seeds.
- `/api/coverage`: how many records each jurisdiction has.
- `/api/multistate?state=WI`, `/api/geo?state=WI`, `/api/national-geo`, `/api/roster?state=WI`, `/api/health`.

### Feed row format

JSON (`{"races": [...]}`) or CSV with columns
`state,chamber,district,seat,candidate,party,status,previous_party,votes,reporting,updated,source,source_kind,source_url,multimember`.
`chamber` is `upper` or `lower` (Nebraska's unicameral legislature is `upper`); `party` is one of `R, D, F, I, O, N`. The same format works with the page's **Import results** button.

## Data and source semantics

- `leading`: votes counted so far favor a candidate; no call implied.
- `reported`: MultiState or another publisher explicitly records a winner; not an official certification or an independent AP call.
- `called`: an explicit call from a named source.
- `certified`: official canvass only.
- `holdover`: a current legislator whose seat was not on the 2026 ballot; not a 2026 result.
- Races without a reported winner are left out. Missing data never becomes zero votes, a projected winner or an inferred party color.
- Flips count only where the previous seat holder's party is known: an explicit "Flipped X to Y" note from the source, or, for Utah, the documented pre-election holder. A vacant seat, or a new member of the same party, is not a flip.
- Districts that elect several members on one ballot (New Hampshire, Vermont, Arizona, North Dakota, South Dakota, parts of Maryland) are listed one row per winner and marked `multimember`; they are not counted in the flips table, because the source doesn't say which seat changed hands. Multi-winner rows whose winners belong to different parties are skipped for the same reason.
- Washington and Idaho elect each House position separately; the feed numbers them in the order MultiState lists them.
- National shading reflects reported 2026 races only, and fades when few races are reported, so a handful of results never paints a whole state solid red or blue.

## Updating the data

- **Results:** the feed is built by `tools/build_atlas_feed.py` in the election-2026 repository. Re-run it after updating that repository's results files and push; open atlas pages pick it up at their next refresh (GitHub may take up to 5 minutes to serve the new file). To refresh the bundled fallback copy here, copy `atlas-feed.json` over `results_feed.json`.
- **Maps:** `tools/build_geo.py` rebuilds `geo/` from the Census files (instructions at the top of the script).

## Sources and limits

Sources and limits are described in `source-policy.html`: NCSL, U.S. Census geographic files, MultiState, Election Wrld, civicAPI and the local news outlets named in each record. District maps ship with the site (2022 Census cartographic boundaries); member rosters, when available, come from Election Wrld. Some 2026 district boundaries may differ from the Census files. Check results against the linked sources before relying on them.

The server is a single Python process and has not been load-tested for heavy public traffic.
