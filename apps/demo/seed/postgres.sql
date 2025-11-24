-- Demo PostgreSQL database with sample data
-- This script creates tables and inserts sample data for testing

-- Create users table
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    first_name VARCHAR(50),
    last_name VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create products table
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    price DECIMAL(10,2) NOT NULL,
    category_id INTEGER,
    stock_quantity INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create categories table
CREATE TABLE categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create orders table
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    total_amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create order_items table
CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER REFERENCES orders(id),
    product_id INTEGER REFERENCES products(id),
    quantity INTEGER NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better performance
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_products_name ON products(name);
CREATE INDEX idx_orders_user_id ON orders(user_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_created_at ON orders(created_at);
CREATE INDEX idx_order_items_order_id ON order_items(order_id);
CREATE INDEX idx_order_items_product_id ON order_items(product_id);

-- Insert sample categories
INSERT INTO categories (name, description) VALUES
('Electronics', 'Electronic devices and accessories'),
('Clothing', 'Apparel and fashion items'),
('Books', 'Books and educational materials'),
('Home & Garden', 'Home improvement and garden supplies'),
('Sports', 'Sports equipment and accessories');

-- Insert sample users
INSERT INTO users (username, email, first_name, last_name) VALUES
('john_doe', 'john@example.com', 'John', 'Doe'),
('jane_smith', 'jane@example.com', 'Jane', 'Smith'),
('bob_wilson', 'bob@example.com', 'Bob', 'Wilson'),
('alice_brown', 'alice@example.com', 'Alice', 'Brown'),
('charlie_davis', 'charlie@example.com', 'Charlie', 'Davis'),
('diana_miller', 'diana@example.com', 'Diana', 'Miller'),
('eve_jones', 'eve@example.com', 'Eve', 'Jones'),
('frank_garcia', 'frank@example.com', 'Frank', 'Garcia'),
('grace_lee', 'grace@example.com', 'Grace', 'Lee'),
('henry_taylor', 'henry@example.com', 'Henry', 'Taylor');

-- Insert sample products
INSERT INTO products (name, description, price, category_id, stock_quantity) VALUES
('Laptop Pro 15"', 'High-performance laptop with 16GB RAM and 512GB SSD', 1299.99, 1, 50),
('Wireless Mouse', 'Ergonomic wireless mouse with USB receiver', 29.99, 1, 200),
('Mechanical Keyboard', 'RGB mechanical keyboard with blue switches', 89.99, 1, 75),
('Cotton T-Shirt', 'Comfortable 100% cotton t-shirt in various colors', 19.99, 2, 300),
('Denim Jeans', 'Classic blue denim jeans with stretch', 59.99, 2, 150),
('Programming Book', 'Learn JavaScript: A comprehensive guide', 39.99, 3, 100),
('Garden Hose', '50ft expandable garden hose with spray nozzle', 24.99, 4, 80),
('Tennis Racket', 'Professional tennis racket for intermediate players', 89.99, 5, 40),
('Smartphone', 'Latest smartphone with 128GB storage', 699.99, 1, 30),
('Running Shoes', 'Comfortable running shoes with air cushioning', 79.99, 5, 120);

-- Insert sample orders
INSERT INTO orders (user_id, total_amount, status) VALUES
(1, 1329.98, 'completed'),
(2, 109.98, 'pending'),
(3, 79.98, 'shipped'),
(4, 199.96, 'completed'),
(5, 39.99, 'pending'),
(6, 89.99, 'completed'),
(7, 24.99, 'shipped'),
(8, 89.99, 'pending'),
(9, 699.99, 'completed'),
(10, 79.99, 'shipped');

-- Insert sample order items
INSERT INTO order_items (order_id, product_id, quantity, price) VALUES
(1, 1, 1, 1299.99),
(1, 2, 1, 29.99),
(2, 3, 1, 89.99),
(2, 4, 1, 19.99),
(3, 5, 1, 59.99),
(3, 4, 1, 19.99),
(4, 6, 2, 39.99),
(4, 7, 2, 24.99),
(5, 6, 1, 39.99),
(6, 8, 1, 89.99),
(7, 7, 1, 24.99),
(8, 8, 1, 89.99),
(9, 9, 1, 699.99),
(10, 10, 1, 79.99);

-- Create a view for order summary
CREATE VIEW order_summary AS
SELECT 
    o.id as order_id,
    u.username,
    u.email,
    o.total_amount,
    o.status,
    o.created_at,
    COUNT(oi.id) as item_count
FROM orders o
JOIN users u ON o.user_id = u.id
LEFT JOIN order_items oi ON o.id = oi.order_id
GROUP BY o.id, u.username, u.email, o.total_amount, o.status, o.created_at;

-- Create a function to get user statistics
CREATE OR REPLACE FUNCTION get_user_stats(user_id INTEGER)
RETURNS TABLE (
    total_orders BIGINT,
    total_spent DECIMAL,
    avg_order_value DECIMAL,
    last_order_date TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        COUNT(o.id) as total_orders,
        COALESCE(SUM(o.total_amount), 0) as total_spent,
        COALESCE(AVG(o.total_amount), 0) as avg_order_value,
        MAX(o.created_at) as last_order_date
    FROM orders o
    WHERE o.user_id = $1;
END;
$$ LANGUAGE plpgsql;

-- Update the updated_at timestamp function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create triggers to automatically update updated_at
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_products_updated_at BEFORE UPDATE ON products
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_orders_updated_at BEFORE UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
