"""Unit tests for red_teaming attack runners."""

from unittest.mock import MagicMock, patch

import pytest

from interplay.assessment.models import JudgeOutput
from interplay.red_teaming.base import create_completion_kwargs, get_env_var
from interplay.red_teaming.crescendo_runner import CrescendoResult
from interplay.red_teaming.garak_runner import create_custom_config
from interplay.red_teaming.goat_runner import GOATResult
from interplay.red_teaming.pair_runner import PairResult, pair_attack
from interplay.red_teaming.slip_runner import SLIPResult
from interplay.red_teaming.tap_runner import TapResult
from interplay.red_teaming.transport import TargetResponse


class TestBaseUtilities:
    """Tests for base utilities."""

    def test_get_env_var_exists(self, monkeypatch):
        """Test getting an existing env var."""
        monkeypatch.setenv("TEST_VAR", "test_value")
        result = get_env_var("TEST_VAR", required=False)
        assert result == "test_value"

    def test_get_env_var_missing_required(self, monkeypatch):
        """Test getting a missing required env var raises."""
        monkeypatch.delenv("TEST_VAR", raising=False)
        with pytest.raises(ValueError, match="TEST_VAR is required"):
            get_env_var("TEST_VAR", required=True)

    def test_create_completion_kwargs_basic(self):
        """Test creating completion kwargs with basic config."""
        kwargs = create_completion_kwargs(provider="openai", model="test-model")
        assert kwargs["provider"] == "openai"
        assert kwargs["model"] == "test-model"

    def test_create_completion_kwargs_with_api_key(self):
        """Test creating completion kwargs with API key."""
        kwargs = create_completion_kwargs(
            provider="openai",
            model="test-model",
            api_key="test-key",
        )
        assert kwargs["api_key"] == "test-key"

    def test_create_completion_kwargs_with_base_url(self):
        """A caller-supplied base_url becomes api_base (what any_llm.completion() accepts),
        never the unrecognized base_url kwarg that any_llm forwards straight to the
        provider SDK and that SDK then rejects with TypeError."""
        kwargs = create_completion_kwargs(
            provider="openai",
            model="test-model",
            base_url="https://custom-url/v1",
        )
        assert kwargs["api_base"] == "https://custom-url/v1"
        assert "base_url" not in kwargs


class TestTapRunner:
    """Tests for TAP attack runner's result dataclass; the search itself (real
    target queries, pruning, judging, budgets, kappa) is covered in
    tests/test_tap_runner.py since it needs a target fixture."""

    def test_tap_result_dataclass(self):
        """Test TapResult dataclass structure."""
        result = TapResult(
            goal="test",
            best_score=0.9,
            best_prompt="prompt",
            trials=[],
            search_trajectory=[],
        )
        assert result.goal == "test"
        assert result.best_score == 0.9
        assert result.best_prompt == "prompt"


class TestPairRunner:
    """Tests for PAIR attack runner."""

    @pytest.mark.asyncio
    async def test_pair_attack_basic(self):
        """Test basic PAIR attack structure."""
        with (
            patch("interplay.red_teaming.pair_runner.acompletion") as mock_acompletion,
            patch("interplay.red_teaming.pair_runner.request_target") as mock_target,
            patch("interplay.red_teaming.pair_runner.score_observation") as mock_score,
        ):
            # Mock responses
            mock_acompletion.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content="refined prompt"))]
            )
            mock_target.return_value = TargetResponse(content="target response")
            mock_score.return_value = (
                JudgeOutput(
                    verdict="failure", reasoning="fixture", evidence_refs_json='["/response"]'
                ),
                None,
            )

            result = await pair_attack(
                goal="test goal",
                target_url="https://target.example/v1",
                attacker_model="openai/test",
                judge_model="openai/test",
                max_queries=2,
            )

            assert isinstance(result, PairResult)
            assert result.goal == "test goal"
            assert result.query_count <= 2
            assert len(result.conversation_history) <= 2

    def test_pair_result_dataclass(self):
        """Test PairResult dataclass structure."""
        result = PairResult(
            goal="test",
            best_score=0.8,
            best_prompt="prompt",
            conversation_history=[],
            query_count=1,
        )
        assert result.goal == "test"
        assert result.best_score == 0.8
        assert result.query_count == 1


class TestCrescendoRunner:
    """Tests for Crescendo attack runner's result dataclass; the attack itself (real
    target queries, escalation decisions, judging, budgets) is covered in
    tests/test_crescendo_runner.py since it needs a target fixture."""

    def test_crescendo_result_dataclass(self):
        """Test CrescendoResult dataclass structure."""
        result = CrescendoResult(
            goal="test",
            best_score=0.7,
            best_prompt="prompt",
            trials=[],
            query_count=1,
            turns=1,
        )
        assert result.goal == "test"
        assert result.turns == 1
        assert result.query_count == 1


class TestGOATRunner:
    """Tests for GOAT attack runner's result dataclass; the attack itself (real
    target queries, strategy validation, judging, budgets) is covered in
    tests/test_goat_runner.py since it needs a target fixture."""

    def test_goat_result_dataclass(self):
        """Test GOATResult dataclass structure."""
        result = GOATResult(
            goal="test",
            best_score=0.6,
            best_prompt="prompt",
            trials=[],
            query_count=1,
            turns=1,
        )
        assert result.goal == "test"
        assert result.turns == 1
        assert result.query_count == 1


class TestSLIPRunner:
    """Tests for SLIP attack runner's result dataclass; the search itself (real
    target queries, deterministic insertion/truncation, refinement, judging,
    budgets) is covered in tests/test_slip_runner.py since it needs a target
    fixture."""

    def test_slip_result_dataclass(self):
        """Test SLIPResult dataclass structure."""
        result = SLIPResult(
            goal="test",
            best_prompt="prompt",
            trials=[],
            search_trajectory=[],
            query_count=1,
            rounds_completed=1,
        )
        assert result.goal == "test"
        assert result.rounds_completed == 1


class TestGarakRunner:
    """Tests for Garak runner."""

    def test_create_custom_config(self, tmp_path):
        """Test creating custom Garak config."""
        config_path = create_custom_config(
            target_url="https://target.example/v1",
            output_path=str(tmp_path / "config.json"),
        )
        assert config_path.endswith(".json")

        import json

        with open(config_path) as f:
            config = json.load(f)
        assert (
            config["plugins"]["generators"]["openai"]["OpenAICompatible"]["uri"]
            == "https://target.example/v1"
        )
