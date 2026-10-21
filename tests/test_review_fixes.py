"""Regression cases for evidence independence, reading limits and stage consistency."""
import copy
import json
import os
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import Mock, patch

from tastecal.cli import save_settings, stage_config
from tastecal.core.config import Config
from tastecal.core.model import Item
from tastecal.judge.audit import Auditor, Thresholds, assess_packs, audit, blind_pack
from tastecal.judge.gates import Gatekeeper, GateThresholds, apply_gates, clean_gates, evidence_line, verdict, verify
from tastecal.lineage.synthesize import synthesize
from tastecal.prompts.lineage import works_block
from tastecal.sources.fulltext import ids_of


def reading(**overrides):
    return dict({"delivery": "delivered", "delivered": "lower error", "claimed": "lower error",
                 "delivery_evidence": "Table 2", "reason_type": "proof", "reason": "a bound",
                 "robustness": "single", "robustness_note": "one benchmark (Table 2)", "basis": "full text",
                 "claims": [{"claim": "lower error", "support": "supported", "evidence": "Table 2"}]}, **overrides)


def graph():
    return {"meta": {"seed": "s"}, "nodes": [{"id": "s", "title": "Seed", "date": "2020-01"},
                                              {"id": "a", "title": "Alpha", "date": "2021-01"}],
            "edges": [], "problems": []}


class EvidenceRulesTest(unittest.TestCase):
    def test_a_taste_answer_in_a_reading_is_ignored(self):
        g = graph()
        apply_gates(g, {"a": reading(taste={"score": 0.9, "why": "close to the profile"})})
        x = g["nodes"][1]["gates"]
        self.assertEqual((x["verdict"], x["fold"]), ("treasure", False))
        self.assertFalse(any(k in x for k in ("attractiveness", "taste_why", "taste_reasons", "treasure_candidate")))

    def test_partial_reading_cannot_establish_absence(self):
        cases = (({"main_coverage": 0.4, "omitted": ["middle of the main text"]}, ("uncertain", "uncertain")),
                 # Only the appendix did not fit: the main text was read, so its findings stand.
                 ({"main_coverage": 1.0, "omitted": ["references", "part of the appendix"]},
                  ("incremental", "not-delivered")))
        for cov, expected in cases:
            for delivery, want in zip(("delivered", "not"), expected):
                g = graph()
                apply_gates(g, {"a": reading(delivery=delivery, reason_type="none", robustness="single",
                                              coverage=cov, robustness_note="One benchmark (Table 2).")})
                self.assertEqual(g["nodes"][1]["gates"]["verdict"], want)

    def test_unchecked_ablation_is_not_missing_ablation(self):
        g = clean_gates(reading(robustness="repeats", checks={"fair_baselines": "no", "novelty_ablation": "unknown"}))
        from tastecal.judge.gates import confounders
        self.assertNotIn("no experiment", " ".join(confounders(g)))
        self.assertEqual(g["checks"]["novelty_ablation"], "unknown")

    def test_adoption_cannot_rescue_invalid_evaluation(self):
        g = clean_gates(reading(robustness="repeats", eval_fit={"can_show": "no", "fit_why": "Wrong construct"},
                               verified={"eval_quote": True}))
        for robust in (False, True):
            self.assertEqual(verdict(g, {"robust": robust}, 0.9, GateThresholds()), "unattributed")

    def test_unverified_or_partial_evaluation_fit_decides_nothing(self):
        # Shown to the reader, but only a quoted, verified "cannot show" changes a verdict.
        for quote in ("", "invented claim not present anywhere"):
            r = reading(robustness="repeats", eval_fit={"can_show": "no", "property_quote": quote,
                                                       "fit_why": "Wrong construct"})
            r["verified"] = verify(r, "real paper text about the method. " * 40)
            self.assertFalse(r["verified"]["eval_quote"])
            self.assertEqual(verdict(clean_gates(r), {}, None, GateThresholds()), "solid")
            r["delivery"] = "not"
            self.assertEqual(verdict(clean_gates(r), {}, None, GateThresholds()), "not-delivered")
        r = reading(robustness="repeats", eval_fit={"can_show": "partly", "fit_why": "Only part of it"})
        self.assertEqual(verdict(clean_gates(r), {}, None, GateThresholds()), "solid")

    def test_adoption_does_not_change_the_label(self):
        g = graph()
        g["nodes"] += [{"id": "b", "title": "B", "date": "2022-01"}, {"id": "c", "title": "C", "date": "2022-02"}]
        g["edges"] = [{"source": "a", "target": "b", "type": "extends"}, {"source": "a", "target": "c", "type": "resolves"}]
        apply_gates(g, {"a": reading(reason_type="none", robustness="single")}, today="2026-10")
        a = g["nodes"][1]["gates"]
        self.assertEqual(a["verdict"], "incremental")
        self.assertFalse(a["fold"])
        self.assertEqual(a["reaction"]["adopted_by"], ["b", "c"])

    def test_borrowed_tools_are_not_read_through_the_gates(self):
        keeper = Gatekeeper(Config(), Mock())
        g = graph()
        g["nodes"][1]["borrowed"] = True
        self.assertEqual([n["id"] for n in keeper.targets(g)], ["s"])

    def test_quote_is_checked_against_shown_text(self):
        quote = "Our method fails when the inputs have no signal"
        raw = reading(reason_type="mechanism", fails_when_stated=True, fails_when=quote)
        keeper = Gatekeeper(Config(), Mock(json=Mock(return_value=raw)))
        keeper.fulltext = lambda *args: ("intro " * 5000 + quote + " end " * 18000, "full text")
        result = keeper.gate({"title": "X"})
        self.assertIn("middle of the main text", result["coverage"]["omitted"])
        self.assertFalse(result["verified"]["fails_when"])

    def test_profile_survives_but_old_calibration_does_not(self):
        g = graph()
        g["gates"] = {"taste_profile": "I like proofs", "taste_name": "Mine", "taste_check": {"old": True}}
        apply_gates(g, {"a": reading()})
        self.assertEqual(g["gates"]["taste_profile"], "I like proofs")
        self.assertNotIn("taste_check", g["gates"])


class SharedEvidenceTest(unittest.TestCase):
    def test_blind_score_receives_evaluation_and_coverage(self):
        r = reading(eval_fit={"property": "Alpha reasoning", "property_quote": "Alpha reasons about agents",
                              "shown_by": "path distance", "can_show": "no", "fit_why": "distance cannot test reasoning",
                              "threat_model": "attacker sees logits"}, verified={"eval_quote": True},
                    coverage={"main_coverage": 0.4, "omitted": ["appendix"]})
        scorer = Auditor(Config(), Mock(), Mock(), reader=Mock(return_value=r))
        for name in ("_uptake", "_precedents", "_stars", "_field_rank"):
            setattr(scorer, name, Mock())
        pack = scorer.gather(Item("a", "Alpha", year=2020), {}, "Alpha")
        blind = blind_pack(pack)
        for text in (blind, evidence_line(r)):
            for fact in ("distance cannot test reasoning", "40%", "appendix", "attacker sees logits"):
                self.assertIn(fact, text)
        self.assertNotIn("Alpha", blind)
        scorer.reader.assert_called_once()
        assessment = assess_packs([pack], {"a": {"score": 0.5}}, "2026-10", Thresholds())["a"]
        self.assertEqual(assessment["evidence"]["coverage"], r["coverage"])
        self.assertEqual(assessment["evidence"]["eval_fit"], r["eval_fit"])

    def test_reference_population_is_saved(self):
        ref = [{"id": "outside", "date": "2020-01", "citations": 50}]
        scorer = Auditor(Config(), Mock(), Mock())
        scorer.run = Mock(return_value={})
        g = graph()
        audit(g, [], scorer, reference=ref)
        self.assertEqual(g["audit"]["reference_values"], ref)


class RerunSettingsTest(unittest.TestCase):
    def test_assess_command_restores_reader_sources_and_reference(self):
        from tastecal import cli
        g = graph()
        ref = [{"id": "ref", "date": "2020-01", "citations": 42}]
        g["audit"] = {"reference_values": ref}
        save_settings(g, Config(provider="codex-cli", model="saved-model", papers_dir="custom-papers"))
        source = Mock()
        source.resolve.side_effect = lambda title: Item(title.lower(), title, year=2020)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "graph.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(g, f)
            with patch("tastecal.cli._setup_logging"), patch("tastecal.cli._missing_hint"), \
                 patch("tastecal.core.http.Http"), patch("tastecal.core.llm.make_llm", return_value=Mock()) as make, \
                 patch("tastecal.sources.semantic_scholar.SemanticScholar", return_value=source), \
                 patch("tastecal.sources.openalex.OpenAlex", return_value=Mock()) as oa, \
                 patch("tastecal.judge.audit.audit") as do_audit, patch("tastecal.report.render.write_report"), \
                 patch("tastecal.core.schema.validate", return_value=[]):
                self.assertEqual(cli.main(["assess", path]), 0)
            cfg = make.call_args.args[0]
            self.assertEqual(cfg.model, "saved-model")
            self.assertEqual(cfg.papers_dir, os.path.abspath("custom-papers"))
            scorer = do_audit.call_args.args[2]
            self.assertIs(scorer.oa, oa.return_value)
            self.assertTrue(callable(scorer.reader))
            self.assertEqual(do_audit.call_args.kwargs["reference"], ref)

    def test_gates_command_restores_profile_and_persists_view(self):
        from tastecal import cli
        g = graph()
        g["gates"] = {"taste_profile": "I like proofs", "taste_name": "Saved profile",
                      "thresholds": {"attractive": 0.8, "too_early_months": 9}, "taste_check": {"stale": True},
                      "rate_next": ["a"]}
        save_settings(g, Config(provider="codex-cli", model="saved-model", papers_dir="custom-papers"))
        llm = Mock()
        llm.json.return_value = {"a": {"score": 0.7, "why": "Some fit"}}
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "graph.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(g, f)
            with patch("tastecal.cli._setup_logging"), patch("tastecal.cli._missing_hint"), \
                 patch("tastecal.core.http.Http"), patch("tastecal.core.llm.make_llm", return_value=llm) as make, \
                 patch.object(Gatekeeper, "read", return_value={"a": reading()}), \
                 patch("tastecal.report.render.write_report"), patch("tastecal.core.schema.validate", return_value=[]):
                self.assertEqual(cli.main(["gates", path, "--folded", "show"]), 0)
            with open(path, encoding="utf-8") as f:
                out = json.load(f)
        self.assertEqual(make.call_args.args[0].model, "saved-model")
        self.assertEqual(out["gates"]["taste_profile"], "I like proofs")
        self.assertEqual(out["gates"]["thresholds"]["too_early_months"], 9)
        self.assertNotIn("attractive", out["gates"]["thresholds"])          # the taste threshold is gone
        self.assertEqual(out["gates"]["view"], "show")
        self.assertNotIn("taste_check", out["gates"])
        self.assertNotIn("rate_next", out["gates"])
        self.assertEqual(out["nodes"][1]["gates"]["verdict"], "treasure")
        self.assertNotIn("treasure_candidate", out["nodes"][1]["gates"])
        llm.json.assert_not_called()                                       # no taste scoring

    def test_saved_paths_choices_and_explicit_overrides(self):
        g = graph()
        cfg = Config(provider="codex-cli", model="test-model", effort="high", papers_dir="my-papers",
                     cache_dir="my-cache", use_openalex=False, base_url="https://example.org/v1")
        save_settings(g, cfg)
        restored = stage_config(Namespace(), g)
        self.assertEqual(restored.provider, "codex-cli")
        self.assertEqual(restored.model, "test-model")
        self.assertEqual(restored.papers_dir, os.path.abspath("my-papers"))
        self.assertFalse(restored.use_openalex)
        switched = stage_config(Namespace(provider="anthropic", papers_dir="new"), g)
        self.assertEqual(switched.model, "")
        self.assertEqual(switched.base_url, "")
        self.assertEqual(switched.papers_dir, "new")

    def test_credentials_are_not_saved(self):
        g = graph()
        cfg = Config(openai_api_key="secret", base_url="https://user:secret@example.org/v1?key=secret")
        save_settings(g, cfg)
        self.assertNotIn("secret", json.dumps(g))
        self.assertNotIn("base_url", g["meta"]["settings"])

    def test_saved_identifiers_survive_without_resolving_an_item(self):
        self.assertEqual(ids_of({"ids": {"doi": "10.1234/example"}})["doi"], "10.1234/example")


class InferredFieldTest(unittest.TestCase):
    def test_inferred_scope_exports_overflow_imports_and_marks_tools(self):
        from test_scope import HomeFieldLLM, OUTSIDE, grow
        from fakes import CORPUS
        # The fake grower rekeys Items in place. Keep this test independent of other fake-corpus stages.
        with patch.dict(CORPUS, copy.deepcopy(CORPUS)), patch.dict(OUTSIDE, {"Alpha: Small Updates Suffice": "outside"}):
            grower, llm = grow("", HomeFieldLLM(), budget=8)
            self.assertTrue(grower.imports_list())
            borrowed = [n for n in grower.nodes.values() if n.borrowed]
            self.assertTrue(borrowed)
            block = works_block(borrowed)
            self.assertIn("Borrowed tool", block)
            for n in borrowed:
                for limitation in n.card.leaves:
                    self.assertNotIn("| leaves: " + limitation, block)
            g = synthesize(grower, llm, "seed")
            self.assertEqual(g["meta"]["scope"], "model adaptation")
            self.assertEqual(g["meta"]["scope_source"], "inferred")
            self.assertEqual(len(g["imports"]), len(grower.imports_list()))


if __name__ == "__main__":
    unittest.main()
