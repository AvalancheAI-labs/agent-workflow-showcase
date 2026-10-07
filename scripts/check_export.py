"""Heuristic release hygiene check; print locations, never matched values."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED = {".venv", "__pycache__", ".pytest_cache", "data", ".git"}
PATTERNS = {
    "private key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "credential URL": r"://[^\s:/]+:[^\s@/]{6,}@",
    "provider credential": r"\b(?:sk-ant-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{20,})",
}
problems = []
count = 0
for file in ROOT.rglob("*"):
    if not file.is_file() or any(part in EXCLUDED for part in file.relative_to(ROOT).parts):
        continue
    if file.name.startswith(".env") and file.name != ".env.example":
        problems.append((str(file.relative_to(ROOT)), "non-template environment file"))
    text = file.read_text(encoding="utf-8")
    count += 1
    for category, pattern in PATTERNS.items():
        if re.search(pattern, text, re.I):
            problems.append((str(file.relative_to(ROOT)), category))
    if file.suffix == ".py":
        ast.parse(text, filename=str(file))
print(f"Checked {count} text files and Python syntax; {len(problems)} indicators.")
for location, category in problems:
    print(f"{location}: {category}")
raise SystemExit(bool(problems))
