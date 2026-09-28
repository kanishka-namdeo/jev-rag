"""Scenario registry: 6 corpora x ground-truth QA pairs.

Scenario categories follow standard RAG-benchmark taxonomy (RAGAS/BeIR/FinanceBench/
AbstentionBench/MIRACL-inspired — see docs/benchmarking.md):
  techdocs    single-hop factoid QA over product docs
  finance     distractor-heavy numeric QA (near-identical numbers across entities)
  policy      conditional rules with exceptions & distractor conditions
  distractor  needle-in-haystack over near-duplicate KB articles
  multilingual cross-lingual retrieval (facts live in non-EN docs)
  outofscope  abstention: answerable + unanswerable questions over one small corpus

Each question pins: reference answer (ground truth), gold_files (files containing
the answer; used for deterministic retrieval metrics), answerable (for the
sufficiency-gate / abstention analysis) and a stress tag.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

CORPUS_DIR = Path(__file__).parent / "corpora"


@dataclass(frozen=True)
class BenchQuestion:
    id: str
    question: str
    reference: str                       # canonical ground-truth answer
    gold_files: tuple[str, ...]          # corpus filenames that contain the answer
    answerable: bool = True
    qtype: str = "lookup"                # lookup|numeric|multi-hop|conditional|cross-lingual|abstention
    note: str = ""                       # what the question stresses


@dataclass(frozen=True)
class BenchScenario:
    id: str
    name: str
    category: str
    description: str
    stresses: str
    docs: tuple[str, ...]
    questions: tuple[BenchQuestion, ...] = field(default_factory=tuple)

    def question_count(self, answerable: bool | None = None) -> int:
        if answerable is None:
            return len(self.questions)
        return sum(1 for q in self.questions if q.answerable == answerable)

    def meta(self) -> dict:
        return {
            "id": self.id, "name": self.name, "category": self.category,
            "description": self.description, "stresses": self.stresses,
            "doc_count": len(self.docs), "question_count": len(self.questions),
            "answerable": self.question_count(True),
            "unanswerable": self.question_count(False),
            "qtypes": sorted({q.qtype for q in self.questions}),
        }


# ================================================================ techdocs
_t = (
    BenchQuestion("t1", "What is the maximum size of a single message on the NimbusDB Pro tier?",
                  "256 MB", ("bench-techdocs-02-limits.md",), qtype="lookup"),
    BenchQuestion("t2", "How long is data retained on the NimbusDB Enterprise tier before automatic deletion?",
                  "90 days", ("bench-techdocs-02-limits.md",), qtype="lookup"),
    BenchQuestion("t3", "Which API endpoint lists all namespaces, and which HTTP method does it use?",
                  "GET /v1/namespaces", ("bench-techdocs-03-api.md",), qtype="lookup"),
    BenchQuestion("t4", "What HTTP status and error code does the NimbusDB API return when the rate limit is exceeded?",
                  "HTTP 429 with error code ERR_RATE_LIMIT", ("bench-techdocs-03-api.md",), qtype="lookup"),
    BenchQuestion("t5", "Which consistency model does the NimbusDB async replication tier provide?",
                  "Eventual consistency (cross-region replication lag typically under 2 seconds)",
                  ("bench-techdocs-04-architecture.md",), qtype="lookup"),
    BenchQuestion("t6", "Is data encrypted at rest by default on NimbusDB, and if so with which algorithm?",
                  "Yes — AES-256 in GCM mode, enabled by default and cannot be disabled",
                  ("bench-techdocs-05-security.md",), qtype="lookup"),
    BenchQuestion("t7", "What is the default limit on concurrent connections for the NimbusDB Starter tier?",
                  "20 concurrent connections", ("bench-techdocs-02-limits.md",), qtype="lookup"),
    BenchQuestion("t8", "In which public regions can Enterprise customers pin namespaces for data residency?",
                  "eu-central-1 (Frankfurt), us-east-1 (Northern Virginia), ap-southeast-2 (Sydney)",
                  ("bench-techdocs-04-architecture.md",), qtype="lookup"),
)

# ================================================================ finance
_f = (
    BenchQuestion("f1", "What was Northwind Analytics' total revenue in Q3 FY2026?",
                  "$142.8 million (up 11.2% year over year)", ("bench-finance-01-northwind-q3.md",),
                  qtype="numeric", note="near-identical Avalanche Q3 revenue $142.6M is a distractor"),
    BenchQuestion("f2", "What was Northwind Analytics' total revenue in Q2 FY2026?",
                  "$128.4 million", ("bench-finance-02-northwind-q2.md",),
                  qtype="numeric", note="same company, previous quarter — quarter discrimination"),
    BenchQuestion("f3", "What was Avalanche Robotics' diluted earnings per share in Q3 FY2026?",
                  "$1.26", ("bench-finance-03-avalanche-q3.md",),
                  qtype="numeric", note="Northwind Q3 EPS is $1.24 — company discrimination"),
    BenchQuestion("f4", "By how much did Northwind Analytics' annual recurring revenue grow between Q2 and Q3 of FY2026?",
                  "From $470 million to $512 million — an increase of $42 million, or 8.9%, in one quarter",
                  ("bench-finance-01-northwind-q3.md", "bench-finance-02-northwind-q2.md"),
                  qtype="multi-hop", note="requires both Q3 and Q2 documents"),
    BenchQuestion("f5", "What Q4 FY2026 revenue guidance did Northwind Analytics give in its Q3 report?",
                  "$150–155 million, representing 10–13% year-over-year growth",
                  ("bench-finance-01-northwind-q3.md",), qtype="numeric"),
    BenchQuestion("f6", "Which company had the higher Q3 FY2026 gross margin, Northwind Analytics or Avalanche Robotics, and what were the two values?",
                  "Northwind Analytics — 68.4% versus Avalanche Robotics' 68.1%",
                  ("bench-finance-01-northwind-q3.md", "bench-finance-03-avalanche-q3.md"),
                  qtype="multi-hop", note="two companies, nearly identical margins, comparison required"),
    BenchQuestion("f7", "How many employees did Avalanche Robotics have at the end of Q3 FY2026?",
                  "2,115 employees (net increase of 75 during the quarter)",
                  ("bench-finance-03-avalanche-q3.md",), qtype="numeric"),
    BenchQuestion("f8", "According to its Q3 FY2026 report, what primarily drove Northwind Analytics' cloud segment growth?",
                  "Enterprise tier adoption and consumption overage from existing accounts expanding workloads",
                  ("bench-finance-01-northwind-q3.md",), qtype="lookup"),
)

# ================================================================ policy
_p = (
    BenchQuestion("p1", "An employee books an intercontinental flight scheduled at 9 hours. Which cabin class are they permitted to book?",
                  "Business class — permitted for intercontinental flights scheduled at 8 hours or longer",
                  ("bench-policy-02-travel.md",), qtype="conditional",
                  note="duration rule only; seniority is explicitly irrelevant"),
    BenchQuestion("p2", "At most, how many unused PTO days can an employee carry over into the next calendar year?",
                  "5 days, regardless of tenure", ("bench-policy-01-leave.md",), qtype="conditional",
                  note="tenure affects total PTO, not the carryover cap — distractor condition"),
    BenchQuestion("p3", "What is the daily per diem for meals and incidentals in a Tier-1 city such as New York?",
                  "$110 per day", ("bench-policy-02-travel.md",), qtype="numeric"),
    BenchQuestion("p4", "Is alcohol ever reimbursable under the corporate expense policy?",
                  "No — alcohol is never reimbursable, including alcohol embedded in a business-dinner bill",
                  ("bench-policy-03-expenses.md",), qtype="lookup"),
    BenchQuestion("p5", "What is the maximum per-person spend for client entertainment?",
                  "$120 per person per occasion", ("bench-policy-03-expenses.md",), qtype="numeric",
                  note="distinct from the $40/person internal team-event cap"),
    BenchQuestion("p6", "How many weeks of parental leave at full pay does a primary caregiver receive?",
                  "16 weeks, usable any time within the first twelve months after birth or adoption",
                  ("bench-policy-01-leave.md",), qtype="lookup",
                  note="secondary caregivers get 8 weeks — role discrimination"),
    BenchQuestion("p7", "An employee classified as remote-first (60% remote) lives in a Tier-1 city and wants a coworking membership. What does the company cover?",
                  "Up to $250 per month, with a 3-month minimum commitment",
                  ("bench-policy-04-remote.md",), qtype="conditional"),
    BenchQuestion("p8", "How many total PTO days does an employee with 5 completed years of service have?",
                  "27 days — the 25-day base plus one extra day for every 2 completed years (2 extra after 5 years)",
                  ("bench-policy-01-leave.md",), qtype="multi-hop",
                  note="requires combining base allowance with the tenure rule"),
)

# ================================================================ distractor
_d = (
    BenchQuestion("d1", "How do you reset the ScanLite SL-300 after an error code 13 paper jam?",
                  "Hold Stop and Scan together for 8 seconds until the display shows READY (after rotating the rear green lever to the locked position)",
                  ("bench-distractor-02-sl300.md",), qtype="lookup",
                  note="each model has a different reset combo — 5 near-identical distractor docs"),
    BenchQuestion("d2", "What is the standard paper tray capacity of the XeroxGraph XG-200?",
                  "550 sheets (80 g/m²), plus a 100-sheet multipurpose tray",
                  ("bench-distractor-05-xg200.md",), qtype="numeric"),
    BenchQuestion("d3", "Which firmware version fixes the duplex issue on the ScanLite SL-400?",
                  "v3.2.1 (fixes the duplex skew issue on units manufactured before March 2025)",
                  ("bench-distractor-03-sl400.md",), qtype="lookup"),
    BenchQuestion("d4", "On the XeroxGraph XG-100, what does a blinking amber status light indicate?",
                  "Low fuser oil — top up the fuser oil reservoir or risk permanent roller glazing",
                  ("bench-distractor-04-xg100.md",), qtype="lookup",
                  note="every model has a different amber-light meaning"),
    BenchQuestion("d5", "What is the full factory-reset procedure for the XeroxGraph XG-300?",
                  "Menu → Service → Factory Reset, confirm, then hold the Go button for 5 seconds to re-initialize feed-path calibration",
                  ("bench-distractor-06-xg300.md",), qtype="lookup"),
    BenchQuestion("d6", "What paper weight range does the ScanLite SL-200 support?",
                  "60–163 g/m² through the standard trays; card stock above that uses the manual bypass",
                  ("bench-distractor-01-sl200.md",), qtype="numeric"),
    BenchQuestion("d7", "After clearing a paper jam on the ScanLite SL-300, what must you do before resuming printing?",
                  "Rotate the green lever on the rear feed module to the locked position",
                  ("bench-distractor-02-sl300.md",), qtype="lookup"),
    BenchQuestion("d8", "Which spare part is most frequently needed for XG-200 roller wear?",
                  "The pickup roller kit RK-220, rated for 65,000 sheets",
                  ("bench-distractor-05-xg200.md",), qtype="lookup",
                  note="each model needs a different RK part number"),
)

# ================================================================ multilingual
_m = (
    BenchQuestion("m1", "What is the daily visitor capacity limit for the Lumen: Northern Light exhibition?",
                  "3,000 visitors per day (每日限流 3,000 人)", ("bench-multi-02-zh.md",),
                  qtype="cross-lingual", note="fact only exists in the Chinese doc; question asked in English"),
    BenchQuestion("m2", "How much does the Lumen exhibition catalogue cost?",
                  "€34 for the 240-page hardcover", ("bench-multi-03-de.md",),
                  qtype="cross-lingual", note="fact only exists in the German doc"),
    BenchQuestion("m3", "What discount do school groups receive for the Lumen exhibition?",
                  "40% off the reduced rate (€9.60 per pupil); accompanying teachers enter free",
                  ("bench-multi-04-fr.md",), qtype="cross-lingual", note="fact only exists in the French doc"),
    BenchQuestion("m4", "How many works are displayed in the Lumen: Northern Light exhibition?",
                  "230 works across 14 halls", ("bench-multi-01-en.md",), qtype="lookup"),
    BenchQuestion("m5", "Which weekday does the museum stay open late for the exhibition, and until when?",
                  "Friday — open until 22:00 (last entry 21:00), stated only in the Chinese guide",
                  ("bench-multi-02-zh.md",), qtype="cross-lingual"),
    BenchQuestion("m6", "《光之北域》特展的标准成人票价是多少欧元？",
                  "标准票价 €24（学生与 65 岁以上 €16，12 岁以下免费）",
                  ("bench-multi-01-en.md",), qtype="cross-lingual",
                  note="question in Chinese; fact lives in the English doc"),
    BenchQuestion("m7", "How many languages does the Lumen exhibition audio guide support?",
                  "Six languages (German, English, Dutch, French, Chinese, Spanish), included in the ticket price",
                  ("bench-multi-03-de.md",), qtype="cross-lingual"),
    BenchQuestion("m8", "Bis wann läuft die Ausstellung Lumen: Northern Light?",
                  "Bis zum 21. September 2026 (Beginn: 4. April 2026)",
                  ("bench-multi-01-en.md",), qtype="cross-lingual",
                  note="question in German; fact lives in the English doc"),
)

# ================================================================ outofscope
_o = (
    BenchQuestion("o1", "What hydration percentage does the house sourdough bread recipe use?",
                  "72% hydration (648 g water per 900 g flour)", ("bench-oos-02-bread.md",), qtype="numeric"),
    BenchQuestion("o2", "What is the distance between Earth and Mars at their closest approach?",
                  "", (), answerable=False, qtype="abstention",
                  note="astronomy — nothing in the corpus; system should abstain"),
    BenchQuestion("o3", "How do I file a patent for a software invention in Germany?",
                  "", (), answerable=False, qtype="abstention", note="legal — not in corpus"),
    BenchQuestion("o4", "How many grams of ground coffee does the barista guide recommend per espresso shot?",
                  "18 g in, 36 g out, in 25–30 seconds", ("bench-oos-03-coffee.md",), qtype="numeric"),
    BenchQuestion("o5", "Who won the 1998 FIFA World Cup final and what was the score?",
                  "", (), answerable=False, qtype="abstention", note="sports history — not in corpus"),
    BenchQuestion("o6", "What is the ideal internal temperature for roasting a whole chicken?",
                  "", (), answerable=False, qtype="abstention",
                  note="cooking-adjacent topic NOT covered by the corpus (only pasta/bread/coffee) — hard abstention case"),
    BenchQuestion("o7", "How long should fresh pasta dough rest before rolling?",
                  "30 minutes at room temperature, wrapped in film", ("bench-oos-01-pasta.md",), qtype="lookup"),
    BenchQuestion("o8", "In what year did the Berlin Wall fall?",
                  "", (), answerable=False, qtype="abstention", note="history — not in corpus"),
)


INTERNAL_SCENARIOS: tuple[BenchScenario, ...] = (
    BenchScenario(
        id="techdocs", name="Tech Product Docs", category="Single-hop factoid QA",
        description="NimbusDB product documentation: overview, limits & quotas, REST API, architecture, security.",
        stresses="Baseline grounding and retrieval sanity over in-domain technical docs (RAGAS 'simple' style).",
        docs=("bench-techdocs-01-overview.md", "bench-techdocs-02-limits.md", "bench-techdocs-03-api.md",
              "bench-techdocs-04-architecture.md", "bench-techdocs-05-security.md"),
        questions=_t,
    ),
    BenchScenario(
        id="finance", name="Earnings Reports", category="Distractor-heavy numeric QA",
        description="Two companies (Northwind Analytics, Avalanche Robotics) x two quarters of near-identical earnings figures.",
        stresses="Entity/quarter discrimination with near-identical numbers; multi-hop aggregation (FinanceBench-style).",
        docs=("bench-finance-01-northwind-q3.md", "bench-finance-02-northwind-q2.md",
              "bench-finance-03-avalanche-q3.md", "bench-finance-04-avalanche-q2.md"),
        questions=_f,
    ),
    BenchScenario(
        id="policy", name="Corporate Policies", category="Conditional rule QA",
        description="Employee handbook, travel, expense and remote-work policies with conditions, caps and exceptions.",
        stresses="Applying the right rule when several near-matching rules and distractor conditions exist.",
        docs=("bench-policy-01-leave.md", "bench-policy-02-travel.md",
              "bench-policy-03-expenses.md", "bench-policy-04-remote.md"),
        questions=_p,
    ),
    BenchScenario(
        id="distractor", name="Support KB (Needle)", category="Needle-in-haystack / near-duplicate retrieval",
        description="Six almost identical troubleshooting guides for six printer models; each answer is model-specific.",
        stresses="Rerank precision under maximum lexical overlap; punishes naive similarity ranking.",
        docs=("bench-distractor-01-sl200.md", "bench-distractor-02-sl300.md", "bench-distractor-03-sl400.md",
              "bench-distractor-04-xg100.md", "bench-distractor-05-xg200.md", "bench-distractor-06-xg300.md"),
        questions=_d,
    ),
    BenchScenario(
        id="multilingual", name="Lumen Exhibition", category="Cross-lingual retrieval",
        description="Museum exhibition guide with facts distributed across English, Chinese, German and French documents.",
        stresses="Cross-lingual embedding retrieval + multilingual Jev rerank; questions in EN/ZH/DE against mixed corpus.",
        docs=("bench-multi-01-en.md", "bench-multi-02-zh.md", "bench-multi-03-de.md", "bench-multi-04-fr.md"),
        questions=_m,
    ),
    BenchScenario(
        id="outofscope", name="Cooking Corpus + OoS", category="Abstention / hallucination under missing context",
        description="Small cooking corpus (pasta, sourdough, espresso) probed with 3 answerable and 5 unanswerable questions.",
        stresses="Context-sufficiency gate and refusal behaviour: over-abstention on answerable, fabrication on unanswerable (AbstentionBench-style).",
        docs=("bench-oos-01-pasta.md", "bench-oos-02-bread.md", "bench-oos-03-coffee.md"),
        questions=_o,
    ),
)

SCENARIO_MAP: dict[str, BenchScenario] = {s.id: s for s in INTERNAL_SCENARIOS}


# ================================================================ public benchmarks
def _load_public_scenarios() -> tuple[BenchScenario, ...]:
    """Load popular public RAG benchmarks (SQuAD, HotpotQA) from the manifest
    generated by backend/scripts/build_public_scenarios.py.

    The manifest carries full provenance (dataset URL, split size, sample seed and
    strategy) so the sample is reproducible; corpora live next to this file under
    corpora/<scenario_id>/. Returns () when the manifest is absent (e.g. a checkout
    that never ran the builder) so the internal suite keeps working standalone.
    """
    manifest_path = CORPUS_DIR / "public_benchmarks.json"
    if not manifest_path.exists():
        return ()
    import json

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        import logging
        logging.getLogger("jevrag.bench.scenarios").warning(
            "public benchmark manifest unreadable (%s) — skipping", e)
        return ()

    out: list[BenchScenario] = []
    for s in data.get("scenarios", []):
        try:
            questions = tuple(
                BenchQuestion(
                    id=q["id"], question=q["question"], reference=q["reference"],
                    gold_files=tuple(q["gold_files"]),
                    answerable=q.get("answerable", True),
                    qtype=q.get("qtype", "lookup"), note=q.get("note", ""),
                ) for q in s["questions"]
            )
            out.append(BenchScenario(
                id=s["id"], name=s["name"], category=s["category"],
                description=s["description"], stresses=s["stresses"],
                docs=tuple(s["docs"]), questions=questions,
            ))
        except (KeyError, TypeError) as e:
            import logging
            logging.getLogger("jevrag.bench.scenarios").warning(
                "public scenario '%s' malformed (%s) — skipped", s.get("id", "?"), e)
    return tuple(out)


PUBLIC_SCENARIOS: tuple[BenchScenario, ...] = _load_public_scenarios()
SCENARIOS: tuple[BenchScenario, ...] = INTERNAL_SCENARIOS + PUBLIC_SCENARIOS
SCENARIO_MAP.update({s.id: s for s in PUBLIC_SCENARIOS})


def scenario_dir(scenario_id: str) -> Path:
    return CORPUS_DIR / scenario_id


def doc_path(scenario_id: str, filename: str) -> Path:
    return scenario_dir(scenario_id) / filename
