from polybot.discovery.validation import validate_resolution_rules


def test_valid_chainlink_market_passes() -> None:
    description = (
        "This market will resolve to 'Up' if the price of BTC/USD reported by "
        "Chainlink at 12:05:00 ET is higher than or equal to the price at "
        "12:00:00 ET. Otherwise it resolves to 'Down'."
    )
    rules = validate_resolution_rules(
        description, "Chainlink BTC/USD Data Streams", expected_start_ts=0, expected_end_ts=300
    )
    assert rules.valid
    assert rules.references_chainlink
    assert rules.up_wins_on_equal
    assert not rules.problems


def test_missing_chainlink_reference_fails() -> None:
    description = "This market resolves Up if the price is higher than or equal to the open."
    rules = validate_resolution_rules(description, "", expected_start_ts=0, expected_end_ts=300)
    assert not rules.valid
    assert not rules.references_chainlink
    assert any("Chainlink" in p for p in rules.problems)


def test_down_on_equal_tie_rule_is_flagged_non_standard() -> None:
    description = (
        "Resolves 'Down' if the Chainlink price at close is equal to or lower "
        "than the open. Otherwise resolves 'Up'. Window: 12:00:00 ET - 12:05:00 ET."
    )
    rules = validate_resolution_rules(
        description, "Chainlink", expected_start_ts=0, expected_end_ts=300
    )
    assert not rules.up_wins_on_equal
    assert not rules.valid
    assert any("non-standard" in p for p in rules.problems)


def test_wrong_interval_length_fails() -> None:
    description = (
        "Resolves Up if Chainlink price is higher than or equal to open. "
        "Window 12:00:00 ET - 12:15:00 ET."
    )
    rules = validate_resolution_rules(
        description, "Chainlink", expected_start_ts=0, expected_end_ts=900
    )
    assert not rules.valid
    assert any("900s" in p or "interval is" in p for p in rules.problems)


def test_never_assumes_validity_without_checking_each_market() -> None:
    """Two markets with subtly different rule text must be validated independently."""
    good = "Resolves Up if Chainlink price >= open. Window 12:00:00 ET - 12:05:00 ET."
    bad = "Resolves Up if Binance price >= open. Window 12:00:00 ET - 12:05:00 ET."
    good_rules = validate_resolution_rules(good, "Chainlink", 0, 300)
    bad_rules = validate_resolution_rules(bad, "Binance", 0, 300)
    assert good_rules.valid
    assert not bad_rules.valid
