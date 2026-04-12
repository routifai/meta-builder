"""
SkillsStore — controlled read/write access to the skills directory.

Access policy:
  - READ:  unrestricted — any agent or tool may call read() or list_skills()
  - WRITE: only through write_new() or update() — no direct file writes

This prevents agents from writing arbitrary .md files into skills/ while
still allowing the monitor's skills_updater to record new knowledge.

Usage:
    store = SkillsStore("skills")

    # Read — always allowed
    content = store.read("meta-builder-project.md")
    names   = store.list_skills()

    # Write — controlled API only
    store.write_new("my-new-skill.md", "# My Skill\\n...")
    store.update("my-new-skill.md", "# My Skill (revised)\\n...")
"""
from __future__ import annotations

from pathlib import Path


class SkillsStoreError(Exception):
    """Base error for SkillsStore violations."""


class SkillsStore:
    """
    Safe read/write facade for the skills/ markdown directory.

    Args:
        skills_dir: Path to the skills directory (default: "skills").
    """

    def __init__(self, skills_dir: str = "skills") -> None:
        self.skills_dir = Path(skills_dir)

    # ── Read access (unrestricted) ─────────────────────────────────────────

    def read(self, name: str) -> str:
        """
        Read a skill file by filename.

        Args:
            name: Filename, e.g. "meta-builder-project.md"

        Raises:
            FileNotFoundError: if the skill does not exist.
            SkillsStoreError: if name contains path separators or "..".
        """
        self._validate_name(name)
        path = self.skills_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Skill not found: {name!r} in {self.skills_dir}")
        return path.read_text(encoding="utf-8")

    def list_skills(self) -> list[str]:
        """Return sorted list of .md filenames in the skills directory."""
        if not self.skills_dir.exists():
            return []
        return sorted(p.name for p in self.skills_dir.glob("*.md"))

    def exists(self, name: str) -> bool:
        """Return True if the named skill file exists."""
        self._validate_name(name)
        return (self.skills_dir / name).exists()

    # ── Write access (controlled API) ─────────────────────────────────────

    def write_new(self, name: str, content: str) -> Path:
        """
        Create a new skill file via the controlled API.

        Agents MUST use this method instead of writing .md files directly.

        Args:
            name:    Plain filename ending in .md (no path separators).
            content: Full markdown content.

        Returns:
            The Path of the newly written file.

        Raises:
            ValueError:        if name is invalid (path separators, no .md suffix).
            FileExistsError:   if a skill with this name already exists.
            SkillsStoreError:  if name contains "..".
        """
        self._validate_name(name)
        if not name.endswith(".md"):
            raise ValueError(f"Skill filename must end in '.md': {name!r}")

        path = self.skills_dir / name
        if path.exists():
            raise FileExistsError(
                f"Skill {name!r} already exists. Use update() to modify it."
            )

        self.skills_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def update(self, name: str, content: str) -> Path:
        """
        Overwrite an existing skill file via the controlled API.

        Args:
            name:    Plain filename of an existing skill.
            content: New markdown content.

        Returns:
            The Path of the updated file.

        Raises:
            FileNotFoundError: if the skill does not exist (use write_new).
            SkillsStoreError:  if name contains "..".
        """
        self._validate_name(name)
        path = self.skills_dir / name
        if not path.exists():
            raise FileNotFoundError(
                f"Skill {name!r} not found. Use write_new() to create it."
            )
        path.write_text(content, encoding="utf-8")
        return path

    # ── Internal validation ────────────────────────────────────────────────

    @staticmethod
    def _validate_name(name: str) -> None:
        """Reject names containing path separators or traversal sequences."""
        if ".." in name:
            raise SkillsStoreError(f"Skill name must not contain '..': {name!r}")
        if "/" in name or "\\" in name:
            raise SkillsStoreError(
                f"Skill name must be a plain filename, not a path: {name!r}"
            )
        if not name:
            raise SkillsStoreError("Skill name must not be empty.")
