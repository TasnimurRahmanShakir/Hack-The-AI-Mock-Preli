from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Union
from datetime import datetime, timedelta
import heapq  
import uuid  

app = FastAPI(title="Library Management API", description="API for Hack The AI - Mock Preli Problems")


CURRENT_DATE = datetime(2025, 9, 14)


members: Dict[int, Dict] = {}  
books: Dict[int, Dict] = {}  
transactions: List[Dict] = []  
reservations: Dict[int, List] = {} 
transaction_counter = 500 
reservation_counter = 0

def get_next_transaction_id():
    global transaction_counter
    transaction_counter += 1
    return transaction_counter

def calculate_due_date(borrowed_at: datetime) -> datetime:
    return borrowed_at + timedelta(days=14)

def calculate_days_overdue(due_date: datetime) -> int:
    delta = CURRENT_DATE - due_date
    return max(0, delta.days)

def find_active_borrow(member_id: int) -> Optional[Dict]:
    for t in transactions:
        if t["member_id"] == member_id and t["status"] == "active":
            return t
    return None

def calculate_priority_score(member_id: int) -> float:
    history = [t for t in transactions if t["member_id"] == member_id]
    frequency = len(history)
    punctuality = sum(1 for t in history if t.get("returned_at") and t["returned_at"] <= t["due_date"]) / len(history) if history else 0
    return frequency * 0.3 + punctuality * 0.7  # Example formula

class MemberCreate(BaseModel):
    member_id: int = Field(..., gt=0)
    name: str = Field(..., min_length=1)
    age: int = Field(..., ge=12)

class MemberUpdate(BaseModel):
    name: Optional[str] = None
    age: Optional[int] = Field(None, ge=12)

class MemberResponse(BaseModel):
    member_id: int
    name: str
    age: int
    has_borrowed: bool

class BorrowRequest(BaseModel):
    member_id: int
    book_id: int

class ReturnRequest(BaseModel):
    member_id: int
    book_id: int

class BorrowedBook(BaseModel):
    transaction_id: int
    member_id: int
    member_name: str
    book_id: int
    book_title: str
    borrowed_at: str
    due_date: str

class HistoryItem(BaseModel):
    transaction_id: int
    book_id: int
    book_title: str
    borrowed_at: str
    returned_at: Optional[str]
    status: str

class MemberHistory(BaseModel):
    member_id: int
    member_name: str
    borrowing_history: List[HistoryItem]

class OverdueBook(BaseModel):
    transaction_id: int
    member_id: int
    member_name: str
    book_id: int
    book_title: str
    borrowed_at: str
    due_date: str
    days_overdue: int

class BookCreate(BaseModel):
    book_id: int = Field(..., gt=0)
    title: str = Field(..., min_length=1)
    author: str = Field(..., min_length=1)
    isbn: str = Field(..., min_length=1)

class BookResponse(BaseModel):
    book_id: int
    title: str
    author: str
    isbn: str
    is_available: bool

class SearchBookResponse(BookResponse):
    category: Optional[str] = None
    published_date: Optional[str] = None
    rating: Optional[float] = None
    borrowing_count: Optional[int] = None
    popularity_score: Optional[float] = None

class SearchResponse(BaseModel):
    books: List[SearchBookResponse]
    pagination: Dict[str, Union[int, bool]]
    analytics: Optional[Dict] = None
    suggestions: Optional[Dict] = None

class ReservationRequest(BaseModel):
    member_id: int
    book_id: int
    reservation_type: str = "standard"  
    preferred_pickup_date: Optional[str] = None
    max_wait_days: Optional[int] = 14

class ReservationResponse(BaseModel):
    reservation_id: str
    member_id: int
    book_id: int
    reservation_status: str
    queue_position: int
  



# Q1: 
@app.post("/api/members", response_model=MemberResponse, status_code=200)
async def create_member(member: MemberCreate):
    if member.member_id in members:
        raise HTTPException(400, detail={"message": f"member with id: {member.member_id} already exists"})
    members[member.member_id] = {
        "member_id": member.member_id,
        "name": member.name,
        "age": member.age,
        "has_borrowed": False
    }
    return members[member.member_id]

# Q2: 
@app.get("/api/members/{member_id}", response_model=MemberResponse)
async def get_member(member_id: int):
    if member_id not in members:
        raise HTTPException(404, detail={"message": f"member with id: {member_id} was not found"})
    return members[member_id]

# Q3:
@app.get("/api/members", response_model=Dict[str, List[Dict[str, Union[int, str]]]])
async def list_members():
    return {"members": [{k: v for k, v in m.items() if k != "has_borrowed"} for m in members.values()]}

# Q4: 
@app.put("/api/members/{member_id}", response_model=MemberResponse)
async def update_member(member_id: int, update: MemberUpdate):
    if member_id not in members:
        raise HTTPException(404, detail={"message": f"member with id: {member_id} was not found"})
    if update.name:
        members[member_id]["name"] = update.name
    if update.age:
        members[member_id]["age"] = update.age
    return members[member_id]
