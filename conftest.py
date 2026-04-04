import pytest

from cause_list_fetcher import get_sample_cause_list_entries


@pytest.fixture
def entries():
    return get_sample_cause_list_entries()
