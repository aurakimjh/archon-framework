"""structlog 설정 테스트 — 개발/프로덕션 모드, 파일 핸들러, 환경변수."""

from __future__ import annotations

import logging
import os
from unittest.mock import patch

import pytest
import structlog

from src.log.config import setup_logging


class TestSetupLogging:
    def teardown_method(self):
        """각 테스트 후 root logger 정리."""
        root = logging.getLogger()
        root.handlers.clear()
        root.setLevel(logging.WARNING)

    def test_default_dev_mode(self):
        setup_logging()
        root = logging.getLogger()
        assert root.level == logging.INFO
        assert len(root.handlers) >= 1

    def test_custom_level(self):
        setup_logging(level="DEBUG")
        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_prod_mode(self):
        setup_logging(mode="prod")
        root = logging.getLogger()
        assert len(root.handlers) >= 1

    def test_env_level_override(self):
        with patch.dict(os.environ, {"ARCHON_LOG_LEVEL": "ERROR"}):
            setup_logging()
        root = logging.getLogger()
        assert root.level == logging.ERROR

    def test_env_mode_override(self):
        with patch.dict(os.environ, {"ARCHON_ENV": "prod"}):
            setup_logging()
        root = logging.getLogger()
        assert len(root.handlers) >= 1

    def test_file_handler(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        setup_logging(log_file=log_file)
        root = logging.getLogger()
        file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 1
        assert file_handlers[0].baseFilename == log_file

    def test_explicit_params_override_env(self):
        with patch.dict(os.environ, {"ARCHON_LOG_LEVEL": "ERROR", "ARCHON_ENV": "prod"}):
            setup_logging(level="DEBUG", mode="dev")
        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_httpx_litellm_suppressed(self):
        setup_logging()
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("litellm").level == logging.WARNING

    def test_src_namespace_set(self):
        setup_logging(level="DEBUG")
        assert logging.getLogger("src").level == logging.DEBUG
