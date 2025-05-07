from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from functools import wraps
from datetime import date
import sqlite3

app = Flask(__name__)
DATABASE = 'rentals.db'

app.secret_key = 'your_secret_key'

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = 'abednegokaume@gmail.com'
app.config['MAIL_PASSWORD'] = 'ssfo ocyi hxbf xjnb'
app.config['MAIL_DEFAULT_SENDER'] = 'abednegokaume@gmail.com'
mail = Mail(app)

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'tenant_id' not in session:
            flash("You must log in to access this page.", "warning")
            return redirect(url_for('tenant_login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def home():
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/announcement/new', methods=['GET', 'POST'])
@login_required
def new_announcement():
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')

        if not title or not content:
            app.logger.error("Missing title or content in announcement form")
            return "Title and content are required", 400

        try:
            conn = get_db_connection()
            conn.execute(
                'INSERT INTO announcements (title, content, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)',
                (title, content)
            )
            conn.commit()
            conn.close()
            app.logger.debug(f"New announcement posted: {title}")
        except Exception as e:
            app.logger.error(f"Failed to post announcement: {e}")
            return "Failed to save announcement", 500

        return redirect(url_for('admin_dashboard'))

    return render_template('new_announcement.html')

@app.route('/tenant/announcements')
@login_required
def view_announcements():
    try:
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT title, content, created_at FROM announcements ORDER BY created_at DESC")
        announcements = cursor.fetchall()
        conn.close()

        app.logger.debug(f"{len(announcements)} announcements fetched.")
        return render_template('tenant_announcements.html', announcements=announcements)

    except Exception as e:
        app.logger.error(f"Error fetching announcements: {str(e)}")
        return "Could not load announcements", 500

@app.route('/tenant/<int:tenant_id>/inbox')
@login_required
def tenant_inbox(tenant_id):
    conn = get_db_connection()
    messages = conn.execute(
        'SELECT message, reply FROM messages WHERE tenant_id = ? AND anonymous = 0 ORDER BY id DESC',
        (tenant_id,)
    ).fetchall()
    conn.close()
    return render_template('tenant_inbox.html', messages=messages, tenant_id=tenant_id)

@app.route('/tenant/<int:tenant_id>/send_named_message', methods=['POST'])
@login_required
def send_message_named(tenant_id):
    # Kupata ujumbe kutoka kwa form ya tenant
    message = request.form['message']
    
    # Ku-connect na database
    conn = get_db_connection()
    
    # Hakikisha kwamba tenant_id ni sahihi na message ni valid
    if message:
        conn.execute(
            'INSERT INTO messages (tenant_id, message, anonymous) VALUES (?, ?, ?)',
            (tenant_id, message, 0)  # Non-anonymous message
        )
        conn.commit()  # Tumia commit ili kueka message kwenye database
        app.logger.debug(f"Message from tenant {tenant_id} inserted successfully.")

    conn.close()
    return redirect(url_for('tenant_inbox', tenant_id=tenant_id))  # Kurudi kwenye inbox ya tenant

@app.route('/admin/reply/<int:tenant_id>/<int:message_id>', methods=['POST'])
@login_required
def reply_admin(tenant_id, message_id):
    reply_text = request.form['reply_text']
    conn = get_db_connection()
    conn.execute(
        'UPDATE messages SET reply = ? WHERE id = ? AND tenant_id = ?',
        (reply_text, message_id, tenant_id)
    )
    conn.commit()
    conn.close()
    return redirect(url_for('admin_inbox'))

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    conn = get_db_connection()
    cursor = conn.cursor()

    # Metrics
    cursor.execute("SELECT COUNT(*) FROM tenants")
    total_tenants = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM tenants WHERE status = 'pending'")
    pending_tenants = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM tenants WHERE rent_paid < rent_amount")
    underpaid_count = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(rent_amount - rent_paid) FROM tenants WHERE rent_paid < rent_amount")
    total_balance_due = cursor.fetchone()[0] or 0.0
    # Search & Pagination
    search_query = request.args.get('search', '').strip()
    page = int(request.args.get('page', 1))
    per_page = 10
    offset = (page - 1) * per_page

    if search_query:
        like_query = f"%{search_query}%"
        cursor.execute('''
            SELECT COUNT(*) FROM tenants
            WHERE full_name LIKE ? OR phone LIKE ? OR id_number LIKE ?
        ''', (like_query, like_query, like_query))
        total_filtered = cursor.fetchone()[0]

        cursor.execute('''
            SELECT * FROM tenants
            WHERE full_name LIKE ? OR phone LIKE ? OR id_number LIKE ?
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        ''', (like_query, like_query, like_query, per_page, offset))
    else:
        total_filtered = total_tenants
        cursor.execute('''
            SELECT * FROM tenants
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        ''', (per_page, offset))

    tenants = cursor.fetchall()
    conn.close()

    total_pages = (total_filtered + per_page - 1) // per_page

    return render_template('admin_dashboard.html',
                           tenants=tenants,
                           page=page,
                           total_pages=total_pages,
                           search_query=search_query,
                            total_tenants=total_tenants,
                           pending_tenants=pending_tenants,
                           underpaid_count=underpaid_count,
                           total_balance_due=total_balance_due)

@app.route('/tenant/dashboard/<int:tenant_id>')
@login_required
def tenant_reply_dashboard(tenant_id):
    conn = sqlite3.connect('rentals.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Fetch tenant info
    cursor.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,))
    tenant = cursor.fetchone()

    # Fetch admin replies
    cursor.execute("""
        SELECT * FROM messages
        WHERE tenant_id = ? AND reply IS NOT NULL
        ORDER BY timestamp DESC
    """, (tenant_id,))
    replies = cursor.fetchall()

    # Fetch announcements
    cursor.execute("""
        SELECT title, content, created_at FROM announcements
        ORDER BY created_at DESC
    """)
    announcements = cursor.fetchall()

    conn.close()

    return render_template(
        'tenant_dashboard.html',
        tenant=tenant,
        replies=replies,
        announcements=announcements  # Hii ndo ilikuwa inakosekana!
    )

@app.route('/tenant_reply/<int:tenant_id>/<int:message_id>', methods=['POST'])
@login_required
def tenant_reply(tenant_id, message_id):
    tenant_reply = request.form.get('tenant_reply')

    if tenant_reply:
        conn = sqlite3.connect('rentals.db')
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE messages
            SET tenant_reply = ?
            WHERE id = ? AND tenant_id = ?
            """, (tenant_reply, message_id, tenant_id))

        conn.commit()
        conn.close()

    return redirect(url_for('tenant_dashboard', tenant_id=tenant_id))

@app.route('/admin/inbox')
@login_required
def admin_inbox():
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row

    # Chukua anonymous messages zote
    anon_messages = conn.execute(
        'SELECT id, message, reply FROM messages WHERE anonymous = 1'
    ).fetchall()

    # Chukua non-anonymous messages pamoja na tenant_id na full_name
    non_anon_messages = conn.execute(
        '''
        SELECT messages.id, messages.message, messages.reply, messages.tenant_id, tenants.full_name
        FROM messages
        JOIN tenants ON messages.tenant_id = tenants.id
        WHERE anonymous = 0
        '''
    ).fetchall()

    conn.close()

    # Debug logs (optional)
    app.logger.debug(f"Anonymous Messages: {anon_messages}")
    app.logger.debug(f"Non-Anonymous Messages: {non_anon_messages}")

    return render_template(
        'admin_inbox.html',
        anon_messages=anon_messages,
        non_anon_messages=non_anon_messages
    )

@app.route('/tenant/<int:tenant_id>/send_anonymous', methods=['POST'])
def send_anonymous_message(tenant_id):
    message = request.form['message']

    conn = sqlite3.connect('rentals.db')
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO messages (tenant_id, message, anonymous)
        VALUES (?, ?, ?)
    ''', (tenant_id, message, 1))  # 1 inaashiria kuwa ni anonymous

    conn.commit()
    conn.close()

    return redirect(url_for('tenant_dashboard', tenant_id=tenant_id))

@app.route('/reply/<int:message_id>', methods=['POST'])
@login_required
def reply_message(message_id):
    reply = request.form['reply_text']
    conn = sqlite3.connect('rentals.db')
    c = conn.cursor()
    c.execute("UPDATE messages SET reply = ? WHERE id = ?", (reply, message_id))
    conn.commit()
    conn.close()
    flash('Reply sent successfully!', 'success')
    return redirect(url_for('admin_inbox'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        id_number = request.form['id_number']
        full_name = request.form['full_name']
        phone = request.form['phone']
        email = request.form['email']
        conn = get_db_connection()
        conn.execute('INSERT INTO tenants (id_number, full_name, phone, email) VALUES (?, ?, ?, ?)',
                     (id_number, full_name, phone, email))
        conn.commit()
        conn.close()
        return redirect(url_for('success'))
    return render_template('register.html')

@app.route('/tenant/login',methods=['GET', 'POST'])
def tenant_login():
    if request.method == 'POST':
        house_number = request.form.get('house_number')
        password = request.form.get('password')

        conn = get_db_connection()
        tenant = conn.execute('SELECT * FROM tenants WHERE house_number = ?', (house_number,)).fetchone()
        conn.close()

        if tenant and check_password_hash(tenant['password'], password):
            session['tenant_id'] = tenant['id']
            return redirect(url_for('tenant_dashboard', tenant_id=tenant['id']))
        else:
            error = 'House number or password is incorrect.'
        return render_template('tenant_login.html', error=error)

    return render_template('tenant_login.html')

@app.route('/tenant/logout')
def tenant_logout():
      session.pop('tenant_id', None)
      return redirect(url_for('tenant_login'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = sqlite3.connect('rentals.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM admins WHERE username=? AND password=?', (username, password))
        admin = cursor.fetchone()
        conn.close()

        if admin:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            return 'Invalid credentials'

    return render_template('admin_login.html')

@app.route('/success')
def success():
    return render_template('success.html')

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_tenant(id):
    conn = get_db_connection()
    if request.method == 'POST':
        house_number = request.form['house_number']
        floor = request.form['floor']
        rent_amount = request.form['rent_amount']
        payment_status = request.form['payment_status']
        balance_amount = request.form['balance_amount']
        conn.execute('UPDATE tenants SET house_number = ?, floor = ?, rent_amount = ?, payment_status = ?, balance_amount = ? WHERE id = ?',
                     (house_number, floor, rent_amount, payment_status, balance_amount, id))
        conn.commit()
        conn.close()
        return redirect(url_for('admin_dashboard'))
    else:
        tenant = conn.execute('SELECT * FROM tenants WHERE id = ?', (id,)).fetchone()
        conn.close()
        return render_template('edit_tenant.html', tenant=tenant)

@app.route('/complete/<int:id>', methods=['GET', 'POST'])
def complete_tenant(id):
    conn = get_db_connection()
    tenant = conn.execute('SELECT * FROM tenants WHERE id = ?', (id,)).fetchone()

    # Angalia kama tenant tayari amekamilisha details
    if tenant['is_completed'] == 1:
        conn.close()
        # Onyesha ujumbe kwa admin kwamba tenant tayari amekamilisha details na kuwaelekeze kutumia "Edit"
        flash("Tenant has already completed their details. Please use the 'Edit' option to make changes.", "info")
        return redirect(url_for('admin_dashboard'))  # Redirect admin back to dashboard

    if request.method == 'POST':
        house_number = request.form['house_number']
        floor = request.form['floor']
        rent_amount = request.form['rent_amount']
        payment_status = request.form['payment_status']
        balance_amount = request.form['balance_amount'] if 'balance_amount' in request.form else 0

        # Update tenant details
        conn.execute('''
            UPDATE tenants
            SET house_number = ?, floor = ?, rent_amount = ?, payment_status = ?, balance_amount = ?, is_completed = 1
            WHERE id = ?
        ''', (house_number, floor, rent_amount, payment_status, balance_amount, id))

        conn.commit()

        # Email notification to tenant after completion
        try:
            msg = Message(
                subject="Welcome to Our Rental System",
                recipients=[tenant['email']],
                body=f'''Hello {tenant['full_name']},

Welcome to our rental community. Your registration has been completed successfully.

Your temporary password is: 1234
Please reset it immediately for your own security by clicking here:
http://127.0.0.1:5000/reset-password/{tenant['id']}

Once your password is updated, you'll be automatically redirected to your tenant dashboard.

Thank you for joining us!

-- Management'''
            )
            mail.send(msg)
        except Exception as e:
            print(f"Error sending email: {e}")

        conn.close()
        # Redirect admin to the dashboard after successful tenant completion
        return redirect(url_for('admin_dashboard'))

    # If GET request, render the complete tenant form
    return render_template('complete_tenant.html', tenant=tenant)

@app.route('/reset-password/<int:tenant_id>', methods=['GET', 'POST'])
def reset_password(tenant_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        if new_password:
            hashed_password = generate_password_hash(new_password)
            cursor.execute('UPDATE tenants SET password = ? WHERE id = ?', (hashed_password, tenant_id))
            conn.commit()
            conn.close()
            return redirect(url_for('tenant_dashboard', tenant_id=tenant_id))
        else:
            conn.close()
            return "Password field cannot be empty", 400

    conn.close()
    return render_template('reset_password.html')

@app.route('/tenant/dashboard/<int:tenant_id>')
@login_required
def tenant_dashboard(tenant_id):
    conn = sqlite3.connect('rentals.db')
    conn.row_factory = sqlite3.Row
    tenant = conn.execute('SELECT * FROM tenants WHERE id = ?', (tenant_id,)).fetchone()
    
    # Chukua announcements zote
    announcements = conn.execute('SELECT * FROM announcements ORDER BY created_at DESC').fetchall()

    conn.close()

    if tenant is None:
        return "Tenant not found", 404

    # Rent details
    rent_amount = tenant['rent_amount']
    rent_paid = tenant['rent_paid']
    balance = rent_amount - rent_paid

    # Countdown to 10th
    today = date.today()
    rent_due = date(today.year, today.month, 10)
    if today > rent_due:
        if today.month == 12:
            rent_due = date(today.year + 1, 1, 10)
        else:
            rent_due = date(today.year, today.month + 1, 10)
    days_remaining = (rent_due - today).days
    return render_template('tenant_dashboard.html',
                           tenant=tenant,
                           balance=balance,
                           days_remaining=days_remaining,
                           announcements=announcements)

@app.route('/delete/<int:id>', methods=['POST'])
def delete_tenant(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM tenants WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/tenant/send_message', methods=['POST'])
@login_required
def send_message():
    message = request.form['message']
    anonymous = request.form.get('anonymous')  # Hii itakuwa None kama haijachaguliwa

    conn = sqlite3.connect('rentals.db')
    c = conn.cursor()

    if anonymous:
        c.execute("INSERT INTO messages (tenant_id, message, anonymous) VALUES (?, ?, ?)", 
                  (None, message, 1))
    else:
        tenant_id = session.get('tenant_id')
        c.execute("INSERT INTO messages (tenant_id, message, anonymous) VALUES (?, ?, ?)", 
                  (tenant_id, message, 0))

    conn.commit()
    conn.close()

    flash('Message sent successfully!', 'success')
    return redirect(url_for('tenant_dashboard', tenant_id=session.get('tenant_id')))

@app.route('/about_system')
def about_system():
    return render_template('about_system.html')

@app.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

if __name__ == '__main__':
    app.run(debug=True)

