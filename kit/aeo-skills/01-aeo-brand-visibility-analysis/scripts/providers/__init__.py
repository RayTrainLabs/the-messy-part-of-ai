"""Provider registry for AEO query execution and scoring.

Each provider module exposes:
    is_available() -> bool
    call(query: str, brand_profile: dict, **kwargs) -> dict   # returns unified row payload

For LLM judge usage (analyze_response.py), each LLM provider also exposes:
    judge(system_prompt: str, user_payload: dict, model: str | None = None) -> str
"""

from . import serpapi_client, apify_client, openai_client, anthropic_client, perplexity_client, gemini_client

# Order matters for SERP fallback (first available wins)
SERP_PROVIDERS = [
    ("serp_google", serpapi_client),
    ("serp_google", apify_client),  # falls back to Apify if SerpApi missing
]

LLM_PROVIDERS = [
    ("llm_openai",     openai_client),
    ("llm_anthropic",  anthropic_client),
    ("llm_perplexity", perplexity_client),
    ("llm_gemini",     gemini_client),
]


def available_engines():
    """Returns [(engine_id, module), ...] for every configured provider."""
    out = []

    # SERP — first-available-wins
    for engine_id, mod in SERP_PROVIDERS:
        if mod.is_available():
            out.append((engine_id, mod))
            break

    for engine_id, mod in LLM_PROVIDERS:
        if mod.is_available():
            out.append((engine_id, mod))

    return out


def judge_provider(prefer="anthropic"):
    """Pick an LLM provider for scoring. Returns a wrapper module that
    transparently falls back across providers when one fails (quota, rate-limit,
    transient HTTP). Anthropic is preferred (different family from typical
    audited engines reduces self-judgment bias).
    """
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
    """Wraps the first-available judge but falls back to the next provider on
    quota / rate-limit / transient errors. Returns a module-like object so
    callers can keep using `mod.judge(...)`, `mod.PROVIDER_NAME`, `mod.JUDGE_MODEL`.
    """

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
                return mod.judge(system_prompt, user_payload, model=model, **kwargs) \
                    if "max_output_tokens" in mod.judge.__code__.co_varnames \
                    else mod.judge(system_prompt, user_payload, model=model)
            except Exception as e:
                import sys as _sys
                last_err = e
                print(f"[providers] {getattr(mod, 'PROVIDER_NAME', '?')} judge failed "
                      f"({type(e).__name__}: {str(e)[:120]}); trying next provider",
                      file=_sys.stderr)
                continue
        raise RuntimeError(f"all judge providers failed; last error: {last_err}")
