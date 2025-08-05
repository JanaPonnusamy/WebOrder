from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import json
from functools import wraps

# Define the Flask application
app = Flask(__name__)
# IMPORTANT: Use a strong, unique secret key in a production environment
app.secret_key = 'your_secret_key_here'

# Paths to data directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data') 

# Define file paths
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
STORE_HEADERS_FILE = os.path.join(DATA_DIR, 'storeheader.json')

# Helper function to load JSON data
def load_json(file_path):
    """Loads and returns data from a JSON file."""
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        print(f"Error decoding JSON from {file_path}")
        return []

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    """Redirects to the login page."""
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles user login and redirects to the dashboard."""
    if request.method == 'POST':
        # Get data from the form
        username = request.form.get('username')
        password = request.form.get('password')
        store_name = request.form.get('storename')

        users = load_json(USERS_FILE)
        # Find the user based on username and password
        user = next((u for u in users if u['username'] == username and u['password'] == password), None)

        if user:
            # Store user and store info in the session
            session['logged_in'] = True
            session['username'] = username
            session['storename'] = store_name
            session['suppliercode'] = user['suppliercode']
            return jsonify({'success': True, 'redirect_url': url_for('dashboard')})
        else:
            return jsonify({'success': False, 'error': 'Invalid username or password'})
    
    # For GET request, render the login page
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Logs out the user by clearing the session."""
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    """Renders the dashboard page."""
    return render_template('dashboard.html')

@app.route('/get_store_headers', methods=['GET'])
def get_store_headers():
    """Returns a list of store headers from the JSON file."""
    store_headers = load_json(STORE_HEADERS_FILE)
    return jsonify({'data': store_headers})

@app.route('/get_orders', methods=['GET'])
@login_required
def get_orders():
    """
    Returns a filtered list of orders based on the logged-in user's
    supplier code and store name from the session.
    """
    store_name = session.get('storename')
    supplier_code = session.get('suppliercode')
    
    # Load all orders
    all_orders = load_json(os.path.join(DATA_DIR, 'OrderSuppliers.json'))
    
    # Filter orders based on the session data
    # NOTE: Assuming suppliercode can be a comma-separated string
    allowed_supplier_codes = supplier_code.split(',') if supplier_code else []
    
    filtered_orders = [
        order for order in all_orders 
        if order.get('StoreName') == store_name and 
           order.get('suppliercode') in allowed_supplier_codes
    ]
    
    return jsonify({'data': filtered_orders})

if __name__ == '__main__':
    # Ensure data directory and files exist with dummy content
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # This section creates dummy data if the files are missing
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'w') as f:
            json.dump([
              {"username": "117", "password": "pass", "suppliercode": "117", "suppliername": "NATHAN MEDICAL AGENCIES", "GSTNumber": "Test"},
              {"username": "user2", "password": "pass", "suppliercode": "001,006", "suppliername": "Multiple Suppliers", "GSTNumber": "Test"}
            ], f, indent=2)

    if not os.path.exists(STORE_HEADERS_FILE):
        with open(STORE_HEADERS_FILE, 'w') as f:
            json.dump([
              {"StoreCode": "6", "StoreName": "NMS", "StoreFullName": "Nathan Medicals S", "Address1": "Near Police Station", "Address2": "Perundurai"},
              {"StoreCode": "7", "StoreName": "NMC", "StoreFullName": "Nathan Medicals C", "Address1": "Old Bus Stand", "Address2": "Perundurai"}
            ], f, indent=2)

    if not os.path.exists(os.path.join(DATA_DIR, 'OrderSuppliers.json')):
        with open(os.path.join(DATA_DIR, 'OrderSuppliers.json'), 'w') as f:
            json.dump([
              {"suppliercode": "117", "Suppliername": "NATHAN MEDICAL AGENCIES", "StoreName": "NMS", "order_details": "Order for store NMS from supplier 117."},
              {"suppliercode": "001", "Suppliername": "S.K. AGENCY", "StoreName": "NMC", "order_details": "Order for store NMC from supplier 001."},
              {"suppliercode": "006", "Suppliername": "SHARADHA MEDICALS", "StoreName": "NMC", "order_details": "Order for store NMC from supplier 006."}
            ], f, indent=2)

    app.run(debug=True)
