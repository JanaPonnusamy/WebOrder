from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import json
from dotenv import load_dotenv
from twilio.rest import Client # Import Twilio Client

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
# This is your Twilio WhatsApp number, in the format 'whatsapp:+1234567890'
TWILIO_WHATSAPP_NUMBER = os.environ.get('TWILIO_WHATSAPP_NUMBER')

# Initialize Twilio Client (only if credentials are available)
twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    try:
        twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    except Exception as e:
        print(f"Error initializing Twilio client: {e}")
        twilio_client = None # Ensure it's None if initialization fails
else:
    print("WARNING: Twilio credentials not set. WhatsApp messages will not be sent.")


# Utility: Load users from users.json (for authentication purposes)
def load_users():
    """Loads user data from the users.json file."""
    if not os.path.exists(USERS_FILE) or os.path.getsize(USERS_FILE) == 0:
        print(f"WARNING: {USERS_FILE} not found or is empty. Please ensure it exists with user data.")
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
    """Loads store header data from the storeheader.json file."""
    if not os.path.exists(STORE_HEADERS_FILE) or os.path.getsize(STORE_HEADERS_FILE) == 0:
        print(f"WARNING: {STORE_HEADERS_FILE} not found or is empty. Please ensure it exists with store data.")
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

# Utility: Load order suppliers from OrderSuppliers.json
def load_order_suppliers():
    """Loads order supplier data from the OrderSuppliers.json file."""
    if not os.path.exists(ORDER_SUPPLIERS_FILE) or os.path.getsize(ORDER_SUPPLIERS_FILE) == 0:
        print(f"WARNING: {ORDER_SUPPLIERS_FILE} not found or is empty. Please ensure it exists with supplier data.")
        return []
    try:
        with open(ORDER_SUPPLIERS_FILE, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error decoding OrderSuppliers.json: {e}")
        return []
    except Exception as e:
        print(f"Error reading OrderSuppliers.json: {e}")
        return []

# Utility: Load specific supplier data
def load_supplier_data(supplier_code, store_name=None):
    """
    Loads data for a specific supplier, optionally filtered by store name.
    If store_name is provided and not 'All Stores', it tries to load
    {store_name}_{supplier_code}.json.
    Otherwise, it loads {supplier_code}.json.
    """
    if store_name and store_name != 'All Stores':
        file_name = f"{store_name}_{supplier_code}.json"
    else:
        file_name = f"{supplier_code}.json"
    
    file_path = os.path.join(DATA_DIR, file_name)
    print(f"Attempting to load data from: {file_path}") # Debugging line

    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return [], f"No records found for the selected store ({store_name}) and supplier.", file_name
    
    if os.path.getsize(file_path) == 0:
        print(f"File is empty: {file_path}")
        return [], f"The file for the selected store ({file_name}) is empty.", file_name

    try:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
            print(f"Successfully loaded {len(data)} records from {file_path}") # Debugging line
            return data, "Data loaded successfully.", file_name
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from {file_path}: {e}")
        return [], f"Error: Invalid JSON format in {file_name}.", file_name
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return [], f"Server error reading {file_name}: {str(e)}", file_name


@app.route('/')
def index():
    """Redirects to the login page."""
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles user login."""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        users = load_users()
        order_suppliers = load_order_suppliers()
        
        user = next((u for u in users if u['username'] == username and u['password'] == password), None)

        if user:
            session['logged_in'] = True
            session['username'] = user['username']
            session['supplier_code'] = str(user.get('suppliercode', ''))
            
            # Enrich user session with supplier details from OrderSuppliers.json
            supplier_details = next((s for s in order_suppliers if s.get('suppliercode') == session['supplier_code']), None)
            if supplier_details:
                session['supplier_name'] = supplier_details.get('Suppliername', 'Unknown Supplier')
                session['gst_number'] = supplier_details.get('GSTNumber', 'N/A')
                
                whatsapp_num = supplier_details.get('WhatsAppNumber')
                if whatsapp_num is None or whatsapp_num == '': # Check for None or empty string
                    whatsapp_num = supplier_details.get('MobileNumber')
                
                # Basic formatting for Twilio: ensure it starts with 'whatsapp:+'
                if whatsapp_num:
                    clean_num = ''.join(filter(str.isdigit, whatsapp_num))
                    if not clean_num.startswith('91') and len(clean_num) == 10: # Assuming India for 10-digit numbers
                        whatsapp_num = f'+91{clean_num}'
                    elif not clean_num.startswith('+'): # Add + if missing
                        whatsapp_num = f'+{clean_num}'
                    else:
                        whatsapp_num = clean_num # Use as is if it already has +
                    
                    if not whatsapp_num.startswith('whatsapp:'):
                        whatsapp_num = f'whatsapp:{whatsapp_num}'
                session['whatsapp_number'] = whatsapp_num
            else:
                session['supplier_name'] = user.get('suppliername', 'Unknown Supplier') # Fallback to users.json
                session['gst_number'] = user.get('GSTNumber', 'N/A') # Fallback to users.json
                session['whatsapp_number'] = None # No WhatsApp number if supplier details not found
            
            print(f"User {username} logged in successfully with supplier code {session['supplier_code']}")
            return redirect(url_for('dashboard'))
        else:
            print(f"Login failed for username: {username}")
            return render_template('login.html', error='Invalid credentials')
    return render_template('login.html', error=None)

@app.route('/dashboard')
def dashboard():
    """Renders the dashboard page, requiring login."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    supplier_code = session.get('supplier_code')
    supplier_name = session.get('supplier_name')
    gst_number = session.get('gst_number')

    return render_template(
        'dashboard.html', 
        supplier_name=supplier_name,
        gst_number=gst_number,
        supplier_code=supplier_code # Pass supplier_code to JS for dynamic file naming
    )

@app.route('/get_orders')
def get_orders():
    """
    Retrieves paginated order data for the logged-in supplier,
    optionally filtered by store name.
    """
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    supplier_code = session.get('supplier_code')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    store_name = request.args.get('storename', None) # Get storename from query params

    all_supplier_data, message, file_name = load_supplier_data(supplier_code, store_name)

    if not all_supplier_data:
        return jsonify({
            'success': True, # Indicate that the request was processed, even if no data
            'data': [], 
            'total_count': 0, 
            'page': page, 
            'per_page': per_page,
            'error': message # Use error key for message in this case
        })

    # Add 'remarks' field if it's missing for any item
    # Also ensure OrderQty is a string for consistency in the frontend input
    for item in all_supplier_data:
        item['remarks'] = item.get('remarks', '')
        item['OrderQty'] = str(item['OrderQty']) # Ensure it's a string for input value

    # Sort data by SerialNo for consistent pagination
    try:
        all_supplier_data.sort(key=lambda x: int(x.get('SerialNo', 0)))
    except ValueError:
        # Fallback if SerialNo is not always an integer
        print("Warning: SerialNo not purely numeric, sorting might be inconsistent.")
        pass

    total_count = len(all_supplier_data)
    
    # Apply pagination
    start_index = (page - 1) * per_page
    end_index = start_index + per_page
    paginated_data = all_supplier_data[start_index:end_index]

    return jsonify({
        'success': True,
        'data': paginated_data,
        'total_count': total_count,
        'page': page,
        'per_page': per_page
    })

@app.route('/update_orders', methods=['POST'])
def update_orders():
    """
    Updates order quantities and remarks in the relevant JSON file.
    Determines the file to update based on `currentStore` sent from frontend.
    """
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    try:
        data = request.get_json()
        updated_items = data.get('updatedData', [])
        current_store = data.get('currentStore', None) # Get current store from frontend
        supplier_code = session.get('supplier_code')
        user_whatsapp_number = session.get('whatsapp_number') 

        if not updated_items:
            return jsonify({'success': False, 'message': 'No data provided for update.'})

        # Determine the file name based on the current store
        if current_store and current_store != 'All Stores':
            file_name = f"{current_store}_{supplier_code}.json"
        else:
            file_name = f"{supplier_code}.json"

        file_path = os.path.join(DATA_DIR, file_name)

        if not os.path.exists(file_path):
            return jsonify({'success': False, 'message': f'Data file for {file_name} not found.'})

        current_data = []
        if os.path.getsize(file_path) > 0:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                current_data = json.load(f)
        else:
            return jsonify({'success': False, 'message': f'Data file for {file_name} is empty.'})

        changes_made = False
        updates_for_whatsapp = {} # To aggregate updates for WhatsApp message

        for updated_item in updated_items:
            # Create a unique key for lookup, ensuring all identifying fields are used
            product_code = updated_item['ProductCode']
            product_name = updated_item.get('ProductName', 'N/A') # Get product name for message
            order_id = updated_item['OrderId']
            store_name = updated_item['StoreName'] 

            for i, item in enumerate(current_data):
                if (item.get('ProductCode') == product_code and
                    item.get('OrderId') == order_id and
                    item.get('StoreName') == store_name):
                    
                    old_qty = str(item.get('OrderQty', '0'))
                    old_remarks = item.get('remarks', '')

                    new_qty = str(updated_item['OrderQty']) 
                    new_remarks = updated_item['remarks']

                    if old_qty != new_qty or old_remarks != new_remarks:
                        item['OrderQty'] = new_qty
                        item['remarks'] = new_remarks
                        changes_made = True
                        
                        # Aggregate for WhatsApp message
                        if order_id not in updates_for_whatsapp:
                            updates_for_whatsapp[order_id] = {'store_name': store_name, 'products': []}
                        updates_for_whatsapp[oid]['products'].append(
                            f"- {product_name}: Qty {old_qty} -> {new_qty}" + 
                            (f", Remarks: '{new_remarks}'" if new_remarks else "")
                        )
                    break 

        if changes_made:
            with open(file_path, 'w', encoding='utf-8-sig') as f:
                json.dump(current_data, f, indent=2, ensure_ascii=False) # Pretty print JSON
            
            # Send WhatsApp message if user has a number and changes were made
            if user_whatsapp_number and TWILIO_WHATSAPP_NUMBER and twilio_client:
                for oid, details in updates_for_whatsapp.items():
                    message_body = (
                        f"Order Update for Supplier: {session.get('supplier_name', 'N/A')}\n"
                        f"Store: {details['store_name']}\n"
                        f"Order ID: {oid}\n"
                        + "\n".join(details['products'])
                    )
                    send_whatsapp_message(user_whatsapp_number, message_body)

            return jsonify({'success': True, 'message': 'Orders updated successfully.'})
        else:
            return jsonify({'success': False, 'message': 'No changes to submit or no matching items found for update.'})

    except json.JSONDecodeError as e:
        print(f"Error decoding JSON file {file_path}: {e}")
        return jsonify({'success': False, 'message': f'Error: Invalid JSON format in {file_name}.'})
    except Exception as e:
        print(f"Error updating orders in {file_path}: {e}")
        return jsonify({'success': False, 'message': f'Server error updating {file_name}: {str(e)}'})

@app.route('/get_store_headers')
def get_store_headers():
    """Returns the list of store headers."""
    store_headers = load_store_headers()
    return jsonify({'data': store_headers})

def send_whatsapp_message(to_number, message_body):
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

# This section ensures that initial data files (if missing) are created
# with dummy content upon application startup for demonstration purposes.
# In a real production environment, you would manage these files differently.
if __name__ == '__main__':
    # Ensure data directory exists
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # In a production environment, ensure that 'users.json', 'OrderSuppliers.json', 
    # 'storeheader.json', and all supplier-specific JSON files (e.g., '117.json', 
    # 'NMC_117.json') are present in the 'data' directory when the application starts.
    # The application will now only attempt to load these files.
    app.run(debug=True, port=5000)
