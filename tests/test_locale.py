"""The app's translations (dodock_wolf/locale): every string of the template is in each .po, and a
translation keeps the placeholders, HTML tags and code of its source, so `.format()` and the
page never break in French."""

import ast
import importlib.util
import re
import unittest
from pathlib import Path

LOCALE = Path(__file__).resolve().parent.parent / "dodock_wolf" / "locale"
FRONTEND = LOCALE.parent.parent / "frontend" / "src"
# Frappe's own extraction of .vue and template files (frappe/gettext/extractors/utils.py,
# TRANSLATE_PATTERN), copied: it reads one call per line and takes a later string argument as the
# context, so a call it cannot read never reaches the catalog.
FRAPPE_TRANSLATE = re.compile(
	r"_\(\s*([\"']{,3})(?P<message>((?!\1).)*)\1"
	r"(\s*,\s*context\s*=\s*([\"'])(?P<py_context>((?!\5).)*)\5)?"
	r"(\s*,\s*(.)*?\s*(,\s*([\"'])(?P<js_context>((?!\11).)*)\11)*)*\s*\)"
)
UI_CALL = re.compile(r"""\b__\(\s*(['"])((?:(?!\1).)*)\1""")
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


def _contexts():
	spec = importlib.util.spec_from_file_location("locale_contexts", LOCALE.parent.parent / "ci" / "locale_contexts.py")
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


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

	def test_every_select_option_has_its_own_entry(self):
		# without one, Desk shows Frappe's own French of the word ("Open" as the verb « Ouvrir »)
		contexts = _contexts()
		wanted = {(doctype, msgid) for doctype, msgid, _src, _opt in contexts.entries()}
		for name, entries in {"main.pot": self.template, **{f"{k}.po": v for k, v in self.translations.items()}}.items():
			self.assertEqual(sorted(wanted - set(entries)), [], f"{name}: run python3 ci/locale_contexts.py")
		for lang, words in contexts.TRANSLATED.items():
			for key, french in words.items():
				self.assertEqual(self.translations[lang][key], french)

	def test_every_wolf_ui_string_reaches_the_catalog(self):
		# a call Frappe's extractor misreads (arguments over several lines, a nested __() taken as
		# the context, no letter in the text) stays in English whatever the .po says
		missed = []
		for path in sorted(FRONTEND.rglob("*")):
			if path.suffix not in (".vue", ".js"):
				continue
			code = path.read_text(encoding="utf-8")
			for call in UI_CALL.finditer(code):
				line_start = code.rfind("\n", 0, call.start()) + 1
				if code[line_start : call.start()].lstrip().startswith(("//", "*")):
					continue  # an example in a comment
				text = call.group(2).replace("\\'", "'")
				match = FRAPPE_TRANSLATE.match(code, call.start() + 1)
				context = match and (match.group("py_context") or match.group("js_context"))
				if not match or match.group("message") != call.group(2) or (context, text) not in self.template:
					missed.append(f"{path.relative_to(FRONTEND)}:{code.count(chr(10), 0, call.start()) + 1} {text[:60]!r}")
		self.assertEqual(missed, [], "keep each __() call on one line, its context the third argument, then regenerate")

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
