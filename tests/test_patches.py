import configparser
import os
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..", "dodock_wolf")


class TestPatchesTxt(unittest.TestCase):
	def test_sections_and_every_patch_module_listed(self):
		# Frappe reads patches.txt with configparser: without its sections, every patch runs before
		# the model sync, when the new fields do not exist yet
		with open(os.path.join(ROOT, "patches.txt")) as f:
			text = f.read()
		parser = configparser.ConfigParser(allow_no_value=True)
		parser.optionxform = str
		parser.read_string(text)
		self.assertEqual(parser.sections(), ["pre_model_sync", "post_model_sync"])
		listed = [p for s in parser.sections() for p in parser[s]]
		self.assertEqual(len(listed), len(set(listed)), "a patch listed twice")
		modules = {f"dodock_wolf.patches.{f[:-3]}" for f in os.listdir(os.path.join(ROOT, "patches"))
		           if f.endswith(".py") and f != "__init__.py"}  # fmt: skip
		self.assertEqual(set(listed), modules, "every patch module is listed, and nothing else")


if __name__ == "__main__":
	unittest.main()
