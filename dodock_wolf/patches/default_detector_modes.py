from dodock_wolf.patches import default_signal_settings


def execute():
	"""Overlapping detectors start in own mode on existing sites, as before (#72 step 4).

	default_signal_settings already ran on those sites, so it is run again under a new name."""
	default_signal_settings.execute()
