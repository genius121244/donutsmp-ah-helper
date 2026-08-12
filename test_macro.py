"""
test_macro.py
Offline tests for everything that isn't the font reader (that has its own
suite in test_ocr.py, which must keep passing 52/52).

  python test_macro.py

No Minecraft, no screen and no clicking: slot images are generated, and
the pieces that talk to the screen are the ones deliberately kept separate
from the pieces that decide what to do, so the decisions can be tested on
their own.
"""

import json
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

import numpy as np
from PIL import Image

import config
import detect
import fontpack
from ui import theme
import keybinds
import pricing
import slots
import updater
import webhook
from stats import SessionStats

SLOT_SIZE = (36, 36)
EMPTY_GREY = (139, 139, 139)


def empty_slot(noise=0):
    """An empty slot, optionally jittered to imitate the small differences
    between two screenshots of the same slot."""
    array = np.full((SLOT_SIZE[1], SLOT_SIZE[0], 3), EMPTY_GREY, dtype=np.int16)
    if noise:
        rng = np.random.default_rng(1)
        array += rng.integers(-noise, noise + 1, array.shape)
    return Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))


def occupied_slot():
    """An empty slot with an item sprite stamped in the middle."""
    array = np.full((SLOT_SIZE[1], SLOT_SIZE[0], 3), EMPTY_GREY, dtype=np.uint8)
    array[8:28, 8:28] = (200, 60, 40)
    return Image.fromarray(array)


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.template = empty_slot()

    def test_identical_slot_is_empty(self):
        state, diff = detect.classify(empty_slot(), self.template)
        self.assertEqual(state, detect.EMPTY)
        self.assertEqual(diff, 0.0)

    def test_slightly_different_slot_is_still_empty(self):
        # Two screenshots of the same empty slot are never byte-identical.
        state, _ = detect.classify(empty_slot(noise=4), self.template)
        self.assertEqual(state, detect.EMPTY)

    def test_item_in_slot_is_occupied(self):
        state, diff = detect.classify(occupied_slot(), self.template)
        self.assertEqual(state, detect.OCCUPIED)
        self.assertGreater(diff, 18.0)

    def test_ambiguous_slot_is_unknown_not_guessed(self):
        # Between the thresholds the answer is "don't know" - the engine
        # stops rather than shift-clicking on a maybe.
        array = np.full((SLOT_SIZE[1], SLOT_SIZE[0], 3), EMPTY_GREY, dtype=np.int16) + 15
        ambiguous = Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))
        state, _ = detect.classify(ambiguous, self.template)
        self.assertEqual(state, detect.UNKNOWN)

    def test_template_of_a_different_size_still_matches(self):
        # A reference captured at another GUI scale is resized, not rejected.
        small = self.template.resize((18, 18), Image.NEAREST)
        state, _ = detect.classify(empty_slot(), small)
        self.assertEqual(state, detect.EMPTY)

    def test_split_strip_gives_nine_equal_slots(self):
        boxes = detect.split_strip((100, 200, 280, 220), 9)
        self.assertEqual(len(boxes), 9)
        self.assertEqual(boxes[0], (100, 200, 120, 220))
        self.assertEqual(boxes[-1], (260, 200, 280, 220))
        self.assertTrue(all(b[2] - b[0] == 20 for b in boxes))


EMPTY, OCC = detect.EMPTY, detect.OCCUPIED


class PickupPlanningTests(unittest.TestCase):
    def test_counts_what_the_hotbar_is_missing(self):
        hotbar = [OCC] * 4 + [EMPTY] * 5
        self.assertEqual(slots.pickups_needed(hotbar, 9), 5)

    def test_hotbar_the_user_filled_by_hand_is_respected(self):
        # The macro never assumes it starts from an empty hotbar.
        self.assertEqual(slots.pickups_needed([OCC] * 9, 9), 0)
        self.assertEqual(slots.pickups_needed([OCC] * 7 + [EMPTY] * 2, 9), 2)

    def test_batch_size_below_nine(self):
        self.assertEqual(slots.pickups_needed([EMPTY] * 9, 4), 4)
        self.assertEqual(slots.pickups_needed([OCC] * 6 + [EMPTY] * 3, 4), 0)

    def test_order_slots_are_taken_in_sequence(self):
        take, short = slots.plan_pickups([EMPTY] * 9, [OCC] * 9, 9)
        self.assertEqual(take, [1, 2, 3, 4, 5, 6, 7, 8, 9])
        self.assertFalse(short)

    def test_only_occupied_order_slots_are_taken(self):
        order = [OCC, EMPTY, OCC, OCC] + [EMPTY] * 5
        take, _ = slots.plan_pickups([EMPTY] * 9, order, 9)
        self.assertEqual(take, [1, 3, 4])

    def test_partial_final_batch_is_reported(self):
        # Three left in the order, nine wanted: take three and flag it, so
        # the caller sells a short batch instead of waiting for a full one.
        order = [OCC] * 3 + [EMPTY] * 6
        take, short = slots.plan_pickups([EMPTY] * 9, order, 9)
        self.assertEqual(take, [1, 2, 3])
        self.assertTrue(short)

    def test_empty_order_yields_no_pickups(self):
        take, short = slots.plan_pickups([EMPTY] * 9, [EMPTY] * 9, 9)
        self.assertEqual(take, [])
        self.assertTrue(short)

    def test_unknown_state_is_visible_to_the_caller(self):
        self.assertTrue(slots.has_unknown([EMPTY, detect.UNKNOWN] + [OCC] * 7))
        self.assertFalse(slots.has_unknown([EMPTY] * 9))

    def test_occupied_slots_are_one_based(self):
        self.assertEqual(slots.occupied_slots([EMPTY, OCC, EMPTY, OCC] + [EMPTY] * 5),
                         [2, 4])


class LastOrdersDetectionTests(unittest.TestCase):
    def test_order_regions_support_last_orders_aliases(self):
        settings = {"regions": {
            "last_order_strip": [100, 200, 280, 220],
        }}
        boxes = slots.order_regions(settings)
        self.assertEqual(len(boxes), 9)
        self.assertEqual(boxes[0], (100, 200, 120, 220))
        self.assertEqual(boxes[-1], (260, 200, 280, 220))

    def test_macro_starts_on_orders_screen(self):
        settings = json.loads(json.dumps(config.DEFAULT_SETTINGS))
        settings["items"] = [{"name": "Rocket", "batch_size": 9, "points": {}, "regions": {}, "hover_points": {}}]
        settings["active_item"] = "Rocket"
        settings["points"]["order_menu_click1"] = [100, 200]
        settings["points"]["order_menu_click2"] = [300, 400]
        engine = __import__("engine").Engine(settings, lambda: True, lambda: False)
        engine.actions = mock.Mock()

        engine.open_order_gui()

        engine.actions.send_command.assert_called_once_with("order")
        self.assertEqual(engine.actions.click_point.call_args_list,
                         [mock.call("order_menu_click1"),
                          mock.call("order_menu_click2")])

    def test_shop_stays_open_while_waiting_for_price(self):
        settings = json.loads(json.dumps(config.DEFAULT_SETTINGS))
        settings["items"] = [{"name": "Rocket", "batch_size": 9,
                              "use_ocr_undercut": True,
                              "points": {}, "regions": {}, "hover_points": {}}]
        settings["active_item"] = "Rocket"
        settings["points"]["shop_hover_item"] = [10, 20]
        settings["regions"]["price_tooltip_region"] = [30, 40, 60, 70]
        engine = __import__("engine").Engine(settings, lambda: True, lambda: False)
        engine.actions = mock.Mock()
        engine.actions.require_region.return_value = (30, 40, 60, 70)
        engine.actions.require_point.return_value = (10, 20)
        engine.actions.hover = mock.Mock()
        engine.actions.close_menu = mock.Mock()

        with mock.patch("engine.ocr.get_lowest_price", side_effect=[50000, 51000]), \
             mock.patch("engine.pricing.decide", side_effect=[
                 __import__("pricing").Decision(__import__("pricing").WAIT, None, 50000, "too low"),
                 __import__("pricing").Decision(__import__("pricing").SELL, 49000, 51000, "ok"),
             ]):
            price = engine.determine_listing_price()

        self.assertEqual(price, "49k")
        self.assertEqual(engine.actions.send_command.call_count, 1)
        self.assertEqual(engine.actions.close_menu.call_count, 1)
        self.assertEqual(engine.actions.hover.call_count, 2)

    def test_order_menu_clicks_whichever_box_matches_the_reference(self):
        """One saved reference, two match boxes: the closer one is clicked.

        The option is picked by coordinates rather than a configured click
        point, so this asserts the centre of the winning box.
        """
        settings = json.loads(json.dumps(config.DEFAULT_SETTINGS))
        settings["items"] = [{"name": "Rocket", "batch_size": 9,
                              "points": {}, "regions": {}, "hover_points": {}}]
        settings["active_item"] = "Rocket"
        settings["regions"]["order_partial_region"] = [60, 10, 100, 30]
        settings["regions"]["order_full_region"] = [10, 10, 50, 30]
        settings["templates"]["order_menu_ref"] = "dummy-ref.png"
        engine = __import__("engine").Engine(settings, lambda: True, lambda: False)
        engine.actions = mock.Mock()

        reference = Image.new("RGB", (40, 20), (255, 0, 0))
        with mock.patch("engine.config.get_template_path", return_value="dummy-ref.png"), \
             mock.patch("engine.detect.load_template", return_value=reference), \
             mock.patch("engine.screen.grab", side_effect=[
                 Image.new("RGB", (40, 20), (250, 0, 0)),   # partial: close
                 Image.new("RGB", (40, 20), (0, 255, 0)),   # full: nothing like it
             ]):
            engine.open_order_gui()

        engine.actions.click.assert_called_once_with(80, 20)  # centre of partial

    def test_order_menu_is_left_alone_without_a_reference(self):
        """No reference saved means no idea which option is which, so the
        macro must not click a guess into the menu."""
        settings = json.loads(json.dumps(config.DEFAULT_SETTINGS))
        settings["items"] = [{"name": "Rocket", "batch_size": 9,
                              "points": {}, "regions": {}, "hover_points": {}}]
        settings["active_item"] = "Rocket"
        engine = __import__("engine").Engine(settings, lambda: True, lambda: False)
        engine.actions = mock.Mock()

        with mock.patch("engine.config.get_template_path", return_value=None):
            engine.open_order_gui()

        engine.actions.click.assert_not_called()

    def test_full_hotbar_keeps_orders_menu_open(self):
        settings = json.loads(json.dumps(config.DEFAULT_SETTINGS))
        settings["items"] = [{"name": "Rocket", "batch_size": 9,
                              "points": {}, "regions": {}, "hover_points": {}}]
        settings["active_item"] = "Rocket"
        engine = __import__("engine").Engine(settings, lambda: True, lambda: False)
        engine.actions = mock.Mock()

        with mock.patch("engine.slots.read_hotbar", return_value=[detect.OCCUPIED] * 9), \
             mock.patch("engine.slots.read_order", return_value=[detect.OCCUPIED] * 9):
            result = engine.fill_hotbar()

        self.assertEqual(result, (9, False))
        self.assertTrue(engine.actions.close_menu.called)
        self.assertEqual(engine.actions.send_command.call_count, 1)

    def test_sell_batch_selects_each_slot_before_each_sale(self):
        settings = json.loads(json.dumps(config.DEFAULT_SETTINGS))
        settings["items"] = [{"name": "Rocket", "batch_size": 9,
                              "points": {}, "regions": {}, "hover_points": {}}]
        settings["active_item"] = "Rocket"
        settings["general"]["price_check_per_sell"] = True
        engine = __import__("engine").Engine(settings, lambda: True, lambda: False)
        engine.actions = mock.Mock()
        engine.read_money = mock.Mock(return_value=None)
        engine.determine_listing_price = mock.Mock(return_value="49k")
        engine.sell_one = mock.Mock(return_value=True)

        with mock.patch("engine.slots.read_hotbar", return_value=[detect.OCCUPIED] * 9):
            engine.sell_batch()

        expected = [mock.call(i) for i in range(1, 10)]
        self.assertEqual(engine.actions.select_hotbar_slot.call_args_list, expected)
        self.assertEqual(engine.sell_one.call_count, 9)

class PickupVerificationTests(unittest.TestCase):
    """The rule the engine enforces after every shift-click: occupied slots
    must go up by exactly one."""

    @staticmethod
    def verified(before, after):
        return (slots.count(after, OCC) == slots.count(before, OCC) + 1)

    def test_successful_pickup(self):
        before = [OCC] * 4 + [EMPTY] * 5
        after = [OCC] * 5 + [EMPTY] * 4
        self.assertTrue(self.verified(before, after))

    def test_click_that_did_nothing_fails(self):
        states = [OCC] * 4 + [EMPTY] * 5
        self.assertFalse(self.verified(states, states))

    def test_two_items_at_once_fails(self):
        before = [OCC] * 4 + [EMPTY] * 5
        after = [OCC] * 6 + [EMPTY] * 3
        self.assertFalse(self.verified(before, after))


class PricingTests(unittest.TestCase):
    def item(self, **overrides):
        item = dict(config.DEFAULT_ITEM)
        item.update(overrides)
        return item

    def test_fixed_undercut(self):
        self.assertEqual(pricing.undercut(50_000, "fixed", amount=1000), 49_000)

    def test_percent_undercut(self):
        self.assertEqual(pricing.undercut(50_000, "percent", percent=2.0), 49_000)

    def test_sells_when_above_the_floor(self):
        decision = pricing.decide(50_000, self.item(undercut_amount=1000, min_price=10_000))
        self.assertEqual(decision.action, pricing.SELL)
        self.assertEqual(decision.price, 49_000)

    def test_waits_instead_of_selling_below_the_floor(self):
        # The whole point of the floor: it must never be rounded away.
        decision = pricing.decide(11_000, self.item(undercut_amount=2000, min_price=10_000))
        self.assertEqual(decision.action, pricing.WAIT)
        self.assertIsNone(decision.price)
        self.assertFalse(decision.should_sell)

    def test_floor_is_inclusive(self):
        decision = pricing.decide(11_000, self.item(undercut_amount=1000, min_price=10_000))
        self.assertEqual(decision.action, pricing.SELL)
        self.assertEqual(decision.price, 10_000)

    def test_caps_instead_of_listing_above_the_ceiling(self):
        decision = pricing.decide(90_000, self.item(undercut_amount=1000, max_price=50_000))
        self.assertEqual(decision.action, pricing.CAPPED)
        self.assertEqual(decision.price, 50_000)
        self.assertTrue(decision.should_sell)

    def test_zero_cap_means_no_cap(self):
        decision = pricing.decide(90_000, self.item(undercut_amount=1000, max_price=0))
        self.assertEqual(decision.action, pricing.SELL)
        self.assertEqual(decision.price, 89_000)


class MoneyParsingTests(unittest.TestCase):
    def test_reads_a_balance_with_separators(self):
        import ocr
        self.assertEqual(ocr.parse_money("$12,345,678"), 12_345_678)

    def test_takes_the_balance_not_the_change_indicator(self):
        import ocr
        self.assertEqual(ocr.parse_money("$1,204,000  +32.5k"), 1_204_000)

    def test_unreadable_glyph_is_skipped(self):
        import ocr
        self.assertIsNone(ocr.parse_money("$1?4,000"))

    def test_a_bare_number_is_still_not_a_price(self):
        # parse_price must stay strict even though parse_money is lenient.
        import ocr
        self.assertIsNone(ocr.parse_price("1204000"))


class KeybindTests(unittest.TestCase):
    def test_describes_keys_and_mouse_buttons(self):
        self.assertEqual(keybinds.describe("f8"), "F8")
        self.assertEqual(keybinds.describe("mouse:x2"), "Mouse X2")
        self.assertEqual(keybinds.describe(None), "Unassigned")

    def test_detects_a_conflict(self):
        clashes = keybinds.conflicts({"toggle": "f8", "pause": "f8", "stop": "f9"})
        self.assertEqual(list(clashes), ["f8"])
        self.assertCountEqual(clashes["f8"], ["toggle", "pause"])

    def test_unassigned_bindings_do_not_conflict(self):
        self.assertEqual(keybinds.conflicts({"a": None, "b": None}), {})


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.settings = json.loads(json.dumps(config.DEFAULT_SETTINGS))

    def test_items_can_be_added_duplicated_and_deleted(self):
        first = config.add_item(self.settings, "Rockets")
        copy = config.add_item(self.settings, source=first)
        self.assertEqual(copy["name"], "Rockets (2)")  # names stay unique

        config.delete_item(self.settings, "Rockets")
        self.assertEqual(config.item_names(self.settings), ["Rockets (2)"])

    def test_item_overrides_win_over_the_shared_value(self):
        item = config.add_item(self.settings, "Rockets")
        config.set_point(self.settings, "shop_hover_item", [10, 20])
        self.assertEqual(config.get_point(self.settings, "shop_hover_item", item), [10, 20])

        config.set_point(self.settings, "shop_hover_item", [30, 40], item)
        self.assertEqual(config.get_point(self.settings, "shop_hover_item", item), [30, 40])
        self.assertEqual(config.get_point(self.settings, "shop_hover_item"), [10, 20])

    def test_hover_point_is_separate_from_the_ocr_box(self):
        config.set_region(self.settings, "price_tooltip_region", [1, 2, 3, 4])
        config.set_hover_point(self.settings, "price_tooltip_region", [50, 60])
        self.assertEqual(config.get_region(self.settings, "price_tooltip_region"), [1, 2, 3, 4])
        self.assertEqual(config.get_hover_point(self.settings, "price_tooltip_region"), [50, 60])

    def test_everything_survives_a_save_and_reload(self):
        item = config.add_item(self.settings, "Rockets")
        item["batch_size"] = 5
        config.set_active_item(self.settings, "Rockets")
        config.set_region(self.settings, "hotbar_strip", [10, 20, 190, 40])
        config.set_point(self.settings, "order_slot_1", [11, 22])
        config.set_hover_point(self.settings, "money_region", [33, 44])
        self.settings["keybinds"]["toggle"] = "mouse:x2"
        self.settings["webhook"]["url"] = "https://example.invalid/hook"
        self.settings["timing"]["sell"] = [700, 800]

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "settings.json")
            original, config.CONFIG_PATH = config.CONFIG_PATH, path
            try:
                config.save_settings(self.settings)
                reloaded = config.load_settings()
            finally:
                config.CONFIG_PATH = original

        self.assertEqual(config.active_item(reloaded)["batch_size"], 5)
        self.assertEqual(config.get_region(reloaded, "hotbar_strip"), [10, 20, 190, 40])
        self.assertEqual(config.get_point(reloaded, "order_slot_1"), [11, 22])
        self.assertEqual(config.get_hover_point(reloaded, "money_region"), [33, 44])
        self.assertEqual(reloaded["keybinds"]["toggle"], "mouse:x2")
        self.assertEqual(reloaded["webhook"]["url"], "https://example.invalid/hook")
        self.assertEqual(config.timing(reloaded, "sell"), (700, 800))

    def test_v1_settings_are_migrated_not_lost(self):
        old = {
            "sell_price": "32k", "undercut_amount": 1500, "min_price": 20_000,
            "use_ocr_undercut": True, "order_full": True,
            "pixels": {
                "shop_hover_item": [100, 200],
                "price_tooltip_region": [10, 20, 110, 60],
            },
        }
        migrated = config._deep_merge(config.DEFAULT_SETTINGS, config._migrate(old))
        item = config.active_item(migrated)
        self.assertEqual(item["undercut_amount"], 1500)
        self.assertEqual(item["min_price"], 20_000)
        self.assertEqual(config.get_point(migrated, "shop_hover_item"), [100, 200])
        self.assertEqual(config.get_region(migrated, "price_tooltip_region"), [10, 20, 110, 60])

    def test_missing_keys_fall_back_to_defaults(self):
        merged = config._deep_merge(config.DEFAULT_SETTINGS, {"version": 2, "items": []})
        self.assertEqual(merged["detection"]["empty_slot_tolerance"],
                         config.DEFAULT_SETTINGS["detection"]["empty_slot_tolerance"])


class ConfigSharingTests(unittest.TestCase):
    """Exporting a setup for a friend, and importing theirs."""

    def setUp(self):
        self.settings = json.loads(json.dumps(config.DEFAULT_SETTINGS))
        config.add_item(self.settings, "Rockets")
        config.set_active_item(self.settings, "Rockets")
        config.set_region(self.settings, "hotbar_strip", [10, 20, 190, 40])

    def _with_template(self, folder):
        """A settings dict pointing at a real reference image on disk."""
        source = os.path.join(folder, "empty_hotbar_slot.png")
        Image.new("RGB", (20, 20), (139, 139, 139)).save(source)
        config.set_template_path(self.settings, "empty_hotbar_slot", source)
        return source

    def test_a_bundle_carries_the_reference_images_too(self):
        # The receiving machine has no copy of the sender's PNG, so an
        # export that only held paths would import as "no references".
        with tempfile.TemporaryDirectory() as folder:
            self._with_template(folder)
            bundle = os.path.join(folder, "config.zip")
            config.export_bundle(self.settings, bundle)

            with zipfile.ZipFile(bundle) as z:
                names = z.namelist()
            self.assertIn("settings.json", names)
            self.assertTrue(any(n.startswith("templates/") for n in names))

    def test_importing_repoints_templates_at_this_machine(self):
        with tempfile.TemporaryDirectory() as folder:
            sender_path = self._with_template(folder)
            bundle = os.path.join(folder, "config.zip")
            config.export_bundle(self.settings, bundle)

            receiver_dir = os.path.join(folder, "their-templates")
            original, config.TEMPLATE_DIR = config.TEMPLATE_DIR, receiver_dir
            try:
                imported = config.import_bundle(bundle)
            finally:
                config.TEMPLATE_DIR = original

            path = (imported.get("templates") or {}).get("empty_hotbar_slot")
            self.assertTrue(path.startswith(receiver_dir))
            self.assertNotEqual(path, sender_path)
            self.assertTrue(os.path.exists(path))
            self.assertEqual(config.get_region(imported, "hotbar_strip"),
                             [10, 20, 190, 40])
            self.assertEqual(config.active_item(imported)["name"], "Rockets")

    def test_a_zip_that_is_not_a_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle = os.path.join(folder, "holiday-photos.zip")
            with zipfile.ZipFile(bundle, "w") as z:
                z.writestr("beach.jpg", "not json")
            with self.assertRaises(ValueError):
                config.import_bundle(bundle)

    def test_a_template_escaping_the_folder_is_ignored(self):
        # Never write where the zip says; a crafted entry must not land a
        # file outside the template folder.
        with tempfile.TemporaryDirectory() as folder:
            bundle = os.path.join(folder, "evil.zip")
            with zipfile.ZipFile(bundle, "w") as z:
                z.writestr("settings.json", json.dumps(
                    {"version": 2, "templates": {"empty_hotbar_slot": "../../evil.png"}}))
                z.writestr("../../evil.png", "x")

            receiver_dir = os.path.join(folder, "templates")
            original, config.TEMPLATE_DIR = config.TEMPLATE_DIR, receiver_dir
            try:
                imported = config.import_bundle(bundle)
            finally:
                config.TEMPLATE_DIR = original

            path = (imported.get("templates") or {}).get("empty_hotbar_slot")
            if path:
                self.assertTrue(os.path.abspath(path).startswith(
                    os.path.abspath(receiver_dir)))
            self.assertFalse(os.path.exists(os.path.join(folder, "..", "evil.png")))


class UIScaleTests(unittest.TestCase):
    """Fitting the window onto whatever monitor it opens on."""

    def test_a_small_laptop_screen_shrinks_the_interface(self):
        scale = theme.fit_scale(1366, 768)
        self.assertLess(scale, 1.0)
        width, height = theme.window_size(1366, 768, scale)
        self.assertLessEqual(width, 1366)
        self.assertLessEqual(height, 768)

    def test_a_big_monitor_is_left_at_the_design_size(self):
        # Auto only ever shrinks: blowing the layout up to fill a 1440p
        # screen would make it worse, not better.
        self.assertEqual(theme.fit_scale(2560, 1440), 1.0)
        self.assertEqual(theme.window_size(2560, 1440, 1.0), theme.DESIGN_SIZE)

    def test_a_chosen_scale_wins_over_the_screen(self):
        self.assertEqual(theme.fit_scale(2560, 1440, 0.7), 0.7)
        self.assertEqual(theme.fit_scale(1366, 768, 1.25), 1.25)

    def test_scales_are_clamped_to_something_usable(self):
        low, high = theme.SCALE_LIMITS
        self.assertEqual(theme.fit_scale(1920, 1080, 5), high)
        self.assertEqual(theme.fit_scale(1920, 1080, 0.1), low)
        # Even a screen too small for the floor scale gets a window that
        # fits on it, rather than one with its buttons off the bottom.
        scale = theme.fit_scale(640, 480)
        self.assertEqual(scale, low)
        width, height = theme.window_size(640, 480, scale)
        self.assertLessEqual(width, 640)
        self.assertLessEqual(height, 480)

    def test_the_minimum_size_never_exceeds_the_window_size(self):
        for screen in ((1366, 768), (1920, 1080), (1280, 720)):
            scale = theme.fit_scale(*screen)
            min_w, min_h = theme.min_window_size(*screen, scale)
            width, height = theme.window_size(*screen, scale)
            self.assertLessEqual(min_w, width)
            self.assertLessEqual(min_h, height)


class FontPackTests(unittest.TestCase):
    """Installing the resource pack into Minecraft."""

    def test_installing_copies_the_whole_pack(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "Font+", "assets", "minecraft",
                                  "textures", "font")
            os.makedirs(source)
            Image.new("RGBA", (128, 128)).save(os.path.join(source, "ascii.png"))
            destination = os.path.join(folder, "resourcepacks")

            with mock.patch("fontpack.find_pack",
                            return_value=os.path.join(folder, "Font+")):
                target = fontpack.install(destination)

            self.assertTrue(os.path.exists(os.path.join(
                target, "assets", "minecraft", "textures", "font", "ascii.png")))
            self.assertTrue(fontpack.is_installed(destination))

    def test_reinstalling_replaces_the_old_copy(self):
        # Minecraft would otherwise keep showing whatever was there before.
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "Font+")
            os.makedirs(source)
            open(os.path.join(source, "pack.mcmeta"), "w").close()
            destination = os.path.join(folder, "resourcepacks")
            stale = os.path.join(destination, "Font+")
            os.makedirs(stale)
            open(os.path.join(stale, "old-file.png"), "w").close()

            with mock.patch("fontpack.find_pack", return_value=source):
                target = fontpack.install(destination)

            self.assertFalse(os.path.exists(os.path.join(target, "old-file.png")))
            self.assertTrue(os.path.exists(os.path.join(target, "pack.mcmeta")))

    def test_a_missing_pack_is_an_error_not_an_empty_install(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch("fontpack.find_pack", return_value=None):
                with self.assertRaises(FileNotFoundError):
                    fontpack.install(os.path.join(folder, "resourcepacks"))

    def test_it_refuses_when_minecraft_was_never_run(self):
        # Creating .minecraft ourselves would report success while putting
        # the pack somewhere the game never looks.
        with tempfile.TemporaryDirectory() as folder:
            missing = os.path.join(folder, "nope", ".minecraft")
            with mock.patch("fontpack.find_pack", return_value=folder), \
                 mock.patch("fontpack.minecraft_dir", return_value=missing), \
                 mock.patch("fontpack.resourcepacks_dir",
                            return_value=os.path.join(missing, "resourcepacks")):
                with self.assertRaises(FileNotFoundError):
                    fontpack.install()
            self.assertFalse(os.path.exists(missing))


class WebhookTests(unittest.TestCase):
    def settings(self, **overrides):
        data = json.loads(json.dumps(config.DEFAULT_SETTINGS))
        data["webhook"].update(overrides)
        return data

    def test_embed_drops_empty_fields(self):
        payload = webhook.build_embed("Title", [("A", 1), ("B", None), ("C", "")])
        names = [f["name"] for f in payload["embeds"][0]["fields"]]
        self.assertEqual(names, ["A"])

    def test_disabled_webhook_sends_nothing(self):
        hook = webhook.Webhook(self.settings(enabled=False, url="https://example.invalid/x"))
        self.assertFalse(hook.enabled)
        self.assertFalse(hook.send("macro_started", {}, blocking=True))

    def test_a_switched_off_event_is_not_sent(self):
        settings = self.settings(enabled=True, url="https://example.invalid/x")
        settings["webhook"]["events"]["macro_started"] = False
        hook = webhook.Webhook(settings)
        self.assertFalse(hook.send("macro_started", {}, blocking=True))

    def test_summary_interval_can_be_disabled(self):
        self.assertEqual(webhook.Webhook(
            self.settings(summary_interval_minutes=0)).summary_interval_seconds(), 0)
        self.assertEqual(webhook.Webhook(
            self.settings(summary_interval_minutes=60)).summary_interval_seconds(), 3600)

    def test_duration_formatting(self):
        self.assertEqual(webhook.format_duration(45), "45s")
        self.assertEqual(webhook.format_duration(605), "10m 5s")
        self.assertEqual(webhook.format_duration(7800), "2h 10m")

    def test_summary_reports_revenue_only_once_both_balances_are_known(self):
        session = SessionStats("Rockets")
        self.assertIsNone(session.revenue())
        session.record_money(1_000_000)
        self.assertEqual(session.revenue(), 0)    # first reading is the baseline
        session.record_money(1_250_000)
        self.assertEqual(session.revenue(), 250_000)
        session.record_batch(9)
        fields = dict(session.summary_fields())
        self.assertEqual(fields["Items sold"], 9)
        self.assertEqual(fields["Revenue"], "$250,000")


class UpdaterTests(unittest.TestCase):
    """Version comparison only - the download and the exe swap need a real
    release and a real Windows process to mean anything."""

    def test_versions_compare_numerically_not_as_text(self):
        self.assertTrue(updater.is_newer("1.10.0", "1.9.0"))
        self.assertTrue(updater.is_newer("v2.0.0", "1.9.9"))
        self.assertFalse(updater.is_newer("1.0.0", "1.0.0"))
        self.assertFalse(updater.is_newer("0.9.0", "1.0.0"))

    def test_tag_prefixes_and_short_tags_are_tolerated(self):
        self.assertEqual(updater.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(updater.parse_version("1.2"), (1, 2, 0))
        self.assertEqual(updater.parse_version("release-3"), (3, 0, 0))

    def test_an_unreadable_tag_never_looks_like_an_update(self):
        # A release named something odd must not trigger an update prompt.
        self.assertFalse(updater.is_newer("", "1.0.0"))
        self.assertFalse(updater.is_newer(None, "1.0.0"))
        self.assertFalse(updater.is_newer("latest", "1.0.0"))


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    print(f"\n{result.testsRun} checks run, {len(result.failures)} failed, "
          f"{len(result.errors)} errored")
    sys.exit(1 if (result.failures or result.errors) else 0)
