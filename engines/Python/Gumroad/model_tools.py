"""
GumOps model tool definitions and helpers.

This module provides common and project-specific tool definitions for use with
LM Studio agent-style `.act()` calls. It also includes helper functions for
running tool-enabled interactions using the local SDK configuration.
"""

from pathlib import Path
from typing import Any, Iterable, List, Optional

from engines.Python.Gumroad.gumsdk import GumroadSDK
from engines.Python.Gumroad.lms_sdk import (
    create_client,
    get_default_model_name,
    local_llm,
    prepare_image,
    tool,
)


@tool(description="Add two integers and return their sum.")
def add(a: int, b: int) -> int:
    return a + b


@tool(description="Multiply two numbers and return the product.")
def multiply(a: float, b: float) -> float:
    return a * b


@tool(description="Return True if the given integer is a prime number.")
def is_prime(n: int) -> bool:
    if n < 2:
        return False
    if n % 2 == 0:
        return n == 2
    limit = int(n**0.5) + 1
    for i in range(3, limit, 2):
        if n % i == 0:
            return False
    return True


@tool(description="Create a file with the provided name and content.")
def create_file(name: str, content: str) -> str:
    dest_path = Path(name)
    if dest_path.exists():
        return f"Error: File already exists: {dest_path}"
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(content, encoding="utf-8")
        return f"Created file: {dest_path}"
    except Exception as exc:
        return f"Error: {exc!r}"


@tool(description="Read the contents of a text file and return it.")
def read_file(path: str) -> str:
    file_path = Path(path)
    if not file_path.exists():
        return f"Error: File not found: {file_path}"
    if not file_path.is_file():
        return f"Error: Path is not a file: {file_path}"
    try:
        return file_path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"Error: {exc!r}"


@tool(description="List files in a directory and return their names.")
def list_directory(path: str = ".") -> str:
    dir_path = Path(path)
    if not dir_path.exists():
        return f"Error: Directory not found: {dir_path}"
    if not dir_path.is_dir():
        return f"Error: Path is not a directory: {dir_path}"
    entries = sorted(str(child.relative_to(dir_path)) for child in dir_path.iterdir())
    return "\n".join(entries) if entries else "No files found."


@tool(description="Search for text in project files and return matching excerpts.")
def search_files(query: str, path: str = ".") -> str:
    dir_path = Path(path)
    if not dir_path.exists() or not dir_path.is_dir():
        return f"Error: Invalid search path: {dir_path}"

    matches: List[str] = []
    for file_path in dir_path.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in {".py", ".md", ".txt", ".json", ".yaml", ".yml"}:
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if query in content:
            excerpt = next(
                (line.strip() for line in content.splitlines() if query in line),
                "",
            )
            matches.append(f"{file_path}: {excerpt}")
    return "\n".join(matches) if matches else "No matches found."


@tool(description="Summarize a file by returning its first lines and metadata.")
def summarize_file(path: str, max_lines: int = 20) -> str:
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        return f"Error: File not found: {file_path}"
    try:
        lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception as exc:
        return f"Error: {exc!r}"
    snippet = "\n".join(lines[:max_lines])
    return (
        f"Path: {file_path}\n"
        f"Total lines: {len(lines)}\n"
        f"Preview:\n{snippet}"
    )


@tool(description="Prepare an image for vision-capable models and return the prepared image handle.")
def prepare_image_tool(image_path: str) -> Any:
    return prepare_image(image_path)


def get_gumroad_client() -> GumroadSDK:
    return GumroadSDK()


@tool(description="List Gumroad products for the configured seller account.")
def list_gumroad_products(page: int = 1) -> str:
    try:
        sdk = get_gumroad_client()
        data = sdk.list_products(page=page)
        products = data.get("products") or []
        if not products:
            return "No Gumroad products found."
        lines = [
            f"{product.get('id')} - {product.get('name')} ({product.get('url') or product.get('permalink', '')})"
            for product in products
        ]
        return "\n".join(lines)
    except Exception as exc:
        return f"Error listing Gumroad products: {exc}"


@tool(description="Return a summary of Gumroad sales, revenue, and refunds.")
def gumroad_sales_summary() -> str:
    try:
        sdk = get_gumroad_client()
        summary = sdk.get_sales_summary()
        return (
            f"Total sales: {summary.get('total_sales')}\n"
            f"Total revenue: {summary.get('total_revenue')}\n"
            f"Total refunds: {summary.get('total_refunds')}"
        )
    except Exception as exc:
        return f"Error fetching Gumroad sales summary: {exc}"


@tool(description="Return Gumroad account information for the configured seller.")
def get_gumroad_account_info() -> str:
    try:
        sdk = get_gumroad_client()
        user = sdk.get_user()
        return (
            f"Seller: {user.get('name')} ({user.get('email')})\n"
            f"Products: {user.get('product_count')}\n"
            f"Sales: {user.get('sales_count')}"
        )
    except Exception as exc:
        return f"Error fetching Gumroad account info: {exc}"


@tool(description="Refund a Gumroad sale by ID; if amount is omitted, refund the full sale.")
def refund_gumroad_sale(sale_id: str, amount: Optional[float] = None) -> str:
    try:
        sdk = get_gumroad_client()
        preview = sdk.preview_refund(sale_id=sale_id, amount=amount)
        if preview.get("success") is not False:
            result = sdk.refund_sale(sale_id=sale_id, amount=amount)
            return f"Refund successful: {result}"
        return f"Refund preview failed: {preview}"
    except Exception as exc:
        return f"Error refunding Gumroad sale {sale_id}: {exc}"


def get_common_tools() -> List[Any]:
    return [add, multiply, is_prime]


def get_project_tools() -> List[Any]:
    return [
        create_file,
        read_file,
        list_directory,
        search_files,
        summarize_file,
        prepare_image_tool,
        list_gumroad_products,
        gumroad_sales_summary,
        get_gumroad_account_info,
        refund_gumroad_sale,
    ]


def get_all_tools() -> List[Any]:
    return get_common_tools() + get_project_tools()


def act_with_tools(
    prompt_or_chat: Any,
    tools: Iterable[Any],
    model_name: Optional[str] = None,
    client: Optional[Any] = None,
    **kwargs: Any,
) -> Any:
    if client is None:
        client = create_client()
    model_name = model_name or get_default_model_name()
    model = local_llm(model_name, client=client)
    return model.act(prompt_or_chat, tools, **kwargs)


def open_tool_enabled_chat(model_name: Optional[str] = None, host: Optional[str] = None, api_key: Optional[str] = None) -> Any:
    model_name = model_name or get_default_model_name()
    return local_llm(model_name, host=host, api_key=api_key)
