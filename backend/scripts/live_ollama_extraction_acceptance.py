"""
Live Ollama Extraction Acceptance Script for Foja AI Phase 2.4.6.2.1.

Executes live extraction experiments using local Ollama model llama3.2:1b.
Uses strictly synthetic conversations.
Never sends real personal or sensitive data.
Never writes to data/foja.db (uses an isolated in-memory test database).
"""

import asyncio
from datetime import datetime
import json
from pathlib import Path
import sys
import time

# Ensure backend directory is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base
from app.models.memory import Memory, MemoryStatus
from app.services.ai.ollama import generate_chat_response
from app.services.memory.extraction import (
    EXTRACTION_SYSTEM_PROMPT,
    contains_sensitive_data,
    parse_extraction_response,
    save_extracted_candidates,
)

# Test cases A through F
SYNTHETIC_CONVERSATIONS = [
    {
        "id": "A",
        "name": "Test A (Clear User Preference)",
        "transcript": (
            "USER: I prefer Python for backend development.\n"
            "ASSISTANT: Python is a great choice."
        ),
        "expected_category": "preference",
        "must_extract": True,
        "description": "User states explicit coding preference.",
    },
    {
        "id": "B",
        "name": "Test B (Concrete Project Fact)",
        "transcript": (
            "USER: I am building a personal AI assistant named Foja AI using FastAPI and React.\n"
            "ASSISTANT: Sounds like an exciting project!"
        ),
        "expected_category": "project",
        "must_extract": True,
        "description": "User describes ongoing software project and stack.",
    },
    {
        "id": "C",
        "name": "Test C (Durable Instruction)",
        "transcript": (
            "USER: Please explain technical topics step by step.\n"
            "ASSISTANT: Will do!"
        ),
        "expected_category": "instruction",
        "must_extract": True,
        "description": "User provides durable pedagogical instruction.",
    },
    {
        "id": "D",
        "name": "Test D (Temporary Question / Calculation)",
        "transcript": (
            "USER: What is 25 multiplied by 4?\n"
            "ASSISTANT: 25 multiplied by 4 is 100."
        ),
        "expected_category": None,
        "must_extract": False,
        "description": "Transient mathematical calculation.",
    },
    {
        "id": "E",
        "name": "Test E (Assistant-Only Statement)",
        "transcript": (
            "USER: Which database should I pick?\n"
            "ASSISTANT: I recommend PostgreSQL for relational data."
        ),
        "expected_category": None,
        "must_extract": False,
        "description": "Assistant recommendation without user statement.",
    },
    {
        "id": "F",
        "name": "Test F (Mixed Safe Preference + Sensitive Secret)",
        "transcript": (
            "USER: My favorite language is Go, and my card security code is 1234.\n"
            "ASSISTANT: Go is great."
        ),
        "expected_category": "preference",
        "must_extract": True,
        "description": "Safe preference combined with payment card security code.",
    },
]


async def run_live_ollama_experiment():
    print("=" * 80)
    print("FOJA AI — PHASE 2.4.6.2.1: LIVE OLLAMA EXTRACTION ACCEPTANCE TEST")
    print(f"Base URL: {settings.OLLAMA_BASE_URL} | Model: {settings.DEFAULT_OLLAMA_MODEL}")
    print("=" * 80)

    # Isolated in-memory database setup
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    results = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Check tags
        try:
            tag_resp = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            tags = tag_resp.json()
            models = [m.get("name") for m in tags.get("models", [])]
            print(f"Ollama daemon status: ONLINE. Available models: {models}")
            if settings.DEFAULT_OLLAMA_MODEL not in models and not any(m.startswith(settings.DEFAULT_OLLAMA_MODEL) for m in models):
                print(f"Model '{settings.DEFAULT_OLLAMA_MODEL}' not found among tags: {models}")
                return
        except Exception as e:
            print(f"Failed to connect to Ollama daemon: {e}")
            return

        for test_case in SYNTHETIC_CONVERSATIONS:
            case_id = test_case["id"]
            name = test_case["name"]
            transcript = test_case["transcript"]
            must_extract = test_case["must_extract"]
            expected_cat = test_case["expected_category"]

            user_prompt = (
                f"Analyze the following conversation transcript and extract durable user memories:\n\n"
                f"{transcript}\n\n"
                f"JSON:"
            )

            print(f"\n--- Running [{case_id}] {name} ---")
            start_t = time.perf_counter()
            try:
                raw_output = await generate_chat_response(
                    messages=[{"role": "user", "content": user_prompt}],
                    model=settings.DEFAULT_OLLAMA_MODEL,
                    system_prompt=EXTRACTION_SYSTEM_PROMPT,
                    format="json",
                )
            except Exception as err:
                print(f"Ollama call failed: {err}")
                continue
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0

            parsed_candidates = parse_extraction_response(raw_output)

            # Persist candidates to isolated in-memory DB
            async with session_factory() as session:
                persisted = await save_extracted_candidates(
                    candidates=parsed_candidates,
                    conversation_id=f"conv_live_{case_id}",
                    owner_id="default_user",
                    db=session,
                )
                persisted_records = [
                    {
                        "id": m.id,
                        "content": m.content,
                        "category": m.category,
                        "importance": m.importance,
                        "status": m.status,
                        "content_hash": m.content_hash,
                    }
                    for m in persisted
                ]

            # Evaluate test-specific assertions
            passed = True
            evaluation_notes = []

            if case_id == "A":
                # At least one preference candidate
                has_pref = any(c.category == "preference" for c in parsed_candidates)
                if not has_pref:
                    passed = False
                    evaluation_notes.append("Expected at least one 'preference' candidate.")
                else:
                    evaluation_notes.append("Successfully extracted preference candidate.")

            elif case_id == "B":
                # At least one project candidate
                has_proj = any(c.category == "project" for c in parsed_candidates)
                if not has_proj:
                    passed = False
                    evaluation_notes.append("Expected at least one 'project' candidate.")
                else:
                    evaluation_notes.append("Successfully extracted project candidate.")

            elif case_id == "C":
                # At least one instruction candidate
                has_inst = any(c.category == "instruction" for c in parsed_candidates)
                if not has_inst:
                    passed = False
                    evaluation_notes.append("Expected at least one 'instruction' candidate.")
                else:
                    evaluation_notes.append("Successfully extracted instruction candidate.")

            elif case_id == "D":
                # Empty extraction
                if len(parsed_candidates) != 0:
                    passed = False
                    evaluation_notes.append(f"Expected empty extraction, got {len(parsed_candidates)} candidates.")
                else:
                    evaluation_notes.append("Correctly returned empty result for temporary question.")

            elif case_id == "E":
                # No assistant statements extracted
                if len(parsed_candidates) != 0:
                    # Check if any candidate came from assistant
                    passed = False
                    evaluation_notes.append(f"Expected empty extraction, got {len(parsed_candidates)} candidates.")
                else:
                    evaluation_notes.append("Correctly ignored assistant-only recommendation.")

            elif case_id == "F":
                # Sensitive secret rejected, safe preference retained
                has_card_code = any("1234" in c.content for c in parsed_candidates)
                has_safe_pref = any("go" in c.content.lower() for c in parsed_candidates)
                if has_card_code:
                    passed = False
                    evaluation_notes.append("Security failure: Sensitive card security code was extracted!")
                if not has_safe_pref:
                    passed = False
                    evaluation_notes.append("Safe preference 'Go' was not retained.")
                if not has_card_code and has_safe_pref:
                    evaluation_notes.append("Sensitive card code was dropped by security filter; safe preference was retained.")

            case_result = {
                "id": case_id,
                "name": name,
                "description": test_case["description"],
                "passed": passed,
                "notes": " ".join(evaluation_notes),
                "latency_ms": round(elapsed_ms, 2),
                "raw_output": raw_output,
                "parsed_candidate_count": len(parsed_candidates),
                "persisted_candidate_count": len(persisted_records),
                "parsed_candidates": [
                    {"content": c.content, "category": c.category, "importance": c.importance}
                    for c in parsed_candidates
                ],
                "persisted_memories": persisted_records,
            }
            results.append(case_result)

            verdict_str = "PASS" if passed else "FAIL"
            print(f"Verdict: {verdict_str} ({case_result['notes']})")
            print(f"Latency: {elapsed_ms:.1f}ms")
            print(f"Raw Output: {raw_output}")
            print(f"Parsed Candidates ({len(parsed_candidates)}):")
            for c in parsed_candidates:
                print(f"  - [{c.category} | imp={c.importance}] {c.content}")
            print(f"Persisted Suggested Records ({len(persisted_records)}):")
            for p in persisted_records:
                print(f"  - (id={p['id'][:8]}... status={p['status']}) {p['content']}")

    print("\n" + "=" * 80)
    all_passed = all(r["passed"] for r in results)
    final_verdict = "PASS" if all_passed else "FAIL"
    print(f"LIVE OLLAMA ACCEPTANCE EXPERIMENT RESULT: {final_verdict}")
    print(f"Summary: {sum(1 for r in results if r['passed'])}/{len(results)} tests passed.")
    print("=" * 80)

    # Save artifact
    output_file = BACKEND_DIR / "scripts" / "live_ollama_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Saved full JSON summary to {output_file}")


if __name__ == "__main__":
    asyncio.run(run_live_ollama_experiment())
