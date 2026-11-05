## v1.2.4 — Utah House 41 integrity fix

John Arthur (D), not Darren Croft (R), led Utah House District 41 in the November 4 general-election reports. The updated client/server repairs a known incorrect cached candidate without clearing other jurisdictions or imports. The correction is a dated unofficial snapshot, not a certified result. civicAPI records must now explicitly identify the November 3 general election or provide matching date metadata; ambiguous race details are omitted, which can reduce automatic coverage. See CHANGELOG_v1_2_4.txt.

## v1.2.3 — Terminal logging restored

The national server previously suppressed all HTTP activity. This version restores concise per-request logs and adds result-source status, provider warnings, and stale/cache labels. Run `python3 -u live_server.py` and keep Chrome open to enable the selected-state 3-minute refresh. This is an observability fix, not a new election data source.

## v1.2.2 — November 4, 2026: flip counter repair

Fixed a regression where a live feed with no `previous_party` field erased the ability to identify party flips. For Utah, the pre-election baseline captured with the November 4 snapshot is preserved even if the results are replaced or a legacy browser cache supplies an unknown previous party. No generic up-to-date roster is treated as a verified 2026 pre-election baseline for other states. The "Flips only" filter now makes its behavior explicit in the table description. Existing local server and user imports are retained. Utah seed: 17 apparent House flips, 2 apparent Senate flips (provisional snapshot; not certified).

# U.S. State and Territory Legislature Atlas — 2026 (v1.2 beta)

**Scope:** 50 U.S. states, the District of Columbia and the five inhabited territories (56 jurisdictions; 7,575 legislative seats). Scheduled 2026 contests: 6,139 **state** seats and 84 in D.C./territorial legislatures according to the jurisdiction inventory built from NCSL's June 25, 2026 chamber schedules. Special-election coverage is not included in these baseline counts.

**Important:** This release is an interactive **incomplete** election results atlas, **not** a nationwide live results declaration. It ships with a dated Utah November 4 morning snapshot (90 2026 election leaders/results and 14 Senate holdovers). Other jurisdictions do not ship with 2026 winners. Remote MultiState and civicAPI integrations are best-effort and have *not* been validated end-to-end from this offline build environment.

## Start

- Open `index.html` for the browser-only dashboard. It shows jurisdiction inventory, all Utah snapshot records, available external map geometry and local CSV/JSON imports. Opening the HTML alone does not create a live nationwide result stream.
- For automatic updates, run `python live_server.py` and open <http://127.0.0.1:8766>. Results are attributed per seat, and only explicit source records are accepted. `GET /api/coverage` shows which jurisdiction result records are currently available.
- To test the upstream publishers from an environment with internet, run `python tools/probe_sources.py UT TX` and compare the returned races against the publisher and official election office. Blank/missing contests remain unknown.
- To save source-verified news rows for *all visitors*, run `python tools/import_verified.py checked_results.csv`. See [DEPLOYMENT.md](DEPLOYMENT.md).

## Data and source semantics

- `leading`: votes counted so far favor a candidate; no call implied.
- `reported`: MultiState/publisher explicitly records a winner; not equivalent to official certification or an independent AP call.
- `called`: direct, verifiable explicit call from a known source.
- `certified`: official canvass/certification only.
- `holdover`: current legislator whose seat was not regularly on the 2026 ballot; not a 2026 result.
- Unavailable source data do not become zeros, projected winners, or inferred party colors.
- Flips count only results with a known, verified party of the previous seat holder. A vacant seat or replacement of a same-party incumbent does not count as a flip.
- Multi-member districts require a *unique seat identifier* for each winner before individual seat-level flip math is permitted. A partially reported multi-member district stays neutral on the map.
- Party color for **Independent American Party** is now the other/minor-party category, rather than unaffiliated/independent. Utah Forward retains a distinct purple color. Local territory parties use `O`, but their original label should be preserved in source evidence.
- National state-level shading stays neutral unless a full, distinct seat roster is loaded. A handful of results must not make a whole state red or blue.
- 2026 pre-election baselines **must be frozen** and verified; a current member roster retrieved after future swearing-in dates is not automatically trusted for retrospective flip math.

## Source attribution

Sources and limits are described in `source-policy.html`, including NCSL, U.S. Census geographic files, MultiState, Election Wrld and civicAPI. Data may be stale or incomplete. Third-party reuse must follow source licensing/usage policies. External geography is Census-derived; some 2026 enacted district boundaries may differ. A neutral tile is a fallback *inventory*, not a geographic polygon.

## Deployment and validation

See `DEPLOYMENT.md` for the Dockerfile, Render Blueprint, optional persistent volume, news-import workflow, and launch acceptance criteria. The included Python server is a simple single-process application; do not assume it has been load-tested or hardened for a high-traffic public launch. Caches persist to `ATLAS_DATA_DIR` when writable; if the source goes down it can serve the last observed record (labeled stale), never a fabricated update.

Commands:

```bash
python -m pytest -q tests
python test_sources.py
python check_ui.py
python tools/audit_coverage.py --csv coverage.csv
```

Release testing: unit tests for result validation, seat identity, MultiState table parsing, source precedence and persistent outage fallback; Playwright browser tests for multi-member districts, neutral-state map, preserved Utah baseline, 50-state scan UI and no browser JS errors. **Not verified in this sandbox:** actual external 2026 feeds, every real GIS provider response, publisher-licensed distribution, territory-specific sources, Render service deployment or public-server scaling.


## v1.2.5: Territory maps and Guam reported slate

See TERRITORIES_README.md. All island territory maps are locally bundled and will load without network requests. See the sidebar seat list for candidate results; these neutral island shapes are **not legislative district maps**. Guam's 15 reported at-large leaders are included with dated local news attribution and no invented individual flips.


## v1.2.5 local installation

No hosting is required. Run `python3 -u live_server.py` on your Mac from the folder containing `index.html`, and browse to `http://127.0.0.1:8766`. Run Ctrl+C to stop.

The geographic coastlines for the five inhabited island territories and a DC outline are bundled locally; they are **not voting-district maps**. Guam's 15-seat Nov. 4 unofficial slate and USVI's Nov. 3 unofficial top-15 reported slate are also bundled with source metadata. **Those territory snapshots do not live-update automatically** until territory-specific official feed parsers are added. Use CSV/JSON imports for verified newer territory returns. Full nationwide coverage remains incomplete.
