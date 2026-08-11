# Palworld Overlay

Always-on-top, click-through overlays for Palworld, with a panel to position and
size them. Right now there's one overlay: a diagram of the element chart. No
window frame and no background panel, just colored nodes and arrows over
whatever is behind them.

The mouse passes straight through, so an overlay can't be clicked, dragged,
focused, or alt-tabbed to. It never steals focus from the game.

The panel also carries a [quest browser](#quests) - all 117 quests as a tree,
with walkthroughs and links between them.

Once installed it runs itself: the watcher starts the overlay when Palworld
launches, and the overlay quits when Palworld does.

## Run it

Set and forget (see [Autostart](#autostart)), or by hand:

| | |
| --- | --- |
| **Overlay Watcher.bat** | waits for Palworld, then starts the overlay |
| **Palworld Overlay.bat** | starts the overlay right now, no waiting |
| **Overlay Settings.bat** | opens the control panel (or press `Ctrl+Alt+O`) |

Stdlib only (tkinter + ctypes), nothing to install.

## How the pieces fit

Two processes that never talk directly. The panel writes `settings.json`, the
overlay stats it once a tick and reloads when the mtime moves, so sliders move
the real thing while you watch. The panel therefore works with the game closed,
and a panel crash can't take the overlay down.

```
watcher.py  (resident, ~12 MB, asleep 5s at a time)
   |-- Ctrl+Alt+O ---> panel.py       (on demand)
   |                      | writes
   |                  settings.json
   |                      | mtime poll, 250 ms
   '-- game starts --> overlay.py     (reads, applies live)
```

| File | Job |
| --- | --- |
| `overlay.py` | windows, Win32 plumbing, tick loop. Draws nothing itself |
| `panel.py` | the two-tab window: settings, and the quest browser |
| `modules/` | what actually gets drawn, one module per overlay |
| `questbrowser.py` | the Quests tab: quest tree, walkthroughs, cross-links |
| `questdata.py` | the quest graph - ordering, questgiver lines, what's related |
| `data/quests.json` | 117 quests, generated; the browser reads only this |
| `tools/fetch_quests.py` | regenerates that file. The only thing here that uses the network |
| `settings.py` | load, coerce, save; the contract between the two processes |
| `watcher.py` | idles until Palworld appears, then launches `overlay.py` |
| `gamestate.py` | the Win32 bit they ask: is the game running, is a UI open |
| `hotkeys.py` | global hotkeys with no window, shared by watcher and overlay |
| `launcher.py` | spawning a sibling script without loading tkinter to do it |
| `icons/` | the nine element icons |

Idle cost is the watcher alone, about 12 MB, asleep 5 seconds at a time. The
overlay (about 24 MB) only exists while you're in the game, and the panel only
while it's open.

## Hotkeys

| Key | Does |
| --- | --- |
| `Ctrl+Alt+P` | show / hide |
| `Ctrl+Alt+O` | open the settings panel |
| `Ctrl+Alt+Shift+P` | quit |

The hotkeys are global, so they work while Palworld has focus. Since the windows
are click-through and hidden from the taskbar, `Ctrl+Alt+Shift+P` is the way out.

`Ctrl+Alt+O` is registered by the watcher, so it works with Palworld closed. The
overlay asks for the same key as a fallback for when the watcher isn't up, and
whichever gets there first wins - either one opens the same panel.

## Settings

Everything is on the panel: position, size and opacity per module, plus the
general behaviour toggles. Changes land on a running overlay within a quarter
second, and `settings.json` sits next to the scripts (gitignored - it's yours).

While the panel has focus the overlay stays on screen even with "Only while
playing" on, since otherwise focusing the panel would hide the very thing you're
positioning.

| Setting | Default | Notes |
| --- | --- | --- |
| Position X / Y | `282, 24` | top-left corner on screen; tucked just right of the party EXP bars, which end around x=274 on a 1920x1080 client area. Sliders span every monitor |
| Size | `0.75` | icons land on 24px here; `1.0` gives native 48px |
| Opacity | `0.92` | lower is more see-through |
| Element names | on | off shrinks the chart a fair bit |
| Settings hotkey in the middle | on | small `CTRL+ALT+O` reminder in the empty centre of the ring; hides itself under about 0.45 size, where it would overlap the glyphs |
| Only while playing | on | hide whenever a game UI is open (see below) |
| Close with Palworld | on | quit once Palworld's process is gone |
| Hotkey reminder | `6 s` | launch reminder; `0` hides it |

Every slider has a typable box next to it for when you know the number you want.
Enter or clicking away commits it, Escape cancels, and anything unparseable
reverts to the live value rather than snapping back to the default. The unit is
stripped on the way in, so pasting `282 px` back works. Arrow keys nudge a
focused slider by exactly one step.

Position sliders span the whole virtual desktop, second monitors included, so
the range goes negative when a monitor sits left of the primary one.

## Quests

The panel's second tab is a browser for all 117 quests: the main story in the
order you meet it, side missions shelved under whoever hands them out, and a
page per quest with its briefing, its objectives as numbered steps with map
coordinates, its rewards, and every quest it connects to as a link. Following
links keeps history, so `Backspace` walks back out.

It's in the panel and not on the overlay because overlay windows are
click-through by design, and a quest tree you can't click is a poster.

### Where the data comes from

`data/quests.json`, generated by `tools/fetch_quests.py` from
[paldb.cc](https://paldb.cc/en/Mission), which publishes a datamine of the
game's own `DT_PalQuestData`. Each quest keeps its internal id (`Main_UnlockFastTravel`,
`Sub_Farmer04`) rather than just its display name, so the snapshot survives a
site redesign and can be diffed against the `.pak`.

Regenerate it when Palworld updates:

```
py -3.10 tools/fetch_quests.py
```

Nothing else in the project touches the network - the browser reads the snapshot,
so it works offline and opens instantly.

### What the data can and can't tell you

Palworld doesn't have a sprawling branching quest tree, and it's worth saying so
plainly:

- The **58 main missions** are essentially one chain about 30 quests long. paldb
  records two tutorial entry points that run separately for a dozen steps and
  then converge; the browser reads from the one a new save actually opens with
  and lists the other behind it. Neither is hidden - `questdata.MAIN_ENTRY` picks
  which leads.
- **57 of the 59 side missions have no recorded links at all.** What unlocks them
  lives in Blueprint graphs the datamine never reached. Rather than invent edges,
  the browser groups them by questgiver (their ids carry it) and offers a
  **Nearby** list built from objective coordinates - if two quests happen within
  150 units of each other, that's a real "while you're here".

Two known gaps, both cosmetic:

- Briefings contain 68 unresolved name placeholders, shown as `{KingWhale}`.
  They're the game's own substitution tokens and paldb ships them unmade. The
  ids often aren't display names - `KingWhale` is the Pal you know as Panthalus -
  so they're left visibly unresolved rather than guessed at. Fixing them properly
  means pulling `DT_ItemNameText` / `DT_PalNameText` out of the `.pak`.
- A handful of objectives are `？？？`, which is paldb declining to spoil a step.

### Checking it against the game files

The snapshot was cross-checked against a real install. Palworld ships a plain
text manifest of everything inside its 38 GB pak:

```
<steam>\steamapps\common\Palworld\Manifest_UFSFiles_Win64.txt
```

Grepping it for `Quest` finds `DataTable/Quest/DT_PalQuestData`, a
`DT_PalQuestLocationData` beside it, and 359 quest Blueprints - 57 `BP_MainQuest_*`
and 60 `BP_SubQuest_*`, which is paldb's 58/59 to within the rounding you'd
expect. The per-quest objective lists line up too: Panthalus has eight
`BP_MainQuestBlock_DefeatKingWhale_*` assets, and its walkthrough here has the
same steps in the same order. Reading the tables themselves would need a pak
extractor (FModel or CUE4Parse); the manifest alone is enough to confirm the
shape without unpacking anything.

## Adding a module

The panel and the host are both generated from `modules/MODULES`. A new overlay
is a class and a line in that list - neither `panel.py` nor `overlay.py` changes:

```python
class Compass(Module):
    id = "compass"
    name = "Compass"
    settings = placement(x=800, y=40) + (
        Toggle("degrees", "Show degrees", True),
    )

    def draw(self, canvas, cfg):
        ...
        return width, height   # the host sizes and places the window from this
```

`placement()` supplies the enabled / position / size / opacity settings every
drawn module has. Declare anything else as `Slider`, `Toggle` or `Choice` and
the panel builds the control for it, coerces whatever ends up in the JSON, and
resets it with the rest. Each module gets its own layered window, so they can
sit anywhere on screen at their own size and opacity - Windows sets alpha per
window, so there's no other way to do it.

`draw` is called on an empty canvas whenever anything but position or opacity
changes, so it can be a plain redraw with no diffing.

## Auto-hide

With **Only while playing** on, the chart is only up during actual gameplay. It hides
the moment you open anything (inventory, Pal box, map, build menu, pause) and
whenever Palworld isn't the focused window.

It works off **cursor visibility**: Palworld hides the mouse cursor during
gameplay and shows it as soon as any UI opens, so `GetCursorInfo` is the whole
detector. No game hooks, no memory reading, no injection, two syscalls per tick.
The focused window's *executable path* is checked rather than its title, because
Palworld's window title is literally `"Pal  "` and a browser tab on the wiki
would otherwise match it.

Because the overlay stays hidden while the game isn't focused, it would be
invisible on the desktop with nothing to react to. Three escape hatches: it
always shows for the first few seconds after launch so you get confirmation it
started, it stays up while the settings panel has focus, and turning **Only
while playing** off pins it up permanently.

`Ctrl+Alt+P` still wins over all of this. Toggling off keeps it off regardless
of game state.

## Palworld must be in borderless windowed

Nothing can draw over **exclusive fullscreen** without hooking DirectX. If the
overlay disappears when you tab into the game, set Palworld's video mode to
*Borderless Window* and it will stay put.

## Reading the chart

An arrow means **beats** (1.5x damage). The whole chart is one 5-element loop
plus a chain hanging off Fire:

- Loop: Fire → Grass → Ground → Electric → Water → Fire
- Chain: Fire → Ice → Dragon → Dark → Neutral

Neutral beats nothing. Fire is the only element that beats two (Grass and Ice).
Each element's weakness is just the arrow pointing at it.

## Element symbols

`icons/` holds the real 48x48 element icons, pulled from the
[Palworld wiki](https://palworld.fandom.com/wiki/Elements). Files are named after
the element in lowercase (`fire.png`, `dragon.png`, ...). Node spacing scales off
whatever size the icons load at, so swapping in bigger or smaller art just works.

`modules/typechart.py` also carries a full set of hand-drawn vector glyphs as a
fallback. Any element missing from `icons/` falls back to its drawn glyph, so
deleting a file is a safe way to compare the two.

Re-downloading them (the CDN serves WebP unless you ask for PNG, and Tk can't
read WebP):

```powershell
Invoke-WebRequest -Uri 'https://static.wikia.nocookie.net/palworld/images/5/5e/Fire_icon.png/revision/latest?format=original' `
  -OutFile icons\fire.png -Headers @{ Accept = 'image/png' }
```

## Autostart

A shortcut in the Startup folder runs `watcher.py` at logon:

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Palworld Overlay Watcher.lnk
```

It points at `pyw.exe` directly rather than at the `.bat`, because a shortcut to
a `.bat` flashes a console window at every logon.

Delete the shortcut to undo it. To recreate:

```powershell
$s = (New-Object -ComObject WScript.Shell).CreateShortcut(
  (Join-Path ([Environment]::GetFolderPath('Startup')) 'Palworld Overlay Watcher.lnk'))
$s.TargetPath = 'C:\Windows\pyw.exe'
$s.Arguments  = '-3.10 "<repo path>\watcher.py"'
$s.WindowStyle = 7
$s.Save()
```

The watcher holds a named mutex, so a second copy exits immediately instead of
racing the first one to spawn a duplicate overlay. It launches the chart once
per game session: quit it by hand with `Ctrl+Alt+Shift+P` and it stays gone
until you next start Palworld.

## Credits

Element icons are the game's own art, from the
[Palworld Wiki](https://palworld.fandom.com/wiki/Elements). Palworld is by
Pocketpair. This is an unofficial fan tool with no affiliation, and it reads
nothing from the game process: no hooks, no injection, no memory access, just
public Win32 calls about cursor and process state.
