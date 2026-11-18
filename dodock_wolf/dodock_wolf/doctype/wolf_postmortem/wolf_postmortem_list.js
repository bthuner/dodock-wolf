// The status pill, translated with the DocType as context (frappe.wolf.status_indicator, wolf.js).
frappe.listview_settings["Wolf Postmortem"] = {
	get_indicator: frappe.wolf.status_indicator("Wolf Postmortem", { Draft: "gray", "In Review": "orange", Published: "green" }),
};
