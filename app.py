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
    if not os.path.exists(USERS_FILE) or os.path.getsize(USERS_FILE) == 0:
        print(f"WARNING: {USERS_FILE} not found or is empty. Please ensure it exists with user data.")
        return []
    try:
        with open(USERS_FILE, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error decoding {USERS_FILE}: {e}")
        return []
    except Exception as e:
        print(f"Error reading {USERS_FILE}: {e}")
        return []

# Utility: Load OrderSuppliers.json (for enriching session data with supplier details)
def load_order_suppliers():
    if not os.path.exists(ORDER_SUPPLIERS_FILE) or os.path.getsize(ORDER_SUPPLIERS_FILE) == 0:
        print(f"WARNING: {ORDER_SUPPLIERS_FILE} not found or is empty. This file is crucial for supplier details.")
        return []
    try:
        with open(ORDER_SUPPLIERS_FILE, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error decoding {ORDER_SUPPLIERS_FILE}: {e}")
        return []
    except Exception as e:
        print(f"Error reading {ORDER_SUPPLIERS_FILE}: {e}")
        return []

# Utility: Load store headers from storeheader.json
def load_store_headers():
    if not os.path.exists(STORE_HEADERS_FILE) or os.path.getsize(STORE_HEADERS_FILE) == 0:
        print(f"WARNING: {STORE_HEADERS_FILE} not found or is empty. Store dropdown might be empty.")
        return []
    try:
        with open(STORE_HEADERS_FILE, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error decoding {STORE_HEADERS_FILE}: {e}")
        return []
    except Exception as e:
        print(f"Error reading {STORE_HEADERS_FILE}: {e}")
        return []

# Utility: Check credentials in Users data and enrich with OrderSuppliers data
def check_login(username, password):
    users = load_users()
    order_suppliers = load_order_suppliers()

    authenticated_user = None
    for user in users:
        # Authenticate using username and password from users.json
        if user.get('username') == username and user.get('password') == password:
            authenticated_user = user
            break
    
    if authenticated_user:
        # Find the matching supplier in OrderSuppliers.json based on suppliercode
        supplier_code_from_user = authenticated_user.get('suppliercode')
        supplier_details = next((s for s in order_suppliers if s.get('suppliercode') == supplier_code_from_user), None)
        
        if supplier_details:
            # Combine details for the session
            # Prioritize WhatsAppNumber if available, otherwise MobileNumber
            whatsapp_num = supplier_details.get('WhatsAppNumber')
            if whatsapp_num is None or whatsapp_num == '': # Check for None or empty string
                whatsapp_num = supplier_details.get('MobileNumber')
            
            # Ensure proper formatting for Twilio (starts with 'whatsapp:+') if it's a raw number
            # This is a basic attempt, for production you'd need more robust validation
            if whatsapp_num and not whatsapp_num.startswith('whatsapp:'):
                # Basic cleanup: remove non-digits and add country code if missing (assuming +91 for India)
                clean_num = ''.join(filter(str.isdigit, whatsapp_num))
                if len(clean_num) == 10 and not clean_num.startswith('91'): # Assumes 10 digit Indian number
                    whatsapp_num = f'+91{clean_num}'
                elif len(clean_num) > 10 and clean_num.startswith('91'):
                     whatsapp_num = f'+{clean_num}'
                else:
                    whatsapp_num = f'+{clean_num}' # Fallback for other formats, Twilio will validate

                if not whatsapp_num.startswith('whatsapp:'): # Add whatsapp: prefix if not present
                    whatsapp_num = f'whatsapp:{whatsapp_num}'
            
            user_session_data = {
                'username': authenticated_user.get('username'),
                'suppliercode': supplier_code_from_user,
                'suppliername': supplier_details.get('Suppliername', 'N/A'),
                'GSTNumber': supplier_details.get('GSTNumber', 'N/A'), # Use GSTNumber from OrderSuppliers if present
                'MobileNumber': supplier_details.get('MobileNumber', ''),
                'WhatsAppNumber': whatsapp_num # Store the formatted WhatsApp number
            }
            return user_session_data
    return None

# Function to send WhatsApp message via Twilio
def send_whatsapp_message(to_number, message_body):
    if not twilio_client or not TWILIO_WHATSAPP_NUMBER:
        print("Twilio client not initialized or sender number missing. Cannot send WhatsApp message.")
        return False

    try:
        # Twilio requires the 'from_' number to be in 'whatsapp:+1234567890' format
        message = twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=message_body,
            to=f'{to_number}' # Recipient number should already be in 'whatsapp:+1234567890' format from session
        )
        print(f"WhatsApp message sent to {to_number}. SID: {message.sid}")
        return True
    except Exception as e:
        print(f"Error sending WhatsApp message to {to_number}: {e}")
        return False

@app.before_request
def require_login():
    allowed_endpoints = ['login', 'static', 'get_orders', 'update_orders', 'get_store_headers']
    if 'user' not in session and request.endpoint not in allowed_endpoints and not request.path.startswith('/logout'):
        return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
def login():
    error = ''
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user_data = check_login(username, password) # Get the full user object with enriched data
        if user_data:
            session['user'] = user_data.get('username')
            session['suppliercode'] = user_data.get('suppliercode')
            session['suppliername'] = user_data.get('suppliername') # Store suppliername
            session['GSTNumber'] = user_data.get('GSTNumber')     # Store GSTNumber
            session['whatsapp_number'] = user_data.get('WhatsAppNumber') # Store WhatsApp number (already formatted)
            return redirect(url_for('dashboard'))
        else:
            error = 'Invalid credentials. Try again.'
    return render_template('login.html', error=error)

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    supplier_name = session.get('suppliername', 'N/A')
    gst_number = session.get('GSTNumber', 'N/A')
    supplier_code = session.get('suppliercode', 'N/A') 
    
    return render_template('dashboard.html', 
                           user=session['user'],
                           supplier_name=supplier_name,
                           gst_number=gst_number,
                           supplier_code=supplier_code) 

# Return supplier-specific paginated order data from JSON file
@app.route('/get_orders')
def get_orders():
    suppliercode = session.get('suppliercode')
    storename_filter = request.args.get('storename') 

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int) 
    
    # Construct the file path based on storename_filter and suppliercode
    # If storename_filter is 'All Stores', it should load the main supplier file (e.g., 117.json)
    # Otherwise, it should load the specific store-supplier file (e.g., NMC_117.json)
    if storename_filter and storename_filter != 'All Stores':
        file_name = f"{storename_filter}_{suppliercode}.json"
    else:
        file_name = f"{suppliercode}.json"

    file_path = os.path.join(DATA_DIR, file_name)

    orders_data = []
    total_count = 0

    if not suppliercode or not os.path.exists(file_path):
        # Provide a more specific error message based on the file expected
        error_message = f"Order file '{file_name}' for supplier {suppliercode} not found in the 'data' directory."
        print(f"ERROR: {error_message}")
        return jsonify({'data': [], 'total_count': 0, 'error': error_message})

    try:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            full_data = json.load(f)
            
            # The filtering logic now assumes the correct file is already loaded.
            # We still keep the OrderQty > 0 filter as it was initially for display.
            filtered_data = [
                item for item in full_data 
                if item.get('OrderQty') is not None and int(item['OrderQty']) > 0
            ]
            
            # Sort data (e.g., by ProductName)
            filtered_data.sort(key=lambda x: x.get('ProductName', '').lower())

            total_count = len(filtered_data)
            
            # Apply pagination
            offset = (page - 1) * per_page
            paginated_data = filtered_data[offset : offset + per_page]

            # Add SerialNo to each item based on its position in the paginated list
            results = []
            for idx, item in enumerate(paginated_data, start=offset + 1):
                item_copy = item.copy() 
                item_copy['SerialNo'] = idx 
                item_copy['Remarks'] = item_copy.get('remarks', '') if item_copy.get('remarks') is not None else ''
                try:
                    item_copy['OrderQty'] = int(item_copy.get('OrderQty', 0))
                except ValueError:
                    item_copy['OrderQty'] = 0 
                results.append(item_copy)
            
        return jsonify({'data': results, 'total_count': total_count})

    except json.JSONDecodeError as e:
        print(f"Error decoding JSON file {file_path}: {e}")
        return jsonify({'data': [], 'total_count': 0, 'error': f'Invalid JSON format in {file_name}.'})
    except Exception as e:
        print(f"Error fetching orders from {file_path}: {e}")
        return jsonify({'data': [], 'total_count': 0, 'error': f'Server error reading {file_name}: {str(e)}'})

# Update supplier order file
@app.route('/update_orders', methods=['POST'])
def update_orders():
    suppliercode = session.get('suppliercode')
    updated_items = request.json.get('updatedData')
    user_whatsapp_number = session.get('whatsapp_number') 
    
    # Determine which file to update based on the store name of the first item
    # This assumes all updated items in a single request belong to the same store.
    # If not, this logic would need to be more complex to update multiple files.
    file_to_update_storename = None
    if updated_items:
        file_to_update_storename = updated_items[0].get('StoreName')

    if file_to_update_storename and file_to_update_storename != 'All Stores':
        file_name = f"{file_to_update_storename}_{suppliercode}.json"
    else:
        # If 'All Stores' was selected, or if the update request doesn't specify a store for the item,
        # we default to the main supplier file (e.g., 117.json).
        # This part might need adjustment based on how your VB app generates / expects updates for 'All Stores'.
        file_name = f"{suppliercode}.json"

    file_path = os.path.join(DATA_DIR, file_name)

    if not suppliercode or not updated_items:
        return jsonify({'success': False, 'message': 'Invalid update data'})

    if not os.path.exists(file_path):
        return jsonify({'success': False, 'message': f"Supplier data file '{file_name}' not found."})

    try:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            current_data = json.load(f)

        data_changed = False
        updates_by_order_id = {}

        for update_item in updated_items:
            product_code = update_item.get('ProductCode')
            product_name = update_item.get('ProductName')
            order_id = update_item.get('OrderId')
            item_store_name = update_item.get('StoreName') 

            found = False
            for item in current_data:
                if item.get('ProductCode') == product_code and \
                   item.get('OrderId') == order_id and \
                   item.get('StoreName') == item_store_name: 
                    
                    old_order_qty = int(item.get('OrderQty', 0))
                    old_remarks = item.get('remarks', '')

                    item['OrderQty'] = str(update_item.get('OrderQty'))
                    item['remarks'] = update_item.get('remarks')
                    
                    if int(update_item.get('OrderQty')) != old_order_qty or update_item.get('remarks') != old_remarks:
                        data_changed = True
                        if order_id not in updates_by_order_id:
                            updates_by_order_id[order_id] = {
                                'store_name': item_store_name, 
                                'products': []
                            }
                        updates_by_order_id[order_id]['products'].append(
                            f"- {product_name}: Qty {old_order_qty} -> {update_item.get('OrderQty')}"
                            f"{f', Remarks: "{update_item.get('remarks')}"' if update_item.get('remarks') else ''}"
                        )
                    found = True
                    break
            if not found:
                print(f"Warning: Item not found for update in {file_name} - ProductCode: {product_code}, OrderId: {order_id}, StoreName: {item_store_name}")

        if data_changed:
            with open(file_path, 'w', encoding='utf-8-sig') as f:
                json.dump(current_data, f, indent=2, ensure_ascii=False) # Pretty print JSON
            
            # Send WhatsApp message if user has a number and changes were made
            if user_whatsapp_number and updates_by_order_id:
                for oid, details in updates_by_order_id.items():
                    whatsapp_message_body = (
                        f"Order update for Supplier: {session.get('suppliername')}\n"
                        f"Store: {details['store_name']}\n"
                        f"Order ID: {oid}:\n"
                        + "\n".join(details['products'])
                    )
                    send_whatsapp_message(user_whatsapp_number, whatsapp_message_body)

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
    store_headers = load_store_headers()
    return jsonify({'data': store_headers})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    # Ensure data directory exists
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # In this version, the application expects these files to already exist.
    # They are NOT created programmatically here.
    # You MUST ensure that 'users.json', 'OrderSuppliers.json', 'storeheader.json',
    # and all supplier-specific JSON files (e.g., '117.json', 'NMC_117.json')
    # are present in the 'data' directory when the application starts.
    # Example structure for your 'data' folder:
    # data/
    #   users.json
    #   OrderSuppliers.json
    #   storeheader.json
    #   117.json
    #   PALEPU.json
    #   691.json
    #   NMA_117.json
    #   NMC_117.json
    #   NMG_117.json
    #   NMS_117.json

    app.run(debug=True)

