# Translating the docs to French

Every page in `content/en/` has a twin in `content/fr/`, at the same relative path, with the same
file name (number prefix included) and the same `.navigation.yml` structure.

## Keep exactly

- Front matter keys, `navigation.icon`, and the MDC structure: `::note`, `::steps{level="3"}`,
  `:::tabs-item{label="…"}`, `:::card{…}`, `:screenshot{…}`, indentation and colons. Translate the
  human text inside attributes (`label`, `title`, `alt`, `caption`, `name` of a collapsible) but not
  `to`, `icon`, `level`, `name` of a screenshot.
- Code blocks, commands, JSON, config keys, file paths, event types and categories
  (`cron_failure`, `web_attack_probe`), metric names, HTTP fields. Translate only comments inside
  code blocks when they are prose (`# then restart…`), and the label after the language
  (```` ```bash [hôte] ````) only when it is prose.
- Names: Dodock Wolf, Wolf Agent, Wolf App, Wolf UI, Desk, Press, Pilot, bench, and DocType names
  (**Wolf Alert Rule**, **Wolf Incident**…).
- UI labels in bold stay in English, as the Wolf UI shows them today (Desk now follows the user's
  language: the French pages move to Desk's French labels with the Wolf UI's translation): **Wolf Settings →
  Retention**, **Send test notification**, **Assign to me**. On first use in a page you may add a
  French gloss in parentheses when the label is not self-explanatory.
- Every number, threshold, duration and default.

## Change

- Internal links: prefix with `/fr`. `/alerts/rules#maintenance-windows` becomes
  `/fr/alerts/rules#fenêtres-de-maintenance` when the French heading is "Fenêtres de maintenance".
  Anchors are generated from the heading text by github-slugger: lower case, accents kept,
  spaces as `-`, punctuation (apostrophes included) dropped. `yarn check:links` catches a wrong one. When you translate a heading that another page links to, update that link
  in every French page you write, and report the anchor in your final message.
- External links stay as they are.

## Voice

- "vous", present tense, short sentences. Same register as doc.dokos.io.
- French typography: narrow no-break space (U+202F) or no-break space (U+00A0) before `: ; ? !`
  and inside « guillemets » (use them for quoted UI text that is not a label); `%` preceded by a
  no-break space; decimal comma in prose (`1,5 s`) but not in code.
- Glossary:

| English | Français |
|---|---|
| alert rule | règle d'alerte |
| incident | incident |
| event | événement |
| metric sample | échantillon de métrique |
| rollup | agrégat |
| scope | périmètre |
| host | hôte |
| site / bench | site / bench |
| scheduled job | tâche planifiée |
| scheduler | planificateur (scheduler) |
| worker | worker |
| queue | file d'attente |
| deployment | déploiement |
| maintenance window | fenêtre de maintenance |
| silence | silence |
| acknowledge / resolve | acquitter / résoudre |
| on-call | astreinte |
| channel | canal |
| push (agent → site) | envoi |
| spool | file locale (spool) |
| scrubbing | nettoyage (scrubbing) |
| watchdog | chien de garde (watchdog) |
| threshold / window | seuil / fenêtre |
| severity | gravité |
| preset | règle prédéfinie |
| response action | action de réponse |
| tamper-evident journal | journal infalsifiable |
| honeytoken | leurre (honeytoken) |
| breach | dépassement (of a threshold) / violation (of data) |
| postmortem | post-mortem |
| status page | page de statut |
| Getting started | Bien démarrer |
| Install | Installer |
| Alerts and incidents | Alertes et incidents |
| Security | Sécurité |
| Reference | Référence |

# Translating the app

Desk (forms, labels, descriptions, messages) is translated with Frappe's gettext files in
`dodock_wolf/locale/`: `main.pot` holds every string, `fr.po` their French, with the glossary
above. `bench build` compiles them; a user whose language is French sees Desk in French.

When a change adds or changes strings, on a bench with the app:

```bash
bench generate-pot-file --app dodock_wolf
python3 ci/locale_contexts.py        # in this repository: the Select options' own entries
bench update-po-files --app dodock_wolf --locale fr
```

Then:
- put `https://github.com/bthuner/dodock-wolf/issues` back in `Report-Msgid-Bugs-To`, and
  "Dodock Wolf contributors" in `Last-Translator` and `Language-Team`, in the header of both
  files: the tool writes `app_email` there;
- translate the new entries (an empty `msgstr` shows the English);
- run `python3 -m unittest tests.test_locale`. It fails when a string of the template is missing
  from `fr.po`, or when a translation drops a placeholder (`{0}`), an HTML tag or code.

Frappe merges every app's translations into one table, Wolf's after Frappe's:
- **A plain entry Wolf translates replaces Frappe's French of the same string in all of Desk.**
  When Frappe already translates a string (`Comment`, `Assigned To`, `To Date`...), leave Wolf's
  `msgstr` empty so Frappe's is used, or give a label its own entry with the DocType as context
  (`LABELS` in `ci/locale_contexts.py`).
- **An empty entry shows Frappe's French when there is one, not the English.** That is why every
  Select option has an entry with its DocType as context (`ci/locale_contexts.py`): a status
  such as `Open` reads « Ouvert » (`TRANSLATED`), and a value the code compares (`none`, `Email`,
  `critical`) is pinned to the English. Python messages that show a status translate it with the
  same context: `_(doc.status, context="Wolf Incident")`.

What stays in English:
- DocType names and product names;
- Select values the code compares (`metric`, `critical`, `hourly`...).
