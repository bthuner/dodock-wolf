import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from wolf_agent import integrity

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def write(path, text):
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w") as f:
		f.write(text)


class TestIntegrity(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.root = self.tmp.name
		self.bench = os.path.join(self.root, "frappe-bench")
		app = os.path.join(self.bench, "apps", "erpnext")
		write(os.path.join(app, "erpnext", "api.py"), "def ping():\n\treturn 'pong'\n")
		write(os.path.join(app, "erpnext", "__pycache__", "api.cpython-312.pyc"), "x")
		write(os.path.join(app, "node_modules", "lib", "index.js"), "x")
		write(os.path.join(app, ".git", "HEAD"), "ref: refs/heads/version-15\n")
		write(os.path.join(app, ".git", "refs", "heads", "version-15"), "a" * 40 + "\n")
		write(os.path.join(self.bench, "sites", "common_site_config.json"), json.dumps({"db_host": "127.0.0.1"}))
		write(os.path.join(self.bench, "sites", "erp.example.com", "site_config.json"),
		      json.dumps({"db_name": "x", "db_password": "secret-1", "encryption_key": "k"}))  # fmt: skip
		write(os.path.join(self.bench, "config", "nginx.conf"), "server {}\n")
		self.etc = os.path.join(self.root, "etc-nginx")
		write(os.path.join(self.etc, "nginx.conf"), "http {}\n")
		self.state = os.path.join(self.root, "integrity-state.json")
		self.benches = [{"name": "frappe-bench", "path": self.bench, "sites": ["erp.example.com"]}]
		self.app = app

	def tearDown(self):
		self.tmp.cleanup()

	def watcher(self):
		return integrity.IntegrityWatcher("bench-01", self.state, [self.etc])

	def run_once(self, watcher=None, epoch=1000):
		return (watcher or self.watcher()).collect(self.benches, NOW, epoch=epoch)

	def test_first_scan_is_the_baseline(self):
		metrics, events = self.run_once()
		self.assertEqual(events, [])
		counts = {m["bench"]: m["value"] for m in metrics if m["metric_name"] == "integrity_files"}
		# api.py, the two site configs, config/nginx.conf; and the host's own path; caches and .git skipped
		self.assertEqual(counts, {"frappe-bench": 4, None: 1})

	def test_code_changed_outside_a_deployment_is_critical(self):
		w = self.watcher()
		self.run_once(w)
		write(os.path.join(self.app, "erpnext", "api.py"), "import os\ndef ping():\n\tos.system(input())\n")
		write(os.path.join(self.app, "erpnext", "www", "shell.py"), "x")
		_, events = self.run_once(w, epoch=1100)
		(ev,) = events
		self.assertEqual((ev["category"], ev["severity"], ev["bench"]), ("bench_code_changed", "critical", "frappe-bench"))
		self.assertEqual(ev["payload"]["modified"], ["erpnext/api.py"])
		self.assertEqual(ev["payload"]["added"], ["erpnext/www/shell.py"])
		self.assertFalse(ev["payload"]["deploy"])
		self.assertIn("outside a deployment", ev["title"])
		self.assertEqual(self.run_once(w, epoch=1200)[1], [], "reported once")

	def test_a_deployment_is_info_with_the_commits(self):
		w = self.watcher()
		self.run_once(w)
		write(os.path.join(self.app, ".git", "refs", "heads", "version-15"), "b" * 40 + "\n")
		write(os.path.join(self.app, "erpnext", "api.py"), "def ping():\n\treturn 'pong!'\n")
		(ev,) = self.run_once(w, epoch=1100)[1]
		self.assertEqual(ev["severity"], "info")
		self.assertTrue(ev["payload"]["deploy"])
		self.assertEqual((ev["payload"]["git_head_before"], ev["payload"]["git_head_after"]), ("a" * 40, "b" * 40))
		self.assertTrue(ev["title"].startswith("erpnext updated (aaaaaaaa → bbbbbbbb)"))

	def test_without_git_it_cannot_tell_a_deployment(self):
		import shutil

		shutil.rmtree(os.path.join(self.app, ".git"))
		w = self.watcher()
		self.run_once(w)
		write(os.path.join(self.app, "erpnext", "api.py"), "def ping():\n\treturn 'v16'\n")
		(ev,) = self.run_once(w, epoch=1100)[1]
		self.assertEqual((ev["severity"], ev["payload"]["deploy"]), ("warning", None))
		self.assertIn("no git checkout", ev["title"])

	def test_site_config_names_the_keys_never_the_values(self):
		w = self.watcher()
		self.run_once(w)
		write(os.path.join(self.bench, "sites", "erp.example.com", "site_config.json"),
		      json.dumps({"db_name": "x", "db_password": "secret-2", "developer_mode": 1}))  # fmt: skip
		(ev,) = self.run_once(w, epoch=1100)[1]
		self.assertEqual((ev["category"], ev["severity"], ev["site"]), ("bench_config_changed", "warning", "erp.example.com"))
		p = ev["payload"]
		self.assertEqual((p["keys_added"], p["keys_changed"], p["keys_removed"]), (["developer_mode"], ["db_password"], ["encryption_key"]))
		self.assertNotIn("secret", json.dumps(ev))

	def test_server_config(self):
		w = self.watcher()
		self.run_once(w)
		write(os.path.join(self.etc, "conf.d", "evil.conf"), "server { proxy_pass http://203.0.113.9; }\n")
		(ev,) = self.run_once(w, epoch=1100)[1]
		self.assertEqual((ev["severity"], ev["bench"], ev["payload"]["added"]), ("warning", None, ["conf.d/evil.conf"]))

	def test_a_restored_size_and_time_is_caught_by_the_full_scan(self):
		w = self.watcher()
		self.run_once(w)
		path = os.path.join(self.app, "erpnext", "api.py")
		st = os.stat(path)
		write(path, "def ping():\n\treturn 'p0ng'\n")  # same size
		os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
		self.assertEqual(self.run_once(w, epoch=1100)[1], [], "a quick scan trusts size and time")
		(ev,) = self.run_once(w, epoch=1000 + 86400)[1]
		self.assertEqual(ev["payload"]["modified"], ["erpnext/api.py"])

	def test_the_baseline_survives_a_restart(self):
		self.run_once()
		os.remove(os.path.join(self.app, "erpnext", "api.py"))
		(ev,) = self.run_once(self.watcher(), epoch=1100)[1]  # a new watcher, the same state file
		self.assertEqual(ev["payload"]["deleted"], ["erpnext/api.py"])

	def test_no_state_file_for_a_dry_run(self):
		w = integrity.IntegrityWatcher("bench-01", None, [self.etc])
		w.collect(self.benches, NOW, epoch=1000)
		self.assertFalse(os.path.exists(self.state))

	def test_what_a_bench_builds_or_runs_is_not_watched(self):
		w = self.watcher()
		self.run_once(w)
		for rel in ("erpnext/public/dist/js/app.bundle.js", "erpnext.egg-info/PKG-INFO", "erpnext/locale/fr/LC_MESSAGES/erpnext.mo",
		            "build/lib/x.py", "dist/erpnext.whl"):  # fmt: skip
			write(os.path.join(self.app, rel), "built")
		write(os.path.join(self.bench, "config", "pids", "redis_queue.pid"), "123")
		write(os.path.join(self.bench, "config", "scheduler_process"), "123")
		self.assertEqual(self.run_once(w, epoch=1100)[1], [], "bench build, pip install -e, a restart")

	def test_a_pull_in_progress_is_judged_at_the_next_scan(self):
		w = self.watcher()
		self.run_once(w)
		write(os.path.join(self.app, ".git", "index.lock"), "")  # git updates the tree before the ref
		write(os.path.join(self.app, "erpnext", "api.py"), "def ping():\n\treturn 'v2'\n")
		self.assertEqual(self.run_once(w, epoch=1100)[1], [], "no verdict while git holds its lock")
		os.remove(os.path.join(self.app, ".git", "index.lock"))
		write(os.path.join(self.app, ".git", "refs", "heads", "version-15"), "b" * 40 + "\n")
		(ev,) = self.run_once(w, epoch=1200)[1]
		self.assertEqual((ev["severity"], ev["payload"]["deploy"]), ("info", True))

	def test_a_deployment_adding_web_code_is_a_warning(self):
		w = self.watcher()
		self.run_once(w)
		write(os.path.join(self.app, ".git", "refs", "heads", "version-15"), "b" * 40 + "\n")
		write(os.path.join(self.app, "erpnext", "www", "pay.py"), "x")
		(ev,) = self.run_once(w, epoch=1100)[1]
		self.assertEqual((ev["severity"], ev["payload"]["added_web_code"]), ("warning", ["erpnext/www/pay.py"]))
		self.assertIn("new web code", ev["title"])

	def test_worktree_heads_resolve_through_the_common_dir(self):
		common = os.path.join(self.root, "repo.git")
		write(os.path.join(common, "refs", "heads", "develop"), "e" * 40 + "\n")
		worktree_git = os.path.join(common, "worktrees", "erpnext")
		write(os.path.join(worktree_git, "HEAD"), "ref: refs/heads/develop\n")
		write(os.path.join(worktree_git, "commondir"), "../..\n")
		app = os.path.join(self.root, "wt-app")
		write(os.path.join(app, ".git"), f"gitdir: {worktree_git}\n")
		self.assertEqual(integrity.git_head(app), "e" * 40)

	def test_large_files_are_compared_by_size_and_time(self):
		big = os.path.join(self.app, "erpnext", "fixtures.json")
		write(big, "x" * 64)
		saved = integrity.MAX_HASH_BYTES
		integrity.MAX_HASH_BYTES = 10
		try:
			w = self.watcher()
			self.run_once(w)
			self.assertEqual(w.state["groups"][f"code:{self.app}"]["files"][big][2], "size:64")
			write(big, "y" * 65)
			(ev,) = self.run_once(w, epoch=1100)[1]
			self.assertEqual(ev["payload"]["modified"], ["erpnext/fixtures.json"])
		finally:
			integrity.MAX_HASH_BYTES = saved

	def test_a_pass_stops_at_its_budget_and_keeps_the_rest(self):
		w = self.watcher()
		self.run_once(w)
		saved = integrity.MAX_FILES
		integrity.MAX_FILES = 1
		try:
			write(os.path.join(self.etc, "conf.d", "late.conf"), "x")
			self.assertEqual(self.run_once(w, epoch=1100)[1], [], "the host's path was not reached")
			self.assertIn(f"server:{self.etc}", w.state["groups"], "its baseline is kept")
		finally:
			integrity.MAX_FILES = saved
		(ev,) = self.run_once(w, epoch=1200)[1]
		self.assertEqual(ev["payload"]["added"], ["conf.d/late.conf"])

	def test_a_bench_missing_from_discovery_keeps_its_baseline(self):
		w = self.watcher()
		self.run_once(w)
		benches, self.benches = self.benches, []
		self.run_once(w, epoch=1100)  # a discovery hiccup
		self.benches = benches
		write(os.path.join(self.app, "erpnext", "api.py"), "changed meanwhile")
		(ev,) = self.run_once(w, epoch=1200)[1]
		self.assertEqual(ev["payload"]["modified"], ["erpnext/api.py"])

	def test_a_removed_app_is_reported_once(self):
		import shutil

		w = self.watcher()
		self.run_once(w)
		shutil.rmtree(self.app)
		(ev,) = self.run_once(w, epoch=1100)[1]
		self.assertEqual((ev["category"], ev["severity"], ev["payload"]["removed"]), ("bench_code_changed", "warning", True))
		self.assertEqual(ev["payload"]["deleted"], ["erpnext/api.py"])
		self.assertEqual(self.run_once(w, epoch=1200)[1], [])

	@unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads everything")
	def test_unreadable_is_not_deleted(self):
		w = self.watcher()
		self.run_once(w)
		folder = os.path.join(self.app, "erpnext")
		os.chmod(folder, 0)
		try:
			metrics, events = self.run_once(w, epoch=1100)
		finally:
			os.chmod(folder, 0o755)
		self.assertEqual(events, [])
		self.assertEqual({m["bench"]: m["value"] for m in metrics if m["metric_name"] == "integrity_unreadable"}["frappe-bench"], 1)

	def test_same_keys_and_values_raise_nothing(self):
		w = self.watcher()
		self.run_once(w)
		path = os.path.join(self.bench, "sites", "erp.example.com", "site_config.json")
		with open(path) as f:
			data = json.load(f)
		write(path, json.dumps(data, indent=2))  # reformatted
		self.assertEqual(self.run_once(w, epoch=1100)[1], [])

	def test_private_files_and_keyed_values(self):
		self.run_once()
		for name in (self.state, os.path.join(self.root, integrity.KEY_FILE)):
			self.assertEqual(os.stat(name).st_mode & 0o777, 0o600, name)
		with open(self.state) as f:
			stored = f.read()
		import hashlib

		plain = hashlib.sha256(json.dumps("secret-1").encode()).hexdigest()
		self.assertNotIn(plain, stored, "a plain hash of a password could be brute-forced")
		self.assertNotIn("secret-1", stored)

	def test_git_head_forms(self):
		self.assertEqual(integrity.git_head(self.app), "a" * 40)
		write(os.path.join(self.app, ".git", "HEAD"), "c" * 40 + "\n")  # detached
		self.assertEqual(integrity.git_head(self.app), "c" * 40)
		os.remove(os.path.join(self.app, ".git", "refs", "heads", "version-15"))
		write(os.path.join(self.app, ".git", "HEAD"), "ref: refs/heads/version-15\n")
		write(os.path.join(self.app, ".git", "packed-refs"), "# pack-refs\n" + "d" * 40 + " refs/heads/version-15\n")
		self.assertEqual(integrity.git_head(self.app), "d" * 40)
		self.assertIsNone(integrity.git_head(os.path.join(self.root, "nowhere")))


if __name__ == "__main__":
	unittest.main()
