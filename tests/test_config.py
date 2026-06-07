import pytest
from pydantic import ValidationError
from ozbargain.config import Settings

def test_settings_default_values():
    # settings singleton loads from .env, let's verify fields are populated
    from ozbargain.config import settings
    assert settings.min_heat_score >= 0
    assert settings.poll_interval > 0
    assert settings.ozbargain_db_path is not None

def test_settings_validation_localhost_cdp():
    # valid localhost / 127.0.0.1 url should pass
    config = Settings(CHROME_CDP_URL="http://127.0.0.1:9222")
    assert config.chrome_cdp_url == "http://127.0.0.1:9222"

    config2 = Settings(CHROME_CDP_URL="http://localhost:9222")
    assert config2.chrome_cdp_url == "http://localhost:9222"

def test_settings_validation_invalid_cdp_raises():
    # invalid external url should raise ValidationError
    with pytest.raises(ValidationError) as exc_info:
        Settings(CHROME_CDP_URL="http://external-host.com:9222")
    assert "CDP URL must bind to localhost/127.0.0.1" in str(exc_info.value)
