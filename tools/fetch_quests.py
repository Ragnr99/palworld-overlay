"""Regenerate data/quests.json from paldb.cc.

Run this when Palworld updates and the quest list moves on; nothing else in the
project touches the network. The overlay ships the generated snapshot instead of
scraping at launch - it has to work offline, mid-game, in under a second, and
hammering someone else's wiki on every start would be rude.

paldb publishes a datamine of DT_PalQuestData, which is why this is worth
scraping rather than hand-writing: every card carries `data-id`, the game's own
row name (Main_UnlockFastTravel, Sub_Farmer04), so the snapshot is keyed by
something stable across site redesigns and comparable against the .pak.

    py -3.10 tools/fetch_quests.py

The one thing paldb cannot give us is what unlocks a *side* quest - those are
gated in Blueprint graphs the datamine doesn't reach, so 57 of 59 arrive with no
edges at all. questdata.py groups them by questgiver instead; see the note there.

    --html PATH   parse a saved page instead of fetching (for offline reruns)
"""

from __future__ import annotations

import argparse
import collections
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

SOURCE = "https://paldb.cc/en/Mission"
OUT = Path(__file__).resolve().parent.parent / "data" / "quests.json"

# Each card opens with its title div, and that div is the only place the game's
# internal id appears. Anchoring on it is what makes the split reliable - the
# surrounding bootstrap markup is generic and repeats everywhere.
CARD = re.compile(
    r'<div id="(?P<slug>[^"]+)" style="background-color: [^"]*" data-id="(?P<id>[^"]+)">'
    r"(?P<name>[^<]*)</div>"
)
SECTION = re.compile(r'<div class="half-bottom-row"><div>([^<]+)</div></div>')
DIV = re.compile(r"<div[^>]*>(.*?)</div>", re.S)
POS = re.compile(r"\?pos=(-?\d+)%2C(-?\d+)")


def fetch(url: str = SOURCE) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "palworld-overlay/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


#: Palworld substitutes names into quest text at runtime, and paldb ships the
#: briefings with those substitutions still unmade - 68 of them, like
#: `<characterName id=|KingWhale|/>`. They look like tags, so stripping tags
#: eats them and leaves "You'll need ' help to make your way into the World
#: Tree", which reads like a typo rather than missing data.
PLACEHOLDER = re.compile(r"<(?:characterName|itemName|mapObjectName) id=\|([^|]*)\|\s*/>")


def text_of(fragment: str) -> str:
    """Tag soup to readable text, keeping paldb's hard line breaks.

    Unresolved name placeholders are kept as `{KingWhale}` rather than guessed
    at. The id is the game's internal one and often is not the display name at
    all - KingWhale is the Pal you know as Panthalus - so inventing a name here
    would put a wrong item in a walkthrough. Braces make it obvious that the
    word is a token and not something to go looking for. Resolving them properly
    means DT_ItemNameText and DT_PalNameText out of the .pak; see README.
    """
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    fragment = PLACEHOLDER.sub(lambda m: "{" + m.group(1) + "}", fragment)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    fragment = html.unescape(fragment)
    # collapse runs of spaces but never newlines: the descriptions are
    # deliberately wrapped and read badly as one long line
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip()
                     for line in fragment.split("\n")).strip()


def split_sections(body: str) -> dict[str, str]:
    """Card body into {'Objective': html, 'Reward': html, 'Next': html, ...}."""
    parts = SECTION.split(body)
    out = {"": parts[0]}
    for i in range(1, len(parts) - 1, 2):
        out[parts[i].strip()] = parts[i + 1]
    return out


def objectives(fragment: str) -> list[dict]:
    """The quest's steps, in order, with map coordinates where paldb links them.

    This is the walkthrough. paldb lists one entry per quest block, so the order
    here is the order the game asks for them - `Investigate, Talk, CollectBones,
    CraftWhistle, Defeat, Report` for Panthalus, matching its eight
    BP_MainQuestBlock_DefeatKingWhale_* assets one for one.
    """
    steps = []
    for match in re.finditer(r"<div>(?!<div)(.*?)</div>", fragment, re.S):
        inner = match.group(1)
        label = text_of(inner)
        if not label:
            continue
        step = {"text": label}
        position = POS.search(inner)
        if position:
            step["map"] = re.search(r'href="([^"?]+)', inner).group(1)
            step["x"], step["y"] = int(position.group(1)), int(position.group(2))
        steps.append(step)
    return steps


def rewards(fragment: str) -> list[str]:
    # Rewards carry an inline icon and sit in a line-height'd div; falling back
    # to every div keeps oddballs (pure-gold rewards) from vanishing silently.
    found = [text_of(m.group(1)) for m in
             re.finditer(r'<div style="line-height: 32px">(.*?)</div>\s*(?=<div|$)', fragment, re.S)]
    found = [f for f in found if f]
    return found or [t for t in (text_of(d) for d in DIV.findall(fragment)) if t]


def parse(page: str) -> list[dict]:
    cards = list(CARD.finditer(page))
    if not cards:
        raise SystemExit("no quest cards found - paldb's markup has changed")

    quests = []
    for n, card in enumerate(cards):
        end = cards[n + 1].start() if n + 1 < len(cards) else len(page)
        section = split_sections(page[card.end():end])
        intro = DIV.findall(section[""])
        quest_id = card.group("id")
        quests.append({
            "id": quest_id,
            "slug": card.group("slug"),
            "name": html.unescape(card.group("name")).strip() or fallback_name(quest_id),
            "kind": text_of(intro[0]) if intro else "",
            "description": "\n".join(t for t in (text_of(d) for d in intro[1:]) if t),
            "objectives": objectives(section.get("Objective", "")),
            "rewards": rewards(section.get("Reward", "")),
            "_next_names": [t for t in (text_of(d) for d in DIV.findall(section.get("Next", ""))) if t],
        })
    return link(quests)


#: Palworld's tutorial was rewritten and paldb still carries both versions, so
#: four display names each belong to two different quests. "Next" links are
#: printed as names, which makes those four edges genuinely undecidable from the
#: page alone - and picking wrong silently welds the old tutorial onto the new
#: one. They are spelled out here (source id -> name -> target id) rather than
#: guessed at, because no rule generalises: the pairs split across the old/new
#: chains in both directions. Anything ambiguous and *not* listed is reported.
DISAMBIGUATE = {
    ("Main_EquipClothArmor", "The Weakest Pal"): "Main_CaptureSheepBall_Old",
    ("Main_EatFood", "The Weakest Pal"): "Main_CaptureSheepBall",
    ("Main_PickupWood", "Enhance Stats"): "Main_GainStatus",
    ("Main_CraftTools", "Enhance Stats"): "Main_StatusUp",
}


def fallback_name(quest_id: str) -> str:
    """A readable name for the ten cards paldb renders with an empty title.

    They are the Pal-display and test entries; without this they all collapse
    into one blank row and become unclickable in the tree.
    """
    stem = quest_id.split("_", 1)[1] if "_" in quest_id else quest_id
    stem = re.sub(r"_+", " ", stem).strip()
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem) or quest_id


def link(quests: list[dict]) -> list[dict]:
    """Turn paldb's display-name 'Next' links into id edges, both directions.

    Names are what the page prints, but ids are what survives a rename, so the
    snapshot stores ids only. An unresolved name means the parse drifted, and
    that is worth shouting about rather than shipping a graph with holes.
    """
    by_name = collections.defaultdict(list)
    for quest in quests:
        by_name[quest["name"]].append(quest["id"])

    missing, ambiguous = collections.Counter(), []
    previous = collections.defaultdict(list)

    for quest in quests:
        quest["next"] = []
        for name in quest.pop("_next_names"):
            candidates = by_name.get(name, [])
            if not candidates:
                missing[name] += 1
                continue
            if len(candidates) == 1:
                target = candidates[0]
            else:
                target = DISAMBIGUATE.get((quest["id"], name))
                if target is None:
                    ambiguous.append((quest["id"], name, candidates))
                    target = candidates[0]
            quest["next"].append(target)
            previous[target].append(quest["id"])

    if missing:
        print(f"  warning: {sum(missing.values())} unresolved Next links: "
              f"{', '.join(list(missing)[:5])}", file=sys.stderr)
    for source, name, candidates in ambiguous:
        print(f"  warning: {source} -> {name!r} is ambiguous {candidates}; took the first. "
              f"Add it to DISAMBIGUATE.", file=sys.stderr)

    for quest in quests:
        quest["prev"] = previous.get(quest["id"], [])
    return quests


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", type=Path, help="parse this saved page instead of fetching")
    args = parser.parse_args()

    page = args.html.read_text(encoding="utf-8") if args.html else fetch()
    quests = parse(page)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(quests, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    edges = sum(len(q["next"]) for q in quests)
    located = sum(1 for q in quests if any("x" in o for o in q["objectives"]))
    print(f"wrote {OUT.relative_to(OUT.parent.parent)}: {len(quests)} quests, "
          f"{edges} edges, {located} with map coordinates")


if __name__ == "__main__":
    main()
