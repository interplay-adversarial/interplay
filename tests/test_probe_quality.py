"""The probe quality gate: translation audit/rewrite for non-English rows and the validity judge.

Three layers, none of which needs a real model:

* pure helpers (scoring, selection, acceptance) called directly;
* structure (flat schemas, templates, which columns each pipeline mode gets);
* end to end through Data Designer against a scripted local endpoint, which is what catches DAG,
  skip-propagation and silent-row-drop problems that unit tests cannot.
"""

import json
import logging
import sys
import threading
from http.server import HTTPServer
from pathlib import Path

import pytest
from jinja2 import Environment

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import mock_openai  # noqa: E402

from interplay import pipeline, probe_quality  # noqa: E402
from interplay.specs import load_spec  # noqa: E402

pq = probe_quality
NAN = float("nan")


def judge(**scores: int) -> dict:
    """A judge cell where every dimension is `2` unless overridden."""
    cell = {name: {"reasoning": "r", "score": 2} for name in pq.MIN_JUDGE_SCORES}
    for name, score in scores.items():
        cell[name] = {"reasoning": "r", "score": score}
    return cell


def audit(critical: int = 0, major: int = 0, minor: int = 0, compliant: bool = True) -> dict:
    return {
        "back_translation": "bt",
        "language_compliant": compliant,
        "critical_errors": critical,
        "major_errors": major,
        "minor_errors": minor,
        "error_categories": "",
        "rationale": "",
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ({}, 100),
        ({"minor": 1}, 99),
        ({"major": 1}, 95),
        ({"critical": 1}, 75),
        ({"critical": 1, "major": 2, "minor": 3}, 62),
        ({"critical": 4}, 0),
        ({"critical": 10}, 0),  # floored, never negative
    ],
)
def test_mqm_score_weights_errors_by_severity(counts, expected):
    assert pq.mqm_score(audit(**counts)) == expected


def test_mqm_score_tolerates_missing_or_null_counts():
    assert pq.mqm_score({}) == 100
    assert (
        pq.mqm_score({"critical_errors": None, "major_errors": None, "minor_errors": None}) == 100
    )


def test_audit_passes_needs_score_and_language_compliance():
    assert pq.audit_passes(audit(minor=5))  # 95
    assert not pq.audit_passes(audit(critical=1))  # 75 < 80
    # Perfect error counts do not rescue a probe the reviewer says is in the wrong language.
    assert not pq.audit_passes(audit(compliant=False))
    # The threshold is inclusive: 100 - 4 * 5 = 80.
    assert pq.audit_passes(audit(major=4))
    assert not pq.audit_passes(audit(major=5))


# ---------------------------------------------------------------------------
# Probe selection
# ---------------------------------------------------------------------------


def test_pick_probe_reads_the_column_for_the_rows_mode():
    row = {
        "probe_mode": "adversarial",
        "adversarial_probe": {"prompt": "adv", "english_translation": "adv-en"},
        "benign_probe": NAN,  # skipped cell
    }
    assert pq.pick_probe(row) == ("adv", "adv-en")
    row["probe_mode"] = "benign"
    row["benign_probe"] = {"prompt": "ben"}
    row["adversarial_probe"] = None
    assert pq.pick_probe(row) == ("ben", "")


def test_pick_probe_accepts_a_json_string_cell():
    row = {
        "probe_mode": "benign",
        "benign_probe": json.dumps({"prompt": "ben", "english_translation": "x"}),
    }
    assert pq.pick_probe(row) == ("ben", "x")


def test_pick_probe_does_not_crash_on_a_missing_probe():
    assert pq.pick_probe({"probe_mode": "benign", "benign_probe": None}) == ("", "")


# ---------------------------------------------------------------------------
# Choosing the final probe
# ---------------------------------------------------------------------------


def final_row(original: int | None, rewritten: int | float | None, **extra) -> dict:
    return {
        "probe_mode": "benign",
        "benign_probe": {"prompt": "ORIGINAL"},
        "probe_rewrite": {"prompt": "REWRITE"},
        "translation_mqm_score": NAN if original is None else original,
        "rewrite_mqm_score": NAN if rewritten is None else rewritten,
        **extra,
    }


def test_english_row_keeps_the_original_and_has_no_score():
    # The translation columns are skipped for English, so they arrive as NaN.
    assert pq.choose_final(final_row(None, None)) == {
        "final_probe": "ORIGINAL",
        "final_mqm_score": None,
        "rewrite_applied": False,
    }


def test_passing_original_is_kept_when_no_rewrite_was_made():
    assert pq.choose_final(final_row(95, None)) == {
        "final_probe": "ORIGINAL",
        "final_mqm_score": 95,
        "rewrite_applied": False,
    }


def test_a_strictly_better_rewrite_replaces_the_original():
    assert pq.choose_final(final_row(70, 90)) == {
        "final_probe": "REWRITE",
        "final_mqm_score": 90,
        "rewrite_applied": True,
    }


@pytest.mark.parametrize("rewritten", [70, 50, 0])
def test_an_equal_or_worse_rewrite_is_discarded(rewritten):
    result = pq.choose_final(final_row(70, rewritten))
    assert result == {"final_probe": "ORIGINAL", "final_mqm_score": 70, "rewrite_applied": False}


PASSING = {"language_compliant": True, "critical_errors": 0, "major_errors": 0, "minor_errors": 0}
WRONG_LANGUAGE = {**PASSING, "language_compliant": False}


def test_a_compliant_rewrite_replaces_a_wrong_language_original_with_the_same_score():
    # The reviewer can flag the wrong language without counting an error, so both score 100.
    row = final_row(100, 100, translation_audit=WRONG_LANGUAGE, rewrite_audit=PASSING)
    assert pq.choose_final(row) == {
        "final_probe": "REWRITE",
        "final_mqm_score": 100,
        "rewrite_applied": True,
    }


def test_a_compliant_rewrite_wins_even_with_a_lower_score_than_a_wrong_language_original():
    row = final_row(
        100, 90, translation_audit=WRONG_LANGUAGE, rewrite_audit={**PASSING, "minor_errors": 10}
    )
    assert pq.choose_final(row)["rewrite_applied"] is True


def test_an_equal_score_rewrite_that_is_still_wrong_language_is_discarded():
    row = final_row(100, 100, translation_audit=WRONG_LANGUAGE, rewrite_audit=WRONG_LANGUAGE)
    assert pq.choose_final(row)["rewrite_applied"] is False


def test_a_better_score_with_an_empty_rewrite_falls_back_to_the_original_text():
    row = final_row(70, 90)
    row["probe_rewrite"] = {"prompt": ""}
    assert pq.choose_final(row)["final_probe"] == "ORIGINAL"


# ---------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------


def accept_row(translation=None, **overrides) -> dict:
    row = {
        "probe_quality_score": judge(),
        "final_mqm_score": None,
        "rewrite_applied": False,
        "translation_audit": translation,
        "rewrite_audit": None,
    }
    row.update(overrides)
    return row


def test_english_row_is_accepted_on_the_judge_alone():
    assert pq.is_accepted(accept_row())


@pytest.mark.parametrize("dimension", list(pq.MIN_JUDGE_SCORES))
def test_each_judge_dimension_can_reject_a_probe(dimension):
    below = pq.MIN_JUDGE_SCORES[dimension] - 1
    assert not pq.is_accepted(accept_row(probe_quality_score=judge(**{dimension: below})))
    at_minimum = pq.MIN_JUDGE_SCORES[dimension]
    assert pq.is_accepted(accept_row(probe_quality_score=judge(**{dimension: at_minimum})))


@pytest.mark.parametrize(
    "cell",
    [None, NAN, {}, {"quality": {"score": None}}, {"quality": {"score": "2"}}, "not json"],
)
def test_a_missing_or_malformed_judge_cell_rejects_instead_of_crashing(cell):
    assert not pq.is_accepted(accept_row(probe_quality_score=cell))


def test_non_english_row_needs_a_passing_original_audit():
    good = accept_row(translation=audit(minor=2), final_mqm_score=98)
    assert pq.is_accepted(good)
    bad = accept_row(translation=audit(critical=1), final_mqm_score=75)
    assert not pq.is_accepted(bad)


def test_non_english_row_is_judged_on_the_rewrite_audit_when_the_rewrite_won():
    row = accept_row(
        translation=audit(critical=2),  # the original was bad...
        rewrite_audit=audit(),  # ...the rewrite is clean
        rewrite_applied=True,
        final_mqm_score=100,
    )
    assert pq.is_accepted(row)
    # A rewrite that beat the original but is still in the wrong language is not accepted.
    row["rewrite_audit"] = audit(compliant=False)
    assert not pq.is_accepted(row)


def test_a_clean_judge_does_not_rescue_a_failing_translation():
    assert not pq.is_accepted(
        accept_row(
            probe_quality_score=judge(quality=3),
            translation=audit(compliant=False),
            final_mqm_score=100,
        )
    )


# ---------------------------------------------------------------------------
# Structure: schemas, templates, columns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model", [pq.TranslationAudit, pq.ProbeRewrite, pipeline.AdversarialProbe, pipeline.BenignProbe]
)
def test_output_schemas_are_flat(model):
    # AGENTS.md: structured output degrades with nesting. A nested model shows up as $defs / $ref.
    schema = json.dumps(model.model_json_schema())
    assert "$defs" not in schema and "$ref" not in schema


def render(template: str, **context) -> str:
    return Environment().from_string(template).render(**context)


def test_adversarial_probes_are_asked_to_write_in_the_target_language():
    # Regression: the adversarial template used to ignore target_language, so regional-language
    # adversarial probes were written in English while being labelled with another language.
    spanish = render(pipeline.ADVERSARIAL_PROBE_TEMPLATE, target_language="Spanish (español)")
    assert "entirely in: Spanish" in spanish
    assert '"english_translation"' in spanish
    english = render(
        pipeline.ADVERSARIAL_PROBE_TEMPLATE,
        target_language="English (grounded in target regional context)",
    )
    assert "entirely in" not in english
    assert "english_translation" not in english


def test_audit_prompt_only_mentions_the_author_translation_when_there_is_one():
    ctx = {"target_language": "Tagalog", "probe_text": "isang tanong", "probe_mode": "benign"}
    with_translation = render(pq.AUDIT_TEMPLATE, probe_english_translation="a question", **ctx)
    without = render(pq.AUDIT_TEMPLATE, probe_english_translation="", **ctx)
    assert "<translation>" in with_translation and "a question" in with_translation
    assert "<translation>" not in without


def test_rewrite_audit_reviews_the_rewrite_not_the_original():
    assert "probe_rewrite.prompt" in pq.REWRITE_AUDIT_TEMPLATE
    assert "probe_rewrite.english_translation" in pq.REWRITE_AUDIT_TEMPLATE
    assert "probe_text" not in pq.REWRITE_AUDIT_TEMPLATE
    assert "probe_english_translation" not in pq.REWRITE_AUDIT_TEMPLATE


def test_reviewer_prompts_fence_the_probe_as_data():
    assert "<probe>" in pq.AUDIT_TEMPLATE and "</probe>" in pq.AUDIT_TEMPLATE
    assert "never answer" in pq.AUDIT_SYSTEM_PROMPT
    assert "<probe>" in pq.JUDGE_PROMPT


def test_judge_keeps_the_quality_dimension_other_code_reads():
    # examples/diverse_dataset.py and the README read probe_quality_score["quality"]["score"].
    assert pq.JUDGE_SCORES[0]["name"] == "quality"
    assert {s["name"] for s in pq.JUDGE_SCORES} == set(pq.MIN_JUDGE_SCORES)


def columns(builder) -> list[str]:
    return [c.name for c in builder.get_column_configs()]


GATE_COLUMNS = [
    "probe_text",
    "translation_audit",
    "translation_mqm_score",
    "probe_rewrite",
    "rewrite_audit",
    "rewrite_mqm_score",
    "final_probe",
    "probe_quality_score",
    "probe_accepted",
]


@pytest.mark.parametrize("mode", ["singapore", "sdg-hub-harm", "combined"])
def test_taxonomy_pipelines_get_the_full_gate_in_order(mode, monkeypatch):
    monkeypatch.delenv("PROBE_TRANSLATION_AUDIT", raising=False)
    names = columns(pipeline._build_taxonomy_pipeline(_keys(mode)))
    positions = [names.index(n) for n in GATE_COLUMNS]
    assert positions == sorted(positions), names
    assert names.index("benign_probe") < names.index("probe_text")


def _keys(mode: str) -> list[str]:
    return {
        "singapore": list(pipeline.CATEGORY_DEFINITIONS),
        "sdg-hub-harm": list(pipeline.SDG_HUB_HARM_DEFINITIONS),
        "combined": list(pipeline.ALL_CATEGORY_DEFINITIONS),
    }[mode]


def test_comparison_pipelines_get_the_gate_too(monkeypatch):
    monkeypatch.delenv("PROBE_TRANSLATION_AUDIT", raising=False)
    names = columns(pipeline.build_comparison_pipeline(load_spec("us-mexico")))
    assert all(n in names for n in GATE_COLUMNS)


def test_translation_audit_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("PROBE_TRANSLATION_AUDIT", "0")
    names = columns(pipeline.build_comparison_pipeline(load_spec("us-mexico")))
    for gone in ("translation_audit", "translation_mqm_score", "probe_rewrite", "rewrite_audit"):
        assert gone not in names
    # The judge and the final column remain, so downstream code sees the same shape.
    for kept in ("probe_text", "final_probe", "probe_quality_score", "probe_accepted"):
        assert kept in names


def test_judge_alias_can_differ_from_the_generator_alias(monkeypatch):
    monkeypatch.delenv("PROBE_TRANSLATION_AUDIT", raising=False)
    monkeypatch.setenv("PROBE_JUDGE_ALIAS", "independent-judge")
    builder = pipeline.build_comparison_pipeline(load_spec("us-mexico"))
    by_name = {c.name: c for c in builder.get_column_configs()}
    for reviewer in ("translation_audit", "probe_rewrite", "rewrite_audit", "probe_quality_score"):
        assert by_name[reviewer].model_alias == "independent-judge", reviewer
    for generator in ("adversarial_probe", "benign_probe"):
        assert by_name[generator].model_alias == "cultural-bias-model", generator


def test_judge_alias_defaults_to_the_generator_alias(monkeypatch):
    monkeypatch.delenv("PROBE_JUDGE_ALIAS", raising=False)
    by_name = {
        c.name: c
        for c in pipeline.build_comparison_pipeline(load_spec("us-mexico")).get_column_configs()
    }
    assert by_name["probe_quality_score"].model_alias == "cultural-bias-model"


# ---------------------------------------------------------------------------
# End to end through Data Designer, against a scripted endpoint
# ---------------------------------------------------------------------------


class ScriptedEndpoint:
    """A fake OpenAI-compatible endpoint whose answers depend on which column is asking.

    Original probes contain "ORIGINAL" and the rewrite contains "REWRITTEN", which is how the audit
    answers differently for each. The judge scores benign probes `benign_score` and adversarial
    ones `adversarial_score`, read from the "{{ probe_mode }} probe" line of its prompt.
    """

    def __init__(self, rewrite_improves: bool, benign_score: int, adversarial_score: int):
        self.rewrite_improves = rewrite_improves
        self.benign_score = benign_score
        self.adversarial_score = adversarial_score
        self.calls: list[tuple[frozenset[str], str]] = []
        endpoint = self

        class Handler(mock_openai.Handler):
            def do_POST(self) -> None:
                body = json.loads(
                    self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"
                )
                content = endpoint.reply(body)
                self._send(
                    {
                        "id": "scripted",
                        "object": "chat.completion",
                        "created": 0,
                        "model": body.get("model", "mock-model"),
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": content},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 5, "completion_tokens": 20, "total_tokens": 25},
                    }
                )

        self.server = HTTPServer(("127.0.0.1", 0), Handler)

    def reply(self, body: dict) -> str:
        last = body["messages"][-1].get("content", "")
        if isinstance(last, list):
            last = "\n".join(p.get("text", "") for p in last if isinstance(p, dict))
        start, end = last.rfind("<response_schema>"), last.rfind("</response_schema>")
        if start == -1 or end <= start:
            return mock_openai.reply_for(body)
        props = set(json.loads(last[start + len("<response_schema>") : end]).get("properties", {}))
        self.calls.append((frozenset(props), last))

        if "back_translation" in props:
            rewritten = "REWRITTEN" in last
            critical = 0 if (rewritten and self.rewrite_improves) else (2 if rewritten else 1)
            value = audit(critical=critical)
        elif "changes_made" in props:
            value = {
                "prompt": "REWRITTEN probe",
                "english_translation": "REWRITTEN en",
                "changes_made": "x",
            }
        elif "why_prompt_harmful" in props:
            value = {k: "x" for k in props} | {
                "prompt": "ORIGINAL adv probe",
                "english_translation": "o",
            }
        elif "why_culturally_biased" in props:
            value = {k: "x" for k in props} | {
                "prompt": "ORIGINAL benign probe",
                "english_translation": "o",
            }
        elif "quality" in props:  # the judge, at either level
            score = self.benign_score if "benign probe from" in last else self.adversarial_score
            value = {name: {"reasoning": "ok", "score": score} for name in props}
        else:
            return mock_openai.reply_for(body)
        return "```json\n" + json.dumps(value) + "\n```"

    def count(self, key: str) -> int:
        return sum(1 for props, _ in self.calls if key in props)

    def start(self) -> str:
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def run_pipeline(
    tmp_path,
    monkeypatch,
    endpoint: ScriptedEndpoint,
    languages: list[str],
    rows: int,
    profiler_warnings_ok: bool = False,
):
    import data_designer.config as dd
    from data_designer.interface import DataDesigner

    monkeypatch.setenv("DATA_DESIGNER_HOME", str(tmp_path / "dd"))
    monkeypatch.delenv("PROBE_JUDGE_ALIAS", raising=False)
    warnings: list[str] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= logging.WARNING:
                warnings.append(record.getMessage())

    collector = Collect()
    logging.getLogger("data_designer").addHandler(collector)
    url = endpoint.start()
    try:
        spec = load_spec("us-mexico").model_copy(update={"languages": languages})
        builder = pipeline.build_comparison_pipeline(spec)
        builder.add_model_config(
            dd.ModelConfig(alias="cultural-bias-model", model="mock-model", provider="scripted")
        )
        provider = dd.ModelProvider(
            name="scripted", endpoint=url, provider_type="openai", api_key="not-a-real-key"
        )
        designer = DataDesigner(artifact_path=tmp_path / "artifacts", model_providers=[provider])
        frame = designer.create(builder, num_records=rows, dataset_name="gate").load_dataset()
    finally:
        endpoint.stop()
        logging.getLogger("data_designer").removeHandler(collector)
    # An expression or generator failure drops rows with only a log line; make that loud.
    assert len(frame) == rows, f"expected {rows} rows, got {len(frame)}: rows were silently dropped"
    # The profiler re-renders each prompt against the final dataset, so a column the prompts read
    # must not be dropped from it (that logs a warning and loses the input-token stats).
    profiler_warnings = [w for w in warnings if "column profile calculation" in w]
    if not profiler_warnings_ok:
        assert not profiler_warnings, profiler_warnings
    return frame


@pytest.fixture(autouse=True)
def _default_settings(monkeypatch):
    for name in ("PROBE_TRANSLATION_AUDIT", "PROBE_JUDGE_LEVEL", "PROBE_DROP_CONCEPT_DEFINITION"):
        monkeypatch.delenv(name, raising=False)


def test_e2e_a_better_rewrite_replaces_the_original_and_is_accepted(tmp_path, monkeypatch):
    endpoint = ScriptedEndpoint(rewrite_improves=True, benign_score=2, adversarial_score=2)
    frame = run_pipeline(tmp_path, monkeypatch, endpoint, ["Spanish (español mexicano)"], rows=6)

    assert (frame["translation_mqm_score"] == 75).all()  # one critical error in the original
    assert (frame["rewrite_mqm_score"] == 100).all()
    assert frame["rewrite_applied"].all()
    assert frame["final_probe"].str.startswith("REWRITTEN").all()
    assert (frame["final_mqm_score"] == 100).all()
    assert frame["probe_accepted"].all()
    # Every non-English row was audited, rewritten and re-audited, and judged once (plus its generation).
    assert endpoint.count("changes_made") == 6
    assert endpoint.count("back_translation") == 12
    # The adversarial template now asks for the target language (it used to ignore it).
    adversarial_prompts = [t for props, t in endpoint.calls if "why_prompt_harmful" in props]
    assert adversarial_prompts and all("entirely in: Spanish" in t for t in adversarial_prompts)


def test_e2e_a_worse_rewrite_is_discarded_and_the_row_is_rejected(tmp_path, monkeypatch):
    endpoint = ScriptedEndpoint(rewrite_improves=False, benign_score=2, adversarial_score=2)
    frame = run_pipeline(tmp_path, monkeypatch, endpoint, ["Spanish (español mexicano)"], rows=6)

    assert (frame["translation_mqm_score"] == 75).all()
    assert (frame["rewrite_mqm_score"] == 50).all()  # two critical errors: worse
    assert not frame["rewrite_applied"].any()
    assert frame["final_probe"].str.startswith("ORIGINAL").all()
    assert (frame["final_mqm_score"] == 75).all()
    # Perfect judge scores do not rescue a probe whose translation failed the gate.
    assert not frame["probe_accepted"].any()


def test_e2e_english_rows_skip_the_translation_gate_but_still_get_judged(tmp_path, monkeypatch):
    endpoint = ScriptedEndpoint(rewrite_improves=True, benign_score=2, adversarial_score=1)
    frame = run_pipeline(tmp_path, monkeypatch, endpoint, ["English"], rows=10)

    assert endpoint.count("back_translation") == 0 and endpoint.count("changes_made") == 0
    assert frame["translation_mqm_score"].isna().all() and frame["final_mqm_score"].isna().all()
    assert not frame["rewrite_applied"].any()
    assert frame["final_probe"].str.startswith("ORIGINAL").all()
    # benign probes were scored 2 (accepted); adversarial probes 1 (quality needs 2, rejected).
    assert (frame["probe_accepted"] == (frame["probe_mode"] == "benign")).all()


def test_e2e_with_the_audit_off_non_english_rows_are_judged_but_not_rewritten(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PROBE_TRANSLATION_AUDIT", "0")
    endpoint = ScriptedEndpoint(rewrite_improves=True, benign_score=2, adversarial_score=2)
    frame = run_pipeline(tmp_path, monkeypatch, endpoint, ["Spanish (español mexicano)"], rows=4)

    assert endpoint.count("back_translation") == 0 and endpoint.count("changes_made") == 0
    assert "translation_audit" not in frame.columns
    assert frame["final_probe"].str.startswith("ORIGINAL").all()
    assert frame["probe_accepted"].all()


def test_e2e_the_basic_judge_level_asks_only_for_quality_and_gates_on_it(tmp_path, monkeypatch):
    monkeypatch.setenv("PROBE_JUDGE_LEVEL", "basic")
    endpoint = ScriptedEndpoint(rewrite_improves=True, benign_score=2, adversarial_score=1)
    frame = run_pipeline(tmp_path, monkeypatch, endpoint, ["English"], rows=10)

    judge_schemas = [props for props, _ in endpoint.calls if "quality" in props]
    assert judge_schemas and all(props == {"quality"} for props in judge_schemas)
    assert all(set(cell) == {"quality"} for cell in frame["probe_quality_score"])
    # quality needs 2: benign probes (2) are accepted, adversarial probes (1) are not.
    assert (frame["probe_accepted"] == (frame["probe_mode"] == "benign")).all()


def test_e2e_the_concept_definition_can_still_be_dropped(tmp_path, monkeypatch):
    monkeypatch.setenv("PROBE_DROP_CONCEPT_DEFINITION", "1")
    endpoint = ScriptedEndpoint(rewrite_improves=True, benign_score=2, adversarial_score=2)
    frame = run_pipeline(
        tmp_path, monkeypatch, endpoint, ["English"], rows=4, profiler_warnings_ok=True
    )

    assert "concept_definition" not in frame.columns
    assert frame[
        "probe_accepted"
    ].all()  # dropping the column after generation changes nothing else


def test_concept_definition_is_kept_by_default(monkeypatch):
    builder = pipeline.build_comparison_pipeline(load_spec("us-mexico"))
    assert [p.name for p in builder.get_processor_configs()] == []
    monkeypatch.setenv("PROBE_DROP_CONCEPT_DEFINITION", "1")
    builder = pipeline.build_comparison_pipeline(load_spec("us-mexico"))
    assert [p.name for p in builder.get_processor_configs()] == ["cleanup"]


def test_the_basic_judge_level_scores_one_dimension_and_the_full_level_five(monkeypatch):
    def judge_dimensions() -> list[str]:
        builder = pipeline.build_comparison_pipeline(load_spec("us-mexico"))
        judge = {c.name: c for c in builder.get_column_configs()}["probe_quality_score"]
        return [s.name for s in judge.scores]

    assert judge_dimensions() == list(pq.MIN_JUDGE_SCORES)
    monkeypatch.setenv("PROBE_JUDGE_LEVEL", "basic")
    assert judge_dimensions() == ["quality"]


def test_an_unknown_judge_level_is_rejected_when_the_pipeline_is_built(monkeypatch):
    monkeypatch.setenv("PROBE_JUDGE_LEVEL", "everything")
    with pytest.raises(ValueError, match="judge_level must be one of"):
        pipeline.build_comparison_pipeline(load_spec("us-mexico"))


def test_acceptance_at_the_basic_level_ignores_the_other_dimensions():
    row = accept_row(probe_quality_score={"quality": {"reasoning": "r", "score": 2}})
    assert pq.is_accepted(row, pq.JUDGE_LEVELS["basic"])
    assert not pq.is_accepted(row)  # the full level asked for dimensions the cell lacks
