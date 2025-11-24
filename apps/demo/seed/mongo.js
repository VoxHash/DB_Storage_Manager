// Demo MongoDB database with sample data
// This script creates collections and inserts sample data for testing

// Switch to the demo database
db = db.getSiblingDB('demo_db');

// Create users collection
db.users.insertMany([
  {
    _id: ObjectId(),
    username: 'john_doe',
    email: 'john@example.com',
    first_name: 'John',
    last_name: 'Doe',
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    _id: ObjectId(),
    username: 'jane_smith',
    email: 'jane@example.com',
    first_name: 'Jane',
    last_name: 'Smith',
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    _id: ObjectId(),
    username: 'bob_wilson',
    email: 'bob@example.com',
    first_name: 'Bob',
    last_name: 'Wilson',
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    _id: ObjectId(),
    username: 'alice_brown',
    email: 'alice@example.com',
    first_name: 'Alice',
    last_name: 'Brown',
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    _id: ObjectId(),
    username: 'charlie_davis',
    email: 'charlie@example.com',
    first_name: 'Charlie',
    last_name: 'Davis',
    created_at: new Date(),
    updated_at: new Date()
  }
]);

// Create categories collection
db.categories.insertMany([
  {
    _id: ObjectId(),
    name: 'Electronics',
    description: 'Electronic devices and accessories',
    created_at: new Date()
  },
  {
    _id: ObjectId(),
    name: 'Clothing',
    description: 'Apparel and fashion items',
    created_at: new Date()
  },
  {
    _id: ObjectId(),
    name: 'Books',
    description: 'Books and educational materials',
    created_at: new Date()
  },
  {
    _id: ObjectId(),
    name: 'Home & Garden',
    description: 'Home improvement and garden supplies',
    created_at: new Date()
  },
  {
    _id: ObjectId(),
    name: 'Sports',
    description: 'Sports equipment and accessories',
    created_at: new Date()
  }
]);

// Get category IDs for products
var electronicsId = db.categories.findOne({name: 'Electronics'})._id;
var clothingId = db.categories.findOne({name: 'Clothing'})._id;
var booksId = db.categories.findOne({name: 'Books'})._id;
var homeGardenId = db.categories.findOne({name: 'Home & Garden'})._id;
var sportsId = db.categories.findOne({name: 'Sports'})._id;

// Create products collection
db.products.insertMany([
  {
    _id: ObjectId(),
    name: 'Laptop Pro 15"',
    description: 'High-performance laptop with 16GB RAM and 512GB SSD',
    price: 1299.99,
    category_id: electronicsId,
    stock_quantity: 50,
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    _id: ObjectId(),
    name: 'Wireless Mouse',
    description: 'Ergonomic wireless mouse with USB receiver',
    price: 29.99,
    category_id: electronicsId,
    stock_quantity: 200,
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    _id: ObjectId(),
    name: 'Mechanical Keyboard',
    description: 'RGB mechanical keyboard with blue switches',
    price: 89.99,
    category_id: electronicsId,
    stock_quantity: 75,
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    _id: ObjectId(),
    name: 'Cotton T-Shirt',
    description: 'Comfortable 100% cotton t-shirt in various colors',
    price: 19.99,
    category_id: clothingId,
    stock_quantity: 300,
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    _id: ObjectId(),
    name: 'Denim Jeans',
    description: 'Classic blue denim jeans with stretch',
    price: 59.99,
    category_id: clothingId,
    stock_quantity: 150,
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    _id: ObjectId(),
    name: 'Programming Book',
    description: 'Learn JavaScript: A comprehensive guide',
    price: 39.99,
    category_id: booksId,
    stock_quantity: 100,
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    _id: ObjectId(),
    name: 'Garden Hose',
    description: '50ft expandable garden hose with spray nozzle',
    price: 24.99,
    category_id: homeGardenId,
    stock_quantity: 80,
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    _id: ObjectId(),
    name: 'Tennis Racket',
    description: 'Professional tennis racket for intermediate players',
    price: 89.99,
    category_id: sportsId,
    stock_quantity: 40,
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    _id: ObjectId(),
    name: 'Smartphone',
    description: 'Latest smartphone with 128GB storage',
    price: 699.99,
    category_id: electronicsId,
    stock_quantity: 30,
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    _id: ObjectId(),
    name: 'Running Shoes',
    description: 'Comfortable running shoes with air cushioning',
    price: 79.99,
    category_id: sportsId,
    stock_quantity: 120,
    created_at: new Date(),
    updated_at: new Date()
  }
]);

// Get user and product IDs for orders
var userIds = db.users.find({}, {_id: 1}).toArray().map(u => u._id);
var productIds = db.products.find({}, {_id: 1}).toArray().map(p => p._id);

// Create orders collection
db.orders.insertMany([
  {
    _id: ObjectId(),
    user_id: userIds[0],
    total_amount: 1329.98,
    status: 'completed',
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    _id: ObjectId(),
    user_id: userIds[1],
    total_amount: 109.98,
    status: 'pending',
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    _id: ObjectId(),
    user_id: userIds[2],
    total_amount: 79.98,
    status: 'shipped',
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    _id: ObjectId(),
    user_id: userIds[3],
    total_amount: 199.96,
    status: 'completed',
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    _id: ObjectId(),
    user_id: userIds[4],
    total_amount: 39.99,
    status: 'pending',
    created_at: new Date(),
    updated_at: new Date()
  }
]);

// Get order IDs for order items
var orderIds = db.orders.find({}, {_id: 1}).toArray().map(o => o._id);

// Create order_items collection
db.order_items.insertMany([
  {
    _id: ObjectId(),
    order_id: orderIds[0],
    product_id: productIds[0],
    quantity: 1,
    price: 1299.99,
    created_at: new Date()
  },
  {
    _id: ObjectId(),
    order_id: orderIds[0],
    product_id: productIds[1],
    quantity: 1,
    price: 29.99,
    created_at: new Date()
  },
  {
    _id: ObjectId(),
    order_id: orderIds[1],
    product_id: productIds[2],
    quantity: 1,
    price: 89.99,
    created_at: new Date()
  },
  {
    _id: ObjectId(),
    order_id: orderIds[1],
    product_id: productIds[3],
    quantity: 1,
    price: 19.99,
    created_at: new Date()
  },
  {
    _id: ObjectId(),
    order_id: orderIds[2],
    product_id: productIds[4],
    quantity: 1,
    price: 59.99,
    created_at: new Date()
  },
  {
    _id: ObjectId(),
    order_id: orderIds[2],
    product_id: productIds[3],
    quantity: 1,
    price: 19.99,
    created_at: new Date()
  },
  {
    _id: ObjectId(),
    order_id: orderIds[3],
    product_id: productIds[5],
    quantity: 2,
    price: 39.99,
    created_at: new Date()
  },
  {
    _id: ObjectId(),
    order_id: orderIds[3],
    product_id: productIds[6],
    quantity: 2,
    price: 24.99,
    created_at: new Date()
  },
  {
    _id: ObjectId(),
    order_id: orderIds[4],
    product_id: productIds[5],
    quantity: 1,
    price: 39.99,
    created_at: new Date()
  }
]);

// Create indexes for better performance
db.users.createIndex({ email: 1 });
db.users.createIndex({ username: 1 });
db.products.createIndex({ category_id: 1 });
db.products.createIndex({ name: 1 });
db.orders.createIndex({ user_id: 1 });
db.orders.createIndex({ status: 1 });
db.orders.createIndex({ created_at: 1 });
db.order_items.createIndex({ order_id: 1 });
db.order_items.createIndex({ product_id: 1 });

// Create a view-like collection for order summary (using aggregation)
db.createCollection('order_summary', {
  viewOn: 'orders',
  pipeline: [
    {
      $lookup: {
        from: 'users',
        localField: 'user_id',
        foreignField: '_id',
        as: 'user'
      }
    },
    {
      $lookup: {
        from: 'order_items',
        localField: '_id',
        foreignField: 'order_id',
        as: 'items'
      }
    },
    {
      $project: {
        order_id: '$_id',
        username: { $arrayElemAt: ['$user.username', 0] },
        email: { $arrayElemAt: ['$user.email', 0] },
        total_amount: 1,
        status: 1,
        created_at: 1,
        item_count: { $size: '$items' }
      }
    }
  ]
});

print('Demo database setup completed successfully!');
print('Collections created: users, categories, products, orders, order_items, order_summary');
print('Sample data inserted and indexes created.');
