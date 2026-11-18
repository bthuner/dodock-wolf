"""The app's translations (dodock_wolf/locale): every string of the template is in each .po, and a
translation keeps the placeholders, HTML tags and code of its source, so `.format()` and the
page never break in French."""

import ast
import re
import unittest
from pathlib import Path

LOCALE = Path(__file__).resolve().parent.parent / "dodock_wolf" / "locale"
PLACEHOLDER = re.compile(r"\{\d*\}|%\(?\w*\)?[sd]")
TAG = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)")
CODE = re.compile(r"`[^`]+`|<code>.*?</code>")


def read_po(path):
	"""{(msgctxt, msgid): msgstr} of a .po or .pot file (no plural forms in this app)."""
	entries, current, key = {}, {}, None
	for line in path.read_text(encoding="utf-8").splitlines() + [""]:
		line = line.strip()
		if not line or line.startswith("#"):
			if "msgid" in current:
				entries[(current.get("msgctxt"), current["msgid"])] = current.get("msgstr", "")
			if not line:
				current, key = {}, None
			continue
		if line.startswith('"'):
			current[key] += ast.literal_eval(line)
			continue
		key, _, value = line.partition(" ")
		if key == "msgid" and "msgid" in current:  # an entry with no blank line before it
			entries[(current.get("msgctxt"), current["msgid"])] = current.get("msgstr", "")
			current = {}
		current[key] = ast.literal_eval(value)
	entries.pop((None, ""), None)  # the header
	return entries


class TestLocale(unittest.TestCase):
	def setUp(self):
		self.template = read_po(LOCALE / "main.pot")
		self.translations = {path.stem: read_po(path) for path in LOCALE.glob("*.po")}

	def test_there_is_french(self):
		self.assertIn("fr", self.translations)
		self.assertGreater(len(self.template), 500)

	def test_every_string_of_the_template_is_in_each_language(self):
		for lang, entries in self.translations.items():
			missing = sorted(msgid for (_ctxt, msgid) in set(self.template) - set(entries))
			self.assertEqual(missing, [], f"{lang}.po misses strings: run update-po-files")

	def test_a_translation_keeps_placeholders_tags_and_code(self):
		for lang, entries in self.translations.items():
			for (_ctxt, msgid), msgstr in entries.items():
				if not msgstr:
					continue
				for pattern in (PLACEHOLDER, CODE):
					self.assertEqual(sorted(pattern.findall(msgstr)), sorted(pattern.findall(msgid)), f"{lang}: {msgid!r}")
				self.assertEqual(sorted(TAG.findall(msgstr)), sorted(TAG.findall(msgid)), f"{lang}: {msgid!r}")


if __name__ == "__main__":
	unittest.main()
