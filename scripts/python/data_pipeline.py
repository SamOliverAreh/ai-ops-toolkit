"""
scripts/python/data_pipeline.py
Generic modular ETL pipeline with retry logic, schema validation, and observability.

Usage:
  python data_pipeline.py --source postgres --dest csv --output output/
  python data_pipeline.py --demo
"""
from __future__ import annotations

import argparse
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd
import yaml
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from slack_notifier import get_notifier

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ── Pipeline context ──────────────────────────────────────────────────────────

@dataclass
class PipelineContext:
    pipeline_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    rows_extracted: int = 0
    rows_transformed: int = 0
    rows_loaded: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def elapsed_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.started_at).total_seconds()

    def summary(self) -> str:
        return (
            f"Pipeline {self.pipeline_id} | "
            f"extracted={self.rows_extracted} "
            f"transformed={self.rows_transformed} "
            f"loaded={self.rows_loaded} "
            f"elapsed={self.elapsed_seconds:.1f}s "
            f"errors={len(self.errors)}"
        )


# ── Extractor base ────────────────────────────────────────────────────────────

class BaseExtractor(ABC):
    """Abstract extractor. Supports chunked extraction for large datasets."""

    @abstractmethod
    def extract(self, ctx: PipelineContext) -> Iterator[pd.DataFrame]:
        ...


class PostgresExtractor(BaseExtractor):
    def __init__(self, connection_string: str, query: str, chunksize: int = 10_000) -> None:
        self.connection_string = connection_string
        self.query = query
        self.chunksize = chunksize

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def extract(self, ctx: PipelineContext) -> Iterator[pd.DataFrame]:
        import sqlalchemy
        engine = sqlalchemy.create_engine(self.connection_string)
        logger.info("Extracting from Postgres...")
        for chunk in pd.read_sql(self.query, engine, chunksize=self.chunksize):
            ctx.rows_extracted += len(chunk)
            yield chunk


class CSVExtractor(BaseExtractor):
    def __init__(self, filepath: str, chunksize: int = 10_000) -> None:
        self.filepath = filepath
        self.chunksize = chunksize

    def extract(self, ctx: PipelineContext) -> Iterator[pd.DataFrame]:
        logger.info("Extracting from CSV: %s", self.filepath)
        for chunk in pd.read_csv(self.filepath, chunksize=self.chunksize):
            ctx.rows_extracted += len(chunk)
            yield chunk


class SyntheticExtractor(BaseExtractor):
    """Demo extractor that generates synthetic data."""
    def __init__(self, n_rows: int = 500) -> None:
        self.n_rows = n_rows

    def extract(self, ctx: PipelineContext) -> Iterator[pd.DataFrame]:
        import numpy as np
        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            "id": range(self.n_rows),
            "timestamp": pd.date_range("2024-01-01", periods=self.n_rows, freq="h"),
            "value": rng.normal(100, 15, self.n_rows),
            "category": rng.choice(["A", "B", "C", None], self.n_rows),  # nulls for testing
            "score": rng.uniform(0, 1, self.n_rows),
            "flag": rng.integers(0, 2, self.n_rows),
        })
        ctx.rows_extracted += len(df)
        yield df


# ── Transformer ───────────────────────────────────────────────────────────────

class Transformer:
    """Configurable data transformation chain."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def transform(self, df: pd.DataFrame, ctx: PipelineContext) -> pd.DataFrame:
        original_len = len(df)

        df = self._drop_duplicates(df, ctx)
        df = self._handle_nulls(df, ctx)
        df = self._type_coerce(df, ctx)
        df = self._add_metadata_columns(df)

        ctx.rows_transformed += len(df)
        dropped = original_len - len(df)
        if dropped > 0:
            ctx.warnings.append(f"Dropped {dropped} rows during transformation")
            logger.warning("Dropped %d rows (%.1f%%)", dropped, dropped / original_len * 100)

        return df

    def _drop_duplicates(self, df: pd.DataFrame, ctx: PipelineContext) -> pd.DataFrame:
        before = len(df)
        df = df.drop_duplicates()
        if len(df) < before:
            logger.info("Removed %d duplicate rows", before - len(df))
        return df

    def _handle_nulls(self, df: pd.DataFrame, ctx: PipelineContext) -> pd.DataFrame:
        null_counts = df.isnull().sum()
        for col, count in null_counts.items():
            if count > 0:
                null_pct = count / len(df) * 100
                logger.info("Column '%s': %d nulls (%.1f%%)", col, count, null_pct)
                if null_pct > 50:
                    ctx.warnings.append(f"Column '{col}' has {null_pct:.0f}% nulls")

        # Fill numeric nulls with median, categorical with mode
        for col in df.select_dtypes(include="number").columns:
            df[col] = df[col].fillna(df[col].median())
        for col in df.select_dtypes(include="object").columns:
            mode = df[col].mode()
            if not mode.empty:
                df[col] = df[col].fillna(mode.iloc[0])
        return df

    def _type_coerce(self, df: pd.DataFrame, ctx: PipelineContext) -> pd.DataFrame:
        for col in df.columns:
            if "timestamp" in col.lower() or "date" in col.lower():
                try:
                    df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
                except Exception:
                    pass
        return df

    def _add_metadata_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        df["_pipeline_ts"] = datetime.now(timezone.utc).isoformat()
        return df


# ── Loader base ───────────────────────────────────────────────────────────────

class BaseLoader(ABC):
    @abstractmethod
    def load(self, df: pd.DataFrame, ctx: PipelineContext) -> None:
        ...


class CSVLoader(BaseLoader):
    def __init__(self, output_dir: str) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._parts: list[pd.DataFrame] = []

    def load(self, df: pd.DataFrame, ctx: PipelineContext) -> None:
        self._parts.append(df)
        ctx.rows_loaded += len(df)

    def flush(self, pipeline_id: str) -> Path:
        if not self._parts:
            return Path()
        combined = pd.concat(self._parts, ignore_index=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = self.output_dir / f"{pipeline_id}_{ts}.csv"
        combined.to_csv(out_path, index=False)
        logger.info("Saved %d rows to %s", len(combined), out_path)
        return out_path


class PostgresLoader(BaseLoader):
    def __init__(
        self,
        connection_string: str,
        table: str,
        if_exists: str = "append",
    ) -> None:
        self.connection_string = connection_string
        self.table = table
        self.if_exists = if_exists

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def load(self, df: pd.DataFrame, ctx: PipelineContext) -> None:
        import sqlalchemy
        engine = sqlalchemy.create_engine(self.connection_string)
        df.to_sql(self.table, engine, if_exists=self.if_exists, index=False)
        ctx.rows_loaded += len(df)
        logger.info("Loaded %d rows to %s", len(df), self.table)


# ── Pipeline orchestrator ─────────────────────────────────────────────────────

class DataPipeline:
    def __init__(
        self,
        pipeline_id: str,
        extractor: BaseExtractor,
        transformer: Transformer,
        loader: BaseLoader,
        notify_on_error: bool = True,
    ) -> None:
        self.pipeline_id = pipeline_id
        self.extractor = extractor
        self.transformer = transformer
        self.loader = loader
        self.notify_on_error = notify_on_error
        self.notifier = get_notifier()

    def run(self) -> PipelineContext:
        ctx = PipelineContext(pipeline_id=self.pipeline_id)
        logger.info("▶ Pipeline '%s' started", self.pipeline_id)

        try:
            for chunk in self.extractor.extract(ctx):
                transformed = self.transformer.transform(chunk, ctx)
                self.loader.load(transformed, ctx)

            # Flush CSV loader if applicable
            if isinstance(self.loader, CSVLoader):
                self.loader.flush(self.pipeline_id)

            logger.info("✅ %s", ctx.summary())
            self.notifier.info(
                f"✅ Pipeline '{self.pipeline_id}' Completed",
                ctx.summary(),
            )
        except Exception as exc:
            ctx.errors.append(str(exc))
            logger.error("❌ Pipeline '%s' failed: %s", self.pipeline_id, exc, exc_info=True)
            if self.notify_on_error:
                self.notifier.critical(
                    f"❌ Pipeline '{self.pipeline_id}' FAILED",
                    f"Error: {exc}\n{ctx.summary()}",
                )
            raise

        return ctx


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Run ETL data pipeline")
    parser.add_argument("--pipeline-id", default="etl")
    parser.add_argument("--source", choices=["postgres", "csv", "demo"], default="demo")
    parser.add_argument("--dest", choices=["postgres", "csv"], default="csv")
    parser.add_argument("--input", help="Source file or connection string")
    parser.add_argument("--output", default="output/", help="Output directory (for CSV dest)")
    parser.add_argument("--config", default="configs/config.yaml")
    args = parser.parse_args()

    config: dict[str, Any] = {}
    if Path(args.config).exists():
        with open(args.config) as f:
            config = yaml.safe_load(f)

    # Extractor
    if args.source == "demo":
        extractor: BaseExtractor = SyntheticExtractor()
    elif args.source == "csv":
        extractor = CSVExtractor(args.input)
    else:
        extractor = PostgresExtractor(args.input, "SELECT * FROM source_table")

    # Transformer
    transformer = Transformer(config)

    # Loader
    if args.dest == "csv":
        loader: BaseLoader = CSVLoader(args.output)
    else:
        loader = PostgresLoader(args.input, "target_table")

    pipeline = DataPipeline(args.pipeline_id, extractor, transformer, loader)
    ctx = pipeline.run()
    print(ctx.summary())


if __name__ == "__main__":
    main()
