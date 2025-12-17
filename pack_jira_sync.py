"""
Utility script to package selected project files into a 7z archive while
temporarily sanitizing sensitive fields in jira_config.json.

Steps performed:
1. Load jira_config.json and stash the original content in memory.
2. Overwrite jira_config.json with placeholder values:
   - source.email -> "YOUR-EMAIL-ADDRESS"
   - source.apiToken -> "YOUR-API-TOKEN"
   - target.apiToken -> "YOUR-API-TOKEN" (kept consistent for safety)
3. Create jira_sync_automation.7z containing:
   - jira_config.json
   - jira_field_mapping.json
   - sync_issues.py
   - README.md
   - requirements.txt
4. Restore the original jira_config.json even if packaging fails.

Usage:
    python pack_jira_sync.py

Prerequisites:
    - 7z (7-Zip) must be available in PATH.
"""

import json
import subprocess
import shutil
from pathlib import Path
from typing import Dict, Any, List


PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "jira_config.json"
FILES_TO_PACKAGE = [
    PROJECT_ROOT / "jira_config.json",
    PROJECT_ROOT / "jira_field_mapping.json",
    PROJECT_ROOT / "sync_issues.py",
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "requirements.txt",
]
REQUIRED_FILES = {p.name for p in FILES_TO_PACKAGE}  # all listed files are required
OUTPUT_7Z = PROJECT_ROOT / "jira_sync_automation.7z"


def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_config(path: Path, data: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def sanitize_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a sanitized copy with placeholders; does not mutate input."""
    import copy

    sanitized = copy.deepcopy(data)
    source_cfg = sanitized.get("source", {})
    target_cfg = sanitized.get("target", {})

    if isinstance(source_cfg, dict):
        if "email" in source_cfg:
            source_cfg["email"] = "YOUR-EMAIL-ADDRESS"
        if "apiToken" in source_cfg:
            source_cfg["apiToken"] = "YOUR-API-TOKEN"
        if "projectKey" in source_cfg:
            source_cfg["projectKey"] = "YOUR-PROJECT-KEY"
    if isinstance(target_cfg, dict):
        if "apiToken" in target_cfg:
            target_cfg["apiToken"] = "YOUR-API-TOKEN"
        if "projectKey" in target_cfg:
            target_cfg["projectKey"] = "YOUR-PROJECT-KEY"
    return sanitized


def build_file_list(paths: List[Path]) -> List[Path]:
    """Return existing files; raise if any required file is missing."""
    existing: List[Path] = []
    missing: List[str] = []
    for p in paths:
        if p.exists():
            existing.append(p)
        else:
            missing.append(p.name)
    if missing:
        raise FileNotFoundError(f"Required file(s) missing: {', '.join(missing)}")
    return existing


def find_7z_executable() -> str:
    """Locate 7z executable; raise helpful error if not found."""
    candidates = [
        "7z",
        "7za",
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ]
    for c in candidates:
        found = shutil.which(c) if not Path(c).is_absolute() else (c if Path(c).exists() else None)
        if found:
            return found
    raise FileNotFoundError(
        "7z executable not found. Please install 7-Zip and ensure 7z/7za is in PATH, "
        "or update the candidates in find_7z_executable()."
    )


def create_7z_archive(files: List[Path], output_path: Path) -> None:
    if not files:
        raise RuntimeError("No files to package.")
    seven_zip = find_7z_executable()
    cmd = [seven_zip, "a", "-t7z", str(output_path)] + [str(p) for p in files]
    print(f"[Info] Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    print(f"[Done] Created archive: {output_path}")


def main():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    original_config = load_config(CONFIG_PATH)
    sanitized_config = sanitize_config(original_config)

    try:
        # Write sanitized config
        save_config(CONFIG_PATH, sanitized_config)
        print("[Info] jira_config.json sanitized for packaging.")

        files = build_file_list(FILES_TO_PACKAGE)
        create_7z_archive(files, OUTPUT_7Z)

    finally:
        # Restore original config no matter what happens
        save_config(CONFIG_PATH, original_config)
        print("[Info] jira_config.json restored to original content.")


if __name__ == "__main__":
    main()

