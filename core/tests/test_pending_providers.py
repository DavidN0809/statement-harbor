import pytest

from paperpull_core.pending_providers import PROVIDERS, UnverifiedProvider


@pytest.mark.parametrize("adapter", PROVIDERS, ids=lambda row: row.slug)
def test_unverified_adapter_never_touches_page_or_downloads(adapter, tmp_path):
    class NoInteraction:
        def __getattr__(self, name):
            pytest.fail("unverified provider attempted page interaction")
    page = NoInteraction()
    assert not adapter.enabled
    assert adapter.verification == "UNVERIFIED"
    assert adapter.authenticated_status(page) == "PAUSED"
    for call in (lambda: adapter.navigate_documents(page), lambda: adapter.discover(page),
                 lambda: adapter.accounts(page), lambda: adapter.download(page, None, tmp_path / "doc.pdf")):
        with pytest.raises(UnverifiedProvider):
            call()
    assert not adapter.safe_url("https://memberaccess.ncsecu.org.evil.example/")
    assert not adapter.safe_url("http://memberaccess.ncsecu.org/")
    assert not list(tmp_path.iterdir())
