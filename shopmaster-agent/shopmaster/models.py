"""Clean, typed data. The messy API values are converted into these in parsers.py."""
from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class OrderStatus(str, Enum):
    """The API uses magic numbers (0,1,2,3,9). The LLM only ever sees these names."""
    NEW = "NEW"
    PAID = "PAID"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderLineInput(BaseModel):
    """One line of an order the LLM wants to create (used as a tool INPUT)."""
    sku: str = Field(description="Product SKU, e.g. 'SKU-1001'. Get it from search_products.")
    qty: int = Field(ge=1, le=99, description="Quantity to order, 1 to 99.")


class Product(BaseModel):
    id: int
    sku: str
    name: str
    category: str | None = None
    price: float | None = Field(default=None, description="Price in USD, None if the system has no valid price")
    in_stock: bool | None = Field(default=None, description="From a legacy flag that is often wrong. Use check_stock for the truth.")
    last_updated: date | None = None
    qty_on_hand: int | None = None
    discontinued: bool | None = None
    description: str | None = None
    weight: str | None = None


class Customer(BaseModel):
    id: int
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    active: bool = True
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    notes: str | None = None


class OrderLine(BaseModel):
    sku: str
    qty: int
    unit_price: float | None = None


class Order(BaseModel):
    order_no: str
    customer_id: int
    order_date: date | None = None
    status: str
    total: float | None = None
    lines: list[OrderLine] = []


class StockRow(BaseModel):
    sku: str
    qty: int
    warehouse: str
