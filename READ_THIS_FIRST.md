# DonutSMP AH macro

Download `DonutAHMacro.zip` from the [releases
page](https://github.com/genius121244/donutsmp-ah-helper/releases), unzip it
and run `DonutAHMacro.exe`. Or from source:

```
pip install -r requirements.txt
python main.py
```

The exe checks for a newer release on launch and offers to update itself
(**Settings → Updates** to check by hand or switch that off). Your settings
live outside the program, so an update never touches your coordinates.
Build one yourself with `python build.py` on Windows.

To publish a new version: set the number in `version.py`, then

```
git tag v1.1.0 && git push origin v1.1.0
```

GitHub builds the exe and creates the release; everyone running an older
copy is offered it the next time they open the program. The tag has to
match `version.py` or the build stops and says so.

Keep the `Font+` folder next to the macro — that's where the price reader
gets your font from. If you switch resource packs, drop the new pack's
`Font+` folder in and it picks it up; no recalibration, no code changes.

## Setting it up the first time

Everything is in the **Pixel / OCR** tab, and nothing needs the mouse:

1. Open the game to the screen you're configuring and press **F7** (or
   whatever you bind *Capture Screen* to in the Keybinds tab). It grabs the
   screen while Minecraft is still in front and brings the editor up with
   the shot loaded. **Capture in 5s** does the same via a countdown if you
   would rather alt-tab.
2. Pick what you're setting from the list on the left.
3. Arrow keys move it, **Shift + Arrows** resize (boxes only), **Ctrl +
   Arrows** move ten pixels at a time. **Enter** saves, **Esc** resets.
4. The panel on the right shows the whole inside of the box, blown up as
   far as it fits, so you can see whether an edge is clipping a digit.
   **Test this selection** then reads it for real.

What you need to set before the macro will start:

- **Hotbar strip** — one box around all nine hotbar slots (it splits them
  for you). Set the nine slots individually only if your GUI is unusual.
- **Order strip** — the same thing for the order window's slots.
- **Empty hotbar slot / empty order slot** — select a box over a slot you
  know is empty and press *Save as empty-slot reference*. This is how the
  macro tells a full slot from an empty one, so capture it at the GUI scale
  you actually play at.
- **Price tooltip (OCR)** plus its **hover point**, and the click points
  for the order menu.
- **Money (OCR)** and its hover point, if you want balance tracking.

Then in **AH Flip**, set the item's batch size, undercut and minimum price.
The item name is just a label for you.

## How a cycle runs

1. Look at the nine hotbar slots and count how many are already full. The
   hotbar is the source of truth — if you left four rockets in it, the
   macro takes five, not nine.
2. Shift-click order slots in order, 1 → 9, and after **every** click
   re-check the hotbar. Occupied slots must go up by exactly one; if they
   don't, it retries and then stops. It never sells on an unverified
   pickup.
3. Read the cheapest listing with the font reader, subtract your undercut,
   and check it against your floor. Below the floor it waits instead of
   selling.
4. Sell the batch, verifying each slot actually emptied.
5. Read your balance while the sell GUI is up (that's the cleanest moment
   to read it), then start again.

When the order runs out it sells the short batch, confirms the order
window is empty by looking at it, sends the Discord notification and stops.
The visual check is what decides that, not a counter — you may have taken
items out of the order yourself.

## When something is off, it stops

Unreadable price, a slot it can't classify, a pickup that didn't register,
a coordinate that was never configured: all of these stop the macro and say
why in the log. Nothing guesses and nothing clicks hopefully.

That's also why a slot can come back "unknown". The two numbers in
**Settings → Detection** are the tolerance: below the first a slot counts
as empty, above the second as occupied, and anything in between is a
refusal to guess. Widen the gap if you get spurious stops, narrow it if a
full slot is being read as empty.

## Checking it without the game

```
python test_ocr.py     # the font reader: 52 checks
python test_macro.py   # detection, pickup rules, pricing, config, webhook
```

## The price reader

`ocr.py` doesn't recognise text, it looks it up. Minecraft draws text by
stamping fixed glyph bitmaps out of `ascii.png` and scaling them by an
integer GUI scale, so the pixels on screen *are* the atlas pixels, just
bigger — shrink them back down and each character matches one in the file
exactly.

Consequences worth knowing:

- A price is either read exactly or not at all. An unknown glyph comes back
  as `?`, and a price touching a `?` is thrown away, so you get `None`
  where Tesseract would have given you a confident wrong number.
- Obfuscated text (`§k`) can't be read by this or anything else.
- Coloured price text is fine; white is preferred, colours fall back to a
  brightness mask.
- If the box covers several listings, the cheapest wins — that's the one
  you're undercutting.

## Files

- `main.py` → `ui/` — the window and its six tabs.
- `engine.py` — the state machine: what happens next and what must be true
  first. `actions.py` does the actual clicking.
- `detect.py` / `slots.py` — is this slot empty, and which ones to take.
- `ocr.py` / `mcfont.py` — the font reader.
- `pricing.py` — undercut and floor arithmetic, no side effects.
- `config.py` — settings, stored in `%APPDATA%\DonutAHMacro` so updating
  the macro never wipes your coordinates.
- `webhook.py`, `applog.py`, `stats.py`, `keybinds.py`.
- `updater.py` / `build.py` / `version.py` — the exe build and self-update.
