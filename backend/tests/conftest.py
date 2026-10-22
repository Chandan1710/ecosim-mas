"""Tests never touch the real learning database: point it at a throwaway SQLite file."""
import os
import tempfile

_dir = tempfile.mkdtemp(prefix="ecosim-test-")
os.environ["ECOSIM_EXPERIENCE_DB"] = f"sqlite:///{_dir}/experience.db"
