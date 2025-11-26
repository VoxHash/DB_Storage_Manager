"""
MongoDB database connection
"""

import asyncio
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

from .base import (
    DatabaseConnection,
    ConnectionConfig,
    StorageAnalysis,
    QueryResult,
    SchemaInfo,
)


class MongoDBConnection(DatabaseConnection):
    """MongoDB database connection"""

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.client = None
        self.db = None

    async def connect(self) -> None:
        """Connect to MongoDB database"""
        if self.config.connection_string:
            self.client = MongoClient(self.config.connection_string)
        else:
            connection_uri = f"mongodb://{self.config.username}:{self.config.password}@{self.config.host or 'localhost'}:{self.config.port or 27017}/{self.config.database}"
            self.client = MongoClient(connection_uri)

        # Test connection
        self.client.admin.command("ping")
        self.db = self.client[self.config.database or "admin"]
        self.connected = True

    async def disconnect(self) -> None:
        """Disconnect from MongoDB database"""
        if self.client:
            self.client.close()
            self.client = None
            self.db = None
        self.connected = False

    async def analyze_storage(self) -> StorageAnalysis:
        """Analyze MongoDB storage"""
        if not self.db:
            await self.connect()

        collections = self.db.list_collection_names()
        tables = []
        total_size = 0

        for collection_name in collections:
            collection = self.db[collection_name]
            stats = self.db.command("collStats", collection_name)

            table_size = stats.get("size", 0)
            index_size = stats.get("totalIndexSize", 0)
            row_count = stats.get("count", 0)

            tables.append(
                {
                    "name": collection_name,
                    "size": table_size,
                    "rowCount": row_count,
                    "indexSize": index_size,
                    "bloat": 0.0,
                }
            )
            total_size += table_size + index_size

        # Sort by size
        tables.sort(key=lambda x: x["size"], reverse=True)

        # Get indexes
        indexes = []
        for collection_name in collections:
            collection = self.db[collection_name]
            index_list = collection.list_indexes()

            for index in index_list:
                indexes.append(
                    {
                        "name": index.get("name", "unnamed"),
                        "tableName": collection_name,
                        "size": 0,
                        "bloat": 0.0,
                    }
                )

        largest_table = (
            tables[0] if tables else {"name": "N/A", "size": 0, "rowCount": 0}
        )

        return {
            "totalSize": total_size,
            "tableCount": len(tables),
            "indexCount": len(indexes),
            "largestTable": largest_table,
            "tables": tables,
            "indexes": indexes,
            "lastAnalyzed": __import__("datetime").datetime.now().isoformat(),
        }

    async def execute_query(self, query: str, safe_mode: bool = True) -> QueryResult:
        """Execute a MongoDB query"""
        if not self.db:
            await self.connect()

        import time
        import json

        start_time = time.time()

        try:
            # Parse query as JSON
            query_dict = json.loads(query)
            collection_name = query_dict.get("collection", "default")
            collection = self.db[collection_name]

            if "find" in query_dict:
                result = list(collection.find(query_dict["find"]))
            elif "aggregate" in query_dict:
                result = list(collection.aggregate(query_dict["aggregate"]))
            else:
                # Fallback to direct command
                result = [self.db.command(query_dict)]

            columns = list(result[0].keys()) if result else []
            rows = [dict(item) for item in result]

            execution_time = int((time.time() - start_time) * 1000)

            return {
                "columns": columns,
                "rows": rows,
                "rowCount": len(rows),
                "executionTime": execution_time,
                "explainPlan": None,
            }
        except json.JSONDecodeError:
            # If not JSON, try as direct command
            try:
                result = [self.db.command(query)]
                columns = list(result[0].keys()) if result else []
                rows = [dict(item) for item in result]

                execution_time = int((time.time() - start_time) * 1000)

                return {
                    "columns": columns,
                    "rows": rows,
                    "rowCount": len(rows),
                    "executionTime": execution_time,
                    "explainPlan": None,
                }
            except Exception as e:
                raise RuntimeError(f"Query execution failed: {str(e)}")

    async def get_schema(self) -> SchemaInfo:
        """Get MongoDB schema"""
        if not self.db:
            await self.connect()

        collections = self.db.list_collection_names()
        tables = []

        for collection_name in collections:
            collection = self.db[collection_name]

            # Get sample document to infer schema
            sample_doc = collection.find_one()
            columns = []
            if sample_doc:
                for key, value in sample_doc.items():
                    columns.append(
                        {
                            "name": key,
                            "type": type(value).__name__,
                            "nullable": True,
                            "defaultValue": None,
                        }
                    )

            # Get indexes
            index_list = collection.list_indexes()
            indexes = []
            for index in index_list:
                indexes.append(
                    {
                        "name": index.get("name", "unnamed"),
                        "columns": list(index.get("key", {}).keys()),
                        "unique": index.get("unique", False),
                    }
                )

            tables.append(
                {
                    "name": collection_name,
                    "columns": columns,
                    "indexes": indexes,
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
        """Create MongoDB backup using mongodump"""
        if not self.db:
            await self.connect()

        backup_file = Path(backup_path)
        backup_file.parent.mkdir(parents=True, exist_ok=True)

        # Create temporary directory for dump
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Build mongodump command
            cmd = [
                "mongodump",
                "--host",
                f"{self.config.host or 'localhost'}:{self.config.port or 27017}",
                "--db",
                self.config.database,
                "--username",
                self.config.username,
                "--password",
                self.config.password,
                "--authenticationDatabase",
                "admin",
                "--out",
                str(temp_path),
            ]

            # Run mongodump
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise RuntimeError(f"mongodump failed: {stderr.decode()}")

            # Compress dump directory
            with tarfile.open(backup_file, "w:gz") as tar:
                tar.add(temp_path, arcname=".")

        size = backup_file.stat().st_size
        return {"path": str(backup_file), "size": size}

    async def restore_backup(self, backup_path: str) -> None:
        """Restore MongoDB backup using mongorestore"""
        if not self.db:
            await self.connect()

        backup_file = Path(backup_path)
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        # Create temporary directory for extraction
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Extract backup
            with tarfile.open(backup_file, "r:gz") as tar:
                tar.extractall(temp_path)

            # Build mongorestore command
            cmd = [
                "mongorestore",
                "--host",
                f"{self.config.host or 'localhost'}:{self.config.port or 27017}",
                "--db",
                self.config.database,
                "--username",
                self.config.username,
                "--password",
                self.config.password,
                "--authenticationDatabase",
                "admin",
                str(temp_path),
            ]

            # Run mongorestore
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise RuntimeError(f"mongorestore failed: {stderr.decode()}")
