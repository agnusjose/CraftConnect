from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_mail import Mail, Message

import os
import sqlite3
from werkzeug.security import check_password_hash
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import SocketIO, emit, join_room, leave_room
import json
import base64


# Store active chat rooms

app = Flask(__name__)
app.secret_key = "your_secret_key_here"  # Change this to a strong secret key
socketio = SocketIO(app) # Enable WebSockets
active_chats = {}

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'your-email@gmail.com'  # Replace with your email
app.config['MAIL_PASSWORD'] = 'your-email-password'  # Replace with an app password
app.config['MAIL_DEFAULT_SENDER'] = 'your-email@gmail.com'

mail = Mail(app)


# Upload folder for profile pictures & product images
UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Ensure the upload folder exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
db_path = os.path.abspath("craftconnect.db")  # Change to your actual database file
print("Using database file at:", db_path)
def init_db():
    conn = sqlite3.connect("craftconnect.db")
    cursor = conn.cursor()

    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            user_type TEXT NOT NULL,
            profile_pic TEXT DEFAULT 'default_profile.jpg'
        )
    """)


    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            receiver TEXT NOT NULL,
             message TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')


    # Products table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            price REAL NOT NULL,
            image TEXT NOT NULL,
            manufacturer_id INTEGER,
            FOREIGN KEY (manufacturer_id) REFERENCES users (id)
        )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        manufacturer_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        is_read INTEGER DEFAULT 0,  -- 0 = Unread, 1 = Read
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (manufacturer_id) REFERENCES users(id)
        )
    """)

    # Cart table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cart (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    """)

    # Orders table (to store customer orders)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            total_price REAL NOT NULL,
            status TEXT DEFAULT 'Processing',
            payment_status TEXT NOT NULL DEFAULT 'COD',  -- "COD" or "Paid"
            refund_status TEXT DEFAULT 'Not Refunded',  -- "Refunded" or "Not Refunded"
            order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    """)

    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contact_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER,
    manufacturer_id INTEGER,
    message TEXT,
    is_image INTEGER DEFAULT 0,  -- 0 for text, 1 for image
    image_url TEXT,              -- URL for the uploaded image
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)

    ''')
    def update_orders_table():
        conn = sqlite3.connect("craftconnect.db")
        cursor = conn.cursor()

        # Step 1: Add manufacturer_id column if not already present
        try:
            cursor.execute("ALTER TABLE orders ADD COLUMN manufacturer_id INTEGER;")
        except sqlite3.OperationalError:
            print("Column manufacturer_id already exists, skipping...")

        # Step 2: Update existing rows with manufacturer_id from products table
        cursor.execute("""
            UPDATE orders 
            SET manufacturer_id = (
                SELECT manufacturer_id FROM products WHERE products.id = orders.product_id
            )
        """)

        conn.commit()
        conn.close()

    update_orders_table()
    conn.commit()
    conn.close()

init_db()


# Home Page


from werkzeug.security import generate_password_hash

@app.route('/signup', methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        user_type = request.form["user_type"]
        profile_pic = request.files["profile_pic"]

        if profile_pic:
            profile_pic_filename = profile_pic.filename
            profile_pic_path = os.path.join(app.config["UPLOAD_FOLDER"], profile_pic_filename)
            profile_pic.save(profile_pic_path)
        else:
            profile_pic_filename = "default_profile.jpg"

        hashed_password = generate_password_hash(password)

        try:
            with sqlite3.connect("craftconnect.db", timeout=10) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO users (name, email, password, user_type, profile_pic) VALUES (?, ?, ?, ?, ?)",
                               (name, email, hashed_password, user_type, profile_pic_filename))
                conn.commit()
                print("User added to database:", name, email, user_type, profile_pic_filename)
                flash("Signup successful!", "success")
                return redirect(url_for("login"))
        except sqlite3.IntegrityError as e:
            print("Database error:", str(e))
            flash(f"Signup failed: Email already exists.", "danger")
        except Exception as e:
            print("Error:", str(e))
            flash(f"Signup failed: {str(e)}", "danger")

    return render_template("signup.html")

from werkzeug.security import check_password_hash

@app.route('/login', methods=["GET", "POST"])
def login():
    user_type = request.form.get('user_type')  # "customer" or "manufacturer"
    session['user_type'] = user_type
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        print(f"Attempting login with email: {email}")

        try:
            with sqlite3.connect("craftconnect.db", timeout=10) as conn:
                cursor = conn.cursor()

                # Fetch user data from the database
                cursor.execute("SELECT * FROM users WHERE email=?", (email,))
                user = cursor.fetchone()
                
                if user:
                    print(f"User found: {user}")
                else:
                    print("No user found with that email")

                # Verify password (user[3] stores hashed password)
                if user and check_password_hash(user[3], password):
                    session["user_id"] = user[0]         # Store user ID in session
                    session["user_name"] = user[1]       # Store user name in session
                    session["user_type"] = user[4]       # Store user type (manufacturer or customer)
                    session["profile_pic"] = user[5]     # Store profile pic if needed
                    
                    flash("Login successful!", "success")
                    print("Login successful!")

                    # Redirect based on user type (customer or manufacturer)
                    if user[4] == "manufacturer":
                        return redirect(url_for("manufacturer_dashboard"))
                    elif user[4] == "customer":  # Explicit handling for customers
                        return redirect(url_for("customer_dashboard"))
                    else:
                        flash("User type is not recognized.", "danger")
                        return redirect(url_for("login"))

                else:
                    flash("Invalid email or password", "danger")
                    print("Invalid email or password")

        except sqlite3.OperationalError as e:
            print("Database error:", str(e))
            return jsonify({"error": str(e)}), 500

        except Exception as e:
            print("Error:", str(e))
            return jsonify({"error": str(e)}), 500

    return render_template("login.html")


# Browse Products
@app.route('/browse_products')
def browse_products():
    conn = sqlite3.connect("craftconnect.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT products.id, products.name, products.description, products.price, products.image, 
               users.name, users.id 
        FROM products
        JOIN users ON products.manufacturer_id = users.id
    """)
    products = cursor.fetchall()
    conn.close()
    
    return render_template("browse_products.html", products=products)


# Add to Cart
@app.route('/add_to_cart/<int:product_id>', methods=["POST"])
def add_to_cart(product_id):
    if "user_id" not in session:
        flash("You must be logged in to add items to the cart.", "danger")
        return redirect(url_for("login"))

    user_id = session["user_id"]

    conn = sqlite3.connect("craftconnect.db")
    cursor = conn.cursor()

    # Check if the product is already in the cart
    cursor.execute("SELECT * FROM cart WHERE user_id=? AND product_id=?", (user_id, product_id))
    item = cursor.fetchone()

    if item:
        cursor.execute("UPDATE cart SET quantity = quantity + 1 WHERE user_id=? AND product_id=?", (user_id, product_id))
    else:
        cursor.execute("INSERT INTO cart (user_id, product_id, quantity) VALUES (?, ?, 1)", (user_id, product_id))

    conn.commit()
    conn.close()

    flash("Product added to cart!", "success")
    return redirect(url_for("browse_products"))

# View Cart
@app.route('/cart')
def cart():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    conn = sqlite3.connect("craftconnect.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT products.id, products.name, products.price, cart.quantity, products.image
        FROM cart 
        JOIN products ON cart.product_id = products.id
        WHERE cart.user_id=?
    """, (user_id,))
    cart_items = cursor.fetchall()
    conn.close()

    return render_template("cart.html", cart_items=cart_items)

# Remove from Cart
@app.route('/remove_from_cart/<int:product_id>', methods=["POST"])
def remove_from_cart(product_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    conn = sqlite3.connect("craftconnect.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cart WHERE user_id=? AND product_id=?", (user_id, product_id))
    conn.commit()
    conn.close()

    flash("Item removed from cart.", "info")
    return redirect(url_for("cart"))

# Logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route('/manufacturer_dashboard')
def manufacturer_dashboard():
    if "user_id" not in session or session["user_type"] != "manufacturer":
        return redirect(url_for("login"))

    # Pass the user_id (manufacturer ID) and other session details to the template
    return render_template("manufacturer_dashboard.html", 
                           user_name=session["user_name"], 
                           profile_pic=session["profile_pic"], 
                           manufacturer_id=session["user_id"])


@app.route('/add_product', methods=["GET", "POST"])
def add_product():
    if "user_id" not in session or session["user_type"] != "manufacturer":
        return redirect(url_for("login"))
    
    if request.method == "POST":
        # Log form data
        print("Form data received:", request.form)

        if 'product_name' not in request.form or 'description' not in request.form:
            return jsonify({"error": "Missing 'product_name' or 'description' in form data"}), 400

        name = request.form["product_name"]
        description = request.form["description"]
        price = float(request.form["price"])
        image = request.files["image"]

        if image:
            image_filename = image.filename
            image_path = os.path.join(app.config["UPLOAD_FOLDER"], image_filename)
            image.save(image_path)
        else:
            image_filename = "default_product.jpg"

        try:
            with sqlite3.connect("craftconnect.db", timeout=10) as conn:
                cursor = conn.cursor()
                # Log SQL query
                print("Executing SQL query: INSERT INTO products (name, description, price, image, manufacturer_id) VALUES (?, ?, ?, ?, ?)")
                print("With values:", (name, description, price, image_filename, session["user_id"]))
                cursor.execute("INSERT INTO products (name, description, price, image, manufacturer_id) VALUES (?, ?, ?, ?, ?)", 
                               (name, description, price, image_filename, session["user_id"]))
                conn.commit()
                print("Product added to database:", name, description, price, image_filename, session["user_id"])
        except sqlite3.OperationalError as e:
            print("Database error:", str(e))
            return jsonify({"error": str(e)}), 500
        except Exception as e:
            print("Error:", str(e))
            return jsonify({"error": str(e)}), 500

        flash("Product added successfully!", "success")
        return redirect(url_for("manufacturer_dashboard"))

    return render_template("add_product.html")

@app.route('/manage_products')
def manage_products():
    if "user_id" not in session or session["user_type"] != "manufacturer":
        return redirect(url_for("login"))

    manufacturer_id = session["user_id"]

    conn = sqlite3.connect("craftconnect.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE manufacturer_id=?", (manufacturer_id,))
    products = cursor.fetchall()
    conn.close()

    return render_template("manage_products.html", products=products)

@app.route('/delete_product/<int:product_id>', methods=["POST"])
def delete_product(product_id):
    if "user_id" not in session or session["user_type"] != "manufacturer":
        return redirect(url_for("login"))

    conn = sqlite3.connect("craftconnect.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE id=? AND manufacturer_id=?", (product_id, session["user_id"]))
    conn.commit()
    conn.close()

    flash("Product deleted successfully!", "success")
    return redirect(url_for("manage_products"))


@app.route('/manage_orders')
def manage_orders():
    if "user_id" not in session or session["user_type"] != "manufacturer":
        return redirect(url_for("login"))

    try:
        with sqlite3.connect("craftconnect.db", timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    orders.id, 
                    users.name AS customer_name, 
                    products.name AS product_name, 
                    orders.quantity, 
                    orders.total_price, 
                    orders.status 
                FROM orders
                JOIN products ON orders.product_id = products.id
                JOIN users ON orders.user_id = users.id
                WHERE products.manufacturer_id = ?
            """, (session["user_id"],))

            orders = cursor.fetchall()
    except sqlite3.OperationalError as e:
        print("Database error:", str(e))
        flash("Failed to load orders due to database error.", "danger")
        orders = []

    return render_template("manage_orders.html", orders=orders)

@app.route('/view_order/<int:order_id>')
def view_order(order_id):
    if "user_id" not in session or session["user_type"] != "manufacturer":
        return redirect(url_for("login"))

    try:
        with sqlite3.connect("craftconnect.db", timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT orders.id, users.username, products.name, orders.quantity, orders.total_price, orders.status
                FROM orders
                JOIN products ON orders.product_id = products.id
                JOIN users ON orders.user_id = users.id  -- Ensure you use "users" table, not "customers"
                WHERE orders.manufacturer_id = ?
            """, (manufacturer_id,))
            order = cursor.fetchone()
    except sqlite3.OperationalError as e:
        print("Database error:", str(e))
        flash("Failed to load order details due to database error.", "danger")
        order = None

    return render_template("view_order.html", order=order)

@app.route('/track_order')
def track_order():
    if "user_id" not in session:
        flash("You must be logged in to track your orders.", "danger")
        return redirect(url_for("login"))

    user_id = session["user_id"]
    orders = []

    try:
        with sqlite3.connect("craftconnect.db", timeout=10) as conn:
            conn.row_factory = sqlite3.Row  # Fetch rows as dictionaries
            cursor = conn.cursor()
            cursor.execute('''
                SELECT orders.id, products.name AS product_name, orders.quantity, 
                       orders.total_price, orders.payment_status, orders.address, 
                       orders.phone, orders.email, orders.status
                FROM orders
                JOIN products ON orders.product_id = products.id
                WHERE orders.user_id = ?
            ''', (user_id,))
            orders = cursor.fetchall()
    except sqlite3.OperationalError as e:
        print(f"Database error: {e}")  # Print error in console for debugging
        flash(f"Failed to load orders: {e}", "danger")

    return render_template("track_order.html", orders=orders)

# Handle incoming messages
@socketio.on('send_message')
def handle_message(data):
    message = data['message']
    sender = data['sender']  # 'customer' or 'manufacturer'
    
    # Broadcast the message to all connected clients
    emit('receive_message', {'message': message, 'sender': sender}, broadcast=True)

@app.route('/update_order_status/<int:order_id>', methods=["POST"])
def update_order_status(order_id):
    if "user_id" not in session or session["user_type"] != "manufacturer":
        return redirect(url_for("login"))

    status = request.form["status"]

    try:
        with sqlite3.connect("craftconnect.db", timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE orders
                SET status = ?
                WHERE id = ? AND product_id IN (SELECT id FROM products WHERE manufacturer_id = ?)
            ''', (status, order_id, session["user_id"]))
            conn.commit()

        # Flash message for UI feedback
        flash("Order status updated successfully!", "success")
        return jsonify({"success": True})

    except sqlite3.OperationalError as e:
        print("Database error:", str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/customer_dashboard')
def customer_dashboard():
    if "user_id" not in session or session["user_type"] != "customer":
        return redirect(url_for("login"))

    return render_template("customer_dashboard.html", user_name=session["user_name"], profile_pic=session["profile_pic"])

@app.route('/checkout', methods=["GET", "POST"])
def checkout():
    if "user_id" not in session:
        flash("You must be logged in to checkout.", "danger")
        return redirect(url_for("login"))

    user_id = session["user_id"]

    conn = sqlite3.connect("craftconnect.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT products.id, products.name, products.price, cart.quantity 
        FROM cart 
        JOIN products ON cart.product_id = products.id
        WHERE cart.user_id=?
    """, (user_id,))
    cart_items = cursor.fetchall()
    conn.close()

    grand_total = sum(item[2] * item[3] for item in cart_items)

    return render_template("checkout.html", cart_items=cart_items, grand_total=grand_total)

@app.route('/place_order', methods=["POST"])
def place_order():
    if "user_id" not in session:
        flash("You must be logged in to place an order.", "danger")
        return redirect(url_for("login"))

    user_id = session["user_id"]
    address = request.form.get("address")
    phone = request.form.get("phone")
    email = request.form.get("email")
    payment_status = request.form.get("payment_status")

    conn = sqlite3.connect("craftconnect.db")
    cursor = conn.cursor()

    # Fetch products from the cart along with manufacturer_id
    cursor.execute("""
        SELECT products.id, products.name, products.price, cart.quantity, products.manufacturer_id 
        FROM cart 
        JOIN products ON cart.product_id = products.id
        WHERE cart.user_id=?
    """, (user_id,))
    cart_items = cursor.fetchall()

    if not cart_items:
        flash("Your cart is empty!", "warning")
        return redirect(url_for("cart"))

    grand_total = 0
    for item in cart_items:
        product_id = item[0]
        product_name = item[1]
        price = item[2]
        quantity = item[3]
        manufacturer_id = item[4]  # Fetching manufacturer_id from products table
        total_price = price * quantity
        grand_total += total_price

        # Insert into orders table
        cursor.execute("""
            INSERT INTO orders (user_id, product_id, quantity, total_price, payment_status, address, phone, email, status) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, product_id, quantity, total_price, payment_status, address, phone, email, "Processing"))

        # Insert a notification for the manufacturer
        cursor.execute("""
            INSERT INTO notifications (manufacturer_id, message, is_read) 
            VALUES (?, ?, 0)
        """, (manufacturer_id, f"New order received for {product_name}",))

    # Clear the cart after placing the order
    cursor.execute("DELETE FROM cart WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

    flash("Order placed successfully! A confirmation email has been sent.", "success")
    return redirect(url_for("customer_dashboard"))

@app.route('/orders')
def orders():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    conn = sqlite3.connect("craftconnect.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT orders.id, products.name, orders.quantity, orders.total_price, orders.status, orders.order_date 
        FROM orders 
        JOIN products ON orders.product_id = products.id
        WHERE orders.user_id=?
        ORDER BY orders.order_date DESC
    """, (user_id,))
    orders = cursor.fetchall()
    conn.close()

    return render_template("orders.html", orders=orders)

@app.route('/test')
def test():
    flash("This is a success message!", "success")
    flash("This is an error message!", "error")
    return redirect(url_for("home"))



@app.route('/')
def home():
    return render_template('index.html')  # Your homepage

@app.route('/about')
def about():
    return render_template('about.html')  # About Us page

@app.route('/faqs')
def faqs():
    return render_template('faqs.html')  # FAQs page

@app.route('/contact')
def contact():
    return render_template('contact.html')  # Contact Us page

@app.route('/terms')
def terms():
    return render_template('terms.html')  # Ensure this file exists in your templates folder

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

# Function to insert contact message into the database
def insert_message(name, email, content):
    conn = sqlite3.connect('craftconnect.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO contact_messages (name, email, content) 
        VALUES (?, ?, ?)
    ''', (name, email, content))
    conn.commit()
    conn.close()

@app.route('/edit_product/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    if "user_id" not in session or session["user_type"] != "manufacturer":
        flash("You must be logged in as a manufacturer to edit products.", "danger")
        return redirect(url_for("login"))

    with sqlite3.connect("craftconnect.db") as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products WHERE id=?", (product_id,))
        product = cursor.fetchone()

    if not product:
        flash("Product not found.", "danger")
        return redirect(url_for("manage_products"))

    if request.method == "POST":
        name = request.form["name"]
        description = request.form["description"]
        price = request.form["price"]
        
        # 🛠 Check if an image is uploaded
        if "image" in request.files:
            image = request.files["image"]
            if image.filename != "":  # Only update if a new image is provided
                image_path = f"static/uploads/{image.filename}"
                image.save(image_path)
            else:
                image_path = product["image"]  # Keep old image if no new file uploaded
        else:
            image_path = product["image"]  # Keep old image if no file uploaded

        # ✅ Update the product in the database
        with sqlite3.connect("craftconnect.db") as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE products SET name=?, description=?, price=?, image=? WHERE id=?",
                (name, description, price, image_path, product_id),
            )
            conn.commit()

        flash("Product updated successfully.", "success")
        return redirect(url_for("manage_products"))

    return render_template("edit_product.html", product=product)


@app.route('/submit_contact_form', methods=['POST'])
def submit_contact_form():
    name = request.form['name']
    email = request.form['email']
    content = request.form['message']

    insert_message(name, email, content)  # Store the message in the database

    flash('Your message has been sent successfully!', 'success')
    return redirect(url_for('contact'))  # Redirect back to the contact page



@app.route("/cancel_order/<int:order_id>")
def cancel_order(order_id):
    return render_template("cancel.html", order_id=order_id)

@app.route('/confirm_cancel_order/<int:order_id>', methods=['POST'])
def confirm_cancel_order(order_id):
    conn = sqlite3.connect("craftconnect.db")
    cursor = conn.cursor()

    # Check if the order exists
    cursor.execute("SELECT status FROM orders WHERE id = ?", (order_id,))
    order = cursor.fetchone()

    if order:
        # Update status to "Cancelled"
        cursor.execute("UPDATE orders SET status = 'Cancelled' WHERE id = ?", (order_id,))
        conn.commit()

    conn.close()
    flash("Order cancelled successfully!", "info")
    return redirect(url_for('track_order'))  # Return nothing, just update status

@app.route('/manufacturer_orders')
def manufacturer_orders():
    if "user_id" not in session or session["user_type"] != "manufacturer":
        return redirect(url_for("login"))

    manufacturer_id = session["user_id"]  # Get the logged-in manufacturer ID

    conn = sqlite3.connect("craftconnect.db")
    cursor = conn.cursor()

    # Fetch orders where this manufacturer is involved
    cursor.execute("""
        SELECT orders.id, users.username, products.name, orders.quantity, orders.total_price, orders.status
        FROM orders
        JOIN products ON orders.product_id = products.id
        JOIN users ON orders.user_id = users.id
        WHERE orders.manufacturer_id = ?
    """, (manufacturer_id,))

    orders = cursor.fetchall()
    conn.close()

    return render_template("manufacturer_orders.html", orders=orders)


@app.route('/manufacturer_notifications')
def manufacturer_notifications():
    if "user_id" not in session or session["user_type"] != "manufacturer":
        return redirect(url_for("login"))

    manufacturer_id = session["user_id"]

    try:
        with sqlite3.connect("craftconnect.db", timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, message, created_at FROM notifications 
                WHERE manufacturer_id = ? AND is_read = 0
            """, (manufacturer_id,))
            notifications = cursor.fetchall()

        return render_template("manufacturer_notifications.html", notifications=notifications)

    except sqlite3.OperationalError as e:
        print("Database error:", str(e))
        flash("Error fetching notifications.", "danger")
        return redirect(url_for("manufacturer_dashboard"))

@app.route('/update_cart_quantity/<int:product_id>', methods=['POST'])
def update_cart_quantity(product_id):
    new_quantity = request.form.get('quantity', type=int)
    
    if new_quantity and new_quantity > 0:
        conn = sqlite3.connect("craftconnect.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE cart SET quantity = ? WHERE product_id = ?", (new_quantity, product_id))
        conn.commit()
        conn.close()
    
    return redirect(url_for('cart'))

# Function to get database connection
def get_db_connection():
    conn = sqlite3.connect("craftconnect.db")
    conn.row_factory = sqlite3.Row
    return conn

# Route for manufacturer to view customer messages (unchanged)
@app.route('/view_messages/<int:manufacturer_id>')
def view_messages(manufacturer_id):
    if "user_id" not in session or session["user_type"] != "manufacturer":
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch all customers who have sent messages to this manufacturer
    cursor.execute("""
        SELECT DISTINCT customers.id, customers.name
        FROM chat_messages
        JOIN users AS customers ON chat_messages.customer_id = customers.id
        WHERE chat_messages.manufacturer_id = ?
    """, (manufacturer_id,))

    customers = cursor.fetchall()
    conn.close()

    # Pass both customers and manufacturer_id to the template
    return render_template("view_messages.html", customers=customers, manufacturer_id=manufacturer_id)

@app.route('/contact_manufacturer/<int:product_id>/<int:manufacturer_id>/<int:customer_id>', methods=["GET"])
def contact_manufacturer(product_id, manufacturer_id, customer_id):
    try:
        # Connect to the SQLite database
        with sqlite3.connect("craftconnect.db", timeout=10) as conn:
            cursor = conn.cursor()

            # Fetch the manufacturer and customer names
            cursor.execute("SELECT name FROM users WHERE id=?", (manufacturer_id,))
            manufacturer_name = cursor.fetchone()

            cursor.execute("SELECT name FROM users WHERE id=?", (customer_id,))
            customer_name = cursor.fetchone()

            # Fetch the chat history between this manufacturer and customer
            cursor.execute("""
                SELECT customer_id, manufacturer_id, message, timestamp
                FROM chat_messages
                WHERE manufacturer_id=? AND customer_id=?
                ORDER BY timestamp ASC
            """, (manufacturer_id, customer_id))
            chat_messages = cursor.fetchall()

            # Render the chat interface with manufacturer name and chat history
            return render_template(
                "chat_interface.html", 
                manufacturer_name=manufacturer_name[0] if manufacturer_name else "Manufacturer",
                customer_name=customer_name[0] if customer_name else "Customer",
                manufacturer_id=manufacturer_id,
                customer_id=customer_id,
                chat_messages=[
                    {
                        'sender': 'customer' if msg[0] == customer_id else 'manufacturer',  # Determine the sender based on customer_id
                        'message': msg[2],
                        'timestamp': msg[3]
                    } for msg in chat_messages
                ]
            )

    except sqlite3.OperationalError as e:
        print("Database error:", str(e))
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        print("Error:", str(e))
        return jsonify({"error": str(e)}), 500


# New Route to view chat with a selected customer
@app.route('/view_customer_chat/<int:manufacturer_id>/<int:customer_id>')
def view_customer_chat(manufacturer_id, customer_id):
    if "user_id" not in session or session["user_type"] != "manufacturer":
        return redirect(url_for("login"))

    # Fetch chat history between the manufacturer and the specific customer
    conn = get_db_connection()
    cursor = conn.cursor()

    # Modify the query to ignore rows where both customer_id and manufacturer_id are NULL
    cursor.execute("""
        SELECT customer_id, manufacturer_id, message, timestamp
        FROM chat_messages
        WHERE customer_id = ? AND manufacturer_id = ? AND (customer_id IS NOT NULL OR manufacturer_id IS NOT NULL)
        ORDER BY timestamp ASC
    """, (customer_id, manufacturer_id))

    chat_messages = cursor.fetchall()
    conn.close()

    # Convert the fetched messages to include a 'sender' field
    formatted_messages = []
    for message in chat_messages:
        if message['customer_id'] == customer_id:
            sender = 'customer'
        else:
            sender = 'manufacturer'
        formatted_messages.append({
            'sender': sender,
            'message': message['message'],
            'timestamp': message['timestamp']
        })

    # Render the chat interface with chat messages, and pass customer_id and manufacturer_id
    return render_template("chat_interface.html", 
                           chat_messages=formatted_messages, 
                           customer_id=customer_id, 
                           manufacturer_id=manufacturer_id)


# Fetch chat messages via API (unchanged)
@app.route("/get_messages", methods=["GET"])
def get_messages():
    customer_id = request.args.get("customer_id")
    manufacturer_id = request.args.get("manufacturer_id")
    current_user_type = session.get('user_type')  # "customer" or "manufacturer"

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT *,
               CASE 
                   WHEN customer_id IS NOT NULL THEN 'customer' 
                   ELSE 'manufacturer' 
               END AS sender_role
        FROM chat_messages 
        WHERE (customer_id=? AND manufacturer_id=?)
           OR (customer_id=? AND manufacturer_id=?)
        ORDER BY timestamp ASC
    ''', (customer_id, manufacturer_id, manufacturer_id, customer_id))

    messages = []
    for msg in cursor.fetchall():
        msg_dict = dict(msg)
        # Add is_sender flag (True if sender matches logged-in user)
        msg_dict['is_sender'] = (msg_dict['sender_role'] == current_user_type)
        messages.append(msg_dict)

    conn.close()
    return jsonify(messages)

@socketio.on('send_message')
def handle_send_message(data):
    # Check if the message is an image
    is_image = data.get('is_image', False)
    message = data['message'] if not is_image else data['image_url']  # Store URL for image
    sender = data['sender']
    manufacturer_id = data['manufacturer_id']
    customer_id = data['customer_id']

    # Determine whether the sender is the customer or manufacturer
    if sender == 'customer':
        customer_id = session['user_id']
    elif sender == 'manufacturer':
        manufacturer_id = session['user_id']

    # Save the message or image URL in the database
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO chat_messages (customer_id, manufacturer_id, message, is_image) 
        VALUES (?, ?, ?, ?)
    """, (customer_id, manufacturer_id, message, int(is_image)))  # is_image is 1 for image, 0 for text

    conn.commit()
    conn.close()

    # Emit the message or image URL in real-time to the room
    room_id = f"{manufacturer_id}_{customer_id}"
    emit('receive_message', {'message': message, 'sender': sender, 'is_image': is_image}, room=room_id, include_self=False)

import os
from flask import request, jsonify

UPLOAD_FOLDER = os.path.join('static', 'uploads')
  # Update this to the actual path where you store images
@app.route('/upload_image', methods=['POST'])
def upload_image():
    # Get the image file and message data from the request
    image = request.files['image']
    message_data = request.form.get('message_data')
    message_data = json.loads(message_data)  # Convert the JSON string back to a dictionary

    # Extract customer and manufacturer IDs, and other message details
    customer_id = message_data.get('customer_id')
    manufacturer_id = message_data.get('manufacturer_id')
    sender = message_data.get('sender')
    
    # Save the image to your upload folder
    image_filename = image.filename
    image_path = os.path.join(app.config["UPLOAD_FOLDER"], image_filename)
    image.save(image_path)

    # Construct the URL for the image
    image_url = f"/static/uploads/{image_filename}"

    # Save the image message to the database
    conn = get_db_connection()  # Make sure you have a function that returns a DB connection
    cursor = conn.cursor()
    
    # Insert the message into the chat_messages table, setting is_image to 1 and saving image_url
    cursor.execute("""
        INSERT INTO chat_messages (customer_id, manufacturer_id, message, is_image, image_url) 
        VALUES (?, ?, ?, ?, ?)
    """, (customer_id, manufacturer_id, None, 1, image_url))  # message is None for images, image_url is set

    conn.commit()

    # Emit the image message via Socket.IO for real-time communication
    data = {
        "message": None,  # No text message, only image
        "image_url": image_url,
        "customer_id": customer_id,
        "manufacturer_id": manufacturer_id,
        "sender": sender,
        "is_image": True  # Flag this as an image message
    }

    socketio.emit('send_message', data, room=manufacturer_id if sender == 'customer' else customer_id)

    # Return the image URL as a JSON response
    return jsonify({"image_url": image_url})






@socketio.on('join_room')
def on_join(data):
    room_id = data  # The room_id sent from the client
    join_room(room_id)
    print(f"User joined room: {room_id}")


if __name__ == '__main__':
    socketio.run(app, debug=True)
