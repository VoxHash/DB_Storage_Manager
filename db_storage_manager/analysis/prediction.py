"""
Storage growth predictions
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import statistics
from ..db.base import DatabaseConnection, StorageAnalysis


class StorageGrowthPredictor:
    """Predict storage growth based on historical data"""

    def __init__(self, connection: DatabaseConnection):
        self.connection = connection
        self.history: List[Dict[str, Any]] = []

    def add_analysis(self, analysis: StorageAnalysis) -> None:
        """Add analysis data point to history"""
        self.history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "totalSize": analysis.get("totalSize", 0),
                "tableCount": analysis.get("tableCount", 0),
                "analysis": analysis,
            }
        )

    def predict_growth(self, days: int = 30) -> Dict[str, Any]:
        """Predict storage growth for the next N days"""
        if len(self.history) < 2:
            return {
                "predictedSize": 0,
                "growthRate": 0,
                "confidence": "low",
                "message": "Insufficient historical data for prediction",
            }

        # Calculate growth rate
        sizes = [h["totalSize"] for h in self.history]
        growth_rates = []

        for i in range(1, len(sizes)):
            if sizes[i - 1] > 0:
                rate = (sizes[i] - sizes[i - 1]) / sizes[i - 1]
                growth_rates.append(rate)

        if not growth_rates:
            return {
                "predictedSize": sizes[-1] if sizes else 0,
                "growthRate": 0,
                "confidence": "low",
                "message": "No growth detected",
            }

        avg_growth_rate = statistics.mean(growth_rates)
        current_size = sizes[-1]

        # Predict future size
        predicted_size = current_size * (1 + avg_growth_rate) ** days

        # Calculate confidence based on data points
        confidence = (
            "high"
            if len(self.history) >= 10
            else "medium" if len(self.history) >= 5 else "low"
        )

        return {
            "predictedSize": int(predicted_size),
            "currentSize": current_size,
            "growthRate": avg_growth_rate * 100,  # Percentage
            "growthAmount": int(predicted_size - current_size),
            "days": days,
            "confidence": confidence,
            "predictedDate": (datetime.now() + timedelta(days=days)).isoformat(),
        }

    def predict_table_growth(self, table_name: str, days: int = 30) -> Dict[str, Any]:
        """Predict growth for a specific table"""
        table_history = []

        for h in self.history:
            analysis = h.get("analysis", {})
            for table in analysis.get("tables", []):
                if table.get("name") == table_name:
                    table_history.append(
                        {
                            "timestamp": h["timestamp"],
                            "size": table.get("size", 0),
                            "rowCount": table.get("rowCount", 0),
                        }
                    )

        if len(table_history) < 2:
            return {
                "predictedSize": 0,
                "growthRate": 0,
                "confidence": "low",
                "message": f"Insufficient data for table {table_name}",
            }

        sizes = [h["size"] for h in table_history]
        growth_rates = []

        for i in range(1, len(sizes)):
            if sizes[i - 1] > 0:
                rate = (sizes[i] - sizes[i - 1]) / sizes[i - 1]
                growth_rates.append(rate)

        if not growth_rates:
            return {
                "predictedSize": sizes[-1] if sizes else 0,
                "growthRate": 0,
                "confidence": "low",
            }

        avg_growth_rate = statistics.mean(growth_rates)
        current_size = sizes[-1]
        predicted_size = current_size * (1 + avg_growth_rate) ** days

        return {
            "tableName": table_name,
            "predictedSize": int(predicted_size),
            "currentSize": current_size,
            "growthRate": avg_growth_rate * 100,
            "growthAmount": int(predicted_size - current_size),
            "days": days,
            "confidence": "high" if len(table_history) >= 10 else "medium",
        }

    def get_growth_trends(self) -> Dict[str, Any]:
        """Get overall growth trends"""
        if len(self.history) < 2:
            return {
                "trend": "insufficient_data",
                "message": "Need at least 2 data points",
            }

        sizes = [h["totalSize"] for h in self.history]
        growth_rates = []

        for i in range(1, len(sizes)):
            if sizes[i - 1] > 0:
                rate = (sizes[i] - sizes[i - 1]) / sizes[i - 1]
                growth_rates.append(rate)

        if not growth_rates:
            return {"trend": "stable", "growthRate": 0}

        avg_rate = statistics.mean(growth_rates)

        if avg_rate > 0.1:
            trend = "rapid_growth"
        elif avg_rate > 0.01:
            trend = "moderate_growth"
        elif avg_rate > 0:
            trend = "slow_growth"
        elif avg_rate == 0:
            trend = "stable"
        else:
            trend = "declining"

        return {
            "trend": trend,
            "growthRate": avg_rate * 100,
            "dataPoints": len(self.history),
            "totalGrowth": sizes[-1] - sizes[0] if sizes else 0,
        }
