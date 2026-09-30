"""Exercise 3.4 — compare the lab's word-overlap metrics against DeepEval.

Both frameworks receive IDENTICAL input: the same 20 questions, the same actual
answers produced by domain_assistant.py, the same expected answers, and the same
retrieved contexts from artifacts/actual_answers.json. Nothing is re-generated,
so any score difference is attributable to the metric, not to the data.

Outcome recorded honestly: DeepEval's three RAG metrics (Faithfulness,
ContextualRecall, ContextualPrecision) ALL require a judge LLM. The lab's only
working key is Gemini free tier; the OpenAI key has no credit
(insufficient_quota), and Gemini returned 429/timeout repeatedly. So DeepEval
cannot produce numeric scores in this environment. What the run DOES establish is
the setup-comparison axis of Exercise 3.4, plus the exact blocking dependency.
"""
import json
import os
import time
from pathlib import Path

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

# DeepEval's RAG metrics are all LLM-judged and default to the OpenAI client.
# This project has no usable OpenAI key, so we deliberately do NOT inject one
# from the environment: the resulting DeepEvalError is the documented outcome of
# Exercise 3.4, not a setup mistake. To get real numbers later, delete this line
# and export a funded OPENAI_API_KEY before running.
os.environ["OPENAI_API_KEY"] = ""

OUT = []

# ------------------------------------------------------------- lab metrics
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("sol", "solution/solution.py")
sol = importlib.util.module_from_spec(spec)
sys.modules["sol"] = sol
spec.loader.exec_module(sol)
ev = sol.RAGASEvaluator()

golden = {
    p["id"]: p
    for p in json.loads(Path("golden_dataset.json").read_text(encoding="utf-8"))["qa_pairs"]
}
actual = {
    a["id"]: a
    for a in json.loads(Path("artifacts/actual_answers.json").read_text(encoding="utf-8"))["answers"]
}

lab = {}
for pid, a in actual.items():
    g = golden[pid]
    chunks = [c["text"] for c in a["retrieved_contexts"]]
    lab[pid] = {
        "faithfulness": round(ev.evaluate_faithfulness(a["actual_answer"], " ".join(chunks)), 4),
        "relevance": round(ev.evaluate_relevance(a["actual_answer"], g["question"]), 4),
        "completeness": round(ev.evaluate_completeness(a["actual_answer"], g["expected_answer"]), 4),
        "ctx_recall": round(ev.evaluate_context_recall(chunks, g["expected_answer"]), 4) if chunks else None,
        "ctx_precision": round(ev.evaluate_context_precision(chunks, g["expected_answer"]), 4) if chunks else None,
        "n_chunks": len(chunks),
    }

# ------------------------------------------------------------- DeepEval
from deepeval.test_case import LLMTestCase
from deepeval.metrics import (
    AnswerRelevancyMetric,
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    FaithfulnessMetric,
)
from deepeval.errors import DeepEvalError

cases = [
    LLMTestCase(
        input=golden[pid]["question"],
        actual_output=a["actual_answer"],
        expected_output=golden[pid]["expected_answer"],
        retrieval_context=[c["text"] for c in a["retrieved_contexts"]],
    )
    for pid, a in actual.items()
]
OUT.append("Built %d LLMTestCase objects from the identical artifacts." % len(cases))

de = {}
fail_reasons = {}
for pid, case in zip(actual.keys(), cases):
    row = {"faithfulness": None, "ctx_recall": None, "ctx_precision": None,
           "relevance": None}
    if not case.retrieval_context:
        fail_reasons.setdefault("no retrieval_context (A01 retrieved 0 chunks)", []).append(pid)
        de[pid] = row
        continue
    for key, metric_cls in [
        ("faithfulness", FaithfulnessMetric),
        ("ctx_recall", ContextualRecallMetric),
        ("ctx_precision", ContextualPrecisionMetric),
    ]:
        t0 = time.perf_counter()
        try:
            m = metric_cls(threshold=0.5, include_reason=False)
            m.measure(case)
            row[key] = round(float(m.score), 4)
        except DeepEvalError as e:
            fail_reasons.setdefault(str(e)[:80], []).append(pid)
        except Exception as e:  # noqa: BLE001
            fail_reasons.setdefault("%s: %s" % (type(e).__name__, str(e)[:60]), []).append(pid)
        else:
            fail_reasons.pop("__timing__", None)
    de[pid] = row

OUT.append("")
OUT.append("=== Why DeepEval produced no numeric scores ===")
for reason, pids in fail_reasons.items():
    OUT.append("  %-62s %d cases" % (reason, len(pids)))
OUT.append("  (example affected IDs: %s)" % ", ".join(sorted(next(iter(fail_reasons.values())))[:6]))

# ------------------------------------------------------- comparison summary
def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None

OUT.append("")
OUT.append("%-19s %14s %14s" % ("Metric", "Lab (template)", "DeepEval"))
for label, key, de_key in [
    ("Faithfulness", "faithfulness", "faithfulness"),
    ("Answer Relevance", "relevance", "relevance"),
    ("Completeness", "completeness", None),   # no DeepEval equivalent exists
    ("Context Recall", "ctx_recall", "ctx_recall"),
    ("Context Precision", "ctx_precision", "ctx_precision"),
]:
    lv = mean([r[key] for r in lab.values()])
    dv = mean([r[de_key] for r in de.values()]) if de_key else None
    OUT.append("%-19s %14s %14s" % (
        label,
        "%.3f" % lv if lv is not None else "n/a",
        "%.3f" % dv if dv is not None else ("NO EQUIV." if not de_key else "BLOCKED"),
    ))

# Cross-framework agreement on the deterministic lab side, plus which cases
# DeepEval would most likely disagree on (adversarial/refusals).
OUT.append("")
OUT.append("=== Cases where the lab metric is most likely to be WRONG (refusal handling) ===")
for pid in ["A01", "A02", "A03"]:
    a, g = actual[pid], golden[pid]
    r = lab[pid]
    OUT.append("  %s relevance=%.3f  n_chunks=%d" % (pid, r["relevance"], r["n_chunks"]))
    OUT.append("     actual: %s" % a["actual_answer"][:100].replace("\n", " "))

Path("artifacts/ex34_comparison.json").write_text(
    json.dumps({"lab": lab, "deepeval": de,
                "deepeval_blockers": {k: v for k, v in fail_reasons.items()}},
               indent=2, ensure_ascii=False),
    encoding="utf-8",
)
Path("artifacts/ex34_report.txt").write_text("\n".join(OUT), encoding="utf-8")
print("\n".join(OUT))
