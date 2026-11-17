from dodock_wolf.patches import default_signal_settings


def execute():
	"""Grouping incidents by entity is on by default on existing sites too (#72 step 5).

	default_signal_settings already ran on those sites, so it is run again under a new name."""
	default_signal_settings.execute()
