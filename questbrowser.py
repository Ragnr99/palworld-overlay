"""The quest browser: a tree of every quest, and a readable page for each one.

Lives in the control panel rather than on the overlay, because the overlay is
click-through on purpose - you cannot click a window that is built never to take
the mouse, and a quest tree you cannot click is a poster. This is a normal
window you alt-tab to, which is also when you actually read a walkthrough.

Two halves. The tree on the left is the whole game at a glance: the main story
in the order you meet it, then the questgiver lines. The pane on the right is
one quest in full - what it asks for, step by step, what it pays, and every
other quest it touches, each of those a link. Following links keeps a history,
so Backspace walks out of wherever a chain of "and then?" led you.

    py -3.10 questbrowser.py      on its own
    Ctrl+Alt+O                    as the panel's Quests tab
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from questdata import QuestBook, Quest

LINK = "#2f6fd0"
MUTED = "#6a7280"
COORD = "#8a5a00"
HEADING = "#111318"

#: Objectives that are a bare map pin repeat the previous line for the game's
#: benefit, not the reader's. paldb also ships a literal "？？？" for content it
#: will not spoil, which is worth keeping but not worth numbering as a step.
HIDDEN_STEP = "？？？"


class QuestBrowser(ttk.Frame):
    """Tree + detail pane. Drop it in a Notebook tab or run it standalone."""

    def __init__(self, parent, book: QuestBook | None = None):
        super().__init__(parent)
        self.book = book or QuestBook()
        self._nodes: dict[str, str] = {}     # quest id -> tree item id
        self._history: list[str] = []
        self._forward: list[str] = []
        self._current: Quest | None = None
        self._suppress = False               # tree selection we caused ourselves

        self.columnconfigure(1, weight=3)
        self.columnconfigure(0, weight=2)
        self.rowconfigure(0, weight=1)
        self._build_tree()
        self._build_detail()
        self._populate()

    # ---------------- left: the tree ----------------

    def _build_tree(self) -> None:
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        search = ttk.Frame(left)
        search.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        search.columnconfigure(0, weight=1)
        self.query = tk.StringVar()
        entry = ttk.Entry(search, textvariable=self.query)
        entry.grid(row=0, column=0, sticky="ew")
        entry.insert(0, "")
        self.query.trace_add("write", lambda *_: self._populate())
        ttk.Button(search, text="Clear", width=6,
                   command=lambda: self.query.set("")).grid(row=0, column=1, padx=(6, 0))

        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        self.tree.grid(row=1, column=0, sticky="nsew")
        bar = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        bar.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        self.count = ttk.Label(left, foreground=MUTED, font=("Segoe UI", 8))
        self.count.grid(row=2, column=0, sticky="w", pady=(4, 0))

    def _populate(self) -> None:
        """Rebuild the tree, filtered by the search box.

        A search collapses the shelving into one flat list of hits: when you are
        hunting a name you want the answer, not the answer's place in a
        hierarchy you then have to unfold.
        """
        self.tree.delete(*self.tree.get_children())
        self._nodes.clear()
        term = self.query.get().strip()

        if term:
            hits = self.book.search(term)
            for quest in hits:
                tag = "main" if quest.is_main else "side"
                self._add(quest, "", prefix=f"[{'Main' if quest.is_main else 'Side'}] ", tag=tag)
            self.count.configure(text=f"{len(hits)} match" + ("" if len(hits) == 1 else "es"))
            return

        for label, quests in self.book.main_sections():
            shelf = self.tree.insert("", "end", text=f"{label}  ({len(quests)})", open=True)
            for n, quest in enumerate(quests, 1):
                self._add(quest, shelf, prefix=f"{n}. ")

        side = self.tree.insert("", "end", text=f"Side missions  ({len(self.book) - 58})",
                                open=True)
        for label, quests in self.book.side_groups():
            shelf = self.tree.insert(side, "end", text=f"{label}  ({len(quests)})", open=False)
            for quest in quests:
                self._add(quest, shelf)
        self.count.configure(text=f"{len(self.book)} quests")

    def _add(self, quest: Quest, parent: str, prefix: str = "", tag: str = "") -> None:
        item = self.tree.insert(parent, "end", text=f"{prefix}{quest.name}",
                                values=(quest.id,), tags=(tag,) if tag else ())
        # A quest can be reachable from two shelves; the first one wins the
        # reveal, which is enough to scroll to.
        self._nodes.setdefault(quest.id, item)

    def _on_select(self, _event=None) -> None:
        if self._suppress:
            return
        selected = self.tree.selection()
        if not selected:
            return
        values = self.tree.item(selected[0], "values")
        if values:
            self.show(values[0], remember=True)

    # ---------------- right: the page ----------------

    def _build_detail(self) -> None:
        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        nav = ttk.Frame(right)
        nav.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.back_button = ttk.Button(nav, text="< Back", width=8, command=self.back,
                                      state="disabled")
        self.back_button.pack(side="left")
        self.forward_button = ttk.Button(nav, text="Forward >", width=10, command=self.forward,
                                         state="disabled")
        self.forward_button.pack(side="left", padx=(4, 0))
        self.crumb = ttk.Label(nav, foreground=MUTED, font=("Segoe UI", 8))
        self.crumb.pack(side="left", padx=(10, 0))

        self.page = tk.Text(right, wrap="word", padx=14, pady=12, borderwidth=1,
                            relief="solid", highlightthickness=0, cursor="arrow",
                            font=("Segoe UI", 10))
        self.page.grid(row=1, column=0, sticky="nsew")
        bar = ttk.Scrollbar(right, orient="vertical", command=self.page.yview)
        bar.grid(row=1, column=1, sticky="ns")
        self.page.configure(yscrollcommand=bar.set)

        self.page.tag_configure("h1", font=("Segoe UI", 15, "bold"), foreground=HEADING,
                                spacing3=2)
        self.page.tag_configure("kind", foreground=MUTED, font=("Segoe UI", 9), spacing3=10)
        self.page.tag_configure("h2", font=("Segoe UI", 9, "bold"), foreground=MUTED,
                                spacing1=14, spacing3=6)
        self.page.tag_configure("body", foreground="#20242c", spacing3=4, lmargin1=2, lmargin2=2)
        self.page.tag_configure("step", spacing3=3, lmargin1=6, lmargin2=26)
        self.page.tag_configure("coord", foreground=COORD, font=("Consolas", 9))
        self.page.tag_configure("muted", foreground=MUTED, font=("Segoe UI", 9))
        self.page.tag_configure("link", foreground=LINK, underline=True)
        self.page.configure(state="disabled")

        self.bind_all("<BackSpace>", lambda _: self.back())

    # ---------------- navigation ----------------

    def show(self, quest_id: str, remember: bool = False, clear_forward: bool = True) -> None:
        quest = self.book.get(quest_id)
        if quest is None or (self._current is not None and quest.id == self._current.id):
            return
        if remember and self._current is not None:
            self._history.append(self._current.id)
            if clear_forward:
                self._forward.clear()
        self._current = quest
        self._render(quest)
        self._reveal(quest)
        self._update_nav()

    def back(self) -> None:
        if not self._history:
            return
        if self._current is not None:
            self._forward.append(self._current.id)
        target = self._history.pop()
        self._current = None                      # so show() does not early-return
        self.show(target, remember=False)

    def forward(self) -> None:
        if not self._forward:
            return
        target = self._forward.pop()
        if self._current is not None:
            self._history.append(self._current.id)
        self._current = None
        self.show(target, remember=False)

    def _update_nav(self) -> None:
        self.back_button.configure(state="normal" if self._history else "disabled")
        self.forward_button.configure(state="normal" if self._forward else "disabled")
        depth = len(self._history)
        self.crumb.configure(text=f"{depth} back" if depth else "")

    def _reveal(self, quest: Quest) -> None:
        """Scroll the tree to the quest the pane is showing, without recursing."""
        item = self._nodes.get(quest.id)
        if not item:
            return
        self._suppress = True
        try:
            parent = self.tree.parent(item)
            while parent:
                self.tree.item(parent, open=True)
                parent = self.tree.parent(parent)
            self.tree.selection_set(item)
            self.tree.see(item)
        finally:
            self._suppress = False

    # ---------------- rendering ----------------

    def _render(self, quest: Quest) -> None:
        self.page.configure(state="normal")
        self.page.delete("1.0", "end")

        self.page.insert("end", quest.name + "\n", "h1")
        self.page.insert("end", f"{quest.kind}  ·  {quest.id}\n", "kind")

        if quest.description:
            self.page.insert("end", "Briefing\n", "h2")
            self.page.insert("end", quest.description.strip() + "\n", "body")

        self._render_steps(quest)

        if quest.rewards:
            self.page.insert("end", "Rewards\n", "h2")
            for reward in quest.rewards:
                self.page.insert("end", f"  •  {reward}\n", "body")

        for label, quests in self.book.related(quest):
            self.page.insert("end", label + "\n", "h2")
            for other in quests:
                self.page.insert("end", "  ")
                self._insert_link(other)
                self.page.insert("end", "\n")

        self.page.configure(state="disabled")
        self.page.yview_moveto(0)

    def _render_steps(self, quest: Quest) -> None:
        """The walkthrough.

        paldb emits one objective per quest block, so this list is already the
        order the game asks for them in - the numbering is real, not invented.
        Map pins are split out and dimmed so a step reads as "do this, at here"
        rather than as a wall of coordinates.
        """
        if not quest.objectives:
            return
        self.page.insert("end", "Walkthrough\n", "h2")
        step = 0
        for objective in quest.objectives:
            text = objective["text"]
            if text == HIDDEN_STEP:
                self.page.insert("end", "     (paldb withholds this step)\n", "muted")
                continue
            step += 1
            if "x" in objective:
                # "Hill of Beginnings 240,-512" - keep the place, retag the pin
                place = text.rsplit(" ", 1)[0] if " " in text else text
                self.page.insert("end", f"  {step}.  {place}  ", "step")
                self.page.insert("end", f"[{objective['x']}, {objective['y']}]", "coord")
                self.page.insert("end", f"  {objective['map'].replace('_', ' ')}\n", "muted")
            else:
                self.page.insert("end", f"  {step}.  {text}\n", "step")

    def _insert_link(self, quest: Quest) -> None:
        """A clickable quest name. Each gets its own tag so the click knows who."""
        tag = f"go-{quest.id}"
        start = self.page.index("end-1c")
        self.page.insert("end", quest.name, ("link", tag))
        self.page.insert("end", f"   {quest.kind.replace(' Mission', '')}", "muted")
        self.page.tag_add(tag, start, self.page.index("end-1c"))
        self.page.tag_bind(tag, "<Button-1>",
                           lambda _e, qid=quest.id: self.show(qid, remember=True))
        self.page.tag_bind(tag, "<Enter>", lambda _e: self.page.configure(cursor="hand2"))
        self.page.tag_bind(tag, "<Leave>", lambda _e: self.page.configure(cursor="arrow"))


def main() -> None:
    root = tk.Tk()
    root.title("Palworld quests")
    root.geometry("1040x680")
    root.minsize(760, 460)
    browser = QuestBrowser(root)
    browser.pack(fill="both", expand=True, padx=12, pady=12)
    browser.show("Main_UnlockFastTravel")
    root.mainloop()


if __name__ == "__main__":
    main()
