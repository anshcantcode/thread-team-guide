"""CPU-only operator selection and loopback observer boundaries; no SDK/model."""
from contextlib import redirect_stdout
import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from scripts import fdb3_live_demo as demo


class CandidateTests(unittest.TestCase):
    def fixture(self, root):
        manifest = {"recordings": []}
        cases = [(["SELF_CORRECTION"], ["add_to_cart"]),
                 (["FALSE_START", "FILLER"], ["book_flight"]),
                 (["FILLER"], ["add_to_cart"]),
                 (["SELF_CORRECTION"], ["search_products"]),
                 (["FALSE_START"], ["search_products", "add_to_cart"]),
                 (["FALSE_START"], ["add_to_cart", "add_to_cart"]),
                 (["SELF_CORRECTION"], [])]
        for index, (features, functions) in enumerate(cases):
            folder = root / "evaluator-data" / f"authored-{index}"
            folder.mkdir(parents=True)
            metadata = folder / "metadata.json"
            metadata.write_text(json.dumps({"disfluency_features": features,
                "dialogue": "SECRET_DIALOGUE_NOT_FOR_AGENT", "num_expected_calls": 1,
                "expected_tool_calls": [{"function": name, "args": {"secret": "EXPECTED_NOT_FOR_AGENT"}}
                                        for name in functions]}), encoding="utf-8")
            manifest["recordings"].append({"recording": folder.name,
                "relative_path": f"{folder.name}/input.wav", "metadata_sha256": demo.file_hash(metadata),
                "duration_seconds": 10 + index})
        (root / "dataset-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return manifest

    def test_list_filters_features_and_exactly_one_write_without_printing_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.fixture(root)
            rows = demo.demo_candidates(root, manifest)
            self.assertEqual([r["index"] for r in rows], [0, 1])
            output = io.StringIO()
            with redirect_stdout(output), patch.object(demo, "run_demo", side_effect=AssertionError("must stay offline")):
                self.assertEqual(demo.main(["--list", "--assets", str(root)]), 0)
            self.assertIn("authored-0", output.getvalue())
            self.assertIn("authored-1", output.getvalue())
            self.assertNotIn("authored-2", output.getvalue())
            self.assertNotIn("SECRET_DIALOGUE", output.getvalue())
            self.assertNotIn("EXPECTED_NOT_FOR_AGENT", output.getvalue())

    def test_changed_metadata_and_escaping_audio_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.fixture(root)
            (root / "evaluator-data/authored-0/metadata.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "metadata hash mismatch"):
                demo.demo_candidates(root, manifest)
            with self.assertRaisesRegex(ValueError, "escapes"):
                demo.asset_path(root, {"relative_path": "../../input.wav"})

    def test_exact_index_or_id_and_neutral_worker_boundary(self):
        manifest = {"recordings": [{"recording": "operator-only-id"}]}
        self.assertEqual(demo.select_recording(manifest, "0")[0], 0)
        self.assertEqual(demo.select_recording(manifest, "operator-only-id")[0], 0)
        for bad in ("-1", "1", "operator", "../input.wav"):
            with self.assertRaises(ValueError):
                demo.select_recording(manifest, bad)
        command = demo.worker_command(Path("neutral-take"), Path("model"), "http://127.0.0.1:8098/v1", "Qwen3.5-4B")
        self.assertEqual(command[-2:], ["--room", "--demo"])
        self.assertEqual(set(arg for arg in command if arg.startswith("--")),
                         {"--audio", "--output", "--contract", "--whisper", "--endpoint", "--model", "--room", "--demo"})
        self.assertTrue(command[command.index("--audio") + 1].endswith("input.wav"))
        self.assertNotIn("operator-only-id", " ".join(command))
        self.assertNotIn("evaluator", " ".join(command))

    def test_take_is_fresh_and_cannot_enter_campaigns_or_external_junction_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.object(demo, "ROOT", root):
                first = demo.create_take(root / "evidence")
                second = demo.create_take(root / "evidence")
                self.assertNotEqual(first, second)
                with self.assertRaises(ValueError):
                    demo.create_take(root / ".thread-run/raw")
                with self.assertRaises(ValueError):
                    demo.create_take(root.parent / "outside-this-checkout")


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / "identity.json").write_text('{"fixture":true}')
        (self.root / "demo-live.html").write_text("<p>fixture observer</p>")
        (self.root / ".env").write_text("PRIVATE")
        (self.root / "benchmark").mkdir()
        (self.root / "benchmark/tool-calls.jsonl").write_text('{"phase":"dispatch_intent"}\n{"phase":')
        self.server = demo.viewer_server(self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.directory.cleanup()

    def get(self, path, method="GET", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_only_exact_allowed_read_paths_and_live_partial_bytes(self):
        for path in ("/", "/identity.json", "/benchmark/tool-calls.jsonl?poll=1"):
            status, headers, body = self.get(path)
            self.assertEqual(status, 200)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertTrue(body)
        body = self.get("/benchmark/tool-calls.jsonl")[2]
        self.assertTrue(body.endswith(b'{"phase":'))  # Observer, not server, withholds incomplete rows.
        for path in ("/.env", "/worker.log", "/source/scripts/fdb3_audio_worker.py", "/benchmark/",
                     "/../identity.json", "/%2e%2e/identity.json", "/%2e%2e%5c.env",
                     "/%252e%252e/.env", "/identity.json/../.env", "/benchmark/result.json"):
            self.assertEqual(self.get(path)[0], 404, path)
        self.assertEqual(self.get("/identity.json", "HEAD")[2], b"")

    def test_no_writes_rebinding_or_escape_via_resolved_path(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertEqual(self.get("/identity.json", method)[0], 405)
        self.assertEqual(self.get("/identity.json", headers={"Host": "attacker.invalid"})[0], 403)
        original = Path.resolve
        def resolve(path, *args, **kwargs):
            return self.root.parent / "outside.json" if path.name == "identity.json" else original(path, *args, **kwargs)
        with patch.object(Path, "resolve", resolve):
            self.assertEqual(self.get("/identity.json")[0], 404)
        # A symlink/junction must not turn an allowed name into an unlisted file,
        # even if that private file happens to live inside the take directory.
        private = self.root / "private.json"
        private.write_text('{"private":true}')
        with patch.object(Path, "resolve", lambda path: private if path.name == "identity.json" else original(path)):
            self.assertEqual(self.get("/identity.json")[0], 404)
        self.assertEqual((self.root / "identity.json").read_text(), '{"fixture":true}')

    def test_free_port_is_reserved_and_8765_forbidden(self):
        self.assertNotEqual(self.server.server_port, 8765)
        with self.assertRaises(OSError):
            demo.viewer_server(self.root, self.server.server_port)
        with self.assertRaisesRegex(ValueError, "8765"):
            demo.viewer_server(self.root, 8765)


if __name__ == "__main__":
    unittest.main()
