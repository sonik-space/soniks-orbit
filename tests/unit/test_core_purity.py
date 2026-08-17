"""Правило 1: ядро не импортирует ничего, кроме stdlib, numpy, scipy, sgp4.

Ядро — единственная часть, которая переживёт переезд на v2 без изменений,
и оно же должно гоняться из голого скрипта фазы 0 и из тестов без поднятия БД.
Один импорт `sqlalchemy` в `fit.py` — и оно перестаёт быть портируемым.

Тест неудаляемый (ai-development-rules.md §5).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

CORE_DIRS = ("domain/od", "domain/waterfall")

ALLOWED_THIRD_PARTY = {"numpy", "scipy", "sgp4"}

FORBIDDEN_EXAMPLES = {
    "fastapi",
    "sqlalchemy",
    "httpx",
    "requests",
    "pydantic",
    "PIL",
    "dishka",
    "taskiq",
}

SRC = Path(__file__).resolve().parents[2] / "src"


def _core_files() -> list[Path]:
    files: list[Path] = []
    for rel in CORE_DIRS:
        d = SRC / rel
        if d.is_dir():
            files.extend(sorted(d.rglob("*.py")))
    return files


def _top_level_imports(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # Относительные импорты — внутри ядра, они разрешены.
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def test_core_dirs_are_not_empty() -> None:
    """Иначе тест зеленеет на пустом месте и перестаёт что-либо охранять."""
    assert _core_files(), f"в {SRC} не найдено ни одного файла ядра"


@pytest.mark.parametrize("path", _core_files(), ids=lambda p: p.name)
def test_core_module_imports_only_allowed(path: Path) -> None:
    imported = _top_level_imports(ast.parse(path.read_text(encoding="utf-8")))
    stdlib = sys.stdlib_module_names
    bad = {
        name
        for name in imported
        if name not in stdlib and name not in ALLOWED_THIRD_PARTY
    }
    assert not bad, (
        f"{path.relative_to(SRC)} импортирует запрещённое: {sorted(bad)}. "
        f"Ядру можно только stdlib, {sorted(ALLOWED_THIRD_PARTY)}. "
        f"Ввод-вывод и декодирование PNG — это инфраструктура, не алгоритм."
    )


def test_forbidden_examples_are_actually_forbidden() -> None:
    """Проверка самого теста: перечисленные в правиле 1 пакеты не в белом списке."""
    assert not (FORBIDDEN_EXAMPLES & ALLOWED_THIRD_PARTY)
    assert not (FORBIDDEN_EXAMPLES & set(sys.stdlib_module_names))
