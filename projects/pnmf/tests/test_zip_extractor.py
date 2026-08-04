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


def test_export_framework_zip_adaptive_includes_sqlite(tmp_path):
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
        
        # Ensure core files are present
        assert any("pnmf_cli.py" in name for name in namelist)
        assert any("pnmf_ui.py" in name for name in namelist)


def test_export_framework_zip_exclude_data(tmp_path):
    dest_zip = str(tmp_path / "test_framework_nodata.zip")
    res = run_powershell(["-Destination", dest_zip, "-ExcludeData", "-Force"])
    assert res.returncode == 0, f"Powershell failed: {res.stderr}"

    assert os.path.exists(dest_zip)
    with zipfile.ZipFile(dest_zip, "r") as zf:
        namelist = zf.namelist()
        assert not any("anp_data.sqlite" in name for name in namelist), "anp_data.sqlite should be excluded when -ExcludeData is specified"
        assert any("pnmf_cli.py" in name for name in namelist)


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
