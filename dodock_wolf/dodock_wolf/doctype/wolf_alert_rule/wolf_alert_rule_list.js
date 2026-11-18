// Alert rules as YAML (dodock_wolf/api/rules_io.py): export, and import with a preview first.
frappe.listview_settings["Wolf Alert Rule"] = {
	onload(listview) {
		if (!frappe.user.has_role(["System Manager", "Wolf Manager"])) return;
		listview.page.add_menu_item(__("Export to YAML"), () => {
			const names = listview.get_checked_items(true);
			frappe.call({
				method: "dodock_wolf.api.rules_io.export_yaml",
				args: names.length ? { names } : {},
				callback: (r) => {
					const blob = new Blob([r.message.content], { type: "application/x-yaml" });
					const link = document.createElement("a");
					link.href = URL.createObjectURL(blob);
					link.download = r.message.filename;
					link.click();
					URL.revokeObjectURL(link.href);
				},
			});
		});
		listview.page.add_menu_item(__("Import from YAML"), () => import_dialog(listview));
	},
};

function import_dialog(listview) {
	const dialog = new frappe.ui.Dialog({
		title: __("Import alert rules from YAML"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				options: `<p class="text-muted small">${__(
					"Rules are matched by name; a field the file leaves out goes back to its default. Rules not in the file are left alone. Channel secrets are never in a file: a channel keeps its stored one."
				)}</p>`,
			},
			{ fieldname: "content", fieldtype: "Code", options: "YAML", label: __("YAML"), reqd: 1 },
			{ fieldname: "plan", fieldtype: "HTML" },
		],
		primary_action_label: __("Preview"),
		primary_action(values) {
			run(values.content, 0);
		},
	});
	let previewed = null; // the text the plan shown is for: Apply writes that one only
	function run(content, apply) {
		frappe.call({
			method: "dodock_wolf.api.rules_io.import_yaml",
			args: { content, apply },
			freeze: true,
			callback: (r) => {
				const result = r.message;
				if (!apply) previewed = content;
				dialog.fields_dict.plan.$wrapper.html(render(result));
				if (result.applied) {
					frappe.show_alert({ message: __("Rules imported"), indicator: "green" });
					dialog.hide();
					listview.refresh();
				} else if (result.valid && (result.counts.create || result.counts.update)) {
					// edited since the preview: show the new plan first
					dialog.set_primary_action(__("Apply"), () => {
						const now = dialog.get_value("content");
						run(now, now === previewed ? 1 : 0);
					});
				} else {
					dialog.set_primary_action(__("Preview"), (values) => run(values.content, 0));
				}
			},
		});
	}
	dialog.show();
}

function render(result) {
	const rows = result.rules
		.map((item) => {
			const details = [
				...item.changes.length ? [__("changes: {0}", [item.changes.join(", ")])] : [],
				...item.errors.map((e) => __("error: {0}", [e])),
				...item.notes.map((n) => __("note: {0}", [n])),
			]
				.map((d) => `<div class="small">${frappe.utils.escape_html(d)}</div>`)
				.join("");
			return `<tr><td>${frappe.utils.escape_html(item.action)}</td><td>${frappe.utils.escape_html(item.rule_name)}${details}</td></tr>`;
		})
		.join("");
	const counts = Object.entries(result.counts)
		.filter(([, n]) => n)
		.map(([a, n]) => `${n} ${a}`)
		.join(", ");
	const head = result.valid
		? __("Preview: {0}. Nothing is written until you apply.", [counts])
		: __("Nothing can be applied until the invalid rules are fixed: {0}.", [counts]);
	return `<p>${frappe.utils.escape_html(head)}</p><table class="table table-bordered small"><tbody>${rows}</tbody></table>`;
}
