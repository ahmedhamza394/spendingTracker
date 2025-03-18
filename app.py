from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import os
from parsers import parse_transactions  # Import the parsing function


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'supersecretkey')

DATABASE = 'transactions.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL,
            merchant TEXT,
            category TEXT,
            transactionDate DATE,
            datetimeAdded TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.execute('''
    CREATE TABLE IF NOT EXISTS custom_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT UNIQUE NOT NULL
    )
''')
  
    # Create default_categories table (if not exists)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS default_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_pattern TEXT NOT NULL,
            category TEXT NOT NULL
        )
    ''')
    
    # Insert default mappings if not already present
    for merchant, category in [
        ('Costco', 'grocery'),
        ('Walmart', 'shopping'),
        ('Amazon', 'shopping')
    ]:
        conn.execute('''
            INSERT INTO default_categories (merchant_pattern, category)
            SELECT ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM default_categories WHERE merchant_pattern = ?
            )
        ''', (merchant, category, merchant))
    
    conn.commit()
    conn.close()


# Initialize the database when the app starts
init_db()

# Simple login_required decorator
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        # Hardcoded credentials (for MVP)
        if username == 'admin' and password == 'password':
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    conn = get_db_connection()
    if request.method == 'POST':
        text = request.form.get('text')
        parsed_transactions = parse_transactions(text)
        
        if not parsed_transactions:
            flash("No valid transactions found.")
            return redirect(url_for('index'))
        
        for parsed in parsed_transactions:
            amount = parsed['amount']
            merchant = parsed['merchant']
            category = parsed.get('category', 'uncategorized')
            transactionDate = parsed['date']
            
            conn.execute('''
                INSERT INTO transactions (amount, merchant, category, transactionDate)
                VALUES (?, ?, ?, ?)
            ''', (amount, merchant, category, transactionDate))
        
        conn.commit()
        flash(f"{len(parsed_transactions)} transactions submitted successfully!")
        return redirect(url_for('index'))
    
    transactions = conn.execute('SELECT * FROM transactions ORDER BY transactionDate DESC').fetchall()
    total_row = conn.execute('SELECT SUM(amount) as total FROM transactions').fetchone()
    total = total_row['total'] if total_row['total'] is not None else 0.0
    
    # Get custom categories from the DB
    custom_cats_rows = conn.execute("SELECT category FROM custom_categories").fetchall()
    custom_categories = [row['category'] for row in custom_cats_rows]
    
    # Predefined categories
    standard_categories = ['Grocery', 'EatingOut', 'Shopping', 'Gas', 'Bills', 'Misc']
    # Combine them (avoiding duplicates)
    all_categories = standard_categories + [cat for cat in custom_categories if cat not in standard_categories]
    
    conn.close()
    return render_template('index.html', transactions=transactions, total=total, categories=all_categories)

@app.route('/update_category/<int:transaction_id>', methods=['POST'])
@login_required
def update_category(transaction_id):
    # Get the new category from the form.
    new_category = request.form.get('category')
    if new_category == 'Custom':
        new_category = request.form.get('custom_category', '').strip()
    # If the new_category is empty, flash a message and redirect.
    if not new_category:
        flash("Please enter a valid category.")
        return redirect(url_for('index'))
    
    # Define the standard categories.
    standard_categories = ['Grocery', 'EatingOut', 'Shopping', 'Gas', 'Bills', 'Misc']
    
    conn = get_db_connection()
    # If the new category is not one of the standard ones, add it to custom_categories if it's new.
    if new_category not in standard_categories:
        try:
            conn.execute("INSERT INTO custom_categories (category) VALUES (?)", (new_category,))
            conn.commit()
        except sqlite3.IntegrityError:
            # Category already exists, no action needed.
            pass

    # Update the transaction's category.
    conn.execute("UPDATE transactions SET category = ? WHERE id = ?", (new_category, transaction_id))
    conn.commit()
    conn.close()
    
    flash("Category updated successfully!")
    return redirect(url_for('index'))

@app.route('/delete/<int:transaction_id>', methods=['POST'])
@login_required
def delete_transaction(transaction_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
    conn.commit()
    conn.close()
    flash("Transaction deleted successfully!")
    return redirect(url_for('index'))

@app.route('/report', methods=['POST'])
@login_required
def report():
    email = request.form.get('email')
    conn = get_db_connection()
    transactions = conn.execute('SELECT * FROM transactions ORDER BY processed_at DESC').fetchall()
    conn.close()
    # Generate a simple text report
    report_content = "Transaction Report\n\n"
    for tx in transactions:
        report_content += f"ID: {tx['id']}, Category: {tx['category']}, Content: {tx['content']}\n"
    
    # Placeholder for email functionality; for now, we display the report.
    flash(f"Report generated and 'sent' to {email} (simulated).")
    return render_template('report.html', report=report_content)

from flask import request, jsonify

@app.route('/update_field/<int:transaction_id>', methods=['POST'])
@login_required
def update_field(transaction_id):
    data = request.get_json()
    field = data.get("field")
    value = data.get("value")
    
    if field not in ["amount", "category"]:
        return jsonify({"status": "error", "message": "Invalid field"}), 400

    conn = get_db_connection()
    try:
        if field == "amount":
            # Convert value to float
            value = float(value.replace('$', '').strip())
        conn.execute(f"UPDATE transactions SET {field} = ? WHERE id = ?", (value, transaction_id))
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({"status": "error", "message": str(e)}), 500
    conn.close()
    return jsonify({"status": "success"})


if __name__ == '__main__':
    app.run(debug=True)
