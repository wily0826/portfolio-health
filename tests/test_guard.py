from app.services.guard import BANNED, find_violations, is_clean


def test_clean_text_returns_empty():
    text = "此投資組合的產業集中度偏高，年化波動度約 25%，可自行檢視分散程度。"
    assert find_violations(text) == []
    assert is_clean(text)


def test_each_banned_word_detected():
    for w in BANNED:
        assert w in find_violations(f"報告內容提到{w}這個詞")


def test_negation_still_flagged():
    # 刻意的保守設計：否定句也會被擋，走重試 / 備援
    assert "買進" in find_violations("本報告不建議買進任何股票")


def test_multiple_violations():
    v = find_violations("建議買進並設定目標價，必漲")
    assert set(v) == {"買進", "目標價", "必漲"}
