import unittest

from dodock_wolf.wolf.i18n import _, fmt, translate


class TestI18n(unittest.TestCase):
	def test_english_without_frappe(self):
		self.assertEqual(_("Some text"), "Some text")  # tests/ is kept out of extraction (babel_extractors.csv)
		self.assertEqual(_(""), "")
		self.assertEqual(translate("Open", "Wolf Incident"), "Open")

	def test_fmt_fills_and_never_raises(self):
		self.assertEqual(fmt("{0} of {1} hosts", 2, 3), "2 of 3 hosts")
		self.assertEqual(fmt("{1} sur {0}", 2, 3), "3 sur 2")  # a translation may reorder
		self.assertEqual(fmt("{0} and {2}", "a"), "a and {2}")  # one it has no value for stays
		self.assertEqual(fmt("{name} {0}", "x"), "{name} x")  # named braces are left alone


if __name__ == "__main__":
	unittest.main()
