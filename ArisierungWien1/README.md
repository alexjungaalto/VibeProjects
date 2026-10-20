# Geraubte Häuser — NS-Vermögensentzug im 1. Wiener Gemeindebezirk

A map of documented Nazi-era property dispossession in Vienna's Innere Stadt,
built only from sources that can be cited line by line.

    make all        # full pipeline (first run ~30 min, mostly the wiki scan)
    make serve      # http://localhost:8111
    ./deploy.sh     # publish to dictionaryofml.org/geraubte-haeuser

## What the map shows

| layer | n | what it is |
|---|---|---|
| Liegenschaft, Gebäude | 10 | a house whose seizure is described on its own page |
| Betrieb, Geschäft, Verein | 40 | a business — shop, café, pharmacy, publisher, cinema |
| Person | 21 | a biography documenting dispossession, pinned to that person's 1st-district address |
| Gedenkzeichen | 10 | a memorial recording a Sammelwohnung at that building |
| Täter- und Profiteursorte | 11 | the other side: the VVSt liquidator's office, banks that financed "Ariseure" |
| Letzte Wohnadressen Ermordeter | 623 | Memento Wien: 5,015 murdered residents |

Every entry quotes the sentence that supports it and links to its source.

## The honest caveat

**This is a lower bound, and a distant one.** There is no open register of
"aryanized" property. The authoritative sources are archival:

- **Vermögensanmeldungen 1938** — the compulsory asset declarations (~47,800
  files, Österreichisches Staatsarchiv). Online only as per-person lookup
  behind registration at [findbuch.at](https://www.findbuch.at/property-notices).
- **Melinz/Hödl**, [„Jüdisches" Liegenschaftseigentum in Wien](https://hiko.univie.ac.at/PDF/13.pdf)
  (Historikerkommission) — reconstructed **670 properties** from the land
  registry across 8 districts, **53 of them in the 1st**. The addresses are not
  in the study; the database sits in the ÖStA.

This map finds fewer than those 53 houses. It shows what is *publicly
documented*, not what happened.

The **Person** layer is the weakest: the pin is the person's 1st-district
address, while the property taken from them may have been elsewhere. The quote
in each popup says which.

## Sources

- **[Wien Geschichte Wiki](https://www.geschichtewiki.wien.gv.at/)** (Wiener
  Stadt- und Landesarchiv) — the systematic house history of the Innere Stadt.
  All 5,450 of its 1st-district pages are scanned sentence by sentence.
  Coordinates come from the wiki's own Semantic MediaWiki properties.
- **[Memento Wien](https://www.memento.wien/)** (DÖW) — last residential
  addresses of victims. **This is not ownership**: most were tenants. It is a
  separate layer and never merged with the property data.

## Pipeline

| script | does |
|---|---|
| `00_enumerate_titles.py` | all 63,463 main-namespace titles via `list=allpages` |
| `02_fetch_memento.py` | Memento Wien GeoJSON → 623 1st-district addresses |
| `03_fetch_wikitext.py` | scans the whole wiki, keeps the 5,450 `Bezirk=1` pages |
| `04_classify.py` | sentence-level evidence, classification, quoting |
| `05_coordinates.py` | coordinates per page via `browsebysubject` |
| `06_build_site.py` | merges everything into `docs/data/map_data.json` |

All steps are cached and resumable.

## Traps found the hard way

Each of these produced visible, plausible-looking false entries:

- **`arisier` matches inside ordinary German words.** Sekul*arisier*ung,
  Invent*arisier*ung, Popul*arisier*ung, Milit*arisier*ung, Solid*arisier*ung.
  Without `\b` the Augustinian friars' 1812 dissolution and the National
  Library's 16th-century cataloguing both became "Aryanizations". Same bug made
  Adolf Loos a perpetrator via "popul*arisierte das*".
- **Austrian state property is not Jewish property.** Dozens of 1st-district
  government buildings passed to the Reichsfinanzverwaltung under the
  **Ostmarkgesetz 1941** and returned to the Republic in 1946. Matching
  "Reichsfinanzverwaltung" alone turned the Dicasterialgebäude and Herrengasse
  23 into robbed houses. The Jewish-specific instrument is the **11. Verordnung
  zum Reichsbürgergesetz**; the *5th* VO barred Jewish lawyers from practising
  and is about professions, not property.
- **Bibliographies.** `== Literatur ==` is full of titles like "Ökonomie der
  Arisierung". Apparatus sections are stripped before scanning.
- **German dates break naive sentence splitting.** `"der 11. Verordnung"` and
  `"vom 25. November 1941"` split after `11.` and `25.`, shredding exactly the
  clauses carrying the evidence. Ordinals and abbreviations are guarded.
- **Taking ≠ taking property.** A *Lehrbefugnis*, a medical registration or a
  *Lebensgrundlage* being "entzogen" is persecution, not real estate.
- **`profitierte` is an everyday word** — it made a profiteer of a suburb that
  profited from a railway. **`Schätzmeister`** also means a picture appraiser,
  including in the 1800s.
- **Mentioning the Vugesta makes you its victim**, not a perpetrator.
- **Semantic MediaWiki `ask` silently truncates.** `[[Bezirk::1]]` stopped
  yielding new subjects past offset ~10000 and returned 3,567 pages while
  missing Kärntner Straße 10. `list=allpages` found 5,450.
- **One page, many addresses.** Taking the first coordinate put Peter Altenberg
  in the 2nd district. The fix is to select the subobject whose `Bezirk` is 1,
  then fall back to the wiki's own `Adresse:` page.
