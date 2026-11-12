import ast
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "launcher.py"


class LauncherStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.app = next(
            node for node in cls.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "App"
        )
        cls.methods = {
            node.name for node in cls.app.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def test_all_navigation_pages_exist(self):
        required = {
            "page_play", "page_stats", "page_accounts", "page_versions",
            "page_mods", "page_settings", "page_doctor", "page_servers",
            "page_worlds", "page_more",
        }
        self.assertTrue(required.issubset(self.methods), sorted(required - self.methods))

    def test_page_builder_targets_exist(self):
        builders = None
        for node in ast.walk(self.app):
            if not isinstance(node, ast.Assign):
                continue
            if any(isinstance(t, ast.Attribute) and t.attr == "builders" for t in node.targets):
                builders = node.value
                break
        self.assertIsInstance(builders, ast.Dict, "App.builders must be a dictionary")
        targets = {
            value.attr for value in builders.values
            if isinstance(value, ast.Attribute)
        }
        self.assertTrue(targets.issubset(self.methods), sorted(targets - self.methods))

    def test_restored_helpers_exist(self):
        required = {
            "version_label", "open_game_folder", "set_placeholder",
            "update_ram_label", "server_entries", "parse_server_address",
        }
        self.assertTrue(required.issubset(self.methods), sorted(required - self.methods))

    def test_no_duplicate_app_methods(self):
        names = [
            node.name for node in self.app.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        self.assertEqual(duplicates, [])

    def test_monochrome_shell_has_no_wallpaper_dependency(self):
        self.assertIn('self.geometry("1040x700")', self.source)
        self.assertIn("self.stage = tk.Frame(self", self.source)
        self.assertNotIn("_wallpaper_source", self.source)
        self.assertNotIn("background.jpg", self.source)
        self.assertIn("def go_back(self):", self.source)
        self.assertIn("self.page_history = []", self.source)

    def test_custom_controls_and_text_motion_are_present(self):
        self.assertIn("class Btn(tk.Canvas):", self.source)
        self.assertIn("class Field(tk.Canvas):", self.source)
        self.assertIn("class Toggle(tk.Canvas):", self.source)
        self.assertIn("def _animate_label(self", self.source)
        self.assertIn("style=\"nav\"", self.source)
        self.assertIn("Toggle(option_row", self.source)


if __name__ == "__main__":
    unittest.main()
