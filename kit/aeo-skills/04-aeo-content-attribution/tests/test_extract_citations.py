"""Tests for extract_citations.py."""

import pytest


# normalize_url

class TestNormalizeUrl:
    def test_strips_protocol(self, ec):
        assert ec.normalize_url("https://example.com/x") == "example.com/x"
        assert ec.normalize_url("http://example.com/x") == "example.com/x"

    def test_strips_www(self, ec):
        assert ec.normalize_url("https://www.example.com/x") == "example.com/x"

    def test_strips_trailing_slash(self, ec):
        assert ec.normalize_url("https://example.com/x/") == "example.com/x"

    def test_drops_query_and_fragment(self, ec):
        assert ec.normalize_url("https://example.com/x?a=1#frag") == "example.com/x"

    def test_lowercases(self, ec):
        assert ec.normalize_url("HTTPS://Example.COM/Path") == "example.com/path"

    def test_empty(self, ec):
        assert ec.normalize_url("") == ""
        assert ec.normalize_url(None) == ""

    def test_strips_trailing_punct(self, ec):
        assert ec.normalize_url("https://example.com/x.") == "example.com/x"
        assert ec.normalize_url("https://example.com/x),") == "example.com/x"


# _strip_trailing_punct

class TestStripTrailingPunct:
    def test_strips_each_punct_char(self, ec):
        for ch in ".,;:!?)]}>\"'":
            assert ec._strip_trailing_punct(f"https://example.com/x{ch}") == "https://example.com/x"

    def test_strips_multiple(self, ec):
        assert ec._strip_trailing_punct("https://x.com/y).,") == "https://x.com/y"

    def test_leaves_clean_url_alone(self, ec):
        assert ec._strip_trailing_punct("https://example.com/x") == "https://example.com/x"

    def test_empty(self, ec):
        assert ec._strip_trailing_punct("") == ""


# extract_urls_from_text

class TestExtractUrlsFromText:
    def test_empty_text(self, ec):
        assert ec.extract_urls_from_text("") == []
        assert ec.extract_urls_from_text(None) == []

    def test_markdown_link(self, ec):
        out = ec.extract_urls_from_text("See [the page](https://example.com/foo) here.")
        assert "example.com/foo" in out

    def test_plain_url(self, ec):
        out = ec.extract_urls_from_text("visit https://example.com/bar for more")
        assert "example.com/bar" in out

    def test_bare_domain_with_path(self, ec):
        out = ec.extract_urls_from_text("Read example.com/baz for details.")
        assert any("example.com" in u for u in out)

    def test_dedupes(self, ec):
        text = "see https://example.com/foo and https://example.com/foo again"
        out = ec.extract_urls_from_text(text)
        assert out.count("example.com/foo") == 1

    def test_strips_trailing_punct(self, ec):
        out = ec.extract_urls_from_text("Source: https://example.com/foo.")
        assert "example.com/foo" in out
        assert "example.com/foo." not in out

    def test_no_double_count_markdown_plus_plain(self, ec):
        # When markdown link and plain url reference same URL, dedupe to 1
        text = "[click](https://example.com/foo) and visit https://example.com/foo too"
        out = ec.extract_urls_from_text(text)
        assert out.count("example.com/foo") == 1

    def test_skips_pure_tokens_without_dot(self, ec):
        # extract_urls_from_text drops tokens without "." in normalized form
        out = ec.extract_urls_from_text("not a url here")
        assert out == []


# Edge cases added for production hardening (subdomains, modern TLDs, multi-URL
# lines, quoted/parenthesized URLs, HTML entities, and explicitly unsupported
# forms like IDN/punycode).

class TestEdgeCases:
    def test_url_inside_parentheses(self, ec):
        # Closing ')' must not be part of the URL
        out = ec.extract_urls_from_text("see (https://example.com)")
        assert "example.com" in out
        assert not any(u.endswith(")") for u in out)

    def test_quoted_url_double_quotes(self, ec):
        out = ec.extract_urls_from_text('"https://example.com"')
        assert "example.com" in out
        assert not any('"' in u for u in out)

    def test_quoted_url_single_quotes(self, ec):
        out = ec.extract_urls_from_text("'https://example.com'")
        assert "example.com" in out

    def test_subdomain_bare_reference(self, ec):
        out = ec.extract_urls_from_text("on m.gymshark.com/page")
        assert "m.gymshark.com/page" in out

    def test_multi_url_comma_separated(self, ec):
        out = ec.extract_urls_from_text("Sources: https://a.com, https://b.com")
        assert "a.com" in out
        assert "b.com" in out
        # Must not be glued into a single concatenated URL
        assert not any("," in u for u in out)
        assert not any("a.comb.com" in u for u in out)

    def test_multi_url_semicolon_separated(self, ec):
        out = ec.extract_urls_from_text("Sources: https://a.com; https://b.com")
        assert "a.com" in out
        assert "b.com" in out

    def test_url_at_end_of_sentence(self, ec):
        out = ec.extract_urls_from_text("visit https://example.com.")
        assert "example.com" in out
        assert "example.com." not in out

    def test_modern_tld_app(self, ec):
        out = ec.extract_urls_from_text("check shopify.app/foo")
        assert "shopify.app/foo" in out

    def test_modern_tld_ai(self, ec):
        out = ec.extract_urls_from_text("see anthropic.ai/news")
        assert "anthropic.ai/news" in out

    def test_modern_tld_dev(self, ec):
        out = ec.extract_urls_from_text("repo at fly.dev/app")
        assert "fly.dev/app" in out

    def test_wikipedia_style_paren_in_path(self, ec):
        # Trade-off: _URL_RE excludes '(' and ')' from its char class so the
        # captured path stops at the underscore before the '('. We document
        # this limit and assert that extraction does not crash and returns
        # *something* reasonable (the wikipedia domain at minimum).
        text = "https://en.wikipedia.org/wiki/Foo_(bar)"
        out = ec.extract_urls_from_text(text)
        assert len(out) >= 1
        assert any("en.wikipedia.org" in u for u in out)

    def test_html_entities_in_url_no_crash(self, ec):
        # We intentionally do not decode HTML entities. The captured URL will
        # contain '&amp' (the trailing ';' before "bar=1" is excluded from the
        # URL character class). What matters is: no crash, and the domain is
        # preserved.
        out = ec.extract_urls_from_text("https://example.com/foo&amp;bar=1")
        assert len(out) >= 1
        assert any(u.startswith("example.com/foo") for u in out)

    def test_empty_string(self, ec):
        assert ec.extract_urls_from_text("") == []

    def test_whitespace_only(self, ec):
        assert ec.extract_urls_from_text("   ") == []
        assert ec.extract_urls_from_text("\n\t  \n") == []

    def test_url_without_path(self, ec):
        out = ec.extract_urls_from_text("https://example.com")
        assert out == ["example.com"]

    def test_anchor_style_bare_domain_with_path(self, ec):
        # "According to gymshark.com/leggings-guide, ..." should yield the full
        # path, not just the domain.
        out = ec.extract_urls_from_text(
            "According to gymshark.com/leggings-guide, the fabric is opaque."
        )
        assert "gymshark.com/leggings-guide" in out

    def test_idn_punycode_not_supported(self, ec):
        # Documented limit: IDN / punycode domains are not recognized by the
        # ASCII-only regex character class. xn--bcher-kva.example would need
        # IDN handling we deliberately omit. The leading "xn--" still matches
        # the bare-domain character class but ".example" is not in the TLD
        # allowlist, so this should yield no URLs.
        out = ec.extract_urls_from_text("see xn--bcher-kva.example for IDN demo")
        assert out == []

    def test_jsessionid_semicolon_not_stripped_from_middle(self, ec):
        # A semicolon mid-path (e.g., jsessionid) is excluded by the URL char
        # class — documented limit. Trailing punct stripping must not corrupt
        # the captured prefix.
        out = ec.extract_urls_from_text("link https://example.com/page;jsessionid=foo")
        assert any(u.startswith("example.com/page") for u in out)
