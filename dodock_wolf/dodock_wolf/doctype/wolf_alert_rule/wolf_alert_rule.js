// Copyright (c) 2026, Dodock Wolf contributors
// For license information, please see license.txt

// The rule in words (wolf/rule_sentence.py), redrawn as its fields change: each sentence is a
// list of [text, is_value] parts, a value in bold. Channel rows go as the two fields it reads:
// never a secret typed in a row and not saved yet.
function draw_sentence(frm) {
	const field = frm.fields_dict.rule_sentence;
	if (!field) return;
	const doc = Object.assign({}, frm.doc);
	for (const listname of ["channels", "escalation_channels"]) {
		doc[listname] = (frm.doc[listname] || []).map((r) => ({
			channel_type: r.channel_type,
			enabled: r.enabled,
		}));
	}
	const seq = (frm.wolf_sentence_seq = (frm.wolf_sentence_seq || 0) + 1);
	frappe.call({
		method: "dodock_wolf.dodock_wolf.doctype.wolf_alert_rule.wolf_alert_rule.describe",
		args: { doc },
	}).then(({ message }) => {
		if (seq !== frm.wolf_sentence_seq) return; // a newer one is on its way
		const text = (message || [])
			.map((parts) =>
				parts.map(([t, value]) => (value ? `<strong>${frappe.wolf.esc(t)}</strong>` : frappe.wolf.esc(t))).join("")
			)
			.join(" ");
		field.$wrapper.html(`<div class="wolf-rule-sentence" style="font-size: var(--text-base); line-height: 1.6;
			padding: var(--padding-sm) var(--padding-md); background: var(--subtle-fg); border-radius: var(--border-radius-md);">${text}</div>`);
	});
}

frappe.ui.form.on("Wolf Alert Rule", {
	onload_post_render(frm) {
		// every change, the channel tables' included, marks the form dirty
		frm.wolf_draw_sentence_soon = frm.wolf_draw_sentence_soon || frappe.utils.debounce(() => draw_sentence(frm), 400);
		$(frm.wrapper).off("dirty.wolf_sentence").on("dirty.wolf_sentence", () => frm.wolf_draw_sentence_soon());
	},
	refresh(frm) {
		draw_sentence(frm);
		frm.add_custom_button(__("Preview"), () =>
			frm.call("preview").then(({ message }) => {
				const rows = message.groups
					.map(
						(g) =>
							`<tr><td>${frappe.wolf.esc(g.group)}</td><td>${frappe.wolf.esc(g.value)}</td>
							<td>${frappe.wolf.esc(g.samples)}</td>
							<td>${g.breached ? `<span class="indicator-pill red">${__("breached")}</span>` : ""}</td></tr>`
					)
					.join("");
				frappe.msgprint({
					title: __("Current values"),
					message:
						(message.active ? "" : `<p class="text-muted">${__("Outside the active window right now.")}</p>`) +
						(rows
							? `<table class="table table-sm"><thead><tr><th>${__("Group")}</th><th>${__("Value")}</th><th>${__("Samples")}</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
							: __("No data in the window.")),
					wide: true,
				});
			})
		);
		if (!frm.is_new() && (frm.doc.channels || []).concat(frm.doc.escalation_channels || []).length) {
			frm.add_custom_button(__("Send test notification"), () =>
				frm.call("send_test_notification").then(({ message }) => {
					const esc = frappe.wolf.esc;
					const rows = (message.results || [])
						.map(
							(r) =>
								`<tr><td>${esc(r.channel_type)}</td><td>${esc(r.target)}</td><td>${esc(r.action || "")}</td>
								<td>${r.ok ? `<span class="indicator-pill green">${__("sent")}</span>` : `<span class="indicator-pill red">${__("failed")}</span>`}</td>
								<td>${esc(r.http_status || "")}</td><td>${esc(r.error || "")}</td></tr>`
						)
						.join("");
					frappe.msgprint({
						title: __("Test notification"),
						message: rows
							? `<table class="table table-sm"><thead><tr><th>${__("Channel")}</th><th>${__("Target")}</th><th>${__("Action")}</th><th></th><th>${__("HTTP")}</th><th>${__("Error")}</th></tr></thead><tbody>${rows}</tbody></table>
							<p class="text-muted">${__("Recorded on incident {0}.", [`<a href="/app/wolf-incident/${encodeURIComponent(message.incident)}">${esc(message.incident)}</a>`])}</p>`
							: __("No enabled channel to test."),
						wide: true,
					});
				})
			);
		}
	},
});
