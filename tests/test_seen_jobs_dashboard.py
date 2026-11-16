"""Unit and integration tests for tools/seen_jobs_dashboard.py."""

import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.request
from datetime import date, timedelta
from http.server import HTTPServer
from pathlib import Path

from tools.seen_jobs_dashboard import (
    SeenJobsHTTPRequestHandler,
    create_backup,
    delete_by_date,
    delete_keys,
    delete_max_cap,
    delete_older_than,
    export_standalone_html,
    list_backups,
    load_data,
    restore_backup,
    save_data,
)


class TestSeenJobsDataLayer(unittest.TestCase):
    """Test data loading, saving, backup, and restore routines."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_seen_jobs_"))
        self.state_file = self.test_dir / "seen_jobs.json"
        self.sample_doc = {
            "seen": {
                "job1": {
                    "title": "Backend Engineer",
                    "company": "Acme Corp",
                    "posted_date": "2026-11-10",
                    "first_seen": "2026-11-12",
                    "rank_score": 88,
                    "portal": "linkedin-search",
                },
                "job2": {
                    "title": "Golang Developer",
                    "company": "Beta LLC",
                    "posted_date": "2026-11-14",
                    "first_seen": "2026-11-15",
                    "rank_score": 92,
                    "portal": "freehire-search",
                },
                "job3": {
                    "title": "Distributed Systems Engineer",
                    "company": "Gamma Inc",
                    "posted_date": "2026-11-01",
                    "first_seen": "2026-11-02",
                    "rank_score": 70,
                    "portal": "linkedin-search",
                },
            }
        }
        save_data(self.state_file, self.sample_doc)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_load_and_save_data(self):
        doc, seen = load_data(self.state_file)
        self.assertEqual(len(seen), 3)
        self.assertIn("job1", seen)
        self.assertEqual(seen["job1"]["company"], "Acme Corp")

        # Test non-existent file returns empty doc
        non_existent = self.test_dir / "missing.json"
        doc_empty, seen_empty = load_data(non_existent)
        self.assertEqual(seen_empty, {})

    def test_create_and_restore_backup(self):
        backup_path = create_backup(self.state_file)
        self.assertIsNotNone(backup_path)
        self.assertTrue(backup_path.is_file())
        self.assertTrue(backup_path.name.startswith("seen_jobs.json.bak-"))

        backups = list_backups(self.test_dir)
        self.assertEqual(len(backups), 1)

        # Mutate current file
        doc, seen = load_data(self.state_file)
        del seen["job1"]
        save_data(self.state_file, doc)

        _, modified_seen = load_data(self.state_file)
        self.assertEqual(len(modified_seen), 2)

        # Restore from backup
        restored_count, restored_name = restore_backup(self.state_file)
        self.assertEqual(restored_count, 3)
        _, restored_seen = load_data(self.state_file)
        self.assertEqual(len(restored_seen), 3)
        self.assertIn("job1", restored_seen)


class TestSeenJobsDeletions(unittest.TestCase):
    """Test various deletion operations."""

    def setUp(self):
        self.doc = {
            "seen": {
                "job_old": {
                    "title": "Old Job",
                    "company": "Past Corp",
                    "posted_date": "2026-10-01",
                    "first_seen": "2026-10-05",
                    "rank_score": 60,
                },
                "job_mid": {
                    "title": "Mid Job",
                    "company": "Current Corp",
                    "posted_date": "2026-11-01",
                    "first_seen": "2026-11-02",
                    "rank_score": 75,
                },
                "job_new": {
                    "title": "New Job",
                    "company": "Future Corp",
                    "posted_date": "2026-11-15",
                    "first_seen": "2026-11-16",
                    "rank_score": 95,
                },
            }
        }

    def test_delete_keys(self):
        doc, deleted = delete_keys(self.doc, ["job_old", "non_existent"])
        self.assertEqual(deleted, 1)
        self.assertNotIn("job_old", doc["seen"])
        self.assertIn("job_new", doc["seen"])

    def test_delete_by_date_before(self):
        doc, deleted = delete_by_date(
            self.doc,
            field="first_seen",
            op="before",
            target_date=date(2026, 11, 1),
        )
        self.assertEqual(deleted, 1)
        self.assertNotIn("job_old", doc["seen"])
        self.assertIn("job_mid", doc["seen"])
        self.assertIn("job_new", doc["seen"])

    def test_delete_older_than(self):
        ref = date(2026, 11, 16)
        doc, deleted = delete_older_than(self.doc, days=10, field="first_seen", reference_date=ref)
        # 16 - 10 = Nov 6. job_old (Oct 5) and job_mid (Nov 2) are before Nov 6
        self.assertEqual(deleted, 2)
        self.assertNotIn("job_old", doc["seen"])
        self.assertNotIn("job_mid", doc["seen"])
        self.assertIn("job_new", doc["seen"])

    def test_delete_max_cap(self):
        doc, deleted = delete_max_cap(self.doc, keep_count=2, sort_by="first_seen")
        self.assertEqual(deleted, 1)
        self.assertEqual(len(doc["seen"]), 2)
        # Should keep job_new and job_mid, pruned job_old
        self.assertIn("job_new", doc["seen"])
        self.assertIn("job_mid", doc["seen"])
        self.assertNotIn("job_old", doc["seen"])


class TestSeenJobsAPIEndpoints(unittest.TestCase):
    """Test HTTP server endpoints using local ephemeral server."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path(tempfile.mkdtemp(prefix="test_server_"))
        cls.state_file = cls.test_dir / "seen_jobs.json"
        sample_doc = {
            "seen": {
                "item1": {
                    "title": "API Test Job",
                    "company": "Test Co",
                    "posted_date": "2026-11-12",
                    "first_seen": "2026-11-16",
                    "rank_score": 85,
                    "portal": "linkedin-search",
                }
            }
        }
        save_data(cls.state_file, sample_doc)

        class CustomHandler(SeenJobsHTTPRequestHandler):
            state_file = cls.state_file

        cls.server = HTTPServer(("127.0.0.1", 0), CustomHandler)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_get_root_html(self):
        req = urllib.request.urlopen(f"{self.base_url}/")
        self.assertEqual(req.status, 200)
        body = req.read().decode("utf-8")
        self.assertIn("Seen Jobs Explorer", body)
        self.assertIn("<!DOCTYPE html>", body)

    def test_get_api_jobs(self):
        req = urllib.request.urlopen(f"{self.base_url}/api/jobs")
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode("utf-8"))
        self.assertIn("seen", data)
        self.assertIn("item1", data["seen"])
        self.assertEqual(data["count"], 1)

    def test_get_api_status(self):
        req = urllib.request.urlopen(f"{self.base_url}/api/status")
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode("utf-8"))
        self.assertEqual(data["count"], 1)
        self.assertGreater(data["mtime"], 0)

    def test_post_delete_and_restore_api(self):
        # Post deletion
        payload = json.dumps({"action": "keys", "keys": ["item1"]}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/delete",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req)
        self.assertEqual(resp.status, 200)
        del_data = json.loads(resp.read().decode("utf-8"))
        self.assertTrue(del_data["success"])
        self.assertEqual(del_data["deleted_count"], 1)
        self.assertEqual(del_data["remaining_count"], 0)

        # Check job is gone
        req_jobs = urllib.request.urlopen(f"{self.base_url}/api/jobs")
        jobs_data = json.loads(req_jobs.read().decode("utf-8"))
        self.assertEqual(jobs_data["count"], 0)

        # Post restore
        req_restore = urllib.request.Request(
            f"{self.base_url}/api/restore",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp_restore = urllib.request.urlopen(req_restore)
        self.assertEqual(resp_restore.status, 200)
        restore_data = json.loads(resp_restore.read().decode("utf-8"))
        self.assertTrue(restore_data["success"])
        self.assertEqual(restore_data["restored_count"], 1)

        # Check job is back
        req_jobs2 = urllib.request.urlopen(f"{self.base_url}/api/jobs")
        jobs_data2 = json.loads(req_jobs2.read().decode("utf-8"))
        self.assertEqual(jobs_data2["count"], 1)


class TestStandaloneExport(unittest.TestCase):
    """Test offline HTML export generation."""

    def test_export(self):
        tmp_dir = Path(tempfile.mkdtemp(prefix="test_export_"))
        try:
            state_file = tmp_dir / "seen_jobs.json"
            export_file = tmp_dir / "export.html"
            sample = {
                "seen": {
                    "test_job": {
                        "title": "Lead Software Engineer",
                        "company": "DeepMind Partner",
                    }
                }
            }
            save_data(state_file, sample)
            export_standalone_html(state_file, export_file)
            self.assertTrue(export_file.is_file())
            content = export_file.read_text(encoding="utf-8")
            self.assertIn("window.EMBEDDED_SEEN_DATA", content)
            self.assertIn("Lead Software Engineer", content)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
