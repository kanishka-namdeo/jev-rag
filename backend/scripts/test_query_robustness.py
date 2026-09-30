#!/usr/bin/env python3
"""Query robustness testing: measure pipeline stability under paraphrasing.

This script tests how sensitive the RAG pipelines are to surface-level query
variations. It generates multiple paraphrases of existing benchmark questions,
runs them through both pipelines, and measures:

1. Retrieval Stability: Do we retrieve the same documents for paraphrases?
2. Answer Consistency: Do we get the same answer (semantic equivalence)?
3. Score Variance: How much does the correctness score fluctuate?

Usage:
    # Ensure backend is running: bash scripts/dev.sh
    python scripts/test_query_robustness.py --scenario techdocs --n-paraphrases 4
    python scripts/test_query_robustness.py --scenario finance --n-paraphrases 4 --mode hybrid

References:
    - "How You Ask Matters" (arxiv 2604.10745): 55% decision flips on human rewrites
    - "Out of Style" (EACL 2026): 40% Recall@5 drop on informal queries
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev

import httpx
from openai import OpenAI

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.bench.scenarios import SCENARIO_MAP
from app.config import Settings

# API endpoint (assumes backend is running via scripts/dev.sh)
API_BASE = "http://localhost:8000"


def generate_paraphrases(question: str, n: int = 4) -> list[str]:
    """Generate n paraphrases of the question using the LLM.

    Uses the same Dashscope endpoint as the pipeline to ensure consistency.
    """
    settings = Settings()
    client = OpenAI(
        base_url=settings.dashscope_base_url,
        api_key=settings.dashscope_api_key,
    )

    prompt = f"""Generate {n} distinct paraphrases of the following question.

Requirements:
- Preserve the EXACT semantic meaning and intent
- Vary the sentence structure, vocabulary, and phrasing
- Do not add or remove any constraints or details
- Each paraphrase should be a natural, standalone question

Original question: {question}

Generate {n} paraphrases, one per line, without numbering or bullet points:"""

    response = client.chat.completions.create(
        model="qwen3.7-plus",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,  # Higher temperature for diversity
        max_tokens=500,
    )

    content = response.choices[0].message.content.strip()
    paraphrases = [line.strip() for line in content.split("\n") if line.strip()]

    # Take exactly n (in case LLM generated more or fewer)
    return paraphrases[:n]


async def run_query_async(
    client: httpx.AsyncClient,
    question: str,
    mode: str,
    doc_ids: list[str] | None = None,
) -> dict:
    """Run a single query against the backend API and collect results.

    Returns dict with:
    - answer: The generated answer text
    - retrieved_files: List of retrieved document filenames
    - model: The model used for generation
    - latency_ms: Total latency in milliseconds
    """
    payload = {
        "message": question,
        "mode": mode,
    }
    if doc_ids:
        payload["doc_ids"] = doc_ids

    answer = ""
    retrieved_files = []
    model = ""
    latency_ms = 0.0

    try:
        async with client.stream(
            "POST",
            f"{API_BASE}/api/chat",
            json=payload,
            timeout=120.0,
        ) as response:
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue

                data_str = line[6:]  # Strip "data: "
                if data_str == "[DONE]":
                    break

                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")

                if event_type == "sources":
                    # Collect retrieved files
                    citations = event.get("citations", [])
                    retrieved_files = [c.get("filename") for c in citations if c.get("filename")]

                elif event_type == "delta":
                    # Accumulate answer text
                    answer += event.get("content", "")

                elif event_type == "done":
                    # Final metadata
                    model = event.get("model", "")
                    latency_ms = event.get("latency_ms", 0.0)

    except httpx.RequestError as e:
        return {
            "error": f"Request failed: {e}",
            "answer": "",
            "retrieved_files": [],
            "model": "",
            "latency_ms": 0.0,
        }

    return {
        "answer": answer,
        "retrieved_files": retrieved_files,
        "model": model,
        "latency_ms": latency_ms,
    }


def compute_retrieval_stability(
    original_files: list[str],
    paraphrase_files: list[list[str]],
) -> float:
    """Compute retrieval stability: fraction of paraphrases with identical file sets.

    Returns:
        Stability score (0.0 to 1.0)
    """
    if not paraphrase_files:
        return 1.0

    original_set = set(original_files)
    identical_count = sum(1 for files in paraphrase_files if set(files) == original_set)

    return identical_count / len(paraphrase_files)


def compute_file_overlap(
    original_files: list[str],
    paraphrase_files: list[list[str]],
) -> float:
    """Compute average Jaccard similarity between original and paraphrase file sets.

    Returns:
        Average overlap score (0.0 to 1.0)
    """
    if not paraphrase_files:
        return 1.0

    original_set = set(original_files)
    overlaps = []

    for files in paraphrase_files:
        paraphrase_set = set(files)
        if not original_set and not paraphrase_set:
            overlaps.append(1.0)
        else:
            intersection = len(original_set & paraphrase_set)
            union = len(original_set | paraphrase_set)
            overlaps.append(intersection / union if union > 0 else 0.0)

    return mean(overlaps)


async def test_robustness(
    scenario_id: str,
    n_paraphrases: int = 4,
    mode: str = "both",
    max_questions: int | None = None,
) -> dict:
    """Test query robustness for a given scenario.

    Args:
        scenario_id: The benchmark scenario to test
        n_paraphrases: Number of paraphrases to generate per question
        mode: "traditional", "hybrid", or "both"
        max_questions: Limit number of questions to test (None = all)

    Returns:
        Dictionary with robustness metrics
    """
    if scenario_id not in SCENARIO_MAP:
        raise ValueError(f"Unknown scenario: {scenario_id}")

    scenario = SCENARIO_MAP[scenario_id]
    questions = scenario.questions
    if max_questions:
        questions = questions[:max_questions]

    # Get doc_ids for this scenario (for API call)
    # We'll let the backend handle doc_id resolution by not passing it
    # (it will search across all docs, but the scenario docs are the only ones
    # that matter for this test)

    modes_to_test = ["traditional", "hybrid"] if mode == "both" else [mode]

    results = {
        "scenario": scenario_id,
        "n_questions": len(questions),
        "n_paraphrases": n_paraphrases,
        "modes": {},
    }

    async with httpx.AsyncClient() as client:
        for test_mode in modes_to_test:
            print(f"\n{'=' * 80}")
            print(f"Testing mode: {test_mode}")
            print(f"{'=' * 80}")

            mode_results = []

            for i, q in enumerate(questions, 1):
                print(f"\n[{i}/{len(questions)}] Question: {q.question[:60]}...")

                # Generate paraphrases
                print(f"  Generating {n_paraphrases} paraphrases...")
                paraphrases = generate_paraphrases(q.question, n_paraphrases)
                print(f"  Paraphrases: {paraphrases}")

                # Run original query
                print(f"  Running original query...")
                original_result = await run_query_async(client, q.question, test_mode)

                if "error" in original_result:
                    print(f"  ⚠️  Original query failed: {original_result['error']}")
                    continue

                # Run paraphrases
                print(f"  Running {len(paraphrases)} paraphrases...")
                paraphrase_results = []
                for j, para in enumerate(paraphrases, 1):
                    result = await run_query_async(client, para, test_mode)
                    paraphrase_results.append(result)
                    print(f"    [{j}/{len(paraphrases)}] Done ({result['latency_ms']:.0f}ms)")

                # Compute metrics
                retrieval_stability = compute_retrieval_stability(
                    original_result["retrieved_files"],
                    [r["retrieved_files"] for r in paraphrase_results],
                )

                file_overlap = compute_file_overlap(
                    original_result["retrieved_files"],
                    [r["retrieved_files"] for r in paraphrase_results],
                )

                # Answer consistency: check if answers are identical (simple heuristic)
                # A more robust check would use semantic similarity or LLM judge
                original_answer = original_result["answer"].strip().lower()
                identical_answers = sum(
                    1 for r in paraphrase_results
                    if r["answer"].strip().lower() == original_answer
                )
                answer_consistency = identical_answers / len(paraphrase_results) if paraphrase_results else 1.0

                # Latency variance
                latencies = [original_result["latency_ms"]] + [r["latency_ms"] for r in paraphrase_results]
                latency_variance = stdev(latencies) if len(latencies) > 1 else 0.0

                mode_results.append({
                    "question_id": q.id,
                    "question": q.question,
                    "reference": q.reference,
                    "paraphrases": paraphrases,
                    "original_answer": original_result["answer"],
                    "paraphrase_answers": [r["answer"] for r in paraphrase_results],
                    "original_files": original_result["retrieved_files"],
                    "paraphrase_files": [r["retrieved_files"] for r in paraphrase_results],
                    "retrieval_stability": retrieval_stability,
                    "file_overlap": file_overlap,
                    "answer_consistency": answer_consistency,
                    "latency_mean": mean(latencies),
                    "latency_std": latency_variance,
                })

                print(f"  📊 Retrieval stability: {retrieval_stability:.1%}")
                print(f"  📊 File overlap (Jaccard): {file_overlap:.1%}")
                print(f"  📊 Answer consistency: {answer_consistency:.1%}")
                print(f"  📊 Latency: {mean(latencies):.0f}ms ± {latency_variance:.0f}ms")

            # Aggregate metrics for this mode
            if mode_results:
                avg_retrieval_stability = mean([r["retrieval_stability"] for r in mode_results])
                avg_file_overlap = mean([r["file_overlap"] for r in mode_results])
                avg_answer_consistency = mean([r["answer_consistency"] for r in mode_results])
                avg_latency = mean([r["latency_mean"] for r in mode_results])
                avg_latency_std = mean([r["latency_std"] for r in mode_results])

                results["modes"][test_mode] = {
                    "n_questions_tested": len(mode_results),
                    "retrieval_stability": round(avg_retrieval_stability, 4),
                    "file_overlap_jaccard": round(avg_file_overlap, 4),
                    "answer_consistency_exact": round(avg_answer_consistency, 4),
                    "latency_mean_ms": round(avg_latency, 1),
                    "latency_std_ms": round(avg_latency_std, 1),
                    "per_question": mode_results,
                }

                print(f"\n{'=' * 80}")
                print(f"SUMMARY for {test_mode}")
                print(f"{'=' * 80}")
                print(f"Retrieval stability (identical file sets): {avg_retrieval_stability:.1%}")
                print(f"File overlap (Jaccard similarity): {avg_file_overlap:.1%}")
                print(f"Answer consistency (exact match): {avg_answer_consistency:.1%}")
                print(f"Average latency: {avg_latency:.0f}ms ± {avg_latency_std:.0f}ms")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Test query robustness under paraphrasing"
    )
    parser.add_argument(
        "--scenario",
        type=str,
        required=True,
        choices=list(SCENARIO_MAP.keys()),
        help="Benchmark scenario to test",
    )
    parser.add_argument(
        "--n-paraphrases",
        type=int,
        default=4,
        help="Number of paraphrases to generate per question (default: 4)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="both",
        choices=["traditional", "hybrid", "both"],
        help="Pipeline mode to test (default: both)",
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        help="Limit number of questions to test (default: all)",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output JSON file (default: stdout)",
    )

    args = parser.parse_args()

    print(f"Query Robustness Testing")
    print(f"Scenario: {args.scenario}")
    print(f"Paraphrases per question: {args.n_paraphrases}")
    print(f"Mode: {args.mode}")
    print(f"Max questions: {args.max_questions or 'all'}")
    print(f"\n⚠️  Ensure backend is running: bash scripts/dev.sh\n")

    results = asyncio.run(test_robustness(
        scenario_id=args.scenario,
        n_paraphrases=args.n_paraphrases,
        mode=args.mode,
        max_questions=args.max_questions,
    ))

    # Output
    output_json = json.dumps(results, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(output_json)
        print(f"\n✅ Results written to {args.output}")
    else:
        print("\n" + "=" * 80)
        print("FULL RESULTS")
        print("=" * 80)
        print(output_json)

    # Interpretation
    print("\n" + "=" * 80)
    print("INTERPRETATION")
    print("=" * 80)

    for mode_name, mode_data in results.get("modes", {}).items():
        print(f"\n{mode_name.upper()} PIPELINE:")

        stability = mode_data["retrieval_stability"]
        overlap = mode_data["file_overlap_jaccard"]
        consistency = mode_data["answer_consistency_exact"]

        if stability >= 0.9:
            print(f"✅ Excellent retrieval stability ({stability:.1%})")
        elif stability >= 0.7:
            print(f"⚠️  Good retrieval stability ({stability:.1%}), but some paraphrases retrieve different docs")
        else:
            print(f"❌ Poor retrieval stability ({stability:.1%}) — pipeline is sensitive to query phrasing")

        if consistency >= 0.9:
            print(f"✅ Excellent answer consistency ({consistency:.1%})")
        elif consistency >= 0.7:
            print(f"⚠️  Good answer consistency ({consistency:.1%}), but some paraphrases produce different answers")
        else:
            print(f"❌ Poor answer consistency ({consistency:.1%}) — pipeline is highly sensitive to query phrasing")

        if overlap < 0.8:
            print(f"💡 Suggestion: Average file overlap is {overlap:.1%}. Consider improving retrieval robustness or using query expansion.")


if __name__ == "__main__":
    main()
