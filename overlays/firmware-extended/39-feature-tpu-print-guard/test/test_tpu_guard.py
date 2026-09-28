"""Render the actual shipped Klipper macro with physical-tool fixtures."""
import configparser
from pathlib import Path
import unittest

import jinja2

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "root/usr/local/share/firmware-config/extended/klipper/tpu_conditional_auto_feed.cfg"


class TpuGuardTests(unittest.TestCase):
    def render(self, types, extruder=None):
        config = configparser.ConfigParser(interpolation=None)
        config.read(CFG)
        template = jinja2.Environment(block_start_string="{%", block_end_string="%}",
            variable_start_string="{", variable_end_string="}").from_string(
                config["gcode_macro SM_PRINT_AUTO_FEED_UNLESS_TPU"]["gcode"])
        printer = {"configfile": {"settings": {"printer": {"max_physical_extruder_num": 4}}},
                   "print_task_config": {"filament_type": types}}
        return template.render(printer=printer,
            params={} if extruder is None else {"EXTRUDER": extruder})

    def test_manually_loaded_tpu_on_each_physical_tool_skips_feeding(self):
        for channel in range(4):
            types = ["PLA"] * 4
            types[channel] = "TPU 85A"
            with self.subTest(channel=channel):
                result = self.render(types, channel)
                self.assertIn("skipping automatic feed", result)
                self.assertNotIn("SM_PRINT_AUTO_FEED EXTRUDER=", result)

    def test_physical_mapping_does_not_use_logical_tool_zero(self):
        types = ["PLA", "PETG", "tpu", "PLA"]
        self.assertIn("skipping automatic feed", self.render(types, 2))
        self.assertIn("SM_PRINT_AUTO_FEED EXTRUDER=0", self.render(types, 0))

    def test_non_tpu_forwards_once_to_existing_macro(self):
        output = self.render(["PLA", "PETG", "ABS", "PA"], 3)
        self.assertEqual(output.count("SM_PRINT_AUTO_FEED EXTRUDER=3"), 1)
        self.assertNotIn("SM_PRINT_AUTO_FEED_UNLESS_TPU", output)

    def test_missing_or_invalid_channel_does_not_feed(self):
        for value in [None, -1, 4, 99]:
            with self.subTest(value=value):
                output = self.render(["PLA"] * 4, value)
                self.assertIn("RESPOND TYPE=error", output)
                self.assertNotIn("SM_PRINT_AUTO_FEED EXTRUDER=", output)

    def test_missing_metadata_does_not_feed(self):
        output = self.render([], 0)
        self.assertIn("no filament metadata", output)
        self.assertNotIn("SM_PRINT_AUTO_FEED EXTRUDER=", output)
