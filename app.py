from flask import Flask, render_template, request, redirect, url_for, session, jsonify, render_template_string
import pyodbc
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Used for session encryption

# SQL Server connection string
conn_str = (
    "Driver={ODBC Driver 17 for SQL Server};"
    "Server=tcp:cpms.database.windows.net,1433;"  # Your Azure SQL Server name
    "Database=CPMS;"  # Assuming your database name is 'ordermanagementdb'
    "UID=cpms;"  # Your SQL admin username
    "PWD=Order@1711;"  # Your SQL admin password
    "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"  # Recommended for Azure SQL
)

# Check credentials in Users table
def check_login(username, password):
    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Users WHERE Username=? AND Password=?", (username, password))
        row = cursor.fetchone()
        conn.close()
        return row is not None
    except Exception as e:
        print("Database error:", e)
        return False

@app.before_request
def require_login():
    allowed = ['login', 'static', 'search_store', 'search_supplier', 'get_orders', 'get_suppliercode', 'update_orders']
    if 'user' not in session and request.endpoint not in allowed and not request.path.startswith('/logout'):
        return redirect(url_for('login'))

# Login route
@app.route('/', methods=['GET', 'POST'])
def login():
    error = ''
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if check_login(username, password):
            session['user'] = username
            return redirect(url_for('dashboard'))
        else:
            error = 'Invalid credentials. Try again.'
    return render_template('login.html', error=error)

# Dashboard route
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', user=session['user'])

# Search Store Endpoint
@app.route('/search_store')
def search_store():
    query = request.args.get('q', '')
    matches = []
    if query:
        try:
            conn = pyodbc.connect(conn_str)
            cursor = conn.cursor()
            cursor.execute("SELECT TOP 10 StoreName FROM Stores WHERE StoreName LIKE ? AND isactive=1", ('%' + query + '%',))
            matches = [row[0] for row in cursor.fetchall()]
            conn.close()
        except Exception as e:
            print("DB error:", e)
    return jsonify(matches)

@app.route('/search_supplier')
def search_supplier():
    query = request.args.get('q', '')
    store = request.args.get('store', '')
    matches = []
    if query and store:
        try:
            conn = pyodbc.connect(conn_str)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT TOP 10 SupplierName 
                FROM OrderSuppliers 
                WHERE SupplierName LIKE ? AND StoreName = ?
            """, ('%' + query + '%', store))
            matches = [row[0] for row in cursor.fetchall()]
            conn.close()
        except Exception as e:
            print("DB error (supplier):", e)
    return jsonify(matches)

@app.route('/get_orders')
def get_orders():
    suppliercode = request.args.get('suppliercode', '')
    storename = request.args.get('storename', '')
    results = []
    if not suppliercode or not storename:
        return jsonify([])
    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        # Modified SELECT statement to include OrderId and StoreCode
        query = """
            SELECT productcode, productname, OrderQty, saleunit, mrp, orsupplier, remarks, OrderId, StoreCode
            FROM ordermanagement
            WHERE status = 1
              AND orsuppliercode IN (SELECT Value FROM dbo.SplitString(?, ','))
              AND storename = ?
              AND orderqty > 0
            ORDER BY productname
        """
        cursor.execute(query, (suppliercode, storename))
        rows = cursor.fetchall()
        for idx, row in enumerate(rows, start=1):
            results.append({
                'SerialNo': idx,
                'ProductCode': row[0],
                'ProductName': row[1],
                'OrderQty': row[2],
                'SaleUnit': row[3],
                'MRP': row[4],
                'ORSUPPLIER': row[5],
                'Remarks': row[6] if row[6] else '',
                'OrderId': row[7],  # Added OrderId
                'StoreCode': row[8]  # Added StoreCode
            })
        conn.close()
    except Exception as e:
        print("Error fetching orders:", e)
    return jsonify(results)

@app.route('/get_suppliercode')
def get_suppliercode():
    suppliername = request.args.get('suppliername', '')
    storename = request.args.get('storename', '')
    code = ''
    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        cursor.execute("SELECT TOP 1 SupplierCode FROM OrderSuppliers WHERE SupplierName=? AND StoreName=?", (suppliername, storename))
        row = cursor.fetchone()
        if row:
            code = row[0]
        conn.close()
    except Exception as e:
        print("Error fetching supplier code:", e)
    return jsonify({'suppliercode': code})

@app.route('/update_orders', methods=['POST'])
def update_orders():
    data = request.json
    print(f"Received data from frontend: {data}")  # DEBUG: See what frontend sends
    updated_items = data.get('updatedData', [])
    if not updated_items:
        return jsonify({'success': False, 'message': 'No data to update.'})
    
    conn = None 
    try:
        conn = pyodbc.connect(conn_str, autocommit=False)  # Start a transaction
        cursor = conn.cursor()
        for item in updated_items:
            print(f"Processing item: {item}")  # DEBUG: See each item's content
            product_code = item.get('ProductCode')
            product_name = item.get('ProductName')
            edit_qty = item.get('EditQty')
            or_qty = item.get('OrQty')
            diff_qty = item.get('Diffqty')
            sale_unit = item.get('SaleUnit')
            wanted_type = item.get('WantedType', 'NA')
            status_text = item.get('Status')
            web_remarks = item.get('webRemarks')
            order_id = item.get('OrderId')
            # Corrected: Get store_name and store_code directly from the item
            item_store_name = item.get('StoreName') 
            item_store_code = item.get('StoreCode')
            print(f"Extracted values for DB: ProductCode={product_code}, ProductName={product_name}, EditQty={edit_qty}, OrQty={or_qty}, Diffqty={diff_qty}, SaleUnit={sale_unit}, WantedType={wanted_type}, Status={status_text}, webRemarks={web_remarks}, OrderId={order_id}, StoreCode={item_store_code}, StoreName={item_store_name}")
            # Check if a record exists in weborderstatus for the given OrderId and ProductCode
            cursor.execute("""
                SELECT COUNT(*) FROM weborderstatus
                WHERE OrderId = ? AND ProductCode = ?
            """, (order_id, product_code))
            exists = cursor.fetchone()[0] > 0
            if exists:
                # Update existing record
                update_query = """
                    UPDATE weborderstatus
                    SET
                        EditQty = ?,
                        Diffqty = ?,
                        Status = ?,
                        webRemarks = ?,
                        OrQty = ?,
                        ProductName = ?,
                        SaleUnit = ?,
                        WantedType = ?,
                        StoreName = ?,
                        StoreCode = ?
                    WHERE OrderId = ? AND ProductCode = ?
                """
                params = (edit_qty, diff_qty, status_text, web_remarks, or_qty,
                          product_name, sale_unit, wanted_type, item_store_name, item_store_code, 
                          order_id, product_code)
                print(f"Executing UPDATE with parameters: {params}")  # DEBUG: Check update parameters
                cursor.execute(update_query, *params) 
            else:
                # Insert new record
                insert_query = """
                    INSERT INTO weborderstatus (
                        ProductCode, ProductName, Diffqty, SaleUnit, WantedType,
                        Status, EditQty, OrQty, webRemarks, OrderId, StoreName, StoreCode
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                params = (product_code, product_name, diff_qty, sale_unit, wanted_type,
                          status_text, edit_qty, or_qty, web_remarks, order_id, item_store_name, item_store_code)
                print(f"Executing INSERT with parameters: {params}")  # DEBUG: Check insert parameters
                cursor.execute(insert_query, *params)
        
        conn.commit()  # Commit the transaction if all operations succeed
        return jsonify({'success': True, 'message': 'Orders updated successfully.'})
    except Exception as e:
        print("Error updating weborderstatus:", e)  # Logs specific database error
        if conn:
            conn.rollback()  # Rollback on error
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'})  # Fixed f-string
    finally:
        if conn:
            conn.close()  # Ensure connection is closed

# 🔓 Logout route
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# 🚀 Start the Flask server
if __name__ == '__main__':
    app.run(debug=True)