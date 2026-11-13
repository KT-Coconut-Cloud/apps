from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RESULT_APP_", env_file=".env", extra="ignore")

    git_sha: str = "dev"
    session_secret: str = "change-me"
    session_idle_minutes: int = 30

    max_login_failures: int = 5
    lockout_minutes: int = 15
    accounts_file: Path = Path("accounts.dev.json")

    # local: read data_dir laid out like the clean bucket; s3: read the bucket
    data_source: Literal["local", "s3"] = "local"
    data_dir: Path = Path("sample-data")
    s3_bucket: str = ""
    s3_region: str = "ap-northeast-2"
    # one credential set per team, matching the IAM split in the spec
    results_profile: str = ""
    reports_profile: str = ""

    # local: fake Lambda that aggregates data_dir/data with pandas
    analysis_backend: Literal["local", "lambda"] = "local"
    analysis_function: str = "analysis-request"
    local_analysis_delay: float = 3.0
    min_cell_size: int = 5
    poll_seconds: int = 5

    @model_validator(mode="after")
    def check_backends(self):
        if self.data_source == "s3" and not self.s3_bucket:
            raise ValueError("RESULT_APP_S3_BUCKET is required when data_source is s3")
        if self.analysis_backend == "local" and self.data_source != "local":
            raise ValueError("the local analysis backend only works with data_source=local")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
