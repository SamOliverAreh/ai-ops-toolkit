"""tests/python/test_data_pipeline.py"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts" / "python"))

from data_pipeline import (
    DataPipeline,
    SyntheticExtractor,
    CSVExtractor,
    Transformer,
    CSVLoader,
    PipelineContext,
)


class TestPipelineContext:
    def test_elapsed_seconds(self):
        import time
        ctx = PipelineContext(pipeline_id="test")
        time.sleep(0.05)
        assert ctx.elapsed_seconds >= 0.05

    def test_summary_format(self):
        ctx = PipelineContext(pipeline_id="my-pipeline")
        ctx.rows_extracted = 100
        ctx.rows_transformed = 95
        ctx.rows_loaded = 95
        summary = ctx.summary()
        assert "my-pipeline" in summary
        assert "extracted=100" in summary


class TestSyntheticExtractor:
    def test_yields_dataframe(self):
        extractor = SyntheticExtractor(n_rows=200)
        ctx = PipelineContext(pipeline_id="test")
        chunks = list(extractor.extract(ctx))
        assert len(chunks) == 1
        assert isinstance(chunks[0], pd.DataFrame)
        assert len(chunks[0]) == 200
        assert ctx.rows_extracted == 200

    def test_expected_columns(self):
        extractor = SyntheticExtractor(n_rows=50)
        ctx = PipelineContext(pipeline_id="test")
        df = next(extractor.extract(ctx))
        assert "id" in df.columns
        assert "value" in df.columns
        assert "score" in df.columns


class TestTransformer:
    def setup_method(self):
        self.transformer = Transformer()

    def test_drops_duplicates(self):
        df = pd.DataFrame({"a": [1, 1, 2], "b": [3, 3, 4]})
        ctx = PipelineContext(pipeline_id="test")
        result = self.transformer.transform(df, ctx)
        assert len(result) == 2

    def test_fills_numeric_nulls(self):
        df = pd.DataFrame({"a": [1.0, None, 3.0], "b": [4, 5, 6]})
        ctx = PipelineContext(pipeline_id="test")
        result = self.transformer.transform(df, ctx)
        assert result["a"].isnull().sum() == 0

    def test_fills_categorical_nulls(self):
        df = pd.DataFrame({"cat": ["A", "A", None, "B"]})
        ctx = PipelineContext(pipeline_id="test")
        result = self.transformer.transform(df, ctx)
        assert result["cat"].isnull().sum() == 0

    def test_adds_pipeline_timestamp(self):
        df = pd.DataFrame({"x": [1, 2, 3]})
        ctx = PipelineContext(pipeline_id="test")
        result = self.transformer.transform(df, ctx)
        assert "_pipeline_ts" in result.columns

    def test_rows_transformed_counter(self):
        df = pd.DataFrame({"x": range(50)})
        ctx = PipelineContext(pipeline_id="test")
        self.transformer.transform(df, ctx)
        assert ctx.rows_transformed == 50


class TestCSVLoader:
    def test_saves_file(self, tmp_path):
        loader = CSVLoader(str(tmp_path))
        ctx = PipelineContext(pipeline_id="test")
        df = pd.DataFrame({"a": [1, 2, 3]})
        loader.load(df, ctx)
        out = loader.flush("test")
        assert out.exists()
        saved = pd.read_csv(out)
        assert len(saved) == 3
        assert ctx.rows_loaded == 3

    def test_multiple_chunks_concatenated(self, tmp_path):
        loader = CSVLoader(str(tmp_path))
        ctx = PipelineContext(pipeline_id="test")
        for _ in range(3):
            loader.load(pd.DataFrame({"a": [1, 2]}), ctx)
        out = loader.flush("test")
        saved = pd.read_csv(out)
        assert len(saved) == 6


class TestDataPipeline:
    def test_full_pipeline_run(self, tmp_path, mocker):
        mocker.patch("slack_notifier.SlackNotifier.send", return_value=True)
        pipeline = DataPipeline(
            pipeline_id="integration-test",
            extractor=SyntheticExtractor(n_rows=100),
            transformer=Transformer(),
            loader=CSVLoader(str(tmp_path)),
        )
        ctx = pipeline.run()
        assert ctx.rows_extracted == 100
        assert ctx.rows_loaded > 0
        assert len(ctx.errors) == 0

    def test_pipeline_error_handling(self, mocker):
        mocker.patch("slack_notifier.SlackNotifier.send", return_value=True)

        class BrokenExtractor:
            def extract(self, ctx):
                raise RuntimeError("Simulated failure")
                yield  # make it a generator

        pipeline = DataPipeline(
            pipeline_id="broken",
            extractor=BrokenExtractor(),
            transformer=Transformer(),
            loader=CSVLoader("/tmp/test-broken"),
            notify_on_error=True,
        )
        with pytest.raises(RuntimeError):
            pipeline.run()
