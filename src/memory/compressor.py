"""Context Compression — 대용량 Handoff Artifact 압축/요약."""

from __future__ import annotations

import logging

import litellm

from src.orchestrator.handoff import (
    Decision,
    HandoffArtifact,
    MemoryContext,
)

logger = logging.getLogger(__name__)

# 기본 토큰 제한 (초과 시 압축 트리거)
DEFAULT_MAX_CONTEXT_TOKENS = 12000

# 압축 요약 모델 (가벼운 모델 사용)
DEFAULT_COMPRESSOR_MODEL = "docs-agent"


def estimate_tokens(text: str) -> int:
    """텍스트의 대략적 토큰 수 추정. 영문 기준 ~4자/토큰, 한글 ~2자/토큰."""
    ascii_count = sum(1 for c in text if ord(c) < 128)
    non_ascii_count = len(text) - ascii_count
    return (ascii_count // 4) + (non_ascii_count // 2) + 1


def compress_text(text: str, max_length: int = 2000) -> str:
    """텍스트를 최대 길이로 자르되 문장 경계를 존중한다."""
    if len(text) <= max_length:
        return text

    truncated = text[:max_length]
    # 마지막 문장 끝 찾기
    for sep in ["\n\n", "\n", ". ", "。"]:
        last_sep = truncated.rfind(sep)
        if last_sep > max_length // 2:
            return truncated[: last_sep + len(sep)].rstrip() + "\n[...truncated]"

    return truncated.rstrip() + "\n[...truncated]"


def compress_decisions(decisions: list[Decision], max_count: int = 5) -> list[Decision]:
    """결정 목록을 최대 개수로 제한 (최근 것 유지)."""
    if len(decisions) <= max_count:
        return decisions
    return decisions[-max_count:]


def compress_memory_context(
    context: MemoryContext | None,
    max_patterns: int = 5,
    max_decisions: int = 5,
) -> MemoryContext | None:
    """메모리 컨텍스트를 압축한다."""
    if context is None:
        return None

    return MemoryContext(
        relevant_past_decisions=context.relevant_past_decisions[:max_decisions],
        known_patterns=context.known_patterns[:max_patterns],
        error_history=context.error_history[:3],
        human_feedback=context.human_feedback[:3],
    )


def compress_handoff(
    handoff: HandoffArtifact,
    max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
) -> HandoffArtifact:
    """Handoff Artifact를 토큰 제한에 맞춰 압축.

    압축 대상 (우선순위):
    1. memory_context — 패턴/결정 수 제한
    2. task.completed_summary — 텍스트 truncation
    3. task.next_instructions — 텍스트 truncation
    4. task.decisions_made — 최근 N개만 유지

    원본을 변경하지 않고 deep copy 후 압축한다.
    """
    # 현재 토큰 수 추정
    serialized = handoff.model_dump_json()
    current_tokens = estimate_tokens(serialized)

    if current_tokens <= max_context_tokens:
        return handoff

    logger.info(
        "Compressing handoff [%s]: %d tokens → target %d",
        handoff.envelope.handoff_id,
        current_tokens,
        max_context_tokens,
    )

    compressed = handoff.model_copy(deep=True)

    # 1단계: 메모리 컨텍스트 압축
    compressed.memory_context = compress_memory_context(
        compressed.memory_context,
        max_patterns=3,
        max_decisions=3,
    )

    # 2단계: completed_summary 압축
    if len(compressed.task.completed_summary) > 1000:
        compressed.task.completed_summary = compress_text(
            compressed.task.completed_summary, max_length=1000
        )

    # 3단계: decisions 제한
    compressed.task.decisions_made = compress_decisions(
        compressed.task.decisions_made, max_count=5
    )

    # 4단계: next_instructions 압축 (최후 수단)
    new_tokens = estimate_tokens(compressed.model_dump_json())
    if new_tokens > max_context_tokens and len(compressed.task.next_instructions) > 2000:
        compressed.task.next_instructions = compress_text(
            compressed.task.next_instructions, max_length=2000
        )

    final_tokens = estimate_tokens(compressed.model_dump_json())
    logger.info(
        "Compression result for [%s]: %d → %d tokens (%.0f%% reduction)",
        handoff.envelope.handoff_id,
        current_tokens,
        final_tokens,
        (1 - final_tokens / current_tokens) * 100,
    )

    return compressed


async def summarize_text(
    text: str,
    model: str = DEFAULT_COMPRESSOR_MODEL,
    max_summary_length: int = 500,
) -> str:
    """LLM을 사용하여 텍스트를 요약한다.

    네트워크 에러 시 단순 truncation으로 폴백.
    """
    if estimate_tokens(text) < 500:
        return text

    try:
        response = await litellm.acompletion(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Summarize the following text concisely. "
                        f"Keep it under {max_summary_length} characters. "
                        "Preserve key technical details and decisions."
                    ),
                },
                {"role": "user", "content": text},
            ],
            max_tokens=max_summary_length,
            temperature=0.1,
        )
        return response.choices[0].message.content or text[:max_summary_length]
    except Exception:
        logger.warning("LLM summarization failed, falling back to truncation")
        return compress_text(text, max_length=max_summary_length)
