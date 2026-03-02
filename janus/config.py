from pydantic import BaseModel, Field
import os


class Settings(BaseModel):
    label_prefix: str = Field(default="janus.autoupdate", description="Label namespace prefix")
    default_interval: int = Field(default=300, description="Default check interval in seconds")
    stop_timeout: int = Field(default=10, description="Seconds to wait when stopping a container")
    max_concurrent_updates: int = Field(default=1, description="Max simultaneous update operations")
    log_level: str = Field(default="INFO", description="Logging level")

    @staticmethod
    def from_env() -> "Settings":
        return Settings(
            label_prefix=os.getenv("JANUS_LABEL_PREFIX", "janus.autoupdate"),
            default_interval=int(os.getenv("JANUS_DEFAULT_INTERVAL", "300")),
            stop_timeout=int(os.getenv("JANUS_STOP_TIMEOUT", "10")),
            max_concurrent_updates=int(os.getenv("JANUS_MAX_CONCURRENT_UPDATES", "1")),
            log_level=os.getenv("JANUS_LOG_LEVEL", "INFO").upper(),
        )