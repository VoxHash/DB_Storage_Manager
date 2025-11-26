"""
Redis database connection
"""

import asyncio
import subprocess
from pathlib import Path
from typing import Any, Dict, List
import redis

from .base import (
    DatabaseConnection,
    ConnectionConfig,
    StorageAnalysis,
    QueryResult,
    SchemaInfo,
)


class RedisConnection(DatabaseConnection):
    """Redis database connection"""

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.client = None

    async def connect(self) -> None:
        """Connect to Redis database"""
        if self.config.connection_string:
            self.client = redis.from_url(self.config.connection_string)
        else:
            self.client = redis.Redis(
                host=self.config.host or "localhost",
                port=self.config.port or 6379,
                db=int(self.config.database) if self.config.database else 0,
                password=self.config.password,
                decode_responses=False,
            )

        # Test connection
        self.client.ping()
        self.connected = True

    async def disconnect(self) -> None:
        """Disconnect from Redis database"""
        if self.client:
            self.client.close()
            self.client = None
        self.connected = False

    async def analyze_storage(self) -> StorageAnalysis:
        """Analyze Redis storage"""
        if not self.client:
            await self.connect()

        info = self.client.info("memory")
        total_size = info.get("used_memory", 0)

        # Get all keys
        keys = self.client.keys("*")
        key_types = {}
        key_sizes = {}

        for key in keys:
            key_type = (
                self.client.type(key).decode()
                if isinstance(self.client.type(key), bytes)
                else self.client.type(key)
            )
            key_types[key_type] = key_types.get(key_type, 0) + 1

            try:
                memory_usage = self.client.memory_usage(key)
                key_sizes[key] = memory_usage
            except Exception:
                key_sizes[key] = 0

        # Create tables from key types
        tables = []
        for key_type, count in key_types.items():
            tables.append(
                {
                    "name": f"keys:{key_type}",
                    "size": 0,
                    "rowCount": count,
                    "indexSize": 0,
                    "bloat": 0.0,
                }
            )

        # Find largest key
        largest_key = {"name": "N/A", "size": 0}
        if key_sizes:
            largest_key_name = max(key_sizes, key=key_sizes.get)
            largest_key = {
                "name": (
                    largest_key_name.decode()
                    if isinstance(largest_key_name, bytes)
                    else largest_key_name
                ),
                "size": key_sizes[largest_key_name],
            }

        return {
            "totalSize": total_size,
            "tableCount": len(tables),
            "indexCount": 0,
            "largestTable": largest_key,
            "tables": tables,
            "indexes": [],
            "lastAnalyzed": __import__("datetime").datetime.now().isoformat(),
        }

    async def execute_query(self, query: str, safe_mode: bool = True) -> QueryResult:
        """Execute a Redis command"""
        if not self.client:
            await self.connect()

        import time
        import json

        start_time = time.time()

        try:
            # Try to parse as JSON array for multi commands
            try:
                commands = json.loads(query)
                if isinstance(commands, list) and all(
                    isinstance(c, list) for c in commands
                ):
                    pipe = self.client.pipeline()
                    for cmd in commands:
                        pipe.execute_command(*cmd)
                    result = pipe.execute()
                else:
                    result = [self.client.execute_command(*commands)]
            except (json.JSONDecodeError, TypeError):
                # Parse as space-separated command
                parts = query.split()
                command = parts[0].upper()
                args = parts[1:] if len(parts) > 1 else []

                # Decode bytes arguments
                args = [arg.decode() if isinstance(arg, bytes) else arg for arg in args]

                result = self.client.execute_command(command, *args)

            # Normalize result
            if not isinstance(result, list):
                result = [result]

            # Decode bytes in result
            def decode_value(val):
                if isinstance(val, bytes):
                    try:
                        return val.decode()
                    except:
                        return val
                elif isinstance(val, list):
                    return [decode_value(v) for v in val]
                elif isinstance(val, dict):
                    return {k: decode_value(v) for k, v in val.items()}
                return val

            result = [decode_value(r) for r in result]

            execution_time = int((time.time() - start_time) * 1000)

            return {
                "columns": ["result"],
                "rows": [{"result": r} for r in result],
                "rowCount": len(result),
                "executionTime": execution_time,
                "explainPlan": None,
            }
        except Exception as e:
            raise RuntimeError(f"Query execution failed: {str(e)}")

    async def get_schema(self) -> SchemaInfo:
        """Get Redis schema"""
        if not self.client:
            await self.connect()

        keys = self.client.keys("*")
        key_types = {}

        for key in keys:
            key_type = (
                self.client.type(key).decode()
                if isinstance(self.client.type(key), bytes)
                else self.client.type(key)
            )
            key_types[key_type] = key_types.get(key_type, 0) + 1

        # Create tables from key types
        tables = []
        for key_type, count in key_types.items():
            tables.append(
                {
                    "name": f"keys:{key_type}",
                    "columns": [
                        {
                            "name": "key",
                            "type": "string",
                            "nullable": False,
                            "defaultValue": None,
                        },
                        {
                            "name": "value",
                            "type": key_type,
                            "nullable": True,
                            "defaultValue": None,
                        },
                    ],
                    "indexes": [],
                }
            )

        return {
            "schemas": [
                {
                    "name": self.config.database or "default",
                    "tables": tables,
                }
            ]
        }

    async def create_backup(self, backup_path: str) -> Dict[str, Any]:
        """Create Redis backup"""
        if not self.client:
            await self.connect()

        # Save Redis RDB file
        self.client.save()

        # Get Redis data directory and dbfilename
        config = self.client.config_get("dir")
        redis_dir = config.get("dir", "/var/lib/redis")
        dbfilename_config = self.client.config_get("dbfilename")
        dbfilename = dbfilename_config.get("dbfilename", "dump.rdb")

        rdb_path = Path(redis_dir) / dbfilename

        if not rdb_path.exists():
            raise FileNotFoundError(f"Redis RDB file not found: {rdb_path}")

        backup_file = Path(backup_path)
        backup_file.parent.mkdir(parents=True, exist_ok=True)

        # Copy RDB file
        import shutil

        shutil.copy2(rdb_path, backup_file)
        size = backup_file.stat().st_size

        return {"path": str(backup_file), "size": size}

    async def restore_backup(self, backup_path: str) -> None:
        """Restore Redis backup"""
        backup_file = Path(backup_path)
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        if not self.client:
            await self.connect()

        # Get Redis data directory and dbfilename
        config = self.client.config_get("dir")
        redis_dir = config.get("dir", "/var/lib/redis")
        dbfilename_config = self.client.config_get("dbfilename")
        dbfilename = dbfilename_config.get("dbfilename", "dump.rdb")

        rdb_path = Path(redis_dir) / dbfilename

        # Disconnect
        await self.disconnect()

        # Copy backup file to Redis data directory
        import shutil

        shutil.copy2(backup_file, rdb_path)

        # Note: Redis needs to be restarted to load the new RDB file
        # This is typically done by the system administrator or Docker container restart
