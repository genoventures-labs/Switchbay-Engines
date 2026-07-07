import os

from dotenv import load_dotenv
import shopify

_env_loaded = False
_session = None


def load_env(env_path=".env"):
    """Load environment variables from a .env file.

    The wrapper reads Shopify configuration from the environment so that
    API keys and tokens are not hard-coded in source.
    """
    global _env_loaded
    load_dotenv(env_path)
    _env_loaded = True
    return _env_loaded


def _env(name, default=None):
    if not _env_loaded:
        load_env()
    return os.getenv(name, default)


def build_shopify_session(shop_name=None, api_version=None, access_token=None):
    """Create and activate a Shopify session.

    This wrapper uses the Shopify Python SDK to create a reusable session.
    It prefers explicit arguments, falling back to environment variables.

    Expected .env values:
      SHOPIFY_SHOP_NAME
      SHOPIFY_API_VERSION
      SHOPIFY_ACCESS_TOKEN
    """
    global _session
    shop_name = shop_name or _env("SHOPIFY_SHOP_NAME")
    api_version = api_version or _env("SHOPIFY_API_VERSION", "2024-10")
    access_token = access_token or _env("SHOPIFY_ACCESS_TOKEN")

    if not shop_name or not access_token:
        raise ValueError(
            "Missing Shopify configuration: SHOPIFY_SHOP_NAME and SHOPIFY_ACCESS_TOKEN are required."
        )

    clean_shop = shop_name.replace("https://", "").replace("http://", "").strip("/")
    session = shopify.Session(clean_shop, api_version, access_token)
    shopify.ShopifyResource.activate_session(session)
    _session = session
    return session


def close_shopify_session():
    """Clear the active Shopify session."""
    global _session
    shopify.ShopifyResource.clear_session()
    _session = None


def _ensure_session():
    if shopify.ShopifyResource.session is None and _session is None:
        build_shopify_session()
    return _session or shopify.ShopifyResource.session


def get_shop_info():
    """Retrieve the current shop details."""
    _ensure_session()
    shop = shopify.Shop.current()
    return dict(shop.attributes)


def list_products(limit=10, product_type=None, published_status="any"):
    """Return a list of products as plain dictionaries."""
    _ensure_session()
    params = {"limit": limit, "published_status": published_status}
    if product_type:
        params["product_type"] = product_type
    return [dict(product.attributes) for product in shopify.Product.find(**params)]


def get_product(product_id):
    """Fetch a single product by ID."""
    _ensure_session()
    product = shopify.Product.find(product_id)
    return dict(product.attributes)

def list_orders(limit=10, status="any"):
    """Return a list of orders with basic order metadata."""
    _ensure_session()
    return [dict(order.attributes) for order in shopify.Order.find(limit=limit, status=status)]

def get_order(order_id):
    """Fetch a single order by ID."""
    _ensure_session()
    order = shopify.Order.find(order_id)
    return dict(order.attributes)

def sample_order_payload():
    """Return a sample order payload for testing purposes."""
    return {
        "order": {
            "line_items": [
                {
                    "title": "Sample Product",
                    "quantity": 1,
                    "price": "19.99"
                }
            ],
            "customer": {
                "first_name": "John",
                "last_name": "Doe",
                "email": "john.doe@example.com"
            }
        }
    }

def create_simple_product(title, price, product_type="Default", vendor="Default Vendor"):
    """Create a simple product with a single variant."""
    _ensure_session()
    product = shopify.Product()
    product.title = title
    product.product_type = product_type
    product.vendor = vendor
    product.variants = [shopify.Variant(price=price)]
    success = product.save()
    if not success:
        raise ValueError(f"Failed to create product: {product.errors.full_messages()}")
    return dict(product.attributes)

def extract_shopify_product_data(product):
    """Extract relevant product data into a simplified dictionary."""
    return {
        "id": product.get("id"),
        "title": product.get("title"),
        "product_type": product.get("product_type"),
        "vendor": product.get("vendor"),
        "variants": [
            {
                "id": variant.get("id"),
                "price": variant.get("price"),
                "sku": variant.get("sku")
            }
            for variant in product.get("variants", [])
        ]
    }

def extract_shopify_order_data(order):
    """Extract relevant order data into a simplified dictionary."""
    return {
        "id": order.get("id"),
        "email": order.get("email"),
        "total_price": order.get("total_price"),
        "line_items": [
            {
                "title": item.get("title"),
                "quantity": item.get("quantity"),
                "price": item.get("price")
            }
            for item in order.get("line_items", [])
        ]
    }

def extract_shopify_customer_data(customer):
    """Extract relevant customer data into a simplified dictionary."""
    return {
        "id": customer.get("id"),
        "first_name": customer.get("first_name"),
        "last_name": customer.get("last_name"),
        "email": customer.get("email"),
        "orders_count": customer.get("orders_count"),
        "total_spent": customer.get("total_spent")
    }

def extract_shopify_variant_data(variant):
    """Extract relevant variant data into a simplified dictionary."""
    return {
        "id": variant.get("id"),
        "product_id": variant.get("product_id"),
        "price": variant.get("price"),
        "sku": variant.get("sku"),
        "inventory_quantity": variant.get("inventory_quantity")
    }

def extract_shopify_collection_data(collection):
    """Extract relevant collection data into a simplified dictionary."""
    return {
        "id": collection.get("id"),
        "title": collection.get("title"),
        "handle": collection.get("handle"),
        "products_count": collection.get("products_count")
    }

## The following functions are for insights.

def get_shopify_insights():
    """Fetch basic insights about the shop, such as total products and orders."""
    _ensure_session()
    shop = shopify.Shop.current()
    total_products = len(shopify.Product.find())
    total_orders = len(shopify.Order.find())
    return {
        "shop_name": shop.name,
        "total_products": total_products,
        "total_orders": total_orders
    }

def get_product_insights(product_id):
    """Fetch insights for a specific product, such as total sales and inventory."""
    _ensure_session()
    product = shopify.Product.find(product_id)
    if not product:
        raise ValueError(f"Product with ID {product_id} not found.")
    total_sales = sum(variant.inventory_quantity for variant in product.variants)
    return {
        "product_id": product.id,
        "title": product.title,
        "total_sales": total_sales,
        "variants": [
            {
                "id": variant.id,
                "price": variant.price,
                "inventory_quantity": variant.inventory_quantity
            }
            for variant in product.variants
        ]
    }

def get_order_insights(order_id):
    """Fetch insights for a specific order, such as total price and line items."""
    _ensure_session()
    order = shopify.Order.find(order_id)
    if not order:
        raise ValueError(f"Order with ID {order_id} not found.")
    return {
        "order_id": order.id,
        "email": order.email,
        "total_price": order.total_price,
        "line_items": [
            {
                "title": item.title,
                "quantity": item.quantity,
                "price": item.price
            }
            for item in order.line_items
        ]
    }

def get_customer_insights(customer_id):
    """Fetch insights for a specific customer, such as total orders and total spent."""
    _ensure_session()
    customer = shopify.Customer.find(customer_id)
    if not customer:
        raise ValueError(f"Customer with ID {customer_id} not found.")
    return {
        "customer_id": customer.id,
        "first_name": customer.first_name,
        "last_name": customer.last_name,
        "email": customer.email,
        "orders_count": customer.orders_count,
        "total_spent": customer.total_spent
    }

def get_collection_insights(collection_id):
    """Fetch insights for a specific collection, such as total products."""
    _ensure_session()
    collection = shopify.CustomCollection.find(collection_id)
    if not collection:
        raise ValueError(f"Collection with ID {collection_id} not found.")
    total_products = len(shopify.Product.find(collection_id=collection.id))
    return {
        "collection_id": collection.id,
        "title": collection.title,
        "handle": collection.handle,
        "total_products": total_products
    }


# Example functional entry points
__all__ = [
    "load_env",
    "build_shopify_session",
    "close_shopify_session",
    "get_shop_info",
    "list_products",
    "get_product",
    "create_simple_product",
    "list_orders",
    "get_order",
    "sample_order_payload",
    "get_shopify_insights",
    "get_product_insights",
    "get_order_insights",
    "get_customer_insights",
    "get_collection_insights"
]
