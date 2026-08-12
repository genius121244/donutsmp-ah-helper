"""
pricing.py
Works out what to list at, given the market price the OCR read.

Pure arithmetic, no screen and no input, so the rules that decide how much
of your money is on the line are testable on their own.

The three original behaviours are unchanged:
  - undercut the cheapest listing by a fixed amount or a percentage
  - never list below min_price: wait for the market to move instead
  - never list above max_price: list at the cap immediately
"""

SELL = "sell"
WAIT = "wait"          # under the floor - keep watching, don't list
CAPPED = "capped"      # over the ceiling - list at the cap


class Decision:
    """What to do with one market price reading."""

    def __init__(self, action, price=None, market_price=None, reason=""):
        self.action = action
        self.price = price
        self.market_price = market_price
        self.reason = reason

    @property
    def should_sell(self):
        return self.action in (SELL, CAPPED)

    def __repr__(self):
        return f"Decision({self.action}, price={self.price}, reason={self.reason!r})"


def undercut(market_price, mode="fixed", amount=1000, percent=2.0):
    """The market price reduced by the configured undercut, as an int."""
    if mode == "percent":
        return int(market_price - (market_price * (float(percent) / 100)))
    return int(market_price - int(amount))


def decide(market_price, item):
    """Decision for one market reading against an item's configuration."""
    mode = item.get("undercut_mode", "fixed")
    amount = item.get("undercut_amount", 1000)
    percent = item.get("undercut_percent", 2.0)
    min_price = int(item.get("min_price", 0) or 0)
    max_price = int(item.get("max_price", 0) or 0)

    price = undercut(market_price, mode, amount, percent)

    if max_price > 0 and price > max_price:
        return Decision(CAPPED, max_price, market_price,
                        f"undercut {price} is above the {max_price} cap")

    if price < min_price:
        return Decision(WAIT, None, market_price,
                        f"undercut {price} is below the {min_price} floor")

    by = f"{percent}%" if mode == "percent" else str(amount)
    return Decision(SELL, price, market_price, f"undercutting {market_price} by {by}")
