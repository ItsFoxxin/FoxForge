from foxforge.denkit import TOKENS, css
from foxforge.review_artifacts import render_html


TASK = {"id": "task-1", "repository": "owner/project", "issue_number": 12, "base_sha": "a" * 40}
PLAN = {
    "summary": "Review <the> change & its boundaries.",
    "acceptance_criteria": ["The result remains safe."],
    "assumptions": [],
    "unknowns": ["Whether <script>alert(1)</script> is escaped."],
    "subtasks": [{"id": "review", "title": "Review", "description": "Inspect the candidate.",
                  "capability": "code.review", "depends_on": []}],
}


def test_denkit_has_the_complete_v01_palette():
    assert TOKENS == {
        "midnight": "#0B1423", "slate": "#25384B", "mint": "#97E7CA",
        "coral": "#F68D91", "amber": "#F5AD66", "cream": "#F7F5E9",
        "raised": "#142335", "border": "#36495D", "muted": "#AFC0D1",
        "critical": "#EF5261",
    }
    stylesheet = css()
    assert all(value in stylesheet for value in TOKENS.values())
    assert "prefers-reduced-motion" in stylesheet and ":focus-visible" in stylesheet


def test_primary_denkit_color_pairs_meet_wcag_aa_contrast():
    def luminance(value: str) -> float:
        channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        channels = [channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4
                    for channel in channels]
        return .2126 * channels[0] + .7152 * channels[1] + .0722 * channels[2]

    def ratio(foreground: str, background: str) -> float:
        lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
        return (lighter + .05) / (darker + .05)

    pairs = [
        (TOKENS["cream"], TOKENS["midnight"]),
        (TOKENS["cream"], TOKENS["raised"]),
        (TOKENS["cream"], TOKENS["slate"]),
        (TOKENS["muted"], TOKENS["raised"]),
        (TOKENS["midnight"], TOKENS["coral"]),
        (TOKENS["midnight"], TOKENS["mint"]),
        (TOKENS["midnight"], TOKENS["amber"]),
    ]
    assert all(ratio(foreground, background) >= 4.5 for foreground, background in pairs)


def test_html_review_is_portable_accessible_and_escapes_plan_content():
    document = render_html(TASK, PLAN, {"configured_model": 'model"><script>x</script>', "routed_via": None})
    assert "Awaiting human review" in document
    assert "authorizes no implementation" in document
    assert "Content-Security-Policy" in document
    assert "https://" not in document and "<script" not in document
    assert "Review &lt;the&gt; change &amp; its boundaries." in document
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in document
    assert 'model&quot;&gt;&lt;script&gt;x&lt;/script&gt;' in document
