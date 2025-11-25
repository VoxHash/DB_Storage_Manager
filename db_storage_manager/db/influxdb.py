"""
InfluxDB database connection
"""

import asyncio
from typing import Any, Dict, List
try:
    from influxdb_client import InfluxDBClient, Point
    from influxdb_client.client.write_api import SYNCHRONOUS
except ImportError:
    InfluxDBClient = None

from .base import (
    DatabaseConnection,
    ConnectionConfig,
    StorageAnalysis,
    QueryResult,
    SchemaInfo,
)


class InfluxDBConnection(DatabaseConnection):
    """InfluxDB database connection"""

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.client = None
        self.write_api = None
        self.query_api = None
        if InfluxDBClient is None:
            raise ImportError("influxdb-client is required for InfluxDB support. Install it with: pip install influxdb-client")

    async def connect(self) -> None:
        """Connect to InfluxDB database"""
        url = f"http://{self.config.host or 'localhost'}:{self.config.port or 8086}"
        token = self.config.password or self.config.extra.get("token", "") if self.config.extra else ""
        org = self.config.extra.get("org", "my-org") if self.config.extra else "my-org"
        
        self.client = InfluxDBClient(
            url=url,
            token=token,
            org=org
        )
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.query_api = self.client.query_api()
        self.connected = True

    async def disconnect(self) -> None:
        """Disconnect from InfluxDB database"""
        if self.client:
            self.client.close()
            self.client = None
            self.write_api = None
            self.query_api = None
        self.connected = False

    async def analyze_storage(self) -> StorageAnalysis:
        """Analyze InfluxDB storage"""
        if not self.client:
            await self.connect()

        # Get bucket sizes (InfluxDB 2.x)
        query = f'''
        from(bucket: "{self.config.database}")
            |> range(start: -30d)
            |> group()
            |> count()
        '''
        
        result = self.query_api.query(query)
        
        tables = []
        total_size = 0
        row_count = 0
        
        # Get measurements (tables)
        query_measurements = f'''
        import "influxdata/influxdb/schema"
        schema.measurements(bucket: "{self.config.database}")
        '''
        
        measurements_result = self.query_api.query(query_measurements)
        measurements = []
        for table in measurements_result:
            for record in table.records:
                measurements.append(record.get_value())
        
        for measurement in measurements:
            # Get size estimate for each measurement
            query_size = f'''
            from(bucket: "{self.config.database}")
                |> range(start: -30d)
                |> filter(fn: (r) => r["_measurement"] == "{measurement}")
                |> group()
                |> count()
            '''
            size_result = self.query_api.query(query_size)
            size = 0
            count = 0
            for table in size_result:
                for record in table.records:
                    count = record.get_value()
                    size = count * 100  # Estimate: ~100 bytes per record
            
            tables.append({
                "name": measurement,
                "size": size,
                "rowCount": count,
                "indexSize": 0,
                "bloat": 0.0,
            })
            total_size += size
            row_count += count

        largest_table = max(tables, key=lambda t: t["size"]) if tables else {
            "name": "", "size": 0, "rowCount": 0, "indexSize": 0, "bloat": 0.0
        }

        return {
            "totalSize": total_size,
            "tableCount": len(tables),
            "indexCount": 0,
            "largestTable": largest_table,
            "tables": tables,
            "indexes": [],
        }

    async def execute_query(self, query: str, safe_mode: bool = True) -> QueryResult:
        """Execute query on InfluxDB database"""
        if not self.client:
            await self.connect()

        # InfluxDB uses Flux language, not SQL
        result = self.query_api.query(query)
        
        columns = []
        rows = []
        
        for table in result:
            if not columns:
                columns = [col for col in table.columns.keys()]
            
            for record in table.records:
                row = {}
                for col in columns:
                    row[col] = record.get_value_by_key(col)
                rows.append(row)
        
        return {
            "columns": columns if columns else ["_time", "_value"],
            "rows": rows,
            "rowCount": len(rows),
        }

    async def get_schema(self) -> SchemaInfo:
        """Get InfluxDB database schema"""
        if not self.client:
            await self.connect()

        # Get measurements (tables)
        query = f'''
        import "influxdata/influxdb/schema"
        schema.measurements(bucket: "{self.config.database}")
        '''
        
        result = self.query_api.query(query)
        tables = []
        for table in result:
            for record in table.records:
                tables.append(record.get_value())

        return {
            "tables": tables,
            "views": [],
            "procedures": [],
        }

    async def test_connection(self) -> bool:
        """Test InfluxDB connection"""
        try:
            await self.connect()
            # Test query
            query = f'from(bucket: "{self.config.database}") |> range(start: -1h) |> limit(n: 1)'
            self.query_api.query(query)
            await self.disconnect()
            return True
        except Exception:
            return False

    async def create_backup(self, backup_path: str) -> str:
        """Create InfluxDB backup"""
        if not self.client:
            await self.connect()

        # Export all data from bucket
        backup_file = f"{backup_path}.csv"
        
        query = f'''
        from(bucket: "{self.config.database}")
            |> range(start: -365d)
            |> to(bucket: "backup-{self.config.database}", org: "{self.config.extra.get('org', 'my-org') if self.config.extra else 'my-org'}")
        '''
        
        # For file backup, we'll export to CSV
        query_export = f'''
        from(bucket: "{self.config.database}")
            |> range(start: -365d)
        '''
        
        result = self.query_api.query_csv(query_export)
        
        with open(backup_file, 'w') as f:
            for line in result:
                f.write(line)
        
        return backup_file

    async def restore_backup(self, backup_path: str) -> None:
        """Restore InfluxDB backup"""
        if not self.client:
            await self.connect()

        # Read CSV and write back to InfluxDB
        import csv
        
        with open(backup_path, 'r') as f:
            reader = csv.DictReader(f)
            points = []
            for row in reader:
                point = Point(row.get("_measurement", "data"))
                for key, value in row.items():
                    if key not in ["_measurement", "_time"]:
                        try:
                            point.field(key, float(value))
                        except ValueError:
                            point.field(key, value)
                points.append(point)
            
            self.write_api.write(
                bucket=self.config.database,
                record=points
            )

