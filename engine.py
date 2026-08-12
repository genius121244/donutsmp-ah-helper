"""
engine.py
The macro itself, as a state machine.

The old version was one long list of clicks: open the order, shift-click
nine fixed spots, sell nine times. It never looked at the screen, so if a
click missed or the order ran out it kept going and sold air - or worse,
sold at a price read from a tooltip that was never there.

Here every state has to prove its result before the next one runs:

  CHECKING_HOTBAR    how many items are missing, read off the hotbar
  PICKING_UP_ORDER   shift-click order slot N (slots consumed 1 -> 9)
  VERIFYING_PICKUP   occupied hotbar slots must have gone up by exactly 1
  CHECKING_PRICE     hover the shop item, read the cheapest listing
  CALCULATING_PRICE  apply the undercut, floor and cap
  SELLING            /ah sell for each item in the batch
  VERIFYING_SALE     the hotbar slot just sold must now be empty
  CHECKING_MONEY     read the balance while the sell GUI is clean
  CHECKING_ORDER     are there any items left in the order
  ORDER_EMPTY        done: notify and stop
  ERROR              something couldn't be verified: stop, don't guess

When a check fails it retries within the configured limit, then stops.
Nothing here ever clicks somewhere else hoping to recover, because the
failure modes that matter (wrong GUI open, order gone) all end with real
money listed at a wrong price.
"""

import time

import pyautogui

import config
import detect
import ocr
import pricing
import screen
import slots
from actions import Actions, Stopped
from applog import log
from stats import SessionStats
from webhook import Webhook

IDLE = "IDLE"
STARTING = "STARTING"
CHECKING_HOTBAR = "CHECKING_HOTBAR"
PICKING_UP_ORDER = "PICKING_UP_ORDER"
VERIFYING_PICKUP = "VERIFYING_PICKUP"
CHECKING_PRICE = "CHECKING_PRICE"
CALCULATING_PRICE = "CALCULATING_PRICE"
SELLING = "SELLING"
VERIFYING_SALE = "VERIFYING_SALE"
CHECKING_MONEY = "CHECKING_MONEY"
CHECKING_ORDER = "CHECKING_ORDER"
ORDER_EMPTY = "ORDER_EMPTY"
ERROR = "ERROR"
STOPPED = "STOPPED"


class UnexpectedState(RuntimeError):
    """A state couldn't confirm its result after every retry. The macro
    stops rather than continuing on an assumption."""


class Engine:
    """One run of the macro. Create, call run(), throw away."""

    def __init__(self, settings, is_running, is_paused=None,
                 on_state=None, on_stats=None):
        self.settings = settings
        self.is_running = is_running
        self.is_paused = is_paused or (lambda: False)
        self.on_state = on_state
        self.on_stats = on_stats

        self.item = config.active_item(settings)
        if self.item is None:
            raise RuntimeError("No item configured. Add one in the AH Flip tab.")

        self.actions = Actions(settings, self._running_and_unpaused, self.item)
        self.webhook = Webhook(settings)
        self.stats = SessionStats(self.item.get("name", "?"))
        self.state = IDLE
        self._last_summary = time.time()

    # -- plumbing --------------------------------------------------------

    def _running_and_unpaused(self):
        """Actions treat 'paused' as 'not running' so they stop between
        steps instead of freezing halfway through a shift-click."""
        return self.is_running() and not self.is_paused()

    def set_state(self, state):
        self.state = state
        self.stats.phase = state
        log.info(f"State -> {state}")
        if self.on_state:
            self.on_state(state)
        self._push_stats()

    def _push_stats(self):
        if self.on_stats:
            self.on_stats(self.stats)

    def _wait_while_paused(self):
        while self.is_running() and self.is_paused():
            time.sleep(0.1)
        if not self.is_running():
            raise Stopped()

    def _retry_limit(self, key, default):
        return int((self.settings.get("general") or {}).get(key, default))

    def _maybe_summary(self):
        interval = self.webhook.summary_interval_seconds()
        if interval and time.time() - self._last_summary >= interval:
            self._last_summary = time.time()
            self.webhook.session_summary(self.stats)
            log.info("Sent periodic session summary to Discord")

    # -- detection -------------------------------------------------------

    def read_hotbar(self):
        states = slots.read_hotbar(self.settings, self.item)
        if slots.has_unknown(states):
            raise UnexpectedState(
                f"Hotbar slot state unclear ({states}). The slot boxes may be "
                f"misaligned, or the empty-slot reference doesn't match your "
                f"GUI scale / resource pack."
            )
        log.info(f"Hotbar: {slots.count(states, detect.OCCUPIED)} occupied, "
                 f"{slots.count(states, detect.EMPTY)} empty")
        return states

    def read_order(self):
        states = slots.read_order(self.settings, self.item)
        if slots.has_unknown(states):
            raise UnexpectedState(
                f"Order slot state unclear ({states}). Check the order slot "
                f"boxes and the empty-order-slot reference image."
            )
        occupied = slots.occupied_slots(states)
        self.stats.order_state = f"{len(occupied)} slot(s) left" if occupied else "empty"
        log.info(f"Order: slots {occupied} still have items" if occupied
                 else "Order: no items left")
        return states

    # -- states ----------------------------------------------------------

    def _choose_order_menu_option(self):
        """Pick the matching option using one reference image and two match
        boxes. The order menu shows both partial/full choices; whichever box
        looks closest to the saved reference is clicked."""
        template_path = config.get_template_path(self.settings, "order_menu_ref")
        if not template_path:
            return

        template = detect.load_template(template_path)
        best_region = None
        best_score = None
        for name in ("order_partial", "order_full"):
            region_key = f"{name}_region"
            region = config.get_region(self.settings, region_key, self.item)
            if not region:
                continue

            screen_image = screen.grab(tuple(region))
            score = detect.difference(screen_image, template)
            log.info(f"Order menu match '{name}': difference={score:.2f}")
            if best_score is None or score < best_score:
                best_region = region
                best_score = score

        if best_region is None:
            return

        x1, y1, x2, y2 = best_region
        self.actions.click((x1 + x2) // 2, (y1 + y2) // 2)

    def open_order_gui(self):
        """/order, then the two menu clicks and the partial/full choice."""
        self.actions.send_command("order")
        self.actions.click_point("order_menu_click1")
        self.actions.click_point("order_menu_click2")
        self._choose_order_menu_option()

    def pick_up(self, order_slot, before_states):
        """Take one order slot and prove the hotbar changed.

        The proof is 'occupied hotbar slots went up by exactly one'. Not
        'up by at least one' - two at once means a shift-click landed on
        the wrong slot, and continuing would sell an item the user didn't
        mean to list.
        """
        self.set_state(PICKING_UP_ORDER)
        expected = slots.count(before_states, detect.OCCUPIED) + 1
        limit = self._retry_limit("pickup_retry_limit", 3)

        for attempt in range(1, limit + 1):
            x, y = self.actions.require_point(f"order_slot_{order_slot}")
            log.info(f"Taking order slot {order_slot} (attempt {attempt}/{limit})")
            self.actions.shift_click(x, y)

            self.set_state(VERIFYING_PICKUP)
            self.actions.wait("inventory_settle")
            after = self.read_hotbar()
            occupied = slots.count(after, detect.OCCUPIED)

            if occupied == expected:
                log.success(f"Pickup verified - hotbar now {occupied}/9 occupied")
                return after
            if occupied > expected:
                raise UnexpectedState(
                    f"Hotbar gained {occupied - expected + 1} items from one "
                    f"shift-click on order slot {order_slot}. Stopping before "
                    f"anything unintended gets listed."
                )
            log.warning(f"Pickup did not register (hotbar still {occupied}/9), retrying")
            self.set_state(PICKING_UP_ORDER)

        raise UnexpectedState(
            f"Order slot {order_slot} did not move an item into the hotbar "
            f"after {limit} attempts. Check the order slot click point."
        )

    def fill_hotbar(self):
        """Top the hotbar up to the batch size. Returns (items in hotbar,
        whether the order came up short)."""
        self.set_state(CHECKING_HOTBAR)
        self.open_order_gui()
        hotbar = self.read_hotbar()
        batch_size = int(self.item.get("batch_size", 9))
        needed = slots.pickups_needed(hotbar, batch_size)

        if needed == 0:
            log.info(f"Hotbar already holds a full batch of {batch_size}")
        else:
            log.info(f"Need {needed} more item(s) to reach a batch of {batch_size}")

        self.set_state(CHECKING_ORDER)
        order = self.read_order()
        take, short = slots.plan_pickups(hotbar, order, batch_size)

        if short:
            log.warning(f"Order only has {len(take)} item(s) left - this will be "
                        f"a partial final batch")

        for order_slot in take:
            self._wait_while_paused()
            hotbar = self.pick_up(order_slot, hotbar)

        self.actions.close_menu()
        return slots.count(hotbar, detect.OCCUPIED), short

    def read_market_price(self):
        """Hover the shop tooltip and read the cheapest listing while /shop
        remains open. The caller decides whether to keep waiting or close it.
        """
        self.set_state(CHECKING_PRICE)
        region = self.actions.require_region("price_tooltip_region")
        hover = config.get_hover_point(self.settings, "price_tooltip_region", self.item)

        if hover:
            self.actions.hover(hover[0], hover[1])
        else:
            # Older configs kept the hover spot as a plain click point.
            self.actions.hover(*self.actions.require_point("shop_hover_item"))
        self.actions.wait("hover")

        price = ocr.get_lowest_price(region)

        if price is None:
            log.warning("Could not read a trustworthy market price")
            self.webhook.detection_error("Market price could not be read from the shop tooltip.")
        else:
            self.stats.market_price = price
            log.info(f"Market price: ${price:,}")
        self._push_stats()
        return price

    def determine_listing_price(self):
        """The price string to type into /ah sell, or None if stopped.

        The /shop window stays open for the whole wait loop so the tooltip can
        keep being re-read while the price is below the floor. Only once the
        price is acceptable do we close it and proceed to the sell command.
        """
        self.actions.send_command("shop")
        try:
            while self._running_and_unpaused():
                price = self.read_market_price()

                if price is None:
                    if not self.item.get("use_ocr_undercut", True):
                        break
                    fallback = str(self.item.get("sell_price", "")).strip()
                    if fallback:
                        log.warning(f"Falling back to the fixed sell price {fallback}")
                        return fallback
                    raise UnexpectedState(
                        "No readable market price and no fixed sell price set. "
                        "Stopping rather than listing at a guessed price."
                    )

                self.set_state(CALCULATING_PRICE)
                decision = pricing.decide(price, self.item)
                log.info(f"{decision.action.upper()}: {decision.reason}")

                if decision.action == pricing.WAIT:
                    self.stats.phase = "WATCHING"
                    self._push_stats()
                    self.actions.wait("watch")
                    continue

                self.stats.listing_price = decision.price
                self._push_stats()
                return ocr.format_price(decision.price)

            if not self.item.get("use_ocr_undercut", True):
                return str(self.item.get("sell_price", "32k"))
            return None
        finally:
            self.actions.close_menu()

    def read_money(self):
        """The balance, if a money box is configured. Optional: not every
        setup has one, and a missing balance is not a reason to stop."""
        region = config.get_region(self.settings, "money_region", self.item)
        if not region:
            return None
        hover = config.get_hover_point(self.settings, "money_region", self.item)
        if hover:
            self.actions.hover(hover[0], hover[1])
            self.actions.wait("hover")
        money = ocr.get_money(tuple(region))
        if money is None:
            log.warning("Money box did not read a balance")
        else:
            self.stats.record_money(money)
            log.info(f"Money: ${money:,}")
        self._push_stats()
        return money

    def sell_one(self, slot, listing_price):
        """Select a hotbar slot and sell it. We intentionally do not re-read
        the hotbar immediately after sending /ah sell, because the inventory
        refresh can lag behind the click and a stale hotbar state is not a
        valid reason to declare the sale failed."""
        self.set_state(SELLING)
        self.actions.select_hotbar_slot(slot)
        log.info(f"Selling hotbar slot {slot} at {listing_price}")
        self.actions.send_command(f"ah sell {listing_price}")
        self.actions.wait("sell")
        return True

    def sell_batch(self):
        """List each currently occupied hotbar slot in order. We take one
        snapshot of the hotbar, then sell slot-by-slot without re-reading the
        hotbar mid-loop; that keeps the sequence stable and prevents false
        retries on stale inventory data."""
        self.set_state(CHECKING_MONEY)
        self.read_money()

        states = self.read_hotbar()
        to_sell = slots.occupied_slots(states)
        if not to_sell:
            self.set_state(CHECKING_MONEY)
            self.read_money()
            self._push_stats()
            return 0

        sold = 0
        for slot in to_sell:
            self._wait_while_paused()
            self.actions.select_hotbar_slot(slot)
            listing_price = self.determine_listing_price()
            if listing_price is None:
                break
            self.sell_one(slot, listing_price)
            sold += 1

        self.set_state(CHECKING_MONEY)
        self.read_money()
        if sold:
            self.stats.record_batch(sold)
        self._push_stats()
        return sold

    def order_is_empty(self):
        """Look at the order GUI itself - never at a counter the macro
        keeps, which goes stale the moment the user takes items by hand."""
        self.set_state(CHECKING_ORDER)
        self.open_order_gui()
        states = self.read_order()
        self.actions.close_menu()
        return not slots.occupied_slots(states)

    # -- main loop -------------------------------------------------------

    def run(self):
        stop_reason = "stopped by user"
        try:
            self.set_state(STARTING)
            log.info(f"Starting macro for '{self.item.get('name')}' "
                     f"(batch size {self.item.get('batch_size', 9)})")
            self.webhook.macro_started(self.item.get("name"), self.item.get("batch_size", 9))

            while self.is_running():
                self._wait_while_paused()

                in_hotbar, short = self.fill_hotbar()

                if in_hotbar == 0:
                    if self.order_is_empty():
                        return self._finish_order_empty()
                    log.warning("Hotbar is empty but the order still has items - "
                                "stopping so nothing runs blind")
                    raise UnexpectedState(
                        "Could not move any items out of the order into the hotbar."
                    )

                self.sell_batch()

                if short and self.order_is_empty():
                    return self._finish_order_empty()

                self._maybe_summary()

                if not (self.settings.get("general") or {}).get("keep_cycling", True):
                    stop_reason = "single cycle finished"
                    break

                self.actions.wait("cycle")

        except Stopped:
            stop_reason = "stopped by user"
        except (UnexpectedState, slots.SlotReadError) as e:
            self.set_state(ERROR)
            log.error(str(e))
            self.webhook.unexpected_state(str(e))
            self.set_state(STOPPED)
            return ERROR
        except pyautogui.FailSafeException:
            stop_reason = "fail-safe triggered (mouse moved to a screen corner)"
            log.warning(stop_reason)
            self.webhook.emergency_stop(stop_reason)
        except Exception as e:
            self.set_state(ERROR)
            log.error(f"Unhandled error: {e}")
            self.webhook.unexpected_state(str(e))
            self.set_state(STOPPED)
            raise

        log.info(f"Macro stopped: {stop_reason}")
        self.webhook.macro_stopped(stop_reason, self.stats)
        self.set_state(STOPPED)
        return STOPPED

    def _finish_order_empty(self):
        self.set_state(ORDER_EMPTY)
        self.stats.order_state = "empty"
        log.success(f"Order for '{self.item.get('name')}' is empty - "
                    f"{self.stats.items_sold} item(s) sold this session")
        self.webhook.order_emptied(self.stats)
        self.set_state(STOPPED)
        return ORDER_EMPTY


def run(settings, is_running, is_paused=None, on_state=None, on_stats=None,
        on_error=None):
    """Entry point for the GUI thread."""
    try:
        return Engine(settings, is_running, is_paused=is_paused,
                      on_state=on_state, on_stats=on_stats).run()
    except Exception as e:
        log.error(str(e))
        if on_error:
            on_error(str(e))
        return ERROR
