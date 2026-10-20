# Full pipeline. Steps are resumable and cached; `make all` is safe to re-run.
PY := python3

all: docs/data/map_data.json

data/all_titles.json:
	$(PY) scripts/00_enumerate_titles.py

data/wikitext.json: data/all_titles.json
	$(PY) scripts/03_fetch_wikitext.py

data/memento_bezirk1.json:
	$(PY) scripts/02_fetch_memento.py

data/classified.json: data/wikitext.json scripts/04_classify.py
	$(PY) scripts/04_classify.py

data/coordinates.json: data/classified.json
	$(PY) scripts/05_coordinates.py

docs/data/map_data.json: data/classified.json data/coordinates.json data/memento_bezirk1.json
	$(PY) scripts/06_build_site.py

verify: docs/data/map_data.json
	$(PY) scripts/07_verify.py

serve: docs/data/map_data.json
	cd docs && $(PY) -m http.server 8111

clean:
	rm -rf docs/data data/classified.json data/candidates.json data/coordinates.json

.PHONY: all serve clean verify
