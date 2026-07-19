import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "neo4j_navigator.py"
SPEC = importlib.util.spec_from_file_location("neo4j_navigator", MODULE_PATH)
engine = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = engine
SPEC.loader.exec_module(engine)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.payload


class Neo4jNavigatorTests(unittest.TestCase):
    def test_noneish_defaults_and_bounds(self):
        self.assertEqual(engine._parse_int("None", 12, 1, 50), 12)
        self.assertEqual(engine._parse_int("999", 12, 1, 50), 50)
        self.assertEqual(engine._csv("None", "name,title"), ["name", "title"])

    def test_query_api_response_is_normalized(self):
        payload = {"data": {"fields": ["ready"], "values": [[1]]}, "bookmarks": []}
        env = {"NEO4J_PASSWORD": "secret", "NEO4J_HTTP_URL": "http://127.0.0.1:7474"}
        with patch.dict(os.environ, env, clear=True), patch.object(engine, "urlopen", return_value=FakeResponse(payload)):
            result = engine._run_query("RETURN 1 AS ready")
        self.assertEqual(result["rows"], [{"ready": 1}])

    def test_branch_depth_is_bounded_in_generated_query(self):
        captured = {}

        def fake(statement, parameters=None):
            captured["statement"] = statement
            captured["parameters"] = parameters
            return {"rows": [], "notifications": []}

        with patch.object(engine, "_run_query", side_effect=fake):
            result = engine.explore_branches("Switchbay", depth="99", limit="None")
        self.assertTrue(result["ok"])
        self.assertIn("[*1..4]", captured["statement"])
        self.assertEqual(captured["parameters"]["limit"], 50)

    def test_invalid_label_is_rejected(self):
        with self.assertRaises(ValueError):
            engine.search_nodes("test", label="Thing`) MATCH (n) DETACH DELETE n //")

    def test_status_does_not_echo_password(self):
        env = {"NEO4J_PASSWORD": "super-secret", "NEO4J_HTTP_URL": "http://127.0.0.1:1"}
        with patch.dict(os.environ, env, clear=True):
            result = engine.status()
        self.assertNotIn("super-secret", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
