import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import User, Product, Order, LoyaltyTransaction

app = FastAPI(title="Cakebox Reimagined API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Cakebox API running"}

# Utility to validate ObjectId

def ensure_object_id(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id format")

# ----------------- Catalog -----------------
@app.get("/api/products")
def list_products(category: Optional[str] = None, q: Optional[str] = None, limit: int = 50):
    flt = {}
    if category:
        flt["category"] = category
    if q:
        flt["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"description": {"$regex": q, "$options": "i"}},
            {"tags": {"$elemMatch": {"$regex": q, "$options": "i"}}},
        ]
    items = get_documents("product", flt, limit)
    for it in items:
        it["_id"] = str(it["_id"])
    return items

@app.get("/api/products/{product_id}")
def get_product(product_id: str):
    pid = ensure_object_id(product_id)
    doc = db["product"].find_one({"_id": pid})
    if not doc:
        raise HTTPException(404, "Product not found")
    doc["_id"] = str(doc["_id"])
    return doc

# ----------------- Users & Loyalty -----------------
class CreateUser(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None

@app.post("/api/users")
def create_user(payload: CreateUser):
    existing = db["user"].find_one({"email": payload.email})
    if existing:
        return {"_id": str(existing["_id"]), "name": existing.get("name"), "email": existing.get("email"), "loyalty_points": int(existing.get("loyalty_points", 0))}
    data = {
        "name": payload.name,
        "email": str(payload.email),
        "phone": payload.phone,
        "loyalty_points": 0,
        "is_active": True,
    }
    uid = create_document("user", data)
    return {"_id": uid, **data}

@app.get("/api/users/{user_id}")
def get_user(user_id: str):
    user = db["user"].find_one({"_id": ensure_object_id(user_id)})
    if not user:
        raise HTTPException(404, "User not found")
    user["_id"] = str(user["_id"])
    return user

@app.get("/api/users/{user_id}/loyalty")
def get_loyalty(user_id: str):
    user = db["user"].find_one({"_id": ensure_object_id(user_id)})
    if not user:
        raise HTTPException(404, "User not found")
    txs = get_documents("loyaltytransaction", {"user_id": user_id}, limit=100)
    for t in txs:
        t["_id"] = str(t["_id"])
    return {"points": int(user.get("loyalty_points", 0)), "transactions": txs}

# ----------------- Checkout -----------------
class CartItem(BaseModel):
    product_id: str
    quantity: int
    variant: Optional[str] = None

class CheckoutRequest(BaseModel):
    user_id: str
    items: List[CartItem]
    redeem_points: int = 0

@app.post("/api/checkout")
def checkout(payload: CheckoutRequest):
    # compute order totals
    items = []
    subtotal = 0.0
    for ci in payload.items:
        pid = ensure_object_id(ci.product_id)
        prod = db["product"].find_one({"_id": pid})
        if not prod:
            raise HTTPException(400, f"Product not found: {ci.product_id}")
        price = float(prod.get("price", 0))
        line = {
            "product_id": ci.product_id,
            "title": prod.get("title", ""),
            "quantity": ci.quantity,
            "unit_price": price,
            "variant": ci.variant,
        }
        items.append(line)
        subtotal += price * ci.quantity

    # points: earn 1 point per $1
    points_earn = int(subtotal)

    # handle redemption: 100 points = $5 off (example)
    redeem = max(0, payload.redeem_points)
    user = db["user"].find_one({"_id": ensure_object_id(payload.user_id)})
    if not user:
        raise HTTPException(400, "User not found")
    balance = int(user.get("loyalty_points", 0))
    if redeem > balance:
        raise HTTPException(400, "Not enough points")

    discount = (redeem // 100) * 5
    points_redeemed = (redeem // 100) * 100
    total = max(0.0, subtotal - discount)

    order_doc = {
        "user_id": payload.user_id,
        "items": items,
        "subtotal": round(subtotal, 2),
        "discount": float(discount),
        "total": round(total, 2),
        "points_earned": points_earn,
        "points_redeemed": points_redeemed,
        "status": "placed",
    }
    order_id = create_document("order", order_doc)

    # update loyalty: subtract redeemed, add earned
    new_balance = balance - points_redeemed + points_earn
    db["user"].update_one({"_id": user["_id"]}, {"$set": {"loyalty_points": new_balance}})

    # log transactions
    if points_redeemed > 0:
        create_document("loyaltytransaction", {
            "user_id": payload.user_id,
            "order_id": order_id,
            "type": "redeem",
            "points": -points_redeemed,
            "note": "Points redeemed at checkout"
        })
    if points_earn > 0:
        create_document("loyaltytransaction", {
            "user_id": payload.user_id,
            "order_id": order_id,
            "type": "earn",
            "points": points_earn,
            "note": "Points earned from order"
        })

    return {"order_id": order_id, "total": order_doc["total"], "points_earned": points_earn, "points_redeemed": points_redeemed, "new_balance": new_balance}

# ----------------- Utilities -----------------
@app.get("/schema")
def get_schema():
    return {
        "user": User.model_json_schema(),
        "product": Product.model_json_schema(),
        "order": Order.model_json_schema(),
        "loyaltytransaction": LoyaltyTransaction.model_json_schema(),
    }

@app.post("/api/seed")
def seed_products():
    # seed a few sample products if none exist
    count = db["product"].count_documents({})
    if count > 0:
        return {"inserted": 0, "message": "Products already exist"}
    samples = [
        {"title": "Classic Vanilla Cake", "description": "Light and fluffy with vanilla buttercream.", "price": 24.99, "category": "Cakes", "image": "https://images.unsplash.com/photo-1565958011703-44f9829ba187?w=800", "tags": ["vanilla", "classic"]},
        {"title": "Decadent Chocolate Cake", "description": "Rich cocoa layers with ganache.", "price": 29.99, "category": "Cakes", "image": "https://images.unsplash.com/photo-1606313564200-e75d5e30476e?w=800", "tags": ["chocolate", "rich"]},
        {"title": "Strawberry Shortcake", "description": "Fresh strawberries and cream.", "price": 27.5, "category": "Cakes", "image": "https://images.unsplash.com/photo-1601979031925-424e53b6caaa?w=800", "tags": ["strawberry", "fresh"]},
        {"title": "Red Velvet Cupcakes", "description": "Velvety cupcakes with cream cheese frosting.", "price": 12.0, "category": "Cupcakes", "image": "https://images.unsplash.com/photo-1541976076758-347942db1970?w=800", "tags": ["red velvet", "cupcakes"]},
    ]
    for s in samples:
        create_document("product", s)
    return {"inserted": len(samples)}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    import os as _os
    response["database_url"] = "✅ Set" if _os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if _os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
