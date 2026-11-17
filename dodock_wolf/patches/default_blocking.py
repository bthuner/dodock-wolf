from dodock_wolf.patches import default_signal_settings


def execute():
	"""Blocks stay with the Wolf Agent on existing sites, as before (#72 step 6).

	default_signal_settings already ran on those sites, so it is run again under a new name."""
	default_signal_settings.execute()
