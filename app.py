# app.py (updated with checkout system)
import os
import sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import json

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'  # Change this to a random secret key

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'store.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static/uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Database initialization
def init_db():
    """Initialize the database with tables"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Products table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            image_filename TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_available BOOLEAN DEFAULT 1
        )
    ''')
    
    # Admin user table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    
    # Orders table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT UNIQUE NOT NULL,
            customer_name TEXT NOT NULL,
            customer_email TEXT NOT NULL,
            customer_phone TEXT NOT NULL,
            shipping_address TEXT NOT NULL,
            shipping_city TEXT NOT NULL,
            shipping_state TEXT,
            shipping_zip TEXT NOT NULL,
            shipping_country TEXT NOT NULL,
            order_items TEXT NOT NULL,
            subtotal REAL NOT NULL,
            shipping_cost REAL DEFAULT 0,
            tax REAL DEFAULT 0,
            total REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Store contact information messages
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contact_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            message TEXT NOT NULL,
            ip_address TEXT,
            status TEXT DEFAULT 'sent',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create index for faster order lookups
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_order_number ON orders(order_number)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_order_email ON orders(customer_email)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_order_status ON orders(status)')
    
    # Check if admin exists, if not create default
    cursor.execute("SELECT * FROM admin_users WHERE username = 'admin'")
    if not cursor.fetchone():
        default_password = generate_password_hash('admin123')
        cursor.execute("INSERT INTO admin_users (username, password_hash) VALUES (?, ?)", 
                      ('admin', default_password))
        print("Default admin created: username='admin', password='admin123' - CHANGE THIS IN PRODUCTION!")
    
    conn.commit()
    conn.close()

def allowed_file(filename):
    """Check if uploaded file has an allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def login_required(f):
    """Decorator to require admin login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Please log in to access the admin area.', 'warning')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def generate_order_number():
    """Generate a unique order number"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    import random
    random_num = random.randint(100, 999)
    return f"ORD-{timestamp}-{random_num}"

# Cart helper functions
def get_cart():
    """Get the current cart from session"""
    return session.get('cart', {})

def save_cart(cart):
    """Save cart to session"""
    session['cart'] = cart
    session.modified = True

def add_to_cart(product_id, quantity=1):
    """Add a product to the cart"""
    cart = get_cart()
    product_id_str = str(product_id)
    
    if product_id_str in cart:
        cart[product_id_str]['quantity'] += quantity
    else:
        # Get product details from database
        conn = get_db()
        product = conn.execute('SELECT id, name, price, image_filename FROM products WHERE id = ? AND is_available = 1', (product_id,)).fetchone()
        conn.close()
        
        if product:
            cart[product_id_str] = {
                'id': product['id'],
                'name': product['name'],
                'price': float(product['price']),
                'image_filename': product['image_filename'],  # ✅ ADD THIS LINE
                'quantity': quantity
            }
    
    save_cart(cart)
    return True

def remove_from_cart(product_id):
    """Remove a product from the cart"""
    cart = get_cart()
    product_id_str = str(product_id)
    
    if product_id_str in cart:
        del cart[product_id_str]
        save_cart(cart)
        return True
    return False

def update_cart_quantity(product_id, quantity):
    """Update quantity of a product in cart"""
    cart = get_cart()
    product_id_str = str(product_id)
    
    if product_id_str in cart:
        if quantity <= 0:
            del cart[product_id_str]
        else:
            cart[product_id_str]['quantity'] = quantity  # ✅ Keeps existing image_filename
        save_cart(cart)
        return True
    return False

def clear_cart():
    """Clear the entire cart"""
    session['cart'] = {}
    session.modified = True

def get_cart_total():
    """Calculate cart subtotal"""
    cart = get_cart()
    total = sum(item['price'] * item['quantity'] for item in cart.values())
    return total

def get_cart_count():
    """Get total number of items in cart"""
    cart = get_cart()
    return sum(item['quantity'] for item in cart.values())

def save_contact_message(name, email, message, ip_address, status="sent"):
    """Save contact form submission to database"""
    conn = get_db()
    conn.execute(
        'INSERT INTO contact_messages (name, email, message, ip_address, status) VALUES (?, ?, ?, ?, ?)',
        (name, email, message, ip_address, status)
    )
    conn.commit()
    conn.close()
    
# Routes
@app.route('/')
def index():
    """Home page - shows featured products"""
    conn = get_db()
    products = conn.execute('SELECT * FROM products WHERE is_available = 1 ORDER BY created_at DESC LIMIT 6').fetchall()
    conn.close()
    cart_count = get_cart_count()
    return render_template('index.html', products=products, cart_count=cart_count)

@app.route('/shop')
def shop():
    """Shop page - shows all products"""
    conn = get_db()
    products = conn.execute('SELECT * FROM products WHERE is_available = 1 ORDER BY created_at DESC').fetchall()
    conn.close()
    cart_count = get_cart_count()
    return render_template('shop.html', products=products, cart_count=cart_count)

@app.route('/product/<int:product_id>')
def product_detail(product_id):
    """Product detail page"""
    conn = get_db()
    product = conn.execute('SELECT * FROM products WHERE id = ? AND is_available = 1', (product_id,)).fetchone()
    conn.close()
    if not product:
        abort(404)
    cart_count = get_cart_count()
    return render_template('product_detail.html', product=product, cart_count=cart_count)

@app.route('/cart')
def cart():
    """Shopping cart page"""
    cart_items = get_cart()
    subtotal = get_cart_total()
    cart_count = get_cart_count()
    return render_template('cart.html', cart_items=cart_items, subtotal=subtotal, cart_count=cart_count)

@app.route('/cart/add/<int:product_id>', methods=['POST'])
def add_to_cart_route(product_id):
    """Add item to cart"""
    quantity = int(request.form.get('quantity', 1))
    if add_to_cart(product_id, quantity):
        flash('Item added to cart!', 'success')
    else:
        flash('Could not add item to cart.', 'danger')
    
    # Redirect back to the page they came from
    return redirect(request.referrer or url_for('shop'))

@app.route('/cart/update/<int:product_id>', methods=['POST'])
def update_cart_route(product_id):
    """Update cart item quantity"""
    quantity = int(request.form.get('quantity', 0))
    if update_cart_quantity(product_id, quantity):
        flash('Cart updated!', 'success')
    return redirect(url_for('cart'))

@app.route('/cart/remove/<int:product_id>', methods=['POST'])
def remove_from_cart_route(product_id):
    """Remove item from cart"""
    if remove_from_cart(product_id):
        flash('Item removed from cart.', 'success')
    return redirect(url_for('cart'))

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    """Checkout page - collect customer information"""
    cart_items = get_cart()
    if not cart_items:
        flash('Your cart is empty.', 'warning')
        return redirect(url_for('shop'))
    
    subtotal = get_cart_total()
    shipping_cost = 5.99 if subtotal > 0 and subtotal < 50 else 0  # Free shipping over $50
    tax = subtotal * 0.08  # 8% tax
    total = subtotal + shipping_cost + tax
    
    if request.method == 'POST':
        # Get form data
        customer_name = request.form.get('customer_name')
        customer_email = request.form.get('customer_email')
        customer_phone = request.form.get('customer_phone')
        shipping_address = request.form.get('shipping_address')
        shipping_city = request.form.get('shipping_city')
        shipping_state = request.form.get('shipping_state')
        shipping_zip = request.form.get('shipping_zip')
        shipping_country = request.form.get('shipping_country')
        notes = request.form.get('notes')
        
        # Validate required fields
        if not all([customer_name, customer_email, customer_phone, shipping_address, shipping_city, shipping_zip, shipping_country]):
            flash('Please fill in all required fields.', 'danger')
            return render_template('checkout.html', cart_items=cart_items, subtotal=subtotal, 
                                 shipping_cost=shipping_cost, tax=tax, total=total, cart_count=get_cart_count())
        
        # Prepare order items as JSON
        order_items = []
        for item in cart_items.values():
            order_items.append({
                'product_id': item['id'],
                'name': item['name'],
                'price': item['price'],
                'quantity': item['quantity'],
                'total': item['price'] * item['quantity']
            })
        
        order_number = generate_order_number()
        
        # Save to database
        conn = get_db()
        try:
            conn.execute('''
                INSERT INTO orders (
                    order_number, customer_name, customer_email, customer_phone,
                    shipping_address, shipping_city, shipping_state, shipping_zip,
                    shipping_country, order_items, subtotal, shipping_cost, tax, total, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                order_number, customer_name, customer_email, customer_phone,
                shipping_address, shipping_city, shipping_state, shipping_zip,
                shipping_country, json.dumps(order_items), subtotal, shipping_cost, tax, total, notes
            ))
            conn.commit()
            
            # Clear the cart
            clear_cart()
            
            # Store order number in session for thank you page
            session['last_order'] = order_number
            
            flash(f'Order placed successfully! Your order number is {order_number}', 'success')
            return redirect(url_for('order_confirmation', order_number=order_number))
            
        except Exception as e:
            conn.rollback()
            flash('There was an error processing your order. Please try again.', 'danger')
            print(f"Order error: {e}")
        finally:
            conn.close()
    
    return render_template('checkout.html', cart_items=cart_items, subtotal=subtotal, 
                         shipping_cost=shipping_cost, tax=tax, total=total, cart_count=get_cart_count())

@app.route('/order/<order_number>')
def order_confirmation(order_number):
    """Order confirmation page"""
    conn = get_db()
    order = conn.execute('SELECT * FROM orders WHERE order_number = ?', (order_number,)).fetchone()
    conn.close()
    
    if not order:
        abort(404)
    
    # Parse order items from JSON
    order_items = json.loads(order['order_items'])
    
    return render_template('order_confirmation.html', order=order, order_items=order_items, cart_count=0)

@app.route('/about')
def about():
    """About page"""
    cart_count = get_cart_count()
    return render_template('about.html', cart_count=cart_count)

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    """Contact page"""
    cart_count = get_cart_count()
    
    if request.method == 'POST':
        # In a real app, you'd send an email here
        flash('Thank you for your message! We\'ll get back to you soon.', 'success')
        return redirect(url_for('contact'))
    
    return render_template('contact.html', cart_count=cart_count)

# Admin routes
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page"""
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = get_db()
        admin = conn.execute('SELECT * FROM admin_users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if admin and check_password_hash(admin['password_hash'], password):
            session['admin_logged_in'] = True
            session['admin_username'] = username
            flash('Login successful!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    """Admin logout"""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# Update this route in app.py

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    """Admin dashboard - manage products and orders"""
    conn = get_db()
    products = conn.execute('SELECT * FROM products ORDER BY created_at DESC').fetchall()
    
    # Get orders for the orders tab
    orders = conn.execute('SELECT * FROM orders ORDER BY created_at DESC').fetchall()
    
    # Get order statistics
    total_orders = conn.execute('SELECT COUNT(*) as count FROM orders').fetchone()['count']
    pending_orders = conn.execute('SELECT COUNT(*) as count FROM orders WHERE status = "pending"').fetchone()['count']
    total_revenue = conn.execute('SELECT SUM(total) as total FROM orders WHERE status != "cancelled"').fetchone()['total'] or 0
    
    conn.close()
    
    return render_template('admin_dashboard.html', 
                         products=products,
                         orders=orders,
                         total_orders=total_orders,
                         pending_orders=pending_orders,
                         total_revenue=total_revenue)

@app.route('/admin/orders')
@login_required
def admin_orders():
    """Admin orders page - view all orders"""
    conn = get_db()
    orders = conn.execute('SELECT * FROM orders ORDER BY created_at DESC').fetchall()
    conn.close()
    return render_template('admin_orders.html', orders=orders)

@app.route('/admin/order/<int:order_id>')
@login_required
def admin_order_detail(order_id):
    """Admin order detail page"""
    conn = get_db()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    
    if not order:
        flash('Order not found.', 'danger')
        return redirect(url_for('admin_orders'))
    
    order_items = json.loads(order['order_items'])
    conn.close()
    
    return render_template('admin_order_detail.html', order=order, order_items=order_items)

@app.route('/admin/order/<int:order_id>/update-status', methods=['POST'])
@login_required
def admin_update_order_status(order_id):
    """Update order status"""
    new_status = request.form.get('status')
    valid_statuses = ['pending', 'processing', 'shipped', 'delivered', 'cancelled']
    
    if new_status not in valid_statuses:
        flash('Invalid status.', 'danger')
        return redirect(url_for('admin_order_detail', order_id=order_id))
    
    conn = get_db()
    conn.execute('UPDATE orders SET status = ? WHERE id = ?', (new_status, order_id))
    conn.commit()
    conn.close()
    
    flash(f'Order status updated to {new_status}.', 'success')
    return redirect(url_for('admin_order_detail', order_id=order_id))

@app.route('/admin/product/new', methods=['GET', 'POST'])
@login_required
def admin_new_product():
    """Add a new product"""
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        price = request.form.get('price')
        is_available = request.form.get('is_available') == 'on'
        
        if not name or not price:
            flash('Name and price are required.', 'danger')
            return redirect(url_for('admin_new_product'))
        
        try:
            price = float(price)
        except ValueError:
            flash('Price must be a number.', 'danger')
            return redirect(url_for('admin_new_product'))
        
        # Handle image upload
        image_filename = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_filename = filename
            elif file and file.filename:
                flash('Invalid file type. Allowed: png, jpg, jpeg, gif, webp', 'warning')
        
        conn = get_db()
        conn.execute(
            'INSERT INTO products (name, description, price, image_filename, is_available) VALUES (?, ?, ?, ?, ?)',
            (name, description, price, image_filename, is_available)
        )
        conn.commit()
        conn.close()
        
        flash(f'Product "{name}" added successfully!', 'success')
        return redirect(url_for('admin_dashboard'))
    
    return render_template('admin_product_form.html', product=None)

@app.route('/admin/product/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_edit_product(product_id):
    """Edit an existing product"""
    conn = get_db()
    product = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
    
    if not product:
        flash('Product not found.', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        price = request.form.get('price')
        is_available = request.form.get('is_available') == 'on'
        
        if not name or not price:
            flash('Name and price are required.', 'danger')
            return redirect(url_for('admin_edit_product', product_id=product_id))
        
        try:
            price = float(price)
        except ValueError:
            flash('Price must be a number.', 'danger')
            return redirect(url_for('admin_edit_product', product_id=product_id))
        
        # Handle image upload
        image_filename = product['image_filename']
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                # Delete old image if exists
                if image_filename:
                    old_image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_filename)
                    if os.path.exists(old_image_path):
                        os.remove(old_image_path)
                
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_filename = filename
            elif file and file.filename:
                flash('Invalid file type. Allowed: png, jpg, jpeg, gif, webp', 'warning')
        
        conn.execute(
            'UPDATE products SET name = ?, description = ?, price = ?, image_filename = ?, is_available = ? WHERE id = ?',
            (name, description, price, image_filename, is_available, product_id)
        )
        conn.commit()
        conn.close()
        
        flash(f'Product "{name}" updated successfully!', 'success')
        return redirect(url_for('admin_dashboard'))
    
    conn.close()
    return render_template('admin_product_form.html', product=product)

@app.route('/admin/product/<int:product_id>/delete', methods=['POST'])
@login_required
def admin_delete_product(product_id):
    """Delete a product"""
    conn = get_db()
    product = conn.execute('SELECT image_filename FROM products WHERE id = ?', (product_id,)).fetchone()
    
    if product and product['image_filename']:
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], product['image_filename'])
        if os.path.exists(image_path):
            os.remove(image_path)
    
    conn.execute('DELETE FROM products WHERE id = ?', (product_id,))
    conn.commit()
    conn.close()
    
    flash('Product deleted successfully.', 'success')
    return redirect(url_for('admin_dashboard'))

# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

# Context processor to make cart count available to all templates
@app.context_processor
def utility_processor():
    def get_cart_count_global():
        return get_cart_count()
    return dict(get_cart_count=get_cart_count_global)





# Initialize database when app starts
with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=55)