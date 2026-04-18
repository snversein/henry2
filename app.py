import os
import sys
import requests
from datetime import datetime

import flask.json
if not hasattr(flask.json, 'JSONEncoder'):
    from json import JSONEncoder as _JSONEncoder
    flask.json.JSONEncoder = _JSONEncoder

from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
import mongoengine
from mongoengine import Document, StringField, FloatField, BooleanField, DateTimeField, ObjectIdField, ListField, DictField, ReferenceField
import os

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'henri-secret-key-change-in-production')

db_uri = os.environ.get('DATABASE_URL', '')
if db_uri and db_uri.startswith('mongodb'):
    from urllib.parse import urlparse, quote
    parsed = urlparse(db_uri)
    user = parsed.username or ''
    pwd = parsed.password or ''
    host = parsed.hostname or ''
    port = parsed.port or ''
    path = parsed.path or ''
    encoded_uri = f"mongodb+srv://{quote(user)}:{quote(pwd)}@{host}"
    if port:
        encoded_uri += f":{port}"
    encoded_uri += path
    mongoengine.connect('henri', host=encoded_uri)
else:
    mongoengine.connect('henri', host='localhost', port=27017)

db = mongoengine

class Product(Document):
    name = StringField(required=True, max_length=200)
    category = StringField(required=True, max_length=100)
    current_stock = FloatField(default=0)
    minimum_stock = FloatField(default=0)
    sale_price = FloatField(required=True)
    purchase_price = FloatField(default=0)
    demo_price = FloatField(default=0)
    description = StringField(default='')
    image_url = StringField(max_length=500, default='')
    is_active = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)

    meta = {'collection': 'product'}

    def to_dict(self):
        return {
            'id': str(self.id),
            'name': self.name,
            'category': self.category,
            'current_stock': self.current_stock,
            'minimum_stock': self.minimum_stock,
            'sale_price': self.sale_price,
            'purchase_price': self.purchase_price,
            'demo_price': self.demo_price,
            'description': self.description,
            'image_url': self.image_url,
            'in_stock': self.current_stock > 0
        }

class User(Document):
    email = StringField(required=True, unique=True, max_length=120)
    password = StringField(required=True, max_length=200)
    name = StringField(required=True, max_length=100)
    phone = db.StringField(max_length=20, default='')
    address = db.StringField(default='')
    is_admin = db.BooleanField(default=False)
    created_at = db.DateTimeField(default=datetime.utcnow)

class Order(db.Document):
    order_number = db.StringField(required=True, unique=True, max_length=20)
    user_id = db.ObjectIdField()
    customer_name = db.StringField(required=True, max_length=100)
    customer_phone = db.StringField(required=True, max_length=20)
    customer_email = db.StringField(required=True, max_length=120)
    shipping_address = db.StringField(required=True)
    subtotal = db.FloatField(required=True)
    total = db.FloatField(required=True)
    status = db.StringField(default='pending', max_length=20)
    payment_method = db.StringField(default='cod', max_length=50)
    notes = db.StringField(default='')
    created_at = db.DateTimeField(default=datetime.utcnow)
    updated_at = db.DateTimeField(default=datetime.utcnow)
    items = db.ListField(db.DictField())

    def to_dict(self):
        return {
            'id': str(self.id),
            'order_number': self.order_number,
            'customer_name': self.customer_name,
            'customer_phone': self.customer_phone,
            'customer_email': self.customer_email,
            'shipping_address': self.shipping_address,
            'subtotal': self.subtotal,
            'total': self.total,
            'status': self.status,
            'payment_method': self.payment_method,
            'notes': self.notes,
            'items': self.items,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else ''
        }

class Rating(db.Document):
    product_id = db.ObjectIdField(required=True)
    customer_name = db.StringField(required=True, max_length=100)
    rating = db.IntField(required=True)
    review = db.StringField(default='')
    is_approved = db.BooleanField(default=False)
    created_at = db.DateTimeField(default=datetime.utcnow)

    product = db.ReferenceField(Product, reverse_delete_rule='NULL')

def generate_order_number():
    last_order = Order.objects.order_by('-id').first()
    if last_order:
        num = int(last_order.order_number.replace('ORD', '')) + 1
    else:
        num = 1
    return f'ORD{str(num).zfill(6)}'

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

@app.before_request
def load_categories():
    from flask import g
    categories = Product.objects.distinct('category')
    g.categories = categories

@app.route('/')
def index():
    products = Product.objects(is_active=True)
    return render_template('index.html', products=products)

@app.route('/product/<product_id>')
def product_detail(product_id):
    try:
        product = Product.objects.get(id=product_id)
    except Product.DoesNotExist:
        flash('Product not found', 'error')
        return redirect(url_for('index'))
    related_products = Product.objects(category=product.category, is_active=True, id__ne=product.id).limit(4)
    ratings = Rating.objects(product_id=product.id, is_approved=True).order_by('-created_at')
    avg_rating = sum(r.rating for r in ratings) / len(ratings) if ratings else 0
    return render_template('product.html', product=product, related_products=related_products, ratings=ratings, avg_rating=avg_rating)

@app.route('/product/<product_id>/rate', methods=['POST'])
def rate_product(product_id):
    try:
        product = Product.objects.get(id=product_id)
    except Product.DoesNotExist:
        flash('Product not found', 'error')
        return redirect(url_for('index'))
    rating = int(request.form.get('rating', 5))
    review = request.form.get('review', '')
    customer_name = request.form.get('customer_name', 'Anonymous')
    
    new_rating = Rating(
        product_id=product.id,
        customer_name=customer_name,
        rating=rating,
        review=review,
        is_approved=False
    )
    new_rating.save()
    flash('Thank you! Your rating has been submitted and is pending approval.', 'success')
    return redirect(url_for('product_detail', product_id=product_id))

@app.route('/category/<category>')
def category(category):
    products = Product.objects(category=category, is_active=True)
    return render_template('index.html', products=products, current_category=category)

@app.route('/cart')
def cart():
    cart = session.get('cart', [])
    cart_items = []
    subtotal = 0
    for item in cart:
        try:
            product = Product.objects.get(id=item['product_id'])
            if product:
                item_total = product.sale_price * item['quantity']
                subtotal += item_total
                cart_items.append({
                    'product': product,
                    'quantity': item['quantity'],
                    'total': item_total
                })
        except:
            pass
    return render_template('cart.html', cart_items=cart_items, subtotal=subtotal, total=subtotal)

@app.route('/add-to-cart/<product_id>', methods=['POST'])
def add_to_cart(product_id):
    quantity = int(request.form.get('quantity', 1))
    cart = session.get('cart', [])
    
    existing_item = next((item for item in cart if str(item['product_id']) == str(product_id)), None)
    if existing_item:
        existing_item['quantity'] += quantity
    else:
        cart.append({'product_id': product_id, 'quantity': quantity})
    
    session['cart'] = cart
    flash('Item added to cart!', 'success')
    return redirect(url_for('cart'))

@app.route('/update-cart/<product_id>', methods=['POST'])
def update_cart(product_id):
    quantity = int(request.form.get('quantity', 1))
    cart = session.get('cart', [])
    
    for item in cart:
        if str(item['product_id']) == str(product_id):
            if quantity > 0:
                item['quantity'] = quantity
            else:
                cart.remove(item)
            break
    
    session['cart'] = cart
    return redirect(url_for('cart'))

@app.route('/remove-from-cart/<product_id>')
def remove_from_cart(product_id):
    cart = session.get('cart', [])
    cart = [item for item in cart if str(item['product_id']) != str(product_id)]
    session['cart'] = cart
    flash('Item removed from cart!', 'success')
    return redirect(url_for('cart'))

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    cart = session.get('cart', [])
    if not cart:
        flash('Your cart is empty!', 'error')
        return redirect(url_for('index'))
    
    cart_items = []
    subtotal = 0
    for item in cart:
        try:
            product = Product.objects.get(id=item['product_id'])
            if product:
                item_total = product.sale_price * item['quantity']
                subtotal += item_total
                cart_items.append({
                    'product': product,
                    'quantity': item['quantity'],
                    'total': item_total
                })
        except:
            pass
    
    if request.method == 'POST':
        order = Order(
            order_number=generate_order_number(),
            customer_name=request.form.get('name'),
            customer_phone=request.form.get('phone'),
            customer_email=request.form.get('email'),
            shipping_address=request.form.get('address'),
            subtotal=subtotal,
            total=subtotal,
            payment_method=request.form.get('payment_method', 'cod'),
            notes=request.form.get('notes', '')
        )
        order.save()
        
        items_list = []
        for item in cart_items:
            items_list.append({
                'product_id': str(item['product'].id),
                'product_name': item['product'].name,
                'quantity': item['quantity'],
                'unit_price': item['product'].sale_price,
                'total': item['total']
            })
            
            product = Product.objects.get(id=item['product'].id)
            if product:
                product.current_stock -= item['quantity']
                product.save()
        
        order.items = items_list
        order.save()
        
        session['cart'] = []
        flash(f'Order placed successfully! Order number: {order.order_number}', 'success')
        return redirect(url_for('order_success', order_number=order.order_number))
    
    return render_template('checkout.html', cart_items=cart_items, subtotal=subtotal, total=subtotal)

@app.route('/order-success/<order_number>')
def order_success(order_number):
    order = Order.objects(order_number=order_number).first()
    return render_template('order_success.html', order=order)

@app.route('/my-orders')
def my_orders():
    email = session.get('customer_email')
    if not email:
        flash('Please login to view your orders', 'error')
        return redirect(url_for('login'))
    
    orders = Order.objects(customer_email=email).order_by('-created_at')
    return render_template('my_orders.html', orders=orders)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.objects(email=email).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = str(user.id)
            session['customer_email'] = user.email
            session['customer_name'] = user.name
            flash('Login successful!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid email or password', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        name = request.form.get('name')
        password = request.form.get('password')
        phone = request.form.get('phone')
        address = request.form.get('address')
        
        existing_user = User.objects(email=email).first()
        if existing_user:
            flash('Email already registered', 'error')
            return redirect(url_for('register'))
        
        user = User(
            email=email,
            name=name,
            phone=phone,
            address=address,
            password=generate_password_hash(password)
        )
        user.save()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/search')
def search():
    query = request.args.get('q', '')
    products = Product.objects(name__icontains=query, is_active=True)
    return render_template('index.html', products=products, search_query=query)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.objects(email=email, is_admin=True).first()
        if user and check_password_hash(user.password, password):
            session['admin_logged_in'] = True
            session['admin_id'] = str(user.id)
            session['admin_email'] = user.email
            flash('Admin login successful!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid admin credentials', 'error')
    
    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_id', None)
    session.pop('admin_email', None)
    flash('Logged out from admin!', 'success')
    return redirect(url_for('admin_login'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    total_orders = Order.objects.count()
    pending_orders = Order.objects(status='pending').count()
    total_products = Product.objects.count()
    low_stock = 0
    for p in Product.objects:
        if p.minimum_stock > 0 and p.current_stock <= p.minimum_stock:
            low_stock += 1
    
    recent_orders = Order.objects.order_by('-created_at').limit(10)
    
    orders_by_status = {
        'pending': Order.objects(status='pending').count(),
        'processing': Order.objects(status='processing').count(),
        'shipped': Order.objects(status='shipped').count(),
        'delivered': Order.objects(status='delivered').count(),
        'cancelled': Order.objects(status='cancelled').count(),
    }
    
    products_by_category = []
    for cat in Product.objects.distinct('category'):
        count = Product.objects(category=cat).count()
        products_by_category.append([cat, count])
    
    from datetime import datetime, timedelta
    last_30_days = datetime.utcnow() - timedelta(days=30)
    daily_sales = []
    
    orders = Order.objects(created_at__gte=last_30_days)
    sales_by_date = {}
    for order in orders:
        date_key = order.created_at.strftime('%Y-%m-%d') if order.created_at else 'N/A'
        if date_key not in sales_by_date:
            sales_by_date[date_key] = 0
        sales_by_date[date_key] += order.total or 0
    
    for date_key in sorted(sales_by_date.keys()):
        daily_sales.append([date_key, sales_by_date[date_key]])
    
    top_products = []
    product_sales = {}
    for order in Order.objects:
        if order.status == 'cancelled':
            continue
        for item in order.items:
            product_name = item.get('product_name', 'Unknown')
            quantity = item.get('quantity', 0)
            if product_name not in product_sales:
                product_sales[product_name] = 0
            product_sales[product_name] += quantity
    
    sorted_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:5]
    for name, qty in sorted_products:
        top_products.append([name, qty])
    
    total_revenue = 0
    for order in Order.objects:
        total_revenue += order.total or 0
    
    return render_template('admin/dashboard.html', 
                         total_orders=total_orders,
                         pending_orders=pending_orders,
                         total_products=total_products,
                         low_stock=low_stock,
                         recent_orders=recent_orders,
                         orders_by_status=orders_by_status,
                         products_by_category=products_by_category,
                         daily_sales=daily_sales,
                         top_products=top_products,
                         total_revenue=total_revenue)

@app.route('/admin/orders')
@admin_required
def admin_orders():
    status = request.args.get('status', 'all')
    if status == 'all':
        orders = Order.objects.order_by('-created_at')
    else:
        orders = Order.objects(status=status).order_by('-created_at')
    return render_template('admin/orders.html', orders=orders, current_status=status)

@app.route('/admin/order/<order_id>')
@admin_required
def admin_order_detail(order_id):
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        flash('Order not found', 'error')
        return redirect(url_for('admin_orders'))
    return render_template('admin/order_detail.html', order=order)

@app.route('/admin/order/<order_id>/update', methods=['POST'])
@admin_required
def admin_update_order(order_id):
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        flash('Order not found', 'error')
        return redirect(url_for('admin_orders'))
    order.status = request.form.get('status')
    order.notes = request.form.get('notes', '')
    order.updated_at = datetime.utcnow()
    order.save()
    flash('Order updated successfully!', 'success')
    return redirect(url_for('admin_order_detail', order_id=order_id))

@app.route('/admin/products')
@admin_required
def admin_products():
    products = Product.objects.order_by('name')
    return render_template('admin/products.html', products=products)

@app.route('/admin/product/new', methods=['GET', 'POST'])
@admin_required
def admin_product_new():
    if request.method == 'POST':
        product = Product(
            name=request.form.get('name'),
            category=request.form.get('category'),
            current_stock=float(request.form.get('current_stock', 0)),
            minimum_stock=float(request.form.get('minimum_stock', 0)),
            sale_price=float(request.form.get('sale_price')),
            purchase_price=float(request.form.get('purchase_price', 0)),
            demo_price=float(request.form.get('demo_price', 0)),
            description=request.form.get('description', ''),
            image_url=request.form.get('image_url', ''),
            is_active=request.form.get('is_active') == 'on'
        )
        product.save()
        flash('Product created successfully!', 'success')
        return redirect(url_for('admin_products'))
    
    return render_template('admin/product_form.html', product=None)

@app.route('/admin/product/<product_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_product_edit(product_id):
    try:
        product = Product.objects.get(id=product_id)
    except Product.DoesNotExist:
        flash('Product not found', 'error')
        return redirect(url_for('admin_products'))
    
    if request.method == 'POST':
        product.name = request.form.get('name')
        product.category = request.form.get('category')
        product.current_stock = float(request.form.get('current_stock', 0))
        product.minimum_stock = float(request.form.get('minimum_stock', 0))
        product.sale_price = float(request.form.get('sale_price'))
        product.purchase_price = float(request.form.get('purchase_price', 0))
        product.demo_price = float(request.form.get('demo_price', 0))
        product.description = request.form.get('description', '')
        product.image_url = request.form.get('image_url', '')
        product.is_active = request.form.get('is_active') == 'on'
        product.save()
        flash('Product updated successfully!', 'success')
        return redirect(url_for('admin_products'))
    
    return render_template('admin/product_form.html', product=product)

@app.route('/admin/product/<product_id>/delete')
@admin_required
def admin_product_delete(product_id):
    try:
        product = Product.objects.get(id=product_id)
        product.delete()
    except Product.DoesNotExist:
        pass
    flash('Product deleted successfully!', 'success')
    return redirect(url_for('admin_products'))

@app.route('/admin/ratings')
@admin_required
def admin_ratings():
    ratings = Rating.objects.order_by('-created_at')
    return render_template('admin/ratings.html', ratings=ratings)

@app.route('/admin/rating/<rating_id>/approve')
@admin_required
def admin_rating_approve(rating_id):
    try:
        rating = Rating.objects.get(id=rating_id)
        rating.is_approved = True
        rating.save()
    except Rating.DoesNotExist:
        pass
    flash('Rating approved successfully!', 'success')
    return redirect(url_for('admin_ratings'))

@app.route('/admin/rating/<rating_id>/delete')
@admin_required
def admin_rating_delete(rating_id):
    try:
        rating = Rating.objects.get(id=rating_id)
        rating.delete()
    except Rating.DoesNotExist:
        pass
    flash('Rating deleted successfully!', 'success')
    return redirect(url_for('admin_ratings'))

@app.route('/admin/rating/<rating_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_rating_edit(rating_id):
    try:
        rating = Rating.objects.get(id=rating_id)
    except Rating.DoesNotExist:
        flash('Rating not found', 'error')
        return redirect(url_for('admin_ratings'))
    
    if request.method == 'POST':
        rating.rating = int(request.form.get('rating', 5))
        rating.review = request.form.get('review', '')
        rating.customer_name = request.form.get('customer_name', 'Anonymous')
        rating.is_approved = request.form.get('is_approved') == 'on'
        rating.save()
        flash('Rating updated successfully!', 'success')
        return redirect(url_for('admin_ratings'))
    
    return render_template('admin/rating_form.html', rating=rating)

@app.route('/admin/customers')
@admin_required
def admin_customers():
    customers = User.objects(is_admin=False).order_by('-created_at')
    return render_template('admin/customers.html', customers=customers)

@app.route('/admin/stats')
@admin_required
def admin_stats():
    total_revenue = Order.objects.sum('total') or 0
    orders_by_status = {}
    for status in ['pending', 'processing', 'shipped', 'delivered', 'cancelled']:
        orders_by_status[status] = Order.objects(status=status).count()
    
    return render_template('admin/stats.html', total_revenue=total_revenue, orders_by_status=orders_by_status)

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message', '')
    
    if not user_message:
        return jsonify({'error': 'No message provided'}), 400
    
    products = Product.objects(is_active=True)
    
    product_list = "\n".join([
        f"- {p.name} ({p.category}): ₹{p.sale_price} (MRP: ₹{p.demo_price if p.demo_price else p.sale_price*2}) | Stock: {'In Stock (' + str(int(p.current_stock)) + ')' if p.current_stock > 0 else 'Out of Stock'} | {p.description[:200] if p.description else 'No description'}"
        for p in products
    ])
    
    product_purposes = """
PRODUCT PURPOSES & USES:
- LIPSTAR (Lip Care): For dry lips, lip hydration, lip shine, lip protection
- WHITOLYN (Body Care): For skin brightening, fairness, dark spots removal, body glow
- XANONICE TAB (Tablet): For skin health, glowing skin, internal skin nutrition
- Picotry Cream (Cream): For pigmentation, skin whitening, age spots, melasma
- HZEUP SOAP (Soap): For acne, oily skin, antibacterial cleansing, pimple control
- ROOFS SPF (Sunscreen): For sun protection, UV protection, SPF 50+
- Opuoxy Bright (Cream): For brightening, dull skin, dark circles, fairness
- GLOWORG (Cream): For fairness, moisturizing, SPF 20 protection, 24hr hydration
- NIDGLOW - G (Gel): For glowing skin, pores, acne marks, collagen boost
- LEUCODERM (Lotion): For vitiligo, depigmentation, skin patches
- PDRN MASK (Face Mask): For skin repair, acne scars, wound healing, damaged skin
- Scparal Mask (Face Mask): For sensitive skin, redness, calming irritated skin
- ECTOSOL SS TINT SPF 50 (Sunscreen): For tinted coverage, SPF 50, daily use
- Elight Sunscreen (Sunscreen): For sensitive skin, reef-safe, chemical-free
- Cuhair Tab (Tablet): For hair growth, hair fall control, hair thickness
"""
    
    system_prompt = f"""You are a beauty and skincare expert assistant for Henry's Store. Your job is to understand customer needs and recommend the RIGHT products from our store.

CUSTOMER NEEDS MATCHING:
When a customer describes their problem, match it to the right product:

- Dry lips → LIPSTAR
- Fairness/brightening → WHITOLYN, Opuoxy Bright, GLOWORG, Picotry Cream
- Skin health from within → XANONICE TAB
- Acne/pimples → HZEUP SOAP, NIDGLOW - G
- Sun protection → ROOFS SPF, ECTOSOL SS TINT SPF 50, Elight Sunscreen
- Dark spots/pigmentation → Picotry Cream, Opuoxy Bright
- Hair growth/hair fall → Cuhair Tab
- Sensitive/irritated skin → Scparal Mask
- Skin repair/scars → PDRN MASK
- Vitiligo/depigmentation → LEUCODERM

IMPORTANT RULES:
1. Always check if product is in stock before recommending
2. Mention the price and the discount (MRP vs sale price)
3. Be friendly and helpful
4. If customer mentions a concern, suggest 1-3 relevant products
5. If out of stock, suggest alternatives
6. Ask follow-up questions to understand their needs better

{product_purposes}

AVAILABLE PRODUCTS:
{product_list}

Provide personalized recommendations with product names, prices, and why it's good for their specific need."""

    try:
        groq_api_key = os.environ.get('GROQ_API_KEY')
        if not groq_api_key:
            return jsonify({'error': 'API key not configured'}), 500
        
        response = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {groq_api_key}',
                'Content-Type': 'application/json'
            },
            json={
                'model': 'llama-3.1-8b-instant',
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_message}
                ],
                'temperature': 0.7,
                'max_tokens': 600
            }
        )
        
        if response.status_code != 200:
            return jsonify({'error': 'Failed to get response from AI'}), 500
        
        data = response.json()
        bot_response = data['choices'][0]['message']['content']
        
        return jsonify({'response': bot_response})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def init_db():
    from bson import ObjectId
    
    admin = User.objects(email='admin@henri.com', is_admin=True).first()
    if not admin:
        admin = User(
            email='admin@henri.com',
            password=generate_password_hash('admin123'),
            name='Admin',
            is_admin=True
        )
        admin.save()
        print('Admin user created: admin@henri.com / admin123')
    
    default_descriptions = {
        'LIPSTAR': 'LIPSTAR is a premium lip care product designed to provide deep hydration and a natural shine. Formulated with vitamin E and natural oils, it helps prevent dry lips and gives a subtle, lasting gloss. Perfect for daily use, this lip care essential suits all skin types and provides protection against environmental damage.',
        'WHITOLYN': 'WHITOLYN is an advanced body care lotion that brightens and evens skin tone. Enriched with glutathione and Kojic acid, it helps reduce dark spots, blemishes, and hyperpigmentation. Regular application reveals smoother, radiant skin while providing long-lasting moisturization.',
        'XANONICE TAB': 'XANONICE TAB is a dietary supplement formulated to support overall skin health from within. Contains essential vitamins and minerals that promote collagen production, reduce inflammation, and protect against oxidative stress.',
        'Picotry Cream': 'Picotry Cream is a specialized skincare treatment targeting stubborn pigmentation and uneven skin tone. Its advanced formula combines natural extracts with proven whitening agents to deliver visible results. Effective for age spots, sun damage, and melasma.',
        'HZEUP SOAP': 'HZEUP SOAP is an antibacterial soap infused with herbal extracts for deep cleansing. Formulated with neem and tea tree oil, it effectively fights acne-causing bacteria while being gentle on skin.',
        'ROOFS SPF': 'ROOFS SPF is a broad-spectrum sunscreen providing SPF 50+ protection against UVA and UVB rays. Lightweight and non-greasy formula absorbs quickly without white cast. Enriched with antioxidants to prevent sun damage.',
        'Opuoxy Bright': 'Opuoxy Bright is a revolutionary brightening cream that targets dullness and uneven skin tone. Contains Oxyresveratrol and vitamin C for powerful antioxidant protection.',
        'GLOWORG': 'GLOWORG is an all-in-one fairness cream that works to brighten, moisturize, and protect skin. Infused with arbutin and mulberry extract for visibly lighter skin tone.',
        'NIDGLOW - G': 'NIDGLOW - G is a premium face gel designed for glowing, radiant skin. Contains glycolic acid and vitamin C to exfoliate dead skin cells and boost collagen.',
        'LEUCODERM': 'LEUCODERM is a medicated lotion specifically formulated for skin depigmentation treatment. Helps manage vitiligo and hypopigmentation by stimulating melanocyte activity.',
        'PDRN MASK': 'PDRN MASK is an advanced sheet mask infused with Polydeoxyribonucleotide (PDRN) for intensive skin repair. Helps accelerate wound healing, reduce acne scars, and improve skin texture.',
        'Scparal Mask': 'Scparal Mask is a soothing face mask enriched with centella asiatica and allantoin. Specifically designed to calm irritated skin, reduce redness, and repair skin barrier.',
        'ECTOSOL SS TINT SPF 50': 'ECTOSOL SS TINT SPF 50 is a tinted sunscreen that provides flawless coverage while protecting skin. Offers high SPF 50 protection against harmful UV rays.',
        'Elight Sunscreen': 'Elight Sunscreen is a lightweight, reef-safe sunscreen suitable for sensitive skin. Provides broad-spectrum SPF 50 protection without harsh chemicals.',
        'Cuhair Tab': 'Cuhair Tab is a hair growth supplement enriched with biotin, zinc, and essential vitamins. Supports healthy hair growth from within.',
    }

    products_data = [
        {'name': 'LIPSTAR', 'category': 'Lip Care', 'current_stock': 50, 'minimum_stock': 5, 'sale_price': 275, 'purchase_price': 65.63, 'demo_price': 550, 'description': 'LIPSTAR is a premium lip care product designed to provide deep hydration and a natural shine. Formulated with vitamin E and natural oils, it helps prevent dry lips and gives a subtle, lasting gloss. Perfect for daily use, this lip care essential suits all skin types and provides protection against environmental damage.', 'image_url': ''},
        {'name': 'WHITOLYN', 'category': 'Body Care', 'current_stock': 45, 'minimum_stock': 5, 'sale_price': 180, 'purchase_price': 122.04, 'demo_price': 360, 'description': 'WHITOLYN is an advanced body care lotion that brightens and evens skin tone. Enriched with glutathione and Kojic acid, it helps reduce dark spots, blemishes, and hyperpigmentation. Regular application reveals smoother, radiant skin while providing long-lasting moisturization.', 'image_url': ''},
        {'name': 'XANONICE-PLUS TABLETS', 'category': 'Tablet', 'current_stock': 100, 'minimum_stock': 10, 'sale_price': 180, 'purchase_price': 90, 'demo_price': 360, 'description': 'XANONICE-PLUS TABLETS is a dietary supplement formulated to support overall skin health from within. Contains essential vitamins and minerals that promote collagen production, reduce inflammation, and protect against oxidative stress. Recommended for achieving healthy, glowing skin.', 'image_url': '/static/images/XANONICE TAB.jpeg'},
        {'name': 'Picotry Cream', 'category': 'Cream', 'current_stock': 30, 'minimum_stock': 5, 'sale_price': 675, 'purchase_price': 288.75, 'demo_price': 1350, 'description': 'Picotry Cream is a specialized skincare treatment targeting stubborn pigmentation and uneven skin tone. Its advanced formula combines natural extracts with proven whitening agents to deliver visible results. Effective for age spots, sun damage, and melasma. Suitable for all skin types.', 'image_url': '/static/images/Nivbrite Cream.jpeg'},
        {'name': 'HZEUP SOAP', 'category': 'Soap', 'current_stock': 60, 'minimum_stock': 10, 'sale_price': 155, 'purchase_price': 42, 'demo_price': 310, 'description': 'HZEUP SOAP is an antibacterial soap infused with herbal extracts for deep cleansing. Formulated with neem and tea tree oil, it effectively fights acne-causing bacteria while being gentle on skin. Helps reduce breakouts, controls excess oil, and keeps skin fresh throughout the day.', 'image_url': '/static/images/Exoderm Face Wash.jpeg'},
        {'name': 'ROOFS SPF', 'category': 'Sunscreen', 'current_stock': 40, 'minimum_stock': 5, 'sale_price': 500, 'purchase_price': 260, 'demo_price': 999, 'description': 'ROOFS SPF is a broad-spectrum sunscreen providing SPF 50+ protection against UVA and UVB rays. Lightweight and non-greasy formula absorbs quickly without white cast. Enriched with antioxidants to prevent sun damage, premature aging, and skin darkening. Water-resistant for up to 80 minutes.', 'image_url': '/static/images/12. Uv Roof 30 Aqua Gel.jpeg'},
        {'name': 'OPUOXY BRIGHT TABLETS', 'category': 'Tablet', 'current_stock': 75, 'minimum_stock': 10, 'sale_price': 340, 'purchase_price': 170, 'demo_price': 680, 'description': 'OPUOXY BRIGHT TABLETS is a revolutionary brightening supplement that targets dullness and uneven skin tone from within. Contains Oxyresveratrol and vitamin C for powerful antioxidant protection. Reduces dark circles, blemishes, and age spots while improving skin elasticity. For best results, take twice daily.', 'image_url': '/static/images/TYROGLO FACE SERUM .jpeg'},
        {'name': 'Opuoxy Bright', 'category': 'Cream', 'current_stock': 55, 'minimum_stock': 5, 'sale_price': 340, 'purchase_price': 230.51, 'demo_price': 680, 'description': 'Opuoxy Bright is a revolutionary brightening cream that targets dullness and uneven skin tone. Contains Oxyresveratrol and vitamin C for powerful antioxidant protection. Reduces dark circles, blemishes, and age spots while improving skin elasticity. For best results, use twice daily.', 'image_url': '/static/images/Opuoxy Bright Cream.jpeg'},
        {'name': 'GLOWORG', 'category': 'Cream', 'current_stock': 35, 'minimum_stock': 5, 'sale_price': 365, 'purchase_price': 200, 'demo_price': 730, 'description': 'GLOWORG is an all-in-one fairness cream that works to brighten, moisturize, and protect skin. Infused with arbutin and mulberry extract, it helps reduce melanin production for visibly lighter skin tone. Provides SPF 20 sun protection and keeps skin hydrated for up to 24 hours.', 'image_url': ''},
        {'name': 'NIDGLOW - G', 'category': 'Gel', 'current_stock': 40, 'minimum_stock': 5, 'sale_price': 690, 'purchase_price': 198.8, 'demo_price': 1380, 'description': 'NIDGLOW - G is a premium face gel designed for glowing, radiant skin. Contains glycolic acid and vitamin C to exfoliate dead skin cells and boost collagen. Helps reduce pores, acne marks, and fine lines. Also provides cooling effect and reduces tanning. Apply on clean face before moisturizer.', 'image_url': '/static/images/07. NIDGLOW - G Gel.jpeg'},
        {'name': 'LEUCODERM', 'category': 'Lotion', 'current_stock': 25, 'minimum_stock': 3, 'sale_price': 895, 'purchase_price': 322.5, 'demo_price': 1790, 'description': 'LEUCODERM is a medicated lotion specifically formulated for skin depigmentation treatment. Helps manage vitiligo and hypopigmentation by stimulating melanocyte activity. Contains monobenzyl ether of hydroquinone. For external use only. Consult dermatologist before use.', 'image_url': '/static/images/ZERODEC H.jpeg'},
        {'name': 'PDRN MASK', 'category': 'Face Mask', 'current_stock': 80, 'minimum_stock': 10, 'sale_price': 350, 'purchase_price': 180, 'demo_price': 700, 'description': 'PDRN MASK is an advanced sheet mask infused with Polydeoxyribonucleotide (PDRN) for intensive skin repair. Helps accelerate wound healing, reduce acne scars, and improve skin texture. Provides deep hydration and boosts skin elasticity. Perfect for damaged or stressed skin.', 'image_url': '/static/images/Ceramy D Cleanser.jpeg'},
        {'name': 'Scparal Mask', 'category': 'Face Mask', 'current_stock': 90, 'minimum_stock': 10, 'sale_price': 150, 'purchase_price': 75, 'demo_price': 300, 'description': 'Scparal Mask is a soothing face mask enriched with centella asiatica and allantoin. Specifically designed to calm irritated skin, reduce redness, and repair skin barrier. Ideal for sensitive skin or after cosmetic procedures. Use 2-3 times per week for optimal results.', 'image_url': '/static/images/D ROLLER.jpeg'},
        {'name': 'ECTOSOL SS TINT SPF 50', 'category': 'Sunscreen', 'current_stock': 30, 'minimum_stock': 5, 'sale_price': 590, 'purchase_price': 236, 'demo_price': 1180, 'description': 'ECTOSOL SS TINT SPF 50 is a tinted sunscreen that provides flawless coverage while protecting skin. Offers high SPF 50 protection against harmful UV rays. The light tint blends seamlessly with natural skin tone. Water-based formula is non-comedogenic and suitable for daily use.', 'image_url': '/static/images/4 SUN CREAME ULTRA DEFENCE.jpeg'},
        {'name': 'Elight Sunscreen', 'category': 'Sunscreen', 'current_stock': 45, 'minimum_stock': 5, 'sale_price': 425, 'purchase_price': 174.6, 'demo_price': 850, 'description': 'Elight Sunscreen is a lightweight, reef-safe sunscreen suitable for sensitive skin. Provides broad-spectrum SPF 50 protection without harsh chemicals. Enriched with aloe vera and chamomile to soothe and protect. Fast-absorbing formula leaves no residue. Perfect for outdoor activities.', 'image_url': '/static/images/50. Elight Sunscreen.jpeg'},
        {'name': 'CUHAIR', 'category': 'Tablet', 'current_stock': 120, 'minimum_stock': 15, 'sale_price': 142, 'purchase_price': 57.766, 'demo_price': 284, 'description': 'CUHAIR is a powerful hair growth supplement enriched with biotin, zinc, and essential vitamins. Supports healthy hair growth from within by providing nutrients directly to hair follicles. Helps reduce hair fall, improve hair thickness, and enhance overall hair health. Take one tablet daily.', 'image_url': '/static/images/Cuhair Tab.jpeg'},
        {'name': 'ZERO DEC-H UNDER EYE CREAM', 'category': 'Eye Care', 'current_stock': 50, 'minimum_stock': 5, 'sale_price': 399, 'purchase_price': 180, 'demo_price': 799, 'description': 'ZERO DEC-H UNDER EYE CREAM is specifically formulated to reduce dark circles, puffiness, and fine lines around the delicate eye area. Contains caffeine, peptides, and vitamin K for brightening and firming. Lightweight formula absorbs quickly without greasiness.', 'image_url': '/static/images/ZERODEC H.jpeg'},
        {'name': 'TRICHOSPIRE HAIR GROWTH SHAMPOO', 'category': 'Hair Care', 'current_stock': 65, 'minimum_stock': 10, 'sale_price': 299, 'purchase_price': 120, 'demo_price': 599, 'description': 'TRICHOSPIRE HAIR GROWTH SHAMPOO is enriched with natural ingredients that stimulate hair follicles and promote healthy hair growth. Helps reduce hair fall, strengthen roots, and add volume. Suitable for all hair types. Contains biotin, keratin, and herbal extracts.', 'image_url': '/static/images/TRICHOSPIRE HAIR GROWTH SHAMPOO.jpeg'},
        {'name': 'REMIGRO REVITALISING HAIR SHAMPOO', 'category': 'Hair Care', 'current_stock': 70, 'minimum_stock': 10, 'sale_price': 275, 'purchase_price': 110, 'demo_price': 550, 'description': 'REMIGRO REVITALISING HAIR SHAMPOO breathes new life into dull, damaged hair. Infused with reviving botanicals and essential nutrients that restore shine, softness, and manageability. Helps repair split ends and protects against heat damage.', 'image_url': '/static/images/REMIGRO.jpeg'},
        {'name': 'DALY HAIR SHAMPOO', 'category': 'Hair Care', 'current_stock': 80, 'minimum_stock': 10, 'sale_price': 225, 'purchase_price': 90, 'demo_price': 450, 'description': 'DALY HAIR SHAMPOO is a daily care shampoo that gently cleanses while nourishing your hair. Formulated with natural ingredients that maintain scalp health and promote shine. Free from sulfates and parabens. Suitable for everyday use.', 'image_url': '/static/images/DALY HAIR SHAMPOO.jpeg'},
        {'name': 'DALY HAIR CONDITIONER', 'category': 'Hair Care', 'current_stock': 75, 'minimum_stock': 10, 'sale_price': 235, 'purchase_price': 95, 'demo_price': 470, 'description': 'DALY HAIR CONDITIONER provides deep conditioning and instant detangling. Lock in moisture and protect your hair from environmental damage. Enriched with argan oil and vitamin E for silky smooth results.', 'image_url': '/static/images/DALY HAIR CONDITIONER.jpeg'},
        {'name': 'DALY GLOW BODY WASH', 'category': 'Body Care', 'current_stock': 60, 'minimum_stock': 10, 'sale_price': 249, 'purchase_price': 100, 'demo_price': 499, 'description': 'DALY GLOW BODY WASH transforms your shower into a spa experience. Infused with brightening ingredients like glutathione and vitamin C that cleanse while revealing radiant skin. Gentle formula suitable for daily use.', 'image_url': '/static/images/DALY GLOW BODY WASH.jpeg'},
        {'name': 'ANTI GREY SHAMPOO', 'category': 'Hair Care', 'current_stock': 55, 'minimum_stock': 5, 'sale_price': 349, 'purchase_price': 140, 'demo_price': 699, 'description': 'ANTI GREY SHAMPOO helps restore natural hair color and prevents premature greying. Contains catalase boosters and melanin stimulators that work gradually to bring back your natural shade. Enriched with black seed oil and biotin.', 'image_url': '/static/images/Antigrety Shampoo.jpeg'},
        {'name': 'TRICHOEDGE HAIR SERUM', 'category': 'Hair Care', 'current_stock': 45, 'minimum_stock': 5, 'sale_price': 449, 'purchase_price': 180, 'demo_price': 899, 'description': 'TRICHOEDGE HAIR SERUM is a lightweight, non-greasy formula that tames frizz, adds shine, and protects against heat styling. Creates a smooth barrier around each strand for sleek, manageable hair all day long.', 'image_url': '/static/images/Trichoedge Hair Serum.jpeg'},
        {'name': 'MELITANE 5 & PEA PEPTIDE H BLACK GEL', 'category': 'Gel', 'current_stock': 40, 'minimum_stock': 5, 'sale_price': 599, 'purchase_price': 240, 'demo_price': 1199, 'description': 'MELITANE 5 & PEA PEPTIDE H BLACK GEL is an advanced formulation for skin brightening and anti-aging. Contains melitane 5 and pea peptides that stimulate collagen production and reduce hyperpigmentation. Results visible in 4-6 weeks.', 'image_url': '/static/images/MELITANE 5 & PEA PEPTIDE H BLACK GEL.jpeg'},
        {'name': 'ANTIFALL SHAMPOO', 'category': 'Hair Care', 'current_stock': 85, 'minimum_stock': 15, 'sale_price': 199, 'purchase_price': 80, 'demo_price': 399, 'description': 'ANTIFALL SHAMPOO is specifically designed to combat hair fall and strengthen hair from roots. Contains redensyl, procapil, and saw palmetto that target hair loss at the root. Visible reduction in hair fall within 3 weeks.', 'image_url': '/static/images/ANTIFALL SHA.jpeg'},
        {'name': 'ANCIA 1K', 'category': 'Tablet', 'current_stock': 90, 'minimum_stock': 10, 'sale_price': 499, 'purchase_price': 200, 'demo_price': 999, 'description': 'ANCIA 1K is a comprehensive hair and skin health supplement with 1000mg of biotin. Supports healthy hair growth, stronger nails, and glowing skin. Contains collagen peptides and vitamin C for enhanced benefits.', 'image_url': '/static/images/ANCIA 1K.jpeg'},
        {'name': 'TRICHOLYS', 'category': 'Hair Care', 'current_stock': 50, 'minimum_stock': 5, 'sale_price': 549, 'purchase_price': 220, 'demo_price': 1099, 'description': 'TRICHOLYS is an advanced hair treatment serum that lyses (dissolves) DHT buildup on the scalp. Helps unclog hair follicles and promote new hair growth. Ideal for androgenetic alopecia and thinning hair.', 'image_url': '/static/images/TRICHOLYS.jpeg'},
        {'name': 'LCETNID-M KID SYRUP', 'category': 'Syrup', 'current_stock': 100, 'minimum_stock': 15, 'sale_price': 125, 'purchase_price': 50, 'demo_price': 250, 'description': 'LCETNID-M KID SYRUP is a pediatric antihistamine syrup for children. Provides relief from allergic symptoms like runny nose, sneezing, and itchy eyes. Cherry-flavored for easy administration. Safe for children above 2 years.', 'image_url': '/static/images/Cetnid Syrup.jpeg'},
        {'name': 'AGA-FP SOLUTION', 'category': 'Hair Care', 'current_stock': 35, 'minimum_stock': 5, 'sale_price': 749, 'purchase_price': 300, 'demo_price': 1499, 'description': 'AGA-FP SOLUTION is a topical treatment for androgenetic alopecia (pattern hair loss). Contains finasteride and minoxidil combination that effectively stops hair loss and promotes regrowth. Apply twice daily as directed.', 'image_url': '/static/images/AGA FP Hair Gel.jpeg'},
        {'name': 'VIRCYCLO CREAM', 'category': 'Cream', 'current_stock': 40, 'minimum_stock': 5, 'sale_price': 299, 'purchase_price': 120, 'demo_price': 599, 'description': 'VIRCYCLO CREAM is an antiviral topical cream for herpes and cold sore treatment. Helps reduce healing time and relieves pain. Apply at the first sign of outbreak for best results.', 'image_url': '/static/images/VIRCYCLO CRM.jpeg'},
        {'name': 'VALATOF-1000 TABLETS', 'category': 'Tablet', 'current_stock': 110, 'minimum_stock': 15, 'sale_price': 199, 'purchase_price': 80, 'demo_price': 399, 'description': 'VALATOF-1000 TABLETS contains valacyclovir 1000mg for effective treatment of herpes infections, chickenpox, and shingles. Fast-acting formula that reduces symptoms and speeds up healing.', 'image_url': '/static/images/VELATOF.jpeg'},
        {'name': 'TRICHOEXITO', 'category': 'Hair Care', 'current_stock': 45, 'minimum_stock': 5, 'sale_price': 649, 'purchase_price': 260, 'demo_price': 1299, 'description': 'TRICHOEXITO is an exit strategy for hair loss. Advanced formula combining multiple growth factors that reactivate dormant hair follicles. Clinically proven to increase hair count by up to 40% in 6 months.', 'image_url': '/static/images/Trichoexito Hair Mask.jpeg'},
        {'name': 'LEVAZE-150 TABLETS', 'category': 'Tablet', 'current_stock': 95, 'minimum_stock': 10, 'sale_price': 299, 'purchase_price': 120, 'demo_price': 599, 'description': 'LEVAZE-150 TABLETS contains levocetirizine 150mg for effective relief from allergies. Provides 24-hour relief from sneezing, runny nose, and itchy eyes. Non-drowsy formula.', 'image_url': '/static/images/LVZ TAB.jpeg'},
        {'name': 'AZINIV-500 TABLETS', 'category': 'Tablet', 'current_stock': 85, 'minimum_stock': 10, 'sale_price': 349, 'purchase_price': 140, 'demo_price': 699, 'description': 'AZINIV-500 TABLETS contains azithromycin 500mg, a powerful antibiotic for bacterial infections. Used for respiratory infections, skin infections, and STIs. Short course treatment.', 'image_url': '/static/images/Aziniv.jpeg'},
        {'name': 'TOPICAL-AGEL', 'category': 'Gel', 'current_stock': 50, 'minimum_stock': 5, 'sale_price': 399, 'purchase_price': 160, 'demo_price': 799, 'description': 'TOPICAL-AGEL is a topical gel for acne and pimple treatment. Contains azelaic acid and niacinamide that fight acne-causing bacteria and reduce inflammation. Helps fade post-acne marks.', 'image_url': '/static/images/Topical A Gel.jpeg'},
        {'name': 'NIDCORT TABLET', 'category': 'Tablet', 'current_stock': 120, 'minimum_stock': 15, 'sale_price': 89, 'purchase_price': 36, 'demo_price': 179, 'description': 'NIDCORT TABLET is a combination of niacin and corticosteroid for inflammatory skin conditions. Provides relief from itching, redness, and swelling associated with eczema and psoriasis.', 'image_url': '/static/images/21. NCMIDE SR.jpeg'},
        {'name': 'MUFASA SERUM', 'category': 'Hair Care', 'current_stock': 40, 'minimum_stock': 5, 'sale_price': 799, 'purchase_price': 320, 'demo_price': 1599, 'description': 'MUFASA SERUM is an ultra-concentrated hair growth serum with 15% minoxidil and retinoic acid. Maximum strength formula for stubborn hair loss. Promotes blood circulation to scalp for enhanced hair growth.', 'image_url': '/static/images/BMAX LTN.jpeg'},
        {'name': 'H BLACK GEL', 'category': 'Gel', 'current_stock': 55, 'minimum_stock': 5, 'sale_price': 349, 'purchase_price': 140, 'demo_price': 699, 'description': 'H BLACK GEL is a powerful skin brightening gel for hyperpigmentation. Contains hydroquinone and tretinoin for dramatic results. Effective for melasma, age spots, and post-inflammatory hyperpigmentation.', 'image_url': '/static/images/H BLACK.jpeg'},
        {'name': 'EFLORNITHINE HYDROCHLORIDE CREAM', 'category': 'Cream', 'current_stock': 35, 'minimum_stock': 5, 'sale_price': 599, 'purchase_price': 240, 'demo_price': 1199, 'description': 'EFLORNITHINE HYDROCHLORIDE CREAM is specifically formulated to reduce unwanted facial hair growth in women. Inhibits ornithine decarboxylase enzyme that promotes hair growth. Apply twice daily to affected areas.', 'image_url': '/static/images/EFLORNITHINE HYDROCHLORIDE CREAM.jpeg'},
        {'name': 'NIDCORT-CS OINTMENT', 'category': 'Ointment', 'current_stock': 60, 'minimum_stock': 10, 'sale_price': 179, 'purchase_price': 72, 'demo_price': 359, 'description': 'NIDCORT-CS OINTMENT is a combination steroid ointment for inflammatory skin conditions. Provides relief from eczema, dermatitis, and allergic reactions. Fast-acting formula with long-lasting relief.', 'image_url': '/static/images/NIDCORT-CS OINT.jpeg'},
        {'name': 'FOLIGAIN HAIR LOTION', 'category': 'Hair Care', 'current_stock': 45, 'minimum_stock': 5, 'sale_price': 899, 'purchase_price': 360, 'demo_price': 1799, 'description': 'FOLIGAIN HAIR LOTION is a clinically proven hair regrowth treatment. Contains 5% minoxidil and 0.025% finasteride for maximum efficacy. Stimulates hair follicles and promotes thicker, fuller hair growth.', 'image_url': '/static/images/FOLIGAIN HAIR LOTION.jpeg'},
        {'name': 'ANCIA GOLD TABLETS', 'category': 'Tablet', 'current_stock': 70, 'minimum_stock': 10, 'sale_price': 899, 'purchase_price': 360, 'demo_price': 1799, 'description': 'ANCIA GOLD TABLETS is a premium hair and nail supplement with gold-standard ingredients. Contains 10000mcg biotin, collagen, and keratin. Promotes rapid hair growth and stronger nails.', 'image_url': '/static/images/ANCIA GOLD TABLETS.jpeg'},
        {'name': 'YORGAIN PRO-HAIR', 'category': 'Tablet', 'current_stock': 80, 'minimum_stock': 10, 'sale_price': 599, 'purchase_price': 240, 'demo_price': 1199, 'description': 'YORGAIN PRO-HAIR is an advanced hair growth supplement with proprietary ProHAir complex. Contains saw palmetto, pumpkin seed extract, and marine collagen. Targets DHT and promotes healthy hair growth.', 'image_url': '/static/images/Yorgain Protein Powder.jpeg'},
        {'name': 'REELINK PLUS TABLET', 'category': 'Tablet', 'current_stock': 75, 'minimum_stock': 10, 'sale_price': 449, 'purchase_price': 180, 'demo_price': 899, 'description': 'REELINK PLUS TABLET is a comprehensive hair regrowth formula with biotin, zinc, and herbal extracts. Helps reduce hair fall and promote new hair growth. Visible results in 8-12 weeks.', 'image_url': '/static/images/REELINK PLUS TABLET.jpeg'},
        {'name': 'HQNDETAN BODY LOTION', 'category': 'Body Care', 'current_stock': 50, 'minimum_stock': 5, 'sale_price': 349, 'purchase_price': 140, 'demo_price': 699, 'description': 'HQNDETAN BODY LOTION is a body brightening lotion for overall skin tone evening. Contains hydroquinone and kojic acid for powerful skin lightening. Reduces dark spots, underarm darkness, and knee/elbow discoloration.', 'image_url': '/static/images/HQN DETAN Lotion.jpeg'},
        {'name': 'HYDROQUINONE TRETINOIN AND FLUCINOLONE ACETONIDE CREAM', 'category': 'Cream', 'current_stock': 40, 'minimum_stock': 5, 'sale_price': 449, 'purchase_price': 180, 'demo_price': 899, 'description': 'HYDROQUINONE TRETINOIN AND FLUCINOLONE ACETONIDE CREAM is a triple-action cream for severe hyperpigmentation. Combines three potent ingredients for maximum skin lightening effect. For melasma and stubborn dark spots.', 'image_url': '/static/images/HYDROQUINONE TRETINOIN AND FLUCINOLONE ACETONIDE CREAM.jpeg'},
        {'name': 'FYNKOJI-NU', 'category': 'Tablet', 'current_stock': 85, 'minimum_stock': 10, 'sale_price': 249, 'purchase_price': 100, 'demo_price': 499, 'description': 'FYNKOJI-NU is a combination supplement for skin health and wound healing. Contains vitamin C, zinc, and L-arginine that support collagen synthesis and immune function. Promotes faster skin recovery.', 'image_url': '/static/images/FYNKOJI.jpeg'},
        {'name': 'EXASOFT FACE MOISTURIZING CREAM', 'category': 'Cream', 'current_stock': 65, 'minimum_stock': 10, 'sale_price': 299, 'purchase_price': 120, 'demo_price': 599, 'description': 'EXASOFT FACE MOISTURIZING CREAM provides intense hydration for dry and dehydrated skin. Contains hyaluronic acid and ceramides that lock in moisture. Lightweight, non-comedogenic formula suitable for all skin types.', 'image_url': '/static/images/EXASOFT.jpeg'},
        {'name': 'skinumet', 'category': 'Cream', 'current_stock': 55, 'minimum_stock': 5, 'sale_price': 499, 'purchase_price': 200, 'demo_price': 999, 'description': 'skinumet is an advanced skin brightening cream with patented Luminescence complex. Targets multiple pathways of melanin production for comprehensive skin lightening. Evens skin tone and adds radiant glow.', 'image_url': '/static/images/SKINLUMET.jpeg'},
        {'name': 'RECONFI-U', 'category': 'Tablet', 'current_stock': 90, 'minimum_stock': 10, 'sale_price': 349, 'purchase_price': 140, 'demo_price': 699, 'description': 'RECONFI-U is a rejuvenating supplement for skin, hair, and nail health. Contains vitamin E, selenium, and grapeseed extract as antioxidants. Fights free radical damage and promotes youthful appearance.', 'image_url': '/static/images/RECONFI U.jpeg'},
        {'name': 'NIDPECIA HERBAL HAIR OIL', 'category': 'Hair Care', 'current_stock': 70, 'minimum_stock': 10, 'sale_price': 199, 'purchase_price': 80, 'demo_price': 399, 'description': 'NIDPECIA HERBAL HAIR OIL is an Ayurvedic-inspired hair oil for preventing hair loss. Contains bringraj, amla, and bhringraj that strengthen hair roots. Promotes blood circulation to the scalp for healthier hair growth.', 'image_url': '/static/images/NIDPC OIL.jpeg'},
        {'name': 'DALY TABLETS', 'category': 'Tablet', 'current_stock': 100, 'minimum_stock': 15, 'sale_price': 149, 'purchase_price': 60, 'demo_price': 299, 'description': 'DALY TABLETS is a daily multivitamin for overall health and wellbeing. Contains essential vitamins and minerals that support energy levels, immunity, and skin health. Take one tablet daily for optimal health.', 'image_url': '/static/images/DALY TABS.jpeg'},
        {'name': 'BUTIN-X SERUM', 'category': 'Serum', 'current_stock': 40, 'minimum_stock': 5, 'sale_price': 599, 'purchase_price': 240, 'demo_price': 1199, 'description': 'BUTIN-X SERUM is a potent vitamin C serum with 20% L-ascorbic acid. Brightens skin, fades dark spots, and boosts collagen production. Antioxidant protection against environmental damage.', 'image_url': '/static/images/Butin -x Serum.jpeg'},
        {'name': 'NIDSOFT MAX LOTION', 'category': 'Lotion', 'current_stock': 45, 'minimum_stock': 5, 'sale_price': 399, 'purchase_price': 160, 'demo_price': 799, 'description': 'NIDSOFT MAX LOTION is a maximum strength emollient for severely dry skin. Provides 24-hour moisture and helps repair skin barrier. Ideal for eczema, psoriasis, and extremely dry skin conditions.', 'image_url': '/static/images/NIDSOFT MX.jpeg'},
        {'name': 'HYNID ANTI ITCH LOTION', 'category': 'Lotion', 'current_stock': 55, 'minimum_stock': 5, 'sale_price': 249, 'purchase_price': 100, 'demo_price': 499, 'description': 'HYNID ANTI ITCH LOTION provides instant relief from itching and irritation. Contains calamine and menthol that soothe itchy skin. Perfect for insect bites, rashes, and allergic reactions.', 'image_url': '/static/images/HYNID Lotion.jpeg'},
        {'name': 'BUTIN-D CREAM', 'category': 'Cream', 'current_stock': 50, 'minimum_stock': 5, 'sale_price': 449, 'purchase_price': 180, 'demo_price': 899, 'description': 'BUTIN-D CREAM is a vitamin D3 enriched cream for skin health. Supports skin cell growth and repair. Helps with psoriasis, eczema, and dry skin conditions. Apply twice daily for best results.', 'image_url': '/static/images/Butin D Cr.jpeg'},
        {'name': 'BEAUTIMAX CREAMY LOTION', 'category': 'Body Care', 'current_stock': 60, 'minimum_stock': 10, 'sale_price': 329, 'purchase_price': 132, 'demo_price': 659, 'description': 'BEAUTIMAX CREAMY LOTION is an all-over body lotion for soft, glowing skin. Enriched with shea butter, cocoa butter, and vitamin E. Provides deep moisturization and leaves skin silky smooth.', 'image_url': '/static/images/SUNCARD SUN SCREEN LOTION SPF 60++.jpeg'},
        {'name': 'SOTRUE', 'category': 'Cream', 'current_stock': 45, 'minimum_stock': 5, 'sale_price': 549, 'purchase_price': 220, 'demo_price': 1099, 'description': 'SOTRUE is a truth-telling skincare cream that reveals your true skin potential. Advanced formula with retinol and peptides that reduce fine lines, wrinkles, and improve skin texture. Anti-aging powerhouse.', 'image_url': '/static/images/SOTRUE.jpeg'},
        {'name': 'POMACTIVE SOFTGEL CAPSULES', 'category': 'Tablet', 'current_stock': 80, 'minimum_stock': 10, 'sale_price': 399, 'purchase_price': 160, 'demo_price': 799, 'description': 'POMACTIVE SOFTGEL CAPSULES contain pomegranate extract and omega fatty acids for skin health. Antioxidant-rich formula that protects skin from within and promotes natural glow. Take one capsule daily.', 'image_url': '/static/images/POMACTIVE SOFTGEL CAPSULES.jpeg'},
        {'name': 'KITONID-AB SHAMPOO', 'category': 'Hair Care', 'current_stock': 50, 'minimum_stock': 5, 'sale_price': 279, 'purchase_price': 112, 'demo_price': 559, 'description': 'KITONID-AB SHAMPOO is an anti-dandruff shampoo with antibacterial formula. Contains ketoconazole and zinc pyrithione that eliminate dandruff and prevent recurrence. Soothes itchy scalp.', 'image_url': '/static/images/KITONIF-AB SHAMPOO.jpeg'},
        {'name': 'JANTIB 2% OINTMENT', 'category': 'Ointment', 'current_stock': 70, 'minimum_stock': 10, 'sale_price': 149, 'purchase_price': 60, 'demo_price': 299, 'description': 'JANTIB 2% OINTMENT is a topical antibiotic ointment for skin infections. Contains mupirocin that effectively treats impetigo, folliculitis, and other bacterial skin infections. Apply 2-3 times daily.', 'image_url': '/static/images/JANTIB 2% Ointment.jpeg'},
        {'name': 'NIDSOFT BODY WASH', 'category': 'Body Care', 'current_stock': 65, 'minimum_stock': 10, 'sale_price': 229, 'purchase_price': 92, 'demo_price': 459, 'description': 'NIDSOFT BODY WASH is a gentle, soap-free body cleanser for sensitive skin. Contains ceramides and niacinamide that cleanse without stripping natural oils. Maintains skin pH balance.', 'image_url': '/static/images/Nidsoft Body Wash.jpeg'},
        {'name': 'KIDCOVER GENTLE WASH AND SHAMPOO', 'category': 'Baby Care', 'current_stock': 55, 'minimum_stock': 5, 'sale_price': 269, 'purchase_price': 108, 'demo_price': 539, 'description': 'KIDCOVER GENTLE WASH AND SHAMPOO is a tear-free, gentle formula for baby bath time. Cleanses hair and body without irritation. Contains chamomile and aloe vera that soothe delicate skin.', 'image_url': '/static/images/KIDCOVER WSH.jpeg'},
        {'name': 'SALITONE BODY ACNE SPRAY', 'category': 'Body Care', 'current_stock': 40, 'minimum_stock': 5, 'sale_price': 399, 'purchase_price': 160, 'demo_price': 799, 'description': 'SALITONE BODY ACNE SPRAY is a convenient spray-on treatment for body acne. Contains salicylic acid and tea tree oil that unclog pores and fight acne bacteria. Easy to apply on back, chest, and shoulders.', 'image_url': '/static/images/SALITONE BODY ACNE SPRAY.jpeg'},
        {'name': 'SKAARTY-FORTE GEL', 'category': 'Gel', 'current_stock': 45, 'minimum_stock': 5, 'sale_price': 349, 'purchase_price': 140, 'demo_price': 699, 'description': 'SKAARTY-FORTE GEL is a strong scar gel for old and new scars. Contains silicone and vitamin E that flatten and fade scars over time. Effective for surgical scars, stretch marks, and acne scars.', 'image_url': '/static/images/Skaar Try Gel.jpeg'},
        {'name': 'EXALITE', 'category': 'Cream', 'current_stock': 50, 'minimum_stock': 5, 'sale_price': 499, 'purchase_price': 200, 'demo_price': 999, 'description': 'EXALITE is an exclusive skin brightening cream with patented technology. Provides dramatic skin lightening results in just 4 weeks. Evens skin tone and reveals luminous complexion.', 'image_url': '/static/images/EXALITE.jpeg'},
        {'name': 'NIDCARE', 'category': 'Cream', 'current_stock': 60, 'minimum_stock': 10, 'sale_price': 279, 'purchase_price': 112, 'demo_price': 559, 'description': 'NIDCARE is a comprehensive skincare cream for daily use. Contains SPF 30 and antioxidants that protect skin from sun damage. Moisturizes and nourishes for healthy, glowing skin.', 'image_url': '/static/images/NIDCARE.jpeg'},
        {'name': 'spadeleaf', 'category': 'Cream', 'current_stock': 45, 'minimum_stock': 5, 'sale_price': 399, 'purchase_price': 160, 'demo_price': 799, 'description': 'spadeleaf is a natural skincare cream inspired by the healing properties of spade leaf extract. Soothes irritated skin, reduces redness, and promotes skin healing. Ideal for sensitive skin types.', 'image_url': '/static/images/SPADELEAF.jpeg'},
    ]
    
    for p in products_data:
        existing = Product.objects(name=p['name']).first()
        if not existing:
            product = Product(**p)
            product.save()
    
    print(f'Products synchronized with database')

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
else:
    init_db()

def handler(environ, start_response):
    return app(environ, start_response)
