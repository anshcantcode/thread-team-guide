"""Provider-free configuration/packaging guards, runnable in Windows phase 1."""
from pathlib import Path
import unittest

from scripts.fdb3_config import candidate_environment, load_config, shell_config

ROOT = Path(__file__).resolve().parents[1]


class CandidateConfigTests(unittest.TestCase):
    def test_candidate_rejects_every_conflicting_feature_override(self):
        expected = load_config()["environment"]
        self.assertEqual(candidate_environment(environ={}), expected)
        for key in expected:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "Candidate drift"):
                candidate_environment(environ={key: "wrong"})

    def test_cpu_is_explicitly_a_different_component_profile(self):
        self.assertEqual(candidate_environment("cpu-component", {})["THREAD_FDB3_WHISPER_DEVICE"], "cpu")
        with self.assertRaises(ValueError):
            candidate_environment("unregistered", {})

    def test_planner_pin_matches_candidate_cache_and_thread_requirements(self):
        llama = load_config()["llama"]
        self.assertEqual(llama["commit"], "56381e407c0ccfb3a6f71e668a27a901001d22ce")
        args = llama["args"]
        for flag, value in (("--ctx-size", "8192"), ("--parallel", "1"),
                            ("--cache-ram", "0"), ("--gpu-layers", "99"), ("--threads", "4")):
            self.assertEqual(args[args.index(flag) + 1], value)
        self.assertTrue(llama["slot_save_path_required"])
        self.assertIsNone(llama["seed"], "Do not invent a seed absent from measured launches")

    def test_both_launchers_consume_shared_configuration(self):
        self.assertIn('fdb3_config.py" --shell', (ROOT / 'scripts/reproduce_fdb3_linux.sh').read_text())
        self.assertIn('apply_environment()', (ROOT / 'scripts/fdb3_agent.py').read_text())
        docker = (ROOT / 'Dockerfile.fdb3').read_text()
        self.assertIn('config/fdb3-candidate.json', docker)
        self.assertIn('FROM cpu AS cuda', docker)
        for key in load_config()['environment']:
            self.assertNotIn(key + '=', docker, 'Do not maintain a second set of feature defaults')
        self.assertIn('WHISPER_SHA256', shell_config())


if __name__ == '__main__':
    unittest.main()
