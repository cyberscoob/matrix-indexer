"""
Configuration management for Matrix Indexer.
"""
from pathlib import Path
from pydantic import BaseModel, Field
import json
import os


class MongoConfig(BaseModel):
    """MongoDB configuration."""
    uri: str = Field(default="mongodb://localhost:27017", description="MongoDB connection URI")
    db: str = Field(default="matrix_index", description="Database name")
    events_collection: str = Field(default="events", description="Events collection name")
    rooms_collection: str = Field(default="rooms", description="Rooms collection name")
    users_collection: str = Field(default="users", description="Users collection name")


class MatrixConfig(BaseModel):
    """Matrix server configuration."""
    homeserver: str = Field(default="https://cclub.cs.wmich.edu", description="Matrix homeserver URL")
    user_id: str = Field(default="@scooby:cclub.cs.wmich.edu", description="Bot user ID")
    password: str = Field(default="", description="Bot password")
    access_token: str = Field(default="", description="Bot access token (if not using password)")
    device_id: str = Field(default="INDEXER", description="Device ID for this indexer")
    device_name: str = Field(default="Matrix Indexer", description="Device name")


class IndexerConfig(BaseModel):
    """Main indexer configuration."""
    matrix: MatrixConfig = Field(default_factory=MatrixConfig, description="Matrix config")
    mongo: MongoConfig = Field(default_factory=MongoConfig, description="MongoDB config")
    log_level: str = Field(default="INFO", description="Logging level")
    sync_timeout_ms: int = Field(default=30000, description="Sync timeout in milliseconds")
    backfill_batch_size: int = Field(default=100, description="Historical events batch size")
    cache_size: int = Field(default=10000, description="In-memory event cache size")
    state_file: Path = Field(default_factory=lambda: Path.home() / ".matrix-indexer" / "state.json", description="State file path")

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def from_file(cls, path: Path) -> "IndexerConfig":
        """Load config from JSON file."""
        if path.exists():
            data = json.loads(path.read_text())
            return cls(**data)
        return cls()

    def to_file(self, path: Path) -> None:
        """Save config to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.json(indent=2))

    @classmethod
    def from_env(cls) -> "IndexerConfig":
        """Load config from environment variables."""
        config = cls()
        
        # Matrix config
        if "MATRIX_HOMESERVER" in os.environ:
            config.matrix.homeserver = os.environ["MATRIX_HOMESERVER"]
        if "MATRIX_USER_ID" in os.environ:
            config.matrix.user_id = os.environ["MATRIX_USER_ID"]
        if "MATRIX_PASSWORD" in os.environ:
            config.matrix.password = os.environ["MATRIX_PASSWORD"]
        if "MATRIX_TOKEN" in os.environ:
            config.matrix.access_token = os.environ["MATRIX_TOKEN"]
        
        # MongoDB config
        if "MONGO_URI" in os.environ:
            config.mongo.uri = os.environ["MONGO_URI"]
        if "MONGO_DB" in os.environ:
            config.mongo.db = os.environ["MONGO_DB"]
        
        # Indexer config
        if "LOG_LEVEL" in os.environ:
            config.log_level = os.environ["LOG_LEVEL"]
        
        return config
