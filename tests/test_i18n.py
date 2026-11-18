import unittest

from dodock_wolf.wolf.i18n import _, fmt


class TestI18n(unittest.TestCase):
	def test_english_without_frappe(self):
		self.assertEqual(_("Two-factor authentication is off"), "Two-factor authentication is off")
		self.assertEqual(_(""), "")

	def test_fmt_fills_and_never_raises(self):
		self.assertEqual(fmt("{0} of {1} hosts", 2, 3), "2 of 3 hosts")
		self.assertEqual(fmt("{1} sur {0}", 2, 3), "3 sur 2")  # a translation may reorder
		self.assertEqual(fmt("{0} and {2}", "a"), "a and {2}")  # one it has no value for stays
		self.assertEqual(fmt("{name} {0}", "x"), "{name} x")  # named braces are left alone


if __name__ == "__main__":
	unittest.main()
