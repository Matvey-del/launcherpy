import ast
import base64
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "launcher.py"


class LauncherStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        cls.app = next(
            node for node in cls.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "App"
        )
        cls.methods = {
            node.name for node in cls.app.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
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

    def test_bundled_wallpaper_is_valid_jpeg(self):
        wallpaper = ROOT / "assets" / "background.jpg.b64"
        self.assertTrue(wallpaper.is_file(), "Bundled Minecraft wallpaper is missing")
        raw = base64.b64decode(wallpaper.read_text(encoding="ascii").strip(), validate=True)
        self.assertTrue(raw.startswith(b"\\xff\\xd8\\xff"), "Wallpaper payload is not a JPEG")

    def test_lainlauncher_brand_and_wallpaper_loader(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('self.title("LainLauncher · Minecraft")', source)
        self.assertIn("self._wallpaper_source_b64", source)
        self.assertIn("base64.b64decode", source)
        self.assertNotIn('if not os.path.isfile(self._wallpaper_source):', source)


if __name__ == "__main__":
    unittest.main()
