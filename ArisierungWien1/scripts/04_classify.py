#!/usr/bin/env python3
"""Find, classify and quote Nazi-era property dispossession in Bezirk-1 pages.

Evidence is judged PER SENTENCE, not per page. A page-level keyword scan
produced four systematic false-positive classes, all of which are now handled:

 1. Bibliography-only hits. "Ulrike Felber: Arisierung und Liquidierung von
    Betrieben ..." in a == Literatur == section is a citation, not a fact about
    the building. -> apparatus sections are stripped before scanning.

 2. Austrian STATE property taken by the Reich. Many Bezirk-1 government
    buildings passed to the "Reichsfinanzverwaltung des Deutschen Reiches"
    under the Ostmarkgesetz 1941 and back to the Republic in 1946. That is a
    transfer between states, not theft from Jewish owners. -> STATE markers
    veto a sentence. The Jewish-specific instrument is the 11. Verordnung zum
    Reichsbuergergesetz (1941), which is kept as strong evidence.

 3. Wrong century. The Burgkapelle page describes Jewish gravestones reused
    after the Geserah of 1420/21. -> sentences naming a pre-1900 year are
    vetoed, and Nazi-era context is required in the sentence window.

 4. Perpetrators and profiteers. Banks that financed "Ariseure", the Dorotheum
    auctioning victims' belongings, a Kaffeesieder valuing cafes for forced
    sale. These are historically important but they are not robbed property.
    -> detected separately and surfaced as their own layer.
"""
import json, re, unicodedata, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKITEXT = ROOT / "data" / "wikitext.json"
OUT = ROOT / "data" / "classified.json"
CAND = ROOT / "data" / "candidates.json"
REPORT = ROOT / "data" / "classification_report.txt"

# ---------------------------------------------------------------- wikitext ---

APPARATUS = re.compile(
    r"^=+\s*(Literatur|Quellen?|Weblinks?|Links?|Einzelnachweise|Siehe auch|"
    r"Nachweise|Bibliographie|Videos?|Bilder)\s*=+\s*$.*?(?=^=+[^=]|\Z)",
    re.M | re.S | re.I)
TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
REF_RE = re.compile(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", re.S)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
TAG_RE = re.compile(r"<[^>]+>")
HEADING_RE = re.compile(r"^=+.*?=+\s*$", re.M)
FILE_RE = re.compile(r"\[\[(?:Datei|File|Bild):[^\]]*\]\]", re.I)
FILE_OPEN = re.compile(r"\[\[(?:Datei|File|Bild):", re.I)


def strip_files(text):
    """Remove [[Datei:...]] blocks, including captions containing links.

    A non-greedy [^\]]* stops at the first "]", so a caption like
      [[Datei:x.jpg|thumb|Vermoegensentzug von "[[Zwieback & Bruder]]": ...]]
    was left half-standing and its caption became a quotable "sentence" - which
    put a fact about Zwieback & Bruder onto the Handelsgericht's page. Captions
    are not body prose and are dropped whole.
    """
    out, i = [], 0
    while True:
        m = FILE_OPEN.search(text, i)
        if not m:
            out.append(text[i:])
            return "".join(out)
        out.append(text[i:m.start()])
        depth, j = 1, m.end()
        while j < len(text) and depth:
            if text.startswith("[[", j):
                depth += 1; j += 2
            elif text.startswith("]]", j):
                depth -= 1; j += 2
            else:
                j += 1
        i = j


def plain(text):
    text = COMMENT_RE.sub(" ", text)
    text = REF_RE.sub(" ", text)
    text = APPARATUS.sub(" ", text)          # drop Literatur/Weblinks/...
    text = re.sub(r"<gallery[^>]*>.*?</gallery>", " ", text, flags=re.S | re.I)
    text = strip_files(text)
    # image captions survive as "...|thumb|Text]]" fragments and read as
    # mangled sentences in a popup
    text = re.sub(r"^[^\n]*\|(thumb|mini|rahmenlos|\d+px)\|[^\n]*$", " ",
                  text, flags=re.M | re.I)
    for _ in range(6):
        new = TEMPLATE_RE.sub(" ", text)
        if new == text:
            break
        text = new
    text = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", text)
    text = text.replace("[[", " ").replace("]]", " ")   # any leftovers
    text = TAG_RE.sub(" ", text)
    text = HEADING_RE.sub(" ", text)
    text = text.replace("'''", "").replace("''", "")
    text = re.sub(r"^[*#:;]+", " ", text, flags=re.M)
    return re.sub(r"[ \t]+", " ", text).strip()


def fold(s):
    s = s.lower().replace("ß", "ss")
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


# German ordinals and dates ("der 11. Verordnung", "vom 25. November 1941")
# and common abbreviations must not end a sentence - naive splitting shredded
# exactly the clauses that carry the evidence.
SENT_GUARD = re.compile(
    r"(\d\.)(?=\s)"                                   # 11.  25.
    r"|((?:Nr|Dr|Prof|Hg|Bd|S|St|bzw|ca|vgl|ehem|geb|gest|urspr|Jh|Abs|Art"
    r"|lit|Mag|Ing|Univ|Sen|jun|sen|evtl|ggf|z|B|u|a|d|h|i|O)\.)(?=\s)")
SENTINEL = "\u0001"


def sentences(text):
    text = re.sub(r"\n+", " \n ", text)
    guarded = SENT_GUARD.sub(lambda m: m.group(0).replace(".", SENTINEL), text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ\"„])|\n", guarded)
    out = []
    for part in parts:
        part = part.replace(SENTINEL, ".").strip()
        if len(part) > 15:
            out.append(part)
    return out


# --------------------------------------------------------------- vocabulary ---

# Evidence comes in two tiers.
#
# SELF_SUFFICIENT: instruments that were Jewish-specific by definition, so the
# sentence needs no separate victim marker. "Arisierung" MEANS expropriation
# from Jewish owners; the Vermoegensverkehrsstelle and the Vugesta existed for
# nothing else; the Verordnung zum Reichsbuergergesetz stripped emigrated Jews
# of citizenship and property. Requiring a second "juedisch" in the same
# sentence lost real cases - house pages state the fact without re-explaining
# it ("1938 \"Arisierung\" durch die nationalsozialistische Stadtverwaltung").
SELF_SUFFICIENT = [
    (r"(11\\.|elfte)\\s*verordnung zum reichsburgergesetz"
     r"|verordnung zum reichsburgergesetz vom 25\\.? november 1941",
     "11. VO Reichsbürgergesetz 1941", "reich"),
    (r"(?:\b|zwangs)arisier|\bariseur", "\"Arisierung\"", "arisiert"),
    (r"vermogensverkehrsstelle", "Vermögensverkehrsstelle", "arisiert"),
    (r"\bvugesta\b", "Vugesta", "arisiert"),
    (r"kommissarische[rn]? verwalter", "kommissarischer Verwalter", "arisiert"),
    (r"sammelwohnung", "Sammelwohnung (Zwangsquartier)", "sammelwohnung"),
    (r"reichsfluchtsteuer", "Reichsfluchtsteuer", "enteignet"),
]

# NEEDS_VICTIM: ordinary German words for taking things. On their own they
# describe plots merged into neighbours, state property moving between states,
# or wartime damage, so an identifiable victim must appear in the window.
NEEDS_VICTIM = [
    (r"reichsfinanzverwaltung", "Reichsfinanzverwaltung", "reich"),
    (r"(einverleibt|verfallen|ubereignet)", "Übergang an das Deutsche Reich", "reich"),
    (r"zwangsverkauf|notverkauf|zwangsweise verkauft|verkaufen (musste|mussten)",
     "Zwangs-/Notverkauf", "zwangsverkauf"),
    (r"enteignet|entzogen|beschlagnahmt|geraubt|weggenommen|konfisziert|entrechtet",
     "Enteignung/Beschlagnahme", "enteignet"),
]

# Post-war return. Implies a prior seizure, but far too ambiguous to stand
# alone, so it is only added once a page has qualified on other evidence.
RESTITUTION = [
    (r"ruckgestellt|ruckstellung|zuruckgegeben|zuruckerstattet|restituiert"
     r"|restitution|ruckerstattung|naturalrestitution",
     "Rückstellung/Restitution", "restitution"),
]

# The victim side must be identifiable.
VICTIM = [
    r"\bjud(e|en|in|innen|isch)", r"israelitisch", r"mosaisch",
    r"\bshoah\b", r"holocaust",
    r"deportiert|ermordet|vertrieben|emigrier|fliehen|flohen|flucht|exil",
    r"theresienstadt|auschwitz|dachau|konzentrationslager",
    r"reichsfluchtsteuer|vermogensverkehrsstelle|vermogensanmeldung",
    r"verordnung zum reichsburgergesetz", r"(?:\b|zwangs)arisier|\bariseur",
]

# Austrian/other state property moving between states - NOT theft from Jews.
# The Ostmarkgesetz 1941 swept Austrian public buildings into the
# Reichsfinanzverwaltung; the Republic got them back in 1946.
STATE = [
    r"ostmarkgesetz", r"bundesschatz", r"republik osterreich",
    r"land osterreich", r"bundesland", r"staatsvertrag",
    r"gemeinde wien.{0,40}(eigentum|erwarb)", r"stadt wien.{0,30}eigentum",
    r"osterreichischen? bundesbahn", r"bundesimmobilien",
    r"deutsche reichspost", r"reichsbahn", r"alliierte", r"besatzungsmacht",
]

# The page's subject is the actor, not the victim.
PERP = [
    # Word boundaries matter here too: without \b, "popularisierte das ..."
    # matched and made Adolf Loos a perpetrator.
    r"\barisierte (das|die|der|rund|mehrere|weitere|sechs|zahlreiche|sich)",
    r"beteiligung an .{0,20}arisierung", r"kreditvergabe an .{0,12}ariseur",
    r"unruhmliche rolle", r"ub(l)?e rolle", r"ermittelte den kaufpreis",
    r"kamen .{0,10}ariseure", r"liquidators? der vvst",
    r"abwicklungsstelle der vermogensverkehrsstelle",
    r"arisierungsagentur", r"\bals ariseur",
    # "profitierte" on its own is an everyday word - it made profiteers out of
    # a suburb that profited from a railway line. It has to profit from this.
    r"profitiert[e]?\s+(von|durch|an)\s+.{0,60}"
    r"(arisier|entzug|enteign|\bjud|geraubt|beschlagnahm|versteigerung)",
    r"geraubtes? .{0,25}eigentum kaufte",
    r"zentraldepot .{0,40}(beschlagnahm|geraubt|entzogen|kunstgut)",
    r"aus dem entzogenen vermogen", r"leitung einer arisierten",
    r"fungierte .{0,25}als .{0,25}(agentur|stelle)",
    # NOT "Schatzmeister": it also means a picture or book appraiser, including
    # in the 19th century ("Gemaeldeschaetzmeister", "Buecherschaetzmeister").
    r"schatzmeister der kaffeesiederinnung",
]

NAZI_ERA = [
    r"\b193[89]\b", r"\b194[0-9]\b", r"\b195[0-2]\b", r"nationalsozial",
    r"ns-zeit", r"\banschluss\b", r"drittes reich", r"nsdap", r"gestapo",
    r"novemberpogrom", r"reichskristallnacht", r"(?:\b|zwangs)arisier|\bariseur",
]

# Generic taking-words need an ownable object in view, or biography pages slip
# in where a teaching licence, a medical registration or library access was
# "entzogen" - persecution, but not property.
PROPERTY_OBJECT = [
    r"\bhaus|hauser|wohnung|liegenschaft|grundstuck|immobilie|gebaude",
    r"villa|palais|schloss|zinshaus|mietshaus|realitat",
    r"geschaft|betrieb|firma|unternehmen|verlag|apotheke|kino|lokal",
    r"\bcafe|kaffeehaus|hotel|warenhaus|kaufhaus|werkstatt|fabrik",
    r"vermogen|eigentum|besitz|anteile|sammlung|bibliothek|nachlass",
    r"konto|wertpapier|schmuck|kunstwerk|gemalde",
]

# Things taken that are explicitly NOT property.
NOT_PROPERTY = re.compile(
    r"(lehrbefugnis|lehrberechtigung|venia|zulassung|approbation|konzession"
    r"|berufsausubung|berufsberechtigung|doktorat|titel|staatsburgerschaft"
    r"|rechtsanwaltsliste|lehrbefahigung|lesesaal|zutritt|lebensgrundlage"
    r"|existenzgrundlage|pension|ruhegenuss)")

# "Das Mietshaus in der 17., Kalvarienberggasse 37 ... wurde arisiert" is a
# real case, but not a 1st-district one: it appears here only because the
# person also had an address in the Innere Stadt.
OTHER_DISTRICT = re.compile(r"\b(?:[2-9]|1[0-9]|2[0-3])\.,")

PRE_MODERN = re.compile(r"\b(1[0-8][0-9]{2})\b")      # a year before 1900

STOP_TITLES = {
    "Arisierung", "Ariernachweis", "Österreichische Historikerkommission",
    "Sammelwohnung", "Sammelwohnungen", "Vermögensverkehrsstelle", "Vugesta",
    "Rückstellungsgesetze", "Nationalsozialismus", "Dorotheum",
    # the looting agencies themselves, not places that were robbed
    "Verwertungsstelle für jüdisches Umzugsgut der Geheimen Staatspolizei",
    "Nationalsozialistische Volkswohlfahrt",
}
STOP_PATTERNS = [
    r"\bNSDAP\b", r"^Gauamt", r"^Gaurechtsamt", r"^Rassenpolitisches",
    r"^Gestapo", r"^Denkmal", r"[Dd]enkmal$",
]

# Memorial pages are kept, not excluded: "Stein der Erinnerung - Sammelwohnung
# Werdertorgasse 17" records that a specific building held a Sammelwohnung, and
# the memorial stands at that building. They are flagged so the map can say the
# documentation comes from a memorial rather than a house history.
MEMORIAL_PATTERNS = [
    r"^Stein der Erinnerung", r"^Steine der Erinnerung", r"^Gedenktafel",
    r"-Gedenktafel", r"^Stolperstein", r"^Mahnmal", r"^Gedenkstein",
]
STOP_KINDS = {"Verkehrsfläche", "Brücke", "Denkmal"}

CATEGORY_RANK = ["reich", "arisiert", "zwangsverkauf", "enteignet",
                 "sammelwohnung", "restitution"]

# The wiki's infobox template says what kind of thing the page is, which is
# exactly the "is this actually real estate?" distinction the map needs:
# a house, a business that occupied premises, a person's own address, or a
# memorial marking the site.
INFOBOX = re.compile(r"\{\{\s*(Bauwerk|Person|Organisation|Erinnerung|"
                     r"Topografisches Objekt)\s*[\n\|]")
TYPE_MAP = {
    "Bauwerk": "gebaeude",
    "Organisation": "betrieb",
    "Person": "person",
    "Erinnerung": "gedenkzeichen",
    "Topografisches Objekt": "gebaeude",
}


def page_type(raw):
    m = INFOBOX.search(raw)
    return TYPE_MAP.get(m.group(1), "sonstiges") if m else "sonstiges"


def any_hit(folded, patterns):
    return [p for p in patterns if re.search(p, folded)]


def excluded(title, kind):
    if title in STOP_TITLES:
        return "stop-list"
    for pat in STOP_PATTERNS:
        if re.search(pat, title):
            return f"title pattern {pat}"
    if kind in STOP_KINDS:
        return f"kind {kind}"
    return None


def analyse(prose):
    """Sentence-level evidence, in two passes.

    Pass 1 qualifies the page on self-sufficient or victim-backed evidence.
    Pass 2 then adds restitution sentences as supporting detail - but only for
    a page that already qualified, so "1946 returned to the Republic" can
    never create a case on its own.
    """
    sents = sentences(prose)
    folded = [fold(s) for s in sents]
    page_era = any_hit(fold(prose), NAZI_ERA)

    perp = [s for s, f in zip(sents, folded) if any_hit(f, PERP)]
    perp_set = set(perp)

    def usable(i, f, sent):
        if sent in perp_set:
            return False
        if any_hit(f, STATE):                       # state-to-state transfer
            return False
        if OTHER_DISTRICT.search(sent):             # property in another Bezirk
            return False
        # wrong century: a pre-1900 year and no Nazi-era marker of its own
        if PRE_MODERN.search(sent) and not any_hit(f, NAZI_ERA):
            return False
        return True

    def in_era(i, f):
        """Nazi-era context must be near the sentence, not merely on the page.

        A page-wide test let the Misrachihaus in, whose "einverleibt" belongs
        to a 1907 foundation transfer. Markers that are themselves Nazi-era
        (Arisierung, VVSt, Vugesta, Reichsfluchtsteuer...) satisfy this alone.
        """
        window = " ".join(folded[max(0, i - 1):i + 2])
        return bool(any_hit(window, NAZI_ERA))

    evidence = []
    for i, (sent, f) in enumerate(zip(sents, folded)):
        if not usable(i, f, sent):
            continue
        window = " ".join(folded[max(0, i - 1):i + 2])

        labels = [(lbl, cat) for pat, lbl, cat in SELF_SUFFICIENT
                  if re.search(pat, f)]

        # generic taking-words: need a victim, an ownable object, Nazi-era
        # context, and must not be about a licence or a professional right
        if (any_hit(window, VICTIM) and any_hit(window, PROPERTY_OBJECT)
                and in_era(i, f) and not NOT_PROPERTY.search(f)):
            labels += [(lbl, cat) for pat, lbl, cat in NEEDS_VICTIM
                       if re.search(pat, f)]

        if labels and (in_era(i, f) or any(
                re.search(pat, f) for pat, _, _ in SELF_SUFFICIENT)):
            evidence.append({"quote": sent, "labels": labels})

    if not evidence:
        return [], perp

    for i, (sent, f) in enumerate(zip(sents, folded)):       # pass 2
        if any(e["quote"] == sent for e in evidence):
            continue
        if not usable(i, f, sent):
            continue
        labels = [(lbl, cat) for pat, lbl, cat in RESTITUTION
                  if re.search(pat, f)]
        if labels:
            evidence.append({"quote": sent, "labels": labels})

    # A page where the subject mostly acts rather than suffers is a
    # perpetrator site, not robbed property (e.g. Cafe Landtmann, whose owner
    # valued other people's cafes for forced sale).
    # Strictly more perpetrator sentences than substantive victim evidence.
    # ">=" was too blunt: Cafe Herrenhof carries one sentence about the SA man
    # installed as its "kommissarischer Verwalter" alongside the sentence
    # saying the cafe itself was "arisiert" - that is a robbed property, not a
    # perpetrator site.
    core = [e for e in evidence
            if any(c != "restitution" for _, c in e["labels"])]
    if len(perp) > len(core):
        return [], perp

    return evidence, perp


def main():
    texts = json.loads(WIKITEXT.read_text())
    print(f"scanning {len(texts)} Bezirk-1 pages")

    kept, perps, rejected, stats = [], [], [], {}
    for title, raw in sorted(texts.items()):
        prose = plain(raw)
        evidence, perp_quotes = analyse(prose)
        if not evidence and not perp_quotes:
            continue

        reason = excluded(title, None)
        if reason:
            rejected.append((title, reason))
            continue

        if not evidence:                       # perpetrator / profiteer only
            perps.append({
                "title": title,
                "url": "https://www.geschichtewiki.wien.gv.at/"
                       + urllib.parse.quote(title.replace(" ", "_")),
                "page_type": page_type(raw),
                "quotes": perp_quotes[:3],
            })
            continue

        cats = {c for e in evidence for _, c in e["labels"]}
        category = next((c for c in CATEGORY_RANK if c in cats), "restitution")
        labels = sorted({l for e in evidence for l, _ in e["labels"]})
        quotes = []
        for e in evidence:
            q = re.sub(r"\s+", " ", e["quote"]).strip(" .,;:|\u201c\u201e\"'")
            if q and q not in quotes and 25 < len(q) < 700:
                quotes.append(q)
        if not quotes:            # nothing quotable -> nothing to show a reader
            rejected.append((title, "evidence not quotable"))
            continue
        years = sorted({int(y) for y in re.findall(r"\b(19[2-5][0-9])\b",
                                                  " ".join(quotes))})
        kept.append({
            "title": title,
            "memorial": any(re.search(p, title) for p in MEMORIAL_PATTERNS),
            "page_type": page_type(raw),
            "url": "https://www.geschichtewiki.wien.gv.at/"
                   + urllib.parse.quote(title.replace(" ", "_")),
            "category": category,
            "evidence": labels,
            "restituted": "Rückstellung/Restitution" in labels,
            "years": years,
            "quotes": quotes[:4],
            "n_evidence": len(evidence),
        })
        stats[category] = stats.get(category, 0) + 1

    kept.sort(key=lambda r: (CATEGORY_RANK.index(r["category"]), r["title"]))
    perps.sort(key=lambda r: r["title"])
    OUT.write_text(json.dumps({"properties": kept, "perpetrators": perps},
                              ensure_ascii=False, indent=1))
    CAND.write_text(json.dumps([r["title"] for r in kept]
                               + [r["title"] for r in perps], ensure_ascii=False))

    lines = [f"scanned:      {len(texts)} Bezirk-1 pages",
             f"properties:   {len(kept)}",
             f"perpetrators: {len(perps)}", ""]
    for cat, n in sorted(stats.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {cat:<16} {n}")
    lines.append("")
    types = {}
    for r in kept:
        types[r["page_type"]] = types.get(r["page_type"], 0) + 1
    for t, n in sorted(types.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {t:<16} {n}")
    lines.append(f"\n  restitution mentioned: {sum(1 for r in kept if r['restituted'])}")
    lines.append(f"\nexcluded ({len(rejected)}):")
    for t, why in sorted(rejected):
        lines.append(f"  {t}  --  {why}")
    REPORT.write_text("\n".join(lines))
    print("\n".join(lines[:16]))
    print(f"\nwritten to {OUT} and {CAND}")


if __name__ == "__main__":
    main()
