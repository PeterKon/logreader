"""Package the verified Windows release with licenses and matching source."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import zipfile


def stream_sha256(stream):
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def sha256(path):
    with path.open("rb") as stream:
        return stream_sha256(stream)


def checked_path(root, name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
        raise ValueError(f"Unsafe release path: {name}")
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Release path leaves its source folder: {name}")
    return path


def validate_files(root, expected, *, complete=False):
    if complete:
        actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
        if actual != set(expected):
            raise ValueError(
                f"File inventory changed in {root}: "
                f"missing={sorted(set(expected) - actual)}, extra={sorted(actual - set(expected))}"
            )
    for name, digest in expected.items():
        path = checked_path(root, name)
        if not path.is_file() or sha256(path) != digest:
            raise ValueError(f"File differs from the reviewed release: {path}")


def write_archive(destination, files):
    """Preserve the complete supplied tree and verify every member after writing."""
    expected = {}
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, source in sorted(files.items()):
            if isinstance(source, bytes):
                archive.writestr(name, source)
                expected[name] = hashlib.sha256(source).hexdigest()
            else:
                expected[name] = sha256(source)
                archive.write(source, name)
    with zipfile.ZipFile(destination) as archive:
        if len(archive.namelist()) != len(expected) or set(archive.namelist()) != set(expected):
            raise ValueError("ZIP inventory differs from the intended release")
        for name, digest in expected.items():
            with archive.open(name) as stream:
                if stream_sha256(stream) != digest:
                    raise ValueError(f"ZIP verification failed: {name}")


def package_release(root, bundle, output):
    assets = root / "packaging/windows-x64"
    manifest = json.loads((assets / "verified-release.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    validate_files(bundle, manifest["bundle"], complete=True)
    validate_files(root, manifest["application_source"])
    validate_files(assets / "licenses", manifest["licenses"], complete=True)

    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="package-", dir=output.resolve()) as temporary:
        work = Path(temporary)
        source_name = f"Logreader-v{version}-source.zip"
        source_files = {
            f"Logreader-v{version}/{name}": checked_path(root, name)
            for name in manifest["source_files"]
        }
        for path in assets.rglob("*"):
            if path.is_file():
                name = path.relative_to(root).as_posix()
                source_files[f"Logreader-v{version}/{name}"] = checked_path(root, name)
        source_files[f"Logreader-v{version}/BUILD.txt"] = (
            f"Logreader v{version} source\n\n"
            "Use Windows x64 and CPython 3.14.7. From this folder, run:\n"
            "python tools/setup_environment.py --constraints packaging/windows-x64/build-constraints.txt\n"
            ".local\\venv\\Scripts\\python.exe -B tools/build.py --clean --noconfirm\n\n"
            "The application is written to .local/dist/Logreader.\n"
            "Pinned dependency versions are in packaging/windows-x64/build-constraints.txt.\n"
            "Dependency sources are listed in packaging/windows-x64/THIRD-PARTY-SOURCES.txt.\n"
            "The package helper checks the reviewed release's exact file hashes. A new\n"
            "build requires renewed verification and an updated verified-release.json.\n"
        ).encode("utf-8")
        write_archive(work / source_name, source_files)

        files = {f"Logreader/{name}": checked_path(bundle, name) for name in manifest["bundle"]}
        files["Logreader/LICENSE"] = root / "LICENSE"
        for name in ("START-HERE.txt", "THIRD-PARTY-NOTICES.txt", "THIRD-PARTY-SOURCES.txt"):
            files[f"Logreader/{name}"] = assets / name
        for name in manifest["licenses"]:
            files[f"Logreader/licenses/{name}"] = assets / "licenses" / name
        files[f"Logreader/source/{source_name}"] = work / source_name
        inventory = "".join(
            f"{sha256(path)}  {name.removeprefix('Logreader/')}\n"
            for name, path in sorted(files.items())
        )
        files["Logreader/FILE-SHA256SUMS.txt"] = inventory.encode("utf-8")
        zip_name = f"Logreader-v{version}-windows-x64.zip"
        write_archive(work / zip_name, files)
        digest = sha256(work / zip_name)
        (work / f"{zip_name}.sha256").write_text(f"{digest}  {zip_name}\n", encoding="ascii")
        shutil.copyfile(assets / "release-notes.md", work / "release-notes.md")
        shutil.copyfile(assets / "THIRD-PARTY-SOURCES.txt", work / "THIRD-PARTY-SOURCES.txt")
        for path in work.iterdir():
            path.replace(output / path.name)
    return {"zip": str(output / zip_name), "sha256": digest, "files": len(files)}


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=root / ".local/dist/Logreader")
    parser.add_argument("--output", type=Path, default=root / ".local/releases/v0.8")
    args = parser.parse_args()
    print(json.dumps(package_release(root, args.bundle.resolve(), args.output.resolve()), indent=2))


if __name__ == "__main__":
    main()
