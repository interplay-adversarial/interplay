"""Unit tests for red_teaming attack runners."""

from unittest.mock import MagicMock, patch

import pytest

from red_teaming.base import create_completion_kwargs, get_env_var
from red_teaming.crescendo_runner import CrescendoResult, crescendo_attack
from red_teaming.garak_runner import create_custom_config, run_garak
from red_teaming.goat_runner import GOATResult, goat_attack
from red_teaming.multimodal_runner import MultimodalResult, multimodal_attack
from red_teaming.pair_runner import PairResult, pair_attack
from red_teaming.slip_runner import SLIPResult, slip_attack
from red_teaming.tap_runner import TapResult, tap_attack


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
        """Test creating completion kwargs with base URL."""
        kwargs = create_completion_kwargs(
            provider="openai",
            model="test-model",
            base_url="https://custom-url/v1",
        )
        assert kwargs["base_url"] == "https://custom-url/v1"


class TestTapRunner:
    """Tests for TAP attack runner."""

    @pytest.mark.asyncio
    async def test_tap_attack_basic(self):
        """Test basic TAP attack structure."""
        # Mock the acompletion and _evaluate_prompt functions
        with (
            patch("red_teaming.tap_runner.acompletion") as mock_acompletion,
            patch("red_teaming.tap_runner._evaluate_prompt") as mock_eval,
        ):
            # Mock responses
            mock_acompletion.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content="refined prompt"))]
            )
            mock_eval.return_value = 0.8

            result = await tap_attack(
                goal="test goal",
                target_url="http://test.com/v1",
                attacker_model="openai/test",
                evaluator_model="openai/test",
                n_iterations=1,
                beam_width=2,
                branching_factor=2,
            )

            assert isinstance(result, TapResult)
            assert result.goal == "test goal"
            assert result.best_score >= 0.0
            assert result.best_score <= 1.0
            assert len(result.search_trajectory) >= 1

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
            patch("red_teaming.pair_runner.acompletion") as mock_acompletion,
            patch("red_teaming.pair_runner._call_target") as mock_target,
            patch("red_teaming.pair_runner._judge_score") as mock_score,
        ):
            # Mock responses
            mock_acompletion.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content="refined prompt"))]
            )
            mock_target.return_value = "target response"
            mock_score.return_value = 0.5

            result = await pair_attack(
                goal="test goal",
                target_url="http://test.com/v1",
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
    """Tests for Crescendo attack runner."""

    @pytest.mark.asyncio
    async def test_crescendo_attack_basic(self):
        """Test basic Crescendo attack structure."""
        with (
            patch("red_teaming.crescendo_runner.acompletion") as mock_acompletion,
            patch("red_teaming.crescendo_runner._call_target") as mock_target,
            patch("red_teaming.crescendo_runner._score_response") as mock_score,
        ):
            # Mock responses
            mock_acompletion.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content="escalated prompt"))]
            )
            mock_target.return_value = "response"
            mock_score.return_value = 0.3

            result = await crescendo_attack(
                goal="test goal",
                target_url="http://test.com/v1",
                attacker_model="openai/test",
                max_turns=2,
            )

            assert isinstance(result, CrescendoResult)
            assert result.goal == "test goal"
            assert result.turns <= 2
            assert len(result.conversation_history) <= 2

    def test_crescendo_result_dataclass(self):
        """Test CrescendoResult dataclass structure."""
        result = CrescendoResult(
            goal="test",
            best_score=0.7,
            best_prompt="prompt",
            conversation_history=[],
            query_count=1,
            turns=1,
        )
        assert result.goal == "test"
        assert result.turns == 1
        assert result.query_count == 1


class TestGOATRunner:
    """Tests for GOAT attack runner."""

    @pytest.mark.asyncio
    async def test_goat_attack_basic(self):
        """Test basic GOAT attack structure."""
        with (
            patch("red_teaming.goat_runner.acompletion") as mock_acompletion,
            patch("red_teaming.goat_runner._call_target") as mock_target,
            patch("red_teaming.goat_runner._score_response") as mock_score,
        ):
            # Mock responses
            mock_acompletion.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content="STRATEGY: test\nPROMPT: prompt"))]
            )
            mock_target.return_value = "response"
            mock_score.return_value = 0.4

            result = await goat_attack(
                goal="test goal",
                target_url="http://test.com/v1",
                attacker_model="openai/test",
                max_turns=2,
            )

            assert isinstance(result, GOATResult)
            assert result.goal == "test goal"
            assert result.turns <= 2
            assert len(result.strategy_trajectory) <= 2

    def test_goat_result_dataclass(self):
        """Test GOATResult dataclass structure."""
        result = GOATResult(
            goal="test",
            best_score=0.6,
            best_prompt="prompt",
            conversation_history=[],
            strategy_trajectory=["test"],
            query_count=1,
            turns=1,
        )
        assert result.goal == "test"
        assert len(result.strategy_trajectory) == 1


class TestSLIPRunner:
    """Tests for SLIP attack runner."""

    @pytest.mark.asyncio
    async def test_slip_attack_basic(self):
        """Test basic SLIP attack structure."""
        with (
            patch("red_teaming.slip_runner.acompletion") as mock_acompletion,
            patch("red_teaming.slip_runner._call_target") as mock_target,
            patch("red_teaming.slip_runner._score_response") as mock_score,
        ):
            # Mock responses
            mock_acompletion.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content="refined prompt"))]
            )
            mock_target.return_value = "response"
            mock_score.return_value = 0.5

            result = await slip_attack(
                goal="test goal",
                target_url="http://test.com/v1",
                target_model="test-model",
                max_iterations=2,
            )

            assert isinstance(result, SLIPResult)
            assert result.goal == "test goal"
            assert result.iterations <= 2
            assert len(result.search_trajectory) <= 2

    def test_slip_result_dataclass(self):
        """Test SLIPResult dataclass structure."""
        result = SLIPResult(
            goal="test",
            best_score=0.7,
            best_prompt="prompt",
            search_trajectory=[],
            query_count=1,
            iterations=1,
        )
        assert result.goal == "test"
        assert result.iterations == 1


class TestMultimodalRunner:
    """Tests for Multimodal attack runner."""

    @pytest.mark.asyncio
    async def test_multimodal_attack_basic(self):
        """Test basic Multimodal attack structure."""
        with (
            patch("red_teaming.multimodal_runner._generate_payload_image") as mock_gen,
            patch("red_teaming.multimodal_runner._call_vision_target") as mock_target,
            patch("red_teaming.multimodal_runner._score_response") as mock_score,
        ):
            # Mock responses
            mock_gen.return_value = "/tmp/test.png"
            mock_target.return_value = "response"
            mock_score.return_value = 0.6

            result = await multimodal_attack(
                goal="test goal",
                vision_target_url="http://test.com/v1",
                vision_model="vision-model",
                transforms=["plain"],
            )

            assert isinstance(result, MultimodalResult)
            assert result.goal == "test goal"
            assert result.query_count == 1

    def test_multimodal_result_dataclass(self):
        """Test MultimodalResult dataclass structure."""
        result = MultimodalResult(
            goal="test",
            best_score=0.8,
            best_prompt="prompt",
            image_path="/tmp/test.png",
            transform_used="plain",
            query_count=1,
        )
        assert result.goal == "test"
        assert result.image_path == "/tmp/test.png"


class TestGarakRunner:
    """Tests for Garak runner."""

    def test_run_garak_command_building(self):
        """Test that run_garak builds correct command."""
        # Just test that the function exists and accepts arguments
        # Actual execution requires Garak to be installed and target available
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="test", stderr="")
            run_garak(
                target_url="http://test.com/v1",
                probe_file="test.jsonl",
            )
            assert "garak" in str(mock_run.call_args)

    def test_create_custom_config(self, tmp_path):
        """Test creating custom Garak config."""
        config_path = create_custom_config(
            target_url="http://test.com/v1",
            output_path=str(tmp_path / "config.json"),
        )
        assert config_path.endswith(".json")

        import json

        with open(config_path) as f:
            config = json.load(f)
        assert config["url"] == "http://test.com/v1"
