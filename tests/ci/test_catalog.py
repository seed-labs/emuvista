"""Ensure every example participates in compilation."""

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import yaml

MODULE_PATH = Path(__file__).resolve().parents[1] / 'run_examples.py'
SPEC = importlib.util.spec_from_file_location('run_examples', MODULE_PATH)
catalog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalog)


class CatalogTests(unittest.TestCase):
    def test_all_example_directories_have_enabled_compile_tests(self):
        manifests = catalog.examples()
        directories = {path.relative_to(catalog.ROOT)
                       for category, prefix in (('examples', 'H'), ('experiments', 'E'))
                       for path in (catalog.ROOT / category).glob(prefix + '[0-9][0-9]*')
                       if path.is_dir()}
        self.assertTrue(directories)
        self.assertEqual({path.parent for path in manifests.values()}, directories)
        for manifest in manifests.values():
            with self.subTest(manifest=str(manifest)):
                path = catalog.ROOT / manifest
                settings = yaml.safe_load(path.read_text())
                self.assertTrue(settings.get('compile', {}).get('enabled', True))
                self.assertTrue((path.parent / settings['script']).is_file())

    def test_missing_manifest_fails_discovery(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'examples/H01_new_example').mkdir(parents=True)
            with patch.object(catalog, 'ROOT', root):
                with self.assertRaisesRegex(ValueError, 'Missing compile test manifest'):
                    catalog.examples()

    def test_duplicate_codes_cannot_overwrite_an_example(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('H01_first', 'H01_second'):
                directory = root / 'examples' / name
                directory.mkdir(parents=True)
                (directory / 'example.yaml').touch()
            with patch.object(catalog, 'ROOT', root):
                with self.assertRaisesRegex(ValueError, 'Duplicate example code: H01'):
                    catalog.examples()


if __name__ == '__main__':
    unittest.main()
