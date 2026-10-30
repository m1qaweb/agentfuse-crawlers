import pytest
from scripts.download_zyte import download_job


@pytest.mark.parametrize('bad', ['https://evil.test', '../../secret', 'not-an-id', '883514/1/9?x=1'])
def test_job_id_allowlist_blocks_arbitrary_urls(bad, tmp_path):
    with pytest.raises(ValueError, match='job-id'):
        download_job(bad, tmp_path, api_key='placeholder')


def test_missing_api_key_is_explicit(tmp_path, monkeypatch):
    monkeypatch.delenv('ZYTE_SCRAPY_CLOUD_API_KEY', raising=False)
    with pytest.raises(ValueError, match='ZYTE_SCRAPY_CLOUD_API_KEY'):
        download_job('883514/1/9', tmp_path)
