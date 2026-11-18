"""Give every Select option of the app's DocTypes its own entry, with the DocType as context.

Desk shows an option as `__(option, null, doctype)`: the `option:DocType` translation first, then
the plain one, which may come from Frappe itself (Frappe's French turns "Open" into « Ouvrir », a
verb, and "Email" into « Courriel »). A context entry decides what Wolf's options say, without
changing what Frappe's own "Open" button says anywhere else.

Run after `bench generate-pot-file --app dodock_wolf` and before `bench update-po-files`:

    python3 ci/locale_contexts.py

It adds the missing entries to `main.pot`, and to each `.po` with an msgstr from
`TRANSLATED` (or `LABELS`) or, for a code value, the option itself, so it stays in English. Existing entries
are kept as they are. Standard library only.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALE = ROOT / "dodock_wolf" / "locale"
DOCTYPES = ROOT / "dodock_wolf" / "dodock_wolf" / "doctype"

# Options that are words for people, per language: everything else is a value the code compares,
# shown as it is.
TRANSLATED = {
	"fr": {
		("Wolf Agent", "Active"): "Actif",
		("Wolf Agent", "Disabled"): "Désactivé",
		("Wolf Entity Alias", "Manual"): "Manuel",
		("Wolf Entity Alias", "Auto"): "Automatique",
		("Wolf Incident", "Open"): "Ouvert",
		("Wolf Incident", "Acknowledged"): "Acquitté",
		("Wolf Incident", "Resolved"): "Résolu",
		("Wolf Postmortem", "Draft"): "Brouillon",
		("Wolf Postmortem", "In Review"): "En relecture",
		("Wolf Postmortem", "Published"): "Publié",
		("Wolf Postmortem Action Item", "Open"): "Ouverte",
		("Wolf Postmortem Action Item", "In Progress"): "En cours",
		("Wolf Postmortem Action Item", "Done"): "Terminée",
		("Wolf Response Action", "Approved"): "Approuvée",
		("Wolf Response Action", "Applied"): "Appliquée",
		("Wolf Response Action", "Failed"): "Échouée",
		("Wolf Response Action", "Expired"): "Expirée",
	}
}


# Labels whose plain msgid Frappe also translates, with a sense that does not fit here (Frappe's
# "Count" is the verb « Compter »): Desk looks labels up with the DocType as context too.
LABELS = {
	"fr": {
		("Wolf Event", "Count"): "Nombre",
		("Wolf Metric Rollup", "Count"): "Nombre",
		("Wolf Outbox", "Count"): "Nombre",
		("Wolf Alert Rule", "Timing"): "Horaires et délais",
	}
}


def select_options():
	"""[(doctype, option, json path)] of every Select field, in file order, without repeats."""
	seen, out = set(), []
	for path in sorted(DOCTYPES.glob("*/*.json")):
		doc = json.loads(path.read_text(encoding="utf-8"))
		if doc.get("doctype") != "DocType":
			continue
		for field in doc.get("fields", []):
			if field.get("fieldtype") != "Select":
				continue
			for option in (field.get("options") or "").split("\n"):
				key = (doc["name"], option)
				if option and key not in seen:
					seen.add(key)
					out.append((doc["name"], option, path.relative_to(ROOT)))
	return out


def entries():
	"""[(doctype, msgid, source, is_option)]: every Select option, then the labels of `LABELS`."""
	out = [(d, o, src, True) for d, o, src in select_options()]
	labels = sorted({key for words in LABELS.values() for key in words})
	return out + [(d, m, Path("dodock_wolf/dodock_wolf/doctype") / d.lower().replace(" ", "_"), False) for d, m in labels]


def _quote(text):
	return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _has(text, doctype, option):
	return f"msgctxt {_quote(doctype)}\nmsgid {_quote(option)}\n" in text


def add(path, msgstr_for):
	text = path.read_text(encoding="utf-8")
	added = []
	for doctype, option, source, is_option in entries():
		if _has(text, doctype, option):
			continue
		what = "Option of a Select field" if is_option else "Label"
		added.append(
			f"\n#. {what} in DocType '{doctype}', shown with the DocType as context\n"
			f"#: {source}\n"
			f"msgctxt {_quote(doctype)}\nmsgid {_quote(option)}\nmsgstr {_quote(msgstr_for(doctype, option))}\n"
		)
	if added:
		path.write_text(text.rstrip("\n") + "\n" + "".join(added), encoding="utf-8")
	return len(added)


def main():
	print(f"main.pot: {add(LOCALE / 'main.pot', lambda d, o: '')} added")
	for po in sorted(LOCALE.glob("*.po")):
		words = {**TRANSLATED.get(po.stem, {}), **LABELS.get(po.stem, {})}
		print(f"{po.name}: {add(po, lambda d, o, w=words: w.get((d, o), o))} added")


if __name__ == "__main__":
	main()
