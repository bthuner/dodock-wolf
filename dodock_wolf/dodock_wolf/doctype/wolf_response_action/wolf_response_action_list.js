// The status pill, translated with the DocType as context (frappe.wolf.status_indicator, wolf.js).
frappe.listview_settings["Wolf Response Action"] = {
	get_indicator: frappe.wolf.status_indicator("Wolf Response Action", { Approved: "blue", Applied: "green", Failed: "red", Expired: "gray" }),
};
