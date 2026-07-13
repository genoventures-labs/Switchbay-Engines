"""Gumroad personal SDK

Lightweight wrapper for common Gumroad seller API actions used locally or in scripts.

Features:
- Initialize with a seller access token or read GUMROAD_ACCESS_TOKEN.
- Get account info, list products, sales, refunds, and individual records.
- Fetch complete paginated lists and summarize sales by product, date, and month.
- Preview and execute refunds, and find objects by name, email, or ID.

"""
from typing import Any, Dict, List, Optional
import csv
import json
import os
import requests
import time

DEFAULT_API_BASE = "https://api.gumroad.com/v2"


class GumroadSDK:
    def __init__(self, access_token: Optional[str] = None, api_base: str = DEFAULT_API_BASE):
        """Create a Gumroad SDK client.

        If access_token is None, the GUMROAD_ACCESS_TOKEN env var is used.
        """
        self.access_token = access_token or os.environ.get("GUMROAD_ACCESS_TOKEN")
        if not self.access_token:
            raise ValueError("access_token required or set GUMROAD_ACCESS_TOKEN")
        self.api_base = api_base.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.access_token}"})

    def _url(self, path: str) -> str:
        return f"{self.api_base}/{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        url = self._url(path)
        resp = self.session.request(method, url, **kwargs)
        try:
            data = resp.json()
        except ValueError:
            resp.raise_for_status()
        if not resp.ok:
            # Raise with useful info
            msg = data.get("message") if isinstance(data, dict) else resp.text
            raise requests.HTTPError(f"{resp.status_code} {msg}")
        return data

    def get_user(self) -> Dict[str, Any]:
        """Return account (seller) info."""
        return self._request("GET", "/user")

    def list_products(self, page: int = 1) -> Dict[str, Any]:
        """List a single page of products."""
        return self._request("GET", "/products", params={"page": page})

    def list_all_products(self) -> List[Dict[str, Any]]:
        """Fetch all products by paging until there are no more."""
        page = 1
        results: List[Dict[str, Any]] = []
        while True:
            data = self.list_products(page=page)
            products = data.get("products") or []
            if not products:
                break
            results.extend(products)
            page += 1
        return results

    def list_sales(self, page: int = 1, per_page: int = 100) -> Dict[str, Any]:
        """List a single page of sales."""
        return self._request("GET", "/sales", params={"page": page, "per_page": per_page})

    def list_all_sales(self, page_delay: Optional[float] = None) -> List[Dict[str, Any]]:
        """Fetch all sales across pages. Optional page_delay in seconds to sleep between pages."""
        import time

        page = 1
        results: List[Dict[str, Any]] = []
        while True:
            data = self.list_sales(page=page)
            sales = data.get("sales") or []
            if not sales:
                break
            results.extend(sales)
            page += 1
            if page_delay:
                time.sleep(page_delay)
        return results

    def preview_refund(self, sale_id: str, amount: Optional[float] = None) -> Dict[str, Any]:
        """Preview a refund (dry-run). If amount is None, full refund is assumed.

        This calls the refund endpoint with dry_run=true when supported.
        """
        payload: Dict[str, Any] = {"sale_id": sale_id, "dry_run": True}
        if amount is not None:
            # Gumroad expects cents or formatted? Use formatted string (e.g. 5.00)
            payload["amount"] = f"{amount:.2f}"
        return self._request("POST", "/sales/refund", json=payload)

    def refund_sale(self, sale_id: str, amount: Optional[float] = None) -> Dict[str, Any]:
        """Refund a sale. If amount is None, full refund is assumed."""
        payload: Dict[str, Any] = {"sale_id": sale_id}
        if amount is not None:
            payload["amount"] = f"{amount:.2f}"
        return self._request("POST", "/sales/refund", json=payload)
    
    def get_product(self, product_id: str) -> Dict[str, Any]:
        """Get details of a single product by ID."""
        return self._request("GET", f"/products/{product_id}")
    
    def get_sale(self, sale_id: str) -> Dict[str, Any]:
        """Get details of a single sale by ID."""
        return self._request("GET", f"/sales/{sale_id}")
    
    def list_refunds(self, page: int = 1, per_page: int = 100) -> Dict[str, Any]:
        """List a single page of refunds."""
        return self._request("GET", "/refunds", params={"page": page, "per_page": per_page})
    
    def list_all_refunds(self, page_delay: Optional[float] = None) -> List[Dict[str, Any]]:
        """Fetch all refunds across pages. Optional page_delay in seconds to sleep between pages."""
        page = 1
        results: List[Dict[str, Any]] = []
        while True:
            data = self.list_refunds(page=page)
            refunds = data.get("refunds") or []
            if not refunds:
                break
            results.extend(refunds)
            page += 1
            if page_delay:
                time.sleep(page_delay)
        return results

    def get_refund(self, refund_id: str) -> Dict[str, Any]:
        """Get details of a single refund by ID."""
        return self._request("GET", f"/refunds/{refund_id}")
    
    def get_product_sales(self, product_id: str, page: int = 1, per_page: int = 100) -> Dict[str, Any]:
        """List sales for a specific product."""
        return self._request("GET", f"/products/{product_id}/sales", params={"page": page, "per_page": per_page})
    
    def list_all_product_sales(self, product_id: str, page_delay: Optional[float] = None) -> List[Dict[str, Any]]:
        """Fetch all sales for a specific product across pages. Optional page_delay in seconds to sleep between pages."""
        page = 1
        results: List[Dict[str, Any]] = []
        while True:
            data = self.get_product_sales(product_id=product_id, page=page)
            sales = data.get("sales") or []
            if not sales:
                break
            results.extend(sales)
            page += 1
            if page_delay:
                time.sleep(page_delay)
        return results
    
    ## Advanced helpers for product and sales managemnt.

    def find_product_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Find a product by name (case-insensitive). Returns the first match or None."""
        all_products = self.list_all_products()
        for product in all_products:
            if product.get("name", "").lower() == name.lower():
                return product
        return None
    
    def find_sale_by_email(self, email: str) -> List[Dict[str, Any]]:
        """Find sales by buyer email (case-insensitive). Returns a list of matching sales."""
        all_sales = self.list_all_sales()
        matching_sales = [sale for sale in all_sales if sale.get("email", "").lower() == email.lower()]
        return matching_sales
    
    def get_sales_summary(self) -> Dict[str, Any]:
        """Get a summary of sales, including total sales, total revenue, and total refunds."""
        all_sales = self.list_all_sales()
        all_refunds = self.list_all_refunds()
        total_sales = len(all_sales)
        total_revenue = sum(float(sale.get("price", 0)) for sale in all_sales)
        total_refunds = len(all_refunds)
        return {
            "total_sales": total_sales,
            "total_revenue": total_revenue,
            "total_refunds": total_refunds,
        }
    
    def get_product_sales_summary(self, product_id: str) -> Dict[str, Any]:
        """Get a summary of sales for a specific product, including total sales and total revenue."""
        all_sales = self.list_all_product_sales(product_id=product_id)
        total_sales = len(all_sales)
        total_revenue = sum(float(sale.get("price", 0)) for sale in all_sales)
        return {
            "product_id": product_id,
            "total_sales": total_sales,
            "total_revenue": total_revenue,
        }
    
    def insight_sales_by_date(self) -> Dict[str, Any]:
        """Get a summary of sales grouped by date."""
        all_sales = self.list_all_sales()
        sales_by_date: Dict[str, List[Dict[str, Any]]] = {}
        for sale in all_sales:
            date_str = sale.get("created_at", "").split("T")[0]  # Assuming ISO format
            if date_str:
                sales_by_date.setdefault(date_str, []).append(sale)
        summary = {date: {"count": len(sales), "total_revenue": sum(float(sale.get("price", 0)) for sale in sales)} for date, sales in sales_by_date.items()}
        return summary
    
    def insight_sales_by_product(self) -> Dict[str, Any]:
        """Get a summary of sales grouped by product."""
        all_sales = self.list_all_sales()
        sales_by_product: Dict[str, List[Dict[str, Any]]] = {}
        for sale in all_sales:
            product_id = sale.get("product_id")
            if product_id:
                sales_by_product.setdefault(product_id, []).append(sale)
        summary = {product_id: {"count": len(sales), "total_revenue": sum(float(sale.get("price", 0)) for sale in sales)} for product_id, sales in sales_by_product.items()}
        return summary

    def monthly_sales_summary(self) -> Dict[str, Any]:
        """Get a summary of sales grouped by month."""
        all_sales = self.list_all_sales()
        sales_by_month: Dict[str, List[Dict[str, Any]]] = {}
        for sale in all_sales:
            date_str = sale.get("created_at", "").split("T")[0]  # Assuming ISO format
            if date_str:
                month_str = date_str[:7]  # YYYY-MM
                sales_by_month.setdefault(month_str, []).append(sale)
        summary = {month: {"count": len(sales), "total_revenue": sum(float(sale.get("price", 0)) for sale in sales)} for month, sales in sales_by_month.items()}
        return summary
    
    def top_selling_products(self, top_n: int = 5) -> List[Dict[str, Any]]:
        """Get the top N selling products by revenue."""
        all_sales = self.list_all_sales()
        sales_by_product: Dict[str, float] = {}
        for sale in all_sales:
            product_id = sale.get("product_id")
            price = float(sale.get("price", 0))
            if product_id:
                sales_by_product[product_id] = sales_by_product.get(product_id, 0) + price
        sorted_products = sorted(sales_by_product.items(), key=lambda x: x[1], reverse=True)
        return [{"product_id": product_id, "total_revenue": revenue} for product_id, revenue in sorted_products[:top_n]]

    def top_customers(self, top_n: int = 5) -> List[Dict[str, Any]]:
        """Get the top N customers by total spend."""
        all_sales = self.list_all_sales()
        spend_by_customer: Dict[str, float] = {}
        for sale in all_sales:
            email = sale.get("email")
            price = float(sale.get("price", 0))
            if email:
                spend_by_customer[email] = spend_by_customer.get(email, 0) + price
        sorted_customers = sorted(spend_by_customer.items(), key=lambda x: x[1], reverse=True)
        return [{"email": email, "total_spent": spent} for email, spent in sorted_customers[:top_n]]

    def find_sale_by_id(self, sale_id: str) -> Optional[Dict[str, Any]]:
        """Find a sale by its ID. Returns the sale dict or None if not found."""
        try:
            return self.get_sale(sale_id)
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise
    
    def compare_sales(self, sale_id1: str, sale_id2: str) -> Dict[str, Any]:
        """Compare two sales by their IDs and return a summary of differences."""
        sale1 = self.find_sale_by_id(sale_id1)
        sale2 = self.find_sale_by_id(sale_id2)
        if not sale1 or not sale2:
            raise ValueError("One or both sales not found.")
        differences = {key: (sale1.get(key), sale2.get(key)) for key in set(sale1.keys()).union(sale2.keys()) if sale1.get(key) != sale2.get(key)}
        return differences
    
    def compare_monthly_sales(self, month1: str, month2: str) -> Dict[str, Any]:
        """Compare sales summaries for two months (format YYYY-MM)."""
        summary1 = self.monthly_sales_summary().get(month1, {"count": 0, "total_revenue": 0.0})
        summary2 = self.monthly_sales_summary().get(month2, {"count": 0, "total_revenue": 0.0})
        return {
            "month1": {"month": month1, **summary1},
            "month2": {"month": month2, **summary2},
            "differences": {
                "count_difference": summary1["count"] - summary2["count"],
                "revenue_difference": summary1["total_revenue"] - summary2["total_revenue"],
            }
        }
    
    def list_sales_by_product(self, product_id: str) -> List[Dict[str, Any]]:
        """List all sales for a specific product."""
        return self.list_all_product_sales(product_id=product_id)
    
# Additional functions for user-friendly summaries, analytics, and reporting.

    def generate_sales_report(self) -> Dict[str, Any]:
        """Generate a comprehensive sales report including summaries and insights."""
        return {
            "total_summary": self.get_sales_summary(),
            "monthly_summary": self.monthly_sales_summary(),
            "sales_by_product": self.insight_sales_by_product(),
            "sales_by_date": self.insight_sales_by_date(),
            "top_products": self.top_selling_products(),
            "top_customers": self.top_customers(),
        }
    
    def generate_product_report(self, product_id: str) -> Dict[str, Any]:
        """Generate a report for a specific product including sales summary and details."""
        return {
            "product_info": self.get_product(product_id),
            "sales_summary": self.get_product_sales_summary(product_id),
            "sales_details": self.list_sales_by_product(product_id),
        }
    
    def generate_customer_report(self, email: str) -> Dict[str, Any]:
        """Generate a report for a specific customer including their sales and total spend."""
        sales = self.find_sale_by_email(email)
        total_spent = sum(float(sale.get("price", 0)) for sale in sales)
        return {
            "customer_email": email,
            "total_spent": total_spent,
            "sales": sales,
        }
    
    def generate_refund_report(self) -> Dict[str, Any]:
        """Generate a report of all refunds including total count and details."""
        all_refunds = self.list_all_refunds()
        total_refunds = len(all_refunds)
        return {
            "total_refunds": total_refunds,
            "refunds": all_refunds,
        }
    
    def generate_comparative_report(self, month1: str, month2: str) -> Dict[str, Any]:
        """Generate a comparative report between two months."""
        return self.compare_monthly_sales(month1, month2)
    
    def generate_sale_comparison(self, sale_id1: str, sale_id2: str) -> Dict[str, Any]:
        """Generate a comparison report between two sales."""
        return self.compare_sales(sale_id1, sale_id2)
    
    def generate_full_report(self) -> Dict[str, Any]:
        """Generate a full report including sales, products, customers, and refunds."""
        return {
            "sales_report": self.generate_sales_report(),
            "refund_report": self.generate_refund_report(),
            "products": [self.generate_product_report(product["id"]) for product in self.list_all_products()],
        }
    
# Additional utility methods for data export, formatting, and analytics.

    def export_sales_to_csv(self, file_path: str) -> None:
        """Export all sales data to a CSV file."""
        all_sales = self.list_all_sales()
        if not all_sales:
            raise ValueError("No sales data to export.")
        fieldnames = all_sales[0].keys()
        with open(file_path, mode='w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for sale in all_sales:
                writer.writerow(sale)
    
    def export_products_to_csv(self, file_path: str) -> None:
        """Export all product data to a CSV file."""
        all_products = self.list_all_products()
        if not all_products:
            raise ValueError("No product data to export.")
        fieldnames = all_products[0].keys()
        with open(file_path, mode='w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for product in all_products:
                writer.writerow(product)

    def export_refunds_to_csv(self, file_path: str) -> None:
        """Export all refund data to a CSV file."""
        all_refunds = self.list_all_refunds()
        if not all_refunds:
            raise ValueError("No refund data to export.")
        fieldnames = all_refunds[0].keys()
        with open(file_path, mode='w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for refund in all_refunds:
                writer.writerow(refund)
    
    def export_customer_sales_to_csv(self, email: str, file_path: str) -> None:
        """Export all sales data for a specific customer to a CSV file."""
        sales = self.find_sale_by_email(email)
        if not sales:
            raise ValueError(f"No sales data found for customer {email}.")
        fieldnames = sales[0].keys()
        with open(file_path, mode='w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for sale in sales:
                writer.writerow(sale)
    
    def export_product_sales_to_csv(self, product_id: str, file_path: str) -> None:
        """Export all sales data for a specific product to a CSV file."""
        sales = self.list_sales_by_product(product_id)
        if not sales:
            raise ValueError(f"No sales data found for product {product_id}.")
        fieldnames = sales[0].keys()
        with open(file_path, mode='w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for sale in sales:
                writer.writerow(sale)
    
    def export_full_report_to_json(self, file_path: str) -> None:
        """Export the full report to a JSON file."""
        full_report = self.generate_full_report()
        with open(file_path, mode='w', encoding='utf-8') as jsonfile:
            json.dump(full_report, jsonfile, indent=4, ensure_ascii=False)
    
    def export_sales_summary_to_json(self, file_path: str) -> None:
        """Export the sales summary to a JSON file."""
        sales_summary = self.get_sales_summary()
        with open(file_path, mode='w', encoding='utf-8') as jsonfile:
            json.dump(sales_summary, jsonfile, indent=4, ensure_ascii=False)
    
    def export_monthly_sales_summary_to_json(self, file_path: str) -> None:
        """Export the monthly sales summary to a JSON file."""
        monthly_summary = self.monthly_sales_summary()
        with open(file_path, mode='w', encoding='utf-8') as jsonfile:
            json.dump(monthly_summary, jsonfile, indent=4, ensure_ascii=False)
    
    def export_top_products_to_json(self, file_path: str, top_n: int = 5) -> None:
        """Export the top N selling products to a JSON file."""
        top_products = self.top_selling_products(top_n=top_n)
        with open(file_path, mode='w', encoding='utf-8') as jsonfile:
            json.dump(top_products, jsonfile, indent=4, ensure_ascii=False)

    def export_top_customers_to_json(self, file_path: str, top_n: int = 5) -> None:
        """Export the top N customers by total spend to a JSON file."""
        top_customers = self.top_customers(top_n=top_n)
        with open(file_path, mode='w', encoding='utf-8') as jsonfile:
            json.dump(top_customers, jsonfile, indent=4, ensure_ascii=False)

    def export_refund_report_to_json(self, file_path: str) -> None:
        """Export the refund report to a JSON file."""
        refund_report = self.generate_refund_report()
        with open(file_path, mode='w', encoding='utf-8') as jsonfile:
            json.dump(refund_report, jsonfile, indent=4, ensure_ascii=False)

# Additional utility methods for user and profile management.

    def health_check(self) -> Dict[str, Any]:
        """Ping the Gumroad API and return a structured health report.

        Checks:
        - Token presence (env or init)
        - /user endpoint reachability and response time
        - /products endpoint reachability and response time
        - Summary of what is reachable

        Returns a dict with keys: token_present, endpoints, healthy, latency_ms, errors.
        """
        import time as _time

        report: Dict[str, Any] = {
            "token_present": bool(self.access_token),
            "token_prefix": (self.access_token[:6] + "…") if self.access_token else None,
            "api_base": self.api_base,
            "endpoints": {},
            "healthy": False,
            "errors": [],
        }

        if not self.access_token:
            report["errors"].append("GUMROAD_ACCESS_TOKEN is missing or empty.")
            return report

        checks = [
            ("user", "/user"),
            ("products", "/products"),
        ]

        all_ok = True
        for label, path in checks:
            t0 = _time.monotonic()
            try:
                resp = self.session.get(self._url(path), timeout=10)
                elapsed_ms = round((_time.monotonic() - t0) * 1000)
                if resp.ok:
                    try:
                        data = resp.json()
                    except ValueError:
                        data = {}
                    endpoint_info: Dict[str, Any] = {
                        "ok": True,
                        "status_code": resp.status_code,
                        "latency_ms": elapsed_ms,
                    }
                    # Attach lightweight metadata per endpoint
                    if label == "user":
                        u = data.get("user", {})
                        endpoint_info["seller_name"] = u.get("name")
                        endpoint_info["seller_email"] = u.get("email")
                    elif label == "products":
                        products = data.get("products") or []
                        endpoint_info["product_count"] = len(products)
                else:
                    all_ok = False
                    try:
                        body = resp.json()
                        msg = body.get("message", resp.text)
                    except ValueError:
                        msg = resp.text
                    endpoint_info = {
                        "ok": False,
                        "status_code": resp.status_code,
                        "latency_ms": elapsed_ms,
                        "error": msg,
                    }
                    report["errors"].append(f"{label}: HTTP {resp.status_code} — {msg}")
            except Exception as exc:
                elapsed_ms = round((_time.monotonic() - t0) * 1000)
                all_ok = False
                endpoint_info = {
                    "ok": False,
                    "status_code": None,
                    "latency_ms": elapsed_ms,
                    "error": str(exc),
                }
                report["errors"].append(f"{label}: {exc}")

            report["endpoints"][label] = endpoint_info

        report["healthy"] = all_ok
        return report

    def update_user_profile(self, profile_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update the user's profile with the provided data."""
        return self._request("POST", "/user/update", json=profile_data)

    def change_user_password(self, old_password: str, new_password: str) -> Dict[str, Any]:
        """Change the user's password."""
        payload = {"old_password": old_password, "new_password": new_password}
        return self._request("POST", "/user/change_password", json=payload)
    
    def get_user_profile(self) -> Dict[str, Any]:
        """Get the user's profile information."""
        return self.get_user()
    
    def delete_product(self, product_id: str) -> Dict[str, Any]:
        """Delete a product by its ID."""
        return self._request("POST", f"/products/{product_id}/delete")
    
    def delete_sale(self, sale_id: str) -> Dict[str, Any]:
        """Delete a sale by its ID."""
        return self._request("POST", f"/sales/{sale_id}/delete")
    
    def delete_refund(self, refund_id: str) -> Dict[str, Any]:
        """Delete a refund by its ID."""
        return self._request("POST", f"/refunds/{refund_id}/delete")

    def create_product(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new product with the provided data."""
        return self._request("POST", "/products", json=product_data)
    
    def update_product(self, product_id: str, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing product with the provided data."""
        return self._request("POST", f"/products/{product_id}/update", json=product_data)
