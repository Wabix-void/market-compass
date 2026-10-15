"""原始层落盘工具：所有采集适配器共用同一套输出格式。

目录约定：
    data/raw/<source>/platforms.jsonl
    data/raw/<source>/categories.jsonl
    data/raw/<source>/listings.jsonl
    data/raw/<source>/signals.jsonl
    data/raw/<source>/reviews.jsonl
    data/raw/<source>/search_heat.jsonl
    data/raw/<source>/collect_meta.json      # 采集元信息（robots 判定、字段范围等）

只要产出这套格式，下游 ETL / 指标 / AI / 看板就无需任何改动。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = PROJECT_ROOT / "data" / "raw"


def source_dir(source: str) -> Path:
    return RAW_ROOT / source


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def merge_by_key(path: Path, rows: list[dict], keys: tuple[str, ...]) -> list[dict]:
    """按主键合并旧数据，多次采集不会产生重复行。"""
    merged: dict[tuple, dict] = {}
    for row in read_jsonl(path):
        merged[tuple(row.get(key) for key in keys)] = row
    for row in rows:
        merged[tuple(row.get(key) for key in keys)] = row
    return list(merged.values())


def persist(source: str, meta: dict, *, platform: dict, categories: list[dict],
            listings: list[dict], signals: list[dict], reviews: list[dict] | None = None,
            heat: list[dict] | None = None) -> None:
    """把一次采集的结果按原始层格式落盘（增量合并）。"""
    root = source_dir(source)
    root.mkdir(parents=True, exist_ok=True)

    write_jsonl(root / "platforms.jsonl", [platform])
    if categories:
        write_jsonl(root / "categories.jsonl", categories)
    write_jsonl(root / "listings.jsonl",
                merge_by_key(root / "listings.jsonl", listings, ("product_id",)))
    write_jsonl(root / "signals.jsonl",
                merge_by_key(root / "signals.jsonl", signals, ("product_id", "stat_date")))
    if reviews:
        write_jsonl(root / "reviews.jsonl",
                    merge_by_key(root / "reviews.jsonl", reviews, ("product_id",)))
    if heat:
        write_jsonl(root / "search_heat.jsonl",
                    merge_by_key(root / "search_heat.jsonl", heat, ("keyword_id", "stat_date")))

    meta = {**meta, "persisted_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (root / "collect_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def save_snapshot(source: str, rows: list[dict], stamp: str) -> Path:
    """把一次采集的原始行归档（不可变，便于追溯与回溯重算）。"""
    path = source_dir(source) / "snapshots" / f"snapshot_{stamp}.jsonl"
    write_jsonl(path, rows)
    return path
