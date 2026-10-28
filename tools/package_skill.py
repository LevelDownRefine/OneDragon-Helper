"""Archive the distributable skill as a separate release asset."""

import argparse
import hashlib
import logging
import zipfile
from pathlib import Path

SKILL_NAME = "onedragon-helper"
SKILL_FILES = (
    "SKILL.md",
    "references/cli.md",
    "scripts/odh.py",
    "scripts/source_cache.py",
    "scripts/log_tools.py",
)
logger = logging.getLogger(__name__)


def archive_skill(skill: Path, output: Path) -> None:
    """Package required skill files, excluding caches and local runtime data."""
    if output.resolve().is_relative_to(skill.resolve()):
        raise ValueError("Skill archive must be outside the skill directory")
    files = []
    for name in SKILL_FILES:
        path = skill / name
        for component in (path, *path.parents):
            if component.is_symlink() or (
                hasattr(component, "is_junction") and component.is_junction()
            ):
                raise ValueError(f"Skill source must not be a link: {component}")
        if not path.is_file():
            raise FileNotFoundError(f"Required skill file is missing: {path}")
        files.append((path, f"{SKILL_NAME}/{name}"))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, name in files:
            archive.write(path, name)
    with output.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{digest}  {output.name}\n", encoding="ascii"
    )


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(f"{SKILL_NAME}-skill.zip"))
    args = parser.parse_args()
    archive_skill(root / ".agents" / "skills" / SKILL_NAME, args.output)
    logger.info("Created %s and its SHA-256 checksum", args.output)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
