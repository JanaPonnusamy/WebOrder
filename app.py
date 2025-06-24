from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import json
from dotenv import load_dotenv

# Load environment variables (if any, though not strictly needed for JSON-only)
load_dotenv('webapp.env')

app = Flask(__name__)
# IMPORTANT: Use a strong, unique secret key in a production environment
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your_default_secret_key_here')

# Paths to data directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data') # Assuming your JSON files are in a 'data' folder
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
STORE_HEADERS_FILE = os.path.join(DATA_DIR, 'storeheader.json') # New: Path to storeheader.json

# Ensure DATA_DIR exists
os.makedirs(DATA_DIR, exist_ok=True)

# Utility: Load users from users.json
def load_users():
    if not os.path.exists(USERS_FILE) or os.path.getsize(USERS_FILE) == 0:
        return []
    try:
        with open(USERS_FILE, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error decoding users.json: {e}")
        return []
    except Exception as e:
        print(f"Error reading users.json: {e}")
        return []

# Utility: Load store headers from storeheader.json
def load_store_headers():
    if not os.path.exists(STORE_HEADERS_FILE) or os.path.getsize(STORE_HEADERS_FILE) == 0:
        return []
    try:
        with open(STORE_HEADERS_FILE, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error decoding storeheader.json: {e}")
        return []
    except Exception as e:
        print(f"Error reading storeheader.json: {e}")
        return []

# Utility: Check credentials in Users data
def check_login(username, password):
    users = load_users()
    for user in users:
        if user.get('username') == username and user.get('password') == password:
            # Return full user object on successful login to get suppliername and GSTNumber
            return user
    return None

@app.before_request
def require_login():
    allowed_endpoints = ['login', 'static', 'get_orders', 'update_orders']
    if 'user' not in session and request.endpoint not in allowed_endpoints and not request.path.startswith('/logout'):
        return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
def login():
    error = ''
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user_data = check_login(username, password) # Get the full user object
        if user_data:
            session['user'] = user_data.get('username')
            session['suppliercode'] = user_data.get('suppliercode')
            session['suppliername'] = user_data.get('suppliername') # Store suppliername
            session['GSTNumber'] = user_data.get('GSTNumber')     # Store GSTNumber
            return redirect(url_for('dashboard'))
        else:
            error = 'Invalid credentials. Try again.'
    return render_template('login.html', error=error)

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    store_headers = load_store_headers()
    supplier_name = session.get('suppliername', 'N/A')
    gst_number = session.get('GSTNumber', 'N/A')

    # Assuming 'NMC' is the default/selected store for display
    # You might expand this to allow selection if needed
    current_store = next((store for store in store_headers if store.get('StoreName') == 'NMC'), None)
    
    # Pass store and supplier details to the template
    return render_template('dashboard.html', 
                           user=session['user'],
                           store=current_store,
                           supplier_name=supplier_name,
                           gst_number=gst_number)

# Return supplier-specific paginated order data from JSON file
@app.route('/get_orders')
def get_orders():
    suppliercode = session.get('suppliercode')
    # Default storename if not provided by request, based on previous data
    storename_filter = request.args.get('storename', 'NMC')

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int) # ITEMS_PER_PAGE from frontend
    
    file_path = os.path.join(DATA_DIR, f"{suppliercode}.json")

    orders_data = []
    total_count = 0

    if not suppliercode or not os.path.exists(file_path):
        return jsonify({'data': [], 'total_count': 0})

    try:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            full_data = json.load(f)
            
            # Filter by StoreName first (assuming 'NMC' is the default/only one for now)
            # You can expand this if you need dynamic store selection for JSON files
            filtered_data = [
                item for item in full_data 
                if item.get('StoreName') == storename_filter and item.get('OrderQty') is not None and int(item['OrderQty']) > 0
            ]
            
            # Sort data (e.g., by ProductName as per previous SQL query)
            filtered_data.sort(key=lambda x: x.get('ProductName', '').lower())

            total_count = len(filtered_data)
            
            # Apply pagination
            offset = (page - 1) * per_page
            paginated_data = filtered_data[offset : offset + per_page]

            # Add SerialNo to each item based on its position in the paginated list
            results = []
            for idx, item in enumerate(paginated_data, start=offset + 1):
                item_copy = item.copy() # Avoid modifying original data directly if not desired
                item_copy['SerialNo'] = idx # Absolute serial number
                # Ensure remarks is always a string
                item_copy['Remarks'] = item_copy.get('remarks', '') if item_copy.get('remarks') is not None else ''
                # Ensure OrderQty is an integer for comparisons later
                item_copy['OrderQty'] = int(item_copy.get('OrderQty', 0))
                results.append(item_copy)
            
        return jsonify({'data': results, 'total_count': total_count})

    except json.JSONDecodeError as e:
        print(f"Error decoding JSON file {file_path}: {e}")
        return jsonify({'data': [], 'total_count': 0, 'error': 'Invalid JSON format'})
    except Exception as e:
        print(f"Error fetching orders from {file_path}: {e}")
        return jsonify({'data': [], 'total_count': 0, 'error': str(e)})

# Update supplier order file
@app.route('/update_orders', methods=['POST'])
def update_orders():
    suppliercode = session.get('suppliercode')
    updated_items = request.json.get('updatedData')

    if not suppliercode or not updated_items:
        return jsonify({'success': False, 'message': 'Invalid update data'})

    file_path = os.path.join(DATA_DIR, f"{suppliercode}.json")

    if not os.path.exists(file_path):
        return jsonify({'success': False, 'message': 'Supplier data file not found.'})

    try:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            current_data = json.load(f)

        data_changed = False
        for update_item in updated_items:
            product_code = update_item.get('ProductCode')
            order_id = update_item.get('OrderId')
            
            # Find the item in current_data to update
            found = False
            for item in current_data:
                if item.get('ProductCode') == product_code and item.get('OrderId') == order_id:
                    # Update fields
                    item['OrderQty'] = str(update_item.get('OrderQty')) # Store as string as per original JSON structure
                    item['remarks'] = update_item.get('remarks')
                    # You might also update other fields like 'Status' here if needed
                    data_changed = True
                    found = True
                    break
            if not found:
                print(f"Warning: Item not found for update - ProductCode: {product_code}, OrderId: {order_id}")

        if data_changed:
            with open(file_path, 'w', encoding='utf-8-sig') as f:
                json.dump(current_data, f, indent=2, ensure_ascii=False) # Pretty print JSON
            return jsonify({'success': True, 'message': 'Orders updated successfully.'})
        else:
            return jsonify({'success': False, 'message': 'No matching items found for update or no changes detected.'})

    except json.JSONDecodeError as e:
        print(f"Error decoding JSON file {file_path}: {e}")
        return jsonify({'success': False, 'message': 'Error: Invalid JSON format in supplier data file.'})
    except Exception as e:
        print(f"Error updating orders in {file_path}: {e}")
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    # Ensure data directory exists
    os.makedirs(DATA_DIR, exist_ok=True)
    # Create a dummy users.json if it doesn't exist for testing
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump([{"username": "testuser", "password": "password", "suppliercode": "72", "suppliername": "Test Supplier Co.", "GSTNumber": "GST12345"}], f, indent=2)
            print(f"Created a default {USERS_FILE} for testing.")
    
    # Create a dummy storeheader.json if it doesn't exist for testing
    if not os.path.exists(STORE_HEADERS_FILE):
        with open(STORE_HEADERS_FILE, 'w', encoding='utf-8') as f:
            json.dump([
                {"StoreCode": "7", "StoreName": "NMC", "StoreFullName": "Nathan Medicals C", "Address1": "Old Bus Stand", "Address2": "Perundurai"},
                {"StoreCode": "6", "StoreName": "NMS", "StoreFullName": "Nathan Medicals S", "Address1": "Near Police Station", "Address2": "Perundurai"}
            ], f, indent=2)
            print(f"Created a default {STORE_HEADERS_FILE} for testing.")

    # You might want to create a dummy 72.json as well if it doesn't exist
    # For this, copy one of your existing JSON data files into the 'data' folder
    # Example for 72.json
    dummy_supplier_data_file = os.path.join(DATA_DIR, '72.json')
    if not os.path.exists(dummy_supplier_data_file):
        with open(dummy_supplier_data_file, 'w', encoding='utf-8') as f:
            json.dump([
                {"ProductCode": "P001", "ProductName": "Dummy Product A", "OrderQty": "5", "SaleUnit": "Pcs", "remarks": "", "MRP": "100", "ORSUPPLIER": "SupX", "OrderId": "ORD001", "StoreName": "NMC"},
                {"ProductCode": "P002", "ProductName": "Dummy Product B", "OrderQty": "10", "SaleUnit": "Boxes", "remarks": "Only 8 available", "MRP": "250", "ORSUPPLIER": "SupY", "OrderId": "ORD002", "StoreName": "NMC"},
                {"ProductCode": "P003", "ProductName": "Dummy Product C", "OrderQty": "2", "SaleUnit": "Kg", "remarks": "Not Available", "MRP": "50", "ORSUPPLIER": "SupZ", "OrderId": "ORD003", "StoreName": "NMC"}
            ], f, indent=2)
            print(f"Created a default {dummy_supplier_data_file} for testing.")
    
    app.run(debug=True)