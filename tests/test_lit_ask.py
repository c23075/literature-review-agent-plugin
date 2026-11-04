"""lit.ask: answers from a library with page citations (FR-RES-2), with a scripted model."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from cairnward_research import GatewayEmbedder, Research
from cairnward_research.ask import (
    ANSWER_TOKENS,
    REASONING_TOKENS,
    cited_numbers,
    fit,
    mark_invalid,
    run_ask,
)
from cairnward_research.library import Hit
from tests.fakes.pdf import make_pdf

QUESTION = "Does longer sleep improve working memory?"


def test_cited_numbers() -> None:
    dash = chr(0x2013)  # en dash, as models often write ranges
    text = f"a [1]. b [2, 3] c [4{dash}6] d [2] e [10-11]"
    assert cited_numbers(text) == [1, 2, 3, 4, 5, 6, 10, 11]
    assert cited_numbers("no citations (see 2020)") == []


def hit(n: int, words: int) -> Hit:
    return Hit(n, n, f"T{n}", f"/p/{n}.pdf", 1, 1, "word " * words, 1.0 / n, n, None)


def test_fit_keeps_best_ranked_within_context() -> None:
    hits = [hit(i, 400) for i in range(1, 9)]  # ~500 tokens each
    assert [h.chunk_id for h in fit(hits, 4096, "q")] == [1, 2, 3, 4]
    assert len(fit(hits, None, "q")) == 8


@pytest.fixture
async def env(tmp_path: Path, rt: Any, core: Any) -> Any:
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "sleep.pdf").write_bytes(make_pdf(
        [[f"Line {i}: participants who slept longer had better working memory." for i in range(25)],
         [f"Line {i}: the effect held after controlling for age." for i in range(25)]],
        title="Sleep and Memory"))  # fmt: skip
    (papers / "caffeine.pdf").write_bytes(make_pdf(
        [[f"Line {i}: caffeine shortened reaction time." for i in range(25)]],
        title="Caffeine Trial"))  # fmt: skip
    with Research.open(rt.paths) as r:
        r.create("thesis", papers, "litreview-offline")
        await r.index("thesis", GatewayEmbedder(rt, environment="litreview-offline"))
    return rt, core


def test_mark_invalid() -> None:
    assert mark_invalid("a [1] b [1, 2] c [1-2].", 2) == "a [1] b [1, 2] c [1-2]."
    text = "a [9] b [1, 9] c [1-3] d [8, 9]."
    assert mark_invalid(text, 2) == "a [?] b [1, ?] c [1, 2, ?] d [?]."


async def test_reasoning_that_uses_the_whole_limit_is_reported(env: Any) -> None:
    """The shape of a real reply (q1 in evals/pdf_qa) through the gateway: empty content and
    finish_reason "length"."""
    rt, fake = env
    fake.reply, fake.finish_reason = "", "length"
    answer = await run_ask(rt, "thesis", QUESTION, k=4)
    assert answer.cut_off and answer.text == "" and answer.sources == []
    rendered = answer.render()
    assert "reached its token limit before answering" in rendered
    assert "cites no passage" not in rendered


async def test_answer_cut_off_after_it_started(env: Any) -> None:
    rt, fake = env
    fake.reply, fake.finish_reason = "Longer sleep went with better memory [1] and", "length"
    answer = await run_ask(rt, "thesis", QUESTION, k=4)
    assert answer.cut_off and [s.n for s in answer.sources] == [1]
    assert "this answer is cut off" in answer.render()


async def test_unfinished_think_tag_is_not_taken_as_the_answer(env: Any) -> None:
    """Servers that keep reasoning in the content: a cut-off reply has no closing tag, and
    numbers in the reasoning must not count as citations."""
    rt, fake = env
    fake.reply, fake.finish_reason = "<think>Passage [1] says...", "length"
    answer = await run_ask(rt, "thesis", QUESTION, k=4)
    assert answer.cut_off and answer.text == "" and answer.sources == []


async def test_limit_leaves_room_for_reasoning_only_when_it_is_on(env: Any) -> None:
    rt, fake = env
    fake.thinking = True
    await run_ask(rt, "thesis", QUESTION, k=4, effort="high")
    assert fake.chats[-1]["max_tokens"] == ANSWER_TOKENS + REASONING_TOKENS
    assert fake.chats[-1]["model"] == "cw/litreview-offline:high"
    fake.thinking = False
    await run_ask(rt, "thesis", QUESTION, k=4, effort="low")
    assert fake.chats[-1]["max_tokens"] == ANSWER_TOKENS


def test_reply_room_comes_out_of_the_passages() -> None:
    hits = [SimpleNamespace(text="word " * 1000, chunk_id=i) for i in range(4)]
    roomy = fit(hits, 8192, "q")  # type: ignore[arg-type]
    tight = fit(hits, 8192, "q", reply_tokens=5000)  # type: ignore[arg-type]
    assert len(tight) < len(roomy)


async def test_reasoning_with_thinking_off_is_not_taken_as_the_answer(env: Any) -> None:
    """The shape of a real reply (qwen3:30b with think=false): reasoning in the content,
    no opening tag, then a closing one. Numbers in it must not count as citations."""
    rt, fake = env
    fake.reply = "We are given passages. Passage [3] looks useful.\n</think>\n\nYes, it helps [1]."
    answer = await run_ask(rt, "thesis", QUESTION, k=4)
    assert answer.text == "Yes, it helps [1]." and [s.n for s in answer.sources] == [1]


async def test_answer_with_sources(env: Any) -> None:
    rt, fake = env
    fake.reply = (
        "<think>let me see</think>Yes: longer sleep went with better working memory [1, 2]. "
        "Some say otherwise [9]."
    )
    answer = await run_ask(rt, "thesis", QUESTION, k=4)
    assert answer.passages == 4 and not answer.uncited and not answer.cannot_answer
    assert [s.n for s in answer.sources] == [1, 2]
    assert answer.invalid_citations == [9] and "[?]" in answer.text and "<think>" not in answer.text
    sent = fake.chats[-1]["messages"]
    assert sent[0]["role"] == "system" and "ONLY the numbered passages" in sent[0]["content"]
    assert "[1] " in sent[1]["content"] and sent[1]["content"].endswith(f"Question: {QUESTION}")
    rendered = answer.render()
    assert "Sources:" in rendered and ", p. " in rendered and "removed citations" in rendered


async def test_cannot_answer_and_uncited(env: Any) -> None:
    rt, fake = env
    fake.reply = "I can't answer this from these sources. They don't cover diet."
    a = await run_ask(rt, "thesis", "What about diet and memory?")
    assert a.cannot_answer and a.uncited and "Warning" not in a.render()
    fake.reply = "Sleep is good for memory."
    b = await run_ask(rt, "thesis", QUESTION)
    assert b.uncited and not b.cannot_answer and "don't rely on it" in b.render()


async def test_a_refusal_from_the_gateway_is_reported(env: Any) -> None:
    from cairnward_research import EmbeddingDenied

    rt, fake = env
    fake.refuse_models = "this run is in 'a', not 'b'"
    with pytest.raises(EmbeddingDenied, match="this run is in"):
        await run_ask(rt, "thesis", QUESTION)
