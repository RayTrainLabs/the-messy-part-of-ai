"""LLM judge providers for the recommendations engine.

Each module exposes:
    is_available() -> bool
    judge(system_prompt: str, user_payload: dict, model: str | None = None) -> str

Anthropic is the default judge (different model family from the brands' typical
in-product LLMs reduces self-judgment bias). Cascades to OpenAI, then Gemini on
quota / rate-limit / transient failures so a single provider issue doesn't kill
the run.
"""

import sys

from . import anthropic_client, openai_client, gemini_client


def judge_provider(prefer="anthropic"):
    order = {
        "anthropic": [anthropic_client, openai_client, gemini_client],
        "openai":    [openai_client, anthropic_client, gemini_client],
        "gemini":    [gemini_client, anthropic_client, openai_client],
    }.get(prefer, [anthropic_client, openai_client, gemini_client])

    available = [m for m in order if m.is_available() and hasattr(m, "judge")]
    if not available:
        return None
    if len(available) == 1:
        return available[0]
    return _CascadingJudge(available)


class _CascadingJudge:
    """Falls back across providers on quota / rate-limit / transient errors."""

    def __init__(self, modules):
        self._modules = modules
        self._active = modules[0]

    @property
    def PROVIDER_NAME(self):
        return getattr(self._active, "PROVIDER_NAME", "?")

    @property
    def JUDGE_MODEL(self):
        return getattr(self._active, "JUDGE_MODEL", None)

    @JUDGE_MODEL.setter
    def JUDGE_MODEL(self, value):
        try:
            self._active.JUDGE_MODEL = value
        except Exception:
            pass

    def judge(self, system_prompt, user_payload, model=None, **kwargs):
        last_err = None
        for mod in self._modules:
            if not mod.is_available():
                continue
            self._active = mod
            try:
                return mod.judge(system_prompt, user_payload, model=model)
            except Exception as e:
                last_err = e
                print(f"[providers] {getattr(mod, 'PROVIDER_NAME', '?')} judge failed "
                      f"({type(e).__name__}: {str(e)[:120]}); trying next provider",
                      file=sys.stderr)
                continue
        raise RuntimeError(f"all judge providers failed; last error: {last_err}")
