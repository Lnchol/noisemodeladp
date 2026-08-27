"""Tests for the PNMF adaptive zip extractor tool."""

import os
import shutil
import sqlite3
import subprocess
import zipfile
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(PROJECT_ROOT, "tools", "export_framework_zip.ps1")


def run_powershell(args):
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", SCRIPT_PATH] + args
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    return res


def test_export_framework_zip_adaptive_includes_sqlite_and_no_tools(tmp_path):
    dest_zip = str(tmp_path / "test_framework_adaptive.zip")
    res = run_powershell(["-Destination", dest_zip, "-Force"])
    assert res.returncode == 0, f"Powershell failed: {res.stderr}"

    assert os.path.exists(dest_zip)
    with zipfile.ZipFile(dest_zip, "r") as zf:
        namelist = zf.namelist()
        # Ensure SQLite database is adaptively included if present in project root
        sqlite_in_zip = any("anp_data.sqlite" in name for name in namelist)
        if os.path.exists(os.path.join(PROJECT_ROOT, "anp_data.sqlite")):
            assert sqlite_in_zip, "anp_data.sqlite should be adaptively included in the archive"
        
        # Ensure core runtime files are present
        assert any("pnmf_cli.py" in name for name in namelist)
        assert any("pnmf_ui.py" in name for name in namelist)
        assert any("Launch_PNMF.cmd" in name for name in namelist)
        assert any("pnmf.ps1" in name for name in namelist)

        # Ensure tools folder is NOT included in clean framework archive
        assert not any("tools/" in name for name in namelist), "tools folder should be excluded"


def test_export_repairs_invalid_existing_destination_without_force(tmp_path):
    dest_zip = str(tmp_path / "broken_framework.zip")
    with open(dest_zip, "wb") as handle:
        handle.write(b"not a zip archive")

    res = run_powershell(["-Destination", dest_zip])
    assert res.returncode == 0, f"Powershell failed: {res.stderr}"

    with zipfile.ZipFile(dest_zip, "r") as zf:
        assert zf.testzip() is None
        assert "pnmf-framework/PACKAGE_MANIFEST.txt" in zf.namelist()


def test_export_keeps_valid_existing_destination_without_force(tmp_path):
    dest_zip = str(tmp_path / "valid_framework.zip")
    first = run_powershell(["-Destination", dest_zip, "-ExcludeData"])
    assert first.returncode == 0, f"Initial Powershell export failed: {first.stderr}"
    original = open(dest_zip, "rb").read()

    res = run_powershell(["-Destination", dest_zip, "-ExcludeData"])
    assert res.returncode != 0
    assert b"Destination already exists" in res.stderr.encode()
    assert open(dest_zip, "rb").read() == original


def test_export_framework_zip_exclude_data(tmp_path):
    dest_zip = str(tmp_path / "test_framework_nodata.zip")
    res = run_powershell(["-Destination", dest_zip, "-ExcludeData", "-Force"])
    assert res.returncode == 0, f"Powershell failed: {res.stderr}"

    assert os.path.exists(dest_zip)
    with zipfile.ZipFile(dest_zip, "r") as zf:
        namelist = zf.namelist()
        assert not any("anp_data.sqlite" in name for name in namelist), "anp_data.sqlite should be excluded when -ExcludeData is specified"
        assert any("pnmf_cli.py" in name for name in namelist)
        assert not any("tools/" in name for name in namelist)


def test_adaptive_extractor_extract_mode(tmp_path):
    dest_zip = str(tmp_path / "test_framework_export.zip")
    extract_dir = str(tmp_path / "extracted_framework")

    # 1. Export archive
    res_export = run_powershell(["-Destination", dest_zip, "-Force"])
    assert res_export.returncode == 0, f"Export failed: {res_export.stderr}"

    # 2. Extract archive using adaptive extractor
    res_extract = run_powershell(["-Extract", "-SourceZip", dest_zip, "-ExtractTo", extract_dir, "-Force"])
    assert res_extract.returncode == 0, f"Extract failed: {res_extract.stderr}"

    assert os.path.exists(extract_dir)

    # Check extracted content
    extracted_sqlite = None
    for root, dirs, files in os.walk(extract_dir):
        if "anp_data.sqlite" in files:
            extracted_sqlite = os.path.join(root, "anp_data.sqlite")
            break

    if os.path.exists(os.path.join(PROJECT_ROOT, "anp_data.sqlite")):
        assert extracted_sqlite is not None, "Extracted directory should contain anp_data.sqlite"
        conn = sqlite3.connect(extracted_sqlite)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        conn.close()
        assert len(tables) > 0, "Extracted SQLite database should have tables"


def test_adaptive_export_custom_naming(tmp_path):
    dest_zip = str(tmp_path / "custom_framework.zip")
    res = run_powershell([
        "-Destination", dest_zip,
        "-PackageName", "custom-pnmf",
        "-TopLevelName", "custom-top",
        "-ExcludeData",
        "-Force"
    ])
    assert res.returncode == 0, f"Powershell export failed: {res.stderr}"

    with zipfile.ZipFile(dest_zip, "r") as zf:
        namelist = zf.namelist()
        # Ensure top level prefix is custom-top
        assert any(name.startswith("custom-top/") for name in namelist)
        # Ensure package code & calibration JSON are discovered
        assert any("pnmf/physics_calibration" in name and name.endswith(".json") for name in namelist)
        # Ensure tools folder is excluded
        assert not any("tools/" in name for name in namelist)


def test_adaptive_extractor_manifest_verification(tmp_path):
    dest_zip = str(tmp_path / "verified_framework.zip")
    extract_dir = str(tmp_path / "verified_extracted")

    res_export = run_powershell(["-Destination", dest_zip, "-ExcludeData", "-Force"])
    assert res_export.returncode == 0, f"Export failed: {res_export.stderr}"

    res_extract = run_powershell(["-Extract", "-SourceZip", dest_zip, "-ExtractTo", extract_dir, "-Force"])
    assert res_extract.returncode == 0, f"Extract failed: {res_extract.stderr}"
    assert "Verification: All" in res_extract.stdout


def test_adaptive_export_include_venv_storage_optimization(tmp_path):
    # Test venv packaging with a mock project root containing a dummy .venv with bytecode cache
    mock_root = tmp_path / "mock_project"
    mock_root.mkdir()
    (mock_root / "pnmf_cli.py").write_text("#!/usr/bin/env python\nprint('hello')")
    (mock_root / "requirements.txt").write_text("numpy\n")
    (mock_root / "README.md").write_text("# Mock\n")
    mock_pnmf = mock_root / "pnmf"
    mock_pnmf.mkdir()
    (mock_pnmf / "__init__.py").write_text("")
    (mock_pnmf / "physics_calibration_mock.json").write_text("{}")

    # Create dummy .venv with runtime python file and cache files to test pruning
    mock_venv = mock_root / ".venv"
    mock_venv_scripts = mock_venv / "Scripts"
    mock_venv_scripts.mkdir(parents=True)
    (mock_venv_scripts / "python.exe").write_text("fake-exe")
    mock_cache = mock_venv / "__pycache__"
    mock_cache.mkdir()
    (mock_cache / "cached.pyc").write_text("cached-bytecode")
    (mock_venv / "regular.py").write_text("print(1)")
    (mock_venv / "regular.pyc").write_text("cached-bytecode-2")

    dest_zip = str(tmp_path / "mock_venv_framework.zip")
    res = run_powershell([
        "-ProjectRoot", str(mock_root),
        "-Destination", dest_zip,
        "-IncludeVenv",
        "-ExcludeData",
        "-Force"
    ])
    assert res.returncode == 0, f"Export failed: {res.stderr}"

    with zipfile.ZipFile(dest_zip, "r") as zf:
        namelist = zf.namelist()
        # Verify .venv files are present
        assert any(".venv/Scripts/python.exe" in name for name in namelist)
        assert any(".venv/regular.py" in name for name in namelist)
        # Verify cache files were pruned to optimize storage
        assert not any("__pycache__" in name for name in namelist)
        assert not any(name.endswith(".pyc") for name in namelist)
        assert not any("tools/" in name for name in namelist)
