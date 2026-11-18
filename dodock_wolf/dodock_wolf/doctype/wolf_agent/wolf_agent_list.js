// The status pill, translated with the DocType as context (frappe.wolf.status_indicator, wolf.js).
frappe.listview_settings["Wolf Agent"] = {
	get_indicator: frappe.wolf.status_indicator("Wolf Agent", { Active: "green", Disabled: "gray" }),
};
