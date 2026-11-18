#!/usr/bin/env python3
"""Drive the Press agent through its HTTP API, as Press does (press/agent.py), on the dev server.

Each call is a job the agent records in jobs.sqlite3, with the Agent Job name Press would send in
X-Agent-Job-Id. Stdlib only; runs inside the `server` container (dev/press/README.md).

    press_api.py new-bench NAME OFFSET           Press's "New Bench" (Bench.bench_config + config)
    press_api.py new-site BENCH SITE [APP...]    "New Site" on the database server
    press_api.py job NAME PATH [JSON] [--method M]   any other job, e.g.
        press_api.py job "Migrate Site" benches/B/sites/S/migrate '{"skip_failing_patches": false}'
    press_api.py jobs                            the agent's latest jobs
"""

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

SERVER = os.environ.get("PRESS_SERVER_NAME", "f1-press")
# as Press reaches it: https://<server>/agent/ through nginx (press/agent.py get_request_url)
AGENT = os.environ.get("PRESS_AGENT_URL", "https://127.0.0.1/agent")
PASSWORD_FILE = os.environ.get("PRESS_PASSWORD_FILE", "/root/wolf-press/agent_password")
TLS = ssl.create_default_context()
TLS.check_hostname, TLS.verify_mode = False, ssl.CERT_NONE  # the dev server's self-signed certificate
SERVER_IP = os.environ.get("PRESS_SERVER_IP", "172.30.80.2")
DB_HOST = os.environ.get("PRESS_DB_HOST", "172.30.80.10")
DB_PASSWORD = os.environ.get("PRESS_DB_PASSWORD", "admin")
REGISTRY = os.environ.get("PRESS_REGISTRY", "localhost:5000")
IMAGE = os.environ.get("PRESS_IMAGE", f"{REGISTRY}/wolf-press-bench:latest")
_counter = [int(time.time())]


def call(method, path, data=None, job_name=None):
	with open(PASSWORD_FILE) as f:
		password = f.read().strip()
	_counter[0] += 1
	headers = {"Authorization": f"bearer {password}", "Content-Type": "application/json", "Host": SERVER}
	if job_name:  # Press's Agent Job document name
		headers["X-Agent-Job-Id"] = f"AGJ-{_counter[0]}"
	body = json.dumps(data).encode() if data is not None else None
	req = urllib.request.Request(f"{AGENT}/{path.lstrip('/')}", data=body, headers=headers, method=method)
	try:
		with urllib.request.urlopen(req, timeout=60, context=TLS) as resp:
			return json.load(resp)
	except urllib.error.HTTPError as e:
		sys.exit(f"{method} {path}: {e.code} {e.read().decode(errors='replace')[:2000]}")


def wait(job_id, timeout=1800):
	deadline = time.time() + timeout
	while time.time() < deadline:
		job = call("GET", f"jobs/{job_id}")
		if job.get("status") in ("Success", "Failure"):
			steps = ", ".join(f"{s['name']}: {s['status']}" for s in job.get("steps") or [])
			print(f"job {job_id} {job['name']}: {job['status']}" + (f" ({steps})" if steps else ""))
			if job["status"] == "Failure":
				print(json.dumps(job.get("data"), indent=1)[:4000], file=sys.stderr)
			return job
		time.sleep(3)
	sys.exit(f"job {job_id}: still running after {timeout}s")


def run(job_name, path, data=None, method="POST"):
	job_id = call(method, path, data, job_name=job_name)["job"]
	print(f"job {job_id} {job_name} queued")
	return wait(job_id)


def bench_payload(name, offset):
	"""What Press's Bench.validate and press/agent.py new_bench send."""
	config = {
		"frappe_cloud": True,
		"monitor": True,
		"redis_cache": "redis://localhost:13000",
		"redis_queue": "redis://localhost:11000",
		"redis_socketio": "redis://localhost:13000",
		"socketio_port": 9000,
		"webserver_port": 8000,
		"restart_supervisor_on_update": True,
		"db_host": DB_HOST,
		"db_port": 3306,
	}
	bench_config = {
		"docker_image": IMAGE,
		"web_port": 18000 + offset,
		"socketio_port": 19000 + offset,
		"private_ip": SERVER_IP,
		"ssh_port": 22000 + offset,
		"codeserver_port": 16000 + offset,
		"is_ssh_enabled": False,  # the image has no sshd
		"gunicorn_workers": 2,
		"background_workers": 1,
		"http_timeout": 120,
		"statsd_host": f"{SERVER_IP}:9125",
		"merge_all_rq_queues": False,
		"merge_default_and_short_rq_queues": False,
		"environment_variables": {},
		"single_container": True,
		"gunicorn_threads_per_worker": 0,
		"is_code_server_enabled": False,
		"use_rq_workerpool": False,
		"rq_port": 11000 + offset,
		"rq_cache_port": 13000 + offset,
	}
	return {
		"name": name,
		"bench_config": bench_config,
		"common_site_config": config,
		"registry": {"url": REGISTRY, "username": "wolf", "password": "wolf"},
	}


def main():
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	sub = parser.add_subparsers(dest="cmd", required=True)
	p = sub.add_parser("new-bench")
	p.add_argument("name")
	p.add_argument("offset", type=int)
	p = sub.add_parser("new-site")
	p.add_argument("bench")
	p.add_argument("site")
	p.add_argument("apps", nargs="*", default=["frappe", "dodock_wolf"])
	p = sub.add_parser("job")
	p.add_argument("name")
	p.add_argument("path")
	p.add_argument("data", nargs="?", default="{}")
	p.add_argument("--method", default="POST")
	sub.add_parser("jobs")
	opts = parser.parse_args()

	if opts.cmd == "new-bench":
		job = run("New Bench", "benches", bench_payload(opts.name, opts.offset))
	elif opts.cmd == "new-site":
		data = {"config": {}, "apps": opts.apps, "name": opts.site, "mariadb_root_password": DB_PASSWORD,
		        "admin_password": "admin", "managed_database_config": {}}  # fmt: skip
		job = run("New Site", f"benches/{opts.bench}/sites", data)
	elif opts.cmd == "job":
		job = run(opts.name, opts.path, json.loads(opts.data), method=opts.method)
	else:
		for job in call("GET", "jobs"):
			print(job.get("id"), job.get("name"), job.get("status"), job.get("enqueue"))
		return 0
	return 0 if job["status"] == "Success" else 1


if __name__ == "__main__":
	sys.exit(main())
