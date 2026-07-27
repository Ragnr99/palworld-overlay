# Palworld Type Chart Overlay

An always-on-top, click-through diagram of Palworld's element chart, pinned to the
top-left of the screen. No window frame and no background panel: just colored
nodes and arrows over whatever is behind them.

The mouse passes straight through it, so it can't be clicked, dragged, focused,
or alt-tabbed to. It never steals focus from the game.

Once installed it runs itself: the watcher starts the chart when Palworld
launches, and the chart quits when Palworld does.

## Run it

Set and forget (see [Autostart](#autostart)), or by hand:

| | |
| --- | --- |
| **Overlay Watcher.bat** | waits for Palworld, then starts the chart |
| **Palworld Overlay.bat** | starts the chart right now, no waiting |

Stdlib only (tkinter + ctypes), nothing to install.

## How the pieces fit

| File | Job |
| --- | --- |
| `overlay.py` | draws the chart, handles hotkeys, hides on menus, quits with the game |
| `watcher.py` | idles until Palworld appears, then launches `overlay.py` |
| `gamestate.py` | the Win32 bit both of them ask: is the game running, is a UI open |
| `icons/` | the nine element icons |

Idle cost is the watcher alone, about 12 MB, asleep 5 seconds at a time. The
overlay (about 24 MB) only exists while you're in the game.

## Hotkeys

| Key | Does |
| --- | --- |
| `Ctrl+Alt+P` | show / hide |
| `Ctrl+Alt+Shift+P` | quit |

The hotkeys are global, so they work while Palworld has focus. Since the window
is click-through and hidden from the taskbar, `Ctrl+Alt+Shift+P` is the way out.

## Auto-hide

With `AUTO_HIDE = True` the chart is only up during actual gameplay. It hides
the moment you open anything (inventory, Pal box, map, build menu, pause) and
whenever Palworld isn't the focused window.

It works off **cursor visibility**: Palworld hides the mouse cursor during
gameplay and shows it as soon as any UI opens, so `GetCursorInfo` is the whole
detector. No game hooks, no memory reading, no injection, two syscalls per tick.
The focused window's *executable path* is checked rather than its title, because
Palworld's window title is literally `"Pal  "` and a browser tab on the wiki
would otherwise match it.

Because the overlay stays hidden while the game isn't focused, it would be
invisible on the desktop with nothing to react to. Two escape hatches: it always
shows for the first `HINT_SECONDS` after launch so you get confirmation it
started, and `AUTO_HIDE = False` pins it up permanently.

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

`overlay.py` also carries a full set of hand-drawn vector glyphs as a fallback.
Any element missing from `icons/` falls back to its drawn glyph, so deleting a
file is a safe way to compare the two.

Re-downloading them (the CDN serves WebP unless you ask for PNG, and Tk can't
read WebP):

```powershell
Invoke-WebRequest -Uri 'https://static.wikia.nocookie.net/palworld/images/5/5e/Fire_icon.png/revision/latest?format=original' `
  -OutFile icons\fire.png -Headers @{ Accept = 'image/png' }
```

## Tweaking

Settings live in a block at the top of `overlay.py`:

| Setting | Default | Notes |
| --- | --- | --- |
| `POS` | `(282, 24)` | top-left corner on screen; tucked just right of the party EXP bars, which end around x=274 on a 1920x1080 client area |
| `OFFSET_WIDTHS` | `0` | extra shift right, in multiples of its own width |
| `SCALE` | `0.75` | icons land on 24px here; `1.0` gives native 48px |
| `AUTO_HIDE` | `True` | hide whenever a game UI is open (see below) |
| `GAME_EXE` | `"palworld"` | matched against the focused window's exe path |
| `OPACITY` | `0.92` | lower is more see-through |
| `START_HIDDEN` | `False` | launch hidden and wait for the hotkey |
| `HINT_SECONDS` | `6` | launch hotkey reminder; `0` disables it |
| `EXIT_WITH_GAME` | `True` | quit once Palworld's process is gone |

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
