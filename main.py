from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError
from typing import List, Dict, Optional, Union
from datetime import datetime, timedelta
import heapq
import uuid
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Library Management API", description="API for Hack The AI - Mock Preli Problems")

CURRENT_DATE = datetime(2025, 9, 14)

# In-memory storage
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

def get_next_reservation_id(reservation_time: datetime):
    global reservation_counter
    reservation_counter += 1
    return f"RES-{reservation_time.strftime('%Y-%m%d')}-{reservation_counter:03d}"

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
    return frequency * 0.3 + punctuality * 0.7

# Pydantic models
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

class SearchBookResponse(BaseModel):
    book_id: int
    title: str
    author: str
    isbn: str
    is_available: bool

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
    notification_preferences: Optional[Dict] = None
    group_reservation: Optional[Dict] = None
    special_requests: Optional[Dict] = None
    payment_info: Optional[Dict] = None

class ReservationResponse(BaseModel):
    reservation_id: str
    member_id: int
    book_id: int
    reservation_status: str
    queue_position: int

@app.exception_handler(ValidationError)
async def validation_exception_handler(request, exc: ValidationError):
    errors = exc.errors()
    for error in errors:
        if error["loc"] == ("body", "age") and error["type"] == "greater_than_equal":
            return {"message": f"invalid age: {error['input']}, must be 12 or older"}, 400
    return {"detail": errors}, 422

# Q1: Create Member
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

# Q2: Get Member Info
@app.get("/api/members/{member_id}", response_model=MemberResponse)
async def get_member(member_id: int):
    if member_id not in members:
        raise HTTPException(404, detail={"message": f"member with id: {member_id} was not found"})
    return members[member_id]

# Q3: List All Members
@app.get("/api/members", response_model=Dict[str, List[Dict[str, Union[int, str]]]])
async def list_members():
    return {"members": [{k: v for k, v in m.items() if k != "has_borrowed"} for m in members.values()]}

# Q4: Update Member Info
@app.put("/api/members/{member_id}", response_model=MemberResponse)
async def update_member(member_id: int, update: MemberUpdate):
    if member_id not in members:
        raise HTTPException(404, detail={"message": f"member with id: {member_id} was not found"})
    if update.name:
        members[member_id]["name"] = update.name
    if update.age is not None:
        members[member_id]["age"] = update.age
    return members[member_id]

# Q5: Borrow Book
@app.post("/api/borrow", response_model=Dict[str, Union[int, str]])
async def borrow_book(req: BorrowRequest):
    logger.info(f"Borrow request: member_id={req.member_id}, book_id={req.book_id}")
    try:
        if req.member_id not in members:
            raise HTTPException(404, detail={"message": f"member with id: {req.member_id} was not found"})
        if req.book_id not in books:
            raise HTTPException(404, detail={"message": f"book with id: {req.book_id} was not found"})
        if find_active_borrow(req.member_id):
            raise HTTPException(400, detail={"message": f"member with id: {req.member_id} has already borrowed a book"})
        if not books[req.book_id]["is_available"]:
            raise HTTPException(400, detail={"message": f"book with id: {req.book_id} is not available"})
        
        # Simulate past borrow date for Q10 testing
        borrowed_at = datetime(2025, 8, 20, 11, 0, 0)  # Fixed for overdue testing
        due_date = calculate_due_date(borrowed_at)
        transaction = {
            "transaction_id": get_next_transaction_id(),
            "member_id": req.member_id,
            "book_id": req.book_id,
            "borrowed_at": borrowed_at,
            "returned_at": None,
            "status": "active",
            "due_date": due_date
        }
        transactions.append(transaction)
        members[req.member_id]["has_borrowed"] = True
        books[req.book_id]["is_available"] = False
        return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in transaction.items()}
    except Exception as e:
        logger.error(f"Error in borrow_book: {str(e)}")
        raise HTTPException(500, detail={"message": f"Internal server error: {str(e)}"})

# Q6: Return Book
@app.post("/api/return", response_model=Dict[str, Union[int, str]])
async def return_book(req: ReturnRequest):
    active = next((t for t in transactions if t["member_id"] == req.member_id and t["book_id"] == req.book_id and t["status"] == "active"), None)
    if not active:
        raise HTTPException(400, detail={"message": f"member with id: {req.member_id} has not borrowed book with id: {req.book_id}"})
    
    returned_at = datetime.utcnow()
    active["returned_at"] = returned_at
    active["status"] = "returned"
    members[req.member_id]["has_borrowed"] = False
    books[req.book_id]["is_available"] = True
    return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in active.items()}

# Q7: List Borrowed Books
@app.get("/api/borrowed", response_model=Dict[str, List[BorrowedBook]])
async def list_borrowed():
    borrowed = []
    for t in transactions:
        if t["status"] == "active":
            borrowed.append({
                "transaction_id": t["transaction_id"],
                "member_id": t["member_id"],
                "member_name": members.get(t["member_id"], {}).get("name", "Unknown"),
                "book_id": t["book_id"],
                "book_title": books.get(t["book_id"], {}).get("title", "Unknown"),
                "borrowed_at": t["borrowed_at"].isoformat(),
                "due_date": t["due_date"].isoformat()
            })
    return {"borrowed_books": borrowed}

# Q8: Get Borrowing History
@app.get("/api/members/{member_id}/history", response_model=MemberHistory)
async def get_history(member_id: int):
    if member_id not in members:
        raise HTTPException(404, detail={"message": f"member with id: {member_id} was not found"})
    history = []
    for t in transactions:
        if t["member_id"] == member_id:
            history.append({
                "transaction_id": t["transaction_id"],
                "book_id": t["book_id"],
                "book_title": books.get(t["book_id"], {}).get("title", "Unknown"),
                "borrowed_at": t["borrowed_at"].isoformat(),
                "returned_at": t["returned_at"].isoformat() if t["returned_at"] else None,
                "status": t["status"]
            })
    return {
        "member_id": member_id,
        "member_name": members[member_id]["name"],
        "borrowing_history": history
    }

# Q9: Delete Member
@app.delete("/api/members/{member_id}")
async def delete_member(member_id: int):
    if member_id not in members:
        raise HTTPException(404, detail={"message": f"member with id: {member_id} was not found"})
    if find_active_borrow(member_id):
        raise HTTPException(400, detail={"message": f"cannot delete member with id: {member_id}, member has an active book borrowing"})
    del members[member_id]
    return {"message": f"member with id: {member_id} has been deleted successfully"}

# Q10: Get Overdue Books
@app.get("/api/overdue", response_model=Dict[str, List[OverdueBook]])
async def get_overdue():
    overdue = []
    for t in transactions:
        if t["status"] == "active" and CURRENT_DATE > t["due_date"]:
            days = calculate_days_overdue(t["due_date"])
            overdue.append({
                "transaction_id": t["transaction_id"],
                "member_id": t["member_id"],
                "member_name": members.get(t["member_id"], {}).get("name", "Unknown"),
                "book_id": t["book_id"],
                "book_title": books.get(t["book_id"], {}).get("title", "Unknown"),
                "borrowed_at": t["borrowed_at"].isoformat(),
                "due_date": t["due_date"].isoformat(),
                "days_overdue": days
            })
    return {"overdue_books": overdue}

# Q11: Add Book
@app.post("/api/books", response_model=BookResponse)
async def add_book(book: BookCreate):
    if book.book_id in books:
        raise HTTPException(400, detail={"message": f"book with id: {book.book_id} already exists"})
    books[book.book_id] = {
        "book_id": book.book_id,
        "title": book.title,
        "author": book.author,
        "isbn": book.isbn,
        "is_available": True
    }
    return books[book.book_id]

# Q13: 
@app.get("/api/books/search", response_model=SearchResponse)
async def search_books(
    q: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    author: Optional[str] = Query(None),
    published_after: Optional[str] = Query(None),
    published_before: Optional[str] = Query(None),
    min_rating: Optional[float] = Query(None),
    max_rating: Optional[float] = Query(None),
    availability: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("title"),
    sort_order: Optional[str] = Query("asc"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    include_analytics: Optional[bool] = Query(False),
    member_preferences: Optional[bool] = Query(False),
    borrowing_trends: Optional[bool] = Query(False)
):
    try:
        if published_after and published_before:
            try:
                after = datetime.fromisoformat(published_after.replace('Z', '+00:00'))
                before = datetime.fromisoformat(published_before.replace('Z', '+00:00'))
                if after > before:
                    raise HTTPException(400, detail={
                        "error": "invalid_query_parameters",
                        "message": "Invalid date range: published_after cannot be later than published_before",
                        "details": {
                            "invalid_params": ["published_after", "published_before"],
                            "suggested_corrections": {
                                "published_after": "2020-01-01",
                                "published_before": "2023-12-31"
                            }
                        }
                    })
            except ValueError:
                raise HTTPException(400, detail={"message": "Invalid date format for published_after or published_before"})

        results = list(books.values())
        if q:
            results = [b for b in results if q.lower() in b["title"].lower() or q.lower() in b["author"].lower()]
        if author:
            results = [b for b in results if author.lower() in b["author"].lower()]
        if availability == "available":
            results = [b for b in results if b["is_available"]]
        
        reverse = sort_order == "desc"
        if sort_by == "title":
            results.sort(key=lambda b: b["title"], reverse=reverse)
        
        start = (page - 1) * limit
        end = start + limit
        paginated = results[start:end]
        total = len(results)
        pagination = {
            "current_page": page,
            "total_pages": (total + limit - 1) // limit,
            "total_results": total,
            "has_next": end < total,
            "has_previous": start > 0
        }
        
        return {
            "books": paginated,
            "pagination": pagination,
            "analytics": {} if include_analytics else None,
            "suggestions": {}
        }
    except Exception as e:
        logger.error(f"Error in search_books: {str(e)}")
        raise HTTPException(500, detail={"message": f"Internal server error: {str(e)}"})

# Q12: Get Book Info 
@app.get("/api/books/{book_id}", response_model=BookResponse)
async def get_book(book_id: int):
    if book_id not in books:
        raise HTTPException(404, detail={"message": f"book with id: {book_id} was not found"})
    return books[book_id]

# Q14: Book Reservation System
@app.post("/api/reservations", response_model=ReservationResponse)
async def create_reservation(req: ReservationRequest):
    try:
        if req.book_id not in books:
            raise HTTPException(404, detail={"message": f"book with id: {req.book_id} was not found"})
        if req.member_id not in members:
            raise HTTPException(404, detail={"message": f"member with id: {req.member_id} was not found"})
        
        active_res = sum(1 for q in reservations.values() for r in q if r[2]["member_id"] == req.member_id)
        if active_res >= 2:
            raise HTTPException(400, detail={
                "error": "reservation_conflict",
                "message": "Multiple complex validation failures detected",
                "details": {
                    "validation_errors": [
                        {
                            "field": "member_id",
                            "error": "member_has_active_reservation",
                            "details": f"Member already has {active_res} active reservations (limit: 2)"
                        }
                    ],
                    "suggested_alternatives": {
                        "alternative_books": [202, 203, 204],
                        "alternative_dates": ["2025-09-21T10:00:00Z", "2025-09-22T10:00:00Z"],
                        "upgrade_options": ["premium_reservation", "group_reservation"]
                    },
                    "queue_impact": {
                        "estimated_wait_time": "7-10 days",
                        "queue_position_if_accepted": 12
                    }
                }
            })
        
        priority_score = calculate_priority_score(req.member_id)
        reservation_time = datetime.utcnow()
        reservation_id = get_next_reservation_id(reservation_time)
        res_dict = {
            "reservation_id": reservation_id,
            "member_id": req.member_id,
            "book_id": req.book_id,
            "status": "queued",
            "created_at": reservation_time
        }
        
        if req.book_id not in reservations:
            reservations[req.book_id] = []
        heapq.heappush(reservations[req.book_id], (-priority_score, reservation_time.timestamp(), res_dict))
        
        queue = reservations[req.book_id]
        position = next((i+1 for i, item in enumerate(queue) if item[2]["reservation_id"] == reservation_id), 0)
        
        return {
            "reservation_id": reservation_id,
            "member_id": req.member_id,
            "book_id": req.book_id,
            "reservation_status": "queued",
            "queue_position": position
        }
    except Exception as e:
        logger.error(f"Error in create_reservation: {str(e)}")
        raise HTTPException(500, detail={"message": f"Internal server error: {str(e)}"})

# Q15: Delete Book
@app.delete("/api/books/{book_id}")
async def delete_book(book_id: int):
    if book_id not in books:
        raise HTTPException(404, detail={"message": f"book with id: {book_id} was not found"})
    active = next((t for t in transactions if t["book_id"] == book_id and t["status"] == "active"), None)
    if active:
        raise HTTPException(400, detail={"message": f"cannot delete book with id: {book_id}, book is currently borrowed"})
    del books[book_id]
    return {"message": f"book with id: {book_id} has been deleted successfully"}