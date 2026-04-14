import main


def test_add_case_comi_valid():
    result = main.parse_add_case_command("add case COMI/257/2019")
    assert result == {
        "case_type": "COMI",
        "case_number": "257",
        "year": "2019",
        "normalized_case": "COMI/257/2019",
    }


def test_add_case_crl_lowercase_valid():
    result = main.parse_add_case_command("add case crl/123/2022")
    assert result == {
        "case_type": "CRL",
        "case_number": "123",
        "year": "2022",
        "normalized_case": "CRL/123/2022",
    }


def test_add_case_civil_with_extra_spaces_valid():
    result = main.parse_add_case_command("add case   CIVIL/45/2020")
    assert result == {
        "case_type": "CIVIL",
        "case_number": "45",
        "year": "2020",
        "normalized_case": "CIVIL/45/2020",
    }


def test_add_case_missing_prefix_ignored():
    result = main.parse_add_case_command("COMI/257/2019")
    assert result is None


def test_add_case_missing_case_number_prompts_user():
    result = main.parse_add_case_command("add case")
    assert result == {"error": "Please provide a case number (e.g., COMI/257/2019)"}


def test_add_case_invalid_without_case_type():
    result = main.parse_add_case_command("add case 123/2020")
    assert result == {"error": "Invalid case format. Please use format like COMI/257/2019"}


def test_add_case_invalid_compact_string():
    result = main.parse_add_case_command("add case COMI2572019")
    assert result == {"error": "Invalid case format. Please use format like COMI/257/2019"}
