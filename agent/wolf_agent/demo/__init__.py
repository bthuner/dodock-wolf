"""Live demo data, written where the real agent reads it.

A demo lays out files the way a real host has them (bench logs, nginx's access log, auth.log,
the Press agent's jobs.sqlite3), waits until the running agent tracks them, then appends days
of history and keeps writing live traffic with scripted incidents. Everything Wolf shows goes
through the agent's own discovery, tailers and parsers; only past host metrics, which the agent
samples from /proc, are handed to its spool. See dev/demo/README.md.
"""
