"""
Example demonstrating how to integrate performance optimizations into the studyplan app.

This example shows how to use the PerformanceCacheService, PerformanceProfiler,
and PerformanceMiddleware to optimize various components of the studyplan application.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from studyplan.performance_integration import (
    initialize_performance_services,
    cache_result,
    profile_operation,
    optimize_function,
    get_performance_cache,
    get_performance_profiler,
    get_performance_stats,
    clear_performance_cache,
    reset_performance_profiler
)
from studyplan.components.performance.caching import PerformanceCacheService
from studyplan.components.performance.profiler import PerformanceProfiler

logger = logging.getLogger(__name__)


class ExampleTutorService:
    """Example tutor service demonstrating performance optimizations."""
    
    def __init__(self):
        self.cache_service = get_performance_cache()
        self.profiler = get_performance_profiler()
    
    @profile_operation("tutor_get_recommendations")
    def get_recommendations(self, user_id: str, topic: str) -> List[Dict[str, Any]]:
        """Get personalized recommendations for a user and topic."""
        # Simulate expensive computation
        time.sleep(0.1)
        
        recommendations = [
            {"type": "practice", "topic": topic, "difficulty": "medium"},
            {"type": "review", "topic": topic, "difficulty": "easy"},
            {"type": "challenge", "topic": topic, "difficulty": "hard"}
        ]
        
        logger.info(f"Generated {len(recommendations)} recommendations for user {user_id}")
        return recommendations
    
    @cache_result("cognitive_state_", ttl_minutes=10)
    def get_cognitive_state(self, user_id: str, topic: str) -> Dict[str, Any]:
        """Get the cognitive state for a user and topic."""
        # Simulate expensive cognitive state calculation
        time.sleep(0.05)
        
        state = {
            "user_id": user_id,
            "topic": topic,
            "confidence": 0.75,
            "mastery": 0.6,
            "last_practice": "2024-01-01",
            "weak_areas": ["concept_a", "concept_b"]
        }
        
        logger.info(f"Calculated cognitive state for user {user_id}")
        return state
    
    @optimize_function("hint_strategy_", ttl_minutes=5, operation_name="generate_hint_strategy")
    def generate_hint_strategy(self, user_id: str, topic: str, difficulty: str) -> Dict[str, Any]:
        """Generate a hint strategy for a user and topic."""
        # Simulate expensive hint strategy generation
        time.sleep(0.08)
        
        strategy = {
            "user_id": user_id,
            "topic": topic,
            "difficulty": difficulty,
            "hints": [
                {"type": "scaffold", "content": "Start with the basic concept"},
                {"type": "example", "content": "Look at a similar example"},
                {"type": "check", "content": "Verify your answer"}
            ],
            "strategy_type": "adaptive"
        }
        
        logger.info(f"Generated hint strategy for user {user_id}")
        return strategy


class ExampleUIRenderer:
    """Example UI renderer demonstrating performance optimizations."""
    
    def __init__(self):
        self.cache_service = get_performance_cache()
        self.profiler = get_performance_profiler()
    
    @cache_result("ui_render_", ttl_minutes=2)
    def render_practice_widget(self, widget_id: str, data: Dict[str, Any]) -> str:
        """Render a practice widget."""
        # Simulate expensive UI rendering
        time.sleep(0.03)
        
        html = f"""
        <div class="practice-widget" id="{widget_id}">
            <h3>Practice: {data.get('topic', 'Unknown')}</h3>
            <p>Difficulty: {data.get('difficulty', 'Unknown')}</p>
            <button onclick="startPractice()">Start Practice</button>
        </div>
        """
        
        logger.info(f"Rendered practice widget {widget_id}")
        return html
    
    @profile_operation("ui_render_dashboard")
    def render_dashboard(self, user_id: str, widgets: List[str]) -> str:
        """Render the main dashboard."""
        # Simulate expensive dashboard rendering
        time.sleep(0.15)
        
        dashboard_html = f"""
        <div class="dashboard" data-user="{user_id}">
            <h1>Welcome back, User {user_id}!</h1>
            <div class="widgets">
                {''.join(f'<div class="widget">{widget}</div>' for widget in widgets)}
            </div>
        </div>
        """
        
        logger.info(f"Rendered dashboard for user {user_id}")
        return dashboard_html


class ExampleDataProcessor:
    """Example data processor demonstrating performance optimizations."""
    
    def __init__(self):
        self.cache_service = get_performance_cache()
        self.profiler = get_performance_profiler()
    
    @cache_result("data_processing_", ttl_minutes=15)
    def process_user_data(self, user_id: str, raw_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Process raw user data into insights."""
        # Simulate expensive data processing
        time.sleep(0.12)
        
        insights = {
            "user_id": user_id,
            "total_practices": len(raw_data),
            "avg_score": sum(item.get("score", 0) for item in raw_data) / len(raw_data) if raw_data else 0,
            "improvement_trend": "positive",
            "recommendations": ["practice_more", "review_weak_areas"]
        }
        
        logger.info(f"Processed data for user {user_id}")
        return insights
    
    @profile_operation("data_aggregation")
    def aggregate_data(self, user_ids: List[str]) -> Dict[str, Any]:
        """Aggregate data across multiple users."""
        # Simulate expensive data aggregation
        time.sleep(0.2)
        
        aggregated = {
            "total_users": len(user_ids),
            "avg_practices_per_user": 15.5,
            "system_wide_improvement": 0.12,
            "top_topics": ["math", "science", "english"]
        }
        
        logger.info(f"Aggregated data for {len(user_ids)} users")
        return aggregated


def demonstrate_performance_optimizations():
    """Demonstrate the performance optimizations in action."""
    
    print("=== Performance Optimization Demonstration ===\n")
    
    # Initialize performance services
    print("1. Initializing performance services...")
    initialize_performance_services()
    
    # Create example services
    tutor_service = ExampleTutorService()
    ui_renderer = ExampleUIRenderer()
    data_processor = ExampleDataProcessor()
    
    print("\n2. Demonstrating caching...")
    
    # First call - should be slow (cache miss)
    print("   First call to get_cognitive_state (cache miss):")
    start_time = time.time()
    state1 = tutor_service.get_cognitive_state("user123", "math")
    first_call_time = time.time() - start_time
    print(f"   Time: {first_call_time:.3f}s")
    
    # Second call - should be fast (cache hit)
    print("   Second call to get_cognitive_state (cache hit):")
    start_time = time.time()
    state2 = tutor_service.get_cognitive_state("user123", "math")
    second_call_time = time.time() - start_time
    print(f"   Time: {second_call_time:.3f}s")
    print(f"   Speedup: {first_call_time / second_call_time:.1f}x")
    
    print("\n3. Demonstrating profiling...")
    
    # Call methods that will be profiled
    recommendations = tutor_service.get_recommendations("user456", "science")
    hint_strategy = tutor_service.generate_hint_strategy("user789", "math", "hard")
    
    # Render UI components
    widget_html = ui_renderer.render_practice_widget("widget_1", {"topic": "math", "difficulty": "medium"})
    dashboard_html = ui_renderer.render_dashboard("user101", ["widget_1", "widget_2"])
    
    # Process data
    user_data = [{"score": 85}, {"score": 90}, {"score": 78}]
    insights = data_processor.process_user_data("user202", user_data)
    aggregated = data_processor.aggregate_data(["user1", "user2", "user3"])
    
    print("\n4. Performance statistics:")
    stats = get_performance_stats()
    
    if stats.get('cache_service'):
        cache_stats = stats['cache_service']
        print(f"   Cache size: {cache_stats['size']}/{cache_stats['max_size']}")
        print(f"   Cache hits: {cache_stats['hits']}")
        print(f"   Cache misses: {cache_stats['misses']}")
        print(f"   Hit rate: {cache_stats['hit_rate']:.2%}")
    
    if stats.get('profiler'):
        profiler_stats = stats['profiler']
        print(f"   Total operations: {profiler_stats['total_operations']}")
        print(f"   Successful operations: {profiler_stats['successful_operations']}")
        print(f"   Failed operations: {profiler_stats['failed_operations']}")
    
    print("\n5. Clearing cache and resetting profiler...")
    clear_performance_cache()
    reset_performance_profiler()
    
    print("\n=== Demonstration Complete ===")


if __name__ == "__main__":
    demonstrate_performance_optimizations()