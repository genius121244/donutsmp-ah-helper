# What changed

The price reader no longer uses Tesseract. `ocr.py` now matches the glyphs
on screen against the actual bitmaps in your resource pack's `ascii.png`.

Minecraft draws text by stamping fixed glyph bitmaps out of that atlas and
scaling them by an integer GUI scale, so the pixels on screen *are* the
atlas pixels, just bigger. That makes reading them a dictionary lookup
rather than a recognition problem — which is why the old path needed seven
thresholds, two page-segmentation modes, a majority vote, a decimal-recovery
pass and a decimal-drop override, and still misread `27.1k` as `271k`.

## Run it

```
pip install -r requirements.txt
python main.py
```

Tesseract is no longer needed — you can uninstall it, and `pytesseract` and
`scipy` are off the requirements list.

**Keep the `Font+` folder next to the macro.** That's where the reader gets
your font from. If you switch resource packs, drop the new pack's `Font+`
folder (or just its `ascii.png`) in and the reader picks it up — no
recalibration, no code changes.

## Check it without launching the game

```
python test_ocr.py
```

This renders prices exactly the way the game does — glyphs from your atlas,
1px drop shadow, nearest-neighbour scaled — and reads them back at GUI
scales 1 through 4, plus your real `15.8K` capture in `samples/`. All 52
checks pass, including `27.1k` and `49.6m`, the two cases that were costing
you money.

## Behaviour differences worth knowing

- **A price is either read exactly or not at all.** Any glyph that isn't in
  the font comes back as `?`, and a price touching a `?` is thrown away. So
  the reader now returns `None` in situations where the old one would return
  a confident wrong number. `macro.py` already handles `None` by falling back
  to your fixed sell price.
- **Obfuscated text (`§k` scrambling) can never be read** by this or any
  other method. It returns `None`, which is correct.
- **Coloured price text** is handled: white text is preferred, and if a line
  is coloured (green/gold/red) the reader falls back to a brightness mask.
- If your capture box covers several listings, the **cheapest** price in the
  box wins, since that's the one you're undercutting.

## Files

- `mcfont.py` — new. Loads `ascii.png` and builds the glyph lookup tables.
- `ocr.py` — rewritten. Same public API (`get_lowest_price`, `parse_price`,
  `format_price`, `read_text`), so `macro.py` and `gui.py` are unchanged.
- `test_ocr.py` — new. The offline check described above.
- `samples/15.8K.png` — your capture, used as a real-data test case.
