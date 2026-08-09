# Palworld Overlay

Always-on-top, click-through overlays for Palworld, with a settings panel to
position and size them. Two of them so far: a diagram of the element chart, and
a live minimap that shows where you are without opening the in-game map. No
window frame and no background panel, just the artwork over whatever is behind
it.

The mouse passes straight through, so an overlay can't be clicked, dragged,
focused, or alt-tabbed to. It never steals focus from the game.

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
| `panel.py` | the settings window, generated from the module registry |
| `modules/` | what actually gets drawn, one module per overlay |
| `settings.py` | load, coerce, save; the contract between the two processes |
| `watcher.py` | idles until Palworld appears, then launches `overlay.py` |
| `gamestate.py` | the Win32 bit they ask: is the game running, is a UI open |
| `position.py` | where the player is, polled off the UI thread. See [Minimap](#minimap) |
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
drawn module has. Declare anything else as `Slider`, `Toggle`, `Choice` or
`Text` and the panel builds the control for it, coerces whatever ends up in the
JSON, and resets it with the rest. Each module gets its own layered window, so
they can sit anywhere on screen at their own size and opacity - Windows sets
alpha per window, so there's no other way to do it.

`draw` is called on an empty canvas whenever anything but position or opacity
changes, so it can be a plain redraw with no diffing.

A module whose picture changes on its own - not just when a setting does - sets
`live = True` and implements `update`, which the host calls ten times a second
on whatever `draw` already put on the canvas:

```python
    live = True

    def update(self, canvas, cfg):
        canvas.coords(self._marker, ...)   # move things; don't rebuild them
```

`update` runs on the UI thread, so it must not block: anything that touches the
network or disk belongs on a thread of its own, the way `position.py` does it.
Rebuilding the drawing there instead of moving it would flicker.

## Auto-hide

With **Only while playing** on, the overlay is only up during actual gameplay. It hides
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

## Minimap

A north-up minimap with you pinned at the centre, the ground scrolling under
you, a breadcrumb trail behind you and your coordinates along the bottom - in
the same numbers the in-game map shows. It is up during normal play, so you can
see where you are without stopping to open the map.

### It needs a dedicated server

This is the catch, and it is worth reading before you turn it on.

The overlay does not hook, inject into, or read the memory of the game, and it
is not going to start. That leaves exactly one place a player's live position is
legitimately published: **Palworld's dedicated-server REST API**. So the minimap
works if you play on a dedicated server - including one running on this same PC,
just for you - and it does not work in a single-player world or a co-op game
hosted from the game client, because neither of those publishes anything to read.

On the server, in `PalWorldSettings.ini`:

```ini
RESTAPIEnabled=True
RESTAPIPort=8212
AdminPassword="something"
```

Then in the panel, under **Minimap**, put in the address, the port and that same
admin password. Check it without launching anything:

```
py -3.10 position.py
```

It prints which source it built, what it asked, and either your coordinates or
why not. The map says the same thing on screen - `no server`, `bad password`,
`nobody online` - rather than sitting there empty.

### Demo mode

**Position from → Demo (no game)** walks a fake player around. It's how you
place and size the map with Palworld closed, and it separates "my overlay is
misconfigured" from "my server is". Nothing about it touches the game.

### A map image is optional

With no image you get the grid, the trail and the marker floating over the game,
covering none of it - the same principle as the type chart. Point **Map image
file** at a square, north-up PNG and it scrolls underneath instead. Tell it what
area the image covers with **Map image covers** (half its width, in map
coordinates, measured out from 0,0 at the image's centre), and flip it if it
comes out upside down. Tk only scales images by whole factors, so the zoom
snaps to the nearest one and the grid and trail follow whatever it landed on.

No map image ships with this: the game's own map is Pocketpair's art.

### If the numbers disagree with the game

The server reports raw Unreal world coordinates, which get converted into the
ones the game shows you. If the readout is offset or scaled wrong against the
in-game map, **Coordinate origin** and **Coordinate scale** at the bottom of the
section are that conversion, and correcting them fixes the map with it.

### Cost

One HTTP request every half second, on its own thread - a socket timeout against
a server that isn't there must not freeze every module on screen. The drawing
updates ten times a second, moving the canvas items `draw` already made rather
than rebuilding them.

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
public Win32 calls about cursor and process state - and, if you turn the minimap
on, your own dedicated server's REST API.
