import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.package_release import package_release, sha256, validate_files


class PackageReleaseTests(unittest.TestCase):
    def test_release_preserves_payload_and_includes_notices_source_and_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle"
            assets = root / "packaging/windows-x64"
            inputs = {
                "bundle/Logreader.exe": b"reviewed application",
                "bundle/_internal/nested/plugin.dll": b"plugin",
                "LICENSE": b"project license",
                "src/app.py": b"print('matching source')",
                "packaging/windows-x64/licenses/Qt.txt": b"dependency license",
                "packaging/windows-x64/START-HERE.txt": b"launch instructions",
                "packaging/windows-x64/THIRD-PARTY-NOTICES.txt": b"notices",
                "packaging/windows-x64/THIRD-PARTY-SOURCES.txt": b"source locations",
                "packaging/windows-x64/release-notes.md": b"release notes",
            }
            for name, data in inputs.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            manifest = {
                "version": "0.8",
                "bundle": {name.removeprefix("bundle/"): hashlib.sha256(data).hexdigest()
                           for name, data in inputs.items() if name.startswith("bundle/")},
                "application_source": {"src/app.py": sha256(root / "src/app.py")},
                "licenses": {"Qt.txt": sha256(assets / "licenses/Qt.txt")},
                "source_files": ["LICENSE", "src/app.py"],
            }
            (assets / "verified-release.json").write_text(json.dumps(manifest))
            result = package_release(root, bundle, root / "output")
            archive_path = Path(result["zip"])
            self.assertEqual(result["sha256"], sha256(archive_path))
            self.assertEqual(
                archive_path.with_suffix(".zip.sha256").read_text(),
                f"{result['sha256']}  {archive_path.name}\n",
            )
            with zipfile.ZipFile(archive_path) as archive:
                for name, data in inputs.items():
                    if name.startswith("bundle/"):
                        self.assertEqual(archive.read("Logreader/" + name.removeprefix("bundle/")), data)
                for name in ("LICENSE", "START-HERE.txt", "THIRD-PARTY-NOTICES.txt",
                             "THIRD-PARTY-SOURCES.txt", "licenses/Qt.txt"):
                    self.assertIn("Logreader/" + name, archive.namelist())
                self.assertEqual(
                    archive.read("Logreader/source/Logreader-v0.8-source.zip"),
                    (root / "output/Logreader-v0.8-source.zip").read_bytes(),
                )
                for line in archive.read("Logreader/FILE-SHA256SUMS.txt").decode().splitlines():
                    digest, name = line.split("  ", 1)
                    self.assertEqual(hashlib.sha256(archive.read("Logreader/" + name)).hexdigest(), digest)
            with zipfile.ZipFile(root / "output/Logreader-v0.8-source.zip") as source:
                self.assertEqual(source.read("Logreader-v0.8/src/app.py"), inputs["src/app.py"])
                self.assertIn("Logreader-v0.8/BUILD.txt", source.namelist())

    def test_changed_missing_or_additional_files_require_new_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            file = root / "component.dll"
            file.write_bytes(b"reviewed")
            expected = {file.name: sha256(file)}
            validate_files(root, expected, complete=True)
            file.write_bytes(b"new component version")
            with self.assertRaisesRegex(ValueError, "differs from the reviewed release"):
                validate_files(root, expected, complete=True)
            file.unlink()
            with self.assertRaisesRegex(ValueError, "missing="):
                validate_files(root, expected, complete=True)
            file.write_bytes(b"reviewed")
            (root / "unexpected.dll").write_bytes(b"unreviewed component")
            with self.assertRaisesRegex(ValueError, "extra="):
                validate_files(root, expected, complete=True)


if __name__ == "__main__":
    unittest.main()
