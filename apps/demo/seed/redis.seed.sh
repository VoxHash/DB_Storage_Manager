#!/bin/bash
# Demo Redis database with sample data
# This script populates Redis with sample key-value pairs for testing

# Wait for Redis to be ready
sleep 5

# Set some string values
redis-cli SET "user:1:name" "John Doe"
redis-cli SET "user:1:email" "john@example.com"
redis-cli SET "user:1:age" "30"
redis-cli SET "user:2:name" "Jane Smith"
redis-cli SET "user:2:email" "jane@example.com"
redis-cli SET "user:2:age" "28"
redis-cli SET "user:3:name" "Bob Wilson"
redis-cli SET "user:3:email" "bob@example.com"
redis-cli SET "user:3:age" "35"

# Set some hash values
redis-cli HSET "product:1" "name" "Laptop Pro 15\""
redis-cli HSET "product:1" "price" "1299.99"
redis-cli HSET "product:1" "category" "Electronics"
redis-cli HSET "product:1" "stock" "50"

redis-cli HSET "product:2" "name" "Wireless Mouse"
redis-cli HSET "product:2" "price" "29.99"
redis-cli HSET "product:2" "category" "Electronics"
redis-cli HSET "product:2" "stock" "200"

redis-cli HSET "product:3" "name" "Cotton T-Shirt"
redis-cli HSET "product:3" "price" "19.99"
redis-cli HSET "product:3" "category" "Clothing"
redis-cli HSET "product:3" "stock" "300"

# Set some list values
redis-cli LPUSH "recent_orders" "order:1"
redis-cli LPUSH "recent_orders" "order:2"
redis-cli LPUSH "recent_orders" "order:3"
redis-cli LPUSH "recent_orders" "order:4"
redis-cli LPUSH "recent_orders" "order:5"

# Set some set values
redis-cli SADD "categories" "Electronics"
redis-cli SADD "categories" "Clothing"
redis-cli SADD "categories" "Books"
redis-cli SADD "categories" "Home & Garden"
redis-cli SADD "categories" "Sports"

redis-cli SADD "tags:product:1" "laptop"
redis-cli SADD "tags:product:1" "computer"
redis-cli SADD "tags:product:1" "electronics"
redis-cli SADD "tags:product:2" "mouse"
redis-cli SADD "tags:product:2" "wireless"
redis-cli SADD "tags:product:2" "electronics"

# Set some sorted set values (for leaderboards, rankings, etc.)
redis-cli ZADD "product_views" 150 "product:1"
redis-cli ZADD "product_views" 89 "product:2"
redis-cli ZADD "product_views" 234 "product:3"
redis-cli ZADD "product_views" 67 "product:4"
redis-cli ZADD "product_views" 178 "product:5"

redis-cli ZADD "user_scores" 1250 "user:1"
redis-cli ZADD "user_scores" 980 "user:2"
redis-cli ZADD "user_scores" 2100 "user:3"
redis-cli ZADD "user_scores" 750 "user:4"
redis-cli ZADD "user_scores" 1650 "user:5"

# Set some expiration times for demo purposes
redis-cli EXPIRE "user:1:name" 3600
redis-cli EXPIRE "user:2:name" 3600
redis-cli EXPIRE "user:3:name" 3600

# Set some counters
redis-cli SET "page_views" "1250"
redis-cli SET "total_orders" "89"
redis-cli SET "active_users" "156"

# Set some configuration values
redis-cli SET "app:config:max_connections" "100"
redis-cli SET "app:config:timeout" "30"
redis-cli SET "app:config:debug_mode" "false"

# Set some session data
redis-cli HSET "session:abc123" "user_id" "1"
redis-cli HSET "session:abc123" "login_time" "2024-01-01T10:00:00Z"
redis-cli HSET "session:abc123" "last_activity" "2024-01-01T10:30:00Z"
redis-cli EXPIRE "session:abc123" 1800

redis-cli HSET "session:def456" "user_id" "2"
redis-cli HSET "session:def456" "login_time" "2024-01-01T11:00:00Z"
redis-cli HSET "session:def456" "last_activity" "2024-01-01T11:15:00Z"
redis-cli EXPIRE "session:def456" 1800

# Set some cache data
redis-cli SET "cache:products:featured" '["product:1", "product:2", "product:3"]'
redis-cli SET "cache:stats:daily" '{"orders": 45, "revenue": 12500.50, "users": 23}'
redis-cli EXPIRE "cache:products:featured" 300
redis-cli EXPIRE "cache:stats:daily" 600

echo "Redis demo data populated successfully!"
echo "Keys created:"
redis-cli KEYS "*" | head -20
echo "..."
echo "Total keys: $(redis-cli DBSIZE)"
