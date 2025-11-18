"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date

class User(BaseModel):
    """
    Users collection schema
    Collection name: "user" (lowercase of class name)
    """
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    phone: Optional[str] = Field(None, description="Phone number")
    address: Optional[str] = Field(None, description="Address")
    birthday: Optional[date] = Field(None, description="Birthday for birthday rewards")
    loyalty_points: int = Field(0, ge=0, description="Total loyalty points balance")
    is_active: bool = Field(True, description="Whether user is active")

class ProductVariant(BaseModel):
    name: str = Field(..., description="Variant name, e.g., 6-inch, 8-inch")
    price: float = Field(..., ge=0, description="Price in dollars")

class Product(BaseModel):
    """
    Products collection schema
    Collection name: "product" (lowercase of class name)
    """
    title: str = Field(..., description="Product title")
    description: Optional[str] = Field(None, description="Product description")
    price: float = Field(..., ge=0, description="Base price in dollars")
    category: str = Field(..., description="Product category")
    image: Optional[str] = Field(None, description="Primary image URL")
    tags: List[str] = Field(default_factory=list, description="Searchable tags")
    in_stock: bool = Field(True, description="Whether product is in stock")
    variants: List[ProductVariant] = Field(default_factory=list, description="Optional size/flavor variants")

class OrderItem(BaseModel):
    product_id: str = Field(..., description="Product ObjectId as string")
    title: str = Field(..., description="Snapshot of product title")
    quantity: int = Field(..., ge=1, description="Quantity")
    unit_price: float = Field(..., ge=0, description="Unit price at purchase time")
    variant: Optional[str] = Field(None, description="Chosen variant if any")

class Order(BaseModel):
    user_id: str = Field(..., description="User ObjectId as string")
    items: List[OrderItem] = Field(..., description="Items in order")
    subtotal: float = Field(..., ge=0)
    discount: float = Field(0, ge=0)
    total: float = Field(..., ge=0)
    points_earned: int = Field(0, ge=0)
    points_redeemed: int = Field(0, ge=0)
    status: str = Field("placed", description="Order status")

class LoyaltyTransaction(BaseModel):
    user_id: str = Field(..., description="User ObjectId as string")
    order_id: Optional[str] = Field(None, description="Related order id")
    type: str = Field(..., description="earn|redeem|adjust")
    points: int = Field(..., description="Positive for earn, negative for redeem")
    note: Optional[str] = Field(None)

# Note: The Flames database viewer will automatically:
# 1. Read these schemas from GET /schema endpoint
# 2. Use them for document validation when creating/editing
# 3. Handle all database operations (CRUD) directly
# 4. You don't need to create any database endpoints!
