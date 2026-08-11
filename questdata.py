"""The quest graph, and the shape the browser draws it in.

data/quests.json is a flat list of 117 quests. Turning that into something you
can navigate is this file's whole job, and it is less obvious than it sounds,
because Palworld does not actually have a branching quest tree:

  * the 58 main missions are one long chain (~30 links) with the old and new
    tutorials forking at the start and merging again a few steps in;
  * 57 of the 59 side missions have no recorded links at all. They are gated in
    Blueprint graphs that the datamine behind quests.json never reached, so the
    honest thing is not to invent edges. Their ids carry the questgiver instead
    (Sub_Farmer04, Sub_Zoe02), which is a real grouping the game itself uses,
    so side quests are shelved by who hands them out and ordered by their
    trailing number.

So: main missions get a true dependency order, side missions get questgiver
lines, and the detail pane leans on `related` to reconnect what the edges miss.

Nothing here imports tkinter - the browser draws what these functions return,
and that keeps the graph testable from a plain interpreter.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "quests.json"

#: Side-quest id stems that read badly when split on capitals, or that are one
#: family under several stems. Everything else is title-cased from its stem.
GROUP_LABELS = {
    "StrongOldMan": "Strong Old Man",
    "RookieExpeditionTeam": "Rookie Expedition Team",
    "LoneWolf": "Lone Wolf",
    "PalDisplay": "Pal Display Requests",
    "Kigurumi": "Depresso Costume",
}
#: Stems collapsed into one shelf, longest prefix first.
GROUP_MERGES = (("Delivery", "Deliveries"), ("PalDisplay", "Pal Display Requests"),
                ("Kigurumi", "Depresso Costume"), ("Zoe", "Zoe"))

#: Where the main line starts. paldb records two tutorial entry points that run
#: separately for a dozen steps and then converge on "Gearing Up" - an older
#: flow beginning at The Adventure Begins, and the one a new save opens with. On
#: id order alone the old flow would sort first and the list would open on
#: quests today's player never sees, so the real opening is named here. Both
#: paths are still listed; only which one leads is decided.
#:
#: Note this is *not* a claim that the other path is dead content. Several of
#: its quests still ship as blueprints in the current build - paldb's Next links
#: are just incomplete for them - so neither branch is hidden or marked stale.
MAIN_ENTRY = "Main_UnlockFastTravel"

#: How close two objectives must be to count as "nearby" on the same map. The
#: maps are in Palworld's own world units; 150 keeps a settlement and its
#: outskirts together without sweeping in the next biome.
NEARBY_RADIUS = 150
NEARBY_LIMIT = 6


class Quest:
    """One quest, with its edges resolved to other Quest objects on demand."""

    __slots__ = ("id", "slug", "name", "kind", "description", "objectives",
                 "rewards", "next_ids", "prev_ids", "_book")

    def __init__(self, raw: dict, book: "QuestBook"):
        self.id = raw["id"]
        self.slug = raw["slug"]
        self.name = raw["name"]
        self.kind = raw["kind"]
        self.description = raw["description"]
        self.objectives = raw["objectives"]
        self.rewards = raw["rewards"]
        self.next_ids = raw["next"]
        self.prev_ids = raw["prev"]
        self._book = book

    def __repr__(self) -> str:
        return f"<Quest {self.id}>"

    @property
    def is_main(self) -> bool:
        # paldb's own label, not the id prefix: one entry is filed under Main
        # Mission while carrying a Test_ id, and its count is the one to match.
        return self.kind.startswith("Main")

    @property
    def next(self) -> list["Quest"]:
        return [self._book[i] for i in self.next_ids]

    @property
    def prev(self) -> list["Quest"]:
        return [self._book[i] for i in self.prev_ids]

    @property
    def group(self) -> str:
        """The questgiver shelf a side quest sits on; '' for main missions."""
        if self.is_main:
            return ""
        stem = self.id.split("_", 1)[1]
        for prefix, label in GROUP_MERGES:
            if stem.startswith(prefix):
                return label
        stem = re.sub(r"_?\d+$", "", stem).rstrip("_")
        return GROUP_LABELS.get(stem, re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem))

    @property
    def order(self) -> int:
        """Trailing number in the id, which orders a questgiver's line."""
        match = re.search(r"(\d+)$", self.id)
        return int(match.group(1)) if match else 0

    @property
    def places(self) -> list[dict]:
        return [o for o in self.objectives if "x" in o]

    @property
    def steps(self) -> list[str]:
        """The walkthrough: paldb lists one objective per quest block, in order."""
        return [o["text"] for o in self.objectives]


class QuestBook:
    def __init__(self, path: Path = DATA):
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.quests = [Quest(r, self) for r in raw]
        self._by_id = {q.id: q for q in self.quests}

    def __getitem__(self, quest_id: str) -> Quest:
        return self._by_id[quest_id]

    def get(self, quest_id: str) -> Quest | None:
        return self._by_id.get(quest_id)

    def __len__(self) -> int:
        return len(self.quests)

    # ---------------- ordering ----------------

    def main_order(self) -> list[Quest]:
        """Main missions in reading order: follow the chain, start to finish.

        Deliberately *not* a topological sort. The two tutorials are cross-linked
        in paldb's data - the current flow's fourth step lists a prereq that sits
        on the older flow - so a strict dependency order has to abandon the chain
        you are reading at step four and run the whole other tutorial first. That
        is faithful and unreadable.

        Walking `next` from the game's actual opening instead keeps the main
        story contiguous the way a player meets it, then picks up whatever the
        walk never reached (the alternate tutorial, then isolated quests) behind
        it. True prerequisites are not lost - the detail pane reads them off the
        edges, where a reader can see both at once.
        """
        mains = [q for q in self.quests if q.is_main]
        seen: set[str] = set()
        out: list[Quest] = []

        def walk(quest: Quest) -> None:
            if quest.id in seen or not quest.is_main:
                return
            seen.add(quest.id)
            out.append(quest)
            for child in sorted(quest.next, key=lambda q: q.id):
                walk(child)

        entry = self.get(MAIN_ENTRY)
        if entry is not None:
            walk(entry)
        # remaining roots first so alternate paths arrive whole, then anything
        # still unvisited, so no quest can silently fall out of the tree
        for quest in sorted((q for q in mains if not q.prev_ids), key=lambda q: q.id):
            walk(quest)
        for quest in sorted(mains, key=lambda q: q.id):
            walk(quest)
        return out

    def main_sections(self) -> list[tuple[str, list[Quest]]]:
        """Main missions split into the story you follow and the rest.

        The walk from the opening covers 30 quests end to end; what is left is
        the alternate tutorial and a handful with no links at all. Shelving them
        apart keeps the story readable without dropping anything - the second
        shelf is still there, still searchable, just not interleaved.
        """
        order = self.main_order()
        entry = self.get(MAIN_ENTRY)
        if entry is None:
            return [("Main missions", order)]

        story: list[Quest] = []
        seen: set[str] = set()
        stack = [entry]
        while stack:                      # everything reachable from the opening
            quest = stack.pop()
            if quest.id in seen or not quest.is_main:
                continue
            seen.add(quest.id)
            story.append(quest)
            stack.extend(quest.next)

        rank = {q.id: i for i, q in enumerate(order)}
        story.sort(key=lambda q: rank[q.id])
        rest = [q for q in order if q.id not in seen]
        sections = [("Main story", story)]
        if rest:
            sections.append(("Other main missions", rest))
        return sections

    def side_groups(self) -> list[tuple[str, list[Quest]]]:
        """Side missions as (questgiver, quests), biggest lines first."""
        shelves: dict[str, list[Quest]] = {}
        for quest in self.quests:
            if not quest.is_main:
                shelves.setdefault(quest.group, []).append(quest)
        for quests in shelves.values():
            quests.sort(key=lambda q: (q.order, q.id))
        return sorted(shelves.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    # ---------------- lookup ----------------

    def search(self, term: str) -> list[Quest]:
        """Quests matching `term` in name, id, description or any objective."""
        term = term.strip().lower()
        if not term:
            return []
        hits = []
        for quest in self.quests:
            haystacks = (quest.name, quest.id, quest.description, " ".join(quest.steps))
            if any(term in h.lower() for h in haystacks):
                hits.append(quest)
        # name matches first - typing "zoe" should surface Zoe Rayne, not the
        # quest that merely mentions her in a paragraph of flavour text
        hits.sort(key=lambda q: (term not in q.name.lower(), q.name))
        return hits

    def nearby(self, quest: Quest) -> list[Quest]:
        """Other quests with an objective close to one of this quest's.

        The point of this is the side missions: with no edges of their own, the
        only honest way to say "and while you are here" is geography.
        """
        mine = quest.places
        if not mine:
            return []
        found = []
        for other in self.quests:
            if other.id == quest.id:
                continue
            best = min(
                (max(abs(a["x"] - b["x"]), abs(a["y"] - b["y"]))
                 for a in mine for b in other.places if a["map"] == b["map"]),
                default=None)
            if best is not None and best <= NEARBY_RADIUS:
                found.append((best, other))
        found.sort(key=lambda pair: (pair[0], pair[1].name))
        return [q for _, q in found[:NEARBY_LIMIT]]

    def related(self, quest: Quest) -> list[tuple[str, list[Quest]]]:
        """Everything the detail pane can offer as a next click, labelled."""
        sections = [("Unlocked by", quest.prev), ("Leads to", quest.next)]
        if not quest.is_main:
            line = [q for q in self.quests
                    if not q.is_main and q.group == quest.group and q.id != quest.id]
            line.sort(key=lambda q: (q.order, q.id))
            sections.append((f"More from {quest.group}", line))
        sections.append(("Nearby", self.nearby(quest)))
        return [(label, quests) for label, quests in sections if quests]


if __name__ == "__main__":
    book = QuestBook()
    order = book.main_order()
    print(f"{len(book)} quests: {len(order)} main, {len(book.quests) - len(order)} side")
    print(f"\nmain order (first 12):")
    for i, quest in enumerate(order[:12], 1):
        print(f"  {i:2d}. {quest.name}")
    print("\nside groups:")
    for label, quests in book.side_groups():
        print(f"  {label:24s} {len(quests)}")
