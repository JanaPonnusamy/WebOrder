from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import json
from dotenv import load_dotenv
from twilio.rest import Client # Import Twilio Client
from functools import wraps

# Load environment variables (from webapp.env locally, or from Render config)
load_dotenv('webapp.env')

app = Flask(__name__)
# IMPORTANT: Use a strong, unique secret key in a production environment
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your_default_secret_key_here')

# Paths to data directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data') # Assuming your JSON files are in a 'data' folder
USERS_FILE = os.path.join(DATA_DIR, 'users.json') 
ORDER_SUPPLIERS_FILE = os.path.join(DATA_DIR, 'OrderSuppliers.json') 
STORE_HEADERS_FILE = os.path.join(DATA_DIR, 'storeheader.json')

# Ensure DATA_DIR exists
os.makedirs(DATA_DIR, exist_ok=True)

# Twilio Configuration
# These will be set as environment variables on Render
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
# This is your Twilio WhatsApp number, in the format 'whatsapp:+1...'
TWILIO_WHATSAPP_NUMBER = os.environ.get('TWILIO_WHATSAPP_NUMBER')

# Initialize Twilio client if credentials are provided
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    print("Twilio client initialized.")
else:
    twilio_client = None
    print("Twilio credentials not found. WhatsApp functionality will be disabled.")


# Helper function to load JSON data
def load_json(file_path):
    """
    Loads and returns data from a JSON file.
    Uses 'utf-8-sig' encoding to handle files with a Byte Order Mark (BOM).
    """
    try:
        # Use 'utf-8-sig' to correctly decode JSON files that might have a BOM
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: The file {file_path} was not found.")
        return []
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from {file_path}: {e}")
        return []

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Routes ---

@app.route('/')
@login_required
def index():
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.json
        username = data.get('username')
        password = data.get('password')
        storename = data.get('storename')
        
        users = load_json(USERS_FILE)
        
        user = next((u for u in users if u['username'] == username and u['password'] == password), None)

        if user:
            session['logged_in'] = True
            session['username'] = user['username']
            session['suppliercode'] = user['suppliercode']
            session['suppliername'] = user['suppliername']
            session['storename'] = storename
            print(f"User {username} logged in successfully for store {storename}.")
            return jsonify({'success': True, 'redirect_url': url_for('dashboard')})
        else:
            print(f"Login failed for user {username}.")
            return jsonify({'success': False, 'error': 'Invalid username or password'}), 401

    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template(
        'dashboard.html',
        supplier_code=session.get('suppliercode', ''),
        supplier_name=session.get('suppliername', ''),
        store_name=session.get('storename', '')
    )

@app.route('/get_supplier_info')
@login_required
def get_supplier_info():
    data = load_json(ORDER_SUPPLIERS_FILE)
    return jsonify(data)

@app.route('/get_store_headers')
def get_store_headers():
    """Returns a list of all store headers."""
    store_headers = load_json(STORE_HEADERS_FILE)
    if store_headers:
        return jsonify({'success': True, 'data': store_headers})
    else:
        return jsonify({'success': False, 'error': 'Could not load store data.'})

@app.route('/get_orders/<string:storename>/<string:suppliercode>', methods=['GET'])
@login_required
def get_orders(storename, suppliercode):
    """
    Fetches order details for a specific store and supplier.
    Maps raw JSON keys (like productcode) to frontend-expected keys (ProductCode).
    """
    # Sanitize inputs
    sanitized_storename = os.path.basename(storename)
    sanitized_suppliercode = os.path.basename(suppliercode)

    # Normalize StoreFullName → StoreName
    store_headers = load_json(STORE_HEADERS_FILE)
    matched = next((s for s in store_headers if s['StoreFullName'] == sanitized_storename), None)
    actual_storename = matched['StoreName'] if matched else sanitized_storename

    filename = f"{actual_storename}_{sanitized_suppliercode}.json"
    file_path = os.path.join(DATA_DIR, filename)

    raw_orders = load_json(file_path)

    if not raw_orders:
        return jsonify({'success': True, 'data': [], 'message': 'No orders found.'})

    normalized_orders = []
    for item in raw_orders:
        normalized = {
    "SerialNo": item.get("SerialNo", ""),
    "ProductCode": item.get("productcode", ""),
    "ProductName": item.get("productname", ""),
    "OrderQty": str(item.get("orderqty", "")),
    "Pack": item.get("saleunit", ""),  # Add this
    "MRP": item.get("mrp", ""),         # Add this
    "remarks": item.get("remarks", "Available ✅"),  # Default
    "OrderId": item.get("OrderId", ""),
    "StoreName": item.get("StoreName", "")
}

        normalized_orders.append(normalized)

    return jsonify({'success': True, 'data': normalized_orders})


@app.route('/send_whatsapp_message', methods=['POST'])
@login_required
def send_whatsapp_message():
    """Sends a WhatsApp message based on the data in the request."""
    if not twilio_client:
        return jsonify({'success': False, 'error': 'WhatsApp functionality is not configured.'}), 500

    data = request.json
    store_name = data.get('store_name')
    supplier_code = data.get('supplier_code')

    if not all([store_name, supplier_code]):
        return jsonify({'success': False, 'error': 'Missing store name or supplier code.'}), 400

    # Find the supplier's WhatsApp number from OrderSuppliers.json
    order_suppliers = load_json(ORDER_SUPPLIERS_FILE)
    supplier = next((s for s in order_suppliers if s['StoreName'] == store_name and s['suppliercode'] == supplier_code), None)

    if not supplier or not supplier.get('WhatsAppNumber'):
        return jsonify({'success': False, 'error': 'Supplier or WhatsApp number not found.'}), 404

    whatsapp_number = supplier['WhatsAppNumber']
    
    # Get the order data
    orders_file_path = os.path.join(DATA_DIR, f"{store_name}_{supplier_code}.json")
    orders = load_json(orders_file_path)
    
    if not orders:
        return jsonify({'success': False, 'error': 'No orders to send.'}), 404

    # Format the message
    message_body = f"Hello {supplier.get('Suppliername', 'Supplier')},\n\nNew order from {store_name}:\n\n"
    for item in orders:
        message_body += f"- {item['product']} (Qty: {item['quantity']})\n"
    message_body += "\nThank you!"

    # Send the message
    success = send_whatsapp(whatsapp_number, message_body)

    if success:
        return jsonify({'success': True, 'message': 'WhatsApp message sent successfully!'})
    else:
        return jsonify({'success': False, 'error': 'Failed to send WhatsApp message.'}), 500


def send_whatsapp(to_number, message_body):
    """Sends a WhatsApp message using Twilio."""
    if not twilio_client or not TWILIO_WHATSAPP_NUMBER:
        print("Twilio client not initialized or sender number missing. Cannot send WhatsApp message.")
        return False

    try:
        message = twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=message_body,
            to=to_number 
        )
        print(f"WhatsApp message sent to {to_number}. SID: {message.sid}")
        return True
    except Exception as e:
        print(f"Error sending WhatsApp message to {to_number}: {e}")
        return False

@app.route('/logout')
def logout():
    """Logs out the user by clearing the session."""
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
