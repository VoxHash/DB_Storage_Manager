"""
Capacity planning tools
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from ..db.base import DatabaseConnection, StorageAnalysis
from .prediction import StorageGrowthPredictor


class CapacityPlanner:
    """Capacity planning and forecasting"""

    def __init__(self, connection: DatabaseConnection):
        self.connection = connection
        self.predictor = StorageGrowthPredictor(connection)

    def add_analysis(self, analysis: StorageAnalysis) -> None:
        """Add analysis for capacity planning"""
        self.predictor.add_analysis(analysis)

    def calculate_capacity_utilization(
        self, analysis: StorageAnalysis, total_capacity: int
    ) -> Dict[str, Any]:
        """Calculate current capacity utilization"""
        current_size = analysis.get("totalSize", 0)
        utilization_percent = (
            (current_size / total_capacity * 100) if total_capacity > 0 else 0
        )

        status = (
            "critical"
            if utilization_percent > 90
            else "warning" if utilization_percent > 75 else "healthy"
        )

        return {
            "currentSize": current_size,
            "totalCapacity": total_capacity,
            "availableSpace": total_capacity - current_size,
            "utilizationPercent": utilization_percent,
            "status": status,
            "timestamp": datetime.now().isoformat(),
        }

    def estimate_time_to_capacity(
        self, total_capacity: int, threshold_percent: float = 90.0
    ) -> Dict[str, Any]:
        """Estimate time until capacity threshold is reached"""
        if len(self.predictor.history) < 2:
            return {
                "estimatedDays": None,
                "estimatedDate": None,
                "confidence": "low",
                "message": "Insufficient historical data",
            }

        current_size = self.predictor.history[-1]["totalSize"]
        threshold_size = total_capacity * (threshold_percent / 100)

        if current_size >= threshold_size:
            return {
                "estimatedDays": 0,
                "estimatedDate": datetime.now().isoformat(),
                "status": "threshold_reached",
                "message": f"Already at {threshold_percent}% capacity",
            }

        # Predict growth
        prediction = self.predictor.predict_growth(days=365)
        growth_rate = prediction.get("growthRate", 0) / 100

        if growth_rate <= 0:
            return {
                "estimatedDays": None,
                "estimatedDate": None,
                "status": "no_growth",
                "message": "No growth detected, capacity threshold not expected",
            }

        # Calculate days to threshold
        remaining_space = threshold_size - current_size
        daily_growth = current_size * growth_rate
        estimated_days = (
            int(remaining_space / daily_growth) if daily_growth > 0 else None
        )

        if estimated_days:
            estimated_date = datetime.now() + timedelta(days=estimated_days)
            return {
                "estimatedDays": estimated_days,
                "estimatedDate": estimated_date.isoformat(),
                "thresholdPercent": threshold_percent,
                "thresholdSize": int(threshold_size),
                "currentSize": current_size,
                "growthRate": growth_rate * 100,
                "confidence": prediction.get("confidence", "low"),
            }
        else:
            return {
                "estimatedDays": None,
                "estimatedDate": None,
                "status": "unable_to_calculate",
            }

    def get_capacity_recommendations(
        self, analysis: StorageAnalysis, total_capacity: int
    ) -> List[Dict[str, Any]]:
        """Get capacity planning recommendations"""
        recommendations = []
        utilization = self.calculate_capacity_utilization(analysis, total_capacity)

        if utilization["utilizationPercent"] > 90:
            recommendations.append(
                {
                    "type": "urgent",
                    "severity": "critical",
                    "message": "Database is at critical capacity (>90%)",
                    "recommendation": "Immediate action required: Consider archiving old data or increasing capacity",
                }
            )
        elif utilization["utilizationPercent"] > 75:
            recommendations.append(
                {
                    "type": "warning",
                    "severity": "high",
                    "message": "Database is approaching capacity (>75%)",
                    "recommendation": "Plan for capacity increase or data archiving in the near future",
                }
            )

        # Check growth trends
        trends = self.predictor.get_growth_trends()
        if trends.get("trend") == "rapid_growth":
            recommendations.append(
                {
                    "type": "growth_alert",
                    "severity": "medium",
                    "message": "Rapid growth detected",
                    "recommendation": "Monitor growth closely and plan capacity expansion",
                }
            )

        # Time to capacity estimate
        time_estimate = self.estimate_time_to_capacity(total_capacity)
        if time_estimate.get("estimatedDays") and time_estimate["estimatedDays"] < 90:
            recommendations.append(
                {
                    "type": "capacity_forecast",
                    "severity": "high",
                    "message": f"Capacity threshold may be reached in {time_estimate['estimatedDays']} days",
                    "recommendation": "Plan capacity increase or data management strategy",
                }
            )

        return recommendations

    def generate_capacity_report(
        self, analysis: StorageAnalysis, total_capacity: int
    ) -> Dict[str, Any]:
        """Generate comprehensive capacity planning report"""
        utilization = self.calculate_capacity_utilization(analysis, total_capacity)
        trends = self.predictor.get_growth_trends()
        time_estimate = self.estimate_time_to_capacity(total_capacity)
        recommendations = self.get_capacity_recommendations(analysis, total_capacity)

        # Predictions for different timeframes
        predictions = {
            "30days": self.predictor.predict_growth(30),
            "90days": self.predictor.predict_growth(90),
            "365days": self.predictor.predict_growth(365),
        }

        return {
            "currentState": utilization,
            "growthTrends": trends,
            "timeToCapacity": time_estimate,
            "predictions": predictions,
            "recommendations": recommendations,
            "reportDate": datetime.now().isoformat(),
        }
